"""Paper-only exit-noise research for green-kernel M5 entries."""
import argparse
import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, trading_symbols_with_filters
from scripts.replay_kernel_green_red3_m5 import ALLOCATION_PCT, MS_5M, features
from scripts.replay_ldc_kernel_m1 import COMMISSION_PCT, INITIAL_BALANCE_TRY, SLIPPAGE_TICKS, iso, normalize


EXIT_RULES = {
    "red3": "3 consecutive red kernel bars",
    "red3_ema30": "3 red bars plus close below EMA30",
    "red3_rsi50": "3 red bars plus RSI10 below 50",
    "red2_atr10": "2 red bars plus kernel decline >=0.10 ATR14",
    "red3_atr10": "3 red bars plus kernel decline >=0.10 ATR14",
}


def simulate(rows, key, tick_size, cost_multiplier):
    commission, slippage = COMMISSION_PCT * cost_multiplier, SLIPPAGE_TICKS * cost_multiplier
    cash, position, trades, peak, dd = INITIAL_BALANCE_TRY, None, [], INITIAL_BALANCE_TRY, 0.0
    for row in rows:
        if position and row[f"exit_{key}"]:
            fill = max(0.0, row["close"] - slippage * tick_size)
            gross = position["qty"] * fill; fee = gross * commission; cash += gross - fee
            trades.append({"entry_time": position["time"], "exit_time": row["time"], "pnl_try": gross - fee - position["cost"],
                           "fees_try": position["fee"] + fee, "reason": key})
            position = None
        elif not position and row["green_transition"]:
            allocation = cash * ALLOCATION_PCT; fill = row["close"] + slippage * tick_size
            notional = allocation / (1 + commission); fee = notional * commission; cash -= allocation
            position = {"time": row["time"], "qty": notional / fill, "cost": allocation, "fee": fee}
        marked = cash if not position else cash + position["qty"] * max(0.0, row["close"] - slippage * tick_size) * (1 - commission)
        peak, dd = max(peak, marked), max(dd, peak - marked)
    if position:
        row = rows[-1]; fill = max(0.0, row["close"] - slippage * tick_size); gross = position["qty"] * fill; fee = gross * commission; cash += gross - fee
        trades.append({"entry_time": position["time"], "exit_time": row["time"], "pnl_try": gross - fee - position["cost"], "fees_try": position["fee"] + fee, "reason": "window_mark_to_market"})
    pnl = [trade["pnl_try"] for trade in trades]; fees = sum(trade["fees_try"] for trade in trades); gains, losses = sum(x for x in pnl if x > 0), sum(x for x in pnl if x <= 0)
    return {"trades": len(trades), "net_pnl_try": round(sum(pnl), 2), "gross_pnl_try": round(sum(pnl) + fees, 2), "fees_try": round(fees, 2),
            "wins": sum(x > 0 for x in pnl), "losses": sum(x <= 0 for x in pnl), "profit_factor": round(gains / abs(losses), 3) if losses else None,
            "expectancy_try": round(sum(pnl) / len(pnl), 2) if pnl else 0.0, "max_drawdown_try": round(dd, 2), "final_balance_try": round(cash, 2),
            "reconciliation_delta_try": round(cash - INITIAL_BALANCE_TRY - sum(pnl), 8), "exit_reasons": dict(Counter(t["reason"] for t in trades)), "trades_detail": trades}


def aggregate(folds):
    trades = [trade for fold in folds for trade in fold["result"]["trades_detail"]]
    pnl = [trade["pnl_try"] for trade in trades]; fees = sum(trade["fees_try"] for trade in trades)
    gains, losses = sum(x for x in pnl if x > 0), sum(x for x in pnl if x <= 0)
    return {"folds": len(folds), "trades": len(trades), "net_pnl_try": round(sum(pnl), 2), "gross_pnl_try": round(sum(pnl) + fees, 2), "fees_try": round(fees, 2),
            "wins": sum(x > 0 for x in pnl), "losses": sum(x <= 0 for x in pnl), "profit_factor": round(gains / abs(losses), 3) if losses else None,
            "expectancy_try": round(sum(pnl) / len(pnl), 2) if pnl else 0.0}


async def main(args):
    cutoff = args.end_time_ms if args.end_time_ms is not None else (int(time.time() * 1000) - args.end_minutes_ago * 60_000) // MS_5M * MS_5M - 1
    start, symbol = cutoff - args.hours * 3_600_000, args.symbol.upper().replace("_", "")
    fetch_days = max(args.fetch_days, args.walk_forward_days + 2)
    raw = await historical_klines(symbol, "5m", fetch_days, cutoff); candles = normalize(raw, cutoff)
    tick = float((await trading_symbols_with_filters("TRY")).get(symbol, {}).get("tick_size") or .01)
    rows = features(candles, start, cutoff)
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(), "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "source": "Binance TR public completed M5 OHLCV", "provenance": {"symbol": symbol, "m5_closed_candles": len(candles), "fetch_days": fetch_days, "tick_size_try": tick},
              "entry": "kernel green transition only", "exit_rules": EXIT_RULES, "execution": {"initial_balance_try": INITIAL_BALANCE_TRY, "allocation_pct": ALLOCATION_PCT, "commission_pct_each_side": COMMISSION_PCT * args.cost_multiplier, "slippage_ticks_each_side": SLIPPAGE_TICKS * args.cost_multiplier, "cost_multiplier": args.cost_multiplier},
              "limitations": ["Research-only causal port of KernelFunctions/2.", "Public OHLCV lacks intrabar sequence, historical spread and depth."]}
    result["variants"] = {key: simulate(rows, key, tick, args.cost_multiplier) for key in EXIT_RULES}
    if args.walk_forward_days:
        folds = []
        for offset in range(args.walk_forward_days - 1, -1, -1):
            fold_end = cutoff - offset * 86_400_000
            fold_start = fold_end - 86_400_000 + 1
            fold_rows = features(candles, fold_start, fold_end)
            folds.append({"start": iso(fold_start), "end": iso(fold_end), "result": simulate(fold_rows, "red3", tick, args.cost_multiplier)})
        result["walk_forward_red3"] = {"folds": folds, "aggregate": aggregate(folds)}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps({key: {k: v for k, v in value.items() if k != "trades_detail"} for key, value in result["variants"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--symbol", default="SPKTRY"); parser.add_argument("--hours", type=int, default=24); parser.add_argument("--fetch-days", type=int, default=10)
    parser.add_argument("--end-minutes-ago", type=int, default=10); parser.add_argument("--end-time-ms", type=int); parser.add_argument("--cost-multiplier", type=float, default=1.0); parser.add_argument("--walk-forward-days", type=int, default=0); parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
