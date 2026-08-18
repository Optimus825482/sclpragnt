"""Find causal M1 features that distinguish large future spikes from controls.

Research only: future price moves are labels.  Every feature is calculated
from candles closed at the decision timestamp, so this file never emits a
trade signal or changes live/paper strategy configuration.
"""
import argparse
import asyncio
import bisect
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from scripts.research_m1_spikes import as_series, features, indicator_features


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def summary(rows, field):
    values = [row["indicators"].get(field) for row in rows
              if isinstance(row["indicators"].get(field), (int, float))]
    if not values:
        return None
    return {
        "count": len(values),
        "median": round(statistics.median(values), 4),
        "p25": round(percentile(values, .25), 4),
        "p75": round(percentile(values, .75), 4),
        "mean": round(statistics.mean(values), 4),
    }


def regime(snapshot, indicators):
    """Classify observed pre-event state; it is not a proposed entry rule."""
    if (snapshot["return_15m_pct"] <= -1.0 and
            (indicators.get("rsi_14") or 100) <= 40):
        return "dip_reversal"
    if (snapshot["return_15m_pct"] >= 1.0 and
            (indicators.get("ema9_ema21_gap_pct") or 0) > 0):
        return "trend_continuation"
    return "other"


async def main(args):
    tz = ZoneInfo(args.timezone)
    start_ts = int(datetime.fromisoformat(args.start_date).replace(tzinfo=tz).timestamp())
    end_ts = int(datetime.fromisoformat(args.end_date).replace(tzinfo=tz).timestamp())
    if start_ts >= end_ts:
        raise SystemExit("Başlangıç bitişten önce olmalıdır")
    await database.init_db()
    symbols = args.symbols or await database.get_market_symbols("5m")
    horizon = args.horizon_minutes * 60
    cadence = args.sample_minutes * 60
    cooldown = args.event_cooldown_minutes * 60
    semaphore = asyncio.Semaphore(args.workers)

    expected_samples = max(1, (end_ts - start_ts) // cadence + 1)
    # The research target is a balanced comparison, not an exhaustive census
    # of every quiet minute.  Decide control timestamps before expensive
    # indicator work, spreading them across the whole window.
    control_stride = max(1, expected_samples // args.max_controls_per_symbol)

    async def inspect(symbol):
        async with semaphore:
            rows = await database.get_market_candles(
                symbol, "1m", (start_ts - 60 * 60) * 1000, (end_ts + horizon) * 1000
            )
        data = as_series(rows)
        positives, controls, next_positive = [], [], 0
        for ts in range(start_ts, end_ts + 1, cadence):
            index = bisect.bisect_right(data["times"], ts) - 1
            future_end = bisect.bisect_right(data["times"], ts + horizon)
            if index < 60 or future_end <= index + 1:
                continue
            price = data["closes"][index]
            if not price:
                continue
            upside = (max(data["highs"][index + 1:future_end]) / price - 1) * 100
            is_positive = upside >= args.spike_threshold_pct and ts >= next_positive
            # Retain a deterministic, evenly spread quiet control sample.
            is_control = upside < args.control_max_upside_pct and ((ts - start_ts) // cadence) % control_stride == 0
            if not is_positive and not is_control:
                continue
            snapshot = features(data, index)
            indicators = indicator_features(data, index)
            if not snapshot or not indicators:
                continue
            downside = (min(data["lows"][index + 1:future_end]) / price - 1) * 100
            row = {"symbol": symbol, "time": ts, "features": snapshot, "indicators": indicators,
                   "future_upside_pct": round(upside, 4), "future_downside_pct": round(downside, 4)}
            if is_positive:
                row["regime"] = regime(snapshot, indicators)
                positives.append(row)
                next_positive = ts + cooldown
            elif is_control:
                controls.append(row)
        return positives, controls

    all_results = []
    tasks = [asyncio.create_task(inspect(symbol)) for symbol in symbols]
    for completed, task in enumerate(asyncio.as_completed(tasks), start=1):
        all_results.append(await task)
        if completed == 1 or completed % 10 == 0 or completed == len(symbols):
            print(f"[PROGRESS] symbols={completed}/{len(symbols)}", flush=True)
    positives = [row for found, _ in all_results for row in found]
    controls = [row for _, found in all_results for row in found]
    fields = ("return_1m_pct", "return_5m_pct", "return_15m_pct", "volume_ratio_20",
              "range_15m_pct", "close_to_15m_high_pct", "rsi_14", "atr_14_pct",
              "vwap20_distance_pct", "ema9_ema21_gap_pct", "macd_histogram",
              "bb20_bandwidth_pct", "adx_14", "plus_di", "minus_di")
    # Make one uniform shape for price and indicator features.
    for row in positives + controls:
        row["indicators"] = {**row["features"], **row["indicators"]}
    regimes = {name: [row for row in positives if row["regime"] == name]
               for name in ("dip_reversal", "trend_continuation", "other")}
    payload = {
        "paper_only": True,
        "source": "historical_candles / Binance TR public M1",
        "window": {"start": args.start_date, "end": args.end_date, "timezone": args.timezone},
        "label": {
            "future_horizon_minutes": args.horizon_minutes,
            "positive": f"future max high >= +{args.spike_threshold_pct}%",
            "control": f"future max high < +{args.control_max_upside_pct}%",
            "warning": "Future outcomes are labels only and are never signal inputs.",
        },
        "sample_minutes": args.sample_minutes,
        "symbols": len(symbols),
        "positive_events": len(positives),
        "controls": len(controls),
        "feature_comparison": {
            "positive_all": {field: summary(positives, field) for field in fields},
            "controls": {field: summary(controls, field) for field in fields},
            "positive_by_regime": {name: {field: summary(rows, field) for field in fields}
                                   for name, rows in regimes.items()},
        },
        "events": positives,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "symbols": len(symbols), "positive_events": len(positives), "controls": len(controls),
        "regimes": {name: len(rows) for name, rows in regimes.items()},
        "feature_medians": {
            "positive": {field: (summary(positives, field) or {}).get("median") for field in fields},
            "controls": {field: (summary(controls, field) or {}).get("median") for field in fields},
        },
    }
    print("[COMPLETE] result=" + str(Path(args.output).resolve()))
    print("RESULT_JSON=" + json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--horizon-minutes", type=int, default=60)
    parser.add_argument("--spike-threshold-pct", type=float, default=20.0)
    parser.add_argument("--control-max-upside-pct", type=float, default=2.0)
    parser.add_argument("--sample-minutes", type=int, default=5)
    parser.add_argument("--event-cooldown-minutes", type=int, default=60)
    parser.add_argument("--max-controls-per-symbol", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--output", default="m1-spike-regime-research.json")
    args = parser.parse_args()
    if (args.horizon_minutes < 5 or args.spike_threshold_pct <= 0 or args.control_max_upside_pct < 0 or
            args.sample_minutes < 1 or args.event_cooldown_minutes < 1 or args.max_controls_per_symbol < 1 or
            not 1 <= args.workers <= 64):
        parser.error("araştırma parametreleri geçersiz")
    asyncio.run(main(args))
