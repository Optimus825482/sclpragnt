import asyncio
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


class MigrationContracts(unittest.TestCase):
    def test_all_durable_a2a_tables_are_migrated(self):
        from app import migration_monitor

        spec = importlib.util.spec_from_file_location(
            "migrate_sqlite_to_postgres",
            ROOT / "scripts" / "migrate_sqlite_to_postgres.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        required = {"a2a_messages", "llm_symbol_guards"}
        self.assertTrue(required.issubset(migration_monitor.TABLES))
        self.assertTrue(required.issubset(module.TABLES))

    def test_count_verification_rejects_missing_target_rows(self):
        from app.migration_monitor import compare_counts

        errors = compare_counts(
            {"a2a_messages": 4, "llm_symbol_guards": 2},
            {"a2a_messages": 3, "llm_symbol_guards": 2},
        )
        self.assertEqual(errors, ["a2a_messages: hedef satır sayısı eksik (3/4)"])


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


class A2AContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "a2a_relay_server", ROOT.parent / "a2a-relay" / "server.py"
        )
        cls.relay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.relay)

    def test_relay_routes_scalper_recipient_to_backend(self):
        with patch.object(self.relay, "BACKEND_URL", "http://backend/api/a2a/messages"), \
             patch.object(self.relay, "PEER_URL", "https://peer/messages"):
            self.assertEqual(
                self.relay.route_target({"to": "scalper-server-llm"}),
                "http://backend/api/a2a/messages",
            )
            self.assertEqual(
                self.relay.route_target({"to": "codex-agent"}),
                "https://peer/messages",
            )

    def test_relay_maps_management_routes_to_backend_a2a_api(self):
        with patch.object(self.relay, "BACKEND_URL", "http://backend:8004/api/a2a/messages"):
            self.assertEqual(
                self.relay.backend_route_url("/api/a2a/messages/abc/ack?source=relay"),
                "http://backend:8004/api/a2a/messages/abc/ack?source=relay",
            )
            self.assertEqual(
                self.relay.backend_route_url("/api/a2a/emit"),
                "http://backend:8004/api/a2a/emit",
            )

    def test_gateway_keeps_browser_a2a_management_on_authenticated_backend(self):
        nginx = (ROOT.parent / "nginx" / "default.conf").read_text(encoding="utf-8")
        exact = nginx.split("location = /api/a2a/messages", 1)[1].split("}", 1)[0]
        prefix = nginx.split("location /api/a2a/", 1)[1].split("}", 1)[0]
        self.assertIn("proxy_pass http://backend:8004", exact)
        self.assertIn("proxy_pass http://backend:8004", prefix)

    def test_signature_contract_is_constant_time_and_header_named(self):
        from app import a2a

        body = b'{"paper_only":true}'
        signed = a2a.signature(body, "secret")
        with patch.object(self.relay, "SECRET", "secret"):
            self.assertTrue(self.relay.valid_signature(body, signed))
        source = (ROOT / "app" / "a2a.py").read_text(encoding="utf-8")
        self.assertIn('"X-A2A-Signature"', source)

    def test_non_success_delivery_remains_queued(self):
        from app import a2a

        message = a2a.make_message(
            sender="scalper-server-llm", recipient="codex-agent",
            message_type="diagnostic", payload={},
        )
        with patch.dict("os.environ", {
            "A2A_RELAY_URL": "https://relay.invalid/api/a2a/messages",
            "A2A_SHARED_SECRET": "secret",
        }), patch("app.a2a.asyncio.to_thread", AsyncMock(return_value=503)):
            result = asyncio.run(a2a.deliver(message))
        self.assertFalse(result["delivered"])
        self.assertTrue(result["queued"])


if __name__ == "__main__":
    unittest.main()
