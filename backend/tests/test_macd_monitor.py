"""MACD MONITOR birim testleri (A13).

Denetim raporu: ``outputs/macd_monitor_denetim_raporu.md``. Bu dosya özellikle
düzeltilen davranışları kalıcı olarak kilitler:

  A1 — M3/M30 REST tazelemesi fiyat değişmese de hücrelere yansımalı.
  A2 — ``_compute_pass`` kilitli; REST ucu taze önbelleği yeniden hesaplamaz.
  A8/A9 — ticker'sız sembol donmamalı; yeni bar kapanınca hücre tazelenmeli.
  A10 — GET yanıtı global snapshot'ı mutasyona uğratmamalı.
  A15 — hizasız OHLC tüm turu düşürmemeli.
  B6 — alarm histerezisi: eşik çevresinde titreyen skor tekrar alarm basmamalı.
"""
import asyncio
import time
import unittest

from app.routers import macd_monitor as mm


def _hist(n: int = 60, marker: float = 1_000.0, volume: float = 10.0,
          shape: str = "flat_then_up") -> dict:
    """Geçerli (hizalı) sentetik mum geçmişi.

    NOT: Düzgün (lineer) bir seri MACD histogramını ~0 verir — EMA farkı sabit
    kalır ve sinyal EMA'sı ona eşitlenir. Yön testi için son 20 barı kıran
    "önce yatay, sonra hareket" şekli kullanılır.
    """
    if shape == "flat_then_up":
        tail = min(20, n)
        closes = [100.0] * (n - tail) + [100.0 + 1.5 * (index + 1) for index in range(tail)]
    elif shape == "flat_then_down":
        tail = min(20, n)
        closes = [100.0] * (n - tail) + [100.0 - 1.5 * (index + 1) for index in range(tail)]
    elif shape == "spike_then_fade":
        # Aynı CANLI fiyatla (131.5) negatif histogram üreten şekil: son 10 bar
        # zirveden geri çekiliyor → momentum aşağı döner. A1 testinde "fiyat
        # değişmedi ama tazelenen seri işareti çevirdi" iddiasını izole eder.
        closes = ([100.0] * (n - 20)
                  + [100.0 + 4.0 * (index + 1) for index in range(10)]
                  + [140.0 - 0.85 * (index + 1) for index in range(10)])
    elif shape == "up":
        closes = [100.0 + 0.5 * index for index in range(n)]
    else:
        closes = [100.0 - 0.5 * index for index in range(n)]
    return {
        "timestamps": [index * 60_000 for index in range(len(closes))],
        "opens": [value - 0.1 for value in closes],
        "highs": [value + 0.2 for value in closes],
        "lows": [value - 0.2 for value in closes],
        "closes": closes,
        "volumes": [volume] * len(closes),
        "last_closed_at_ms": marker,
    }


class _FakeMarket:
    def __init__(self):
        self.klines: dict[tuple[str, str], dict] = {}
        self.tickers: dict[str, dict] = {}
        self.trade_flow: dict = {}
        self.refresh_calls: list[tuple[str, str]] = []
        self.refresh_ok = True

    def set(self, sym: str, tf: str, hist: dict) -> None:
        self.klines[(sym.upper(), tf)] = hist

    def tick(self, sym: str, price: float, fresh: bool = True) -> None:
        age_ms = 0 if fresh else 10 ** 9
        self.tickers[sym.upper()] = {
            "last_price": price,
            "timestamp": int(time.time() * 1000) - age_ms,
        }

    def get_ut_kline(self, symbol, tf=None):
        return self.klines.get((str(symbol).upper(), tf or "5m"), {
            "timestamps": [], "opens": [], "highs": [], "lows": [],
            "closes": [], "volumes": [], "last_closed_at_ms": 0,
        })

    def get_ticker(self, symbol):
        return self.tickers.get(str(symbol).upper())

    async def refresh_series(self, symbol, tf, limit=150):
        self.refresh_calls.append((str(symbol).upper(), tf))
        return self.refresh_ok


class _FakeWs:
    def __init__(self):
        self.messages: list[dict] = []

    async def broadcast(self, message):
        self.messages.append(message)


class _MacdTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.market = _FakeMarket()
        self.ws = _FakeWs()
        self._orig = {
            "market": mm.market,
            "ws_manager": mm.ws_manager,
            "get_macd_settings": mm.get_macd_settings,
            "_active_symbols": mm._active_symbols,
            "_maybe_fire_jump_alert": mm._maybe_fire_jump_alert,
            "_maybe_fire_early_alert": mm._maybe_fire_early_alert,
        }
        mm.market = self.market
        mm.ws_manager = self.ws
        self.fired_jump: list[tuple] = []
        self.fired_early: list[tuple] = []

        async def _settings(force=False):
            return {"jump_min_score": 60, "alerts_enabled": True,
                    "push_enabled": False, "early_alerts_enabled": True}

        async def _record_jump(symbol, score, jump_min, settings):
            self.fired_jump.append((symbol, score))

        async def _record_early(symbol, pre, settings):
            self.fired_early.append((symbol, pre))

        mm.get_macd_settings = _settings
        mm._maybe_fire_jump_alert = _record_jump
        mm._maybe_fire_early_alert = _record_early
        # Modül global durumunu sıfırla (testler arası sızıntı olmasın)
        mm._SNAPSHOT = {"universe": [], "symbols": {}, "generated_at": 0.0}
        mm._last_price_seen = {}
        mm._last_bar_ts = {}
        mm._last_rest_refresh = {}
        mm._trend_cache = {}
        mm._pending_changed = set()
        mm._jump_alerted_at = {}
        mm._early_alerted_at = {}
        mm._dirty = False
        mm._pass_lock = asyncio.Lock()
        mm._last_pass_at = 0.0

    def tearDown(self):
        mm.market = self._orig["market"]
        mm.ws_manager = self._orig["ws_manager"]
        mm.get_macd_settings = self._orig["get_macd_settings"]
        mm._active_symbols = self._orig["_active_symbols"]
        mm._maybe_fire_jump_alert = self._orig["_maybe_fire_jump_alert"]
        mm._maybe_fire_early_alert = self._orig["_maybe_fire_early_alert"]

    def _universe(self, symbols):
        async def _active():
            return list(symbols)
        mm._active_symbols = _active

    def _fill(self, sym: str, n: int = 60, shape: str = "flat_then_up") -> None:
        for tf in mm.TF_LIST:
            self.market.set(sym, tf, _hist(n, shape=shape))


class ComputeCellTests(_MacdTestBase):
    async def test_compute_cell_green_on_uptrend(self):
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        cell = mm._compute_cell("AAA", "5m")
        self.assertIsNotNone(cell)
        self.assertTrue(cell["green"])
        self.assertGreater(cell["hist"], 0)

    async def test_compute_cell_red_on_downtrend(self):
        self._fill("AAA", shape="flat_then_down")
        self.market.tick("AAA", 68.5)
        cell = mm._compute_cell("AAA", "5m")
        self.assertIsNotNone(cell)
        self.assertFalse(cell["green"])

    async def test_compute_cell_none_when_insufficient_candles(self):
        self.market.set("AAA", "5m", _hist(mm._MACD_MIN_CANDLES - 2))
        self.market.tick("AAA", 100.0)
        self.assertIsNone(mm._compute_cell("AAA", "5m"))

    async def test_compute_cell_ignores_stale_ticker(self):
        """Bayat ticker canlı fiyat olarak eklenmez (MAX_TICKER_AGE kapısı)."""
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 999.0, fresh=False)
        with_stale = mm._compute_cell("AAA", "5m")
        self.market.tickers.pop("AAA")
        without_live = mm._compute_cell("AAA", "5m")
        self.assertEqual(with_stale, without_live)


class StrengthMetaTests(_MacdTestBase):
    async def test_min_max_mapping_and_tiers(self):
        self.assertEqual((10.0, "strong"), mm._strength_meta(1.0, 0.0, 1.0))
        self.assertEqual((0.0, "weak"), mm._strength_meta(0.0, 0.0, 1.0))
        score, tier = mm._strength_meta(0.5, 0.0, 1.0)
        self.assertEqual(5.0, score)
        self.assertEqual("normal", tier)

    async def test_flat_universe_branch(self):
        """hi == lo iken bölme yapılmaz: 0 → 0.0, pozitif → 5.0."""
        self.assertEqual((0.0, "weak"), mm._strength_meta(0.0, 0.0, 0.0))
        self.assertEqual((5.0, "normal"), mm._strength_meta(0.3, 0.0, 0.0))

    async def test_none_inputs(self):
        self.assertEqual((None, None), mm._strength_meta(None, 0.0, 1.0))
        self.assertEqual((None, None), mm._strength_meta(1.0, None, None))


class JumpScoreTests(_MacdTestBase):
    async def test_none_when_strength_missing(self):
        self.assertIsNone(mm._jump_score(None, 3, {}, {}))

    async def test_bounds_and_components(self):
        sigs = {
            "5m": {"break": True, "state": "expand", "vol": True},
            "15m": {"break": True, "state": "expand", "vol": True},
        }
        score = mm._jump_score(10.0, len(mm.TF_LIST), sigs, {"buy_dominant": True})
        # 30 (güç) + 20 (yeşil) + 14+7+6 (M5) + 11+5+4 (M15) + 3 (CVD) = 100
        self.assertEqual(100, score)

    async def test_score_is_non_negative_and_capped(self):
        score = mm._jump_score(0.0, 0, {"5m": {}, "15m": {}}, {})
        self.assertEqual(0, score)
        self.assertLessEqual(mm._jump_score(50.0, 99, {}, {"buy_dominant": True}), 100)


class RefreshedCellTests(_MacdTestBase):
    """A1 — REST ile tazelenen TF, fiyat değişmese de hücreye yansımalı."""

    async def test_rest_refresh_updates_cell_without_price_change(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)

        await mm._compute_pass(1)
        first = mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["3m"]
        self.assertIsNotNone(first)
        self.assertTrue(first["green"])

        # Fiyat SABİT (131.5) kalırken 3m serisi REST'ten farklı gelir; yeni
        # seri aynı canlı fiyatla NEGATİF histogram üretir.
        self.market.set("AAA", "3m", _hist(60, shape="spike_then_fade"))
        mm._last_rest_refresh[("AAA", "3m")] = 0.0  # tazeleme süresi gelsin

        await mm._compute_pass(2)
        second = mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["3m"]

        self.assertIn(("AAA", "3m"), self.market.refresh_calls)
        self.assertNotEqual(first, second, "Tazelenen 3m hücresi güncellenmedi (A1)")
        self.assertFalse(second["green"], "Tazelenen seri negatif histogram vermeliydi")

    async def test_price_change_still_updates_cells(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        await mm._compute_pass(1)
        first = mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"]

        # Ne fiyat ne bar değişti → hücre aynı kalmalı (gereksiz hesap yok).
        await mm._compute_pass(2)
        self.assertEqual(first, mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"])

        self.market.set("AAA", "5m", _hist(60, shape="flat_then_down"))
        mm._last_bar_ts[("AAA", "5m")] = 1_000.0  # bar işareti değişmedi
        self.market.tick("AAA", 68.5)              # yalnız fiyat değişti
        await mm._compute_pass(3)
        self.assertNotEqual(first, mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"])


class NewBarAndMissingTickerTests(_MacdTestBase):
    """A8/A9 — yeni bar kapanışı ve ticker'sızlık donmaya yol açmamalı."""

    async def test_new_closed_bar_forces_refresh_without_price_change(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        await mm._compute_pass(1)
        first = mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"]

        self.market.set("AAA", "5m", _hist(60, shape="flat_then_down", marker=2_000.0))
        await mm._compute_pass(2)  # aynı fiyat, yeni bar işareti
        self.assertNotEqual(first, mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"])

    async def test_symbol_without_ticker_does_not_freeze(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")  # ticker YOK
        await mm._compute_pass(1)
        first = mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"]

        self.market.set("AAA", "5m", _hist(60, shape="flat_then_down", marker=2_000.0))
        await mm._compute_pass(2)
        self.assertNotEqual(
            first, mm._SNAPSHOT["symbols"]["AAA"]["tfs"]["5m"],
            "Ticker'sız sembol yeni barda tazelenmedi (A8/A9)")


class PerSymbolIsolationTests(_MacdTestBase):
    """A15 — bir sembolün bozuk verisi turun kalanını düşürmemeli."""

    async def test_broken_symbol_does_not_block_others(self):
        self._universe(["BAD", "GOOD"])
        # BAD: highs kısa → index tabanlı TR/ATR hesapları eski kodda IndexError
        # fırlatıp turun kalanını düşürürdü.
        broken = _hist(60)
        broken["highs"] = broken["highs"][:10]
        self.market.set("BAD", "5m", broken)
        self._fill("GOOD", shape="flat_then_up")
        self.market.tick("GOOD", 131.5)

        await mm._compute_pass(1)

        good = mm._SNAPSHOT["symbols"].get("GOOD")
        self.assertIsNotNone(good)
        self.assertIsNotNone(good["tfs"]["5m"], "Sağlam sembol hesaplanmadı (A15)")
        # Bozuk sembol istisna yerine None döner.
        self.assertIsNone(mm._tf_vol_state("BAD", "5m"))
        self.assertIsNone(mm._atr_14_closed("BAD", "5m"))

    async def test_aligned_ohlc_rejects_mismatched_lengths(self):
        self.market.set("AAA", "5m", _hist(60))
        self.assertIsNotNone(mm._aligned_ohlc("AAA", "5m", 22))
        bad = _hist(60)
        bad["lows"] = bad["lows"][:5]
        self.market.set("BBB", "5m", bad)
        self.assertIsNone(mm._aligned_ohlc("BBB", "5m", 22))
        # Yeterli mum yoksa da reddedilir
        self.market.set("CCC", "5m", _hist(3))
        self.assertIsNone(mm._aligned_ohlc("CCC", "5m", 22))


class AlertHysteresisTests(_MacdTestBase):
    """B6 — eşik çevresinde titreme tekrar tekrar alarm basmamalı."""

    async def test_boot_is_silent_but_arms(self):
        row: dict = {}
        # İlk gözlem (prev_jump None) alarm BASMAZ, ama bayrağı kurar.
        self.assertFalse(mm._update_jump_arm(row, 75, 60, None))
        self.assertTrue(row["jump_armed"])

    async def test_crossing_fires_once(self):
        row: dict = {}
        mm._update_jump_arm(row, 55, 60, 55)          # eşik altı → bayrak yok
        self.assertFalse(row.get("jump_armed", False))
        self.assertTrue(mm._update_jump_arm(row, 65, 60, 55))   # geçiş → alarm
        self.assertFalse(mm._update_jump_arm(row, 70, 60, 65))  # bayrak kurulu → tekrar yok

    async def test_hysteresis_blocks_retrigger_on_small_dip(self):
        """Eşik 60, pay 5 → 58'e inmek bayrağı SIFIRLAMAZ (yeniden alarm yok)."""
        clear = max(0, 60 - mm._JUMP_HYSTERESIS)
        self.assertEqual(55, clear)
        row = {"jump_armed": True}
        self.assertFalse(mm._update_jump_arm(row, 58, 60, 65))
        self.assertTrue(row["jump_armed"], "58 temizleme eşiğinin üstünde kalmalı")
        # Temizleme eşiğinin altına inince bayrak düşer...
        self.assertFalse(mm._update_jump_arm(row, 54, 60, 58))
        self.assertFalse(row["jump_armed"])
        # ...ve sonraki geçiş yeniden alarm üretebilir.
        self.assertTrue(mm._update_jump_arm(row, 61, 60, 54))

    async def test_none_jump_never_fires(self):
        row = {"jump_armed": True}
        self.assertFalse(mm._update_jump_arm(row, None, 60, 70))


class SnapshotPurityTests(_MacdTestBase):
    """A10 — GET/yayın payload'ı global snapshot'ı kirletmemeli."""

    async def test_snapshot_payload_is_shallow_copy(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        await mm._compute_pass(1)

        payload = mm._snapshot_payload()
        payload["running"] = True
        payload["symbols"]["AAA"] = {"injected": True}

        self.assertNotIn("running", mm._SNAPSHOT)
        self.assertNotEqual({"injected": True}, mm._SNAPSHOT["symbols"]["AAA"])

    async def test_get_endpoint_returns_running_flag(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        response = await mm.get_macd_monitor()
        self.assertTrue(response["paper_only"])
        self.assertIn("running", response)
        self.assertIn("symbols", response)


class TrendCacheTests(_MacdTestBase):
    """C4/B8 — değişmeyen sembolün trend/sinyal hesabı yeniden yapılmamalı.

    Fiyat ve kapanmış barlar aynıysa 6 TF × OLS + ATR + kırılım + hacim
    hesabı pahalıdır; önbellekten okunmalı. MIN-MAX normalizasyonu ise
    evrene bağlı olduğundan her turda YENİDEN uygulanır.
    """

    async def test_unchanged_symbol_reuses_cached_trend(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
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
            # Fiyat ve barlar değişmedi → ikinci turda yeniden hesaplanmamalı
            await mm._compute_pass(2)
            self.assertEqual(1, calls["n"], "Değişmeyen sembol önbellekten okunmadı (B8)")
            # Fiyat değişince yeniden hesaplanmalı
            self.market.tick("AAA", 132.0)
            await mm._compute_pass(3)
            self.assertEqual(2, calls["n"], "Fiyat değişince trend tazelenmeli")
        finally:
            mm._symbol_trend_and_signals = original

    async def test_cache_is_cleaned_when_symbol_leaves_universe(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        await mm._compute_pass(1)
        self.assertIn("AAA", mm._trend_cache)
        self._universe([])
        await mm._compute_pass(2)
        self.assertNotIn("AAA", mm._trend_cache, "Evrenden çıkan sembol önbellekte kaldı")

    async def test_dir_field_is_descriptive_sign(self):
        """Yön alanı taşınır ama GÜÇ skorunu etkilemez (kanıt: contrarian)."""
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        await mm._compute_pass(1)
        row = mm._SNAPSHOT["symbols"]["AAA"]
        self.assertIn("dir", row)
        self.assertIsNotNone(row["dir"])
        self.assertGreater(row["dir"], 0, "Yükseliş serisinde yön pozitif olmalı")

        self._universe(["BBB"])
        self._fill("BBB", shape="flat_then_down")
        self.market.tick("BBB", 68.5)
        await mm._compute_pass(2)
        self.assertLess(mm._SNAPSHOT["symbols"]["BBB"]["dir"], 0,
                        "Düşüş serisinde yön negatif olmalı")


class DeltaBroadcastTests(_MacdTestBase):
    """C4/B9 — tam snapshot yerine yalnızca değişen semboller yayınlanmalı."""

    async def test_pending_changed_collects_touched_symbols(self):
        self._universe(["AAA", "BBB"])
        self._fill("AAA", shape="flat_then_up")
        self._fill("BBB", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        self.market.tick("BBB", 231.5)
        mm._pending_changed = set()
        await mm._compute_pass(1)
        self.assertEqual({"AAA", "BBB"}, mm._pending_changed)
        # Aynı verilerle tekrar hesaplanınca satırlar değişmez → yeni delta yok
        mm._pending_changed = set()
        await mm._compute_pass(2)
        self.assertEqual(set(), mm._pending_changed,
                         "Değişmeyen semboller delta'ya girmemeli")

    async def test_delta_payload_carries_only_requested_symbols(self):
        self._universe(["AAA", "BBB"])
        self._fill("AAA", shape="flat_then_up")
        self._fill("BBB", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        self.market.tick("BBB", 231.5)
        await mm._compute_pass(1)

        data = mm._delta_payload({"AAA"})
        self.assertTrue(data["delta"])
        self.assertEqual(["AAA"], list(data["symbols"].keys()))
        self.assertNotIn("BBB", data["symbols"])
        self.assertIn("universe", data)
        self.assertIn("jump_min", data)

    async def test_delta_payload_empty_for_unknown_symbol(self):
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        await mm._compute_pass(1)
        self.assertEqual({}, mm._delta_payload({"ZZZ"}))


class AlertEvidenceTests(_MacdTestBase):
    """C3 — alarm → sonuç kanıt katmanı kaydı (kritik yol DEĞİL)."""

    async def test_record_alert_evidence_writes_row(self):
        from app import database
        self._universe(["AAA"])
        self._fill("AAA", shape="flat_then_up")
        self.market.tick("AAA", 131.5)
        await mm._compute_pass(1)

        captured: list[dict] = []
        original = database.record_macd_monitor_alert

        async def fake(**kwargs):
            captured.append(kwargs)
            return 1

        database.record_macd_monitor_alert = fake
        try:
            await mm._record_alert_evidence("AAA", "jump", score=72, jump_min=60)
        finally:
            database.record_macd_monitor_alert = original

        self.assertEqual(1, len(captured))
        entry = captured[0]
        self.assertEqual("AAA", entry["symbol"])
        self.assertEqual("jump", entry["kind"])
        self.assertEqual(72, entry["score"])
        self.assertEqual(131.5, entry["price"])
        self.assertIsNotNone(entry["signals"], "Sinyal imzası kayda girmeli")
        self.assertIn("strength", entry["signals"])

    async def test_record_alert_evidence_swallows_errors(self):
        """Kanıt katmanı çökse bile alarm akışı bozulmamalı."""
        from app import database
        original = database.record_macd_monitor_alert

        async def boom(**kwargs):
            raise RuntimeError("db down")

        database.record_macd_monitor_alert = boom
        try:
            await mm._record_alert_evidence("AAA", "jump", score=72, jump_min=60)
        finally:
            database.record_macd_monitor_alert = original


class AlertEndpointTests(_MacdTestBase):
    async def test_alerts_endpoint_shape(self):
        from app import database
        originals = (database.list_macd_monitor_alerts, database.macd_monitor_alert_stats)

        async def fake_list(limit=100, symbol=None):
            return [{"id": 1, "symbol": "AAA", "kind": "jump", "score": 70}]

        async def fake_stats(days=30):
            return {"days": days, "kinds": {}, "pending": 0}

        database.list_macd_monitor_alerts = fake_list
        database.macd_monitor_alert_stats = fake_stats
        try:
            response = await mm.get_macd_monitor_alerts(limit=10, days=7)
        finally:
            database.list_macd_monitor_alerts, database.macd_monitor_alert_stats = originals

        self.assertTrue(response["paper_only"])
        self.assertEqual(1, len(response["alerts"]))
        self.assertEqual(7, response["stats"]["days"])


class SettingsTests(_MacdTestBase):
    async def test_to_bool_variants(self):
        self.assertTrue(mm._to_bool(True, False))
        self.assertTrue(mm._to_bool("TRUE", False))
        self.assertTrue(mm._to_bool("1", False))
        self.assertTrue(mm._to_bool("Açık", False))
        self.assertFalse(mm._to_bool("0", True))
        self.assertFalse(mm._to_bool(False, True))
        self.assertTrue(mm._to_bool(None, True))

    async def test_defaults_shape(self):
        defaults = mm._macd_settings_defaults()
        self.assertEqual(
            {"jump_min_score", "alerts_enabled", "push_enabled", "early_alerts_enabled"},
            set(defaults),
        )


if __name__ == "__main__":
    unittest.main()
