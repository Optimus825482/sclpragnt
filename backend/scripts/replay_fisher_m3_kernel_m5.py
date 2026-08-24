"""Source-aligned paper replay for the supplied Fisher M3 + Kernel M5 Pine strategy.

The decision clock is completed M1 candles.  M3 Fisher and M5 Kernel values
are only released after their respective source candle closes (Pine
``request.security(..., lookahead_off)``), and orders fill at the next M1 open.
"""
import argparse
import asyncio
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config

MS_1M, MS_3M, MS_5M = 60_000, 180_000, 300_000


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def parse_end_date(value):
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError as exc:
        raise ValueError("end-date ISO-8601 olmalı, örn. 2026-08-24T12:00:00Z") from exc


def normalize(raw, cutoff):
    rows = []
    for item in raw:
        if len(item) < 7:
            continue
        close_time = int(item[6])
        if close_time > cutoff:
            continue
        rows.append({"time": int(item[0]), "close_time": close_time, "open": float(item[1]),
                     "high": float(item[2]), "low": float(item[3]), "close": float(item[4])})
    return sorted({row["time"]: row for row in rows}.values(), key=lambda row: row["time"])


def resample(rows, bucket_ms):
    buckets = {}
    for row in rows:
        bucket = row["time"] - row["time"] % bucket_ms
        group = buckets.setdefault(bucket, [])
        group.append(row)
    output = []
    expected = bucket_ms // MS_1M
    for stamp, group in sorted(buckets.items()):
        if len(group) != expected or any(group[i]["time"] != stamp + i * MS_1M for i in range(expected)):
            continue
        output.append({"time": stamp, "close_time": group[-1]["close_time"], "open": group[0]["open"],
                       "high": max(item["high"] for item in group), "low": min(item["low"] for item in group),
                       "close": group[-1]["close"]})
    return output


def fisher(rows, length):
    values, f1s, f2s = [], [], []
    value = f1 = 0.0
    for index, row in enumerate(rows):
        if index + 1 < length:
            values.append(None); f1s.append(None); f2s.append(None); continue
        window = rows[index - length + 1:index + 1]
        highs = [(item["high"] + item["low"]) / 2 for item in window]
        hi, lo, hl2 = max(highs), min(highs), (row["high"] + row["low"]) / 2
        previous_value, previous_f1 = value, f1
        ratio = (hl2 - lo) / (hi - lo) - 0.5 if hi != lo else 0.0
        value = max(-0.999, min(0.999, 0.66 * ratio + 0.67 * previous_value))
        f1 = 0.5 * math.log((1 + value) / (1 - value)) + 0.5 * previous_f1
        values.append(value); f1s.append(f1); f2s.append(previous_f1)
    return list(zip(f1s, f2s))


def kernel(rows, h=8, relative_weight=8.0, level=25, lag=2):
    output, gaussian_h = [], max(h - lag, 1)
    for index in range(len(rows)):
        if index < level + h:
            output.append((None, None)); continue
        ws_rq = wt_rq = ws_g = wt_g = 0.0
        for offset in range(level + h + 1):
            close = rows[index - offset]["close"]
            wrq = math.pow(1.0 + offset ** 2 / (2.0 * relative_weight * h ** 2), -relative_weight)
            wg = math.exp(-(offset ** 2) / (2.0 * gaussian_h ** 2))
            ws_rq += close * wrq; wt_rq += wrq; ws_g += close * wg; wt_g += wg
        output.append((ws_rq / wt_rq, ws_g / wt_g))
    return output


def held_at_m1(rows_m1, source_rows, values):
    result, source_index = [], 0
    current = None
    for row in rows_m1:
        while source_index < len(source_rows) and source_rows[source_index]["close_time"] <= row["close_time"]:
            current = values[source_index]
            source_index += 1
        result.append(current)
    return result


def atr_series(rows, length=14):
    """Wilder ATR using only the completed M1 bar available at entry time."""
    values, previous_close, atr = [], None, None
    for index, row in enumerate(rows):
        tr = row["high"] - row["low"] if previous_close is None else max(
            row["high"] - row["low"], abs(row["high"] - previous_close), abs(row["low"] - previous_close))
        if index + 1 < length:
            values.append(None)
        elif index + 1 == length:
            first_trs = []
            prior = None
            for item in rows[:length]:
                first_trs.append(item["high"] - item["low"] if prior is None else max(
                    item["high"] - item["low"], abs(item["high"] - prior), abs(item["low"] - prior)))
                prior = item["close"]
            atr = sum(first_trs) / length
            values.append(atr)
        else:
            atr = ((atr or tr) * (length - 1) + tr) / length
            values.append(atr)
        previous_close = row["close"]
    return values


def ema_series(values, length):
    if not values:
        return []
    alpha, ema, output = 2.0 / (length + 1), float(values[0]), []
    for value in values:
        ema = alpha * float(value) + (1 - alpha) * ema
        output.append(ema)
    return output


def close(cash, position, raw_price, commission, impact, when, reason):
    fill = raw_price * (1 - impact)
    proceeds = position["quantity"] * fill
    fee = proceeds * commission
    cash += proceeds - fee
    max_high_raw = max(position["entry"], position.get("max_high_raw", position["entry"]))
    gross_cost_per_unit = position["entry"] * (1 + commission)
    net_exit_per_unit_at_high = max_high_raw * (1 - impact) * (1 - commission)
    net_mfe_pct = (net_exit_per_unit_at_high / gross_cost_per_unit - 1) * 100
    return cash, {**position, "exit_time": when, "exit": fill, "exit_fee": fee, "reason": reason,
                  "max_high_raw": max_high_raw, "net_mfe_pct": net_mfe_pct,
                  "reached_net_breakeven": net_mfe_pct >= 0,
                  "pnl_try": proceeds - fee - position["order_value"] - position["entry_fee"]}


def replay(rows, start, end, commission, impact, profit_lock=False, fixed_stop_pct=None,
           atr_stop_multiple=None, atr_stop_min_pct=0.015, atr_stop_max_pct=0.030,
           m5_ema_bull_filter=False, net_breakeven_stop=False):
    m3, m5 = resample(rows, MS_3M), resample(rows, MS_5M)
    fish = held_at_m1(rows, m3, fisher(m3, 11))
    ker = held_at_m1(rows, m5, kernel(m5))
    atr_values = atr_series(rows)
    m5_closes = [item["close"] for item in m5]
    m5_trend = held_at_m1(rows, m5, [
        ema9 > ema21 > ema50
        for ema9, ema21, ema50 in zip(ema_series(m5_closes, 9), ema_series(m5_closes, 21), ema_series(m5_closes, 50))
    ])
    cash, position, trades, equity = 10_000.0, None, [], []
    for index, row in enumerate(rows[:-1]):
        if not start <= row["close_time"] <= end:
            continue
        f1, f2 = fish[index] if fish[index] else (None, None)
        pf1, pf2 = fish[index - 1] if index and fish[index - 1] else (None, None)
        rq, gauss = ker[index] if ker[index] else (None, None)
        ready = all(value is not None for value in (f1, f2, pf1, pf2, rq, gauss))
        cross_up = ready and f1 > f2 and pf1 <= pf2
        cross_down = ready and f1 < f2 and pf1 >= pf2
        next_open = rows[index + 1]["open"]
        if position:
            # The stop is evaluated first because a completed M1 OHLC bar
            # cannot reveal the intrabar ordering of a stop touch versus an
            # oscillator signal. A gap exits at the worse M1 open.
            stop_pct = fixed_stop_pct if fixed_stop_pct else position.get("initial_stop_pct")
            stop_raw = position["entry"] * (1 - stop_pct) if stop_pct else None
            if stop_raw is not None and row["low"] <= stop_raw:
                stop_fill_raw = min(row["open"], stop_raw)
                cash, trade = close(cash, position, stop_fill_raw, commission, impact, row["time"],
                                    (f"initial_fixed_stop_{fixed_stop_pct * 100:.1f}pct" if fixed_stop_pct
                                     else f"initial_atr_stop_{atr_stop_multiple:.1f}x"))
                trades.append(trade); position = None
            # Arm only after the current bar has completed. This intentionally
            # avoids assuming high occurred before low within the same M1 bar.
            if position and net_breakeven_stop and position["breakeven_armed"] and row["low"] <= position["breakeven_stop_raw"]:
                stop_fill_raw = min(row["open"], position["breakeven_stop_raw"])
                cash, trade = close(cash, position, stop_fill_raw, commission, impact, row["time"], "net_breakeven_stop")
                trades.append(trade); position = None
            if position:
                # MFE uses the bar high after the modeled next-open entry. It
                # remains a bar-level potential because public OHLCV does not
                # disclose intrabar order.
                position["max_high_raw"] = max(position["max_high_raw"], row["high"])
                if net_breakeven_stop and row["high"] >= position["breakeven_stop_raw"]:
                    position["breakeven_armed"] = True
            if position and profit_lock:
                if f1 >= 2.5:
                    position["fisher_floor"] = max(float(position["fisher_floor"]), 2.0)
                elif f1 >= 2.0:
                    position["fisher_floor"] = max(float(position["fisher_floor"]), 1.5)
                elif f1 >= 1.5:
                    position["fisher_floor"] = max(float(position["fisher_floor"]), 1.0)
                if pf1 >= position["fisher_floor"] and f1 < position["fisher_floor"]:
                    cash, trade = close(cash, position, next_open, commission, impact, rows[index + 1]["time"],
                                        f"fisher_profit_lock_floor_{position['fisher_floor']:.1f}")
                    trades.append(trade); position = None
            if position and cross_down and f1 > 2.0:
                cash, trade = close(cash, position, next_open, commission, impact, rows[index + 1]["time"], "fisher_cross_under_above_2")
                trades.append(trade); position = None
        trend_ok = not m5_ema_bull_filter or m5_trend[index] is True
        if not position and cross_up and f1 < -1.0 and gauss >= rq and trend_ok:
            value = cash * 0.20
            fee = value * commission
            if value + fee > cash:
                value = cash / (1 + commission); fee = value * commission
            entry = next_open * (1 + impact)
            initial_stop_pct = None
            if atr_stop_multiple is not None and atr_values[index] is not None:
                initial_stop_pct = min(atr_stop_max_pct, max(atr_stop_min_pct,
                                                              float(atr_values[index]) * atr_stop_multiple / entry))
            cash -= value + fee
            breakeven_stop_raw = entry * (1 + commission) / ((1 - impact) * (1 - commission))
            position = {"entry_time": rows[index + 1]["time"], "entry_signal_time": row["close_time"], "entry": entry,
                        "quantity": value / entry, "order_value": value, "entry_fee": fee, "entry_fisher": f1,
                        "fisher_floor": -math.inf, "initial_stop_pct": initial_stop_pct, "max_high_raw": entry,
                        "breakeven_stop_raw": breakeven_stop_raw, "breakeven_armed": False}
        mark = cash if not position else cash + position["quantity"] * row["close"] * (1 - impact) * (1 - commission)
        equity.append(mark)
    open_at_end = position is not None
    if position:
        last = next(item for item in reversed(rows) if item["close_time"] <= end)
        cash, trade = close(cash, position, last["close"], commission, impact, last["close_time"], "window_mark_to_market")
        trades.append(trade)
    gains = sum(max(trade["pnl_try"], 0) for trade in trades)
    losses = -sum(min(trade["pnl_try"], 0) for trade in trades)
    peak, drawdown = 10_000.0, 0.0
    for point in equity + [cash]:
        peak = max(peak, point); drawdown = max(drawdown, peak - point)
    profitable_trades = sum(trade["pnl_try"] > 0 for trade in trades)
    losing_trades = sum(trade["pnl_try"] < 0 for trade in trades)
    flat_trades = len(trades) - profitable_trades - losing_trades
    breakeven_touched = sum(trade["reached_net_breakeven"] for trade in trades)
    losing_breakeven_touched = sum(
        trade["pnl_try"] < 0 and trade["reached_net_breakeven"] for trade in trades)
    return {"trades": len(trades), "profitable_trades": profitable_trades, "losing_trades": losing_trades,
            "flat_trades": flat_trades, "win_rate_pct": round(profitable_trades / len(trades) * 100, 2) if trades else None,
            "net_pnl_try": round(cash - 10_000.0, 4), "fees_try": round(sum(t["entry_fee"] + t["exit_fee"] for t in trades), 4),
            "profit_factor": round(gains / losses, 4) if losses else None, "expectancy_try": round((cash - 10_000.0) / len(trades), 4) if trades else None,
            "max_drawdown_try": round(drawdown, 4), "final_balance_try": round(cash, 4), "open_position_at_end": open_at_end,
            "net_breakeven_touched_trades": breakeven_touched,
            "net_breakeven_touched_pct": round(breakeven_touched / len(trades) * 100, 2) if trades else None,
            "losing_trades_that_touched_net_breakeven": losing_breakeven_touched,
            "mean_net_mfe_pct": round(sum(trade["net_mfe_pct"] for trade in trades) / len(trades), 4) if trades else None,
            "exit_reasons": dict(Counter(t["reason"] for t in trades)), "reconciliation_delta_try": round(cash - 10_000.0 - sum(t["pnl_try"] for t in trades), 8), "trades_detail": trades}


async def main(args):
    requested_end = parse_end_date(args.end_date)
    cutoff = requested_end if requested_end is not None else int(time.time() * 1000) - 3 * MS_1M
    cutoff = min(cutoff, int(time.time() * 1000) - 3 * MS_1M)
    cutoff -= cutoff % MS_1M
    start = cutoff - args.hours * 3_600_000
    rows = normalize(await historical_klines(args.symbol, "1m", args.fetch_days, cutoff), cutoff)
    if len(rows) < args.hours * 60 + 200:
        raise RuntimeError("M3/M5 warm-up ve test penceresi için yeterli kapanmış M1 mum yok")
    source_commission = 0.001
    modeled_commission = float(config.COMMISSION_PCT) * args.cost_multiplier
    modeled_impact = (float(config.BACKTEST_ASSUMED_SPREAD_PCT) / 2 + float(config.ESTIMATED_SLIPPAGE_PCT)) * args.cost_multiplier
    variants = {"pine_commission_only_0_1pct_each_side": replay(rows, start, cutoff, source_commission, 0.0),
                "production_cost_model": replay(rows, start, cutoff, modeled_commission, modeled_impact),
                "production_cost_model_fisher_profit_lock": replay(rows, start, cutoff, modeled_commission, modeled_impact, True),
                "production_cost_model_initial_stop_1_5pct": replay(rows, start, cutoff, modeled_commission, modeled_impact, fixed_stop_pct=0.015),
                "production_cost_model_initial_stop_2_0pct": replay(rows, start, cutoff, modeled_commission, modeled_impact, fixed_stop_pct=0.020),
                "production_cost_model_initial_stop_3_0pct": replay(rows, start, cutoff, modeled_commission, modeled_impact, fixed_stop_pct=0.030),
                "production_cost_model_atr_stop_1_5x_clamped": replay(rows, start, cutoff, modeled_commission, modeled_impact, atr_stop_multiple=1.5),
                "production_cost_model_atr_stop_2_0x_clamped": replay(rows, start, cutoff, modeled_commission, modeled_impact, atr_stop_multiple=2.0),
                "production_cost_model_m5_ema_bull_filter": replay(rows, start, cutoff, modeled_commission, modeled_impact, m5_ema_bull_filter=True),
                "production_cost_model_m5_ema_bull_filter_atr_stop_1_5x": replay(rows, start, cutoff, modeled_commission, modeled_impact, atr_stop_multiple=1.5, m5_ema_bull_filter=True),
                "production_cost_model_m5_ema_bull_filter_atr_stop_1_5x_net_breakeven": replay(rows, start, cutoff, modeled_commission, modeled_impact, atr_stop_multiple=1.5, m5_ema_bull_filter=True, net_breakeven_stop=True)}
    if args.profile_stop_pct is not None:
        profile_pct = float(args.profile_stop_pct)
        variants[f"production_cost_model_profile_initial_stop_{profile_pct * 100:.1f}pct"] = replay(
            rows, start, cutoff, modeled_commission, modeled_impact, fixed_stop_pct=profile_pct)
    for value in variants.values(): value.pop("trades_detail", None)
    missing = sum(right["time"] - left["time"] != MS_1M for left, right in zip(rows, rows[1:]))
    result = {"paper_only": True, "generated_at": iso(int(time.time() * 1000)), "strategy": "Fisher M3 Cross + Kernel M5 Renk - Long Only",
              "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "provenance": {"source": "Binance TR public /api/v3/klines completed M1 OHLCV", "symbol": args.symbol, "closed_m1_candles": len(rows), "missing_m1_intervals": missing, "timezone": "UTC"},
              "rules": {"fisher": "M3, length=11; long crossover below -1", "kernel": "M5 rational-quadratic vs Gaussian, h=8 r=8 x=25 lag=2; green if Gaussian >= RQ", "exit": "M3 Fisher crossunder while Fisher > 2", "profit_lock_variant": "Fisher >=1.5 locks 1.0; >=2.0 locks 1.5; >=2.5 locks 2.0; exit next M1 open when Fisher crosses below its highest armed floor", "initial_stop_variants": "Fixed 1.5%, 2.0%, or 3.0% below modeled entry fill; a stop-touch exits intrabar at stop, or at the lower M1 open after a gap", "dynamic_atr_stop_variants": "Entry-time completed M1 Wilder ATR(14) x 1.5 or x 2.0, clamped to 1.5%-3.0%; the calculated stop is immutable after entry", "net_breakeven_stop_variant": "After a completed M1 high reaches the modeled all-in breakeven price, arm a stop there for subsequent M1 bars only; a gap exits at the lower M1 open", "m5_ema_bull_filter": "Require M5 EMA9 > EMA21 > EMA50 on the same closed M5 value released to M1 with lookahead_off", "pyramiding": 0, "order_pct_of_equity": 0.20, "fill": "completed M1 decision, next M1 open; M3/M5 security lookahead_off"},
              "cost_models": {"pine": "0.1% commission each side; no spread/slippage specified", "production": {"cost_multiplier": args.cost_multiplier, "commission_pct_each_side": modeled_commission, "full_spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT * args.cost_multiplier, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT * args.cost_multiplier}},
              "variants": variants, "limitations": ["Public OHLCV has no historical bid-ask spread, depth, or intrabar order sequence.", "A 24-hour sample is exploratory only and cannot approve an active paper rule.", "Source-aligned MTF replay; it is not a byte-identical TradingView Strategy Tester run."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE]")
    print("RESULT_JSON=" + json.dumps(variants, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="INJTRY")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--fetch-days", type=int, default=4)
    parser.add_argument("--end-date", help="UTC ISO-8601 test end timestamp")
    parser.add_argument("--profile-stop-pct", type=float, help="Entry-fixed stop profile, e.g. 0.02")
    parser.add_argument("--cost-multiplier", type=float, default=1.0, help="Scale production commission, spread and slippage")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.hours <= 0 or args.fetch_days < 2 or not 0 < args.cost_multiplier <= 3 or (args.profile_stop_pct is not None and not 0 < args.profile_stop_pct < 0.25):
        parser.error("hours pozitif ve fetch-days en az 2 olmalı")
    asyncio.run(main(args))
