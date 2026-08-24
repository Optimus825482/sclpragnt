"""Paper-only causal comparison of Pump Monitor entries with kernel confirmation.

All variants share the same M5 red-3 kernel exit.  The only changing element is
the entry event: Pump Monitor alone, or Pump Monitor plus 1/2/3 closed green
kernel bars on the same completed M5 candle.
"""
import argparse
import asyncio
import json
import time
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, trading_symbols_with_filters
from scripts import replay_kernel_smoothing_red3_m1 as kernel
from scripts.replay_pump_monitor import resample, wilder_dmi


MS_5M = 5 * 60_000
VARIANTS = ("pump_only", "pump_kernel_green1", "pump_kernel_green2", "pump_kernel_green3",
            "pump_arm3_kernel_green1", "pump_arm3_kernel_green2", "pump_arm3_kernel_green3",
            "pump_pullback_reclaim_kernel", "pump_pullback_reclaim_m15_dmi")


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def missing_intervals(rows):
    return sum(max(0, (rows[index]["time"] - rows[index - 1]["time"]) // MS_5M - 1) for index in range(1, len(rows)))


def sma_seeded_ema(values, period):
    """Series equivalent of Pump Monitor's completed-candle EMA helper."""
    result, value, alpha = [], None, 2.0 / (period + 1)
    for index, current in enumerate(values):
        if index == period - 1:
            value = sum(values[:period]) / period
        elif index >= period and value is not None:
            value = alpha * current + (1.0 - alpha) * value
        result.append(value)
    return result


def dynamic_activity_gate(rows, turnover_bars=288, min_quote_turnover_try=1_000_000.0, relative_turnover_multiple=0.0):
    """Causal high-activity gate from public M5 candles, not real order flow.

    A bar is eligible only when it has sufficient trailing TRY turnover, current
    volume is elevated over its prior 20 bars, candle-volume pressure is positive
    over 20 bars, and the recent 15 minutes are not flat.
    """
    gate, quote_turnover, pressure, volumes = [], [], [], []
    quote_sum = pressure_sum = volume_sum = 0.0
    counts = {"total_bars": len(rows), "qualified_bars": 0, "quote_turnover_blocks": 0,
              "relative_turnover_blocks": 0, "volume_blocks": 0, "flow_proxy_blocks": 0, "range_blocks": 0}
    for index, row in enumerate(rows):
        quote = row["close"] * row["volume"]
        span = max(row["high"] - row["low"], 1e-12)
        close_location = (2.0 * row["close"] - row["high"] - row["low"]) / span
        body_direction = 1.0 if row["close"] > row["open"] else -1.0 if row["close"] < row["open"] else 0.0
        signed_pressure = row["volume"] * (.7 * close_location + .3 * body_direction)
        quote_turnover.append(quote); pressure.append(signed_pressure); volumes.append(row["volume"])
        quote_sum += quote; pressure_sum += signed_pressure
        if index >= turnover_bars:
            quote_sum -= quote_turnover[index - turnover_bars]
        if index >= 20:
            pressure_sum -= pressure[index - 20]
        prior_volume = volume_sum / 20.0 if index >= 20 and volume_sum > 0 else None
        volume_ratio = row["volume"] / prior_volume if prior_volume else None
        volume_sum += row["volume"]
        if index >= 20:
            volume_sum -= volumes[index - 20]
        recent = rows[max(0, index - 2):index + 1]
        range_15m_pct = (max(item["high"] for item in recent) - min(item["low"] for item in recent)) / row["close"] if row["close"] else 0.0
        flow_proxy = pressure_sum / sum(volumes[max(0, index - 19):index + 1]) if index >= 19 and sum(volumes[max(0, index - 19):index + 1]) else None
        quote_ok = quote_sum >= min_quote_turnover_try
        prior_quote_sum = sum(quote_turnover[max(0, index - turnover_bars - 288):max(0, index - turnover_bars)])
        expected_turnover = prior_quote_sum * turnover_bars / 288.0
        relative_ok = relative_turnover_multiple <= 0 or (index >= turnover_bars + 288 and quote_sum >= expected_turnover * relative_turnover_multiple)
        volume_ok = volume_ratio is not None and volume_ratio >= 1.2
        flow_ok = flow_proxy is not None and flow_proxy >= .10
        range_ok = range_15m_pct >= .0005
        allowed = quote_ok and relative_ok and volume_ok and flow_ok and range_ok
        gate.append(allowed)
        if allowed:
            counts["qualified_bars"] += 1
        else:
            counts["quote_turnover_blocks"] += int(not quote_ok)
            counts["relative_turnover_blocks"] += int(not relative_ok)
            counts["volume_blocks"] += int(not volume_ok)
            counts["flow_proxy_blocks"] += int(not flow_ok)
            counts["range_blocks"] += int(not range_ok)
    return gate, counts


def pump_and_kernel_signals(rows, entry_min_mfi=0.0, entry_require_mfi_rising=False):
    """Build only from information closed no later than each M5 signal candle."""
    closes = [row["close"] for row in rows]
    volumes = [row["volume"] for row in rows]
    rq = [kernel.rational_quadratic(closes, index) for index in range(len(rows))]
    gauss = [kernel.gaussian(closes, index) for index in range(len(rows))]
    volume_ema20 = kernel.ema(volumes, 20)
    m5_ema9, m5_ema21, atr14 = kernel.ema(closes, 9), kernel.ema(closes, 21), kernel.atr(rows, 14)
    m15, m30 = resample(rows, 15), resample(rows, 30)
    m15_closes = [row["close"] for row in m15]
    ema9, ema21, ema50 = (sma_seeded_ema(m15_closes, period) for period in (9, 21, 50))
    m15_bullish = {row["close_time"]: bool(ema9[index] is not None and ema21[index] is not None and ema50[index] is not None and ema9[index] > ema21[index] > ema50[index]) for index, row in enumerate(m15)}
    m15_dmi = wilder_dmi(m15)
    m30_ready_time = m30[54]["close_time"] if len(m30) >= 55 else float("inf")
    signals = {name: [False] * len(rows) for name in VARIANTS}
    mfi_gate = [False] * len(rows)
    green_streak, pump_hits, last_m15_bullish, pump_arm_until, last_m15_dmi, prior_mfi = 0, 0, False, -1, None, None
    pullback_state = None
    closes_sum = closes_sq_sum = 0.0
    gain_sum = loss_sum = pos_flow = neg_flow = 0.0
    gains, losses, positive_flows, negative_flows = [], [], [], []
    typical = [(row["high"] + row["low"] + row["close"]) / 3.0 for row in rows]
    for index, row in enumerate(rows):
        green = rq[index] is not None and gauss[index] is not None and gauss[index] >= rq[index]
        green_streak = green_streak + 1 if green else 0
        if row["close_time"] in m15_bullish:
            last_m15_bullish = m15_bullish[row["close_time"]]
            last_m15_dmi = m15_dmi.get(row["close_time"])
        # Rolling M5 BB(20), RSI(14) and MFI(14), matched to the Pump Monitor
        # conditions with completed data only.
        closes_sum += row["close"]; closes_sq_sum += row["close"] ** 2
        if index >= 20:
            stale = closes[index - 20]; closes_sum -= stale; closes_sq_sum -= stale ** 2
        if index == 0:
            gain = loss = positive = negative = 0.0
        else:
            change = row["close"] - rows[index - 1]["close"]
            gain, loss = max(change, 0.0), max(-change, 0.0)
            flow = typical[index] * row["volume"]
            positive, negative = (flow, 0.0) if typical[index] > typical[index - 1] else (0.0, flow) if typical[index] < typical[index - 1] else (0.0, 0.0)
        gains.append(gain); losses.append(loss); positive_flows.append(positive); negative_flows.append(negative)
        gain_sum += gain; loss_sum += loss; pos_flow += positive; neg_flow += negative
        if index >= 15:
            gain_sum -= gains[index - 14]; loss_sum -= losses[index - 14]
            pos_flow -= positive_flows[index - 14]; neg_flow -= negative_flows[index - 14]
        if index < 54 or index < 19 or row["close_time"] < m30_ready_time or not last_m15_bullish:
            continue
        variance = max(0.0, closes_sq_sum / 20.0 - (closes_sum / 20.0) ** 2)
        std = variance ** 0.5
        upper, lower = closes_sum / 20.0 + 2.0 * std, closes_sum / 20.0 - 2.0 * std
        if upper <= lower:
            continue
        bb_ok = row["close"] >= lower + .80 * (upper - lower)
        rsi = 100.0 if loss_sum == 0 and gain_sum > 0 else 50.0 if loss_sum == 0 else 100.0 - 100.0 / (1.0 + gain_sum / loss_sum)
        mfi = 100.0 if neg_flow == 0 else 100.0 - 100.0 / (1.0 + pos_flow / neg_flow)
        mfi_gate[index] = mfi >= entry_min_mfi and (not entry_require_mfi_rising or (prior_mfi is not None and mfi > prior_mfi))
        prior_mfi = mfi
        volume_ok = volume_ema20[index] is not None and row["volume"] >= volume_ema20[index]
        # M15 bullish makes the M15/M30 continuation score component true;
        # score>=3 therefore needs at least two of BB/MFI/RSI as well.
        pump_ok = last_m15_bullish and sum((bb_ok, mfi >= 45.0, rsi >= 65.0)) >= 2 and volume_ok
        if pump_ok:
            pump_hits += 1
            signals["pump_only"][index] = True
            pump_arm_until = max(pump_arm_until, index + 3)
            for bars in (1, 2, 3):
                if green_streak == bars:
                    signals[f"pump_kernel_green{bars}"][index] = True
        for bars in (1, 2, 3):
            if green_streak == bars and index <= pump_arm_until:
                signals[f"pump_arm3_kernel_green{bars}"][index] = True
        # Causal continuation entry: an initial Pump event arms a short
        # pullback/reclaim sequence instead of buying the extension candle.
        if pullback_state and index > pullback_state["expires"]:
            pullback_state = None
        if pullback_state and pullback_state["phase"] == "armed":
            if row["close"] < m5_ema21[index]:
                pullback_state = None
            else:
                retrace_atr = (pullback_state["high"] - row["low"]) / pullback_state["atr"] if pullback_state["atr"] else float("inf")
                if .25 <= retrace_atr <= .80 and row["close"] < pullback_state["high"]:
                    pullback_state = {"phase": "reclaim", "expires": index + 2, "pullback_high": row["high"]}
        elif pullback_state and pullback_state["phase"] == "reclaim":
            if row["close"] < m5_ema21[index]:
                pullback_state = None
            elif (row["close"] > pullback_state["pullback_high"] and row["close"] > m5_ema9[index] and green):
                signals["pump_pullback_reclaim_kernel"][index] = True
                dmi_ok = bool(last_m15_dmi and last_m15_dmi["plus_di"] > last_m15_dmi["minus_di"] and last_m15_dmi["adx"] >= 25.0 and last_m15_dmi["adx_rising"])
                if dmi_ok:
                    signals["pump_pullback_reclaim_m15_dmi"][index] = True
                pullback_state = None
        if pullback_state is None and pump_ok and atr14[index] and m5_ema21[index] is not None:
            pullback_state = {"phase": "armed", "expires": index + 3, "high": row["high"], "atr": atr14[index]}
    return signals, {"m15_completed_candles": len(m15), "m30_completed_candles": len(m30), "pump_qualified_m5_bars": pump_hits}, mfi_gate


async def fetch(symbol, days, cutoff, semaphore):
    async with semaphore:
        try:
            raw = await historical_klines(symbol, "5m", days, cutoff)
            return symbol, kernel.normalize(raw, cutoff), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


def compact(result):
    return {key: value for key, value in result.items() if key != "trades_detail"}


async def main(args):
    cutoff = args.end_time_ms if args.end_time_ms is not None else (int(time.time() * 1000) - args.end_minutes_ago * MS_5M) // MS_5M * MS_5M - 1
    start = cutoff - args.hours * 3_600_000
    eligibility_start = start - args.eligibility_days * 24 * 3_600_000
    symbols = [symbol.upper().replace("_", "") for symbol in args.symbols]
    filters = await trading_symbols_with_filters("TRY")
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, cutoff, asyncio.Semaphore(args.concurrency)) for symbol in symbols))
    per_symbol, aggregate, errors = {}, {name: {"net_pnl_try": 0.0, "fees_try": 0.0, "trades": 0, "gross_profit": 0.0, "gross_loss": 0.0, "max_drawdown_try": 0.0} for name in VARIANTS}, {}
    liquidity_scores = {}
    if args.top_liquid_symbols:
        for symbol, rows, error in loaded:
            if error:
                continue
            quote_turnover = sum(row["close"] * row["volume"] for row in rows if eligibility_start <= row["close_time"] < start)
            liquidity_scores[symbol] = quote_turnover / args.eligibility_days if args.eligibility_days else 0.0
        selected_symbols = set(symbol for symbol, _ in sorted(liquidity_scores.items(), key=lambda item: item[1], reverse=True)[:args.top_liquid_symbols])
    else:
        selected_symbols = set(symbols)
    for symbol, rows, error in loaded:
        provenance = {"m5_closed_candles": len(rows), "m5_missing_intervals": missing_intervals(rows), "tick_size_try": float((filters.get(symbol) or {}).get("tick_size") or 0.01), "development_avg_daily_quote_turnover_try": round(liquidity_scores.get(symbol, 0.0), 2) if args.top_liquid_symbols else None}
        if error or len(rows) < 400:
            errors[symbol] = error or "insufficient completed M5 history"
            per_symbol[symbol] = {"provenance": provenance, "error": errors[symbol]}
            continue
        if symbol not in selected_symbols:
            per_symbol[symbol] = {"provenance": provenance, "excluded": "outside pre-declared top daily-quote-turnover liquidity cohort"}
            continue
        signals, signal_provenance, mfi_gate = pump_and_kernel_signals(rows, args.entry_min_mfi, args.entry_require_mfi_rising)
        activity_gate, activity_provenance = dynamic_activity_gate(rows, args.activity_turnover_bars, args.activity_min_quote_turnover_try, args.activity_relative_turnover_multiple)
        if args.dynamic_activity_filter:
            signals = {name: [signal and activity_gate[index] for index, signal in enumerate(values)] for name, values in signals.items()}
        if args.entry_min_mfi > 0:
            signals = {name: [signal and mfi_gate[index] for index, signal in enumerate(values)] for name, values in signals.items()}
        variants = {}
        for name in VARIANTS:
            result = kernel.replay(rows, start, cutoff, args.cost_multiplier, args.red_confirm_bars, 1, "none", args.atr_stop_multiplier, args.break_even_r, signals[name], args.take_profit_r, args.cooldown_bars)
            variants[name] = result
            aggregate[name]["net_pnl_try"] += result["net_pnl_try"]
            aggregate[name]["fees_try"] += result["fees_try"]
            aggregate[name]["trades"] += result["trades"]
            aggregate[name]["gross_profit"] += sum(t["pnl_try"] for t in result["trades_detail"] if t["pnl_try"] > 0)
            aggregate[name]["gross_loss"] += sum(t["pnl_try"] for t in result["trades_detail"] if t["pnl_try"] <= 0)
            aggregate[name]["max_drawdown_try"] += result["max_drawdown_try"]
        per_symbol[symbol] = {"provenance": {**provenance, **signal_provenance, "dynamic_activity": activity_provenance}, "variants": variants}
    for name, values in aggregate.items():
        values["net_pnl_try"] = round(values["net_pnl_try"], 2)
        values["fees_try"] = round(values["fees_try"], 2)
        values["max_drawdown_try"] = round(values["max_drawdown_try"], 2)
        values["profit_factor"] = round(values["gross_profit"] / abs(values["gross_loss"]), 3) if values["gross_loss"] else None
        values["expectancy_try"] = round(values["net_pnl_try"] / values["trades"], 2) if values["trades"] else 0.0
        del values["gross_profit"]; del values["gross_loss"]
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
              "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "eligibility_window": {"start": iso(eligibility_start), "end": iso(start - 1), "hours": args.eligibility_days * 24} if args.top_liquid_symbols else None,
              "source": "Binance TR public /api/v3/klines completed M5 OHLCV",
              "configuration": {"pump_monitor": "score>=3/4 + M15 EMA(9)>EMA(21)>EMA(50) + M5 volume>=EMA(20)",
                                "kernel": "Gaussian >= rational quadratic; confirmation must occur on the same completed M5 bar as Pump Monitor", 
                                "entry_mfi_filter": {"minimum": args.entry_min_mfi, "rising": args.entry_require_mfi_rising} if args.entry_min_mfi > 0 else "disabled",
                                "dynamic_activity_filter": {"trailing_quote_turnover_bars": args.activity_turnover_bars, "min_quote_turnover_try": args.activity_min_quote_turnover_try, "relative_turnover_multiple": args.activity_relative_turnover_multiple, "m5_volume_ratio_min": 1.2, "candle_volume_flow_proxy_min": .10, "range_15m_pct_min": .05} if args.dynamic_activity_filter else "disabled",
                                "atr_stop_multiplier": args.atr_stop_multiplier, "break_even_r": args.break_even_r, "take_profit_r": args.take_profit_r, "cooldown_bars": args.cooldown_bars,
                                "exit": f"{args.red_confirm_bars} completed red kernel bars; next M5 open", "long_only": True},
              "variants": {"pump_only": "Pump Monitor only; no green-kernel requirement", "pump_kernel_green1": "Pump Monitor + first green kernel close on the same bar", "pump_kernel_green2": "Pump Monitor + second consecutive green kernel close on the same bar", "pump_kernel_green3": "Pump Monitor + third consecutive green kernel close on the same bar", "pump_arm3_kernel_green1": "Pump Monitor arms a maximum three-M5-bar window; first subsequent green kernel close enters", "pump_arm3_kernel_green2": "Pump Monitor arms a maximum three-M5-bar window; second subsequent green kernel close enters", "pump_arm3_kernel_green3": "Pump Monitor arms a maximum three-M5-bar window; third subsequent green kernel close enters", "pump_pullback_reclaim_kernel": "Pump arms a maximum three-bar window, then requires a 0.25-0.80 ATR pullback holding M5 EMA21 and a two-bar reclaim above pullback high and EMA9 while kernel is green", "pump_pullback_reclaim_m15_dmi": "The pullback/reclaim rule plus last completed M15 +DI>-DI, ADX>=25 and ADX rising"},
              "symbol_eligibility": {"method": "top historical daily TRY quote-turnover only; no PnL used", "top_symbols": args.top_liquid_symbols, "selected_symbols": sorted(selected_symbols), "development_daily_quote_turnover_try": {symbol: round(value, 2) for symbol, value in sorted(liquidity_scores.items(), key=lambda item: item[1], reverse=True)}} if args.top_liquid_symbols else None,
              "execution": {"initial_balance_try_per_symbol": kernel.INITIAL_BALANCE_TRY, "allocation_pct_of_current_cash": kernel.ALLOCATION_PCT, "one_open_position_per_symbol": True, "entry_exit_fill": "next M5 open", "cost_multiplier": args.cost_multiplier, "commission_pct_each_side": kernel.config.COMMISSION_PCT * args.cost_multiplier, "spread_pct": kernel.config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": kernel.config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier},
              "aggregate_independent_symbol_accounts": aggregate, "per_symbol": per_symbol, "errors": errors,
              "limitations": ["This compares entry timing only; all variants use the same red-kernel exit and no ATR stop.", "Aggregate is a sum of independent 10,000 TRY per-symbol research accounts, not a shared-capital portfolio.", "Public OHLCV lacks historical order-book depth, actual spread and intrabar execution order.", "Kernel is source-aligned to the supplied Pine configuration, not byte-for-byte TradingView execution."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps(aggregate, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["PENGUTRY", "TRUMPTRY", "SPKTRY", "MORPHOTRY"])
    parser.add_argument("--hours", type=int, default=240); parser.add_argument("--fetch-days", type=int, default=15)
    parser.add_argument("--end-minutes-ago", type=int, default=10); parser.add_argument("--end-time-ms", type=int)
    parser.add_argument("--concurrency", type=int, default=4); parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--red-confirm-bars", type=int, choices=(1, 2, 3), default=3); parser.add_argument("--output", required=True)
    parser.add_argument("--eligibility-days", type=int, default=0, help="Development-only liquidity window before the OOS start.")
    parser.add_argument("--top-liquid-symbols", type=int, default=0, help="Use only this many top daily-quote-turnover symbols from the development window.")
    parser.add_argument("--dynamic-activity-filter", action="store_true", help="Require causal high volume and positive candle-flow proxy at each entry bar.")
    parser.add_argument("--activity-turnover-bars", type=int, default=288, help="Trailing M5 bars used for quote-turnover activity.")
    parser.add_argument("--activity-min-quote-turnover-try", type=float, default=1_000_000.0)
    parser.add_argument("--activity-relative-turnover-multiple", type=float, default=0.0, help="Require current trailing turnover to exceed this multiple of its prior 24h expectation.")
    parser.add_argument("--atr-stop-multiplier", type=float, default=0.0)
    parser.add_argument("--break-even-r", type=float, default=0.0)
    parser.add_argument("--take-profit-r", type=float, default=0.0)
    parser.add_argument("--cooldown-bars", type=int, default=0)
    parser.add_argument("--entry-min-mfi", type=float, default=0.0)
    parser.add_argument("--entry-require-mfi-rising", action="store_true")
    asyncio.run(main(parser.parse_args()))
