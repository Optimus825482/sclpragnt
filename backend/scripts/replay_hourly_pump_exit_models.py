"""Fee-aware, causal exit comparison for the frozen hourly-pump alarm.

Research only.  The entry set is the previously frozen four-condition score
(three-or-more conditions), calculated from candles completed before H1 start.
There is no order placement or mutation of the live strategy.
"""
import argparse
import asyncio
import glob
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config


ORDER_VALUE_TRY = 1_000.0
HOLD_MINUTES = 60
PUMP_RULE = ("m5_bb_position_ge_0.80", "m15_or_m30_continuation", "m5_mfi_ge_45", "m5_rsi_ge_65")


def normalize(raw):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = []
    for row in raw or []:
        if len(row) < 7 or int(row[6]) > now_ms:
            continue
        try:
            rows.append({"time": int(row[0]), "close_time": int(row[6]), "open": float(row[1]),
                         "high": float(row[2]), "low": float(row[3]), "close": float(row[4])})
        except (TypeError, ValueError):
            continue
    return sorted({row["time"]: row for row in rows}.values(), key=lambda row: row["time"])


def candidate(point):
    metrics = point.get("snapshots", {}).get("5m", {}).get("key_metrics")
    if not isinstance(metrics, dict):
        return False, {name: False for name in PUMP_RULE}
    conditions = {
        "m5_bb_position_ge_0.80": metrics.get("bb_position") is not None and metrics["bb_position"] >= .80,
        "m15_or_m30_continuation": bool(point["flags"].get("continuation_context")),
        "m5_mfi_ge_45": metrics.get("mfi_14") is not None and metrics["mfi_14"] >= 45,
        "m5_rsi_ge_65": metrics.get("rsi_14") is not None and metrics["rsi_14"] >= 65,
    }
    return sum(conditions.values()) >= 3, conditions


def atr(rows, end_index, period=14):
    if end_index < period:
        return None
    true_ranges = []
    for index in range(end_index - period, end_index):
        row = rows[index]
        previous = rows[index - 1]["close"] if index else row["open"]
        true_ranges.append(max(row["high"] - row["low"], abs(row["high"] - previous), abs(row["low"] - previous)))
    return sum(true_ranges) / len(true_ranges)


def entry_fill(price):
    return price * (1 + config.BACKTEST_ASSUMED_SPREAD_PCT / 2 + config.ESTIMATED_SLIPPAGE_PCT)


def exit_fill(price):
    return price * (1 - config.BACKTEST_ASSUMED_SPREAD_PCT / 2 - config.ESTIMATED_SLIPPAGE_PCT)


def close_piece(piece, raw_price):
    filled = exit_fill(raw_price)
    gross = piece["quantity"] * filled
    fee = gross * config.COMMISSION_PCT
    return gross - fee - piece["invested"] - piece["entry_fee"], fee


def simulate(rows, entry_index, model):
    """Conservative intrabar model: existing stop is processed before high."""
    entry = entry_fill(rows[entry_index]["open"])
    quantity = ORDER_VALUE_TRY / entry
    entry_fee = ORDER_VALUE_TRY * config.COMMISSION_PCT
    initial_atr = atr(rows, entry_index) or entry * config.HARD_STOP_LOSS_PCT
    hard_stop = entry * (1 - config.BB_MFI_STOP_LOSS_PCT)
    target = entry * (1 + config.BB_MFI_TAKE_PROFIT_PCT)
    end = min(len(rows), entry_index + HOLD_MINUTES)
    if end - entry_index < HOLD_MINUTES:
        return None
    remaining = {"quantity": quantity, "invested": ORDER_VALUE_TRY, "entry_fee": entry_fee}
    realized, exit_fees, exit_reasons = 0.0, 0.0, []
    peak, armed, partial = entry, False, False
    trailing_stop = None
    max_high, min_low = entry, entry
    exit_index = end - 1

    for index in range(entry_index, end):
        bar = rows[index]
        max_high, min_low = max(max_high, bar["high"]), min(min_low, bar["low"])
        active_stop = hard_stop
        if model != "fixed_v3" and trailing_stop is not None:
            active_stop = max(active_stop, trailing_stop)
        if bar["low"] <= active_stop:
            pnl, fee = close_piece(remaining, active_stop)
            realized += pnl; exit_fees += fee
            if trailing_stop is not None and active_stop == trailing_stop:
                exit_reasons.append("profit_lock_stop" if model == "profit_lock_runner" else "atr_trailing_stop")
            else:
                exit_reasons.append("bb_mfi_fixed_stop_loss")
            remaining["quantity"] = 0
            exit_index = index
            break

        peak = max(peak, bar["high"])
        if model == "fixed_v3" and bar["high"] >= target:
            pnl, fee = close_piece(remaining, target)
            realized += pnl; exit_fees += fee; exit_reasons.append("bb_mfi_fixed_take_profit")
            remaining["quantity"] = 0
            exit_index = index
            break

        if model == "profit_lock_runner" and not armed and peak >= target:
            armed = True
            trailing_stop = max(entry * 1.006, peak * .994)
        elif model == "atr_trailing_runner" and not armed and peak >= entry + initial_atr:
            armed = True
            trailing_stop = max(entry, peak - initial_atr * config.SYSTEM_ATR_TRAILING_MULTIPLIER)
        elif model == "partial_atr_runner" and not partial and peak >= target:
            half = {key: value * .5 for key, value in remaining.items()}
            pnl, fee = close_piece(half, target)
            realized += pnl; exit_fees += fee; exit_reasons.append("partial_take_profit")
            for key in remaining: remaining[key] -= half[key]
            partial = True; armed = True; trailing_stop = max(entry, peak - initial_atr * config.SYSTEM_ATR_TRAILING_MULTIPLIER)

        if armed and remaining["quantity"] > 0:
            if model == "profit_lock_runner":
                trailing_stop = max(trailing_stop or entry, peak * .994)
            else:
                trailing_stop = max(trailing_stop or entry, peak - initial_atr * config.SYSTEM_ATR_TRAILING_MULTIPLIER)

    if remaining["quantity"] > 0:
        pnl, fee = close_piece(remaining, rows[end - 1]["close"])
        realized += pnl; exit_fees += fee; exit_reasons.append("time_limit_60m")
    net_pct = realized / (ORDER_VALUE_TRY + entry_fee) * 100
    return {"net_pnl_try": realized, "net_return_pct": net_pct, "fees_try": entry_fee + exit_fees,
            "exit_reason": "+".join(exit_reasons), "max_up_pct": (max_high / entry - 1) * 100,
            "max_down_pct": (min_low / entry - 1) * 100, "entry_time": rows[entry_index]["time"],
            "exit_time": rows[exit_index]["close_time"], "hold_minutes": exit_index - entry_index + 1}


def median(values):
    values = sorted(values)
    return values[len(values) // 2] if len(values) % 2 else (values[len(values)//2-1] + values[len(values)//2]) / 2


def summarize(records):
    if not records:
        return {"trades": 0}
    returns = [row["result"]["net_return_pct"] for row in records]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    curve = peak = max_dd = 0.0
    for value in returns:
        curve += value; peak = max(peak, curve); max_dd = min(max_dd, curve - peak)
    return {"trades": len(records), "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(records) * 100, 2),
            "net_pnl_try": round(sum(row["result"]["net_pnl_try"] for row in records), 2),
            "fees_try": round(sum(row["result"]["fees_try"] for row in records), 2),
            "expectancy_pct_per_trade": round(sum(returns) / len(returns), 4),
            "median_net_return_pct": round(median(returns), 4),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
            "max_drawdown_pct": round(max_dd, 4),
            "median_max_up_pct": round(median([r["result"]["max_up_pct"] for r in records]), 4),
            "median_max_down_pct": round(median([r["result"]["max_down_pct"] for r in records]), 4),
            "exit_reasons": dict(Counter(r["result"]["exit_reason"] for r in records))}


async def fetch_event(event, semaphore):
    symbol, start = event["symbol"], event["signal_time"]
    async with semaphore:
        try:
            # Contains 24h pre-entry warmup and almost 24h post-entry outcome.
            rows = normalize(await historical_klines(symbol, "1m", 2, start + 86_400_000))
            index = next((i for i, row in enumerate(rows) if row["time"] == start), None)
            return event, rows, index, None
        except Exception as exc:
            return event, [], None, f"{type(exc).__name__}: {exc}"


async def main(args):
    events = []
    cutoffs = []
    for filename in sorted(glob.glob(args.inputs)):
        source = json.loads(Path(filename).read_text(encoding="utf-8"))
        events.extend(source["events"])
        if source.get("cutoff_ms") is not None:
            cutoffs.append(int(source["cutoff_ms"]))
    if not cutoffs or len(set(cutoffs)) != 1:
        raise SystemExit("Input files must share one chronological cutoff_ms")
    cutoff_ms = cutoffs[0]
    events.sort(key=lambda item: item["event"]["hour_start_ms"])
    selected = []
    for item in events:
        point_sets = [("pump_event", [item.get("event_point")])]
        point_sets.append(("quiet_control", item.get("control_points") or [item.get("control_point")]))
        for label, points in point_sets:
            for point in points:
                if not point:
                    continue
                passed, conditions = candidate(point)
                if passed:
                    selected.append({"symbol": item["event"]["symbol"], "signal_time": point["time_ms"],
                                     "reference_event_time": item["event"]["hour_start_ms"],
                                     "reference_event_hour_start": item["event"]["hour_start"], "label": label,
                                     "conditions": conditions})
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch_event(event, semaphore) for event in selected))
    models = ("fixed_v3", "profit_lock_runner", "atr_trailing_runner", "partial_atr_runner")
    records = {model: [] for model in models}; errors = {}
    for event, rows, index, error in loaded:
        key = f"{event['symbol']}@{event['signal_time']}"
        if error or index is None:
            errors[key] = error or "entry candle unavailable"; continue
        for model in models:
            result = simulate(rows, index, model)
            if result:
                records[model].append({"symbol": event["symbol"], "signal_time": event["signal_time"],
                                       "reference_event_time": event["reference_event_time"],
                                       "reference_event_hour_start": event["reference_event_hour_start"], "label": event["label"],
                                       "conditions": event["conditions"], "result": result})
    for model in models:
        records[model].sort(key=lambda row: row["signal_time"])
    payload = {"research_only": True, "source": "Binance TR public historical M1 OHLCV via configured public adapter",
               "generated_at": datetime.now(timezone.utc).isoformat(), "candidate_rule": {"conditions": list(PUMP_RULE), "minimum_score": 3},
               "execution": {"entry": "H1-start M1 open after all input M5/M15/M30 candles have closed", "order_value_try": ORDER_VALUE_TRY,
                             "commission_pct_each_side": config.COMMISSION_PCT, "assumed_full_spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT,
                             "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT, "intrabar_order": "existing stop before high", "max_hold_minutes": HOLD_MINUTES},
               "models": {"fixed_v3": "Current BB-MFI v3 fixed stop and take-profit.",
                          "profit_lock_runner": "Same fixed stop; after v3 target, lock +0.6% and trail 0.6%, no fixed target close.",
                          "atr_trailing_runner": "Same fixed stop; after +1 ATR, trail by current configured 2.5 ATR.",
                          "partial_atr_runner": "Take 50% at v3 target; trail the remaining 50% after target by current 2.5 ATR."},
               "sample": {"selected_signals": len(selected), "loaded": len(selected) - len(errors), "errors": errors,
                          "chronological_cutoff_ms": cutoff_ms},
               "partitions": {}}
    for name, is_final in {"development": False, "final_chronological": True}.items():
        payload["partitions"][name] = {}
        for model in models:
            partition = [row for row in records[model] if (row["reference_event_time"] >= cutoff_ms) == is_final]
            payload["partitions"][name][model] = {"all": summarize(partition),
                "pump_events": summarize([row for row in partition if row["label"] == "pump_event"]),
                "quiet_controls": summarize([row for row in partition if row["label"] == "quiet_control"])}
    payload["records"] = records
    payload["limitations"] = ["This is isolated-trade replay; portfolio overlap, liquidity caps and real historical order book are not simulated.",
                              "The candidate rule was previously explored, so final chronological results are not fully blind.",
                              "No model is eligible for live activation from this sample alone."]
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["partitions"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", default="hourly-pump-context-60d-batch-*.json")
    parser.add_argument("--output", default="hourly-pump-exit-replay-60d.json")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--train-fraction", type=float, default=.70)
    main_args = parser.parse_args()
    asyncio.run(main(main_args))
