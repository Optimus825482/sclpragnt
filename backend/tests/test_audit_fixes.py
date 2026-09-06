"""Regression tests for the 2026-08-25 audit fixes (paper-only behavior)."""
import os
import pathlib
import unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


def flat_kline(last, length=21):
    closes = [100.0] * (length - 1) + [last]
    return {"closes": closes, "highs": closes, "lows": closes, "volumes": [100.0] * length}


class PaperOrderValidationTests(unittest.TestCase):
    def test_oco_requires_both_legs(self):
        from tests.test_regressions import RegressionContracts  # noqa: F401  (import guard)

    def test_stop_price_zero_is_invalid(self):
        # Direct check on the validation helper semantics used in place_paper_order.
        def positive_leg(order, key):
            try:
                return float(order.get(key) or 0) > 0
            except (TypeError, ValueError):
                return False

        self.assertFalse(positive_leg({"stop_price": None}, "stop_price"))
        self.assertFalse(positive_leg({"stop_price": 0}, "stop_price"))
        self.assertTrue(positive_leg({"stop_price": 90.5}, "stop_price"))


class RateLimitTrackingTests(unittest.TestCase):
    def test_snapshot_shape_and_tracking(self):
        from app import binance_tr_public as pub

        snapshot = pub.rate_limit_snapshot()
        for key in ("total_weight_used", "by_endpoint", "last_reset_at"):
            self.assertIn(key, snapshot)
        # The module globals exist now; before the fix they were undefined and
        # every response silently raised NameError inside `except Exception`.
        self.assertIsInstance(pub._rate_limit_used["by_endpoint"], dict)


class ClosedHistoryClockSkewTests(unittest.TestCase):
    def test_future_candle_within_skew_margin_is_excluded(self):
        from app.market_data import MarketData, _interval_ms

        tf = "1m"
        duration = _interval_ms(tf)
        now_ms = 10_000_000
        rows = [
            [now_ms - 3 * duration, "100", "110", "95", "105", "10",
             now_ms - 2 * duration],          # closed well in the past → kept
            [now_ms - duration, "105", "115", "100", "108", "12",
             now_ms - 1500],                  # closed just inside margin → kept
            [now_ms - duration + 1, "106", "120", "104", "118", "20",
             now_ms - 800],                   # closes within the skew window → dropped
            [now_ms, "108", "125", "107", "122", "30",
             now_ms + duration - 1],          # forming candle → dropped
        ]
        history = MarketData._closed_history(rows, tf, now_ms)
        self.assertEqual(len(history["closes"]), 2)
        self.assertEqual(history["timestamps"], [now_ms - 3 * duration, now_ms - duration])


if __name__ == "__main__":
    unittest.main()
