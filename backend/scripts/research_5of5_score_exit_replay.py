"""Fee-aware, causal exit comparison for score >= 4 5/5 spike candidates.

Research only: candidate formation is imported unchanged from the score replay;
each model gets the same next-M1-open fill and only the exit rule differs.
"""

import argparse
import asyncio
import bisect
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.config import config
from scripts.research_5of5_spike_score import DEFAULT_SYMBOLS, build_symbol_events, fetch


ORDER_VALUE_TRY = 1000.0
HARD_STOP_PCT = 0.0075
ARM_PCT = 0.01
MODELS = {
    "fixed_15m": {"hold": 15, "hard_stop": False, "arm": False, "trail": None},
    "fixed_30m": {"hold": 30, "hard_stop": False, "arm": False, "trail": None},
    "breakeven_30m": {"hold": 30, "hard_stop": True, "arm": True, "trail": None},
    "trail_04_30m": {"hold": 30, "hard_stop": True, "arm": True, "trail": 0.004},
    "trail_06_30m": {"hold": 30, "hard_stop": True, "arm": True, "trail": 0.006},
}


def fill_exit(raw_price):
    return raw_price * (1 - config.BACKTEST_ASSUMED_SPREAD_PCT / 2 - config.ESTIMATED_SLIPPAGE_PCT)


def net_pct(entry_fill, raw_exit):
    quantity = ORDER_VALUE_TRY / entry_fill
    proceeds = quantity * fill_exit(raw_exit) * (1 - config.COMMISSION_PCT)
    spent = ORDER_VALUE_TRY * (1 + config.COMMISSION_PCT)
    return (proceeds / spent - 1) * 100


def simulate(m1, entry_index, model):
    """Simulate a long exit with adverse-first OHLC ordering in each M1 bar."""
    params = MODELS[model]
    entry = m1[entry_index]["open"] * (1 + config.BACKTEST_ASSUMED_SPREAD_PCT / 2 + config.ESTIMATED_SLIPPAGE_PCT)
    bars = m1[entry_index:min(len(m1), entry_index + params["hold"])]
    if len(bars) < params["hold"]:
        return None

    armed = False
    peak = entry
    stop = entry * (1 - HARD_STOP_PCT) if params["hard_stop"] else None
    peak_high, trough_low = entry, entry
    for number, bar in enumerate(bars, start=1):
        peak_high = max(peak_high, bar["high"])
        trough_low = min(trough_low, bar["low"])
        # Conservative candle treatment: a low can hit the already-active stop
        # before the high of the same candle arms or ratchets protection.
        if stop is not None and bar["low"] <= stop:
            return {
                "net_pct": net_pct(entry, min(stop, bar["low"])),
                "exit_reason": "breakeven_stop" if armed and stop >= entry else "hard_stop",
                "hold_minutes": number,
                "max_up_pct": (peak_high / entry - 1) * 100,
                "max_down_pct": (trough_low / entry - 1) * 100,
            }
        peak = max(peak, bar["high"])
        if params["arm"] and not armed and peak >= entry * (1 + ARM_PCT):
            armed = True
            stop = entry
        if armed and params["trail"] is not None:
            stop = max(entry, peak * (1 - params["trail"]))

    return {
        "net_pct": net_pct(entry, bars[-1]["close"]),
        "exit_reason": "time_limit",
        "hold_minutes": params["hold"],
        "max_up_pct": (peak_high / entry - 1) * 100,
        "max_down_pct": (trough_low / entry - 1) * 100,
    }


def median(values):
    values = sorted(values)
    return values[len(values) // 2] if len(values) % 2 else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2


def summarize(records, include_symbols=True):
    if not records:
        return {"n": 0}
    net = [record["result"]["net_pct"] for record in records]
    report = {
        "n": len(records),
        "mean_net_pct": round(sum(net) / len(net), 4),
        "median_net_pct": round(median(net), 4),
        "net_positive_rate": round(sum(value > 0 for value in net) / len(net), 4),
        "median_max_up_pct": round(median([record["result"]["max_up_pct"] for record in records]), 4),
        "median_max_down_pct": round(median([record["result"]["max_down_pct"] for record in records]), 4),
        "median_hold_minutes": round(median([record["result"]["hold_minutes"] for record in records]), 2),
        "exit_reasons": dict(sorted(Counter(record["result"]["exit_reason"] for record in records).items())),
    }
    if include_symbols:
        report["by_symbol"] = {
            symbol: summarize([record for record in records if record["symbol"] == symbol], include_symbols=False)
            for symbol in sorted({record["symbol"] for record in records})
        }
    return report


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--oos-fraction", type=float, default=0.30)
    parser.add_argument("--output", default="research_5of5_score_exit_replay.json")
    args = parser.parse_args()
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    end_ms = int(end.timestamp() * 1000)
    cutoff = start + (end - start) * (1 - args.oos_fraction)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    records = {model: [] for model in MODELS}
    provenance = {}

    for symbol in args.symbols:
        print(f"Fetching {symbol}...", flush=True)
        m1 = await fetch(symbol, "1m", args.days, end_ms)
        provenance[symbol] = {"m1_closed_candles": len(m1)}
        events, stages = build_symbol_events(symbol, m1)
        provenance[symbol]["stages"] = stages
        index_by_time = {row["time"]: index for index, row in enumerate(m1)}
        for event in events:
            if event["score"] < 4:
                continue
            entry_index = index_by_time.get(event["entry_time"])
            if entry_index is None:
                continue
            for model in MODELS:
                result = simulate(m1, entry_index, model)
                if result:
                    records[model].append({"symbol": symbol, "score": event["score"], "signal_time": event["signal_time"], "entry_time": event["entry_time"], "result": result})

    for model in MODELS:
        records[model].sort(key=lambda record: record["signal_time"])
    payload = {
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": args.days},
        "source": "Binance TR public historical M1 OHLCV",
        "candidate": "score >=4 from unchanged causal 5/5 spike-score generator",
        "execution": "next M1 open; commission, spread and slippage from active config; per-candle adverse-first stop ordering",
        "models": {
            "fixed_15m": "close at 15 minutes",
            "fixed_30m": "close at 30 minutes",
            "breakeven_30m": "-0.75% hard stop; after +1.0%, stop moved to entry; maximum 30m",
            "trail_04_30m": "same arm and hard stop; after arm, trail peak by 0.4%; maximum 30m",
            "trail_06_30m": "same arm and hard stop; after arm, trail peak by 0.6%; maximum 30m",
        },
        "oos_start": cutoff.isoformat(),
        "provenance": provenance,
        "all": {model: summarize(items) for model, items in records.items()},
        "in_sample": {model: summarize([item for item in items if item["signal_time"] < cutoff_ms]) for model, items in records.items()},
        "oos": {model: summarize([item for item in items if item["signal_time"] >= cutoff_ms]) for model, items in records.items()},
        "records": records,
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload["oos"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
