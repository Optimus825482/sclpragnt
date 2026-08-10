"""Compare conservative, balanced and runner exits on the same historical entries."""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import database
from app.backtest import run_backtest


def progress_line(done, total, active, started):
    width = 30
    filled = int(width * done / total) if total else 0
    bar = "#" * filled + "." * (width - filled)
    elapsed = time.monotonic() - started
    sys.stdout.write(f"\r[PROGRESS] [{bar}] {done}/{total} {done / total * 100 if total else 0:5.1f}% | {active} | {elapsed:5.1f}s")
    sys.stdout.flush()


async def main(args):
    await database.init_db()
    print("[START] Exit profile comparison | source=historical_candles", flush=True)
    rows = []
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    total_tests = len(args.symbols) * 2 * len(profiles)
    completed_tests = 0
    overall_started = time.monotonic()
    progress_line(completed_tests, total_tests, "basliyor", overall_started)
    for days in (3, 7):
        for profile in profiles:
            for symbol in args.symbols:
                started = time.monotonic()
                progress_line(completed_tests, total_tests, f"{profile} {symbol} {days}d", overall_started)
                print(f"[RUNNING] {profile} {symbol} {days}d", flush=True)
                try:
                    effective_profile = None if profile == "baseline" else profile
                    job = asyncio.create_task(run_backtest(symbol, args.interval, days, args.strategy, {},
                        order_size=args.order_size, stop_pct=args.stop_pct, tp_pct=args.tp_pct,
                        trail_pct=args.trail_pct, exit_profile=effective_profile))
                    while not job.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(job), timeout=5)
                        except asyncio.TimeoutError:
                            pass
                        elapsed = time.monotonic() - started
                        if not job.done():
                            progress_line(completed_tests, total_tests, f"{profile} {symbol} {days}d heartbeat", overall_started)
                            print(f"[HEARTBEAT] {profile} {symbol} {days}d | elapsed={elapsed:.0f}s", flush=True)
                        if elapsed >= 60:
                            job.cancel()
                            raise TimeoutError("tek test 60 saniyeyi asti")
                    run_id, result = await job
                    row = {"run_id": run_id, "profile": profile, "symbol": symbol,
                           "period": f"{days * 24}h", "net_pnl": result["net_pnl"],
                           "total_trades": result["total_trades"], "wins": result["wins"],
                           "losses": result["losses"], "win_rate": result["win_rate"],
                           "max_drawdown_pct": result.get("max_drawdown_pct"),
                           "exit_reason_counts": result.get("exit_reason_counts", {})}
                    rows.append(row)
                    completed_tests += 1
                    progress_line(completed_tests, total_tests, f"tamamlandi: {profile} {symbol} {days}d", overall_started)
                    print()
                    print(f"[DONE] {profile} {symbol} {days}d | pnl={row['net_pnl']} trades={row['total_trades']} elapsed={time.monotonic()-started:.1f}s", flush=True)
                except Exception as exc:
                    completed_tests += 1
                    progress_line(completed_tests, total_tests, f"hata: {profile} {symbol} {days}d", overall_started)
                    print()
                    print(f"[ERROR] {profile} {symbol} {days}d | {exc}", flush=True)
    progress_line(completed_tests, total_tests, "tamamlandi", overall_started)
    print()
    print("[COMPLETE] tests=" + str(len(rows)), flush=True)
    print("RESULTS_JSON=" + json.dumps(rows, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--strategy", default="MOMENTUM")
    parser.add_argument("--order-size", type=float, default=500.0)
    parser.add_argument("--stop-pct", type=float, default=0.005)
    parser.add_argument("--tp-pct", type=float, default=0.015)
    parser.add_argument("--trail-pct", type=float, default=0.003)
    parser.add_argument("--profiles", default="baseline,runner_a,runner_b,runner_c,runner_d")
    asyncio.run(main(parser.parse_args()))
