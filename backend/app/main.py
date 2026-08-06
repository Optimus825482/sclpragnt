import os
import asyncio
import time
import subprocess
import json
import tempfile
import random
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import config
from app.market_intelligence import (estimate_local_regime, execution_quality,
                                     symbol_safety, cost_aware_trade_metrics,
                                     walk_forward_assessment)
from app.self_learning import build_learning_context
from app.market_data import MarketData
from app.analyzer import ScalpAnalyzer
from app import database
from app.backtest import run_backtest, run_custom_backtest
from app.binance_tr_public import klines as fetch_klines, historical_klines, trading_symbols, ticker_24h, orderbook
from app.technical_analysis import calculate_snapshot
from app import llm_analysis
from app.embedding_worker import worker as embedding_worker, trade_document, signal_document
from app.memory_service import build_document
from app import memory_service
from app import migration_monitor
try:
    import asyncpg
except ImportError:
    asyncpg = None

app = FastAPI(title="Scalper Agent V4 - Paper Trading")
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3004,http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

market = MarketData(config.SYMBOLS)
analyzer = ScalpAnalyzer(market)
_pg_pool = None
_embedding_backfill = {"status": "idle", "queued": 0, "message": None}
_embedding_repair = {"status": "idle", "queued": 0, "message": None}
_trade_repair = {"status": "idle", "phase": "idle", "progress": 0, "message": None, "logs": [], "preview": None, "result": None}
_llm_replenish_lock = asyncio.Lock()

async def _public_json(url, timeout=10):
    def read():
        request = Request(url, headers={"User-Agent": "ScalperAgent/4.0"})
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    return await asyncio.to_thread(read)

@app.get("/api/btc-5min-scan")
async def btc_5min_scan():
    raise HTTPException(status_code=410, detail="BTC_5M_ODDS_SCALPER sistemden kaldırıldı")
    """Return a read-only BTC 5-minute Up/Down signal summary (S1-S6)."""
    try:
        candles = await _public_json("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=60")
        ticker = await _public_json("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT")
        now = int(time.time()); window = now // 300 * 300
        markets = await _public_json("https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=100")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Public market data unavailable: {exc}") from exc
    parsed = [{"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in candles if len(k) >= 6]
    if len(parsed) < 25: raise HTTPException(status_code=502, detail="Insufficient 1m candles")
    price = parsed[-1]["close"]; changes = [x["close"] - x["open"] for x in parsed]
    ema9 = sum(x["close"] for x in parsed[-9:]) / 9; ema21 = sum(x["close"] for x in parsed[-21:]) / 21
    ema_dir = "UP" if ema9 > ema21 else "DOWN" if ema9 < ema21 else "FLAT"
    mom5 = sum(changes[-5:]); range5 = max(x["high"] for x in parsed[-5:]) - min(x["low"] for x in parsed[-5:])
    gains = sum(max(x, 0) for x in changes[-14:]); losses = sum(max(-x, 0) for x in changes[-14:]); rsi = 100 if not losses and gains else 50 if not losses else 100 - 100 / (1 + gains / losses)
    s1 = "UP" if all(x > 0 for x in changes[-2:]) else "DOWN" if all(x < 0 for x in changes[-2:]) else "NONE"
    s2 = ema_dir if ema_dir in {"UP", "DOWN"} else "NONE"
    s3 = "UP" if rsi < 30 else "DOWN" if rsi > 70 else "NONE"
    avg_volume = sum(x["volume"] for x in parsed[-26:-1]) / 25; volume_ratio = parsed[-1]["volume"] / avg_volume if avg_volume else 0
    utc_hour = datetime.now(timezone.utc).hour
    s4 = "DOWN" if utc_hour >= 15 and mom5 > 200 else "UP" if utc_hour >= 15 and mom5 < -200 else "NONE"
    if isinstance(markets, dict):
        markets = markets.get("data") or markets.get("markets") or []
    candidates = []
    for item in markets if isinstance(markets, list) else []:
        question = str(item.get("question", "")).lower()
        slug = str(item.get("slug", "")).lower()
        is_btc = "bitcoin" in question or slug.startswith("btc-")
        is_binary = ("up" in question and "down" in question) or "updown" in slug
        is_5m = any(marker in slug for marker in ("5m", "5-min", "5_min")) or any(marker in question for marker in ("5 minute", "5 minutes", "5-minute"))
        if is_btc and is_binary and is_5m and item.get("active") is not False and item.get("closed") is not True:
            candidates.append(item)
    market = sorted(candidates, key=lambda item: str(item.get("endDate") or item.get("endDateIso") or ""))[-1] if candidates else None
    if market is None:
        # Gamma's paginated active list can omit the short-lived market. Try
        # the documented event-by-slug shape for the current and next window.
        for slug in (
            f"btc-updown-5m-{window}",
            f"btc-updown-5m-{window + 300}",
            f"btc-up-or-down-5m-{window}",
            f"btc-up-or-down-5m-{window + 300}",
            f"bitcoin-up-or-down-5m-{window}",
            f"bitcoin-up-or-down-5m-{window + 300}",
        ):
            try:
                direct = await _public_json(f"https://gamma-api.polymarket.com/events/slug/{slug}")
                direct_markets = direct.get("markets") if isinstance(direct, dict) else None
                if isinstance(direct_markets, list) and direct_markets:
                    market = direct_markets[0]
                    break
                if isinstance(direct, dict) and direct.get("clobTokenIds"):
                    market = direct
                    break
            except Exception:
                continue
    prices = market.get("outcomePrices") if market else None
    if isinstance(prices, str):
        try: prices = json.loads(prices)
        except json.JSONDecodeError: prices = None
    up_price = float(prices[0]) if isinstance(prices, list) and len(prices) >= 2 else None; down_price = float(prices[1]) if isinstance(prices, list) and len(prices) >= 2 else None
    odds_source = "polymarket_gamma"
    if market and (up_price is None or down_price is None):
        token_ids = market.get("clobTokenIds") or []
        if isinstance(token_ids, str):
            try: token_ids = json.loads(token_ids)
            except json.JSONDecodeError: token_ids = []
        if isinstance(token_ids, list) and len(token_ids) >= 2:
            try:
                up_quote = await _public_json("https://clob.polymarket.com/price?" + urlencode({"token_id": token_ids[0], "side": "BUY"}))
                down_quote = await _public_json("https://clob.polymarket.com/price?" + urlencode({"token_id": token_ids[1], "side": "BUY"}))
                up_price = float(up_quote.get("price")); down_price = float(down_quote.get("price"))
                odds_source = "polymarket_clob"
            except Exception:
                up_price = down_price = None
    s5 = "UP" if up_price is not None and up_price < 0.45 else "DOWN" if down_price is not None and down_price < 0.45 else "UNKNOWN"
    support, resistance = float(ticker.get("lowPrice", 0)), float(ticker.get("highPrice", 0))
    s6 = "UP" if support and (price - support) / price < 0.003 else "DOWN" if resistance and (resistance - price) / price < 0.003 else "NONE"
    session = "ASIAN_MOMENTUM" if 3 <= datetime.now(timezone.utc).hour < 7 else "US_REVERSION" if 15 <= datetime.now(timezone.utc).hour < 18 else "DANGER" if 13 <= datetime.now(timezone.utc).hour < 14 else "NEUTRAL"
    active = [s1, s2, s3, s4, s5, s6]; up = sum(x == "UP" for x in active); down = sum(x == "DOWN" for x in active)
    verdict = "SKIP - danger zone" if session == "DANGER" else "ENTER UP" if up >= 2 and up > down else "ENTER DOWN" if down >= 2 and down > up else "SKIP - one signal only" if up or down else "SKIP - no signal"
    matched_count = len(candidates) if candidates else (1 if market else 0)
    return {"symbol": "BTCUSDT", "window_start": window, "price": price, "session": session, "ema": {"ema9": ema9, "ema21": ema21, "direction": ema_dir}, "rsi": rsi, "momentum_5m": mom5, "range_5m": range5, "volume_ratio": volume_ratio, "signals": {"S1_momentum": s1, "S2_ema": s2, "S3_rsi": s3, "S4_mean_reversion": s4, "S5_odds_bias": s5, "S6_support_resistance": s6}, "odds": {"available": up_price is not None and down_price is not None, "up": up_price, "down": down_price, "market_slug": market.get("slug") if market else None, "source": odds_source if market else "unavailable"}, "levels": {"support_24h": support, "resistance_24h": resistance}, "up_signals": up, "down_signals": down, "verdict": verdict, "paper_only": True, "odds_diagnostics": {"gamma_market_count": len(markets) if isinstance(markets, list) else 0, "matched_market_count": matched_count}}

@app.get("/api/btc-5min-backtest")
async def btc_5min_backtest(days_back: int = 7, order_size: float = 500.0, take_profit_pct: float = 0.01, stop_loss_pct: float = 0.02):
    raise HTTPException(status_code=410, detail="BTC_5M_ODDS_SCALPER sistemden kaldırıldı")
    """Replay recorded BTC odds signals against real BTCTRY 5m candles.

    Historical Polymarket odds are not reconstructed or invented. Only
    recorded BUY_SIGNAL entries are evaluated; missing odds remain reported.
    """
    days_back = max(1, min(int(days_back), 90)); order_size = max(100.0, min(float(order_size), 10000.0))
    candles = await historical_klines("BTCTRY", "5m", days_back)
    rows = []
    for row in candles:
        if len(row) >= 7:
            rows.append({"time": float(row[0]) / 1000, "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4])})
    if not rows: raise HTTPException(status_code=502, detail="BTCTRY 5m geçmiş verisi alınamadı")
    signals = await database.get_decision_logs(5000, "BTCTRY", "BTC_5M_ODDS_SCALPER")
    candidates = [s for s in signals if s.get("decision") == "BUY_SIGNAL"]
    commission_pct = config.COMMISSION_PCT
    trades = []; missing_candle = 0; incomplete_forward_window = 0
    for signal in sorted(candidates, key=lambda item: float(item.get("timestamp") or 0)):
        entry_time = float(signal.get("timestamp") or 0)
        index = min(range(len(rows)), key=lambda i: abs(rows[i]["time"] - entry_time))
        if abs(rows[index]["time"] - entry_time) > 600: missing_candle += 1; continue
        if len(rows) - index < 49:
            incomplete_forward_window += 1
            continue
        entry = rows[index]["close"]; exit_price = None; reason = "max_hold_4h"
        end = min(len(rows), index + 48 + 1)
        for candle in rows[index + 1:end]:
            if candle["low"] <= entry * (1 - stop_loss_pct): exit_price = entry * (1 - stop_loss_pct); reason = "hard_stop_loss"; break
            if candle["high"] >= entry * (1 + take_profit_pct): exit_price = entry * (1 + take_profit_pct); reason = "profit_target"; break
        if exit_price is None: exit_price = rows[end - 1]["close"]
        gross = order_size * ((exit_price / entry) - 1); commission = (order_size + order_size * (exit_price / entry)) * commission_pct; net = gross - commission
        trades.append({"signal_id": signal.get("id"), "entry": entry, "exit": exit_price, "gross_pnl": gross, "commission": commission, "net_pnl": net, "reason": reason, "hold_minutes": round((rows[min(end - 1, len(rows) - 1)]["time"] - rows[index]["time"]) / 60, 2)})
    wins = sum(1 for trade in trades if trade["net_pnl"] > 0); net = sum(trade["net_pnl"] for trade in trades); commission = sum(trade["commission"] for trade in trades)
    return {"strategy": "BTC_5M_ODDS_SCALPER", "symbol": "BTCTRY", "days_back": days_back, "source": "recorded_signals_plus_binance_tr_public_5m", "odds_policy": "historical_odds_not_invented", "total_signals": len(candidates), "evaluated_trades": len(trades), "missing_candle_matches": missing_candle, "incomplete_forward_window": incomplete_forward_window, "wins": wins, "losses": len(trades) - wins, "win_rate": round(wins / len(trades) * 100, 2) if trades else 0, "net_pnl": round(net, 4), "commission": round(commission, 4), "trades": trades, "paper_only": True}

def _repair_log(level, message):
    _trade_repair["logs"].append({"time": time.time(), "level": level, "message": message})
    _trade_repair["logs"] = _trade_repair["logs"][-100:]

def _chat_memory_document(messages, *, layer="session", symbol=None, strategy=None, session_id="default"):
    recent = [m for m in (messages or [])[-4:] if isinstance(m, dict)]
    content = json.dumps(recent, ensure_ascii=False, default=str)
    return build_document(layer=layer, scope=session_id, symbol=symbol, strategy=strategy,
                          source_type="chat_message", source_id=f"{session_id}:{len(messages or [])}",
                          content=content, metadata={"session_id": session_id, "message_count": len(messages or [])})

async def _persist_chat_memory(messages, **kwargs):
    if _pg_pool and messages:
        embedding_worker.enqueue_nowait(_chat_memory_document(messages, **kwargs))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WELL_KNOWN_DIR = os.path.join(BASE_DIR, "..", ".well-known")
app.mount("/.well-known", StaticFiles(directory=WELL_KNOWN_DIR), name="wellknown")

class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections: self.active_connections.remove(ws)
    async def broadcast(self, message: dict):
        for c in list(self.active_connections):
            try: await c.send_json(message)
            except: self.disconnect(c)

ws_manager = ConnectionManager()

@app.on_event("startup")
async def startup():
    global _pg_pool
    await database.init_db()
    await analyzer.load_state()
    if os.getenv("DB_BACKEND", "sqlite").lower() == "postgres" and asyncpg and os.getenv("DATABASE_URL"):
        try:
            _pg_pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=4)
            await embedding_worker.start(_pg_pool, llm_analysis.embedding)
        except Exception as exc:
            print(f"[Memory] PostgreSQL/embedding worker başlatılamadı: {exc}")
    asyncio.create_task(market.connect())
    asyncio.create_task(strategy_loop())
    asyncio.create_task(radar_loop())
    asyncio.create_task(ws_broadcast_loop())

@app.on_event("shutdown")
async def shutdown():
    global _pg_pool
    market.stop()
    await embedding_worker.stop()
    if _pg_pool:
        await _pg_pool.close()
    await database.close_db()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: ws_manager.disconnect(websocket)

async def ws_broadcast_loop():
    while True:
        if market.tickers:
            tickers = []
            for t in market.tickers.values():
                item = dict(t)
                item["avg_volume"] = market.get_avg_volume(t["symbol"])
                tickers.append(item)
            await ws_manager.broadcast({"type": "tickers", "data": tickers})

            try_bal = await database.get_wallet_balance("TRY")
            total_value = try_bal
            open_positions = []
            for sym, pos in analyzer.positions.items():
                ticker = market.get_ticker(sym)
                # A stale/missing ticker must not make a real open position
                # disappear from equity or reconciliation. Mark it at entry
                # until a fresh public price arrives.
                current_price = float((ticker or {}).get("last_price") or pos["entry_price"])
                current_value = pos["quantity"] * current_price
                total_value += current_value
                gross_pnl_try = (current_price - pos["entry_price"]) * pos["quantity"]
                entry_commission = pos["entry_price"] * pos["quantity"] * config.COMMISSION_PCT
                pnl_try = gross_pnl_try - entry_commission
                pnl_pct = (pnl_try / (pos["entry_price"] * pos["quantity"]) * 100) if pos["entry_price"] and pos["quantity"] else 0.0
                open_positions.append({
                    "symbol": sym, "entry": pos["entry_price"], "current": current_price,
                    "pnl_pct": pnl_pct, "pnl_try": pnl_try, "value": current_value,
                    "strategy": pos.get("strategy", "UT"), "price_stale": ticker is None
                })
            realized_pnl = await database.get_realized_pnl()
            unrealized_pnl = sum(item["pnl_try"] for item in open_positions)
            open_entry_commission = sum(pos["entry_price"] * pos["quantity"] * config.COMMISSION_PCT for pos in analyzer.positions.values())
            reconciliation_expected = config.INITIAL_BALANCE_TRY + realized_pnl + unrealized_pnl - open_entry_commission
            reconciliation_delta = total_value - reconciliation_expected
            await ws_manager.broadcast({
                "type": "portfolio",
                "data": {"try": try_bal, "total_value": total_value, "realized_pnl": realized_pnl,
                         "unrealized_pnl": unrealized_pnl, "reconciliation_expected": reconciliation_expected,
                         "reconciliation_delta": reconciliation_delta, "positions": open_positions}
            })
        await asyncio.sleep(1.0)

async def strategy_loop():
    await asyncio.sleep(5)
    while True:
        for sym in config.SYMBOLS:
            if migration_monitor.state["status"] == "running":
                await asyncio.sleep(0.1)
                continue
            ticker = market.get_ticker(sym)
            if not ticker or (time.time() - (ticker.get("timestamp", 0) / 1000)) > config.MAX_TICKER_AGE_SEC:
                continue
            try:
                signals = await analyzer.evaluate(sym, ticker)
            except Exception as exc:
                # Tek bir sembolün DB/strateji hatası bütün strategy loop'u düşürmemeli.
                print(f"[Strategy] {sym} değerlendirme hatası: {exc}")
                continue
            for sig in signals:
                print(f"[Sinyal] {sig}")
                await ws_manager.broadcast({"type": "signal", "data": sig})
                if str(sig.get("action", "")).startswith("CLOSE"):
                    await ws_manager.broadcast({"type": "trade_updated", "data": {"symbol": sig.get("symbol"), "reason": sig.get("reason")}})
                    asyncio.create_task(llm_replenish_after_close())
        await asyncio.sleep(2)

async def radar_loop():
    await asyncio.sleep(15)
    while True:
        if migration_monitor.state["status"] == "running":
            await asyncio.sleep(1)
            continue
        try:
            await gainers_radar(execute=True)
        except Exception as exc:
            print(f"[Radar] otomatik tarama hatası: {exc}")
            await asyncio.sleep(30)

async def llm_replenish_after_close():
    """Replace each closed paper position with one fresh eligible candidate."""
    if (await database.get_llm_setting("llm_auto_paper_enabled", "0")) != "1":
        return
    if (await database.get_llm_setting("llm_paper_trade_enabled", "0")) != "1":
        return
    async with _llm_replenish_lock:
        if len(analyzer.positions) >= analyzer.max_open_positions():
            return
        try:
            await llm_open_paper_trade({"source": "llm_after_close"})
        except Exception as exc:
            print(f"[LLM replenish] yeni aday bulunamadı: {exc}")

@app.get("/health")
async def health():
    age = time.time() - market.last_event_at if market.last_event_at else None
    return {
        "status": "alive" if market.running and (age is None or age <= config.MAX_TICKER_AGE_SEC * 2) else "degraded",
        "mode": "paper", "market_data": "binance_tr_public",
        "history_loaded": market.history_loaded, "ticker_age_sec": age,
        "market_error": market.last_error, "open_positions": list(analyzer.positions.keys())
    }

@app.get("/api/system/health")
async def system_health():
    now_ms = time.time() * 1000
    ages = [max(0.0, (now_ms - float(t.get("timestamp", now_ms))) / 1000) for t in market.tickers.values() if t.get("timestamp")]
    vector_status = "not_checked_until_postgres_backend_is_enabled"
    db_status = "sqlite"
    if _pg_pool:
        try:
            async with _pg_pool.acquire() as conn:
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
    return {"status": "degraded" if db_status.startswith("postgres_error") or llm_error else "ok", "generated_at": time.time(), "market": {"symbols": len(market.symbols), "tickers": len(market.tickers), "max_ticker_age_sec": max(ages) if ages else None, "timeframes": market.timeframes}, "portfolio": {"open_positions": len(analyzer.positions), "max_open_positions": analyzer.max_open_positions()}, "database": {"backend": os.getenv("DB_BACKEND", "sqlite"), "status": db_status, "postgres_configured": bool(os.getenv("DATABASE_URL", "").strip()), "vector_extension": vector_status}, "embedding": embedding_worker.snapshot(), "websocket_clients": len(ws_manager.active_connections), "llm": {"configured": bool(os.getenv("LLM_ENCRYPTION_KEY", "").strip()), "active": llm_active, "error": llm_error}}

@app.get("/api/memory/status")
async def memory_status():
    persistent = {"documents": 0, "embedded": 0}
    if _pg_pool:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS documents, COUNT(*) FILTER (WHERE embedding_status='ready') AS embedded FROM memory_documents")
            persistent = {"documents": int(row["documents"]), "embedded": int(row["embedded"])}
    return {"enabled": bool(_pg_pool), "backend": os.getenv("DB_BACKEND", "sqlite"), "worker": embedding_worker.snapshot(), "persistent": persistent, "backfill": dict(_embedding_backfill), "repair": dict(_embedding_repair), "message": None if _pg_pool else "PostgreSQL memory backend aktif değil"}

@app.post("/api/memory/backfill")
async def memory_backfill():
    if not _pg_pool: raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    if _embedding_backfill["status"] == "running": return {"ok": False, **_embedding_backfill}
    _embedding_backfill.update({"status": "running", "queued": 0, "message": "Kayıtlar embedding kuyruğuna alınıyor"})
    async def enqueue_existing():
        try:
            queued = 0
            async with _pg_pool.acquire() as conn:
                trades = [dict(row) for row in await conn.fetch("SELECT * FROM trades ORDER BY id")]
                signals = [dict(row) for row in await conn.fetch("SELECT * FROM signals ORDER BY id")]
            for trade in trades:
                doc = trade_document("historical", trade.get("symbol") or "unknown", trade, {"action": "HISTORICAL_TRADE", "timestamp": trade.get("exit_time")})
                queued += int(embedding_worker.enqueue_nowait(doc))
            for signal in signals:
                queued += int(embedding_worker.enqueue_nowait(signal_document(signal)))
            _embedding_backfill.update({"status": "completed", "queued": queued, "message": "Embedding kuyruğu hazır; worker kayıtları işliyor"})
        except Exception as exc:
            _embedding_backfill.update({"status": "error", "message": str(exc)})
    asyncio.create_task(enqueue_existing(), name="embedding-backfill")
    return {"ok": True, **_embedding_backfill}

@app.post("/api/memory/repair-historical")
async def repair_historical_memory():
    """Rebuild historical trade memory without inventing unavailable market data."""
    if not _pg_pool: raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    if _embedding_repair["status"] == "running": return {"ok": False, **_embedding_repair}
    _embedding_repair.update({"status": "running", "queued": 0, "message": "Tarihsel snapshot'lar onarılıyor"})
    async def repair():
        try:
            queued = 0
            async with _pg_pool.acquire() as conn:
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
                    queued += int(embedding_worker.enqueue_nowait(doc))
            _embedding_repair.update({"status": "completed", "queued": queued, "message": "Eksik tarihsel likidite alanları tahmin edilmeden yeniden embedding kuyruğuna alındı"})
        except Exception as exc:
            _embedding_repair.update({"status": "error", "message": str(exc)})
    asyncio.create_task(repair(), name="historical-memory-repair")
    return {"ok": True, **_embedding_repair}

@app.get("/api/migration/status")
async def migration_status():
    return dict(migration_monitor.state)

@app.post("/api/migration/start")
async def migration_start(payload: dict = None):
    body = payload or {}
    source = str(body.get("source") or os.getenv("MIGRATION_SOURCE_PATH") or database.DB_NAME)
    if migration_monitor.state["status"] == "running": return {"ok": False, "message": "Migration zaten çalışıyor"}
    try: info = migration_monitor.inspect_source(source)
    except Exception as exc: raise HTTPException(status_code=400, detail=str(exc))
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url: raise HTTPException(status_code=503, detail="DATABASE_URL tanımlı değil")
    migration_monitor.state.update({"source":info, "status":"queued", "phase":"queued", "progress":0, "message":"Migration kuyruğa alındı"})
    asyncio.create_task(migration_monitor.run(source, database_url), name="sqlite-postgres-migration")
    return {"ok":True, "source":info}

@app.post("/api/memory/retrieve")
async def memory_retrieve(payload: dict = None):
    if not _pg_pool: raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    body = payload or {}
    text = str(body.get("query", "")).strip()
    if not text: raise HTTPException(status_code=400, detail="query gerekli")
    embedded = await llm_analysis.embedding(text, body.get("model_id"))
    if embedded.get("status") == "disabled":
        return {"query": text, "results": [], "count": 0, "status": "disabled", "message": embedded.get("error", "Embedding modeli aktif değil")}
    if embedded.get("status") != "ok": raise HTTPException(status_code=502, detail=embedded.get("error", "Embedding üretilemedi"))
    requested_symbol = str(body.get("symbol")).strip().upper() if body.get("symbol") else None
    async with _pg_pool.acquire() as conn:
        rows = await memory_service.retrieve(conn, embedded["vector"], limit=body.get("limit", 8), layer=body.get("layer"), symbol=requested_symbol, strategy=body.get("strategy"), timeframe=body.get("timeframe"), model_id=embedded.get("model_id"))
        await conn.execute("INSERT INTO memory_retrieval_logs(query_scope,query_text_hash,filters,model_id,result_ids,latency_ms) VALUES($1,$2,$3::jsonb,$4,$5::jsonb,$6)", body.get("scope", "memory"), memory_service.content_hash(text), json.dumps({k: body.get(k) for k in ("layer", "symbol", "strategy", "timeframe") if body.get(k) is not None}), embedded.get("model_id"), json.dumps([r.get("id") for r in rows]), None)
    return {"query": text, "results": rows, "count": len(rows)}

CONFIG_FIELDS = {
    "gainer_radar_min_score": "GAINER_RADAR_MIN_SCORE",
    "min_notional": "MIN_NOTIONAL",
    "min_24h_quote_volume_try": "MIN_24H_QUOTE_VOLUME_TRY",
    "high_liquidity_bypass_volume_try": "HIGH_LIQUIDITY_BYPASS_VOLUME_TRY",
    "min_volume_ratio": "MIN_VOLUME_RATIO",
    "max_spread_pct": "MAX_SPREAD_PCT",
    "min_orderbook_depth_multiplier": "MIN_ORDERBOOK_DEPTH_MULTIPLIER",
    "liquidity_filter_enabled": "LIQUIDITY_FILTER_ENABLED",
    "default_order_usdt": "DEFAULT_ORDER_USDT",
    "max_open_positions": "MAX_OPEN_POSITIONS",
    "take_profit_pct": "SPOT_PROFIT_TARGET_PCT",
    "hard_stop_loss_pct": "HARD_STOP_LOSS_PCT",
    "cooldown_bars": "COOLDOWN_BARS",
    "orderflow_min_imbalance": "ORDERFLOW_MIN_IMBALANCE",
    "momentum_short_lookback": "MOMENTUM_SHORT_LOOKBACK",
    "momentum_long_lookback": "MOMENTUM_LONG_LOOKBACK",
    "momentum_min_return_pct": "MOMENTUM_MIN_RETURN_PCT",
    "momentum_min_volume_ratio": "MOMENTUM_MIN_VOLUME_RATIO",
    "momentum_require_mtf_alignment": "MOMENTUM_REQUIRE_MTF_ALIGNMENT",
    "adr_filter_enabled": "ADR_FILTER_ENABLED",
    "adr_period": "ADR_PERIOD",
    "adr_min_pct": "ADR_MIN_PCT",
    "adr_max_utilization_pct": "ADR_MAX_UTILIZATION_PCT",
    "adr_min_remaining_pct": "ADR_MIN_REMAINING_PCT",
    "keltner_ema_period": "KELTNER_EMA_PERIOD",
    "keltner_atr_period": "KELTNER_ATR_PERIOD",
    "keltner_atr_multiplier": "KELTNER_ATR_MULTIPLIER",
    "keltner_volume_multiplier": "KELTNER_VOLUME_MULTIPLIER",
    "keltner_require_mtf_alignment": "KELTNER_REQUIRE_MTF_ALIGNMENT",
    "ema_vwap_min_volume_ratio": "EMA_VWAP_MIN_VOLUME_RATIO",
    "ema_vwap_min_adx": "EMA_VWAP_MIN_ADX",
    "ema_vwap_require_mtf_alignment": "EMA_VWAP_REQUIRE_MTF_ALIGNMENT",
    "chop_period": "CHOP_PERIOD",
    "chop_max_value": "CHOP_MAX_VALUE",
    "chop_min_rsi": "CHOP_MIN_RSI",
    "donchian_lookback": "DONCHIAN_LOOKBACK",
    "donchian_volume_multiplier": "DONCHIAN_VOLUME_MULTIPLIER",
    "ut_enabled": "UT_ENABLED",
    "ut_key_value": "UT_KEY_VALUE",
    "ut_atr_period": "UT_ATR_PERIOD",
    "ut_heikin_ashi": "UT_HEIKIN_ASHI",
    "ut_timeframe": "UT_TIMEFRAME",
    "bb_squeeze_enabled": "BB_SQUEEZE_ENABLED",
    "ema_pullback_enabled": "EMA_PULLBACK_ENABLED",
    "vwap_macd_enabled": "VWAP_MACD_ENABLED",
    "cmo_crsi_enabled": "CMO_CRSI_ENABLED",
    "ema_vwap_enabled": "EMA_VWAP_ENABLED",
    "breakout_enabled": "BREAKOUT_ENABLED",
    "orderflow_enabled": "ORDERFLOW_ENABLED",
    "momentum_enabled": "MOMENTUM_ENABLED",
    "mean_reversion_enabled": "MEAN_REVERSION_ENABLED",
    "keltner_enabled": "KELTNER_ENABLED", "chop_enabled": "CHOP_ENABLED", "donchian_enabled": "DONCHIAN_ENABLED",
    "bb_squeeze_timeframe": "BB_SQUEEZE_TIMEFRAME",
    "ema_pullback_timeframe": "EMA_PULLBACK_TIMEFRAME",
    "vwap_macd_timeframe": "VWAP_MACD_TIMEFRAME",
    "cmo_crsi_timeframe": "CMO_CRSI_TIMEFRAME",
    "ema_vwap_timeframe": "EMA_VWAP_TIMEFRAME",
    "breakout_timeframe": "BREAKOUT_TIMEFRAME",
    "orderflow_timeframe": "ORDERFLOW_TIMEFRAME",
    "momentum_timeframe": "MOMENTUM_TIMEFRAME",
    "mean_reversion_timeframe": "MEAN_REVERSION_TIMEFRAME",
    "keltner_timeframe": "KELTNER_TIMEFRAME", "chop_timeframe": "CHOP_TIMEFRAME", "donchian_timeframe": "DONCHIAN_TIMEFRAME",
    "squeeze_lookback": "SQUEEZE_LOOKBACK",
    "bb_period": "BB_PERIOD",
    "bb_std_dev": "BB_STD_DEV",
    "ema_short": "EMA_SHORT",
    "ema_mid": "EMA_MID",
    "ema_trend": "EMA_TREND",
    "rsi_period": "RSI_PERIOD",
    "vwap_period": "VWAP_PERIOD",
    "macd_fast": "MACD_FAST",
    "macd_slow": "MACD_SLOW",
    "macd_signal": "MACD_SIGNAL",
}

BOOL_FIELDS = {"liquidity_filter_enabled", "adr_filter_enabled", "ut_enabled", "ut_heikin_ashi", "bb_squeeze_enabled", "ema_pullback_enabled", "vwap_macd_enabled", "cmo_crsi_enabled", "ema_vwap_enabled", "breakout_enabled", "orderflow_enabled", "momentum_enabled", "mean_reversion_enabled", "keltner_enabled", "chop_enabled", "donchian_enabled", "momentum_require_mtf_alignment", "keltner_require_mtf_alignment", "ema_vwap_require_mtf_alignment"}
INT_FIELDS = {"gainer_radar_min_score", "max_open_positions", "adr_period", "cooldown_bars", "momentum_short_lookback", "momentum_long_lookback", "keltner_ema_period", "keltner_atr_period", "chop_period", "donchian_lookback", "squeeze_lookback", "bb_period", "ema_short", "ema_mid", "ema_trend", "rsi_period", "vwap_period", "macd_fast", "macd_slow", "macd_signal", "ut_atr_period"}
STR_FIELDS = {"ut_timeframe", "bb_squeeze_timeframe", "ema_pullback_timeframe", "vwap_macd_timeframe", "cmo_crsi_timeframe", "ema_vwap_timeframe", "breakout_timeframe", "orderflow_timeframe", "momentum_timeframe", "mean_reversion_timeframe", "keltner_timeframe", "chop_timeframe", "donchian_timeframe"}

@app.get("/api/config")
async def get_config():
    return {
        "gainer_radar_min_score": config.GAINER_RADAR_MIN_SCORE,
        "symbols": config.SYMBOLS,
        "min_notional": config.MIN_NOTIONAL,
        "min_24h_quote_volume_try": config.MIN_24H_QUOTE_VOLUME_TRY,
        "high_liquidity_bypass_volume_try": config.HIGH_LIQUIDITY_BYPASS_VOLUME_TRY,
        "min_volume_ratio": config.MIN_VOLUME_RATIO,
        "max_spread_pct": config.MAX_SPREAD_PCT,
        "min_orderbook_depth_multiplier": config.MIN_ORDERBOOK_DEPTH_MULTIPLIER,
        "liquidity_filter_enabled": config.LIQUIDITY_FILTER_ENABLED,
        "default_order_usdt": config.DEFAULT_ORDER_USDT,
        "max_open_positions": max(1, int(config.MAX_OPEN_POSITIONS)),
        "hard_stop_loss_pct": config.HARD_STOP_LOSS_PCT,
        "cooldown_bars": config.COOLDOWN_BARS,
        "orderflow_min_imbalance": config.ORDERFLOW_MIN_IMBALANCE,
        "momentum_short_lookback": config.MOMENTUM_SHORT_LOOKBACK,
        "momentum_long_lookback": config.MOMENTUM_LONG_LOOKBACK,
        "momentum_min_return_pct": config.MOMENTUM_MIN_RETURN_PCT,
        "momentum_min_volume_ratio": config.MOMENTUM_MIN_VOLUME_RATIO,
        "momentum_require_mtf_alignment": config.MOMENTUM_REQUIRE_MTF_ALIGNMENT,
        "adr_filter_enabled": config.ADR_FILTER_ENABLED,
        "adr_period": config.ADR_PERIOD,
        "adr_min_pct": config.ADR_MIN_PCT,
        "adr_max_utilization_pct": config.ADR_MAX_UTILIZATION_PCT,
        "adr_min_remaining_pct": config.ADR_MIN_REMAINING_PCT,
        "keltner_ema_period": config.KELTNER_EMA_PERIOD,
        "keltner_atr_period": config.KELTNER_ATR_PERIOD,
        "keltner_atr_multiplier": config.KELTNER_ATR_MULTIPLIER,
        "keltner_volume_multiplier": config.KELTNER_VOLUME_MULTIPLIER,
        "keltner_require_mtf_alignment": config.KELTNER_REQUIRE_MTF_ALIGNMENT,
        "ema_vwap_min_volume_ratio": config.EMA_VWAP_MIN_VOLUME_RATIO,
        "ema_vwap_min_adx": config.EMA_VWAP_MIN_ADX,
        "ema_vwap_require_mtf_alignment": config.EMA_VWAP_REQUIRE_MTF_ALIGNMENT,
        "chop_period": config.CHOP_PERIOD,
        "chop_max_value": config.CHOP_MAX_VALUE,
        "chop_min_rsi": config.CHOP_MIN_RSI,
        "donchian_lookback": config.DONCHIAN_LOOKBACK,
        "donchian_volume_multiplier": config.DONCHIAN_VOLUME_MULTIPLIER,
        "take_profit_pct": config.SPOT_PROFIT_TARGET_PCT,
        "trailing_stop_pct": 0.0,
        "ut_enabled": config.UT_ENABLED,
        "ut_symbols": config.UT_SYMBOLS,
        "ut_key_value": config.UT_KEY_VALUE,
        "ut_atr_period": config.UT_ATR_PERIOD,
        "ut_heikin_ashi": config.UT_HEIKIN_ASHI,
        "ut_timeframe": config.UT_TIMEFRAME,
        "bb_squeeze_enabled": config.BB_SQUEEZE_ENABLED,
        "ema_pullback_enabled": config.EMA_PULLBACK_ENABLED,
        "vwap_macd_enabled": config.VWAP_MACD_ENABLED,
        "cmo_crsi_enabled": config.CMO_CRSI_ENABLED,
        "ema_vwap_enabled": config.EMA_VWAP_ENABLED, "breakout_enabled": config.BREAKOUT_ENABLED,
        "orderflow_enabled": config.ORDERFLOW_ENABLED, "momentum_enabled": config.MOMENTUM_ENABLED,
        "mean_reversion_enabled": config.MEAN_REVERSION_ENABLED,
        "keltner_enabled": config.KELTNER_ENABLED, "chop_enabled": config.CHOP_ENABLED, "donchian_enabled": config.DONCHIAN_ENABLED,
        "bb_squeeze_timeframe": config.BB_SQUEEZE_TIMEFRAME,
        "ema_pullback_timeframe": config.EMA_PULLBACK_TIMEFRAME,
        "vwap_macd_timeframe": config.VWAP_MACD_TIMEFRAME,
        "cmo_crsi_timeframe": config.CMO_CRSI_TIMEFRAME,
        "ema_vwap_timeframe": config.EMA_VWAP_TIMEFRAME, "breakout_timeframe": config.BREAKOUT_TIMEFRAME,
        "orderflow_timeframe": config.ORDERFLOW_TIMEFRAME, "momentum_timeframe": config.MOMENTUM_TIMEFRAME,
        "mean_reversion_timeframe": config.MEAN_REVERSION_TIMEFRAME,
        "keltner_timeframe": config.KELTNER_TIMEFRAME, "chop_timeframe": config.CHOP_TIMEFRAME, "donchian_timeframe": config.DONCHIAN_TIMEFRAME,
        "squeeze_lookback": config.SQUEEZE_LOOKBACK,
        "bb_period": config.BB_PERIOD,
        "bb_std_dev": config.BB_STD_DEV,
        "ema_short": config.EMA_SHORT,
        "ema_mid": config.EMA_MID,
        "ema_trend": config.EMA_TREND,
        "rsi_period": config.RSI_PERIOD,
        "vwap_period": config.VWAP_PERIOD,
        "macd_fast": config.MACD_FAST,
        "macd_slow": config.MACD_SLOW,
        "macd_signal": config.MACD_SIGNAL,
        "initial_balance_try": config.INITIAL_BALANCE_TRY,
        "mode": "paper",
        "market_data": "public",
    }

@app.get("/api/market-symbols")
async def get_market_symbols():
    try:
        return {"symbols": await trading_symbols("TRY"), "quote_asset": "TRY"}
    except Exception as exc:
        return {"symbols": [], "quote_asset": "TRY", "error": str(exc)}

@app.get("/api/radar/gainers")
async def gainers_radar(execute: bool = False):
    """Public-data fırsat tarayıcı: pump kovalamaz, devam edebilecek %2 adaylarını sıralar."""
    rows = []
    radar_analyzer = ScalpAnalyzer(None)
    auto_added = []
    try:
        all_tickers = await ticker_24h()
        known_try = set(await trading_symbols("TRY"))
        gainer_candidates = []
        for item in all_tickers:
            symbol = str(item.get("symbol", "")).upper()
            change = float(item.get("priceChangePercent", 0) or 0)
            quote_volume = float(item.get("quoteVolume", 0) or 0)
            if symbol in known_try and 3 <= change <= 18 and quote_volume >= config.MIN_24H_QUOTE_VOLUME_TRY:
                gainer_candidates.append((change, quote_volume, symbol))
        for _, _, symbol in sorted(gainer_candidates, reverse=True)[:10]:
            if symbol not in config.SYMBOLS:
                config.SYMBOLS.append(symbol)
                config.UT_SYMBOLS = list(config.SYMBOLS)
                if symbol.lower() not in market.symbols:
                    market.symbols.append(symbol.lower())
                    market.reconnect_requested = True
                auto_added.append(symbol)
    except Exception as exc:
        print(f"[Radar] gainer tarama hatası: {exc}")
    for symbol in config.SYMBOLS:
        bars = market.get_ut_kline(symbol, "5m")
        closes, volumes = bars.get("closes", []), bars.get("volumes", [])
        if len(closes) < 25 or len(volumes) < 25:
            continue
        price = closes[-1]
        ret_5m = (closes[-1] / closes[-2] - 1) * 100
        ret_1h = (closes[-1] / closes[-13] - 1) * 100 if len(closes) >= 13 else 0
        ret_24h = (closes[-1] / closes[0] - 1) * 100
        avg_volume = sum(volumes[-21:-1]) / 20
        volume_ratio = volumes[-1] / avg_volume if avg_volume else 0
        flow = market.get_orderflow(symbol)
        bid, ask = flow.get("bid_qty", 0), flow.get("ask_qty", 0)
        imbalance = ((bid - ask) / (bid + ask) * 100) if bid + ask else 0
        spread = flow.get("spread_pct") or 999
        ema9 = sum(closes[-9:]) / 9
        ema21 = sum(closes[-21:]) / 21
        trend = price > ema9 > ema21
        crsi = radar_analyzer.calculate_crsi(closes)
        crsi_score = 10 if crsi is not None and 20 <= crsi <= 75 else 0
        score = 0
        score += min(max(volume_ratio / 2, 0), 20)
        score += min(max(imbalance, 0), 25)
        score += 20 if trend else 0
        score += min(max(ret_1h * 3, 0), 15)
        score += 10 if 0 < spread <= 0.20 else 0
        score += crsi_score
        eligible = 3 <= ret_24h <= 18 and ret_1h > 0 and volume_ratio >= 2.0 and spread <= 0.15 and crsi is not None and 20 <= crsi <= 80 and score >= config.GAINER_RADAR_MIN_SCORE
        rows.append({"symbol": symbol, "price": price, "score": round(score, 1), "eligible": eligible,
                     "ret_5m": round(ret_5m, 2), "ret_1h": round(ret_1h, 2), "ret_24h": round(ret_24h, 2),
                     "volume_ratio": round(volume_ratio, 2), "imbalance": round(imbalance, 2), "spread": round(spread, 3), "trend": trend, "crsi": round(crsi, 2) if crsi is not None else None})
    rows.sort(key=lambda row: row["score"], reverse=True)
    radar_trades = []
    if execute and config.GAINER_RADAR_AUTO_TRADE:
        for candidate in [row for row in rows if row["eligible"]][:1]:
            symbol = candidate["symbol"]
            ticker = market.get_ticker(symbol)
            if ticker and symbol not in analyzer.positions:
                bars = market.get_ut_kline(symbol, "5m")
                closes = bars.get("closes", [])
                macd, macd_signal, hist = radar_analyzer.calculate_macd(closes, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL) if len(closes) >= 35 else (None, None, None)
                rsi = radar_analyzer.calculate_rsi(closes, 14) if closes else None
                if macd is not None and hist is not None and macd > macd_signal and hist > 0 and rsi is not None and rsi < 70:
                    signal = await analyzer.open_position(symbol, ticker["last_price"], "LONG", "GAINER_RADAR")
                    if signal:
                        radar_trades.append(signal)
                        await ws_manager.broadcast({"type": "signal", "data": signal})
    return {"items": rows[:20], "auto_added": auto_added, "symbols": config.SYMBOLS, "paper_trades": radar_trades,
            "auto_trade": config.GAINER_RADAR_AUTO_TRADE, "generated_at": time.time(), "model": "public_data_continuation_2pct"}

@app.post("/api/radar/execute")
async def execute_gainers_radar():
    return await gainers_radar(execute=True)

@app.put("/api/config")
async def update_config(payload: dict):
    for key, attr in CONFIG_FIELDS.items():
        if key in payload:
            val = payload[key]
            if key in BOOL_FIELDS:
                if isinstance(val, str):
                    val = val.strip().lower() in {"1", "true", "yes", "on"}
                setattr(config, attr, bool(val))
            elif key in INT_FIELDS:
                number = int(val)
                if key == "adr_period" and not 5 <= number <= 60:
                    raise ValueError("adr_period 5 ile 60 arasında olmalıdır")
                if key == "max_open_positions" and not 1 <= number <= 36:
                    raise ValueError("max_open_positions 1 ile 36 arasında olmalıdır")
                if key == "gainer_radar_min_score" and not 0 <= number <= 100:
                    raise ValueError("gainer_radar_min_score 0 ile 100 arasında olmalıdır")
                setattr(config, attr, number)
            elif key in STR_FIELDS:
                setattr(config, attr, str(val))
            else:
                number = float(val)
                if key in {"min_notional", "default_order_usdt", "min_24h_quote_volume_try", "high_liquidity_bypass_volume_try", "min_volume_ratio", "max_spread_pct", "min_orderbook_depth_multiplier"} and number <= 0:
                    raise ValueError(f"{key} pozitif olmalıdır")
                if key in {"hard_stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "adr_min_pct", "adr_max_utilization_pct", "adr_min_remaining_pct"} and not 0 < number < 1:
                    raise ValueError(f"{key} 0 ile 1 arasında olmalıdır")
                setattr(config, attr, number)
    if "ut_symbols" in payload:
        config.UT_SYMBOLS = payload["ut_symbols"]
    if "symbols" in payload:
        symbols = sorted({str(s).replace("_", "").upper() for s in payload["symbols"] if str(s).strip()})
        allowed = set(await trading_symbols("TRY"))
        invalid = sorted(set(symbols) - allowed)
        if invalid:
            raise ValueError(f"Binance TR'de geçersiz TRY sembolü: {', '.join(invalid)}")
        if not symbols:
            raise ValueError("En az bir aktif sembol seçilmelidir")
        config.SYMBOLS = symbols
        config.UT_SYMBOLS = symbols
        market.symbols = [s.lower() for s in symbols]
    # timeframe değiştiyse market veri setini güncelle
    market.timeframes = market._all_timeframes()
    # Apply symbol/timeframe changes immediately. Settings are runtime-only,
    # but the running websocket/cache must not continue using the old universe.
    market.reconnect_requested = True
    await market.fetch_historical_data()
    analyzer._last_signal_lengths.clear()
    return await get_config()

@app.post("/api/portfolio/reconcile")
async def reconcile_portfolio(payload: dict = None):
    if not (payload or {}).get("confirm", False):
        return {"status": "preview", **await database.preview_portfolio_reconcile()}
    result = await database.reconcile_portfolio()
    # The reconciliation mutates the persistent position set. Keep the
    # long-running analyzer in sync immediately; otherwise its next portfolio
    # broadcast can resurrect positions that were just removed from the DB.
    for item in result.get("removed_overallocated_positions", []):
        analyzer.positions.pop(str(item.get("symbol", "")).upper(), None)
    await ws_manager.broadcast({"type": "portfolio_reconciled", "data": result})
    return {"status": "ok", **result}

@app.get("/api/trade-repair/status")
async def trade_repair_status():
    return dict(_trade_repair)

@app.post("/api/trade-repair/preview")
async def trade_repair_preview():
    if _trade_repair["status"] == "running":
        return {"ok": False, **_trade_repair}
    _trade_repair.update({"status":"preview", "phase":"audit", "progress":10, "message":"Geçmiş işlem bağlantıları denetleniyor", "logs":[], "result":None})
    _repair_log("info", "Salt-okunur onarım önizlemesi başlatıldı")
    preview = await database.preview_trade_repair()
    _trade_repair.update({"progress":100, "message":"Önizleme tamamlandı", "preview":preview})
    _repair_log("info", f"Önizleme tamamlandı: {preview['actions']['assign_trade_ids']} bağlantı adayı")
    return {"ok":True, **_trade_repair}

@app.post("/api/trade-repair/apply")
async def trade_repair_apply(payload: dict = None):
    body = payload or {}
    if body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Onarım için confirm=true gerekli")
    preview = await database.preview_trade_repair()
    _trade_repair.update({"status":"running", "phase":"apply", "progress":15, "message":"Onaylı deterministik onarım uygulanıyor", "preview":preview, "result":None, "logs":[]})
    _repair_log("warning", "Kullanıcı onayı alındı; yalnızca silme yapmayan onarım çalışıyor")
    try:
        result = await database.apply_trade_repair()
        _trade_repair.update({"status":"complete", "phase":"complete", "progress":100, "message":"Onarım tamamlandı", "result":result})
        _repair_log("info", f"Güncellenen trade: {result['updated_trades']}, pozisyon: {result['updated_positions']}, karar logu: {result['enriched_close_logs']}")
        await ws_manager.broadcast({"type":"trade_repair_completed", "data":result})
        return {"ok":True, **_trade_repair}
    except Exception as exc:
        _trade_repair.update({"status":"error", "phase":"error", "message":str(exc)})
        _repair_log("error", str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/trade-repair/legacy-cleanup")
async def legacy_trade_cleanup_preview():
    return {"records": await database.preview_legacy_trade_cleanup(), "requires_confirmation": True}

@app.post("/api/trade-repair/legacy-cleanup")
async def legacy_trade_cleanup_apply(payload: dict = None):
    body = payload or {}
    ids = body.get("trade_ids") or []
    if body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Silme işlemi için confirm=true gerekli")
    try:
        _trade_repair.update({"status":"running", "phase":"legacy_cleanup", "progress":20, "message":"Onaylı legacy kayıt temizliği çalışıyor", "result":None})
        _repair_log("warning", f"Onaylı legacy temizlik başlatıldı: {', '.join(map(str, ids))}")
        result = await database.purge_legacy_trade_records(ids)
        _trade_repair.update({"status":"complete", "phase":"complete", "progress":100, "message":"Legacy kayıt temizliği tamamlandı", "result":result})
        _repair_log("info", f"Legacy kayıt temizlendi: {result['deleted_count']}")
        await ws_manager.broadcast({"type":"trade_repair_completed", "data":result})
        return {"ok":True, **result, "monitor":dict(_trade_repair)}
    except Exception as exc:
        _trade_repair.update({"status":"error", "phase":"error", "progress":100, "message":str(exc)})
        _repair_log("error", str(exc))
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/chart/{symbol}")
async def get_chart_settings(symbol: str):
    data = await database.get_chart_settings(symbol)
    if data is None:
        return {"symbol": symbol, "settings": None}
    return {"symbol": symbol, "settings": data}

@app.put("/api/chart/{symbol}")
async def save_chart_settings(symbol: str, payload: dict):
    await database.save_chart_settings(symbol, payload)
    return {"symbol": symbol, "saved": True}

@app.get("/api/positions")
async def get_positions():
    positions = []
    for sym, pos in analyzer.positions.items():
        ticker = market.get_ticker(sym)
        current = ticker["last_price"] if ticker else pos["entry_price"]
        gross_pnl_try = (current - pos["entry_price"]) * pos["quantity"]
        pnl_try = gross_pnl_try - pos["entry_price"] * pos["quantity"] * config.COMMISSION_PCT
        pnl_pct = (pnl_try / (pos["entry_price"] * pos["quantity"]) * 100) if pos["entry_price"] and pos["quantity"] else 0.0
        positions.append({
            "symbol": sym,
            "side": pos["side"],
            "strategy": pos.get("strategy", "UT"),
            "entry": pos["entry_price"],
            "current": current,
            "pnl_pct": pnl_pct,
            "pnl_try": pnl_try,
            "quantity": pos["quantity"],
            "entry_time": pos.get("entry_time"),
            "stop": pos.get("stop_price"),
            "take_profit": pos.get("take_profit")
        })
    return {"positions": positions}

@app.get("/api/symbol-analysis/{symbol}")
async def symbol_analysis(symbol: str, timeframe: str = ""):
    sym = symbol.upper()
    requested_timeframe = timeframe if timeframe in {"1m", "5m", "15m", "1h", "4h", "1d"} else config.MOMENTUM_TIMEFRAME
    ticker = market.get_ticker(sym)
    # The analysis page can request a valid market that was not warm when the
    # process started (or whose websocket stream briefly missed an event).
    # Hydrate that symbol from the public REST API instead of reporting it as
    # unknown. This remains read-only and paper-trading safe.
    primary_history = market.klines.get(requested_timeframe, {}).get(sym, {})
    history_ready = len(primary_history.get("closes", [])) >= 55
    analysis_klines = {
        requested_timeframe: primary_history,
        "1d": market.klines.get("1d", {}).get(sym, {}),
    }
    if not ticker or not history_ready:
        try:
            available = set(await trading_symbols("TRY"))
            if sym not in available:
                return {"symbol": sym, "analysis_build": "rest-fallback-v4", "data_ready": False, "error": "Sembol Binance TR'de işlem görmüyor"}
            rows = await fetch_klines(sym, requested_timeframe, limit=300)
            if rows and len(rows) >= 55:
                hydrated = {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": []}
                for row in rows:
                    hydrated["opens"].append(float(row[1]))
                    hydrated["highs"].append(float(row[2]))
                    hydrated["lows"].append(float(row[3]))
                    hydrated["closes"].append(float(row[4]))
                    hydrated["volumes"].append(float(row[5]))
                market.klines[requested_timeframe][sym] = hydrated
                analysis_klines = {
                    requested_timeframe: hydrated,
                    "1d": market.klines.get("1d", {}).get(sym, {}),
                }
                last_price = float(rows[-1][4])
                ticker = {"symbol": sym, "last_price": last_price, "timestamp": int(time.time() * 1000)}
                market.tickers[sym] = ticker
            else:
                count = len(rows) if rows else 0
                return {"symbol": sym, "analysis_build": "rest-fallback-v4", "timeframes": {requested_timeframe: {"candles": count, "required": 55}}, "data_ready": False, "error": "Teknik analiz için yeterli mum verisi alınamadı"}
        except Exception as exc:
            return {"symbol": sym, "analysis_build": "rest-fallback-v4", "data_ready": False, "error": f"Sembol verisi alınamadı: {exc}"}
    if not ticker:
        return {"symbol": sym, "analysis_build": "rest-fallback-v4", "data_ready": False, "error": "Sembol verisi bulunamadı"}
    flow = market.get_orderflow(sym)
    if not flow.get("spread_pct") or not (flow.get("bid_qty") or flow.get("ask_qty")):
        try:
            book = await orderbook(sym, 5)
            bids, asks = book.get("bids", []), book.get("asks", [])
            if bids and asks:
                bid_qty = sum(float(row[1]) for row in bids[:5])
                ask_qty = sum(float(row[1]) for row in asks[:5])
                bid, ask = float(bids[0][0]), float(asks[0][0])
                flow.update({"bid_qty": bid_qty, "ask_qty": ask_qty,
                             "spread_pct": ((ask - bid) / bid * 100) if bid else None,
                             "source": "binance_tr_public_rest", "updated_at": time.time()})
                market.orderflow[sym] = flow
        except Exception as exc:
            flow["rest_error"] = str(exc)
    snapshot = calculate_snapshot(sym, ticker["last_price"], analysis_klines, flow, market.ticker_24h.get(sym, 0), config.DEFAULT_ORDER_USDT, requested_timeframe)
    snapshot["analysis_build"] = "rest-fallback-v4"
    return snapshot

@app.get("/api/llm/config")
async def llm_config():
    data = await llm_analysis.list_config()
    paper_enabled = (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"
    auto_enabled = (await database.get_llm_setting("llm_auto_paper_enabled", "0")) == "1"
    return {**data, "encryption_configured": bool(os.getenv("LLM_ENCRYPTION_KEY", "").strip()), "paper_trade_enabled": paper_enabled, "auto_paper_enabled": auto_enabled, "auto_paper_interval_minutes": 15}

@app.get("/api/llm/learning")
async def llm_learning():
    """Expose the descriptive closed-trade learning summary for audit/UI."""
    return build_learning_context(await database.get_trades(), limit=200)

@app.put("/api/llm/paper-trading")
async def set_llm_paper_trading(payload: dict):
    enabled = bool(payload.get("enabled"))
    await database.set_llm_setting("llm_paper_trade_enabled", "1" if enabled else "0")
    return {"ok": True, "paper_trade_enabled": enabled, "real_trading": False}

@app.put("/api/llm/auto-paper-trading")
async def set_llm_auto_paper_trading(payload: dict):
    enabled = bool(payload.get("enabled"))
    await database.set_llm_setting("llm_auto_paper_enabled", "1" if enabled else "0")
    return {"ok": True, "auto_paper_enabled": enabled, "trigger": "after_each_closed_position", "paper_only": True}

@app.post("/api/llm/paper-trade")
async def llm_open_paper_trade(payload: dict):
    if (await database.get_llm_setting("llm_paper_trade_enabled", "0")) != "1":
        raise HTTPException(status_code=403, detail="LLM paper işlem açma yetkisi ayarlardan kapalı")
    symbol = str(payload.get("symbol", "")).replace("_", "").upper()
    candidates = []
    if not symbol:
        scan = await scan_market_snapshots({"symbols": config.SYMBOLS, "timeframes": ["5m", "15m", "1h"], "limit": 5})
        candidates = [x for x in scan.get("bullish_candidates", []) if float(x.get("score", 0)) >= 2.5]
        if not candidates:
            raise HTTPException(status_code=409, detail="Paper işlem için yeterli güvene sahip bullish aday bulunamadı")
    else:
        candidates = [{"symbol": symbol, "score": None}]
    # Otomatik seçimde symbol başlangıçta boştur; geçerlilik kontrolü yalnızca
    # kullanıcı belirli bir sembol gönderdiğinde uygulanmalıdır.
    if symbol and symbol not in config.SYMBOLS:
        try:
            available_symbols = set(await trading_symbols("TRY"))
        except Exception:
            available_symbols = set()
        if symbol not in available_symbols:
            raise HTTPException(status_code=400, detail="Geçerli TRY sembolü gerekli")
    blocked = []
    for candidate in candidates:
        symbol = str(candidate["symbol"]).upper()
        if symbol not in config.SYMBOLS:
            continue
        ticker = market.get_ticker(symbol)
        if not ticker or not ticker.get("last_price"):
            try:
                latest = await fetch_klines(symbol, "1m", 2)
                if latest:
                    ticker = {"symbol": symbol, "last_price": float(latest[-1][4]), "timestamp": time.time() * 1000, "source": "binance_tr_public_rest"}
            except Exception as exc:
                blocked.append({"symbol": symbol, "reason": f"price_unavailable:{exc}"})
        if not ticker or not ticker.get("last_price"):
            blocked.append({"symbol": symbol, "reason": "price_unavailable"})
            continue
        signal = await analyzer.open_position(symbol, float(ticker["last_price"]), "LONG", "LLM_PAPER")
        if signal and str(signal.get("action", "")).upper() == "BUY_SIGNAL":
            await ws_manager.broadcast({"type": "signal", "data": signal})
            return {"ok": True, "paper_only": True, "real_trading": False, "signal": signal, "research_attempts": blocked}
        blocked.append({"symbol": symbol, "reason": (signal or {}).get("reason", "risk_or_position_limit")})
    raise HTTPException(status_code=409, detail={"message": "Hiçbir aday paper işlem kurallarını geçemedi; işlem açılmadı", "blocked_candidates": blocked, "retry_research": True})

@app.post("/api/llm/providers")
async def add_llm_provider(payload: dict):
    name = str(payload.get("name", "")).strip()
    base_url = str(payload.get("base_url", "")).strip()
    key = str(payload.get("api_key", "")).strip()
    if not name: raise HTTPException(status_code=400, detail="Provider adı gerekli")
    if not base_url.startswith(("http://", "https://")): raise HTTPException(status_code=400, detail="Base URL http:// veya https:// ile başlamalı")
    if not key: raise HTTPException(status_code=400, detail="API key gerekli")
    try:
        provider_id = await database.save_llm_provider(name, base_url, llm_analysis.encrypt_key(key))
        return {"ok": True, "provider_id": provider_id}
    except RuntimeError as exc: raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/llm/models")
async def add_llm_model(payload: dict):
    try:
        provider_id = int(payload["provider_id"])
        name = str(payload["name"]).strip()
        if not name: raise ValueError("Model adı gerekli")
        if provider_id <= 0: raise ValueError("Geçerli bir provider seçin")
        model_type = str(payload.get("model_type", "chat")).strip().lower()
        if model_type not in ("chat", "embedding"): raise ValueError("Model tipi chat veya embedding olmalı")
        dimensions = payload.get("dimensions")
        dimensions = int(dimensions) if dimensions not in (None, "") else None
        if model_type == "embedding" and dimensions != 2048: raise ValueError("Bu deployment için embedding dimension 2048 olmalı")
        return {"ok": True, "model_id": await database.save_llm_model(provider_id, name, float(payload.get("temperature", 0.2)), model_type, dimensions, payload.get("embedding_metric", "cosine"))}
    except (KeyError, ValueError) as exc: raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/llm/skills")
async def add_llm_skill(payload: dict):
    name = str(payload.get("name", "")).strip()
    instructions = str(payload.get("instructions", "")).strip()
    if not name or not instructions: raise HTTPException(status_code=400, detail="Uzmanlık adı ve talimatları gerekli")
    try: return {"ok": True, "skill_id": await database.save_llm_skill(name, instructions)}
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

@app.put("/api/llm/providers/{provider_id}")
async def update_llm_provider(provider_id: int, payload: dict):
    name, base_url, key = str(payload.get("name", "")).strip(), str(payload.get("base_url", "")).strip(), str(payload.get("api_key", "")).strip()
    if not name or not base_url.startswith(("http://", "https://")): raise HTTPException(status_code=400, detail="Provider adı ve geçerli Base URL gerekli")
    try: await database.update_llm_provider(provider_id, name, base_url, llm_analysis.encrypt_key(key) if key else None); return {"ok": True}
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

@app.delete("/api/llm/providers/{provider_id}")
async def delete_llm_provider(provider_id: int):
    await database.delete_llm_provider(provider_id); return {"ok": True}

@app.put("/api/llm/models/{model_id}")
async def update_llm_model(model_id: int, payload: dict):
    name = str(payload.get("name", "")).strip()
    if not name: raise HTTPException(status_code=400, detail="Model adı gerekli")
    model_type = payload.get("model_type")
    dimensions = payload.get("dimensions")
    await database.update_llm_model(model_id, name, float(payload.get("temperature", 0.2)), model_type, int(dimensions) if dimensions not in (None, "") else None, payload.get("embedding_metric")); return {"ok": True}

@app.delete("/api/llm/models/{model_id}")
async def delete_llm_model(model_id: int):
    await database.delete_llm_model(model_id); return {"ok": True}

@app.put("/api/llm/skills/{skill_id}")
async def update_llm_skill(skill_id: int, payload: dict):
    name, instructions = str(payload.get("name", "")).strip(), str(payload.get("instructions", "")).strip()
    if not name or not instructions: raise HTTPException(status_code=400, detail="Uzmanlık adı ve talimatları gerekli")
    await database.update_llm_skill(skill_id, name, instructions); return {"ok": True}

@app.delete("/api/llm/skills/{skill_id}")
async def delete_llm_skill(skill_id: int):
    await database.delete_llm_skill(skill_id); return {"ok": True}

@app.put("/api/llm/active")
async def activate_llm(payload: dict):
    await database.set_llm_setting("llm_enabled", "1" if payload.get("enabled") else "0")
    if payload.get("model_id") is not None: await database.set_llm_setting("active_model_id", payload["model_id"])
    return {"ok": True}

@app.post("/api/llm/test")
async def test_llm(payload: dict = None):
    result = await llm_analysis.analyze({"test": True, "message": "Return exactly: CONNECTION_OK"})
    return result

@app.post("/api/llm/embedding/test")
async def test_embedding(payload: dict = None):
    body = payload or {}
    text = str(body.get("text", "embedding bağlantı testi"))[:4000]
    return await llm_analysis.embedding(text, body.get("model_id"))

async def symbol_llm_context(symbol: str, preferred_timeframe: str = ""):
    """Build a fresh, read-only multi-timeframe tool context for the LLM."""
    supported = ("1m", "5m", "15m", "1h", "4h", "1d")
    preferred = preferred_timeframe if preferred_timeframe in supported else config.MOMENTUM_TIMEFRAME
    snapshots = {}
    results = await asyncio.gather(*(symbol_analysis(symbol, tf) for tf in supported), return_exceptions=True)
    for tf, snapshot in zip(supported, results):
        if isinstance(snapshot, dict) and snapshot.get("data_ready"):
            snapshots[tf] = snapshot
    selected = snapshots.get(preferred) or await symbol_analysis(symbol, preferred)
    if selected.get("data_ready"):
        # Do not attach the context to the same object stored inside snapshots;
        # that would create a circular JSON reference.
        selected = dict(selected)
        selected["llm_context"] = {
            "selected_timeframe": preferred,
            "available_timeframes": list(snapshots.keys()),
            "data_policy": "Use only supplied public OHLCV, ticker, order-flow and calculated indicators. Missing values remain unknown.",
            "available_calculations": ["trend", "oscillators", "moving_averages", "candlestick_patterns", "channels", "volatility", "volume", "pivots", "liquidity"],
            "timeframes": snapshots,
        }
    return selected

@app.post("/api/symbol-analysis/{symbol}/llm")
async def symbol_analysis_llm(symbol: str, payload: dict = None):
    snapshot = await symbol_llm_context(symbol, str((payload or {}).get("timeframe", "")))
    if not snapshot.get("data_ready"): return {"enabled": False, "status": "data_not_ready", "error": snapshot.get("error")}
    return await llm_analysis.analyze(snapshot)

async def llm_query_database(args: dict, default_symbol: str | None = None):
    """Read-only structured DB query exposed to LLMs; never executes raw SQL."""
    resource = str(args.get("resource", "trades")).lower()
    symbol = str(args.get("symbol") or default_symbol or "").upper() or None
    strategy = str(args.get("strategy") or "").upper() or None
    limit = max(1, min(int(args.get("limit", 100)), 500))
    if resource == "positions":
        db_positions = await database.load_positions()
        db_rows = [dict(v, symbol=k) for k, v in db_positions.items()]
        live_rows = [dict(v, symbol=k) for k, v in analyzer.positions.items()]
        if symbol:
            db_rows = [r for r in db_rows if str(r.get("symbol", "")).upper() == symbol]
            live_rows = [r for r in live_rows if str(r.get("symbol", "")).upper() == symbol]
        return {"resource": resource, "database_count": len(db_rows), "live_count": len(live_rows),
                "database_rows": db_rows[-limit:], "live_rows": live_rows[-limit:],
                "consistent": {k: k in db_positions for k in analyzer.positions}}
    elif resource == "trades":
        rows = await database.get_trades()
    elif resource == "signals":
        rows = await database.get_signals(limit)
    elif resource in {"decisions", "decision_logs"}:
        rows = await database.get_decision_logs(limit, symbol, strategy)
    elif resource == "wallet":
        return {"resource": resource, "balances": {"TRY": await database.get_wallet_balance("TRY")},
                "live_open_position_count": len(analyzer.positions)}
    else:
        return {"error": "resource yalnızca positions, trades, signals, decisions veya wallet olabilir"}
    if symbol: rows = [r for r in rows if str(r.get("symbol", "")).upper() == symbol]
    if strategy: rows = [r for r in rows if str(r.get("strategy", "")).upper() == strategy]
    if args.get("action"): rows = [r for r in rows if str(r.get("action", "")).upper() == str(args["action"]).upper()]
    return {"resource": resource, "count": len(rows), "rows": rows[-limit:]}

def _market_candidate_score(snapshot: dict):
    """Deterministic ranking used before asking the LLM for deeper analysis."""
    trend = snapshot.get("trend") or {}
    momentum = snapshot.get("momentum") or {}
    volume = snapshot.get("volume") or {}
    liquidity = snapshot.get("liquidity") or {}
    methodology = snapshot.get("methodology") or {}
    score = 0.0; evidence = []; risks = []
    alignment = str(trend.get("alignment") or "").lower()
    if alignment == "bullish": score += 2.5; evidence.append("EMA hizalaması bullish")
    elif alignment == "bearish": score -= 2.5; risks.append("EMA hizalaması bearish")
    else: risks.append("EMA hizalaması karışık")
    adx = trend.get("adx") if trend.get("adx") is not None else (trend.get("adx_14") if trend else None)
    if isinstance(adx, dict): adx = adx.get("adx")
    if adx is not None:
        if float(adx) >= 20: score += 1.0; evidence.append(f"ADX {float(adx):.1f} ile trend gücü var")
        else: risks.append(f"ADX düşük ({float(adx):.1f})")
    for key in ("return_5m", "return_15m", "return_1h"):
        value = momentum.get(key)
        if value is not None:
            if float(value) > 0: score += 0.35
            elif float(value) < 0: score -= 0.35
    if momentum.get("return_15m", 0) > 0 and momentum.get("return_1h", 0) > 0:
        score += 1.0; evidence.append("15m ve 1h momentum aynı yönde")
    vr = volume.get("volume_ratio_20")
    if vr is not None and float(vr) >= 1.1: score += .6; evidence.append("hacim ortalamanın üzerinde")
    elif vr in (None, 0): risks.append("hacim verisi eksik veya sıfır")
    spread = liquidity.get("spread_pct")
    depth = liquidity.get("orderbook_depth_try")
    if spread is None or depth in (None, 0): risks.append("spread/derinlik eksik")
    elif float(spread) <= .25: score += .4; evidence.append("spread kabul edilebilir")
    regime = (methodology.get("regime") or {}).get("name") if isinstance(methodology, dict) else None
    if regime and str(regime).startswith("bull"): score += .8; evidence.append(f"rejim {regime}")
    execution = execution_quality(snapshot, config.DEFAULT_ORDER_USDT)
    if execution["score"] >= 0.8:
        score += 0.5; evidence.append("işlem kalitesi uygun")
    elif execution["score"] < 0.5:
        score -= 0.8; risks.extend(execution["reasons"][:2])
    safety = symbol_safety(snapshot)
    if safety["status"] != "PASS":
        risks.extend(safety["flags"][:2])
    return round(score, 3), evidence, risks

async def scan_market_snapshots(args: dict | None = None):
    args = args or {}
    requested = args.get("symbols") or config.SYMBOLS
    requested_symbols = list(dict.fromkeys(str(s).replace("_", "").upper() for s in requested if str(s).strip()))[:100]
    db_positions = await database.load_positions()
    open_symbols = set(db_positions) | set(analyzer.positions)
    symbols = [symbol for symbol in requested_symbols if symbol not in open_symbols]
    timeframes = [str(tf) for tf in (args.get("timeframes") or ["1m", "5m", "15m", "1h", "4h", "1d"]) if str(tf) in {"1m","5m","15m","1h","4h","1d"}]
    if not timeframes: timeframes = ["5m", "15m", "1h"]
    sem = asyncio.Semaphore(4)
    async def one(sym):
        async with sem:
            rows = {}
            for tf in timeframes:
                try: rows[tf] = await symbol_analysis(sym, tf)
                except Exception as exc: rows[tf] = {"symbol": sym, "data_ready": False, "error": str(exc)}
            ready = [row for row in rows.values() if row.get("data_ready")]
            selected = rows.get("5m") if rows.get("5m", {}).get("data_ready") else (ready[0] if ready else rows.get(timeframes[0], {}))
            score, evidence, risks = _market_candidate_score(selected)
            return {"symbol": sym, "selected_timeframe": selected.get("timeframe", "5m"), "score": score,
                    "data_ready": bool(selected.get("data_ready")),
                    "trend_direction": (selected.get("summary") or (selected.get("trend") or {}).get("alignment") or "unknown"),
                    "evidence": evidence, "risks": risks, "data_ready_timeframes": list(rows.keys()),
                    "snapshot": selected, "timeframes": rows}
    results = await asyncio.gather(*(one(sym) for sym in symbols))
    results.sort(key=lambda row: row["score"], reverse=True)
    regime = estimate_local_regime(results)
    learning = build_learning_context(await database.get_trades(), limit=200)
    # Regime is a soft selector: hard paper risk rules remain authoritative.
    if regime["zone"] == "RISK_OFF":
        for row in results:
            row["score"] = round(float(row["score"]) - 0.75, 3)
            row.setdefault("risks", []).append("genel piyasa rejimi risk-off")
        results.sort(key=lambda row: row["score"], reverse=True)
    limit = max(1, min(int(args.get("limit", 10)), 30))
    bullish = [row for row in results if row["score"] >= 2 and str(row.get("trend_direction", "")).lower() not in {"bearish", "mixed"}]
    return {"generated_at": time.time(), "symbols_scanned": len(symbols), "symbols_skipped_open": sorted(open_symbols & set(requested_symbols)), "timeframes": timeframes,
            "bullish_candidates": bullish[:limit], "ranked": results[:limit],
            "market_regime": regime,
            "learning_context": learning,
            "paper_only": True, "live_portfolio_changed": False,
            "data_policy": "Binance TR public market data; missing values remain unknown. Contract/wallet safety is not inferred."}

async def deep_analyze_symbol(args: dict):
    symbol = str(args.get("symbol", "")).replace("_", "").upper()
    if not symbol: return {"error": "symbol gerekli"}
    context = await symbol_llm_context(symbol, str(args.get("timeframe") or "5m"))
    if not context.get("data_ready"): return context
    score, evidence, risks = _market_candidate_score(context)
    context = dict(context); context["candidate_assessment"] = {"score": score, "bullish_evidence": evidence, "risks": risks,
        "execution_quality": execution_quality(context, config.DEFAULT_ORDER_USDT),
        "symbol_safety": symbol_safety(context),
        "paper_candidate": "candidate" if score >= 2.5 and not risks else "watch"}
    return context

@app.post("/api/market-snapshot-scan")
async def market_snapshot_scan(payload: dict = None):
    """Tüm etkin sembolleri salt-okunur biçimde tarar; canlı portföyü değiştirmez."""
    return await scan_market_snapshots(payload or {})

@app.get("/api/market-snapshot/{symbol}/deep")
async def market_snapshot_deep(symbol: str, timeframe: str = "5m"):
    """Tek sembol için LLM'e sunulacak güncel derin snapshot'ı döndürür."""
    return await deep_analyze_symbol({"symbol": symbol, "timeframe": timeframe})

LLM_MARKET_SCAN_TOOL = {"type":"function","function":{"name":"scan_market_snapshots","description":"Tüm etkin paper-trading sembollerini güncel public market verisiyle tarar, bullish adayları deterministik olarak sıralar. Salt-okunur; pozisyon açmaz.","parameters":{"type":"object","properties":{"symbols":{"type":"array","items":{"type":"string"}},"timeframes":{"type":"array","items":{"type":"string","enum":["1m","5m","15m","1h","4h","1d"]}},"limit":{"type":"integer"}},"required":[]}}}
LLM_DEEP_SYMBOL_TOOL = {"type":"function","function":{"name":"deep_analyze_symbol","description":"Bir sembolün seçili timeframe ve çoklu timeframe teknik snapshot'ını getirir; trend fazı ve aday değerlendirmesi için kullanılır. Salt-okunur.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"timeframe":{"type":"string","enum":["1m","5m","15m","1h","4h","1d"]}},"required":["symbol"]}}}

LLM_DATABASE_TOOL = {"type":"function","function":{"name":"query_database","description":"Sistemin PostgreSQL/SQLite veri katmanında güvenli, salt-okunur sorgu yapar. Açık pozisyon sorgusunda hem veritabanı hem canlı portföy belleğini karşılaştırır; böylece stale/mutabakat farkını gizlemez. Ham SQL çalıştırmaz.","parameters":{"type":"object","properties":{"resource":{"type":"string","enum":["positions","trades","signals","decisions","wallet"]},"symbol":{"type":"string"},"strategy":{"type":"string"},"action":{"type":"string"},"limit":{"type":"integer"}},"required":["resource"]}}}
LLM_READONLY_SQL_TOOL = {"type":"function","function":{"name":"read_only_sql","description":"İleri seviye salt-okunur veritabanı incelemesi. Yalnızca tek SELECT veya WITH...SELECT sorgusu çalıştırır; yazma/DDL komutları ve izin verilmeyen tablolar reddedilir. Sadece gerektiğinde kullan.","parameters":{"type":"object","properties":{"sql":{"type":"string","description":"Tek bir SELECT veya WITH...SELECT sorgusu"},"limit":{"type":"integer"}},"required":["sql"]}}}

@app.post("/api/symbol-analysis/{symbol}/llm/chat")
async def symbol_analysis_llm_chat(symbol: str, payload: dict = None):
    body = payload or {}
    last_message = str((body.get("messages") or [{}])[-1].get("content", "")).lower().replace("ı", "i").replace("ş", "s")
    broad_scan = any(token in last_message for token in ("tum sembol", "tüm sembol", "en uygun", "en guclu", "en güçlü", "gainer", "piyasa tar"))
    is_trade_command = ("islem" in last_message or "pozisyon" in last_message) and ("ac" in last_message or "aç" in last_message)
    if body.get("stream") is True and is_trade_command:
        async def paper_events():
            yield "event: status\ndata: {\"text\":\"Tüm semboller taranıyor, risk kontrolleri hazırlanıyor...\"}\n\n"
            try:
                result = await llm_open_paper_trade({})
                signal = result.get("signal", {})
                text = f"### Paper işlem açıldı\\n\\n- **Sembol:** `{signal.get('symbol', '—')}`\\n- **Yön:** {signal.get('side', 'LONG')}\\n- **Giriş:** `{signal.get('entry_price', '—')}`\\n- **Durum:** Mevcut risk kuralları geçti."
                yield f"event: delta\ndata: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
                yield "event: done\ndata: {\"status\":\"ok\",\"paper_only\":true}\n\n"
            except HTTPException as exc:
                yield f"event: error\ndata: {json.dumps({'error': exc.detail}, ensure_ascii=False)}\n\n"
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        return StreamingResponse(paper_events(), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "Connection":"keep-alive", "X-Accel-Buffering":"no"})
    snapshot = await symbol_llm_context(symbol, str(body.get("timeframe", "")))
    if not snapshot.get("data_ready"):
        return {"enabled": False, "status": "data_not_ready", "error": snapshot.get("error")}
    try:
        market_scan = await scan_market_snapshots({
            "symbols": config.SYMBOLS if broad_scan else [symbol.upper()],
            "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"] if broad_scan else ["5m", "15m", "1h"],
            "limit": 8,
        })
        snapshot = dict(snapshot)
        snapshot["market_scan"] = {
            "symbols_scanned": market_scan["symbols_scanned"],
            "bullish_candidates": market_scan["bullish_candidates"][:5],
            "ranked": market_scan["ranked"],
            "market_regime": market_scan.get("market_regime"),
            "learning_context": market_scan.get("learning_context"),
            "paper_only": True,
            "data_policy": market_scan["data_policy"],
        }
    except Exception as exc:
        snapshot = dict(snapshot)
        snapshot["market_scan"] = {"error": str(exc), "paper_only": True}
    if body.get("stream") is True:
        async def events():
            async for event in llm_analysis.stream_chat(snapshot, body.get("messages", [])):
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "Connection":"keep-alive", "X-Accel-Buffering":"no"})
    tools = [{"type":"function","function":{"name":"get_symbol_analysis","description":"Seçili sembolün güncel teknik analizini ve istenen timeframe snapshot'ını getirir.","parameters":{"type":"object","properties":{"timeframe":{"type":"string"}},"required":[]}}}, {"type":"function","function":{"name":"get_historical_klines","description":"Binance TR public API'den seçili sembol için geçmiş mumları getirir. En fazla 1000 mum.","parameters":{"type":"object","properties":{"interval":{"type":"string","enum":["1m","5m","15m","1h","4h","1d"]},"limit":{"type":"integer"}},"required":[]}}}, {"type":"function","function":{"name":"get_symbol_trades","description":"Seçili sembolün geçmiş işlemlerini getirir.","parameters":{"type":"object","properties":{"limit":{"type":"integer"}},"required":[]}}}, {"type":"function","function":{"name":"run_backtest","description":"Seçili sembol üzerinde public historical candles ile paper-only mevcut strateji backtesti çalıştırır; canlı portföyü değiştirmez.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"interval":{"type":"string","enum":["1m","5m","15m","1h","4h","1d"]},"days_back":{"type":"integer"},"strategy":{"type":"string"},"order_size":{"type":"number"},"stop_loss_pct":{"type":"number"},"take_profit_pct":{"type":"number"}},"required":["strategy"]}}}, {"type":"function","function":{"name":"run_custom_backtest","description":"Seçili sembol üzerinde güvenli deklaratif gösterge koşullarıyla paper-only backtest çalıştırır; Python kodu çalıştırmaz.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"interval":{"type":"string","enum":["5m","15m","1h","4h","1d"]},"days_back":{"type":"integer"},"strategy_definition":{"type":"object"},"order_size":{"type":"number"},"stop_loss_pct":{"type":"number"},"take_profit_pct":{"type":"number"}},"required":["strategy_definition"]}}}, {"type":"function","function":{"name":"run_backtest_robustness","description":"Seçili sembol ve stratejiyi farklı tarih pencerelerinde ve deterministik Monte Carlo özetiyle test eder; canlı portföyü değiştirmez.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"interval":{"type":"string"},"strategy":{"type":"string"},"windows":{"type":"array","items":{"type":"integer"}}},"required":["strategy"]}}}, {"type":"function","function":{"name":"get_backtest_history","description":"Daha önce kaydedilmiş backtest sonuçlarını getirir.","parameters":{"type":"object","properties":{"limit":{"type":"integer"},"strategy":{"type":"string"},"symbol":{"type":"string"}}}}}, LLM_DATABASE_TOOL, LLM_READONLY_SQL_TOOL, {"type":"function","function":{"name":"search_memory","description":"Seçili sembolle ilgili geçmiş konuşma, işlem ve karar hafızasını arar.","parameters":{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer"}},"required":["query"]}}}]
    async def execute_tool(name, args):
        if name == "scan_market_snapshots": return await scan_market_snapshots(args)
        if name == "deep_analyze_symbol": return await deep_analyze_symbol(args)
        if name == "query_database": return await llm_query_database(args, symbol.upper())
        if name == "read_only_sql": return {"rows": await database.read_only_query(args.get("sql", ""), args.get("limit", 500))}
        if name == "get_symbol_analysis": return await symbol_analysis(symbol, str(args.get("timeframe") or body.get("timeframe") or "5m"))
        if name == "get_historical_klines":
            interval = str(args.get("interval") or "5m"); limit = max(1, min(int(args.get("limit", 300)), 1000))
            rows = await fetch_klines(symbol, interval, limit)
            return {"symbol": symbol.upper(), "interval": interval, "count": len(rows), "klines": rows}
        if name == "get_symbol_trades":
            rows = [r for r in await database.get_trades() if str(r.get("symbol", "")).upper() == symbol.upper()]
            limited = rows[-max(1, min(int(args.get("limit", 100)), 500)):]
            return {"count": len(rows), "trades": limited}
        if name == "run_backtest":
            target = str(args.get("symbol") or symbol).upper()
            interval = str(args.get("interval") or "5m")
            days = max(1, min(int(args.get("days_back", 30)), 90))
            strategy = str(args.get("strategy") or "EMA_VWAP_PULLBACK")
            order_size = max(10.0, min(float(args.get("order_size", 500.0)), config.INITIAL_BALANCE_TRY))
            run_id, result = await run_backtest(target, interval, days, strategy, args.get("params") or {}, order_size, float(args.get("stop_loss_pct", config.HARD_STOP_LOSS_PCT)), float(args.get("take_profit_pct", config.TIME_DECAY_TP_1_PCT)), 0.0)
            return {"run_id": run_id, "result": result, "paper_only": True, "live_portfolio_changed": False}
        if name == "run_custom_backtest":
            target = str(args.get("symbol") or symbol).upper()
            interval = str(args.get("interval") or "5m")
            days = max(1, min(int(args.get("days_back", 30)), 90))
            order_size = max(10.0, min(float(args.get("order_size", 500.0)), config.INITIAL_BALANCE_TRY))
            result = await run_custom_backtest(target, interval, days, args.get("strategy_definition") or {}, order_size, args.get("stop_loss_pct", config.HARD_STOP_LOSS_PCT), args.get("take_profit_pct", config.TIME_DECAY_TP_1_PCT))
            return {"result": result, "paper_only": True, "live_portfolio_changed": False}
        if name == "get_backtest_history":
            rows = await database.get_backtests(max(1, min(int(args.get("limit", 20)), 50)))
            return {"count": len(rows), "backtests": rows}
        if name == "run_backtest_robustness":
            target = str(args.get("symbol") or symbol).upper()
            interval = str(args.get("interval") or "5m")
            strategy = str(args.get("strategy") or "EMA_VWAP_PULLBACK")
            windows = [max(7, min(int(x), 90)) for x in (args.get("windows") or [14, 30, 60])][:3]
            runs = []; first_result = None
            for days in windows:
                _, result = await run_backtest(target, interval, days, strategy, {}, 500.0, config.HARD_STOP_LOSS_PCT, config.TIME_DECAY_TP_1_PCT, 0.0)
                if first_result is None: first_result = result
                runs.append({"days_back": days, "net_pnl": result.get("net_pnl"), "win_rate": result.get("win_rate"), "profit_factor": result.get("profit_factor"), "max_drawdown_pct": result.get("max_drawdown_pct"), "trades": result.get("total_trades"), "exit_reason_counts": result.get("exit_reason_counts")})
            pnls = [float(t.get("pnl") or 0) for t in (first_result or {}).get("trades", [])]
            rng = random.Random(42)
            samples = [sum(rng.choice(pnls) for _ in pnls) for _ in range(1000)] if pnls else []
            samples.sort()
            return {"paper_only": True, "windows": runs,
                    "walk_forward_assessment": walk_forward_assessment(runs),
                    "cost_aware_metrics": cost_aware_trade_metrics((first_result or {}).get("trades", [])),
                    "monte_carlo": {"iterations": len(samples), "p05": samples[int(len(samples) * 0.05)] if samples else None, "median": samples[len(samples) // 2] if samples else None, "p95": samples[int(len(samples) * 0.95) - 1] if samples else None},
                    "limitations": ["Gerçek out-of-sample tarih aralığı ayrımı yoktur", "Order-book yerine candle/order-flow proxy kullanılır", "Monte Carlo trade sırasını yeniden örnekler; piyasa rejimi garantisi değildir"]}
        if name == "search_memory":
            if not _pg_pool: return {"count": 0, "results": [], "message": "Memory backend aktif değil"}
            embedded = await llm_analysis.embedding(str(args.get("query", "")))
            if embedded.get("status") != "ok": return {"count": 0, "results": [], "error": embedded.get("error")}
            async with _pg_pool.acquire() as conn:
                rows = await memory_service.retrieve(conn, embedded["vector"], limit=max(1, min(int(args.get("limit", 6)), 20)), symbol=symbol.upper(), model_id=embedded.get("model_id"))
            return {"count": len(rows), "results": rows}
        return {"error": "Bilinmeyen araç"}
    tools.extend([LLM_MARKET_SCAN_TOOL, LLM_DEEP_SYMBOL_TOOL])
    result = await llm_analysis.chat(snapshot, body.get("messages", []), tools, execute_tool)
    await _persist_chat_memory(body.get("messages", []), layer="symbol", symbol=symbol.upper(), session_id=str(body.get("session_id") or "symbol:" + symbol.upper()))
    return result

@app.post("/api/positions/{symbol}/close")
async def close_position_manual(symbol: str):
    """Açık pozisyonu manuel kapat (komisyon + işlem geçmişi dahil)."""
    symbol = symbol.replace("_", "").upper()
    ticker = market.get_ticker(symbol)
    if not ticker or not ticker.get("last_price"):
        try:
            latest = await fetch_klines(symbol, "1m", 2)
            if latest:
                ticker = {"symbol": symbol, "last_price": float(latest[-1][4]), "source": "binance_tr_public_rest"}
        except Exception as exc:
            print(f"[Manual close] {symbol} fiyat fallback hatası: {exc}")
    price = ticker["last_price"] if ticker else None
    if price is None:
        return {"ok": False, "message": f"{symbol} için güncel fiyat bulunamadı"}
    sig = await analyzer.close_position(symbol.upper(), price, "manual_close")
    if not sig:
        return {"ok": False, "message": f"{symbol} için açık pozisyon yok"}
    await ws_manager.broadcast({"type": "signal", "data": sig})
    asyncio.create_task(llm_replenish_after_close())
    return {"ok": True, "message": f"{symbol} kapatıldı @ {price:.2f}", "signal": sig}

@app.get("/api/trades")
async def get_trades():
    """Kapanan pozisyonların işlem geçmişi."""
    return {"trades": await database.get_trades()}

@app.get("/api/backup")
async def download_backup():
    """Download a consistent snapshot of the active SQLite or PostgreSQL database."""
    if os.getenv("DB_BACKEND", "sqlite").lower() == "postgres":
        if not os.getenv("DATABASE_URL"):
            raise HTTPException(status_code=503, detail="DATABASE_URL tanımlı değil")
        fd, path = tempfile.mkstemp(prefix="scalper-postgres-", suffix=".dump")
        os.close(fd)
        try:
            result = await asyncio.to_thread(subprocess.run, ["pg_dump", "--format=custom", "--no-owner", "--file", path, os.environ["DATABASE_URL"]], capture_output=True, text=True, timeout=600)
        except FileNotFoundError as exc:
            if os.path.exists(path): os.unlink(path)
            raise HTTPException(status_code=503, detail="PostgreSQL yedek aracı pg_dump backend imajında kurulu değil") from exc
        if result.returncode != 0:
            if os.path.exists(path): os.unlink(path)
            raise HTTPException(status_code=502, detail=result.stderr[-2000:] or "pg_dump başarısız")
        return FileResponse(path, media_type="application/octet-stream", filename=f"scalperagent-postgres-{time.strftime('%Y%m%d-%H%M%S')}.dump", background=BackgroundTask(lambda: os.unlink(path) if os.path.exists(path) else None))
    path = await database.create_backup_file()
    return FileResponse(
        path,
        media_type="application/vnd.sqlite3",
        filename=f"scalperagent-backup-{time.strftime('%Y%m%d-%H%M%S')}.sqlite",
        background=BackgroundTask(lambda: os.unlink(path) if os.path.exists(path) else None),
    )

@app.get("/api/postgres/backup")
async def download_postgres_backup():
    if not os.getenv("DATABASE_URL"): raise HTTPException(status_code=503, detail="DATABASE_URL tanımlı değil")
    import tempfile, subprocess
    fd, path = tempfile.mkstemp(prefix="scalper-postgres-", suffix=".dump"); os.close(fd)
    result = await asyncio.to_thread(subprocess.run, ["pg_dump", "--format=custom", "--no-owner", "--file", path, os.environ["DATABASE_URL"]], capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        if os.path.exists(path): os.unlink(path)
        raise HTTPException(status_code=502, detail=result.stderr[-2000:] or "pg_dump başarısız")
    return FileResponse(path, media_type="application/octet-stream", filename=f"scalper-postgres-{time.strftime('%Y%m%d-%H%M%S')}.dump", background=BackgroundTask(lambda: os.unlink(path) if os.path.exists(path) else None))

@app.post("/api/postgres/restore")
async def restore_postgres_backup(payload: dict = None):
    body = payload or {}; path = os.path.abspath(str(body.get("path", "")))
    if body.get("confirmation") != "RESTORE_POSTGRES": raise HTTPException(status_code=400, detail="RESTORE_POSTGRES onayı gerekli")
    if not os.getenv("DATABASE_URL") or not path or not os.path.isfile(path): raise HTTPException(status_code=400, detail="Geçerli backup yolu ve DATABASE_URL gerekli")
    result = await asyncio.to_thread(subprocess.run, ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", os.environ["DATABASE_URL"], path], capture_output=True, text=True, timeout=1200)
    if result.returncode != 0: raise HTTPException(status_code=502, detail=result.stderr[-3000:] or "pg_restore başarısız")
    return {"ok": True, "message": "PostgreSQL backup geri yüklendi; backend yeniden başlatılması önerilir"}

@app.post("/api/memory/reset")
async def reset_memory():
    if not _pg_pool: raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    async with _pg_pool.acquire() as conn:
        await conn.execute("TRUNCATE memory_retrieval_logs, memory_embeddings, memory_documents RESTART IDENTITY")
    embedding_worker.stats.update({"queued":0,"processed":0,"failed":0,"last_error":None,"last_processed_at":None})
    return {"ok": True, "message": "LLM memory kayıtları sıfırlandı; paper-trading kayıtları korunuyor"}

@app.get("/api/signals")
async def get_signals(limit: int = 100):
    return {"signals": await database.get_signals(limit), "total": await database.get_signal_count()}

@app.get("/api/analysis-snapshots/{symbol}")
async def get_analysis_snapshots(symbol: str, limit: int = 50):
    """İşlem açılışında kaydedilen metodoloji snapshot'larını getirir."""
    limit = max(1, min(int(limit), 500))
    def op(conn):
        rows = conn.execute("SELECT * FROM analysis_snapshots WHERE symbol=? ORDER BY captured_at DESC LIMIT ?", (symbol.upper(), limit)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = database._json_value(item.get("payload"), {})
            output.append(item)
        return output
    return {"symbol": symbol.upper(), "snapshots": await database._run_db(op)}

@app.get("/api/decisions")
async def get_decisions(limit: int = 500, symbol: str = "", strategy: str = ""):
    return {"decisions": await database.get_decision_logs(limit, symbol or None, strategy or None)}

@app.get("/api/llm/tool-logs")
async def get_llm_tool_logs(limit: int = 500):
    return {"logs": await database.get_llm_tool_logs(limit)}

@app.get("/api/strategies/stats")
async def get_strategy_stats():
    """Her stratejinin başarı istatistikleri (işlem sayısı, kazanma oranı, PnL)."""
    trades = await database.get_trades()
    stats = {}
    for t in trades:
        s = stats.setdefault(t["strategy"], {"trades": 0, "wins": 0, "pnl": 0.0, "commission": 0.0})
        s["trades"] += 1
        s["pnl"] += t["pnl"] or 0.0
        s["commission"] += t["commission"] or 0.0
        if (t["pnl"] or 0.0) > 0:
            s["wins"] += 1
    for s in stats.values():
        s["win_rate"] = (s["wins"] / s["trades"] * 100) if s["trades"] else 0.0
    return {"stats": stats}

@app.get("/api/strategies/comparison")
async def strategy_comparison():
    trades = await database.get_trades()
    grouped = {}
    for trade in trades:
        name = trade.get("strategy") or "Bilinmeyen"
        item = grouped.setdefault(name, {"strategy": name, "trades": 0, "wins": 0, "losses": 0, "net_pnl": 0.0, "commission": 0.0, "hold_seconds": 0.0, "timeouts": 0, "gross_wins": 0.0, "gross_losses": 0.0})
        pnl = float(trade.get("pnl") or 0.0)
        item["trades"] += 1; item["net_pnl"] += pnl
        item["commission"] += float(trade.get("commission") or 0.0)
        item["hold_seconds"] += float(trade.get("hold_seconds") or 0.0)
        item["wins"] += int(pnl > 0); item["losses"] += int(pnl <= 0)
        item["gross_wins"] += max(0.0, pnl); item["gross_losses"] += min(0.0, pnl)
        reason = str(trade.get("reason") or "").lower()
        item["timeouts"] += int(any(token in reason for token in ("time", "timeout", "max_hold", "early_failure", "stale_position")))
    for item in grouped.values():
        n = item["trades"]
        item["win_rate"] = item["wins"] / n * 100 if n else 0.0
        item["avg_pnl"] = item["net_pnl"] / n if n else 0.0
        item["avg_hold_seconds"] = item["hold_seconds"] / n if n else 0.0
        item["profit_factor"] = item["gross_wins"] / abs(item["gross_losses"]) if item["gross_losses"] else None
        del item["hold_seconds"], item["gross_wins"], item["gross_losses"]
    return {"strategies": sorted(grouped.values(), key=lambda x: x["net_pnl"], reverse=True)}

@app.get("/api/risk/summary")
async def risk_summary():
    trades = await database.get_trades()
    positions = analyzer.positions
    realized = sum(float(t.get("pnl") or 0.0) for t in trades)
    commission = sum(float(t.get("commission") or 0.0) for t in trades)
    losses = 0
    for trade in trades:
        if float(trade.get("pnl") or 0.0) < 0: losses += 1
        else: break
    today_start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    today_pnl = sum(float(t.get("pnl") or 0.0) for t in trades if float(t.get("exit_time") or 0) >= today_start)
    return {"open_positions": len(positions), "realized_pnl": realized, "today_pnl": today_pnl,
            "commission": commission, "consecutive_losses": losses, "max_positions": config.MAX_OPEN_POSITIONS,
            "risk_flags": {"consecutive_loss_streak": losses >= 3, "daily_loss": today_pnl < 0}}

@app.post("/api/strategies/llm/chat")
async def strategies_llm_chat(payload: dict = None):
    body = payload or {}
    context = {"type": "strategy_research_tool_mode", "data_policy": "Paper trading/public data. Use net PnL after commission; missing fields are unknown.", "note": "Use a tool only when the question requires its data.", "self_learning": build_learning_context(await database.get_trades(), limit=200)}
    tools = [{"type":"function","function":{"name":"get_strategy_config","description":"Mevcut strateji ayarlarını getirir.","parameters":{"type":"object","properties":{}}}}, {"type":"function","function":{"name":"get_strategy_stats","description":"Strateji başına işlem, net PnL ve başarı istatistiklerini getirir.","parameters":{"type":"object","properties":{}}}}, {"type":"function","function":{"name":"get_trades","description":"İşlem geçmişini filtreleyerek getirir.","parameters":{"type":"object","properties":{"strategy":{"type":"string"},"symbol":{"type":"string"},"limit":{"type":"integer"}},"required":[]}}}, {"type":"function","function":{"name":"get_signals","description":"Sinyal geçmişini filtreleyerek getirir.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"strategy":{"type":"string"},"limit":{"type":"integer"}},"required":[]}}}, {"type":"function","function":{"name":"get_decision_logs","description":"BUY_BLOCKED dahil karar kayıtlarını getirir.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"strategy":{"type":"string"},"limit":{"type":"integer"}},"required":[]}}}, {"type":"function","function":{"name":"run_backtest","description":"Public historical candles üzerinde yalnızca paper/backtest simülasyonu çalıştırır. Gerçek emir ve canlı portföy değişikliği yoktur.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"interval":{"type":"string","enum":["1m","3m","5m","15m","30m","1h","2h","4h","1d"]},"days_back":{"type":"integer","description":"1-90 arası tarihsel gün"},"strategy":{"type":"string","enum":["EMA_VWAP_PULLBACK","BB_SQUEEZE_ORDERFLOW","ORDERFLOW","MOMENTUM","VWAP_MEAN_REVERSION","KELTNER_BREAKOUT","CHOP_TREND_FILTER","DONCHIAN_BREAKOUT"]},"params":{"type":"object"},"order_size":{"type":"number"},"stop_loss_pct":{"type":"number"},"take_profit_pct":{"type":"number"}},"required":["symbol","strategy"]}}}, {"type":"function","function":{"name":"run_custom_backtest","description":"LLM tarafından oluşturulan güvenli deklaratif gösterge koşullarını candle verisi üzerinde backtest eder; Python kodu çalıştırmaz.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"interval":{"type":"string","enum":["5m","15m","1h","4h","1d"]},"days_back":{"type":"integer"},"strategy_definition":{"type":"object","description":"entry/exit koşulları: indicator, op, value. En fazla 8 koşul.","properties":{"entry":{"type":"array"},"exit":{"type":"array"}}},"order_size":{"type":"number"},"stop_loss_pct":{"type":"number"},"take_profit_pct":{"type":"number"}},"required":["symbol","strategy_definition"]}}}, {"type":"function","function":{"name":"run_backtest_robustness","description":"Aynı stratejiyi birden fazla tarih penceresinde çalıştırır ve trade PnL'leri üzerinde deterministik Monte Carlo dayanıklılık özeti üretir. Sonuçlar araştırma amaçlıdır; walk-forward için gerçek tarih aralığı ayrımı olmadığını açıkça belirtir.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"interval":{"type":"string","enum":["5m","15m","1h","4h","1d"]},"strategy":{"type":"string","enum":["EMA_VWAP_PULLBACK","BB_SQUEEZE_ORDERFLOW","ORDERFLOW","MOMENTUM","VWAP_MEAN_REVERSION","KELTNER_BREAKOUT","CHOP_TREND_FILTER","DONCHIAN_BREAKOUT"]},"windows":{"type":"array","items":{"type":"integer"},"description":"En fazla 3 pencere; 7-90 gün"}},"required":["symbol","strategy"]}}}, {"type":"function","function":{"name":"get_backtest_history","description":"Daha önce kaydedilmiş backtest sonuçlarını getirir.","parameters":{"type":"object","properties":{"limit":{"type":"integer"},"strategy":{"type":"string"},"symbol":{"type":"string"}},"required":[]}}}, LLM_DATABASE_TOOL, LLM_READONLY_SQL_TOOL, {"type":"function","function":{"name":"search_memory","description":"Geçmiş sohbet, karar ve strateji hafızasını arar.","parameters":{"type":"object","properties":{"query":{"type":"string"},"strategy":{"type":"string"},"symbol":{"type":"string"},"limit":{"type":"integer"}},"required":["query"]}}}]
    async def execute_tool(name, args):
        started = time.perf_counter(); success = True
        try:
            if name == "scan_market_snapshots": return await scan_market_snapshots(args)
            if name == "deep_analyze_symbol": return await deep_analyze_symbol(args)
            if name == "query_database": return await llm_query_database(args)
            if name == "read_only_sql": return {"rows": await database.read_only_query(args.get("sql", ""), args.get("limit", 500))}
            if name == "get_strategy_config": return await get_config()
            if name == "get_strategy_stats": return (await get_strategy_stats()).get("stats", {})
            if name == "run_backtest":
                symbol = str(args.get("symbol") or "BTCTRY").upper()
                interval = str(args.get("interval") or "5m")
                days = max(1, min(int(args.get("days_back", 30)), 90))
                strategy = str(args.get("strategy") or "EMA_VWAP_PULLBACK")
                order_size = max(10.0, min(float(args.get("order_size", 500.0)), config.INITIAL_BALANCE_TRY))
                run_id, result = await run_backtest(symbol, interval, days, strategy, args.get("params") or {}, order_size, float(args.get("stop_loss_pct", config.HARD_STOP_LOSS_PCT)), float(args.get("take_profit_pct", config.TIME_DECAY_TP_1_PCT)), float(args.get("trailing_stop_pct", 0.0)))
                return {"run_id": run_id, "result": result, "paper_only": True, "live_portfolio_changed": False}
            if name == "run_custom_backtest":
                symbol = str(args.get("symbol") or "BTCTRY").upper(); interval = str(args.get("interval") or "5m")
                days = max(1, min(int(args.get("days_back", 30)), 90)); order_size = max(10.0, min(float(args.get("order_size", 500.0)), config.INITIAL_BALANCE_TRY))
                result = await run_custom_backtest(symbol, interval, days, args.get("strategy_definition") or {}, order_size, args.get("stop_loss_pct", config.HARD_STOP_LOSS_PCT), args.get("take_profit_pct", config.TIME_DECAY_TP_1_PCT))
                return {"result": result, "paper_only": True, "live_portfolio_changed": False, "allowed_indicators":["rsi","ema_9","ema_21","ema_50","adx","volume_ratio","price_vs_vwap","return_5","return_21","chop","macd_histogram","stochastic_k","bollinger_position","atr_pct","mfi","cci","williams_r","price_vs_ema_21","cmo","crsi","confluence_score","regime_confidence","turtle_breakout","wyckoff_score","elliott_score","fib_distance_support","fib_distance_resistance"]}
            if name == "get_backtest_history":
                limit = max(1, min(int(args.get("limit", 20)), 50))
                rows = await database.get_backtests(limit)
                rows = [r for r in rows if (not args.get("strategy") or r.get("strategy") == args.get("strategy")) and (not args.get("symbol") or r.get("symbol") == str(args.get("symbol")).upper())]
                return {"count": len(rows), "backtests": rows}
            if name == "run_backtest_robustness":
                symbol = str(args.get("symbol") or "BTCTRY").upper(); interval = str(args.get("interval") or "5m"); strategy = str(args.get("strategy") or "EMA_VWAP_PULLBACK")
                windows = [max(7, min(int(x), 90)) for x in (args.get("windows") or [14, 30, 60])][:3]
                runs = []; first_result = None
                for days in windows:
                    _, result = await run_backtest(symbol, interval, days, strategy, {}, 500.0, config.HARD_STOP_LOSS_PCT, config.TIME_DECAY_TP_1_PCT, 0.0)
                    if first_result is None: first_result = result
                    runs.append({"days_back": days, "net_pnl": result.get("net_pnl"), "win_rate": result.get("win_rate"), "profit_factor": result.get("profit_factor"), "max_drawdown_pct": result.get("max_drawdown_pct"), "trades": result.get("total_trades"), "exit_reason_counts": result.get("exit_reason_counts")})
                pnls = [float(t.get("pnl") or 0) for t in (first_result or {}).get("trades", [])]
                rng = random.Random(42); samples = [sum(rng.choice(pnls) for _ in pnls) for _ in range(1000)] if pnls else []
                samples.sort()
                return {"paper_only":True,"windows":runs,"monte_carlo":{"iterations":len(samples),"p05":samples[int(len(samples)*0.05)] if samples else None,"median":samples[len(samples)//2] if samples else None,"p95":samples[int(len(samples)*0.95)-1] if samples else None},"limitations":["Gerçek out-of-sample tarih aralığı ayrımı yoktur","Order-book yerine candle/order-flow proxy kullanılır","Monte Carlo trade sırasını yeniden örnekler; piyasa rejimi garantisi değildir"]}
            if name == "get_trades":
                rows = await database.get_trades(); strategy, symbol = args.get("strategy"), args.get("symbol")
                rows = [r for r in rows if (not strategy or r.get("strategy") == strategy) and (not symbol or r.get("symbol") == symbol)]
                limit = max(1, min(int(args.get("limit", 100)), 500))
                return {"count": len(rows), "trades": rows[-limit:]}
            if name == "get_signals":
                rows = await database.get_signals(max(1, min(int(args.get("limit", 100)), 500))); strategy, symbol = args.get("strategy"), args.get("symbol")
                rows = [r for r in rows if (not strategy or r.get("strategy") == strategy) and (not symbol or r.get("symbol") == symbol)]
                return {"count": len(rows), "signals": rows}
            if name == "get_decision_logs":
                rows = await database.get_decision_logs(args.get("limit", 100), args.get("symbol"), args.get("strategy"))
                return {"count": len(rows), "decisions": rows}
            if name == "search_memory":
                if not _pg_pool: return {"count": 0, "results": [], "message": "Memory backend aktif değil"}
                embedded = await llm_analysis.embedding(str(args.get("query", "")))
                if embedded.get("status") != "ok": return {"count": 0, "results": [], "error": embedded.get("error")}
                async with _pg_pool.acquire() as conn:
                    rows = await memory_service.retrieve(conn, embedded["vector"], limit=max(1, min(int(args.get("limit", 6)), 20)), symbol=args.get("symbol"), strategy=args.get("strategy"), model_id=embedded.get("model_id"))
                return {"count": len(rows), "results": rows}
            return {"error": f"Bilinmeyen araç: {name}"}
        except Exception:
            success = False
            raise
        finally:
            try:
                await database.save_llm_tool_log({"scope": "strategies", "tool_name": name, "arguments": args,
                    "result_summary": "success" if success else "error", "duration_ms": (time.perf_counter() - started) * 1000, "success": success})
            except Exception as log_error:
                # Observability must never turn a valid LLM/tool response into
                # a failed chat request.
                print(f"[LLM] tool log kaydedilemedi: {log_error}")
    tools.extend([LLM_MARKET_SCAN_TOOL, LLM_DEEP_SYMBOL_TOOL])
    if body.get("stream") is True:
        async def events():
            async for event in llm_analysis.stream_chat(context, body.get("messages", [])):
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "Connection":"keep-alive", "X-Accel-Buffering":"no"})
    result = await llm_analysis.chat(context, body.get("messages", []), tools, execute_tool)
    await _persist_chat_memory(body.get("messages", []), layer="strategy", strategy=str(body.get("strategy") or "") or None, session_id=str(body.get("session_id") or "strategy:default"))
    return result

@app.post("/api/reset")
async def reset_all():
    """Paper trading geçmişini ve açık pozisyonları sil, cüzdanı 10.000 TRY'ye sıfırla."""
    analyzer.positions.clear()
    # Reset sonrası mevcut mum uzunlukları eski sinyal durumuyla karşılaştırılmasın;
    # aksi halde yeni mum kapanana kadar tüm stratejiler sessiz kalabiliyordu.
    analyzer._last_signal_lengths.clear()
    analyzer._cooldown_until.clear()
    analyzer._timeout_block_until.clear()
    analyzer._hard_stop_block_until.clear()
    await database.reset_trading_data()
    await ws_manager.broadcast({"type": "reset", "data": {"ok": True}})
    return {"ok": True, "message": "Paper trading kayıtları silindi, cüzdan 10.000 TRY'ye sıfırlandı"}

@app.post("/api/backtest/run")
async def backtest_run(payload: dict):
    """Backtest çalıştır ve sonucu DB'ye kaydet."""
    symbol = str(payload.get("symbol", "BTCTRY")).upper()
    interval = str(payload.get("interval", "5m"))
    days_back = int(payload.get("days_back", 30))
    strategy = str(payload.get("strategy", "EMA_VWAP_PULLBACK"))
    params = payload.get("params") or {}
    order_size = float(payload.get("order_size", 500.0))
    stop_pct = float(payload.get("stop_loss_pct", 0.005))
    tp_pct = float(payload.get("take_profit_pct", config.TIME_DECAY_TP_1_PCT))
    trail_pct = float(payload.get("trailing_stop_pct", 0.003))
    try:
        run_id, result = await run_backtest(
            symbol, interval, days_back, strategy, params,
            order_size, stop_pct, tp_pct, trail_pct
        )
        return {"ok": True, "run_id": run_id, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/backtests")
async def backtest_list(limit: int = 50):
    """Kayıtlı backtest sonuçları."""
    return {"backtests": await database.get_backtests(limit)}

@app.post("/api/backtest/robustness")
async def backtest_robustness(payload: dict):
    """Run bounded multi-window paper research; never changes live paper state."""
    target = str(payload.get("symbol", "BTCTRY")).upper()
    interval = str(payload.get("interval", "5m"))
    strategy = str(payload.get("strategy", "EMA_VWAP_PULLBACK"))
    windows = [max(7, min(int(x), 90)) for x in (payload.get("windows") or [14, 30, 60])][:3]
    runs = []
    try:
        for days in windows:
            _, result = await run_backtest(target, interval, days, strategy, {}, 500.0,
                                           config.HARD_STOP_LOSS_PCT,
                                           config.TIME_DECAY_TP_1_PCT, 0.0)
            runs.append({"days_back": days, "net_pnl": result.get("net_pnl"),
                         "win_rate": result.get("win_rate"),
                         "profit_factor": result.get("profit_factor"),
                         "max_drawdown_pct": result.get("max_drawdown_pct"),
                         "trades": result.get("total_trades")})
        return {"ok": True, "paper_only": True, "windows": runs,
                "walk_forward_assessment": walk_forward_assessment(runs)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "paper_only": True}

@app.delete("/api/backtests/{run_id}")
async def backtest_delete(run_id: int):
    await database.delete_backtest(run_id)
    return {"ok": True}
