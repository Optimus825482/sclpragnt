"""`app.rescan.pattern_study` — olay tanımı, 3 dk toplulaştırma, gösterge paritesi, istatistik/desen yardımcıları."""
from __future__ import annotations

import numpy as np
import pytest

from app import technical_analysis as TA
from app.rescan import pattern_study as P

T0 = 1_790_000_000_000 - (1_790_000_000_000 % 900_000)  # 15 dk sınırı (3, 5 dk ile hizalı)


def _bars(closes, *, opens=None, bar_ms=300_000, t0=T0, vol=100.0, spread=0.0005):
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]]) if opens is None else np.asarray(opens, dtype=float)
    n = len(c)
    arr = np.zeros((n, 7))
    arr[:, 0] = t0 + np.arange(n) * bar_ms
    arr[:, 1] = o
    arr[:, 2] = np.maximum(o, c) * (1 + spread)
    arr[:, 3] = np.minimum(o, c) * (1 - spread)
    arr[:, 4] = c
    arr[:, 5] = vol
    arr[:, 6] = vol * c * 100  # yüksek quote → likidite filtresini geçer
    return arr


def _flat_then(closes_after, n_pre=400, base=10.0):
    return np.concatenate([np.full(n_pre, base), np.asarray(closes_after, dtype=float)])


# ------------------------------------------------------------------------------------------ 3 dk toplulaştırma
def test_aggregate_3m_values_and_alignment():
    # 1 dk mumlar 3 dk sınırından başlar: 2 tam kova + 1 eksik kova
    t0 = T0
    c = np.arange(1, 9, dtype=float)  # 8 mum → kovalar: [0-2], [3-5], [6-7 eksik]
    arr = _bars(c, bar_ms=60_000, t0=t0)
    arr[:, 2] = c + 0.5; arr[:, 3] = c - 0.5; arr[:, 5] = 1.0
    out = P.aggregate_bars(arr, 3)
    assert out.shape == (2, 7)
    assert out[0, 0] == t0 and out[1, 0] == t0 + 180_000
    assert out[0, 0] % 180_000 == 0
    assert out[0, P.COL_O] == arr[0, P.COL_O] and out[0, P.COL_C] == arr[2, P.COL_C]
    assert out[0, P.COL_H] == arr[:3, P.COL_H].max() and out[0, P.COL_L] == arr[:3, P.COL_L].min()
    assert out[1, P.COL_V] == 3.0
    assert out[1, P.COL_QV] == arr[3:6, P.COL_QV].sum()


def test_aggregate_drops_partial_leading_and_gap_buckets():
    t0 = T0 + 60_000  # ilk kova eksik başlıyor (1 dk geç)
    arr = _bars(np.arange(1, 13, dtype=float), bar_ms=60_000, t0=t0)  # 12 mum
    out = P.aggregate_bars(arr, 3)
    assert out[0, 0] == T0 + 180_000  # kısmi ilk kova atıldı
    assert all(out[:, 0] % 180_000 == 0)
    # boşluk: ortadan bir mum eksik → o kova atılır, diğerleri kalır
    full = _bars(np.arange(1, 10, dtype=float), bar_ms=60_000, t0=T0)
    gap = np.delete(full, 4, axis=0)  # ikinci kovadan bir mum çıkar
    out2 = P.aggregate_bars(gap, 3)
    assert list(out2[:, 0]) == [T0, T0 + 360_000]


def test_aggregate_empty():
    assert P.aggregate_bars(np.zeros((0, 7)), 3).shape == (0, 7)


def test_fill_gaps_flat_candles_and_zero_volume():
    arr = _bars([10.0, 10.2, 10.4, 10.6, 10.8])
    gap = np.delete(arr, [2, 3], axis=0)           # 3. ve 4. mum satırı yok
    out = P.fill_gaps(gap, 300_000)
    assert len(out) == 5 and list(out[:, 0]) == list(arr[:, 0])
    assert out[2, P.COL_C] == 10.2 and out[2, P.COL_O] == 10.2 and out[2, P.COL_H] == 10.2 and out[2, P.COL_V] == 0
    assert out[3, P.COL_C] == 10.2 and out[4, P.COL_C] == 10.8
    assert P.fill_gaps(arr, 300_000).shape == arr.shape       # boşluk yoksa aynı


def test_event_survives_missing_rows_via_fill():
    stair = _staircase(10, 0.6)
    arr = _bars(np.concatenate([np.full(400, 10.0), stair, np.full(30, stair[-1])]))
    gap = np.delete(arr, [403, 407], axis=0)        # koşu içinde iki satır eksik
    assert P.find_events("T", gap, P.EventParams()) == []   # ham satırlarda zaman boşluğu → olay yok
    ev = P.find_events("T", P.fill_gaps(gap, 300_000), P.EventParams())
    assert len(ev) == 1 and ev[0]["s"] == 400


# ------------------------------------------------------------------------------------------ olay tanımı
def _staircase(n_bars=10, step=0.6):
    """Her mum +step% (yeşil, tek mum < 2.5%), toplam ≈ +6% — geri çekilmesiz merdiven."""
    c = [10.0]
    for _ in range(n_bars):
        c.append(c[-1] * (1 + step / 100))
    return np.array(c[1:])


def test_event_detects_staircase_and_reports_t0():
    stair = _staircase(10, 0.6)
    closes = np.concatenate([np.full(400, 10.0), stair, np.full(30, stair[-1])])
    arr = _bars(closes)
    ev = P.find_events("TEST", arr, P.EventParams())
    assert len(ev) == 1
    e = ev[0]
    assert e["s"] == 400                          # koşunun ilk mumu
    assert e["t0"] == int(arr[400, 0])
    assert e["gain"] == pytest.approx((stair[-1] / 10.0 - 1) * 100, rel=1e-6)
    assert e["dur_min"] == 50
    assert e["green"] == 1.0


def test_event_ends_before_climax_spike_and_ignores_flat_fill():
    # 8 mum merdiven (+%5), sonra tek mum +%3 patlama: koşu spike'tan ÖNCE biten geçerli (e) ile olay sayılır
    stair = _staircase(8, 0.65)
    spike = stair[-1] * 1.03
    closes = np.concatenate([np.full(400, 10.0), stair, [spike], np.full(10, spike)])
    ev = P.find_events("T", _bars(closes), P.EventParams())
    assert len(ev) == 1 and ev[0]["s"] == 400
    assert ev[0]["dur_min"] == 40 and ev[0]["maxc"] <= 2.5          # 8 mum; spike dahil değil
    assert ev[0]["gain"] == pytest.approx((stair[-1] / 10.0 - 1) * 100, rel=1e-6)


def test_event_rejects_spike_single_candle():
    closes = np.concatenate([np.full(400, 10.0), [10.0 * 1.05], np.full(15, 10.5)])  # tek mum +5%
    ev = P.find_events("TEST", _bars(closes), P.EventParams())
    assert ev == []


def test_event_rejects_deep_pullback_and_low_green():
    # +%1.6 → -%2 geri çekilme → yeniden yükseliş: toplam > 4 ama dd > 1.5
    path = [10.16, 10.35, 10.10, 10.30, 10.45, 10.60]
    ev = P.find_events("TEST", _bars(_flat_then(path)), P.EventParams())
    assert ev == []
    # yeşil payı düşük: kırmızı mumlar çoğunlukta (aynı kapanış serisi, açılışlar ters) — kapanış > açılış değil
    stair = _staircase(10, 0.5)
    closes = _flat_then(stair)
    arr = _bars(closes)
    arr[400:, P.COL_O] = arr[400:, P.COL_C] * 1.0001   # tüm koşu mumları kırmızı
    assert P.find_events("TEST", arr, P.EventParams()) == []


def test_event_rejects_low_liquidity_and_small_gain():
    arr = _bars(_flat_then(_staircase(10, 0.6)))
    arr[:, P.COL_QV] = 1.0        # 24 sa quote çok düşük
    assert P.find_events("TEST", arr, P.EventParams()) == []
    small = _bars(_flat_then(_staircase(10, 0.2)))  # toplam ≈ +2%
    assert P.find_events("TEST", small, P.EventParams()) == []


def test_event_requires_start_low_and_dedupes_3h():
    stair = _staircase(10, 0.6)
    # iki ardışık merdiven 20 bar (100 dk) arayla → 3 saatlik dedupe ikincisini eler
    seg = np.concatenate([stair, np.full(10, stair[-1])])
    closes = np.concatenate([np.full(400, 10.0), seg, seg[-1] * (stair / 10.0), np.full(20, 10.0)])
    ev = P.find_events("TEST", _bars(closes), P.EventParams())
    assert len(ev) == 1
    ev2 = P.find_events("TEST", _bars(closes), P.EventParams(dedupe_hours=0.5))
    assert len(ev2) >= 2


def test_event_time_filter_and_no_forward_window_at_end():
    stair = _staircase(10, 0.6)
    arr = _bars(np.concatenate([np.full(400, 10.0), stair[:5]]))  # veri koşunun ortasında bitiyor
    mask, _ = P.event_mask(arr, P.EventParams())
    assert not mask.any()      # tam pencere yok → olay yok
    arr2 = _bars(np.concatenate([np.full(400, 10.0), stair, np.full(5, stair[-1])]))
    assert P.find_events("T", arr2, P.EventParams(), t_min_ms=int(arr2[405, 0])) == []


# ------------------------------------------------------------------------------------------ gösterge paritesi
@pytest.fixture(scope="module")
def walk():
    rng = np.random.default_rng(3)
    n = 500
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.concatenate([[c[0]], c[:-1]]) * (1 + rng.normal(0, 0.0007, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0015, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0015, n)))
    v = rng.uniform(50, 500, n)
    arr = np.column_stack([T0 + np.arange(n) * 300_000, o, h, l, c, v, v * c])
    return arr


def _feat(walk, tf="5m"):
    names, X = P.features_matrix(walk, tf)
    return {nm.split(".", 1)[1]: X[:, i] for i, nm in enumerate(names)}, X


@pytest.mark.parametrize("cut", [330, 421, 500])
def test_indicator_parity_with_canonical(walk, cut):
    f, _ = _feat(walk)
    a = walk[:cut]
    h, l, c, v, o = a[:, 2], a[:, 3], a[:, 4], a[:, 5], a[:, 1]
    i = cut - 1
    assert f["rsi14"][i] == pytest.approx(TA._rsi(list(c), 14), abs=1e-7)
    assert f["mfi14"][i] == pytest.approx(TA._mfi(h, l, c, v, 14), abs=1e-6)
    assert f["atr14_pct"][i] == pytest.approx(TA._atr(h, l, c, 14) / c[-1] * 100, rel=1e-9)
    bb = TA._bollinger(list(c), 20)
    assert f["bb_width_pct"][i] == pytest.approx(bb["width_pct"] * 100, rel=1e-9)
    assert f["bb_pctb"][i] == pytest.approx(bb["position"], rel=1e-9)
    m = TA._macd(list(c))
    assert f["macd_hist_pct"][i] == pytest.approx(m["histogram"] / c[-1] * 100, rel=1e-6, abs=1e-9)
    ad = TA._adx(list(h), list(l), list(c), 14)
    assert f["adx14"][i] == pytest.approx(ad["adx"], abs=1e-6)
    assert f["plus_di14"][i] == pytest.approx(ad["plus_di"], abs=1e-6)
    assert f["minus_di14"][i] == pytest.approx(ad["minus_di"], abs=1e-6)
    ar = TA._aroon(list(h), list(l), 25)
    assert f["aroon_up25"][i] == pytest.approx(ar["up"]) and f["aroon_down25"][i] == pytest.approx(ar["down"])
    assert f["linreg10_pct"][i] == pytest.approx(TA._linreg_slope_pct(list(c), 10), rel=1e-9)
    assert f["linreg20_pct"][i] == pytest.approx(TA._linreg_slope_pct(list(c), 20), rel=1e-9)
    e7, e20, e99 = TA._ema(list(c), 7), TA._ema(list(c), 20), TA._ema(list(c), 99)
    assert f["px_ema7"][i] == pytest.approx((c[-1] / e7 - 1) * 100, rel=1e-9, abs=1e-9)
    assert f["ema20_50"][i] == pytest.approx((e20 / TA._ema(list(c), 50) - 1) * 100, rel=1e-9, abs=1e-9)
    assert f["px_ema99"][i] == pytest.approx((c[-1] / e99 - 1) * 100, rel=1e-9, abs=1e-9)


def test_features_are_causal(walk):
    """i. satır, i'den sonraki barlar değiştirilince DEĞİŞMEMELİ."""
    names, X = P.features_matrix(walk, "5m")
    cut = 420
    mutated = walk.copy()
    mutated[cut + 1:, 1:6] *= 1.3
    _, X2 = P.features_matrix(mutated, "5m")
    np.testing.assert_allclose(X[: cut + 1], X2[: cut + 1], rtol=1e-9, atol=1e-9, equal_nan=True)


def test_feature_names_and_hour_only_on_5m(walk):
    n5, _ = P.features_matrix(walk, "5m")
    n1, _ = P.features_matrix(walk, "1m")
    assert "5m.hour" in n5 and "1m.hour" not in n1
    assert [x.split(".", 1)[1] for x in n5 if not x.endswith(".hour")] == [x.split(".", 1)[1] for x in n1]


def test_green_run_and_hl_run():
    c = np.array([10, 10.1, 10.2, 10.3, 10.2, 10.3, 10.4], dtype=float)
    arr = _bars(c)
    arr[:, P.COL_L] = np.array([9.9, 10.0, 10.1, 10.2, 10.0, 10.1, 10.2])
    # 1. mumdan itibaren yeşil: open=prev close
    names, X = P.features_matrix(arr, "5m")
    f = {nm.split(".", 1)[1]: X[:, i] for i, nm in enumerate(names)}
    assert list(f["green_run"]) == [0, 1, 2, 3, 0, 1, 2]
    assert list(f["hl_run"]) == [0, 1, 2, 3, 0, 1, 2]


# ------------------------------------------------------------------------------------------ anlık görüntü / istatistik
def test_snapshot_index_uses_only_closed_bars():
    ot = np.array([0, 180_000, 360_000], dtype=np.int64)
    # t = 360_000: 3. bar (open 360000) henüz kapanmadı → son kapanmış = 2. bar (indeks 1)
    assert P.snapshot_index(ot, 180_000, 360_000) == 1
    assert P.snapshot_index(ot, 180_000, 539_999) == 1
    assert P.snapshot_index(ot, 180_000, 540_000) == 2
    assert P.snapshot_index(ot, 180_000, 100_000) == -1           # hiç kapanmış bar yok
    assert P.snapshot_index(ot, 180_000, 540_000 + 10 * 180_000) == -1  # bayat


def test_auc_smd_and_fwer():
    rng = np.random.default_rng(1)
    y = np.r_[np.ones(40), np.zeros(800)]
    x_sig = np.r_[rng.normal(1.5, 1, 40), rng.normal(0, 1, 800)]
    x_noise = rng.normal(0, 1, 840)
    X = np.column_stack([x_sig, x_noise])
    auc = P.auc_matrix(X, y)
    assert auc[0] > 0.85 and abs(auc[1] - 0.5) < 0.1
    d = P.smd(X, y)
    assert d[0] > 1.0 and abs(d[1]) < 0.4
    strata = np.arange(840) % 10
    thr, mx = P.fwer_threshold(X, y, strata, n_perm=60, seed=2)
    assert abs(auc[0] - 0.5) > thr and abs(auc[1] - 0.5) < thr + 0.05
    assert len(mx) == 60


def test_tree_pattern_recovers_conjunction():
    rng = np.random.default_rng(5)
    n1, n0 = 60, 1200
    y = np.r_[np.ones(n1), np.zeros(n0)]
    a = np.r_[rng.normal(2, 0.5, n1), rng.normal(0, 1, n0)]
    b = np.r_[rng.normal(-1, 0.4, n1), rng.normal(0, 1, n0)]
    z = rng.normal(0, 1, n1 + n0)
    X = np.column_stack([a, b, z])
    tp = P.fit_pattern_tree(X, y, ["f.a", "f.b", "f.z"], depth=2, min_leaf_events=10)
    assert tp is not None
    feats = {c.feature for c in tp.conditions}
    assert feats == {"f.a", "f.b"}
    cols = {"f.a": a, "f.b": b, "f.z": z}
    m = P.eval_conditions(cols, tp.conditions)
    assert m[y == 1].mean() > 0.6 and m[y == 0].mean() < 0.10
    assert tp.leaf_recall == pytest.approx(m[y == 1].mean())


def test_eval_conditions_nan_false_and_merge():
    cols = {"x": np.array([1.0, np.nan, 3.0]), "y": np.array([5.0, 5.0, 1.0])}
    m = P.eval_conditions(cols, [P.Condition("x", ">", 0.5), P.Condition("y", "<=", 4.0)])
    assert list(m) == [False, False, True]
    merged = P.merge_conditions([P.Condition("x", "<=", 5.0), P.Condition("x", "<=", 3.0), P.Condition("x", ">", 1.0)])
    assert {(c.op, c.value) for c in merged} == {("<=", 3.0), (">", 1.0)}
    with pytest.raises(ValueError):
        P.eval_conditions(cols, [])


def test_tree_max_fpr_selects_pure_leaf():
    rng = np.random.default_rng(8)
    n1, n0 = 80, 3000
    y = np.r_[np.ones(n1), np.zeros(n0)]
    a = np.r_[rng.normal(2.0, 0.8, n1), rng.normal(0, 1, n0)]
    b = np.r_[rng.normal(2.0, 0.8, n1), rng.normal(0, 1, n0)]
    X = np.column_stack([a, b])
    loose = P.fit_pattern_tree(X, y, ["f.a", "f.b"], depth=3, min_leaf_events=5)
    tight = P.fit_pattern_tree(X, y, ["f.a", "f.b"], depth=3, min_leaf_events=5, max_fpr=0.03, min_recall=0.05)
    assert tight is not None and tight.leaf_fpr <= 0.03
    assert loose is None or tight.leaf_fpr <= loose.leaf_fpr


# ------------------------------------------------------------------------------------------ taker özellikleri
def _taker_arr(n=400, seed=5, bar_ms=300_000, buy_share=None):
    rng = np.random.default_rng(seed)
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    qv = rng.uniform(1e4, 5e4, n)
    share = rng.uniform(0.3, 0.7, n) if buy_share is None else np.asarray(buy_share, dtype=float)
    tbq = qv * share
    o = np.concatenate([[c[0]], c[:-1]])
    arr = np.zeros((n, 9))
    arr[:, 0] = T0 + np.arange(n) * bar_ms
    arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4] = o, np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999, c
    arr[:, 5] = qv / c
    arr[:, 6] = qv
    arr[:, 7] = tbq / c
    arr[:, 8] = tbq
    return arr, qv, tbq, share


def test_taker_share_windows_and_net_flow_values():
    n = 500
    arr, qv, tbq, share = _taker_arr(n)
    f = P.taker_features(tbq, qv, 288)
    i = 450
    assert f["tk_share1"][i] == pytest.approx(tbq[i] / qv[i])
    for k in (3, 6, 12):
        assert f[f"tk_share{k}"][i] == pytest.approx(tbq[i - k + 1:i + 1].sum() / qv[i - k + 1:i + 1].sum())
    for k in (6, 12):
        want = (2 * tbq[i - k + 1:i + 1] - qv[i - k + 1:i + 1]).sum() / qv[i - 287:i + 1].sum() * 100
        assert f[f"tk_net{k}"][i] == pytest.approx(want)
    assert f["tk_qratio"][i] == pytest.approx(tbq[i] / tbq[i - 20:i].mean())
    # z-skoru: son-3 payı, ondan ÖNCEKİ 288 barlık (3 bar boşluklu) son-3 payı dağılımına göre
    s3 = np.array([tbq[j - 2:j + 1].sum() / qv[j - 2:j + 1].sum() for j in range(2, n)])   # s3[j-2]
    prev = s3[(i - 3 - 287) - 2:(i - 3) - 2 + 1]
    assert f["tk_share_z3"][i] == pytest.approx((s3[i - 2] - prev.mean()) / prev.std())


def test_taker_slope_balanced_and_directional():
    share = np.full(60, 0.5)
    share[-6:] = np.linspace(0.40, 0.60, 6)               # son 6 barda doğrusal artış, adım 0,04
    arr, qv, tbq, _ = _taker_arr(60, buy_share=share)
    f = P.taker_features(tbq, qv, 288)
    assert f["tk_share_slope6"][-1] == pytest.approx(0.04)
    flat, qv2, tbq2, _ = _taker_arr(400, buy_share=np.full(400, 0.5))
    g = P.taker_features(tbq2, qv2, 288)
    assert g["tk_share1"][-1] == pytest.approx(0.5) and g["tk_share12"][-1] == pytest.approx(0.5)
    assert g["tk_share_slope6"][-1] == pytest.approx(0.0, abs=1e-12) and g["tk_net6"][-1] == pytest.approx(0.0, abs=1e-12)
    # saf alış → pay 1, net akış = Σqv / q24 · 100
    buy, qv3, tbq3, _ = _taker_arr(400, buy_share=np.ones(400))
    h = P.taker_features(tbq3, qv3, 288)
    assert h["tk_share6"][-1] == pytest.approx(1.0)
    assert h["tk_net6"][-1] == pytest.approx(qv3[-6:].sum() / qv3[-288:].sum() * 100)


def test_taker_nan_zero_volume_and_causality():
    arr, qv, tbq, _ = _taker_arr(400)
    tb = tbq.copy(); tb[300] = np.nan
    f = P.taker_features(tb, qv, 288)
    assert np.isnan(f["tk_share1"][300]) and np.isnan(f["tk_share3"][302]) and np.isfinite(f["tk_share3"][303])
    assert np.isnan(f["tk_net6"][305]) and np.isfinite(f["tk_net6"][306])
    assert np.isfinite(f["tk_share_z3"][350])            # tek NaN 24 sa istatistiğini öldürmez
    # işlem yok (qv=0, tbq=0) → nötr 0,5 payı
    q0, t0_ = qv.copy(), tbq.copy()
    q0[200:206] = 0.0; t0_[200:206] = 0.0
    g = P.taker_features(t0_, q0, 288)
    assert g["tk_share1"][203] == pytest.approx(0.5) and g["tk_share6"][205] == pytest.approx(0.5)
    # nedensellik: i'den sonrasını bozmak i. değeri değiştirmez
    cut = 350
    tb2, q2 = tbq.copy(), qv.copy()
    tb2[cut + 1:] *= 3.0; q2[cut + 1:] *= 2.0
    a, b = P.taker_features(tbq, qv, 288), P.taker_features(tb2, q2, 288)
    for k in a:
        np.testing.assert_allclose(a[k][:cut + 1], b[k][:cut + 1], rtol=1e-9, atol=1e-9, equal_nan=True)


def test_features_matrix_adds_taker_only_with_taker_columns():
    arr, *_ = _taker_arr(400)
    n9, X9 = P.features_matrix(arr, "5m")
    n7, X7 = P.features_matrix(arr[:, :7], "5m")
    assert [x for x in n9 if x.split(".", 1)[1].startswith("tk_")] == [f"5m.{k}" for k in P.TAKER_FEATURES]
    assert n9[:len(n7)] == n7 and not any(".tk_" in x for x in n7)
    np.testing.assert_allclose(X9[:, :len(n7)], X7, equal_nan=True)
    n1, _ = P.features_matrix(arr, "1m")
    assert "1m.tk_share3" in n1 and "1m.hour" not in n1


def test_aggregate_and_fill_gaps_carry_taker_columns():
    arr, *_ = _taker_arr(12, bar_ms=60_000)
    out = P.aggregate_bars(arr, 3)
    assert out.shape == (4, 9)
    assert out[0, P.COL_TBQ] == pytest.approx(arr[:3, P.COL_TBQ].sum()) and out[1, P.COL_TBB] == pytest.approx(arr[3:6, P.COL_TBB].sum())
    withnan = arr.copy(); withnan[4, P.COL_TBQ] = np.nan
    o2 = P.aggregate_bars(withnan, 3)
    assert np.isnan(o2[1, P.COL_TBQ]) and np.isfinite(o2[0, P.COL_TBQ]) and np.isfinite(o2[2, P.COL_TBQ])
    gap = np.delete(arr, [5, 6], axis=0)
    filled = P.fill_gaps(gap, 60_000)
    assert filled.shape == (12, 9) and filled[5, P.COL_TBQ] == 0.0 and filled[6, P.COL_TBB] == 0.0 and filled[7, P.COL_TBQ] == arr[7, P.COL_TBQ]
    rm = P.real_mask(gap, 60_000)
    assert rm.shape == (12,) and list(np.flatnonzero(~rm)) == [5, 6]


# ------------------------------------------------------------------------------------------ vektörel ileri sonuçlar
def test_forward_outcomes_matches_eval_window_and_trail_window():
    """`forward_outcomes` (vektörel) ≡ `eval_window` + `trail_window` — boşluklu (eksik satırlı) rastgele yürüyüşte."""
    from scripts.notification_outcomes_report import CandleStore, eval_window
    from scripts.strategy_rescan import trail_window
    rng = np.random.default_rng(11)
    n = 700
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
    arr = np.column_stack([T0 + np.arange(n) * 300_000, o, h, l, c, np.full(n, 5.0), np.full(n, 50.0)])
    keep = np.ones(n, dtype=bool)
    keep[rng.choice(np.arange(20, n - 20), size=40, replace=False)] = False
    keep[300:306] = False                                   # uzun boşluk
    raw = arr[keep]
    filled = P.fill_gaps(raw, 300_000)
    real = P.real_mask(raw, 300_000)
    out = P.forward_outcomes(filled[:, P.COL_H], filled[:, P.COL_L], filled[:, P.COL_C], real, tps=(1.5, 2.0, 4.0))
    store = CandleStore({"X": (raw[:, 0], raw[:, 2], raw[:, 3], raw[:, 4])})
    ot = filled[:, 0]
    checked = valid_n = 0
    for i in range(0, len(filled) - 14, 3):
        det = (ot[i] + 300_000) / 1000.0
        entry = float(filled[i, P.COL_C])
        for tp in (1.5, 2.0, 4.0):
            ref = eval_window(*store.d["X"], det, entry, tp, 60, 3.0, 0.225)
            if ref is None:
                assert out["valid"][i] == 0 or tp != 1.5
                continue
            assert out["valid"][i] == 1
            assert out[f"hit{tp}"][i] == float(ref["hit"]) and out[f"net{tp}"][i] == pytest.approx(ref["net"])
            if tp == 1.5:
                assert out["mfe"][i] == pytest.approx(ref["mfe"]) and out["mae"][i] == pytest.approx(ref["mae"])
                tr = trail_window(store, "X", det, entry, trigger=1.0, gap=0.8, sl=3.0, cost=0.225)
                assert tr is not None and out["trail_net"][i] == pytest.approx(tr["net"])
                valid_n += 1
        checked += 1
    assert checked > 100 and valid_n > 100
    # eval_window geçersiz derse vektörel de geçersiz (en az bir boşluklu pencere yakalandı)
    inval = [i for i in range(0, len(filled) - 14, 3)
             if eval_window(*store.d["X"], (ot[i] + 300_000) / 1000.0, float(filled[i, P.COL_C]), 1.5, 60, 3.0, 0.225) is None]
    assert inval and all(out["valid"][i] == 0 for i in inval)
