"""RADAR TARAMA DÜZELTMELERİ (docs/RADAR_TARAMA_ANALIZI_2026-10-15.md bölüm 3).

Her madde için kilit test; düzeltme geri alınırsa ilgili test KIRILIR.

  (1) database.evaluate_daily_rising_report — canlı fiyat yalnız AÇIK pencereye
      girer; MFE/hit girişi `notify_price`; anchor ayrı alan.
  (2) unified_outcomes — `detected_at` gerçek sinyal zamanı; dedup penceresi
      (symbol, horizon, floor(t/horizon)); boş mum dönen satır mühürlenir.
  (3) panel_score her kaynakta normalize_score(raw); rising/squeeze ham alanı
      `_raw_from_panel`; `_rank` yalnız panel.
  (4) Tek `gate_candidate()` hem `_notify` hem kombine listede; süzülen satır
      `blocked_by` ile UI çıktısında kalır.
  (5) Kombine yol velocity taramasını `journal_enabled=False` ile çağırır.
  (6) Kombine liste tekilleştirmesi SEMBOL bazında; ufuklar liste.
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app import database  # noqa: E402


# ---------------------------------------------------------------------------
# Ortak sahte DB (test_m4_database_fixes.py deseni)
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows) if rows else []
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _RoutedConn:
    """SQL metnine göre satır döndüren sahte bağlantı; çağrıları kaydeder."""

    def __init__(self, routes=(), default=()):
        self.routes = list(routes)
        self.default = list(default)
        self.calls = []
        self.commits = 0

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        self.calls.append((text, params))
        for needle, rows in self.routes:
            if needle in text:
                return _FakeCursor(rows, rowcount=1)
        return _FakeCursor(self.default, rowcount=1)

    def commit(self):
        self.commits += 1


def _patched_run_db(conn):
    async def runner(operation):
        return operation(conn)
    return runner


def _candles_5m(since_s: float, highs: list[float], lows: list[float]):
    """`historical_candles` satırları: since_s'den sonra 5 dk aralıklı mumlar."""
    rows = []
    for i, (h, lo) in enumerate(zip(highs, lows)):
        rows.append({"open_time": (since_s + 300 * (i + 1)) * 1000.0,
                     "high": h, "low": lo, "close": (h + lo) / 2.0})
    return rows


# ---------------------------------------------------------------------------
# (1) MÜHÜRLÜ PENCERE + notify_price GİRİŞİ
# ---------------------------------------------------------------------------
def _evaluate(monkeypatch, candidates, since_s, max_sec, live, candles):
    conn = _RoutedConn(routes=[("FROM historical_candles", candles)])
    monkeypatch.setattr(database, "_run_db", _patched_run_db(conn))
    return asyncio.run(database.evaluate_daily_rising_report(
        candidates, since_s, live_prices=live, max_sec=max_sec))


def test_sealed_window_ignores_live_price(monkeypatch):
    """Ufku BİTMİŞ (mühürlü) listede şimdiki fiyat MFE/MAE penceresine GİRMEZ:
    mumlar +%2'ye çıkmışken canlı fiyat +%10 olsa da MFE %2 kalır."""
    since = 1_700_000_000.0
    rows = _evaluate(
        monkeypatch,
        [{"symbol": "SEALTRY", "price": 100.0, "ceiling_pct": 5.0}],
        since, max_sec=600.0, live={"SEALTRY": 110.0},
        candles=_candles_5m(since, highs=[101.0, 102.0], lows=[99.5, 99.0]))
    assert len(rows) == 1
    r = rows[0]
    assert r["mfe_pct"] == pytest.approx(2.0), f"mühürlü MFE canlı fiyatla değişti: {r['mfe_pct']}"
    assert r["mae_pct"] == pytest.approx(-1.0)
    assert r["hit_ceiling"] is False, "tavan (%5) mum penceresinde vurulmadı"
    # Anlık fiyat yine raporlanır (değişim sütunu), ama pencereye katılmaz.
    assert r["current_price"] == 110.0


def test_open_window_includes_live_price(monkeypatch):
    """Ufku SÜREN (en yeni) listede canlı fiyat pencereye girer (eski davranış)."""
    since = time.time() - 120.0           # 2 dk önce gönderildi, 10 dk ömür
    rows = _evaluate(
        monkeypatch,
        [{"symbol": "OPENTRY", "price": 100.0, "ceiling_pct": 5.0}],
        since, max_sec=600.0, live={"OPENTRY": 110.0},
        candles=_candles_5m(since, highs=[101.0], lows=[99.5]))
    assert rows[0]["mfe_pct"] == pytest.approx(10.0)
    assert rows[0]["hit_ceiling"] is True


def test_mfe_entry_is_notify_price_not_anchor(monkeypatch):
    """Taşınan (carried) sembolde MFE/hit girişi BU listenin fiyatı
    (`notify_price`); zincir başı `anchor_price` ayrı alanda raporlanır —
    sinyal öncesi kazanç MFE'ye karışmaz (sim ile aynı giriş)."""
    since = 1_700_000_000.0
    rows = _evaluate(
        monkeypatch,
        [{"symbol": "CARRYTRY", "price": 80.0, "notify_price": 100.0,
          "anchor_price": 80.0, "ceiling_pct": 10.0}],
        since, max_sec=600.0, live=None,
        candles=_candles_5m(since, highs=[103.0], lows=[99.0]))
    r = rows[0]
    assert r["entry_price"] == 100.0
    assert r["mfe_pct"] == pytest.approx(3.0), "anchor (80) girişiyle MFE %28.75 olurdu"
    assert r["hit_ceiling"] is False
    assert r["anchor_price"] == 80.0
    assert r["anchor_mfe_pct"] == pytest.approx(28.75)


def test_report_summary_does_not_override_price_with_anchor():
    """monitoring.daily_rising_reports_summary: adayın `price`'ı anchor ile
    EZİLMEZ (DB fonksiyonu notify_price'ı kendisi seçer)."""
    import inspect
    from app.routers import monitoring as mo
    src = inspect.getsource(mo.daily_rising_reports_summary)
    assert '"price": x.get("anchor_price")' not in src


# ---------------------------------------------------------------------------
# Ortak kombine tarama sahnesi (test_daily_rising_combined deseni)
# ---------------------------------------------------------------------------
def _run_combined(monkeypatch, *, velocity_by_h: dict, rising=None, squeeze=None,
                  enrich=None, horizons=(5, 15), velocity_calls=None):
    from app.routers import monitoring as mo
    from app import binance_tr_public, rising_signals, early_discovery, snapback_service, macd_mtf
    from app.routers import velocity as _vel_mod

    async def _symbols(quote_asset="TRY"):
        syms = set()
        for rows in velocity_by_h.values():
            syms.update(r["symbol"] for r in rows)
        syms.update(r["symbol"] for r in (rising or []))
        syms.update(r["symbol"] for r in (squeeze or []))
        return sorted(syms)

    async def _velocity(*args, **kwargs):
        if velocity_calls is not None:
            velocity_calls.append((args, kwargs))
        h = kwargs.get("horizon_minutes", 5)
        rows = [dict(r) for r in velocity_by_h.get(h, [])]
        return {"candidates": [r for r in rows if r.get("passes", True)],
                "watchlist": [r for r in rows if not r.get("passes", True)]}

    async def _empty_momentum(*args, **kwargs):
        return []

    async def _squeeze(*args, **kwargs):
        return [dict(r) for r in (squeeze or [])]

    async def _empty_snapback(*args, **kwargs):
        return {"opportunities": []}

    async def _no_today(limit=200):
        return []

    async def _no_atr(symbol):
        return None

    async def _no_pot(symbol, price):
        return None

    monkeypatch.setattr(binance_tr_public, "trading_symbols", _symbols)
    monkeypatch.setattr(mo, "detect_velocity_candidates", _velocity)
    monkeypatch.setattr(mo, "_daily_momentum_candidates", _empty_momentum)
    monkeypatch.setattr(mo, "_short_squeeze_candidates", _squeeze)
    monkeypatch.setattr(mo, "_today_rising_rows", _no_today)
    monkeypatch.setattr(mo, "_live_atr_pct", _no_atr)
    monkeypatch.setattr(mo, "_compute_potential", _no_pot)
    monkeypatch.setattr(snapback_service, "scan_snapback_opportunities", _empty_snapback)
    monkeypatch.setattr(early_discovery, "top_candidates", lambda limit: [])
    monkeypatch.setattr(macd_mtf, "cached_compact", lambda symbol: None)
    monkeypatch.setattr(mo, "_ticker_price", lambda symbol: None)
    monkeypatch.setattr(mo.unified_signals, "enrich_candidates",
                        enrich if enrich is not None else (lambda rows: []))
    monkeypatch.setattr(rising_signals, "detect_rising_candidates",
                        lambda: [dict(r) for r in (rising or [])])
    monkeypatch.setattr(_vel_mod, "_active_horizons", lambda: list(horizons))
    return asyncio.run(mo._combined_scan_rows())


# ---------------------------------------------------------------------------
# (2) detected_at GERÇEK SİNYAL ZAMANI + ufuk kovalı dedup + boş mum mühürü
# ---------------------------------------------------------------------------
def test_candidate_row_keeps_real_signal_time():
    """`_candidate_row`: satırın `detected_at`'i (yoksa `created_at`) aynen
    geçer; yalnız ikisi de yoksa şimdi."""
    from app import unified_outcomes as uo
    row = {"symbol": "ABCTRY", "price": 1.0, "horizon_minutes": 5,
           "detected_at": 1_750_000_000.0}
    assert uo._candidate_row(row)["detected_at"] == 1_750_000_000.0
    row2 = {"symbol": "ABCTRY", "price": 1.0, "horizon_minutes": 5,
            "created_at": 1_750_000_100.0}
    assert uo._candidate_row(row2)["detected_at"] == 1_750_000_100.0
    before = time.time()
    got = uo._candidate_row({"symbol": "ABCTRY", "price": 1.0})["detected_at"]
    assert got >= before


def test_unified_dedup_window_is_horizon_bucket():
    """Dedup anahtarı (symbol, horizon, floor(detected_at/horizon)): aynı
    ufuk kovasındaki iki tespit aynı pencereye düşer, komşu kova düşmez."""
    t = 1_750_000_130.0
    start, end = database.unified_dedup_window(5, t)
    assert start % 300 == 0 and end - start == 300.0
    assert start <= t < end
    s2, _ = database.unified_dedup_window(5, t + 20)
    assert s2 == start                       # aynı kova (20 sn sonra)
    s3, _ = database.unified_dedup_window(5, end + 1)
    assert s3 == end                         # komşu kova
    # Ufuksuz satır (0 dk) → 60 sn taban kova.
    s0, e0 = database.unified_dedup_window(0, t)
    assert e0 - s0 == 60.0


def test_save_unified_candidates_dedups_by_bucket():
    """`save_unified_candidates` NOT EXISTS koşulu kova penceresiyle
    (detected_at >= start AND < end) çalışır; eşitlik değil."""
    conn = _RoutedConn()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "_run_db", _patched_run_db(conn))
        asyncio.run(database.save_unified_candidates([{
            "symbol": "ABCTRY", "horizon_minutes": 15, "sources": '["velocity"]',
            "scan_score": 70.0, "entry_price": 1.0, "detected_at": 1_750_000_130.0,
        }]))
    inserts = [(sql, p) for sql, p in conn.calls if "INSERT INTO unified_candidate_outcomes" in sql]
    assert inserts, "insert yok"
    sql, params = inserts[0]
    assert "detected_at >= ?" in sql and "detected_at < ?" in sql
    assert "AND detected_at=?" not in sql
    start, end = database.unified_dedup_window(15, 1_750_000_130.0)
    assert tuple(params[-2:]) == (start, end)


def test_fill_seals_row_when_no_candles(monkeypatch):
    """Boş mum dönen satır MÜHÜRLENİR (mfe/mae/hit None, outcome_filled_at
    dolu) → `LIMIT 200` kuyruğunu süresiz tıkamaz. Dolu sayılmaz."""
    from app import unified_outcomes as uo
    pending = [{"id": 11, "symbol": "GONETRY", "horizon_minutes": 5,
                "entry_price": 1.0, "detected_at": 1_750_000_000.0}]

    async def _pending(older_than_sec, limit=200):
        return [dict(r) for r in pending]

    updates = []

    async def _update(row_id, mfe_pct, mae_pct, hit):
        updates.append((row_id, mfe_pct, mae_pct, hit))

    async def _klines(*_a, **_k):
        return []

    monkeypatch.setattr(uo.database, "get_unified_pending_outcomes", _pending)
    monkeypatch.setattr(uo.database, "update_unified_outcome", _update)
    monkeypatch.setattr(uo, "klines", _klines)
    filled = asyncio.run(uo.fill_pending_outcomes(max_age_sec=0))
    assert filled == 0
    assert updates == [(11, None, None, None)]


def test_update_unified_outcome_keeps_hit_null():
    """`update_unified_outcome(hit=None)` NULL yazar (False DEĞİL) — mühürlü
    ama ölçülemeyen satır isabet oranını düşürmez."""
    conn = _RoutedConn()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "_run_db", _patched_run_db(conn))
        asyncio.run(database.update_unified_outcome(11, None, None, None))
    sql, params = conn.calls[-1]
    assert "UPDATE unified_candidate_outcomes" in sql
    assert params[2] is None


def test_combined_rows_carry_candidate_detected_at(monkeypatch):
    """combined_scan_rows: satırın `detected_at`'i adayın kendi zaman damgası
    (velocity satırı → tarama anı, rising satırı → kendi `detected_at`'i),
    her /latest yenilemesinde `time.time()` DEĞİL."""
    rows = _run_combined(monkeypatch, velocity_by_h={5: [
        {"symbol": "VELTRY", "price": 10.0, "velocity_score": 1000,
         "horizon_minutes": 5, "ceiling_pct": 2.0, "detected_at": 1_750_000_000.0,
         "passes": True},
    ]}, rising=[{"symbol": "RISTRY", "score": 70.0, "horizon_minutes": 5,
                "price": 2.0, "kind": "yukselis", "detected_at": 1_750_000_050.0}])
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["VELTRY"]["detected_at"] == 1_750_000_000.0
    assert by_sym["RISTRY"]["detected_at"] == 1_750_000_050.0


# ---------------------------------------------------------------------------
# (3) panel_score HER KAYNAKTA normalize_score(raw); rising/squeeze ham alanı
#     _raw_from_panel; _rank yalnız panel
# ---------------------------------------------------------------------------
def test_fusion_uses_normalized_panel_when_panel_missing(monkeypatch):
    """enrich_candidates: `panel_score` yoksa ham velocity_score (1800) DOĞRUDAN
    füzyona girmez; normalize_score(1800) (~74) girer. Eskiden min(100, 1800)
    = 100 ile doyuyordu."""
    from app import unified_signals as us
    from app.unified_scan import normalize_score
    monkeypatch.setattr(us, "macd_components", lambda sym: ({}, {}))
    monkeypatch.setattr(us, "enabled", lambda: False)
    cand = {"symbol": "RAWTRY", "velocity_score": 1800.0}
    us.enrich_candidates([cand])
    expected = normalize_score(1800.0)
    assert expected < 100.0
    assert cand["unified_score"] == pytest.approx(expected, abs=0.2), \
        f"füzyon ham skorla doydu: {cand['unified_score']}"


def test_rising_rows_use_raw_from_panel(monkeypatch):
    """Kombine yolda rising satırı: panel = 0-100 skoru (70), ham alan
    `_raw_from_panel(70)`; kalite puanı panel 70'ten türer (0.6·70 + 8 = 50),
    ikinci kez log-normalize edilmez (70→~42 → 33.2 olurdu)."""
    from app.unified_scan import _raw_from_panel
    rows = _run_combined(monkeypatch, velocity_by_h={}, rising=[
        {"symbol": "RISTRY", "score": 70.0, "horizon_minutes": 5,
         "price": 2.0, "kind": "yukselis"}])
    assert len(rows) == 1
    r = rows[0]
    assert r["panel_score"] == pytest.approx(70.0)
    assert r["velocity_score"] == pytest.approx(_raw_from_panel(70.0), rel=1e-6)
    assert r["scan_score"] == pytest.approx(50.0)


def test_short_squeeze_rows_use_raw_from_panel(monkeypatch):
    """`_short_squeeze_candidates`: squeeze skoru (40-187) 0-100'e kırpılıp
    panel olur; ham alan `_raw_from_panel(panel)`; ham squeeze skoru
    `squeeze_score` alanında korunur."""
    from app.routers import monitoring as mo
    from app import derivatives_service as ds
    from app.unified_scan import _raw_from_panel

    async def _scan(symbols, top_n=20):
        return [{"symbol": "SQZTRY", "score": 70.0, "funding_rate_pct": -0.05,
                 "funding_state": "EXTREME_SHORT", "short_squeeze_potential": True},
                {"symbol": "BIGTRY", "score": 187.0, "funding_rate_pct": -0.2,
                 "funding_state": "EXTREME_SHORT", "short_squeeze_potential": True}]

    async def _confirm(symbol):
        return {}

    async def _atr(symbol):
        return 1.0

    async def _pot(symbol, price):
        return None

    monkeypatch.setattr(ds, "scan_short_squeeze", _scan)
    monkeypatch.setattr(ds, "squeeze_confirmation", _confirm)
    monkeypatch.setattr(mo, "_ticker_price", lambda symbol: 1.0)
    monkeypatch.setattr(mo, "_live_atr_pct", _atr)
    monkeypatch.setattr(mo, "_compute_potential", _pot)
    rows = asyncio.run(mo._short_squeeze_candidates(["SQZTRY", "BIGTRY"]))
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["SQZTRY"]["panel_score"] == pytest.approx(70.0)
    assert by_sym["SQZTRY"]["velocity_score"] == pytest.approx(_raw_from_panel(70.0), rel=1e-6)
    assert by_sym["SQZTRY"]["squeeze_score"] == pytest.approx(70.0)
    assert by_sym["BIGTRY"]["panel_score"] == pytest.approx(100.0)
    assert by_sym["BIGTRY"]["squeeze_score"] == pytest.approx(187.0)


def test_rank_compares_panel_only(monkeypatch):
    """(sembol, ufuk) tekilleştirmesinde `_rank` YALNIZ panel ile kıyaslar:
    velocity ham 300 (panel ~56) ile rising panel 70 → rising kazanır. Eski
    `panel_score or velocity_score` ham 300'ü panel 70 ile kıyaslayıp velocity'yi
    seçiyordu. Her kaynak satırı `panel_score` taşır."""
    from app.unified_scan import normalize_score
    rows = _run_combined(monkeypatch, velocity_by_h={5: [
        {"symbol": "DUOTRY", "price": 10.0, "velocity_score": 300.0,
         "horizon_minutes": 5, "ceiling_pct": 2.0, "passes": True},
    ]}, rising=[{"symbol": "DUOTRY", "score": 70.0, "horizon_minutes": 5,
                "price": 10.0, "kind": "yukselis"}])
    assert len(rows) == 1
    r = rows[0]
    assert normalize_score(300.0) < 70.0           # sahne ön koşulu
    assert r["panel_score"] == pytest.approx(70.0), f"panel 70 kazanmalıydı: {r}"
    assert r["strategy"] == "rising", "seçilen satır rising olmalı (velocity → combined)"
    assert "rising" in r["signal_sources"]


# ---------------------------------------------------------------------------
# (4) TEK gate_candidate(): master-surge sert blok + failed_layer==1 + passes
#     + exhausted/üst fitil/spread — hem _notify hem kombine liste
# ---------------------------------------------------------------------------
def test_gate_candidate_reasons():
    from app.routers import monitoring as mo
    g = mo.gate_candidate
    # Temiz radar adayı → None.
    assert g({"symbol": "OKTRY", "passes": True, "velocity_score": 2000}) is None
    # Kaynak satırında `passes` alanı yok (rising/pulse/snapback) → kapı yok.
    assert g({"symbol": "RISTRY", "strategy": "rising"}) is None
    # Füzyon-tek aday: passes False ama unified_pass → kapı yok.
    assert g({"symbol": "FUSTRY", "passes": False, "unified_pass": True}) is None
    # Master Surge SERT risk bloğu.
    assert g({"symbol": "A", "passes": True,
              "master_surge": {"block_reason": "EXTREME_LONG_LIQUIDATION_RISK"}}) \
        == "EXTREME_LONG_LIQUIDATION_RISK"
    # Katman 1 (likidite) elemesi artık blok.
    assert g({"symbol": "A", "passes": True,
              "master_surge": {"failed_layer": 1, "gate": "LIQUIDITY"}}).startswith("master_surge_katman1")
    # Katman 2-4 / yetersiz 4'lü teyit SKORLAMA girdisidir, blok DEĞİL (P0-1).
    assert g({"symbol": "A", "passes": True,
              "master_surge": {"failed_layer": 3, "passed": False, "gate": "NO_4WAY_CONFLUENCE"}}) is None
    # Watchlist satırı (passes False) → block_reason, yoksa genel neden.
    assert g({"symbol": "A", "passes": False, "block_reason": "asiri_spread:1.20%>0.70%_siniri"}) \
        == "asiri_spread:1.20%>0.70%_siniri"
    assert g({"symbol": "A", "passes": False}) == "radar_kapisi_gecilmedi"
    # exhausted / üst fitil bayrakları tek başına da blok.
    assert g({"symbol": "A", "passes": True, "exhausted": "rsi_asiri_alim:91"}) == "rsi_asiri_alim:91"
    assert g({"symbol": "A", "passes": True, "rejection_wick": True}).startswith("ust_fitil")
    # Boş/bozuk girdi düşürmez.
    assert g({}) is None
    assert g({"master_surge": "garbage", "passes": True}) is None


def test_notify_uses_gate_candidate(monkeypatch):
    """`_notify`: kapıya takılan aday (exhausted) yüksek skorlu olsa bile
    bildirim ÜRETMEZ; tek kaynak `gate_candidate`."""
    import inspect
    from app.routers import monitoring as mo
    assert "gate_candidate(" in inspect.getsource(mo._notify)

    async def _no_pending(symbols):
        return {}
    monkeypatch.setattr(mo.database, "get_pending_monitoring_notifications", _no_pending)
    monkeypatch.setattr(mo, "_effective_min_raw_score", lambda s: 0.0)
    monkeypatch.setattr(mo, "_effective_min_score", lambda s: 0.0)
    monkeypatch.setattr(mo, "_in_quiet_hours", lambda s: False)
    cand = {"symbol": "EXHTRY", "velocity_score": 5000.0, "target_pct": 2.0,
            "price": 1.0, "horizon_minutes": 5, "passes": True,
            "exhausted": "mfi_asiri_alim:88"}
    out = asyncio.run(mo._notify([cand], {"enabled": True}))
    assert out == []
    blocked = mo._monitoring_state.get("surge_blocked_symbols", {}).get("EXHTRY")
    assert blocked and blocked["reason"] == "mfi_asiri_alim:88"


def test_combined_rows_keep_blocked_with_reason(monkeypatch):
    """Kombine çıktı: süzülen satır LİSTEDEN DÜŞMEZ, `blocked_by` ile kalır
    (UI gri gösterir) ve sıralamada temiz satırların ARKASINA gider."""
    rows = _run_combined(monkeypatch, velocity_by_h={5: [
        {"symbol": "CLEANTRY", "price": 1.0, "velocity_score": 800.0,
         "horizon_minutes": 5, "ceiling_pct": 2.0, "passes": True},
        {"symbol": "SPRDTRY", "price": 1.0, "velocity_score": 9000.0,
         "horizon_minutes": 5, "ceiling_pct": 2.0, "passes": False,
         "block_reason": "asiri_spread:1.20%>0.70%_siniri"},
    ]})
    by_sym = {r["symbol"]: r for r in rows}
    assert set(by_sym) == {"CLEANTRY", "SPRDTRY"}
    assert by_sym["CLEANTRY"]["blocked_by"] is None
    assert by_sym["SPRDTRY"]["blocked_by"] == "asiri_spread:1.20%>0.70%_siniri"
    assert [r["symbol"] for r in rows] == ["CLEANTRY", "SPRDTRY"], "bloklu satır sona gitmeli"


def test_send_combined_list_excludes_blocked(monkeypatch):
    """Gönderilen TOP N'e `blocked_by` dolu satır GİRMEZ (combined_paper da
    açmaz); puanı en yüksek olsa bile."""
    from app.routers import monitoring as mo
    import app.whatsapp_notify as wn

    async def _scan():
        return [
            {"symbol": "BLKTRY", "price": 1.0, "scan_score": 95.0,
             "blocked_by": "mfi_asiri_alim:90", "horizon_minutes": 5},
            {"symbol": "OKTRY", "price": 1.0, "scan_score": 80.0,
             "blocked_by": None, "horizon_minutes": 5},
        ]

    async def _last(kind=mo.COMBINED_LIST_KIND):
        return None

    sent_rows = []

    async def _save(item):
        sent_rows.append(item)
        return 1

    async def _send(text):
        return True

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(mo, "_combined_scan_rows", _scan)
    monkeypatch.setattr(mo.database, "last_daily_rising_report", _last)
    monkeypatch.setattr(mo.database, "save_daily_rising_report", _save)
    monkeypatch.setattr(mo, "_persist_combined_scan_rows", _noop)
    monkeypatch.setattr(mo, "_record_unified_outcomes", _noop)
    monkeypatch.setattr(wn, "whatsapp_enabled", lambda: True)
    monkeypatch.setattr(wn, "send_whatsapp", _send)
    monkeypatch.setattr(wn, "format_combined_list", lambda cands, **k: "X")
    cfg = {"top_n": 3, "min_score": 10.0, "list_min": 15, "track_min": 5}
    assert asyncio.run(mo._send_combined_list(cfg=cfg, force=True)) is True
    syms = [c["symbol"] for c in sent_rows[-1]["candidates"]]
    assert syms == ["OKTRY"], f"bloklu aday listeye girdi: {syms}"


# ---------------------------------------------------------------------------
# (5) Kombine yol velocity taramasını journal_enabled=False ile çağırır
# ---------------------------------------------------------------------------
def test_combined_scan_calls_velocity_without_journal(monkeypatch):
    """combined_scan_rows → detect_velocity_candidates her ufukta
    `journal_enabled=False`: /latest yenilemesi (20 sn) ve manuel tarama
    kalibrasyon journal'ına kopya yazmaz (yalnız `_run_scan` yazar)."""
    calls = []
    _run_combined(monkeypatch, velocity_by_h={}, horizons=(5, 15, 30),
                  velocity_calls=calls)
    assert len(calls) == 3, f"3 ufuk beklenir: {calls}"
    for _args, kwargs in calls:
        assert kwargs.get("journal_enabled") is False, \
            f"kombine yol journal yazıyor: {kwargs}"


# ---------------------------------------------------------------------------
# (6) Kombine liste tekilleştirmesi SEMBOL bazında; ufuklar liste
# ---------------------------------------------------------------------------
def test_dedup_rows_by_symbol_keeps_best_and_collects_horizons():
    from app.unified_scan import dedup_rows_by_symbol
    rows = [
        {"symbol": "AAATRY", "horizon_minutes": 5, "scan_score": 90.0},
        {"symbol": "AAATRY", "horizon_minutes": 15, "scan_score": 85.0},
        {"symbol": "BBBTRY", "horizon_minutes": 5, "scan_score": 80.0},
        {"symbol": "AAATRY", "horizon_minutes": 30, "scan_score": 95.0},
    ]
    out = dedup_rows_by_symbol(rows)
    assert [r["symbol"] for r in out] == ["AAATRY", "BBBTRY"]
    best = out[0]
    assert best["scan_score"] == 95.0 and best["horizon_minutes"] == 30
    assert best["horizons"] == [5, 15, 30]
    assert out[1]["horizons"] == [5]
    # Girdi satırları DEĞİŞTİRİLMEZ (kopya döner).
    assert "horizons" not in rows[0]


def test_send_combined_list_dedups_by_symbol(monkeypatch):
    """Aynı sembol 5m+15m olarak TOP 2'yi tek başına DOLDURAMAZ: liste
    sembol bazında tekildir, ufuklar rozet (`horizons`)."""
    from app.routers import monitoring as mo
    import app.whatsapp_notify as wn

    async def _scan():
        return [
            {"symbol": "DUPTRY", "price": 1.0, "scan_score": 92.0, "horizon_minutes": 5},
            {"symbol": "DUPTRY", "price": 1.0, "scan_score": 90.0, "horizon_minutes": 15},
            {"symbol": "OTHTRY", "price": 1.0, "scan_score": 70.0, "horizon_minutes": 5},
        ]

    async def _last(kind=mo.COMBINED_LIST_KIND):
        return None

    sent_rows = []

    async def _save(item):
        sent_rows.append(item)
        return 1

    async def _send(text):
        return True

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(mo, "_combined_scan_rows", _scan)
    monkeypatch.setattr(mo.database, "last_daily_rising_report", _last)
    monkeypatch.setattr(mo.database, "save_daily_rising_report", _save)
    monkeypatch.setattr(mo, "_persist_combined_scan_rows", _noop)
    monkeypatch.setattr(mo, "_record_unified_outcomes", _noop)
    monkeypatch.setattr(wn, "whatsapp_enabled", lambda: True)
    monkeypatch.setattr(wn, "send_whatsapp", _send)
    monkeypatch.setattr(wn, "format_combined_list", lambda cands, **k: "X")
    cfg = {"top_n": 2, "min_score": 10.0, "list_min": 15, "track_min": 5}
    assert asyncio.run(mo._send_combined_list(cfg=cfg, force=True)) is True
    cands = sent_rows[-1]["candidates"]
    assert [c["symbol"] for c in cands] == ["DUPTRY", "OTHTRY"]
    assert cands[0]["horizons"] == [5, 15]
    assert cands[0]["horizon_minutes"] == 5          # en iyi satırın ufku
