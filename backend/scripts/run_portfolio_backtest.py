"""Chronological shared-wallet replay of the live BB-MFI paper strategy."""

import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analyzer import ScalpAnalyzer
from app import database
from app.binance_tr_public import historical_klines, orderbook, ticker_24h, trading_symbols
from app.config import config
from app.technical_analysis import _mfi


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def rows_to_series(rows):
    result = {key: [] for key in ("opens", "highs", "lows", "closes", "volumes", "times")}
    seen = set()
    now_ms = int(time.time() * 1000)
    for row in rows:
        if isinstance(row, dict):
            close_ms = int(row["close_time"])
            values = [float(row[key]) for key in ("open", "high", "low", "close", "volume")]
        else:
            close_ms = int(row[6])
            values = [float(row[index]) for index in range(1, 6)]
        if close_ms > now_ms or close_ms in seen:
            continue
        if not all(math.isfinite(value) for value in values):
            continue
        seen.add(close_ms)
        for key, value in zip(("opens", "highs", "lows", "closes", "volumes"), values):
            result[key].append(value)
        result["times"].append(close_ms // 1000)
    return result


def window_at(data, index, lookback=250):
    """Bound replay indicator input; BB/MFI/RSI need far less than full history."""
    start = max(0, index - lookback + 1)
    return {key: values[start:index + 1] for key, values in data.items()}


def data_quality(data):
    times = data.get("times", [])
    gaps = [times[index] - times[index - 1] for index in range(1, len(times))
            if times[index] - times[index - 1] > 450]
    return {
        "candle_count": len(times), "sorted": times == sorted(times),
        "duplicate_timestamps": len(times) != len(set(times)),
        "missing_gap_count": len(gaps), "max_gap_seconds": max(gaps) if gaps else 0,
    }


def arm_profit_lock(position, candle_high, trigger_pct, lock_pct):
    """Raise a long position's exit floor after a confirmed profitable move.

    The caller invokes this after intrabar exits, so an OHLC bar that merely
    touched the trigger cannot also claim a same-bar stop fill.
    """
    if trigger_pct <= 0 or candle_high < position["entry"] * (1 + trigger_pct):
        return False
    candidate = position["entry"] * (1 + lock_pct)
    previous = float(position.get("profit_lock_stop") or 0)
    if candidate <= previous:
        return False
    position["profit_lock_stop"] = candidate
    return True


def activity_metrics(analyzer, data, quote_volume, spread_pct):
    closes, highs, lows, volumes = (data[key] for key in ("closes", "highs", "lows", "volumes"))
    if len(closes) < 21:
        return {"status": "WARMING", "reason": "insufficient_candles"}
    low, high = min(lows[-3:]), max(highs[-3:])
    range_pct = ((high - low) / low * 100) if low else 0.0
    atr = analyzer.calculate_atr(data, 14) or 0.0
    atr_pct = atr / closes[-1] if closes[-1] else 0.0
    average_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / average_volume if average_volume else 0.0
    checks = {
        "quote_volume": quote_volume >= config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY,
        "range_15m": range_pct >= config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT,
        "atr": atr_pct >= config.SYMBOL_ACTIVITY_MIN_ATR_PCT,
        "volume_ratio": volume_ratio >= config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO,
        "spread": spread_pct is not None and spread_pct <= config.SYMBOL_ACTIVITY_MAX_SPREAD_PCT,
    }
    return {
        "status": "ACTIVE" if all(checks.values()) else "PASSIVE",
        "quote_volume": round(quote_volume, 2), "range_15m_pct": round(range_pct, 4),
        "atr_pct": round(atr_pct * 100, 4), "volume_ratio": round(volume_ratio, 4),
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "checks": checks,
        "reason": "active" if all(checks.values()) else "movement_or_liquidity_below_threshold",
    }


def historical_activity(analyzer, window, spread_pct):
    """Time-correct counterpart of the live activity gate for replay."""
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    if len(closes) < 21:
        return False, "warming"
    quote_volume = sum(close * volume for close, volume in zip(closes[-288:], volumes[-288:]))
    range_pct = ((max(highs[-3:]) - min(lows[-3:])) / min(lows[-3:]) * 100) if min(lows[-3:]) else 0.0
    atr = analyzer.calculate_atr(window, 14) or 0.0
    atr_pct = atr / closes[-1] if closes[-1] else 0.0
    avg_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / avg_volume if avg_volume else 0.0
    active = (quote_volume >= config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY and
              range_pct >= config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT and
              atr_pct >= config.SYMBOL_ACTIVITY_MIN_ATR_PCT and
              volume_ratio >= config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO and
              spread_pct <= config.SYMBOL_ACTIVITY_MAX_SPREAD_PCT)
    return active, "active" if active else "passive"


def historical_quality_score(analyzer, window, spread_pct):
    """Rank an already-ACTIVE symbol without using future candles."""
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    quote_volume = sum(close * volume for close, volume in zip(closes[-288:], volumes[-288:]))
    atr = analyzer.calculate_atr(window, 14) or 0.0
    atr_pct = atr / closes[-1] if closes[-1] else 0.0
    avg_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0.0
    volume_ratio = volumes[-1] / avg_volume if avg_volume else 0.0
    # Score favours liquid, tradable volatility and volume while penalizing spread.
    return math.log10(max(quote_volume, 1)) + min(atr_pct * 100, 3) + min(volume_ratio, 3) - spread_pct * 2


async def current_spread(symbol):
    try:
        book = await orderbook(symbol, 5)
        bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
        mid = (bid + ask) / 2
        return ((ask - bid) / mid * 100) if mid else None
    except Exception as exc:
        print(f"[ACTIVITY-WARN] {symbol} orderbook alınamadı: {exc}", flush=True)
        return None


async def load_market(symbols, days, data_source, start_ts, end_ts, interval="5m"):
    if data_source == "historical-db":
        interval_ms = {"1m": 60 * 1000, "3m": 3 * 60 * 1000, "5m": 5 * 60 * 1000, "15m": 15 * 60 * 1000}[interval]
        warmup_ms = max(int(days * 86400 * 1000), 250 * interval_ms)
        start_ms = int(start_ts * 1000) - warmup_ms
        end_ms = int(end_ts * 1000)

        async def load_cached(symbol):
            try:
                rows = await database.get_market_candles(symbol, interval, start_ms, end_ms)
                data = rows_to_series(rows)
                print(f"[DATA] {symbol} source=historical_candles interval={interval} candles={len(data['times'])}", flush=True)
                return symbol, data, 0.0, None, None
            except Exception as exc:
                return symbol, None, 0.0, None, str(exc)

        return await asyncio.gather(*(load_cached(symbol) for symbol in symbols))

    ticker_rows = await ticker_24h()
    quote_volumes = {str(row.get("symbol", "")).upper(): float(row.get("quoteVolume", 0) or 0) for row in ticker_rows}
    semaphore = asyncio.Semaphore(6)

    async def fetch(symbol):
        async with semaphore:
            try:
                rows, spread = await asyncio.gather(historical_klines(symbol, interval, days), current_spread(symbol))
                data = rows_to_series(rows)
                print(f"[DATA] {symbol} source=BinanceTR-public interval={interval} candles={len(data['times'])}", flush=True)
                return symbol, data, quote_volumes.get(symbol, 0.0), spread, None
            except Exception as exc:
                return symbol, None, 0.0, None, str(exc)

    return await asyncio.gather(*(fetch(symbol) for symbol in symbols))


def feature_snapshot(analyzer, window):
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    bb = analyzer.calculate_bollinger_bands(closes, config.BB_MFI_BB_PERIOD, config.BB_MFI_BB_STD_DEV)
    return {
        "close": closes[-1],
        "bb_lower": bb["lower"] if bb else None,
        "mfi": _mfi(highs, lows, closes, volumes, config.BB_MFI_MFI_PERIOD),
        "rsi": analyzer.calculate_rsi(closes, config.BB_MFI_RSI_PERIOD),
        "atr": analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD),
    }


def pine_profile(version):
    return {
        "v1": {"bb_period": 21, "bb_std": 2.0, "rsi_period": 13,
               "buy_rsi_min": 30.0, "sell_rsi_min": 70.0, "stop_pct": None, "tp_pct": None},
        "v2": {"bb_period": 18, "bb_std": 2.0, "rsi_period": 13,
               "buy_rsi_min": 22.0, "sell_rsi_min": 82.0, "stop_pct": 0.06604, "tp_pct": 0.02328},
        "v3": {"bb_period": 21, "bb_std": 2.0, "rsi_period": 13, "mfi_period": 16,
               "buy_mfi_max": 59.0, "sell_rsi_min": 69.0, "sell_mfi_min": 69.0,
               "stop_pct": 0.08882, "tp_pct": 0.02317},
    }.get(version)


def strategy_decision(analyzer, window, symbol, version):
    if version == "current":
        return analyzer.strategy_bb_mfi_mean_reversion(window, symbol)
    profile = pine_profile(version)
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    minimum = max(profile["bb_period"], profile.get("mfi_period", 0) + 1, profile["rsi_period"] + 1)
    if min(len(closes), len(highs), len(lows), len(volumes)) < minimum:
        return None
    bb = analyzer.calculate_bollinger_bands(closes, profile["bb_period"], profile["bb_std"])
    rsi = analyzer.calculate_rsi(closes, profile["rsi_period"])
    if not bb or rsi is None:
        return None
    if version in {"v1", "v2"}:
        if closes[-1] < bb["lower"] and rsi > profile["buy_rsi_min"]:
            return "buy"
        if closes[-1] > bb["upper"] and rsi > profile["sell_rsi_min"]:
            return "sell"
        return None
    mfi = _mfi(highs, lows, closes, volumes, profile["mfi_period"])
    if mfi is None:
        return None
    if closes[-1] < bb["lower"] and mfi < profile["buy_mfi_max"]:
        return "buy"
    if closes[-1] > bb["upper"] and rsi > profile["sell_rsi_min"] and mfi > profile["sell_mfi_min"]:
        return "sell"
    return None


def replay_features(analyzer, window, version):
    profile = pine_profile(version)
    if not profile:
        return feature_snapshot(analyzer, window)
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    bb = analyzer.calculate_bollinger_bands(closes, profile["bb_period"], profile["bb_std"])
    return {"close": closes[-1], "bb_lower": bb["lower"] if bb else None,
            "bb_upper": bb["upper"] if bb else None,
            "rsi": analyzer.calculate_rsi(closes, profile["rsi_period"]),
            "mfi": _mfi(highs, lows, closes, volumes, profile.get("mfi_period", 16)) if version == "v3" else None,
            "atr": analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD)}


async def run(args):
    if args.interval not in {"1m", "3m", "5m", "15m"}:
        raise SystemExit("Bu replay yalnızca 1m, 3m, 5m veya 15m ile çalışır")
    now = int(time.time())
    local_tz = ZoneInfo(args.timezone)
    end_ts = min(now, int(datetime.fromisoformat(args.end_date).replace(tzinfo=local_tz).timestamp())) if args.end_date else now - int(args.end_hours_ago * 3600)
    start_ts = int(datetime.fromisoformat(args.start_date).replace(tzinfo=local_tz).timestamp()) if args.start_date else now - int(args.start_hours_ago * 3600)
    if start_ts >= end_ts:
        raise SystemExit("start-hours-ago, end-hours-ago değerinden büyük olmalıdır")
    if args.profit_lock_trigger_pct < 0 or args.profit_lock_pct < 0 or args.profit_lock_pct > args.profit_lock_trigger_pct:
        raise SystemExit("profit-lock yüzdeleri 0 <= lock <= trigger olmalıdır")

    discovered_symbols = args.symbols or await trading_symbols("TRY")
    requested_symbols = [symbol.replace("_", "").upper() for symbol in discovered_symbols]
    profile = pine_profile(args.pine_version)
    base_stop_pct = profile["stop_pct"] if profile else args.stop_pct
    stop_pct = args.risk_stop_pct if args.risk_stop_pct is not None else base_stop_pct
    tp_pct = profile["tp_pct"] if profile else args.tp_pct
    stop_pct = stop_pct if stop_pct and stop_pct > 0 else None
    tp_pct = tp_pct if tp_pct and tp_pct > 0 else None
    print(f"[START] strategy={config.ACTIVE_STRATEGY} pine_version={args.pine_version} initial={config.INITIAL_BALANCE_TRY:.2f} TRY window={iso(start_ts)}..{iso(end_ts)}", flush=True)
    print(f"[CONFIG] universe={len(requested_symbols)} source={'cli' if args.symbols else 'BinanceTR-exchangeInfo'} order_pct={args.order_pct:.4f} pyramiding={args.pyramiding} max_positions={args.max_positions} commission={config.COMMISSION_PCT:.6f} spread={args.spread_pct:.6f} slippage={args.slippage_pct:.6f}", flush=True)

    if args.data_source == "historical-db":
        await database.init_db()
    loaded = await load_market(requested_symbols, args.fetch_days, args.data_source, start_ts, end_ts, args.interval)
    analyzer = ScalpAnalyzer(None)
    series, activity, quality, skipped = {}, {}, {}, {}
    for symbol, data, quote_volume, live_spread, error in loaded:
        if error or not data or not data["times"]:
            skipped[symbol] = error or "empty_candles"
            print(f"[DATA-SKIP] {symbol} reason={skipped[symbol]}", flush=True)
            continue
        status = activity_metrics(analyzer, data, quote_volume, live_spread)
        activity[symbol] = status
        quality[symbol] = data_quality(data)
        print(f"[ACTIVITY] {symbol} status={status['status']} metrics={json.dumps(status, ensure_ascii=False)}", flush=True)
        if args.use_all_requested or args.historical_activity or args.data_source == "historical-db" or status["status"] == "ACTIVE":
            series[symbol] = data
    if not series:
        raise SystemExit("Aktif ve kullanılabilir sembol bulunamadı")

    indices = {symbol: {ts: index for index, ts in enumerate(data["times"])} for symbol, data in series.items()}
    if args.initial_active_only:
        # Start from the symbols that were objectively ACTIVE at the beginning
        # of this replay window, not from today's visible activity list.
        initially_active = {}
        for symbol, data in series.items():
            index = next((i for i, candle_ts in enumerate(data["times"]) if candle_ts >= start_ts), None)
            if index is None:
                continue
            active, _ = historical_activity(analyzer, window_at(data, index), args.spread_pct)
            if active:
                initially_active[symbol] = (data, historical_quality_score(analyzer, window_at(data, index), args.spread_pct))
        if args.initial_active_limit:
            initially_active = dict(sorted(initially_active.items(), key=lambda item: item[1][1], reverse=True)[:args.initial_active_limit])
        initially_active = {symbol: item[0] for symbol, item in initially_active.items()}
        series = initially_active
        indices = {symbol: {ts: index for index, ts in enumerate(data["times"])} for symbol, data in series.items()}
        if not series:
            raise SystemExit("Pencere başlangıcında ACTIVE sembol bulunamadı")
    timeline = sorted({ts for data in series.values() for ts in data["times"] if start_ts <= ts <= end_ts})
    cash = initial = float(config.INITIAL_BALANCE_TRY)
    positions, trades = {}, []
    fees_paid = 0.0
    peak_equity, max_drawdown = cash, 0.0
    signal_counts = Counter()
    activity_status = {symbol: False for symbol in series}
    last_activity_hour = None

    for ts in timeline:
        exits = entries = blocked = signals = 0
        activity_hour = ts // 3600
        if args.historical_activity and activity_hour != last_activity_hour:
            last_activity_hour = activity_hour
            for symbol, data in series.items():
                index = indices[symbol].get(ts)
                if index is None: continue
                active, state = historical_activity(analyzer, window_at(data, index), args.spread_pct)
                activity_status[symbol] = active
                position = positions.get(symbol)
                if not active and position:
                    price = data["opens"][index]
                    exit_fill = price * (1 - args.spread_pct / 2 - args.slippage_pct)
                    proceeds = position["quantity"] * exit_fill
                    exit_fee = proceeds * config.COMMISSION_PCT
                    pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                    if pnl >= 0:
                        cash += proceeds - exit_fee; fees_paid += exit_fee
                        trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                                       "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                                       "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6),
                                       "reason": "historical_activity_passive_net_exit"})
                        del positions[symbol]; exits += 1
                elif (args.passive_loss_exit_hours > 0 and not active and
                      ts - position["entry_time"] >= args.passive_loss_exit_hours * 3600):
                    close = data["closes"][index]
                    ema9 = analyzer.calculate_ema(window_at(data, index)["closes"], 9)
                    ema21 = analyzer.calculate_ema(window_at(data, index)["closes"], 21)
                    atr = analyzer.calculate_atr(window_at(data, index), 14) or 0.0
                    if ema9 is not None and ema21 is not None and ema9 < ema21 and close < position["entry"] - atr:
                        exit_fill = price * (1 - args.spread_pct / 2 - args.slippage_pct)
                        proceeds = position["quantity"] * exit_fill; exit_fee = proceeds * config.COMMISSION_PCT
                        cash += proceeds - exit_fee; fees_paid += exit_fee
                        pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                        trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                                       "entry": position["entry"], "exit": exit_fill, "layers": position["layers"], "pnl": round(pnl, 6),
                                       "commission": round(position["entry_fees"] + exit_fee, 6), "reason": "historical_passive_loss_ema_atr_exit"})
                        del positions[symbol]; exits += 1
        # Confirmed sell signals from the previous candle execute at this open.
        for symbol, position in list(positions.items()):
            index = indices[symbol].get(ts)
            if index is None or index < 1:
                continue
            data = series[symbol]
            previous_window = window_at(data, index - 1)
            if strategy_decision(analyzer, previous_window, symbol, args.pine_version) != "sell":
                continue
            exit_quote, reason = data["opens"][index], "bb_mfi_v3_signal_exit"
            exit_fill = exit_quote * (1 - args.spread_pct / 2 - args.slippage_pct)
            proceeds = position["quantity"] * exit_fill
            exit_fee = proceeds * config.COMMISSION_PCT
            cash += proceeds - exit_fee
            fees_paid += exit_fee
            pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
            trade = {"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                     "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                     "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6), "reason": reason}
            trades.append(trade)
            del positions[symbol]
            exits += 1
            print(f"[EXIT] {iso(ts)} {symbol} reason={reason} pnl={pnl:+.2f} cash={cash:.2f}", flush=True)

        # Confirmed buy signals from the previous candle execute at this open.
        for symbol, data in series.items():
            index = indices[symbol].get(ts)
            if index is None or index < 21:
                continue
            window = window_at(data, index - 1)
            feature = replay_features(analyzer, window, args.pine_version)
            decision = strategy_decision(analyzer, window, symbol, args.pine_version)
            signal_counts[decision or "none"] += 1
            if decision != "buy":
                continue
            if args.historical_activity and not activity_status.get(symbol, False):
                blocked += 1
                continue
            signals += 1
            print(f"[SIGNAL] {iso(data['times'][index - 1])} {symbol} BUY fill_at={iso(ts)} features={json.dumps(feature, ensure_ascii=False, default=str)}", flush=True)
            position = positions.get(symbol)
            if position and position["layers"] >= args.pyramiding:
                blocked += 1
                print(f"[BLOCKED] {symbol} reason=max_layers", flush=True)
                continue
            if position is None and len(positions) >= args.max_positions:
                blocked += 1
                print(f"[BLOCKED] {symbol} reason=max_open_positions", flush=True)
                continue
            marked_positions = sum(pos["quantity"] * series[held]["closes"][indices[held].get(ts, 0)] for held, pos in positions.items())
            equity = cash + marked_positions
            order_value = min(equity * args.order_pct, cash / (1 + config.COMMISSION_PCT))
            if order_value < config.MIN_PARTIAL_ORDER_TRY:
                blocked += 1
                print(f"[BLOCKED] {symbol} reason=insufficient_cash order={order_value:.2f} cash={cash:.2f}", flush=True)
                continue
            entry_quote = data["opens"][index]
            entry_fill = entry_quote * (1 + args.spread_pct / 2 + args.slippage_pct)
            entry_fee = order_value * config.COMMISSION_PCT
            quantity = order_value / entry_fill
            cash -= order_value + entry_fee
            fees_paid += entry_fee
            if position:
                total_quantity = position["quantity"] + quantity
                position["entry"] = (position["entry"] * position["quantity"] + entry_fill * quantity) / total_quantity
                position["quantity"] = total_quantity
                position["invested"] += order_value
                position["entry_fees"] += entry_fee
                position["layers"] += 1
                position.pop("profit_lock_stop", None)
            else:
                position = {"entry": entry_fill, "quantity": quantity, "invested": order_value,
                            "entry_fees": entry_fee, "layers": 1, "entry_time": ts}
                positions[symbol] = position
            position["stop"] = position["entry"] * (1 - stop_pct) if stop_pct is not None else None
            position["target"] = position["entry"] * (1 + tp_pct) if tp_pct is not None else None
            entries += 1
            print(f"[ENTRY] {iso(ts)} {symbol} layer={position['layers']} value={order_value:.2f} entry={entry_fill:.8f} cash={cash:.2f}", flush=True)

        # Intrabar stop/target events occur after the candle open. Conservative
        # ordering assumes stop first when both levels are touched in one bar.
        for symbol, position in list(positions.items()):
            index = indices[symbol].get(ts)
            if index is None:
                continue
            data = series[symbol]
            high, low = data["highs"][index], data["lows"][index]
            fixed_stop = position["stop"]
            profit_lock_stop = position.get("profit_lock_stop")
            active_stop = max(value for value in (fixed_stop, profit_lock_stop) if value is not None) if any(value is not None for value in (fixed_stop, profit_lock_stop)) else None
            if active_stop is not None and low <= active_stop:
                exit_quote = active_stop
                reason = "profit_lock_stop" if profit_lock_stop is not None and active_stop == profit_lock_stop else "fixed_stop_loss"
            elif position["target"] is not None and high >= position["target"]:
                exit_quote, reason = position["target"], "fixed_take_profit"
            else:
                if arm_profit_lock(position, high, args.profit_lock_trigger_pct, args.profit_lock_pct):
                    print(f"[PROFIT-LOCK-ARMED] {symbol} floor={position['profit_lock_stop']:.8f}", flush=True)
                continue
            exit_fill = exit_quote * (1 - args.spread_pct / 2 - args.slippage_pct)
            proceeds = position["quantity"] * exit_fill
            exit_fee = proceeds * config.COMMISSION_PCT
            cash += proceeds - exit_fee
            fees_paid += exit_fee
            pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
            trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                           "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                           "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6), "reason": reason})
            del positions[symbol]
            exits += 1
            print(f"[EXIT] {iso(ts)} {symbol} reason={reason} pnl={pnl:+.2f} cash={cash:.2f}", flush=True)

        marked = cash
        for symbol, position in positions.items():
            index = indices[symbol].get(ts)
            mark = series[symbol]["closes"][index] if index is not None else position["entry"]
            marked += position["quantity"] * mark
        peak_equity = max(peak_equity, marked)
        max_drawdown = max(max_drawdown, (peak_equity - marked) / peak_equity if peak_equity else 0.0)
        print(f"[SCAN] {iso(ts)} symbols={len(series)} signals={signals} entries={entries} exits={exits} blocked={blocked} open={len(positions)} cash={cash:.2f} equity={marked:.2f}", flush=True)

    excluded_open = []
    marked_open = []
    if args.open_position_policy == "exclude":
        # Compatibility mode for prior research reports: unfinished trades are
        # treated as if never opened.
        for symbol, position in positions.items():
            restored = position["invested"] + position["entry_fees"]
            cash += restored
            fees_paid -= position["entry_fees"]
            excluded_open.append({"symbol": symbol, "entry_time": position["entry_time"], "layers": position["layers"], "restored_try": round(restored, 6)})
            print(f"[OPEN-EXCLUDED] {symbol} restored={restored:.2f} reason=treated_as_never_opened", flush=True)
    else:
        # Portfolio-parity mode: retain open paper positions at their last
        # available close instead of erasing their capital and PnL.
        for symbol, position in positions.items():
            data = series[symbol]
            closing_index = max((index for index, ts in enumerate(data["times"]) if ts <= end_ts), default=None)
            mark_price = data["closes"][closing_index] if closing_index is not None else position["entry"]
            liquidation_fill = mark_price * (1 - args.spread_pct / 2 - args.slippage_pct)
            marked_value = position["quantity"] * liquidation_fill
            exit_fee = marked_value * config.COMMISSION_PCT
            unrealized_pnl = marked_value - exit_fee - position["invested"] - position["entry_fees"]
            cash += marked_value - exit_fee
            fees_paid += exit_fee
            marked_open.append({"symbol": symbol, "entry_time": position["entry_time"], "layers": position["layers"],
                                "mark_price": round(mark_price, 8), "liquidation_fill": round(liquidation_fill, 8),
                                "marked_value_try": round(marked_value - exit_fee, 6),
                                "unrealized_pnl_try": round(unrealized_pnl, 6)})
            print(f"[OPEN-MARKED] {symbol} value={marked_value:.2f} unrealized={unrealized_pnl:+.2f}", flush=True)

    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] <= 0]
    gross_profit = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))
    result = {
        "paper_only": True, "source": "Binance TR public API", "retrieved_at": iso(now),
        "window": {"start": iso(start_ts), "end": iso(end_ts), "hours": round((end_ts - start_ts) / 3600, 2)},
        "strategy": config.ACTIVE_STRATEGY, "pine_version": args.pine_version,
        "pine_profile": profile,
        "risk_stop_pct": stop_pct,
        "selection_mode": ("all_requested_scan_symbols" if args.use_all_requested else
                           "historical_cached_requested_symbols" if args.data_source == "historical-db" else
                           "current_activity_active_only"),
        "initial_active_only": args.initial_active_only,
        "initial_active_limit": args.initial_active_limit,
        "passive_loss_exit_hours": args.passive_loss_exit_hours,
        "historical_activity_gate": args.historical_activity,
        "initial_balance_try": initial, "final_balance_try": round(cash, 6),
        "net_pnl_try": round(cash - initial, 6), "net_pnl_pct": round((cash / initial - 1) * 100, 6),
        "closed_trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 4) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "fees_total_including_open_liquidation_try": round(fees_paid, 6), "max_drawdown_pct": round(max_drawdown * 100, 6),
        "active_symbols": sorted(series), "activity": activity, "skipped_symbols": skipped,
        "data_quality": quality,
        "prepared_features": ["bb_lower", "bb_upper", "mfi", "rsi", "atr", "close"],
        "open_position_policy": args.open_position_policy,
        "open_positions_excluded": excluded_open, "open_positions_marked": marked_open,
        "signal_counts": dict(signal_counts),
        "exit_reasons": dict(Counter(trade["reason"] for trade in trades)), "trades": trades,
        "cost_model": {"commission_pct_each_side": config.COMMISSION_PCT,
                       "assumed_full_spread_pct": args.spread_pct, "slippage_pct_each_side": args.slippage_pct},
        "profit_lock": {"trigger_pct": args.profit_lock_trigger_pct, "lock_pct": args.profit_lock_pct,
                        "same_bar_fill": False},
        "limitations": ["Historical order-book depth and spread are unavailable; current spread selects the active universe and configured spread models fills."],
        "reconciliation": {"expected": round(initial + sum(trade["pnl"] for trade in trades) + sum(item["unrealized_pnl_try"] for item in marked_open), 6),
                           "actual": round(cash, 6),
                           "difference": round(cash - (initial + sum(trade["pnl"] for trade in trades) + sum(item["unrealized_pnl_try"] for item in marked_open)), 8)},
    }
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[COMPLETE] result={output.resolve()}", flush=True)
    print("RESULT_JSON=" + json.dumps({key: result[key] for key in ("initial_balance_try", "final_balance_try", "net_pnl_try", "net_pnl_pct", "closed_trades", "wins", "losses", "win_rate_pct", "profit_factor", "fees_total_including_open_liquidation_try", "max_drawdown_pct", "active_symbols", "open_positions_excluded", "open_positions_marked", "reconciliation")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--use-all-requested", action="store_true", help="Verilen tarama evrenini güncel ACTIVE filtresi uygulamadan replay et")
    parser.add_argument("--interval", choices=("1m", "3m", "5m", "15m"), default="5m")
    parser.add_argument("--data-source", choices=("public", "historical-db"), default="public")
    parser.add_argument("--pine-version", choices=("current", "v1", "v2", "v3"), default="current")
    parser.add_argument("--fetch-days", type=int, default=2, help="Feature warmup dahil public candle window")
    parser.add_argument("--start-hours-ago", type=float, default=24)
    parser.add_argument("--end-hours-ago", type=float, default=3)
    parser.add_argument("--start-date", help="ISO yerel tarih/saat; ör. 2026-07-20T00:00:00")
    parser.add_argument("--end-date", help="ISO yerel tarih/saat; gelecekteyse mevcut zamana kırpılır")
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--order-pct", type=float, default=config.ORDER_PCT)
    parser.add_argument("--pyramiding", type=int, default=config.PYRAMIDING_LAYERS)
    parser.add_argument("--max-positions", type=int, default=config.MAX_OPEN_POSITIONS)
    parser.add_argument("--stop-pct", type=float, default=config.BB_MFI_STOP_LOSS_PCT)
    parser.add_argument("--risk-stop-pct", type=float,
                        help="Araştırma için strateji sinyalini değiştirmeden eklenen koruyucu stop")
    parser.add_argument("--tp-pct", type=float, default=config.BB_MFI_TAKE_PROFIT_PCT)
    parser.add_argument("--spread-pct", type=float, default=config.BACKTEST_ASSUMED_SPREAD_PCT)
    parser.add_argument("--slippage-pct", type=float, default=config.ESTIMATED_SLIPPAGE_PCT)
    parser.add_argument("--profit-lock-trigger-pct", type=float, default=0.0,
                        help="Pozisyon bu brüt yükselişi gördükten sonraki mumlarda maliyet-kilit stopu etkinleşir")
    parser.add_argument("--profit-lock-pct", type=float, default=0.0,
                        help="Kilitli stopun giriş fiyatının üzerindeki seviyesi; 0 gerçek brüt break-even'dır")
    parser.add_argument("--open-position-policy", choices=("exclude", "mark-to-market"), default="exclude")
    parser.add_argument("--historical-activity", action="store_true", help="Aktiviteyi her saat geçmiş mumlardan yeniden hesapla; pasif kârlı pozisyonu kapat")
    parser.add_argument("--initial-active-only", action="store_true", help="Yalnız replay başlangıcında tarihsel olarak ACTIVE olan sembollerle başla")
    parser.add_argument("--initial-active-limit", type=int, default=0, help="Başlangıç ACTIVE evreninden kalite puanıyla en iyi N sembol")
    parser.add_argument("--passive-loss-exit-hours", type=float, default=0.0, help="Pasif zarar pozisyonu için EMA/ATR kontrollü çıkış süresi")
    parser.add_argument("--output", default="portfolio-replay-latest.json")
    asyncio.run(run(parser.parse_args()))
