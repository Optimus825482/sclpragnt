"""Evaluate causal M1 dip-reversal and trend-continuation candidates.

Research only.  The candidate decision uses closed M1 candles at timestamp T;
the following 60 minutes are evaluation labels and never a signal input.
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


def first_touch(data, index, end, entry, tp, sl):
    target, stop = entry * (1 + tp / 100), entry * (1 - sl / 100)
    for i in range(index + 1, end):
        # Conservative within-candle accounting.
        if data["lows"][i] <= stop:
            return "stop"
        if data["highs"][i] >= target:
            return "target"
    return "timeout"


def active(snapshot, indicators, args):
    return ((snapshot.get("range_15m_pct") or 0) >= args.min_range_pct and
            (indicators.get("atr_14_pct") or 0) >= args.min_atr_pct)


def dip_reversal(snapshot, indicators):
    # Selling was present, but the latest minute is no longer making a new low.
    return (snapshot["return_15m_pct"] <= -1.0 and snapshot["return_5m_pct"] <= -0.20 and
            snapshot["return_1m_pct"] >= -0.25 and (indicators.get("rsi_14") or 100) <= 42 and
            (indicators.get("vwap20_distance_pct") or 0) <= 0 and
            (indicators.get("minus_di") or 0) > (indicators.get("plus_di") or 0))


def trend_continuation(snapshot, indicators):
    return (snapshot["return_5m_pct"] >= 0.5 and snapshot["return_15m_pct"] >= 1.0 and
            snapshot["close_to_15m_high_pct"] >= -0.5 and (indicators.get("rsi_14") or 0) >= 52 and
            (indicators.get("ema9_ema21_gap_pct") or 0) > 0 and
            (indicators.get("macd_histogram") or 0) > 0 and
            (indicators.get("vwap20_distance_pct") or 0) > 0 and
            (indicators.get("plus_di") or 0) > (indicators.get("minus_di") or 0))


def strict_dip_reversal(snapshot, indicators):
    # Deep selloff, then a closed positive M1 reversal.  This is intentionally
    # selective: it tests whether the rare violent reversals are tradable.
    return (snapshot["return_15m_pct"] <= -3.0 and snapshot["return_5m_pct"] <= -1.0 and
            snapshot["return_1m_pct"] >= 0.10 and (indicators.get("rsi_14") or 100) <= 30 and
            (indicators.get("vwap20_distance_pct") or 0) <= -0.25)


def strict_trend_continuation(snapshot, indicators):
    plus_di, minus_di = indicators.get("plus_di") or 0, indicators.get("minus_di") or 0
    return (snapshot["return_5m_pct"] >= 1.5 and snapshot["return_15m_pct"] >= 3.0 and
            snapshot["close_to_15m_high_pct"] >= -0.5 and (indicators.get("adx_14") or 0) >= 45 and
            plus_di - minus_di >= 15 and (indicators.get("ema9_ema21_gap_pct") or 0) > 0 and
            (indicators.get("macd_histogram") or 0) > 0 and (indicators.get("vwap20_distance_pct") or 0) > 0 and
            (indicators.get("bb20_bandwidth_pct") or 0) >= 2.0)


CANDIDATES = {
    "dip_reversal": dip_reversal,
    "trend_continuation": trend_continuation,
    "strict_dip_reversal": strict_dip_reversal,
    "strict_trend_continuation": strict_trend_continuation,
}


def raw_candidate_names(snapshot):
    """Cheap prefilter so we do not calculate ADX/MACD for every active bar."""
    names = []
    if (snapshot["return_15m_pct"] <= -1.0 and snapshot["return_5m_pct"] <= -0.20 and
            snapshot["return_1m_pct"] >= -0.25):
        names.append("dip_reversal")
    if (snapshot["return_15m_pct"] <= -3.0 and snapshot["return_5m_pct"] <= -1.0 and
            snapshot["return_1m_pct"] >= 0.10):
        names.append("strict_dip_reversal")
    if (snapshot["return_5m_pct"] >= 0.5 and snapshot["return_15m_pct"] >= 1.0 and
            snapshot["close_to_15m_high_pct"] >= -0.5):
        names.append("trend_continuation")
    if (snapshot["return_5m_pct"] >= 1.5 and snapshot["return_15m_pct"] >= 3.0 and
            snapshot["close_to_15m_high_pct"] >= -0.5):
        names.append("strict_trend_continuation")
    return names


async def main(args):
    tz = ZoneInfo(args.timezone)
    start = int(datetime.fromisoformat(args.start_date).replace(tzinfo=tz).timestamp())
    end = int(datetime.fromisoformat(args.end_date).replace(tzinfo=tz).timestamp())
    if start >= end:
        raise SystemExit("Başlangıç bitişten önce olmalıdır")
    await database.init_db()
    symbols = args.symbols or await database.get_market_symbols("5m")
    horizon, cooldown = args.horizon_minutes * 60, args.cooldown_minutes * 60
    semaphore = asyncio.Semaphore(args.workers)

    async def inspect(symbol):
        async with semaphore:
            rows = await database.get_market_candles(symbol, "1m", (start - 60 * 60) * 1000, (end + horizon) * 1000)
        data, found, next_ok = as_series(rows), defaultdict(list), defaultdict(int)
        for ts in range(start, end + 1, args.sample_minutes * 60):
            index = bisect.bisect_right(data["times"], ts) - 1
            future_end = bisect.bisect_right(data["times"], ts + horizon)
            if index < 60 or future_end <= index + 1:
                continue
            snapshot = features(data, index)
            if not snapshot:
                continue
            raw_names = raw_candidate_names(snapshot)
            if not raw_names:
                continue
            indicators = indicator_features(data, index)
            if not indicators or not active(snapshot, indicators, args):
                continue
            for name in raw_names:
                if ts < next_ok[name] or not CANDIDATES[name](snapshot, indicators):
                    continue
                entry = snapshot["price"]
                high = max(data["highs"][index + 1:future_end])
                low = min(data["lows"][index + 1:future_end])
                found[name].append({"symbol": symbol, "time": ts, "entry": entry,
                                    "future_upside_pct": round((high / entry - 1) * 100, 4),
                                    "future_downside_pct": round((low / entry - 1) * 100, 4),
                                    "tp5_sl2": first_touch(data, index, future_end, entry, 5, 2),
                                    "tp10_sl3": first_touch(data, index, future_end, entry, 10, 3),
                                    "features": snapshot, "indicators": indicators})
                next_ok[name] = ts + cooldown
        return found

    results = []
    tasks = [asyncio.create_task(inspect(symbol)) for symbol in symbols]
    for number, task in enumerate(asyncio.as_completed(tasks), 1):
        results.append(await task)
        if number == 1 or number % 10 == 0 or number == len(symbols):
            print(f"[PROGRESS] symbols={number}/{len(symbols)}", flush=True)
    combined = defaultdict(list)
    for result in results:
        for name, rows in result.items():
            combined[name].extend(rows)
    report = {}
    for name in CANDIDATES:
        rows = combined[name]
        count = len(rows)
        outcomes = {}
        for outcome_name in ("tp5_sl2", "tp10_sl3"):
            tally = {key: sum(row[outcome_name] == key for row in rows) for key in ("target", "stop", "timeout")}
            outcomes[outcome_name] = {**tally, **{f"{key}_pct": round(value / count * 100, 2) if count else 0 for key, value in tally.items()}}
        report[name] = {"signals": count,
                        "future_up_5pct": sum(row["future_upside_pct"] >= 5 for row in rows),
                        "future_up_10pct": sum(row["future_upside_pct"] >= 10 for row in rows),
                        "median_upside_pct": sorted([row["future_upside_pct"] for row in rows])[count // 2] if count else None,
                        "median_downside_pct": sorted([row["future_downside_pct"] for row in rows])[count // 2] if count else None,
                        **outcomes, "examples": sorted(rows, key=lambda row: row["future_upside_pct"], reverse=True)[:20]}
    payload = {"paper_only": True, "source": "historical_candles / Binance TR public M1",
               "window": {"start": args.start_date, "end": args.end_date, "timezone": args.timezone},
               "activity_gate": {"min_range_15m_pct": args.min_range_pct, "min_atr_14_pct": args.min_atr_pct},
               "evaluation": {"horizon_minutes": args.horizon_minutes, "future_labels_only": True,
                              "same_candle_policy": "stop_first"}, "candidates": report}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] result=" + str(Path(args.output).resolve()))
    print("RESULT_JSON=" + json.dumps({"activity_gate": payload["activity_gate"], "candidates":
          {name: {key: value for key, value in result.items() if key != "examples"} for name, result in report.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--horizon-minutes", type=int, default=60)
    parser.add_argument("--sample-minutes", type=int, default=5)
    parser.add_argument("--cooldown-minutes", type=int, default=60)
    parser.add_argument("--min-range-pct", type=float, default=0.05)
    parser.add_argument("--min-atr-pct", type=float, default=0.12)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--output", default="m1-regime-candidate-audit.json")
    args = parser.parse_args()
    if args.horizon_minutes < 5 or args.sample_minutes < 1 or args.cooldown_minutes < 1 or not 1 <= args.workers <= 64:
        parser.error("araştırma parametreleri geçersiz")
    asyncio.run(main(args))
