"""Run reproducible paper backtests from historical PostgreSQL tables only."""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from app.backtest import run_backtest
from app.binance_tr_public import historical_klines
from scripts.build_market_cache import normalize


async def ensure_symbol_data(symbol, interval, days, semaphore):
    """Fetch the requested window when the historical table is missing/short."""
    if interval != "5m":
        return
    async with semaphore:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - int(days * 86400 * 1000)
        existing = await database.get_market_candles(symbol, interval, start_ms, now_ms)
        expected = max(1, int(days * 288 * 0.90))
        if len(existing) >= expected:
            print(f"[DATA] {symbol} | mevcut={len(existing)}/{days * 288} yeterli", flush=True)
            return
        print(f"[DATA] {symbol} | mevcut={len(existing)}/{days * 288} eksik, Binance TR'den cekiliyor", flush=True)
        raw = await historical_klines(symbol, interval, days)
        candles = normalize(symbol, raw, interval)
        if candles:
            await database.upsert_market_candles(candles)
        print(f"[DATA] {symbol} | cekildi={len(candles)} DB'ye yazildi", flush=True)


async def main(args):
    print("[START] Historical backtest basladi | source=historical_candles | timeframe=" + args.interval, flush=True)
    print("[DB] Mevcut historical tablolar okunuyor (migration tekrar calistirilmiyor)...", flush=True)
    results = []
    data_semaphore = asyncio.Semaphore(8)
    for days in args.days:
        print(f"[DATA] {days} gunluk pencere icin eksik mumlar tamamlanıyor | workers=8", flush=True)
        await asyncio.gather(*(ensure_symbol_data(symbol, args.interval, days, data_semaphore) for symbol in args.symbols))
    for days in args.days:
        for symbol in args.symbols:
            candles = await database.get_market_candles(symbol, args.interval)
            features = await database.get_market_feature_snapshots(symbol, args.interval, feature_version=args.feature_version)
            if not candles:
                print(f"{symbol} {days}d: SKIP historical_candles bos", flush=True)
                continue
            print(f"[QUEUE] {symbol} {days}d | candles={len(candles)} features={len(features)}", flush=True)
            try:
                started = time.monotonic()
                print(f"[RUNNING] {symbol} {days}d | strategy={args.strategy}", flush=True)
                job = asyncio.create_task(run_backtest(
                    symbol, args.interval, days, args.strategy, {},
                    order_size=args.order_size, stop_pct=args.stop_pct,
                    tp_pct=args.tp_pct, trail_pct=args.trail_pct,
                    pyramiding_layers=args.pyramiding,
                    order_pct=args.order_pct,
                ))
                while not job.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(job), timeout=5)
                    except asyncio.TimeoutError:
                        pass
                    if not job.done():
                        print(f"[HEARTBEAT] {symbol} {days}d | elapsed={time.monotonic() - started:.0f}s still_running", flush=True)
                run_id, result = await job
                row = {
                    "run_id": run_id, "symbol": symbol, "period": f"{days * 24}h",
                    "days": days, "candle_count": result.get("data_quality", {}).get("candle_count"),
                    "feature_count": len(features), "total_trades": result.get("total_trades"),
                    "wins": result.get("wins"), "losses": result.get("losses"),
                    "win_rate": result.get("win_rate"), "net_pnl": result.get("net_pnl"),
                    "profit_factor": result.get("profit_factor"),
                    "max_drawdown_pct": result.get("max_drawdown_pct"),
                    "avg_loss": result.get("avg_loss"),
                    "worst_trade_pnl": min((float(t.get("pnl", 0)) for t in result.get("trades", [])), default=0.0),
                    "final_balance": result.get("final_balance"), "data_source": "historical_candles",
                }
                results.append(row)
                print(f"[DONE] {symbol} {days}d | pnl={row['net_pnl']} trades={row['total_trades']} elapsed={time.monotonic() - started:.1f}s", flush=True)
                print(json.dumps(row, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(f"[ERROR] {symbol} {days}d | {exc}", flush=True)
    print("[COMPLETE] tests=" + str(len(results)), flush=True)
    print("RESULTS_JSON=" + json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--strategy", default="MOMENTUM")
    parser.add_argument("--feature-version", default="snapshot-v1-5m")
    parser.add_argument("--order-size", type=float, default=500.0)
    parser.add_argument("--stop-pct", type=float, default=0.005)
    parser.add_argument("--tp-pct", type=float, default=0.015)
    parser.add_argument("--trail-pct", type=float, default=0.003)
    parser.add_argument("--pyramiding", type=int, choices=(1, 2, 3), default=3,
                        help="Maximum pyramid layers; 1 disables pyramiding")
    parser.add_argument("--order-pct", type=float, choices=(0.1, 0.2, 0.25), default=None,
                        help="Dynamic order size as portfolio cash percentage")
    parser.add_argument("--days", nargs="+", type=int, choices=(1, 3, 7, 30), default=(3, 7),
                        help="Test periods in days; default: 3 7")
    asyncio.run(main(parser.parse_args()))
