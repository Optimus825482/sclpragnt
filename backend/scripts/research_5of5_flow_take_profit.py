"""Fee-aware 15m take-profit ablation for score>=4 + positive volume/flow."""

import argparse
import asyncio
import bisect
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.config import config
from scripts.research_5of5_score_ablation import DEFAULT_SYMBOLS
from scripts.research_5of5_spike_score import build_symbol_events
from scripts.research_m1_cache import cached_m1


ORDER_VALUE_TRY = 1000.0
HOLD_MINUTES = 15
MODELS = {"time_15m": None, "tp_06": 0.006, "tp_08": 0.008, "tp_10": 0.010}


def exit_net_pct(entry_fill, raw_exit):
    exit_fill = raw_exit * (1 - config.BACKTEST_ASSUMED_SPREAD_PCT / 2 - config.ESTIMATED_SLIPPAGE_PCT)
    quantity = ORDER_VALUE_TRY / entry_fill
    proceeds = quantity * exit_fill * (1 - config.COMMISSION_PCT)
    spent = ORDER_VALUE_TRY * (1 + config.COMMISSION_PCT)
    return (proceeds / spent - 1) * 100


def simulate(m1, entry_index, target):
    entry = m1[entry_index]["open"] * (1 + config.BACKTEST_ASSUMED_SPREAD_PCT / 2 + config.ESTIMATED_SLIPPAGE_PCT)
    bars = m1[entry_index:entry_index + HOLD_MINUTES]
    if len(bars) < HOLD_MINUTES:
        return None
    peak = max(bar["high"] for bar in bars)
    trough = min(bar["low"] for bar in bars)
    if target is not None:
        raw_target = entry * (1 + target)
        for hold, bar in enumerate(bars, start=1):
            if bar["high"] >= raw_target:
                return {"net_pct": exit_net_pct(entry, raw_target), "exit_reason": "take_profit", "hold_minutes": hold,
                        "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100}
    return {"net_pct": exit_net_pct(entry, bars[-1]["close"]), "exit_reason": "time_limit", "hold_minutes": HOLD_MINUTES,
            "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100}


def median(values):
    values = sorted(values); middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def summary(records, include_symbols=True):
    if not records:
        return {"n": 0}
    net = [record["result"]["net_pct"] for record in records]
    report = {"n": len(records), "mean_net_pct": round(sum(net) / len(net), 4), "median_net_pct": round(median(net), 4),
            "net_positive_rate": round(sum(value > 0 for value in net) / len(net), 4),
            "median_hold_minutes": round(median([record["result"]["hold_minutes"] for record in records]), 2),
            "exit_reasons": dict(sorted(Counter(record["result"]["exit_reason"] for record in records).items()))}
    if include_symbols:
        report["by_symbol"] = {symbol: summary([record for record in records if record["symbol"] == symbol], include_symbols=False)
                               for symbol in sorted({record["symbol"] for record in records})}
    return report


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--end-ms", type=int, required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--oos-fraction", type=float, default=0.30)
    parser.add_argument("--output", default="research_5of5_flow_take_profit.json")
    args = parser.parse_args()
    end = datetime.fromtimestamp(args.end_ms / 1000, timezone.utc)
    start = end - timedelta(days=args.days)
    cutoff = start + (end - start) * (1 - args.oos_fraction)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    records = {name: [] for name in MODELS}; provenance = {}
    for symbol in args.symbols:
        rows, cache = await cached_m1(symbol, int(start.timestamp() * 1000), args.end_ms, args.cache_dir)
        provenance[symbol] = {"m1_closed_candles": len(rows), "cache": cache}
        events, _ = build_symbol_events(symbol, rows)
        indexes = {row["time"]: index for index, row in enumerate(rows)}
        for event in events:
            if event["score"] < 4 or not event["components"]["positive_volume_flow"]:
                continue
            index = indexes.get(event["entry_time"])
            if index is None:
                continue
            for name, target in MODELS.items():
                result = simulate(rows, index, target)
                if result:
                    records[name].append({"symbol": symbol, "signal_time": event["signal_time"], "score": event["score"], "result": result})
    for items in records.values(): items.sort(key=lambda item: item["signal_time"])
    payload = {"research_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
               "source": "cached Binance TR public historical M1 OHLCV", "window": {"start": start.isoformat(), "end": end.isoformat(), "days": args.days},
               "oos_start": cutoff.isoformat(), "candidate": "score >=4 AND positive M1/M5 volume-flow component",
               "entry": "unchanged causal first EMA9/VWAP hold; next M1 open", "exit": "full position at target touch or 15m close; no stop added",
               "costs": "active commission, spread and slippage config", "provenance": provenance,
               "all": {name: summary(items) for name, items in records.items()},
               "in_sample": {name: summary([item for item in items if item["signal_time"] < cutoff_ms]) for name, items in records.items()},
               "oos": {name: summary([item for item in items if item["signal_time"] >= cutoff_ms]) for name, items in records.items()}, "records": records}
    with open(args.output, "w", encoding="utf-8") as handle: json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload["oos"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
