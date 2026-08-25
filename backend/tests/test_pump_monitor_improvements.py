"""Regression tests for PUMP Monitor improvements derived from the
2026-08-25 trade-history analysis (292 trades, -1680 TRY net)."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch


class PumpBreakEvenTests(unittest.TestCase):
    def _make_analyzer(self):
        import os
        import time as _time
        os.environ.setdefault("DB_BACKEND", "sqlite")
        from unittest.mock import MagicMock
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(None)
        analyzer.market = MagicMock()
        analyzer.market.get_ut_kline.return_value = {}
        # Fresh ticker (current ms epoch) so the stale-price guard does not
        # short-circuit the management path.
        analyzer.market.get_ticker.return_value = {"last_price": 100.0, "timestamp": int(_time.time() * 1000)}
        return analyzer

    def test_break_even_arms_at_trigger_and_lifts_stop(self):
        analyzer = self._make_analyzer()
        pos = {"strategy": "PUMP_MONITOR", "entry_price": 100.0, "quantity": 5.0,
               "max_price": 100.6, "min_price": 100.0, "stop_price": 98.8,
               "entry_time": 0.0}
        analyzer.positions["TESTTRY"] = pos

        async def noop(*a, **k):
            raise AssertionError("position must not close while above stop")

        from app.config import config as _config
        net_floor_pct = _config.min_net_exit_pct(500)
        with patch("app.analyzer.config.PUMP_MONITOR_BREAK_EVEN_ENABLED", True), \
             patch("app.analyzer.config.PUMP_MONITOR_BREAK_EVEN_TRIGGER_PCT", 0.005), \
             patch.object(analyzer, "close_position", new=AsyncMock(side_effect=noop)):
            # Price must sit above the lifted BE stop (entry * (1+net_floor)).
            result = asyncio.run(analyzer._manage_open_position("TESTTRY", 100.0 * (1 + net_floor_pct + 0.01), "PUMP_MONITOR"))
        self.assertTrue(pos.get("pump_break_even_armed"))
        expected_floor = 100.0 * (1 + net_floor_pct)
        self.assertGreaterEqual(pos["system_stop_price"], 100.0)
        self.assertLessEqual(pos["system_stop_price"], expected_floor + 1e-9)
        self.assertIsNone(result)

    def test_below_trigger_stop_is_not_moved(self):
        analyzer = self._make_analyzer()
        pos = {"strategy": "PUMP_MONITOR", "entry_price": 100.0, "quantity": 5.0,
               "max_price": 100.2, "min_price": 100.0,
               "entry_time": time.time() - 30}  # fresh entry: no fast-fail yet
        analyzer.positions["TESTTRY"] = pos
        captured = {}

        async def fake_close(symbol, price, reason, commission=0.0):
            captured["reason"] = reason
            return {"action": "CLOSE_POSITION", "symbol": symbol}

        with patch("app.analyzer.config.PUMP_MONITOR_BREAK_EVEN_ENABLED", True), \
             patch("app.analyzer.config.PUMP_MONITOR_BREAK_EVEN_TRIGGER_PCT", 0.005), \
             patch.object(analyzer, "close_position", new=fake_close):
            asyncio.run(analyzer._manage_open_position("TESTTRY", 98.5, "PUMP_MONITOR"))
        self.assertNotIn("pump_break_even_armed", pos)
        # Below the original stop the position closes with the plain reason.
        self.assertEqual(captured.get("reason"), "system_stop_loss")

    def test_armed_stop_closes_with_pump_reason(self):
        analyzer = self._make_analyzer()
        pos = {"strategy": "PUMP_MONITOR", "entry_price": 100.0, "quantity": 5.0,
               "max_price": 101.0, "min_price": 99.0, "system_stop_price": 100.3,
               "pump_break_even_armed": True, "entry_time": 0.0}
        analyzer.positions["TESTTRY"] = pos
        captured = {}

        async def fake_close(symbol, price, reason, commission=0.0):
            captured["reason"] = reason
            return {"action": "CLOSE_POSITION", "symbol": symbol, "reason": reason}

        with patch.object(analyzer, "close_position", new=fake_close), \
             patch.object(analyzer, "_persist_reentry_blocks", new=AsyncMock()):
            result = asyncio.run(analyzer._manage_open_position("TESTTRY", 100.2, "PUMP_MONITOR"))
        self.assertEqual(captured.get("reason"), "pump_break_even_stop")

    def test_fast_fail_exits_early_when_no_progress(self):
        import time as _time
        analyzer = self._make_analyzer()
        pos = {"strategy": "PUMP_MONITOR", "entry_price": 100.0, "quantity": 5.0,
               "max_price": 100.05, "min_price": 100.0,
               "entry_time": _time.time() - 1000}  # well past 15 min
        analyzer.positions["TESTTRY"] = pos
        captured = {}

        async def fake_close(symbol, price, reason, commission=0.0):
            captured["reason"] = reason
            return {"action": "CLOSE_POSITION", "symbol": symbol}

        with patch("app.analyzer.config.PUMP_MONITOR_FAST_FAIL_ENABLED", True), \
             patch("app.analyzer.config.PUMP_MONITOR_FAST_FAIL_SEC", 900), \
             patch("app.analyzer.config.PUMP_MONITOR_FAST_FAIL_MIN_PROGRESS_PCT", 0.003), \
             patch.object(analyzer, "close_position", new=fake_close):
            asyncio.run(analyzer._manage_open_position("TESTTRY", 100.0, "PUMP_MONITOR"))
        self.assertEqual(captured.get("reason"), "pump_fast_fail_no_progress")

    def test_fast_fail_disabled_by_default_after_replay(self):
        # The 48h replay showed fast-fail cutting trades that later reached
        # ATR trailing; the flag must default to off.
        from app.config import config

        self.assertFalse(config.PUMP_MONITOR_FAST_FAIL_ENABLED)


class PumpVolumeChaseFilterTests(unittest.TestCase):
    def test_config_defaults_derived_from_replay(self):
        from app.config import config

        self.assertAlmostEqual(config.PUMP_MONITOR_MAX_ENTRY_VOLUME_RATIO, 2.0)
        self.assertTrue(config.PUMP_MONITOR_BREAK_EVEN_ENABLED)
        # Replay sweep: trigger 0.3% beat 0.5% (-1353 vs -1690 TRY).
        self.assertAlmostEqual(config.PUMP_MONITOR_BREAK_EVEN_TRIGGER_PCT, 0.003)
        self.assertEqual(config.PUMP_MONITOR_FAST_FAIL_SEC, 900)
        self.assertAlmostEqual(config.PUMP_MONITOR_FAST_FAIL_MIN_PROGRESS_PCT, 0.003)


if __name__ == "__main__":
    unittest.main()
