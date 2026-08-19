"""Causal, paper-only replay for the MTF 5/5 continuation hypothesis.

The entry gate uses the same historical order-flow proxy as ScalpAnalyzer;
historical order-book snapshots do not exist, so it never pretends to replay
live bid/ask imbalance. Signals are observed on completed candles, filled on
the following M1 open, and evaluated with a conservative intrabar exit order.
"""
import argparse
import asyncio
import bisect
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.config import config
from app.binance_tr_public import historical_klines

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
ORDER_VALUE_TRY = 1000.0
MAX_HOLD_MINUTES = 15
STOP_PCT = 0.0075
TRAIL_ARM_PCT = 0.008
TRAIL_DISTANCE_PCT = 0.0025

CANDIDATES = {
    "baseline_5of5": {"m1_volume": 0.0, "m5_volume": 0.0, "m1_flow": -1.0, "m5_flow": -1.0},
    "balanced_confirmation": {"m1_volume": 1.0, "m5_volume": 1.0, "m1_flow": 0.0, "m5_flow": 0.0},
    "strict_confirmation": {"m1_volume": 1.2, "m5_volume": 1.2, "m1_flow": 0.05, "m5_flow": 0.05},
}


def normalize(raw):
    now_ms = int(time.time() * 1000)
    rows = []
    for row in raw or []:
        if len(row) < 7 or int(row[6]) > now_ms:
            continue
        try:
            rows.append({"time": int(row[0]), "close_time": int(row[6]), "open": float(row[1]),
                         "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5])})
        except (TypeError, ValueError):
            continue
    return sorted({row["time"]: row for row in rows}.values(), key=lambda row: row["time"])


def resample(rows, minutes):
    buckets, output, width = {}, [], minutes * 60_000
    for row in rows:
        start = row["time"] // width * width
        current = buckets.get(start)
        if current is None:
            current = {"time": start, "close_time": start + width - 1, "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"], "volume": row["volume"]}
            buckets[start] = current; output.append(current)
        else:
            current["high"] = max(current["high"], row["high"]); current["low"] = min(current["low"], row["low"])
            current["close"] = row["close"]; current["volume"] += row["volume"]
    return output


def ema(values, period):
    if len(values) < period:
        return None
    result, multiplier = sum(values[:period]) / period, 2 / (period + 1)
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def bullish(rows):
    closes = [row["close"] for row in rows]
    if len(closes) < 55:
        return False
    e9, e21, e50, previous_e9 = ema(closes, 9), ema(closes, 21), ema(closes, 50), ema(closes[:-1], 9)
    return bool(e9 and e21 and e50 and previous_e9 and closes[-1] > e9 > e21 > e50 and e9 > previous_e9)


def volume_ratio(rows, lookback=20):
    if len(rows) < lookback + 1:
        return None
    baseline = sum(row["volume"] for row in rows[-lookback - 1:-1]) / lookback
    return rows[-1]["volume"] / baseline if baseline > 0 else None


def flow_proxy(rows, lookback=20):
    if len(rows) < lookback:
        return None
    sample = rows[-lookback:]
    total = sum(row["volume"] for row in sample)
    if total <= 0:
        return None
    pressure = 0.0
    for row in sample:
        span = max(row["high"] - row["low"], 1e-12)
        close_location = (2 * row["close"] - row["high"] - row["low"]) / span
        body_direction = 1 if row["close"] > row["open"] else -1 if row["close"] < row["open"] else 0
        pressure += row["volume"] * (0.7 * close_location + 0.3 * body_direction)
    return max(-1.0, min(1.0, pressure / total))


def passes(features, rule):
    return all(features[key] is not None and features[key] >= threshold for key, threshold in rule.items())


def simulate(rows, signal_index):
    """Fill on next M1 open; if high and low conflict inside a bar, stop wins."""
    entry_index = signal_index + 1
    end_index = min(len(rows), entry_index + MAX_HOLD_MINUTES)
    if entry_index >= len(rows) or end_index <= entry_index:
        return None
    entry_quote = rows[entry_index]["open"] * (1 + config.BACKTEST_ASSUMED_SPREAD_PCT / 2 + config.ESTIMATED_SLIPPAGE_PCT)
    quantity = ORDER_VALUE_TRY / entry_quote
    peak, armed = entry_quote, False
    exit_quote, reason, exit_index = None, None, None
    for index in range(entry_index, end_index):
        row = rows[index]
        stop = entry_quote * (1 - STOP_PCT)
        if armed:
            stop = max(stop, peak * (1 - TRAIL_DISTANCE_PCT))
        if row["low"] <= stop:
            exit_quote, reason, exit_index = stop, "initial_stop" if not armed else "trailing_stop", index
            break
        peak = max(peak, row["high"])
        armed = armed or peak >= entry_quote * (1 + TRAIL_ARM_PCT)
    if exit_quote is None:
        exit_index, exit_quote, reason = end_index - 1, rows[end_index - 1]["close"], "time_exit_15m"
    exit_fill = exit_quote * (1 - config.BACKTEST_ASSUMED_SPREAD_PCT / 2 - config.ESTIMATED_SLIPPAGE_PCT)
    entry_fee = ORDER_VALUE_TRY * config.COMMISSION_PCT
    proceeds = quantity * exit_fill
    exit_fee = proceeds * config.COMMISSION_PCT
    pnl = proceeds - exit_fee - ORDER_VALUE_TRY - entry_fee
    return {"entry_time": rows[entry_index]["time"], "exit_time": rows[exit_index]["close_time"], "gross_return_pct": (exit_fill / entry_quote - 1) * 100,
            "net_return_pct": pnl / (ORDER_VALUE_TRY + entry_fee) * 100, "pnl_try": pnl, "fees_try": entry_fee + exit_fee,
            "reason": reason, "hold_minutes": exit_index - entry_index + 1}


def summarize(trades):
    if not trades:
        return {"trades": 0}
    net = [trade["net_return_pct"] for trade in trades]
    wins, losses = [value for value in net if value > 0], [value for value in net if value <= 0]
    cumulative, peak, max_drawdown = 0.0, 0.0, 0.0
    for value in net:
        cumulative += value; peak = max(peak, cumulative); max_drawdown = min(max_drawdown, cumulative - peak)
    return {"trades": len(trades), "wins": len(wins), "losses": len(losses), "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
            "net_pnl_try": round(sum(trade["pnl_try"] for trade in trades), 2), "fees_try": round(sum(trade["fees_try"] for trade in trades), 2),
            "expectancy_pct_per_trade": round(sum(net) / len(net), 4), "median_net_return_pct": round(sorted(net)[(len(net) - 1) // 2], 4),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None, "max_drawdown_pct": round(max_drawdown, 4),
            "exit_reasons": dict(Counter(trade["reason"] for trade in trades)), "median_hold_minutes": sorted(trade["hold_minutes"] for trade in trades)[(len(trades) - 1) // 2]}


async def fetch(symbol, days):
    try:
        return symbol, normalize(await historical_klines(symbol, "1m", days)), None
    except Exception as exc:
        return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    symbols = [symbol.replace("_", "").upper() for symbol in args.symbols]
    loaded = await asyncio.gather(*(fetch(symbol, args.days) for symbol in symbols))
    events, provenance, errors = [], {}, {}
    for symbol, rows, error in loaded:
        provenance[symbol] = {"m1_closed_candles": len(rows)}
        if error or len(rows) < 60 * 24 * 10:
            errors[symbol] = error or "insufficient M1 history"; continue
        frames = {"1m": rows, **{tf: resample(rows, minutes) for tf, minutes in (("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240))}}
        close_times = {tf: [item["close_time"] for item in frame] for tf, frame in frames.items()}
        for index, row in enumerate(rows):
            if row["close_time"] % 3_600_000 > 60_000:
                continue
            completed = {tf: frames[tf][:bisect.bisect_right(close_times[tf], row["close_time"])] for tf in TIMEFRAMES}
            if not all(bullish(completed[tf]) for tf in TIMEFRAMES):
                continue
            features = {"m1_volume": volume_ratio(completed["1m"]), "m5_volume": volume_ratio(completed["5m"]),
                        "m1_flow": flow_proxy(completed["1m"]), "m5_flow": flow_proxy(completed["5m"])}
            trade = simulate(rows, index)
            if trade:
                events.append({"symbol": symbol, "signal_time": row["close_time"], "features": features, "trade": trade})
    events.sort(key=lambda event: event["signal_time"])
    split = int(len(events) * .70)
    result = {"paper_only": True, "source": "Binance TR public historical M1 OHLCV", "generated_at": datetime.now(timezone.utc).isoformat(),
              "symbols": symbols, "provenance": provenance, "errors": errors,
              "signal": "M1/M5/M15/H1/H4 close > EMA9 > EMA21 > EMA50 and EMA9 rising; all candles closed.",
              "confirmation": "Historical volume-ratio and Analyzer-compatible OHLCV orderflow_proxy; order-book imbalance unavailable historically.",
              "execution": {"entry": "next M1 open", "max_hold_minutes": MAX_HOLD_MINUTES, "initial_stop_pct": STOP_PCT * 100, "trail_arm_pct": TRAIL_ARM_PCT * 100, "trail_distance_pct": TRAIL_DISTANCE_PCT * 100,
                            "commission_pct_each_side": config.COMMISSION_PCT * 100, "assumed_full_spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * 100, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * 100},
              "candidates": CANDIDATES, "partitions": {}}
    for name, partition in {"in_sample": events[:split], "out_of_sample": events[split:]}.items():
        result["partitions"][name] = {}
        for candidate, rule in CANDIDATES.items():
            trades = [{**event["trade"], "symbol": event["symbol"], "signal_time": event["signal_time"], "features": event["features"]} for event in partition if passes(event["features"], rule)]
            result["partitions"][name][candidate] = {"rule": rule, "summary": summarize(trades), "trades": trades}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps({name: {candidate: data["summary"] for candidate, data in partition.items()} for name, partition in result["partitions"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", default="mtf-5of5-managed-replay.json")
    parsed = parser.parse_args()
    if parsed.days < 11 or parsed.days > 30:
        parser.error("days 11 ile 30 arasında olmalıdır")
    asyncio.run(main(parsed))
