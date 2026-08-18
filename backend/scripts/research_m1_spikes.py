"""Causal M1 spike-label research; never opens a paper position.

Labels are future-only analysis targets. Reported pre-event features use only
the candle available at the decision time, so any later strategy test can
reuse them without look-ahead leakage.
"""
import argparse
import asyncio
import bisect
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from app.technical_analysis import _adx


def as_series(rows):
    return {
        "times": [int(row["close_time"]) // 1000 for row in rows],
        "opens": [float(row["open"]) for row in rows],
        "highs": [float(row["high"]) for row in rows],
        "lows": [float(row["low"]) for row in rows],
        "closes": [float(row["close"]) for row in rows],
        "volumes": [float(row["volume"]) for row in rows],
    }


def features(data, index):
    closes, highs, lows, volumes = (data[key] for key in ("closes", "highs", "lows", "volumes"))
    if index < 20 or not closes[index - 15]:
        return None
    price = closes[index]
    volume_average = sum(volumes[index - 20:index]) / 20
    prior_low, prior_high = min(lows[index - 15:index]), max(highs[index - 15:index])
    return {
        "price": price,
        "return_1m_pct": round((price / closes[index - 1] - 1) * 100, 4),
        "return_5m_pct": round((price / closes[index - 5] - 1) * 100, 4),
        "return_15m_pct": round((price / closes[index - 15] - 1) * 100, 4),
        "volume_ratio_20": round(volumes[index] / volume_average, 4) if volume_average else None,
        "range_15m_pct": round((prior_high / prior_low - 1) * 100, 4) if prior_low else None,
        "close_to_15m_high_pct": round((price / prior_high - 1) * 100, 4) if prior_high else None,
    }


def _ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for item in values[period:]:
        value = item * alpha + value * (1 - alpha)
    return value


def indicator_features(data, index):
    """Indicators calculated only for labelled events, never using future bars."""
    closes, highs, lows, volumes = (data[key] for key in ("closes", "highs", "lows", "volumes"))
    if index < 35:
        return {}
    price = closes[index]
    changes = [closes[i] - closes[i - 1] for i in range(index - 13, index + 1)]
    gains = sum(max(change, 0) for change in changes) / 14
    losses = sum(max(-change, 0) for change in changes) / 14
    rsi = 100 if losses == 0 else 100 - 100 / (1 + gains / losses)
    tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(index - 13, index + 1)]
    atr_pct = sum(tr) / 14 / price * 100 if price else None
    start = index - 19
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(start, index + 1)]
    total_volume = sum(volumes[start:index + 1])
    vwap = sum(value * volume for value, volume in zip(typical, volumes[start:index + 1])) / total_volume if total_volume else None
    ema_window = closes[max(0, index - 59):index + 1]
    ema9, ema21 = _ema(ema_window, 9), _ema(ema_window, 21)
    ema12, ema26 = _ema(ema_window, 12), _ema(ema_window, 26)
    macd_history = []
    for cutoff in range(26, len(ema_window) + 1):
        fast, slow = _ema(ema_window[:cutoff], 12), _ema(ema_window[:cutoff], 26)
        if fast is not None and slow is not None:
            macd_history.append(fast - slow)
    macd = macd_history[-1] if macd_history else None
    signal = _ema(macd_history, 9)
    bb_slice = closes[start:index + 1]
    mean = sum(bb_slice) / len(bb_slice)
    std = (sum((value - mean) ** 2 for value in bb_slice) / len(bb_slice)) ** 0.5
    directional = _adx(highs[max(0, index - 29):index + 1], lows[max(0, index - 29):index + 1], closes[max(0, index - 29):index + 1]) or {}
    return {
        "rsi_14": round(rsi, 4), "atr_14_pct": round(atr_pct, 4) if atr_pct is not None else None,
        "vwap20_distance_pct": round((price / vwap - 1) * 100, 4) if vwap else None,
        "ema9_ema21_gap_pct": round((ema9 / ema21 - 1) * 100, 4) if ema9 and ema21 else None,
        "macd_histogram": round(macd - signal, 8) if macd is not None and signal is not None else None,
        "bb20_bandwidth_pct": round((4 * std / mean) * 100, 4) if mean else None,
        "adx_14": round(float(directional.get("adx")), 4) if directional.get("adx") is not None else None,
        "plus_di": round(float(directional.get("plus_di")), 4) if directional.get("plus_di") is not None else None,
        "minus_di": round(float(directional.get("minus_di")), 4) if directional.get("minus_di") is not None else None,
    }


def summarize(rows, field):
    values = [row["features"].get(field) for row in rows if isinstance(row["features"].get(field), (int, float))]
    if not values:
        return None
    return {"median": round(statistics.median(values), 4), "mean": round(statistics.mean(values), 4)}


async def main(args):
    tz = ZoneInfo(args.timezone)
    start_ts = int(datetime.fromisoformat(args.start_date).replace(tzinfo=tz).timestamp())
    end_ts = int(datetime.fromisoformat(args.end_date).replace(tzinfo=tz).timestamp())
    if start_ts >= end_ts:
        raise SystemExit("Başlangıç bitişten önce olmalıdır")
    await database.init_db()
    symbols = args.symbols or await database.get_market_symbols("5m")
    horizon_seconds = args.horizon_minutes * 60
    cooldown_seconds = args.event_cooldown_minutes * 60
    semaphore = asyncio.Semaphore(args.workers)

    async def inspect(symbol):
        async with semaphore:
            rows = await database.get_market_candles(symbol, "1m", (start_ts - 30 * 60) * 1000,
                                                     (end_ts + horizon_seconds) * 1000)
        data = as_series(rows)
        if len(data["times"]) < 81:
            return symbol, [], 0
        events, samples, next_allowed = [], 0, 0
        for ts in range(start_ts, end_ts + 1, args.sample_minutes * 60):
            index = bisect.bisect_right(data["times"], ts) - 1
            if index < 20:
                continue
            future_end = bisect.bisect_right(data["times"], ts + horizon_seconds)
            if future_end <= index + 1:
                continue
            sample = features(data, index)
            if not sample:
                continue
            samples += 1
            future_high = max(data["highs"][index + 1:future_end])
            move_pct = (future_high / sample["price"] - 1) * 100 if sample["price"] else 0
            if move_pct >= args.spike_threshold_pct and ts >= next_allowed:
                high_index = data["highs"].index(future_high, index + 1, future_end)
                events.append({"symbol": symbol, "decision_time": ts, "peak_time": data["times"][high_index],
                               "peak_move_pct": round(move_pct, 4), "features": sample,
                               "indicators": indicator_features(data, index)})
                next_allowed = ts + cooldown_seconds
        return symbol, events, samples

    inspected = await asyncio.gather(*(inspect(symbol) for symbol in symbols))
    events = [event for _, found, _ in inspected for event in found]
    samples = sum(count for _, _, count in inspected)
    events.sort(key=lambda row: row["peak_move_pct"], reverse=True)
    fields = ("return_1m_pct", "return_5m_pct", "return_15m_pct", "volume_ratio_20", "range_15m_pct", "close_to_15m_high_pct")
    payload = {
        "paper_only": True,
        "source": "historical_candles / Binance TR public M1",
        "window": {"start": args.start_date, "end": args.end_date, "timezone": args.timezone},
        "label": {"future_horizon_minutes": args.horizon_minutes, "minimum_peak_move_pct": args.spike_threshold_pct,
                  "warning": "Future peak is a research label only; never use it as a live signal."},
        "samples": samples, "symbols_requested": len(symbols), "events": events,
        "pre_event_feature_summary": {field: summarize(events, field) for field in fields},
        "indicator_summary": {field: {"median": round(statistics.median(values), 4), "mean": round(statistics.mean(values), 4)}
                              for field in ("rsi_14", "atr_14_pct", "vwap20_distance_pct", "ema9_ema21_gap_pct", "macd_histogram", "bb20_bandwidth_pct", "adx_14", "plus_di", "minus_di")
                              if (values := [event["indicators"].get(field) for event in events if isinstance(event["indicators"].get(field), (int, float))])},
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] result=" + str(Path(args.output).resolve()))
    print("RESULT_JSON=" + json.dumps({"symbols": len(symbols), "samples": samples, "spike_events": len(events),
                                         "top_events": events[:10], "feature_summary": payload["pre_event_feature_summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--horizon-minutes", type=int, default=60)
    parser.add_argument("--spike-threshold-pct", type=float, default=10.0)
    parser.add_argument("--sample-minutes", type=int, default=5)
    parser.add_argument("--event-cooldown-minutes", type=int, default=60)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--output", default="m1-spike-research.json")
    args = parser.parse_args()
    if args.horizon_minutes < 5 or args.spike_threshold_pct <= 0 or args.sample_minutes < 1 or args.event_cooldown_minutes < 1 or not 1 <= args.workers <= 64:
        parser.error("horizon/eşik/örnekleme/soğuma/worker değerleri geçersiz")
    asyncio.run(main(args))
