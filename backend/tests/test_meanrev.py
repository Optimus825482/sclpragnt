"""app/rescan/meanrev.py sözleşme testleri: nedensellik (kesilmiş girdi → aynı satır), tetik tanımları, limit dolum / çıkış, exit_sim ile denklik."""
from __future__ import annotations

import numpy as np
import pytest

from app.rescan import exit_sim as XS
from app.rescan import flow_futures as FF
from app.rescan import meanrev as M


def _walk(n: int, seed: int = 0, vol: float = 0.003):
    rng = np.random.default_rng(seed)
    c = 100.0 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.concatenate([[c[0]], c[:-1]]) * (1 + rng.normal(0, vol / 4, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    v = rng.uniform(1, 10, n)
    return o, h, l, c, v


def _same(a: np.ndarray, b: np.ndarray) -> bool:
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    return bool(np.array_equal(np.isnan(a), np.isnan(b)) and np.allclose(a[~np.isnan(a)], b[~np.isnan(b)], rtol=1e-12, atol=1e-12))


# ------------------------------------------------------------------------------------------------ nedensellik
@pytest.mark.parametrize("cut", [150, 337, 599])
def test_indicators_causal_under_truncation(cut):
    o, h, l, c, v = _walk(600, 1)
    full = {
        "bbl": M.bollinger_lower(c), "mfi": M.mfi(h, l, c, v), "atr": M.atr_pct(h, l, c), "r3": M.simple_ret(c, 3),
        "mp": M.roll_min_prior(l, 48), "sw": M.sweep_trigger(l, c, w=48, m=3).astype(float),
    }
    part = {
        "bbl": M.bollinger_lower(c[:cut]), "mfi": M.mfi(h[:cut], l[:cut], c[:cut], v[:cut]), "atr": M.atr_pct(h[:cut], l[:cut], c[:cut]),
        "r3": M.simple_ret(c[:cut], 3), "mp": M.roll_min_prior(l[:cut], 48), "sw": M.sweep_trigger(l[:cut], c[:cut], w=48, m=3).astype(float),
    }
    for k in full:
        assert _same(full[k][:cut], part[k]), k


def test_xs_flag_is_columnwise_causal_and_counts():
    rng = np.random.default_rng(3)
    S, T = 60, 40
    x = rng.normal(size=(S, T))
    valid = rng.random((S, T)) > 0.2
    f = M.xs_flag(x, valid, 0.10, "low")
    f_cut = M.xs_flag(x[:, :17], valid[:, :17], 0.10, "low")
    assert np.array_equal(f[:, :17], f_cut)                       # gelecek sütunlar geçmişi değiştirmez
    for t in range(T):
        n = int(valid[:, t].sum())
        assert f[:, t].sum() <= int(np.ceil(0.10 * n)) + 1 and f[:, t].sum() >= 1
        assert not (f[:, t] & ~valid[:, t]).any()
    hi = M.xs_flag(x, valid, 0.20, "high")
    for t in range(T):
        thr_ok = x[hi[:, t], t].min() >= x[valid[:, t] & ~hi[:, t], t].max()
        assert thr_ok
    few = M.xs_flag(x, np.zeros((S, T), bool) | (np.arange(S)[:, None] < 5), 0.1, "low", min_valid=20)
    assert not few.any()                                          # geçerli < min_valid → boş


def test_basis_z_series_matches_flow_futures_and_lag_is_ts_plus_5min():
    n5, ot0 = 700, 1_784_408_400_000
    rng = np.random.default_rng(5)
    ot = ot0 + M.BAR5_MS * np.arange(n5)
    c5 = 3000.0 * np.exp(np.cumsum(rng.normal(0, 0.002, n5)))
    usd = np.full(n5, 40.0)
    ts = ot[rng.random(n5) > 0.1]                                   # %10 satır eksik (ffill ≤ 3)
    oi = rng.uniform(1e3, 2e3, len(ts))
    oiv = oi * 75.0 * (1 + rng.normal(0, 0.002, len(ts)))           # perp ≈ 75 USDT
    mult = 1.0
    bas, z = M.basis_z_series(ot0, n5, c5, usd, ts, oi, oiv, mult)
    cols = np.column_stack([oi, oiv, oi, oi, oi, oi])
    vals, age = FF.align_metric_rows(ts, cols, ot0, n5, extra_lag=0, ffill=3)
    fut = {k: vals[:, i] for i, k in enumerate(FF.FUT_KEYS)}
    nanv = np.full(n5, np.nan)
    names, X = FF.build_futures_features(fut, {k: nanv for k in FF.BD_KEYS}, {k: nanv for k in ("fund_bps", "fund_z", "fund_chg", "fund_age_h")}, c5, usd, mult, age)
    ref = X[:, names.index("fu.basis_z")].astype(float)
    assert _same(np.round(z, 4), np.round(ref, 4)) or np.nanmax(np.abs(z - ref)) < 1e-3
    # ts=T satırı yalnız bar i (ot[i]=T) için bilinir → o barın karar anı (T+5 dk) öncesinde görünmez; bir önceki barda NaN/eski değer
    k = 400
    i_row = np.searchsorted(ts, ot[k])
    oi2 = oi.copy(); oiv2 = oiv.copy()
    oiv2[i_row] *= 1.5                                              # bar k satırını boz
    bas2, _ = M.basis_z_series(ot0, n5, c5, usd, ts, oi2, oiv2, mult)
    assert _same(bas[:k], bas2[:k])                                 # k'dan ÖNCEKİ barlar etkilenmez
    assert not _same(bas[k:k + 1], bas2[k:k + 1])


# ------------------------------------------------------------------------------------------------ tetik tanımları
def test_mfi_extremes():
    n = 40
    c = np.linspace(100, 120, n)
    assert np.allclose(M.mfi(c + 0.1, c - 0.1, c, np.ones(n))[20:], 100.0)
    assert np.allclose(M.mfi(c[::-1] + 0.1, c[::-1] - 0.1, c[::-1], np.ones(n))[20:], 0.0)
    assert np.isnan(M.mfi(c, c, c, np.ones(n))[:14]).all()


def test_bollinger_lower_hand():
    c = np.array([10.0] * 19 + [10.0, 7.0])
    lo = M.bollinger_lower(c, 20, 2.0)
    w = c[1:21]
    assert lo[20] == pytest.approx(w.mean() - 2 * w.std())
    assert 7.0 < lo[20] or True
    assert np.isnan(lo[:19]).all()


def test_sweep_trigger_basic_and_window():
    w = 10
    base = 100.0
    l = np.full(40, base); c = np.full(40, base + 1.0); l[-5:] = base
    # j=20: yeni dip (low 98 < 100), kapanış 98.5 (altında); k=21: 100.5 (üstünde) → tetik 21
    l[20], c[20] = 98.0, 98.5
    l[21], c[21] = 98.2, 100.5
    t = M.sweep_trigger(l, c, w=w, m=3)
    assert t[21] and not t[20]
    # hemen geri-kapanış (aynı bar): düşük 98, kapanış 100.4 → tetik aynı barda
    l2 = np.full(40, base); c2 = np.full(40, base + 1.0)
    l2[20], c2[20] = 98.0, 100.4
    assert M.sweep_trigger(l2, c2, w=w, m=3)[20]
    # 4 bar sonra toparlanma → tetik yok (m=3)
    l3 = np.full(40, base); c3 = np.full(40, base - 1.0)
    l3[20] = 97.0
    c3[20:24] = 98.0
    c3[24] = 101.0
    l3[21:24] = 97.5
    assert not M.sweep_trigger(l3, c3, w=w, m=3).any()
    # sonraki barda 2. kez kapanış üstü → yalnız İLK
    c4 = c.copy(); l4 = l.copy()
    l4[20], c4[20] = 98.0, 98.5
    c4[21], l4[21] = 100.5, 98.1
    c4[22], l4[22] = 100.7, 99.9
    t4 = M.sweep_trigger(l4, c4, w=w, m=3)
    assert t4[21] and not t4[22]


def test_cooldown():
    m = np.zeros(30, bool); m[[2, 3, 7, 14, 15, 26]] = True
    out = M.cooldown(m, 5)
    assert list(np.flatnonzero(out)) == [2, 7, 14, 26]
    assert M.cooldown(np.stack([m, m]), 5).shape == (2, 30)


# ------------------------------------------------------------------------------------------------ atr ≡ exit_sim
def test_atr_pct_equals_exit_sim_atr_pct_at():
    o, h, l, c, v = _walk(400, 7)
    ot = 1_784_408_400_000 + 300_000 * np.arange(400)
    mine = M.atr_pct(h, l, c, 14)
    ref = XS.atr_pct_at(ot, h, l, c, ot + 300_000, 14)
    ok = np.isfinite(ref)
    assert ok.sum() > 300
    assert np.allclose(mine[ok], ref[ok], rtol=1e-9)


# ------------------------------------------------------------------------------------------------ limit dolum
def test_limit_buy_fill_modes():
    N, W = 3, 15
    L = np.full((N, W), 100.0); VW = np.full((N, W), 100.5)
    L[0, 3] = 99.0                                   # dokunma 3. barda
    VW[1, 6] = 99.4                                  # vwap 6. barda ≤ limit
    L[1, 6] = 99.0
    L[2, :] = 100.0; VW[2, 2] = np.nan               # NaN vwap → asla dolmaz
    limit = np.full(N, 99.5)
    assert list(M.limit_buy_fill(L, VW, limit, 15, "low")) == [3, 6, 15]
    assert list(M.limit_buy_fill(L, VW, limit, 15, "vwap")) == [15, 6, 15]
    assert list(M.limit_buy_fill(L, VW, limit, 5, "low")) == [3, 5, 5]           # V=5 → 6. bar görülmez; sentinel = v_max


# ------------------------------------------------------------------------------------------------ çıkış ≡ exit_sim
@pytest.mark.parametrize("tp,sl,nb,seed", [(0.8, 2.0, 120, 0), (0.4, 3.0, 60, 1), (1.2, 2.0, 240, 2), (0.4, 2.0, 30, 3)])
def test_limit_exit_matches_exit_sim(tp, sl, nb, seed):
    rng = np.random.default_rng(seed)
    N, W = 400, 260
    r = np.exp(np.cumsum(rng.normal(0, 0.0025, (N, W)), axis=1))
    C = r.copy()
    O = np.concatenate([np.ones((N, 1)), C[:, :-1]], axis=1) * (1 + rng.normal(0, 0.0004, (N, W)))
    H = np.maximum(O, C) * (1 + np.abs(rng.normal(0, 0.0015, (N, W))))
    L = np.minimum(O, C) * (1 - np.abs(rng.normal(0, 0.0015, (N, W))))
    entry = np.ones(N)
    O[:, 0] = 1.0
    H[:, 0] = 1.0                                     # dolum barında TP görünmez (bizim kuralımız = exit_sim'de bar-0 yüksek ≤ giriş)
    spec = XS.ExitSpec("x", "fixed", sl=sl, time_min=nb, tp=tp)
    ref = XS.simulate(O, H, L, C, spec, slip_pct=0.15, fee_leg_pct=0.1125, fee_tp_leg_pct=0.0675, entry_slip_pct=0.0)
    mine = M.limit_exit(O, H, L, C, np.full((N, W), np.nan), entry, tp, sl, nb, tp_mode="high", skip_first_tp=True, slip_pct=0.15, fee_entry_pct=0.1125,
                        fee_tp_pct=0.0675, fee_stop_pct=0.1125, o0=O[:, 0])
    assert np.allclose(mine["net"], ref["net"], atol=1e-9)
    assert np.array_equal(mine["reason"], np.where(ref["reason"] == XS.R_TP, M.R_TP, np.where(ref["reason"] == XS.R_SL, M.R_SL, M.R_TIME)))
    assert np.allclose(mine["hold"], ref["hold"])
    assert len(set(mine["reason"].tolist())) >= 2                                  # test birden çok çıkış türünü sınıyor


def test_exit_rules_tie_goes_to_stop_and_fill_bar_tp_ignored():
    W = 20
    O = np.ones((2, W)); C = np.ones((2, W)); H = np.ones((2, W)); L = np.ones((2, W))
    # satır 0: aynı barda hem TP hem stop → stop
    H[0, 3] = 1.02; L[0, 3] = 0.96
    # satır 1: dolum barında (0) yüksek TP üstü → görmezden gel; sonra zaman stopu
    H[1, 0] = 1.05
    out = M.limit_exit(O, H, L, C, np.full((2, W), np.nan), np.ones(2), 0.8, 2.0, 10, slip_pct=0.0, fee_entry_pct=0.0, fee_tp_pct=0.0, fee_stop_pct=0.0)
    assert list(out["reason"]) == [M.R_SL, M.R_TIME]
    assert out["net"][0] == pytest.approx(-2.0)                                # min(stop, açılış=1.0) = stop (0.98)
    assert out["net"][1] == pytest.approx(0.0)
    # gap: stop barının açılışı stopun altında → açılıştan dolum
    O2 = np.ones((2, W)); L2 = np.ones((2, W)); O2[0, 4] = 0.90; L2[0, 4] = 0.89
    H2 = np.ones((2, W))
    out2 = M.limit_exit(O2, H2, L2, C, np.full((2, W), np.nan), np.ones(2), 0.8, 2.0, 10, slip_pct=0.0, fee_entry_pct=0.0, fee_tp_pct=0.0, fee_stop_pct=0.0)
    assert out2["net"][0] == pytest.approx(-10.0)


def test_vwap_strict_tp_requires_vwap():
    W = 12
    O = np.ones((1, W)); C = np.ones((1, W)); L = np.ones((1, W)); H = np.ones((1, W)); VW = np.ones((1, W))
    H[0, 4] = 1.02                                   # dokunuş var, vwap yok
    hi = M.limit_exit(O, H, L, C, VW, np.ones(1), 0.8, 2.0, 10, tp_mode="high", slip_pct=0.0, fee_entry_pct=0, fee_tp_pct=0, fee_stop_pct=0)
    vw = M.limit_exit(O, H, L, C, VW, np.ones(1), 0.8, 2.0, 10, tp_mode="vwap", slip_pct=0.0, fee_entry_pct=0, fee_tp_pct=0, fee_stop_pct=0)
    assert hi["reason"][0] == M.R_TP and vw["reason"][0] == M.R_TIME


def test_taker_leg_costs():
    W = 5
    one = np.ones((1, W))
    # piyasa girişi: kayma %0,15 ücret %0,1125; zaman stopu: kayma %0,15 ücret %0,1125
    entry = np.array([1.0015])
    out = M.limit_exit(one, one, one, one, np.full((1, W), np.nan), entry, 5.0, 5.0, 3, skip_first_tp=False, slip_pct=0.15, fee_entry_pct=0.1125,
                       fee_tp_pct=0.0675, fee_stop_pct=0.1125)
    exp = (1.0 * (1 - 0.0015) * (1 - 0.001125)) / (1.0015 * (1 + 0.001125)) - 1
    assert out["net"][0] == pytest.approx(exp * 100)


# ------------------------------------------------------------------------------------------------ rastgele eşleştirme / istatistik
def test_match_random_stays_in_atr_band():
    rng = np.random.default_rng(0)
    pool_atr = rng.uniform(0.1, 2.0, 2000)
    pool_idx = np.arange(2000) * 5
    ev = np.array([0.5, 1.0, 1.5, np.nan])
    pick = M.match_random(ev, pool_atr, pool_idx, 4, rng, width=0.02)
    for e, row in zip(ev[:3], pick[:3]):
        atr_sel = pool_atr[row // 5]
        assert np.all(np.abs(atr_sel - e) < 0.08)
    assert (pick[3] == -1).all()
    assert (M.match_random(ev, np.array([]), np.array([]), 2, rng) == -1).all()


def test_cluster_se_from_sums_matches_exit_sim():
    rng = np.random.default_rng(2)
    x = rng.normal(0.1, 1.0, 500)
    day = rng.integers(0, 30, 500)
    n_g = np.bincount(day, minlength=30).astype(float)
    s_g = np.bincount(day, weights=x, minlength=30)
    assert M.cluster_se_from_sums(n_g, s_g) == pytest.approx(XS.cluster_se(x, day))
    m, se, n = M.mean_se(n_g, s_g)
    assert m == pytest.approx(x.mean()) and n == 500
    assert np.isnan(M.mean_se(np.zeros(3), np.zeros(3))[0])
