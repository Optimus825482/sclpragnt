"""Regression tests for the 2026-09-12 indicator audit fixes (C-01, C-02, C-04, C-09, C-12).

Each test pins the *measured* wrong behaviour it replaces, so a silent revert
fails loudly instead of quietly restoring the old number.
"""
import math
import time
import unittest

import numpy as np

from app.technical_analysis import (
    _historical_volatility, _periods_per_day, _pivots, _rsi, _rsi_series,
    _signal, _stoch_rsi, _stochastic, calculate_snapshot,
)


def _series(n=120):
    """Deterministic, non-monotonic OHLC series (no randomness, no I/O)."""
    closes = [100.0 + 4.0 * math.sin(i / 7.0) + 1.5 * math.sin(i / 2.3) for i in range(n)]
    highs = [close + 0.6 for close in closes]
    lows = [close - 0.6 for close in closes]
    return highs, lows, closes


def _reference_stochastic(highs, lows, closes, period=14, smooth=3):
    """Textbook slow stochastic: raw %K -> %K = SMA(raw, smooth) -> %D = SMA(%K, smooth)."""
    raw = []
    for i in range(period - 1, len(closes)):
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        raw.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k_series = [float(np.mean(raw[i - smooth + 1:i + 1])) for i in range(smooth - 1, len(raw))]
    return {"k": k_series[-1], "d": float(np.mean(k_series[-smooth:]))}


def _reference_stoch_rsi(closes, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    """The pre-C-12 O(n^2) implementation, kept as a bit-exact oracle."""
    values = [_rsi(closes[:end], rsi_period) for end in range(rsi_period + 1, len(closes) + 1)]
    raw = []
    for i in range(stoch_period - 1, len(values)):
        window = values[i - stoch_period + 1:i + 1]
        lo, hi = min(window), max(window)
        raw.append((values[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    if len(raw) < k_period + d_period - 1:
        return None
    k_values = [float(np.mean(raw[i - k_period + 1:i + 1])) for i in range(k_period - 1, len(raw))]
    return {"k": k_values[-1], "d": float(np.mean(k_values[-d_period:]))}


def _klines(closes, highs, lows, volumes=None):
    return {"opens": list(closes), "highs": list(highs), "lows": list(lows),
            "closes": list(closes), "volumes": volumes or [100.0] * len(closes),
            "timestamps": list(range(len(closes)))}


class PivotLevelsTests(unittest.TestCase):
    """C-01 — R3/S3 lost their `+high` / `+low` term."""

    def test_classic_pivot_values(self):
        pivots = _pivots(105, 95, 100)          # P = 100, H-L = 10
        self.assertAlmostEqual(pivots["R3"], 115.0, places=9)   # 2P - 2L + H
        self.assertAlmostEqual(pivots["S3"], 85.0, places=9)    # 2P - 2H + L
        self.assertAlmostEqual(pivots["R2"], 110.0, places=9)
        self.assertAlmostEqual(pivots["R1"], 105.0, places=9)
        self.assertAlmostEqual(pivots["S1"], 95.0, places=9)
        self.assertAlmostEqual(pivots["S2"], 90.0, places=9)

    def test_levels_are_ordered_and_straddle_the_pivot(self):
        for high, low, close in ((105, 95, 100), (1.05, 0.95, 1.0), (31250.5, 29800.25, 30500.0)):
            p = _pivots(high, low, close)
            with self.subTest(high=high, low=low, close=close):
                self.assertLess(p["R1"], p["R2"])
                self.assertLess(p["R2"], p["R3"])
                self.assertGreater(p["S1"], p["S2"])
                self.assertGreater(p["S2"], p["S3"])
                self.assertGreater(p["R1"], p["P"])
                self.assertLess(p["S1"], p["P"])
                # The broken version put R3 at 2P-2L (10.0) and S3 at 2P-2H (-10.0).
                self.assertGreater(p["R3"], p["R2"])
                self.assertLess(p["S3"], p["S2"])


class WilliamsRSignalTests(unittest.TestCase):
    """C-02 — %R is negative; the old call read the ladder backwards."""

    def test_overbought_is_sell_and_oversold_is_buy(self):
        # Production call shape (technical_analysis.py oscillator_signals):
        # the value is negated so `_signal`'s ascending convention matches how
        # %R is conventionally read; bands mirror the -20/-80 and -40/-60 lines.
        self.assertEqual(_signal(-(-10.0), 60, 80, 40, 20), "strong_sell")  # -10 = overbought
        self.assertEqual(_signal(-(-25.0), 60, 80, 40, 20), "sell")         # -25 = overbought side
        self.assertEqual(_signal(-(-45.0), 60, 80, 40, 20), "neutral")
        self.assertEqual(_signal(-(-55.0), 60, 80, 40, 20), "neutral")
        self.assertEqual(_signal(-(-65.0), 60, 80, 40, 20), "buy")          # -65 = oversold side
        self.assertEqual(_signal(-(-90.0), 60, 80, 40, 20), "strong_buy")   # -90 = oversold

    def test_snapshot_signal_follows_the_same_direction(self):
        # Last close pinned to the top of the 14-bar range -> %R ~ 0 (overbought).
        up = [100 + i * 0.5 for i in range(60)]
        snapshot = calculate_snapshot("UP", up[-1], {
            "5m": _klines(up, [c + 0.2 for c in up], [c - 0.2 for c in up]),
            "1d": _klines(up, [c + 0.2 for c in up], [c - 0.2 for c in up])})
        self.assertLessEqual(snapshot["oscillators"]["values"]["williams_r"], 0.0)
        self.assertGreaterEqual(snapshot["oscillators"]["values"]["williams_r"], -100.0)
        self.assertEqual(snapshot["oscillators"]["signals"]["williams_r"], "strong_sell")
        # Last close pinned to the bottom -> %R ~ -100 (oversold).
        down = [100 - i * 0.5 for i in range(60)]
        snapshot = calculate_snapshot("DOWN", down[-1], {
            "5m": _klines(down, [c + 0.2 for c in down], [c - 0.2 for c in down]),
            "1d": _klines(down, [c + 0.2 for c in down], [c - 0.2 for c in down])})
        self.assertEqual(snapshot["oscillators"]["signals"]["williams_r"], "strong_buy")


class StochasticDTests(unittest.TestCase):
    """C-04 — %D used the lagging `values[-6:-3]` window instead of SMA(%K, 3)."""

    def setUp(self):
        self.highs, self.lows, self.closes = _series(120)

    def test_d_matches_the_reference_implementation(self):
        result = _stochastic(self.highs, self.lows, self.closes)
        reference = _reference_stochastic(self.highs, self.lows, self.closes)
        self.assertAlmostEqual(result["d"], reference["d"], places=9)
        self.assertAlmostEqual(result["k"], reference["k"], places=9)

    def test_d_is_the_smoothing_of_k_not_a_lagging_raw_window(self):
        result = _stochastic(self.highs, self.lows, self.closes)
        raw = []
        for i in range(13, len(self.closes)):
            hi = max(self.highs[i - 13:i + 1]); lo = min(self.lows[i - 13:i + 1])
            raw.append((self.closes[i] - lo) / (hi - lo) * 100)
        buggy_d = float(np.mean(raw[-6:-3]))          # the pre-fix formula
        with self.subTest("regression guard"):
            self.assertNotAlmostEqual(result["d"], buggy_d, places=2)
            self.assertGreater(abs(result["d"] - buggy_d), 1.0)
        # %K is unchanged by the fix: still SMA of the last `smooth` raw values.
        self.assertAlmostEqual(result["k"], float(np.mean(raw[-3:])), places=9)


class HistoricalVolatilityTests(unittest.TestCase):
    """C-09 — the annualizer was hardcoded to sqrt(1440) (1-minute bars)."""

    def test_periods_per_day_follows_the_interval(self):
        self.assertEqual(_periods_per_day("1m"), 1440)
        self.assertEqual(_periods_per_day("5m"), 288)
        self.assertEqual(_periods_per_day("15m"), 96)
        self.assertEqual(_periods_per_day("4h"), 6)
        self.assertEqual(_periods_per_day("1d"), 1)
        self.assertIsNone(_periods_per_day(None))
        self.assertIsNone(_periods_per_day("nonsense"))

    def test_annualizer_scales_with_the_bar_interval(self):
        _, _, closes = _series(120)
        hv_1m = _historical_volatility(closes, _periods_per_day("1m"))
        hv_5m = _historical_volatility(closes, _periods_per_day("5m"))
        hv_4h = _historical_volatility(closes, _periods_per_day("4h"))
        self.assertAlmostEqual(hv_1m / hv_5m, math.sqrt(5), places=9)
        self.assertAlmostEqual(hv_1m / hv_4h, math.sqrt(240), places=9)
        # The old value was the 1-minute number regardless of the interval fed in.
        self.assertAlmostEqual(hv_5m, hv_1m / math.sqrt(5), places=9)
        self.assertGreater(hv_1m, hv_5m)
        self.assertGreater(hv_5m, hv_4h)
        self.assertIsNone(_historical_volatility(closes, None))
        self.assertIsNone(_historical_volatility([1.0] * 5, _periods_per_day("5m")))

    def test_snapshot_uses_the_primary_timeframe_interval(self):
        _, _, closes = _series(120)
        highs = [c + 0.6 for c in closes]; lows = [c - 0.6 for c in closes]
        klines = {tf: _klines(closes, highs, lows) for tf in ("1m", "5m", "1d")}
        five = calculate_snapshot("X", closes[-1], klines, primary_timeframe="5m")
        one = calculate_snapshot("X", closes[-1], klines, primary_timeframe="1m")
        self.assertEqual(five["volatility_indicators"]["historical_volatility_bars_per_day"], 288)
        self.assertEqual(one["volatility_indicators"]["historical_volatility_bars_per_day"], 1440)
        self.assertAlmostEqual(
            one["volatility_indicators"]["historical_volatility_20"]
            / five["volatility_indicators"]["historical_volatility_20"],
            math.sqrt(5), places=9)


class StochRsiComplexityTests(unittest.TestCase):
    """C-12 — `_stoch_rsi` recomputed RSI on every prefix (O(n^2))."""

    def _real_series(self, n=600):
        closes, price = [], 100.0
        for i in range(n):
            price *= 1 + 0.004 * math.sin(i / 5.0) + 0.0015 * math.sin(i / 1.7)
            closes.append(price)
        return closes

    def test_rsi_series_matches_prefix_rsi_exactly(self):
        closes = self._real_series(120)
        series = _rsi_series(closes, 14)
        self.assertEqual(len(series), len(closes) - 14)
        for offset, value in enumerate(series):
            self.assertEqual(value, _rsi(closes[:14 + 1 + offset], 14))
        self.assertEqual(_rsi(closes, 14), series[-1])

    def test_stoch_rsi_matches_the_quadratic_reference_exactly(self):
        closes = self._real_series(600)
        self.assertEqual(_stoch_rsi(closes), _reference_stoch_rsi(closes))

    def test_stoch_rsi_is_linear_not_quadratic(self):
        closes = self._real_series(600)
        start = time.perf_counter()
        fast = _stoch_rsi(closes)
        fast_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        slow = _reference_stoch_rsi(closes)
        slow_ms = (time.perf_counter() - start) * 1000
        self.assertEqual(fast, slow)
        # Pre-fix: ~128 ms at n=600. Generous bound so a loaded CI box cannot
        # turn a complexity fix into a flaky failure.
        self.assertLess(fast_ms, 60.0, f"_stoch_rsi took {fast_ms:.1f} ms at n=600")
        self.assertGreater(slow_ms, fast_ms * 2, f"only {slow_ms:.1f} ms vs {fast_ms:.1f} ms")


if __name__ == "__main__":
    unittest.main()
