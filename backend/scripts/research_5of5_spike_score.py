"""Causal research for the 5/5 bullish spike score.

This is deliberately a paper-research script.  It measures the next 15
minutes after a candidate, with no future data used to form the score.
"""

import argparse
import asyncio
import bisect
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.binance_tr_public import historical_klines
from scripts.research_5of5_spike_setup import (
    TFS,
    adr_ok,
    atr,
    ema_values,
    find_pullback,
    outcome,
    radar_series,
    summarize,
    vwap,
    vwap_values,
    width,
    width_values,
)
from scripts.research_mtf_5of5_managed_replay import flow_proxy, normalize, resample, volume_ratio


DEFAULT_SYMBOLS = ("HEMITRY", "PUMPTRY", "ESPTRY", "ACETRY")
COOLDOWN_MS = 60 * 60 * 1000


async def fetch(symbol: str, interval: str, days: int, end_ms: int):
    rows = await historical_klines(symbol, interval, days, end_time_ms=end_ms)
    return normalize(rows)


def at_or_before(times, timestamp):
    """Return the number of completed rows at timestamp."""
    return bisect.bisect_right(times, timestamp)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def squeeze_expansion(widths, index):
    current = widths[index]
    previous = widths[index - 1] if index else None
    history = [x for x in widths[max(0, index - 24):index] if x is not None]
    if current is None or previous is None or len(history) < 12:
        return False
    recent_low = min(history[-12:])
    low_quartile = percentile(history, 0.25)
    return current >= previous * 1.15 and recent_low <= low_quartile


def build_symbol_events(symbol, m1):
    frames = {"1m": m1}
    for tf in TFS[1:]:
        frames[tf] = resample(m1, {"5m": 5, "15m": 15, "1h": 60, "4h": 240}[tf])
    if any(not frames[tf] for tf in TFS):
        return [], {"all5": 0, "pullback": 0, "scored": 0}

    times = {tf: [row["close_time"] for row in rows] for tf, rows in frames.items()}
    flags = {tf: radar_series(rows) for tf, rows in frames.items()}
    five = frames["5m"]
    widths = width_values(five)
    m1_ema9 = ema_values(m1, 9)
    m1_vwap = vwap_values(m1, 20)
    events = []
    counts = defaultdict(int)
    next_allowed = 0
    alignment_streak = 0

    for index, candle in enumerate(five):
        if index < 24:
            continue
        close_time = candle["close_time"]
        ends = {tf: at_or_before(times[tf], close_time) for tf in TFS}
        if not all(ends.values()):
            alignment_streak = 0
            continue
        all5_bullish = all(flags[tf][ends[tf] - 1] for tf in TFS)
        if not all5_bullish:
            alignment_streak = 0
            continue
        alignment_streak += 1
        counts["all5"] += 1

        m1_end = ends["1m"]
        causal_m1 = m1[:m1_end]
        causal_m5 = five[: index + 1]
        components = {"base_5of5": True, "fresh_5of5": alignment_streak == 1}
        score = 2

        components["squeeze_expansion"] = squeeze_expansion(widths, index)
        if components["squeeze_expansion"]:
            score += 1

        previous_high = max(row["high"] for row in five[index - 3:index])
        components["breakout"] = candle["close"] > previous_high
        if components["breakout"]:
            score += 1

        m1_vr = volume_ratio(causal_m1, 20)
        m5_vr = volume_ratio(causal_m5, 20)
        m1_flow = flow_proxy(causal_m1, 20)
        m5_flow = flow_proxy(causal_m5, 20)
        components["positive_volume_flow"] = (
            m1_vr >= 1.5 and m5_vr >= 1.2 and m1_flow >= 0.05 and m5_flow >= 0.05
        )
        if components["positive_volume_flow"]:
            score += 1

        current_vwap = vwap(causal_m5)
        current_atr = atr(causal_m5)
        components["not_extended"] = bool(
            current_vwap
            and current_atr
            and candle["close"] - current_vwap <= 1.5 * current_atr
            and adr_ok(causal_m1)
        )
        if not components["not_extended"]:
            score -= 1

        entry_index = find_pullback(m1, m1_end - 1, m1_ema9, m1_vwap, limit=10)
        components["ema_vwap_pullback"] = entry_index is not None
        if entry_index is not None:
            score += 1
            counts["pullback"] += 1

        if entry_index is None or score < 3:
            continue
        entry_time = m1[entry_index]["time"]
        if entry_time < next_allowed:
            continue
        measured = outcome(m1, entry_index)
        if measured is None:
            continue
        next_allowed = entry_time + COOLDOWN_MS
        counts["scored"] += 1
        events.append(
            {
                "symbol": symbol,
                "signal_time": candle["time"],
                "entry_time": entry_time,
                "entry_delay_minutes": round((entry_time - candle["time"]) / 60000, 1),
                "score": score,
                "components": components,
                "features": {
                    "m1_volume_ratio": m1_vr,
                    "m5_volume_ratio": m5_vr,
                    "m1_flow": m1_flow,
                    "m5_flow": m5_flow,
                    "flow_min": min(m1_flow, m5_flow) if m1_flow is not None and m5_flow is not None else None,
                    "m5_atr_pct": (current_atr / candle["close"] * 100) if current_atr and candle["close"] else None,
                    "vwap_extension_atr": ((candle["close"] - current_vwap) / current_atr) if current_vwap and current_atr else None,
                    "m5_bb_width_pct": widths[index] * 100 if widths[index] is not None else None,
                    "alignment_age_5m": alignment_streak,
                },
                "outcome": measured,
            }
        )
    return events, dict(counts)


def threshold_summary(events, threshold):
    selected = [event for event in events if event["score"] >= threshold]
    report = summarize(selected)
    report["score_threshold"] = threshold
    report["score_distribution"] = dict(sorted(Counter(event["score"] for event in selected).items()))
    report["by_symbol"] = {
        symbol: summarize([event for event in selected if event["symbol"] == symbol])
        for symbol in sorted({event["symbol"] for event in selected})
    }
    return report


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--oos-fraction", type=float, default=0.30)
    parser.add_argument("--output", default="research_5of5_spike_score.json")
    args = parser.parse_args()
    if not 0 < args.oos_fraction < 1:
        raise SystemExit("--oos-fraction must be between 0 and 1")

    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    all_events, counts = [], {}
    for symbol in args.symbols:
        print(f"Fetching {symbol} 1m data...", flush=True)
        rows = await fetch(symbol, "1m", args.days, end_ms)
        if not rows:
            print(f"  no data for {symbol}", flush=True)
            continue
        events, symbol_counts = build_symbol_events(symbol, rows)
        all_events.extend(events)
        counts[symbol] = symbol_counts
        print(f"  candidates score>=3: {len(events)}", flush=True)

    all_events.sort(key=lambda event: event["signal_time"])
    cutoff = start + (end - start) * (1 - args.oos_fraction)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    insample = [event for event in all_events if event["signal_time"] < cutoff_ms]
    oos = [event for event in all_events if event["signal_time"] >= cutoff_ms]
    payload = {
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": args.days},
        "method": {
            "base": "all M1/M5/M15/H1/H4 radar states bullish, score +2",
            "additions": {
                "squeeze_expansion": "+1",
                "five_minute_breakout": "+1",
                "positive_volume_flow": "+1",
                "ema9_vwap_pullback_hold": "+1",
                "adr_or_vwap_extended": "-1",
            },
            "entry": "first 1m EMA9/VWAP hold within 10m; 60m per-symbol cooldown",
            "outcome": "entry next 1m open; next 15 completed 1m candles; max peak, max dip, terminal close and estimated costs",
            "costs": "config commission + spread + slippage",
            "split": f"time-based chronological {round((1 - args.oos_fraction) * 100)}% development / {round(args.oos_fraction * 100)}% OOS",
            "oos_start": cutoff.isoformat(),
        },
        "stage_counts": counts,
        "all_candidates": {"score_ge_3": threshold_summary(all_events, 3), "score_ge_4": threshold_summary(all_events, 4)},
        "in_sample": {"score_ge_3": threshold_summary(insample, 3), "score_ge_4": threshold_summary(insample, 4)},
        "oos": {"score_ge_3": threshold_summary(oos, 3), "score_ge_4": threshold_summary(oos, 4)},
        "events": all_events,
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload["oos"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
