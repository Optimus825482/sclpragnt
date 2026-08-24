"""24-hour, source-faithful Fisher M3 / Kernel M5 replay on the historical ACTIVE universe.

The ACTIVE gate selects which symbols are observed.  It does not change the
user-supplied Pine entry or exit rule.
"""
import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts.replay_fisher_m3_kernel_m5 import MS_1M, MS_5M, normalize, replay, resample


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def with_volume(raw, cutoff):
    rows = normalize(raw, cutoff)
    by_time = {int(item[0]): float(item[5]) for item in raw if len(item) >= 7 and int(item[6]) <= cutoff}
    for row in rows:
        row["volume"] = by_time.get(row["time"], 0.0)
    return rows


def m5_with_volume(rows):
    output = []
    for candle in resample(rows, MS_5M):
        members = [row for row in rows if candle["time"] <= row["time"] < candle["time"] + MS_5M]
        output.append({**candle, "volume": sum(row["volume"] for row in members)})
    return output


def atr_pct(rows, length=14):
    if len(rows) < length:
        return 0.0
    trs, previous = [], None
    for row in rows[-length:]:
        trs.append(row["high"] - row["low"] if previous is None else max(
            row["high"] - row["low"], abs(row["high"] - previous), abs(row["low"] - previous)))
        previous = row["close"]
    return sum(trs) / length / rows[-1]["close"] if rows[-1]["close"] else 0.0


def active_at_start(rows, start):
    m5 = [row for row in m5_with_volume(rows) if row["close_time"] <= start]
    if len(m5) < 288:
        return False, "insufficient_m5_history"
    quote_volume = sum(row["close"] * row["volume"] for row in m5[-288:])
    low = min(row["low"] for row in m5[-3:])
    range_pct = (max(row["high"] for row in m5[-3:]) - low) / low * 100 if low else 0.0
    average_volume = sum(row["volume"] for row in m5[-21:-1]) / 20
    volume_ratio = m5[-1]["volume"] / average_volume if average_volume else 0.0
    is_active = (quote_volume >= config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY
                 and range_pct >= config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT
                 and atr_pct(m5) >= config.SYMBOL_ACTIVITY_MIN_ATR_PCT
                 and volume_ratio >= config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO)
    return is_active, {"quote_volume_try": round(quote_volume, 2), "range_15m_pct": round(range_pct, 4),
                       "atr_pct": round(atr_pct(m5) * 100, 4), "volume_ratio": round(volume_ratio, 4)}


async def main(args):
    cutoff = int(time.time() * 1000) - 3 * MS_1M
    cutoff -= cutoff % MS_1M
    start = cutoff - args.hours * 3_600_000
    semaphore = asyncio.Semaphore(5)

    async def load(symbol):
        async with semaphore:
            try:
                return symbol, with_volume(await historical_klines(symbol, "1m", args.fetch_days, cutoff), cutoff), None
            except Exception as exc:
                return symbol, [], str(exc)

    loaded = await asyncio.gather(*(load(symbol) for symbol in config.SYMBOLS))
    active, skipped, results = {}, {}, {}
    for symbol, rows, error in loaded:
        if error or len(rows) < args.hours * 60 + 300:
            skipped[symbol] = error or "insufficient_closed_m1_history"
            continue
        eligible, metadata = active_at_start(rows, start)
        if not eligible:
            skipped[symbol] = metadata if isinstance(metadata, str) else "historical_activity_gate"
            continue
        active[symbol] = metadata
        value = replay(rows, start, cutoff, 0.001, 0.0)
        value.pop("trades_detail", None)
        results[symbol] = value
    trades = sum(value["trades"] for value in results.values())
    net = sum(value["net_pnl_try"] for value in results.values())
    result = {"paper_only": True, "strategy": "Fisher M3 Cross + Kernel M5 Renk - Long Only",
              "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "provenance": {"source": "Binance TR public completed M1 OHLCV", "timezone": "UTC",
                             "configured_symbols": list(config.SYMBOLS), "active_symbol_count": len(active)},
              "source_exact_execution": {"commission_pct_each_side": 0.001, "spread": 0.0, "slippage": 0.0,
                                          "allocation_pct_of_equity": 0.20, "pyramiding": 0,
                                          "fill": "next M1 open after closed M1 decision"},
              "activation_gate": "Historical platform ACTIVE gate only selects the M1-monitored universe; it is not a Pine entry condition.",
              "active_symbols_at_window_start": active, "skipped_symbols": skipped, "per_symbol": results,
              "aggregate_per_chart": {"symbols_with_trades": sum(value["trades"] > 0 for value in results.values()),
                                      "trades": trades, "net_pnl_try": round(net, 4),
                                      "fees_try": round(sum(value["fees_try"] for value in results.values()), 4)},
              "limitations": ["Each Pine chart starts with its own 10,000 TRY equity; aggregate PnL is not a shared-wallet portfolio.",
                              "Historical spread, depth, and intrabar ordering are unavailable."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE]")
    print("RESULT_JSON=" + json.dumps(result["aggregate_per_chart"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--fetch-days", type=int, default=4)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.hours <= 0 or args.fetch_days < 3:
        parser.error("hours pozitif, fetch-days en az 3 olmalı")
    asyncio.run(main(args))
