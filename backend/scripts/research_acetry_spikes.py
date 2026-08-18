"""Fetch ACETRY MTF history and research causal M1 spike start-to-peak patterns.

Paper-only research. Future highs are labels; all reported entry features use
only candles closed at the labelled start/decision time.
"""
import argparse
import asyncio
import bisect
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from app.binance_tr_public import historical_klines
from app.technical_analysis import calculate_snapshot, _atr, _ema

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
FETCH_DAYS = {"1m": 8, "5m": 14, "15m": 21, "1h": 30, "4h": 40}


def normalize(symbol, timeframe, rows):
    result = []
    for row in rows or []:
        if len(row) < 7:
            continue
        values = [float(row[i]) for i in range(1, 6)]
        if not all(math.isfinite(value) for value in values):
            continue
        result.append({"symbol": symbol, "timeframe": timeframe, "open_time": int(row[0]), "close_time": int(row[6]),
                       "open": values[0], "high": values[1], "low": values[2], "close": values[3], "volume": values[4],
                       "quote_volume": float(row[7]) if len(row) > 7 else None, "trade_count": int(row[8]) if len(row) > 8 else None,
                       "source": "binance_tr_public", "fetched_at": time.time()})
    return sorted({row["open_time"]: row for row in result}.values(), key=lambda row: row["open_time"])


def series(rows):
    return {key: [row[source] for row in rows] for key, source in {
        "times": "close_time", "opens": "open", "highs": "high", "lows": "low", "closes": "close", "volumes": "volume"}.items()}


def compact_snapshot(symbol, price, data, timestamp_ms, timeframe):
    end = bisect.bisect_right(data["times"], timestamp_ms)
    if end < 55:
        return {"data_ready": False, "timeframe": timeframe, "candles": end}
    start = max(0, end - 250)
    history = {key: values[start:end] for key, values in data.items() if key != "times"}
    history["timestamps"] = data["times"][start:end]
    history["last_closed_at_ms"] = data["times"][end - 1]
    snapshot = calculate_snapshot(symbol, price, {timeframe: history}, primary_timeframe=timeframe)
    trend = snapshot.get("trend") or {}; adx = trend.get("adx") or {}
    volatility = snapshot.get("volatility") or {}; volume = snapshot.get("volume") or {}
    bollinger = (snapshot.get("channels") or {}).get("bollinger") or {}
    closes = history["closes"]
    ema20 = _ema(closes, 20); previous = _ema(closes[:-3], 20) if len(closes) >= 23 else None
    return {"data_ready": bool(snapshot.get("data_ready")), "timeframe": timeframe, "candles": end,
            "alignment": trend.get("alignment"), "adx": adx.get("adx"),
            "di_gap": (adx.get("plus_di") - adx.get("minus_di")) if adx.get("plus_di") is not None and adx.get("minus_di") is not None else None,
            "ema20_slope_3_pct": ((ema20 / previous - 1) * 100) if ema20 and previous else None,
            "atr_pct": volatility.get("atr_pct"), "volume_ratio_20": volume.get("volume_ratio_20"),
            "bb_position": bollinger.get("position"), "bb_width_pct": bollinger.get("width_pct"),
            "rsi_14": (snapshot.get("momentum") or {}).get("rsi_14"), "mfi_14": (snapshot.get("momentum") or {}).get("mfi_14")}


def event_features(symbol, mtf, timestamp_ms):
    base = mtf["1m"]
    end = bisect.bisect_right(base["times"], timestamp_ms)
    if end < 60:
        return None
    price = base["closes"][end - 1]
    snapshots = {tf: compact_snapshot(symbol, price, mtf[tf], timestamp_ms, tf) for tf in TIMEFRAMES}
    alignments = [item.get("alignment") for item in snapshots.values() if item.get("data_ready")]
    return {"price": price, "mtf_bullish_count": sum(value == "bullish" for value in alignments),
            "mtf_bearish_count": sum(value == "bearish" for value in alignments),
            "mtf_alignment_score": sum(value == "bullish" for value in alignments) - sum(value == "bearish" for value in alignments),
            "timeframes": snapshots}


def detect_events(symbol, mtf, start_ms, end_ms, threshold_pct, horizon_minutes, cooldown_minutes):
    data = mtf["1m"]; times = data["times"]; start_index = bisect.bisect_left(times, start_ms); end_index = bisect.bisect_right(times, end_ms)
    horizon_ms = horizon_minutes * 60_000; cooldown_ms = cooldown_minutes * 60_000
    events, next_allowed = [], 0
    for index in range(max(60, start_index), min(end_index, len(times))):
        if times[index] < next_allowed:
            continue
        future_end = bisect.bisect_right(times, times[index] + horizon_ms)
        if future_end <= index + 1:
            continue
        price = data["closes"][index]; peak_price = max(data["highs"][index + 1:future_end])
        peak_index = data["highs"].index(peak_price, index + 1, future_end)
        upside = (peak_price / price - 1) * 100 if price else 0
        if upside < threshold_pct:
            continue
        # Define onset as the lowest low in the preceding 60 minutes before
        # the first threshold crossing; this is a reproducible event anchor.
        crossing = next((j for j in range(index + 1, peak_index + 1) if (data["highs"][j] / price - 1) * 100 >= threshold_pct), peak_index)
        onset_start = max(start_index, crossing - 60)
        onset_index = min(range(onset_start, crossing + 1), key=lambda j: data["lows"][j])
        onset_price = data["lows"][onset_index]
        features = event_features(symbol, mtf, data["times"][onset_index])
        if not features:
            continue
        events.append({"symbol": symbol, "decision_time": times[index], "onset_time": times[onset_index], "peak_time": times[peak_index],
                       "decision_price": price, "onset_price": onset_price, "peak_price": peak_price,
                       "decision_to_peak_pct": round(upside, 5), "onset_to_peak_pct": round((peak_price / onset_price - 1) * 100, 5),
                       "onset_to_peak_minutes": round((times[peak_index] - times[onset_index]) / 60_000, 2),
                       "features": features})
        next_allowed = times[peak_index] + cooldown_ms
    return events


def controls(symbol, mtf, events, start_ms, end_ms, horizon_minutes, max_controls):
    data = mtf["1m"]; event_times = [event["onset_time"] for event in events]; candidates = []
    for timestamp in range(start_ms, end_ms + 1, 5 * 60_000):
        if any(abs(timestamp - event_time) <= horizon_minutes * 60_000 for event_time in event_times):
            continue
        end = bisect.bisect_right(data["times"], timestamp + horizon_minutes * 60_000); index = bisect.bisect_right(data["times"], timestamp) - 1
        if index < 60 or end <= index + 1:
            continue
        price = data["closes"][index]; future_high = max(data["highs"][index + 1:end])
        if price and (future_high / price - 1) * 100 < 0.5:
            features = event_features(symbol, mtf, data["times"][index])
            if features:
                candidates.append({"symbol": symbol, "time": data["times"][index], "future_upside_pct": round((future_high / price - 1) * 100, 5), "features": features})
    if len(candidates) <= max_controls:
        return candidates
    # Keep a deterministic, evenly spaced sample across the seven-day window.
    positions = [round(index * (len(candidates) - 1) / (max_controls - 1)) for index in range(max_controls)]
    return [candidates[position] for position in positions]


def feature_summary(rows, path):
    values = []
    for row in rows:
        current = row["features"]
        for part in path.split("."):
            current = current.get(part) if isinstance(current, dict) else None
        if isinstance(current, (int, float)) and math.isfinite(float(current)):
            values.append(float(current))
    return {"n": len(values), "median": round(statistics.median(values), 6), "mean": round(statistics.mean(values), 6)} if values else None


async def main(args):
    end_dt = datetime.fromisoformat(args.end_date).replace(tzinfo=ZoneInfo(args.timezone)) if args.end_date else datetime.now(ZoneInfo(args.timezone))
    end_ms = int(end_dt.timestamp() * 1000); start_ms = end_ms - args.days * 86_400_000
    await database.init_db(); mtf = {}
    for timeframe in TIMEFRAMES:
        print(f"[FETCH] ACETRY {timeframe} days={FETCH_DAYS[timeframe]}", flush=True)
        raw = await historical_klines("ACETRY", timeframe, FETCH_DAYS[timeframe], end_ms)
        rows = normalize("ACETRY", timeframe, raw); mtf[timeframe] = series(rows)
        for offset in range(0, len(rows), 1000):
            await database.upsert_market_candles(rows[offset:offset + 1000])
        print(f"[DATA] {timeframe} candles={len(rows)}", flush=True)
    events = detect_events("ACETRY", mtf, start_ms, end_ms, args.spike_threshold_pct, args.horizon_minutes, args.cooldown_minutes)
    controls_rows = controls("ACETRY", mtf, events, start_ms, end_ms, args.horizon_minutes, args.max_controls)
    paths = ["mtf_bullish_count", "mtf_alignment_score"] + [f"timeframes.{tf}.{field}" for tf in TIMEFRAMES for field in ("adx", "di_gap", "ema20_slope_3_pct", "atr_pct", "volume_ratio_20", "bb_position", "bb_width_pct", "rsi_14", "mfi_14")]
    comparison = {path: {"events": feature_summary(events, path), "controls": feature_summary(controls_rows, path)} for path in paths}
    output = {"paper_only": True, "source": "Binance TR public API historical OHLCV", "symbol": "ACETRY",
              "window": {"start_ms": start_ms, "end_ms": end_ms, "days": args.days, "timezone": args.timezone},
              "fetch_days_by_timeframe": FETCH_DAYS, "candle_counts": {tf: len(mtf[tf]["times"]) for tf in TIMEFRAMES},
              "label": {"threshold_pct": args.spike_threshold_pct, "horizon_minutes": args.horizon_minutes, "future_high_is_label_only": True},
              "event_count": len(events), "control_count": len(controls_rows), "events": events, "controls": controls_rows,
              "feature_comparison": comparison, "limitations": ["7-day single-symbol sample; thresholds are exploratory.", "Historical orderbook/spread/liquidity are unavailable.", "Onset is defined as the lowest low in the preceding 60 minutes before threshold crossing."]}
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] result=" + str(Path(args.output).resolve()), flush=True)
    print(json.dumps({"candles": output["candle_counts"], "events": len(events), "controls": len(controls_rows), "top_events": events[:5]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--days", type=int, default=7); parser.add_argument("--end-date"); parser.add_argument("--timezone", default="Europe/Istanbul"); parser.add_argument("--spike-threshold-pct", type=float, default=2.0); parser.add_argument("--horizon-minutes", type=int, default=60); parser.add_argument("--cooldown-minutes", type=int, default=60); parser.add_argument("--max-controls", type=int, default=200); parser.add_argument("--output", default="acetry-7d-mtf-spike-research.json")
    args = parser.parse_args()
    if args.days < 1 or args.spike_threshold_pct <= 0 or args.horizon_minutes < 5: parser.error("geçersiz araştırma parametresi")
    asyncio.run(main(args))
