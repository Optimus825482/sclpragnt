"""Capture causal, detailed MTF snapshots at confirmed H1 +20% candle starts.

For every event and timeframe, the ``at_start`` snapshot only receives candles
that had already closed before the event H1 opened. ``previous_tf_start`` is
the equivalent snapshot one native timeframe earlier.  No candle that starts
at or after either observation timestamp is used by an indicator.
"""

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.binance_tr_public import historical_klines
from app.technical_analysis import calculate_snapshot
from scripts.research_mtf_5of5_managed_replay import normalize


TIMEFRAMES = {"1m": 60_000, "5m": 5 * 60_000, "15m": 15 * 60_000, "30m": 30 * 60_000, "1h": 60 * 60_000}
FETCH_DAYS = {"1m": 4, "5m": 5, "15m": 7, "30m": 9, "1h": 13}


def local_time(timestamp_ms: int, timezone_name: str) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M:%S %Z")


def closed_before(rows, timestamp_ms: int):
    return [row for row in rows if row["close_time"] < timestamp_ms]


def kline_payload(rows):
    if not rows:
        return None
    return {
        "opens": [row["open"] for row in rows], "highs": [row["high"] for row in rows], "lows": [row["low"] for row in rows],
        "closes": [row["close"] for row in rows], "volumes": [row["volume"] for row in rows],
        "timestamps": [row["close_time"] for row in rows], "last_closed_at_ms": rows[-1]["close_time"],
    }


def value_at(snapshot, *path):
    current = snapshot
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def compact(snapshot):
    price = snapshot.get("price") if snapshot else None
    ema9 = value_at(snapshot, "trend", "ema_9")
    vwap = value_at(snapshot, "volume", "vwap")
    return {
        "last_closed_price": price,
        "trend_alignment": value_at(snapshot, "trend", "alignment"),
        "price_vs_ema9_pct": ((price / ema9 - 1) * 100) if price and ema9 else None,
        "price_vs_vwap_pct": ((price / vwap - 1) * 100) if price and vwap else None,
        "rsi_14": value_at(snapshot, "momentum", "rsi_14"),
        "macd_histogram": value_at(snapshot, "momentum", "macd", "histogram"),
        "mfi_14": value_at(snapshot, "momentum", "mfi_14"),
        "stochastic_k": value_at(snapshot, "momentum", "stochastic", "k"),
        "stochastic_d": value_at(snapshot, "momentum", "stochastic", "d"),
        "adx_14": value_at(snapshot, "trend", "adx", "adx"),
        "plus_di": value_at(snapshot, "trend", "adx", "plus_di"),
        "minus_di": value_at(snapshot, "trend", "adx", "minus_di"),
        "atr_pct": value_at(snapshot, "volatility", "atr_pct"),
        "bb_position": value_at(snapshot, "channels", "bollinger", "position"),
        "bb_width_pct": value_at(snapshot, "channels", "bollinger", "width_pct"),
        "volume_ratio_20": value_at(snapshot, "volume", "volume_ratio_20"),
        "candlestick_patterns": snapshot.get("candlestick_patterns") if snapshot else None,
        "price_action": value_at(snapshot, "price_action", "setup"),
    }


def number_delta(current, previous):
    return current - previous if isinstance(current, (int, float)) and isinstance(previous, (int, float)) else None


def snapshot_at(symbol: str, timeframe: str, rows, observation_ms: int, timezone_name: str):
    history = closed_before(rows, observation_ms)
    target = next((row for row in rows if row["time"] == observation_ms), None)
    if not history:
        return {"observation_time": local_time(observation_ms, timezone_name), "error": "no_closed_history"}
    snapshot = calculate_snapshot(symbol, history[-1]["close"], {timeframe: kline_payload(history)}, primary_timeframe=timeframe)
    return {
        "observation_time": local_time(observation_ms, timezone_name),
        "observation_time_ms": observation_ms,
        "last_closed_candle": history[-1],
        "forming_candle_open": target["open"] if target else None,
        "forming_candle_open_gap_pct": ((target["open"] / history[-1]["close"] - 1) * 100) if target and history[-1]["close"] else None,
        "snapshot": snapshot,
        "key_metrics": compact(snapshot),
    }


async def fetch(symbol: str, timeframe: str, event_end_ms: int, semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            raw = await historical_klines(symbol, timeframe, FETCH_DAYS[timeframe], event_end_ms)
            return symbol, timeframe, normalize(raw), None
        except Exception as exc:
            return symbol, timeframe, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    source = json.loads(Path(args.events).read_text(encoding="utf-8"))
    events = list(source.get("confirmed_events", []))
    if args.include_wick_only:
        events.extend(source.get("wick_only_events", []))
    if not events:
        raise SystemExit("Input has no confirmed hourly events")
    symbols = sorted({event["symbol"] for event in events})
    event_end_ms = max(event["hour_start_ms"] for event in events) + 1
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, timeframe, event_end_ms, semaphore) for symbol in symbols for timeframe in TIMEFRAMES))
    series, errors = {}, {}
    for symbol, timeframe, rows, error in loaded:
        if error:
            errors[f"{symbol}:{timeframe}"] = error
        else:
            series[(symbol, timeframe)] = rows
    result_events = []
    for event in events:
        start_ms = int(event["hour_start_ms"])
        by_timeframe = {}
        for timeframe, duration_ms in TIMEFRAMES.items():
            rows = series.get((event["symbol"], timeframe), [])
            at_start = snapshot_at(event["symbol"], timeframe, rows, start_ms, args.timezone)
            previous = snapshot_at(event["symbol"], timeframe, rows, start_ms - duration_ms, args.timezone)
            current_metrics, prior_metrics = at_start.get("key_metrics", {}), previous.get("key_metrics", {})
            deltas = {key: number_delta(current_metrics.get(key), prior_metrics.get(key)) for key in current_metrics}
            by_timeframe[timeframe] = {"at_start": at_start, "previous_tf_start": previous, "key_metric_deltas": deltas}
        result_events.append({"event": event, "timeframes": by_timeframe})
    payload = {
        "research_only": True,
        "source": "Binance TR public historical OHLCV via configured public adapter",
        "event_source": str(Path(args.events)),
        "definition": {
            "events": "Confirmed events have H1 close/open gain >=20%; optional wick-only events hit +20% intrahour without close confirmation.",
            "at_start": "Indicators use only candles closed strictly before the H1 pump candle began.",
            "previous_tf_start": "Indicators use only candles closed strictly before one native timeframe earlier.",
            "timeframes": list(TIMEFRAMES),
            "limitations": ["Historical bid/ask spread, depth and order-flow snapshots are not available.", "The exact intrahour onset minute requires a separate M1 crossing scan; this artifact compares preconditions at the H1-candle boundary."],
        },
        "fetch_days": FETCH_DAYS,
        "errors": errors,
        "events": result_events,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"events": len(result_events), "timeframes_per_event": len(TIMEFRAMES), "errors": len(errors), "output": str(Path(args.output).resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--include-wick-only", action="store_true")
    parser.add_argument("--output", default="hourly-20pct-confirmed-mtf-snapshots.json")
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("concurrency must be positive")
    asyncio.run(main(args))
