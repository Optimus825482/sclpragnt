"""Capture M15/M30 causal context triplets for hourly +20% moves."""

import argparse
import asyncio
import csv
import json
from pathlib import Path

from app.binance_tr_public import historical_klines
from scripts.analyze_hourly_spike_m5_triplets import CSV_METRICS, m5_row
from scripts.capture_hourly_spike_mtf_snapshots import normalize, snapshot_at


TIMEFRAMES = {"15m": (15 * 60_000, 7), "30m": (30 * 60_000, 9)}
LABELS = (("two_tf_before", 2), ("previous_tf", 1), ("pump_start", 0))


async def fetch(symbol, timeframe, end_ms, days, semaphore):
    async with semaphore:
        try:
            return symbol, normalize(await historical_klines(symbol, timeframe, days, end_ms)), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    source = json.loads(Path(args.events).read_text(encoding="utf-8"))
    events = list(source.get("confirmed_events", []))
    if args.include_wick_only:
        events.extend(source.get("wick_only_events", []))
    if not events:
        raise SystemExit("No hourly events found")
    timeframe = args.timeframe
    duration_ms, days = TIMEFRAMES[timeframe]
    end_ms = max(int(event["hour_start_ms"]) for event in events) + 1
    semaphore = asyncio.Semaphore(args.concurrency)
    symbols = sorted({event["symbol"] for event in events})
    loaded = await asyncio.gather(*(fetch(symbol, timeframe, end_ms, days, semaphore) for symbol in symbols))
    data = {symbol: rows for symbol, rows, error in loaded if not error}
    errors = {symbol: error for symbol, rows, error in loaded if error}
    output_events, csv_rows = [], []
    for event in events:
        category = "confirmed_close_20pct" if float(event["close_move_pct"]) >= 20 else "wick_only_20pct"
        triplet = {}
        for label, offset in LABELS:
            point = int(event["hour_start_ms"]) - offset * duration_ms
            raw = snapshot_at(event["symbol"], timeframe, data.get(event["symbol"], []), point, args.timezone)
            entry = m5_row(label, offset, raw)
            entry["tf_offset"] = offset
            triplet[label] = entry
        output_events.append({"category": category, "event": event, f"{timeframe}_triplet": triplet})
        base = {"category": category, "symbol": event["symbol"], "hour_start": event["hour_start"], "close_move_pct": event["close_move_pct"], "high_move_pct": event["high_move_pct"]}
        for label, entry in triplet.items():
            row = {**base, "snapshot_label": label, "tf_offset": entry["tf_offset"], "observation_time": entry["observation_time"]}
            for key in CSV_METRICS:
                row[key] = entry["metrics"].get(key)
            row.update(entry["extras"]); csv_rows.append(row)
    payload = {"research_only": True, "source": f"Binance TR public historical {timeframe} OHLCV via configured public adapter", "event_source": str(Path(args.events)),
               "definition": {"pump_start": "H1 +20% event boundary; indicators use only closed context candles.", "previous_tf": f"pump_start - one {timeframe}.", "two_tf_before": f"pump_start - two {timeframe}.", "control_group": "wick-only +20% intrahour events."},
               "timeframe": timeframe, "errors": errors, "events": output_events}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with Path(args.output).with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]) if csv_rows else []); writer.writeheader(); writer.writerows(csv_rows)
    print(json.dumps({"timeframe": timeframe, "events": len(output_events), "rows": len(csv_rows), "errors": len(errors), "output": str(Path(args.output).resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--events", required=True); parser.add_argument("--timeframe", choices=TIMEFRAMES, required=True)
    parser.add_argument("--timezone", default="Europe/Istanbul"); parser.add_argument("--include-wick-only", action="store_true"); parser.add_argument("--concurrency", type=int, default=8); parser.add_argument("--output", required=True)
    args = parser.parse_args(); asyncio.run(main(args))
