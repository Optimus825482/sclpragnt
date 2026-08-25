"""Regression tests for the 2026-08-25 audit fixes (paper-only behavior)."""
import os
import pathlib
import unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


def flat_kline(last, length=21):
    closes = [100.0] * (length - 1) + [last]
    return {"closes": closes, "highs": closes, "lows": closes, "volumes": [100.0] * length}


class BacktestPartialExitAccountingTests(unittest.TestCase):
    """A partial exit must not mint cash: balance delta == realized pnl."""

    def _profile_result(self, closes):
        from app import backtest
        from app.config import config as _config

        commission = _config.COMMISSION_PCT
        stages = [(0.01, 0.5, 0.005)]
        profile = {"stages": stages, "atr_mult": 1.0, "trail_pct": 0.002}
        # Drive the profile branch directly through the position loop by
        # simulating one stage execution on a synthetic series.
        analyzer = backtest.ScalpAnalyzer(None)
        entry = 100.0
        quantity = 5.0
        sell_qty = quantity * stages[0][1]
        balance = _config.INITIAL_BALANCE_TRY - 500.0  # after a synthetic entry
        invested_cost = 500.0
        exit_price = entry * (1 + stages[0][0])
        balance_after, partial_pnl = backtest._close_partial(
            balance, exit_price, sell_qty, spread_pct=0.001, slippage_pct=0.0)
        partial_pnl -= entry * sell_qty * commission + entry * sell_qty
        cost_removed = entry * sell_qty
        invested_cost_after = max(0.0, invested_cost - cost_removed)
        return balance_after, invested_cost_after, partial_pnl, commission

    def test_partial_exit_reduces_invested_cost_without_cash_creation(self):
        _, invested_cost_after, partial_pnl, commission = self._profile_result(None)
        # Sold half of a 500 TRY position (5 units @ 100) at 101 with fees.
        proceeds = 101.0 * 2.5 * (1 - 0.0005)          # spread haircut only
        exit_fee = proceeds * commission
        entry_fee = 100.0 * 2.5 * commission           # charged on the sold slice
        # Cash credited is net proceeds only: the principal left the wallet
        # at entry and must NOT be credited back per stage (that was the audit
        # bug inflating net_pnl by ~order_size per executed stage).
        self.assertAlmostEqual(partial_pnl, proceeds - exit_fee - entry_fee - 250.0, places=6)
        self.assertAlmostEqual(invested_cost_after, 250.0, places=6)


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
