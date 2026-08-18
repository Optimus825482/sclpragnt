"""Detect >=5% forward M1 spikes within 15 minutes across the configured symbols."""

import argparse
import asyncio
import bisect
import csv
import json
import math
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.binance_tr_public import historical_klines, trading_symbols


def normalize(rows):
    result = []
    seen = set()
    for row in rows or []:
        if len(row) < 7:
            continue
        values = [float(row[index]) for index in range(1, 6)]
        close_time = int(row[6])
        if close_time in seen or not all(math.isfinite(value) for value in values):
            continue
        seen.add(close_time)
        result.append({"time": close_time, "open": values[0], "high": values[1], "low": values[2],
                       "close": values[3], "volume": values[4]})
    return sorted(result, key=lambda item: item["time"])


def format_time(timestamp_ms, timezone_name):
    return datetime.fromtimestamp(timestamp_ms / 1000, ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S")


def detect(symbol, rows, start_ms, end_ms, threshold_pct, horizon_minutes, cooldown_minutes, timezone_name):
    times = [row["time"] for row in rows]
    horizon_ms = horizon_minutes * 60_000
    cooldown_ms = cooldown_minutes * 60_000
    last_allowed = 0
    events = []
    final_decision_ms = end_ms - horizon_ms
    start_index = bisect.bisect_left(times, start_ms)
    end_index = bisect.bisect_right(times, final_decision_ms)
    for index in range(start_index, min(end_index, len(rows))):
        decision_time = times[index]
        if decision_time < last_allowed:
            continue
        future_end = bisect.bisect_right(times, decision_time + horizon_ms)
        if future_end <= index + 1:
            continue
        entry_price = rows[index]["close"]
        peak_price = max(row["high"] for row in rows[index + 1:future_end])
        upside_pct = (peak_price / entry_price - 1) * 100 if entry_price else 0
        if upside_pct < threshold_pct:
            continue
        peak_index = next(position for position in range(index + 1, future_end) if rows[position]["high"] == peak_price)
        crossing_index = next((position for position in range(index + 1, peak_index + 1)
                               if (rows[position]["high"] / entry_price - 1) * 100 >= threshold_pct), peak_index)
        onset_start = max(start_index, crossing_index - horizon_minutes)
        onset_index = min(range(onset_start, crossing_index + 1), key=lambda position: rows[position]["low"])
        events.append({
            "symbol": symbol,
            "entry_time": format_time(decision_time, timezone_name),
            "entry_time_ms": decision_time,
            "onset_time": format_time(rows[onset_index]["time"], timezone_name),
            "onset_time_ms": rows[onset_index]["time"],
            "peak_time": format_time(rows[peak_index]["time"], timezone_name),
            "peak_time_ms": rows[peak_index]["time"],
            "entry_price": entry_price,
            "peak_price": peak_price,
            "spike_pct": round(upside_pct, 5),
            "entry_to_peak_minutes": round((rows[peak_index]["time"] - decision_time) / 60_000, 2),
            "onset_to_peak_minutes": round((rows[peak_index]["time"] - rows[onset_index]["time"]) / 60_000, 2),
        })
        last_allowed = rows[peak_index]["time"] + cooldown_ms
    return events


def max_forward_move(rows, start_ms, end_ms, horizon_minutes, timezone_name):
    times = [row["time"] for row in rows]
    horizon_ms = horizon_minutes * 60_000
    start_index = bisect.bisect_left(times, start_ms)
    end_index = bisect.bisect_right(times, end_ms - horizon_ms)
    best = None
    for index in range(start_index, min(end_index, len(rows))):
        future_end = bisect.bisect_right(times, times[index] + horizon_ms)
        if future_end <= index + 1 or not rows[index]["close"]:
            continue
        peak_index = max(range(index + 1, future_end), key=lambda position: rows[position]["high"])
        move_pct = (rows[peak_index]["high"] / rows[index]["close"] - 1) * 100
        if best is None or move_pct > best["max_forward_pct"]:
            best = {"max_forward_pct": round(move_pct, 5), "entry_time": format_time(rows[index]["time"], timezone_name),
                    "peak_time": format_time(rows[peak_index]["time"], timezone_name)}
    return best


async def fetch_symbol(symbol, days, end_ms, semaphore):
    async with semaphore:
        try:
            raw = await historical_klines(symbol, "1m", days, end_ms)
            rows = normalize(raw)
            print(f"[DATA] {symbol} candles={len(rows)}", flush=True)
            return symbol, rows, None
        except Exception as exc:
            print(f"[DATA-ERROR] {symbol} {type(exc).__name__}: {exc}", flush=True)
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    timezone_name = args.timezone
    end_dt = datetime.now(ZoneInfo(timezone_name))
    end_ms = int(end_dt.timestamp() * 1000)
    start_ms = end_ms - args.hours * 3_600_000
    symbols = [symbol.upper() for symbol in (args.symbols or await trading_symbols("TRY"))]
    print(f"[START] symbols={len(symbols)} window={format_time(start_ms, timezone_name)}..{format_time(end_ms, timezone_name)}", flush=True)
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch_symbol(symbol, args.fetch_days, end_ms, semaphore) for symbol in symbols))
    all_events, candle_counts, errors, maxima = [], {}, {}, {}
    for symbol, rows, error in loaded:
        candle_counts[symbol] = len(rows)
        if error:
            errors[symbol] = error
            continue
        maxima[symbol] = max_forward_move(rows, start_ms, end_ms, args.horizon_minutes, timezone_name)
        all_events.extend(detect(symbol, rows, start_ms, end_ms, args.threshold_pct, args.horizon_minutes, args.cooldown_minutes, timezone_name))
    all_events.sort(key=lambda event: (event["entry_time_ms"], event["symbol"]))
    output = {"paper_only": True, "source": "Binance TR public API historical OHLCV", "interval": "1m",
              "symbols_requested": symbols, "window": {"start": format_time(start_ms, timezone_name), "end": format_time(end_ms, timezone_name), "hours": args.hours, "timezone": timezone_name},
              "label": {"threshold_pct": args.threshold_pct, "horizon_minutes": args.horizon_minutes, "cooldown_minutes": args.cooldown_minutes, "entry_time_definition": "M1 candle close used as forward-label decision proxy", "onset_definition": "lowest low in the preceding horizon window before threshold crossing"},
              "candle_counts": candle_counts, "errors": errors, "max_forward_move_by_symbol": maxima, "event_count": len(all_events), "events": all_events,
              "limitations": ["Events are forward labels for research, not executable signals.", "Historical spread, orderbook, liquidity and slippage are unavailable.", "The last 15 minutes are excluded from candidate decisions because the full forward horizon is required."]}
    output_path = Path(args.output)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = output_path.with_suffix(".csv")
    fields = ["symbol", "entry_time", "onset_time", "peak_time", "entry_price", "peak_price", "spike_pct", "entry_to_peak_minutes", "onset_to_peak_minutes"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: event[field] for field in fields} for event in all_events)
    print(f"[COMPLETE] events={len(all_events)} json={output_path.resolve()} csv={csv_path.resolve()}", flush=True)
    for event in all_events:
        print(f"[SPIKE] {event['symbol']} entry={event['entry_time']} onset={event['onset_time']} peak={event['peak_time']} +{event['spike_pct']:.2f}%", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", help="Belirtilirse bu evreni kullanır; verilmezse Binance TR'deki tüm TRY/TRADING sembollerini tarar")
    parser.add_argument("--hours", type=int, default=72)
    parser.add_argument("--fetch-days", type=int, default=3)
    parser.add_argument("--threshold-pct", type=float, default=5.0)
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--cooldown-minutes", type=int, default=15)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--output", default="m1-spikes-all-symbols-72h.json")
    args = parser.parse_args()
    if args.hours < 1 or args.threshold_pct <= 0 or args.horizon_minutes < 1 or args.cooldown_minutes < 0:
        parser.error("geçersiz araştırma parametresi")
    asyncio.run(main(args))
