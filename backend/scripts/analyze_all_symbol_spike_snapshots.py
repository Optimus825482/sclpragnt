"""Build causal M1 indicator snapshots around all-symbol spike events."""

import argparse
import asyncio
import bisect
import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.binance_tr_public import historical_klines


FIELDS = [
    "close", "return_1m_pct", "return_3m_pct", "return_5m_pct", "return_15m_pct",
    "rsi_14", "cmo_14", "stoch_k", "stoch_d", "cci_20", "adx_14", "di_gap",
    "ema9_21_gap_pct", "ema_cross_up", "macd_histogram_pct", "roc_10_pct",
    "atr_pct", "bb_position", "bb_width_pct", "volume_ratio_20", "cmf_20",
    "obv_slope_5", "body_pct", "range_pct", "close_position_in_range",
]


def ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for item in values[period:]:
        value = alpha * item + (1 - alpha) * value
    return value


def ema_series(values, period):
    if len(values) < period:
        return []
    seed = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    result = [None] * (period - 1) + [seed]
    current = seed
    for item in values[period:]:
        current = alpha * item + (1 - alpha) * current
        result.append(current)
    return result


def sma(values, period):
    return sum(values[-period:]) / period if len(values) >= period else None


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def atr(rows, period=14):
    if len(rows) < period + 1:
        return None
    trs = []
    for i in range(1, len(rows)):
        row, previous = rows[i], rows[i - 1]
        trs.append(max(row["high"] - row["low"], abs(row["high"] - previous["close"]), abs(row["low"] - previous["close"])))
    return sum(trs[-period:]) / period


def stoch(rows, period=14, smooth=3):
    if len(rows) < period:
        return None, None
    ks = []
    for end in range(period, len(rows) + 1):
        window = rows[end - period:end]
        high, low, close = max(item["high"] for item in window), min(item["low"] for item in window), rows[end - 1]["close"]
        ks.append((close - low) / (high - low) * 100 if high != low else 50.0)
    return ks[-1], sum(ks[-smooth:]) / min(smooth, len(ks))


def cci(rows, period=20):
    if len(rows) < period:
        return None
    typical = [(item["high"] + item["low"] + item["close"]) / 3 for item in rows[-period:]]
    mean = sum(typical) / period
    deviation = sum(abs(item - mean) for item in typical) / period
    return (typical[-1] - mean) / (0.015 * deviation) if deviation else 0.0


def cmo(closes, period=14):
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    gains = sum(change for change in changes if change > 0)
    losses = sum(-change for change in changes if change < 0)
    return 100 * (gains - losses) / (gains + losses) if gains + losses else 0.0


def adx_di(rows, period=14):
    if len(rows) < period * 2:
        return None, None
    trs, plus, minus = [], [], []
    for i in range(1, len(rows)):
        current, previous = rows[i], rows[i - 1]
        trs.append(max(current["high"] - current["low"], abs(current["high"] - previous["close"]), abs(current["low"] - previous["close"])))
        up, down = current["high"] - previous["high"], previous["low"] - current["low"]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
    dx = []
    last_plus, last_minus = None, None
    for i in range(period - 1, len(trs)):
        tr = sum(trs[i - period + 1:i + 1])
        p, m = sum(plus[i - period + 1:i + 1]), sum(minus[i - period + 1:i + 1])
        pdi, mdi = 100 * p / tr if tr else 0, 100 * m / tr if tr else 0
        dx.append((100 * abs(pdi - mdi) / (pdi + mdi), pdi, mdi) if pdi + mdi else (0.0, pdi, mdi))
    if len(dx) < period:
        return None, None
    adx = sum(item[0] for item in dx[-period:]) / period
    return adx, dx[-1][1] - dx[-1][2]


def features(rows, index):
    history = rows[max(0, index - 250):index + 1]
    if len(history) < 55:
        return None
    closes = [item["close"] for item in history]
    volumes = [item["volume"] for item in history]
    current = history[-1]
    close = current["close"]
    atr_value = atr(history)
    ema9, ema21 = ema(closes, 9), ema(closes, 21)
    ema9_previous, ema21_previous = ema(closes[:-1], 9), ema(closes[:-1], 21)
    macd_fast, macd_slow = ema(closes, 12), ema(closes, 26)
    macd_prev_fast, macd_prev_slow = ema(closes[:-1], 12), ema(closes[:-1], 26)
    macd = (macd_fast - macd_slow) if macd_fast is not None and macd_slow is not None else None
    macd_prev = (macd_prev_fast - macd_prev_slow) if macd_prev_fast is not None and macd_prev_slow is not None else None
    signal_series = [a - b for a, b in zip(ema_series(closes, 12), ema_series(closes, 26)) if a is not None and b is not None]
    signal = ema(signal_series, 9) if signal_series else None
    high20, low20 = max(item["high"] for item in history[-20:]), min(item["low"] for item in history[-20:])
    mean20 = sma(closes, 20)
    std20 = statistics.pstdev(closes[-20:]) if len(closes) >= 20 else None
    upper, lower = (mean20 + 2 * std20, mean20 - 2 * std20) if mean20 is not None and std20 is not None else (None, None)
    recent_volume = sum(volumes[-20:-1]) / 19 if len(volumes) >= 21 else None
    cmf_rows = history[-20:]
    cmf_denominator = sum(item["volume"] for item in cmf_rows)
    cmf = sum((((item["close"] - item["low"]) - (item["high"] - item["close"])) / (item["high"] - item["low"]) * item["volume"] if item["high"] != item["low"] else 0) for item in cmf_rows) / cmf_denominator if cmf_denominator else None
    obv = [0.0]
    for previous, item in zip(history, history[1:]):
        obv.append(obv[-1] + (item["volume"] if item["close"] > previous["close"] else -item["volume"] if item["close"] < previous["close"] else 0))
    obv_slope = (obv[-1] - obv[-6]) / sum(volumes[-5:]) if len(obv) >= 6 and sum(volumes[-5:]) else None
    stoch_k, stoch_d = stoch(history)
    adx, di_gap = adx_di(history)
    candle_range = current["high"] - current["low"]
    result = {
        "close": close,
        "return_1m_pct": (close / closes[-2] - 1) * 100 if len(closes) >= 2 and closes[-2] else None,
        "return_3m_pct": (close / closes[-4] - 1) * 100 if len(closes) >= 4 and closes[-4] else None,
        "return_5m_pct": (close / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None,
        "return_15m_pct": (close / closes[-16] - 1) * 100 if len(closes) >= 16 and closes[-16] else None,
        "rsi_14": rsi(closes), "cmo_14": cmo(closes), "stoch_k": stoch_k, "stoch_d": stoch_d, "cci_20": cci(history), "adx_14": adx, "di_gap": di_gap,
        "ema9_21_gap_pct": (ema9 / ema21 - 1) * 100 if ema9 and ema21 else None,
        "ema_cross_up": int(bool(ema9 and ema21 and ema9_previous and ema21_previous and ema9 > ema21 and ema9_previous <= ema21_previous)),
        "macd_histogram_pct": ((macd - signal) / close * 100) if macd is not None and signal is not None and close else None,
        "roc_10_pct": (close / closes[-11] - 1) * 100 if len(closes) >= 11 and closes[-11] else None,
        "atr_pct": atr_value / close if atr_value and close else None,
        "bb_position": (close - lower) / (upper - lower) if upper is not None and lower is not None and upper != lower else None,
        "bb_width_pct": (upper - lower) / mean20 if upper is not None and mean20 else None,
        "volume_ratio_20": current["volume"] / recent_volume if recent_volume else None, "cmf_20": cmf, "obv_slope_5": obv_slope,
        "body_pct": (current["close"] - current["open"]) / current["open"] * 100 if current["open"] else None,
        "range_pct": candle_range / close * 100 if close else None,
        "close_position_in_range": (current["close"] - current["low"]) / candle_range if candle_range else None,
    }
    return {key: round(value, 8) if isinstance(value, float) else value for key, value in result.items()}


def normalize(raw):
    rows, seen = [], set()
    for row in raw or []:
        if len(row) < 7:
            continue
        close_time = int(row[6])
        if close_time in seen:
            continue
        values = [float(row[i]) for i in range(1, 6)]
        if not all(math.isfinite(value) for value in values):
            continue
        seen.add(close_time)
        rows.append({"time": close_time, "open": values[0], "high": values[1], "low": values[2], "close": values[3], "volume": values[4]})
    return sorted(rows, key=lambda row: row["time"])


def extract_at(rows, timestamp_ms):
    index = bisect.bisect_right([row["time"] for row in rows], timestamp_ms) - 1
    if index < 0:
        return None
    return index, features(rows, index)


def numeric_values(rows, key):
    return [float(row[key]) for row in rows if isinstance(row.get(key), (int, float)) and math.isfinite(float(row[key]))]


def rank_biserial(a, b):
    if not a or not b:
        return None
    greater = lower = 0
    for left in a:
        for right in b:
            if left > right:
                greater += 1
            elif left < right:
                lower += 1
    return round((greater - lower) / (len(a) * len(b)), 6)


def summary(events, controls, key):
    a, b = numeric_values(events, key), numeric_values(controls, key)
    return {"events_n": len(a), "controls_n": len(b), "event_median": round(statistics.median(a), 8) if a else None,
            "control_median": round(statistics.median(b), 8) if b else None,
            "delta": round(statistics.median(a) - statistics.median(b), 8) if a and b else None,
            "rank_biserial": rank_biserial(a, b)}


def control_rows(symbol_rows, events, start_ms, end_ms, max_controls, timezone_name):
    candidates = []
    event_times = [event["onset_time_ms"] for event in events]
    times = [row["time"] for row in symbol_rows]
    for timestamp in range(start_ms + 60 * 60_000, end_ms - 15 * 60_000, 15 * 60_000):
        if any(abs(timestamp - event_time) <= 30 * 60_000 for event_time in event_times):
            continue
        index = bisect.bisect_right(times, timestamp) - 1
        future_end = bisect.bisect_right(times, timestamp + 15 * 60_000)
        if index < 55 or future_end <= index + 1:
            continue
        price = symbol_rows[index]["close"]
        max_high = max(row["high"] for row in symbol_rows[index + 1:future_end])
        if price and (max_high / price - 1) * 100 < 1.0:
            feature = features(symbol_rows, index)
            if feature:
                candidates.append({"symbol": "", "time": timestamp, "features": feature})
    if len(candidates) <= max_controls:
        return candidates
    positions = [round(i * (len(candidates) - 1) / (max_controls - 1)) for i in range(max_controls)]
    return [candidates[position] for position in positions]


async def fetch(symbol, end_ms, days, semaphore):
    async with semaphore:
        try:
            rows = normalize(await historical_klines(symbol, "1m", days, end_ms))
            print(f"[DATA] {symbol} candles={len(rows)}", flush=True)
            return symbol, rows, None
        except Exception as exc:
            print(f"[DATA-ERROR] {symbol} {type(exc).__name__}: {exc}", flush=True)
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    event_data = json.loads(Path(args.events).read_text(encoding="utf-8"))
    symbols = event_data["symbols_requested"]
    start_ms = min(event["onset_time_ms"] for event in event_data["events"]) - 60 * 60_000
    end_ms = max(event["peak_time_ms"] for event in event_data["events"]) + 60 * 60_000
    # Keep the actual event window inside the fresh data request while adding warmup.
    fetch_end_ms = max(end_ms, int(datetime.now(ZoneInfo(args.timezone)).timestamp() * 1000)) if args.use_now else end_ms
    fetch_days = args.fetch_days
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, fetch_end_ms, fetch_days, semaphore) for symbol in symbols))
    rows_by_symbol = {symbol: rows for symbol, rows, error in loaded if rows}
    errors = {symbol: error for symbol, rows, error in loaded if error}
    event_rows, control_rows_all = [], []
    events_by_symbol = {}
    for event in event_data["events"]:
        events_by_symbol.setdefault(event["symbol"], []).append(event)
        rows = rows_by_symbol.get(event["symbol"])
        if not rows:
            continue
        anchor = extract_at(rows, event["onset_time_ms"])
        if not anchor or not anchor[1]:
            continue
        index, current_features = anchor
        for lag in (0, 1, 3, 5, 10):
            lag_index = index - lag
            if lag_index < 55:
                continue
            feature = features(rows, lag_index)
            row = {"symbol": event["symbol"], "entry_time": event["entry_time"], "onset_time": event["onset_time"], "peak_time": event["peak_time"], "spike_pct": event["spike_pct"], "lag_minutes": lag, **(feature or {})}
            event_rows.append(row)
    for symbol, rows in rows_by_symbol.items():
        control_rows_all.extend({"symbol": symbol, "time": item["time"], "features": item["features"]} for item in control_rows(rows, events_by_symbol.get(symbol, []), start_ms, end_ms, args.max_controls_per_symbol, args.timezone))
    comparisons = {}
    for lag in (0, 1, 3, 5, 10):
        event_lag = [row for row in event_rows if row["lag_minutes"] == lag]
        # Compare each lag against controls measured at their own control time.
        controls_flat = [{**item["features"], "symbol": item["symbol"]} for item in control_rows_all]
        comparisons[f"lag_{lag}m"] = {field: summary(event_lag, controls_flat, field) for field in FIELDS if field != "close"}
    event_at_anchor = [row for row in event_rows if row["lag_minutes"] == 0]
    pattern_rules = {
        "rsi_lt_40": lambda row: row.get("rsi_14") is not None and row["rsi_14"] < 40,
        "stoch_k_lt_20": lambda row: row.get("stoch_k") is not None and row["stoch_k"] < 20,
        "ema_cross_up": lambda row: row.get("ema_cross_up") == 1,
        "macd_hist_positive": lambda row: row.get("macd_histogram_pct") is not None and row["macd_histogram_pct"] > 0,
        "cmf_positive": lambda row: row.get("cmf_20") is not None and row["cmf_20"] > 0,
        "volume_ratio_gt_2": lambda row: row.get("volume_ratio_20") is not None and row["volume_ratio_20"] > 2,
        "atr_gt_0_5pct": lambda row: row.get("atr_pct") is not None and row["atr_pct"] > 0.005,
        "bb_width_gt_1pct": lambda row: row.get("bb_width_pct") is not None and row["bb_width_pct"] > 0.01,
        "close_low_quarter": lambda row: row.get("close_position_in_range") is not None and row["close_position_in_range"] < 0.25,
    }
    pattern_comparison = {}
    controls_flat = [{**item["features"], "symbol": item["symbol"]} for item in control_rows_all]
    for name, predicate in pattern_rules.items():
        event_hits = sum(predicate(row) for row in event_at_anchor)
        control_hits = sum(predicate(row) for row in controls_flat)
        pattern_comparison[name] = {"events_true": event_hits, "events_total": len(event_at_anchor), "events_rate_pct": round(event_hits / len(event_at_anchor) * 100, 2) if event_at_anchor else 0,
                                    "controls_true": control_hits, "controls_total": len(controls_flat), "controls_rate_pct": round(control_hits / len(controls_flat) * 100, 2) if controls_flat else 0}
    output = {"paper_only": True, "source": "Binance TR public API historical OHLCV", "interval": "1m", "event_source": str(Path(args.events)), "symbols_requested": symbols,
              "event_count": len(event_at_anchor), "control_count": len(controls_flat), "errors": errors, "event_rows": event_rows, "controls": control_rows_all,
              "feature_comparison": comparisons, "pattern_comparison_at_anchor": pattern_comparison,
              "features": FIELDS, "lags_minutes": [0, 1, 3, 5, 10],
              "limitations": ["Sıçrama olayları gelecekteki 15 dakikadaki yüksek fiyatla etiketlendi; göstergeler yalnızca olay başlangıcı ve önceki kapanmış mumlardan hesaplandı.", "Kontroller aynı sembollerde sonraki 15 dakikada %1'in altında hareketlerden örneklendi.", "Spread, orderbook, likidite ve slippage geçmişi yoktur.", "Tek 72 saatlik pencere; sonuçlar keşif amaçlıdır."]}
    output_path = Path(args.output)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = output_path.with_suffix(".csv")
    csv_fields = ["symbol", "entry_time", "onset_time", "peak_time", "spike_pct", "lag_minutes", *FIELDS]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in csv_fields} for row in event_rows)
    print(f"[COMPLETE] events={len(event_at_anchor)} controls={len(controls_flat)} json={output_path.resolve()} csv={csv_path.resolve()}", flush=True)
    for name, result in sorted(pattern_comparison.items(), key=lambda item: item[1]["events_rate_pct"] - item[1]["controls_rate_pct"], reverse=True):
        print(f"[PATTERN] {name} events={result['events_rate_pct']:.1f}% controls={result['controls_rate_pct']:.1f}%", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default="m1-spikes-all-308-symbols-72h.json")
    parser.add_argument("--fetch-days", type=int, default=3)
    parser.add_argument("--max-controls-per-symbol", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--use-now", action="store_true", help="Veriyi mevcut zamana kadar çek; olay penceresi yine event JSON'dan gelir")
    parser.add_argument("--output", default="all-symbol-spike-snapshot-pattern-analysis.json")
    asyncio.run(main(parser.parse_args()))
