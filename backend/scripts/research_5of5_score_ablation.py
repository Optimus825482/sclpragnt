"""Time-based OOS component ablation for the causal 5/5 spike score.

This does not add a live entry gate.  It asks which already-calculated score
components improve the same next-15-minute, fee-aware outcome.
"""

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

from scripts.research_5of5_spike_score import build_symbol_events, threshold_summary
from scripts.research_m1_cache import cached_m1


DEFAULT_SYMBOLS = ("HEMITRY", "PUMPTRY", "ESPTRY", "ACETRY", "BTCTRY", "ETHTRY", "SOLTRY", "XRPTRY")
COHORTS = {
    "score_ge_3": lambda event: event["score"] >= 3,
    "score_ge_4": lambda event: event["score"] >= 4,
    "score_ge_4_breakout": lambda event: event["score"] >= 4 and event["components"]["breakout"],
    "score_ge_4_volume_flow": lambda event: event["score"] >= 4 and event["components"]["positive_volume_flow"],
    "score_ge_4_breakout_volume_flow": lambda event: event["score"] >= 4 and event["components"]["breakout"] and event["components"]["positive_volume_flow"],
    "score_ge_4_squeeze": lambda event: event["score"] >= 4 and event["components"]["squeeze_expansion"],
    "score_ge_5": lambda event: event["score"] >= 5,
}


async def fetch_m1_paged(symbol, days, end_ms, cache_dir):
    """Fetch fixed M1 pages sequentially with durable cache checkpoints."""
    start_ms = end_ms - days * 86_400_000
    return await cached_m1(symbol, start_ms, end_ms, cache_dir)


async def loaded_symbol(symbol, days, end_ms, cache_dir, symbol_semaphore):
    try:
        async with symbol_semaphore:
            rows, cache_stats = await fetch_m1_paged(symbol, days, end_ms, cache_dir)
        return symbol, rows, cache_stats, None
    except Exception as exc:  # retain source failures in the artifact
        return symbol, [], {}, f"{type(exc).__name__}: {exc}"


def cohort_report(events):
    return {name: threshold_summary([event for event in events if rule(event)], 0) for name, rule in COHORTS.items()}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--oos-fraction", type=float, default=0.30)
    parser.add_argument("--parallel", type=int, default=1, help="concurrent symbols; each M1 page stream stays sequential")
    parser.add_argument("--cache-dir", default=".research_cache/binance_tr_m1")
    parser.add_argument("--end-ms", type=int, help="fixed UTC end timestamp in milliseconds for resumable runs")
    parser.add_argument("--output", default="research_5of5_score_ablation.json")
    args = parser.parse_args()
    if not 0 < args.oos_fraction < 1:
        raise SystemExit("--oos-fraction must be between 0 and 1")

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms = args.end_ms if args.end_ms is not None else now_ms // 60_000 * 60_000
    if end_ms > now_ms:
        raise SystemExit("--end-ms cannot be in the future")
    end = datetime.fromtimestamp(end_ms / 1000, timezone.utc)
    start = end - timedelta(days=args.days)
    cutoff = start + (end - start) * (1 - args.oos_fraction)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    symbols = [symbol.replace("_", "").upper() for symbol in args.symbols]
    semaphore = asyncio.Semaphore(args.parallel)
    results = await asyncio.gather(*(loaded_symbol(symbol, args.days, end_ms, args.cache_dir, semaphore) for symbol in symbols))

    events, provenance, errors = [], {}, {}
    for symbol, rows, cache_stats, error in results:
        provenance[symbol] = {"m1_closed_candles": len(rows), "cache": cache_stats}
        if error:
            errors[symbol] = error
            continue
        print(f"Scoring {symbol}: {len(rows)} closed M1 candles", flush=True)
        symbol_events, stages = build_symbol_events(symbol, rows)
        provenance[symbol]["stage_counts"] = stages
        events.extend(symbol_events)
    events.sort(key=lambda event: event["signal_time"])
    insample = [event for event in events if event["signal_time"] < cutoff_ms]
    oos = [event for event in events if event["signal_time"] >= cutoff_ms]
    payload = {
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Binance TR public historical M1 OHLCV",
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": args.days},
        "oos_start": cutoff.isoformat(),
        "candidate": "unchanged causal 5/5 score; first EMA9/VWAP hold within 10m; 60m per-symbol cooldown",
        "outcome": "next-M1-open fill, 15 completed M1 candles, active-config commission/spread/slippage",
        "cohorts": {
            name: "component is an ablation subset, not a standalone signal" for name in COHORTS
        },
        "provenance": provenance,
        "errors": errors,
        "all": cohort_report(events),
        "in_sample": cohort_report(insample),
        "oos": cohort_report(oos),
        "events": events,
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload["oos"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
