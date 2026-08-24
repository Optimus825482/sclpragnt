"""Causal, paper-only Pump Monitor replay using Binance TR completed M5 OHLCV.

This script intentionally models only information that is available from
historical candles.  Historical depth/order-book liquidity and ticker-level
intra-candle sequencing are unavailable, so those live gates are reported as
unknown rather than treated as passed.
"""
import argparse
import asyncio
import json
import math
import time
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.binance_tr_public import historical_klines
from app.config import config
from app.technical_analysis import _atr, _bollinger, _ema, _mfi, _rsi


MS_5M = 5 * 60 * 1000
ORDER_VALUE = float(config.FALLBACK_ORDER_TRY)
COST_MULTIPLIER = 1.0


def commission_pct():
    return config.COMMISSION_PCT * COST_MULTIPLIER


def spread_pct():
    return config.BACKTEST_ASSUMED_SPREAD_PCT * COST_MULTIPLIER


def slippage_pct():
    return config.ESTIMATED_SLIPPAGE_PCT * COST_MULTIPLIER


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(raw, cutoff_ms):
    rows = []
    for item in raw:
        try:
            row = {"time": int(item[0]), "open": float(item[1]), "high": float(item[2]),
                   "low": float(item[3]), "close": float(item[4]), "volume": float(item[5]),
                   "close_time": int(item[6])}
            if row["close_time"] <= cutoff_ms and row["high"] >= row["low"] > 0:
                rows.append(row)
        except (IndexError, TypeError, ValueError):
            continue
    return sorted({row["time"]: row for row in rows}.values(), key=lambda row: row["time"])


def resample(rows, minutes):
    bucket_ms = minutes * 60 * 1000
    groups = {}
    for row in rows:
        bucket = row["time"] - row["time"] % bucket_ms
        group = groups.get(bucket)
        if group is None:
            groups[bucket] = {"time": bucket, "open": row["open"], "high": row["high"],
                              "low": row["low"], "close": row["close"], "volume": row["volume"],
                              "close_time": row["close_time"], "count": 1}
        else:
            group["high"] = max(group["high"], row["high"]); group["low"] = min(group["low"], row["low"])
            group["close"] = row["close"]; group["volume"] += row["volume"]
            group["close_time"] = row["close_time"]; group["count"] += 1
    required = minutes // 5
    return [row for _, row in sorted(groups.items()) if row["count"] == required]


def alignment(rows):
    closes = [row["close"] for row in rows]
    ema9, ema21, ema50 = _ema(closes, 9), _ema(closes, 21), _ema(closes, 50)
    return "bullish" if ema9 and ema21 and ema50 and ema9 > ema21 > ema50 else "mixed"


def time_correlation(values, period=10):
    """Pine ta.correlation(close, bar_index, period) equivalent for a fixed window."""
    sample = [float(value) for value in values[-period:]]
    if len(sample) != period:
        return None
    x_mean, y_mean = (period - 1) / 2, sum(sample) / period
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(sample))
    x_sum = sum((index - x_mean) ** 2 for index in range(period))
    y_sum = sum((value - y_mean) ** 2 for value in sample)
    return numerator / math.sqrt(x_sum * y_sum) if x_sum > 0 and y_sum > 0 else None


def wilder_atr(rows, period=10):
    """Causal ta.atr-compatible Wilder smoothing for the SuperTrend research proxy."""
    values, previous_close, current = [], None, None
    for row in rows:
        tr = row["high"] - row["low"] if previous_close is None else max(row["high"] - row["low"], abs(row["high"] - previous_close), abs(row["low"] - previous_close))
        values.append(None)
        if len(values) == period:
            current = sum(max(r["high"] - r["low"], abs(r["high"] - (rows[j - 1]["close"] if j else r["close"])), abs(r["low"] - (rows[j - 1]["close"] if j else r["close"]))) for j, r in enumerate(rows[:period])) / period
            values[-1] = current
        elif len(values) > period and current is not None:
            current = (current * (period - 1) + tr) / period; values[-1] = current
        previous_close = row["close"]
    return values


def kmeans_three(values, max_iter=100):
    ordered = sorted(float(value) for value in values)
    if len(ordered) < 3:
        return None
    def percentile(p):
        pos = (len(ordered) - 1) * p; lo, hi = int(pos), math.ceil(pos)
        return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
    centroids = [percentile(.25), percentile(.50), percentile(.75)]
    for _ in range(max_iter):
        groups = [[], [], []]
        for value in values:
            index = min(range(3), key=lambda idx: abs(value - centroids[idx])); groups[index].append(value)
        updated = [sum(group) / len(group) if group else centroids[index] for index, group in enumerate(groups)]
        if all(abs(left - right) < 1e-12 for left, right in zip(centroids, updated)):
            break
        centroids = updated
    return sorted(centroids)


def supertrend_representatives(rows, atr_period=10, min_factor=1.0, max_factor=5.0, step=.5):
    """Independent research implementation of the supplied oscillator's three clusters.

    bear > 0 means every factor is bullish (the source plot calls this strong bullish).
    """
    factors = [min_factor + step * index for index in range(int((max_factor - min_factor) / step) + 1)]
    atr_values, states, output = wilder_atr(rows, atr_period), [None] * len(factors), {}
    for index, row in enumerate(rows):
        atr = atr_values[index]
        if atr is None:
            continue
        distances = []
        for factor_index, factor in enumerate(factors):
            upper_raw, lower_raw = (row["high"] + row["low"]) / 2 + atr * factor, (row["high"] + row["low"]) / 2 - atr * factor
            prior = states[factor_index]
            if prior is None:
                upper, lower, trend = upper_raw, lower_raw, 0
            else:
                upper = min(upper_raw, prior["upper"]) if rows[index - 1]["close"] < prior["upper"] else upper_raw
                lower = max(lower_raw, prior["lower"]) if rows[index - 1]["close"] > prior["lower"] else lower_raw
                trend = 1 if row["close"] > upper else 0 if row["close"] < lower else prior["trend"]
            line = lower if trend == 1 else upper
            states[factor_index] = {"upper": upper, "lower": lower, "trend": trend}
            distances.append(row["close"] - line)
        centroids = kmeans_three(distances)
        if centroids:
            output[index] = {"bear": centroids[0], "neutral": centroids[1], "bull": centroids[2]}
    return output


def signal_features(m5, m15, m30):
    closes = [row["close"] for row in m5]
    bb = _bollinger(closes)
    mfi = _mfi([r["high"] for r in m5], [r["low"] for r in m5], closes, [r["volume"] for r in m5])
    rsi = _rsi(closes)
    if not bb or mfi is None or rsi is None:
        return None
    a15, a30 = alignment(m15), alignment(m30)
    checks = {"bb": bb["position"] >= .80, "context": a15 == "bullish" or a30 == "bullish",
              "mfi": mfi >= 45, "rsi": rsi >= 65}
    atr = _atr([r["high"] for r in m5], [r["low"] for r in m5], closes, config.SYSTEM_ATR_PERIOD)
    return {"score": sum(checks.values()), "bb_position": float(bb["position"]), "mfi_14": float(mfi),
            "rsi_14": float(rsi), "m15_alignment": a15, "m30_alignment": a30, "checks": checks,
            "ema9": _ema(closes, 9), "ema21": _ema(closes, 21), "atr14": atr,
            "tsi_correlation_10": time_correlation(closes, 10)}


def fill_buy(price):
    return price * (1 + spread_pct() / 2 + slippage_pct())


def fill_sell(price):
    return price * (1 - spread_pct() / 2 - slippage_pct())


def simulate(rows, entry_index, end_ms):
    """Approximate Analyzer generic exits; stop is evaluated before high per bar."""
    if entry_index >= len(rows):
        return None
    entry_row = rows[entry_index]
    if entry_row["time"] >= end_ms:
        return None
    entry = fill_buy(entry_row["open"]); quantity = ORDER_VALUE / entry
    peak = entry; trailing = None; exit_price = exit_time = reason = None
    for index in range(entry_index, len(rows)):
        row = rows[index]
        if row["time"] >= end_ms:
            break
        elapsed = (row["close_time"] - entry_row["time"]) / 1000
        # The live manager sees ticks. With only OHLCV, adverse stop is first
        # when high/low order is ambiguous: conservative, deterministic replay.
        hard_stop = entry * (1 - config.HARD_STOP_LOSS_PCT)
        if row["low"] <= hard_stop:
            exit_price, exit_time, reason = hard_stop, row["close_time"], "system_stop_loss"
            break
        if trailing is not None and row["low"] <= trailing:
            exit_price, exit_time, reason = trailing, row["close_time"], "atr_trailing_stop"
            break
        peak = max(peak, row["high"])
        max_progress = max(0.0, (peak - entry) / entry)
        if elapsed >= config.EARLY_FAILURE_SEC and max_progress < config.EARLY_FAILURE_MIN_PROGRESS_PCT:
            exit_price, exit_time, reason = row["close"], row["close_time"], "early_failure_no_progress"
            break
        if elapsed >= config.STALE_POSITION_SEC and max_progress < config.STALE_POSITION_MIN_PROGRESS_PCT:
            exit_price, exit_time, reason = row["close"], row["close_time"], "stale_position_no_progress"
            break
        window = rows[:index + 1]
        atr = _atr([r["high"] for r in window], [r["low"] for r in window], [r["close"] for r in window], config.SYSTEM_ATR_PERIOD)
        if atr and max_progress >= atr * config.SYSTEM_ATR_TRAILING_ACTIVATION_ATR / entry:
            trailing = max(trailing or 0, peak - atr * config.SYSTEM_ATR_TRAILING_MULTIPLIER)
    if exit_price is None:
        observed = [row for row in rows[entry_index:] if row["close_time"] <= end_ms]
        if not observed:
            return None
        exit_price, exit_time, reason = observed[-1]["close"], observed[-1]["close_time"], "window_mark_to_market"
    exit_fill = fill_sell(exit_price); proceeds = quantity * exit_fill
    entry_fee, exit_fee = ORDER_VALUE * commission_pct(), proceeds * commission_pct()
    pnl = proceeds - exit_fee - ORDER_VALUE - entry_fee
    return {"entry_time": entry_row["time"], "exit_time": exit_time, "entry": entry, "exit": exit_fill,
            "pnl_try": pnl, "fees_try": entry_fee + exit_fee, "net_return_pct": pnl / (ORDER_VALUE + entry_fee) * 100,
            "reason": reason, "hold_minutes": (exit_time - entry_row["time"]) / 60000}


def allowed(features, name):
    if features["m15_alignment"] != "bullish":
        return False
    if name == "baseline": return features["score"] >= 3
    if name == "score4": return features["score"] >= 4
    if name == "m30_bullish": return features["score"] >= 3 and features["m30_alignment"] == "bullish"
    return features["score"] >= 4 and features["m30_alignment"] == "bullish" and features["bb_position"] < 1.0


def representative_allowed(event, representative):
    return allowed(event["features"], "baseline") and float((event.get("supertrend_representatives") or {}).get(representative) or 0) > 0


def cvd_proxy_series(rows):
    """TradingView-style lower-timeframe directional-volume proxy, not true CVD."""
    cumulative, signs, values, closes, times, running = [], [], [], [], [], 0.0
    previous_close, previous_sign = None, 0
    for row in rows:
        if row["close"] > row["open"]:
            sign = 1
        elif row["close"] < row["open"]:
            sign = -1
        elif previous_close is not None and row["close"] > previous_close:
            sign = 1
        elif previous_close is not None and row["close"] < previous_close:
            sign = -1
        else:
            sign = previous_sign
        delta = sign * row["volume"]
        running += delta; signs.append(sign); values.append(delta); cumulative.append(running)
        closes.append(row["close"]); times.append(row["close_time"])
        previous_close, previous_sign = row["close"], sign
    return {"times": times, "cumulative": cumulative, "deltas": values, "closes": closes}


def cvd_proxy_at(series, observation_ms):
    index = bisect_right(series["times"], observation_ms) - 1
    if index < 15:
        return None
    cumulative, closes = series["cumulative"], series["closes"]
    delta_5, delta_15 = cumulative[index] - cumulative[index - 5], cumulative[index] - cumulative[index - 15]
    price_new_high = closes[index] > max(closes[index - 15:index])
    cvd_new_high = cumulative[index] > max(cumulative[index - 15:index])
    return {"delta_5": delta_5, "delta_15": delta_15, "bearish_divergence": price_new_high and not cvd_new_high}


def cvd_proxy_allowed(event):
    cvd = event.get("cvd_proxy") or {}
    return (allowed(event["features"], "baseline") and cvd.get("delta_15", 0) > 0 and
            cvd.get("delta_5", 0) > 0 and not cvd.get("bearish_divergence", False))


def anchored_cvd_at(series, observation_ms, anchor_minutes=15):
    """M1 time-aggregation equivalent of requestVolumeDelta(..., "15M")."""
    anchor_ms = anchor_minutes * 60 * 1000
    anchor_start = observation_ms - observation_ms % anchor_ms
    end_index = bisect_right(series["times"], observation_ms)
    start_index = bisect_right(series["times"], anchor_start - 1)
    deltas, closes = series["deltas"][start_index:end_index], series["closes"][start_index:end_index]
    if not deltas:
        return None
    running, high, low = 0.0, 0.0, 0.0
    for delta in deltas:
        running += delta; high, low = max(high, running), min(low, running)
    price_new_high = len(closes) > 1 and closes[-1] > max(closes[:-1])
    cvd_new_high = running >= high
    return {"anchor_minutes": anchor_minutes, "open": 0.0, "high": high, "low": low, "last": running,
            "price_new_high": price_new_high, "cvd_new_high": cvd_new_high,
            "bearish_divergence": price_new_high and not cvd_new_high}


def anchored_cvd_allowed(event):
    candle = event.get("anchored_cvd") or {}
    return allowed(event["features"], "baseline") and candle.get("last", 0) >= candle.get("open", 0)


def anchored_cvd_trap_allowed(event):
    candle = event.get("anchored_cvd") or {}
    return (allowed(event["features"], "baseline") and candle.get("last", 0) > candle.get("open", 0) and
            candle.get("cvd_new_high", False) and not candle.get("bearish_divergence", False))


def anchored_m5_cvd_allowed(event):
    candle = event.get("anchored_m5_cvd") or {}
    return allowed(event["features"], "baseline") and candle.get("last", 0) >= candle.get("open", 0)


def wilder_dmi(rows, period=14):
    """Completed-candle DMI/ADX using Wilder smoothing, keyed by close time."""
    output, tr_values, plus_values, minus_values, dx_values = {}, [], [], [], []
    smoothed_tr = smoothed_plus = smoothed_minus = adx = None
    prior_adx = None
    for index in range(1, len(rows)):
        row, previous = rows[index], rows[index - 1]
        up_move, down_move = row["high"] - previous["high"], previous["low"] - row["low"]
        true_range = max(row["high"] - row["low"], abs(row["high"] - previous["close"]), abs(row["low"] - previous["close"]))
        tr_values.append(true_range)
        plus_values.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_values.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        if len(tr_values) == period:
            smoothed_tr, smoothed_plus, smoothed_minus = sum(tr_values), sum(plus_values), sum(minus_values)
        elif len(tr_values) > period:
            smoothed_tr = smoothed_tr - smoothed_tr / period + tr_values[-1]
            smoothed_plus = smoothed_plus - smoothed_plus / period + plus_values[-1]
            smoothed_minus = smoothed_minus - smoothed_minus / period + minus_values[-1]
        if smoothed_tr is None or smoothed_tr <= 0:
            continue
        plus_di, minus_di = 100 * smoothed_plus / smoothed_tr, 100 * smoothed_minus / smoothed_tr
        denominator = plus_di + minus_di
        dx_values.append(100 * abs(plus_di - minus_di) / denominator if denominator else 0.0)
        if len(dx_values) == period:
            adx = sum(dx_values) / period
        elif len(dx_values) > period and adx is not None:
            prior_adx, adx = adx, (adx * (period - 1) + dx_values[-1]) / period
        if adx is not None:
            output[row["close_time"]] = {"plus_di": plus_di, "minus_di": minus_di, "adx": adx,
                                       "adx_rising": prior_adx is not None and adx > prior_adx}
    return output


def confirmed_swing_low_avwap(rows, flank=2):
    """AVWAP resets only after a swing low is confirmed by later M5 candles."""
    output, anchor = {}, None
    for index, row in enumerate(rows):
        if index >= flank * 2:
            pivot = index - flank
            pivot_lows = [rows[item]["low"] for item in range(pivot - flank, pivot + flank + 1)]
            if rows[pivot]["low"] <= min(pivot_lows):
                anchor = pivot
        if anchor is None:
            continue
        window = rows[anchor:index + 1]
        volume = sum(item["volume"] for item in window)
        if volume <= 0:
            continue
        avwap = sum(((item["high"] + item["low"] + item["close"]) / 3) * item["volume"] for item in window) / volume
        output[index] = {"value": avwap, "anchor_index": anchor, "anchor_time": rows[anchor]["time"]}
    return output


def choppiness(rows, period=14):
    """Completed-candle CHOP(14), with the current reading's falling state."""
    values, output, prior = [], {}, None
    for index, row in enumerate(rows):
        if index == 0:
            values.append(None)
            continue
        previous = rows[index - 1]
        values.append(max(row["high"] - row["low"], abs(row["high"] - previous["close"]), abs(row["low"] - previous["close"])))
        if index < period:
            continue
        window = rows[index - period + 1:index + 1]
        price_range = max(item["high"] for item in window) - min(item["low"] for item in window)
        sum_tr = sum(value for value in values[index - period + 1:index + 1] if value is not None)
        if price_range <= 0 or sum_tr <= 0:
            continue
        current = 100 * math.log10(sum_tr / price_range) / math.log10(period)
        output[row["close_time"]] = {"value": current, "falling": prior is not None and current < prior}
        prior = current
    return output


def dmi_adx_allowed(event):
    dmi = event.get("dmi_15m") or {}
    return (allowed(event["features"], "baseline") and dmi.get("plus_di", 0) > dmi.get("minus_di", 0) and
            dmi.get("adx", 0) >= 25 and dmi.get("adx_rising", False))


def avwap_reclaim_allowed(event):
    return allowed(event["features"], "baseline") and event.get("avwap_reclaim", False)


def chop_allowed(event):
    chop = event.get("chop_15m") or {}
    return allowed(event["features"], "baseline") and chop.get("value", 100) < 38.2 and chop.get("falling", False)


def pullback_reclaim_events(symbol, rows, feature_by_index, end_ms, require_tsi=False):
    """One pre-declared, causal shadow rule: breakout -> pullback -> reclaim.

    It deliberately does not tune a parameter grid against this window.
    """
    events, state = [], None
    for index in sorted(feature_by_index):
        features = feature_by_index[index]; row = rows[index]
        if state and index > state["expires"]:
            state = None
        if state and state["phase"] == "armed":
            retrace_atr = (state["high"] - row["low"]) / state["atr"] if state["atr"] else math.inf
            valid_pullback = (.25 <= retrace_atr <= .80 and row["close"] >= features["ema21"] and row["close"] < state["high"])
            if row["close"] < features["ema21"]:
                state = None
            elif valid_pullback:
                state = {"phase": "reclaim", "expires": index + 2, "pullback_high": row["high"]}
        elif state and state["phase"] == "reclaim":
            prior_one = feature_by_index.get(index - 1, {}).get("tsi_correlation_10")
            prior_two = feature_by_index.get(index - 2, {}).get("tsi_correlation_10")
            tsi_ok = (not require_tsi or (features["tsi_correlation_10"] is not None and prior_one is not None and prior_two is not None and
                                          features["tsi_correlation_10"] > .35 and features["tsi_correlation_10"] > prior_one > prior_two))
            if row["close"] < features["ema21"]:
                state = None
            elif (row["close"] > state["pullback_high"] and row["close"] > features["ema9"] and
                  features["m15_alignment"] == "bullish" and tsi_ok):
                trade = simulate(rows, index + 1, end_ms)
                if trade:
                    events.append({"symbol": symbol, "signal_time": row["close_time"], "features": features, "trade": trade})
                state = None
        if state is None and (features["score"] >= 3 and features["m15_alignment"] == "bullish" and
                              features["checks"]["bb"] and features["atr14"]):
            state = {"phase": "armed", "expires": index + 3, "high": row["high"], "atr": features["atr14"]}
    return events


def portfolio(events, name, order_pct, remaining_cash_sizing, max_open_positions):
    """Chronological shared-wallet execution for research variants.

    The event's exit path is calculated from completed OHLCV only.  Notional is
    deliberately selected when the entry becomes due, so skipped/capital-bound
    events cannot silently retain the fixed 1,000 TRY sizing used by the older
    exploratory runner.
    """
    cash, peak_equity, max_dd, realized = float(config.INITIAL_BALANCE_TRY), float(config.INITIAL_BALANCE_TRY), 0.0, 0.0
    open_positions, trades, blocked, cooldown_until = {}, [], Counter(), {}
    use_rearm_cooldown = name == "pullback_reclaim_shadow"
    for event in sorted(events, key=lambda item: (item["signal_time"], item["symbol"])):
        now = event["signal_time"]
        for symbol, position in list(open_positions.items()):
            if position["trade"]["exit_time"] <= now:
                trade, order_value = position["trade"], position["order_value"]
                cash += order_value + trade["pnl_try"] + order_value * commission_pct()
                realized += trade["pnl_try"]; trades.append({**trade, "symbol": symbol, "signal_time": position["signal_time"]})
                if use_rearm_cooldown and trade["reason"] == "early_failure_no_progress":
                    cooldown_until[symbol] = trade["exit_time"] + 60 * 60 * 1000
                del open_positions[symbol]
        if event["symbol"] in open_positions:
            blocked["same_symbol_open"] += 1; continue
        if use_rearm_cooldown and now < cooldown_until.get(event["symbol"], 0):
            blocked["early_failure_cooldown"] += 1; continue
        if max_open_positions > 0 and len(open_positions) >= max_open_positions:
            blocked["pump_cap_reached"] += 1; continue
        available_cash = cash / (1 + commission_pct())
        order_value = (available_cash if remaining_cash_sizing else config.INITIAL_BALANCE_TRY) * order_pct
        order_value = min(order_value, available_cash)
        required = order_value * (1 + commission_pct())
        if cash < required:
            blocked["insufficient_cash"] += 1; continue
        if order_value < config.MIN_PARTIAL_ORDER_TRY:
            blocked["insufficient_cash"] += 1; continue
        cash -= required
        scale = order_value / ORDER_VALUE
        trade = {**event["trade"], "pnl_try": event["trade"]["pnl_try"] * scale,
                 "fees_try": event["trade"]["fees_try"] * scale,
                 "order_value_try": order_value}
        open_positions[event["symbol"]] = {**event, "trade": trade, "order_value": order_value}
        equity = cash + sum(pos["order_value"] + pos["trade"]["pnl_try"] + pos["order_value"] * commission_pct() for pos in open_positions.values())
        peak_equity = max(peak_equity, equity); max_dd = max(max_dd, peak_equity - equity)
    for symbol, position in open_positions.items():
        trade, order_value = position["trade"], position["order_value"]
        cash += order_value + trade["pnl_try"] + order_value * commission_pct()
        realized += trade["pnl_try"]; trades.append({**trade, "symbol": symbol, "signal_time": position["signal_time"]})
    net_values = [trade["pnl_try"] for trade in trades]; gains = sum(value for value in net_values if value > 0); losses = sum(value for value in net_values if value < 0)
    return {"trades": len(trades), "net_pnl_try": round(realized, 2), "fees_try": round(sum(t["fees_try"] for t in trades), 2),
            "wins": sum(v > 0 for v in net_values), "losses": sum(v <= 0 for v in net_values),
            "profit_factor": round(gains / abs(losses), 3) if losses else None,
            "expectancy_try": round(realized / len(trades), 2) if trades else 0.0,
            "max_drawdown_try": round(max_dd, 2), "final_balance_try": round(cash, 2),
            "reconciliation_delta_try": round(cash - (config.INITIAL_BALANCE_TRY + realized), 8),
            "exit_reasons": dict(Counter(t["reason"] for t in trades)), "blocked": dict(blocked), "trades_detail": trades}


async def fetch(symbol, days, end_ms, semaphore):
    async with semaphore:
        try:
            raw5, raw1 = await asyncio.gather(historical_klines(symbol, "5m", days, end_ms), historical_klines(symbol, "1m", days, end_ms))
            return symbol, normalize(raw5, end_ms), normalize(raw1, end_ms), None
        except Exception as exc:
            return symbol, [], [], f"{type(exc).__name__}: {exc}"


async def main(args):
    global COST_MULTIPLIER
    COST_MULTIPLIER = args.cost_multiplier
    if args.end_date:
        end_ms = int(datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc).timestamp() * 1000) - 1
    else:
        end_ms = (int(time.time() * 1000) - args.end_minutes_ago * 60000) // MS_5M * MS_5M - 1
    start_ms = end_ms - args.hours * 3600000
    symbols = [item.strip().upper().replace("_", "") for item in (args.symbols or config.SYMBOLS)]
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, end_ms, semaphore) for symbol in symbols))
    all_events, pullback_events, tsi_pullback_events, provenance, errors = [], [], [], {}, {}
    for symbol, rows, m1_rows, error in loaded:
        provenance[symbol] = {"m5_closed_candles": len(rows), "m1_closed_candles": len(m1_rows)}
        if error or len(rows) < 180 or len(m1_rows) < 60:
            errors[symbol] = error or "insufficient M5 history"; continue
        m15, m30 = resample(rows, 15), resample(rows, 30)
        representatives = supertrend_representatives(rows)
        dmi15, chop15 = wilder_dmi(m15), choppiness(m15)
        avwap5 = confirmed_swing_low_avwap(rows)
        cvd_series = cvd_proxy_series(m1_rows)
        m5_cvd_series = cvd_proxy_series(rows)
        t15, t30 = [r["close_time"] for r in m15], [r["close_time"] for r in m30]
        feature_by_index = {}
        for index, row in enumerate(rows[:-1]):
            if not start_ms <= row["close_time"] <= end_ms:
                continue
            w5 = rows[:index + 1]; w15 = m15[:bisect_right(t15, row["close_time"])]; w30 = m30[:bisect_right(t30, row["close_time"])]
            if min(len(w5), len(w15), len(w30)) < 55:
                continue
            features = signal_features(w5, w15, w30)
            trade = simulate(rows, index + 1, end_ms)
            cvd = cvd_proxy_at(cvd_series, row["close_time"])
            anchored_cvd = anchored_cvd_at(cvd_series, row["close_time"])
            anchored_m5_cvd = anchored_cvd_at(m5_cvd_series, row["close_time"])
            active_m15_index = bisect_right(t15, row["close_time"]) - 1
            current_avwap, previous_avwap = avwap5.get(index), avwap5.get(index - 1)
            avwap_reclaim = bool(current_avwap and previous_avwap and current_avwap["anchor_index"] <= index - 1 and
                                 rows[index - 1]["close"] <= previous_avwap["value"] and row["close"] > current_avwap["value"])
            if features and trade and cvd and anchored_cvd and anchored_m5_cvd:
                features["return_1h"] = row["close"] / rows[index - 12]["close"] - 1 if index >= 12 and rows[index - 12]["close"] else None
                feature_by_index[index] = features
                all_events.append({"symbol": symbol, "signal_time": row["close_time"], "features": features, "trade": trade,
                                   "supertrend_representatives": representatives.get(index), "cvd_proxy": cvd, "anchored_cvd": anchored_cvd,
                                   "anchored_m5_cvd": anchored_m5_cvd,
                                   "dmi_15m": dmi15.get(w15[-1]["close_time"]), "avwap_reclaim": avwap_reclaim,
                                   "chop_15m": chop15.get(m15[active_m15_index]["close_time"]) if active_m15_index >= 0 else None})
        pullback_events.extend(pullback_reclaim_events(symbol, rows, feature_by_index, end_ms))
        tsi_pullback_events.extend(pullback_reclaim_events(symbol, rows, feature_by_index, end_ms, require_tsi=True))
    execution = (args.order_pct, args.remaining_cash_sizing, args.max_open_positions)
    variants = {name: portfolio([{**event, "trade": event["trade"]} for event in all_events if allowed(event["features"], name)], name, *execution)
                for name in ("baseline", "score4", "m30_bullish", "strict_score4_m30_bb_lt_1")}
    variants["return_1h_le_1_13pct"] = portfolio([event for event in all_events if allowed(event["features"], "baseline") and event["features"].get("return_1h") is not None and event["features"]["return_1h"] <= .0113], "return_1h_le_1_13pct", *execution)
    variants["pullback_reclaim_shadow"] = portfolio(pullback_events, "pullback_reclaim_shadow", *execution)
    variants["pullback_reclaim_tsi_shadow"] = portfolio(tsi_pullback_events, "pullback_reclaim_tsi_shadow", *execution)
    variants["cvd_proxy_entry_filter"] = portfolio([event for event in all_events if cvd_proxy_allowed(event)], "cvd_proxy_entry_filter", *execution)
    variants["cvd_15m_anchor_entry_filter"] = portfolio([event for event in all_events if anchored_cvd_allowed(event)], "cvd_15m_anchor_entry_filter", *execution)
    variants["cvd_15m_anchor_trap_filter"] = portfolio([event for event in all_events if anchored_cvd_trap_allowed(event)], "cvd_15m_anchor_trap_filter", *execution)
    variants["cvd_15m_anchor_m5_entry_filter"] = portfolio([event for event in all_events if anchored_m5_cvd_allowed(event)], "cvd_15m_anchor_m5_entry_filter", *execution)
    variants["m15_dmi_adx_entry_filter"] = portfolio([event for event in all_events if dmi_adx_allowed(event)], "m15_dmi_adx_entry_filter", *execution)
    variants["swing_low_avwap_reclaim_filter"] = portfolio([event for event in all_events if avwap_reclaim_allowed(event)], "swing_low_avwap_reclaim_filter", *execution)
    variants["m15_chop_entry_filter"] = portfolio([event for event in all_events if chop_allowed(event)], "m15_chop_entry_filter", *execution)
    for representative in ("bull", "neutral", "bear"):
        variants[f"supertrend_{representative}_representative"] = portfolio(
            [event for event in all_events if representative_allowed(event, representative)], f"supertrend_{representative}_representative", *execution)
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(),
              "window": {"start": iso(start_ms), "end": iso(end_ms), "hours": args.hours}, "symbols": symbols,
              "provenance": {"source": "Binance TR public /api/v3/klines completed M5 and M1 OHLCV", "per_symbol": provenance, "errors": errors},
              "baseline_rule": "score>=3 + M15 bullish",
              "pullback_reclaim_shadow_rule": "Arm only at score>=3 + M15 bullish + BB>=0.80; within 3 M5 bars require 0.25-0.80 ATR pullback holding EMA21, then within 2 bars a close above pullback high and EMA9; enter next M5 open; after early-failure, re-arm only after 60 minutes.",
              "pullback_reclaim_tsi_shadow_rule": "Same shadow rule, plus TSI(10)=correlation(close, bar_index, 10) > 0.35 and rising for two completed M5 observations at reclaim.",
              "supertrend_representative_rules": {"bull": "least strict: highest K-means centroid of close-minus-SuperTrend factors > 0", "neutral": "middle centroid > 0", "bear": "strict unanimous bullish: lowest centroid > 0"},
              "supertrend_source_notice": "Supplied LuxAlgo code is CC BY-NC-SA 4.0. This is an independent, research-only calculation; it is not imported into or activated in product code.",
              "cvd_proxy_rule": "Baseline plus completed-M1 directional-volume proxy: delta_15m>0, delta_5m>0, and no price-new-high / CVD-not-new-high bearish divergence.",
              "cvd_15m_anchor_rule": "Pine requestVolumeDelta-style M1 time aggregation reset every 15 minutes; baseline only when the current anchor CVD candle closes at or above its open.",
              "cvd_15m_anchor_trap_rule": "Baseline plus positive 15-minute anchor CVD closing at its anchor high; block a price-new-high when anchor CVD is not at a new high.",
              "cvd_15m_anchor_m5_rule": "Same 15-minute anchor CVD candle rule, using completed M5 candles as the lower timeframe instead of M1.",
              "m15_dmi_adx_rule": "Baseline plus completed M15 +DI > -DI, ADX(14) >= 25, and ADX rising versus the prior completed M15 candle.",
              "swing_low_avwap_reclaim_rule": "Baseline plus M5 close reclaim above an AVWAP anchored to the latest swing low confirmed with two completed M5 candles on each side; enter next M5 open.",
              "m15_chop_rule": "Baseline plus completed M15 CHOP(14) < 38.2 and falling versus its prior completed M15 reading.",
              "variants": variants,
              "execution": {"order_pct": args.order_pct, "remaining_cash_sizing": args.remaining_cash_sizing, "initial_balance_try": config.INITIAL_BALANCE_TRY, "max_pump_positions": args.max_open_positions,
                            "cost_multiplier": COST_MULTIPLIER, "commission_pct_each_side": commission_pct(), "spread_pct": spread_pct(), "slippage_pct_each_side": slippage_pct(),
                            "entry": "next M5 open", "exit": "Analyzer generic exit approximation; adverse stop first within OHLC bar"},
              "limitations": ["Historical order-book/depth, live liquidity gate, ticker timing and M1-flat override are unavailable and not assumed passed.", "CVD proxy uses M1 candle direction; it is not trade-level/aggressor CVD.", "Open positions at replay end are marked to the final completed M5 close.", "The pullback/reclaim rule is research-only and must pass a separate chronological OOS window before any paper activation."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps({name: {key: value for key, value in summary.items() if key != "trades_detail"} for name, summary in variants.items()}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--end-minutes-ago", type=int, default=10)
    parser.add_argument("--end-date", help="UTC ISO bitiş zamanı; ör. 2026-08-24T00:50:00")
    parser.add_argument("--fetch-days", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument("--order-pct", type=float, default=config.ORDER_PCT)
    parser.add_argument("--remaining-cash-sizing", action="store_true")
    parser.add_argument("--max-open-positions", type=int, default=config.PUMP_MONITOR_MAX_OPEN_POSITIONS,
                        help="0 küresel sınırı kapatır; sembol başına tek açık işlem daima korunur")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    required_days = math.ceil((args.hours + 55 * 30 / 60) / 24)
    if args.hours < 1 or args.fetch_days < required_days or args.cost_multiplier <= 0:
        parser.error(f"hours>=1 ve bu pencere için fetch-days>={required_days} gerekli")
    asyncio.run(main(args))
