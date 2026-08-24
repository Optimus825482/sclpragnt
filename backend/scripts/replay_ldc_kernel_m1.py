"""Paper-only, causal M1 replay of the supplied LDC Kernel M3 Pro Pine v6 strategy.

The supplied Pine parameters are kept unchanged.  In particular, the script
uses ``supertrendDir > 0`` exactly as written, although Pine v6 defines +1 as
the down direction.  This file is deliberately research-only.
"""
import argparse
import asyncio
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, trading_symbols_with_filters


MS_1M = 60_000
INITIAL_BALANCE_TRY = 10_000.0
COMMISSION_PCT = 0.001  # Pine: strategy.commission.percent = 0.1
SLIPPAGE_TICKS = 2


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(raw, cutoff):
    rows = []
    for item in raw:
        try:
            row = {"time": int(item[0]), "open": float(item[1]), "high": float(item[2]), "low": float(item[3]),
                   "close": float(item[4]), "volume": float(item[5]), "close_time": int(item[6])}
            if row["close_time"] <= cutoff and row["high"] >= row["low"] > 0 and row["volume"] >= 0:
                rows.append(row)
        except (IndexError, TypeError, ValueError):
            continue
    return sorted({row["time"]: row for row in rows}.values(), key=lambda row: row["time"])


def missing_intervals(rows):
    return sum(max(0, (rows[index]["time"] - rows[index - 1]["time"]) // MS_1M - 1) for index in range(1, len(rows)))


def ema(values, period):
    result, value, alpha = [], None, 2 / (period + 1)
    for current in values:
        value = current if value is None else alpha * current + (1 - alpha) * value
        result.append(value)
    return result


def rma(values, period):
    result, value = [], None
    for index, current in enumerate(values):
        if index == period - 1:
            value = sum(values[:period]) / period
        elif index >= period and value is not None:
            value = (value * (period - 1) + current) / period
        result.append(value)
    return result


def rsi(closes, period):
    changes = [0.0] + [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = rma([max(value, 0.0) for value in changes], period)
    losses = rma([max(-value, 0.0) for value in changes], period)
    return [None if gain is None or loss is None else 100.0 if loss == 0 and gain > 0 else 50.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
            for gain, loss in zip(gains, losses)]


def atr(rows, period):
    values = [row["high"] - row["low"] if index == 0 else max(
        row["high"] - row["low"], abs(row["high"] - rows[index - 1]["close"]), abs(row["low"] - rows[index - 1]["close"])
    ) for index, row in enumerate(rows)]
    return rma(values, period)


def adx(rows, period=14):
    tr, plus, minus = [rows[0]["high"] - rows[0]["low"]], [0.0], [0.0]
    for index in range(1, len(rows)):
        row, previous = rows[index], rows[index - 1]
        up, down = row["high"] - previous["high"], previous["low"] - row["low"]
        tr.append(max(row["high"] - row["low"], abs(row["high"] - previous["close"]), abs(row["low"] - previous["close"])))
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
    smooth_tr, smooth_plus, smooth_minus = rma(tr, period), rma(plus, period), rma(minus, period)
    dx = []
    for total, positive, negative in zip(smooth_tr, smooth_plus, smooth_minus):
        if total is None or total == 0:
            dx.append(0.0)
            continue
        pdi, mdi = 100 * positive / total, 100 * negative / total
        dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    smoothed = rma(dx, period)
    return [None if index < period * 2 - 2 else value for index, value in enumerate(smoothed)]


def mfi(rows, period):
    source = [(row["high"] + row["low"] + row["close"]) / 3 for row in rows]
    positive, negative = [0.0], [0.0]
    for index in range(1, len(rows)):
        change = source[index] - source[index - 1]
        positive.append(rows[index]["volume"] * source[index] if change > 0 else 0.0)
        negative.append(rows[index]["volume"] * source[index] if change < 0 else 0.0)
    result = []
    for index in range(len(rows)):
        if index + 1 < period:
            result.append(None)
            continue
        upper, lower = sum(positive[index - period + 1:index + 1]), sum(negative[index - period + 1:index + 1])
        result.append(100.0 if lower == 0 and upper > 0 else 50.0 if lower == 0 else 100 - 100 / (1 + upper / lower))
    return result


def supertrend_direction(rows, factor=3.0, period=21):
    """Return Pine's direction convention: +1 down, -1 up."""
    atr_values, directions, final_upper, final_lower, previous_line = atr(rows, period), [], [], [], None
    for index, row in enumerate(rows):
        current_atr = atr_values[index]
        if current_atr is None:
            directions.append(None); final_upper.append(None); final_lower.append(None); continue
        midpoint = (row["high"] + row["low"]) / 2
        upper, lower = midpoint + factor * current_atr, midpoint - factor * current_atr
        prior_upper, prior_lower = (final_upper[index - 1], final_lower[index - 1]) if index else (None, None)
        prior_close = rows[index - 1]["close"] if index else None
        if prior_lower is not None:
            lower = lower if lower > prior_lower or prior_close < prior_lower else prior_lower
        if prior_upper is not None:
            upper = upper if upper < prior_upper or prior_close > prior_upper else prior_upper
        if index == 0 or atr_values[index - 1] is None:
            direction = 1
        elif previous_line == prior_upper:
            direction = -1 if row["close"] > upper else 1
        else:
            direction = 1 if row["close"] < lower else -1
        previous_line = lower if direction == -1 else upper
        directions.append(direction); final_upper.append(upper); final_lower.append(lower)
    return directions


def rational_quadratic(closes, index, lookback=8, weight=10.0, start=15):
    if index < start:
        return None
    numerator = denominator = 0.0
    for lag in range(min(index + 1, start + lookback)):
        kernel = (1 + lag * lag / (2 * weight * lookback * lookback)) ** (-weight)
        numerator += closes[index - lag] * kernel
        denominator += kernel
    return numerator / denominator if denominator else None


def run(rows, start_ms, end_ms, tick_size):
    closes = [row["close"] for row in rows]
    yhat = [rational_quadratic(closes, index) for index in range(len(rows))]
    adx_values, ema_values, rsi_values = adx(rows), ema(closes, 30), rsi(closes, 10)
    mfi_values, atr_values, trend_direction = mfi(rows, 30), atr(rows, 14), supertrend_direction(rows)
    cash, quantity, entry_equity, entry_time, entry_price, entry_fee = INITIAL_BALANCE_TRY, 0.0, 0.0, None, None, None
    last_close_index, state_count, previous_state, start_kernel = 0, 0, None, None
    peak, max_drawdown, trades, signal_counts = INITIAL_BALANCE_TRY, 0.0, [], {"entry_candidates": 0, "exit_candidates": 0}
    for index, row in enumerate(rows):
        current_yhat = yhat[index]
        if current_yhat is None or index < 2 or yhat[index - 2] is None:
            continue
        bullish = yhat[index - 1] < current_yhat
        state_count = state_count + 1 if bullish == previous_state else 1
        if bullish != previous_state:
            start_kernel = yhat[index - 1] if yhat[index - 1] is not None else current_yhat
        previous_state = bullish
        current_atr = atr_values[index]
        slope_ok = current_atr is not None and start_kernel is not None and abs(current_yhat - start_kernel) >= current_atr * .45
        momentum_ok = current_yhat > yhat[index - 2]
        confirmed_bullish = bullish and state_count >= 2 and slope_ok and momentum_ok
        confirmed_bearish = not bullish and state_count >= 2 and slope_ok
        filters_ok = all((
            adx_values[index] is not None and adx_values[index] > 25,
            closes[index] > ema_values[index],
            rsi_values[index] is not None and rsi_values[index] > 65,
            trend_direction[index] is not None and trend_direction[index] > 0,  # Exact supplied Pine condition.
            mfi_values[index] is not None and mfi_values[index] > 70,
        ))
        in_window = start_ms <= row["close_time"] <= end_ms
        if in_window and confirmed_bullish and filters_ok:
            signal_counts["entry_candidates"] += 1
        if in_window and confirmed_bearish:
            signal_counts["exit_candidates"] += 1
        if not in_window:
            continue
        if quantity and confirmed_bearish:
            fill = max(0.0, row["close"] - SLIPPAGE_TICKS * tick_size)
            gross = quantity * fill
            fee = gross * COMMISSION_PCT
            cash = gross - fee
            pnl = cash - entry_equity
            trades.append({"entry_time": entry_time, "exit_time": row["close_time"], "entry_fill": entry_price,
                           "exit_fill": fill, "pnl_try": pnl, "fees_try": entry_fee + fee, "reason": "confirmed_bearish_kernel"})
            quantity, last_close_index = 0.0, index
        elif not quantity and confirmed_bullish and filters_ok and index - last_close_index >= 5:
            entry_equity = cash
            fill = row["close"] + SLIPPAGE_TICKS * tick_size
            notional = cash / (1 + COMMISSION_PCT)
            entry_fee = notional * COMMISSION_PCT
            quantity, entry_time, entry_price, cash = notional / fill, row["close_time"], fill, 0.0
        equity = cash if not quantity else quantity * max(0.0, row["close"] - SLIPPAGE_TICKS * tick_size) * (1 - COMMISSION_PCT)
        peak, max_drawdown = max(peak, equity), max(max_drawdown, peak - equity)
    if quantity:
        row = rows[-1]
        fill = max(0.0, row["close"] - SLIPPAGE_TICKS * tick_size)
        gross = quantity * fill
        fee = gross * COMMISSION_PCT
        cash = gross - fee
        trades.append({"entry_time": entry_time, "exit_time": row["close_time"], "entry_fill": entry_price,
                       "exit_fill": fill, "pnl_try": cash - entry_equity, "fees_try": entry_fee + fee, "reason": "window_mark_to_market"})
    pnl = [trade["pnl_try"] for trade in trades]
    gains, losses = sum(value for value in pnl if value > 0), sum(value for value in pnl if value <= 0)
    fees = sum(trade["fees_try"] for trade in trades)
    return {"trades": len(trades), "gross_pnl_try": round(sum(pnl) + fees, 2), "net_pnl_try": round(sum(pnl), 2), "fees_try": round(fees, 2),
            "wins": sum(value > 0 for value in pnl), "losses": sum(value <= 0 for value in pnl),
            "profit_factor": round(gains / abs(losses), 3) if losses else None,
            "expectancy_try": round(sum(pnl) / len(pnl), 2) if pnl else 0.0, "max_drawdown_try": round(max_drawdown, 2),
            "final_balance_try": round(cash, 2), "reconciliation_delta_try": round(cash - INITIAL_BALANCE_TRY - sum(pnl), 8),
            "exit_reasons": {reason: sum(trade["reason"] == reason for trade in trades) for reason in {trade["reason"] for trade in trades}},
            "signal_counts": signal_counts, "trades_detail": trades}


async def main(args):
    cutoff = (int(time.time() * 1000) - args.end_minutes_ago * MS_1M) // MS_1M * MS_1M - 1
    start = cutoff - args.hours * 3_600_000
    symbol = args.symbol.upper().replace("_", "")
    filters = await trading_symbols_with_filters("TRY")
    tick_size = float((filters.get(symbol) or {}).get("tick_size") or 0.01)
    raw = await historical_klines(symbol, "1m", args.fetch_days, cutoff)
    rows = normalize(raw, cutoff)
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
              "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "source": "Binance TR public /api/v3/klines completed M1 OHLCV",
              "provenance": {"symbol": symbol, "m1_closed_candles": len(rows), "m1_missing_intervals": missing_intervals(rows), "fetch_days": args.fetch_days, "tick_size_try": tick_size},
              "configuration": {"kernel": {"h": 8, "r": 10.0, "x": 15}, "confirm_bars": 2, "cooldown_bars": 5,
                                "adx": {"period": 14, "threshold": 25}, "ema_period": 30, "rsi": {"period": 10, "threshold": 65},
                                "supertrend": {"factor": 3.0, "atr_period": 21, "source_condition": "direction > 0 (Pine: down direction)"},
                                "mfi": {"period": 30, "threshold": 70}, "min_kernel_move_atr": 0.45},
              "execution": {"initial_balance_try": INITIAL_BALANCE_TRY, "position_sizing": "100% available equity, long-only", "commission_pct_each_side": COMMISSION_PCT,
                            "slippage": f"{SLIPPAGE_TICKS} exchange price ticks each side", "entry": "signal bar close (process_orders_on_close=true)", "exit": "confirmed bearish kernel bar close"},
              "limitations": ["The supplied Pine imports KernelFunctions/2; rational-quadratic kernel is a causal research port, not a byte-for-byte execution of TradingView's imported library.", "Historical OHLCV has no intrabar order sequence, spread or depth.", "The provided SuperTrend condition is reproduced exactly even though its Pine direction sign is bearish."]}
    if len(rows) < 1_100:
        result["error"] = "insufficient completed M1 history"
    else:
        result["result"] = run(rows, start, cutoff, tick_size)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps(result.get("result") or {"error": result.get("error")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SPKTRY"); parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--fetch-days", type=int, default=3); parser.add_argument("--end-minutes-ago", type=int, default=3)
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
