"""W15b — MACD monitor + monitoring KALAN bulguları için regresyon kilitleri.

Denetim: ``outputs/denetim_2026-09-12/F_macd_monitoring.md``.

Bu dosya yalnızca aşağıdaki düzeltmeleri kilitler; HER test ilgili düzeltme
geri alınırsa KIRILACAK şekilde yazıldı:

  F-04 — erken (dip) alarmında boot/restart "ilk gözlem sessiz arm" koruması.
  F-07 — cooldown'lar GÖRELİ ölçüm için `time.monotonic()` (duvar saati adımına
         dayanıklı); kalıcı/yayınlanan alanlar `time.time()` kalır.
  F-08 — trend/sinyal yeniden hesabı kaba kadansa bağlı (`_trend_cache` canlı).
  F-11 — eşiğin ÜSTÜNDE evrene giren sembol sınırlı pass sonra bir kez ateşler.
  F-12 — `_active_symbols` 10-30 sn TTL ile önbelleklenir (her pass DB yok).
  F-14 — referans verisi yokken `risk_off` BİLİNMİYOR; eşik +20 yükseltilmez.
  F-15 — REST `/api/monitoring/scan` yolu da `_locked_state()` alır.
  F-19 — `_to_bool` tanınmayan değeri loglar; ayar `sources` alanı raporlanır.
  F-20 — kanıt döngüsü ana döngüden BAĞIMSIZ yeniden başlatılır.
"""
import asyncio
import time
import unittest
from unittest.mock import patch, AsyncMock

from app.routers import macd_monitor as mm
from app.routers import monitoring


def _hist(n: int = 60, marker: float = 1_000.0, shape: str = "flat_then_up") -> dict:
    """Hizalı sentetik mum serisi (trend yolunu canlandıracak yükseliş/düşüş)."""
    if shape == "flat_then_up":
        tail = min(20, n)
        closes = [100.0] * (n - tail) + [100.0 + 1.5 * (i + 1) for i in range(tail)]
    elif shape == "flat_then_down":
        tail = min(20, n)
        closes = [100.0] * (n - tail) + [100.0 - 1.5 * (i + 1) for i in range(tail)]
    else:
        closes = [100.0] * n
    return {
        "timestamps": [i * 60_000 for i in range(len(closes))],
        "opens": [v - 0.1 for v in closes],
        "highs": [v + 0.2 for v in closes],
        "lows": [v - 0.2 for v in closes],
        "closes": closes,
        "volumes": [10.0] * len(closes),
        "last_closed_at_ms": marker,
    }


def _fixed_trend(pre: dict):
    """`_symbol_trend_and_signals` yerine sabit bir öncü paketi döndürür (F-04)."""
    extra = {
        "sigs": {"5m": {"break": False, "state": None, "vol": None},
                 "15m": {"break": False, "state": None, "vol": None}},
        "cvd": {"fresh": False, "buy_dominant": False},
        "green": 1,
        "pre": pre,
        "pre_any": any(pre.values()),
        "pre_detail": {},
        "early_score": 0,
    }

    def _f(sym, symbols):
        return ({"raw": 0.5, "r2": 0.5, "speed": 0.1, "dir": 0.1}, extra)

    return _f


class _FakeMarket:
    def __init__(self):
        self.klines: dict[tuple[str, str], dict] = {}
        self.tickers: dict[str, dict] = {}
        self.trade_flow: dict = {}
        self.refresh_calls: list[tuple[str, str]] = []

    def set(self, sym: str, tf: str, hist: dict) -> None:
        self.klines[(sym.upper(), tf)] = hist

    def tick(self, sym: str, price: float, fresh: bool = True) -> None:
        age_ms = 0 if fresh else 10 ** 9
        self.tickers[sym.upper()] = {"last_price": price,
                                     "timestamp": int(time.time() * 1000) - age_ms}

    def get_ut_kline(self, symbol, tf=None):
        return self.klines.get((str(symbol).upper(), tf or "5m"), {
            "timestamps": [], "opens": [], "highs": [], "lows": [],
            "closes": [], "volumes": [], "last_closed_at_ms": 0,
        })

    def get_ticker(self, symbol):
        return self.tickers.get(str(symbol).upper())

    async def refresh_series(self, symbol, tf, limit=150):
        self.refresh_calls.append((str(symbol).upper(), tf))
        return True


class _FakeWs:
    def __init__(self):
        self.messages: list[dict] = []

    async def broadcast(self, message):
        self.messages.append(message)


class _MacdBase(unittest.IsolatedAsyncioTestCase):
    """Testler arası sızıntı olmasın diye modül global durumunu izole eder."""

    def setUp(self):
        self.market = _FakeMarket()
        self.ws = _FakeWs()
        self._orig = {
            "market": mm.market,
            "ws_manager": mm.ws_manager,
            "get_macd_settings": mm.get_macd_settings,
            "active_symbols": mm._active_symbols,
            "fire_jump": mm._maybe_fire_jump_alert,
            "fire_early": mm._maybe_fire_early_alert,
            "trend": mm._symbol_trend_and_signals,
            "bg": mm._start_background,
            "loop_task": mm._loop_task,
            "evidence_task": mm._evidence_task,
        }
        mm.market = self.market
        mm.ws_manager = self.ws
        self.fired_jump: list[tuple] = []
        self.fired_early: list[tuple] = []

        async def _settings(force=False):
            return {"jump_min_score": 60, "alerts_enabled": True,
                    "push_enabled": False, "early_alerts_enabled": True}

        async def _jump(symbol, score, jump_min, settings):
            self.fired_jump.append((symbol, score))

        async def _early(symbol, pre, settings):
            self.fired_early.append((symbol, pre))

        mm.get_macd_settings = _settings
        mm._maybe_fire_jump_alert = _jump
        mm._maybe_fire_early_alert = _early
        mm._SNAPSHOT = {"universe": [], "symbols": {}, "generated_at": 0.0}
        mm._last_price_seen = {}
        mm._last_bar_ts = {}
        mm._last_rest_refresh = {}
        mm._trend_cache = {}
        mm._trend_recomputed_at = {}
        mm._pending_changed = set()
        mm._jump_alerted_at = {}
        mm._early_alerted_at = {}
        mm._early_last_gap = {}
        mm._active_symbols_cache = {"value": None, "at": 0.0}
        mm._settings_cache = {"value": None, "at": 0.0}
        mm._dirty = False
        mm._pass_lock = asyncio.Lock()
        mm._last_pass_at = 0.0
        mm._loop_task = None
        mm._evidence_task = None
        mm._bool_warned = set()

    def tearDown(self):
        mm.market = self._orig["market"]
        mm.ws_manager = self._orig["ws_manager"]
        mm.get_macd_settings = self._orig["get_macd_settings"]
        mm._active_symbols = self._orig["active_symbols"]
        mm._maybe_fire_jump_alert = self._orig["fire_jump"]
        mm._maybe_fire_early_alert = self._orig["fire_early"]
        mm._symbol_trend_and_signals = self._orig["trend"]
        mm._start_background = self._orig["bg"]
        mm._loop_task = self._orig["loop_task"]
        mm._evidence_task = self._orig["evidence_task"]
        mm._active_symbols_cache = {"value": None, "at": 0.0}

    def _universe(self, symbols):
        async def _active(force=False):
            return list(symbols)
        mm._active_symbols = _active

    def _fill(self, sym: str, n: int = 60, shape: str = "flat_then_up") -> None:
        for tf in mm.TF_LIST:
            self.market.set(sym, tf, _hist(n, shape=shape))


# ---------------------------------------------------------------------------
# F-04 — erken alarmda boot/restart "ilk gözlem sessiz arm"
# ---------------------------------------------------------------------------

class EarlyBootSilentArmTests(_MacdBase):
    def test_early_trigger_first_observation_is_silent(self):
        # İlk gözlem (satırda pre_key yok) → tetik YOK.
        self.assertFalse(mm._early_trigger(("dip",), (), False, first_observation=True))
        # İlk gözlem OLMADIĞINDA mevcut B5 davranışı korunur (kenar tetikler).
        self.assertTrue(mm._early_trigger(("dip",), (), False, first_observation=False))

    async def test_restart_does_not_fire_for_already_dipped_symbol(self):
        self._universe(["AAA"])
        self._fill("AAA")
        self.market.tick("AAA", 131.5)
        # Restart senaryosu: sembol zaten "dip" açık, satırda pre_key YOK.
        mm._symbol_trend_and_signals = _fixed_trend({"approach": False, "m1": False, "dip": True})
        await mm._compute_pass(1)
        self.assertEqual([], self.fired_early,
                         "Restart'ta ilk gözlemde erken alarm basılmamalı (F-04)")
        self.assertEqual(("dip",), mm._SNAPSHOT["symbols"]["AAA"]["pre_key"],
                         "İlk gözlem yine de öncü imzasını KAYDETMELİ (sessiz arm)")

    async def test_new_precursor_after_priming_still_fires(self):
        self._universe(["AAA"])
        self._fill("AAA")
        self.market.tick("AAA", 131.5)
        mm._symbol_trend_and_signals = _fixed_trend({"approach": False, "m1": False, "dip": True})
        await mm._compute_pass(1)          # sessiz arm
        self.assertEqual([], self.fired_early)
        # Cache'i tazeleyip YENİ bir öncü (m1) ekle: artık ilk gözlem değil.
        mm._trend_cache.clear()
        mm._trend_recomputed_at.clear()
        mm._symbol_trend_and_signals = _fixed_trend({"approach": False, "m1": True, "dip": True})
        await mm._compute_pass(2)
        self.assertEqual(1, len(self.fired_early),
                         "İlk gözlemden sonra yeni öncü alarm üretmeli (F-04 kilit hâlâ çalışır)")


# ---------------------------------------------------------------------------
# F-07 — cooldown ölçümü monotonik (duvar saati adımına dayanıklı)
# ---------------------------------------------------------------------------

class _Clock:
    """Dışarıdan sürülebilir saat (test kontrolü)."""

    def __init__(self, wall: float = 10_000.0, mono: float = 100.0):
        self.wall = wall
        self.mono = mono

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def localtime(self, *args, **kwargs):
        return time.localtime(*args, **kwargs)


class MacdCooldownMonotonicTests(_MacdBase):
    def setUp(self):
        super().setUp()
        mm._maybe_fire_jump_alert = self._orig["fire_jump"]
        mm._maybe_fire_early_alert = self._orig["fire_early"]

    async def test_jump_cooldown_ignores_wall_clock_step(self):
        clock = _Clock(wall=10_000.0, mono=100.0)
        settings = {"alerts_enabled": True, "push_enabled": False}
        with patch.object(mm, "time", clock), \
             patch.object(mm, "_record_alert_evidence", new_callable=AsyncMock):
            await mm._maybe_fire_jump_alert("AAA", 80, 60, settings)
            self.assertEqual(1, len(self.ws.messages))
            clock.wall += 3600.0     # NTP ileri sıçraması
            clock.mono += 5.0        # gerçekte yalnız 5 sn geçti
            await mm._maybe_fire_jump_alert("AAA", 80, 60, settings)
            self.assertEqual(1, len(self.ws.messages),
                             "Duvar saati sıçraması cooldown'u doldurmamalı (F-07)")
            clock.mono += 30 * 60    # monotonik 30 dk doldu
            await mm._maybe_fire_jump_alert("AAA", 80, 60, settings)
            self.assertEqual(2, len(self.ws.messages))

    async def test_early_cooldown_ignores_wall_clock_step(self):
        clock = _Clock(wall=20_000.0, mono=500.0)
        settings = {"alerts_enabled": True, "early_alerts_enabled": True, "push_enabled": False}
        with patch.object(mm, "time", clock), \
             patch.object(mm, "_record_alert_evidence", new_callable=AsyncMock):
            await mm._maybe_fire_early_alert("AAA", {"dip": True}, settings)
            self.assertEqual(1, len(self.ws.messages))
            clock.wall += 3600.0
            clock.mono += 5.0
            await mm._maybe_fire_early_alert("AAA", {"dip": True}, settings)
            self.assertEqual(1, len(self.ws.messages),
                             "Duvar saati sıçraması erken cooldown'u doldurmamalı (F-07)")
            clock.mono += 30 * 60
            await mm._maybe_fire_early_alert("AAA", {"dip": True}, settings)
            self.assertEqual(2, len(self.ws.messages))


class MonitoringCooldownMonotonicTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_cooldown_uses_monotonic(self):
        clock = _Clock(wall=50_000.0, mono=800.0)
        monitoring._monitoring_state["notified_symbols"] = {}
        monitoring._monitoring_state["candidate_streak"] = {}
        monitoring._monitoring_state["pending_targets"] = {}
        monitoring._monitoring_state["risk_off"] = False
        settings = {"enabled": True, "min_score": 0.5, "min_target_pct": 0.0,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        cands = [{"symbol": "MONOTRY", "velocity_score": 15.0, "target_pct": 5.0, "price": 1.0}]
        with patch.object(monitoring, "time", clock), \
             patch.object(monitoring.database, "save_monitoring_notifications",
                          new_callable=AsyncMock, return_value=0), \
             patch.object(monitoring.database, "get_pending_monitoring_notifications",
                          new_callable=AsyncMock, return_value={}), \
             patch.object(monitoring, "deliver_web_push",
                          new_callable=AsyncMock, return_value={"ok": True}), \
             patch.object(monitoring.config, "MONITORING_DEBOUNCE_SCANS", 0):
            first = await monitoring._notify(cands, settings)
            clock.wall += 3600.0     # NTP ileri sıçraması
            clock.mono += 5.0        # gerçekte 5 sn
            second = await monitoring._notify(cands, settings)
        self.assertEqual(1, len(first))
        self.assertEqual([], second,
                         "Duvar saati sıçraması bildirim cooldown'unu doldurmamalı (F-07)")


# ---------------------------------------------------------------------------
# F-08 — trend yeniden hesabı kaba kadansa bağlı
# ---------------------------------------------------------------------------

class TrendRecomputeCadenceTests(_MacdBase):
    async def test_price_churn_does_not_recompute_within_cadence(self):
        self._universe(["AAA"])
        self._fill("AAA")
        self.market.tick("AAA", 131.5)
        calls = {"n": 0}
        original = mm._symbol_trend_and_signals

        def counting(sym, symbols):
            calls["n"] += 1
            return original(sym, symbols)

        mm._symbol_trend_and_signals = counting
        try:
            await mm._compute_pass(1)                 # cache boş → hesapla
            self.assertEqual(1, calls["n"])
            self.market.tick("AAA", 131.6)            # yalnız fiyat değişti
            await mm._compute_pass(2)
            self.assertEqual(1, calls["n"],
                             "Fiyat churn'ü trend'i yeniden hesaplamamalı (F-08)")
            self.market.tick("AAA", 131.7)
            await mm._compute_pass(3)
            self.assertEqual(1, calls["n"], "Kadans içinde cache kullanılmalı (F-08)")
        finally:
            mm._symbol_trend_and_signals = original

    async def test_cadence_elapsed_forces_recompute(self):
        self._universe(["AAA"])
        self._fill("AAA")
        self.market.tick("AAA", 131.5)
        calls = {"n": 0}
        original = mm._symbol_trend_and_signals

        def counting(sym, symbols):
            calls["n"] += 1
            return original(sym, symbols)

        mm._symbol_trend_and_signals = counting
        try:
            await mm._compute_pass(1)
            self.assertEqual(1, calls["n"])
            mm._trend_recomputed_at["AAA"] = 0.0      # kadans doldu
            await mm._compute_pass(2)
            self.assertEqual(2, calls["n"], "Kadans dolunca trend tazelenmeli (F-08)")
        finally:
            mm._symbol_trend_and_signals = original

    async def test_new_closed_bar_forces_recompute_immediately(self):
        self._universe(["AAA"])
        self._fill("AAA")
        self.market.tick("AAA", 131.5)
        calls = {"n": 0}
        original = mm._symbol_trend_and_signals

        def counting(sym, symbols):
            calls["n"] += 1
            return original(sym, symbols)

        mm._symbol_trend_and_signals = counting
        try:
            await mm._compute_pass(1)
            self.assertEqual(1, calls["n"])
            # Yalnız yeni KAPANMIŞ bar (marker değişti) → kadans beklemeden tazele.
            self.market.set("AAA", "5m", _hist(60, marker=2_000.0))
            await mm._compute_pass(2)
            self.assertEqual(2, calls["n"],
                             "Yeni kapanmış bar kadansı BYPASS etmeli (F-08)")
        finally:
            mm._symbol_trend_and_signals = original

    async def test_cells_still_refresh_on_price_change(self):
        """F-08 yalnız TREND hesabını kadansa bağlar; MACD hücreleri tazelenir."""
        self._universe(["AAA"])
        self._fill("AAA")
        self.market.tick("AAA", 131.5)
        await mm._compute_pass(1)
        first = mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"]
        self.market.set("AAA", "5m", _hist(60, shape="flat_then_down"))
        mm._last_bar_ts[("AAA", "5m")] = 1_000.0
        self.market.tick("AAA", 68.5)               # yalnız fiyat değişti
        await mm._compute_pass(2)
        self.assertNotEqual(first, mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"],
                            "Hücre (tfs) fiyat değişiminde tazelenmeli (F-08 kapsamı dışı)")


# ---------------------------------------------------------------------------
# F-11 — eşiğin üstünde evrene giren sembol sınırlı pass sonra bir kez ateşler
# ---------------------------------------------------------------------------

class JumpArmBoundedBootTests(_MacdBase):
    def test_high_score_new_symbol_fires_once_within_bounded_passes(self):
        row: dict = {}
        fired = [mm._update_jump_arm(row, 95, 60, None)
                 for _ in range(mm._JUMP_ARM_MAX_PASSES + 2)]
        self.assertFalse(fired[0], "İlk pass hâlâ sessiz olmalı (boot koruması)")
        self.assertTrue(any(fired),
                        "Sürekli yüksek skorlu yeni sembol sınırlı pass'ta ateşlemeli (F-11)")
        self.assertEqual(1, sum(1 for f in fired if f), "Yalnız BİR kez ateşlemeli (F-11)")

    def test_normal_threshold_crossing_still_fires_immediately(self):
        row: dict = {}
        self.assertFalse(mm._update_jump_arm(row, 55, 60, 55))   # eşik altı
        self.assertTrue(mm._update_jump_arm(row, 65, 60, 55))    # geçiş → hemen ateş
        self.assertFalse(mm._update_jump_arm(row, 70, 60, 65))   # bayrak kurulu → tekrar yok

    def test_hysteresis_resets_bounded_counter(self):
        row: dict = {}
        mm._update_jump_arm(row, 95, 60, None)      # sessiz arm (sayaç=1)
        mm._update_jump_arm(row, 54, 60, 95)        # temizleme eşiğinin altı → bayrak düşer
        self.assertFalse(row["jump_armed"])
        self.assertEqual(0, row["jump_arm_passes"])


# ---------------------------------------------------------------------------
# F-12 — aktif evren TTL önbelleği
# ---------------------------------------------------------------------------

class ActiveSymbolsCacheTests(_MacdBase):
    async def test_universe_is_cached_within_ttl(self):
        from app import database
        calls = {"n": 0}

        async def fake_list(status="open"):
            calls["n"] += 1
            return []

        clock = _Clock(wall=1_000.0, mono=10_000.0)
        with patch.object(database, "list_auto_paper_trades", side_effect=fake_list), \
             patch.object(mm, "time", clock):
            first = await mm._active_symbols()
            second = await mm._active_symbols()
            self.assertEqual(first, second)
            self.assertEqual(1, calls["n"],
                             "TTL içinde evren DB'den yeniden okunmamalı (F-12)")
            clock.mono += mm._ACTIVE_SYMBOLS_TTL_SEC + 1.0
            await mm._active_symbols()
            self.assertEqual(2, calls["n"], "TTL dolunca evren tazelenmeli (F-12)")


# ---------------------------------------------------------------------------
# F-14 — risk_off bilinmiyor (veri yok) → eşik +20 yükseltilmez
# ---------------------------------------------------------------------------

class RiskOffUnknownTests(unittest.IsolatedAsyncioTestCase):
    def test_effective_min_score_ignores_risk_off(self):
        monitoring._monitoring_state["risk_off"] = True
        try:
            self.assertEqual(70.0, monitoring._effective_min_score({"min_score": 70}),
                             "RISK_OFF eşiği değiştirmemeli (F-14)")
            self.assertEqual(30.0, monitoring._effective_min_score({"min_score": 30}))
        finally:
            monitoring._monitoring_state["risk_off"] = False

    def test_unknown_when_no_reference_data(self):
        with patch.object(monitoring.market, "get_ut_kline", return_value={"closes": []}):
            risk_off, unknown = monitoring._risk_state_from_references()
        self.assertFalse(risk_off, "Veri yokken risk_off=True dememeli (F-14)")
        self.assertTrue(unknown, "Veri yokken rejim BİLİNMİYOR olmalı (F-14)")

    def test_known_risk_off_from_bearish_references(self):
        closes = [100.0] * 24 + [50.0]   # son fiyat EMA25'in ALTINDA
        with patch.object(monitoring.market, "get_ut_kline", return_value={"closes": closes}):
            risk_off, unknown = monitoring._risk_state_from_references()
        self.assertTrue(risk_off)
        self.assertFalse(unknown)

    async def test_settings_endpoint_exposes_risk_off_unknown(self):
        async def fake_settings():
            return {"enabled": True, "min_score": 50.0, "min_target_pct": 2.0,
                    "quiet_hours_start": None, "quiet_hours_end": None}

        with patch.object(monitoring, "get_user_notification_settings",
                          side_effect=fake_settings):
            result = await monitoring.get_monitoring_settings()
        self.assertIn("risk_off_unknown", result, "F-14: bayrak API'de açık olmalı")


# ---------------------------------------------------------------------------
# F-15 — REST tarama yolu da state kilidini alır
# ---------------------------------------------------------------------------

class _RecordingLock:
    def __init__(self):
        self.entered = 0
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        await self._lock.__aenter__()
        self.entered += 1
        return self

    async def __aexit__(self, *exc):
        return await self._lock.__aexit__(*exc)


class RestScanStateLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_rest_scan_holds_state_lock(self):
        lock = _RecordingLock()

        async def fake_run():
            return {"settings": {"min_score": 50.0}, "candidates": [], "watchlist": [],
                    "new_notifications": []}

        monitoring._monitoring_state["history"] = []
        with patch.object(monitoring, "_state_lock", lock), \
             patch.object(monitoring, "_run_scan", side_effect=fake_run), \
             patch("app.main._require_admin", return_value=None):
            await monitoring.monitoring_scan(request=None)
        self.assertGreaterEqual(lock.entered, 1,
                                "REST tarama `_locked_state()` almalı (F-15)")


# ---------------------------------------------------------------------------
# F-19 — `_to_bool` tanınmayan değeri loglar + ayar `sources` alanı
# ---------------------------------------------------------------------------

class ToBoolLoggingTests(_MacdBase):
    def test_unrecognized_value_logs_warning_and_returns_false(self):
        with self.assertLogs("scalper.macd_monitor", level="WARNING") as cm:
            result = mm._to_bool("enabled_typo", False, source="test")
        self.assertFalse(result)
        self.assertTrue(any("tanınmayan" in line for line in cm.output),
                        "Tanınmayan boolean SESSİZCE yutulmamalı (F-19)")

    def test_recognized_values_do_not_warn(self):
        # Bilinen değerler uyarı üretmemeli (davranış korunur).
        self.assertTrue(mm._to_bool("true", False))
        self.assertTrue(mm._to_bool("1", False))
        self.assertFalse(mm._to_bool("0", True))
        self.assertTrue(mm._to_bool(None, True))

    async def test_sources_field_reports_db_and_default(self):
        from app import database

        async def fake_get(key, default=None):
            return '{"alerts_enabled": true}'

        mm.get_macd_settings = self._orig["get_macd_settings"]
        mm._settings_cache = {"value": None, "at": 0.0}
        with patch.object(database, "get_llm_setting", side_effect=fake_get):
            settings = await mm.get_macd_settings(force=True)
        self.assertIn("sources", settings, "Ayarların kaynağı raporlanmalı (F-19)")
        self.assertEqual("db", settings["sources"]["alerts_enabled"])
        self.assertEqual("default", settings["sources"]["push_enabled"])
        self.assertEqual("env", settings["sources"]["early_adaptive_cooldown"])


# ---------------------------------------------------------------------------
# F-20 — kanıt döngüsü ana döngüden bağımsız yeniden başlatılır
# ---------------------------------------------------------------------------

class _AliveTask:
    def done(self):
        return False


class _DeadTask:
    def done(self):
        return True


class EvidenceLoopRestartTests(unittest.TestCase):
    def setUp(self):
        self._orig_bg = mm._start_background
        self._orig_loop = mm._loop_task
        self._orig_ev = mm._evidence_task

    def tearDown(self):
        mm._start_background = self._orig_bg
        mm._loop_task = self._orig_loop
        mm._evidence_task = self._orig_ev

    def test_evidence_loop_restarts_even_if_main_loop_alive(self):
        started: list[str] = []
        mm._start_background = lambda fn, name: (started.append(name), _AliveTask())[1]
        mm._loop_task = _AliveTask()      # ana döngü AYAKTA
        mm._evidence_task = _DeadTask()   # kanıt döngüsü ÖLMÜŞ
        result = mm.start_macd_monitor_loop()
        self.assertTrue(result)
        self.assertIn("macd-evidence-loop", started,
                      "Kanıt döngüsü tek başına ölünce yeniden başlatılmalı (F-20)")
        self.assertNotIn("macd-monitor-loop", started)

    def test_idempotent_when_both_alive(self):
        started: list[str] = []
        mm._start_background = lambda fn, name: (started.append(name), _AliveTask())[1]
        mm._loop_task = _AliveTask()
        mm._evidence_task = _AliveTask()
        result = mm.start_macd_monitor_loop()
        self.assertFalse(result)
        self.assertEqual([], started, "İkisi de sağsa hiçbir şey başlatılmamalı")


if __name__ == "__main__":
    unittest.main()
