"""Standalone, causal Fisher Transform(7) M1 replay for PENGUTRY.

Entry: Fisher < -1.5 and Fisher crosses above its trigger.
Exit:  Fisher >  1.5 and Fisher crosses below its trigger.
"""
import argparse
import asyncio
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts.replay_pump_monitor import fisher_transform_series, normalize


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def parse_end(value):
    if not value:
        return int(time.time() * 1000) - 10 * 60 * 1000
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def main_rows(rows, start_ms, end_ms, order_pct, cost_multiplier=1.0):
    fisher = fisher_transform_series(rows, length=7)
    cash, position, trades, equity_curve = float(config.INITIAL_BALANCE_TRY), None, [], []
    commission = float(config.COMMISSION_PCT) * cost_multiplier
    buy_cost = (float(config.BACKTEST_ASSUMED_SPREAD_PCT) / 2 + float(config.ESTIMATED_SLIPPAGE_PCT)) * cost_multiplier
    sell_cost = buy_cost
    for index, row in enumerate(rows[:-1]):
        if not start_ms <= row["close_time"] <= end_ms:
            continue
        current, trigger = fisher["fish"][index], fisher["trigger"][index]
        previous, previous_trigger = (fisher["fish"][index - 1], fisher["trigger"][index - 1]) if index else (None, None)
        if current is None or trigger is None or previous is None or previous_trigger is None:
            continue
        next_row = rows[index + 1]
        cross_up = current > trigger and previous <= previous_trigger
        cross_down = current < trigger and previous >= previous_trigger
        if position is None and current < -1.5 and cross_up:
            order_value = cash * order_pct
            entry_fill = next_row["open"] * (1 + buy_cost)
            entry_fee = order_value * commission
            if order_value + entry_fee > cash:
                order_value = cash / (1 + commission)
                entry_fee = order_value * commission
            quantity = order_value / entry_fill
            cash -= order_value + entry_fee
            position = {"entry_time": next_row["time"], "entry_signal_time": row["close_time"], "entry": entry_fill,
                        "quantity": quantity, "entry_fee": entry_fee, "order_value": order_value,
                        "entry_fisher": current, "entry_trigger": trigger}
        elif position is not None and current > 1.5 and cross_down:
            exit_fill = next_row["open"] * (1 - sell_cost)
            proceeds = position["quantity"] * exit_fill
            exit_fee = proceeds * commission
            cash += proceeds - exit_fee
            trades.append({**position, "exit_time": next_row["time"], "exit_signal_time": row["close_time"],
                           "exit": exit_fill, "exit_fisher": current, "exit_trigger": trigger,
                           "exit_fee": exit_fee, "reason": "fisher7_overbought_bearish_cross",
                           "pnl_try": proceeds - exit_fee - position["order_value"] - position["entry_fee"]})
            position = None
        mark = cash if position is None else cash + position["quantity"] * row["close"] * (1 - sell_cost)
        equity_curve.append(mark)
    if position is not None:
        last = next((row for row in reversed(rows) if row["close_time"] <= end_ms), None)
        if last:
            exit_fill = last["close"] * (1 - sell_cost)
            proceeds = position["quantity"] * exit_fill
            exit_fee = proceeds * commission
            cash += proceeds - exit_fee
            trades.append({**position, "exit_time": last["close_time"], "exit_signal_time": None, "exit": exit_fill,
                           "exit_fisher": None, "exit_trigger": None, "exit_fee": exit_fee,
                           "reason": "window_mark_to_market", "pnl_try": proceeds - exit_fee - position["order_value"] - position["entry_fee"]})
            position = None
    gross_profit = sum(max(trade["pnl_try"], 0) for trade in trades)
    gross_loss = -sum(min(trade["pnl_try"], 0) for trade in trades)
    running_peak, max_drawdown = float(config.INITIAL_BALANCE_TRY), 0.0
    for value in equity_curve + [cash]:
        running_peak = max(running_peak, value)
        max_drawdown = max(max_drawdown, running_peak - value)
    return {"trades": len(trades), "wins": sum(t["pnl_try"] > 0 for t in trades), "losses": sum(t["pnl_try"] <= 0 for t in trades),
            "net_pnl_try": cash - float(config.INITIAL_BALANCE_TRY), "fees_try": sum(t["entry_fee"] + t["exit_fee"] for t in trades),
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "expectancy_try": (cash - float(config.INITIAL_BALANCE_TRY)) / len(trades) if trades else None,
            "max_drawdown_try": max_drawdown, "final_balance_try": cash,
            "reconciliation_delta_try": cash - float(config.INITIAL_BALANCE_TRY) - sum(t["pnl_try"] for t in trades),
            "trades_detail": trades}


async def run(args):
    end_ms = parse_end(args.end_date)
    start_ms = end_ms - args.hours * 60 * 60 * 1000
    rows = normalize(await historical_klines("PENGUTRY", "1m", args.fetch_days, end_ms), end_ms)
    if not rows:
        raise RuntimeError("PENGUTRY için tamamlanmış M1 mum verisi alınamadı")
    result = {"paper_only": True, "strategy": "Standalone PENGUTRY M1 Fisher Transform(7)",
              "rules": {"entry": "completed M1: Fisher(7) < -1.5 and Fisher crosses trigger upward; enter next M1 open",
                        "exit": "completed M1: Fisher(7) > 1.5 and Fisher crosses trigger downward; exit next M1 open"},
              "window": {"start": iso(start_ms), "end": iso(end_ms), "hours": args.hours},
              "provenance": {"source": "Binance TR public /api/v3/klines completed M1 OHLCV", "symbol": "PENGUTRY", "closed_m1_candles": len(rows)},
              "execution": {"initial_balance_try": config.INITIAL_BALANCE_TRY, "order_pct_of_remaining_cash": args.order_pct,
                            "single_open_position": True, "cost_multiplier": args.cost_multiplier,
                            "commission_pct_each_side": config.COMMISSION_PCT * args.cost_multiplier,
                            "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier,
                            "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier},
              "summary": main_rows(rows, start_ms, end_ms, args.order_pct, args.cost_multiplier),
              "limitations": ["Historical spread, depth, and intrabar order sequence are unavailable; costs are modeled.", "This is source-aligned public-candle replay, not a TradingView Strategy Tester export."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps({k: v for k, v in result["summary"].items() if k != "trades_detail"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--fetch-days", type=int, default=3)
    parser.add_argument("--end-date")
    parser.add_argument("--order-pct", type=float, default=config.ORDER_PCT)
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.hours < 1 or args.fetch_days < math.ceil((args.hours + 2) / 24) or not 0 < args.order_pct <= 1 or args.cost_multiplier <= 0:
        parser.error("hours>=1, yeterli fetch-days, 0<order-pct<=1 ve cost-multiplier>0 gerekli")
    asyncio.run(run(args))
