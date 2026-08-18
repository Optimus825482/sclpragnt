"""Audit causal M1 squeeze-release candidates against future labels.

Candidates are based solely on completed M1 candles.  This is research-only:
future highs/lows determine labels, never entries or live paper positions.
"""
import argparse
import asyncio
import bisect
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from scripts.research_m1_spikes import as_series


def sma(values):
    return sum(values) / len(values) if values else None


def ema(values, period):
    if len(values) < period:
        return None
    value, alpha = sum(values[:period]) / period, 2 / (period + 1)
    for item in values[period:]:
        value = item * alpha + value * (1 - alpha)
    return value


def atr(values_h, values_l, values_c):
    if len(values_c) < 2:
        return None
    return sum(max(values_h[i] - values_l[i], abs(values_h[i] - values_c[i - 1]), abs(values_l[i] - values_c[i - 1]))
               for i in range(1, len(values_c))) / (len(values_c) - 1)


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)] if ordered else None


def squeeze_state(data, index):
    """LazyBear-style BB/KC squeeze and a causal, rising momentum estimate."""
    if index < 41:
        return None
    closes, highs, lows = data["closes"], data["highs"], data["lows"]
    window = closes[index - 19:index + 1]
    basis = sma(window)
    std = math.sqrt(sum((value - basis) ** 2 for value in window) / 20)
    atr20 = atr(highs[index - 20:index + 1], lows[index - 20:index + 1], closes[index - 20:index + 1])
    kc_mid = ema(closes[index - 39:index + 1], 20)
    if not basis or not atr20 or not kc_mid:
        return None
    squeeze_on = basis - 2 * std > kc_mid - 1.5 * atr20 and basis + 2 * std < kc_mid + 1.5 * atr20
    # TTM-inspired oscillator: close relative to the range/moving-average midpoint.
    momentum = closes[index] - ((max(highs[index - 19:index + 1]) + min(lows[index - 19:index + 1])) / 4 + basis / 2)
    prior_window = closes[index - 1 - 19:index]
    prior_basis = sma(prior_window)
    prior_momentum = closes[index - 1] - ((max(highs[index - 1 - 19:index]) + min(lows[index - 1 - 19:index])) / 4 + prior_basis / 2)
    range15 = (max(highs[index - 14:index + 1]) / min(lows[index - 14:index + 1]) - 1) * 100 if min(lows[index - 14:index + 1]) else 0
    return {"squeeze_on": squeeze_on, "momentum": momentum, "prior_momentum": prior_momentum,
            "atr_pct": atr20 / closes[index] * 100 if closes[index] else 0, "range15_pct": range15}


def first_touch(data, index, future_end, entry, target_pct, stop_pct):
    target, stop = entry * (1 + target_pct / 100), entry * (1 - stop_pct / 100)
    for i in range(index + 1, future_end):
        if data["lows"][i] <= stop:
            return "stop"
        if data["highs"][i] >= target:
            return "target"
    return "timeout"


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
            rows = await database.get_market_candles(symbol, "1m", (start - 25 * 3600) * 1000, (end + horizon) * 1000)
        data, found, next_ok = as_series(rows), defaultdict(list), defaultdict(int)
        for ts in range(start, end + 1, args.sample_minutes * 60):
            index = bisect.bisect_right(data["times"], ts) - 1
            future_end = bisect.bisect_right(data["times"], ts + horizon)
            if index < 1500 or future_end <= index + 1:
                continue
            current, previous = squeeze_state(data, index), squeeze_state(data, index - 1)
            if not current or not previous:
                continue
            release_positive = previous["squeeze_on"] and not current["squeeze_on"] and current["momentum"] > 0 and current["momentum"] > current["prior_momentum"]
            if not release_positive:
                continue
            entry = data["closes"][index]
            swing_high = max(data["highs"][index - 20:index])
            atr_history, range_history = [], []
            for i in range(index - 1440, index, 5):
                state = squeeze_state(data, i)
                if state:
                    atr_history.append(state["atr_pct"])
                    range_history.append(state["range15_pct"])
            atr_p80, range_p80 = percentile(atr_history, .80), percentile(range_history, .80)
            candidates = ["squeeze_release"]
            if entry > swing_high:
                candidates.append("squeeze_swing_breakout")
            if atr_p80 is not None and range_p80 is not None and current["atr_pct"] >= atr_p80 and current["range15_pct"] >= range_p80:
                candidates.append("squeeze_percentile_regime")
            upside = (max(data["highs"][index + 1:future_end]) / entry - 1) * 100
            downside = (min(data["lows"][index + 1:future_end]) / entry - 1) * 100
            for name in candidates:
                if ts < next_ok[name]:
                    continue
                found[name].append({"symbol": symbol, "time": ts, "future_upside_pct": round(upside, 4),
                                    "future_downside_pct": round(downside, 4), "tp5_sl2": first_touch(data, index, future_end, entry, 5, 2),
                                    "tp10_sl3": first_touch(data, index, future_end, entry, 10, 3),
                                    "atr_pct": round(current["atr_pct"], 4), "range15_pct": round(current["range15_pct"], 4),
                                    "atr_p80": round(atr_p80, 4) if atr_p80 else None, "range_p80": round(range_p80, 4) if range_p80 else None})
                next_ok[name] = ts + cooldown
        return found

    collected, tasks = [], [asyncio.create_task(inspect(symbol)) for symbol in symbols]
    for number, task in enumerate(asyncio.as_completed(tasks), 1):
        collected.append(await task)
        if number == 1 or number % 10 == 0 or number == len(symbols):
            print(f"[PROGRESS] symbols={number}/{len(symbols)}", flush=True)
    combined = defaultdict(list)
    for result in collected:
        for name, rows in result.items():
            combined[name].extend(rows)
    report = {}
    for name in ("squeeze_release", "squeeze_swing_breakout", "squeeze_percentile_regime"):
        rows, count = combined[name], len(combined[name])
        record = {"signals": count, "future_up_5pct": sum(row["future_upside_pct"] >= 5 for row in rows),
                  "future_up_10pct": sum(row["future_upside_pct"] >= 10 for row in rows),
                  "median_upside_pct": sorted([row["future_upside_pct"] for row in rows])[count // 2] if count else None,
                  "median_downside_pct": sorted([row["future_downside_pct"] for row in rows])[count // 2] if count else None,
                  "examples": sorted(rows, key=lambda row: row["future_upside_pct"], reverse=True)[:20]}
        for label in ("tp5_sl2", "tp10_sl3"):
            totals = {key: sum(row[label] == key for row in rows) for key in ("target", "stop", "timeout")}
            record[label] = {**totals, **{f"{key}_pct": round(value / count * 100, 2) if count else 0 for key, value in totals.items()}}
        report[name] = record
    payload = {"paper_only": True, "source": "historical_candles / Binance TR public M1",
               "window": {"start": args.start_date, "end": args.end_date, "timezone": args.timezone},
               "definitions": {"squeeze_release": "previous BB-inside-KC squeeze releases with rising positive TTM-style momentum",
                               "squeeze_swing_breakout": "squeeze release plus close above prior 20 M1 swing high",
                               "squeeze_percentile_regime": "squeeze release plus ATR and 15m range at/above own trailing 24h p80"},
               "evaluation": {"horizon_minutes": args.horizon_minutes, "same_candle_policy": "stop_first", "future_labels_only": True},
               "candidates": report}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] result=" + str(Path(args.output).resolve()))
    print("RESULT_JSON=" + json.dumps({"candidates": {name: {key: value for key, value in row.items() if key != "examples"} for name, row in report.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--horizon-minutes", type=int, default=60)
    parser.add_argument("--sample-minutes", type=int, default=5)
    parser.add_argument("--cooldown-minutes", type=int, default=60)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--output", default="m1-squeeze-candidate-audit.json")
    args = parser.parse_args()
    if args.horizon_minutes < 5 or args.sample_minutes < 1 or args.cooldown_minutes < 1 or not 1 <= args.workers <= 64:
        parser.error("araştırma parametreleri geçersiz")
    asyncio.run(main(args))
