"""Non-blocking memory embedding worker for PostgreSQL/pgvector."""
import asyncio, json, time
from .memory_service import build_document, upsert_document, save_embedding, link_contradictions

class EmbeddingWorker:
    def __init__(self, max_queue=500, poll_interval=2.0):
        self.queue = asyncio.Queue(maxsize=max_queue)
        self.poll_interval = max(0.01, float(poll_interval))
        self.task = None
        self.pool = None
        self.embedder = None
        self._fill_lock = asyncio.Lock()
        self.stats = {"queued": 0, "processed": 0, "failed": 0, "last_error": None, "last_processed_at": None}

    async def start(self, pool, embedder):
        self.pool, self.embedder = pool, embedder
        if not self.task or self.task.done():
            await self._recover_interrupted_jobs()
            try:
                await self._fill_from_persistence()
            except Exception as exc:
                # DB başlangıçta erişilemezse worker görevi yine de başlatılır;
                # _run döngüsü DB döndüğünde işleri devralır.
                import logging
                logging.getLogger("scalper.embedding").warning(
                    "Başlangıç fill_from_persistence hatası (daha sonra tekrarlacak): %s", exc, exc_info=True
                )
            self.task = asyncio.create_task(self._run(), name="embedding-worker")

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    async def enqueue_persistent(self, document):
        """Persist first, then wake the in-process worker; jobs survive deploys."""
        if not self.pool or not document:
            return False
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchrow(
                    """INSERT INTO embedding_jobs(document) VALUES($1::jsonb)
                       RETURNING id""",
                    json.dumps(document, ensure_ascii=False, default=str),
                )
            await self._fill_from_persistence()
            return True
        except Exception as exc:
            self.stats["failed"] += 1; self.stats["last_error"] = str(exc)
            return False

    async def _recover_interrupted_jobs(self):
        """A new process owns no queued work, so make interrupted rows claimable."""
        async with self.pool.acquire() as conn:
            await conn.execute("""UPDATE embedding_jobs SET status='pending', locked_at=NULL
                WHERE status='queued'
                   OR (status='processing' AND locked_at < now() - interval '10 minutes')""")

    async def _claim_pending_jobs(self, limit):
        if limit <= 0:
            return []
        claimed = []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""SELECT id, document FROM embedding_jobs
                WHERE status='pending' AND available_at <= now()
                ORDER BY created_at LIMIT $1""", limit)
            for row in rows:
                locked = await conn.fetchrow("""UPDATE embedding_jobs
                    SET status='queued', locked_at=now()
                    WHERE id=$1 AND status='pending'
                    RETURNING id""", int(row["id"]))
                if not locked:
                    continue
                document = row["document"]
                if isinstance(document, str):
                    document = json.loads(document)
                else:
                    document = dict(document)
                claimed.append({"job_id": int(row["id"]), "document": document})
        return claimed

    async def _fill_from_persistence(self):
        """Keep the bounded RAM queue fed from the durable queue."""
        if not self.pool:
            return 0
        async with self._fill_lock:
            capacity = self.queue.maxsize - self.queue.qsize()
            jobs = await self._claim_pending_jobs(capacity)
            for job in jobs:
                self.queue.put_nowait(job)
                self.stats["queued"] += 1
            return len(jobs)

    async def _mark_processing(self, job_id):
        async with self.pool.acquire() as conn:
            await conn.execute("""UPDATE embedding_jobs SET status='processing', attempts=attempts+1,
                locked_at=now(), last_error=NULL WHERE id=$1""", job_id)

    async def _mark_completed(self, job_id):
        async with self.pool.acquire() as conn:
            await conn.execute("""UPDATE embedding_jobs SET status='completed', completed_at=now(),
                locked_at=NULL WHERE id=$1""", job_id)

    async def _mark_failed(self, job_id, error):
        async with self.pool.acquire() as conn:
            await conn.execute("""UPDATE embedding_jobs SET status=CASE WHEN attempts >= 3 THEN 'failed' ELSE 'pending' END,
                available_at=now() + CASE WHEN attempts >= 3 THEN interval '0 seconds' ELSE interval '30 seconds' END,
                locked_at=NULL, last_error=$2 WHERE id=$1""", job_id, str(error))

    async def _persist_embedding(self, document, vector_result):
        async with self.pool.acquire() as conn:
            document_id = await upsert_document(conn, document, vector_result.get("model_id"))
            await save_embedding(conn, document_id, int(vector_result.get("model_id") or 0), vector_result["vector"], int(vector_result["dimensions"]))
            await link_contradictions(conn, document_id, document)

    async def _run(self):
        while True:
            await self._fill_from_persistence()
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                continue
            job_id = item.get("job_id") if isinstance(item, dict) and "document" in item else None
            document = item.get("document") if job_id is not None else item
            try:
                last_error = None
                for attempt in range(3):
                    if job_id is not None:
                        await self._mark_processing(job_id)
                    try:
                        vector_result = await self.embedder(document["content"])
                        if vector_result.get("status") != "ok": raise RuntimeError(vector_result.get("error", "embedding failed"))
                        vector = vector_result.get("vector")
                        if not vector: raise RuntimeError("embedding provider vector döndürmedi")
                        await self._persist_embedding(document, vector_result)
                        last_error = None; break
                    except Exception as exc:
                        last_error = exc
                        if attempt < 2: await asyncio.sleep(0.5 * (2 ** attempt))
                if last_error: raise last_error
                if job_id is not None:
                    await self._mark_completed(job_id)
                self.stats["processed"] += 1; self.stats["last_processed_at"] = time.time()
            except Exception as exc:
                self.stats["failed"] += 1; self.stats["last_error"] = str(exc)
                if job_id is not None:
                    await self._mark_failed(job_id, exc)
            finally: self.queue.task_done()

    def snapshot(self):
        return {**self.stats, "pending": self.queue.qsize(), "running": bool(self.task and not self.task.done())}

worker = EmbeddingWorker()

def signal_document(signal):
    return build_document(layer="strategy" if signal.get("strategy") else "system", scope=signal.get("symbol") or "global",
                          symbol=signal.get("symbol"), strategy=signal.get("strategy"), source_type="signal",
                          source_id=str(signal.get("id") or signal.get("timestamp")), content=json.dumps(signal, ensure_ascii=False, default=str), metadata=signal)

def trade_document(event, symbol, payload, signal):
    data = {"event": event, "symbol": symbol, "trade": payload, "signal": signal}
    if event in {"exit", "historical"}:
        # A malformed pnl string must degrade to a flat outcome, not crash the
        # trade-close path before the document reaches the durable queue.
        try:
            pnl_value = float(payload.get("pnl") or 0)
        except (TypeError, ValueError):
            pnl_value = 0.0
        data["outcome"] = "profit" if pnl_value > 0 else "loss" if pnl_value < 0 else "flat"
    return build_document(layer="trade", scope=symbol, symbol=symbol, strategy=payload.get("strategy"),
                          source_type=f"trade_{event}", source_id=str(payload.get("id") or signal.get("timestamp")),
                          content=json.dumps(data, ensure_ascii=False, default=str), metadata=data)
