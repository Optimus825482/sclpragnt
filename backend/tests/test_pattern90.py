"""`scripts.pattern90_study` / `scripts.pattern90_analysis` — kümesizleştirme, bölmeler, cooldown, şans tabanı motoru."""
from __future__ import annotations

import numpy as np
import pytest

from app.rescan import pattern_study as P
from scripts import pattern90_analysis as A
from scripts import pattern90_study as S


def _ev(t0, sym="X"):
    return {"sym": sym, "t0": t0, "t_end": t0 + 1_800_000}


def test_declusterize_flags_market_wide_buckets_only():
    t = 1_790_000_100_000
    t = t - t % 300_000
    events = [_ev(t, f"S{i}") for i in range(10)]                       # 10 > 8 → küme
    events += [_ev(t + 3_600_000, f"S{i}") for i in range(3)]           # 3 olay: küme değil
    events += [_ev(t + 7_200_000, "S0")]
    info = S.declusterize(events, seed=1)
    big = [e for e in events if e["t0"] == t]
    assert all(e["bucket_n"] == 10 and e["cluster"] for e in big)
    assert sum(e["keep"] for e in big) == 1                              # kümede tek olay kalır
    small = [e for e in events if e["t0"] == t + 3_600_000]
    assert all(e["keep"] for e in small) and sum(e["keep_b"] for e in small) == 1   # her-kovada-tek varyantı
    assert info["keep_a"] == 1 + 3 + 1 and info["keep_b"] == 3 and info["n_cluster_buckets"] == 1
    # tohum aynı → seçim aynı
    again = [_ev(t, f"S{i}") for i in range(10)] + [_ev(t + 3_600_000, f"S{i}") for i in range(3)] + [_ev(t + 7_200_000, "S0")]
    S.declusterize(again, seed=1)
    assert [e["keep"] for e in again] == [e["keep"] for e in events]


def test_cooldown_and_intervals():
    idx = np.array([3, 5, 14, 15, 27, 40])
    assert list(A.cooldown_idx(idx, 12)) == [3, 15, 27, 40]
    assert list(A.cooldown_idx(np.array([], dtype=int), 12)) == []
    t = np.array([5, 10, 15, 20])
    assert list(A.in_iv(t, [(6, 15), (20, 30)])) == [False, True, True, True]
    assert A.iv_days([(0, S.DAY_MS * 2)], 0, S.DAY_MS) == pytest.approx(1.0)


def test_sets_partition_and_ordering():
    end = S.parse_day("2026-10-17", end=True)
    sets, blocks = A.make_sets(end)
    a, b = sets["A"], sets["B"]
    assert a["train"][0][0] == S.parse_day("2026-10-12") and b["train"][0][0] == S.parse_day("2026-10-02")
    assert a["test"][0][1] < a["train"][0][0] and b["test"][0][1] < b["train"][0][0]          # test zamanda geriye
    assert a["test"][0][0] == b["test"][0][0] == S.parse_day("2026-07-29")                   # 10 günlük ısınma
    for k in ("C1", "C2", "C3"):
        tr, te = sets[k]["train"][0], sets[k]["test"]
        assert len(te) == 2
        assert all(not (lo <= tr[1] and hi >= tr[0]) for lo, hi in te)                       # eğitim ile test ayrık
    b1, b2, b3 = blocks["blk1"][0], blocks["blk2"][0], blocks["blk3"][0]
    assert b1[1] + 1 == b2[0] and b2[1] + 1 == b3[0]
    assert round((b1[1] + 1 - b1[0]) / S.DAY_MS) == 30 and round((b2[1] + 1 - b2[0]) / S.DAY_MS) == 30


def test_day_label_roundtrip():
    ms = S.parse_day("2026-09-03") + 5 * 3_600_000
    assert S.day_label(int(S.day_idx(ms))) == "2026-09-03"


def _write_grid(tmp_path, sym, n=3000, seed=0):
    rng = np.random.default_rng(seed)
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    ot = 1_790_000_100_000 - (1_790_000_100_000 % 300_000) + np.arange(n) * 300_000
    f5 = np.column_stack([ot, o, h, l, c, np.full(n, 5.0), np.full(n, 50.0), np.full(n, 2.0), np.full(n, 20.0)])
    real = np.ones(n, dtype=bool)
    on = P.forward_outcomes(f5[:, 2], f5[:, 3], f5[:, 4], real, tps=(1.5, 4.0), first=1, last=12)
    g = tmp_path / "grid"
    g.mkdir(exist_ok=True)
    np.save(g / f"F5_{sym}.npy", f5)
    np.save(g / f"OT_{sym}.npy", ot.astype(np.int64))
    np.save(g / f"ON_{sym}.npy", np.column_stack([on["valid"], on["hit1.5"], on["hit4.0"], on["net1.5"], on["trail_net"]]).astype(np.float32))
    return ot, on


def test_null_engine_zero_lift_for_random_signals(tmp_path):
    ot, on = _write_grid(tmp_path, "AAA")
    eng = A.NullEngine(str(tmp_path), ["AAA"])
    rng = np.random.default_rng(3)
    ok = np.flatnonzero((on["valid"] == 1) & (np.arange(len(ot)) > 40) & (np.arange(len(ot)) < len(ot) - 60))
    rows = np.sort(rng.choice(ok, size=600, replace=False))
    t = ot[rows] + 300_000                                  # karar anı = bar kapanışı
    sid = np.zeros(len(rows), dtype=np.int16)
    r = eng.lift(sid, t, np.nan_to_num(on["hit1.5"][rows]), np.nan_to_num(on["hit4.0"][rows]), n_sample=500, seed=1,
                 net15=np.nan_to_num(on["net1.5"][rows]), trail=np.nan_to_num(on["trail_net"][rows]))
    assert r["n"] > 300
    assert abs(r["liftnet"]) < 0.25 and abs(r["lifttr"]) < 0.25 and r["nullnet"] < 0     # net: rastgele anlarda şans farkı ≈ 0
    assert abs(r["lift15"]) < 0.06 and abs(r["lift4"]) < 0.04       # rastgele anlar → şans farkı ≈ 0
    assert 0.0 < r["null15"] < 1.0
    # sinyal hep "isabet" ise lift = 1 − null
    r1 = eng.lift(sid, t, np.ones(len(rows)), np.ones(len(rows)), n_sample=300, seed=1)
    assert r1["lift15"] == pytest.approx(1.0 - r1["null15"])
    assert eng.lift(sid[:10], t[:10], np.ones(10), np.ones(10), n_sample=10, seed=1) == {"n": 0}


def test_rank_cell_marks_signal_and_ignores_noise_in_taker_family():
    rng = np.random.default_rng(2)
    n1, n0 = 150, 3000
    y = np.r_[np.ones(n1), np.zeros(n0)]
    names = ["5m.sig", "5m.noise", "5m.tk_share3", "1m.tk_net6"]
    X = np.column_stack([np.r_[rng.normal(1.5, 1, n1), rng.normal(0, 1, n0)], rng.normal(size=n1 + n0),
                         np.r_[rng.normal(0.8, 1, n1), rng.normal(0, 1, n0)], rng.normal(size=n1 + n0)])
    strata = rng.integers(0, 20, size=n1 + n0)
    recs, meta = A.rank_cell(X, y, strata, names, n_perm=60, seed=0, stratified=False)
    by = {r["feature"]: r for r in recs}
    assert by["5m.sig"]["rank_all"] == 1 and by["5m.sig"]["sig_all"] and by["5m.sig"]["sig_base"]
    assert by["5m.tk_share3"]["tk"] and by["5m.tk_share3"]["rank_base"] == -1 and by["5m.tk_share3"]["sig_base"] is None
    assert by["5m.tk_share3"]["sig_all"] and not by["1m.tk_net6"]["sig_all"] and not by["5m.noise"]["sig_all"]
    assert meta["n_taker"] == 2 and meta["thr_all"] >= meta["thr_base"] - 1e-9
