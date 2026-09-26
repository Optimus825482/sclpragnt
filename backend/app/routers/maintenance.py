"""Backfill/replay-parity/strategy-replay maintenance jobs and routes."""
import asyncio
import bisect
import math
import time
import logging
from datetime import datetime, timezone
from functools import partial

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
import io
import csv
import json
from fastapi.responses import Response
from app.technical_analysis import calculate_snapshot, _atr, _bollinger, _ema
from app.ml_forecast import predict_target
from app.routers.velocity import (_velocity_ml_feature_dict,
                                  _velocity_horizon_from_candidate_id,
                                  _post_signal_window, _mfe_from_window,
                                  _exit_pct_from_window, round_trip_cost_pct)

from app.config import config
from app import database
from app.state import market, analyzer
from app.api_common import _start_background
from app.binance_tr_public import klines as fetch_klines, historical_klines, trading_symbols

logger = logging.getLogger("scalper.maintenance")
router = APIRouter()


_historical_mtf_backfill = {"status": "idle", "phase": "idle", "progress": 0, "completed": 0, "total": 0, "message": None, "logs": [], "result": None, "started_at": None, "finished_at": None}
_historical_mtf_backfill_task = None
_replay_parity_backfill = {"status": "idle", "phase": "idle", "progress": 0, "completed": 0, "total": 0, "message": None, "logs": [], "result": None, "started_at": None, "finished_at": None}
_replay_parity_backfill_task = None
_velocity_ml_backfill = {"status": "idle", "phase": "idle", "progress": 0, "completed": 0, "total": 0,
                         "updated": 0, "skipped": 0, "current_symbol": None, "message": None,
                         "logs": [], "result": None, "started_at": None, "finished_at": None}
_velocity_ml_backfill_task = None
_combined_radar_replay = {"status": "idle", "progress": 0, "completed": 0, "total": 0,
                          "message": None, "logs": [], "result": None,
                          "started_at": None, "finished_at": None}
_combined_radar_replay_task = None
_radar_outcomes_backfill = {"status": "idle", "phase": "idle", "progress": 0, "completed": 0, "total": 0,
                            "updated": 0, "skipped": 0, "current_symbol": None, "message": None,
                            "logs": [], "result": None, "started_at": None, "finished_at": None}
_radar_outcomes_backfill_task = None
_symbol_history_backfills = set()

def _replay_parity_config_snapshot():
    """Return only decision-relevant, JSON-safe settings for a scan record."""
    fields = (
        "ORDER_PCT",
        "MAX_OPEN_POSITIONS", "COMMISSION_PCT",
        "ESTIMATED_SLIPPAGE_PCT", "HARD_STOP_LOSS_PCT",
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
    """Persist one scan outcome with enough context for later decision matching.

    ⚠️ BAĞLANMAMIŞ KANCA (2026-09-10, Madde 21): çağıranı yok. Replay-parity
    gözlemlerini kalıcılaştırmak için yazılmış; toplu backfill yolu
    (``_run_replay_parity_backfill``) farklı bir fonksiyon kullanıyor. Canlı
    tarama gözlemi kaydı devreye girdiğinde çağrılmalı. Silinmedi — gerçek
    işlevsellik kaybı olurdu.
    """
    symbol = str(entry.get("symbol") or "").upper()
    timeframe = str(entry.get("timeframe") or "5m")
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


async def history_candle_loop(interval_minutes: int = 5):
    """Canlı 5m mum kalıcılığı: her 5 dakikada son kapanan barları upsert eder.

    historical_candles'a yalnızca tek seferlik backfill'ler yazıyordu; deploy
    aralarında tablo bayatlıyor ve ML eğitimi 'boş' pencereye düşüyordu.
    Evren: config.SYMBOLS + veritabanında zaten bulunan semboller (hız avcısı
    backfill'leriyle büyüyen evren). Kapanmamış bar yazılmaz.
    """
    semaphore = asyncio.Semaphore(8)
    await asyncio.sleep(120)  # startup backfill'i bitmeden çakışmasın
    while True:
        try:
            universe = list(dict.fromkeys(
                [s.upper() for s in config.SYMBOLS] + await database.get_market_symbols("5m")))
            now_ms = int(time.time() * 1000)
            written_total = 0
            async def persist(symbol: str) -> int:
                try:
                    raw = await fetch_klines(symbol, "5m", limit=3)
                    rows = []
                    for item in raw or []:
                        if len(item) < 6:
                            continue
                        open_time = int(item[0])
                        close_time = int(item[6]) if len(item) > 6 else open_time
                        if close_time > now_ms:  # henüz kapanmamış bar
                            continue
                        rows.append({"symbol": symbol, "timeframe": "5m", "open_time": open_time,
                                     "close_time": close_time, "open": float(item[1]), "high": float(item[2]),
                                     "low": float(item[3]), "close": float(item[4]), "volume": float(item[5]),
                                     "quote_volume": float(item[7]) if len(item) > 7 else None,
                                     "trade_count": int(item[8]) if len(item) > 8 else None,
                                     "source": "binance_tr_public_live", "fetched_at": now_ms})
                    return await database.upsert_market_candles(rows)
                except Exception as exc:
                    # G-21: `except Exception: return 0` mum kalıcılık hatasını
                    # tamamen sessizleştiriyordu; historical_candles sessizce
                    # bayatlayıp ML eğitimini boş pencereye düşürebiliyordu.
                    logger.warning("canlı mum kalıcılığı başarısız | symbol=%s error=%s: %s",
                                   symbol, type(exc).__name__, exc)
                    return 0
            async def worker(symbol: str):
                nonlocal written_total
                async with semaphore:
                    written_total += await persist(symbol)
            await asyncio.gather(*(worker(sym) for sym in universe))
            if written_total:
                print(f"[History] canlı mum kalıcılığı | symbols={len(universe)} rows={written_total}", flush=True)
        except Exception as exc:
            print(f"[History] canlı mum döngüsü hatası: {exc}", flush=True)
        await asyncio.sleep(interval_minutes * 60)


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
async def start_historical_mtf_backfill(payload: dict = None, request: Request = None):
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    global _historical_mtf_backfill_task
    if _historical_mtf_backfill.get("status") == "running":
        return {"ok": True, "already_running": True, "paper_only": True, **_historical_mtf_backfill}
    options = payload or {}
    if options.get("force") is True and options.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="force backfill için confirm=true gerekli")
    _historical_mtf_backfill_task = _start_background(partial(_run_historical_mtf_backfill, options), "historical-mtf-backfill", single_pass=True)
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
async def start_replay_parity_backfill(request: Request = None):
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    global _replay_parity_backfill_task
    if _replay_parity_backfill.get("status") == "running":
        return {"ok": True, "already_running": True, "paper_only": True, **_replay_parity_backfill}
    _replay_parity_backfill_task = _start_background(_run_replay_parity_backfill, "replay-parity-backfill", single_pass=True)
    return {"ok": True, "status": "queued", "paper_only": True}


def _velocity_ml_backfill_log(level: str, message: str):
    _velocity_ml_backfill["logs"].append({"timestamp": time.time(), "level": level, "message": message})
    _velocity_ml_backfill["logs"] = _velocity_ml_backfill["logs"][-500:]


async def _run_velocity_ml_backfill(options: dict | None = None):
    """velocity_candidates'in boş ML kolonlarını geçmiş 1m mumlardan geri doldurur.

    Her aday satırı için tarama anındaki 60'lık 1m penceresi geçmiş klines'ten
    kurulur, scan_one ile aynı özellikler hesaplanır ve MEVCUT ML modeliyle
    gölge tahmin üretilip satıra yazılır. Yalnız rapor/kalibrasyon verisi;
    işlem, PnL ve pozisyon etkisi yoktur. Model o günkü değil bugünkü
    artifacts olduğundan sonuç 'gölge' niteliğindedir.
    """
    options = options or {}
    days = max(0, int(options.get("days") or 0))
    state = _velocity_ml_backfill
    state.update({"status": "running", "phase": "scan", "progress": 0, "completed": 0, "total": 0,
                  "updated": 0, "skipped": 0, "current_symbol": None,
                  "message": "ML kolonları boş adaylar taranıyor", "logs": [],
                  "result": None, "started_at": time.time(), "finished_at": None})
    _velocity_ml_backfill_log("info", "ML geri doldurma başladı; geçmiş 1m mumlardan özellik hesaplanıp mevcut modelle gölge tahmin yazılacak. İşlem/PnL değişmez.")
    try:
        rows = await database.get_velocity_candidates_missing_ml()
        if days > 0:
            cutoff = time.time() - days * 86400
            rows = [r for r in rows if float(r["created_at"]) >= cutoff]
        if not rows:
            state.update({"status": "complete", "phase": "complete", "progress": 100,
                          "message": "Doldurulacak satır yok", "finished_at": time.time()})
            _velocity_ml_backfill_log("success", "Doldurulacak boş ML satırı bulunamadı.")
            return
        by_symbol: dict[str, list] = {}
        for r in rows:
            by_symbol.setdefault(str(r["symbol"]).upper(), []).append(r)
        total = len(rows)
        state.update({"phase": "predict", "total": total,
                      "message": f"{len(by_symbol)} sembol / {total} satır işlenecek"})
        updated = skipped = done = 0
        for index, (sym, sym_rows) in enumerate(sorted(by_symbol.items()), 1):
            state["current_symbol"] = sym
            sym_rows.sort(key=lambda r: float(r["created_at"]))
            first_created = float(sym_rows[0]["created_at"])
            last_created = float(sym_rows[-1]["created_at"])
            days_back = max(1, math.ceil((time.time() - first_created) / 86400) + 1)
            try:
                candles = await historical_klines(sym, "1m", days_back,
                                                  end_time_ms=int((last_created + 120) * 1000))
            except Exception as exc:
                skipped += len(sym_rows); done += len(sym_rows)
                _velocity_ml_backfill_log("error", f"{sym}: geçmiş mumlar alınamadı | {type(exc).__name__}: {exc}")
                _advance_ml_backfill_progress(state, done, total, updated, skipped)
                await asyncio.sleep(0.1)
                continue
            if not candles:
                skipped += len(sym_rows); done += len(sym_rows)
                _velocity_ml_backfill_log("warning", f"{sym}: geçmiş mum verisi yok, {len(sym_rows)} satır atlandı")
                _advance_ml_backfill_progress(state, done, total, updated, skipped)
                continue
            open_times = [int(c[0]) for c in candles]
            closes = [float(c[4]) for c in candles]
            highs = [float(c[2]) for c in candles]
            lows = [float(c[3]) for c in candles]
            vols = [float(c[5]) for c in candles]
            updates = []
            for r in sym_rows:
                cid = r["candidate_id"]
                created_ms = int(float(r["created_at"]) * 1000)
                # Tarama anındaki görünüm: open_time <= tespit anı olan son 60 mum.
                end_idx = bisect.bisect_right(open_times, created_ms)
                if end_idx < 30:
                    skipped += 1
                    continue
                start_idx = max(0, end_idx - 60)
                features = _velocity_ml_feature_dict(closes[start_idx:end_idx],
                                                     highs[start_idx:end_idx],
                                                     lows[start_idx:end_idx],
                                                     vols[start_idx:end_idx])
                horizon = _velocity_horizon_from_candidate_id(cid)
                try:
                    pred = predict_target(sym, features, horizon)
                except Exception:
                    pred = None
                if not pred:
                    skipped += 1
                    continue
                updates.append({"candidate_id": cid,
                                "ml_target_pct": float(pred["target_pct"]),
                                "ml_hit_probability": float(pred["hit_probability"])})
            if updates:
                try:
                    updated += await database.set_velocity_candidates_ml(updates)
                except Exception as exc:
                    skipped += len(updates)
                    _velocity_ml_backfill_log("error", f"{sym}: DB güncellemesi başarısız | {type(exc).__name__}: {exc}")
            done += len(sym_rows)
            _advance_ml_backfill_progress(state, done, total, updated, skipped, sym=sym)
            if index % 25 == 0 or index == len(by_symbol):
                _velocity_ml_backfill_log("info", f"İlerleme: {done}/{total} satır | güncellenen={updated} atlanan={skipped}")
            await asyncio.sleep(0.1)
        result = {"total": total, "updated": updated, "skipped": skipped,
                  "symbols": len(by_symbol), "days_filter": days or None,
                  "paper_only": True, "model_mode": "current-artifact-shadow"}
        state.update({"status": "complete", "phase": "complete", "progress": 100,
                      "completed": done, "updated": updated, "skipped": skipped,
                      "message": "ML geri doldurma tamamlandı", "result": result,
                      "current_symbol": None, "finished_at": time.time()})
        _velocity_ml_backfill_log("success", f"Tamamlandı | güncellenen={updated} atlanan={skipped} toplam={total}")
    except Exception as exc:
        state.update({"status": "error", "phase": "error",
                      "message": f"{type(exc).__name__}: {exc}", "finished_at": time.time()})
        _velocity_ml_backfill_log("error", f"Backfill durdu | {type(exc).__name__}: {exc}")


def _advance_ml_backfill_progress(state, done, total, updated, skipped, sym=None):
    state.update({"completed": done, "updated": updated, "skipped": skipped,
                  "progress": round(done / max(1, total) * 100, 1),
                  "message": f"{done}/{total} satır | güncellenen={updated} atlanan={skipped}"
                  + (f" | {sym}" if sym else "")})


@router.get("/api/velocity-ml-backfill/status")
async def velocity_ml_backfill_status():
    return {"ok": True, "paper_only": True, **_velocity_ml_backfill}


@router.post("/api/velocity-ml-backfill/start")
async def start_velocity_ml_backfill(payload: dict = None, request: Request = None):
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    global _velocity_ml_backfill_task
    if _velocity_ml_backfill.get("status") == "running":
        return {"ok": True, "already_running": True, "paper_only": True, **_velocity_ml_backfill}
    _velocity_ml_backfill_task = _start_background(partial(_run_velocity_ml_backfill, payload or {}), "velocity-ml-backfill", single_pass=True)
    return {"ok": True, "status": "queued", "paper_only": True}


@router.get("/api/replay-parity-backfill/trades.csv")
async def download_replay_parity_trade_csv(request: Request = None):
    """Download all closed paper-trade detail, including the saved entry context."""
    # G-05: tüm kapanan işlem geçmişi + giriş bağlamını döker; admin kapısı yoktu.
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
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


# ---------------------------------------------------------------------------
# BİRLEŞİK RADAR 24H REPLAY (Ayarlar > Radar sekmesi butonu, 2026-09-16)
# ---------------------------------------------------------------------------
def _combined_radar_replay_log(level: str, message: str) -> None:
    _combined_radar_replay["logs"].append({"timestamp": time.time(), "level": level, "message": str(message)})
    _combined_radar_replay["logs"] = _combined_radar_replay["logs"][-500:]


def _parse_float_list(raw, default: list[float]) -> list[float]:
    """İsteğe bağlı "1,1.5,2" (veya liste) girdisini pozitif float listesine çevirir.

    Geçersiz/boş girdi varsayılana düşer; okuma yolunda ASLA hata fırlatmaz
    (panelden gelen serbest metin 500 üretmemeli).
    """
    if raw in (None, ""):
        return list(default)
    items = list(raw) if isinstance(raw, (list, tuple)) else str(raw).split(",")
    out: list[float] = []
    for item in items:
        try:
            value = float(str(item).strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            out.append(value)
    return out or list(default)


def _load_replay_module():
    """Replay çekirdeğini scripts/... dosyasından GEÇ yükler (döngü yok)."""
    import importlib.util
    import pathlib
    script = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "combined_radar_replay_24h.py"
    spec = importlib.util.spec_from_file_location("combined_radar_replay_24h", str(script))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _replay_result_or_conflict() -> dict:
    """Birleşik radar replay sonucu — YOKSA 409 (boş CSV'yi 'başarılı' sayma).

    Gerçek olay (2026-09-17): kullanıcı yalnız BAŞLIK satırı içeren bir CSV indirdi
    ve bunu "replay çalıştı ama sonuç boş" diye okudu. Boş dosya HİÇBİR şey
    söylemiyordu: iş bitmemiş de olabilir, hata ile durmuş da. Bu yüzden sonuç
    yoksa indirme reddedilir ve durum + iş mesajı AÇIKÇA döner.
    """
    state = _combined_radar_replay
    result = state.get("result")
    if not result:
        status = state.get("status")
        reason = {"idle": "replay hiç çalıştırılmadı",
                  "running": "replay hâlâ çalışıyor",
                  "error": "replay HATA ile durdu"}.get(status, f"durum: {status}")
        raise HTTPException(status_code=409, detail=(
            f"Replay sonucu yok ({reason}). İş mesajı: {state.get('message') or '-'}. "
            f"Önce REPLAY BAŞLAT ile koşumu tamamla."))
    return result


async def _run_combined_radar_replay(options: dict) -> None:
    state = _combined_radar_replay
    state.update({"status": "running", "progress": 0, "completed": 0, "total": 0,
                  "message": "Replay hazırlanıyor", "result": None,
                  "started_at": time.time(), "finished_at": None, "logs": []})
    try:
        replay = _load_replay_module()
        hours = int(options.get("hours") or 24)
        symbols = [str(s).strip() for s in str(options.get("symbols") or "").split(",") if s.strip()] or None
        # 72 saatlik pencerede 400 sinyal tavanı akışları kırpardı (ölçüm
        # eksik dönem kapsardı); pencereyle ölçeklenir, açık değer her zaman kazanır.
        max_signals = int(options.get("max_signals")
                          or (400 if hours <= 24 else 400 * max(1, hours // 24)))
        confluence_window = options.get("confluence_window")
        skip_fetch = bool(options.get("skip_fetch", False))
        # GEOMETRİ TARAMASI: buton panelinden açılabilir (varsayılan AÇIK — asıl
        # soru "kenar var mı" olduğu için tarama asıl çıktıdır).
        sweep = bool(options.get("sweep", True))
        sweep_targets = _parse_float_list(options.get("sweep_targets"),
                                          [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0])
        sweep_sls = _parse_float_list(options.get("sweep_sls"), [0.5, 0.75, 1.0, 1.5, 2.0, 3.0])
        # Ratchet açıklığı: MFE'nin ne kadarının korunduğunu belirleyen boyut.
        sweep_gaps = _parse_float_list(options.get("sweep_gaps"), [0.3, 0.6, 1.0, 1.5])
        # OUT-OF-SAMPLE: pencereyi geçmişe kaydırır. Tek dönemde ızgaranın
        # MAKSİMUMUNU seçmek iyimser yanlıdır; aynı ızgara ikinci bir dönemde
        # koşulup en iyi hücrenin DAYANIP DAYANMADIĞI ölçülür.
        offset_hours = max(0.0, float(options.get("offset_hours") or 0))

        _combined_radar_replay_log(
            "info", f"Birleşik radar replay başladı | pencere={hours}h"
                    + (f" | offset={offset_hours:g}h (out-of-sample)" if offset_hours else "")
                    + f" | skip_fetch={skip_fetch}")

        def on_progress(done: int, total: int) -> None:
            state.update({"completed": done, "total": total,
                          "progress": round(done / max(1, total) * 100, 1)})
            state["message"] = f"{done}/{total} sinyal ölçüldü"

        def on_log(message: str) -> None:
            _combined_radar_replay_log("info", str(message))

        result = await replay.build_report(
            hours, symbols, max_signals, confluence_window, skip_fetch,
            out_path=None, log=on_log, progress=on_progress,
            sweep=sweep, sweep_targets=sweep_targets, sweep_sls=sweep_sls,
            sweep_gaps=sweep_gaps, offset_hours=offset_hours)
        # OOS DOĞRULAMA: `offset_hours > 0` verildiğinde baz dönem de koşulur ve
        # aynı hücre iki dönemde karşılaştırılır. İki raporu elle kıyaslamak
        # yerine karar TEK raporda ve önceden sabitlenmiş kuralla verilir —
        # böylece sonuç görüldükten sonra yorum değiştirilemez.
        if offset_hours > 0:
            _combined_radar_replay_log(
                "info", f"OOS doğrulama: baz dönem (offset=0) ayrıca koşuluyor "
                        f"— aynı ızgara, {offset_hours:g} saat kaydırılmış ikinci dönem.")
            base_result = await replay.build_report(
                hours, symbols, max_signals, confluence_window, skip_fetch,
                out_path=None, log=on_log,
                sweep=sweep, sweep_targets=sweep_targets, sweep_sls=sweep_sls,
                sweep_gaps=sweep_gaps, offset_hours=0)
            verdict_lines = replay.attach_oos_comparison(base_result, result)
            result = base_result
            for line in verdict_lines:
                if line.strip():
                    _combined_radar_replay_log("info", line)
        state.update({"status": "complete", "progress": 100,
                      "message": "Replay tamamlandı — rapor ve CSV hazır",
                      "result": result, "finished_at": time.time()})
        _combined_radar_replay_log("success", "Replay tamamlandı — rapor ve CSV hazır")
    except Exception as exc:
        state.update({"status": "error", "message": f"{type(exc).__name__}: {exc}",
                      "finished_at": time.time()})
        _combined_radar_replay_log("error", f"Replay durdu | {type(exc).__name__}: {exc}")


@router.get("/api/combined-radar-replay/status")
async def combined_radar_replay_status():
    """Birleşik radar replay işinin canlı durumu (log + ilerleme + sonuç)."""
    return {"ok": True, "paper_only": True, **_combined_radar_replay}


@router.post("/api/combined-radar-replay/start")
async def start_combined_radar_replay(payload: dict = None, request: Request = None):
    """Birleşik radar 24h replay'ini arka planda başlat (yalnız admin)."""
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    global _combined_radar_replay_task
    if _combined_radar_replay.get("status") == "running":
        return {"ok": True, "already_running": True, "paper_only": True, **_combined_radar_replay}
    _combined_radar_replay_task = _start_background(
        partial(_run_combined_radar_replay, payload or {}), "combined-radar-replay", single_pass=True)
    return {"ok": True, "paper_only": True, **_combined_radar_replay}


@router.get("/api/combined-radar-replay/report.csv")
async def download_combined_radar_replay_csv(request: Request = None):
    """Replay'de ölçülen her sinyali CSV olarak indir (yalnız admin).

    SAVUNMACI (2026-09-16): satır şekli beklenmedik olsa bile 500 vermez. Eskiden
    `",".join(s.get("sources") or [])` çağrısı `sources=[None]` geldiğinde
    "TypeError: sequence item 0: expected str instance, NoneType found" ile
    **500** üretiyordu (journal satırlarında `source` alanı yok). Artık tüm
    değerler güvenli biçimde stringe çevrilir ve bozuk satır ATLANIR.
    """
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    result = _replay_result_or_conflict()
    signals = result.get("signals") or []
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["stream", "symbol", "detected_at_unix", "price", "target_pct", "score",
                     "confluence", "sources", "horizon_minutes", "exit_reason", "exit_price",
                     "gross_pct", "net_pct", "mfe_pct", "mae_pct", "hold_minutes"])

    def _src(value):
        if not value:
            return ""
        if isinstance(value, (list, tuple)):
            return ",".join(str(item) for item in value if item)
        return str(value)

    skipped = 0
    for s in signals:
        if not isinstance(s, dict):
            skipped += 1
            continue
        try:
            writer.writerow([
                s.get("stream"), s.get("symbol"), s.get("detected_at"), s.get("price"),
                s.get("target_pct"), s.get("score"), s.get("confluence"),
                _src(s.get("sources")), s.get("horizon_minutes"),
                s.get("exit_reason"), s.get("exit_price"),
                s.get("gross_pct"), s.get("net_pct"), s.get("mfe_pct"), s.get("mae_pct"),
                s.get("hold_minutes"),
            ])
        except Exception as exc:  # tek bozuk satır tüm indirmeyi düşürmesin
            skipped += 1
            logger.warning("replay CSV satırı atlandı (%s): %s", s.get("symbol"), exc)
    if skipped:
        logger.warning("replay CSV: %d satır atlandı", skipped)
    return Response(content="\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="birlesik-radar-replay-{time.strftime("%Y%m%d-%H%M%S")}.csv"'})


@router.get("/api/combined-radar-replay/sweep.csv")
async def download_combined_radar_replay_sweep_csv(request: Request = None):
    """Geometri taraması (sabit TP/SL ızgarası) sonucunu CSV olarak indir (admin).

    Raporun asıl karar çıktısı budur: her (hedef, stop, akış) hücresi için
    n / ort.net% / medyan / toplam / kazanma%. Sonuç YOKSA 409 döner (boş dosya
    "başarılı indirme" gibi görünmesin); sonuç var ama tarama boşsa yalnız başlık
    satırı yazılır.
    """
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    result = _replay_result_or_conflict()
    sweep_rows = result.get("sweep") or []
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["hedef_pct", "stop_pct", "ratchet_gap_pct", "stream", "n", "ort_net_pct",
                     "medyan_net_pct", "toplam_net_pct", "kazanma_pct"])
    for row in sweep_rows:
        if not isinstance(row, dict):
            continue
        writer.writerow([row.get("target_pct"), row.get("sl_pct"), row.get("gap_pct"),
                         row.get("stream"), row.get("n"), row.get("avg_net_pct"),
                         row.get("median_net_pct"), row.get("total_net_pct"),
                         row.get("win_rate")])
    return Response(content="\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="birlesik-radar-geometri-taramasi-{time.strftime("%Y%m%d-%H%M%S")}.csv"'})


async def backfill_missing_active_history():
    """At startup, queue active symbols whose persisted 5m history is missing or stale.

    2026-09-26 (deploy düzeltmesi): bu fonksiyon `_start_background` ile
    BAŞLATILIYOR ama gövdesi `asyncio.gather` ile TÜM sembolleri bekliyordu
    (70 sembol × [get_market_candles + historical_klines + upsert]). Her
    `database._run_db` çağrısı `run_in_executor` ile varsayılan thread
    havuzuna, her bağlantı ise `max_size=8` havuzuna gidiyordu. Sonuç:
    açılışta bu döngü dakikalarca event loop'u meşgul ediyor, uvicorn
    bağlantı kabul ediyor ama `/health` YANIT VERMIYOR (TimeoutError,
    bağlantı reddi değil) → container healthcheck başarısız → Coolify
    deploy'u başarısız sayıyordu. Log kanıtı: "başlangıç historical
    kontrolü" ve "arka plan backfill başladı" satırlarından SONRA
    "Application startup complete" geliyor, arada backfill'ler sürüyordu.

    Çözüm iki katmanlıdır:

    1. Backfill'ler startup'ı BEKLETMER (aşağıdaki `_start_background`).
    2. Backfill'ler kontrollü sırayla çalışır. İlk denemede her eksik
       sembol için ayrı `_start_background` çağrısı yapılmıştı; bu 70
       PARALEL görev demek ve hepsi aynı `max_size=8` bağlantı havuzunu
       kullanıyordu. Log kanıtı: onlarca "backfill başladı" satırı
       vardı, "backfill tamamlandı" HİÇ yoktu — hepsi kuyrukta
       sıkışmıştı. 8 GB sunucuda bu, event loop'un her isteği
       geciktiriyor, `/api/*` istekleri 499 alıyor ve backend
       `unhealthy` oluyordu.
    """
    symbols = list(config.SYMBOLS)
    now_ms = int(time.time() * 1000)
    stale_ms = 30 * 60 * 1000
    print(f"[History] başlangıç historical kontrolü | symbols={len(symbols)} timeframe=5m", flush=True)

    # Tarama: DB havuzuna gider ama YALNIZCA SELECT yapar. Backfill ile
    # aynı anda çalışmaması için havuzun TAMAMINI bırakmıyoruz.
    scan_semaphore = asyncio.Semaphore(4)
    stale_symbols: list[str] = []

    async def inspect(symbol):
        try:
            rows = await database.get_market_candles(symbol, "5m")
            newest = max((int(r.get("open_time") or 0) for r in rows), default=0)
            # Satır sayısı tek başına yetmez: yazıcı döngü olmadan sayı sabit
            # kalır ve eski tarihli 2016+ satır "taze" sanılır. Mumlar 30 dakikadan
            # eskiyse de backfill çalışsın.
            if len(rows) < 2016 or newest < now_ms - stale_ms:
                stale_symbols.append(symbol)
        except Exception as exc:
            print(f"[History] eksik veri kontrolü başarısız | symbol={symbol} error={exc}", flush=True)

    async def scan(symbol):
        async with scan_semaphore:
            await inspect(symbol)

    await asyncio.gather(*(scan(symbol) for symbol in symbols))
    print(
        f"[History] başlangıç historical kontrolü tamamlandı | "
        f"backfill_gereken={len(stale_symbols)} (kuyruğa alındı)",
        flush=True,
    )

    if not stale_symbols:
        return

    # Backfill işleri: TEK döngü, sınırlı eşzamanlılık. Her biri REST
    # (klines) + DB (upsert) yapıyor; ikisi de aynı 8 bağlantılı havuzu
    # ve thread havuzunu kullanıyor. Sınırsız paralellik bu ikisini
    # tüketir.
    async def drain_backfills():
        semaphore = asyncio.Semaphore(2)

        async def one(symbol):
            async with semaphore:
                await backfill_symbol_history(symbol, 7)

        for chunk_start in range(0, len(stale_symbols), 8):
            chunk = stale_symbols[chunk_start:chunk_start + 8]
            await asyncio.gather(*(one(symbol) for symbol in chunk))
            # 8'lik gruplar arasında nefes: REST rate limit'i ve DB havuzu
            # diğer döngülere (strategy, alert, broadcast) dönsün.
            await asyncio.sleep(1.0)
        print(f"[History] backfill kuyruğu tamamlandı | toplam={len(stale_symbols)}", flush=True)

    _start_background(drain_backfills, "history-backfill-drain", single_pass=True)


# ---------------------------------------------------------------------------
# RADAR ÖLÇÜMLERİ YENİDEN HESAPLAMA (BACKFILL / REPLAY)
# ---------------------------------------------------------------------------
def _radar_outcomes_log(level: str, message: str) -> None:
    _radar_outcomes_backfill["logs"].append({
        "timestamp": time.time(),
        "level": level,
        "message": str(message)
    })
    _radar_outcomes_backfill["logs"] = _radar_outcomes_backfill["logs"][-500:]


async def _run_radar_outcomes_backfill(payload: dict):
    _radar_outcomes_backfill.update({
        "status": "running", "phase": "fetching", "progress": 0, "completed": 0,
        "total": 0, "updated": 0, "skipped": 0, "current_symbol": None,
        "message": "Ölçülemeyen bildirimler taranıyor...",
        "logs": [], "result": None, "started_at": time.time(), "finished_at": None,
    })
    _radar_outcomes_log("info", "Radar bildirimleri ölçüm yeniden hesaplama süreci başlatıldı.")
    day = payload.get("day")
    force = bool(payload.get("force", False))
    now = time.time()
    try:
        matches = await database.get_monitoring_velocity_matches(limit=None, day=day if day and day != "all" else None)
        unmeasured = []
        for row in matches:
            detected_at = float(row.get("detected_at") or 0)
            horizon = int(row.get("horizon_minutes") or 5)
            window_closed = bool(detected_at and horizon and (now - detected_at) >= (horizon + 1) * 60)
            cstatus = row.get("candidate_status")
            mfe = row.get("mfe_pct")
            if window_closed and (force or cstatus != "evaluated" or mfe is None):
                unmeasured.append(row)

        total = len(unmeasured)
        if total == 0:
            _radar_outcomes_log("info", "Ölçülecek eksik bildirim bulunamadı. Tüm bildirimler güncel.")
            _radar_outcomes_backfill.update({
                "status": "complete", "phase": "done", "progress": 100,
                "message": "Ölçülecek eksik bildirim bulunamadı.",
                "finished_at": time.time(), "result": {"total": 0, "updated": 0, "skipped": 0}
            })
            return

        _radar_outcomes_backfill.update({
            "phase": "evaluating", "total": total,
            "message": f"Toplam {total} adet bildirim ölçülüyor..."
        })
        _radar_outcomes_log("info", f"Toplam {total} adet ölçülmemiş bildirim bulundu. Binance TR 1m barları taranıyor...")

        done = 0
        updated = 0
        skipped = 0

        for item in unmeasured:
            notif_id = item.get("id")
            symbol = str(item.get("symbol") or "").upper()
            detected_at = float(item.get("detected_at") or 0)
            horizon = int(item.get("horizon_minutes") or getattr(config, "MONITORING_OUTCOME_WINDOW_MINUTES", 60))
            target = float(item.get("target_pct") or 2.0)
            price = float(item.get("price") or 0)
            timestr = time.strftime('%d/%m %H:%M', time.localtime(detected_at))
            _radar_outcomes_backfill["current_symbol"] = f"{symbol} ({timestr})"

            created_ms = int(detected_at * 1000)
            due_ms = created_ms + horizon * 60_000
            rows = None
            try:
                rows = await fetch_klines(symbol, "1m", horizon + 15, created_ms, due_ms + 65_000)
            except Exception as exc:
                _radar_outcomes_log("warning", f"{symbol} ({timestr}): kline çekilemedi: {exc}")

            window = _post_signal_window(rows, created_ms, due_ms) if rows else []
            if not window and rows:
                window = [r for r in rows if int(r[0]) >= created_ms - 30_000 and int(r[0]) <= due_ms + 60_000]

            if window:
                entry = price if price > 0 else float(window[0][1])
                mfe_pct = _mfe_from_window(window, entry)
                exit_pct = _exit_pct_from_window(window, entry)
                net_pct = (exit_pct - round_trip_cost_pct()) if exit_pct is not None else None
                touched = (mfe_pct >= target) if (mfe_pct is not None and target > 0) else False

                cand_id = item.get("candidate_id") or f"backfill-{int(created_ms)}-{symbol}"
                await database.upsert_evaluated_velocity_candidate(
                    cand_id,
                    symbol=symbol,
                    created_at=detected_at,
                    price=entry,
                    target_pct=target,
                    mfe_pct=round(mfe_pct, 4) if mfe_pct is not None else 0.0,
                    touched_target=touched,
                    exit_pct=round(exit_pct, 4) if exit_pct is not None else None,
                    net_pct=round(net_pct, 4) if net_pct is not None else None,
                    details={"window_bars": len(window), "entry": entry, "backfill": True},
                    notification_id=notif_id
                )
                updated += 1
                status_txt = "TAMAMEN BAŞARILI" if touched else "KISMİ" if (mfe_pct is not None and mfe_pct > 0) else "BAŞARISIZ"
                mfe_str = f"%{mfe_pct:.2f}" if mfe_pct is not None else "0.00"
                _radar_outcomes_log("success", f"✓ {symbol} ({timestr}) | MFE: {mfe_str} | Hedef: %{target:g} -> {status_txt}")
            else:
                skipped += 1
                _radar_outcomes_log("warning", f"⚠ {symbol} ({timestr}): Bu ufukta kapanmış M1 mum bulunamadı.")

            done += 1
            progress = int((done / total) * 100)
            _radar_outcomes_backfill.update({
                "completed": done, "updated": updated, "skipped": skipped,
                "progress": progress,
                "message": f"{done}/{total} bildirim işlendi ({updated} güncellendi, {skipped} atlandı)"
            })
            await asyncio.sleep(0.05)

        _radar_outcomes_backfill.update({
            "status": "complete", "phase": "done", "progress": 100,
            "current_symbol": None, "finished_at": time.time(),
            "message": f"Tamamlandı: {updated} bildirim ölçüldü, {skipped} atlandı.",
            "result": {"total": total, "updated": updated, "skipped": skipped}
        })
        _radar_outcomes_log("success", f"Radar ölçüm backfill tamamlandı! {updated}/{total} bildirim başarıyla değerlendirildi.")
    except Exception as exc:
        logger.exception("radar outcomes backfill hatası: %s", exc)
        _radar_outcomes_backfill.update({
            "status": "error", "phase": "error", "finished_at": time.time(),
            "message": f"Hata oluştu: {exc}"
        })
        _radar_outcomes_log("error", f"İşlem sırasında hata: {exc}")


@router.get("/api/radar-outcomes-backfill/status")
async def radar_outcomes_backfill_status():
    return {"ok": True, "paper_only": True, **_radar_outcomes_backfill}


@router.post("/api/radar-outcomes-backfill/start")
async def start_radar_outcomes_backfill(payload: dict = None, request: Request = None):
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    global _radar_outcomes_backfill_task
    if _radar_outcomes_backfill.get("status") == "running":
        return {"ok": True, "already_running": True, "paper_only": True, **_radar_outcomes_backfill}
    _radar_outcomes_backfill_task = _start_background(
        partial(_run_radar_outcomes_backfill, payload or {}),
        "radar-outcomes-backfill", single_pass=True
    )
    return {"ok": True, "status": "queued", "paper_only": True}


