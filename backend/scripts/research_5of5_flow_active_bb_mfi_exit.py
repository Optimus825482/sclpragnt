"""Apply the active BB-MFI fixed TP/SL price levels to the flow candidate."""

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.config import config
from scripts.research_5of5_flow_take_profit import DEFAULT_SYMBOLS, exit_net_pct, summary
from scripts.research_5of5_spike_score import build_symbol_events
from scripts.research_m1_cache import cached_m1


HOLD_MINUTES = 15


def simulate(m1, entry_index):
    entry = m1[entry_index]["open"] * (1 + config.BACKTEST_ASSUMED_SPREAD_PCT / 2 + config.ESTIMATED_SLIPPAGE_PCT)
    bars = m1[entry_index:entry_index + HOLD_MINUTES]
    if len(bars) < HOLD_MINUTES:
        return None
    target = entry * (1 + config.BB_MFI_TAKE_PROFIT_PCT)
    stop = entry * (1 - config.BB_MFI_STOP_LOSS_PCT)
    peak, trough = entry, entry
    for hold, bar in enumerate(bars, start=1):
        peak, trough = max(peak, bar["high"]), min(trough, bar["low"])
        # Conservative adverse-first sequencing when one OHLC bar spans both.
        if bar["low"] <= stop:
            return {"net_pct": exit_net_pct(entry, min(stop, bar["low"])), "exit_reason": "active_bb_mfi_stop", "hold_minutes": hold,
                    "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100}
        if bar["high"] >= target:
            return {"net_pct": exit_net_pct(entry, target), "exit_reason": "active_bb_mfi_take_profit", "hold_minutes": hold,
                    "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100}
    return {"net_pct": exit_net_pct(entry, bars[-1]["close"]), "exit_reason": "research_15m_time_limit", "hold_minutes": HOLD_MINUTES,
            "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS)); parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--end-ms", type=int, required=True); parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--oos-fraction", type=float, default=.30); parser.add_argument("--output", default="research_5of5_flow_active_bb_mfi_exit.json")
    args = parser.parse_args(); end = datetime.fromtimestamp(args.end_ms / 1000, timezone.utc); start = end - timedelta(days=args.days)
    cutoff = start + (end - start) * (1 - args.oos_fraction); cutoff_ms = int(cutoff.timestamp() * 1000)
    records, provenance = [], {}
    for symbol in args.symbols:
        rows, cache = await cached_m1(symbol, int(start.timestamp() * 1000), args.end_ms, args.cache_dir)
        provenance[symbol] = {"m1_closed_candles": len(rows), "cache": cache}; events, _ = build_symbol_events(symbol, rows)
        index_by_time = {row["time"]: index for index, row in enumerate(rows)}
        for event in events:
            if event["score"] < 4 or not event["components"]["positive_volume_flow"]: continue
            index = index_by_time.get(event["entry_time"])
            result = simulate(rows, index) if index is not None else None
            if result: records.append({"symbol": symbol, "signal_time": event["signal_time"], "score": event["score"], "result": result})
    records.sort(key=lambda item: item["signal_time"])
    payload = {"research_only": True, "generated_at": datetime.now(timezone.utc).isoformat(), "source": "cached Binance TR public historical M1 OHLCV",
               "window": {"start": start.isoformat(), "end": end.isoformat(), "days": args.days}, "oos_start": cutoff.isoformat(),
               "candidate": "score >=4 AND positive M1/M5 volume-flow component", "entry": "unchanged causal first EMA9/VWAP hold; next M1 open",
               "exit": {"take_profit_pct": config.BB_MFI_TAKE_PROFIT_PCT, "stop_loss_pct": config.BB_MFI_STOP_LOSS_PCT,
                        "active_strategy": config.ACTIVE_STRATEGY, "research_time_limit_minutes": HOLD_MINUTES,
                        "note": "The active BB-MFI 5m sell signal is not applied because this experiment changes only TP/SL price points."},
               "costs": "active commission, spread and slippage config", "provenance": provenance,
               "all": summary(records), "in_sample": summary([item for item in records if item["signal_time"] < cutoff_ms]),
               "oos": summary([item for item in records if item["signal_time"] >= cutoff_ms]), "records": records}
    with open(args.output, "w", encoding="utf-8") as handle: json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload["oos"], ensure_ascii=False, indent=2))


if __name__ == "__main__": asyncio.run(main())
