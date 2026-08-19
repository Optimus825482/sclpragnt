"""Causal, paper-only study of the Gainer Radar M1/M5/M15/H1/H4 alignment.

The definition exactly mirrors the radar: close > EMA9 > EMA21 > EMA50 and
EMA9 is rising.  It is a forward-outcome study, not an execution strategy.
"""

import argparse
import asyncio
import bisect
import json
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
HORIZONS = (15, 30, 60)
SHORT_HORIZON_MINUTES = 15


def normalize(raw):
    now_ms = int(time.time() * 1000)
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


def resample(rows, minutes):
    buckets, output = {}, []
    width = minutes * 60_000
    for row in rows:
        start = row["time"] // width * width
        current = buckets.get(start)
        if current is None:
            current = {"time": start, "close_time": start + width - 1, "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"]}
            buckets[start] = current
            output.append(current)
        else:
            current["high"] = max(current["high"], row["high"])
            current["low"] = min(current["low"], row["low"])
            current["close"] = row["close"]
    return output


def ema(values, period):
    if len(values) < period:
        return None
    result = sum(values[:period]) / period
    multiplier = 2 / (period + 1)
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def bullish(completed):
    closes = [row["close"] for row in completed]
    if len(closes) < 55:
        return False
    ema9, ema21, ema50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    previous_ema9 = ema(closes[:-1], 9)
    return bool(ema9 and ema21 and ema50 and previous_ema9 and closes[-1] > ema9 > ema21 > ema50 and ema9 > previous_ema9)


def outcome(rows, index, horizon):
    entry = rows[index]["close"]
    end_time = rows[index]["close_time"] + horizon * 60_000
    end = bisect.bisect_right([row["close_time"] for row in rows], end_time)
    future = rows[index + 1:end]
    if not future or not entry:
        return None
    return {"max_up_pct": (max(row["high"] for row in future) / entry - 1) * 100,
            "max_down_pct": (min(row["low"] for row in future) / entry - 1) * 100,
            "close_return_pct": (future[-1]["close"] / entry - 1) * 100}


def short_trajectory(rows, index):
    """Describe the first 15 closed M1 candles after an alignment event.

    This is deliberately descriptive rather than a trading simulation: it
    preserves the exact first-bar direction, the intrawindow peak/trough time,
    and how much the price gave back after the peak.
    """
    entry = rows[index]["close"]
    end_time = rows[index]["close_time"] + SHORT_HORIZON_MINUTES * 60_000
    end = bisect.bisect_right([row["close_time"] for row in rows], end_time)
    future = rows[index + 1:end]
    if len(future) < SHORT_HORIZON_MINUTES or not entry:
        return None
    first_close_return = (future[0]["close"] / entry - 1) * 100
    peak_index = max(range(len(future)), key=lambda position: future[position]["high"])
    trough_index = min(range(len(future)), key=lambda position: future[position]["low"])
    peak = future[peak_index]["high"]
    trough = future[trough_index]["low"]
    final_close = future[-1]["close"]
    # With OHLCV we cannot know intrabar tick order, so a reversal is defined
    # conservatively as the first completed lower close *after* the peak bar.
    reversal_index = next(
        (position for position in range(peak_index + 1, len(future))
         if future[position]["close"] < future[position - 1]["close"]),
        None,
    )
    return {
        "first_1m_direction": "up" if first_close_return > 0 else "down" if first_close_return < 0 else "flat",
        "first_1m_close_return_pct": (first_close_return),
        "peak_return_pct": (peak / entry - 1) * 100,
        "peak_minute": peak_index + 1,
        "trough_return_pct": (trough / entry - 1) * 100,
        "trough_minute": trough_index + 1,
        "close_15m_return_pct": (final_close / entry - 1) * 100,
        "giveback_from_peak_pct": (final_close / peak - 1) * 100,
        "peak_before_trough": peak_index < trough_index,
        "first_lower_close_after_peak_minute": reversal_index + 1 if reversal_index is not None else None,
    }


def summary(rows):
    if not rows:
        return {"n": 0}
    values = lambda key: sorted(float(row[key]) for row in rows)
    percentile = lambda vals, q: vals[min(len(vals) - 1, int((len(vals) - 1) * q))]
    result = {"n": len(rows)}
    for horizon in HORIZONS:
        subset = [row[f"h{horizon}"] for row in rows if row.get(f"h{horizon}")]
        if not subset:
            continue
        up, close, down = values_for(subset, "max_up_pct"), values_for(subset, "close_return_pct"), values_for(subset, "max_down_pct")
        result[str(horizon)] = {"median_max_up_pct": round(percentile(up, .5), 4),
                                "p75_max_up_pct": round(percentile(up, .75), 4),
                                "median_close_return_pct": round(percentile(close, .5), 4),
                                "median_max_down_pct": round(percentile(down, .5), 4),
                                "up_1pct_rate": round(sum(value >= 1.0 for value in up) / len(up), 4),
                                "net_close_positive_after_0_30pct_cost_rate": round(sum(value > .30 for value in close) / len(close), 4)}
    return result


def values_for(rows, key):
    return sorted(float(row[key]) for row in rows)


def trajectory_summary(records):
    trajectories = [row["trajectory_15m"] for row in records if row.get("trajectory_15m")]
    if not trajectories:
        return {"n": 0}
    percentile = lambda values, q: values[min(len(values) - 1, int((len(values) - 1) * q))]
    numbers = lambda key: sorted(float(item[key]) for item in trajectories)
    reversal_minutes = sorted(item["first_lower_close_after_peak_minute"] for item in trajectories if item["first_lower_close_after_peak_minute"] is not None)
    return {
        "n": len(trajectories),
        "first_1m_up_rate": round(sum(item["first_1m_direction"] == "up" for item in trajectories) / len(trajectories), 4),
        "first_1m_down_rate": round(sum(item["first_1m_direction"] == "down" for item in trajectories) / len(trajectories), 4),
        "median_first_1m_close_return_pct": round(percentile(numbers("first_1m_close_return_pct"), .5), 4),
        "median_peak_return_pct": round(percentile(numbers("peak_return_pct"), .5), 4),
        "median_peak_minute": round(percentile(numbers("peak_minute"), .5), 2),
        "median_trough_return_pct": round(percentile(numbers("trough_return_pct"), .5), 4),
        "median_trough_minute": round(percentile(numbers("trough_minute"), .5), 2),
        "median_giveback_from_peak_pct": round(percentile(numbers("giveback_from_peak_pct"), .5), 4),
        "peak_before_trough_rate": round(sum(item["peak_before_trough"] for item in trajectories) / len(trajectories), 4),
        "lower_close_after_peak_rate": round(len(reversal_minutes) / len(trajectories), 4),
        "median_first_lower_close_after_peak_minute": round(percentile(reversal_minutes, .5), 2) if reversal_minutes else None,
    }


async def fetch(symbol, days):
    try:
        return symbol, normalize(await historical_klines(symbol, "1m", days)), None
    except Exception as exc:
        return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    symbols = [symbol.replace("_", "").upper() for symbol in args.symbols]
    loaded = await asyncio.gather(*(fetch(symbol, args.days) for symbol in symbols))
    observations, errors, provenance = [], {}, {}
    for symbol, rows, error in loaded:
        provenance[symbol] = {"m1_closed_candles": len(rows)}
        if error or len(rows) < 60 * 24 * 10:
            errors[symbol] = error or "insufficient M1 history"
            continue
        frames = {"1m": rows, **{tf: resample(rows, minutes) for tf, minutes in (("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240))}}
        times = {tf: [item["close_time"] for item in frame] for tf, frame in frames.items()}
        # Hourly decision stride limits overlapping forward labels at the 60m horizon.
        for index, row in enumerate(rows):
            if row["close_time"] % 3_600_000 > 60_000:
                continue
            states = {}
            for tf in TIMEFRAMES:
                end = bisect.bisect_right(times[tf], row["close_time"])
                states[tf] = bullish(frames[tf][:end])
            count = sum(states.values())
            record = {"symbol": symbol, "time": row["close_time"], "bullish_count": count, "all_5_bullish": count == 5}
            for horizon in HORIZONS:
                record[f"h{horizon}"] = outcome(rows, index, horizon)
            record["trajectory_15m"] = short_trajectory(rows, index)
            if all(record[f"h{horizon}"] for horizon in HORIZONS):
                observations.append(record)
    observations.sort(key=lambda row: row["time"])
    split = int(len(observations) * .70)
    partitions = {"in_sample": observations[:split], "out_of_sample": observations[split:]}
    result = {"paper_only": True, "source": "Binance TR public historical 1m OHLCV", "generated_at": datetime.now(timezone.utc).isoformat(),
              "definition": "Per timeframe: close > EMA9 > EMA21 > EMA50 and EMA9 rising; only fully closed candles.",
              "sampling": "One decision per symbol per hour; 15/30/60 minute forward outcomes; no historical spread/depth.",
              "cost_assumption": "0.30% round-trip fee proxy only; historical spread/slippage unknown.",
              "symbols_requested": symbols, "provenance": provenance, "errors": errors, "observations": len(observations), "partitions": {}, "five_of_five_15m_events": {}}
    for name, data in partitions.items():
        groups = defaultdict(list)
        for row in data:
            groups["5_of_5" if row["all_5_bullish"] else "other"].append(row)
            groups[f"count_{row['bullish_count']}"] .append(row)
        result["partitions"][name] = {key: summary(value) for key, value in groups.items()}
        five_of_five = [row for row in data if row["all_5_bullish"]]
        result["five_of_five_15m_events"][name] = {
            "summary": trajectory_summary(five_of_five),
            "events": [{"symbol": row["symbol"], "time": row["time"], **row["trajectory_15m"]} for row in five_of_five if row.get("trajectory_15m")],
        }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--output", default="mtf-5of5-forward-study.json")
    parsed = parser.parse_args()
    if parsed.days < 11 or parsed.days > 30:
        parser.error("days 11 ile 30 arasında olmalıdır")
    asyncio.run(main(parsed))
