"""Paper-only M1 replay of the supplied Lorentzian kernel colour rule.

The copied Pine configuration plots the rational-quadratic estimate green when
the Gaussian estimate is at or above it (smoothing enabled).  This replay enters
on that red-to-green transition and exits after three consecutive completed red
bars.  It intentionally does not reuse the Lorentzian classifier entry rule.
"""
import argparse
import asyncio
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, trading_symbols_with_filters
from app.config import config
from scripts.replay_ldc_kernel_m1 import adx, atr, ema


MS_1M = 60_000
INITIAL_BALANCE_TRY = float(config.INITIAL_BALANCE_TRY)
ALLOCATION_PCT = 0.30
H, R, X, LAG = 5, 10.0, 5, 3


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(raw, cutoff):
    output = []
    for value in raw:
        try:
            row = {"time": int(value[0]), "open": float(value[1]), "high": float(value[2]),
                   "low": float(value[3]), "close": float(value[4]), "volume": float(value[5]),
                   "close_time": int(value[6])}
            if row["close_time"] <= cutoff and row["high"] >= row["low"] > 0 and row["volume"] >= 0:
                output.append(row)
        except (IndexError, TypeError, ValueError):
            continue
    return sorted({row["time"]: row for row in output}.values(), key=lambda row: row["time"])


def missing_intervals(rows):
    return sum(max(0, (rows[index]["time"] - rows[index - 1]["time"]) // MS_1M - 1) for index in range(1, len(rows)))


def rational_quadratic(closes, index):
    """Causal port of KernelFunctions/2 rationalQuadratic(src, h, r, x)."""
    if index < X:
        return None
    numerator = denominator = 0.0
    for lag in range(min(index + 1, X + H)):
        weight = (1.0 + lag * lag / (2.0 * R * H * H)) ** (-R)
        numerator += closes[index - lag] * weight
        denominator += weight
    return numerator / denominator if denominator else None


def gaussian(closes, index):
    """Causal port of KernelFunctions/2 gaussian(src, h-lag, x)."""
    lookback = H - LAG
    if index < X or lookback <= 0:
        return None
    numerator = denominator = 0.0
    for offset in range(min(index + 1, X + lookback)):
        weight = math.exp(-(offset * offset) / (2.0 * lookback * lookback))
        numerator += closes[index - offset] * weight
        denominator += weight
    return numerator / denominator if denominator else None


def buy_fill(price, cost_multiplier=1.0):
    return price * (1.0 + cost_multiplier * (config.BACKTEST_ASSUMED_SPREAD_PCT / 2.0 + config.ESTIMATED_SLIPPAGE_PCT))


def sell_fill(price, cost_multiplier=1.0):
    return max(0.0, price * (1.0 - cost_multiplier * (config.BACKTEST_ASSUMED_SPREAD_PCT / 2.0 + config.ESTIMATED_SLIPPAGE_PCT)))


def close_position(position, price, timestamp, reason, cost_multiplier=1.0):
    fill = sell_fill(price, cost_multiplier)
    proceeds = position["qty"] * fill
    fee = proceeds * config.COMMISSION_PCT * cost_multiplier
    return {"entry_time": position["entry_time"], "exit_time": timestamp, "entry_fill": position["entry_fill"],
            "exit_fill": fill, "pnl_try": proceeds - fee - position["allocation"],
            "fees_try": position["entry_fee"] + fee, "reason": reason}, proceeds - fee


def rolling_mean(values, period):
    output, total = [], 0.0
    for index, value in enumerate(values):
        total += 0.0 if value is None else value
        if index >= period:
            prior = values[index - period]
            total -= 0.0 if prior is None else prior
        window = values[max(0, index - period + 1):index + 1]
        output.append(total / period if len(window) == period and all(item is not None for item in window) else None)
    return output


def entry_filter_allows(row, index, ema30, ema50, volume_ema20, adx14, atr_pct, atr_pct_mean50, entry_filter):
    if entry_filter == "none":
        return True
    trend_ok = row["close"] > ema30[index]
    if entry_filter == "ema30":
        return trend_ok
    if entry_filter == "ema30_adx18":
        return trend_ok and adx14[index] is not None and adx14[index] >= 18.0
    if entry_filter == "ema30_rising":
        return trend_ok and index >= 3 and ema30[index] > ema30[index - 3]
    if entry_filter == "ema30_rising_atr50":
        return trend_ok and index >= 3 and ema30[index] > ema30[index - 3] and atr_pct[index] is not None and atr_pct_mean50[index] is not None and atr_pct[index] >= atr_pct_mean50[index]
    if entry_filter == "ema30_rising_volume20":
        return trend_ok and index >= 3 and ema30[index] > ema30[index - 3] and row["volume"] >= volume_ema20[index]
    return trend_ok and ema30[index] > ema50[index]


def replay(rows, start_ms, end_ms, cost_multiplier=1.0, red_confirm_bars=3, green_confirm_bars=1, entry_filter="none", atr_stop_multiplier=0.0, break_even_r=0.0, entry_signal=None, take_profit_r=0.0, cooldown_bars=0):
    closes = [row["close"] for row in rows]
    rq = [rational_quadratic(closes, index) for index in range(len(rows))]
    gauss = [gaussian(closes, index) for index in range(len(rows))]
    volumes = [row["volume"] for row in rows]
    ema30, ema50, volume_ema20, adx14, atr14 = ema(closes, 30), ema(closes, 50), ema(volumes, 20), adx(rows, 14), atr(rows, 14)
    atr_pct = [None if value is None or close <= 0 else value / close for value, close in zip(atr14, closes)]
    atr_pct_mean50 = rolling_mean(atr_pct, 50)
    cash, position, pending, trades = INITIAL_BALANCE_TRY, None, None, []
    peak, max_drawdown = INITIAL_BALANCE_TRY, 0.0
    prior_green, red_streak, green_streak, cooldown_until_index = None, 0, 0, -1
    counts = Counter()
    sell_adjustment = 1.0 - cost_multiplier * (config.BACKTEST_ASSUMED_SPREAD_PCT / 2.0 + config.ESTIMATED_SLIPPAGE_PCT)
    for index, row in enumerate(rows):
        in_window = start_ms <= row["close_time"] <= end_ms
        # A downside gap through the active stop is filled at the bar open.  This
        # is intentionally conservative and takes priority over a pending signal exit.
        if position and position["stop_reference"] is not None and row["open"] <= position["stop_reference"]:
            trade, proceeds_net = close_position(position, row["open"], row["time"], "atr_stop_gap", cost_multiplier)
            cash += proceeds_net
            trades.append(trade); position = None; pending = None; cooldown_until_index = index + cooldown_bars; counts["atr_stop_exits"] += 1
        # A signal observed only after the previous close can execute at this open.
        if pending and pending["execute_index"] == index:
            if pending["side"] == "exit" and position:
                trade, proceeds_net = close_position(position, row["open"], row["time"], f"kernel_red_{red_confirm_bars}_completed_bar(s)", cost_multiplier)
                cash += proceeds_net
                trades.append(trade); position = None; cooldown_until_index = index + cooldown_bars; counts[f"executed_red{red_confirm_bars}_exits"] += 1
            elif pending["side"] == "entry" and not position and cash > 0 and index >= cooldown_until_index:
                allocation = cash * ALLOCATION_PCT
                fill = buy_fill(row["open"], cost_multiplier)
                notional = allocation / (1.0 + config.COMMISSION_PCT * cost_multiplier)
                entry_fee = notional * config.COMMISSION_PCT * cost_multiplier
                cash -= allocation
                qty = notional / fill
                risk_distance = pending.get("risk_distance", 0.0)
                break_even_reference = allocation / (qty * (1.0 - config.COMMISSION_PCT * cost_multiplier) * sell_adjustment)
                position = {"entry_time": row["time"], "entry_fill": fill, "qty": notional / fill,
                            "allocation": allocation, "entry_fee": entry_fee, "risk_distance": risk_distance,
                            "stop_reference": fill - risk_distance if risk_distance > 0 else None,
                            "take_profit_reference": fill + risk_distance * take_profit_r if risk_distance > 0 and take_profit_r > 0 else None,
                            "break_even_reference": break_even_reference, "break_even_locked": False}
                counts["executed_green_entries"] += 1
            elif pending["side"] == "entry" and index < cooldown_until_index:
                counts["cooldown_blocks"] += 1
            pending = None
        # With OHLCV we cannot know whether the high or low occurred first.  When
        # both are possible, the existing stop is assumed to execute before a
        # same-bar break-even upgrade, avoiding favorable intrabar assumptions.
        if position and position["stop_reference"] is not None:
            if row["low"] <= position["stop_reference"]:
                trade, proceeds_net = close_position(position, position["stop_reference"], row["close_time"], "atr_stop")
                cash += proceeds_net
                trades.append(trade); position = None; pending = None; cooldown_until_index = index + cooldown_bars; counts["atr_stop_exits"] += 1
            elif position["take_profit_reference"] is not None and row["high"] >= position["take_profit_reference"]:
                trade, proceeds_net = close_position(position, position["take_profit_reference"], row["close_time"], f"atr_take_profit_{take_profit_r:g}R")
                cash += proceeds_net
                trades.append(trade); position = None; pending = None; cooldown_until_index = index + cooldown_bars; counts["atr_take_profit_exits"] += 1
            elif not position["break_even_locked"] and break_even_r > 0 and row["high"] >= position["entry_fill"] + position["risk_distance"] * break_even_r:
                position["stop_reference"] = position["break_even_reference"]
                position["break_even_locked"] = True
                counts["break_even_locks"] += 1
        if rq[index] is None or gauss[index] is None:
            continue
        green = gauss[index] >= rq[index]  # Exact source colour with useKernelSmoothing=true.
        red_streak = 0 if green else red_streak + 1
        green_streak = green_streak + 1 if green else 0
        green_transition = green and prior_green is False
        prior_green = green
        if in_window and green_transition:
            counts["green_transition_signals"] += 1
        # External research runners can pass a causal per-bar entry signal.  The
        # normal kernel-only replay retains its original confirmation behavior.
        entry_ready = bool(entry_signal[index]) if entry_signal is not None else green_streak == green_confirm_bars
        if in_window and entry_ready:
            counts[f"green{green_confirm_bars}_confirmation_signals"] += 1
            if not position and pending is None and index + 1 < len(rows):
                if entry_filter_allows(row, index, ema30, ema50, volume_ema20, adx14, atr_pct, atr_pct_mean50, entry_filter):
                    risk_distance = (atr14[index] or 0.0) * atr_stop_multiplier
                    if atr_stop_multiplier <= 0 or risk_distance > 0:
                        pending = {"side": "entry", "execute_index": index + 1, "risk_distance": risk_distance}
                    else:
                        counts["missing_atr_blocks"] += 1
                else:
                    counts["entry_filter_blocks"] += 1
        if in_window and red_streak == red_confirm_bars:
            counts[f"red{red_confirm_bars}_confirmation_signals"] += 1
            if position and pending is None and index + 1 < len(rows):
                pending = {"side": "exit", "execute_index": index + 1}
        marked = cash if not position else cash + position["qty"] * sell_fill(row["close"], cost_multiplier) * (1.0 - config.COMMISSION_PCT * cost_multiplier)
        peak, max_drawdown = max(peak, marked), max(max_drawdown, peak - marked)
    if position:
        last = rows[-1]
        trade, proceeds_net = close_position(position, last["close"], last["close_time"], "window_mark_to_market", cost_multiplier)
        cash += proceeds_net
        trades.append(trade)
    pnl = [trade["pnl_try"] for trade in trades]
    gains, losses = sum(value for value in pnl if value > 0), sum(value for value in pnl if value <= 0)
    fees = sum(trade["fees_try"] for trade in trades)
    return {"trades": len(trades), "gross_pnl_try": round(sum(pnl) + fees, 2), "net_pnl_try": round(sum(pnl), 2),
            "fees_try": round(fees, 2), "wins": sum(value > 0 for value in pnl), "losses": sum(value <= 0 for value in pnl),
            "profit_factor": round(gains / abs(losses), 3) if losses else None,
            "expectancy_try": round(sum(pnl) / len(pnl), 2) if pnl else 0.0,
            "max_drawdown_try": round(max_drawdown, 2), "final_balance_try": round(cash, 2),
            "reconciliation_delta_try": round(cash - INITIAL_BALANCE_TRY - sum(pnl), 8),
            "signals": dict(counts), "exit_reasons": dict(Counter(trade["reason"] for trade in trades)), "trades_detail": trades}


async def fetch(symbol, days, cutoff, semaphore):
    async with semaphore:
        try:
            rows = normalize(await historical_klines(symbol, "1m", days, cutoff), cutoff)
            return symbol, rows, None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    cutoff = args.end_time_ms if args.end_time_ms is not None else (int(time.time() * 1000) - args.end_minutes_ago * MS_1M) // MS_1M * MS_1M - 1
    start = cutoff - args.hours * 3_600_000
    symbols = [symbol.upper().replace("_", "") for symbol in args.symbols]
    filters = await trading_symbols_with_filters("TRY")
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, cutoff, asyncio.Semaphore(args.concurrency)) for symbol in symbols))
    per_symbol, errors = {}, {}
    for symbol, rows, error in loaded:
        provenance = {"m1_closed_candles": len(rows), "m1_missing_intervals": missing_intervals(rows),
                      "tick_size_try": float((filters.get(symbol) or {}).get("tick_size") or 0.01)}
        if error or len(rows) < 1_500:
            errors[symbol] = error or "insufficient completed M1 history"
            per_symbol[symbol] = {"provenance": provenance, "error": errors[symbol]}
        else:
            per_symbol[symbol] = {"provenance": provenance, "result": replay(rows, start, cutoff)}
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
              "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "source": "Binance TR public /api/v3/klines completed M1 OHLCV",
              "configuration": {"kernel": {"rational_quadratic_h": H, "relative_weight_r": R, "regression_level_x": X,
                                               "gaussian_h": H - LAG, "lag": LAG, "smoothing": True},
                                "entry": "kernel colour changes red to green (Gaussian >= rational quadratic)",
                                "exit": "three consecutive completed red kernel bars", "long_only": True},
              "execution": {"initial_balance_try_per_symbol": INITIAL_BALANCE_TRY, "allocation_pct_of_current_cash": ALLOCATION_PCT,
                            "one_open_position_per_symbol": True, "entry_exit_fill": "next M1 open after closed signal",
                            "commission_pct_each_side": config.COMMISSION_PCT, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT,
                            "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT},
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
    parser.add_argument("--hours", type=int, default=24); parser.add_argument("--fetch-days", type=int, default=4)
    parser.add_argument("--end-minutes-ago", type=int, default=5); parser.add_argument("--end-time-ms", type=int)
    parser.add_argument("--concurrency", type=int, default=2); parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
