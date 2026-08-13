"""Fetch public candles and optionally persist deterministic feature snapshots.

Usage: python -m scripts.build_market_cache --symbols BMTTRY MUBARAKTRY --days 7 --timeframes 5m 30m

Feature snapshots are deliberately opt-in: current portfolio replay reads
historical_candles directly, so generating snapshots would only add CPU/DB
work until a parity-verified snapshot reader is introduced.
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


async def build_symbol(symbol, days, timeframe, feature_version, end_time_ms=None, from_db=False, args=None):
    started = time.monotonic()
    if from_db:
        interval_ms = {"1m": 60_000, "3m": 180_000, "5m": 300_000,
                       "15m": 900_000, "30m": 1_800_000}[timeframe]
        end_ms = end_time_ms or int(time.time() * 1000)
        # Include the full indicator warm-up, but only derive snapshots from
        # the selected historical window below.
        start_ms = end_ms - days * 86_400_000 - 250 * interval_ms
        candles = await database.get_market_candles(symbol, timeframe, start_ms, end_ms)
        print(f"[{symbol}] DB tamamlandi | candles={len(candles)}", flush=True)
    else:
        print(f"[START] {symbol} {timeframe}: {days} gunluk veri cekiliyor...", flush=True)
        raw = await historical_klines(symbol, timeframe, days, end_time_ms)
        candles = normalize(symbol, raw, timeframe)
        print(f"[{symbol}] API tamamlandi | raw={len(raw)} candles={len(candles)}", flush=True)
    batch_size = 300
    if not from_db:
        for start in range(0, len(candles), batch_size):
            batch = candles[start:start + batch_size]
            await database.upsert_market_candles(batch)
            print(f"[{symbol}] candles {min(start + len(batch), len(candles))}/{len(candles)} DB yazildi", flush=True)
    if not args.with_features:
        print(f"[DONE] {symbol} {timeframe} | candles={len(candles)} features=skipped elapsed={time.monotonic() - started:.1f}s", flush=True)
        return symbol, timeframe, len(candles), 0

    features = []
    feature_start_ms = (end_time_ms or int(time.time() * 1000)) - days * 86_400_000
    for idx in range(54, len(candles)):
        # Indicators need a bounded warm-up window. Keeping the last 250
        # confirmed candles preserves EMA/ATR/structure context while avoiding
        # quadratic work over a multi-day history.
        window = candles[max(0, idx - 249):idx + 1]
        klines = {key: [c[key] for c in window] for key in ("open", "high", "low", "close", "volume")}
        klines = {timeframe: {"opens": klines["open"], "highs": klines["high"], "lows": klines["low"], "closes": klines["close"], "volumes": klines["volume"]}}
        snapshot = calculate_snapshot(symbol, candles[idx]["close"], klines, primary_timeframe=timeframe)
        if from_db and candles[idx]["open_time"] < feature_start_ms:
            continue
        features.append({
            "symbol": symbol, "timeframe": timeframe, "open_time": candles[idx]["open_time"],
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
    feature_count = sum(1 for candle in candles[54:] if not from_db or candle["open_time"] >= feature_start_ms)
    if features:
        await database.upsert_market_feature_snapshots(features)
        print(f"[{symbol}] features {feature_count}/{feature_count} DB yazildi", flush=True)
    print(f"[DONE] {symbol} {timeframe} | candles={len(candles)} features={feature_count} elapsed={time.monotonic() - started:.1f}s", flush=True)
    return symbol, timeframe, len(candles), feature_count


async def main(args):
    await database.init_db()
    symbols = args.symbols or await database.get_market_symbols(args.cached_symbols_timeframe)
    if not symbols:
        raise SystemExit("Cachelenecek sembol bulunamadı")
    print(f"[START] Market cache | symbols={len(symbols)} days={args.days} timeframes={','.join(args.timeframes)} workers={args.workers}", flush=True)
    print("[DB] Mevcut historical tablolar kullaniliyor (migration tekrar calistirilmiyor)...", flush=True)
    semaphore = asyncio.Semaphore(args.workers)
    async def one(symbol):
        async with semaphore:
            try:
                results = []
                for timeframe in args.timeframes:
                    feature_version = f"{args.feature_version}-{timeframe}"
                    results.append(await build_symbol(symbol, args.days, timeframe, feature_version,
                                                      args.end_time_ms, args.from_db, args))
                for result in results:
                    print(f"{result[0]} {result[1]}: {result[2]} candles, {result[3]} feature snapshots", flush=True)
            except Exception as exc:
                print(f"{symbol}: ERROR {exc}", flush=True)
    await asyncio.gather(*(one(s) for s in symbols))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--symbols", nargs="+")
    source.add_argument("--cached-symbols", action="store_true",
                        help="Sembol listesini historical_candles içindeki mevcut timeframe'den al")
    parser.add_argument("--cached-symbols-timeframe", default="5m",
                        choices=("1m", "3m", "5m", "15m", "30m"))
    parser.add_argument("--days", type=int, choices=(3, 7, 30), default=7)
    parser.add_argument("--workers", type=int, default=8,
                        help="Aynı anda işlenecek sembol sayısı; API/DB yükünü sınırlamak için 8-16 önerilir")
    parser.add_argument("--timeframes", nargs="+", choices=("1m", "3m", "5m", "15m", "30m"), default=["5m"],
                        help="Cachelenecek mum aralıkları; M30 aktivite filtresi için 30m ekleyin")
    parser.add_argument("--feature-version", default="snapshot-v1")
    parser.add_argument("--with-features", action="store_true",
                        help="Feature snapshot üret; mevcut portfolio replay bunu okumadığı için normal cache güncellemesinde kapalı bırakın")
    parser.add_argument("--from-db", action="store_true",
                        help="API çağrısı yapmadan mevcut historical_candles satırlarından snapshot üret")
    parser.add_argument("--end-date", help="ISO UTC bitiş zamanı; ör. 2026-08-04T07:00:00+00:00")
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 64:
        parser.error("--workers 1 ile 64 arasında olmalıdır")
    if args.from_db and not args.with_features:
        parser.error("--from-db yalnız --with-features ile kullanılabilir")
    args.end_time_ms = int(datetime.fromisoformat(args.end_date).timestamp() * 1000) if args.end_date else None
    asyncio.run(main(args))
