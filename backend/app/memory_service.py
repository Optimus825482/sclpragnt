"""PostgreSQL/pgvector memory primitives.

The service is intentionally independent from the paper-trading loop. A failed
embedding or retrieval must never stop market-data processing.
"""
import hashlib
import json
import time
from typing import Any

LAYERS = {"session", "symbol", "strategy", "trade", "system", "user"}

def canonical_content(content: str, metadata: dict[str, Any] | None = None) -> str:
    payload = {"content": str(content), "metadata": metadata or {}}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def content_hash(content: str, metadata: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(canonical_content(content, metadata).encode("utf-8")).hexdigest()

def build_document(*, layer: str, scope: str, content: str, source_type: str,
                   source_id: str | None = None, symbol: str | None = None,
                   strategy: str | None = None, timeframe: str | None = None,
                   metadata: dict[str, Any] | None = None, observed_at: float | None = None) -> dict[str, Any]:
    if layer not in LAYERS: raise ValueError(f"Geçersiz memory layer: {layer}")
    if not scope or not content or not source_type: raise ValueError("scope, content ve source_type zorunlu")
    metadata = metadata or {}
    return {"layer": layer, "scope": scope, "symbol": symbol, "strategy": strategy,
            "timeframe": timeframe, "source_type": source_type, "source_id": source_id,
            "content": content, "metadata": metadata, "observed_at": observed_at or time.time(),
            "content_hash": content_hash(content, metadata)}

async def upsert_document(conn, document: dict[str, Any], model_id: int | None = None):
    """Insert one memory document and return its id; safe for duplicate events."""
    row = await conn.fetchrow("""INSERT INTO memory_documents
      (layer,scope,symbol,strategy,timeframe,source_type,source_id,content,metadata,observed_at,embedding_model_id,content_hash)
      VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,to_timestamp($10),$11,$12)
      ON CONFLICT(content_hash,embedding_model_id) DO UPDATE SET content=EXCLUDED.content
      RETURNING id""", document["layer"], document["scope"], document.get("symbol"), document.get("strategy"),
      document.get("timeframe"), document["source_type"], document.get("source_id"), document["content"],
      json.dumps(document.get("metadata", {}), ensure_ascii=False), document["observed_at"], model_id, document["content_hash"])
    return int(row["id"])

async def save_embedding(conn, document_id: int, model_id: int, vector: list[float], dimensions: int):
    if not vector or len(vector) != int(dimensions): raise ValueError("Embedding dimension uyumsuz")
    await conn.execute("""INSERT INTO memory_embeddings(memory_document_id,model_id,dimensions,embedding)
      VALUES($1,$2,$3,$4::halfvec) ON CONFLICT(memory_document_id) DO UPDATE SET model_id=EXCLUDED.model_id,dimensions=EXCLUDED.dimensions,embedding=EXCLUDED.embedding,created_at=now()""",
      document_id, model_id, dimensions, "[" + ",".join(str(float(x)) for x in vector) + "]")
    await conn.execute("UPDATE memory_documents SET embedding_status='ready' WHERE id=$1", document_id)

async def retrieve(conn, query_vector: list[float], *, limit: int = 8, layer: str | None = None,
                   symbol: str | None = None, strategy: str | None = None,
                   timeframe: str | None = None, model_id: int | None = None, query_text: str | None = None):
    if not query_vector: return []
    clauses, args = ["d.embedding_status='ready'"], ["[" + ",".join(str(float(x)) for x in query_vector) + "]"]
    for field, value in (("d.layer", layer), ("d.symbol", symbol), ("d.strategy", strategy), ("d.timeframe", timeframe), ("e.model_id", model_id)):
        if value is not None: args.append(value); clauses.append(f"{field}=${len(args)}")
    text_param = None
    if query_text:
        args.append(query_text); text_param = len(args)
    args.append(max(1, min(int(limit), 50)))
    rows = await conn.fetch(f"""SELECT d.id,d.layer,d.scope,d.symbol,d.strategy,d.timeframe,d.content,d.metadata,d.observed_at,
      1-(e.embedding <=> $1::halfvec) AS similarity,
      {f"ts_rank_cd(d.search_vector, plainto_tsquery('simple', ${text_param}))" if text_param else "0"} AS lexical_score
      FROM memory_documents d JOIN memory_embeddings e ON e.memory_document_id=d.id
      WHERE {' AND '.join(clauses)}
      ORDER BY ((1-(e.embedding <=> $1::halfvec)) * 0.8 + {f"ts_rank_cd(d.search_vector, plainto_tsquery('simple', ${text_param}))" if text_param else "0"} * 0.2) DESC
      LIMIT ${len(args)}""", *args)
    return [dict(row) for row in rows]
