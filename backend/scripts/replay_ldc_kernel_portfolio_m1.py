"""Paper-only M1 portfolio replay for the supplied LDC Kernel Pro Pine strategy."""
import argparse
import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines, trading_symbols_with_filters
from app.config import config
from scripts.replay_ldc_kernel_m1 import (
    COMMISSION_PCT, INITIAL_BALANCE_TRY, MS_1M, SLIPPAGE_TICKS, adx, atr, ema,
    iso, mfi, missing_intervals, normalize, rational_quadratic, rsi, supertrend_direction,
)


ALLOCATION_PCT = 0.30


def signal_rows(rows, start_ms, end_ms):
    """Evaluate the supplied Pine signal conditions using completed M1 bars only."""
    closes = [row["close"] for row in rows]
    yhat = [rational_quadratic(closes, index) for index in range(len(rows))]
    adx_values, ema_values, rsi_values = adx(rows), ema(closes, 30), rsi(closes, 10)
    mfi_values, atr_values, directions = mfi(rows, 30), atr(rows, 14), supertrend_direction(rows)
    output, state_count, previous_state, start_kernel = {}, 0, None, None
    for index, row in enumerate(rows):
        current = yhat[index]
        if current is None or index < 2 or yhat[index - 2] is None:
            continue
        bullish = yhat[index - 1] < current
        state_count = state_count + 1 if bullish == previous_state else 1
        if bullish != previous_state:
            start_kernel = yhat[index - 1] if yhat[index - 1] is not None else current
        previous_state = bullish
        current_atr = atr_values[index]
        slope_ok = current_atr is not None and start_kernel is not None and abs(current - start_kernel) >= current_atr * .45
        confirmed_bullish = bullish and state_count >= 2 and slope_ok and current > yhat[index - 2]
        confirmed_bearish = not bullish and state_count >= 2 and slope_ok
        filters_ok = all((
            adx_values[index] is not None and adx_values[index] > 25,
            closes[index] > ema_values[index],
            rsi_values[index] is not None and rsi_values[index] > 65,
            directions[index] is not None and directions[index] > 0,  # Exact supplied Pine condition (+1 is down).
            mfi_values[index] is not None and mfi_values[index] > 70,
        ))
        if start_ms <= row["close_time"] <= end_ms:
            output[row["close_time"]] = {"index": index, "close": row["close"], "entry": confirmed_bullish and filters_ok,
                                           "exit": confirmed_bearish}
    return output


def portfolio(markets, start_ms, end_ms):
    times = sorted({timestamp for market in markets.values() for timestamp in market["signals"]})
    cash, positions, last_close_index, trades = INITIAL_BALANCE_TRY, {}, defaultdict(int), []
    latest_prices, peak, drawdown, max_positions, blocked = {}, INITIAL_BALANCE_TRY, 0.0, 0, Counter()

    def equity():
        marked = sum(position["quantity"] * max(0.0, latest_prices.get(symbol, position["entry_close"]) - SLIPPAGE_TICKS * position["tick_size"]) * (1 - COMMISSION_PCT)
                     for symbol, position in positions.items())
        return cash + marked

    for timestamp in times:
        active = {symbol: market["signals"].get(timestamp) for symbol, market in markets.items()}
        for symbol, signal in active.items():
            if signal:
                latest_prices[symbol] = signal["close"]
        closed_now = set()
        # Pine source closes before it can consider a later entry; process all exits first at the shared close.
        for symbol in sorted(positions):
            signal = active.get(symbol)
            if not signal or not signal["exit"]:
                continue
            position = positions.pop(symbol)
            fill = max(0.0, signal["close"] - SLIPPAGE_TICKS * position["tick_size"])
            proceeds = position["quantity"] * fill
            exit_fee = proceeds * COMMISSION_PCT
            cash += proceeds - exit_fee
            trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": timestamp,
                           "entry_fill": position["entry_fill"], "exit_fill": fill, "pnl_try": proceeds - exit_fee - position["entry_cost"],
                           "fees_try": position["entry_fee"] + exit_fee, "reason": "confirmed_bearish_kernel"})
            last_close_index[symbol] = signal["index"]
            closed_now.add(symbol)
        for symbol in sorted(markets):
            signal = active.get(symbol)
            if not signal or not signal["entry"]:
                continue
            if symbol in positions or symbol in closed_now:
                blocked["same_symbol_open_or_same_bar_close"] += 1
                continue
            if signal["index"] - last_close_index[symbol] < 5:
                blocked["cooldown"] += 1
                continue
            allocation = equity() * ALLOCATION_PCT
            if cash + 1e-9 < allocation:
                blocked["insufficient_cash_no_leverage"] += 1
                continue
            tick_size = markets[symbol]["tick_size"]
            fill = signal["close"] + SLIPPAGE_TICKS * tick_size
            notional = allocation / (1 + COMMISSION_PCT)
            entry_fee = notional * COMMISSION_PCT
            cash -= allocation
            positions[symbol] = {"quantity": notional / fill, "entry_time": timestamp, "entry_fill": fill, "entry_close": signal["close"],
                                 "entry_fee": entry_fee, "entry_cost": allocation, "tick_size": tick_size}
        current_equity = equity()
        peak, drawdown, max_positions = max(peak, current_equity), max(drawdown, peak - current_equity), max(max_positions, len(positions))
    for symbol, position in list(positions.items()):
        final = markets[symbol]["signals"].get(end_ms)
        if final is None:
            final = max(markets[symbol]["signals"].values(), key=lambda item: item["index"])
            exit_time = next(timestamp for timestamp, item in markets[symbol]["signals"].items() if item is final)
        else:
            exit_time = end_ms
        fill = max(0.0, final["close"] - SLIPPAGE_TICKS * position["tick_size"])
        proceeds = position["quantity"] * fill
        exit_fee = proceeds * COMMISSION_PCT
        cash += proceeds - exit_fee
        trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": exit_time,
                       "entry_fill": position["entry_fill"], "exit_fill": fill, "pnl_try": proceeds - exit_fee - position["entry_cost"],
                       "fees_try": position["entry_fee"] + exit_fee, "reason": "window_mark_to_market"})
    pnl = [trade["pnl_try"] for trade in trades]
    fees = sum(trade["fees_try"] for trade in trades)
    gains, losses = sum(value for value in pnl if value > 0), sum(value for value in pnl if value <= 0)
    by_symbol = {}
    for symbol in markets:
        group = [trade for trade in trades if trade["symbol"] == symbol]
        values = [trade["pnl_try"] for trade in group]
        by_symbol[symbol] = {"trades": len(group), "net_pnl_try": round(sum(values), 2), "fees_try": round(sum(trade["fees_try"] for trade in group), 2),
                             "wins": sum(value > 0 for value in values), "losses": sum(value <= 0 for value in values),
                             "exit_reasons": dict(Counter(trade["reason"] for trade in group))}
    return {"trades": len(trades), "gross_pnl_try": round(sum(pnl) + fees, 2), "net_pnl_try": round(sum(pnl), 2), "fees_try": round(fees, 2),
            "wins": sum(value > 0 for value in pnl), "losses": sum(value <= 0 for value in pnl),
            "profit_factor": round(gains / abs(losses), 3) if losses else None, "expectancy_try": round(sum(pnl) / len(pnl), 2) if pnl else 0.0,
            "max_drawdown_try": round(drawdown, 2), "max_concurrent_positions": max_positions, "final_balance_try": round(cash, 2),
            "reconciliation_delta_try": round(cash - INITIAL_BALANCE_TRY - sum(pnl), 8), "exit_reasons": dict(Counter(trade["reason"] for trade in trades)),
            "blocked": dict(blocked), "by_symbol": by_symbol, "trades_detail": trades}


async def fetch(symbol, cutoff, days, semaphore):
    async with semaphore:
        try:
            return symbol, normalize(await historical_klines(symbol, "1m", days, cutoff), cutoff), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    cutoff = (int(time.time() * 1000) - args.end_minutes_ago * MS_1M) // MS_1M * MS_1M - 1
    start = cutoff - args.hours * 3_600_000
    symbols = [value.upper().replace("_", "") for value in (args.symbols or config.SYMBOLS)]
    symbol_filters = await trading_symbols_with_filters("TRY")
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, cutoff, args.fetch_days, semaphore) for symbol in symbols))
    # The public adapter performs blocking requests in a worker thread; one shared semaphore protects the API.
    markets, errors, provenance = {}, {}, {}
    for symbol, rows, error in loaded:
        provenance[symbol] = {"m1_closed_candles": len(rows), "m1_missing_intervals": missing_intervals(rows) if rows else None,
                              "tick_size_try": float((symbol_filters.get(symbol) or {}).get("tick_size") or .01)}
        if error or len(rows) < 1_100:
            errors[symbol] = error or "insufficient completed M1 history"
            continue
        markets[symbol] = {"signals": signal_rows(rows, start, cutoff), "tick_size": provenance[symbol]["tick_size_try"]}
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(), "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "source": "Binance TR public /api/v3/klines completed M1 OHLCV", "provenance": {"per_symbol": provenance, "errors": errors},
              "configuration": {"strategy": "supplied LDC Kernel M3 Pro parameters evaluated on M1", "kernel": {"h": 8, "r": 10.0, "x": 15},
                                "confirm_bars": 2, "cooldown_bars": 5, "adx_threshold": 25, "ema_period": 30, "rsi_threshold": 65,
                                "supertrend": {"factor": 3.0, "atr_period": 21, "source_condition": "direction > 0 (Pine: down direction)"},
                                "mfi_threshold": 70, "min_kernel_move_atr": .45},
              "execution": {"initial_balance_try": INITIAL_BALANCE_TRY, "allocation_pct_of_current_equity": ALLOCATION_PCT, "long_only": True,
                            "pyramiding": False, "one_open_position_per_symbol": True, "global_open_position_cap": None, "no_leverage": True,
                            "commission_pct_each_side": COMMISSION_PCT, "slippage": f"{SLIPPAGE_TICKS} exchange price ticks each side",
                            "entry": "signal bar close (process_orders_on_close=true)", "exit": "confirmed bearish kernel bar close", "open_policy": "mark-to-market at window end"},
              "limitations": ["The Pine KernelFunctions import is causally ported, not byte-for-byte executable outside TradingView.", "Historical OHLCV has no intrabar sequence, spread or depth.", "No explicit position cap does not create leverage: an entry is skipped if 30% of current equity is not available as cash."]}
    result["result"] = portfolio(markets, start, cutoff) if markets else {"error": "no symbols with sufficient data"}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {key: value for key, value in result["result"].items() if key not in {"trades_detail", "by_symbol"}}
    print("RESULT_JSON=" + json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24); parser.add_argument("--fetch-days", type=int, default=3)
    parser.add_argument("--end-minutes-ago", type=int, default=3); parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--symbols", nargs="*"); parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
