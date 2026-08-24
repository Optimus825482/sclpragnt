"""Paper-only M5 runner for the supplied smoothed-kernel green/red-3 rule."""
import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, trading_symbols_with_filters
from scripts import replay_kernel_smoothing_red3_m1 as kernel


MS_5M = 5 * 60_000


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def missing_intervals(rows):
    return sum(max(0, (rows[index]["time"] - rows[index - 1]["time"]) // MS_5M - 1) for index in range(1, len(rows)))


async def fetch(symbol, days, cutoff, semaphore):
    async with semaphore:
        try:
            return symbol, kernel.normalize(await historical_klines(symbol, "5m", days, cutoff), cutoff), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    cutoff = args.end_time_ms if args.end_time_ms is not None else (int(time.time() * 1000) - args.end_minutes_ago * MS_5M) // MS_5M * MS_5M - 1
    start = cutoff - args.hours * 3_600_000
    symbols = [symbol.upper().replace("_", "") for symbol in args.symbols]
    filters, semaphore = await trading_symbols_with_filters("TRY"), asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, cutoff, semaphore) for symbol in symbols))
    per_symbol, errors = {}, {}
    for symbol, rows, error in loaded:
        provenance = {"m5_closed_candles": len(rows), "m5_missing_intervals": missing_intervals(rows),
                      "tick_size_try": float((filters.get(symbol) or {}).get("tick_size") or 0.01)}
        if error or len(rows) < 300:
            errors[symbol] = error or "insufficient completed M5 history"
            per_symbol[symbol] = {"provenance": provenance, "error": errors[symbol]}
        else:
            per_symbol[symbol] = {"provenance": provenance, "result": kernel.replay(rows, start, cutoff, args.cost_multiplier, args.red_confirm_bars, args.green_confirm_bars, args.entry_filter, args.atr_stop_multiplier, args.break_even_r)}
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
              "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "source": "Binance TR public /api/v3/klines completed M5 OHLCV",
              "configuration": {"kernel": {"rational_quadratic_h": kernel.H, "relative_weight_r": kernel.R,
                                               "regression_level_x": kernel.X, "gaussian_h": kernel.H - kernel.LAG,
                                               "lag": kernel.LAG, "smoothing": True},
                                "entry": f"{args.green_confirm_bars} consecutive completed green kernel bar(s) (Gaussian >= rational quadratic)",
                                "exit": f"{args.red_confirm_bars} consecutive completed red kernel bar(s)",
                                "entry_filter": args.entry_filter, "atr_stop_multiplier": args.atr_stop_multiplier,
                                "break_even_r": args.break_even_r, "long_only": True},
              "execution": {"initial_balance_try_per_symbol": kernel.INITIAL_BALANCE_TRY,
                            "allocation_pct_of_current_cash": kernel.ALLOCATION_PCT, "one_open_position_per_symbol": True,
                            "entry_exit_fill": "next M5 open after closed signal", "cost_multiplier": args.cost_multiplier,
                            "commission_pct_each_side": kernel.config.COMMISSION_PCT * args.cost_multiplier,
                            "spread_pct": kernel.config.BACKTEST_ASSUMED_SPREAD_PCT, "slippage_pct_each_side": kernel.config.ESTIMATED_SLIPPAGE_PCT},
              "per_symbol": per_symbol, "errors": errors,
              "limitations": ["KernelFunctions/2 is causally ported from the supplied open source; this is source-aligned, not byte-for-byte TradingView execution.",
                              "Public candles do not include historical depth, actual spread or intrabar execution sequence.",
                              "A single 24-hour result is exploratory and cannot activate a production or live rule."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {symbol: {key: value for key, value in details.get("result", {}).items() if key != "trades_detail"} if "result" in details else {"error": details["error"]} for symbol, details in per_symbol.items()}
    print("RESULT_JSON=" + json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["SPKTRY", "MORPHOTRY"])
    parser.add_argument("--hours", type=int, default=24); parser.add_argument("--fetch-days", type=int, default=7)
    parser.add_argument("--end-minutes-ago", type=int, default=10); parser.add_argument("--end-time-ms", type=int)
    parser.add_argument("--concurrency", type=int, default=2); parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--red-confirm-bars", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--green-confirm-bars", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--entry-filter", choices=("none", "ema30", "ema30_adx18", "ema30_rising", "ema30_rising_atr50", "ema30_rising_volume20", "ema30_ema50"), default="none")
    parser.add_argument("--atr-stop-multiplier", type=float, default=0.0)
    parser.add_argument("--break-even-r", type=float, default=0.0)
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
