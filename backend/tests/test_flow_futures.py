"""app/rescan/flow_futures.py testleri: yuvarlanan istatistikler, hizalama zamanlaması, elle hesaplı özellikler, KESME (nedensellik) testi."""
import numpy as np

from app.rescan import flow_futures as FF

OT0 = 1_784_408_400_000          # 5 dk hizalı


def _synth_flow(n=700, seed=1):
    rng = np.random.default_rng(seed)
    tr = rng.poisson(8, n).astype(float)
    bq = rng.gamma(2.0, 20_000.0, n) * (tr > 0)
    sq = rng.gamma(2.0, 20_000.0, n) * (tr > 0)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    bars = {"n": tr, "bq": bq, "sq": sq, "bb": bq / px, "sb": sq / px,
            "bbq": bq * rng.random(n) * 0.4, "sbq": sq * rng.random(n) * 0.4, "bbn": rng.poisson(1, n).astype(float), "sbn": rng.poisson(1, n).astype(float),
            "wbq": bq * rng.random(n) * 0.15, "wsq": sq * rng.random(n) * 0.15, "mx": rng.gamma(2.0, 8_000.0, n)}
    return bars, px


def _synth_fut(n=700, seed=2):
    rng = np.random.default_rng(seed)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    oi = 1e6 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    fut = {"oi": oi, "oiv": oi * px * 1.0005, "tt_sum": np.exp(rng.normal(0.3, 0.1, n)), "tt_cnt": np.exp(rng.normal(0.2, 0.1, n)),
           "acc": np.exp(rng.normal(0.4, 0.1, n)), "taker": np.exp(rng.normal(0, 0.4, n))}
    d = {k: 1e6 * (1 + rng.random(n)) for k in FF.BD_KEYS}
    t_dec = OT0 + (np.arange(n) + 1) * FF.BAR_MS
    ft = OT0 + np.arange(0, n * FF.BAR_MS, 8 * 3_600_000) + 3
    fr = rng.normal(1e-4, 5e-5, len(ft))
    return fut, d, px, t_dec, ft, fr


def _same(a, b, tol=1e-6):
    a, b = np.asarray(a, float), np.asarray(b, float)
    assert a.shape == b.shape
    both_nan = np.isnan(a) & np.isnan(b)
    ok = both_nan | (np.abs(a - b) <= tol * np.maximum(1.0, np.abs(a)))
    return bool(ok.all())


def test_roll_helpers_match_bruteforce():
    rng = np.random.default_rng(0)
    x = rng.normal(5, 2, 120)
    x[10] = np.nan
    s = FF.roll_sum(np.nan_to_num(x), 4)
    assert np.isnan(s[:3]).all() and abs(s[10] - np.nan_to_num(x)[7:11].sum()) < 1e-9
    m, sd = FF.roll_mean_std(x, n=30, min_n=10)
    for i in (15, 40, 100):
        w = x[max(0, i - 29): i + 1]
        w = w[np.isfinite(w)]
        assert abs(m[i] - w.mean()) < 1e-9 and abs(sd[i] - w.std(ddof=1)) < 1e-9
    assert np.isnan(m[5])
    mx = FF.roll_max(np.array([1.0, 3.0, 2.0, 5.0, 1.0, 0.0]), 3)
    assert np.isnan(mx[:2]).all() and mx[2] == 3 and mx[3] == 5 and mx[5] == 5
    sl = FF.roll_slope(np.arange(10, dtype=float) * 2.0, 5)
    assert np.isnan(sl[:4]).all() and np.allclose(sl[4:], 2.0)
    assert np.isnan(FF.sdiv(np.array([1.0]), np.array([0.0]))[0])


def test_minute_rows_to_bars_and_alignment_boundaries():
    mins = np.array([OT0, OT0 + 60_000, OT0 + 299_000 - 59_000 + 60_000, OT0 + 300_000])        # son dakika 4. dk (OT0+240000)? hesapla
    mins = np.array([OT0, OT0 + 60_000, OT0 + 240_000, OT0 + 300_000], dtype=np.int64)
    cols = {k: np.array([1.0, 2.0, 4.0, 8.0]) for k in FF.FLOW_KEYS}
    cols["mx"] = np.array([5.0, 9.0, 3.0, 7.0])
    b = FF.minute_rows_to_bars(mins, cols, OT0, 3)
    assert b["n"].tolist() == [7.0, 8.0, 0.0] and b["mx"].tolist() == [9.0, 7.0, 0.0]
    # metrics: ts=T satırı T+5dk'da bilinir -> bar (T-ot0)//5dk; t_dec(bar) = T+5dk
    vals = np.arange(1.0, 5.0)[:, None]
    ts = OT0 + np.arange(4) * FF.BAR_MS
    out, age = FF.align_metric_rows(ts, vals, OT0, 6, ffill=1)
    assert out[:4, 0].tolist() == [1.0, 2.0, 3.0, 4.0] and out[4, 0] == 4.0 and np.isnan(out[5, 0]) and age[4] == 1 and age[0] == 0
    # defter: ts dilim içindeki gerçek an; dilim sınırında bir sonraki bara
    out2, _ = FF.align_snapshot_rows(np.array([OT0 + 270_000, OT0 + 300_000]), np.array([[1.0], [2.0]]), OT0, 3, ffill=0)
    assert out2[0, 0] == 1.0 and out2[1, 0] == 2.0


def test_alignment_never_uses_rows_available_after_decision_time():
    n = 40
    rng = np.random.default_rng(3)
    ts = OT0 + np.arange(n) * FF.BAR_MS
    v = rng.normal(size=(n, 2))
    full, _ = FF.align_metric_rows(ts, v, OT0, n, ffill=3)
    for k in (5, 17, 30):
        # t_dec(k) anında bilinen satırlar: T + 5dk <= t_dec(k)=ot[k]+5dk  <=>  T <= ot[k]
        known = ts <= OT0 + k * FF.BAR_MS
        part, _ = FF.align_metric_rows(ts[known], v[known], OT0, n, ffill=3)
        assert _same(full[: k + 1], part[: k + 1])
    tb = OT0 + np.arange(n) * FF.BAR_MS + 4 * 60_000
    fullb, _ = FF.align_snapshot_rows(tb, v, OT0, n, ffill=3)
    for k in (5, 17):
        tdec = OT0 + (k + 1) * FF.BAR_MS
        known = tb <= tdec
        partb, _ = FF.align_snapshot_rows(tb[known], v[known], OT0, n, ffill=3)
        assert _same(fullb[: k + 1], partb[: k + 1])


def test_funding_is_asof_settled_and_z_uses_past_only():
    ft = np.array([0, 8, 16, 24, 32, 40, 48, 56, 64], dtype=np.int64) * 3_600_000 + OT0 + 3
    r = np.array([1, 2, 1, 2, 1, 2, 1, 2, 10], dtype=float) * 1e-4
    t = np.array([ft[0] - 1, ft[0] + 5, ft[8] - 1, ft[8] + 1], dtype=np.int64)
    f = FF.funding_features(ft, r, t, hist=21, min_hist=6)
    assert np.isnan(f["fund_bps"][0]) and abs(f["fund_bps"][1] - 1.0) < 1e-9
    assert abs(f["fund_bps"][2] - 2.0) < 1e-9                 # ft[8] henüz yerleşmedi
    assert abs(f["fund_bps"][3] - 10.0) < 1e-9 and f["fund_z"][3] > 5 and abs(f["fund_chg"][3] - 8.0) < 1e-9
    # gelecek oranı değiştirmek önceki karar anlarını etkilemez
    r2 = r.copy(); r2[8] = -50e-4
    f2 = FF.funding_features(ft, r2, t, hist=21, min_hist=6)
    assert _same(f["fund_bps"][:3], f2["fund_bps"][:3]) and _same(f["fund_z"][:3], f2["fund_z"][:3])


def test_flow_hand_example():
    n = 30
    bars = {k: np.zeros(n) for k in FF.FLOW_KEYS}
    bars["bq"][:] = 100.0
    bars["sq"][:] = 100.0
    bars["n"][:] = 10.0
    bars["bb"][:] = 1.0
    bars["sb"][:] = 1.0
    bars["bq"][29] = 300.0        # son bar: alış baskın
    bars["bbq"][29] = 200.0
    bars["wbq"][29] = 150.0
    bars["wsq"][29] = 50.0
    bars["mx"][29] = 150.0
    c5 = np.full(n, 100.0)
    names, X = FF.build_flow_features(bars, c5, cov0=0)
    ix = {nm: j for j, nm in enumerate(names)}
    assert abs(X[29, ix["tf.buy_share_5"]] - 0.75) < 1e-6
    assert abs(X[29, ix["tf.bigbuy_share_5"]] - 1.0) < 1e-6
    assert abs(X[29, ix["tf.big_net_5"]] - 0.5) < 1e-6
    assert abs(X[29, ix["tf.whale_net_5"]] - np.log10(101.0)) < 1e-5
    assert abs(X[29, ix["tf.buy_share_15"]] - (300 + 200) / (300 + 200 + 300)) < 1e-6
    assert abs(X[10, ix["tf.buy_share_5"]] - 0.5) < 1e-6
    assert np.isnan(X[1, ix["tf.buy_share_15"]])                # pencere dolmadı
    assert abs(X[29, ix["tf.vwap_dist_5"]] - np.log(100.0 / (400.0 / 2.0))) < 1e-5     # vwap=quote/base=200
    # akış kapsamı öncesi NaN
    _, X2 = FF.build_flow_features(bars, c5, cov0=12)
    assert np.isnan(X2[10, ix["tf.buy_share_5"]]) and not np.isnan(X2[29, ix["tf.buy_share_5"]])


def test_flow_features_truncation_causality():
    bars, px = _synth_flow(700)
    names, X = FF.build_flow_features(bars, px, cov0=5)
    assert X.shape[1] == len(FF.flow_feature_names()) and names == FF.flow_feature_names()
    for k in (30, 150, 321, 700):
        tb = {kk: v[:k] for kk, v in bars.items()}
        _, Xt = FF.build_flow_features(tb, px[:k], cov0=5)
        assert _same(X[k - 1], Xt[k - 1], tol=1e-5), k
        assert _same(X[:k], Xt, tol=1e-5), k


def test_futures_features_truncation_causality_and_values():
    n = 700
    fut, bd, px, t_dec, ft, fr = _synth_fut(n)
    usd = np.full(n, 40.0)
    c5 = px * usd                               # TRY fiyat
    age = np.zeros(n)
    f = FF.funding_features(ft, fr, t_dec)
    names, X = FF.build_futures_features(fut, bd, f, c5, usd, 1.0, age)
    assert names == FF.futures_feature_names() and X.shape[1] == len(names)
    ix = {nm: j for j, nm in enumerate(names)}
    # baz: oiv/oi = px*1.0005 -> +5 bps
    assert abs(X[400, ix["fu.basis_bps"]] - 1e4 * np.log(1.0005)) < 1e-2
    # çarpan: perp 1000x -> baz = 1e4*ln(1000*1.0005/1000)... c5/usd*1000 gibi dolaylı; çarpan 1000 verilirse baz ln(1.0005/1000)
    _, X3 = FF.build_futures_features(fut, bd, f, c5, usd, 1000.0, age)
    assert abs(X3[400, ix["fu.basis_bps"]] - 1e4 * np.log(1.0005 / 1000.0)) < 1e-1
    # OI değişimi
    assert abs(X[400, ix["fu.oi_chg_15"]] - 100 * np.log(fut["oi"][400] / fut["oi"][397])) < 1e-4
    b = FF.build_futures_features
    for k in (40, 200, 333, 700):
        fut_t = {kk: v[:k] for kk, v in fut.items()}
        bd_t = {kk: v[:k] for kk, v in bd.items()}
        ft_ = FF.funding_features(ft, fr, t_dec[:k])
        _, Xt = b(fut_t, bd_t, ft_, c5[:k], usd[:k], 1.0, age[:k])
        assert _same(X[:k], Xt, tol=1e-5), k
    # bayat satır -> baz NaN
    age2 = age.copy(); age2[400] = 1
    _, X4 = FF.build_futures_features(fut, bd, f, c5, usd, 1.0, age2)
    assert np.isnan(X4[400, ix["fu.basis_bps"]]) and not np.isnan(X4[401, ix["fu.basis_bps"]])


def test_quadrants():
    n = 40
    fut, bd, px, t_dec, ft, fr = _synth_fut(n)
    fut["oi"] = np.full(n, 1e6)
    fut["oiv"] = fut["oi"] * 100.0
    c5 = np.full(n, 100.0)
    c5[20:] = 101.0                                   # +1 % bar 20'de
    fut["oi"][20:] = 1.01e6                           # OI +1 %
    f = FF.funding_features(ft, fr, t_dec)
    names, X = FF.build_futures_features(fut, bd, f, c5, np.full(n, 40.0), 1.0, np.zeros(n))
    ix = {nm: j for j, nm in enumerate(names)}
    assert X[20, ix["fu.quad_15"]] == 1.0 and X[20, ix["fu.quad_newlong_15"]] == 1.0
    assert X[10, ix["fu.quad_15"]] == 0.0
    fut["oi"][20:] = 0.99e6                           # OI -1 % -> short kapatma
    names, X = FF.build_futures_features(fut, bd, f, c5, np.full(n, 40.0), 1.0, np.zeros(n))
    assert X[20, ix["fu.quad_15"]] == 2.0 and X[20, ix["fu.quad_shortcover_15"]] == 1.0


def test_families_cover_all_names():
    for nm in FF.flow_feature_names() + FF.futures_feature_names():
        assert FF.family_of(nm) != "?", nm


def test_study_helpers_group_auc_and_bootstrap_and_signals():
    from scripts import flowfut_study as FS
    # grup-içi AUC: olay skoru en yüksek -> 1.0; eşit -> 0.5
    y = np.array([1, 0, 0, 0, 1, 0, 0, 0])
    g = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    p = np.array([0.9, 0.1, 0.2, 0.3, 0.5, 0.5, 0.5, 0.5])
    ids, a = FS.group_auc_vec(p, y, g)
    assert ids.tolist() == [0, 1] and abs(a[0] - 1.0) < 1e-12 and abs(a[1] - 0.5) < 1e-12
    rng = np.random.default_rng(0)
    x = rng.normal(0.5, 1.0, 200)
    day = np.repeat(np.arange(40), 5)
    m, se, lo, hi = FS.boot_mean_ci(x, day)
    assert abs(m - x.mean()) < 1e-12 and lo < m < hi and se > 0
    # sinyal maskeleri: NaN tetiklemez, eşik üstü tetikler
    n = 30
    nan = np.full(n, np.nan)
    F = {k: nan.copy() for k in ("tf.whale_net_5", "tf.whale_net_rel_5", "tf.whale_net_15", "tf.bigbuy_share_15", "tf.bigcnt_15", "tf.buy_share_15", "tf.flow_acc", "tf.ntr_z_15",
                                 "fu.oi_chg_15", "fu.oi_chg_60", "fu.fund_z", "fu.fund_bps", "fu.taker_ls_acc", "fu.bd_imb2", "fu.bd_imb2_d3", "fu.basis_d15", "fu.basis_z", "fu.taker_ls_z")}
    c5 = np.full(n, 100.0)
    ms = FS.signal_masks(F, c5)
    assert set(ms) == set(FS.SIGNALS) and not any(m.any() for m in ms.values())
    F["tf.whale_net_5"][10] = 5.2
    assert ms["whale_flat_abs"].sum() == 0 and FS.signal_masks(F, c5)["whale_flat_abs"].tolist() == [i == 10 for i in range(n)]
