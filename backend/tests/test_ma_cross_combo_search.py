"""scripts/ma_cross_combo_search.simulate: vektörel 1 dk çıkış simülasyonu (hedef / stop / iz süren / süre dolumu / tekilleştirme)."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "scripts"))
search = pytest.importorskip("ma_cross_combo_search")


def _w(path):
    """path: [(high, low, close)...] giriş=1.0 oranları → [1,3,MAXW]."""
    W = np.full((1, 3, search.MAXW), np.nan, dtype=np.float32)
    for t, (h, l, c) in enumerate(path):
        W[0, :, t] = (h, l, c)
    return W


def test_target_hit_pays_target_minus_cost():
    W = _w([(1.005, 0.999, 1.004), (1.021, 1.003, 1.015), (1.05, 1.0, 1.0)])
    net = search.simulate(W, tp=2.0, sl=1.0, hold=60, trig=0.0, gap=0.0, cost_pct=0.275)
    assert net[0] == pytest.approx(2.0 - 0.275, abs=1e-4)


def test_stop_wins_over_target_in_same_bar():
    W = _w([(1.03, 0.985, 1.02)])
    net = search.simulate(W, tp=2.0, sl=1.0, hold=60, trig=0.0, gap=0.0, cost_pct=0.0)
    assert net[0] == pytest.approx(-1.0, abs=1e-4)


def test_trailing_stop_uses_previous_bar_peak():
    # tepe 1.03 → iz süren stop 1.03*(1-0.01)=1.0197; sonraki mum 1.015'e düşer → oradan çıkar
    W = _w([(1.03, 1.0, 1.028), (1.029, 1.015, 1.016), (1.0, 0.9, 0.9)])
    net = search.simulate(W, tp=5.0, sl=4.0, hold=60, trig=2.0, gap=1.0, cost_pct=0.0)
    assert net[0] == pytest.approx(1.97, abs=1e-3)


def test_timeout_exits_at_last_close_within_hold():
    W = _w([(1.004, 0.998, 1.001)] * 30 + [(1.5, 1.0, 1.4)] * 5)   # 31. dakikadaki patlama tutma dışında
    net = search.simulate(W, tp=5.0, sl=4.0, hold=30, trig=0.0, gap=0.0, cost_pct=0.0)
    assert net[0] == pytest.approx(0.1, abs=1e-4)


def test_no_data_gives_nan():
    net = search.simulate(np.full((1, 3, search.MAXW), np.nan, dtype=np.float32), 2.0, 1.0, 60, 0.0, 0.0, 0.0)
    assert np.isnan(net[0])


def test_dedup_keeps_one_position_per_symbol_until_hold_expires():
    syms = np.array(["A", "A", "A", "B"])
    t = np.array([0, 10 * 60_000, 70 * 60_000, 5 * 60_000], dtype=np.int64)
    keep = search.dedup_mask(syms, t, hold_min=60)
    assert keep.tolist() == [True, False, True, True]


def test_pullback_limit_entry_fills_on_first_dip_and_renormalizes(monkeypatch):
    monkeypatch.setattr(search, "PULLBACK_PCT", 1.0)
    monkeypatch.setattr(search, "PULLBACK_WAIT", 15)
    n = 60
    m1 = {"open_ms": np.arange(n, dtype=np.int64) * 60_000, "high": np.full(n, 101.0), "low": np.full(n, 100.0),
          "close": np.full(n, 100.5)}
    m1["low"][3] = 98.9                     # 4. dakikada %1 altına iniyor → 99.0'dan dolum, pencere 5. dakikadan başlar
    W = search.windows_for([0], m1, None, np.array([100.0]))
    assert W[0, 1, 0] == pytest.approx(100.0 / 99.0, rel=1e-6)   # ilk pencere mumu = 5. dakika, düşük 100/99
    m1["low"][3] = 100.0                    # geri çekilme yok → dolum yok → pencere tamamen NaN
    W = search.windows_for([0], m1, None, np.array([100.0]))
    assert np.isnan(W[0]).all()
