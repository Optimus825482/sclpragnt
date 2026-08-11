"""Fetch public 5m candles and persist deterministic feature snapshots.

Usage: python -m scripts.build_market_cache --symbols BMTTRY MUBARAKTRY --days 7
"""
import argparse
import asyncio
import time
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from app.binance_tr_public import historical_klines
from app.technical_analysis import calculate_snapshot


def normalize(symbol, raw, timeframe):
    out = []
    for row in raw:
        if len(row) < 6:
            continue
        try:
            values = [float(row[i]) for i in range(1, 6)]
            if not all(v == v and abs(v) != float("inf") for v in values):
                continue
            out.append({
                "symbol": symbol.upper(), "timeframe": timeframe,
                "open_time": int(row[0]), "close_time": int(row[6]) if len(row) > 6 else int(row[0]),
                "open": values[0], "high": values[1], "low": values[2], "close": values[3],
                "volume": values[4], "quote_volume": float(row[7]) if len(row) > 7 else None,
                "trade_count": int(row[8]) if len(row) > 8 else None,
                "source": "binance_tr_public", "fetched_at": time.time(),
            })
        except (TypeError, ValueError, IndexError):
            continue
    return sorted({r["open_time"]: r for r in out}.values(), key=lambda r: r["open_time"])


async def build_symbol(symbol, days, feature_version, end_time_ms=None):
    started = time.monotonic()
    print(f"[START] {symbol}: {days} gunluk 5m veri cekiliyor...", flush=True)
    raw = await historical_klines(symbol, "5m", days, end_time_ms)
    candles = normalize(symbol, raw, "5m")
    print(f"[{symbol}] API tamamlandi | raw={len(raw)} candles={len(candles)}", flush=True)
    batch_size = 300
    for start in range(0, len(candles), batch_size):
        batch = candles[start:start + batch_size]
        await database.upsert_market_candles(batch)
        print(f"[{symbol}] candles {min(start + len(batch), len(candles))}/{len(candles)} DB yazildi", flush=True)
    features = []
    for idx in range(54, len(candles)):
        # Indicators need a bounded warm-up window. Keeping the last 250
        # confirmed candles preserves EMA/ATR/structure context while avoiding
        # quadratic work over a multi-day history.
        window = candles[max(0, idx - 249):idx + 1]
        klines = {key: [c[key] for c in window] for key in ("open", "high", "low", "close", "volume")}
        klines = {"5m": {"opens": klines["open"], "highs": klines["high"], "lows": klines["low"], "closes": klines["close"], "volumes": klines["volume"]}}
        snapshot = calculate_snapshot(symbol, candles[idx]["close"], klines, primary_timeframe="5m")
        features.append({
            "symbol": symbol, "timeframe": "5m", "open_time": candles[idx]["open_time"],
            "captured_at": candles[idx]["close_time"], "feature_version": feature_version,
            "payload": snapshot, "regime": (snapshot.get("methodologies", {}).get("regime") or {}).get("name"),
            "regime_confidence": (snapshot.get("methodologies", {}).get("regime") or {}).get("confidence"),
            "confluence_score": (snapshot.get("methodologies", {}).get("confluence") or {}).get("score"),
            "data_ready": bool(snapshot.get("data_ready")),
        })
        if len(features) >= batch_size:
            await database.upsert_market_feature_snapshots(features)
            print(f"[{symbol}] features {idx - 53}/{len(candles) - 54} DB yazildi", flush=True)
            features = []
    feature_count = len(candles) - 54
    if features:
        await database.upsert_market_feature_snapshots(features)
        print(f"[{symbol}] features {feature_count}/{feature_count} DB yazildi", flush=True)
    print(f"[DONE] {symbol} | candles={len(candles)} features={feature_count} elapsed={time.monotonic() - started:.1f}s", flush=True)
    return symbol, len(candles), feature_count


async def main(args):
    await database.init_db()
    print(f"[START] Market cache | symbols={len(args.symbols)} days={args.days} timeframe=5m workers=8", flush=True)
    print("[DB] Mevcut historical tablolar kullaniliyor (migration tekrar calistirilmiyor)...", flush=True)
    semaphore = asyncio.Semaphore(8)
    async def one(symbol):
        async with semaphore:
            try:
                result = await build_symbol(symbol, args.days, args.feature_version, args.end_time_ms)
                print(f"{result[0]}: {result[1]} candles, {result[2]} feature snapshots", flush=True)
            except Exception as exc:
                print(f"{symbol}: ERROR {exc}", flush=True)
    await asyncio.gather(*(one(s) for s in args.symbols))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--days", type=int, choices=(3, 7, 30), default=7)
    parser.add_argument("--feature-version", default="snapshot-v1-5m")
    parser.add_argument("--end-date", help="ISO UTC bitiş zamanı; ör. 2026-08-04T07:00:00+00:00")
    args = parser.parse_args()
    args.end_time_ms = int(datetime.fromisoformat(args.end_date).timestamp() * 1000) if args.end_date else None
    asyncio.run(main(args))
