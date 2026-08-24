"""Paper-only M5 entry-quality study for the Pump + kernel pullback/reclaim rule.

This intentionally does *not* simulate a red-kernel exit, take-profit, or a
portfolio.  Every completed entry is measured independently after its next-M5
open fill, so MFE/MAE answers whether the entry itself has enough post-cost
movement to justify later exit optimisation.
"""
import argparse
import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts import replay_kernel_smoothing_red3_m1 as kernel
from scripts.replay_kernel_pump_combo_m5 import dynamic_activity_gate, pump_and_kernel_signals, resample, sma_seeded_ema


MS_5M = 5 * 60_000
HORIZONS = (3, 6, 12)
VARIANTS = ("pullback_reclaim", "activity_1h_150", "activity_1h_150_mfi55_rising")


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def missing_intervals(rows):
    return sum(max(0, (rows[index]["time"] - rows[index - 1]["time"]) // MS_5M - 1) for index in range(1, len(rows)))


def h1_regimes(rows):
    """Map each closed M5 bar to only the last fully closed H1 EMA regime."""
    h1 = resample(rows, 60)
    closes = [row["close"] for row in h1]
    ema21, ema50 = sma_seeded_ema(closes, 21), sma_seeded_ema(closes, 50)
    result, latest = {}, None
    for row in rows:
        while h1 and h1[0]["close_time"] <= row["close_time"]:
            current = h1.pop(0)
            index = len(result.get("_h1_seen", []))
            result.setdefault("_h1_seen", []).append(current)
            if ema21[index] is not None and ema50[index] is not None:
                latest = "h1_bullish" if current["close"] > ema21[index] > ema50[index] else "h1_not_bullish"
        result[row["close_time"]] = latest or "h1_unready"
    result.pop("_h1_seen", None)
    return result


def net_return(entry_fill, exit_raw_price, cost_multiplier):
    """Return of a fixed allocation, including entry/exit fees and execution costs."""
    allocation = 1.0
    notional = allocation / (1.0 + config.COMMISSION_PCT * cost_multiplier)
    qty = notional / entry_fill
    proceeds = qty * kernel.sell_fill(exit_raw_price, cost_multiplier)
    return proceeds * (1.0 - config.COMMISSION_PCT * cost_multiplier) - allocation


def edge_event(rows, signal_index, horizon, cost_multiplier, regime):
    entry_index = signal_index + 1
    end_index = entry_index + horizon - 1
    if end_index >= len(rows):
        return None
    entry_raw = rows[entry_index]["open"]
    entry_fill = kernel.buy_fill(entry_raw, cost_multiplier)
    highs = [row["high"] for row in rows[entry_index:end_index + 1]]
    lows = [row["low"] for row in rows[entry_index:end_index + 1]]
    max_high, min_low = max(highs), min(lows)
    entry_atr = kernel.atr(rows[:signal_index + 1], 14)[-1]
    if entry_atr is None or entry_atr <= 0:
        return None
    # The execution model treats this as the price that merely covers both
    # transaction sides.  A 0.5 ATR target must clear this price too.
    # ``allocation`` also funds the entry commission.  Therefore the raw exit
    # price must recover the ``(1 + entry_fee)`` notional factor as well as the
    # sell-side commission, spread and slippage.  Omitting this factor makes a
    # break-even reachability rate look too optimistic even though terminal
    # net-return calculations remain correct.
    break_even_raw = entry_fill * (1.0 + config.COMMISSION_PCT * cost_multiplier) / (
        (1.0 - config.COMMISSION_PCT * cost_multiplier) *
        (1.0 - cost_multiplier * (config.BACKTEST_ASSUMED_SPREAD_PCT / 2.0 + config.ESTIMATED_SLIPPAGE_PCT))
    )
    target_raw = max(break_even_raw, entry_fill + 0.5 * entry_atr)
    close_raw = rows[end_index]["close"]
    return {
        "signal_time": rows[signal_index]["close_time"], "entry_time": rows[entry_index]["time"],
        "regime": regime, "mfe_pct": max_high / entry_fill - 1.0, "mae_pct": min_low / entry_fill - 1.0,
        "close_net_return_pct": net_return(entry_fill, close_raw, cost_multiplier),
        "cost_recovered": max_high >= break_even_raw,
        "cost_plus_half_atr_reached": max_high >= target_raw,
        "target_distance_pct": target_raw / entry_fill - 1.0,
    }


def summarize(events):
    if not events:
        return {"signals": 0}
    count = len(events)
    return {
        "signals": count,
        "median_mfe_pct": round(sorted(event["mfe_pct"] for event in events)[count // 2] * 100, 4),
        "median_mae_pct": round(sorted(event["mae_pct"] for event in events)[count // 2] * 100, 4),
        "mean_close_net_return_pct": round(sum(event["close_net_return_pct"] for event in events) / count * 100, 4),
        "cost_recovery_rate_pct": round(sum(event["cost_recovered"] for event in events) / count * 100, 2),
        "cost_plus_half_atr_rate_pct": round(sum(event["cost_plus_half_atr_reached"] for event in events) / count * 100, 2),
        "median_target_distance_pct": round(sorted(event["target_distance_pct"] for event in events)[count // 2] * 100, 4),
    }


async def fetch(symbol, days, cutoff, semaphore):
    async with semaphore:
        try:
            raw = await historical_klines(symbol, "5m", days, cutoff)
            return symbol, kernel.normalize(raw, cutoff), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    cutoff = (int(time.time() * 1000) - args.end_minutes_ago * 60_000) // MS_5M * MS_5M - 1
    start = cutoff - args.hours * 3_600_000
    # At least one extra day is fetched exclusively for completed higher-TF
    # context and initial indicator state; no event before start can be counted.
    symbols = [value.strip().upper().replace("_", "") for value in args.symbols]
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, cutoff, semaphore) for symbol in symbols))
    all_events = {variant: {horizon: [] for horizon in HORIZONS} for variant in VARIANTS}
    per_symbol, errors = {}, {}
    for symbol, rows, error in loaded:
        provenance = {"m5_closed_candles": len(rows), "m5_missing_intervals": missing_intervals(rows)}
        if error or len(rows) < 400:
            errors[symbol] = error or "insufficient completed M5 history"
            per_symbol[symbol] = {"provenance": provenance, "error": errors[symbol]}
            continue
        signals, signal_meta, mfi_gate = pump_and_kernel_signals(rows, 55.0, True)
        activity_gate, activity_meta = dynamic_activity_gate(rows, 12, args.min_quote_turnover_try, 1.5)
        candidate = signals["pump_pullback_reclaim_kernel"]
        variants = {
            "pullback_reclaim": candidate,
            "activity_1h_150": [value and activity_gate[index] for index, value in enumerate(candidate)],
            "activity_1h_150_mfi55_rising": [value and activity_gate[index] and mfi_gate[index] for index, value in enumerate(candidate)],
        }
        regimes = h1_regimes(rows)
        per_symbol_events = {variant: {horizon: [] for horizon in HORIZONS} for variant in VARIANTS}
        for variant, entries in variants.items():
            for index, enabled in enumerate(entries):
                if not enabled or not (start <= rows[index]["close_time"] <= cutoff):
                    continue
                for horizon in HORIZONS:
                    event = edge_event(rows, index, horizon, args.cost_multiplier, regimes.get(rows[index]["close_time"], "h1_unready"))
                    if event:
                        all_events[variant][horizon].append({"symbol": symbol, **event})
                        per_symbol_events[variant][horizon].append(event)
        per_symbol[symbol] = {"provenance": {**provenance, **signal_meta, "activity": activity_meta},
                              "entry_edge": {variant: {str(horizon): summarize(values) for horizon, values in horizons.items()} for variant, horizons in per_symbol_events.items()}}

    aggregates, folds = {}, {}
    fold_ms = args.hours * 3_600_000 // 3
    for variant, horizons in all_events.items():
        aggregates[variant] = {}
        for horizon, events in horizons.items():
            by_regime = defaultdict(list)
            for event in events:
                by_regime[event["regime"]].append(event)
            aggregates[variant][str(horizon)] = {"overall": summarize(events), "by_h1_regime": {regime: summarize(values) for regime, values in sorted(by_regime.items())}}
        folds[variant] = {}
        for fold in range(3):
            fold_start, fold_end = start + fold * fold_ms, start + (fold + 1) * fold_ms
            folds[variant][f"oos_fold_{fold + 1}"] = {
                "window": {"start": iso(fold_start), "end": iso(fold_end - 1)},
                "horizons": {str(horizon): summarize([event for event in events if fold_start <= event["signal_time"] < fold_end]) for horizon, events in horizons.items()},
            }
    result = {
        "paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours, "three_chronological_oos_folds": True},
        "source": "Binance TR public /api/v3/klines completed M5 OHLCV",
        "symbols": symbols,
        "entry_rule": "Pump Monitor arm -> 0.25-0.80 ATR pullback holding M5 EMA21 -> reclaim above pullback high and EMA9 while kernel green; enter next M5 open",
        "variants": {"pullback_reclaim": "entry rule only", "activity_1h_150": "entry rule + causal 1h quote-turnover acceleration >=1.5x, current M5 volume ratio >=1.2, positive candle-volume proxy and 15m range", "activity_1h_150_mfi55_rising": "activity variant + MFI(14)>=55 and rising"},
        "measurement": {"horizons_m5_bars": list(HORIZONS), "mfe_mae": "entry-open to future highs/lows; no exit rule is used", "cost_recovery": "future high can close at or above modeled round-trip break-even", "cost_plus_half_atr": "future high reaches max(round-trip break-even, entry fill + 0.5 ATR(14))", "close_net_return": "hypothetical close at the final completed bar of each horizon, after modeled costs"},
        "execution_costs": {"commission_pct_each_side": config.COMMISSION_PCT * args.cost_multiplier, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier},
        "aggregate": aggregates, "chronological_oos_folds": folds, "per_symbol": per_symbol, "errors": errors,
        "limitations": ["Each signal is measured independently; this is entry-quality research, not a shared-capital or one-position portfolio replay.", "Public OHLCV lacks historical bid-ask spread, depth and intrabar order sequence.", "The candle-volume pressure condition is a directional-volume proxy, not real order flow or CVD.", "Results may guide only further paper testing; they do not activate a strategy."],
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {variant: {horizon: summary["overall"] for horizon, summary in values.items()} for variant, values in aggregates.items()}
    print("RESULT_JSON=" + json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=config.SYMBOLS)
    parser.add_argument("--hours", type=int, default=720)
    parser.add_argument("--fetch-days", type=int, default=34)
    parser.add_argument("--end-minutes-ago", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--min-quote-turnover-try", type=float, default=41_666.67)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.hours < 3 or args.fetch_days * 24 < args.hours + 30 or args.cost_multiplier <= 0:
        parser.error("hours>=3, positive cost multiplier and sufficient warm-up history are required")
    asyncio.run(main(args))
