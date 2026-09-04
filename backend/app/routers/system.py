"""Health, memory and migration system routes."""
import asyncio
import os
import time
import logging

from fastapi import APIRouter, HTTPException

from app.config import config
from app import database
from app.state import market, analyzer
from app.api_common import _start_background, _background_tasks
from app import memory_service
from app import migration_monitor
from app.embedding_worker import worker as embedding_worker, trade_document, signal_document
from app.memory_service import build_document
from app.ws_runtime import ws_manager
import math
import json
from app.binance_tr_public import klines as fetch_klines
from app.technical_analysis import calculate_snapshot
from app import llm_analysis
from app.api_common import _main_pg_pool

logger = logging.getLogger("scalper.system")
router = APIRouter()


_embedding_backfill = {"status": "idle", "queued": 0, "message": None}
_embedding_repair = {"status": "idle", "queued": 0, "message": None}

@router.get("/health")
async def health():
    snapshots = {symbol: market.data_freshness(symbol, config.ACTIVE_STRATEGY_TIMEFRAME)
                 for symbol in market.symbols}
    ready = [value for value in snapshots.values()
             if value["ticker"]["fresh"] and value["kline"]["fresh"]]
    market_healthy = market.running and bool(ready)
    return {
        "status": "alive" if market_healthy else "degraded",
        "mode": "paper", "market_data": "binance_tr_public",
        "history_loaded": market.history_loaded,
        "fresh_symbols": len(ready), "tracked_symbols": len(snapshots),
        "rest": {"last_event_at": market.rest_last_event_at, "last_error": market.rest_last_error},
        "ws": {"last_event_at": market.ws_last_event_at, "last_error": market.ws_last_error,
               "generation": market.connection_generation},
        "market_error": market.last_error, "open_positions": list(analyzer.positions.keys())
    }

@router.get("/api/system/health")
async def system_health():
    now_ms = time.time() * 1000
    ages = [max(0.0, (now_ms - float(t.get("timestamp", now_ms))) / 1000) for t in market.tickers.values() if t.get("timestamp")]
    vector_status = "not_checked_until_postgres_backend_is_enabled"
    db_status = "postgres_not_configured"
    if _main_pg_pool():
        try:
            async with _main_pg_pool().acquire() as conn:
                await conn.fetchval("SELECT 1")
                vector_status = bool(await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"))
                db_status = "postgres_healthy"
        except Exception as exc:
            db_status = f"postgres_error:{type(exc).__name__}"
            vector_status = False
    try:
        llm_active = bool(await database.get_active_llm_config())
        llm_error = None
    except Exception as exc:
        llm_active = False
        llm_error = f"{type(exc).__name__}: {exc}"
    freshness = {symbol: market.data_freshness(symbol, config.ACTIVE_STRATEGY_TIMEFRAME)
                 for symbol in market.symbols}
    fresh_count = sum(1 for value in freshness.values()
                      if value["ticker"]["fresh"] and value["kline"]["fresh"])
    market_degraded = market.running and bool(market.symbols) and fresh_count == 0
    overall_degraded = (db_status.startswith("postgres_") and db_status != "postgres_healthy") or llm_error or market_degraded
    # MAX_OPEN_POSITIONS=0 "sınırsız" demektir; analyzer float("inf") döndürür ve
    # JSON bunu temsil edemez (allow_nan=False) → API'ye null olarak çıkar.
    _max_open_raw = analyzer.max_open_positions()
    max_open_json = None if isinstance(_max_open_raw, float) and not math.isfinite(_max_open_raw) else _max_open_raw
    return {"status": "degraded" if overall_degraded else "ok", "generated_at": time.time(), "market": {"symbols": len(market.symbols), "tickers": len(market.tickers), "fresh_symbols": fresh_count, "max_ticker_age_sec": max(ages) if ages else None, "timeframes": market.timeframes, "rest_last_event_at": market.rest_last_event_at, "rest_error": market.rest_last_error, "ws_last_event_at": market.ws_last_event_at, "ws_error": market.ws_last_error, "ws_generation": market.connection_generation}, "portfolio": {"open_positions": len(analyzer.positions), "max_open_positions": max_open_json, "pending_paper_orders": len(analyzer.pending_orders)}, "database": {"backend": "postgres", "status": db_status, "postgres_configured": bool(os.getenv("DATABASE_URL", "").strip()), "vector_extension": vector_status}, "embedding": embedding_worker.snapshot(), "websocket_clients": len(ws_manager.active_connections), "llm": {"configured": bool(os.getenv("LLM_ENCRYPTION_KEY", "").strip()), "active": llm_active, "error": llm_error}, "safety": {"paper_only": True, "memory_content_untrusted": True, "tool_audit_enabled": True}}

@router.get("/api/memory/status")
async def memory_status():
    persistent = {"documents": 0, "embedded": 0}
    if _main_pg_pool():
        async with _main_pg_pool().acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS documents, COUNT(*) FILTER (WHERE embedding_status='ready') AS embedded FROM memory_documents")
            persistent = {"documents": int(row["documents"]), "embedded": int(row["embedded"])}
    return {"enabled": bool(_main_pg_pool()), "backend": os.getenv("DB_BACKEND", "postgres"), "worker": embedding_worker.snapshot(), "persistent": persistent, "backfill": dict(_embedding_backfill), "repair": dict(_embedding_repair), "message": None if _main_pg_pool() else "PostgreSQL memory backend aktif değil"}

@router.post("/api/memory/backfill")
async def memory_backfill():
    if not _main_pg_pool(): raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    if _embedding_backfill["status"] == "running": return {"ok": False, **_embedding_backfill}
    _embedding_backfill.update({"status": "running", "queued": 0, "message": "Kayıtlar embedding kuyruğuna alınıyor"})
    async def enqueue_existing():
        try:
            queued = 0
            async with _main_pg_pool().acquire() as conn:
                trades = [dict(row) for row in await conn.fetch("SELECT * FROM trades ORDER BY id")]
                signals = [dict(row) for row in await conn.fetch("SELECT * FROM signals ORDER BY id")]
            for trade in trades:
                doc = trade_document("historical", trade.get("symbol") or "unknown", trade, {"action": "HISTORICAL_TRADE", "timestamp": trade.get("exit_time")})
                queued += int(await embedding_worker.enqueue_persistent(doc))
            for signal in signals:
                queued += int(await embedding_worker.enqueue_persistent(signal_document(signal)))
            _embedding_backfill.update({"status": "completed", "queued": queued, "message": "Embedding kuyruğu hazır; worker kayıtları işliyor"})
        except Exception as exc:
            _embedding_backfill.update({"status": "error", "message": str(exc)})
    asyncio.create_task(enqueue_existing(), name="embedding-backfill")
    return {"ok": True, **_embedding_backfill}

@router.post("/api/memory/repair-historical")
async def repair_historical_memory():
    """Rebuild historical trade memory without inventing unavailable market data."""
    if not _main_pg_pool(): raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    if _embedding_repair["status"] == "running": return {"ok": False, **_embedding_repair}
    _embedding_repair.update({"status": "running", "queued": 0, "message": "Tarihsel snapshot'lar onarılıyor"})
    async def repair():
        try:
            queued = 0
            async with _main_pg_pool().acquire() as conn:
                trades = [dict(row) for row in await conn.fetch("SELECT * FROM trades ORDER BY id")]
                for trade in trades:
                    context = trade.get("entry_context")
                    if isinstance(context, str):
                        try: context = json.loads(context)
                        except json.JSONDecodeError: context = {}
                    context = context if isinstance(context, dict) else {}
                    technical = context.get("technical") if isinstance(context.get("technical"), dict) else {}
                    # Reconstruct OHLCV-based indicators around the original
                    # entry time. Order-book fields remain explicitly unknown.
                    try:
                        entry_ms = int(float(trade.get("entry_time") or 0) * 1000)
                        symbol = str(trade.get("symbol") or "").upper()
                        rows_5m = await fetch_klines(symbol, "5m", 300, max(0, entry_ms - 300 * 5 * 60 * 1000))
                        rows_1d = await fetch_klines(symbol, "1d", 250, max(0, entry_ms - 250 * 86400 * 1000))
                        def pack(rows):
                            return {"opens": [float(r[1]) for r in rows], "highs": [float(r[2]) for r in rows], "lows": [float(r[3]) for r in rows], "closes": [float(r[4]) for r in rows], "volumes": [float(r[5]) for r in rows]}
                        rebuilt = calculate_snapshot(symbol, float(trade.get("entry_price") or 0), {"5m": pack(rows_5m), "1d": pack(rows_1d)}, {"source": "historical_reconstruction", "spread_pct": None, "bid_qty": 0, "ask_qty": 0}, 0, float(trade.get("entry_price") or 0) * float(trade.get("quantity") or 0), "5m")
                        technical = rebuilt if rebuilt.get("data_ready") else technical
                    except Exception as exc:
                        _embedding_repair["message"] = f"Bazı kayıtlar yeniden hesaplanamadı: {exc}"
                    liquidity = technical.get("liquidity") if isinstance(technical.get("liquidity"), dict) else {}
                    missing = [key for key in ("spread_pct", "orderbook_depth_try", "orderflow_imbalance") if liquidity.get(key) in (None, 0, 0.0)]
                    technical["liquidity"] = {**liquidity, "spread_pct": None, "orderbook_depth_try": None, "depth_multiplier": None, "orderflow_imbalance": None, "source": "historical_reconstruction", "missing_fields": missing}
                    context["technical"] = technical
                    context["data_provenance"] = "historical_reconstruction"
                    context["data_quality"] = {"missing_fields": missing, "note": "Historical order-book data was not available; no values were estimated."}
                    trade["entry_context"] = context
                    source_id = str(trade.get("id"))
                    await conn.execute("DELETE FROM memory_embeddings WHERE memory_document_id IN (SELECT id FROM memory_documents WHERE source_type='trade_historical' AND source_id=$1)", source_id)
                    await conn.execute("DELETE FROM memory_documents WHERE source_type='trade_historical' AND source_id=$1", source_id)
                    doc = trade_document("historical", trade.get("symbol") or "unknown", trade, {"action": "HISTORICAL_TRADE", "timestamp": trade.get("exit_time")})
                    queued += int(await embedding_worker.enqueue_persistent(doc))
            _embedding_repair.update({"status": "completed", "queued": queued, "message": "Eksik tarihsel likidite alanları tahmin edilmeden yeniden embedding kuyruğuna alındı"})
        except Exception as exc:
            _embedding_repair.update({"status": "error", "message": str(exc)})
    asyncio.create_task(repair(), name="historical-memory-repair")
    return {"ok": True, **_embedding_repair}

@router.get("/api/migration/status")
async def migration_status():
    return dict(migration_monitor.state)

@router.post("/api/migration/start")
async def migration_start(payload: dict = None):
    body = payload or {}
    source = str(body.get("source") or os.getenv("MIGRATION_SOURCE_PATH") or "legacy-pasif")
    if migration_monitor.state["status"] == "running": return {"ok": False, "message": "Migration zaten çalışıyor"}
    try: info = migration_monitor.inspect_source(source)
    except Exception as exc: raise HTTPException(status_code=400, detail=str(exc))
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url: raise HTTPException(status_code=503, detail="DATABASE_URL tanımlı değil")
    migration_monitor.state.update({"source":info, "status":"queued", "phase":"queued", "progress":0, "message":"Migration kuyruğa alındı"})
    asyncio.create_task(migration_monitor.run(source, database_url), name="legacy-migration-check")
    return {"ok":True, "source":info}

@router.post("/api/memory/retrieve")
async def memory_retrieve(payload: dict = None):
    if not _main_pg_pool(): raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    body = payload or {}
    text = str(body.get("query", "")).strip()
    if not text: raise HTTPException(status_code=400, detail="query gerekli")
    embedded = await llm_analysis.embedding(text, body.get("model_id"))
    if embedded.get("status") == "disabled":
        return {"query": text, "results": [], "count": 0, "status": "disabled", "message": embedded.get("error", "Embedding modeli aktif değil")}
    if embedded.get("status") != "ok": raise HTTPException(status_code=502, detail=embedded.get("error", "Embedding üretilemedi"))
    requested_symbol = str(body.get("symbol")).strip().upper() if body.get("symbol") else None
    async with _main_pg_pool().acquire() as conn:
        rows = await memory_service.retrieve(conn, embedded["vector"], limit=body.get("limit", 8), layer=body.get("layer"), symbol=requested_symbol, strategy=body.get("strategy"), timeframe=body.get("timeframe"), model_id=embedded.get("model_id"), query_text=text)
        await conn.execute("INSERT INTO memory_retrieval_logs(query_scope,query_text_hash,filters,model_id,result_ids,latency_ms) VALUES($1,$2,$3::jsonb,$4,$5::jsonb,$6)", body.get("scope", "memory"), memory_service.content_hash(text), json.dumps({k: body.get(k) for k in ("layer", "symbol", "strategy", "timeframe") if body.get(k) is not None}), embedded.get("model_id"), json.dumps([r.get("id") for r in rows]), None)
    return {"query": text, "results": rows, "count": len(rows)}

