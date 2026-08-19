"""Create comparable causal M5 triplets around hourly +20% moves."""

import argparse
import asyncio
import csv
import json
from pathlib import Path

from app.binance_tr_public import historical_klines
from scripts.capture_hourly_spike_mtf_snapshots import local_time, normalize, snapshot_at


M5_MS = 5 * 60_000
LABELS = (("two_m5_before", 2), ("previous_m5", 1), ("pump_start", 0))
CSV_METRICS = (
    "last_closed_price", "trend_alignment", "price_vs_ema9_pct", "price_vs_vwap_pct", "rsi_14", "macd_histogram",
    "mfi_14", "stochastic_k", "stochastic_d", "adx_14", "plus_di", "minus_di", "atr_pct", "bb_position",
    "bb_width_pct", "volume_ratio_20", "candlestick_patterns", "price_action",
)


async def fetch(symbol, end_ms, semaphore):
    async with semaphore:
        try:
            return symbol, normalize(await historical_klines(symbol, "5m", 5, end_ms)), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


def m5_row(label, offset, snapshot):
    full = snapshot.get("snapshot", {})
    metrics = snapshot.get("key_metrics", {})
    extras = {
        "cmo_9": full.get("momentum", {}).get("cmo_9"),
        "cci_20": full.get("oscillators", {}).get("values", {}).get("cci_20"),
        "williams_r": full.get("oscillators", {}).get("values", {}).get("williams_r"),
        "ema_9": full.get("trend", {}).get("ema_9"), "ema_21": full.get("trend", {}).get("ema_21"), "ema_50": full.get("trend", {}).get("ema_50"),
        "sma_20": full.get("moving_averages", {}).get("sma_20"), "sma_50": full.get("moving_averages", {}).get("sma_50"),
        "vwap_20": full.get("volume", {}).get("vwap"),
        "macd_line": full.get("momentum", {}).get("macd", {}).get("line"), "macd_signal": full.get("momentum", {}).get("macd", {}).get("signal"),
        "last_closed_candle": snapshot.get("last_closed_candle"), "forming_candle_open": snapshot.get("forming_candle_open"),
        "forming_candle_open_gap_pct": snapshot.get("forming_candle_open_gap_pct"),
    }
    return {"label": label, "m5_offset": offset, "observation_time": snapshot.get("observation_time"), "metrics": metrics, "extras": extras, "full_snapshot": full}


async def main(args):
    source = json.loads(Path(args.events).read_text(encoding="utf-8"))
    events = list(source.get("confirmed_events", []))
    if args.include_wick_only:
        events.extend(source.get("wick_only_events", []))
    if not events:
        raise SystemExit("No hourly events found")
    symbols = sorted({event["symbol"] for event in events})
    end_ms = max(int(event["hour_start_ms"]) for event in events) + 1
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, end_ms, semaphore) for symbol in symbols))
    data = {symbol: rows for symbol, rows, error in loaded if not error}
    errors = {symbol: error for symbol, rows, error in loaded if error}
    output_events, csv_rows = [], []
    for event in events:
        category = "confirmed_close_20pct" if float(event["close_move_pct"]) >= 20 else "wick_only_20pct"
        start_ms = int(event["hour_start_ms"])
        triplet = {}
        for label, offset in LABELS:
            snapshot = snapshot_at(event["symbol"], "5m", data.get(event["symbol"], []), start_ms - offset * M5_MS, args.timezone)
            triplet[label] = m5_row(label, offset, snapshot)
        output_events.append({"category": category, "event": event, "m5_triplet": triplet})
        base = {"category": category, "symbol": event["symbol"], "hour_start": event["hour_start"], "close_move_pct": event["close_move_pct"], "high_move_pct": event["high_move_pct"]}
        for label, entry in triplet.items():
            row = {**base, "snapshot_label": label, "m5_offset": entry["m5_offset"], "observation_time": entry["observation_time"]}
            for key in CSV_METRICS:
                row[key] = entry["metrics"].get(key)
            row.update(entry["extras"])
            csv_rows.append(row)
    payload = {
        "research_only": True,
        "source": "Binance TR public historical M5 OHLCV via configured public adapter",
        "event_source": str(Path(args.events)),
        "definition": {"pump_start": "H1 +20% event opening boundary; indicators use only completed M5 candles before it.", "previous_m5": "same calculation at pump_start - 5 minutes.", "two_m5_before": "same calculation at pump_start - 10 minutes.", "control_group": "wick_only_20pct reached +20% intrahour but did not close H1 >=20%."},
        "errors": errors, "events": output_events,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(csv_rows[0]) if csv_rows else []
    with Path(args.output).with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(csv_rows)
    print(json.dumps({"events": len(output_events), "rows": len(csv_rows), "errors": len(errors), "output": str(Path(args.output).resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True); parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--include-wick-only", action="store_true"); parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", default="hourly-20pct-m5-triplets.json")
    args = parser.parse_args()
    asyncio.run(main(args))
