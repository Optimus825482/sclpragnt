import asyncio
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


class MigrationContracts(unittest.TestCase):
    def test_all_durable_tables_are_migrated(self):
        from app import migration_monitor

        spec = importlib.util.spec_from_file_location(
            "migrate_sqlite_to_postgres",
            ROOT / "scripts" / "migrate_sqlite_to_postgres.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        required = {"llm_symbol_guards"}
        self.assertTrue(required.issubset(migration_monitor.TABLES))
        self.assertTrue(required.issubset(module.TABLES))

    def test_count_verification_rejects_missing_target_rows(self):
        from app.migration_monitor import compare_counts

        errors = compare_counts(
            {"llm_symbol_guards": 4},
            {"llm_symbol_guards": 3},
        )
        self.assertEqual(errors, ["llm_symbol_guards: hedef satır sayısı uyuşmuyor (3/4)"])


class EmbeddingWorkerContracts(unittest.IsolatedAsyncioTestCase):
    async def test_worker_refills_from_persistence_beyond_queue_capacity(self):
        from app.embedding_worker import EmbeddingWorker

        class InMemoryWorker(EmbeddingWorker):
            def __init__(self):
                super().__init__(max_queue=2, poll_interval=0.01)
                self.pending = [
                    {"job_id": job_id, "document": {"content": f"doc-{job_id}"}}
                    for job_id in range(1, 6)
                ]
                self.completed = []
                self.failures = []

            async def _recover_interrupted_jobs(self):
                return None

            async def _claim_pending_jobs(self, limit):
                claimed, self.pending = self.pending[:limit], self.pending[limit:]
                return claimed

            async def _mark_processing(self, job_id):
                return None

            async def _mark_completed(self, job_id):
                self.completed.append(job_id)

            async def _mark_failed(self, job_id, error):
                self.failures.append((job_id, str(error)))

        worker = InMemoryWorker()
        worker.pool = object()
        worker.embedder = AsyncMock(return_value={
            "status": "ok", "vector": [0.1, 0.2], "model_id": 1, "dimensions": 2,
        })
        with patch("app.embedding_worker.upsert_document", AsyncMock(return_value=10)), \
             patch("app.embedding_worker.save_embedding", AsyncMock()), \
             patch("app.embedding_worker.link_contradictions", AsyncMock()), \
             patch.object(worker, "_persist_embedding", AsyncMock()):
            worker.task = asyncio.create_task(worker._run())
            for _ in range(100):
                if worker.completed == [1, 2, 3, 4, 5]:
                    break
                await asyncio.sleep(0.01)
            await worker.stop()
        self.assertEqual(worker.completed, [1, 2, 3, 4, 5])
        self.assertEqual(worker.failures, [])
        self.assertEqual(worker.stats["processed"], 5)


class WalkForwardContracts(unittest.IsolatedAsyncioTestCase):
    async def _run(self, rows, folds=3):
        from app import backtest

        iterator = iter(rows)
        with patch.object(backtest, "_run_single", side_effect=lambda *args, **kwargs: next(iterator)):
            return await backtest.run_walk_forward("BTCTRY", "5m", "MOMENTUM", folds=folds)

    async def test_positive_fold_majority_cannot_hide_negative_total_pnl(self):
        result = await self._run([
            {"net_pnl": 2, "total_trades": 12},
            {"net_pnl": 2, "total_trades": 12},
            {"net_pnl": -10, "total_trades": 12},
        ])
        self.assertFalse(result["oos_consistent"])
        self.assertEqual(result["validation_status"], "FAIL")
        self.assertIn("non_positive_total_net_pnl", result["validation_reasons"])

    async def test_oos_requires_adequate_folds_and_minimum_trades(self):
        result = await self._run([
            {"net_pnl": 2, "total_trades": 2},
            {"net_pnl": 2, "total_trades": 2},
        ], folds=2)
        self.assertFalse(result["oos_consistent"])
        self.assertIn("insufficient_folds", result["validation_reasons"])
        self.assertIn("insufficient_trades", result["validation_reasons"])

    async def test_walk_forward_discloses_that_no_parameter_training_occurs(self):
        result = await self._run([
            {"net_pnl": 2, "total_trades": 12},
            {"net_pnl": 2, "total_trades": 12},
            {"net_pnl": 2, "total_trades": 12},
        ])
        self.assertFalse(result["training_performed"])
        self.assertEqual(result["parameter_selection"], "none")
        self.assertEqual(result["warmup_context_days"], result["train_days"])

    async def test_custom_walk_forward_applies_same_oos_acceptance_rules(self):
        from app import backtest

        rows = iter([
            {"net_pnl": 2, "total_trades": 12},
            {"net_pnl": 2, "total_trades": 12},
            {"net_pnl": 2, "total_trades": 12},
        ])
        with patch.object(backtest, "_run_custom", side_effect=lambda *args, **kwargs: next(rows)):
            result = await backtest.run_custom_walk_forward(
                "BTCTRY", "5m", {"entry": [{"indicator": "close", "op": ">", "value": 0}]}, folds=3
            )
        self.assertTrue(result["oos_consistent"])
        self.assertFalse(result["training_performed"])
        self.assertEqual(result["total_oos_trades"], 36)

    def test_custom_warmup_cannot_open_position_before_oos_start(self):
        from app import backtest

        data = {key: [100.0] * 24 for key in ("opens", "highs", "lows", "closes", "volumes")}
        data["times"] = list(range(24))
        definition = {"entry": [{"indicator": "close", "op": ">", "value": 0}],
                      "exit_policy": {"mode": "protection_only", "use_stop_loss": False,
                                      "use_take_profit": False, "use_max_hold": True, "max_hold_bars": 1}}
        with patch.object(backtest, "_fetch_klines", return_value=data):
            result = backtest._run_custom("BTCTRY", "5m", 1, definition, start_ts=10, end_ts=23)
        self.assertTrue(result["trades"])
        self.assertGreaterEqual(result["trades"][0]["entry_time"], 11)

    def test_fast_bb_mfi_signal_series_matches_strategy_bar_by_bar(self):
        from app.analyzer import ScalpAnalyzer
        from app.backtest import _bb_mfi_signal_series

        closes = [100.0 + ((index % 17) - 8) * 0.31 + index * 0.012 for index in range(120)]
        data = {"closes": closes, "opens": [value - 0.08 for value in closes],
                "highs": [value + 0.4 for value in closes], "lows": [value - 0.5 for value in closes],
                "volumes": [100 + (index % 11) * 9 for index in range(120)], "times": list(range(120))}
        analyzer = ScalpAnalyzer(None)
        fast = _bb_mfi_signal_series(data, analyzer)
        slow = [analyzer.strategy_bb_mfi_mean_reversion({key: values[:index + 1] for key, values in data.items()}, "TESTTRY")
                for index in range(len(closes))]
        self.assertEqual(fast, slow)


if __name__ == "__main__":
    unittest.main()
