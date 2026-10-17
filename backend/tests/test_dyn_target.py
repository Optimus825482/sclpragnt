"""Dinamik hedef modülü (app/rescan/dyn_target.py) birim testleri — nedensellik dahil."""
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rescan import dyn_target as D  # noqa: E402

T0 = 1_800_000_000_000          # 5 dk hizalı (1_800_000_000_000 % 300000 == 0)


def _series(n5: int = 1000, seed: int = 1, base: float = 100.0, vol: float = 0.2) -> D.SymbolCandles:
    """Sentetik: n5 adet 5m bar ve her birinde 5 adet 1m bar."""
    rng = np.random.default_rng(seed)
    n1 = n5 * 5
    open1 = T0 + np.arange(n1, dtype=np.int64) * D.BAR1
    c1 = base * np.exp(np.cumsum(rng.normal(0, vol / 100, n1)))
    o1 = np.concatenate([[base], c1[:-1]])
    h1 = np.maximum(o1, c1) * (1 + np.abs(rng.normal(0, vol / 200, n1)))
    l1 = np.minimum(o1, c1) * (1 - np.abs(rng.normal(0, vol / 200, n1)))
    open5 = T0 + np.arange(n5, dtype=np.int64) * D.BAR5
    h5 = h1.reshape(n5, 5).max(axis=1)
    l5 = l1.reshape(n5, 5).min(axis=1)
    c5 = c1.reshape(n5, 5)[:, -1]
    return D.SymbolCandles(open1=open1, h1=h1, open5=open5, h5=h5, l5=l5, c5=c5)


def test_round_trip_cost_and_net_target():
    # 2026-10-17: hedefe ulaşan işlem = giriş taker + giriş kayması + çıkış maker (bekleyen LIMIT, kaymasız)
    assert abs(D.round_trip_cost_pct() - 0.33) < 1e-12
    assert abs(D.round_trip_cost_pct(0.15, 0.15) - 0.48) < 1e-12
    assert abs(D.round_trip_cost_pct(0.15, 0.15, fee_exit_leg_pct=D.FEE_LEG_PCT) - 0.525) < 1e-12   # eski iki taker bacak
    assert abs(float(D.net_target_pct(2.5)) - (2.5 - 0.33)) < 1e-12
    assert np.isnan(D.net_target_pct(np.nan))
    assert abs(float(D.net_target_pct(3.0, 0.3)) - 2.7) < 1e-12


def test_atr_target_scales_with_k_and_sqrt_horizon():
    a5 = D.atr_target_pct(1.0, 5, 1.0)
    assert abs(float(a5) - 1.0) < 1e-12
    assert abs(float(D.atr_target_pct(1.0, 20, 1.0)) - 2.0) < 1e-12      # sqrt(20/5) = 2
    assert abs(float(D.atr_target_pct(0.8, 15, 1.5)) - 1.5 * 0.8 * np.sqrt(3)) < 1e-12
    assert np.isnan(D.atr_target_pct(np.nan, 5, 1.0))
    arr = D.atr_target_pct(np.array([1.0, 2.0]), np.array([5, 5]), 2.0)
    assert np.allclose(arr, [2.0, 4.0])


def test_rolling_max_basic():
    x = np.array([1.0, 3.0, 2.0, 5.0, 4.0])
    r = D.rolling_max(x, 3)
    assert np.isnan(r[0]) and np.isnan(r[1])
    assert np.allclose(r[2:], [3.0, 5.0, 5.0])


def test_mfe_forward_pct_and_gap_guard():
    open5 = T0 + np.arange(6, dtype=np.int64) * D.BAR5
    c5 = np.array([100.0, 100, 100, 100, 100, 100])
    h5 = np.array([100.0, 101, 103, 102, 100, 100])
    m = D.mfe_forward_pct(open5, h5, c5, 2)           # a=0: max(101,103)=103 → 3 %
    assert abs(m[0] - 3.0) < 1e-9
    assert abs(m[1] - 3.0) < 1e-9                       # max(103,102)
    assert np.isnan(m[4]) and np.isnan(m[5])
    open5g = open5.copy()
    open5g[3:] += D.BAR5                                # 2. ile 3. bar arasında boşluk
    mg = D.mfe_forward_pct(open5g, h5, c5, 2)
    assert np.isnan(mg[1]) and np.isnan(mg[2])          # boşluktan geçen pencere geçersiz


def test_last_closed_index_excludes_forming_bar():
    open5 = T0 + np.arange(5, dtype=np.int64) * D.BAR5
    t = T0 + 2 * D.BAR5 + 10_000                        # 3. barın (idx 2) içinde
    assert int(D.last_closed_index(open5, np.array([t]), D.BAR5)[0]) == 1
    t2 = T0 + 2 * D.BAR5                                # tam sınır: idx1 kapandı
    assert int(D.last_closed_index(open5, np.array([t2]), D.BAR5)[0]) == 1


def test_room_to_resistance_uses_nearest_level_above_tolerance():
    price = np.array([100.0, 100.0, 100.0])
    peak60 = np.array([100.1, 101.0, 99.0])             # 0.1 % (tol altı), %1, fiyat altı
    high24 = np.array([104.0, 104.0, 103.0])
    r = D.room_to_resistance_pct(price, peak60, high24, tol_pct=0.3)
    assert np.allclose(r, [4.0, 1.0, 3.0])               # 1. satır: peak60 tol altında → 24sa zirve
    r2 = D.room_to_resistance_pct(price, peak60, high24, tol_pct=0.3, levels="h24")
    assert np.allclose(r2, [4.0, 4.0, 3.0])
    none = D.room_to_resistance_pct(np.array([110.0]), np.array([100.0]), np.array([105.0]))
    assert np.isinf(none[0])                              # fiyat tüm seviyelerin üstünde → direnç yok


def test_peak_levels_ignore_forming_bar_and_future():
    sc = _series()
    t = int(sc.open1[1200]) + 30_000                     # 1m barın ortası: o bar KAPANMAMIŞ
    peak, h24 = D.peak_levels(sc, np.array([t]))
    expected = sc.h1[1140:1200].max()                    # kapanmış son 60 1m bar: idx 1140..1199
    assert abs(peak[0] - expected) < 1e-9
    assert h24[0] >= peak[0]


def test_dynamic_targets_do_not_look_ahead():
    sc = _series(seed=3)
    price = float(sc.h1[4000])
    t = int(sc.open1[4000]) + 20_000
    atr = np.array([0.9])
    base = D.compute_targets(sc, np.array([t]), np.array([price]), 15, atr)
    # t'den sonraki tüm barlar bozuluyor → sonuç aynı kalmalı
    sc2 = _series(seed=3)
    cut1 = int(np.searchsorted(sc2.open1, t, side="left"))
    cut5 = int(np.searchsorted(sc2.open5, t, side="left")) + 1     # t'yi içeren (kapanmamış) bar ve sonrası
    sc2.h1[cut1:] *= 1.5
    sc2.h5[cut5 - 1:] *= 1.5
    sc2.c5[cut5 - 1:] *= 1.5
    sc2 = D.SymbolCandles(sc2.open1, sc2.h1, sc2.open5, sc2.h5, sc2.l5, sc2.c5)
    new = D.compute_targets(sc2, np.array([t]), np.array([price]), 15, atr)
    for key in ("a", "b", "c", "room", "peak60", "high24"):
        x, y = base[key][0], new[key][0]
        assert (np.isnan(x) and np.isnan(y)) or x == y or (np.isinf(x) and np.isinf(y)), key


def test_empirical_upside_uses_only_prior_window_and_min_anchors():
    n5 = 800
    open5 = T0 + np.arange(n5, dtype=np.int64) * D.BAR5
    c5 = np.full(n5, 100.0)
    h5 = np.full(n5, 101.0)                               # her pencerenin MFE'si = %1
    h5[600:] = 110.0                                      # gelecek: %10
    open1 = T0 + np.arange(n5 * 5, dtype=np.int64) * D.BAR1
    sc = D.SymbolCandles(open1=open1, h1=np.full(n5 * 5, 101.0), open5=open5, h5=h5, l5=c5 - 1, c5=c5)
    t = int(open5[550])                                    # bar 549 kapandı; 600+ gelecekte
    e = D.empirical_upside_pct(sc, np.array([t]), 15, lookback_days=14, q=0.6, min_anchors=100)
    assert abs(e[0] - 1.0) < 1e-9                          # gelecekteki %10'lar karışmaz
    short = D.empirical_upside_pct(sc, np.array([int(open5[50])]), 15, min_anchors=100)
    assert np.isnan(short[0])                              # yetersiz geçmiş


def test_compute_targets_variant_b_capped_by_room_and_a():
    sc = _series(seed=5)
    t = int(sc.open1[4200]) + 5_000
    price = np.array([100.0])
    atr = np.array([1.0])
    out = D.compute_targets(sc, np.array([t]), price, 15, atr, D.DynParams(k_atr=2.0))
    a = out["a"][0]
    assert abs(a - 2.0 * 1.0 * np.sqrt(3)) < 1e-9
    assert out["b"][0] <= a + 1e-12
    p = D.DynParams(k_atr=2.0, room_frac=0.5)
    out2 = D.compute_targets(sc, np.array([t]), np.array([sc.h1[4199] / 1.02]), 15, atr, p)   # fiyat zirvenin %2 altı
    if np.isfinite(out2["room"][0]):
        assert out2["b"][0] <= 0.5 * out2["room"][0] + 1e-9
