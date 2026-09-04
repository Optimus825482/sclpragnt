"""Backtest run/list/robustness/delete endpoints."""
import asyncio
import json
import time
import logging

from fastapi import APIRouter, HTTPException, Request

from app.config import config
from app import database
from app.backtest import (run_backtest, run_custom_backtest, run_walk_forward, run_execution_stress,
                          run_parameter_sensitivity, run_holdout_test, run_statistical_validation,
                          get_backtest_data_quality, CUSTOM_IDENTIFIER_SCHEMA, CUSTOM_INDICATORS)
from app.binance_tr_public import historical_klines
from app.market_intelligence import walk_forward_assessment

logger = logging.getLogger("scalper.backtest")
router = APIRouter()


async def ensure_backtest_candles(symbol: str, interval: str, days_back: int):
    """Ensure the requested historical window exists before a UI backtest."""
    if not 1 <= days_back <= 365:
        raise ValueError("days_back 1 ile 365 arasında olmalıdır")
    symbol = symbol.upper()
    interval = interval.lower()
    existing = await database.get_market_candles(symbol, interval)
    now_ms = int(time.time() * 1000)
    requested_start = now_ms - days_back * 86400 * 1000
    expected = max(1, int(days_back * 86400 * 1000 / {
        "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
        "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000,
        "12h": 43_200_000, "1d": 86_400_000,
    }.get(interval, 300_000)))
    in_window = [row for row in existing if requested_start <= int(row.get("open_time", 0)) <= now_ms]
    latest = max((int(row.get("open_time", 0)) for row in in_window), default=0)
    # Tam pencere ve güncel son mum zaten varsa API çağrısı yapma.
    if len(in_window) >= int(expected * 0.98) and latest >= requested_start + int((days_back - 1) * 86400 * 1000):
        return {"status": "ready", "symbol": symbol, "interval": interval,
                "existing": len(in_window), "fetched": 0, "expected": expected}

    print(f"[Backtest data] {symbol} {interval} {days_back}d eksik; public mumlar çekiliyor", flush=True)
    raw = await historical_klines(symbol, interval, days_back)
    rows = []
    for item in raw:
        if len(item) < 6:
            continue
        try:
            values = [float(item[i]) for i in range(1, 6)]
            if not all(value == value and abs(value) != float("inf") for value in values):
                continue
            rows.append({
                "symbol": symbol, "timeframe": interval,
                "open_time": int(item[0]), "close_time": int(item[6]) if len(item) > 6 else int(item[0]),
                "open": values[0], "high": values[1], "low": values[2], "close": values[3],
                "volume": values[4], "quote_volume": float(item[7]) if len(item) > 7 else None,
                "trade_count": int(item[8]) if len(item) > 8 else None,
                "source": "binance_tr_public", "fetched_at": time.time(),
            })
        except (TypeError, ValueError, IndexError):
            continue
    written = await database.upsert_market_candles(rows)
    final_count = len(await database.get_market_candles(symbol, interval, requested_start, now_ms))
    print(f"[Backtest data] {symbol} {interval} hazır | fetched={len(rows)} written={written} candles={final_count}", flush=True)
    if not final_count:
        raise ValueError(f"{symbol} {interval} için public historical veri alınamadı")
    return {"status": "collected", "symbol": symbol, "interval": interval,
            "existing": len(in_window), "fetched": len(rows), "written": written,
            "candles": final_count, "expected": expected}

@router.post("/api/backtest/run")
async def backtest_run(payload: dict):
    """Backtest çalıştır ve sonucu DB'ye kaydet."""
    symbol = str(payload.get("symbol", "BTCTRY")).upper()
    interval = str(payload.get("interval", "5m"))
    days_back = int(payload.get("days_back", 30))
    strategy = str(payload.get("strategy", "EMA_VWAP_PULLBACK"))
    is_pine_v3 = strategy.upper() == "BB_MFI_MEAN_REVERSION"
    params = payload.get("params") or {}
    order_size = float(payload.get("order_size", 500.0))
    stop_pct = float(payload.get("stop_loss_pct", config.BB_MFI_STOP_LOSS_PCT if is_pine_v3 else 0.005))
    tp_pct = float(payload.get("take_profit_pct", config.BB_MFI_TAKE_PROFIT_PCT if is_pine_v3 else config.TIME_DECAY_TP_1_PCT))
    trail_pct = float(payload.get("trailing_stop_pct", 0.003))
    backtest_order_pct = float(payload.get("order_pct", config.ORDER_PCT)) if is_pine_v3 else None
    backtest_pyramiding = int(payload.get("pyramiding_layers", config.PYRAMIDING_LAYERS)) if is_pine_v3 else 3
    if is_pine_v3:
        if not 0.001 <= backtest_order_pct <= 1:
            raise ValueError("Backtest işlem yüzdesi %0,1 ile %100 arasında olmalıdır")
        if not 1 <= backtest_pyramiding <= 10:
            raise ValueError("Backtest piramitleme 1 ile 10 arasında olmalıdır")
    try:
        # Arayüz backtest'i historical tabloyu önceden doldurmayı kullanıcıya
        # bırakmamalı. İstenen pencere için public mumları çekip idempotent
        # şekilde tabloya yazarız; mevcut kayıtlar tekrar işlem görmez.
        # OOS doğrulaması da aynı isteğin parçasıdır: 3 fold için gereken
        # eğitim + test penceresi ana backtest gün sayısından uzun olabilir.
        oos_test_days = max(1, min(days_back // 3, 30))
        required_history_days = max(days_back, 7 + oos_test_days * 3)
        collection = await ensure_backtest_candles(symbol, interval, required_history_days)
        run_id, result = await run_backtest(
            symbol, interval, days_back, strategy, params,
            order_size, stop_pct, tp_pct, 0.0 if strategy.upper() == "BB_MFI_MEAN_REVERSION" else trail_pct,
            pyramiding_layers=backtest_pyramiding,
            order_pct=backtest_order_pct,
        )
        # A headline backtest is not accepted without a chronological OOS check.
        # Keep the base result for inspection, but expose the validation beside it.
        oos = await run_walk_forward(symbol, interval, strategy,
                                     train_days=max(7, min(days_back, 90)),
                                     test_days=max(1, min(days_back // 3, 30)),
                                     folds=3, order_size=order_size,
                                     stop_pct=stop_pct, tp_pct=tp_pct, params=params,
                                     pyramiding_layers=backtest_pyramiding,
                                     order_pct=backtest_order_pct)
        result["oos_validation"] = oos
        result["validation_status"] = "PASS" if oos.get("oos_consistent") else "FAIL"
        result["data_collection"] = collection
        return {"ok": True, "run_id": run_id, "result": result, "data_collection": collection}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/api/backtests")
async def backtest_list(limit: int = 50):
    """Kayıtlı backtest sonuçları."""
    return {"backtests": await database.get_backtests(limit)}

@router.post("/api/backtest/robustness")
async def backtest_robustness(payload: dict):
    """Run bounded multi-window paper research; never changes live paper state."""
    target = str(payload.get("symbol", "BTCTRY")).upper()
    interval = str(payload.get("interval", "5m"))
    strategy = str(payload.get("strategy", "EMA_VWAP_PULLBACK"))
    is_pine_v3 = strategy.upper() == "BB_MFI_MEAN_REVERSION"
    windows = [max(7, min(int(x), 90)) for x in (payload.get("windows") or [14, 30, 60])][:3]
    runs = []
    try:
        for days in windows:
            _, result = await run_backtest(target, interval, days, strategy, {}, 500.0,
                                           config.BB_MFI_STOP_LOSS_PCT if is_pine_v3 else config.HARD_STOP_LOSS_PCT,
                                           config.BB_MFI_TAKE_PROFIT_PCT if is_pine_v3 else config.TIME_DECAY_TP_1_PCT,
                                           0.0, pyramiding_layers=2 if is_pine_v3 else 3,
                                           order_pct=0.10 if is_pine_v3 else None)
            runs.append({"days_back": days, "net_pnl": result.get("net_pnl"),
                         "win_rate": result.get("win_rate"),
                         "profit_factor": result.get("profit_factor"),
                         "max_drawdown_pct": result.get("max_drawdown_pct"),
                         "trades": result.get("total_trades")})
        return {"ok": True, "paper_only": True, "windows": runs,
                "walk_forward_assessment": walk_forward_assessment(runs)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "paper_only": True}

@router.delete("/api/backtests/{run_id}")
async def backtest_delete(run_id: int, request: Request = None):
    from app.main import _require_admin
    _require_admin(request)
    await database.delete_backtest(run_id)
    return {"ok": True}
