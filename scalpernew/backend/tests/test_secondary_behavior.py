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
    """Backtest kaldırıldı (2026-09-06); ilgili kontrat testleri kaldırıldı."""
    pass



