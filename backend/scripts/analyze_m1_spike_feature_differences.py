"""Compare stored causal M1 features at future-spike labels and controls."""
import argparse
import asyncio
import bisect
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import database


def stats(values):
    if not values: return None
    ordered = sorted(values)
    return {"count": len(values), "median": round(statistics.median(values), 5),
            "p25": round(ordered[round((len(ordered)-1)*.25)], 5), "p75": round(ordered[round((len(ordered)-1)*.75)], 5), "mean": round(statistics.mean(values), 5)}


async def main(args):
    tz = ZoneInfo(args.timezone); end = int(datetime.fromisoformat(args.end_date).replace(tzinfo=tz).timestamp() * 1000); start = end - args.hours * 3_600_000
    await database.init_db(); symbols = args.symbols or await database.get_market_symbols("1m")
    horizon, cooldown = args.horizon_minutes * 60_000, args.event_cooldown_minutes * 60_000
    fields = ("return_1m_pct", "return_5m_pct", "return_15m_pct", "return_1h_pct", "atr14_pct", "atr14_p80_24h", "range15_pct", "range60_pct", "rsi14", "volume_ratio20", "vwap20_distance_pct", "ema9_ema21_gap_pct", "macd_acceleration", "bb_bandwidth_pct", "bb_position", "lower_wick_atr", "body_atr")
    spikes, controls, bool_counts = [], [], {"spike": 0, "control": 0}
    for number, symbol in enumerate(symbols, 1):
        snapshots = await database.get_market_feature_snapshots(symbol, "1m", start, end, args.feature_version)
        candles = await database.get_market_candles(symbol, "1m", start, end + horizon)
        times, highs = [int(row["close_time"]) for row in candles], [float(row["high"]) for row in candles]
        next_spike = 0
        for row in snapshots:
            captured = int(row["captured_at"]); entry = float(row["payload"].get("return_1m_pct") or 0)
            candle_index = bisect.bisect_right(times, captured) - 1; future_end = bisect.bisect_right(times, captured + horizon)
            if candle_index < 0 or future_end <= candle_index + 1: continue
            close = float(candles[candle_index]["close"])
            upside = (max(highs[candle_index + 1:future_end]) / close - 1) * 100 if close else 0
            item = row["payload"]
            if upside >= args.spike_threshold_pct and captured >= next_spike:
                spikes.append(item); next_spike = captured + cooldown; bool_counts["spike"] += bool(item.get("liquidity_sweep_reclaim"))
            elif upside < args.control_max_upside_pct:
                controls.append(item); bool_counts["control"] += bool(item.get("liquidity_sweep_reclaim"))
        if number == 1 or number % 25 == 0 or number == len(symbols): print(f"[PROGRESS] symbols={number}/{len(symbols)} spikes={len(spikes)} controls={len(controls)}", flush=True)
    comparison = {}
    for field in fields:
        positive = [float(x[field]) for x in spikes if isinstance(x.get(field), (int, float))]
        negative = [float(x[field]) for x in controls if isinstance(x.get(field), (int, float))]
        comparison[field] = {"spikes": stats(positive), "controls": stats(negative), "median_delta": round(statistics.median(positive) - statistics.median(negative), 5) if positive and negative else None}
    result = {"paper_only": True, "source": "historical_feature_snapshots + historical_candles / Binance TR public M1", "feature_version": args.feature_version,
              "window": {"hours": args.hours, "end_date": args.end_date, "timezone": args.timezone},
              "label": {"future_horizon_minutes": args.horizon_minutes, "spike_min_upside_pct": args.spike_threshold_pct, "control_max_upside_pct": args.control_max_upside_pct, "future_labels_only": True},
              "spike_snapshots": len(spikes), "control_snapshots": len(controls), "feature_comparison": comparison,
              "boolean_feature_rates": {"liquidity_sweep_reclaim": {"spikes_pct": round(bool_counts["spike"] / len(spikes) * 100, 3) if spikes else 0, "controls_pct": round(bool_counts["control"] / len(controls) * 100, 3) if controls else 0}}}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {"feature_version": args.feature_version, "spike_snapshots": len(spikes), "control_snapshots": len(controls), "boolean_feature_rates": result["boolean_feature_rates"], "feature_medians": {key: {"spikes": value["spikes"]["median"] if value["spikes"] else None, "controls": value["controls"]["median"] if value["controls"] else None, "delta": value["median_delta"]} for key, value in comparison.items()}}
    print("[COMPLETE] result=" + str(Path(args.output).resolve())); print("RESULT_JSON=" + json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--symbols", nargs="*"); parser.add_argument("--hours", type=int, default=24); parser.add_argument("--end-date", required=True); parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--feature-version", default="m1-spike-v1"); parser.add_argument("--horizon-minutes", type=int, default=60); parser.add_argument("--spike-threshold-pct", type=float, default=20); parser.add_argument("--control-max-upside-pct", type=float, default=2); parser.add_argument("--event-cooldown-minutes", type=int, default=60); parser.add_argument("--output", default="m1-spike-feature-differences.json")
    args = parser.parse_args()
    if args.hours < 1 or args.hours > 72 or args.horizon_minutes < 5 or args.spike_threshold_pct <= 0: parser.error("araştırma parametreleri geçersiz")
    asyncio.run(main(args))
