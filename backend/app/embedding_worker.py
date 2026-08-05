"""Non-blocking memory embedding worker for PostgreSQL/pgvector."""
import asyncio, json, time
from .memory_service import build_document, upsert_document, save_embedding

class EmbeddingWorker:
    def __init__(self, max_queue=500):
        self.queue = asyncio.Queue(maxsize=max_queue)
        self.task = None
        self.pool = None
        self.embedder = None
        self.stats = {"queued": 0, "processed": 0, "failed": 0, "last_error": None, "last_processed_at": None}

    async def start(self, pool, embedder):
        self.pool, self.embedder = pool, embedder
        if not self.task or self.task.done(): self.task = asyncio.create_task(self._run(), name="embedding-worker")

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    def enqueue_nowait(self, document):
        if not self.task or self.task.done():
            return False
        try:
            self.queue.put_nowait(document); self.stats["queued"] += 1; return True
        except asyncio.QueueFull:
            self.stats["failed"] += 1; self.stats["last_error"] = "embedding queue full"; return False

    async def _run(self):
        while True:
            document = await self.queue.get()
            try:
                vector_result = await self.embedder(document["content"])
                if vector_result.get("status") != "ok": raise RuntimeError(vector_result.get("error", "embedding failed"))
                vector = vector_result.get("vector")
                if not vector: raise RuntimeError("embedding provider vector döndürmedi")
                async with self.pool.acquire() as conn:
                    document_id = await upsert_document(conn, document, vector_result.get("model_id"))
                    await save_embedding(conn, document_id, int(vector_result.get("model_id") or 0), vector, int(vector_result["dimensions"]))
                self.stats["processed"] += 1; self.stats["last_processed_at"] = time.time()
            except Exception as exc:
                self.stats["failed"] += 1; self.stats["last_error"] = str(exc)
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
    return build_document(layer="trade", scope=symbol, symbol=symbol, strategy=payload.get("strategy"),
                          source_type=f"trade_{event}", source_id=str(payload.get("id") or signal.get("timestamp")),
                          content=json.dumps(data, ensure_ascii=False, default=str), metadata=data)
