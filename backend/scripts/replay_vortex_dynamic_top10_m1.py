"""Paper-only dynamic top-10 gainer replay for Vortex Breakout PRO v4.1 on M1.
"""
import argparse
import asyncio
import bisect
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, trading_symbols
from app.config import config
from scripts.replay_vortex_breakout_pro_hmtry_m1 import (
    MS_1M as MS_1M,
    compute_indicators,
    cost_parameters,
    iso,
    normalize,
    run_state_machine,
    simulate_trade,
    summarize,
)

LOOKBACK_BARS_24H = 1440


async def fetch_symbol(symbol, days, cutoff, semaphore):
    async with semaphore:
        try:
            rows = normalize(await historical_klines(symbol, "1m", days, cutoff), cutoff)
            return symbol, rows, None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


def refresh_times(rows, start_ms, cutoff_ms, refresh_ms):
    times = sorted({row["close_time"] for row in rows if start_ms <= row["close_time"] <= cutoff_ms})
    return [value for value in times if (value + 1) % refresh_ms == 0]


def build_universe_sets(symbol_rows, refreshes, refresh_ms):
    """Build point-in-time top-10 sets from rolling 24h returns."""
    close_maps = {}
    for symbol, rows in symbol_rows.items():
        close_maps[symbol] = {row["close_time"]: row["close"] for row in rows}

    active_sets = {}
    previous = set()
    additions = 0
    removals = 0
    for refresh in refreshes:
        past = refresh - LOOKBACK_BARS_24H * MS_1M
        ranked = []
        for symbol, closes in close_maps.items():
            current = closes.get(refresh)
            previous_close = closes.get(past)
            if current is None or previous_close in (None, 0):
                continue
            change = current / previous_close - 1.0
            ranked.append((change, symbol))
        ranked.sort(reverse=True)
        selected = {symbol for _, symbol in ranked[:10]}
        active_sets[refresh] = selected
        additions += len(selected - previous)
        removals += len(previous - selected)
        previous = selected
    return active_sets, additions, removals


def latest_refresh(signal_time, refreshes):
    index = bisect.bisect_right(refreshes, signal_time) - 1
    return refreshes[index] if index >= 0 else None


def main_result(events, window_rows, active_sets, additions, removals, errors, args, costs):
    summary = summarize(events, config.INITIAL_BALANCE_TRY, len(window_rows))
    return {
        "paper_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "Vortex Breakout PRO v4.1 - M1 dynamic top-10 gainer universe",
        "window": {
            "start": iso(args.start_ms),
            "end": iso(args.end_ms),
            "hours": args.hours,
        },
        "source": "Binance TR public completed M1 OHLCV; rolling 24h point-in-time returns",
        "universe": {
            "mode": "dynamic_top_10_24h_return",
            "refresh_minutes": args.refresh_minutes,
            "refresh_count": len(active_sets),
            "average_entries_added_per_refresh": round(additions / len(active_sets), 2) if active_sets else 0,
            "average_entries_removed_per_refresh": round(removals / len(active_sets), 2) if active_sets else 0,
            "errors": errors,
        },
        "configuration": {
            "trend_filter": args.trend_filter,
            "position_size": "98%_equity_compounded_common_wallet",
            "open_positions": 1,
            "pyramiding": 0,
            "universe_size": 10,
        },
        "execution": {
            "entry": "next completed M1 bar open",
            "initial_balance_try": config.INITIAL_BALANCE_TRY,
            "cost_mode": args.cost_mode,
            "cost_multiplier": args.cost_multiplier,
            **costs,
        },
        "result": summary,
        "trades_detail": events,
        "limitations": [
            "Dynamic universe is reconstructed from completed public M1 candles, not the historical HTML top-gainer page.",
            "Rolling 24h return is used as the top-gainer ranking proxy; exact page tie-break and UI filtering may differ.",
            "Public OHLCV has no historical spread/depth or intrabar order sequence.",
            "When stop and target occur in the same M1 bar, fill priority uses the open-to-target distance heuristic.",
            "Max drawdown is computed from completed trade PnL, not intrabar equity.",
        ],
    }


async def main(args):
    if args.end_time_ms is not None:
        end_ms = args.end_time_ms
    else:
        now_ms = int(time.time() * 1000) - args.end_minutes_ago * 60000
        end_ms = now_ms // MS_1M * MS_1M
    cutoff_ms = end_ms - 1
    start_ms = end_ms - args.hours * 3600000
    args.start_ms, args.end_ms = start_ms, end_ms

    if args.fixed_symbols:
        all_symbols = [symbol.strip().upper() for symbol in args.fixed_symbols]
    else:
        all_symbols = await trading_symbols("TRY")
    required_days = math.ceil((args.hours + 24 + 10) / 24)
    fetch_days = max(args.fetch_days, required_days)
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch_symbol(symbol, fetch_days, cutoff_ms, semaphore) for symbol in all_symbols))

    symbol_rows = {}
    errors = {}
    for symbol, rows, error in loaded:
        if error or len(rows) < LOOKBACK_BARS_24H + 250:
            errors[symbol] = error or f"insufficient history ({len(rows)} M1 candles)"
            continue
        symbol_rows[symbol] = rows

    all_rows = [row for rows in symbol_rows.values() for row in rows]
    refreshes = refresh_times(all_rows, start_ms, cutoff_ms, args.refresh_minutes * 60 * 1000)
    if args.fixed_symbols:
        fixed_set = set(all_symbols)
        active_sets = {refresh: fixed_set for refresh in refreshes}
        additions, removals = 0, 0
    else:
        active_sets, additions, removals = build_universe_sets(symbol_rows, refreshes, args.refresh_minutes * 60 * 1000)
    refresh_index = refreshes

    costs = cost_parameters(args)
    signals = []
    for symbol, rows in symbol_rows.items():
        indicators = compute_indicators(rows)
        for signal in run_state_machine(rows, indicators, start_ms, cutoff_ms, args.trend_filter):
            if not signal["long_signal_raw"] or not signal["trend_filter_pass"]:
                continue
            refresh = latest_refresh(rows[signal["idx"]]["close_time"], refresh_index)
            if refresh is None or symbol not in active_sets[refresh]:
                continue
            signals.append((rows[signal["idx"]]["close_time"], symbol, rows, indicators, signal))

    signals.sort(key=lambda item: (item[0], item[1]))
    events = []
    equity = config.INITIAL_BALANCE_TRY
    open_until_ms = -1
    for signal_time, symbol, rows, indicators, signal in signals:
        if signal_time <= open_until_ms:
            continue
        trade = simulate_trade(rows, indicators, signal, cutoff_ms, equity, costs)
        if trade is None:
            continue
        events.append({"symbol": symbol, "signal_time": signal["time"], "trade": trade})
        equity += trade["net_pnl_try"]
        open_until_ms = rows[trade["last_bar_idx"]]["close_time"]

    window_rows = [row for rows in symbol_rows.values() for row in rows if start_ms <= row["close_time"] <= cutoff_ms]
    result = main_result(events, window_rows, active_sets, additions, removals, errors, args, costs)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] " + args.output)
    print("RESULT_JSON=" + json.dumps(result["result"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--end-minutes-ago", type=int, default=10)
    parser.add_argument("--end-time-ms", type=int)
    parser.add_argument("--fetch-days", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--trend-filter", choices=("none", "ema200", "ema200_slope", "adx20"), default="none")
    parser.add_argument("--refresh-minutes", type=int, default=15)
    parser.add_argument("--fixed-symbols", nargs="*")
    parser.add_argument("--cost-mode", choices=("config", "pine"), default="config")
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--tick-size", type=float, default=0.0001)
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
