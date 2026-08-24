"""Paper-only, causal SPKTRY M1 Fisher(9) replay for the user-specified ladder.

Signals use the supplied Pine recurrence.  A closed M1 signal is filled at the
next M1 open.  The ladder is Fisher-based (not a price stop): +1.5 locks +1.0,
+2.0 locks +1.5, and +2.5 locks +2.0.  The last threshold makes the user's
"+2'nin uzerine" instruction executable as a distinct stage.
"""
import argparse
import asyncio
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts.replay_pump_monitor import fisher_transform_series, normalize


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def parse_end(value):
    if value:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    # Exclude the currently forming candle and leave a small exchange-finality buffer.
    return int(time.time() * 1000) - 10 * 60 * 1000


def consecutive_missing(rows, interval_ms):
    if len(rows) < 2:
        return 0
    return sum((right["time"] - left["time"]) != interval_ms for left, right in zip(rows, rows[1:]))


def close_position(cash, position, quote, commission, impact, exit_time, reason, extra=None):
    fill = quote * (1 - impact)
    proceeds = position["quantity"] * fill
    exit_fee = proceeds * commission
    cash += proceeds - exit_fee
    trade = {**position, "exit_time": exit_time, "exit": fill, "exit_fee": exit_fee,
             "reason": reason, "pnl_try": proceeds - exit_fee - position["order_value"] - position["entry_fee"]}
    if extra:
        trade.update(extra)
    return cash, trade


def replay(rows, start_ms, end_ms, entry_floor, exit_mode, order_pct, cost_multiplier):
    fisher = fisher_transform_series(rows, length=9)
    commission = float(config.COMMISSION_PCT) * cost_multiplier
    impact = (float(config.BACKTEST_ASSUMED_SPREAD_PCT) / 2 + float(config.ESTIMATED_SLIPPAGE_PCT)) * cost_multiplier
    cash, position, trades, equity = float(config.INITIAL_BALANCE_TRY), None, [], []

    for index, row in enumerate(rows[:-1]):
        if not start_ms <= row["close_time"] <= end_ms:
            continue
        current, trigger = fisher["fish"][index], fisher["trigger"][index]
        previous = fisher["fish"][index - 1] if index else None
        previous_trigger = fisher["trigger"][index - 1] if index else None
        next_row = rows[index + 1]
        if current is None or trigger is None or previous is None or previous_trigger is None:
            continue

        if position is not None:
            if exit_mode == "ladder":
                # All decisions use this completed candle; never infer intrabar Fisher values.
                if current >= 2.5:
                    position["floor"] = max(position["floor"] if position["floor"] is not None else -math.inf, 2.0)
                    position["highest_stage"] = max(position["highest_stage"], 3)
                elif current >= 2.0:
                    position["floor"] = max(position["floor"] if position["floor"] is not None else -math.inf, 1.5)
                    position["highest_stage"] = max(position["highest_stage"], 2)
                elif current >= 1.5:
                    position["floor"] = max(position["floor"] if position["floor"] is not None else -math.inf, 1.0)
                    position["highest_stage"] = max(position["highest_stage"], 1)
                if position["floor"] is not None and previous >= position["floor"] and current < position["floor"]:
                    cash, trade = close_position(cash, position, next_row["open"], commission, impact, next_row["time"],
                                                  f"fisher_ladder_floor_{position['floor']:.1f}",
                                                  {"exit_signal_time": row["close_time"], "exit_fisher": current})
                    trades.append(trade); position = None
            elif exit_mode == "pine_exact" and (current >= 2.0 or (current < trigger and previous >= previous_trigger)):
                reason = "pine_target_fisher_ge_2" if current >= 2.0 else "pine_any_bearish_cross"
                cash, trade = close_position(cash, position, next_row["open"], commission, impact, next_row["time"],
                                              reason, {"exit_signal_time": row["close_time"], "exit_fisher": current})
                trades.append(trade); position = None
            elif current > 1.5 and current < trigger and previous >= previous_trigger:
                cash, trade = close_position(cash, position, next_row["open"], commission, impact, next_row["time"],
                                              "baseline_overbought_bearish_cross",
                                              {"exit_signal_time": row["close_time"], "exit_fisher": current})
                trades.append(trade); position = None

        cross_up = current > trigger and previous <= previous_trigger
        if position is None and current < entry_floor and cross_up:
            order_value = cash * order_pct
            entry_fee = order_value * commission
            if order_value + entry_fee > cash:
                order_value = cash / (1 + commission); entry_fee = order_value * commission
            entry_fill = next_row["open"] * (1 + impact)
            cash -= order_value + entry_fee
            position = {"entry_time": next_row["time"], "entry_signal_time": row["close_time"], "entry": entry_fill,
                        "quantity": order_value / entry_fill, "entry_fee": entry_fee, "order_value": order_value,
                        "entry_fisher": current, "entry_trigger": trigger, "floor": None, "highest_stage": 0}
        mark = cash if position is None else cash + position["quantity"] * row["close"] * (1 - impact) * (1 - commission)
        equity.append(mark)

    if position is not None:
        last = next(row for row in reversed(rows) if row["close_time"] <= end_ms)
        cash, trade = close_position(cash, position, last["close"], commission, impact, last["close_time"], "window_mark_to_market")
        trades.append(trade)

    gains = sum(max(t["pnl_try"], 0) for t in trades)
    losses = -sum(min(t["pnl_try"], 0) for t in trades)
    peak, max_dd = float(config.INITIAL_BALANCE_TRY), 0.0
    for point in equity + [cash]:
        peak = max(peak, point); max_dd = max(max_dd, peak - point)
    return {"trades": len(trades), "wins": sum(t["pnl_try"] > 0 for t in trades), "losses": sum(t["pnl_try"] <= 0 for t in trades),
            "net_pnl_try": round(cash - float(config.INITIAL_BALANCE_TRY), 4), "fees_try": round(sum(t["entry_fee"] + t["exit_fee"] for t in trades), 4),
            "profit_factor": round(gains / losses, 4) if losses else None,
            "expectancy_try": round((cash - float(config.INITIAL_BALANCE_TRY)) / len(trades), 4) if trades else None,
            "max_drawdown_try": round(max_dd, 4), "final_balance_try": round(cash, 4),
            "reconciliation_delta_try": round(cash - float(config.INITIAL_BALANCE_TRY) - sum(t["pnl_try"] for t in trades), 8),
            "exit_reasons": dict(Counter(t["reason"] for t in trades)), "stage_reached": dict(Counter(str(t["highest_stage"]) for t in trades)),
            "trades_detail": trades}


def compact(summary):
    return {key: value for key, value in summary.items() if key != "trades_detail"}


async def main(args):
    end_ms = parse_end(args.end_date)
    interval_ms = {"1m": 60_000, "5m": 300_000}[args.interval]
    bars_per_hour = 3_600_000 // interval_ms
    raw = await historical_klines("SPKTRY", args.interval, args.fetch_days, end_ms)
    rows = normalize(raw, end_ms)
    if len(rows) < args.hours * bars_per_hour + 12:
        raise RuntimeError(f"SPKTRY için istenen pencereyi kapsayacak yeterli tamamlanmış {args.interval} mum yok")
    start_ms = end_ms - args.hours * 3_600_000
    folds = []
    for fold in range(args.hours // args.fold_hours):
        fold_start = start_ms + fold * args.fold_hours * 3_600_000
        fold_end = fold_start + args.fold_hours * 3_600_000 - 1
        variants = {}
        if args.pine_exact:
            for multiplier in (0.0, 1.0, 2.0):
                key = f"pine_exact_entry_-2.0_cost_{multiplier:.0f}x"
                variants[key] = compact(replay(rows, fold_start, fold_end, -2.0, "pine_exact", args.order_pct, multiplier))
        else:
            for floor in (-2.0, -2.5):
                for mode in ("baseline", "ladder"):
                    for multiplier in (1.0, 2.0):
                        key = f"{mode}_entry_{floor:.1f}_cost_{multiplier:.0f}x"
                        variants[key] = compact(replay(rows, fold_start, fold_end, floor, mode, args.order_pct, multiplier))
        folds.append({"start": iso(fold_start), "end": iso(fold_end), "variants": variants})
    result = {"paper_only": True, "generated_at": iso(int(time.time() * 1000)),
              "strategy": f"SPKTRY {args.interval.upper()} " + ("exact supplied Pine Fisher Transform(9) long-only research" if args.pine_exact else "Fisher Transform(9) staged-profit-lock research"),
              "provenance": {"source": f"Binance TR public /api/v3/klines completed {args.interval} OHLCV", "symbol": "SPKTRY", "retrieved_closed_candles": len(rows), "missing_expected_intervals": consecutive_missing(rows, interval_ms), "timezone": "UTC"},
              "window": {"start": iso(start_ms), "end": iso(end_ms), "hours": args.hours, "fold_hours": args.fold_hours, "non_overlapping_chronological_folds": len(folds)},
              "rules": ({"indicator": "supplied Pine Fisher Transform, length 9", "entry": f"ta.crossover(fish1, fish2) and fish1 < -2.0 on completed {args.interval}; strategy.entry fill next {args.interval} open", "exit": f"(fish1 >= +2.0) OR ta.crossunder(fish1, fish2), both enabled; strategy.close fill next {args.interval} open", "pyramiding": 0, "calc_on_every_tick": False} if args.pine_exact else {"indicator": "supplied Pine Fisher Transform, length 9", "entry": f"completed {args.interval} Fisher crosses above trigger while Fisher is below entry floor; fill next {args.interval} open", "entry_floor_variants": [-2.0, -2.5], "ladder": f"+1.5 reached -> Fisher floor +1.0; +2.0 -> +1.5; +2.5 -> +2.0; exit next {args.interval} open after a completed Fisher cross below current floor", "baseline": f"same entry; completed Fisher bearish cross above +1.5 exits next {args.interval} open", "price_trailing": "not tested: distance was not specified"}),
              "execution": {"initial_balance_try": config.INITIAL_BALANCE_TRY, "single_open_position": True, "order_pct_of_remaining_cash": args.order_pct, "commission_pct_each_side": config.COMMISSION_PCT, "assumed_full_spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT, "cost_scenarios": (["0x diagnostic matching the Pine code's unspecified commission", "1x fee-aware", "2x stress"] if args.pine_exact else ["1x", "2x"]), "intrabar_policy": "Fisher is evaluated only on completed candles; no unobservable intrabar Fisher stop is assumed"},
              "folds": folds,
              "limitations": ["Historical bid-ask spread, depth, and intrabar price path are unavailable; spread/slippage are modeled.", "No initial price stop was specified, so a trade that never reaches +1.5 is held until the test window ends. This is a rule limitation, not evidence of acceptable downside.", "This is source-aligned public-candle replay, not TradingView Strategy Tester output."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.pine_exact:
        print("RESULT_JSON=" + json.dumps([{ "window": f["start"], "pine_exact": f["variants"]["pine_exact_entry_-2.0_cost_1x"]} for f in folds], ensure_ascii=False))
    else:
        print("RESULT_JSON=" + json.dumps([{ "window": f["start"], "ladder_-2": f["variants"]["ladder_entry_-2.0_cost_1x"], "ladder_-2.5": f["variants"]["ladder_entry_-2.5_cost_1x"]} for f in folds], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", choices=("1m", "5m"), default="1m")
    parser.add_argument("--pine-exact", action="store_true", help="Test the supplied Pine entry/exit flags exactly.")
    parser.add_argument("--hours", type=int, default=504)
    parser.add_argument("--fold-hours", type=int, default=168)
    parser.add_argument("--fetch-days", type=int, default=23)
    parser.add_argument("--end-date")
    parser.add_argument("--order-pct", type=float, default=config.ORDER_PCT)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.hours < args.fold_hours or args.hours % args.fold_hours or args.fetch_days < math.ceil((args.hours + 1) / 24) or not 0 < args.order_pct <= 1:
        parser.error("hours fold-hours katı olmalı, fetch-days yeterli olmalı ve 0<order-pct<=1 gerekli")
    asyncio.run(main(args))
