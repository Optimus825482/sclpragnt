"""app/rescan/confirm_elems.py saf yardımcı birim testleri."""
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rescan import confirm_elems as C  # noqa: E402


def test_wilson_known_values():
    lo, hi = C.wilson_ci(1, 1)
    assert abs(lo - 0.2065) < 5e-3 and hi == 1.0       # n=1 aralığı çok geniş
    lo, hi = C.wilson_ci(50, 100)
    assert abs(lo - 0.4038) < 2e-3 and abs(hi - 0.5962) < 2e-3
    assert all(np.isnan(C.wilson_ci(0, 0)))
    assert C.wilson_ci(0, 20)[0] == 0.0


def test_bh_adjust_monotone_and_nan():
    q = C.bh_adjust([0.01, 0.04, 0.03, np.nan, 0.5])
    assert np.isnan(q[3])
    # sıralı p: .01,.03,.04,.5 (m=4) → ham q: .04,.06,.0533,.5 → sondan kümülatif min: .04,.0533,.0533,.5
    assert abs(q[0] - 0.04) < 1e-9 and abs(q[2] - 0.16 / 3) < 1e-9 and abs(q[1] - 0.16 / 3) < 1e-9
    assert abs(q[4] - 0.5) < 1e-9
    assert np.all(q[np.isfinite(q)] <= 1.0)


def test_lift_stats_simple():
    e = np.array([1, 1, 1, 0, 0, 0, 0, 0], dtype=bool)
    s = np.array([1, 1, 0, 1, 0, 0, 0, 0], dtype=bool)
    r = C.lift_stats(e, s)
    assert r["a"] == 2 and r["b"] == 1 and r["n_e"] == 3
    assert abs(r["p_s"] - 2 / 3) < 1e-12 and abs(r["p_f"] - 1 / 5) < 1e-12
    assert abs(r["lift"] - (2 / 3) / (1 / 5)) < 1e-12
    assert 0.0 <= r["p"] <= 1.0
    # başarısız yoksa lift NaN
    r2 = C.lift_stats(e, np.ones(8, dtype=bool))
    assert np.isnan(r2["lift"])


def test_cluster_bootstrap_mean_brackets_mean():
    rng = np.random.default_rng(3)
    x = rng.normal(0.5, 1.0, 400)
    day = np.repeat(np.arange(20), 20)
    m, lo, hi = C.cluster_bootstrap_mean(x, day, n_boot=500, seed=1)
    assert abs(m - x.mean()) < 1e-12 and lo < m < hi
    assert (hi - lo) < 1.0
    # tek gün → aralık yok
    m1, lo1, hi1 = C.cluster_bootstrap_mean(x[:20], np.zeros(20), n_boot=50)
    assert np.isnan(lo1) and np.isnan(hi1)
    assert all(np.isnan(C.cluster_bootstrap_mean([], [])))


def test_paired_diff_stats_drops_nan_base():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([0.5, np.nan, 2.5, 3.5])
    day = np.array([1, 1, 2, 2])
    r = C.paired_diff_stats(x, b, day)
    assert r["n"] == 3 and abs(r["mean"] - 0.5) < 1e-12
    assert C.paired_diff_stats([1.0], [np.nan], [1])["n"] == 0


def test_rsi_monotone_and_flat():
    up = np.arange(1.0, 101.0)
    r = C.rsi_wilder(up, 14)
    assert np.all(np.isnan(r[:14])) and np.all(r[14:] > 99.9)
    dn = up[::-1].copy()
    assert np.all(C.rsi_wilder(dn, 14)[14:] < 0.1)
    flat = np.full(60, 5.0)
    assert np.all(C.rsi_wilder(flat, 14)[14:] == 50.0)


def test_rsi_alternating_near_50():
    x = 100 + np.tile([1.0, -1.0], 100)
    r = C.rsi_wilder(x, 14)
    assert 40 < r[-1] < 60


def test_mfi_up_down_and_window():
    n = 40
    c = np.arange(1.0, n + 1.0)
    h = c + 0.1
    l = c - 0.1
    v = np.full(n, 10.0)
    m = C.mfi(h, l, c, v, 14)
    assert np.all(np.isnan(m[:14])) and np.all(m[14:] == 100.0)
    m2 = C.mfi(h[::-1], l[::-1], c[::-1], v, 14)
    assert np.all(m2[14:] == 0.0)
    # elle: 15 barlık kısa seri, son pencerede 8 artış (hacim 2) + 6 düşüş (hacim 1)
    tp = np.array([10, 11, 12, 11, 12, 13, 14, 13, 14, 15, 16, 15, 16, 17, 18], dtype=float)
    vol = np.array([1, 2, 2, 1, 2, 2, 2, 1, 2, 2, 2, 1, 2, 2, 2], dtype=float)
    mm = C.mfi(tp, tp, tp, vol, 14)
    flow = tp * vol
    pos = sum(flow[i] for i in range(1, 15) if tp[i] > tp[i - 1])
    neg = sum(flow[i] for i in range(1, 15) if tp[i] < tp[i - 1])
    assert abs(mm[14] - 100.0 * pos / (pos + neg)) < 1e-9


def test_taker_buy_share_window_and_edges():
    qv = np.array([10.0, 10.0, 10.0, 10.0, 10.0])
    tb = np.array([5.0, 5.0, 8.0, 9.0, 10.0])
    r = C.taker_buy_share(qv, tb, np.array([0, 1, 2, 4]), 3)
    assert np.isnan(r[0]) and np.isnan(r[1])
    assert abs(r[2] - 18 / 30) < 1e-12 and abs(r[3] - 27 / 30) < 1e-12
    # sıfır hacim
    assert np.isnan(C.taker_buy_share(np.zeros(5), tb, np.array([4]), 3)[0])


def test_tercile_bucket3():
    x = np.arange(1.0, 10.0)
    e = C.tercile_edges(x)
    b = C.bucket3(np.array([1.0, 5.0, 9.0, np.nan]), e)
    assert list(b) == [0, 1, 2, -1]
    assert all(np.isnan(C.tercile_edges([1.0])))


def test_source_flags_pairs_and_exact():
    f = C.source_flags(("velocity", "jump", "early"))
    assert f["src:velocity"] and f["src:jump"] and f["src:early"] and not f["src:rising"]
    assert f["pair:velocity+jump"] and f["pair:jump+early"] and not f["pair:velocity+rising"]
    assert f["exact:velocity+jump+early"] and sum(1 for k in f if k.startswith("exact:")) == 1


def test_hour_block():
    assert C.hour_block(0).startswith("gece") and C.hour_block(5).startswith("gece")
    assert C.hour_block(6).startswith("sabah") and C.hour_block(14).startswith("öğleden")
    assert C.hour_block(23).startswith("akşam")


def test_search_conjunctions_finds_planted_signal():
    rng = np.random.default_rng(11)
    n = 600
    t = np.arange(n, dtype=float)
    day = (t // 20).astype(int)
    a = rng.random(n) < 0.5
    b = rng.random(n) < 0.5
    noise = rng.random(n) < 0.5
    delta = rng.normal(0, 0.5, n) + np.where(a & b, 0.6, 0.0)
    elems = {"a": a, "b": b, "noise": noise, "na": ~a}
    groups = {"a": "ga", "na": "ga", "b": "gb", "noise": "gn"}
    res = C.search_conjunctions(elems, groups, delta, day, t, min_n=40, max_k=3, top=3)
    assert res, "kararlı birleşim bulunmalı"
    assert set(res[0]["names"]) >= {"a", "b"}
    # aynı gruptan iki öge birleşmez
    for r in res:
        assert not ({"a", "na"} <= set(r["names"]))
    assert res[0]["lcb"] > 0


def test_search_conjunctions_respects_min_n_and_stability():
    n = 200
    t = np.arange(n, dtype=float)
    day = (t // 10).astype(int)
    delta = np.where(t < 100, 1.0, -1.0) + np.random.default_rng(1).normal(0, 0.1, n)   # yalnız ilk yarı pozitif
    e = {"x": np.ones(n, dtype=bool)}
    assert C.search_conjunctions(e, {"x": "g"}, delta, day, t, min_n=20) == []
    tiny = {"y": np.arange(n) < 5}
    assert C.search_conjunctions(tiny, {"y": "g"}, np.ones(n), day, t, min_n=20) == []


def test_search_conjunctions_dedupes_identical_masks():
    rng = np.random.default_rng(5)
    n = 400
    t = np.arange(n, dtype=float)
    day = (t // 20).astype(int)
    a = rng.random(n) < 0.5
    delta = rng.normal(0, 0.4, n) + np.where(a, 0.5, 0.0)
    elems = {"a": a, "a_kopya": a.copy(), "z": rng.random(n) < 0.6}
    groups = {"a": "g1", "a_kopya": "g2", "z": "g3"}
    res = C.search_conjunctions(elems, groups, delta, day, t, min_n=40, max_k=2, top=10)
    keys = [tuple(sorted(r["names"])) for r in res]
    # "a" ile "a_kopya" aynı satırları seçer → yalnız biri raporlanır
    assert not any({"a", "a_kopya"} <= set(k) for k in keys)
    assert sum(1 for k in keys if k in (("a",), ("a_kopya",))) == 1
