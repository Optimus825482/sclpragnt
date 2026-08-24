"""Paper-only PENGUTRY M1 Fisher(7) trend-pullback replay."""
import argparse
import asyncio
import json
import math
import time
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts.replay_pump_monitor import fisher_transform_series, normalize


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def parse_end(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000) if value else int(time.time() * 1000) - 10 * 60 * 1000


def resample_m1(rows, minutes):
    bucket_ms, groups = minutes * 60 * 1000, {}
    for row in rows:
        bucket = row["time"] - row["time"] % bucket_ms
        group = groups.get(bucket)
        if group is None:
            groups[bucket] = {**row, "time": bucket, "count": 1}
        else:
            group["high"] = max(group["high"], row["high"]); group["low"] = min(group["low"], row["low"])
            group["close"] = row["close"]; group["close_time"] = row["close_time"]; group["volume"] += row["volume"]; group["count"] += 1
    return [row for _, row in sorted(groups.items()) if row["count"] == minutes]


def ema_series(rows, period):
    alpha, prior, values = 2.0 / (period + 1), None, []
    for row in rows:
        prior = row["close"] if prior is None else alpha * row["close"] + (1 - alpha) * prior
        values.append(prior)
    return values


def atr_series(rows, period=14):
    values, prior_close, prior_atr, tr_values = [], None, None, []
    for row in rows:
        tr = row["high"] - row["low"] if prior_close is None else max(row["high"] - row["low"], abs(row["high"] - prior_close), abs(row["low"] - prior_close))
        tr_values.append(tr)
        if len(tr_values) < period:
            values.append(None)
        elif prior_atr is None:
            prior_atr = sum(tr_values[-period:]) / period; values.append(prior_atr)
        else:
            prior_atr = (prior_atr * (period - 1) + tr) / period; values.append(prior_atr)
        prior_close = row["close"]
    return values


def at_or_before(rows, times, timestamp):
    index = bisect_right(times, timestamp) - 1
    return index if index >= 0 else None


def run_strategy(m1, start_ms, end_ms, order_pct, cost_multiplier):
    m5, m15 = resample_m1(m1, 5), resample_m1(m1, 15)
    m1_ema9, m5_ema20 = ema_series(m1, 9), ema_series(m5, 20)
    m15_ema50, m15_ema200, m5_atr = ema_series(m15, 50), ema_series(m15, 200), atr_series(m5)
    fisher = fisher_transform_series(m1, length=7)
    m5_times, m15_times = [row["close_time"] for row in m5], [row["close_time"] for row in m15]
    commission = float(config.COMMISSION_PCT) * cost_multiplier
    impact = (float(config.BACKTEST_ASSUMED_SPREAD_PCT) / 2 + float(config.ESTIMATED_SLIPPAGE_PCT)) * cost_multiplier
    cash, position, trades, equity = float(config.INITIAL_BALANCE_TRY), None, [], []
    for index, row in enumerate(m1[:-1]):
        if not start_ms <= row["close_time"] <= end_ms:
            continue
        m5_index, m15_index = at_or_before(m5, m5_times, row["close_time"]), at_or_before(m15, m15_times, row["close_time"])
        if position is not None:
            # Conservative M1 OHLC ordering: existing protective stop is checked before a new intrabar high can improve it.
            if row["low"] <= position["stop"]:
                exit_fill = position["stop"] * (1 - impact); proceeds = position["quantity"] * exit_fill; exit_fee = proceeds * commission
                cash += proceeds - exit_fee
                trades.append({**position, "exit_time": row["time"], "exit": exit_fill, "exit_fee": exit_fee, "reason": position["stop_reason"], "pnl_try": proceeds - exit_fee - position["order_value"] - position["entry_fee"]})
                position = None
            else:
                position["peak"] = max(position["peak"], row["high"])
                if position["peak"] >= position["entry"] + position["risk"]:
                    position["stop"] = max(position["stop"], position["entry"]); position["stop_reason"] = "breakeven_or_atr_trailing"
                    if m5_index is not None and m5_atr[m5_index] is not None:
                        position["stop"] = max(position["stop"], position["peak"] - 1.5 * m5_atr[m5_index])
                current, trigger = fisher["fish"][index], fisher["trigger"][index]
                previous, previous_trigger = fisher["fish"][index - 1], fisher["trigger"][index - 1]
                if current is not None and trigger is not None and previous is not None and previous_trigger is not None and current > .75 and current < trigger and previous >= previous_trigger:
                    next_row = m1[index + 1]; exit_fill = next_row["open"] * (1 - impact); proceeds = position["quantity"] * exit_fill; exit_fee = proceeds * commission
                    cash += proceeds - exit_fee
                    trades.append({**position, "exit_time": next_row["time"], "exit": exit_fill, "exit_fee": exit_fee, "reason": "fisher_profit_protection", "pnl_try": proceeds - exit_fee - position["order_value"] - position["entry_fee"]})
                    position = None
        if position is None and m5_index is not None and m15_index is not None and m5_index >= 20 and m15_index >= 200:
            current, trigger = fisher["fish"][index], fisher["trigger"][index]
            previous, previous_trigger = fisher["fish"][index - 1], fisher["trigger"][index - 1]
            recent_fisher = [value for value in fisher["fish"][max(0, index - 9):index + 1] if value is not None]
            trend = (m15[m15_index]["close"] > m15_ema50[m15_index] > m15_ema200[m15_index] and m15_ema50[m15_index] > m15_ema50[m15_index - 1])
            pullback = (m5[m5_index]["close"] > m5_ema20[m5_index] and min(item["low"] for item in m5[m5_index - 3:m5_index + 1]) <= m5_ema20[m5_index])
            fisher_cross = (current is not None and trigger is not None and previous is not None and previous_trigger is not None and current < 0 and current > trigger and previous <= previous_trigger and recent_fisher and min(recent_fisher) <= -.75)
            price_confirmation = row["close"] > m1_ema9[index]
            if trend and pullback and fisher_cross and price_confirmation and m5_atr[m5_index]:
                next_row = m1[index + 1]; entry = next_row["open"] * (1 + impact)
                swing_stop = min(item["low"] for item in m5[m5_index - 4:m5_index + 1]) * .999
                atr_stop = entry - 1.2 * m5_atr[m5_index]
                stop = min(swing_stop, atr_stop); risk = entry - stop
                if risk > 0:
                    order_value = cash * order_pct; entry_fee = order_value * commission
                    if order_value + entry_fee > cash: order_value, entry_fee = cash / (1 + commission), cash / (1 + commission) * commission
                    cash -= order_value + entry_fee
                    position = {"entry_time": next_row["time"], "entry": entry, "entry_fee": entry_fee, "order_value": order_value, "quantity": order_value / entry, "stop": stop, "stop_reason": "initial_swing_or_atr_stop", "risk": risk, "peak": entry, "entry_fisher": current, "entry_trigger": trigger}
        mark = cash if position is None else cash + position["quantity"] * row["close"] * (1 - impact)
        equity.append(mark)
    if position is not None:
        last = next(row for row in reversed(m1) if row["close_time"] <= end_ms); exit_fill = last["close"] * (1 - impact); proceeds = position["quantity"] * exit_fill; exit_fee = proceeds * commission; cash += proceeds - exit_fee
        trades.append({**position, "exit_time": last["close_time"], "exit": exit_fill, "exit_fee": exit_fee, "reason": "window_mark_to_market", "pnl_try": proceeds - exit_fee - position["order_value"] - position["entry_fee"]})
    gross_profit, gross_loss = sum(max(t["pnl_try"], 0) for t in trades), -sum(min(t["pnl_try"], 0) for t in trades)
    peak, drawdown = float(config.INITIAL_BALANCE_TRY), 0.0
    for value in equity + [cash]: peak = max(peak, value); drawdown = max(drawdown, peak - value)
    return {"trades": len(trades), "wins": sum(t["pnl_try"] > 0 for t in trades), "losses": sum(t["pnl_try"] <= 0 for t in trades), "net_pnl_try": cash - float(config.INITIAL_BALANCE_TRY), "fees_try": sum(t["entry_fee"] + t["exit_fee"] for t in trades), "profit_factor": gross_profit / gross_loss if gross_loss else None, "expectancy_try": (cash - float(config.INITIAL_BALANCE_TRY)) / len(trades) if trades else None, "max_drawdown_try": drawdown, "final_balance_try": cash, "reconciliation_delta_try": cash - float(config.INITIAL_BALANCE_TRY) - sum(t["pnl_try"] for t in trades), "exit_reasons": {reason: sum(t["reason"] == reason for t in trades) for reason in sorted({t["reason"] for t in trades})}, "trades_detail": trades}


async def main(args):
    end_ms = parse_end(args.end_date)
    start_ms = end_ms - args.hours * 3600000
    rows = normalize(await historical_klines("PENGUTRY", "1m", args.fetch_days, end_ms), end_ms)
    if len(rows) < 3_100: raise RuntimeError("M15 EMA200 için yeterli kapanmış M1 verisi yok")
    summary = run_strategy(rows, start_ms, end_ms, args.order_pct, args.cost_multiplier)
    result = {"paper_only": True, "strategy": "PENGUTRY M1 Fisher(7) trend-pullback", "window": {"start": iso(start_ms), "end": iso(end_ms), "hours": args.hours}, "provenance": {"source": "Binance TR public /api/v3/klines completed M1 OHLCV", "closed_m1_candles": len(rows)}, "rules": {"regime": "completed M15 close > EMA50 > EMA200 and EMA50 rising", "pullback": "latest completed M5 close above EMA20 and a low touches EMA20 in the last four completed M5 bars", "entry": "completed M1 Fisher(7) has dipped <= -0.75 in prior 10 bars, crosses above trigger while below zero, and close > EMA9; next M1 open", "exit": "initial stop below latest M5 swing or 1.2 ATR(14), whichever is farther; after 1R breakeven + 1.5 M5 ATR trailing; Fisher profit protection on a cross down above +0.75"}, "execution": {"initial_balance_try": config.INITIAL_BALANCE_TRY, "order_pct_of_remaining_cash": args.order_pct, "single_open_position": True, "cost_multiplier": args.cost_multiplier, "commission_pct_each_side": config.COMMISSION_PCT * args.cost_multiplier, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier}, "summary": summary, "limitations": ["Historical spread, depth and intrabar order sequence are unavailable; OHLC stop order is conservative stop-first.", "This is a source-aligned public-candle replay, not a TradingView Strategy Tester export."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps({k: v for k, v in summary.items() if k != "trades_detail"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--hours", type=int, default=24); parser.add_argument("--fetch-days", type=int, default=3); parser.add_argument("--end-date"); parser.add_argument("--order-pct", type=float, default=config.ORDER_PCT); parser.add_argument("--cost-multiplier", type=float, default=1.0); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.hours < 1 or args.fetch_days < 3 or not 0 < args.order_pct <= 1 or args.cost_multiplier <= 0: parser.error("hours>=1, fetch-days>=3, 0<order-pct<=1 and cost-multiplier>0 required")
    asyncio.run(main(args))
