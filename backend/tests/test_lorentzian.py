"""app/rescan/lorentzian.py testleri: mesafe, komşu seçimi (elle hesaplı küçük örnek), vektörel == satır satır, nedensellik."""
import numpy as np

from app.rescan import lorentzian as L


def _series(n=900, seed=3):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.004, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    return o, h, l, c


def test_lorentzian_distance():
    a = np.array([0.1, 0.5, 0.9]); b = np.array([0.1, 0.2, 0.4])
    assert abs(float(L.lorentzian_distance(a, b)) - (np.log1p(0.3) + np.log1p(0.5))) < 1e-12
    assert float(L.lorentzian_distance(a, a)) == 0.0
    # satır başına
    A = np.array([[0.0, 0.0], [1.0, 1.0]])
    assert np.allclose(L.lorentzian_distance(A, np.zeros(2)), [0.0, 2 * np.log(2.0)])


def test_labels():
    c = np.array([1, 2, 3, 4, 5, 4, 3, 3, 3, 3, 9.0])
    f = L.labels_future(c)
    assert f[0] == 1 and f[1] == 1 and f[4] == -1 and f[5] == -1 and f[6] == 1 and (f[-4:] == 0).all()
    p = L.labels_pine(c)                       # c[j-4] < c[j] -> -1 (geçmiş yükseliş -> SHORT)
    assert p[4] == -1 and p[:4].tolist() == [0, 0, 0, 0] and p[10] == -1 and p[8] == 1


def test_ann_hand_case_neighbor_selection():
    # tek özellik, k=2, pencere tüm geçmiş, mod4 'none', gecikme 0. t=5 sorgusu x=0,
    # geçmiş j=0..4 değerleri ve etiketler: mesafe d=log1p(|x|)
    x = np.array([[0.5], [0.2], [0.9], [0.4], [0.7], [0.0]], dtype=np.float32)
    y = np.array([1, -1, 1, 1, -1, 0], dtype=np.float32)
    r = L.ann_predict(x, y, lag=1, k=2, window=10, mod4="none", min_hist=1, t_from=5, t_to=6)
    # j=0..4 gezilir (lag=1 -> j<=4): d=[.405,.182,.642,.336,.531]
    # j0 d.405>=-1 ekle -> [.405]; j1 .182<.405 yok; j2 .642>=.405 ekle -> [.405,.642]; j3 .336<.642 yok;
    # j4 .531<.642 yok -> komşular j0, j2 -> etiket 1+1 = 2
    assert r["pred"][5] == 2.0
    # k=2 taşma: 3. ekleme olursa lastDistance = distances[round(1.5)=2]; kaba kuvvetle de aynı olmalı
    bf, dist = L.ann_predict_bruteforce(x, y, 5, lag=1, k=2, window=10, mod4="none")
    assert bf == 2.0 and len(dist) == 2


def test_ann_matches_bruteforce_pine_quirk():
    o, h, l, c = _series()
    F = L.build_features(o, h, l, c)
    y = L.labels_future(c)
    t0, t1 = 700, 712
    r = L.ann_predict(F, y, lag=4, window=300, mod4="pine", min_hist=10, t_from=t0, t_to=t1)
    for t in range(t0, t1):
        bf, _ = L.ann_predict_bruteforce(F, y, t, lag=4, window=300, mod4="pine")
        assert r["pred"][t] == bf, t
    r2 = L.ann_predict(F, y, lag=0, window=300, mod4="eq0", min_hist=10, t_from=t0, t_to=t0 + 4)
    for t in range(t0, t0 + 4):
        bf, _ = L.ann_predict_bruteforce(F, y, t, lag=0, window=300, mod4="eq0")
        assert r2["pred"][t] == bf


def test_truncation_invariance_features_filters_kernel_and_prediction():
    o, h, l, c = _series(900)
    cut = 760
    full = L.lorentzian(o, h, l, c, label_mode="future", window=250, min_hist=50)
    part = L.lorentzian(o[:cut], h[:cut], l[:cut], c[:cut], label_mode="future", window=250, min_hist=50)
    for key in ("feats", "pred", "sig", "filt", "bull", "entry_long"):
        a, b = full[key][:cut], part[key]
        if a.dtype.kind == "f":
            assert np.allclose(a, b, equal_nan=True, atol=1e-5), key
        else:
            assert (a == b).all(), key
    # pine etiket kipi de nedensel
    fp = L.lorentzian(o, h, l, c, label_mode="pine", window=250, min_hist=50)
    pp = L.lorentzian(o[:cut], h[:cut], l[:cut], c[:cut], label_mode="pine", window=250, min_hist=50)
    assert np.allclose(fp["pred"][:cut], pp["pred"], equal_nan=True)


def test_future_label_uses_no_unknown_bars():
    # t anındaki tahmin, t'den SONRAKİ fiyatları değiştirince değişmemeli
    o, h, l, c = _series(800)
    c2 = c.copy(); c2[701:] *= 1.5
    h2 = h.copy(); l2 = l.copy(); o2 = o.copy()
    h2[701:] *= 1.5; l2[701:] *= 1.5; o2[701:] *= 1.5
    a = L.lorentzian(o, h, l, c, label_mode="future", window=250, min_hist=50)
    b = L.lorentzian(o2, h2, l2, c2, label_mode="future", window=250, min_hist=50)
    assert np.allclose(a["pred"][:701], b["pred"][:701], equal_nan=True)


def test_features_in_unit_range_and_filters_boolean():
    o, h, l, c = _series(600)
    F = L.build_features(o, h, l, c)
    fin = F[np.isfinite(F).all(axis=1)]
    assert len(fin) > 400 and fin.min() >= -1e-6 and fin.max() <= 1 + 1e-6
    assert L.filter_volatility(h, l, c).dtype == bool and L.regime_filter((o + h + l + c) / 4, h, l).dtype == bool
    assert L.kernel_bullish(c).dtype == bool


def test_event_label_and_our_features_causal():
    rng = np.random.default_rng(5)
    n = 700
    o, h, l, c = _series(n)
    qv = rng.uniform(1e5, 1e6, n); tbq = qv * rng.uniform(0.3, 0.7, n)
    ev, mfe = L.event_label(o, h)
    assert (ev[-12:] == -1).all() and (ev[:-12] >= 0).all()
    # elle: t=10 için giriş o[11], yüksekler h[11..22]
    assert abs(mfe[10] - (h[11:23].max() / o[11] - 1) * 100) < 1e-4
    F = L.our_features(o, h, l, c, qv, tbq)
    cut = 520
    Fp = L.our_features(o[:cut], h[:cut], l[:cut], c[:cut], qv[:cut], tbq[:cut])
    assert np.allclose(F[:cut], Fp, equal_nan=True, atol=1e-4)
    S = L.causal_squash(F, win=300, min_periods=50)
    Sp = L.causal_squash(Fp, win=300, min_periods=50)
    assert np.allclose(S[:cut], Sp, equal_nan=True, atol=1e-4)
    fin = S[np.isfinite(S).all(axis=1)]
    assert len(fin) > 200 and fin.min() >= 0 and fin.max() <= 1


def test_knn_event_truncation_invariant():
    rng = np.random.default_rng(7)
    n = 800
    o, h, l, c = _series(n)
    qv = rng.uniform(1e5, 1e6, n); tbq = qv * rng.uniform(0.3, 0.7, n)
    F = L.our_features(o, h, l, c, qv, tbq)
    ev, _ = L.event_label(o, h, pct=0.3)
    full = L.knn_event(F, ev, window=300, min_hist=50, win_norm=300)
    cut = 650
    Fp = F[:cut]; evp, _ = L.event_label(o[:cut], h[:cut], pct=0.3)
    part = L.knn_event(Fp, evp, window=300, min_hist=50, win_norm=300)
    assert np.allclose(full["pred"][:cut], part["pred"], equal_nan=True)
