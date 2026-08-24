"""Research-only M5 replay: enter on a green kernel transition, exit after 3 red bars."""
import argparse
import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, trading_symbols_with_filters
from scripts.replay_ldc_kernel_m1 import (
    COMMISSION_PCT, INITIAL_BALANCE_TRY, SLIPPAGE_TICKS, adx, atr, ema, iso,
    normalize, rational_quadratic, rsi,
)


MS_5M = 5 * 60_000
ALLOCATION_PCT = .30


def missing_m5_intervals(rows):
    return sum(max(0, (rows[index]["time"] - rows[index - 1]["time"]) // MS_5M - 1) for index in range(1, len(rows)))


def features(rows, start_ms, end_ms):
    closes, volumes = [row["close"] for row in rows], [row["volume"] for row in rows]
    yhat = [rational_quadratic(closes, index) for index in range(len(rows))]
    adx_values, rsi_values, atr_values = adx(rows), rsi(closes, 10), atr(rows, 14)
    ema30, vol_ema20 = ema(closes, 30), ema(volumes, 20)
    red_streak, prior_green, output = 0, None, []
    for index, row in enumerate(rows):
        current = yhat[index]
        if current is None or index < 3 or yhat[index - 3] is None:
            continue
        green = current > yhat[index - 1]
        red_streak = 0 if green else red_streak + 1
        green_transition = green and prior_green is False
        prior_green = green
        if not start_ms <= row["close_time"] <= end_ms:
            continue
        trend_ok = adx_values[index] is not None and adx_values[index] >= 16 and row["close"] > ema30[index] and rsi_values[index] is not None and rsi_values[index] >= 50
        participation_ok = volumes[index] >= vol_ema20[index] * .60
        slope_ok = atr_values[index] is not None and current - yhat[index - 3] >= atr_values[index] * .02
        strict_trend_ok = adx_values[index] is not None and adx_values[index] >= 18 and row["close"] > ema30[index] and rsi_values[index] is not None and rsi_values[index] >= 52
        strict_participation_ok = volumes[index] >= vol_ema20[index] * .80
        strict_slope_ok = atr_values[index] is not None and current - yhat[index - 3] >= atr_values[index] * .10
        red_move_2 = atr_values[index] is not None and yhat[index - 2] - current >= atr_values[index] * .10
        red_move_3 = atr_values[index] is not None and yhat[index - 3] - current >= atr_values[index] * .10
        output.append({"index": index, "time": row["close_time"], "close": row["close"], "green_transition": green_transition,
                       "red_streak": red_streak, "baseline_entry": green_transition, "trend_entry": green_transition and trend_ok,
                       "relaxed_entry": green_transition and trend_ok and participation_ok and slope_ok,
                       "balanced_entry": green_transition and strict_trend_ok and strict_participation_ok and strict_slope_ok,
                       "exit_red3": red_streak >= 3, "exit_red3_ema30": red_streak >= 3 and row["close"] < ema30[index],
                       "exit_red3_rsi50": red_streak >= 3 and rsi_values[index] is not None and rsi_values[index] < 50,
                       "exit_red2_atr10": red_streak >= 2 and red_move_2, "exit_red3_atr10": red_streak >= 3 and red_move_3})
    return output


def simulate(rows, variant, tick_size):
    cash, position, trades, peak, drawdown = INITIAL_BALANCE_TRY, None, [], INITIAL_BALANCE_TRY, 0.0
    signals = {row["time"]: row for row in rows}
    candidates, exit_candidates = 0, 0
    for signal in rows:
        if signal[f"{variant}_entry"]:
            candidates += 1
        if signal["red_streak"] >= 3:
            exit_candidates += 1
        if position and signal["red_streak"] >= 3:
            fill = max(0.0, signal["close"] - SLIPPAGE_TICKS * tick_size)
            proceeds = position["qty"] * fill
            exit_fee = proceeds * COMMISSION_PCT
            cash += proceeds - exit_fee
            trades.append({"entry_time": position["time"], "exit_time": signal["time"], "entry_fill": position["fill"], "exit_fill": fill,
                           "pnl_try": proceeds - exit_fee - position["cost"], "fees_try": position["fee"] + exit_fee, "reason": "kernel_red_3_bars"})
            position = None
        elif not position and signal[f"{variant}_entry"]:
            allocation = cash * ALLOCATION_PCT
            fill = signal["close"] + SLIPPAGE_TICKS * tick_size
            notional = allocation / (1 + COMMISSION_PCT)
            fee = notional * COMMISSION_PCT
            cash -= allocation
            position = {"time": signal["time"], "fill": fill, "qty": notional / fill, "cost": allocation, "fee": fee}
        marked = cash if not position else cash + position["qty"] * max(0.0, signal["close"] - SLIPPAGE_TICKS * tick_size) * (1 - COMMISSION_PCT)
        peak, drawdown = max(peak, marked), max(drawdown, peak - marked)
    if position:
        signal = rows[-1]
        fill = max(0.0, signal["close"] - SLIPPAGE_TICKS * tick_size)
        proceeds = position["qty"] * fill
        exit_fee = proceeds * COMMISSION_PCT
        cash += proceeds - exit_fee
        trades.append({"entry_time": position["time"], "exit_time": signal["time"], "entry_fill": position["fill"], "exit_fill": fill,
                       "pnl_try": proceeds - exit_fee - position["cost"], "fees_try": position["fee"] + exit_fee, "reason": "window_mark_to_market"})
    pnl = [trade["pnl_try"] for trade in trades]
    fees = sum(trade["fees_try"] for trade in trades)
    gains, losses = sum(value for value in pnl if value > 0), sum(value for value in pnl if value <= 0)
    return {"trades": len(trades), "entry_candidates": candidates, "red3_exit_candidates": exit_candidates,
            "gross_pnl_try": round(sum(pnl) + fees, 2), "net_pnl_try": round(sum(pnl), 2), "fees_try": round(fees, 2),
            "wins": sum(value > 0 for value in pnl), "losses": sum(value <= 0 for value in pnl),
            "profit_factor": round(gains / abs(losses), 3) if losses else None, "expectancy_try": round(sum(pnl) / len(pnl), 2) if pnl else 0.0,
            "max_drawdown_try": round(drawdown, 2), "final_balance_try": round(cash, 2),
            "reconciliation_delta_try": round(cash - INITIAL_BALANCE_TRY - sum(pnl), 8), "exit_reasons": dict(Counter(trade["reason"] for trade in trades)),
            "trades_detail": trades}


async def main(args):
    cutoff = args.end_time_ms if args.end_time_ms is not None else (int(time.time() * 1000) - args.end_minutes_ago * 60_000) // MS_5M * MS_5M - 1
    start = cutoff - args.hours * 3_600_000
    symbol = args.symbol.upper().replace("_", "")
    raw = await historical_klines(symbol, "5m", args.fetch_days, cutoff)
    candles = normalize(raw, cutoff)
    tick_size = float((await trading_symbols_with_filters("TRY")).get(symbol, {}).get("tick_size") or .01)
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(), "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "source": "Binance TR public /api/v3/klines completed M5 OHLCV", "provenance": {"symbol": symbol, "m5_closed_candles": len(candles), "m5_missing_intervals": missing_m5_intervals(candles), "tick_size_try": tick_size},
              "strategy": {"kernel": {"h": 8, "r": 10.0, "x": 15}, "entry": "kernel green transition", "exit": "close when kernel is red for 3 consecutive completed M5 bars",
                           "variants": {"baseline": "green transition only", "trend": "EMA30 + ADX>=16 + RSI10>=50", "relaxed": "trend + volume>=0.60x EMA20 + kernel 3-bar slope>=0.02 ATR", "balanced": "EMA30 + ADX>=18 + RSI10>=52 + volume>=0.80x EMA20 + kernel 3-bar slope>=0.10 ATR"}},
              "execution": {"initial_balance_try": INITIAL_BALANCE_TRY, "allocation_pct_of_current_cash": ALLOCATION_PCT, "long_only": True, "one_open_position": True,
                            "commission_pct_each_side": COMMISSION_PCT, "slippage": f"{SLIPPAGE_TICKS} exchange price ticks each side", "entry": "signal bar close", "exit": "third red bar close"},
              "limitations": ["KernelFunctions/2 is causally ported, not executed byte-for-byte outside TradingView.", "The 24-hour comparison is exploratory; filter selection needs chronological OOS validation.", "Historical OHLCV has no intrabar sequence, spread or depth."]}
    if len(candles) < 250:
        result["error"] = "insufficient completed M5 history"
    else:
        rows = features(candles, start, cutoff)
        result["variants"] = {variant: simulate(rows, variant, tick_size) for variant in ("baseline", "trend", "relaxed", "balanced")}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {name: {key: value for key, value in details.items() if key != "trades_detail"} for name, details in result.get("variants", {}).items()}
    print("RESULT_JSON=" + json.dumps(compact or {"error": result.get("error")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SPKTRY"); parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--fetch-days", type=int, default=10); parser.add_argument("--end-minutes-ago", type=int, default=10)
    parser.add_argument("--end-time-ms", type=int, help="Exact completed-candle cutoff for reproducible chronological OOS folds.")
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
