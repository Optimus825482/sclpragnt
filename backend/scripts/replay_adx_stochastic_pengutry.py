"""Causal, fee-aware replay of the bundled ADX-Stochastic long strategy.

This is research-only.  It mirrors strategy/adx_stochastic.py: ADX(14)>20,
Stoch(14,3,3) K crosses above D after an oversold reading within 10 bars; the
long is closed on the corresponding overbought bearish crossover.  Optional
DI confirmation prevents long entries while -DI is at least +DI.
"""
import argparse
import asyncio
import json
import time
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts.replay_pump_monitor import normalize, resample


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def parse_end(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000) if value else int(time.time() * 1000) - 10 * 60 * 1000


def sma(values, length):
    out = []
    for i in range(len(values)):
        out.append(sum(values[i - length + 1:i + 1]) / length if i + 1 >= length else None)
    return out


def ema(rows, period):
    alpha, previous, values = 2 / (period + 1), None, []
    for row in rows:
        previous = row["close"] if previous is None else alpha * row["close"] + (1 - alpha) * previous
        values.append(previous)
    return values


def atr(rows, period=14):
    values, prior_close, prior_atr, trs = [], None, None, []
    for row in rows:
        tr = row["high"] - row["low"] if prior_close is None else max(row["high"] - row["low"], abs(row["high"] - prior_close), abs(row["low"] - prior_close))
        trs.append(tr)
        if len(trs) < period:
            values.append(None)
        elif prior_atr is None:
            prior_atr = sum(trs[-period:]) / period; values.append(prior_atr)
        else:
            prior_atr = (prior_atr * (period - 1) + tr) / period; values.append(prior_atr)
        prior_close = row["close"]
    return values


def indicators(rows, length=14, smooth_k=3, smooth_d=3):
    plus_dm, minus_dm, tr = [0.0], [0.0], [rows[0]["high"] - rows[0]["low"]]
    for i in range(1, len(rows)):
        up, down = rows[i]["high"] - rows[i - 1]["high"], rows[i - 1]["low"] - rows[i]["low"]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(rows[i]["high"] - rows[i]["low"], abs(rows[i]["high"] - rows[i - 1]["close"]), abs(rows[i]["low"] - rows[i - 1]["close"])))
    atr, plus_sm, minus_sm = [None] * len(rows), [None] * len(rows), [None] * len(rows)
    if len(rows) > length:
        atr[length] = sum(tr[1:length + 1]) / length
        plus_sm[length], minus_sm[length] = sum(plus_dm[1:length + 1]) / length, sum(minus_dm[1:length + 1]) / length
        for i in range(length + 1, len(rows)):
            atr[i] = (atr[i - 1] * (length - 1) + tr[i]) / length
            plus_sm[i] = (plus_sm[i - 1] * (length - 1) + plus_dm[i]) / length
            minus_sm[i] = (minus_sm[i - 1] * (length - 1) + minus_dm[i]) / length
    plus_di, minus_di, dx = [None] * len(rows), [None] * len(rows), [None] * len(rows)
    for i in range(len(rows)):
        if atr[i] and atr[i] > 0:
            plus_di[i], minus_di[i] = 100 * plus_sm[i] / atr[i], 100 * minus_sm[i] / atr[i]
            total = plus_di[i] + minus_di[i]
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / total if total else 0.0
    adx = [None] * len(rows)
    first = 2 * length
    if len(rows) > first:
        adx[first] = sum(x for x in dx[length + 1:first + 1] if x is not None) / length
        for i in range(first + 1, len(rows)):
            adx[i] = (adx[i - 1] * (length - 1) + dx[i]) / length
    raw_k = []
    for i, row in enumerate(rows):
        if i + 1 < length: raw_k.append(None); continue
        window = rows[i - length + 1:i + 1]
        highest, lowest = max(x["high"] for x in window), min(x["low"] for x in window)
        raw_k.append(100 * (row["close"] - lowest) / (highest - lowest) if highest > lowest else 50.0)
    k = sma([x if x is not None else 0.0 for x in raw_k], smooth_k)
    for i in range(len(k)):
        if raw_k[i] is None or i + 1 < length + smooth_k - 1: k[i] = None
    d = sma([x if x is not None else 0.0 for x in k], smooth_d)
    for i in range(len(d)):
        if k[i] is None or i + 1 < length + smooth_k + smooth_d - 2: d[i] = None
    return adx, plus_di, minus_di, k, d


def close(position, row, reason, cash, commission, impact):
    fill = row["open"] * (1 - impact)
    proceeds = position["quantity"] * fill
    fee = proceeds * commission
    cash += proceeds - fee
    return cash, {**position, "exit_time": row["time"], "exit": fill, "exit_fee": fee, "reason": reason, "pnl_try": proceeds - fee - position["order_value"] - position["entry_fee"]}


def replay(rows, start_ms, end_ms, order_pct, costs, require_di, require_m15_regime, atr_stop, rr_target):
    adx, plus_di, minus_di, k, d = indicators(rows)
    atr_values = atr(rows)
    m15 = resample(rows, 15)
    m15_times, m15_ema50, m15_ema200 = [row["close_time"] for row in m15], ema(m15, 50), ema(m15, 200)
    commission = float(config.COMMISSION_PCT) * costs
    impact = (float(config.BACKTEST_ASSUMED_SPREAD_PCT) / 2 + float(config.ESTIMATED_SLIPPAGE_PCT)) * costs
    cash, position, pending, trades, equity = float(config.INITIAL_BALANCE_TRY), None, None, [], []
    oversold_at, overbought_at = None, None
    diagnostic = {"window_bars": 0, "base_buy_signals": 0, "di_blocked_buy_signals": 0, "m15_regime_blocked_buy_signals": 0, "m15_bullish_regime_bars": 0, "accepted_entries": 0, "sell_signals": 0}
    for i, row in enumerate(rows[:-1]):
        in_window = start_ms <= row["close_time"] <= end_ms
        if not in_window: continue
        diagnostic["window_bars"] += 1
        m15_index = bisect_right(m15_times, row["close_time"]) - 1
        m15_bullish = m15_index >= 199 and m15[m15_index]["close"] > m15_ema50[m15_index] > m15_ema200[m15_index]
        if m15_bullish: diagnostic["m15_bullish_regime_bars"] += 1
        if pending is not None and pending["kind"] == "entry" and position is None:
            entry = row["open"] * (1 + impact)
            order_value = cash * order_pct
            entry_fee = order_value * commission
            if order_value + entry_fee > cash: order_value, entry_fee = cash / (1 + commission), cash / (1 + commission) * commission
            cash -= order_value + entry_fee
            position = {"entry_time": row["time"], "entry": entry, "quantity": order_value / entry, "order_value": order_value, "entry_fee": entry_fee, "entry_adx": adx[i - 1], "entry_plus_di": plus_di[i - 1], "entry_minus_di": minus_di[i - 1], "entry_k": k[i - 1], "entry_d": d[i - 1]}
            if atr_stop is not None:
                risk = pending["signal_atr"] * atr_stop
                position["stop"] = entry - risk
                position["target"] = entry + risk * rr_target
            diagnostic["accepted_entries"] += 1
        elif pending is not None and pending["kind"] == "exit" and position is not None:
            cash, trade = close(position, row, "stoch_overbought_cross", cash, commission, impact); trades.append(trade); position = None
        pending = None
        if position is not None and atr_stop is not None:
            path = (row["open"], row["high"], row["low"], row["close"]) if abs(row["open"] - row["high"]) <= abs(row["open"] - row["low"]) else (row["open"], row["low"], row["high"], row["close"])
            for left, right in zip(path, path[1:]):
                low, high = min(left, right), max(left, right)
                stop_hit, target_hit = low <= position["stop"] <= high, low <= position["target"] <= high
                if stop_hit or target_hit:
                    level, reason = (position["stop"], "atr_stop_loss") if stop_hit and (not target_hit or right < left) else (position["target"], "atr_take_profit")
                    exit_row = {**row, "open": level}
                    cash, trade = close(position, exit_row, reason, cash, commission, impact); trades.append(trade); position = None
                    break
        if all(value is not None for value in (adx[i], plus_di[i], minus_di[i], k[i], d[i])):
            if k[i] <= 20: oversold_at = i
            if k[i] >= 80: overbought_at = i
            cross_up = i > 0 and k[i - 1] is not None and d[i - 1] is not None and k[i - 1] <= d[i - 1] and k[i] > d[i]
            cross_down = i > 0 and k[i - 1] is not None and d[i - 1] is not None and k[i - 1] >= d[i - 1] and k[i] < d[i]
            buy = adx[i] > 20 and oversold_at is not None and i - oversold_at <= 10 and cross_up
            sell = adx[i] > 20 and overbought_at is not None and i - overbought_at <= 10 and cross_down
            if buy:
                diagnostic["base_buy_signals"] += 1
                if require_di and plus_di[i] <= minus_di[i]: diagnostic["di_blocked_buy_signals"] += 1
                elif require_m15_regime and not m15_bullish: diagnostic["m15_regime_blocked_buy_signals"] += 1
                elif position is None and atr_values[i] is not None: pending = {"kind": "entry", "signal_atr": atr_values[i]}
            if sell:
                diagnostic["sell_signals"] += 1
                if position is not None: pending = {"kind": "exit"}
        mark = cash if position is None else cash + position["quantity"] * row["close"] * (1 - impact)
        equity.append(mark)
    if position is not None:
        last = next(x for x in reversed(rows) if x["close_time"] <= end_ms)
        fill = last["close"] * (1 - impact); proceeds = position["quantity"] * fill; fee = proceeds * commission; cash += proceeds - fee
        trades.append({**position, "exit_time": last["time"], "exit": fill, "exit_fee": fee, "reason": "window_mark_to_market", "pnl_try": proceeds - fee - position["order_value"] - position["entry_fee"]})
    gross_profit, gross_loss = sum(max(x["pnl_try"], 0) for x in trades), -sum(min(x["pnl_try"], 0) for x in trades)
    peak, dd = float(config.INITIAL_BALANCE_TRY), 0.0
    for value in equity + [cash]: peak = max(peak, value); dd = max(dd, peak - value)
    return {"trades": len(trades), "wins": sum(x["pnl_try"] > 0 for x in trades), "losses": sum(x["pnl_try"] <= 0 for x in trades), "net_pnl_try": cash - float(config.INITIAL_BALANCE_TRY), "fees_try": sum(x["entry_fee"] + x["exit_fee"] for x in trades), "profit_factor": gross_profit / gross_loss if gross_loss else None, "expectancy_try": (cash - float(config.INITIAL_BALANCE_TRY)) / len(trades) if trades else None, "max_drawdown_try": dd, "final_balance_try": cash, "reconciliation_delta_try": cash - float(config.INITIAL_BALANCE_TRY) - sum(x["pnl_try"] for x in trades), "exit_reasons": {reason: sum(x["reason"] == reason for x in trades) for reason in sorted({x["reason"] for x in trades})}, "diagnostics": diagnostic, "trades_detail": trades}


async def main(args):
    end_ms = parse_end(args.end_date); start_ms = end_ms - args.hours * 3600000
    symbol = args.symbol.replace("_", "").upper()
    rows = normalize(await historical_klines(symbol, "5m", args.fetch_days, end_ms), end_ms)
    if len(rows) < 150: raise RuntimeError("ADX/Stochastic warm-up for insufficient completed M5 candles")
    summary = replay(rows, start_ms, end_ms, args.order_pct, args.cost_multiplier, args.require_di, args.require_m15_regime, args.atr_stop, args.rr_target)
    entry_rule = "completed M5 ADX(14)>20, Stoch(14,3,3) K crosses above D; K touched <=20 in last 10 completed bars"
    if args.require_di: entry_rule += "; +DI > -DI required"
    if args.require_m15_regime: entry_rule += "; last completed M15 close > EMA50 > EMA200 required"
    exit_rule = "completed M5 ADX(14)>20, Stoch K crosses below D; K touched >=80 in last 10 completed bars; fills next M5 open"
    if args.atr_stop is not None: exit_rule += f"; ATR(14) stop={args.atr_stop}x and target={args.rr_target}R, modeled on M5 OHLC path"
    result = {"paper_only": True, "strategy": f"{symbol} M5 ADX-Stochastic long", "window": {"start": iso(start_ms), "end": iso(end_ms), "hours": args.hours}, "provenance": {"source": "Binance TR public /api/v3/klines completed M5 OHLCV", "closed_m5_candles": len(rows)}, "rules": {"entry": entry_rule, "exit": exit_rule}, "execution": {"initial_balance_try": config.INITIAL_BALANCE_TRY, "order_pct_of_remaining_cash": args.order_pct, "single_open_position": True, "commission_pct_each_side": config.COMMISSION_PCT * args.cost_multiplier, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier}, "summary": summary, "limitations": ["Historical depth, spread and intrabar order sequence are unavailable; spread/slippage and M5 OHLC exit path are modeled."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps({k: v for k, v in summary.items() if k != "trades_detail"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="PENGUTRY"); parser.add_argument("--hours", type=int, default=24); parser.add_argument("--fetch-days", type=int, default=5); parser.add_argument("--end-date"); parser.add_argument("--order-pct", type=float, default=config.ORDER_PCT); parser.add_argument("--cost-multiplier", type=float, default=1.0); parser.add_argument("--require-di", action="store_true"); parser.add_argument("--require-m15-regime", action="store_true"); parser.add_argument("--atr-stop", type=float); parser.add_argument("--rr-target", type=float, default=2.0); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.hours < 1 or args.fetch_days < 2 or not 0 < args.order_pct <= 1 or args.cost_multiplier <= 0 or (args.atr_stop is not None and args.atr_stop <= 0) or args.rr_target <= 0: parser.error("invalid arguments")
    asyncio.run(main(args))
