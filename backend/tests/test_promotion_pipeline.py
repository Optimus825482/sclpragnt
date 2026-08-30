"""Tests for S7: point-in-time universe registry + promotion pipeline gates."""
import unittest
from unittest.mock import patch


class UniverseRegistryTests(unittest.TestCase):
    def test_record_and_reconstruct(self):
        import asyncio
        import app.database as database
        from app.universe_registry import record_universe, universe_at

        stored = {}

        async def fake_get(key, default=None):
            return stored.get(key, default)

        async def fake_set(key, value):
            stored[key] = value

        async def flow():
            r1 = await record_universe(["BTCTRY", "ETHTRY"], source="test")
            self.assertTrue(r1["recorded"])
            # Duplicate within 10 min must be skipped.
            r2 = await record_universe(["ETHTRY", "BTCTRY"], source="test")
            self.assertFalse(r2["recorded"])
            past = await universe_at(9999999999)
            self.assertEqual(past["symbols"], ["BTC", "ETH"] if False else sorted(["BTCTRY", "ETHTRY"]) or [])

        with patch.object(database, "get_llm_setting", new=fake_get), \
             patch.object(database, "set_llm_setting", new=fake_set):
            asyncio.run(flow())

    def test_universe_at_empty_history(self):
        import asyncio
        import app.database as database
        from app.universe_registry import universe_at

        async def fake_get(key, default=None):
            return default

        async def flow():
            result = await universe_at(time_now())
            self.assertEqual(result["symbols"], [])

        with patch.object(database, "get_llm_setting", new=fake_get):
            asyncio.run(flow())


def time_now():
    import time
    return time.time()


class PromotionPipelineTests(unittest.TestCase):
    def _pipeline(self):
        from app.promotion import PromotionPipeline

        return PromotionPipeline()

    def _run(self, coro):
        return asyncio_run(coro)

    def test_full_gated_lifecycle(self):
        import app.database as database

        b = self._pipeline()
        saved = {}

        async def fake_set(key, value):
            saved[key] = value

        async def flow():
            await b.register("NEW_STRAT", stage="shadow")
            # Gate 1: shadow observations insufficient -> refused.
            r = await b.promote("NEW_STRAT", shadow_observations=10)
            self.assertFalse(r["advanced"])
            # Gate 1 pass.
            r = await b.promote("NEW_STRAT", shadow_observations=200)
            self.assertTrue(r["advanced"])
            self.assertEqual(r["to"], "walk_forward")
            # Gate 2: WF not passed -> refused.
            r = await b.promote("NEW_STRAT", walk_forward_pass=False)
            self.assertFalse(r["advanced"])
            # Gate 2 pass.
            r = await b.promote("NEW_STRAT", walk_forward_pass=True)
            self.assertTrue(r["advanced"])
            self.assertEqual(r["to"], "paper_candidate")
            # Gate 3: paper evidence thin -> refused even WITH human approval.
            r = await b.promote("NEW_STRAT", paper_trades=5,
                                paper_expectancy=0.4, human_approved=True)
            self.assertFalse(r["advanced"])
            # Gate 3: evidence ok but NO human approval -> refused (policy).
            r = await b.promote("NEW_STRAT", paper_trades=30,
                                paper_expectancy=0.4, human_approved=False)
            self.assertFalse(r["advanced"])
            self.assertIn("insan onayı", r["reason"])
            # Gate 3 full pass.
            r = await b.promote("NEW_STRAT", paper_trades=30,
                                paper_expectancy=0.4, human_approved=True)
            self.assertTrue(r["advanced"])
            self.assertEqual(r["to"], "active")

        async def fake_get(key, default=None):
            return default

        with patch.object(database, "get_llm_setting", new=fake_get), \
             patch.object(database, "set_llm_setting", new=fake_set):
            self._run(flow())
        self.assertEqual(b.stage_of("NEW_STRAT"), "active")


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
