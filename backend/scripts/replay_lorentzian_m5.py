"""Paper-only M5 replay for the supplied Lorentzian Classification v2 settings.

This is a causal source-aligned implementation of the open Pine indicator. It
uses only completed Binance TR M5 candles and deliberately remains separate
from every product entry path.
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


MS_5M = 5 * 60 * 1000
ORDER_VALUE = float(config.FALLBACK_ORDER_TRY)


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(raw, cutoff):
    rows = []
    for value in raw:
        try:
            row = {"time": int(value[0]), "open": float(value[1]), "high": float(value[2]), "low": float(value[3]),
                   "close": float(value[4]), "volume": float(value[5]), "close_time": int(value[6])}
            if row["close_time"] <= cutoff and row["high"] >= row["low"] > 0:
                rows.append(row)
        except (IndexError, TypeError, ValueError):
            continue
    return sorted({row["time"]: row for row in rows}.values(), key=lambda row: row["time"])


def ema(values, period):
    output, current, alpha = [], None, 2 / (period + 1)
    for value in values:
        current = value if current is None else alpha * value + (1 - alpha) * current
        output.append(current)
    return output


def rma(values, period):
    output, current = [], None
    for index, value in enumerate(values):
        if index == period - 1:
            current = sum(values[:period]) / period
        elif index >= period and current is not None:
            current = (current * (period - 1) + value) / period
        output.append(current)
    return output


def rsi(values, period):
    changes = [0.0] + [values[index] - values[index - 1] for index in range(1, len(values))]
    gains, losses = rma([max(value, 0.0) for value in changes], period), rma([max(-value, 0.0) for value in changes], period)
    return [None if gain is None or loss is None else 100.0 if loss == 0 and gain > 0 else 50.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
            for gain, loss in zip(gains, losses)]


def cci(rows, period):
    typical = [(row["high"] + row["low"] + row["close"]) / 3 for row in rows]
    output = []
    for index, value in enumerate(typical):
        if index + 1 < period:
            output.append(None); continue
        window = typical[index - period + 1:index + 1]
        average = sum(window) / period
        deviation = sum(abs(item - average) for item in window) / period
        output.append((value - average) / (.015 * deviation) if deviation else 0.0)
    return output


def adx(rows, period):
    trs, plus, minus = [0.0], [0.0], [0.0]
    for index in range(1, len(rows)):
        row, previous = rows[index], rows[index - 1]
        up, down = row["high"] - previous["high"], previous["low"] - row["low"]
        trs.append(max(row["high"] - row["low"], abs(row["high"] - previous["close"]), abs(row["low"] - previous["close"])))
        plus.append(up if up > down and up > 0 else 0.0); minus.append(down if down > up and down > 0 else 0.0)
    sm_tr, sm_plus, sm_minus = rma(trs, period), rma(plus, period), rma(minus, period)
    dx = []
    for total, positive, negative in zip(sm_tr, sm_plus, sm_minus):
        if total is None or not total:
            dx.append(None); continue
        pdi, mdi = 100 * positive / total, 100 * negative / total
        dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    valid = [0.0 if value is None else value for value in dx]
    smoothed = rma(valid, period)
    return [None if index < period * 2 - 2 else value for index, value in enumerate(smoothed)]


def rescale(values, old_min, old_max):
    return [None if value is None else (value - old_min) / (old_max - old_min) for value in values]


def normalize_unbounded(values):
    """Pine MLExtensions normalize(): expanding historical min/max to [-1, 1]."""
    output, historic_min, historic_max = [], math.inf, -math.inf
    for value in values:
        if value is None:
            output.append(None); continue
        historic_min, historic_max = min(historic_min, value), max(historic_max, value)
        output.append(0.0 if historic_max == historic_min else -1 + 2 * (value - historic_min) / (historic_max - historic_min))
    return output


def wavetrend(rows, n1, n2):
    typical = [(row["high"] + row["low"] + row["close"]) / 3 for row in rows]
    esa = ema(typical, n1); deviation = ema([abs(value - base) for value, base in zip(typical, esa)], n1)
    ci = [0.0 if value == 0 else (source - base) / (.015 * value) for source, base, value in zip(typical, esa, deviation)]
    wt1 = ema(ci, n2)
    wt2 = [None if index < 3 else sum(wt1[index - 3:index + 1]) / 4 for index in range(len(wt1))]
    return [None if second is None else first - second for first, second in zip(wt1, wt2)]


def feature_matrix(rows):
    closes = [row["close"] for row in rows]
    # Screenshot settings: RSI(10,1), WT(7,16), CCI(30,1), ADX(30), RSI(21,1).
    rsi10, rsi21 = rsi(closes, 10), rsi(closes, 21)
    return list(zip(rescale(ema([value or 50.0 for value in rsi10], 1), 0, 100), normalize_unbounded(wavetrend(rows, 7, 16)),
                    normalize_unbounded(ema([value or 0.0 for value in cci(rows, 30)], 1)), rescale(adx(rows, 30), 0, 100),
                    rescale(ema([value or 50.0 for value in rsi21], 1), 0, 100)))


def rational_quadratic(closes, index, lookback=8, weight=8.0, start=25):
    if index < start:
        return None
    numerator = denominator = 0.0
    for lag in range(0, min(index + 1, start + lookback)):
        kernel = (1 + lag * lag / (2 * weight * lookback * lookback)) ** (-weight)
        numerator += closes[index - lag] * kernel; denominator += kernel
    return numerator / denominator if denominator else None


def regime_ok(closes, index, threshold=-.1):
    """Causal compact regime gate matching the source default directionally."""
    if index < 20:
        return False
    recent, prior = sum(closes[index - 9:index + 1]) / 10, sum(closes[index - 19:index - 9]) / 10
    return (recent - prior) / prior > threshold if prior else False


def volatility_ok(rows, index):
    if index < 10:
        return False
    ranges = [row["high"] - row["low"] for row in rows[index - 9:index + 1]]
    return ranges[-1] >= sum(ranges) / len(ranges) * .25


def signal_series(rows, first_index, max_bars=2000, neighbors=8):
    features, closes = feature_matrix(rows), [row["close"] for row in rows]
    output, prior_signal = [{"signal": 0, "prediction": 0, "new_long": False} for _ in rows], 0
    for index in range(first_index, len(features)):
        current = features[index]
        prediction = 0
        if index >= 35 and all(value is not None for value in current):
            distances, labels, last_distance = [], [], -1.0
            start = max(4, index - max_bars)
            for candidate in range(start, index - 3):
                if candidate % 4 == 0 or any(value is None for value in features[candidate]):
                    continue
                distance = sum(math.log(1 + abs(left - right)) for left, right in zip(current, features[candidate]))
                if distance >= last_distance:
                    # Exact supplied Pine label: src[4] < src ? short : long.
                    # At array index ``candidate``, src[4] is candidate - 4.
                    label = -1 if closes[candidate - 4] < closes[candidate] else 1 if closes[candidate - 4] > closes[candidate] else 0
                    distances.append(distance); labels.append(label); last_distance = distance
                    if len(labels) > neighbors:
                        last_distance = distances[round(neighbors * .75)]
                        distances.pop(0); labels.pop(0)
            prediction = sum(labels)
        yhat = rational_quadratic(closes, index)
        kernel_bullish = bool(yhat is not None and index > 0 and yhat > rational_quadratic(closes, index - 1))
        permitted = volatility_ok(rows, index) and regime_ok(closes, index)
        signal = 1 if prediction > 0 and permitted else -1 if prediction < 0 and permitted else prior_signal
        new_long = signal == 1 and signal != prior_signal and kernel_bullish
        output[index] = {"signal": signal, "prediction": prediction, "new_long": new_long}
        prior_signal = signal
    return output


def buy_fill(price):
    return price * (1 + config.BACKTEST_ASSUMED_SPREAD_PCT / 2 + config.ESTIMATED_SLIPPAGE_PCT)


def sell_fill(price):
    return price * (1 - config.BACKTEST_ASSUMED_SPREAD_PCT / 2 - config.ESTIMATED_SLIPPAGE_PCT)


def simulate(rows, signals, signal_index, end_ms):
    entry_index = signal_index + 1
    if entry_index >= len(rows) or rows[entry_index]["time"] >= end_ms:
        return None
    entry = buy_fill(rows[entry_index]["open"]); quantity = ORDER_VALUE / entry
    exit_index, reason = min(entry_index + 3, len(rows) - 1), "four_bar_exit"
    for index in range(entry_index, min(entry_index + 4, len(rows))):
        if signals[index]["signal"] == -1:
            exit_index, reason = index, "opposite_signal_before_four_bars"; break
    if rows[exit_index]["close_time"] > end_ms:
        eligible = [index for index in range(entry_index, len(rows)) if rows[index]["close_time"] <= end_ms]
        if not eligible:
            return None
        exit_index, reason = eligible[-1], "window_mark_to_market"
    proceeds = quantity * sell_fill(rows[exit_index]["close"])
    entry_fee, exit_fee = ORDER_VALUE * config.COMMISSION_PCT, proceeds * config.COMMISSION_PCT
    return {"entry_time": rows[entry_index]["time"], "exit_time": rows[exit_index]["close_time"], "pnl_try": proceeds - exit_fee - ORDER_VALUE - entry_fee,
            "fees_try": entry_fee + exit_fee, "reason": reason, "prediction": signals[signal_index]["prediction"]}


def portfolio(events):
    cash, realized, peak, drawdown, positions, trades, blocked = float(config.INITIAL_BALANCE_TRY), 0.0, float(config.INITIAL_BALANCE_TRY), 0.0, {}, [], Counter()
    for event in sorted(events, key=lambda item: (item["signal_time"], item["symbol"])):
        for symbol, position in list(positions.items()):
            if position["trade"]["exit_time"] <= event["signal_time"]:
                trade = position["trade"]; cash += ORDER_VALUE + trade["pnl_try"] + ORDER_VALUE * config.COMMISSION_PCT; realized += trade["pnl_try"]
                trades.append({**trade, "symbol": symbol}); del positions[symbol]
        if event["symbol"] in positions:
            blocked["same_symbol_open"] += 1; continue
        if len(positions) >= config.PUMP_MONITOR_MAX_OPEN_POSITIONS:
            blocked["position_cap"] += 1; continue
        cash -= ORDER_VALUE * (1 + config.COMMISSION_PCT); positions[event["symbol"]] = event
        equity = cash + sum(ORDER_VALUE + item["trade"]["pnl_try"] + ORDER_VALUE * config.COMMISSION_PCT for item in positions.values())
        peak, drawdown = max(peak, equity), max(drawdown, peak - equity)
    for symbol, position in positions.items():
        trade = position["trade"]; cash += ORDER_VALUE + trade["pnl_try"] + ORDER_VALUE * config.COMMISSION_PCT; realized += trade["pnl_try"]
        trades.append({**trade, "symbol": symbol})
    pnl = [trade["pnl_try"] for trade in trades]; gains, losses = sum(value for value in pnl if value > 0), sum(value for value in pnl if value < 0)
    return {"trades": len(trades), "net_pnl_try": round(realized, 2), "fees_try": round(sum(trade["fees_try"] for trade in trades), 2),
            "wins": sum(value > 0 for value in pnl), "losses": sum(value <= 0 for value in pnl), "profit_factor": round(gains / abs(losses), 3) if losses else None,
            "expectancy_try": round(realized / len(trades), 2) if trades else 0.0, "max_drawdown_try": round(drawdown, 2), "final_balance_try": round(cash, 2),
            "reconciliation_delta_try": round(cash - (config.INITIAL_BALANCE_TRY + realized), 8), "exit_reasons": dict(Counter(trade["reason"] for trade in trades)),
            "blocked": dict(blocked), "trades_detail": trades}


async def fetch(symbol, days, cutoff, semaphore):
    async with semaphore:
        try:
            return symbol, normalize(await historical_klines(symbol, "5m", days, cutoff), cutoff), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"


async def main(args):
    cutoff = (int(time.time() * 1000) - args.end_minutes_ago * 60000) // MS_5M * MS_5M - 1
    start = cutoff - args.hours * 3600000
    symbols = [value.strip().upper().replace("_", "") for value in (args.symbols or config.SYMBOLS)]
    semaphore = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(symbol, args.fetch_days, cutoff, semaphore) for symbol in symbols))
    events, provenance, errors = [], {}, {}
    for symbol, rows, error in loaded:
        provenance[symbol] = {"m5_closed_candles": len(rows)}
        if error or len(rows) < 2050:
            errors[symbol] = error or "insufficient M5 history"; continue
        first_index = max(35, next((index for index, row in enumerate(rows) if row["close_time"] >= start), len(rows)) - 50)
        signals = signal_series(rows, first_index)
        for index, row in enumerate(rows[:-4]):
            if not start <= row["close_time"] <= cutoff or not signals[index]["new_long"]:
                continue
            trade = simulate(rows, signals, index, cutoff)
            if trade:
                events.append({"symbol": symbol, "signal_time": row["close_time"], "trade": trade})
    result = {"paper_only": True, "generated_at": datetime.now(timezone.utc).isoformat(), "window": {"start": iso(start), "end": iso(cutoff), "hours": args.hours},
              "source": "Binance TR public /api/v3/klines completed M5 OHLCV", "provenance": {"per_symbol": provenance, "errors": errors},
              "configuration": {"feature_1": "RSI(10,1)", "feature_2": "WT(7,16)", "feature_3": "CCI(30,1)", "feature_4": "ADX(30,2)", "feature_5": "RSI(21,1)",
                                "neighbors": 8, "max_bars_back": 2000, "volatility_filter": True, "regime_filter": {"enabled": True, "threshold": -0.1}, "adx_filter": False,
                                "ema_filter": False, "sma_filter": False, "kernel_filter": {"enabled": True, "lookback": 8, "relative_weight": 8, "regression_level": 25}, "native_exit": "four M5 bars, or earlier opposite signal"},
              "execution": {"initial_balance_try": config.INITIAL_BALANCE_TRY, "order_value_try": ORDER_VALUE, "max_positions": config.PUMP_MONITOR_MAX_OPEN_POSITIONS,
                            "commission_pct_each_side": config.COMMISSION_PCT, "spread_pct": config.BACKTEST_ASSUMED_SPREAD_PCT, "slippage_pct_each_side": config.ESTIMATED_SLIPPAGE_PCT,
                            "entry": "next completed M5 bar open", "exit": "source-aligned strict four-bar exit on completed M5 data"},
              "result": portfolio(events), "limitations": ["Source imports MLExtensions and KernelFunctions. This replay causally reimplements their documented normalized RSI/WT/CCI/ADX and Rational Quadratic concepts; it cannot certify byte-for-byte TradingView parity without running the imported Pine libraries.", "Public OHLCV has no historical spread/depth or intrabar order sequence; fixed costs are modeled.", "A 24-hour result is exploratory and cannot activate a paper-entry rule."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT_JSON=" + json.dumps({key: value for key, value in result["result"].items() if key != "trades_detail"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24); parser.add_argument("--end-minutes-ago", type=int, default=10)
    parser.add_argument("--fetch-days", type=int, default=10); parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--symbols", nargs="*"); parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
