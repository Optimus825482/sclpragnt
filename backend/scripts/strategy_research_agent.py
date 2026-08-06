"""Bounded local strategy-research agent.

Runs each symbol/timeframe as an isolated VectorBT subprocess. This agent is
research-only: it never starts the API, changes config, writes paper trades,
or places orders. A small worker limit prevents Windows/Numba memory spikes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNNER = ROOT / "scripts" / "vectorbt_research.py"


def _run_one(symbol: str, interval: str, days: int, candidate: str, take_profit: float, stop_loss: float) -> dict:
    command = [
        sys.executable, str(RUNNER),
        "--symbols", symbol,
        "--interval", interval,
        "--days", str(days),
        "--candidates", candidate,
        "--take-profit", str(take_profit),
        "--stop-loss", str(stop_loss),
    ]
    started = time.time()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=900)
    if completed.returncode != 0:
        return {
            "symbol": symbol, "interval": interval, "days": days,
            "status": "error", "error": completed.stderr[-2000:],
            "duration_sec": round(time.time() - started, 1),
        }
    try:
        payload = json.loads(completed.stdout)
        result = payload[0] if isinstance(payload, list) and payload else payload
    except (json.JSONDecodeError, TypeError, IndexError) as exc:
        return {
            "symbol": symbol, "interval": interval, "days": days,
            "status": "error", "error": f"Geçersiz araştırma çıktısı: {exc}",
            "raw_tail": completed.stdout[-1000:],
        }
    return {"status": "ok", "duration_sec": round(time.time() - started, 1), **result}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded paper-trading strategy research agent")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--intervals", default="5m:90,15m:90")
    parser.add_argument("--candidate", default="tv_confluence_trend_long")
    parser.add_argument("--take-profit", type=float, default=0.015)
    parser.add_argument("--stop-loss", type=float, default=0.045)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("--workers 1 ile 8 arasında olmalıdır")

    if args.symbols:
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    else:
        from app.config import config
        symbols = list(config.SYMBOLS)
    runs = []
    for spec in args.intervals.split(","):
        interval, _, days_text = spec.strip().partition(":")
        if not interval or not days_text.isdigit():
            parser.error(f"Geçersiz timeframe tanımı: {spec}")
        runs.extend((symbol, interval, int(days_text)) for symbol in symbols)

    started = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_run_one, symbol, interval, days, args.candidate, args.take_profit, args.stop_loss): (symbol, interval) for symbol, interval, days in runs}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({"event": "completed", "symbol": result["symbol"], "interval": result["interval"], "status": result["status"]}, ensure_ascii=False), flush=True)

    results.sort(key=lambda item: (item.get("interval", ""), item.get("symbol", "")))
    report = {
        "agent": "strategy_research_agent",
        "candidate": args.candidate,
        "paper_only": True,
        "started_at": started,
        "finished_at": time.time(),
        "workers": args.workers,
        "results": results,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
