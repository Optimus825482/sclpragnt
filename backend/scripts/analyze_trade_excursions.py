"""Analyze post-entry maximum favorable excursion for saved backtests."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import database


async def main(args):
    await database.init_db()
    runs = await database.get_backtests(args.limit)
    if args.run_ids:
        wanted = {int(x) for x in args.run_ids}
        runs = [r for r in runs if int(r.get("id", -1)) in wanted]
    all_rows = []
    for run in runs:
        candles = await database.get_market_candles(run["symbol"], run.get("interval") or "5m")
        by_open = {int(c["open_time"] / 1000): c for c in candles}
        for n, trade in enumerate(run.get("trades") or [], 1):
            entry_time = int(float(trade.get("entry_time") or 0))
            exit_time = int(float(trade.get("exit_time") or entry_time))
            window = [c for c in candles if entry_time <= int(c["open_time"] / 1000) <= exit_time]
            if not window:
                continue
            entry = float(trade.get("entry") or trade.get("quoted_entry") or 0)
            quantity = float(trade.get("quantity") or 0)
            max_candle = max(window, key=lambda c: float(c["high"]))
            max_high = float(max_candle["high"])
            mfe_pct = (max_high / entry - 1) * 100 if entry else 0
            mfe_gross = (max_high - entry) * quantity
            commission = float(run.get("commission_pct") or 0.001)
            estimated_net_at_peak = mfe_gross - (entry * quantity * commission) - (max_high * quantity * commission)
            row = {
                "run_id": run.get("id"), "symbol": run["symbol"], "period": f"{run.get('days_back')}d",
                "trade_no": n, "entry_time": entry_time, "exit_time": exit_time,
                "entry": round(entry, 8), "exit": trade.get("exit"), "closed_pnl": trade.get("pnl"),
                "max_high": max_high, "mfe_pct": round(mfe_pct, 3),
                "mfe_gross_try": round(mfe_gross, 4), "estimated_net_at_peak_try": round(estimated_net_at_peak, 4),
                "ever_profitable_after_cost": estimated_net_at_peak > 0,
                "max_candle_time": int(max_candle["open_time"] / 1000),
            }
            all_rows.append(row)
    profitable = [r for r in all_rows if r["ever_profitable_after_cost"]]
    print(f"[COMPLETE] analyzed_trades={len(all_rows)}", flush=True)
    print(f"[SUMMARY] ever_profitable={len(profitable)}/{len(all_rows)} ({(len(profitable)/len(all_rows)*100 if all_rows else 0):.2f}%)", flush=True)
    groups = {}
    for row in all_rows:
        key = (row["run_id"], row["symbol"], row["period"])
        groups.setdefault(key, []).append(row)
    for (run_id, symbol, period), rows in groups.items():
        good = sum(r["ever_profitable_after_cost"] for r in rows)
        print(f"[GROUP] run={run_id} {symbol} {period} trades={len(rows)} profitable_after_cost={good} "
              f"max_mfe_pct={max(r['mfe_pct'] for r in rows):.3f} avg_mfe_pct={sum(r['mfe_pct'] for r in rows)/len(rows):.3f}", flush=True)
    for row in all_rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    print("RESULTS_JSON=" + json.dumps(all_rows, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--run-ids", nargs="*")
    asyncio.run(main(parser.parse_args()))
