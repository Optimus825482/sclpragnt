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
