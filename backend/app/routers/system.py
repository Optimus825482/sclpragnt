"""Health, memory and migration system routes."""
import asyncio
import os
import time
import logging
from functools import partial

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import config
from app import database
from app.state import market, analyzer
from app.api_common import _start_background, _background_tasks, rate_limit
from app.api_common import loop_health, get_task, is_shutting_down
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

# 2026-10-15 (denetim düzeltmesi, §5 P1): /health sabit "alive" dönüyordu —
# event loop kilitlense ya da strateji döngüsü kalıcı olarak düşse bile
# konteyner "healthy" kalıyordu ("canlı ama ölü"). Artık uç, süpervizörün
# döngü kaydına (`api_common.loop_health` + `get_task`) ve market akışının
# son olay zamanına bakar; aşağıdaki durumlardan biri varsa 503 döner:
#   * kritik bir döngü `MAX_BACKGROUND_RESTARTS` sonrası KALICI "failed",
#   * kritik bir döngünün görevi bitmiş/ölmüş (respawn edilmemiş),
#   * market akışı çalışıyor görünürken son olay `SCALPER_HEALTH_STALE_SEC`
#     saniyeden eski (varsayılan 120; 0 → bu kontrol kapalı).
# Ucuz kalır: sembol taraması/DB sorgusu YOK; yalnızca sözlük okumaları.
# Kritik döngü listesi env ile değiştirilebilir (virgülle ayrılmış isimler).
_HEALTH_CRITICAL_LOOPS_DEFAULT = ("market-connect", "strategy-loop", "ws-broadcast")


def _health_stale_sec() -> float:
    try:
        return max(0.0, float(os.getenv("SCALPER_HEALTH_STALE_SEC", "120") or 0))
    except (TypeError, ValueError):
        return 120.0


def _health_critical_loops() -> tuple[str, ...]:
    raw = os.getenv("SCALPER_HEALTH_CRITICAL_LOOPS", "").strip()
    if not raw:
        return _HEALTH_CRITICAL_LOOPS_DEFAULT
    return tuple(name.strip() for name in raw.split(",") if name.strip())


def _health_loop_states() -> tuple[dict, list[str]]:
    """Kritik döngülerin durumunu ve 503 gerektiren sebepleri döndür.

    Durumlar: ``running`` / ``starting`` (henüz kaydedilmedi — açılış
    sürüyor, ceza YOK) / ``failed`` (süpervizör vazgeçti) / ``dead`` (görev
    bitmiş ama respawn yok) / ``stopping`` (kapanış sırasında normal).
    """
    snapshot = loop_health()
    failed = snapshot.get("failed", {}) or {}
    counters = snapshot.get("restart_counters", {}) or {}
    shutting_down = is_shutting_down()
    states: dict = {}
    reasons: list[str] = []
    for name in _health_critical_loops():
        task = get_task(name)
        if name in failed:
            state = "failed"
        elif task is None:
            state = "starting"
        elif task.done():
            state = "stopping" if shutting_down else "dead"
        else:
            state = "running"
        states[name] = {"state": state, "restarts": int(counters.get(name, 0) or 0)}
        if state in ("failed", "dead"):
            reasons.append(f"loop:{name}:{state}")
    return states, reasons


@router.get("/health")
async def health():
    # 2026-09-26 (deploy düzeltmesi): bu uç container healthcheck'inin
    # hedefi. Önceden TÜM semboller için `market.data_freshness()` çağırıyordu
    # (310 sembol × senkron sözlük/len hesabı) ve ayrıca `analyzer.positions`
    # ile `market.symbols` üzerinde tam tarama yapıyordu. Açılışta history
    # backfill'i event loop'u meşgul ettiği için bu uç zaman aşımına
    # uğruyor, container "unhealthy" oluyor ve Coolify deploy'u başarısız
    # sayıyordu.
    #
    # Liveness SÖZLEŞMESİ: bu uç SADECE sürecin ayakta olduğunu ve
    # market akışının bağlı olup olmadığını bildirir. "Piyasa taze mi"
    # sorusu bir hazırlık (readiness) sorusudur ve `/api/system/health`
    # (kimlik doğrulamalı) ile `market.data_freshness` üzerinden verilir.
    # Liveness, tazelik KOŞULU üzerinden karar verirse, veri geciktiğinde
    # yeniden başlatma tetiklenir — bu da aracın kurtarılmasını engeller.
    #
    # 2026-10-15 (denetim düzeltmesi, §5 P1): "sembol başına tazelik" hâlâ
    # readiness'tedir; burada eklenen YALNIZ süreç-içi döngü canlılığı
    # (süpervizör kaydı) ve market akışının TEK bir "son olay" zaman damgası
    # (`market.last_event_at`, WS ∪ REST). Akış `running` iken 120 sn boyunca
    # hiç olay gelmemesi "döngü kilitli/ölü" demektir; yeniden başlatma bu
    # durumda kurtarmanın ta kendisidir. Gövde biçimi geriye uyumlu: 200'de
    # eski anahtarlar aynen kalır, `loops` ayrıntısı EKLENİR; 503'te aynı
    # gövde `status: "unhealthy"` + `reasons` ile döner.
    loop_states, reasons = _health_loop_states()
    stale_sec = _health_stale_sec()
    last_event_at = getattr(market, "last_event_at", None)
    market_running = bool(getattr(market, "running", False))
    heartbeat_age = None
    if last_event_at:
        try:
            heartbeat_age = max(0.0, time.time() - float(last_event_at))
        except (TypeError, ValueError):
            heartbeat_age = None
    if (stale_sec > 0 and market_running and heartbeat_age is not None
            and heartbeat_age > stale_sec and not is_shutting_down()):
        reasons.append(f"market_heartbeat_stale:{heartbeat_age:.0f}s>{stale_sec:.0f}s")
    body = {
        "status": "unhealthy" if reasons else "alive",
        "mode": "paper", "market_data": "binance_tr_public",
        "market_running": market_running,
        "history_loaded": bool(getattr(market, "history_loaded", False)),
        "tracked_symbols": len(getattr(market, "symbols", ()) or ()),
        # G-30: /health kimlik doğrulamasız bir yoldur; açık pozisyon sembolleri
        # (hangi sembollerde pozisyon var) sızdırılmamalı. Yalnız sayı verilir;
        # sembol listesi kimlik doğrulamalı /api/positions'tan alınır.
        "open_position_count": len(getattr(analyzer, "positions", {}) or {}),
        "loops": {
            "critical": loop_states,
            "failed": sorted((loop_health().get("failed") or {}).keys()),
            "market_heartbeat_age_sec": None if heartbeat_age is None else round(heartbeat_age, 1),
            "stale_threshold_sec": stale_sec,
        },
    }
    if reasons:
        body["reasons"] = reasons
        return JSONResponse(status_code=503, content=body)
    return body

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
    freshness = {symbol: market.data_freshness(symbol, "5m")
                 for symbol in market.symbols}
    fresh_count = sum(1 for value in freshness.values()
                      if value["ticker"]["fresh"] and value["kline"]["fresh"])
    market_degraded = market.running and bool(market.symbols) and fresh_count == 0
    overall_degraded = (db_status.startswith("postgres_") and db_status != "postgres_healthy") or llm_error or market_degraded
    # MAX_OPEN_POSITIONS=0 "sınırsız" demektir; analyzer float("inf") döndürür ve
    # JSON bunu temsil edemez (allow_nan=False) → API'ye null olarak çıkar.
    _max_open_raw = analyzer.max_open_positions()
    max_open_json = None if isinstance(_max_open_raw, float) and not math.isfinite(_max_open_raw) else _max_open_raw
    real_sell_enabled = os.getenv("ENABLE_REAL_BINANCE_SELL", "0").strip().lower() in {"1", "true", "yes", "on"}
    return {"status": "degraded" if overall_degraded else "ok", "generated_at": time.time(), "market": {"symbols": len(market.symbols), "tickers": len(market.tickers), "fresh_symbols": fresh_count, "max_ticker_age_sec": max(ages) if ages else None, "timeframes": market.timeframes, "rest_last_event_at": market.rest_last_event_at, "rest_error": market.rest_last_error, "ws_last_event_at": market.ws_last_event_at, "ws_error": market.ws_last_error, "ws_generation": market.connection_generation}, "portfolio": {"open_positions": len(analyzer.positions), "max_open_positions": max_open_json, "pending_paper_orders": len(analyzer.pending_orders)}, "database": {"backend": "postgres", "status": db_status, "postgres_configured": bool(os.getenv("DATABASE_URL", "").strip()), "vector_extension": vector_status}, "embedding": embedding_worker.snapshot(), "websocket_clients": len(ws_manager.active_connections), "llm": {"configured": bool(os.getenv("LLM_ENCRYPTION_KEY", "").strip()), "active": llm_active, "error": llm_error}, "safety": {"paper_only": not real_sell_enabled, "paper_trading_core": True, "real_sell_enabled": real_sell_enabled, "memory_content_untrusted": True, "tool_audit_enabled": True}}

@router.get("/api/memory/status")
async def memory_status():
    persistent = {"documents": 0, "embedded": 0}
    if _main_pg_pool():
        async with _main_pg_pool().acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS documents, COUNT(*) FILTER (WHERE embedding_status='ready') AS embedded FROM memory_documents")
            persistent = {"documents": int(row["documents"]), "embedded": int(row["embedded"])}
    return {"enabled": bool(_main_pg_pool()), "backend": os.getenv("DB_BACKEND", "postgres"), "worker": embedding_worker.snapshot(), "persistent": persistent, "backfill": dict(_embedding_backfill), "repair": dict(_embedding_repair), "message": None if _main_pg_pool() else "PostgreSQL memory backend aktif değil"}

@router.post("/api/memory/backfill")
async def memory_backfill(request: Request = None):
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
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
    _start_background(enqueue_existing, "embedding-backfill", single_pass=True)
    return {"ok": True, **_embedding_backfill}

@router.post("/api/memory/repair-historical")
async def repair_historical_memory(request: Request = None):
    """Rebuild historical trade memory without inventing unavailable market data."""
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
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
    _start_background(repair, "historical-memory-repair", single_pass=True)
    return {"ok": True, **_embedding_repair}

@router.get("/api/migration/status")
async def migration_status():
    return dict(migration_monitor.state)

@router.post("/api/migration/start")
async def migration_start(payload: dict = None, request: Request = None):
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    body = payload or {}
    source = str(body.get("source") or os.getenv("MIGRATION_SOURCE_PATH") or "legacy-pasif")
    if migration_monitor.state["status"] == "running": return {"ok": False, "message": "Migration zaten çalışıyor"}
    # V-21: SQLite migration kalıcı olarak kaldırıldı → 410 Gone (400 "bad
    # request" kullanıcıyı girdiyi düzeltmeye çalıştırıyordu).
    try: info = migration_monitor.inspect_source(source)
    except Exception as exc: raise HTTPException(status_code=410, detail=str(exc))
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url: raise HTTPException(status_code=503, detail="DATABASE_URL tanımlı değil")
    migration_monitor.state.update({"source":info, "status":"queued", "phase":"queued", "progress":0, "message":"Migration kuyruğa alındı"})
    _start_background(partial(migration_monitor.run, source, database_url), "legacy-migration-check", single_pass=True)
    return {"ok":True, "source":info}

@router.post("/api/memory/retrieve")
async def memory_retrieve(payload: dict = None, request: Request = None):
    # G-13: her çağrı ücretli/uzak bir embedding + vektör arama + log yazımı
    # yapıyordu; admin kapısı ve hız sınırı yoktu. İkisi de eklendi.
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    if not rate_limit("memory-retrieve", rate_per_sec=1.0, burst=5):
        raise HTTPException(status_code=429, detail="Hafıza sorgusu çok sık çağrıldı; lütfen bekleyin")
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

