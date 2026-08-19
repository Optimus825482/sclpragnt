"""Apply active BB-MFI TP, SL and closed-5m sell exit to the flow candidate."""

import argparse
import asyncio
import bisect
import json
import math
from datetime import datetime, timedelta, timezone

from app.config import config
from scripts.research_5of5_flow_take_profit import DEFAULT_SYMBOLS, exit_net_pct, summary
from scripts.research_5of5_spike_score import build_symbol_events
from scripts.research_m1_cache import cached_m1
from scripts.research_mtf_5of5_managed_replay import resample


def active_sell_flags(rows):
    """Linear-time equivalent of the active v3 BB/MFI closed-candle sell rule."""
    length = len(rows); flags = [False] * length
    bb_period, rsi_period, mfi_period = config.BB_MFI_BB_PERIOD, config.BB_MFI_RSI_PERIOD, config.BB_MFI_MFI_PERIOD
    closes = [row["close"] for row in rows]; total = squares = 0.0
    gains = losses = 0.0; average_gain = average_loss = None
    pos = [0.0] * length; neg = [0.0] * length; pos_sum = neg_sum = 0.0
    for i, row in enumerate(rows):
        close = closes[i]; total += close; squares += close * close
        if i >= bb_period:
            old = closes[i - bb_period]; total -= old; squares -= old * old
        if i:
            delta = close - closes[i - 1]; gain, loss = max(delta, 0.0), max(-delta, 0.0)
            if i <= rsi_period:
                gains += gain; losses += loss
                if i == rsi_period: average_gain, average_loss = gains / rsi_period, losses / rsi_period
            else:
                average_gain = (average_gain * (rsi_period - 1) + gain) / rsi_period
                average_loss = (average_loss * (rsi_period - 1) + loss) / rsi_period
            typical = (row["high"] + row["low"] + row["close"]) / 3
            previous_typical = (rows[i-1]["high"] + rows[i-1]["low"] + rows[i-1]["close"]) / 3
            if typical > previous_typical: pos[i] = typical * row["volume"]
            elif typical < previous_typical: neg[i] = typical * row["volume"]
            pos_sum += pos[i]; neg_sum += neg[i]
            if i > mfi_period:
                pos_sum -= pos[i - mfi_period]; neg_sum -= neg[i - mfi_period]
        if i < max(bb_period - 1, rsi_period, mfi_period):
            continue
        mean = total / bb_period; upper = mean + config.BB_MFI_BB_STD_DEV * math.sqrt(max(0.0, squares / bb_period - mean * mean))
        rsi = 100.0 if not average_loss else 100 - 100 / (1 + average_gain / average_loss)
        mfi = 100.0 if not neg_sum else 100 - 100 / (1 + pos_sum / neg_sum)
        flags[i] = close > upper and rsi > config.BB_MFI_EXIT_RSI_MIN and mfi > config.BB_MFI_EXIT_MFI_MIN
    return flags


def simulate(m1, m5, m5_close_times, sell_flags, entry_index):
    entry = m1[entry_index]["open"] * (1 + config.BACKTEST_ASSUMED_SPREAD_PCT / 2 + config.ESTIMATED_SLIPPAGE_PCT)
    target, stop = entry * (1 + config.BB_MFI_TAKE_PROFIT_PCT), entry * (1 - config.BB_MFI_STOP_LOSS_PCT)
    peak, trough = entry, entry
    for index in range(entry_index, len(m1)):
        row = m1[index]; peak, trough = max(peak, row["high"]), min(trough, row["low"]); hold = index - entry_index + 1
        if row["low"] <= stop:
            return {"net_pct": exit_net_pct(entry, min(stop, row["low"])), "exit_reason": "active_bb_mfi_stop", "hold_minutes": hold, "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100, "realized": True}
        if row["high"] >= target:
            return {"net_pct": exit_net_pct(entry, target), "exit_reason": "active_bb_mfi_take_profit", "hold_minutes": hold, "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100, "realized": True}
        m5_index = bisect.bisect_left(m5_close_times, row["close_time"])
        if m5_index < len(m5_close_times) and m5_close_times[m5_index] == row["close_time"] and sell_flags[m5_index]:
            return {"net_pct": exit_net_pct(entry, row["close"]), "exit_reason": "active_bb_mfi_v3_signal_exit", "hold_minutes": hold, "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100, "realized": True}
    return {"net_pct": exit_net_pct(entry, m1[-1]["close"]), "exit_reason": "end_of_data_mark_to_market", "hold_minutes": len(m1) - entry_index, "max_up_pct": (peak / entry - 1) * 100, "max_down_pct": (trough / entry - 1) * 100, "realized": False}


async def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS)); parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--end-ms", type=int, required=True); parser.add_argument("--cache-dir", required=True); parser.add_argument("--oos-fraction", type=float, default=.30); parser.add_argument("--output", default="research_5of5_flow_active_exit.json")
    args = parser.parse_args(); end = datetime.fromtimestamp(args.end_ms / 1000, timezone.utc); start = end - timedelta(days=args.days); cutoff = start + (end-start)*(1-args.oos_fraction); cutoff_ms = int(cutoff.timestamp()*1000)
    records, provenance = [], {}
    for symbol in args.symbols:
        m1, cache = await cached_m1(symbol, int(start.timestamp()*1000), args.end_ms, args.cache_dir); m5 = resample(m1, 5); flags = active_sell_flags(m5); m5_times = [row["close_time"] for row in m5]
        provenance[symbol] = {"m1_closed_candles": len(m1), "m5_closed_candles": len(m5), "cache": cache}; events, _ = build_symbol_events(symbol, m1); indexes = {row["time"]: i for i, row in enumerate(m1)}
        for event in events:
            if event["score"] < 4 or not event["components"]["positive_volume_flow"]: continue
            idx = indexes.get(event["entry_time"]); result = simulate(m1, m5, m5_times, flags, idx) if idx is not None else None
            if result: records.append({"symbol": symbol, "signal_time": event["signal_time"], "score": event["score"], "components": event["components"], "features": event["features"], "result": result})
    records.sort(key=lambda item:item["signal_time"])
    payload = {"research_only": True, "generated_at": datetime.now(timezone.utc).isoformat(), "source": "cached Binance TR public historical M1 OHLCV", "window": {"start":start.isoformat(),"end":end.isoformat(),"days":args.days}, "oos_start":cutoff.isoformat(), "candidate":"score >=4 AND positive M1/M5 volume-flow component", "entry":"unchanged causal first EMA9/VWAP hold; next M1 open", "exit":{"take_profit_pct":config.BB_MFI_TAKE_PROFIT_PCT,"stop_loss_pct":config.BB_MFI_STOP_LOSS_PCT,"sell_signal":"active BB-MFI v3 closed 5m sell","no_15m_time_exit":True,"end_of_data":"mark-to-market only"}, "costs":"active commission, spread and slippage config", "provenance":provenance, "all":summary(records), "in_sample":summary([x for x in records if x["signal_time"]<cutoff_ms]), "oos":summary([x for x in records if x["signal_time"]>=cutoff_ms]), "records":records}
    with open(args.output,"w",encoding="utf-8") as handle: json.dump(payload,handle,ensure_ascii=False,indent=2)
    print(json.dumps(payload["oos"],ensure_ascii=False,indent=2))


if __name__ == "__main__": asyncio.run(main())
