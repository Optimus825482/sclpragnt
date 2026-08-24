"""Paper-only M5 breakout/retest entry-quality research.

Two pre-declared entry families are compared without any discretionary exit:
1) the existing Keltner-style breakout/retest contract; and
2) a strict Donchian-20 breakout followed by a later retest within three M5 bars.
Both require a completed H1 bullish EMA stack.  Every entry is independently
measured after the next M5 open, so no later exit choice can manufacture edge.
"""
import argparse
import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts import replay_kernel_smoothing_red3_m1 as kernel
from scripts.replay_kernel_pump_combo_m5 import resample, sma_seeded_ema
from scripts.research_kernel_entry_edge_m5 import HORIZONS, edge_event, iso, missing_intervals, summarize


MS_5M = 5 * 60_000
VARIANTS = ("keltner_retest_h1", "donchian20_retest_h1")


def h1_bullish_map(rows):
    """Use only the last fully completed H1 candle at each M5 close."""
    h1 = resample(rows, 60)
    closes = [row["close"] for row in h1]
    ema9, ema21, ema50 = (sma_seeded_ema(closes, period) for period in (9, 21, 50))
    output, h1_index, last = {}, 0, False
    for row in rows:
        while h1_index < len(h1) and h1[h1_index]["close_time"] <= row["close_time"]:
            current = h1[h1_index]
            last = bool(ema9[h1_index] is not None and ema21[h1_index] is not None and ema50[h1_index] is not None and
                        h1_index > 0 and ema9[h1_index - 1] is not None and
                        current["close"] > ema9[h1_index] > ema21[h1_index] > ema50[h1_index] and ema9[h1_index] > ema9[h1_index - 1])
            h1_index += 1
        output[row["close_time"]] = last
    return output


def signals(rows):
    """Causal M5 signals; no future bar confirms either setup."""
    closes = [row["close"] for row in rows]
    volumes = [row["volume"] for row in rows]
    ema20, atr20 = kernel.ema(closes, 20), kernel.atr(rows, 20)
    output = {variant: [False] * len(rows) for variant in VARIANTS}
    armed_until, level = -1, None
    for index, row in enumerate(rows):
        prior_volume = sum(volumes[index - 20:index]) / 20.0 if index >= 20 else None
        volume_keltner = prior_volume is not None and row["volume"] >= prior_volume * 1.5
        if index >= 1 and ema20[index] is not None and atr20[index] is not None and ema20[index - 1] is not None and atr20[index - 1] is not None:
            upper, prior_upper = ema20[index] + 1.8 * atr20[index], ema20[index - 1] + 1.8 * atr20[index - 1]
            was_below = rows[index - 1]["close"] <= prior_upper
            retest = row["low"] <= upper * 1.001 and row["close"] > upper
            output["keltner_retest_h1"][index] = was_below and retest and volume_keltner
        # A true structural retest cannot signal on its own breakout bar.
        if level is not None and index > armed_until:
            level = None
        if level is not None and index <= armed_until:
            if row["low"] <= level * 1.001 and row["close"] > level and prior_volume is not None and row["volume"] >= prior_volume * 1.2:
                output["donchian20_retest_h1"][index] = True
                level = None
        if index >= 20 and prior_volume is not None:
            breakout_level = max(item["high"] for item in rows[index - 20:index])
            if row["close"] > breakout_level and row["volume"] >= prior_volume * 1.2:
                level, armed_until = breakout_level, index + 3
    return output


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
    symbols = [value.strip().upper().replace("_", "") for value in args.symbols]
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, cutoff, asyncio.Semaphore(args.concurrency)) for symbol in symbols))
    all_events = {variant: {horizon: [] for horizon in HORIZONS} for variant in VARIANTS}
    per_symbol, errors = {}, {}
    for symbol, rows, error in loaded:
        provenance = {"m5_closed_candles": len(rows), "m5_missing_intervals": missing_intervals(rows)}
        if error or len(rows) < 700:
            errors[symbol] = error or "insufficient M5 history for completed H1 EMA50 context"
            per_symbol[symbol] = {"provenance": provenance, "error": errors[symbol]}
            continue
        h1_ok, signals_by_variant = h1_bullish_map(rows), signals(rows)
        symbol_events = {variant: {horizon: [] for horizon in HORIZONS} for variant in VARIANTS}
        for variant, values in signals_by_variant.items():
            for index, hit in enumerate(values):
                if not hit or not h1_ok.get(rows[index]["close_time"], False) or not (start <= rows[index]["close_time"] <= cutoff):
                    continue
                for horizon in HORIZONS:
                    event = edge_event(rows, index, horizon, args.cost_multiplier, "h1_bullish")
                    if event:
                        all_events[variant][horizon].append({"symbol": symbol, **event})
                        symbol_events[variant][horizon].append(event)
        per_symbol[symbol] = {"provenance": provenance, "entry_edge": {variant: {str(horizon): summarize(events) for horizon, events in values.items()} for variant, values in symbol_events.items()}}

    aggregate, folds = {}, {}
    fold_ms = args.hours * 3_600_000 // 3
    for variant, by_horizon in all_events.items():
        aggregate[variant] = {str(horizon): summarize(events) for horizon, events in by_horizon.items()}
        folds[variant] = {}
        for fold in range(3):
            fold_start, fold_end = start + fold * fold_ms, start + (fold + 1) * fold_ms
            folds[variant][f"oos_fold_{fold + 1}"] = {"window": {"start": iso(fold_start), "end": iso(fold_end - 1)},
                                                         "horizons": {str(horizon): summarize([event for event in events if fold_start <= event["signal_time"] < fold_end]) for horizon, events in by_horizon.items()}}
    result = {
        "paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours, "three_chronological_oos_folds": True},
        "source": "Binance TR public /api/v3/klines completed M5 OHLCV",
        "symbols": symbols,
        "variants": {
            "keltner_retest_h1": "M5 EMA20 + 1.8*ATR20 upper-band transition/retest, volume >= 1.5x prior-20-M5 average, completed H1 price>EMA9>EMA21>EMA50 and EMA9 rising",
            "donchian20_retest_h1": "M5 close above preceding 20-M5 high with >=1.2x volume arms a 3-bar window; later M5 retests the prior high and closes above it with >=1.2x volume; same completed H1 trend",
        },
        "measurement": {"horizons_m5_bars": list(HORIZONS), "entry": "next M5 open", "mfe_mae": "entry-open to future highs/lows; no exit rule", "cost_recovery": "future high reaches modeled round-trip break-even", "cost_plus_half_atr": "future high reaches max(round-trip break-even, entry fill + 0.5 ATR14)", "close_net_return": "hypothetical horizon-close return after modeled costs"},
        "execution_costs": {"commission_pct_each_side": config.COMMISSION_PCT * args.cost_multiplier, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier},
        "aggregate": aggregate, "chronological_oos_folds": folds, "per_symbol": per_symbol, "errors": errors,
        "limitations": ["Independent-entry measurement is not a portfolio or exit backtest.", "Public OHLCV has no historical bid-ask, depth, or intrabar execution order.", "No activity, MFI, or directional-volume proxy is applied; this deliberately isolates the new price/volume structure.", "This is research-only and cannot activate a strategy."],
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps(aggregate, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=config.SYMBOLS)
    parser.add_argument("--hours", type=int, default=720)
    parser.add_argument("--fetch-days", type=int, default=34)
    parser.add_argument("--end-minutes-ago", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.hours < 3 or args.fetch_days * 24 < args.hours + 55 or args.cost_multiplier <= 0:
        parser.error("hours>=3, positive cost multiplier and sufficient H1 warm-up history are required")
    asyncio.run(main(args))
