"""Paper-only regime selection for pre-declared M5 breakout/retest entries.

The development half chooses at most one simple regime-score threshold per
entry family.  The following chronological half evaluates the frozen choice.
No sell rule, target, or shared portfolio is modelled here: this is an
exit-independent test of whether a regime creates post-cost entry edge.
"""
import argparse
import asyncio
import json
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts import replay_kernel_smoothing_red3_m1 as kernel
from scripts.replay_kernel_pump_combo_m5 import resample, sma_seeded_ema
from scripts.research_breakout_retest_entry_edge_m5 import VARIANTS, h1_bullish_map, signals
from scripts.research_kernel_entry_edge_m5 import edge_event, iso, missing_intervals, summarize


MS_5M = 5 * 60_000
HORIZON = 12


def round_trip_break_even_pct(cost_multiplier):
    entry = kernel.buy_fill(100.0, cost_multiplier)
    raw_exit = entry * (1.0 + config.COMMISSION_PCT * cost_multiplier) / (
        (1.0 - config.COMMISSION_PCT * cost_multiplier) *
        (1.0 - cost_multiplier * (config.BACKTEST_ASSUMED_SPREAD_PCT / 2.0 + config.ESTIMATED_SLIPPAGE_PCT))
    )
    return raw_exit / entry - 1.0


def h4_bullish_map(rows):
    h4 = resample(rows, 240)
    closes = [row["close"] for row in h4]
    ema9, ema21, ema50 = (sma_seeded_ema(closes, period) for period in (9, 21, 50))
    output, index, latest = {}, 0, False
    for row in rows:
        while index < len(h4) and h4[index]["close_time"] <= row["close_time"]:
            latest = bool(ema9[index] is not None and ema21[index] is not None and ema50[index] is not None and index > 0 and
                          ema9[index - 1] is not None and h4[index]["close"] > ema9[index] > ema21[index] > ema50[index] and ema9[index] > ema9[index - 1])
            index += 1
        output[row["close_time"]] = latest
    return output


def regime_score(rows, cost_multiplier):
    """Four causal, pre-declared components; current bar is fully closed."""
    closes, volumes = [row["close"] for row in rows], [row["volume"] for row in rows]
    atr14 = kernel.atr(rows, 14)
    h4 = h4_bullish_map(rows)
    widths, percentiles, output = [], [None] * len(rows), []
    for index, row in enumerate(rows):
        if index >= 19:
            window = closes[index - 19:index + 1]
            mean = sum(window) / 20.0
            width = (4.0 * math.sqrt(sum((value - mean) ** 2 for value in window) / 20.0) / mean) if mean > 0 else None
        else:
            width = None
        widths.append(width)
        historical = [value for value in widths[max(0, index - 288):index] if value is not None]
        if width is not None and len(historical) >= 100:
            percentiles[index] = sum(value <= width for value in historical) / len(historical)
        current_hour = sum(volumes[index - 11:index + 1]) if index >= 11 else None
        prior_hour = sum(volumes[index - 23:index - 11]) if index >= 23 else None
        volume_expansion = bool(current_hour is not None and prior_hour and current_hour > prior_hour)
        atr_capacity = bool(atr14[index] is not None and row["close"] > 0 and atr14[index] / row["close"] >= round_trip_break_even_pct(cost_multiplier))
        bb_expansion = percentiles[index] is not None and percentiles[index] >= .70
        components = {"h4_bullish": bool(h4.get(row["close_time"], False)), "atr_cost_capacity": atr_capacity,
                      "bb_width_top30pct": bb_expansion, "volume_1h_expansion": volume_expansion}
        output.append({"score": sum(components.values()), "components": components, "bb_width_percentile": percentiles[index]})
    return output


async def fetch(symbol, days, cutoff, semaphore):
    async with semaphore:
        try:
            raw = await historical_klines(symbol, "5m", days, cutoff)
            return symbol, kernel.normalize(raw, cutoff), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


def select_threshold(events):
    """Development-only choice: positive 60m net mean, >=20 samples, then highest mean."""
    eligible = []
    scores = sorted({event["regime_score"] for event in events})
    candidates = {}
    for threshold in scores:
        summary = summarize([event for event in events if event["regime_score"] >= threshold])
        candidates[str(threshold)] = summary
        if summary.get("signals", 0) >= 20 and summary.get("mean_close_net_return_pct", 0.0) > 0.0:
            eligible.append((summary["mean_close_net_return_pct"], summary["signals"], threshold))
    chosen = max(eligible) if eligible else None
    return (chosen[2] if chosen else None), candidates


async def main(args):
    cutoff = (int(time.time() * 1000) - args.end_minutes_ago * 60_000) // MS_5M * MS_5M - 1
    oos_start = cutoff - args.oos_hours * 3_600_000
    development_start = oos_start - args.development_hours * 3_600_000
    symbols = [value.strip().upper().replace("_", "") for value in args.symbols]
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, cutoff, asyncio.Semaphore(args.concurrency)) for symbol in symbols))
    events = {variant: {"development": [], "oos": []} for variant in VARIANTS}
    errors, provenance = {}, {}
    for symbol, rows, error in loaded:
        provenance[symbol] = {"m5_closed_candles": len(rows), "m5_missing_intervals": missing_intervals(rows)}
        if error or len(rows) < 2_500:
            errors[symbol] = error or "insufficient M5 history for H4 EMA50 and regime percentile warm-up"; continue
        h1, setup_signals, regimes = h1_bullish_map(rows), signals(rows), regime_score(rows, args.cost_multiplier)
        for variant, values in setup_signals.items():
            for index, hit in enumerate(values):
                signal_time = rows[index]["close_time"]
                partition = "development" if development_start <= signal_time < oos_start else "oos" if oos_start <= signal_time <= cutoff else None
                if not partition or not hit or not h1.get(signal_time, False):
                    continue
                event = edge_event(rows, index, HORIZON, args.cost_multiplier, "h1_bullish")
                if event:
                    events[variant][partition].append({"symbol": symbol, "regime_score": regimes[index]["score"], "regime_components": regimes[index]["components"], **event})
    result_variants = {}
    for variant, partitions in events.items():
        chosen, development_candidates = select_threshold(partitions["development"])
        oos_events = [event for event in partitions["oos"] if chosen is not None and event["regime_score"] >= chosen]
        result_variants[variant] = {
            "development_threshold_candidates": development_candidates,
            "frozen_selected_score_gte": chosen,
            "development_selected": summarize([event for event in partitions["development"] if chosen is not None and event["regime_score"] >= chosen]),
            "oos_selected": summarize(oos_events),
            "oos_unfiltered_baseline": summarize(partitions["oos"]),
            "development_signals": len(partitions["development"]), "oos_signals_before_regime": len(partitions["oos"]),
        }
    result = {
        "paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Binance TR public /api/v3/klines completed M5 OHLCV",
        "symbols": symbols,
        "windows": {"development": {"start": iso(development_start), "end": iso(oos_start - 1), "hours": args.development_hours}, "oos": {"start": iso(oos_start), "end": iso(cutoff), "hours": args.oos_hours}},
        "entry_families": {"keltner_retest_h1": "existing Keltner-style M5 breakout/retest + completed H1 bullish stack", "donchian20_retest_h1": "M5 Donchian-20 breakout then later 3-bar retest + completed H1 bullish stack"},
        "regime_score": {"h4_bullish": "completed H4 close>EMA9>EMA21>EMA50 and EMA9 rising", "atr_cost_capacity": "M5 ATR14 percent >= modeled round-trip break-even percent", "bb_width_top30pct": "M5 BB(20,2) width at or above its trailing completed-24h 70th percentile", "volume_1h_expansion": "completed last 12 M5 volume > preceding 12 M5 volume", "selection": "development-only score threshold with >=20 signals and positive 60-minute mean net return; frozen before OOS"},
        "measurement": {"horizon": "12 completed M5 bars after next-M5-open entry", "costs": {"commission_pct_each_side": config.COMMISSION_PCT * args.cost_multiplier, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier, "round_trip_break_even_move_pct": round(round_trip_break_even_pct(args.cost_multiplier) * 100, 4)}},
        "variants": result_variants, "provenance": provenance, "errors": errors,
        "limitations": ["This chooses a regime threshold on development data and evaluates only that frozen choice in OOS.", "No exit, target or portfolio is simulated; this is entry-edge evidence only.", "Public OHLCV lacks historical bid-ask, depth and intrabar execution order.", "No result can activate a strategy without later fee-stress and shared-portfolio validation."],
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps({variant: {"selected": values["frozen_selected_score_gte"], "oos": values["oos_selected"], "oos_baseline": values["oos_unfiltered_baseline"]} for variant, values in result_variants.items()}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=config.SYMBOLS)
    parser.add_argument("--development-hours", type=int, default=720)
    parser.add_argument("--oos-hours", type=int, default=720)
    parser.add_argument("--fetch-days", type=int, default=70)
    parser.add_argument("--end-minutes-ago", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.development_hours < 24 or args.oos_hours < 24 or args.fetch_days * 24 < args.development_hours + args.oos_hours + 250 or args.cost_multiplier <= 0:
        parser.error("positive costs plus sufficient H4/percentile warm-up history are required")
    asyncio.run(main(args))
