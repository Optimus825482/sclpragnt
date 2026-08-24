"""Causal, fee-aware PENGUTRY SMC long replay: H1 sweep -> M5 CHoCH -> later OB retest."""
import argparse
import asyncio
import json
import math
import time
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from scripts.replay_pump_monitor import normalize, resample


def iso(ms): return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
def parse_end(value): return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000) if value else int(time.time() * 1000) - 10 * 60 * 1000


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
        if len(trs) < period: values.append(None)
        elif prior_atr is None: prior_atr = sum(trs[-period:]) / period; values.append(prior_atr)
        else: prior_atr = (prior_atr * (period - 1) + tr) / period; values.append(prior_atr)
        prior_close = row["close"]
    return values


def index_at(times, timestamp):
    index = bisect_right(times, timestamp) - 1
    return index if index >= 0 else None


def close_long(position, exit_time, exit_price, reason, cash, commission, impact):
    fill = exit_price * (1 - impact); proceeds = position["quantity"] * fill; exit_fee = proceeds * commission; cash += proceeds - exit_fee
    trade = {**position, "exit_time": exit_time, "exit": fill, "exit_fee": exit_fee, "reason": reason, "pnl_try": proceeds - exit_fee - position["order_value"] - position["entry_fee"]}
    return cash, trade


def replay(rows, start_ms, end_ms, order_pct, cost_multiplier, swing_minutes, swing_lookback, retest_bars, entry_mode):
    m15, swing_rows = resample(rows, 15), resample(rows, swing_minutes)
    swing_times, m15_times = [r["close_time"] for r in swing_rows], [r["close_time"] for r in m15]
    m15_e50, m15_e200, m5_atr = ema(m15, 50), ema(m15, 200), atr(rows)
    commission = float(config.COMMISSION_PCT) * cost_multiplier
    impact = (float(config.BACKTEST_ASSUMED_SPREAD_PCT) / 2 + float(config.ESTIMATED_SLIPPAGE_PCT)) * cost_multiplier
    cash, position, state, trades, equity = float(config.INITIAL_BALANCE_TRY), None, None, [], []
    diagnostics = {"m5_bars_in_window": 0, "m15_bullish_regime_bars": 0, "sweeps_in_regime": 0, "choch_confirmations": 0, "later_ob_retests": 0, "accepted_entries": 0}
    pending = None
    for i, row in enumerate(rows[:-1]):
        if not start_ms <= row["close_time"] <= end_ms: continue
        diagnostics["m5_bars_in_window"] += 1
        if pending is not None and pending["fill_index"] == i and position is None:
            entry = row["open"] * (1 + impact)
            if pending["stop"] < entry < pending["target"]:
                order_value = cash * order_pct; entry_fee = order_value * commission
                if order_value + entry_fee > cash: order_value, entry_fee = cash / (1 + commission), cash / (1 + commission) * commission
                cash -= order_value + entry_fee
                position = {**pending, "entry_time": row["time"], "entry": entry, "quantity": order_value / entry, "order_value": order_value, "entry_fee": entry_fee}
            pending = None
        if position is not None:
            sl, tp = position["stop"], position["target"]
            path = (row["open"], row["high"], row["low"], row["close"]) if abs(row["open"] - row["high"]) <= abs(row["open"] - row["low"]) else (row["open"], row["low"], row["high"], row["close"])
            for a, b in zip(path, path[1:]):
                lo, hi = min(a, b), max(a, b); sl_hit, tp_hit = lo <= sl <= hi, lo <= tp <= hi
                if sl_hit or tp_hit:
                    level, reason = (sl, "stop_loss") if sl_hit and (not tp_hit or (b < a)) else (tp, "take_profit")
                    cash, trade = close_long(position, row["time"], level, reason, cash, commission, impact); trades.append(trade); position = None; break
        swing_i, m15_i = index_at(swing_times, row["close_time"]), index_at(m15_times, row["close_time"])
        trend = m15_i is not None and m15_i >= 200 and m15[m15_i]["close"] > m15_e50[m15_i] > m15_e200[m15_i]
        if trend: diagnostics["m15_bullish_regime_bars"] += 1
        if position is None and pending is None and trend and swing_i is not None and swing_i >= swing_lookback and m5_atr[i] is not None:
            swing_low = min(item["low"] for item in swing_rows[swing_i - swing_lookback:swing_i])
            if state is None and row["low"] < swing_low and row["close"] > swing_low:
                state = {"phase": "swept", "sweep_index": i, "sweep_low": row["low"], "expires": i + 24}
                diagnostics["sweeps_in_regime"] += 1
            elif state is not None and i > state["expires"]:
                state = None
            elif state is not None and state["phase"] == "swept" and i >= state["sweep_index"] + 8:
                micro_high = max(item["high"] for item in rows[i - 8:i])
                if row["close"] > micro_high:
                    bearish = [j for j in range(max(0, i - 20), i) if rows[j]["close"] < rows[j]["open"]]
                    if bearish:
                        j = bearish[-1]
                        diagnostics["choch_confirmations"] += 1
                        if entry_mode == "aggressive_choch":
                            stop = min(state["sweep_low"] - .25 * m5_atr[i], row["close"] - 1.2 * m5_atr[i]); risk = row["close"] - stop
                            if risk > 0:
                                pending = {"fill_index": i + 1, "stop": stop, "target": row["close"] + 2 * risk, "sweep_time": rows[state["sweep_index"]]["close_time"], "confirm_time": row["close_time"], "ob_low": rows[j]["low"], "ob_high": rows[j]["high"]}
                                diagnostics["accepted_entries"] += 1
                            state = None
                        else:
                            state = {**state, "phase": "confirmed", "confirm_index": i, "ob_low": rows[j]["low"], "ob_high": rows[j]["high"], "expires": i + retest_bars}
            elif state is not None and state["phase"] == "confirmed" and i > state["confirm_index"]:
                if row["low"] <= state["ob_high"] and row["high"] >= state["ob_low"]:
                    diagnostics["later_ob_retests"] += 1
                    stop = min(state["sweep_low"] - .25 * m5_atr[i], row["close"] - 1.2 * m5_atr[i]); risk = row["close"] - stop
                    if risk > 0:
                        pending = {"fill_index": i + 1, "stop": stop, "target": row["close"] + 2 * risk, "sweep_time": rows[state["sweep_index"]]["close_time"], "confirm_time": rows[state["confirm_index"]]["close_time"], "ob_low": state["ob_low"], "ob_high": state["ob_high"]}
                        diagnostics["accepted_entries"] += 1
                    state = None
        mark = cash if position is None else cash + position["quantity"] * row["close"] * (1 - impact); equity.append(mark)
    if position is not None:
        last = next(r for r in reversed(rows) if r["close_time"] <= end_ms); cash, trade = close_long(position, last["close_time"], last["close"], "window_mark_to_market", cash, commission, impact); trades.append(trade)
    gp, gl = sum(max(t["pnl_try"], 0) for t in trades), -sum(min(t["pnl_try"], 0) for t in trades); peak, dd = float(config.INITIAL_BALANCE_TRY), 0.0
    for value in equity + [cash]: peak = max(peak, value); dd = max(dd, peak - value)
    return {"trades": len(trades), "wins": sum(t["pnl_try"] > 0 for t in trades), "losses": sum(t["pnl_try"] <= 0 for t in trades), "net_pnl_try": cash - float(config.INITIAL_BALANCE_TRY), "fees_try": sum(t["entry_fee"] + t["exit_fee"] for t in trades), "profit_factor": gp / gl if gl else None, "expectancy_try": (cash - float(config.INITIAL_BALANCE_TRY)) / len(trades) if trades else None, "max_drawdown_try": dd, "final_balance_try": cash, "reconciliation_delta_try": cash - float(config.INITIAL_BALANCE_TRY) - sum(t["pnl_try"] for t in trades), "exit_reasons": {x: sum(t["reason"] == x for t in trades) for x in sorted({t["reason"] for t in trades})}, "diagnostics": diagnostics, "trades_detail": trades}


async def main(args):
    end_ms = parse_end(args.end_date); start_ms = end_ms - args.hours * 3600000
    rows = normalize(await historical_klines("PENGUTRY", "5m", args.fetch_days, end_ms), end_ms)
    if len(rows) < 650: raise RuntimeError("M15 EMA200 için yeterli kapanmış M5 veri yok")
    summary = replay(rows, start_ms, end_ms, args.order_pct, args.cost_multiplier, args.swing_minutes, args.swing_lookback, args.retest_bars, args.entry_mode)
    entry_rule = "enter next M5 open at CHoCH confirmation" if args.entry_mode == "aggressive_choch" else f"last bearish OB must be retested only on a later bar within {args.retest_bars} M5 bars; enter next M5 open"
    result = {"paper_only": True, "strategy": f"PENGUTRY long SMC: real {args.swing_minutes}m sweep -> M5 CHoCH -> {args.entry_mode}", "window": {"start": iso(start_ms), "end": iso(end_ms), "hours": args.hours}, "provenance": {"source": "Binance TR public /api/v3/klines completed M5 OHLCV", "closed_m5_candles": len(rows)}, "rules": {"regime": "completed M15 close > EMA50 > EMA200", "entry": f"completed {args.swing_minutes}m-derived swing({args.swing_lookback}) liquidity sweep, then M5 close above prior 8-bar high within 24 M5 bars; {entry_rule}", "exit": "stop below sweep/ATR and fixed 2R target"}, "execution": {"initial_balance_try": config.INITIAL_BALANCE_TRY, "order_pct_of_remaining_cash": args.order_pct, "single_open_position": True, "cost_multiplier": args.cost_multiplier, "commission_pct_each_side": config.COMMISSION_PCT * args.cost_multiplier, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier}, "summary": summary, "limitations": ["Historical depth, spread and intrabar sequence are unavailable; OHLC exit path is modeled.", "Research-only source-aligned replay; not an active strategy."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"); print("RESULT_JSON=" + json.dumps({k: v for k, v in summary.items() if k != "trades_detail"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--hours", type=int, default=24); parser.add_argument("--fetch-days", type=int, default=5); parser.add_argument("--end-date"); parser.add_argument("--order-pct", type=float, default=config.ORDER_PCT); parser.add_argument("--cost-multiplier", type=float, default=1.0); parser.add_argument("--swing-minutes", type=int, choices=[15, 60], default=60); parser.add_argument("--swing-lookback", type=int, default=6); parser.add_argument("--retest-bars", type=int, default=12); parser.add_argument("--entry-mode", choices=["retest_ob", "aggressive_choch"], default="retest_ob"); parser.add_argument("--output", required=True); args = parser.parse_args()
    if args.hours < 1 or args.fetch_days < 3 or not 0 < args.order_pct <= 1 or args.cost_multiplier <= 0: parser.error("invalid arguments")
    asyncio.run(main(args))
