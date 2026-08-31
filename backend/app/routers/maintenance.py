"""Backfill/replay-parity/strategy-replay maintenance jobs and routes."""
import asyncio
import time
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import io
import csv
import json
from fastapi.responses import Response
from app.technical_analysis import calculate_snapshot, _atr, _bollinger, _ema

from app.config import config
from app import database
from app.state import market, analyzer
from app.api_common import _start_background, _record_strategy_scan_log
from app.binance_tr_public import klines as fetch_klines, historical_klines, trading_symbols

logger = logging.getLogger("scalper.maintenance")
router = APIRouter()


_historical_mtf_backfill = {"status": "idle", "phase": "idle", "progress": 0, "completed": 0, "total": 0, "message": None, "logs": [], "result": None, "started_at": None, "finished_at": None}
_historical_mtf_backfill_task = None
_replay_parity_backfill = {"status": "idle", "phase": "idle", "progress": 0, "completed": 0, "total": 0, "message": None, "logs": [], "result": None, "started_at": None, "finished_at": None}
_replay_parity_backfill_task = None

_strategy_replay_jobs = {}
_symbol_history_backfills = set()

def _replay_parity_config_snapshot():
    """Return only decision-relevant, JSON-safe settings for a scan record."""
    fields = (
        "ACTIVE_STRATEGY", "ACTIVE_STRATEGY_TIMEFRAME", "ORDER_PCT",
        "MAX_OPEN_POSITIONS", "PYRAMIDING_LAYERS", "COMMISSION_PCT",
        "ESTIMATED_SLIPPAGE_PCT", "HARD_STOP_LOSS_PCT",
        "BB_MFI_PINE_VERSION", "BB_MFI_BB_PERIOD", "BB_MFI_BB_STD_DEV",
        "BB_MFI_MFI_PERIOD", "BB_MFI_RSI_PERIOD", "BB_MFI_ENTRY_MFI_MAX",
        "BB_MFI_EXIT_RSI_MIN", "BB_MFI_EXIT_MFI_MIN",
        "BB_MFI_SELL_SIGNAL_CONFIRM_BARS",
        "BB_MFI_DIP_CONFIRMATION_ENABLED", "BB_MFI_DIP_MIN_CLOSE_POSITION",
        "BB_MFI_ENTRY_MFI_REVERSAL_ENABLED", "BB_MFI_ENTRY_MFI_REVERSAL_MIN_DELTA",
        "BB_MFI_BEAR_PRESSURE_FILTER_ENABLED", "BB_MFI_BEARISH_REQUIRE_REVERSAL_CONFIRMATION",
        "BB_MFI_PYRAMID_REQUIRE_NET_PROFIT", "BB_MFI_STOP_LOSS_PCT", "BB_MFI_TAKE_PROFIT_PCT",
        "PUMP_MONITOR_ENABLED", "PUMP_MONITOR_AUTO_TRADE", "PUMP_MONITOR_MIN_SCORE",
        "PUMP_MONITOR_MAX_OPEN_POSITIONS", "PUMP_MONITOR_REQUIRE_M15_BULLISH",
        "PUMP_MONITOR_BREAK_EVEN_ENABLED", "PUMP_MONITOR_BREAK_EVEN_TRIGGER_PCT",
        "PUMP_MONITOR_MAX_ENTRY_VOLUME_RATIO", "PUMP_MONITOR_FAST_FAIL_SEC",
        "PUMP_MONITOR_FAST_FAIL_MIN_PROGRESS_PCT",
        "TOP_GAINERS_AUTO_ACTIVATE", "TOP_GAINERS_LIMIT", "TOP_GAINERS_REFRESH_SEC",
        "SYMBOL_ACTIVITY_FILTER_ENABLED", "SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY",
        "SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT", "SYMBOL_ACTIVITY_MIN_ATR_PCT",
        "SYMBOL_ACTIVITY_MIN_VOLUME_RATIO",
        "SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED", "SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT",
        "SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT", "SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT",
    )
    snapshot = {field.lower(): getattr(config, field, None) for field in fields}
    snapshot["symbols"] = list(config.SYMBOLS)
    snapshot["symbol_order_pct"] = dict(config.SYMBOL_ORDER_PCT)
    return snapshot


def _replay_parity_candle_evidence(symbol: str, timeframe: str):
    """Keep the latest completed-candle identity, without duplicating history."""
    history = market.get_ut_kline(symbol, timeframe) or {}
    timestamps = list(history.get("timestamps") or [])
    result = {"timeframe": timeframe, "candle_count": len(timestamps), "last_closed_open_time_ms": timestamps[-2] if len(timestamps) >= 2 else None}
    for key in ("opens", "highs", "lows", "closes", "volumes"):
        values = list(history.get(key) or [])
        result[f"last_closed_{key[:-1]}"] = values[-2] if len(values) >= 2 else None
    return result


async def _persist_replay_parity_observation(entry: dict):
    """Persist one scan outcome with enough context for later decision matching."""
    symbol = str(entry.get("symbol") or "").upper()
    timeframe = str(entry.get("timeframe") or config.ACTIVE_STRATEGY_TIMEFRAME)
    try:
        metadata = {
            "schema": "replay-parity-v1",
            "paper_only": True,
            "scan": entry,
            "effective_config": _replay_parity_config_snapshot(),
            "portfolio": {
                "try_cash": await database.get_wallet_balance("TRY"),
                "open_symbols": sorted(analyzer.positions),
                "open_position_count": len(analyzer.positions),
            },
            "symbol_activity": dict(config.SYMBOL_ACTIVITY_STATUS.get(symbol) or {}),
            "closed_candle": _replay_parity_candle_evidence(symbol, timeframe) if symbol and symbol != "*" else None,
            "data_freshness": market.data_freshness(symbol, timeframe) if symbol and symbol != "*" else None,
        }
        await database.save_decision_log({
            "timestamp": entry["timestamp"], "symbol": symbol or None,
            "strategy": "REPLAY_PARITY", "decision": f"SCAN_{entry['status']}",
            "reason": entry.get("reason") or str(entry["status"]).lower(),
            "price": entry.get("price"), "metadata": metadata,
        })
    except Exception as exc:
        # Audit telemetry must never interrupt the paper strategy loop.
        logger.warning("Replay-parity observation could not be persisted: %s", exc)


async def backfill_symbol_history(symbol: str, days: int = 7):
    """Persist missing 5m history for one newly activated symbol in background."""
    symbol = str(symbol).upper()
    if symbol in _symbol_history_backfills:
        return
    _symbol_history_backfills.add(symbol)
    try:
        print(f"[History] arka plan backfill başladı | symbol={symbol} timeframe=5m days={days}", flush=True)
        raw = await historical_klines(symbol, "5m", days)
        now_ms = int(time.time() * 1000)
        rows = []
        for item in raw:
            if len(item) < 6:
                continue
            rows.append({"symbol": symbol, "timeframe": "5m", "open_time": int(item[0]), "close_time": int(item[6]) if len(item) > 6 else int(item[0]),
                         "open": float(item[1]), "high": float(item[2]), "low": float(item[3]), "close": float(item[4]), "volume": float(item[5]),
                         "quote_volume": float(item[7]) if len(item) > 7 else None, "trade_count": int(item[8]) if len(item) > 8 else None,
                         "source": "binance_tr_public_background", "fetched_at": now_ms})
        count = await database.upsert_market_candles(rows)
        print(f"[History] arka plan backfill tamamlandı | symbol={symbol} timeframe=5m rows={count}", flush=True)
    except Exception as exc:
        print(f"[History] arka plan backfill hatası | symbol={symbol} error={exc}", flush=True)
    finally:
        _symbol_history_backfills.discard(symbol)


async def microstructure_snapshot_loop():
    """Sample live bid/ask and depth only for symbols with open positions.

    Sürekli tüm sembolleri saniyede bir kaydetmek tabloyu aylık ~130M satıra
    (34 GB) büyütüyordu; mikro yapı kanıtının değeri işlem anında olduğundan
    yalnızca açık pozisyonu olan semboller örneklenir.
    """
    while True:
        try:
            open_symbols = {str(symbol or "").upper() for symbol in analyzer.positions}
            if open_symbols:
                captured_at = float(int(time.time()))
                rows = []
                now = time.time()
                for symbol in list(config.SYMBOLS):
                    if str(symbol).upper() not in open_symbols:
                        continue
                    flow = market.get_orderflow(symbol) or {}
                    updated_at = float(flow.get("updated_at") or 0)
                    if not updated_at or now - updated_at > 10:
                        continue
                    ticker = market.get_ticker(symbol) or {}
                    price = float(ticker.get("last_price") or 0)
                    bid_qty = float(flow.get("bid_qty") or 0)
                    ask_qty = float(flow.get("ask_qty") or 0)
                    imbalance = ((bid_qty - ask_qty) / (bid_qty + ask_qty)) if bid_qty + ask_qty else None
                    rows.append({
                        "symbol": str(symbol).upper(), "captured_at": captured_at,
                        "bid_price": flow.get("bid_price"), "ask_price": flow.get("ask_price"),
                        "bid_qty": bid_qty, "ask_qty": ask_qty,
                        "spread_pct": flow.get("spread_pct"),
                        "depth_try": (bid_qty + ask_qty) * price if price else None,
                        "orderflow_imbalance": imbalance, "source": flow.get("source") or "binance_tr_public_ws",
                        "updated_at": updated_at,
                    })
                if rows:
                    await database.upsert_microstructure_snapshots(rows)
        except Exception as exc:
            print(f"[Microstructure] snapshot yazma hatası: {exc}", flush=True)
        await asyncio.sleep(1)


def _public_kline_pack(rows, cutoff_ms=None):
    """Convert Binance public kline rows to the analyzer's causal OHLCV shape."""
    valid = [row for row in (rows or []) if isinstance(row, (list, tuple)) and len(row) >= 6 and (cutoff_ms is None or int(row[6] if len(row) > 6 else row[0]) <= int(cutoff_ms))]
    return {
        "opens": [float(row[1]) for row in valid],
        "highs": [float(row[2]) for row in valid],
        "lows": [float(row[3]) for row in valid],
        "closes": [float(row[4]) for row in valid],
        "volumes": [float(row[5]) for row in valid],
        "timestamps": [int(row[6] if len(row) > 6 else row[0]) for row in valid],
        "last_closed_at_ms": int(valid[-1][6] if len(valid[-1]) > 6 else valid[-1][0]) if valid else None,
    }


def _entry_derived_features(history, snapshot):
    """Causal, compact entry features added to historical MTF snapshots."""
    opens = history.get("opens", []); highs = history.get("highs", [])
    lows = history.get("lows", []); closes = history.get("closes", [])
    if not closes:
        return {}
    price = float(closes[-1]); result = {}
    ema20 = _ema(closes, 20)
    ema20_prev = _ema(closes[:-3], 20) if len(closes) >= 23 else None
    result["ema20_slope_3_pct"] = ((ema20 / ema20_prev - 1) * 100) if ema20 and ema20_prev else None
    adx = (snapshot.get("trend") or {}).get("adx") or {}
    plus_di, minus_di = adx.get("plus_di"), adx.get("minus_di")
    result["adx_di_gap"] = (plus_di - minus_di) if plus_di is not None and minus_di is not None else None
    result["adx"] = adx.get("adx")
    atr_now = _atr(highs, lows, closes, 14)
    atr_prev = _atr(highs[:-5], lows[:-5], closes[:-5], 14) if len(closes) >= 20 else None
    result["atr_expansion_ratio_5"] = (atr_now / atr_prev) if atr_now and atr_prev else None
    bb = _bollinger(closes)
    result["bb_width_pct"] = bb.get("width_pct") if bb else None
    candle_range = highs[-1] - lows[-1] if highs and lows else 0.0
    lower_wick = min(opens[-1], closes[-1]) - lows[-1] if candle_range > 0 else None
    result["lower_wick_ratio"] = (lower_wick / candle_range) if lower_wick is not None and candle_range > 0 else None
    result["close_position"] = ((closes[-1] - lows[-1]) / candle_range) if candle_range > 0 else None
    result["price_vs_ema20_pct"] = ((price / ema20 - 1) * 100) if ema20 else None
    return result


def _aggregate_mtf_entry_features(snapshots):
    alignments = [(item.get("trend") or {}).get("alignment") for item in snapshots.values()]
    bullish = sum(value == "bullish" for value in alignments)
    bearish = sum(value == "bearish" for value in alignments)
    return {
        "mtf_bullish_count": bullish,
        "mtf_bearish_count": bearish,
        "mtf_mixed_count": len(alignments) - bullish - bearish,
        "mtf_alignment_score": bullish - bearish,
        "mtf_all_ready": len(snapshots) == 5 and all(item.get("data_ready") for item in snapshots.values()),
    }


async def _historical_entry_mtf(symbol, entry_time, entry_price, order_value=500):
    """Build entry-time M1/M5/M15/H1/H4 snapshots from public OHLCV only."""
    entry_ms = int(float(entry_time) * 1000)
    flow = {"source": "binance_tr_public_historical", "spread_pct": None, "bid_qty": 0, "ask_qty": 0}
    snapshots = {}
    for timeframe in ("1m", "5m", "15m", "1h", "4h"):
        rows = await fetch_klines(symbol, timeframe, limit=300, end_time_ms=entry_ms)
        history = _public_kline_pack(rows, entry_ms)
        snapshot = calculate_snapshot(symbol, float(entry_price), {timeframe: history}, flow, 0, order_value, timeframe)
        snapshot["data_policy"] = "Binance TR public historical OHLCV; entry-time reconstruction; liquidity and orderflow unavailable"
        snapshot["historical_backfill"] = True
        snapshot["entry_time"] = float(entry_time)
        snapshot["derived_entry_features"] = _entry_derived_features(history, snapshot)
        snapshots[timeframe] = snapshot
    return snapshots


def _historical_backfill_log(level, message):
    _historical_mtf_backfill["logs"].append({"timestamp": time.time(), "level": level, "message": message})
    _historical_mtf_backfill["logs"] = _historical_mtf_backfill["logs"][-500:]


async def _run_historical_mtf_backfill(job_options=None):
    """Backfill old closed/open entries without changing balances or PnL."""
    options = job_options or {}
    force = bool(options.get("force"))
    trades = await database.get_trades(None)
    positions = await database.load_positions()
    targets = [("trade", row) for row in trades] + [("position", row) for row in positions.values()]
    if not force:
        filtered = []
        for target_type, row in targets:
            context = database._json_value(row.get("entry_context"), {}) if isinstance(row.get("entry_context"), str) else (row.get("entry_context") or {})
            if not ((context.get("mtf_backfill") or {}).get("version") == "public-entry-mtf-v1"):
                filtered.append((target_type, row))
        targets = filtered
    _historical_mtf_backfill.update({"status": "running", "phase": "fetch", "progress": 0, "completed": 0, "total": len(targets), "message": "Public history okunuyor", "logs": [], "result": None, "started_at": time.time(), "finished_at": None})
    _historical_backfill_log("info", f"Backfill başladı | hedef={len(targets)} | force={force} | timeframe=M1,M5,M15,H1,H4")
    updated = 0
    failed = 0
    skipped = 0
    try:
        for index, (target_type, row) in enumerate(targets, start=1):
            symbol = str(row.get("symbol") or "").replace("_", "").upper()
            entry_time = row.get("entry_time")
            target_id = row.get("id") if target_type == "trade" else symbol
            trade_id = row.get("trade_id") or f"legacy-{symbol}-{entry_time}"
            if not symbol or entry_time is None:
                skipped += 1
                _historical_backfill_log("warning", f"Atlandı | {target_type}={target_id} | sembol veya giriş zamanı eksik")
            else:
                try:
                    entry_price = float(row.get("entry_price") or 0)
                    order_value = entry_price * float(row.get("quantity") or 1) if entry_price else 500
                    snapshots = await _historical_entry_mtf(symbol, entry_time, entry_price or 500, order_value)
                    context = database._json_value(row.get("entry_context"), {}) if isinstance(row.get("entry_context"), str) else dict(row.get("entry_context") or {})
                    technical = dict(context.get("technical") or {})
                    technical["mtf_snapshots"] = snapshots
                    technical["mtf_timeframes"] = list(snapshots)
                    technical["derived_entry_features"] = _aggregate_mtf_entry_features(snapshots)
                    context["technical"] = technical
                    context["mtf_backfill"] = {"version": "public-entry-mtf-v1", "source": "binance_tr_public", "completed_at": time.time(), "entry_time": float(entry_time), "liquidity_fields": "unknown"}
                    await database.apply_historical_mtf_backfill(target_type, target_id, symbol, trade_id, context, snapshots)
                    updated += 1
                    _historical_backfill_log("info", f"Tamamlandı | {target_type}={target_id} | {symbol} | hazır={sum(1 for item in snapshots.values() if item.get('data_ready'))}/5")
                except Exception as exc:
                    failed += 1
                    _historical_backfill_log("error", f"Başarısız | {target_type}={target_id} | {symbol} | {type(exc).__name__}: {exc}")
            _historical_mtf_backfill["completed"] = index
            _historical_mtf_backfill["progress"] = round(index / max(1, len(targets)) * 100, 1)
        result = {"updated": updated, "failed": failed, "skipped": skipped, "total": len(targets), "paper_only": True, "pnl_changed": False}
        _historical_mtf_backfill.update({"status": "complete", "phase": "complete", "progress": 100, "message": "Backfill tamamlandı", "result": result, "finished_at": time.time()})
        _historical_backfill_log("success", f"Backfill tamamlandı | güncellenen={updated} başarısız={failed} atlanan={skipped}")
    except Exception as exc:
        _historical_mtf_backfill.update({"status": "error", "phase": "error", "message": str(exc), "finished_at": time.time()})
        _historical_backfill_log("error", f"Backfill durdu | {type(exc).__name__}: {exc}")


@router.get("/api/historical-mtf-backfill/status")
async def historical_mtf_backfill_status():
    return {"ok": True, "paper_only": True, **_historical_mtf_backfill}


@router.post("/api/historical-mtf-backfill/start")
async def start_historical_mtf_backfill(payload: dict = None):
    global _historical_mtf_backfill_task
    if _historical_mtf_backfill.get("status") == "running":
        return {"ok": True, "already_running": True, "paper_only": True, **_historical_mtf_backfill}
    options = payload or {}
    if options.get("force") is True and options.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="force backfill için confirm=true gerekli")
    _historical_mtf_backfill_task = asyncio.create_task(_run_historical_mtf_backfill(options), name="historical-mtf-backfill")
    return {"ok": True, "status": "queued", "paper_only": True}


def _replay_parity_backfill_log(level: str, message: str):
    _replay_parity_backfill["logs"].append({"timestamp": time.time(), "level": level, "message": message})
    _replay_parity_backfill["logs"] = _replay_parity_backfill["logs"][-500:]


async def _run_replay_parity_backfill():
    """Append only audited legacy decision evidence; never mutate trading data."""
    _replay_parity_backfill.update({"status": "running", "phase": "scan", "progress": 0, "completed": 0, "total": 0,
                                    "message": "Eski karar kayıtları taranıyor", "logs": [], "result": None,
                                    "started_at": time.time(), "finished_at": None})
    _replay_parity_backfill_log("info", "Replay-parity backfill başladı; işlemler, bakiyeler ve strateji ayarları değişmez.")

    def on_progress(summary):
        total = int(summary.get("eligible") or 0)
        completed = int(summary.get("processed") or 0)
        _replay_parity_backfill.update({"phase": "write", "total": total, "completed": completed,
                                        "progress": round(completed / max(1, total) * 100, 1),
                                        "message": f"{completed}/{total} denetim kaydı işlendi"})
        if completed and (completed % 250 == 0 or completed == total):
            _replay_parity_backfill_log("info", f"İlerleme: {completed}/{total}")

    try:
        result = await database.backfill_replay_parity_observations(apply=True, progress_callback=on_progress)
        _replay_parity_backfill.update({"status": "complete", "phase": "complete", "progress": 100,
                                        "completed": int(result.get("processed") or 0), "total": int(result.get("eligible") or 0),
                                        "message": "Backfill tamamlandı", "result": result, "finished_at": time.time()})
        _replay_parity_backfill_log("success", f"Tamamlandı | eklenen={result.get('written', 0)} | teknik={result.get('technical_context', 0)} | aktivite={result.get('activity_context', 0)} | unknown={result.get('unknown_context', 0)}")
    except Exception as exc:
        _replay_parity_backfill.update({"status": "error", "phase": "error", "message": str(exc), "finished_at": time.time()})
        _replay_parity_backfill_log("error", f"Backfill durdu | {type(exc).__name__}: {exc}")


@router.get("/api/replay-parity-backfill/status")
async def replay_parity_backfill_status():
    return {"ok": True, "paper_only": True, **_replay_parity_backfill}


@router.post("/api/replay-parity-backfill/start")
async def start_replay_parity_backfill():
    global _replay_parity_backfill_task
    if _replay_parity_backfill.get("status") == "running":
        return {"ok": True, "already_running": True, "paper_only": True, **_replay_parity_backfill}
    _replay_parity_backfill_task = asyncio.create_task(_run_replay_parity_backfill(), name="replay-parity-backfill")
    return {"ok": True, "status": "queued", "paper_only": True}


@router.get("/api/replay-parity-backfill/trades.csv")
async def download_replay_parity_trade_csv():
    """Download all closed paper-trade detail, including the saved entry context."""
    rows = await database.get_trade_export_rows()
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([
        "id", "trade_id", "symbol", "strategy", "side", "entry_time_unix", "exit_time_unix",
        "entry_price", "exit_price", "quantity", "pnl_try", "pnl_pct", "commission_try",
        "reason", "hold_seconds", "max_favorable_pct", "max_adverse_pct", "strategy_revision",
        "symbol_activity_json", "technical_json", "mtf_snapshots_json", "entry_context_json",
    ])
    for row in rows:
        context = row.get("entry_context") or {}
        technical = context.get("technical") or {}
        writer.writerow([
            row.get("id"), row.get("trade_id"), row.get("symbol"), row.get("strategy"), row.get("side"),
            row.get("entry_time"), row.get("exit_time"), row.get("entry_price"), row.get("exit_price"),
            row.get("quantity"), row.get("pnl"), row.get("pnl_pct"), row.get("commission"), row.get("reason"),
            row.get("hold_seconds"), row.get("max_favorable_pct"), row.get("max_adverse_pct"),
            context.get("strategy_revision"),
            json.dumps(context.get("symbol_activity") or context.get("activity") or {}, ensure_ascii=False, default=str),
            json.dumps(technical, ensure_ascii=False, default=str),
            json.dumps(technical.get("mtf_snapshots") or {}, ensure_ascii=False, default=str),
            json.dumps(context, ensure_ascii=False, default=str),
        ])
    return Response(content="\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="paper-islem-detaylari-{time.strftime("%Y%m%d-%H%M%S")}.csv"'})


async def backfill_missing_active_history():
    """At startup, queue only active symbols whose persisted 5m history is missing."""
    semaphore = asyncio.Semaphore(8)
    async def inspect(symbol):
        try:
            rows = await database.get_market_candles(symbol, "5m")
            if len(rows) < 2016:  # seven days of 5m candles, with a small tolerance
                async with semaphore:
                    await backfill_symbol_history(symbol, 7)
        except Exception as exc:
            print(f"[History] eksik veri kontrolü başarısız | symbol={symbol} error={exc}", flush=True)
    print(f"[History] başlangıç historical kontrolü | symbols={len(config.SYMBOLS)} timeframe=5m", flush=True)
    await asyncio.gather(*(inspect(symbol) for symbol in list(config.SYMBOLS)))
    print("[History] başlangıç historical kontrolü tamamlandı", flush=True)


async def _run_strategy_replay(job_id: str, candle_count: int = 6):
    """Evaluate the latest closed 5m candles without mutating strategy state."""
    job = _strategy_replay_jobs[job_id]
    # Replay salt-okunur bir tarihsel denetimdir; otomatik giriş döngüsündeki
    # PASSIVE ön elemesi burada kullanılmaz. Aksi halde aktivite filtresi tüm
    # ayarlı sembolleri dışarıda bırakıp replay'i symbols=0 ile başlatabilir.
    symbols = [s.upper() for s in config.SYMBOLS]
    job.update(status="running", total=0, completed=0, results=[])
    job["logs"].append({"level": "info", "message": f"Denetim başladı | strategy={config.ACTIVE_STRATEGY} timeframe=5m closed_candles={candle_count} symbols={len(symbols)}"})
    strategy_fn = analyzer.strategy_bb_mfi_mean_reversion if config.ACTIVE_STRATEGY == "BB_MFI_MEAN_REVERSION" else analyzer.strategy_mean_reversion
    try:
        async def load(symbol):
            rows = await database.get_market_candles(symbol, "5m")
            now_ms = int(time.time() * 1000)
            # Only completed candles may be evaluated.  The live in-progress
            # 5m candle would otherwise make a historical replay non-repeatable.
            rows = [row for row in rows if int(row.get("close_time") or 0) <= now_ms]
            # The cache is preferred.  If it cannot provide the warm-up window,
            # use the public endpoint for this read-only job; do not persist or
            # otherwise mutate market/strategy state from the replay path.
            if len(rows) < 20 + candle_count:
                raw = await fetch_klines(symbol, "5m", limit=400)
                public_rows = []
                for item in raw or []:
                    if len(item) < 6:
                        continue
                    close_time = int(item[6]) if len(item) > 6 else int(item[0])
                    if close_time > now_ms:
                        continue
                    public_rows.append({
                        "symbol": symbol, "timeframe": "5m", "open_time": int(item[0]),
                        "close_time": close_time, "open": float(item[1]), "high": float(item[2]),
                        "low": float(item[3]), "close": float(item[4]), "volume": float(item[5]),
                        "quote_volume": float(item[7]) if len(item) > 7 else None,
                        "trade_count": int(item[8]) if len(item) > 8 else None,
                        "source": "binance_tr_public_replay", "fetched_at": now_ms,
                    })
                rows = public_rows
            return symbol, rows[-400:]
        loaded = await asyncio.gather(*(load(symbol) for symbol in symbols), return_exceptions=True)
        usable = [(symbol, rows) for item in loaded if not isinstance(item, Exception) for symbol, rows in [item] if len(rows) >= candle_count]
        missing = sorted(set(symbols) - {symbol for symbol, _ in usable})
        if not symbols:
            raise ValueError("Aktif tarama sembol listesi boş; Ayarlar > Semboller bölümünden en az bir sembol seçilmeli")
        if not usable:
            raise ValueError("historical_candles içinde kullanılabilir 5m veri yok")
        job["total"] = len(usable) * candle_count
        if missing:
            job["logs"].append({"level": "warning", "message": f"Verisi bulunamayan semboller atlandı | missing={len(missing)} | örnek={', '.join(missing[:12])}"})
        job["results"] = []
        for candle_index in range(candle_count):
            signals = 0
            evaluated = 0
            for symbol, rows in usable:
                prefix = rows[:len(rows) - candle_count + candle_index + 1]
                fields = {"opens": "open", "highs": "high", "lows": "low", "closes": "close", "volumes": "volume"}
                kline = {key: [float(row[db_key]) for row in prefix] for key, db_key in fields.items()}
                candle = prefix[-1]
                close_time = int(candle["close_time"])
                label = datetime.fromtimestamp(close_time / 1000, tz=timezone.utc).astimezone().strftime("%d.%m %H:%M")
                if len(kline["closes"]) < 21:
                    action = "WARMUP"
                else:
                    evaluated += 1
                    action = "BUY_SIGNAL" if strategy_fn(kline, symbol) == "buy" else "NO_SIGNAL"
                if action == "BUY_SIGNAL":
                    signals += 1
                job["results"].append({
                    "symbol": symbol, "candle_number": candle_index + 1,
                    "timestamp": close_time / 1000, "close": kline["closes"][-1],
                    "action": action,
                })
                job["completed"] += 1
            job["logs"].append({"level": "summary", "message": f"Mum {candle_index + 1}/{candle_count} tamamlandı | evaluated={evaluated} signals={signals} no_signal={evaluated - signals}"})
        job.update(status="completed", finished_at=time.time())
        job["logs"].append({"level": "success", "message": "Denetim tamamlandı; canlı portföy ve strateji durumu değiştirilmedi."})
    except Exception as exc:
        job.update(status="error", error=str(exc), finished_at=time.time())
        job["logs"].append({"level": "error", "message": f"Replay hatası: {exc}"})
