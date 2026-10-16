"""TARAMA GÜNCELLEMESİ (2026-10-16): kanıta dayalı liste politikası.

Kaynak: docs/BACKTEST_RAPORU_7G_2026-10-16.md §2.5/§3,
docs/RADAR_TARAMA_ANALIZI_2026-10-15.md §3, docs/DENEY_KAYDI.md.

  (1) Aile kara listesi `RADAR_DISABLED_SOURCE_FAMILIES` (vars.
      short_squeeze,snapback) — `gate_candidate` yalnız TÜM etiketleri kara
      listede olan adayı bloklar; boş değer kapatır.
  (2) Liste skor tabanı `RADAR_LIST_MIN_SCAN_SCORE` (vars. 0 = kapalı) — journal
      `scan_score` (= `_combined_quality_score`, 0-99) alanında; kombine liste
      etkin tabanı max(kullanıcı `min_score`, ölçülen taban).
  (3) jump+velocity uyum bonusu `RADAR_JUMP_VELOCITY_BONUS` (vars. 0 = kapalı),
      99 tavanı korunur.
  (4) Otonom paper `AUTO_PAPER_ALLOWED_MODES` (vars. trend_devam) env'den.

Fixture/mock deseni `tests/test_radar_fixes.py` ile aynıdır.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")


# ---------------------------------------------------------------------------
# Ortak kombine tarama koşucusu (test_radar_fixes._run_combined kopyası)
# ---------------------------------------------------------------------------
def _run_combined(monkeypatch, *, velocity_by_h: dict, squeeze=None, enrich=None,
                  horizons=(5, 15)):
    from app.routers import monitoring as mo
    from app import binance_tr_public, rising_signals, early_discovery, snapback_service, macd_mtf
    from app.routers import velocity as _vel_mod

    async def _symbols(quote_asset="TRY"):
        syms = set()
        for rows in velocity_by_h.values():
            syms.update(r["symbol"] for r in rows)
        syms.update(r["symbol"] for r in (squeeze or []))
        return sorted(syms)

    async def _velocity(*args, **kwargs):
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
    monkeypatch.setattr(rising_signals, "detect_rising_candidates", lambda: [])
    monkeypatch.setattr(_vel_mod, "_active_horizons", lambda: list(horizons))
    return asyncio.run(mo._combined_scan_rows())


# ---------------------------------------------------------------------------
# (1) Aile kara listesi
# ---------------------------------------------------------------------------
def test_config_defaults():
    from app.config import config
    assert config.RADAR_DISABLED_SOURCE_FAMILIES == "short_squeeze,snapback"
    assert config.RADAR_LIST_MIN_SCAN_SCORE == 0.0   # kapalı; bkz. config yorumu
    assert config.RADAR_JUMP_VELOCITY_BONUS == 0.0
    assert config.AUTO_PAPER_ALLOWED_MODES == "trend_devam"


def test_family_blocklist_blocks_short_squeeze_only(monkeypatch):
    from app.routers import monitoring as mo
    monkeypatch.setattr(mo.config, "RADAR_LIST_MIN_SCAN_SCORE", 0.0)
    reason = mo.gate_candidate({"symbol": "SQZTRY", "strategy": "short_squeeze",
                                "unified_sources": ["short_squeeze"]})
    assert reason == "aile devre dışı: short_squeeze"
    # snapback-tek de bloklanır; `sources` alanı da sayılır.
    assert mo.gate_candidate({"symbol": "SNPTRY", "sources": ["snapback"]}) \
        == "aile devre dışı: snapback"
    # kombine satırındaki `signal_sources` da okunur.
    assert mo.gate_candidate({"symbol": "SQZTRY", "signal_sources": ["short_squeeze"]}) \
        .startswith("aile devre dışı")


def test_family_blocklist_keeps_mixed_candidates(monkeypatch):
    from app.routers import monitoring as mo
    monkeypatch.setattr(mo.config, "RADAR_LIST_MIN_SCAN_SCORE", 0.0)
    g = mo.gate_candidate
    assert g({"symbol": "A", "unified_sources": ["short_squeeze", "velocity"]}) is None
    assert g({"symbol": "A", "unified_sources": ["snapback", "jump"]}) is None
    assert g({"symbol": "A", "unified_sources": ["short_squeeze"], "sources": ["macd_mtf"]}) is None
    # `fusion` kara listede DEĞİL (n=35, GA geniş).
    assert g({"symbol": "A", "unified_sources": ["fusion"]}) is None
    # Etiketi hiç olmayan aday bloklanmaz (boş küme ⊆ kara liste tuzağı yok).
    assert g({"symbol": "A", "passes": True, "velocity_score": 2000}) is None


def test_family_blocklist_env_override_empty_disables(monkeypatch):
    from app.routers import monitoring as mo
    monkeypatch.setattr(mo.config, "RADAR_LIST_MIN_SCAN_SCORE", 0.0)
    monkeypatch.setattr(mo.config, "RADAR_DISABLED_SOURCE_FAMILIES", "")
    assert mo._disabled_source_families() == set()
    assert mo.gate_candidate({"symbol": "SQZTRY", "unified_sources": ["short_squeeze"]}) is None
    # Virgüllü/boşluklu/büyük harfli env değeri normalize edilir.
    monkeypatch.setattr(mo.config, "RADAR_DISABLED_SOURCE_FAMILIES", " Short_Squeeze , ,FUSION ")
    assert mo._disabled_source_families() == {"short_squeeze", "fusion"}
    assert mo.gate_candidate({"symbol": "A", "unified_sources": ["fusion"]}) \
        == "aile devre dışı: fusion"
    assert mo.gate_candidate({"symbol": "A", "unified_sources": ["snapback"]}) is None


def test_combined_rows_block_short_squeeze_only_with_reason(monkeypatch):
    """Kombine liste: `_short_squeeze_candidates` çıktısı aynı kapıdan geçer;
    satır listeden DÜŞMEZ, `blocked_by` dolar (UI gri)."""
    from app.routers import monitoring as mo
    monkeypatch.setattr(mo.config, "RADAR_LIST_MIN_SCAN_SCORE", 0.0)
    rows = _run_combined(monkeypatch, velocity_by_h={5: [
        {"symbol": "VELTRY", "price": 1.0, "velocity_score": 2000.0,
         "horizon_minutes": 5, "ceiling_pct": 2.0, "passes": True},
    ]}, squeeze=[
        {"symbol": "SQZTRY", "price": 1.0, "velocity_score": 9000.0,
         "panel_score": 90.0, "horizon_minutes": 0, "ceiling_pct": 3.0,
         "strategy": "short_squeeze"},
    ])
    by_sym = {r["symbol"]: r for r in rows}
    assert set(by_sym) == {"VELTRY", "SQZTRY"}
    assert by_sym["SQZTRY"]["blocked_by"] == "aile devre dışı: short_squeeze"
    assert by_sym["VELTRY"]["blocked_by"] is None
    assert [r["symbol"] for r in rows] == ["VELTRY", "SQZTRY"], "bloklu satır sona gitmeli"


# ---------------------------------------------------------------------------
# (2) Skor tabanı — journal `scan_score` alanında
# ---------------------------------------------------------------------------
def test_journal_scan_score_is_quality_score():
    """`unified_outcomes._candidate_row` journal'a satırın `scan_score`'unu
    (kombine satırda = kalite puanı 0-99) yazar; panel 0-100 DEĞİL."""
    from app import unified_outcomes as uo
    row = {"symbol": "ABCTRY", "price": 1.0, "horizon_minutes": 5,
           "scan_score": 72.4, "quality_score": 72.4, "panel_score": 95.0,
           "velocity_score": 9000.0, "detected_at": 1_700_000_000.0}
    out = uo._candidate_row(row)
    assert out["scan_score"] == 72.4


def test_score_floor_blocks_65_passes_70(monkeypatch):
    from app.routers import monitoring as mo
    g = mo.gate_candidate
    monkeypatch.setattr(mo.config, "RADAR_LIST_MIN_SCAN_SCORE", 70.0)
    assert g({"symbol": "A", "scan_score": 65.0}) == "skor tabanı altı (65.0 < 70)"
    assert g({"symbol": "A", "scan_score": 70.0}) is None
    assert g({"symbol": "A", "scan_score": 69.9}).startswith("skor tabanı altı")
    # DOĞRU alan: panel 95 olsa bile kalite 65 bloklanır; kalite 70 panel 40 geçer.
    assert g({"symbol": "A", "scan_score": 65.0, "panel_score": 95.0, "velocity_score": 9000}) \
        .startswith("skor tabanı altı")
    assert g({"symbol": "A", "scan_score": 70.0, "panel_score": 40.0}) is None
    # Kombine yol puanı parametreyle geçirir; parametre alanın önüne geçer.
    assert g({"symbol": "A", "passes": True}, scan_score=65.0).startswith("skor tabanı altı")
    assert g({"symbol": "A", "scan_score": 65.0}, scan_score=71.0) is None
    # `quality_score` yedek alan.
    assert g({"symbol": "A", "quality_score": 60.0}).startswith("skor tabanı altı")
    # Alan YOKSA (radar bildirim yolu: yalnız ham/panel skor) taban uygulanmaz.
    assert g({"symbol": "A", "passes": True, "velocity_score": 300.0}) is None
    # 0 = kapalı.
    monkeypatch.setattr(mo.config, "RADAR_LIST_MIN_SCAN_SCORE", 0.0)
    assert g({"symbol": "A", "scan_score": 5.0}) is None


def test_combined_rows_mark_low_quality_with_floor_reason(monkeypatch):
    """Kombine satırda taban, satırın `scan_score`'u (kalite) ile aynı değere
    uygulanır: 800 ham tek kaynak → kalite ~39.6 < 70 → bloklu."""
    from app.routers import monitoring as mo
    monkeypatch.setattr(mo.config, "RADAR_LIST_MIN_SCAN_SCORE", 70.0)  # varsayılan 0 (kapalı)
    rows = _run_combined(monkeypatch, velocity_by_h={5: [
        {"symbol": "LOWTRY", "price": 1.0, "velocity_score": 800.0,
         "horizon_minutes": 5, "ceiling_pct": 2.0, "passes": True},
    ]})
    assert len(rows) == 1
    row = rows[0]
    assert row["scan_score"] < 70
    assert row["blocked_by"] == f"skor tabanı altı ({row['scan_score']:.1f} < 70)"


def test_send_combined_list_effective_floor_is_max(monkeypatch):
    """Kullanıcı `min_score`=10 olsa bile etkin taban max(10, 70)=70; 60 puanlı
    temiz satır gönderilmez, 80 gönderilir."""
    from app.routers import monitoring as mo
    import app.whatsapp_notify as wn
    monkeypatch.setattr(mo.config, "RADAR_LIST_MIN_SCAN_SCORE", 70.0)  # varsayılan 0 (kapalı)

    scan_rows = [
        {"symbol": "MIDTRY", "price": 1.0, "scan_score": 60.0,
         "blocked_by": None, "horizon_minutes": 5},
    ]

    async def _scan():
        return [dict(r) for r in scan_rows]

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
    assert asyncio.run(mo._send_combined_list(cfg=cfg, force=True)) is False
    assert sent_rows == []
    scan_rows.append({"symbol": "OKTRY", "price": 1.0, "scan_score": 80.0,
                      "blocked_by": None, "horizon_minutes": 5})
    assert asyncio.run(mo._send_combined_list(cfg=cfg, force=True)) is True
    assert [c["symbol"] for c in sent_rows[-1]["candidates"]] == ["OKTRY"]
    # Kullanıcı tabanı ölçülenin ÜSTÜNE çıkabilir.
    cfg["min_score"] = 85.0
    assert asyncio.run(mo._send_combined_list(cfg=cfg, force=True)) is False


# ---------------------------------------------------------------------------
# (3) jump+velocity uyum bonusu
# ---------------------------------------------------------------------------
def _quality(c):
    from app.unified_scan import _combined_quality_score
    return _combined_quality_score(c)[0]


def test_jump_velocity_bonus_off_by_default():
    from app.config import config
    assert float(config.RADAR_JUMP_VELOCITY_BONUS) == 0.0
    base = _quality({"velocity_score": 2000.0, "unified_sources": ["velocity"]})
    both = _quality({"velocity_score": 2000.0, "unified_sources": ["velocity", "jump"]})
    # Kapalıyken yalnız ikinci kaynağın +8'i vardır, ek bonus yoktur.
    assert both == pytest.approx(base + 8.0, abs=0.11)


def test_jump_velocity_bonus_only_when_both_sources(monkeypatch):
    from app import unified_scan as us
    monkeypatch.setattr(us.config, "RADAR_JUMP_VELOCITY_BONUS", 8.0)
    assert us._jump_velocity_bonus({"unified_sources": ["velocity", "jump"]}) == 8.0
    assert us._jump_velocity_bonus({"sources": ["velocity"], "unified_sources": ["jump"]}) == 8.0
    assert us._jump_velocity_bonus({"unified_sources": ["velocity"]}) == 0.0
    assert us._jump_velocity_bonus({"unified_sources": ["jump", "early"]}) == 0.0
    assert us._jump_velocity_bonus({}) == 0.0
    two = _quality({"velocity_score": 2000.0, "unified_sources": ["velocity", "early"]})
    both = _quality({"velocity_score": 2000.0, "unified_sources": ["velocity", "jump"]})
    assert both == pytest.approx(two + 8.0, abs=0.11)
    monkeypatch.setattr(us.config, "RADAR_JUMP_VELOCITY_BONUS", 0.0)
    assert us._jump_velocity_bonus({"unified_sources": ["velocity", "jump"]}) == 0.0
    # Negatif/bozuk değer = kapalı.
    monkeypatch.setattr(us.config, "RADAR_JUMP_VELOCITY_BONUS", -5.0)
    assert us._jump_velocity_bonus({"unified_sources": ["velocity", "jump"]}) == 0.0
    monkeypatch.setattr(us.config, "RADAR_JUMP_VELOCITY_BONUS", "bozuk")
    assert us._jump_velocity_bonus({"unified_sources": ["velocity", "jump"]}) == 0.0


def test_jump_velocity_bonus_respects_99_ceiling(monkeypatch):
    from app import unified_scan as us
    monkeypatch.setattr(us.config, "RADAR_JUMP_VELOCITY_BONUS", 50.0)
    c = {"velocity_score": 10_000_000.0,
         "unified_sources": ["velocity", "jump", "early"],
         "master_surge": {"confluence_count": 4}}
    assert _quality(c) == 99.0


# ---------------------------------------------------------------------------
# (4) Otonom paper mod listesi env'den
# ---------------------------------------------------------------------------
def test_auto_paper_allowed_modes_default_trend_devam_only(monkeypatch):
    from app.routers import auto_paper as ap
    from app.config import config
    assert config.AUTO_PAPER_ALLOWED_MODES == "trend_devam"
    assert ap._allowed_modes_from_config() == ["trend_devam"]
    defaults = asyncio.run(ap.get_default_settings())
    assert defaults["allowed_modes"] == ["trend_devam"]
    assert "unified" not in defaults["allowed_modes"]


def test_auto_paper_allowed_modes_env_override(monkeypatch):
    from app.routers import auto_paper as ap
    monkeypatch.setattr(ap.config, "AUTO_PAPER_ALLOWED_MODES", "trend_devam,unified")
    assert ap._allowed_modes_from_config() == ["trend_devam", "unified"]
    defaults = asyncio.run(ap.get_default_settings())
    assert defaults["allowed_modes"] == ["trend_devam", "unified"]
    # Boşluk/tekrar temizlenir; boş değer = tüm modlar (boş liste).
    monkeypatch.setattr(ap.config, "AUTO_PAPER_ALLOWED_MODES", " unified , trend_devam,unified, ")
    assert ap._allowed_modes_from_config() == ["unified", "trend_devam"]
    monkeypatch.setattr(ap.config, "AUTO_PAPER_ALLOWED_MODES", "")
    assert ap._allowed_modes_from_config() == []
