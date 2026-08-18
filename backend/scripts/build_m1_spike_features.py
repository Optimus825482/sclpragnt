"""Persist compact causal M1 research features in historical_feature_snapshots.

No future bar is read while computing a row.  This is a research cache only;
the portfolio runner and live strategy do not consume this feature version.
"""
import argparse
import asyncio
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import database


def ema(values, period):
    if len(values) < period: return None
    value, alpha = sum(values[:period]) / period, 2 / (period + 1)
    for item in values[period:]: value = item * alpha + value * (1 - alpha)
    return value


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)] if ordered else None


def build_rows(symbol, candles, start_ms, version):
    o = [float(row["open"]) for row in candles]; h = [float(row["high"]) for row in candles]
    l = [float(row["low"]) for row in candles]; c = [float(row["close"]) for row in candles]
    v = [float(row["volume"]) for row in candles]
    atr_pct_series = [None] * len(candles)
    for i in range(14, len(candles)):
        local = [max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1])) for j in range(i - 13, i + 1)]
        atr_pct_series[i] = sum(local) / 14 / c[i] * 100 if c[i] else None
    result = []
    for i in range(60, len(candles)):
        if int(candles[i]["open_time"]) < start_ms or not c[i]: continue
        close, prior = c[i], c[i - 1]
        tr = [max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1])) for j in range(i - 13, i + 1)]
        atr14 = sum(tr) / 14
        changes = [c[j] - c[j - 1] for j in range(i - 13, i + 1)]
        gain, loss = sum(max(x, 0) for x in changes) / 14, sum(max(-x, 0) for x in changes) / 14
        rsi = 100 if not loss else 100 - 100 / (1 + gain / loss)
        typical = [(h[j] + l[j] + c[j]) / 3 for j in range(i - 19, i + 1)]
        volumes = v[i - 19:i + 1]; total_volume = sum(volumes)
        vwap = sum(x * y for x, y in zip(typical, volumes)) / total_volume if total_volume else None
        bb = c[i - 19:i + 1]; mean = sum(bb) / 20; std = math.sqrt(sum((x - mean) ** 2 for x in bb) / 20)
        ema9, ema21 = ema(c[i - 39:i + 1], 9), ema(c[i - 59:i + 1], 21)
        ema12, ema26 = ema(c[i - 59:i + 1], 12), ema(c[i - 59:i + 1], 26)
        macd = ema12 - ema26 if ema12 and ema26 else None
        # Causal two-point MACD acceleration proxy; no future signal line.
        prev12, prev26 = ema(c[i - 1 - 59:i], 12), ema(c[i - 1 - 59:i], 26)
        prev_macd = prev12 - prev26 if prev12 and prev26 else None
        prior_low = min(l[i - 20:i]); body = abs(c[i] - o[i]); lower_wick = min(o[i], c[i]) - l[i]
        atr_history = [value for value in atr_pct_series[max(14, i - 1439):i + 1:15] if value is not None]
        range15 = (max(h[i - 14:i + 1]) / min(l[i - 14:i + 1]) - 1) * 100 if min(l[i - 14:i + 1]) else 0
        range60 = (max(h[i - 59:i + 1]) / min(l[i - 59:i + 1]) - 1) * 100 if min(l[i - 59:i + 1]) else 0
        payload = {
            "return_1m_pct": round((close / c[i - 1] - 1) * 100, 5), "return_5m_pct": round((close / c[i - 5] - 1) * 100, 5),
            "return_15m_pct": round((close / c[i - 15] - 1) * 100, 5), "return_1h_pct": round((close / c[i - 60] - 1) * 100, 5),
            "atr14_pct": round(atr14 / close * 100, 5), "atr14_p80_24h": round(percentile(atr_history, .80), 5) if atr_history else None,
            "range15_pct": round(range15, 5), "range60_pct": round(range60, 5),
            "rsi14": round(rsi, 5), "volume_ratio20": round(v[i] / (sum(v[i - 20:i]) / 20), 5) if sum(v[i - 20:i]) else None,
            "vwap20_distance_pct": round((close / vwap - 1) * 100, 5) if vwap else None,
            "ema9_ema21_gap_pct": round((ema9 / ema21 - 1) * 100, 5) if ema9 and ema21 else None,
            "macd_acceleration": round(macd - prev_macd, 8) if macd is not None and prev_macd is not None else None,
            "bb_bandwidth_pct": round(4 * std / mean * 100, 5) if mean else None,
            "bb_position": round((close - (mean - 2 * std)) / (4 * std), 5) if std else None,
            "lower_wick_atr": round(lower_wick / atr14, 5) if atr14 else None,
            "body_atr": round(body / atr14, 5) if atr14 else None,
            "liquidity_sweep_reclaim": bool(l[i] < prior_low - atr14 * .10 and close > prior_low and close > o[i] and lower_wick >= max(body * 1.5, atr14 * .10)),
        }
        result.append({"symbol": symbol, "timeframe": "1m", "open_time": candles[i]["open_time"], "captured_at": candles[i]["close_time"],
                       "feature_version": version, "payload": payload, "regime": None, "regime_confidence": None, "confluence_score": None, "data_ready": True})
    return result


async def main(args):
    tz = ZoneInfo(args.timezone); end = int(datetime.fromisoformat(args.end_date).replace(tzinfo=tz).timestamp() * 1000)
    start = end - args.hours * 3_600_000
    await database.init_db(); symbols = args.symbols or await database.get_market_symbols("1m")
    if not symbols: raise SystemExit("M1 historical_candles içinde sembol bulunamadı")
    semaphore = asyncio.Semaphore(args.workers)
    async def one(symbol):
        async with semaphore:
            candles = await database.get_market_candles(symbol, "1m", start - 90 * 60_000, end)
        rows = build_rows(symbol, candles, start, args.feature_version)
        for offset in range(0, len(rows), 1000): await database.upsert_market_feature_snapshots(rows[offset:offset + 1000])
        return symbol, len(rows)
    tasks = [asyncio.create_task(one(symbol)) for symbol in symbols]; total = 0
    for number, task in enumerate(asyncio.as_completed(tasks), 1):
        symbol, count = await task; total += count
        if number == 1 or number % 10 == 0 or number == len(symbols): print(f"[PROGRESS] symbols={number}/{len(symbols)} snapshots={total}", flush=True)
    print(f"[COMPLETE] feature_version={args.feature_version} symbols={len(symbols)} snapshots={total} window_hours={args.hours}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--symbols", nargs="*"); parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--end-date", required=True); parser.add_argument("--timezone", default="Europe/Istanbul"); parser.add_argument("--feature-version", default="m1-spike-v1")
    parser.add_argument("--workers", type=int, default=16); args = parser.parse_args()
    if args.hours < 1 or args.hours > 72 or not 1 <= args.workers <= 64: parser.error("hours/worker değeri geçersiz")
    asyncio.run(main(args))
