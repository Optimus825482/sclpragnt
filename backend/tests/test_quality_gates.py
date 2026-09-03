"""Tests for S1 (cost-aware gates) and S2 (strategy circuit breaker)."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class CostAwareGateTests(unittest.TestCase):
    def test_expected_net_gate_source_present(self):
        # The gate must live inside open_position's liquidity block and use
        # the configured floor.
        import pathlib

        src = pathlib.Path(__file__).resolve().parents[1].joinpath("app", "analyzer.py").read_text()
        self.assertIn("expected_net_below_floor", src)
        self.assertIn("MIN_EXPECTED_NET_PNL_TRY", src)


class StrategyCircuitBreakerTests(unittest.TestCase):
    def _breaker(self):
        from app.circuit_breaker import StrategyCircuitBreaker

        return StrategyCircuitBreaker()

    def test_resume_unknown_strategy_returns_false(self):
        b = self._breaker()
        self.assertFalse(asyncio.run(b.resume("NOPE_STRATEGY")))

    def test_pause_blocks_and_resume_clears(self):
        b = self._breaker()
        b._loaded = True  # skip KV load in unit context
        b._paused["TEST_STRAT"] = {"reason": "rolling_expectancy_below_floor"}
        self.assertTrue(b.is_paused("TEST_STRAT"))
        self.assertTrue(asyncio.run(b.resume("TEST_STRAT")))
        self.assertFalse(b.is_paused("TEST_STRAT"))

    def test_evaluate_skips_small_windows(self):
        import app.database as database

        b = self._breaker()
        b._loaded = True

        async def fake_trades(limit=None, strategy=None):
            return [{"pnl": -5.0}] * 3  # fewer than window size

        with patch.object(database, "get_trades", new=fake_trades), \
             patch("app.config.config.STRATEGY_BREAKER_WINDOW", 20, create=True):
            result = asyncio.run(b.evaluate_after_close("PUMP_MONITOR"))
        self.assertIsNone(result)
        self.assertFalse(b.is_paused("PUMP_MONITOR"))

    def test_evaluate_pauses_on_breached_floor(self):
        import app.database as database

        b = self._breaker()
        b._loaded = True
        saved = []

        async def fake_trades(limit=None, strategy=None):
            return [{"pnl": -2.0}] * 20  # expectancy -2.0 < floor

        async def fake_set(key, value):
            saved.append((key, value))

        with patch.object(database, "get_trades", new=fake_trades), \
             patch.object(database, "set_llm_setting", new=fake_set), \
             patch.object(database, "save_signal", new=AsyncMock()), \
             patch("app.config.config.STRATEGY_BREAKER_WINDOW", 20, create=True):
            detail = asyncio.run(b.evaluate_after_close("PUMP_MONITOR"))
        self.assertIsNotNone(detail)
        self.assertTrue(b.is_paused("PUMP_MONITOR"))
        self.assertEqual(detail["reason"], "rolling_expectancy_below_floor")

    def test_analyzer_entry_gate_references_breaker(self):
        # 2026-09-03 kararı: strategy-level pause kapısı giriş engelinden
        # kaldırıldı (pause'lu strateji açabilir); breaker yalnızca kapanış
        # sonrası rolling-expectancy değerlendirmesi için çağrılır.
        import pathlib

        src = pathlib.Path(__file__).resolve().parents[1].joinpath("app", "analyzer.py").read_text()
        self.assertNotIn("strategy_circuit_breaker_paused", src)
        self.assertIn("strategy_breaker.evaluate_after_close", src)


if __name__ == "__main__":
    unittest.main()
