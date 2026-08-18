"""Compare causal M1 momentum candidate rules against future move labels.

This is research only: every candidate uses data available at its timestamp;
future move labels are evaluation outcomes and never a signal input.
"""
import argparse
import asyncio
import bisect
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from scripts.research_m1_spikes import as_series, features, indicator_features


CANDIDATES = {
    "confirmed_breakout": {"ret_1m": 0.5, "ret_5m": 1.0, "ret_15m": 1.0, "volume": 1.5, "near_high": -0.5},
    "fast_acceleration": {"ret_1m": 1.0, "ret_5m": 3.0, "ret_15m": 3.0, "volume": 2.0, "near_high": -0.5},
    "volume_ignition": {"ret_1m": 0.2, "ret_5m": 0.5, "ret_15m": 0.5, "volume": 3.0, "near_high": -0.5},
    "trend_continuation_confirmed": {"ret_1m": 1.0, "ret_5m": 3.0, "ret_15m": 3.0, "volume": 2.0, "near_high": -0.5},
    # Earlier than fast_acceleration: seeks the first sustained M5/M15 push,
    # then requires independent trend confirmation below.
    "early_trend_continuation": {"ret_1m": -0.25, "ret_5m": 0.5, "ret_15m": 1.0, "volume": 2.0, "near_high": -0.5},
}


def passes(snapshot, rule):
    return (snapshot["return_1m_pct"] >= rule["ret_1m"] and
            snapshot["return_5m_pct"] >= rule["ret_5m"] and
            snapshot["return_15m_pct"] >= rule["ret_15m"] and
            (snapshot["volume_ratio_20"] or 0) >= rule["volume"] and
            snapshot["close_to_15m_high_pct"] >= rule["near_high"])


def first_touch_outcome(data, index, future_end, entry, target_pct, stop_pct):
    target, stop = entry * (1 + target_pct / 100), entry * (1 - stop_pct / 100)
    for i in range(index + 1, future_end):
        # Conservative: a candle touching both exits is treated as stop first.
        if data["lows"][i] <= stop:
            return "stop"
        if data["highs"][i] >= target:
            return "target"
    return "timeout"


def trend_confirmation(indicators):
    return (indicators.get("rsi_14", 0) >= 65 and indicators.get("ema9_ema21_gap_pct", 0) > 0 and
            indicators.get("macd_histogram", 0) > 0 and indicators.get("vwap20_distance_pct", 0) > 0 and
            indicators.get("adx_14", 0) >= 25 and indicators.get("plus_di", 0) > indicators.get("minus_di", 0))


async def main(args):
    tz = ZoneInfo(args.timezone)
    start_ts = int(datetime.fromisoformat(args.start_date).replace(tzinfo=tz).timestamp())
    end_ts = int(datetime.fromisoformat(args.end_date).replace(tzinfo=tz).timestamp())
    if start_ts >= end_ts:
        raise SystemExit("Başlangıç bitişten önce olmalıdır")
    await database.init_db()
    symbols = args.symbols or await database.get_market_symbols("5m")
    horizon = args.horizon_minutes * 60
    semaphore = asyncio.Semaphore(args.workers)

    async def audit(symbol):
        async with semaphore:
            rows = await database.get_market_candles(symbol, "1m", (start_ts - 30 * 60) * 1000, (end_ts + horizon) * 1000)
        data = as_series(rows)
        found = defaultdict(list)
        next_allowed = defaultdict(int)
        for ts in range(start_ts, end_ts + 1, 60):
            index = bisect.bisect_right(data["times"], ts) - 1
            future_end = bisect.bisect_right(data["times"], ts + horizon)
            if index < 20 or future_end <= index + 1:
                continue
            snapshot = features(data, index)
            if not snapshot:
                continue
            future_high = max(data["highs"][index + 1:future_end])
            future_low = min(data["lows"][index + 1:future_end])
            upside = (future_high / snapshot["price"] - 1) * 100 if snapshot["price"] else 0
            downside = (future_low / snapshot["price"] - 1) * 100 if snapshot["price"] else 0
            for name, rule in CANDIDATES.items():
                if ts < next_allowed[name] or not passes(snapshot, rule):
                    continue
                indicators = indicator_features(data, index) if name in {"trend_continuation_confirmed", "early_trend_continuation"} else None
                if name in {"trend_continuation_confirmed", "early_trend_continuation"} and not trend_confirmation(indicators):
                    continue
                if ts >= next_allowed[name]:
                    outcome_5_2 = first_touch_outcome(data, index, future_end, snapshot["price"], 5, 2)
                    outcome_10_3 = first_touch_outcome(data, index, future_end, snapshot["price"], 10, 3)
                    found[name].append({"symbol": symbol, "time": ts, "upside_pct": round(upside, 4),
                                        "downside_pct": round(downside, 4), "tp5_sl2": outcome_5_2,
                                        "tp10_sl3": outcome_10_3, "features": snapshot, "indicators": indicators})
                    next_allowed[name] = ts + args.cooldown_minutes * 60
        return found

    combined = defaultdict(list)
    for found in await asyncio.gather(*(audit(symbol) for symbol in symbols)):
        for name, rows in found.items():
            combined[name].extend(rows)
    summary = {}
    for name, rows in combined.items():
        count = len(rows)
        summary[name] = {
            "rule": CANDIDATES[name], "signals": count,
            "future_up_5pct": sum(row["upside_pct"] >= 5 for row in rows),
            "future_up_10pct": sum(row["upside_pct"] >= 10 for row in rows),
            "future_up_20pct": sum(row["upside_pct"] >= 20 for row in rows),
            "median_future_upside_pct": round(sorted([row["upside_pct"] for row in rows])[count // 2], 4) if count else None,
            "median_future_downside_pct": round(sorted([row["downside_pct"] for row in rows])[count // 2], 4) if count else None,
            "examples": sorted(rows, key=lambda row: row["upside_pct"], reverse=True)[:20],
        }
        for target in (5, 10, 20):
            summary[name][f"precision_up_{target}pct"] = round(summary[name][f"future_up_{target}pct"] / count * 100, 2) if count else 0.0
        for label in ("tp5_sl2", "tp10_sl3"):
            outcomes = {outcome: sum(row[label] == outcome for row in rows) for outcome in ("target", "stop", "timeout")}
            summary[name][label] = {**outcomes, **{key + "_pct": round(value / count * 100, 2) if count else 0.0 for key, value in outcomes.items()}}
    output = {"paper_only": True, "source": "historical_candles / Binance TR public M1",
              "window": {"start": args.start_date, "end": args.end_date, "timezone": args.timezone},
              "evaluation": {"future_horizon_minutes": args.horizon_minutes,
                             "warning": "Future upside/downside is evaluation-only, never a live condition."},
              "candidates": summary}
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] result=" + str(Path(args.output).resolve()))
    print("RESULT_JSON=" + json.dumps({"candidates": {name: {key: value for key, value in report.items() if key != "examples"} for name, report in summary.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--horizon-minutes", type=int, default=60)
    parser.add_argument("--cooldown-minutes", type=int, default=60)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--output", default="m1-momentum-candidate-audit.json")
    args = parser.parse_args()
    if args.horizon_minutes < 5 or args.cooldown_minutes < 1 or not 1 <= args.workers <= 64:
        parser.error("horizon/soğuma/worker değerleri geçersiz")
    asyncio.run(main(args))
