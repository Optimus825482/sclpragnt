"""ATR M15 tabanlı dinamik trailing (2026-11-25, kullanıcı isteği).

Kural: otonom paper'da (profil/plan işlemi olmayan) iz süren stop tetiği ve
mesafesi ATR M15 ile ölçeklenir; ATR okunamazsa sabit ayarlara düşülür.

Ayrıca bu dosya ATR **ölçek sözleşmesini** kilitler: `_atr_pct_for` KESİR
(0.017 = %1,7) döndürür; trailing tarafı yüzde kullandığı için yardımcı
fonksiyon ×100 yapar. Karışırsa trailing tetiği 1,0 alt sınırına çakılır.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config  # noqa: E402
from app.routers import auto_paper  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    auto_paper._ATR15_TRAIL_CACHE.clear()
    yield
    auto_paper._ATR15_TRAIL_CACHE.clear()


def test_atr_pct_for_returns_fraction(monkeypatch):
    """`_atr_pct_for` KESİR döndürür (0.017 = %1,7) — SL tarafı bu birimi kullanır."""
    monkeypatch.setattr(auto_paper.market, "get_ut_kline",
                        lambda symbol, tf: {"highs": [1] * 20, "lows": [1] * 20, "closes": [1] * 20})
    import app.technical_analysis as ta
    monkeypatch.setattr(ta, "_atr", lambda h, l, c, n: 1.7)
    assert auto_paper._atr_pct_for("AAA_TRY", 100.0, "15m") == pytest.approx(0.017)


def test_atr_cached_helper_returns_percent(monkeypatch):
    """Trailing yardımcısı yüzdeye çevirir: 0.017 → 1.7."""
    monkeypatch.setattr(auto_paper, "_atr_pct_for", lambda s, p, tf: 0.017)
    assert auto_paper._atr_pct_15m_cached("AAA_TRY", 100.0) == pytest.approx(1.7)


def test_atr_cache_avoids_recompute(monkeypatch):
    calls = []

    def fake(symbol, price, timeframe):
        calls.append(symbol)
        return 0.02

    monkeypatch.setattr(auto_paper, "_atr_pct_for", fake)
    auto_paper._atr_pct_15m_cached("AAA_TRY", 100.0)
    auto_paper._atr_pct_15m_cached("AAA_TRY", 101.0)
    assert calls == ["AAA_TRY"]


@pytest.mark.parametrize("atr,expected", [
    (2.0, (2.0, 1.0)),   # tipik: tetik %2, mesafe %1
    (5.0, (3.0, 1.5)),   # üst sınırlar
    (0.5, (1.0, 0.4)),   # alt sınırlar (tetik>gap korunur)
])
def test_atr_trailing_levels_clamped(monkeypatch, atr, expected):
    monkeypatch.setattr(auto_paper, "_atr_pct_15m_cached", lambda symbol, price: atr)
    assert auto_paper._atr_trailing_levels("AAA_TRY", 10.0) == expected


def test_atr_levels_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(config, "AUTO_PAPER_TRAIL_ATR_ENABLED", False)
    monkeypatch.setattr(auto_paper, "_atr_pct_15m_cached", lambda symbol, price: 2.0)
    assert auto_paper._atr_trailing_levels("AAA_TRY", 10.0) is None


def test_gap_always_below_trigger(monkeypatch):
    """Aşırı dar sınırlarda bile mesafe tetiğin altında kalmalı."""
    monkeypatch.setattr(auto_paper, "_atr_pct_15m_cached", lambda symbol, price: 10.0)
    monkeypatch.setattr(config, "AUTO_PAPER_TRAIL_TRIGGER_MAX_PCT", 1.0)
    monkeypatch.setattr(config, "AUTO_PAPER_TRAIL_GAP_MAX_PCT", 1.5)
    trigger, gap = auto_paper._atr_trailing_levels("AAA_TRY", 10.0)
    assert gap < trigger


def test_trailing_params_use_atr(monkeypatch):
    """ATR varsa tetik/mesafe ayarlardaki sabitlerden DEĞİL, ATR'den gelir."""
    monkeypatch.setattr(auto_paper, "_atr_trailing_levels", lambda s, p: (2.4, 1.2))
    trigger, gap = auto_paper._trailing_params(
        "AAA_TRY", 10.0, None, {"trailing_trigger_pct": 3.5, "trailing_gap_pct": 1.8},
        None, 0.0, False, 0.4)
    assert (trigger, gap) == (2.4, 1.2)


def test_trailing_params_fall_back_when_atr_missing(monkeypatch):
    monkeypatch.setattr(auto_paper, "_atr_trailing_levels", lambda s, p: None)
    trigger, gap = auto_paper._trailing_params(
        "AAA_TRY", 10.0, None, {"trailing_trigger_pct": 2.0, "trailing_gap_pct": 1.0},
        None, 0.0, False, 0.4)
    assert (trigger, gap) == (2.0, 1.0)


def test_atr_gap_not_capped_by_breakeven_gap(monkeypatch):
    """Breakeven gap tavanı ATR mesafesini daraltmamalı (yüksek volatilitede erken stop)."""
    monkeypatch.setattr(auto_paper, "_atr_trailing_levels", lambda s, p: (2.8, 1.4))
    trigger, gap = auto_paper._trailing_params(
        "AAA_TRY", 10.0, None, {}, None, 0.0, True, 0.4)
    assert (trigger, gap) == (2.8, 1.4)


def test_profile_trade_keeps_profile_values(monkeypatch):
    """Profil işlemi (MA BUY H4) ATR'den etkilenmez — replay birebirliği."""
    monkeypatch.setattr(auto_paper, "_atr_trailing_levels", lambda s, p: (2.9, 1.4))
    manage = {"trailing": True, "trailing_trigger_pct": 3.0, "trailing_gap_pct": 1.5}
    assert auto_paper._trailing_params("AAA_TRY", 10.0, manage, {}, None, 0.0, False, 1.0) == (3.0, 1.5)
