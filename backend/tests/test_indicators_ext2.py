"""`app.rescan.indicators_ext2` — el hesaplı fixture'lar + nedensellik (gelecek barları değiştirmek geçmişi değiştirmez; kesilmiş dizi = tam dizinin öneki)."""
from __future__ import annotations

import numpy as np
import pytest

from app.rescan import indicators_ext2 as X

DAY = 86_400_000


def _ohlcv(n=1700, seed=3, bar_ms=300_000, start=1_790_000_000_000):
    rng = np.random.default_rng(seed)
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.random(n) * 0.002)
    l = np.minimum(o, c) * (1 - rng.random(n) * 0.002)
    v = 100 + rng.random(n) * 80
    arr = np.zeros((n, 9))
    arr[:, 0] = start - (start % DAY) + np.arange(n) * bar_ms
    arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5] = o, h, l, c, v
    arr[:, 6] = v * c
    arr[:, 7] = v * rng.random(n)
    arr[:, 8] = arr[:, 6] * rng.random(n)
    return arr


# ---------------------------------------------------------------------------------------------------- el hesaplı değerler
def test_aroon_oscillator_hand():
    n = 25
    up = np.arange(1.0, 60.0)
    a = X.aroon(up, up, n)
    assert np.isnan(a["osc"][:n]).all()
    assert a["up"][-1] == pytest.approx(100.0) and a["dn"][-1] == pytest.approx(0.0) and a["osc"][-1] == pytest.approx(100.0)
    dn = up[::-1].copy()
    assert X.aroon(dn, dn, n)["osc"][-1] == pytest.approx(-100.0)
    # tepe 10 bar önce: up = 100*(25-10)/25 = 60
    h = np.r_[np.arange(30.0), 40.0, np.full(10, 20.0)]
    l = h - 1.0
    out = X.aroon(h, l, n)
    assert out["up"][-1] == pytest.approx(100.0 * (n - 10) / n)


def test_rci_hand():
    n = 9
    inc = np.arange(1.0, 30.0)
    assert X.rci(inc, n)[-1] == pytest.approx(100.0)
    assert X.rci(inc[::-1].copy(), n)[-1] == pytest.approx(-100.0)
    assert np.isnan(X.rci(inc, n)[: n - 1]).all()
    # [1,3,2,4,5]: zaman sırası 1..5, fiyat sırası 1,3,2,4,5 -> d = 0,-1,1,0,0 -> sum d^2 = 2 -> 1 - 6*2/(5*24) = 0,9
    assert X.rci(np.array([1.0, 3.0, 2.0, 4.0, 5.0]), 5)[-1] == pytest.approx(90.0)


def test_laguerre_rsi_hand():
    out = X.laguerre_rsi([10.0, 10.0, 10.0, 12.0], 0.5)
    # L0 = 11, L1 = 9,5, L2 = 10,25, L3 = 9,875 ; CU = 1,5 + 0,375, CD = 0,75 -> 1,875 / 2,625
    assert out[3] == pytest.approx(1.875 / 2.625)
    assert np.allclose(X.laguerre_rsi(np.full(30, 7.0)), 0.5)
    up = X.laguerre_rsi(np.linspace(1, 10, 80))
    assert up[-1] > 0.9
    dn = X.laguerre_rsi(np.linspace(10, 1, 80))
    assert dn[-1] < 0.1


def test_rollmax_exp_matches_bruteforce():
    rng = np.random.default_rng(1)
    x = rng.normal(size=137)
    w, mp = 20, 5
    got = X._rollmax_exp(x, w, mp)
    ref = np.array([x[max(0, i - w + 1): i + 1].max() if i >= mp - 1 else np.nan for i in range(len(x))])
    assert np.allclose(got, ref, equal_nan=True)
    gm = X._rollmin_exp(x, w, mp)
    refm = np.array([x[max(0, i - w + 1): i + 1].min() if i >= mp - 1 else np.nan for i in range(len(x))])
    assert np.allclose(gm, refm, equal_nan=True)


def test_rvol_time_of_day_hand():
    bpd = 6
    v = np.tile([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 5).astype(float)       # 5 gün, aynı profil
    v[-1] = 12.0                                                         # son gün son bar iki katı
    r = X._rvol_tod(v, bpd, ndays=7, min_days=3)
    assert np.isnan(r[: 3 * bpd]).all()                                   # 3 önceki gün olmadan NaN
    assert r[3 * bpd] == pytest.approx(1.0)
    assert r[-1] == pytest.approx(2.0) and r[-2] == pytest.approx(1.0)


def test_prev_day_levels_hand():
    bar = 6 * 3_600_000                                                  # 4 bar/gün
    t = 1_790_000_000_000 - (1_790_000_000_000 % DAY) + np.arange(12) * bar     # 3 tam gün
    h = np.array([5.0, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    l = h - 2.0
    c = h - 1.0
    r = X.prev_day_levels(t, h, l, c, 0)
    assert np.isnan(r["pdh"][:4]).all()
    assert r["pdh"][4] == 8.0 and r["pdl"][4] == 3.0 and r["pdh"][8] == 12.0 and r["pdl"][11] == 7.0
    assert r["dhi"][5] == 10.0
    assert r["dlo"][5] == 7.0


def test_orb_and_first_break_hand():
    n = 3 * 288
    t = 1_790_000_000_000 - (1_790_000_000_000 % DAY) + np.arange(n) * 300_000
    c = np.full(n, 100.0)
    h = c + 0.2
    l = c - 0.2
    o = c.copy()
    # gün 2: ilk 30 dk (6 bar) aralık 99,8..100,2 ; 12. barda kırılım
    k0 = 288 + 12
    c[k0:k0 + 5] = 101.0
    h[k0:k0 + 5] = 101.2
    l[k0:k0 + 5] = 100.9
    d = X._day_feats(t, o, h, l, c, np.ones(n), np.full(n, 0.5), 300_000)
    first = d["orb30_utc_up_first"]
    assert first[288 + 6] == 0.0 and np.isnan(first[288 + 5])                # OR 6. barda tamam
    assert first[k0] == 1.0 and np.nansum(first[288:2 * 288]) == 1.0
    assert d["orb30_utc_state"][k0 + 1] == 1.0 and d["orb30_utc_state"][k0 + 6] == 0.0


def test_cisd_hand():
    o = np.array([10, 10, 9.8, 9.6, 9.4, 9.2, 9.3, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9], float)
    c = np.array([10, 9.8, 9.6, 9.4, 9.2, 9.3, 9.9, 10.1, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9], float)
    # düşüş serisi i=1..4 (ilk açılış 10), i=5 yükseliş (c 9,3) ; i=7 kapanış 10,1 > 10 -> CISD yukarı
    r = X._cisd(np.r_[np.full(12, 10.0), o], np.r_[np.full(12, 10.0), c])
    assert r["cisd_up"][12 + 7] == 1.0 and np.nansum(r["cisd_up"]) == 1.0
    assert r["cisd_up_r6"][12 + 9] == 1.0


def test_ifvg_inversion_and_tap():
    n = 90
    h = np.full(n, 10.2)
    l = np.full(n, 9.8)
    c = np.full(n, 10.0)
    o = c.copy()
    # düşüş FVG: l[i-2] > h[i] ; i=40 : h[40] = 9,0 < l[38] = 9,8
    h[39], l[39], c[39], o[39] = 9.9, 9.3, 9.4, 9.8
    h[40], l[40], c[40], o[40] = 9.0, 8.5, 8.8, 9.3
    h[41:50], l[41:50], c[41:50], o[41:50] = 9.0, 8.6, 8.8, 8.8
    # 50: kapanış FVG tepesinin (9,8) üstüne -> yükseliş iFVG
    h[50], l[50], c[50], o[50] = 10.3, 8.9, 10.2, 8.9
    h[51:60], l[51:60], c[51:60], o[51:60] = 10.6, 10.3, 10.5, 10.5
    h[60], l[60], c[60], o[60] = 10.5, 9.7, 10.2, 10.4          # bölgeye dönüş (l <= üst 9,8 ; c >= alt)
    atr = np.full(n, 0.4)
    r = X._fvg_inv(o, h, l, c, atr, min_atr=0.25)
    assert r["ifvg_bull_new"][50] == 1.0 and np.nansum(r["ifvg_bull_new"]) >= 1
    assert r["ifvg_bull_tap"][60] == 1.0


def test_chandelier_and_range_filter_trend_states():
    n = 200
    c = np.linspace(10, 30, n)
    h, l = c + 0.1, c - 0.1
    ce = X.chandelier(h, l, c, 22, 3.0)
    assert ce["dir"][-1] == 1.0 and ce["stop"][-1] < c[-1]
    c2 = np.r_[np.linspace(10, 30, 120), np.linspace(30, 12, 120)]
    ce2 = X.chandelier(c2 + 0.1, c2 - 0.1, c2, 22, 3.0)
    assert ce2["dir"][-1] == -1.0 and np.nansum(ce2["flip_dn"]) >= 1
    rf = X.range_filter(c2, 20, 2.0)
    assert rf["dir"][100] == 1.0 and rf["dir"][-1] == -1.0


def test_psych_line_and_qstick_hand():
    arr = _ohlcv(900)
    names, M = X.compute_all(arr, "5m")
    j = names.index("5m.x2.psy12")
    c = arr[:, 4]
    i = 500
    assert M[i, j] == pytest.approx(float((c[i - 11: i + 1] > c[i - 12: i]).mean() * 100.0), abs=1e-3)
    q = names.index("5m.x2.qstick8")
    assert M[i, q] == pytest.approx(float(np.mean(c[i - 7: i + 1] - arr[i - 7: i + 1, 1]) / c[i] * 100.0), rel=1e-3, abs=1e-4)


# ---------------------------------------------------------------------------------------------------- toplu / nedensellik
@pytest.mark.parametrize("tf,bar", [("5m", 300_000), ("15m", 900_000)])
def test_compute_all_shape_names_and_warmup(tf, bar):
    n = 1700 if tf == "5m" else 1500
    a = _ohlcv(n, bar_ms=bar)
    names, M = X.compute_all(a, tf)
    assert M.shape == (n, len(names)) and len(set(names)) == len(names)
    assert not np.isinf(M).any()
    assert all(nm.startswith(tf + ".x2.") for nm in names)
    assert set(X.FAMILY.values()) >= {"x2_basic", "x2_day", "x2_pivot", "x2_smc", "x2_pattern", "x2_comm", "x2_adv"}
    j = names.index(tf + ".x2.rci52")
    assert np.isnan(M[:51, j]).all() and np.isfinite(M[60:, j]).all()
    # hiçbir sütun tümüyle NaN değil (RVOL/7g gibi gün bazlıları dahil) ve sabit değil
    allnan = [nm for k, nm in enumerate(names) if np.isnan(M[:, k]).all()]
    assert allnan == [] or all(("d30" in nm or "pos30" in nm or "adr" in nm or "vd_" in nm) for nm in allnan)
    assert len(X.feature_names(tf)) == len(names)


def test_no_taker_columns_gives_nan_volume_delta():
    a = _ohlcv(900)[:, :7]
    names, M = X.compute_all(a, "5m")
    j = names.index("5m.x2.vd_ratio")
    assert np.isnan(M[:, j]).all()


@pytest.mark.parametrize("tf,bar,n", [("5m", 300_000, 1700), ("15m", 900_000, 1500), ("1m", 60_000, 2500)])
def test_causality_future_bars_do_not_change_past(tf, bar, n):
    a = _ohlcv(n, bar_ms=bar)
    names, M = X.compute_all(a, tf)
    b = a.copy()
    rng = np.random.default_rng(9)
    cut = int(n * 0.8)
    b[cut:, 1:5] = b[cut:, 1:5] * rng.uniform(0.5, 1.8, size=(len(b) - cut, 4))
    b[cut:, 2] = b[cut:, 1:5].max(axis=1)
    b[cut:, 3] = b[cut:, 1:5].min(axis=1)
    b[cut:, 5:9] = b[cut:, 5:9] * rng.uniform(0.2, 3.0, size=(len(b) - cut, 4))
    _, Y = X.compute_all(b, tf)
    bad = [nm for j, nm in enumerate(names) if not np.allclose(M[:cut, j], Y[:cut, j], rtol=1e-4, atol=1e-5, equal_nan=True)]
    assert bad == []


@pytest.mark.parametrize("tf,bar,n", [("5m", 300_000, 1700), ("15m", 900_000, 1500)])
def test_truncation_equals_prefix(tf, bar, n):
    a = _ohlcv(n, seed=5, bar_ms=bar)
    names, M = X.compute_all(a, tf)
    cut = int(n * 0.7) + 37                  # gün ortasında kesim
    _, Z = X.compute_all(a[:cut], tf)
    bad = [nm for j, nm in enumerate(names) if not np.allclose(M[:cut, j], Z[:, j], rtol=1e-4, atol=1e-5, equal_nan=True)]
    assert bad == []
