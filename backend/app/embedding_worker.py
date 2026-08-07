"""Non-blocking memory embedding worker for PostgreSQL/pgvector."""
import asyncio, json, time
from .memory_service import build_document, upsert_document, save_embedding, link_contradictions

class EmbeddingWorker:
    def __init__(self, max_queue=500):
        self.queue = asyncio.Queue(maxsize=max_queue)
        self.task = None
        self.pool = None
        self.embedder = None
        self.stats = {"queued": 0, "processed": 0, "failed": 0, "last_error": None, "last_processed_at": None}

    async def start(self, pool, embedder):
        self.pool, self.embedder = pool, embedder
        if not self.task or self.task.done():
            await self._rehydrate_jobs()
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
                row = await conn.fetchrow(
                    """INSERT INTO embedding_jobs(document) VALUES($1::jsonb)
                       RETURNING id""",
                    json.dumps(document, ensure_ascii=False, default=str),
                )
            job = {"job_id": int(row["id"]), "document": document}
            try:
                self.queue.put_nowait(job); self.stats["queued"] += 1
            except asyncio.QueueFull:
                # The durable row remains pending and will be rehydrated later.
                self.stats["last_error"] = "embedding queue full; durable job bekliyor"
            return True
        except Exception as exc:
            self.stats["failed"] += 1; self.stats["last_error"] = str(exc)
            return False

    async def _rehydrate_jobs(self):
        """Requeue pending jobs and reclaim jobs interrupted by a restart."""
        async with self.pool.acquire() as conn:
            await conn.execute("""UPDATE embedding_jobs SET status='pending', locked_at=NULL
                WHERE status='processing' AND locked_at < now() - interval '10 minutes'""")
            rows = await conn.fetch("""SELECT id, document FROM embedding_jobs
                WHERE status='pending' AND available_at <= now()
                ORDER BY created_at LIMIT $1""", self.queue.maxsize)
        for row in rows:
            try:
                self.queue.put_nowait({"job_id": int(row["id"]), "document": dict(row["document"])})
                self.stats["queued"] += 1
            except asyncio.QueueFull:
                break

    async def _run(self):
        while True:
            item = await self.queue.get()
            job_id = item.get("job_id") if isinstance(item, dict) and "document" in item else None
            document = item.get("document") if job_id is not None else item
            try:
                last_error = None
                for attempt in range(3):
                    if job_id is not None:
                        async with self.pool.acquire() as conn:
                            await conn.execute("""UPDATE embedding_jobs SET status='processing', attempts=attempts+1,
                                locked_at=now(), last_error=NULL WHERE id=$1""", job_id)
                    try:
                        vector_result = await self.embedder(document["content"])
                        if vector_result.get("status") != "ok": raise RuntimeError(vector_result.get("error", "embedding failed"))
                        vector = vector_result.get("vector")
                        if not vector: raise RuntimeError("embedding provider vector döndürmedi")
                        async with self.pool.acquire() as conn:
                            document_id = await upsert_document(conn, document, vector_result.get("model_id"))
                            await save_embedding(conn, document_id, int(vector_result.get("model_id") or 0), vector, int(vector_result["dimensions"]))
                            await link_contradictions(conn, document_id, document)
                        last_error = None; break
                    except Exception as exc:
                        last_error = exc
                        if attempt < 2: await asyncio.sleep(0.5 * (2 ** attempt))
                if last_error: raise last_error
                if job_id is not None:
                    async with self.pool.acquire() as conn:
                        await conn.execute("""UPDATE embedding_jobs SET status='completed', completed_at=now(),
                            locked_at=NULL WHERE id=$1""", job_id)
                self.stats["processed"] += 1; self.stats["last_processed_at"] = time.time()
            except Exception as exc:
                self.stats["failed"] += 1; self.stats["last_error"] = str(exc)
                if job_id is not None:
                    async with self.pool.acquire() as conn:
                        await conn.execute("""UPDATE embedding_jobs SET status=CASE WHEN attempts >= 3 THEN 'failed' ELSE 'pending' END,
                            available_at=now() + CASE WHEN attempts >= 3 THEN interval '0 seconds' ELSE interval '30 seconds' END,
                            locked_at=NULL, last_error=$2 WHERE id=$1""", job_id, str(exc))
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
        data["outcome"] = "profit" if float(payload.get("pnl") or 0) > 0 else "loss" if float(payload.get("pnl") or 0) < 0 else "flat"
    return build_document(layer="trade", scope=symbol, symbol=symbol, strategy=payload.get("strategy"),
                          source_type=f"trade_{event}", source_id=str(payload.get("id") or signal.get("timestamp")),
                          content=json.dumps(data, ensure_ascii=False, default=str), metadata=data)
