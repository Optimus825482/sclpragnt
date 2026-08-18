"""Research causal M1 price-structure and adaptive-indicator candidates.

This script never opens a position.  It evaluates completed-candle signals
against future labels with conservative stop-first intrabar accounting.
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


def atr(data, index, length=20):
    if index < length:
        return None
    h, l, c = data["highs"], data["lows"], data["closes"]
    return sum(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(index - length + 1, index + 1)) / length


def nw_lower(data, index, lookback=30, bandwidth=10, multiplier=2.0):
    if index < lookback:
        return None
    closes = data["closes"]
    values = closes[index - lookback + 1:index + 1]
    weights = [math.exp(-(lookback - 1 - i) ** 2 / (2 * bandwidth ** 2)) for i in range(lookback)]
    total = sum(weights)
    basis = sum(value * weight for value, weight in zip(values, weights)) / total
    mad = sum(abs(value - basis) * weight for value, weight in zip(values, weights)) / total
    return basis - multiplier * mad


def kama(data, index, length=10, fast=2, slow=30):
    if index < length + 1:
        return None, None
    closes = data["closes"]
    value = sum(closes[:length]) / length
    fast_sc, slow_sc = 2 / (fast + 1), 2 / (slow + 1)
    er = 0.0
    for i in range(length, index + 1):
        change = abs(closes[i] - closes[i - length])
        volatility = sum(abs(closes[j] - closes[j - 1]) for j in range(i - length + 1, i + 1))
        er = change / volatility if volatility else 0.0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        value += sc * (closes[i] - value)
    return value, er


def vfi(data, index, length=50):
    if index < length + 30:
        return None
    h, l, c, v = data["highs"], data["lows"], data["closes"], data["volumes"]
    typical = [(h[i] + l[i] + c[i]) / 3 for i in range(index - length - 30, index + 1)]
    returns = [math.log(typical[i] / typical[i - 1]) if typical[i - 1] else 0 for i in range(1, len(typical))]
    sigma = math.sqrt(sum(x * x for x in returns[-30:]) / 30)
    avg_volume = sum(v[index - length:index]) / length
    if not avg_volume or not sigma:
        return None
    flow = 0.0
    for offset in range(length):
        i = index - length + 1 + offset
        delta = math.log(((h[i] + l[i] + c[i]) / 3) / ((h[i - 1] + l[i - 1] + c[i - 1]) / 3)) if c[i - 1] else 0
        cutoff = 0.2 * sigma
        signed = min(v[i], avg_volume * 3) if delta > cutoff else -min(v[i], avg_volume * 3) if delta < -cutoff else 0
        flow += signed
    return flow / avg_volume


def first_touch(data, index, end, entry, tp, sl):
    for i in range(index + 1, end):
        if data["lows"][i] <= entry * (1 - sl / 100): return "stop"
        if data["highs"][i] >= entry * (1 + tp / 100): return "target"
    return "timeout"


async def main(args):
    tz = ZoneInfo(args.timezone)
    start = int(datetime.fromisoformat(args.start_date).replace(tzinfo=tz).timestamp())
    end = int(datetime.fromisoformat(args.end_date).replace(tzinfo=tz).timestamp())
    if start >= end:
        raise SystemExit("Başlangıç bitişten önce olmalıdır")
    await database.init_db()
    symbols = args.symbols or await database.get_market_symbols("5m")
    horizon, cooldown, semaphore = args.horizon_minutes * 60, args.cooldown_minutes * 60, asyncio.Semaphore(args.workers)

    async def inspect(symbol):
        async with semaphore:
            rows = await database.get_market_candles(symbol, "1m", (start - 2 * 3600) * 1000, (end + horizon) * 1000)
        data, found, next_ok = as_series(rows), defaultdict(list), defaultdict(int)
        o, h, l, c, v = (data[key] for key in ("opens", "highs", "lows", "closes", "volumes"))
        for ts in range(start, end + 1, args.sample_minutes * 60):
            i, future_end = bisect.bisect_right(data["times"], ts) - 1, bisect.bisect_right(data["times"], ts + horizon)
            if i < 90 or future_end <= i + 1 or not c[i]: continue
            current_atr = atr(data, i)
            if not current_atr or current_atr / c[i] * 100 < args.min_atr_pct: continue
            prior_low = min(l[i - 20:i])
            body = abs(c[i] - o[i]); lower_wick = min(o[i], c[i]) - l[i]
            sweep = l[i] < prior_low - current_atr * .10 and c[i] > prior_low and c[i] > o[i] and lower_wick >= max(body * 1.5, current_atr * .10)
            candidates = []
            if sweep:
                candidates.append("liquidity_sweep_reclaim")
                lower_now, lower_prev = nw_lower(data, i), nw_lower(data, i - 1)
                if lower_now is not None and lower_prev is not None and c[i - 1] < lower_prev and c[i] >= lower_now:
                    candidates.append("sweep_nw_reclaim")
            # Adaptive trend candidate: first efficient M5/M15 impulse, before
            # the much later high-momentum rules already rejected above.
            if c[i] > c[i - 5] * 1.005 and c[i] > c[i - 15] * 1.01:
                k, er = kama(data, i)
                if k is not None and c[i] > k and er >= .45:
                    candidates.append("kama_efficient_trend")
            if v[i] > 0 and c[i] > c[i - 5] * 1.002:
                current_vfi, prior_vfi = vfi(data, i), vfi(data, i - 1)
                if current_vfi is not None and prior_vfi is not None and current_vfi > 0 >= prior_vfi:
                    candidates.append("vfi_zero_cross")
            if not candidates: continue
            entry, upside, downside = c[i], (max(h[i + 1:future_end]) / c[i] - 1) * 100, (min(l[i + 1:future_end]) / c[i] - 1) * 100
            for name in candidates:
                if ts < next_ok[name]: continue
                found[name].append({"symbol": symbol, "time": ts, "future_upside_pct": round(upside, 4), "future_downside_pct": round(downside, 4),
                                    "tp5_sl2": first_touch(data, i, future_end, entry, 5, 2), "tp10_sl3": first_touch(data, i, future_end, entry, 10, 3)})
                next_ok[name] = ts + cooldown
        return found

    results, tasks = [], [asyncio.create_task(inspect(symbol)) for symbol in symbols]
    for number, task in enumerate(asyncio.as_completed(tasks), 1):
        results.append(await task)
        if number == 1 or number % 10 == 0 or number == len(symbols): print(f"[PROGRESS] symbols={number}/{len(symbols)}", flush=True)
    combined = defaultdict(list)
    for result in results:
        for name, rows in result.items(): combined[name].extend(rows)
    report = {}
    for name in ("liquidity_sweep_reclaim", "sweep_nw_reclaim", "kama_efficient_trend", "vfi_zero_cross"):
        rows, count = combined[name], len(combined[name])
        item = {"signals": count, "future_up_5pct": sum(row["future_upside_pct"] >= 5 for row in rows), "future_up_10pct": sum(row["future_upside_pct"] >= 10 for row in rows),
                "median_upside_pct": sorted([row["future_upside_pct"] for row in rows])[count // 2] if count else None,
                "median_downside_pct": sorted([row["future_downside_pct"] for row in rows])[count // 2] if count else None}
        for label in ("tp5_sl2", "tp10_sl3"):
            total = {key: sum(row[label] == key for row in rows) for key in ("target", "stop", "timeout")}
            item[label] = {**total, **{f"{key}_pct": round(value / count * 100, 2) if count else 0 for key, value in total.items()}}
        report[name] = item
    payload = {"paper_only": True, "source": "historical_candles / Binance TR public M1", "window": {"start": args.start_date, "end": args.end_date, "timezone": args.timezone},
               "evaluation": {"horizon_minutes": args.horizon_minutes, "same_candle_policy": "stop_first", "future_labels_only": True}, "candidates": report}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] result=" + str(Path(args.output).resolve()))
    print("RESULT_JSON=" + json.dumps({"candidates": report}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*"); parser.add_argument("--start-date", required=True); parser.add_argument("--end-date", required=True); parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--horizon-minutes", type=int, default=60); parser.add_argument("--sample-minutes", type=int, default=15); parser.add_argument("--cooldown-minutes", type=int, default=60)
    parser.add_argument("--min-atr-pct", type=float, default=.12); parser.add_argument("--workers", type=int, default=16); parser.add_argument("--output", default="m1-structure-candidate-audit.json")
    args = parser.parse_args()
    if args.horizon_minutes < 5 or args.sample_minutes < 1 or args.cooldown_minutes < 1 or not 1 <= args.workers <= 64: parser.error("araştırma parametreleri geçersiz")
    asyncio.run(main(args))
