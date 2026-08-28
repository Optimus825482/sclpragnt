"""Paper-only M5 replay for Vortex Breakout PRO v4.1 on HEMITRY.

This is a source-aligned Python replay of the supplied Pine strategy. It uses
completed Binance TR M1 candles, fills entries on the next bar open, enforces
pyramiding=0, compounds 98% equity sizing, and applies explicit modeled costs.
"""
import argparse
import asyncio
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, ticker_24h, trading_symbols
from app.config import config

MS_1M = 60 * 1000


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(raw, cutoff):
    rows = []
    for value in raw:
        try:
            row = {
                "time": int(value[0]),
                "open": float(value[1]),
                "high": float(value[2]),
                "low": float(value[3]),
                "close": float(value[4]),
                "volume": float(value[5]),
                "close_time": int(value[6]),
            }
            if row["close_time"] <= cutoff and row["high"] >= row["low"] > 0:
                rows.append(row)
        except (IndexError, TypeError, ValueError):
            continue
    return sorted({row["time"]: row for row in rows}.values(), key=lambda row: row["time"])


def sma(values, period):
    output = []
    for index in range(len(values)):
        if index < period - 1:
            output.append(None)
            continue
        window = values[index - period + 1 : index + 1]
        if any(value is None for value in window):
            output.append(None)
        else:
            output.append(sum(window) / period)
    return output


def ema(values, period):
    output = []
    multiplier = 2 / (period + 1)
    current = None
    for value in values:
        if value is None:
            output.append(None)
            continue
        current = value if current is None else multiplier * value + (1 - multiplier) * current
        output.append(current)
    return output


def stdev(values, period, averages):
    output = []
    for index in range(len(values)):
        if index < period - 1 or averages[index] is None:
            output.append(None)
            continue
        window = values[index - period + 1 : index + 1]
        mean = averages[index]
        variance = sum((value - mean) ** 2 for value in window) / period
        output.append(math.sqrt(variance))
    return output


def rma(values, period):
    output = []
    seed = []
    current = None
    for value in values:
        if value is None:
            output.append(None)
            continue
        if current is None:
            seed.append(value)
            if len(seed) == period:
                current = sum(seed) / period
                output.append(current)
            else:
                output.append(None)
        else:
            current = (current * (period - 1) + value) / period
            output.append(current)
    return output


def pivothigh(highs, left, right):
    output = []
    for index in range(len(highs)):
        if index < left or index + right >= len(highs):
            output.append(None)
            continue
        value = highs[index]
        is_pivot = all(highs[j] < value for j in range(index - left, index))
        is_pivot = is_pivot and all(highs[j] < value for j in range(index + 1, index + right + 1))
        output.append(value if is_pivot else None)
    return output


def pivotlow(lows, left, right):
    output = []
    for index in range(len(lows)):
        if index < left or index + right >= len(lows):
            output.append(None)
            continue
        value = lows[index]
        is_pivot = all(lows[j] > value for j in range(index - left, index))
        is_pivot = is_pivot and all(lows[j] > value for j in range(index + 1, index + right + 1))
        output.append(value if is_pivot else None)
    return output


def compute_indicators(rows):
    closes = [row["close"] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    previous_closes = [None] + closes[:-1]

    basis = sma(closes, 21)
    deviation = stdev(closes, 21, basis)
    band_width = [
        None if basis[index] in (None, 0) else deviation[index] / basis[index]
        for index in range(len(rows))
    ]
    average_width = sma(band_width, 50)

    true_range = [highs[0] - lows[0]]
    vortex_plus_source = [None]
    vortex_minus_source = [None]
    plus_direction_source = [None]
    minus_direction_source = [None]
    for index in range(1, len(rows)):
        high, low, previous_close = highs[index], lows[index], closes[index - 1]
        true_range.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        vortex_plus_source.append(abs(high - lows[index - 1]))
        vortex_minus_source.append(abs(low - highs[index - 1]))
        up_move = high - highs[index - 1]
        down_move = lows[index - 1] - low
        plus_direction_source.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_direction_source.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    tr_sma = sma(true_range, 8)
    plus_sma = sma(vortex_plus_source, 8)
    minus_sma = sma(vortex_minus_source, 8)
    vortex_plus = [
        None if tr_sma[index] in (None, 0) or plus_sma[index] is None
        else plus_sma[index] / tr_sma[index]
        for index in range(len(rows))
    ]
    vortex_minus = [
        None if tr_sma[index] in (None, 0) or minus_sma[index] is None
        else minus_sma[index] / tr_sma[index]
        for index in range(len(rows))
    ]
    smoothed_true_range = rma(true_range, 14)
    smoothed_plus_direction = rma(plus_direction_source, 14)
    smoothed_minus_direction = rma(minus_direction_source, 14)
    plus_directional_index = []
    minus_directional_index = []
    directional_index = []
    for index in range(len(rows)):
        if None in (smoothed_true_range[index], smoothed_plus_direction[index], smoothed_minus_direction[index]) or smoothed_true_range[index] == 0:
            plus_directional_index.append(None)
            minus_directional_index.append(None)
            directional_index.append(None)
            continue
        plus_di = 100 * smoothed_plus_direction[index] / smoothed_true_range[index]
        minus_di = 100 * smoothed_minus_direction[index] / smoothed_true_range[index]
        plus_directional_index.append(plus_di)
        minus_directional_index.append(minus_di)
        denominator = plus_di + minus_di
        directional_index.append(100 * abs(plus_di - minus_di) / denominator if denominator else 0.0)
    average_directional_index = rma(directional_index, 14)
    ema_200 = ema(closes, 200)

    return {
        "basis": basis,
        "band_width": band_width,
        "average_width": average_width,
        "vortex_plus": vortex_plus,
        "vortex_minus": vortex_minus,
        "atr": rma(true_range, 15),
        "ema_200": ema_200,
        "adx_14": average_directional_index,
        "plus_di_14": plus_directional_index,
        "minus_di_14": minus_directional_index,
        "pivothigh": pivothigh(highs, 5, 5),
        "pivotlow": pivotlow(lows, 5, 5),
        "closes": closes,
    }


def trend_filter_pass(index, indicators, trend_filter):
    if trend_filter == "none":
        return True
    close = indicators["closes"][index]
    if trend_filter == "ema200":
        ema_value = indicators["ema_200"][index]
        return ema_value is not None and close > ema_value
    if trend_filter == "ema200_slope":
        ema_value = indicators["ema_200"][index]
        previous_ema = indicators["ema_200"][index - 12] if index >= 12 else None
        return (
            None not in (ema_value, previous_ema)
            and close > ema_value
            and ema_value > previous_ema
        )
    if trend_filter == "adx20":
        adx_value = indicators["adx_14"][index]
        plus_di = indicators["plus_di_14"][index]
        minus_di = indicators["minus_di_14"][index]
        return None not in (adx_value, plus_di, minus_di) and adx_value >= 20 and plus_di > minus_di
    raise ValueError(f"unknown trend filter: {trend_filter}")


def run_state_machine(rows, indicators, start_ms, cutoff_ms, trend_filter="none"):
    signals = []
    last_swing_high = None
    last_swing_low = None
    bull_active = False
    bull_armed = False
    bull_arm_bar = None

    for index, row in enumerate(rows):
        if row["close_time"] > cutoff_ms:
            break

        previous_swing_high = last_swing_high
        previous_swing_low = last_swing_low
        if index >= 5:
            confirmed_high = indicators["pivothigh"][index - 5]
            confirmed_low = indicators["pivotlow"][index - 5]
            if confirmed_high is not None:
                last_swing_high = confirmed_high
            if confirmed_low is not None:
                last_swing_low = confirmed_low

        close = indicators["closes"][index]
        basis = indicators["basis"][index]
        atr_value = indicators["atr"][index]
        vi_plus = indicators["vortex_plus"][index]
        vi_minus = indicators["vortex_minus"][index]
        previous_vi_plus = indicators["vortex_plus"][index - 1] if index > 0 else None
        previous_vi_minus = indicators["vortex_minus"][index - 1] if index > 0 else None

        vortex_bull = None not in (vi_plus, vi_minus) and vi_plus > vi_minus
        previous_vortex_bull = (
            None not in (previous_vi_plus, previous_vi_minus)
            and previous_vi_plus > previous_vi_minus
        )
        vortex_turn_up = vortex_bull and not previous_vortex_bull
        vortex_turn_down = (not vortex_bull) and previous_vortex_bull

        if vortex_turn_up:
            bull_active = True
            bull_armed = False
            bull_arm_bar = None
        if vortex_turn_down:
            bull_active = False
            bull_armed = False
            bull_arm_bar = None
        if bull_active and basis is not None and close < basis:
            bull_armed = True
            bull_arm_bar = index

        arm_valid = bull_armed and bull_arm_bar is not None and index - bull_arm_bar <= 50

        band_width = indicators["band_width"][index]
        average_width = indicators["average_width"][index]
        is_flat = False
        if None not in (band_width, average_width, vi_plus, vi_minus) and average_width > 0:
            is_flat = (
                band_width < average_width * 0.65
                or abs(vi_plus - vi_minus) < 0.1
            )

        previous_close = indicators["closes"][index - 1] if index > 0 else None
        swing_cross_up = (
            None not in (last_swing_high, previous_swing_high, previous_close)
            and close > last_swing_high
            and previous_close <= previous_swing_high
        )

        raw_distance = atr_value * 4.0 if atr_value is not None else None
        structural_stop = (
            close - raw_distance
            if raw_distance is not None and last_swing_low is None
            else last_swing_low - atr_value * 2.5
            if atr_value is not None
            else None
        )
        structural_ok = last_swing_low is None or (
            atr_value is not None and close > structural_stop
        )

        long_signal_raw = (
            bull_active
            and arm_valid
            and not is_flat
            and last_swing_high is not None
            and swing_cross_up
            and basis is not None
            and close > basis
            and structural_ok
            and atr_value is not None
        )

        if row["close_time"] < start_ms:
            continue

        passes_trend_filter = trend_filter_pass(index, indicators, trend_filter)

        signals.append(
            {
                "idx": index,
                "time": iso(row["time"]),
                "close": close,
                "bull_active": bull_active,
                "bull_armed": bull_armed,
                "arm_valid": arm_valid,
                "is_flat": is_flat,
                "swing_cross_up": swing_cross_up,
                "structural_ok": structural_ok,
                "long_signal_raw": long_signal_raw,
                "trend_filter": trend_filter,
                "trend_filter_pass": passes_trend_filter,
                "last_swing_high": last_swing_high,
                "last_swing_low": last_swing_low,
                "atr": atr_value,
                "basis": basis,
                "vortex_plus": vi_plus,
                "vortex_minus": vi_minus,
            }
        )

    return signals


def cost_parameters(args):
    multiplier = args.cost_multiplier
    if args.cost_mode == "pine":
        return {
            "mode": "pine",
            "commission_pct_each_side": 0.001 * multiplier,
            "slippage_ticks_each_side": 2 * multiplier,
            "tick_size": args.tick_size,
            "spread_pct_each_side": 0.0,
        }
    return {
        "mode": "config",
        "commission_pct_each_side": config.COMMISSION_PCT * multiplier,
        "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * multiplier,
        "spread_pct_each_side": config.BACKTEST_ASSUMED_SPREAD_PCT * multiplier,
        "tick_size": args.tick_size,
    }


def execution_price(price, side, costs):
    if costs["mode"] == "pine":
        adjustment = costs["slippage_ticks_each_side"] * costs["tick_size"]
        return price + adjustment if side == "buy" else price - adjustment
    adjustment = costs["slippage_pct_each_side"] + costs["spread_pct_each_side"]
    return price * (1 + adjustment) if side == "buy" else price * (1 - adjustment)


def simulate_trade(rows, indicators, signal, cutoff_ms, equity, costs):
    signal_idx = signal["idx"]
    entry_idx = signal_idx + 1
    if entry_idx >= len(rows):
        return None

    close = signal["close"]
    atr_value = signal["atr"]
    last_swing_low = signal["last_swing_low"]
    if atr_value is None or atr_value <= 0:
        return None

    raw_distance = atr_value * 4.0
    structural_stop = (
        close - raw_distance if last_swing_low is None else last_swing_low - atr_value * 2.5
    )
    stop_loss = min(max(structural_stop, close - raw_distance), close - costs["tick_size"])
    risk_distance = close - stop_loss
    if risk_distance <= 0:
        return None

    quantity = equity * 0.98 / close
    if quantity <= 0:
        return None

    tp1_price = close + risk_distance * 0.75
    tp2_price = close + risk_distance * 4.5
    entry_price = rows[entry_idx]["open"]
    breakeven_price = entry_price + risk_distance * 0.35
    tp1_quantity = quantity * 0.25
    runner_quantity = quantity - tp1_quantity

    legs = []
    tp1_done = False
    current_stop = stop_loss
    runner_exit_idx = None

    for index in range(entry_idx, len(rows)):
        row = rows[index]
        if row["close_time"] > cutoff_ms:
            break

        bar_high, bar_low, bar_open = row["high"], row["low"], row["open"]
        if not tp1_done:
            stop_hit = bar_low <= current_stop
            tp1_hit = bar_high >= tp1_price
            if stop_hit and tp1_hit:
                stop_first = abs(bar_open - current_stop) < abs(bar_open - tp1_price)
                if stop_first:
                    exit_price = current_stop
                    legs.append({"idx": index, "qty": tp1_quantity, "price": exit_price, "reason": "stop_loss", "open": False})
                    legs.append({"idx": index, "qty": runner_quantity, "price": exit_price, "reason": "stop_loss", "open": False})
                    runner_exit_idx = index
                    break
            elif stop_hit:
                legs.append({"idx": index, "qty": tp1_quantity, "price": current_stop, "reason": "stop_loss", "open": False})
                legs.append({"idx": index, "qty": runner_quantity, "price": current_stop, "reason": "stop_loss", "open": False})
                runner_exit_idx = index
                break

            if tp1_hit:
                legs.append({"idx": index, "qty": tp1_quantity, "price": tp1_price, "reason": "tp1", "open": False})
                tp1_done = True
                current_stop = max(stop_loss, breakeven_price)

        if tp1_done and runner_exit_idx is None:
            stop_hit = bar_low <= current_stop
            tp2_hit = bar_high >= tp2_price
            if stop_hit and tp2_hit:
                if abs(bar_open - current_stop) < abs(bar_open - tp2_price):
                    runner_exit_idx = index
                    legs.append({"idx": index, "qty": runner_quantity, "price": current_stop, "reason": "stop_loss_post_tp1", "open": False})
                else:
                    runner_exit_idx = index
                    legs.append({"idx": index, "qty": runner_quantity, "price": tp2_price, "reason": "tp2", "open": False})
                break
            if stop_hit:
                runner_exit_idx = index
                legs.append({"idx": index, "qty": runner_quantity, "price": current_stop, "reason": "stop_loss_post_tp1", "open": False})
                break
            if tp2_hit:
                runner_exit_idx = index
                legs.append({"idx": index, "qty": runner_quantity, "price": tp2_price, "reason": "tp2", "open": False})
                break

    final_row = rows[-1]
    if not legs:
        legs.append({"idx": len(rows) - 1, "qty": quantity, "price": final_row["close"], "reason": "open_pre_tp1", "open": True})
    elif runner_exit_idx is None:
        legs.append({"idx": len(rows) - 1, "qty": runner_quantity, "price": final_row["close"], "reason": "open_runner", "open": True})

    entry_execution_price = execution_price(entry_price, "buy", costs)
    entry_notional = entry_execution_price * quantity
    gross_pnl = 0.0
    fees = entry_notional * costs["commission_pct_each_side"]
    realized_pnl = 0.0
    open_unrealized_pnl = 0.0

    for leg in legs:
        exit_execution_price = execution_price(leg["price"], "sell", costs)
        exit_notional = exit_execution_price * leg["qty"]
        leg_gross = exit_notional - entry_notional * (leg["qty"] / quantity)
        leg_fees = exit_notional * costs["commission_pct_each_side"]
        leg_net = leg_gross - leg_fees
        leg["execution_price"] = exit_execution_price
        leg["time"] = iso(rows[leg["idx"]]["time"])
        leg["gross_pnl"] = round(leg_gross, 4)
        leg["fees"] = round(leg_fees, 4)
        leg["net_pnl"] = round(leg_net, 4)
        gross_pnl += leg_gross
        fees += leg_fees
        if leg["open"]:
            open_unrealized_pnl += leg_net
        else:
            realized_pnl += leg_net

    net_pnl = gross_pnl - fees
    last_bar_idx = max(leg["idx"] for leg in legs)
    return {
        "signal_idx": signal_idx,
        "entry_idx": entry_idx,
        "last_bar_idx": last_bar_idx,
        "entry_time": iso(rows[entry_idx]["time"]),
        "entry_price": entry_price,
        "entry_execution_price": entry_execution_price,
        "signal_close": close,
        "stop_loss": stop_loss,
        "breakeven_price": breakeven_price,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "risk_distance": risk_distance,
        "quantity": quantity,
        "legs": legs,
        "gross_pnl_try": round(gross_pnl, 4),
        "fees_try": round(fees, 4),
        "net_pnl_try": round(net_pnl, 4),
        "realized_pnl_try": round(realized_pnl, 4),
        "open_unrealized_pnl_try": round(open_unrealized_pnl, 4),
        "status": "open" if any(leg["open"] for leg in legs) else "closed",
        "exit_reason": legs[-1]["reason"],
    }


async def fetch(symbol, days, cutoff, semaphore):
    async with semaphore:
        try:
            return symbol, normalize(await historical_klines(symbol, "1m", days, cutoff), cutoff), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def select_top_gainers(limit):
    known_try = set(await trading_symbols("TRY"))
    ranked = []
    for item in await ticker_24h():
        symbol = str(item.get("symbol", "")).replace("_", "").upper()
        if symbol not in known_try:
            continue
        try:
            change_pct = float(item.get("priceChangePercent", 0) or 0)
            quote_volume = float(item.get("quoteVolume", 0) or 0)
        except (TypeError, ValueError):
            continue
        ranked.append(
            {
                "symbol": symbol,
                "change_pct": change_pct,
                "quote_volume": quote_volume,
            }
        )
    ranked.sort(key=lambda row: (row["change_pct"], row["quote_volume"]), reverse=True)
    if not ranked:
        raise RuntimeError("Binance TR top-gainer TRY listesi boş döndü")
    return ranked[:limit]


def summarize(events, initial_balance, window_bars):
    pnl = [event["trade"]["net_pnl_try"] for event in events]
    realized = sum(event["trade"]["realized_pnl_try"] for event in events)
    open_pnl = sum(event["trade"]["open_unrealized_pnl_try"] for event in events)
    total = sum(pnl)
    fees = sum(event["trade"]["fees_try"] for event in events)
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value <= 0]
    gains = sum(wins)
    loss_total = abs(sum(losses))

    running = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in pnl:
        running += value
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)

    bars_open = sum(event["trade"]["last_bar_idx"] - event["trade"]["entry_idx"] + 1 for event in events)
    return {
        "trades": len(events),
        "closed_trades": sum(event["trade"]["status"] == "closed" for event in events),
        "open_positions": sum(event["trade"]["status"] == "open" for event in events),
        "net_pnl_try": round(total, 4),
        "realized_net_pnl_try": round(realized, 4),
        "open_unrealized_pnl_try": round(open_pnl, 4),
        "gross_pnl_try": round(sum(event["trade"]["gross_pnl_try"] for event in events), 4),
        "fees_try": round(fees, 4),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(pnl) * 100, 2) if pnl else 0.0,
        "profit_factor": round(gains / loss_total, 3) if loss_total else None,
        "expectancy_try": round(total / len(pnl), 4) if pnl else 0.0,
        "max_drawdown_try": round(drawdown, 4),
        "exposure_pct": round(bars_open / window_bars * 100, 2) if window_bars else 0.0,
        "final_balance_try": round(initial_balance + total, 4),
        "reconciliation_delta_try": round((initial_balance + total) - (initial_balance + total), 8),
        "exit_reasons": dict(Counter(event["trade"]["exit_reason"] for event in events)),
    }


async def main(args):
    if args.end_time_ms is not None:
        end_open_ms = args.end_time_ms
    else:
        now_ms = int(time.time() * 1000) - args.end_minutes_ago * 60000
        end_open_ms = now_ms // MS_1M * MS_1M
    cutoff_ms = end_open_ms - 1
    start_ms = end_open_ms - args.hours * 3600000
    universe_selection = None
    if args.universe == "top-gainers":
        universe_selection = await select_top_gainers(args.universe_limit)
        symbols = [row["symbol"] for row in universe_selection]
    else:
        symbols = [value.strip().upper().replace("_", "") for value in (args.symbols or ["HEMITRY"])]
    required_days = math.ceil(args.hours / 24) + 2
    fetch_days = max(args.fetch_days, required_days)
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, fetch_days, cutoff_ms, semaphore) for symbol in symbols))

    all_events = []
    provenance = {}
    errors = {}
    raw_signal_count = 0
    trend_filtered_signal_count = 0
    blocked_by_trend_filter = 0
    blocked_open = 0
    blocked_cooldown = 0
    costs = cost_parameters(args)

    for symbol, rows, error in loaded:
        window_rows = [row for row in rows if start_ms <= row["close_time"] <= cutoff_ms]
        provenance[symbol] = {
            "m5_closed_candles": len(rows),
            "window_m5_candles": len(window_rows),
            "first_candle": iso(rows[0]["time"]) if rows else None,
            "last_candle": iso(rows[-1]["time"]) if rows else None,
        }
        if error or len(window_rows) < 2:
            errors[symbol] = error or f"insufficient window M5 history ({len(window_rows)} candles)"
            continue

        indicators = compute_indicators(rows)
        signals = run_state_machine(rows, indicators, start_ms, cutoff_ms, args.trend_filter)
        raw_signal_count += sum(signal["long_signal_raw"] for signal in signals)
        trend_filtered_signal_count += sum(
            signal["long_signal_raw"] and signal["trend_filter_pass"]
            for signal in signals
        )
        blocked_by_trend_filter += sum(
            signal["long_signal_raw"] and not signal["trend_filter_pass"]
            for signal in signals
        )
        equity = config.INITIAL_BALANCE_TRY
        last_entry_idx = None
        open_until_idx = -1

        for signal in signals:
            if not signal["long_signal_raw"]:
                continue
            if not signal["trend_filter_pass"]:
                continue
            if signal["idx"] < open_until_idx:
                blocked_open += 1
                continue
            if last_entry_idx is not None and signal["idx"] - last_entry_idx <= args.cooldown:
                blocked_cooldown += 1
                continue

            trade = simulate_trade(rows, indicators, signal, cutoff_ms, equity, costs)
            if trade is None:
                continue
            all_events.append({"symbol": symbol, "signal_time": signal["time"], "trade": trade})
            open_until_idx = trade["last_bar_idx"]
            last_entry_idx = trade["entry_idx"]
            equity += trade["net_pnl_try"]

    result_summary = summarize(all_events, config.INITIAL_BALANCE_TRY, len(window_rows) if "window_rows" in locals() else 0)
    result = {
        "paper_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "Vortex Breakout PRO v4.1 - Optimize SPOT LONG",
        "window": {"start": iso(start_ms), "end": iso(end_open_ms), "hours": args.hours},
        "source": "Binance TR public /api/v3/klines completed M1 OHLCV",
        "universe": {
            "mode": args.universe,
            "limit": args.universe_limit,
            "selection": universe_selection,
        },
        "provenance": {"per_symbol": provenance, "errors": errors},
        "configuration": {
            "bollinger_period": 21,
            "vortex_period": 8,
            "swing_length": 5,
            "atr_period": 15,
            "atr_sl_mult": 4.0,
            "swing_buffer_atr": 2.5,
            "partial": {"enabled": True, "tp1_qty_pct": 25, "tp1_r": 0.75, "tp2_r": 4.5, "be_r": 0.35},
            "filters": {
                "flat_width_ratio": 0.65,
                "flat_vi_diff": 0.1,
                "cooldown_bars": args.cooldown,
                "pb_expiry_bars": 50,
                "trend_filter": args.trend_filter,
            },
            "trailing": {"enabled": False},
            "position_size": "98%_equity_compounded",
            "pyramiding": 0,
        },
        "execution": {
            "entry": "next completed M1 bar open",
            "initial_balance_try": config.INITIAL_BALANCE_TRY,
            "cost_mode": args.cost_mode,
            "cost_multiplier": args.cost_multiplier,
            **costs,
        },
        "signal_flow": {
            "raw_long_signals": raw_signal_count,
            "trend_filter_passed_signals": trend_filtered_signal_count,
            "blocked_by_trend_filter": blocked_by_trend_filter,
            "selected_trades": len(all_events),
            "blocked_by_open_position": blocked_open,
            "blocked_by_cooldown": blocked_cooldown,
        },
        "result": result_summary,
        "trades_detail": all_events,
        "limitations": [
            "Source-aligned Python replay; not TradingView byte-identical.",
            "Public OHLCV has no historical spread/depth or intrabar order sequence.",
            "When stop and target occur in the same M5 bar, fill priority uses the open-to-target distance heuristic.",
            "Max drawdown is computed from completed trade PnL, not intrabar equity.",
            "A favorable 24-hour result cannot activate a paper-entry rule.",
            "Top-gainer universe selection reflects the current public 24h ticker snapshot; historical folds cannot reconstruct the universe as it appeared at each past bar.",
        ],
    }

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] " + args.output)
    print("RESULT_JSON=" + json.dumps(result_summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--end-minutes-ago", type=int, default=10)
    parser.add_argument("--end-time-ms", type=int)
    parser.add_argument("--fetch-days", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--trend-filter", choices=("none", "ema200", "ema200_slope", "adx20"), default="none")
    parser.add_argument("--universe", choices=("explicit", "top-gainers"), default="explicit")
    parser.add_argument("--universe-limit", type=int, default=10)
    parser.add_argument("--cooldown", type=int, default=3)
    parser.add_argument("--cost-mode", choices=("config", "pine"), default="config")
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--tick-size", type=float, default=0.0001)
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
