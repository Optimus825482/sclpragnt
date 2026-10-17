"""`app.rescan.indicators_ext` — el hesaplı fixture'lar + nedensellik (gelecek barları değiştirmek geçmişi değiştirmez)."""
from __future__ import annotations

import numpy as np
import pytest

from app.rescan import indicators_ext as I


def _ohlcv(n=700, seed=3, bar_ms=300_000):
    rng = np.random.default_rng(seed)
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.random(n) * 0.002)
    l = np.minimum(o, c) * (1 - rng.random(n) * 0.002)
    v = 100 + rng.random(n) * 80
    arr = np.zeros((n, 9))
    arr[:, 0] = 1_790_000_000_000 - (1_790_000_000_000 % 900_000) + np.arange(n) * bar_ms
    arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5] = o, h, l, c, v
    arr[:, 6] = v * c
    arr[:, 7] = v * rng.random(n)
    arr[:, 8] = arr[:, 6] * rng.random(n)
    return arr


# ---------------------------------------------------------------------------------------------------- hareketli ortalamalar
def test_wma_hand():
    out = I.wma([1, 2, 3, 4], 3)
    assert np.isnan(out[:2]).all()
    assert out[2] == pytest.approx((1 * 1 + 2 * 2 + 3 * 3) / 6)
    assert out[3] == pytest.approx((2 * 1 + 3 * 2 + 4 * 3) / 6)


def test_constant_series_ma_family():
    x = np.full(120, 7.0)
    for fn in (lambda a: I.alma(a, 9), lambda a: I.hull_ma(a, 21), lambda a: I.dema(a, 10), lambda a: I.tema(a, 10),
               lambda a: I.kama(a, 10), lambda a: I.mcginley(a, 14)):
        out = fn(x)
        assert np.allclose(out[60:], 7.0)


def test_kama_trending_uses_fast_constant():
    x = np.arange(1.0, 60.0)            # ER = 1 → sc = fastSC²
    out = I.kama(x, 10, 2, 30)
    fsc = 2 / 3
    assert out[11] == pytest.approx(out[10] + fsc ** 2 * (x[11] - out[10]))


def test_linreg_band_exact_line_and_noise():
    x = 3.0 + 0.5 * np.arange(50)
    r = I.linreg_band(x, 10)
    assert np.allclose(r["value"][9:], x[9:]) and np.allclose(r["slope"][9:], 0.5) and np.allclose(r["stderr"][9:], 0.0, atol=1e-9)
    y = x.copy()
    y[30] += 2.0
    assert I.linreg_band(y, 10)["stderr"][31] > 0.1


# ---------------------------------------------------------------------------------------------------- hacim / akış
def test_obv_and_slope():
    c = np.array([1, 2, 2, 1.0])
    v = np.array([10, 20, 30, 40.0])
    assert I.obv(c, v).tolist() == [0.0, 20.0, 20.0, -20.0]
    s = I.obv_slope(c, v, 2)
    assert s[2] == pytest.approx(20.0 / 50.0) and s[3] == pytest.approx(-40.0 / 70.0)


def test_ad_line_and_cmf_close_at_high():
    h = np.array([2.0, 3, 4])
    l = np.array([1.0, 2, 3])
    c = h.copy()
    v = np.array([5.0, 6, 7])
    assert I.ad_line(h, l, c, v).tolist() == [5.0, 11.0, 18.0]
    assert I.cmf(h, l, c, v, 2)[2] == pytest.approx(1.0)
    assert I.ad_line([2.0, 2], [2.0, 2], [2.0, 2], [9.0, 9.0]).tolist() == [0.0, 0.0]


def test_cvd_and_slope():
    qv = np.array([10.0, 10.0, 10.0])
    tbq = np.array([8.0, 2.0, 5.0])
    assert I.cvd(qv, tbq).tolist() == [6.0, 0.0, 0.0]
    assert I.cvd_slope(qv, tbq, 2)[2] == pytest.approx((0.0 - 6.0) / 20.0)


def test_volume_oscillator_hand():
    v = np.array([10.0, 10, 10, 10, 10, 20, 20, 20, 20, 20])
    out = I.volume_oscillator(v, 2, 4)
    assert out[5] == pytest.approx((15.0 - 12.5) / 12.5 * 100)


# ---------------------------------------------------------------------------------------------------- osilatörler
def test_cmo_extremes():
    up = np.arange(1.0, 40.0)
    assert I.cmo(up, 14)[-1] == pytest.approx(100.0)
    assert I.cmo(up[::-1].copy(), 14)[-1] == pytest.approx(-100.0)


def test_williams_stochastic_ultimate_extremes():
    c = np.arange(10.0, 70.0)
    h = c.copy()
    l = np.r_[c[0], c[:-1]]                  # alçak = önceki kapanış, kapanış = yüksek
    assert I.williams_r(h, l, c, 14)[-1] == pytest.approx(0.0)
    assert I.stochastic(h, l, c)["k"][-1] == pytest.approx(100.0)
    assert I.ultimate_osc(h, l, c)[-1] == pytest.approx(100.0)
    low = c[::-1].copy()
    assert I.williams_r(low, low, low, 14)[-1] == pytest.approx(-100.0)


def test_tsi_trix_constant_and_trend():
    assert I.tsi(np.arange(1.0, 120.0))[-1] == pytest.approx(100.0)
    assert np.allclose(I.trix(np.full(200, 5.0))[-50:], 0.0)
    assert I.trix(np.linspace(1, 3, 200))[-1] > 0


def test_cci_awesome_dpo_flat():
    f = np.full(80, 4.0)
    assert np.allclose(I.cci(f, f, f, 20)[19:], 0.0)
    assert np.allclose(I.awesome_osc(f, f)[40:], 0.0)
    assert np.allclose(I.dpo(f, 20)[40:], 0.0)
    rise = np.linspace(1, 5, 80)
    assert I.awesome_osc(rise, rise)[-1] > 0


def test_connors_fisher_bounds():
    a = _ohlcv()
    crsi = I.connors_rsi(a[:, 4])
    assert np.nanmin(crsi) >= 0 and np.nanmax(crsi) <= 100
    fi = I.fisher_transform(a[:, 2], a[:, 3])["fisher"]
    assert np.isfinite(fi[20:]).all() and np.abs(fi[20:]).max() < 20


def test_rvi_bop_signs():
    o = np.full(60, 10.0)
    c = np.full(60, 11.0)
    h = np.full(60, 11.0)
    l = np.full(60, 10.0)
    assert I.rvi_vigor(o, h, l, c)["rvi"][-1] == pytest.approx(1.0)
    assert I.balance_of_power(o, h, l, c, 5)[-1] == pytest.approx(1.0)


# ---------------------------------------------------------------------------------------------------- trend / yapı
def test_vortex_donchian_inside_bar():
    c = np.linspace(10, 20, 60)
    h = c + 0.2
    l = c - 0.2
    vx = I.vortex(h, l, c, 14)
    assert vx["plus"][-1] > vx["minus"][-1] and vx["diff"][-1] > 0
    dn = I.donchian(c + 0.05, c - 0.05, c, 20)
    assert dn["pos"][-1] > 0.9 and dn["break_up"][-1] == 1.0
    hh = np.array([5.0, 6.0, 5.5, 6.5])          # bar1 ana mum, bar2 iç mum, bar3 kapanış > h[1]
    ll = np.array([4.0, 3.0, 3.5, 4.0])
    cc = np.array([4.5, 5.0, 5.0, 6.2])
    ib = I.inside_bar_breakout(hh, ll, cc)
    assert ib["inside"].tolist() == [0.0, 0.0, 1.0, 0.0] and ib["up"][3] == 1.0


def test_psar_supertrend_flip():
    c = np.r_[np.linspace(100, 160, 80), np.linspace(160, 90, 60)]
    h = c + 0.3
    l = c - 0.3
    ps = I.parabolic_sar(h, l)
    assert ps["state"][60] == 1.0 and ps["state"][-1] == -1.0 and (ps["flip"] == -1.0).any()
    st = I.supertrend(h, l, c, 10, 3.0)
    assert st["state"][70] == 1.0 and st["state"][-1] == -1.0 and (st["flip"] == -1.0).any()
    cl = I.supertrend_cluster(h, l, c)
    assert cl["sum"][70] == 3.0 and cl["sum"][-1] == -3.0


def test_ichimoku_cloud_position():
    c = np.linspace(100, 200, 150)
    h = c + 0.5
    l = c - 0.5
    ic = I.ichimoku(h, l, c)
    assert ic["cloud_pos"][-1] == 1.0 and ic["cloud_dist"][-1] > 0 and ic["tk_diff"][-1] > 0
    assert np.isnan(ic["cloud_pos"][:60]).all()                  # senkou_n + disp ısınması
    d = I.ichimoku(h[::-1].copy(), l[::-1].copy(), c[::-1].copy())
    assert d["cloud_pos"][-1] == -1.0


def test_choppiness_trend_vs_zigzag():
    c = np.linspace(10, 30, 80)
    tr = I.choppiness(c + 0.1, c - 0.1, c, 14)[-1]
    z = np.tile([10.0, 10.5], 40)
    zz = I.choppiness(z + 0.1, z - 0.1, z, 14)[-1]
    assert tr < 38.2 and zz > 61.8


def test_squeeze_flat_on_and_release():
    rng = np.random.default_rng(1)
    flat = 10 + rng.normal(0, 0.001, 120)
    big = 10 + 0.5 * np.arange(1, 41)
    c = np.r_[flat, big]
    w = np.r_[np.full(120, 0.05), np.full(40, 0.3)]
    sq = I.squeeze(c + w, c - w, c)
    assert sq["on"][100] == 1.0 and sq["run"][100] >= 20
    assert sq["ratio"][100] < 1.0
    assert sq["release"][120:150].max() == 1.0


def test_vwap_session_two_days():
    ot = np.array([0, 1, 2, 86_400_000, 86_400_001])
    p = np.array([2.0, 2, 2, 5, 5])
    v = np.array([1.0, 1, 2, 3, 1])
    vw = I.vwap_session(ot, p, p, p, v)
    assert vw[2] == pytest.approx(2.0) and vw[3] == pytest.approx(5.0) and vw[4] == pytest.approx(5.0)
    c2 = np.array([1.0, 3.0, 3.0])
    assert I.vwap_session(np.array([0, 1, 2]), c2, c2, c2, np.array([1.0, 1.0, 2.0]))[2] == pytest.approx((1 + 3 + 6) / 4)


def test_anchored_vwap_and_poc():
    n = 40
    c = np.concatenate([np.linspace(10, 8, 20), np.linspace(8, 12, 20)])
    h = c + 0.1
    l = c - 0.1
    v = np.ones(n)
    av = I.anchored_vwap_swing_low(h, l, c, v, window=30)
    win = l[n - 30:]
    a = int(len(win) - 1 - np.argmin(win[::-1])) + (n - 30)     # çapa = pencerenin en düşük dibi (eşitlikte EN YENİ)
    tp = (h + l + c) / 3
    assert av["vwap"][-1] == pytest.approx(tp[a:].mean()) and av["age"][-1] == pytest.approx((n - 1 - a) / 30)
    cc = np.concatenate([np.full(50, 10.0), np.full(10, 12.0)])           # hacim 10.0 civarında yoğun
    vv = np.r_[np.full(50, 100.0), np.full(10, 1.0)]
    poc = I.volume_profile_poc(cc + 0.01, cc - 0.01, cc, vv, window=60, bins=50)
    assert poc[-1] == pytest.approx(10.0, abs=0.1)


# ---------------------------------------------------------------------------------------------------- SMC
def test_swing_pivot_confirmation_lag():
    h = np.array([1.0, 2, 3, 9, 3, 2, 1, 2, 3, 4])
    pv = I.swing_pivots(h, h - 0.5, 3, 3)
    assert np.isnan(pv["sh_price"][:6]).all() and pv["sh_price"][6] == 9.0         # tepe j=3 → onay bar 6
    h2 = h.copy()
    h2[6:] = [1, 0, 0, 0]
    assert np.isnan(I.swing_pivots(h2, h2 - 0.5, 3, 3)["sh_price"][:6]).all()


def test_market_structure_sweep():
    seq = [20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 11, 12, 13, 14, 15, 14, 13, 12, 11, 10.3, 11, 12]
    c = np.array(seq, dtype=float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.1
    l = np.minimum(o, c) - 0.1
    l[20] = 9.5                                  # fitil, onaylı dibin (9.9) altına; kapanış 10.3 üstünde
    pv = I.swing_pivots(h, l, 3, 3)
    assert np.isfinite(pv["sl_price"]).any()
    ms = I.market_structure(o, h, l, c, 3, 3)
    assert ms["sweep_low"][20] == 1.0 and ms["sweep_low"].sum() == 1.0 and ms["sweep_depth"][20] > 0
    assert ms["sweep_low_recent3"][22] == 1.0


def test_market_structure_choch_up_after_downtrend():
    c = np.r_[np.linspace(30, 20, 12), [21, 22, 21, 20, 19, 18, 17, 18, 19, 21, 23, 25, 27]].astype(float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.1
    l = np.minimum(o, c) - 0.1
    ms = I.market_structure(o, h, l, c, 2, 2)
    assert ms["choch_dn"].sum() + ms["bos_dn"].sum() >= 1
    assert ms["choch_up"].sum() >= 1 and ms["trend"][-1] == 1.0


def test_fair_value_gap_new_tap_fill():
    n = 40
    h = np.full(n, 10.2)
    l = np.full(n, 9.8)
    c = np.full(n, 10.0)
    h[29], l[29], c[29] = 12.0, 10.0, 11.9
    h[30], l[30], c[30] = 12.5, 11.0, 12.2             # l[30]=11.0 > h[28]=10.2 → boşluk [10.2, 11.0]
    f = I.fair_value_gaps(h, l, c, min_atr=0.1)
    assert f["bull_new"][30] > 0 and f["bull_open"][30] == 1.0
    for i in (31, 32, 34, 35, 36, 37, 38, 39):             # boşluk açık kalsın (alçak boşluk üstünde)
        h[i], l[i], c[i] = 12.6, 11.5, 12.0
    h[33], l[33], c[33] = 12.0, 10.8, 11.5             # tap
    f = I.fair_value_gaps(h, l, c, min_atr=0.1)
    assert f["bull_tap"][33] == 1.0 and f["bull_open"][33] == 1.0
    h[35], l[35], c[35] = 11.0, 10.0, 10.5             # dolum (alçak ≤ boşluk altı 10.2)
    f = I.fair_value_gaps(h, l, c, min_atr=0.1)
    assert f["bull_open"][35] == 0.0


def test_order_block_displacement_and_tap():
    n = 60
    c = np.full(n, 10.0) + np.tile([0.05, -0.05], n // 2)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.05
    l = np.minimum(o, c) - 0.05
    o[40], c[40], h[40], l[40] = 10.1, 9.8, 10.1, 9.7          # düşüş mumu = OB [9.7, 10.1]
    o[41], c[41], h[41], l[41] = 9.8, 11.5, 11.6, 9.8          # yukarı yer değiştirme
    d = I.displacement(o, c, h, l, 1.5)
    assert d["up"][41] == 1.0 and d["body_atr"][41] > 1.5
    ob = I.order_blocks(o, h, l, c, 1.5)
    assert ob["active"][41] == 1.0 and ob["dist"][41] > 0
    o[45], c[45], h[45], l[45] = 11.4, 10.3, 11.4, 10.0        # OB bölgesine giriş
    assert I.order_blocks(o, h, l, c, 1.5)["tap"][45] == 1.0


def test_td_sequential_buy9():
    c = np.r_[np.full(5, 10.0), 10.0 - 0.1 * np.arange(1, 13)]
    td = I.td_sequential(c)
    assert td["buy"][5 + 8] == 9.0 and td["buy9"][13] == 1.0 and td["sell"].max() == 0.0


# ---------------------------------------------------------------------------------------------------- toplu / nedensellik
def test_compute_all_shape_names_and_no_inf():
    a = _ohlcv(700)
    names, X = I.compute_all(a, "15m")
    assert X.shape == (700, len(names)) and len(set(names)) == len(names)
    assert not np.isinf(X).any()
    assert all(nm.startswith("15m.") for nm in names)
    n1, _ = I.compute_all(a, "1m")
    assert len(n1) == len(names) - 1 and not any(nm.endswith("poc_dist") for nm in n1)     # 1m'de POC yok
    assert set(I.FAMILY.values()) >= {"ma", "flow", "osc", "trend", "vol", "loc", "smc"}


@pytest.mark.parametrize("tf", ["5m", "15m"])
def test_causality_future_bars_do_not_change_past(tf):
    a = _ohlcv(700)
    names, X = I.compute_all(a, tf)
    b = a.copy()
    rng = np.random.default_rng(9)
    cut = 560
    b[cut:, 1:5] = b[cut:, 1:5] * rng.uniform(0.5, 1.8, size=(len(b) - cut, 4))
    b[cut:, 2] = b[cut:, 1:5].max(axis=1)
    b[cut:, 3] = b[cut:, 1:5].min(axis=1)
    b[cut:, 5:9] = b[cut:, 5:9] * rng.uniform(0.2, 3.0, size=(len(b) - cut, 4))
    _, Y = I.compute_all(b, tf)
    bad = [nm for j, nm in enumerate(names) if not np.allclose(X[:cut, j], Y[:cut, j], rtol=1e-4, atol=1e-5, equal_nan=True)]
    assert bad == []


def test_truncation_equals_prefix():
    a = _ohlcv(700)
    names, X = I.compute_all(a, "15m")
    _, Z = I.compute_all(a[:520], "15m")
    bad = [nm for j, nm in enumerate(names) if not np.allclose(X[:520, j], Z[:, j], rtol=1e-4, atol=1e-5, equal_nan=True)]
    assert bad == []
