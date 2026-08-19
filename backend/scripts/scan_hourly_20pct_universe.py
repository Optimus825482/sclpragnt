"""List all completed H1 candles with a >= threshold move across Binance TR TRY symbols.

This is a read-only market scan.  It deliberately keeps close-confirmed and
high-only (wick) events separate: an H1 candle can touch +20% and close far
below it, which is not the same as a confirmed hourly gain.
"""

import argparse
import asyncio
import csv
import json
import math
import time
from math import ceil
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.binance_tr_public import historical_klines, trading_symbols
from scripts.research_mtf_5of5_managed_replay import normalize


HOUR_MS = 60 * 60 * 1000


def display_time(timestamp_ms: int, timezone_name: str) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S %Z")


def completed_hour_rows(raw, start_ms: int, end_ms: int):
    return [row for row in normalize(raw) if row["time"] >= start_ms and row["close_time"] < end_ms]


def detect(symbol: str, rows, threshold_pct: float, timezone_name: str):
    confirmed, wick_only = [], []
    for row in rows:
        if not row["open"]:
            continue
        close_pct = (row["close"] / row["open"] - 1) * 100
        high_pct = (row["high"] / row["open"] - 1) * 100
        if high_pct < threshold_pct:
            continue
        event = {
            "symbol": symbol,
            "hour_start": display_time(row["time"], timezone_name),
            "hour_start_ms": row["time"],
            "hour_close": display_time(row["close_time"], timezone_name),
            "open": row["open"],
            "high": row["high"],
            "close": row["close"],
            "high_move_pct": round(high_pct, 4),
            "close_move_pct": round(close_pct, 4),
        }
        (confirmed if close_pct >= threshold_pct else wick_only).append(event)
    return confirmed, wick_only


async def fetch(symbol: str, end_ms: int, days: int, semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            return symbol, await historical_klines(symbol, "1h", days, end_ms), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    observed_at_ms = int(time.time() * 1000)
    if args.end:
        parsed = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise SystemExit("--end must include timezone, for example 2026-06-20T18:00:00+03:00")
        window_end_ms = int(parsed.timestamp() * 1000) // HOUR_MS * HOUR_MS
    else:
        window_end_ms = observed_at_ms // HOUR_MS * HOUR_MS
    window_start_ms = window_end_ms - args.hours * HOUR_MS
    fetch_days = max(2, ceil(args.hours / 24) + 1)
    symbols = await trading_symbols("TRY")
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, window_end_ms - 1, fetch_days, semaphore) for symbol in symbols))
    confirmed, wick_only, errors, candle_counts = [], [], {}, {}
    for symbol, raw, error in loaded:
        if error:
            errors[symbol] = error
            continue
        rows = completed_hour_rows(raw, window_start_ms, window_end_ms)
        candle_counts[symbol] = len(rows)
        close_events, wick_events = detect(symbol, rows, args.threshold_pct, args.timezone)
        confirmed.extend(close_events)
        wick_only.extend(wick_events)
    confirmed.sort(key=lambda item: (item["hour_start_ms"], item["symbol"]))
    wick_only.sort(key=lambda item: (item["hour_start_ms"], item["symbol"]))
    payload = {
        "read_only": True,
        "source": "Binance TR public API H1 OHLCV via configured public adapter",
        "observed_at": display_time(observed_at_ms, args.timezone),
        "universe": {"quote_asset": "TRY", "symbols_requested": len(symbols), "symbols_successful": len(candle_counts), "symbols_failed": len(errors)},
        "window": {"start": display_time(window_start_ms, args.timezone), "end_exclusive": display_time(window_end_ms, args.timezone), "completed_hours": args.hours, "timezone": args.timezone, "fetch_days": fetch_days},
        "definition": {"threshold_pct": args.threshold_pct, "confirmed": "H1 close / H1 open - 1 >= threshold", "wick_only": "H1 high / H1 open - 1 >= threshold but close did not confirm", "start_time": "opening time of the H1 candle that met the threshold; intrahour onset cannot be determined from H1 data"},
        "candle_counts": candle_counts,
        "errors": errors,
        "confirmed_events": confirmed,
        "wick_only_events": wick_only,
    }
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["symbol", "hour_start", "hour_close", "open", "high", "close", "high_move_pct", "close_move_pct"]
    with output.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["event_type", *fields])
        writer.writeheader()
        for kind, items in (("confirmed", confirmed), ("wick_only", wick_only)):
            for item in items:
                writer.writerow({"event_type": kind, **{name: item[name] for name in fields}})
    print(json.dumps({"symbols_requested": len(symbols), "symbols_successful": len(candle_counts), "symbols_failed": len(errors), "confirmed_events": len(confirmed), "wick_only_events": len(wick_only), "output": str(output.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--threshold-pct", type=float, default=20.0)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--end", help="Exclusive ISO-8601 window end with timezone; defaults to current completed hour")
    parser.add_argument("--output", default="hourly-20pct-universe-24h.json")
    args = parser.parse_args()
    if args.hours < 1 or args.threshold_pct <= 0 or args.concurrency < 1:
        parser.error("hours, threshold-pct and concurrency must be positive")
    asyncio.run(main(args))
