"""signal_eta: geçmiş sinyallerden süre / stop istatistiği (saf fonksiyonlar + eşik seçimi)."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app import signal_eta


def _c(i, h, l):  # 1m mum
    return [i * 60_000, 1.0, h, l, 1.0]


def test_first_hits_minutes_and_mae():
    candles = [_c(0, 1.01, 0.97), _c(1, 1.04, 0.99), _c(2, 1.06, 1.0)]
    hits, mae = signal_eta.first_hits(candles, 1.0, (3.6, 5.0, 8.0))
    assert hits == {"3.6": 2, "5.0": 3, "8.0": None}
    assert mae["3.6"] == pytest.approx(-3.0)
    assert mae["8.0"] is None


def test_bucket_stats_needs_30():
    s = [{"hits": {"3.6": 10}, "mae_before": {"3.6": -1.0}}] * 29
    assert signal_eta.bucket_stats(s, 3.6) is None


def test_bucket_stats_percentiles():
    s = ([{"hits": {"3.6": m}, "mae_before": {"3.6": -m / 10}} for m in range(1, 31)]
         + [{"hits": {"3.6": None}, "mae_before": {"3.6": None}}] * 10)
    r = signal_eta.bucket_stats(s, 3.6)
    assert r["n"] == 40 and r["hit_rate"] == pytest.approx(0.75)
    assert r["p50_min"] == pytest.approx(15.5) and r["mae_p80_pct"] > 0


def test_bucket_for():
    assert signal_eta.bucket_for("rising", {"kind": "erken"}) == "rising:erken"
    assert signal_eta.bucket_for("ma_buy", {"timeframe": "4h"}) == "ma_buy:4h"
    assert signal_eta.bucket_for("radar", {}) == "radar"


@pytest.mark.parametrize("gross,expected", [(3.0, 3.6), (3.6, 3.6), (3.7, 5.0), (9.0, 10.0), (14.0, 10.0)])
def test_pick_threshold(gross, expected):
    assert signal_eta.pick_threshold(gross) == expected


def test_get_stats_uses_threshold_and_cache():
    signal_eta._CACHE.clear()
    row = {"n": 40, "hit_rate": 0.7, "p50_min": 12.0, "p75_min": 30.0, "mae_p80_pct": 1.5}
    with patch("app.signal_eta.database.get_eta_stats", new=AsyncMock(return_value=row)) as g:
        r1 = asyncio.run(signal_eta.get_stats("radar", 4.2))
        r2 = asyncio.run(signal_eta.get_stats("radar", 4.2))
    assert r1 == row and r2 == row
    assert g.await_count == 1
    assert g.await_args.args == ("radar", 5.0)


def test_first_hits_minute_is_time_based_with_gap():
    # 3. dakikada mum yok (islem yok); hedef 4. dakikanin mumunda: dakika 4 (indeks 3 degil)
    candles = [_c(0, 1.01, 0.99), _c(1, 1.02, 0.99), _c(3, 1.05, 1.0)]
    hits, _ = signal_eta.first_hits(candles, 1.0, (3.6,), start_ms=0)
    assert hits == {"3.6": 4}


def test_first_hits_cuts_window_by_time():
    candles = [_c(0, 1.0, 1.0), _c(1440, 1.10, 1.0)]
    hits, _ = signal_eta.first_hits(candles, 1.0, (3.6,), start_ms=0)
    assert hits == {"3.6": None}


def test_tombstone_excluded_from_stats():
    s = [{"hits": {"3.6": 5}, "mae_before": {"3.6": -1.0}}] * 29 + [{"hits": {}, "mae_before": {}}] * 5
    assert signal_eta.bucket_stats(s, 3.6) is None
