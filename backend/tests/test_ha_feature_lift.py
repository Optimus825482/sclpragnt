"""scripts/ha_feature_lift.py saf yardımcıları — bayrak, ATR, vektörel çıkış değerlendirmesi (skaler kaynakla birebir)."""
import numpy as np
import pytest

from app.rescan.series import bar_features
from scripts import ha_feature_lift as F
from scripts.notification_outcomes_report import CandleStore, eval_window
from scripts.strategy_rescan import trail_window

BAR = 300_000


def _series(n=400, seed=0, gap_at=None):
    """7 kolonlu 5m dizi (ot, o, h, l, c, v, qv); isteğe bağlı bar boşluğu."""
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.01, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.01, n))
    ot = np.arange(n, dtype=float) * BAR + 1_700_000_000_000
    arr = np.column_stack([ot, o, h, l, c, rng.uniform(1, 5, n), rng.uniform(1e5, 1e6, n)])
    if gap_at is not None:
        arr = np.delete(arr, slice(gap_at, gap_at + 4), axis=0)
    return arr


# ---------------------------------------------------------------- bayrak
def test_flag_prior_signal_window_and_lead():
    m = 60_000
    ticks = np.array([100 * m, 200 * m, 1000 * m, 5 * m])
    sig = np.array([90 * m, 50 * m, 150 * m, 1000 * m])
    flag, lead = F.flag_prior_signal(ticks, sig, 90 * m)
    # 100: son sinyal 90 → 10 dk; 200: son 150 → 50 dk; 1000: sinyal tam tick'te → 0 dk; 5: öncesinde sinyal yok
    assert flag.tolist() == [True, True, True, False]
    assert lead[:3].tolist() == [10.0, 50.0, 0.0] and np.isnan(lead[3])
    flag2, _ = F.flag_prior_signal(ticks, sig, 30 * m)
    assert flag2.tolist() == [True, False, True, False]
    f0, l0 = F.flag_prior_signal(ticks, np.zeros(0, np.int64), 90 * m)
    assert not f0.any() and np.isnan(l0).all()


def test_signal_times_are_bar_close_sorted():
    arr = _series(50)
    st = F.signal_times(arr, lambda a, min_quote_24h: np.array([7, 3]), BAR, 0.0)
    assert st.tolist() == [int(arr[3, 0]) + BAR, int(arr[7, 0]) + BAR]
    assert len(F.signal_times(arr, lambda a, min_quote_24h: np.zeros(0, np.int64), BAR, 0.0)) == 0


# ---------------------------------------------------------------- ATR
def test_atr14_pct_matches_series_bar_features():
    arr = _series(120, seed=2)
    nine = np.column_stack([arr, np.zeros(len(arr)), np.zeros(len(arr))])  # close_time, trades yer tutucu
    nine[:, 7] = arr[:, 6]
    ref = bar_features(nine)["atr_pct"]
    got = F.atr14_pct(arr)
    assert np.isnan(got[:14]).all()
    assert np.allclose(got[14:], ref[14:], equal_nan=True)


def test_last_closed_index():
    ot = np.arange(10, dtype=np.int64) * BAR
    assert F.last_closed_index(ot, [5 * BAR, 5 * BAR + 1, 4 * BAR + 1, 0], BAR).tolist() == [4, 4, 3, -1]


# ---------------------------------------------------------------- vektörel çıkış == skaler kaynak
@pytest.mark.parametrize("gap_at", [None, 230])
def test_exit_fixed_matches_eval_window(gap_at):
    arr = _series(400, seed=5, gap_at=gap_at)
    ot, hi, lo, cl = arr[:, 0], arr[:, 2], arr[:, 3], arr[:, 4]
    rng = np.random.default_rng(1)
    ticks = (ot[rng.integers(20, 390, 60)] + BAR).astype(np.int64)  # bar kapanışı = sonraki bar açılışı
    ticks = np.r_[ticks, int(ot[-3]) + BAR, int(ot[-1]) + BAR]       # pencere sonu: kapsam yetersiz
    entry = cl[np.searchsorted(ot, ticks - BAR, side="right") - 1]
    tp = rng.uniform(0.3, 3.0, len(ticks)); sl = 3.0; cost = 0.225
    win = F.build_windows(ot, hi, lo, cl, ticks)
    for H in (15, 60):
        ok, inH = F.horizon_mask(win["ot"], ticks, H)
        ref = [eval_window(ot, hi, lo, cl, t / 1000.0, e, p, H, sl, cost) for t, e, p in zip(ticks, entry, tp)]
        assert ok.tolist() == [r is not None for r in ref]
        sel = np.flatnonzero(ok)
        got = F.exit_fixed({k: v[sel] for k, v in win.items()}, inH[sel], entry[sel], tp[sel], sl, cost)
        for j, i in enumerate(sel):
            assert got["net"][j] == pytest.approx(ref[i]["net"])
            assert bool(got["hit"][j]) == ref[i]["hit"]
            assert got["mfe"][j] == pytest.approx(ref[i]["mfe"]) and got["mae"][j] == pytest.approx(ref[i]["mae"])


def test_exit_fixed_same_bar_tp_and_sl_counts_as_sl():
    ot = np.arange(5, dtype=float) * BAR
    hi = np.array([100, 110, 100, 100, 100.0]); lo = np.array([100, 90, 100, 100, 100.0]); cl = np.full(5, 100.0)
    win = F.build_windows(ot, hi, lo, cl, np.array([0]))  # tick = 0 → ilk bar index 1
    ok, inH = F.horizon_mask(win["ot"], np.array([0]), 15)
    r = F.exit_fixed(win, inH, [100.0], 2.0, 3.0, 0.0)
    assert ok[0] and r["net"][0] == -3.0 and r["outcome"][0] == -1 and bool(r["hit"][0])


def test_exit_trailing_matches_trail_window():
    arr = _series(400, seed=9)
    ot, hi, lo, cl = arr[:, 0], arr[:, 2], arr[:, 3], arr[:, 4]
    store = CandleStore({"X": (ot, hi, lo, cl)})
    rng = np.random.default_rng(4)
    ticks = (ot[rng.integers(20, 380, 80)] + BAR).astype(np.int64)
    entry = cl[np.searchsorted(ot, ticks - BAR, side="right") - 1]
    win = F.build_windows(ot, hi, lo, cl, ticks)
    ok, inH = F.horizon_mask(win["ot"], ticks, 60)
    assert ok.all()
    for trig, gap, sl in ((1.0, 0.8, 3.0), (0.4, 0.3, 1.0)):
        got = F.exit_trailing(win, inH, entry, trig, gap, sl, 0.225)
        ref = [trail_window(store, "X", t / 1000.0, e, trigger=trig, gap=gap, sl=sl, cost=0.225) for t, e in zip(ticks, entry)]
        assert all(r is not None for r in ref)
        assert np.allclose(got["net"], [r["net"] for r in ref])
    # tetik hiç görülmezse SL ya da ufuk sonu; en az bir senaryoda aktivasyon olmalı
    assert got["activated"].any()


def test_exit_trailing_per_row_atr_parameters_broadcast():
    arr = _series(300, seed=11)
    ot, hi, lo, cl = arr[:, 0], arr[:, 2], arr[:, 3], arr[:, 4]
    ticks = (ot[[30, 60, 90]] + BAR).astype(np.int64)
    entry = cl[[30, 60, 90]]
    win = F.build_windows(ot, hi, lo, cl, ticks)
    ok, inH = F.horizon_mask(win["ot"], ticks, 60)
    per_row = F.exit_trailing(win, inH, entry, np.array([1.0, 2.0, 0.5]), np.array([0.8, 1.6, 0.4]), np.array([3.0, 3.0, 1.0]), 0.0)
    for j, (tr, gp, sl) in enumerate(((1.0, 0.8, 3.0), (2.0, 1.6, 3.0), (0.5, 0.4, 1.0))):
        single = F.exit_trailing({k: v[[j]] for k, v in win.items()}, inH[[j]], entry[[j]], tr, gp, sl, 0.0)
        assert per_row["net"][j] == pytest.approx(single["net"][0])


# ---------------------------------------------------------------- istatistik yardımcıları
def test_cell_stats_and_terciles_and_diff_ci():
    s = F.cell_stats(np.array([1.0, -1.0, 2.0, np.nan]), np.array([True, False, True]))
    assert s["n"] == 3 and s["net"] == pytest.approx(2 / 3) and s["win"] == pytest.approx(2 / 3) and s["hit"] == pytest.approx(2 / 3)
    assert F.cell_stats(np.array([]))["n"] == 0
    assert F.tercile_labels(np.array([1, 2, 3, 4, 5, 6, np.nan])).tolist() == [0, 0, 1, 1, 2, 2, -1]
    lo_, hi_ = F.hit_diff_ci(30, 100, 20, 100)
    assert lo_ < 0.10 < hi_ and F.hit_diff_ci(0, 0, 1, 2) is None
