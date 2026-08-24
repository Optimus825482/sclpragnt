"""Paper-only M15 continuation entry-quality test with completed H1 trend context."""
import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts import replay_kernel_smoothing_red3_m1 as kernel
from scripts.replay_kernel_pump_combo_m5 import sma_seeded_ema
from scripts.research_kernel_entry_edge_m5 import edge_event, iso, summarize


MS_15M = 15 * 60_000
HORIZONS = (4, 8, 16)  # 1h, 2h and 4h after the next M15-open fill.
VARIANTS = ("keltner_retest_h1", "donchian20_retest_h1")


def missing_intervals(rows):
    return sum(max(0, (rows[index]["time"] - rows[index - 1]["time"]) // MS_15M - 1) for index in range(1, len(rows)))


def resample_m15(rows, minutes):
    """Resample completed M15 candles; the shared Pump helper assumes M5 input."""
    bucket_ms, required, groups = minutes * 60_000, minutes // 15, {}
    for row in rows:
        bucket = row["time"] - row["time"] % bucket_ms
        group = groups.get(bucket)
        if group is None:
            groups[bucket] = {"time": bucket, "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"], "volume": row["volume"], "close_time": row["close_time"], "count": 1}
        else:
            group["high"] = max(group["high"], row["high"]); group["low"] = min(group["low"], row["low"])
            group["close"] = row["close"]; group["volume"] += row["volume"]; group["close_time"] = row["close_time"]; group["count"] += 1
    return [row for _, row in sorted(groups.items()) if row["count"] == required]


def h1_bullish_map(rows):
    h1 = resample_m15(rows, 60)
    closes = [row["close"] for row in h1]
    ema9, ema21, ema50 = (sma_seeded_ema(closes, period) for period in (9, 21, 50))
    output, h1_index, last = {}, 0, False
    for row in rows:
        while h1_index < len(h1) and h1[h1_index]["close_time"] <= row["close_time"]:
            current = h1[h1_index]
            last = bool(ema9[h1_index] is not None and ema21[h1_index] is not None and ema50[h1_index] is not None and h1_index > 0 and ema9[h1_index - 1] is not None and
                        current["close"] > ema9[h1_index] > ema21[h1_index] > ema50[h1_index] and ema9[h1_index] > ema9[h1_index - 1])
            h1_index += 1
        output[row["close_time"]] = last
    return output


def signals(rows):
    closes, volumes = [row["close"] for row in rows], [row["volume"] for row in rows]
    ema20, atr20 = kernel.ema(closes, 20), kernel.atr(rows, 20)
    output = {name: [False] * len(rows) for name in VARIANTS}
    level, armed_until = None, -1
    for index, row in enumerate(rows):
        prior_volume = sum(volumes[index - 20:index]) / 20.0 if index >= 20 else None
        if index >= 1 and ema20[index] is not None and atr20[index] is not None and ema20[index - 1] is not None and atr20[index - 1] is not None:
            upper, prior_upper = ema20[index] + 1.8 * atr20[index], ema20[index - 1] + 1.8 * atr20[index - 1]
            output["keltner_retest_h1"][index] = bool(rows[index - 1]["close"] <= prior_upper and row["low"] <= upper * 1.001 and row["close"] > upper and prior_volume is not None and row["volume"] >= prior_volume * 1.5)
        if level is not None and index > armed_until:
            level = None
        if level is not None and index <= armed_until and prior_volume is not None and row["low"] <= level * 1.001 and row["close"] > level and row["volume"] >= prior_volume * 1.2:
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
            return symbol, kernel.normalize(await historical_klines(symbol, "15m", days, cutoff), cutoff), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    cutoff = (int(time.time() * 1000) - args.end_minutes_ago * 60_000) // MS_15M * MS_15M - 1
    start = cutoff - args.hours * 3_600_000
    symbols = [value.strip().upper().replace("_", "") for value in args.symbols]
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, cutoff, asyncio.Semaphore(args.concurrency)) for symbol in symbols))
    all_events = {variant: {horizon: [] for horizon in HORIZONS} for variant in VARIANTS}
    per_symbol, errors = {}, {}
    for symbol, rows, error in loaded:
        provenance = {"m15_closed_candles": len(rows), "m15_missing_intervals": missing_intervals(rows)}
        if error or len(rows) < 400:
            errors[symbol] = error or "insufficient completed M15 history"; per_symbol[symbol] = {"provenance": provenance, "error": errors[symbol]}; continue
        h1, entries = h1_bullish_map(rows), signals(rows)
        symbol_events = {variant: {horizon: [] for horizon in HORIZONS} for variant in VARIANTS}
        for variant, values in entries.items():
            for index, hit in enumerate(values):
                if not hit or not h1.get(rows[index]["close_time"], False) or not (start <= rows[index]["close_time"] <= cutoff):
                    continue
                for horizon in HORIZONS:
                    event = edge_event(rows, index, horizon, args.cost_multiplier, "h1_bullish")
                    if event:
                        all_events[variant][horizon].append({"symbol": symbol, **event})
                        symbol_events[variant][horizon].append(event)
        per_symbol[symbol] = {"provenance": provenance, "entry_edge": {variant: {str(horizon): summarize(events) for horizon, events in values.items()} for variant, values in symbol_events.items()}}
    fold_ms, aggregate, folds = args.hours * 3_600_000 // 3, {}, {}
    for variant, by_horizon in all_events.items():
        aggregate[variant] = {str(horizon): summarize(events) for horizon, events in by_horizon.items()}
        folds[variant] = {}
        for fold in range(3):
            fold_start, fold_end = start + fold * fold_ms, start + (fold + 1) * fold_ms
            folds[variant][f"oos_fold_{fold + 1}"] = {"window": {"start": iso(fold_start), "end": iso(fold_end - 1)}, "horizons": {str(horizon): summarize([event for event in events if fold_start <= event["signal_time"] < fold_end]) for horizon, events in by_horizon.items()}}
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(), "source": "Binance TR public /api/v3/klines completed M15 OHLCV", "symbols": symbols,
              "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours, "three_chronological_oos_folds": True},
              "variants": {"keltner_retest_h1": "M15 EMA20 + 1.8*ATR20 breakout/retest and volume >=1.5x prior 20 M15 candles, completed H1 bullish EMA stack", "donchian20_retest_h1": "M15 Donchian-20 breakout then later retest within 3 M15 bars, volume >=1.2x and completed H1 bullish EMA stack"},
              "measurement": {"horizons_m15_bars": list(HORIZONS), "entry": "next M15 open", "mfe_mae": "entry-open to future highs/lows; no exit rule", "close_net_return": "horizon-close return after modeled costs"},
              "execution_costs": {"commission_pct_each_side": config.COMMISSION_PCT * args.cost_multiplier, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier},
              "aggregate": aggregate, "chronological_oos_folds": folds, "per_symbol": per_symbol, "errors": errors,
              "limitations": ["Independent-entry test only; no exit or portfolio is simulated.", "Public OHLCV lacks historical bid-ask, depth and intrabar execution order.", "This is paper-only research and cannot activate a strategy."]}
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
    if args.hours < 3 or args.fetch_days * 24 < args.hours + 60 or args.cost_multiplier <= 0:
        parser.error("positive costs and sufficient H1 warm-up history are required")
    asyncio.run(main(args))
