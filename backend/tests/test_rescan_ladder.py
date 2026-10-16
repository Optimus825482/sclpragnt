"""Merdiven yükseliş dedektörü prototipi (app/rescan/ladder.py) — saf birim testleri."""
import numpy as np

from app.rescan import ladder as L


def _arr(closes, lows=None, vols=None, qv=None):
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    lows = np.asarray(lows if lows is not None else closes * 0.995, dtype=float)
    vols = np.asarray(vols if vols is not None else np.ones(n), dtype=float)
    qv = np.asarray(qv if qv is not None else np.full(n, 100_000.0), dtype=float)
    ot = np.arange(n, dtype=float) * L.BAR_MS
    return np.column_stack([ot, closes, closes * 1.005, lows, closes, vols, qv])


def _staircase(n_flat=320, n_up=5, step=0.4):
    base = [100.0 + 0.05 * ((i % 3) - 1) for i in range(n_flat)]  # hafif dalgalı yatay
    last = base[-1]
    ups = [last * (1 + step / 100) ** (k + 1) for k in range(n_up)]
    return base + ups


def test_rsi_wilder_bounds_and_warmup():
    c = np.array(_staircase(), dtype=float)
    r = L.rsi_wilder(c, 14)
    assert np.isnan(r[:14]).all() and np.isfinite(r[14:]).all()
    assert (r[14:] >= 0).all() and (r[14:] <= 100).all()
    assert r[-1] > r[-6]  # merdivende RSI yükselir


def test_run_length_counts_consecutive_higher_close_and_low():
    c = np.array([1, 2, 3, 2.5, 2.6, 2.7, 2.8], dtype=float)
    l = c - 0.1
    run = L.ladder_run_length(c, l)
    assert list(run) == [0, 1, 2, 0, 1, 2, 3]


def test_staircase_triggers_once_with_cooldown_and_flat_does_not():
    closes = _staircase(n_up=6, step=0.4)
    arr = _arr(closes)
    idx = L.ladder_signals(arr, n_bars=3, gain_min=0.8, gain_max=4.0, vol_min=0.0, rsi_max=101.0,
                           min_quote_24h=0.0, cooldown_bars=12)
    assert len(idx) == 1 and idx[0] >= 320  # yalnız merdivende, soğuma tekrarını engeller
    flat = _arr([100.0] * 340)
    assert len(L.ladder_signals(flat, n_bars=3, gain_min=0.8, vol_min=0.0, rsi_max=101.0, min_quote_24h=0.0)) == 0


def test_gates_block_exploded_illiquid_or_overbought():
    closes = _staircase(n_up=6, step=2.0)  # 3 barda ≥ %4.1 → gain_max=4 üstü (yatay tabanın son tiki de sayılır)
    arr = _arr(closes)
    assert len(L.ladder_signals(arr, n_bars=3, gain_min=0.8, gain_max=4.0, vol_min=0.0, rsi_max=101.0, min_quote_24h=0.0)) == 0
    closes = _staircase(n_up=6, step=0.4)
    arr = _arr(closes)
    assert len(L.ladder_signals(arr, n_bars=3, gain_min=0.8, vol_min=0.0, rsi_max=101.0, min_quote_24h=10 ** 12)) == 0
    assert len(L.ladder_signals(arr, n_bars=3, gain_min=0.8, vol_min=0.0, rsi_max=50.0, min_quote_24h=0.0)) == 0


def test_signal_time_is_bar_close():
    arr = _arr([100.0] * 30)
    assert L.signal_time_ms(arr, 3) == 3 * L.BAR_MS + L.BAR_MS
