"""`app.rescan.exit_sim` — gerçekçi doluşlu çıkış simülatörü: doluş sırası, boşluk, ücret/kayma, izleyen stop, ATR, pencere yardımcıları."""
from __future__ import annotations

import numpy as np
import pytest

from app.rescan import exit_sim as X

FEE = X.FEE_LEG_PCT / 100.0


def _path(bars, w=20):
    """bars: [(o,h,l,c), ...] → (O,H,L,C) (1, w); kalan barlar son kapanışta düz."""
    b = list(bars)
    while len(b) < w:
        c = b[-1][3]
        b.append((c, c, c, c))
    a = np.array(b, dtype=float)[None, :, :]
    return a[:, :, 0], a[:, :, 1], a[:, :, 2], a[:, :, 3]


def _net(entry, exit_px):
    return ((exit_px * (1 - FEE)) / (entry * (1 + FEE)) - 1) * 100


def test_fixed_tp_fills_at_tp_price_and_fees():
    O, H, L, C = _path([(100, 100.2, 99.9, 100.1), (100.1, 101.6, 100.0, 101.5)])
    spec = X.ExitSpec("t", "fixed", sl=3.0, time_min=20, tp=1.5)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0)
    assert r["reason"][0] == X.R_TP and r["hold"][0] == 2
    assert r["net"][0] == pytest.approx(_net(100.0, 101.5))
    assert r["mfe"][0] == pytest.approx(1.6, abs=1e-9)


def test_entry_slippage_shifts_levels_and_net():
    # kayma %1 → giriş 101; TP girişe göre %1,5 → 102,515
    O, H, L, C = _path([(100, 103, 100, 102)])
    spec = X.ExitSpec("t", "fixed", sl=3.0, time_min=20, tp=1.5)
    r = X.simulate(O, H, L, C, spec, slip_pct=1.0)
    assert r["reason"][0] == X.R_TP
    assert r["net"][0] == pytest.approx(_net(101.0, 101.0 * 1.015))


def test_stop_beats_tp_in_same_bar():
    O, H, L, C = _path([(100, 102, 96, 100)])
    spec = X.ExitSpec("t", "fixed", sl=3.0, time_min=20, tp=1.5)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0)
    assert r["reason"][0] == X.R_SL
    assert r["net"][0] == pytest.approx(_net(100.0, 97.0))


def test_gap_through_stop_fills_at_open_with_slippage():
    O, H, L, C = _path([(100, 100.5, 99.8, 100.2), (95.0, 95.5, 94.0, 94.5)])
    spec = X.ExitSpec("t", "fixed", sl=3.0, time_min=20, tp=1.5)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.15)
    entry = 100.0 * 1.0015
    stop = entry * 0.97
    assert 95.0 < stop
    assert r["reason"][0] == X.R_SL and r["hold"][0] == 2
    assert r["net"][0] == pytest.approx(_net(entry, 95.0 * (1 - 0.0015)))


def test_time_stop_exits_at_last_close_with_slippage():
    O, H, L, C = _path([(100, 100.3, 99.9, 100.1)] * 1 + [(100.1, 100.4, 99.8, 100.2)] * 4, w=10)
    spec = X.ExitSpec("t", "fixed", sl=3.0, time_min=5, tp=1.5)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.05)
    assert r["reason"][0] == X.R_TIME and r["hold"][0] == 5
    assert r["net"][0] == pytest.approx(_net(100.0 * 1.0005, 100.2 * (1 - 0.0005)))


def test_trailing_activates_then_exits_at_trail_level():
    # tetik %1: bar0 high 101,2 → HWM 101,2, iz 0,8 → stop 100,3904 (bar1'den geçerli); bar1 low 100,3 → stop vurulur
    O, H, L, C = _path([(100, 101.2, 99.9, 101.0), (101.0, 101.1, 100.3, 100.5)])
    spec = X.ExitSpec("t", "trail", sl=3.0, time_min=20, act=1.0, gap=0.8)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0)
    stop = 101.2 * (1 - 0.008)
    assert r["reason"][0] == X.R_TRAIL and r["hold"][0] == 2
    assert r["net"][0] == pytest.approx(_net(100.0, stop))


def test_stop_checked_before_hwm_update_inside_bar():
    # bar0: yüksek 102 (HWM→102 ama stop bar1'den geçerli), düşük 99,5 (eski stop 97 → vurulmaz).
    # Yeni iz stopu 102·0,992 = 101,184; aynı bar içinde düşük 99,5 < 101,184 olsa da bar0'da stop vurulmamalı.
    O, H, L, C = _path([(100, 102, 99.5, 101.9), (101.9, 102.1, 101.0, 101.5)])
    spec = X.ExitSpec("t", "trail", sl=3.0, time_min=20, act=1.0, gap=0.8)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0)
    assert r["hold"][0] == 2                           # bar0'da çıkmadı, bar1'de çıktı
    assert r["net"][0] == pytest.approx(_net(100.0, 102.0 * 0.992))


def test_trailing_gap_down_fills_at_open():
    O, H, L, C = _path([(100, 102, 99.9, 101.9), (100.0, 100.4, 99.0, 99.5)])
    spec = X.ExitSpec("t", "trail", sl=3.0, time_min=20, act=1.0, gap=0.8)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0)
    assert r["net"][0] == pytest.approx(_net(100.0, 100.0))   # stop 101,18 > açılış 100 → açılıştan


def test_trailing_not_activated_below_trigger():
    O, H, L, C = _path([(100, 100.8, 99.9, 100.6), (100.6, 100.7, 99.0, 99.2)])
    spec = X.ExitSpec("t", "trail", sl=3.0, time_min=3, act=1.0, gap=0.4)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0)
    assert r["reason"][0] == X.R_TIME                         # tetik görülmedi, SL (97) de vurulmadı


def test_breakeven_moves_stop_to_entry():
    O, H, L, C = _path([(100, 100.8, 99.9, 100.7), (100.7, 100.7, 99.9, 100.0)])
    spec = X.ExitSpec("t", "be", sl=3.0, time_min=20, tp=1.5, be=0.6)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0)
    assert r["reason"][0] == X.R_BE
    assert r["net"][0] == pytest.approx(_net(100.0, 100.0))


def test_atr_trailing_uses_per_trade_gap():
    O1, H1, L1, C1 = _path([(100, 102, 99.9, 101.9), (101.9, 102.0, 100.0, 100.5)])
    O = np.vstack([O1, O1]); H = np.vstack([H1, H1]); L = np.vstack([L1, L1]); C = np.vstack([C1, C1])
    spec = X.ExitSpec("t", "atr", sl=3.0, time_min=20, act=1.0, atr_k=1.0)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0, atr_pct=np.array([0.5, 3.0]))
    # iz %0,5 → stop 101,49 → bar1'de vurulur; iz %3 → stop 98,94 → vurulmaz (zaman stopu)
    assert r["reason"][0] == X.R_TRAIL and r["net"][0] == pytest.approx(_net(100.0, 102.0 * 0.995))
    assert r["reason"][1] == X.R_TIME


def test_candidate_target_and_fallback():
    O1, H1, L1, C1 = _path([(100, 104.5, 99.9, 104.0)])
    O = np.vstack([O1, O1]); H = np.vstack([H1, H1]); L = np.vstack([L1, L1]); C = np.vstack([C1, C1])
    spec = X.ExitSpec("t", "fixed", sl=3.0, time_min=20, tp_cand=True, tp_fallback=5.0)
    r = X.simulate(O, H, L, C, spec, slip_pct=0.0, tp_cand_pct=np.array([4.0, np.nan]))
    assert r["reason"][0] == X.R_TP and r["reason"][1] == X.R_TIME      # 2. işlemde hedef yok → yedek %5 görülmedi


def test_vectorised_matches_single_runs():
    rng = np.random.default_rng(3)
    n, w = 200, 60
    steps = rng.normal(0, 0.25, (n, w))
    close = 100 * np.exp(np.cumsum(steps, axis=1) / 100)
    open_ = np.concatenate([np.full((n, 1), 100.0), close[:, :-1]], axis=1)
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, (n, w))))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, (n, w))))
    for spec in X.default_grid()[::7]:
        full = X.simulate(open_, high, low, close, spec, slip_pct=0.15, tp_cand_pct=np.full(n, 2.5), atr_pct=np.full(n, 0.8))
        for k in (0, 17, 101):
            one = X.simulate(open_[k:k + 1], high[k:k + 1], low[k:k + 1], close[k:k + 1], spec, slip_pct=0.15,
                             tp_cand_pct=np.array([2.5]), atr_pct=np.array([0.8]))
            assert full["net"][k] == pytest.approx(one["net"][0]) and full["reason"][k] == one["reason"][0]


def test_default_grid_size_and_unique():
    g = X.default_grid()
    assert len(g) <= 70 and len({s.name for s in g}) == len(g)
    assert {s.family for s in g} == {"fixed", "trail", "atr", "be", "be_trail"}
    assert {s.time_min for s in g} == {30, 60, 120}


def test_entry_index_and_gather_windows_flat_fill():
    ot = np.array([0, 60_000, 120_000, 240_000, 300_000, 360_000], dtype=np.int64)   # 180_000 eksik
    o = np.array([10., 11., 12., 14., 15., 16.]); c = o + 0.5; h = c + 0.2; l = o - 0.2
    idx, ok = X.entry_index(ot, np.array([30_000, 61_000, 10_000_000]), delay_s=0)
    assert list(idx[:2]) == [1, 2] and ok[:2].all() and not ok[2]
    O, H, L, C, ref, cov = X.gather_windows(ot, o, h, l, c, np.array([1]), 4)
    assert ref[0] == 11.0
    # pencere: 60k, 120k, 180k(eksik → önceki kapanış 12,5 ile düz), 240k
    assert O[0, 2] == pytest.approx(12.5 / 11.0) and H[0, 2] == L[0, 2] == C[0, 2]
    assert O[0, 3] == pytest.approx(14.0 / 11.0) and cov[0]
    _, _, _, _, _, cov2 = X.gather_windows(ot, o, h, l, c, np.array([4]), 4)
    assert not cov2[0]


def test_atr_pct_at_constant_range_and_causality():
    n = 60
    ot = np.arange(n, dtype=np.int64) * 300_000
    c = np.full(n, 100.0); h = c * 1.01; l = c * 0.99
    t = np.array([ot[40] + 300_000, ot[5] + 300_000])
    a = X.atr_pct_at(ot, h, l, c, t)
    assert a[0] == pytest.approx(2.0) and np.isnan(a[1])
    # t'den sonra kapanacak bar kullanılmaz: bar 40 t'de henüz kapanmadı
    h2 = h.copy(); h2[40] = 200.0
    assert X.atr_pct_at(ot, h2, l, c, np.array([ot[40] + 100_000]))[0] == pytest.approx(2.0)


def test_cluster_se_and_trade_stats():
    x = np.array([1.0, 1.0, -1.0, -1.0])
    iid = X.cluster_se(x, np.arange(4))
    assert iid == pytest.approx(0.5)                                  # √(4)/4
    assert X.cluster_se(x, np.array([0, 0, 1, 1])) == pytest.approx(np.sqrt(8) / 4)   # küme toplamları ±2... d=x → (2²+(-2)²)=8
    st = X.trade_stats(x, np.arange(4), reason=np.array([0, 0, 1, 1]), hold=np.array([1, 2, 3, 4]))
    assert st["n"] == 4 and st["mean"] == 0.0 and st["win"] == 0.5 and st["avg_win"] == 1.0 and st["avg_loss"] == -1.0
    assert st["mix"][0] == 0.5 and st["mix"][1] == 0.5 and st["hold"] == 2.5


def test_diff_stats():
    a = {"n": 10, "mean": 0.5, "se": 0.3}; b = {"n": 10, "mean": 0.1, "se": 0.4}
    d = X.diff_stats(a, b)
    assert d["diff"] == pytest.approx(0.4) and d["se"] == pytest.approx(0.5) and d["lo"] < 0.4 < d["hi"]
    assert X.diff_stats({}, b) == {}


def test_time_major_equals_default_layout():
    rng = np.random.default_rng(5)
    n, w = 50, 40
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.2, (n, w)), axis=1) / 100)
    open_ = np.concatenate([np.full((n, 1), 100.0), close[:, :-1]], axis=1)
    high = np.maximum(open_, close) * 1.001; low = np.minimum(open_, close) * 0.999
    spec = X.ExitSpec("t", "trail", sl=1.5, time_min=40, act=0.5, gap=0.4)
    a = X.simulate(open_, high, low, close, spec, slip_pct=0.05)
    b = X.simulate(open_.T.copy(), high.T.copy(), low.T.copy(), close.T.copy(), spec, slip_pct=0.05, time_major=True)
    assert np.allclose(a["net"], b["net"]) and (a["reason"] == b["reason"]).all()


def _ref_one(o, h, l, c, spec, slip, tp_cand, atr):
    """Spesifikasyondan bağımsız, düz Python döngüsüyle referans (tek işlem)."""
    s = slip / 100.0
    entry = o[0] * (1 + s)
    stop = entry * (1 - spec.sl / 100)
    tp = None
    if spec.tp_cand:
        tp = tp_cand if (tp_cand == tp_cand and tp_cand > 0) else spec.tp_fallback
    elif spec.tp is not None:
        tp = spec.tp
    tp_px = entry * (1 + tp / 100) if tp is not None else None
    gap = spec.gap if spec.family in ("trail", "be_trail") else (spec.atr_k * atr if spec.family == "atr" else None)
    hwm = entry
    for i in range(min(spec.time_min, len(o))):
        if l[i] <= stop:
            return min(stop, o[i]) * (1 - s), i + 1, entry
        if tp_px is not None and h[i] >= tp_px:
            return tp_px, i + 1, entry
        hwm = max(hwm, h[i])
        if spec.be is not None and hwm >= entry * (1 + spec.be / 100):
            stop = max(stop, entry)
        if gap is not None and spec.act is not None and hwm >= entry * (1 + spec.act / 100):
            stop = max(stop, hwm * (1 - gap / 100))
    n = min(spec.time_min, len(o))
    return c[n - 1] * (1 - s), n, entry


def test_matches_scalar_reference_on_random_paths_all_cells():
    rng = np.random.default_rng(11)
    n, w = 120, 120
    vol = rng.uniform(0.05, 0.6, (n, 1))
    steps = rng.normal(0, 1, (n, w)) * vol
    close = 100 * np.exp(np.cumsum(steps, axis=1) / 100)
    open_ = np.concatenate([np.full((n, 1), 100.0), close[:, :-1]], axis=1) * (1 + rng.normal(0, 0.0005, (n, w)))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.0015, (n, w))))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.0015, (n, w))))
    tp_c = rng.choice([1.0, 2.5, 4.0, np.nan], n)
    atr = rng.uniform(0.2, 1.5, n)
    f = X.FEE_LEG_PCT / 100
    for spec in X.default_grid():
        for slip in (0.05, 0.15):
            r = X.simulate(open_, high, low, close, spec, slip_pct=slip, tp_cand_pct=tp_c, atr_pct=atr)
            for k in range(0, n, 7):
                px, hold, entry = _ref_one(open_[k], high[k], low[k], close[k], spec, slip, tp_c[k], atr[k])
                ref_net = ((px * (1 - f)) / (entry * (1 + f)) - 1) * 100
                assert r["net"][k] == pytest.approx(ref_net, abs=1e-9), (spec.name, slip, k)
                assert r["hold"][k] == hold, (spec.name, slip, k)
