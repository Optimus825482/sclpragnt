"""Deterministic, public-data paper-trading backtest motoru."""

import asyncio
import threading
import time
from collections import Counter
from typing import Any

from app import database
from app.analyzer import ScalpAnalyzer
from app.binance_tr_public import historical_klines
from app.config import config

STRATEGIES = {
    "EMA_VWAP_PULLBACK": ("EMA_VWAP_ENABLED", "EMA_VWAP_TIMEFRAME", "strategy_ema_vwap"),
    "BB_SQUEEZE_ORDERFLOW": ("BB_SQUEEZE_ENABLED", "BB_SQUEEZE_TIMEFRAME", "strategy_bb_squeeze_orderflow"),
    "ORDERFLOW": ("ORDERFLOW_ENABLED", "ORDERFLOW_TIMEFRAME", "strategy_orderflow"),
    "MOMENTUM": ("MOMENTUM_ENABLED", "MOMENTUM_TIMEFRAME", "strategy_momentum"),
    "VWAP_MEAN_REVERSION": ("MEAN_REVERSION_ENABLED", "MEAN_REVERSION_TIMEFRAME", "strategy_mean_reversion"),
    "KELTNER_BREAKOUT": ("KELTNER_ENABLED", "KELTNER_TIMEFRAME", "strategy_keltner_breakout"),
    "CHOP_TREND_FILTER": ("CHOP_ENABLED", "CHOP_TIMEFRAME", "strategy_chop_trend"),
    "DONCHIAN_BREAKOUT": ("DONCHIAN_ENABLED", "DONCHIAN_TIMEFRAME", "strategy_donchian_breakout"),
}

PARAM_FIELDS = {
    "ut_key_value": "UT_KEY_VALUE", "ut_atr_period": "UT_ATR_PERIOD",
    "ut_heikin_ashi": "UT_HEIKIN_ASHI", "squeeze_lookback": "SQUEEZE_LOOKBACK",
    "bb_period": "BB_PERIOD", "bb_std_dev": "BB_STD_DEV", "ema_short": "EMA_SHORT",
    "ema_mid": "EMA_MID", "ema_trend": "EMA_TREND", "rsi_period": "RSI_PERIOD",
    "vwap_period": "VWAP_PERIOD", "macd_fast": "MACD_FAST", "macd_slow": "MACD_SLOW",
    "macd_signal": "MACD_SIGNAL",
}

# Analyzer stratejileri mevcut global config'i okuduğu için backtest config değişimini serileştir.
_CONFIG_LOCK = threading.RLock()


def _fetch_klines(symbol: str, interval: str, days_back: int) -> dict[str, list[float]]:
    rows = asyncio.run(historical_klines(symbol, interval, days_back))
    if not rows:
        raise ValueError(f"{symbol} için tarihsel veri bulunamadı")
    result = {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": [], "times": []}
    for row in rows:
        if len(row) < 6:
            continue
        values = [float(row[i]) for i in range(1, 6)]
        if not all(v == v and abs(v) != float("inf") for v in values):
            continue
        result["opens"].append(values[0]); result["highs"].append(values[1])
        result["lows"].append(values[2]); result["closes"].append(values[3])
        result["volumes"].append(values[4])
        # Binance kline kapanış zamanı milisaniyedir; kullanıcıya saniye olarak verilir.
        result["times"].append(int(row[6] / 1000) if len(row) > 6 else int(row[0] / 1000))
    if not result["closes"]:
        raise ValueError(f"{symbol} için kullanılabilir mum bulunamadı")
    return result


def _validate(symbol, interval, days_back, strategy, params, order_size, stop_pct, tp_pct, trail_pct):
    if not symbol or not symbol.isalnum():
        raise ValueError("Geçersiz sembol")
    if interval not in {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}:
        raise ValueError("Geçersiz timeframe")
    if strategy not in STRATEGIES:
        raise ValueError(f"Bilinmeyen strateji: {strategy}")
    if not 1 <= days_back <= 365:
        raise ValueError("days_back 1 ile 365 arasında olmalıdır")
    if not 0 < order_size <= config.INITIAL_BALANCE_TRY:
        raise ValueError("order_size başlangıç bakiyesi ile 0 arasında olmalıdır")
    # Spot modelinde SL/trailing ve karşıt-sinyal çıkışı yoktur; satış yalnızca sabit %2 kârla yapılır.
    unknown = set(params) - set(PARAM_FIELDS)
    if unknown:
        raise ValueError(f"Bilinmeyen parametre: {sorted(unknown)[0]}")


def _close_trade(balance, entry, exit_price, quantity, order_size, reason):
    gross = (exit_price - entry) * quantity
    entry_fee = entry * quantity * config.COMMISSION_PCT
    exit_fee = exit_price * quantity * config.COMMISSION_PCT
    pnl = gross - entry_fee - exit_fee
    return balance + order_size + gross - exit_fee, pnl, entry_fee + exit_fee, {
        "side": "LONG", "entry": entry, "exit": exit_price, "quantity": quantity,
        "pnl": round(pnl, 8), "commission": round(entry_fee + exit_fee, 8), "reason": reason,
    }


def _run_single(symbol, interval, days_back, strategy, params, order_size, stop_pct, tp_pct, trail_pct):
    _validate(symbol, interval, days_back, strategy, params, order_size, stop_pct, tp_pct, trail_pct)
    with _CONFIG_LOCK:
        saved = {attr: getattr(config, attr) for attr in PARAM_FIELDS.values() if attr in {PARAM_FIELDS[k] for k in params}}
        saved_flags = {flag: getattr(config, flag) for flag, _, _ in STRATEGIES.values()}
        saved_tfs = {tf: getattr(config, tf) for _, tf, _ in STRATEGIES.values()}
        try:
            for key, attr in PARAM_FIELDS.items():
                if key in params:
                    setattr(config, attr, params[key])
            for name, (flag, tf, _) in STRATEGIES.items():
                setattr(config, flag, name == strategy)
                setattr(config, tf, interval)

            data = _fetch_klines(symbol, interval, days_back)
            analyzer = ScalpAnalyzer(None)
            fn = getattr(analyzer, STRATEGIES[strategy][2])
            balance = config.INITIAL_BALANCE_TRY
            profit_target_pct = config.SPOT_PROFIT_TARGET_PCT
            equity_peak = balance
            max_drawdown = 0.0
            position = None
            wins = losses = 0
            trades = []
            open_at_end = False
            unrealized_pnl = 0.0

            for i, close in enumerate(data["closes"]):
                high, low = data["highs"][i], data["lows"][i]
                if position:
                    window = {key: values[:i + 1] for key, values in data.items()}
                    target_price = position["entry"] * (1 + profit_target_pct)
                    # Pozisyon yalnızca kendi stratejisinin sell sinyaliyle kapanır.
                    exit_price = target_price if high >= target_price else None
                    reason = "profit_target_configured"
                    if data["times"][i] - position["entry_time"] >= config.MAX_POSITION_HOLD_SEC:
                        exit_price = close
                        reason = "max_hold_12h"
                    elif exit_price is None and fn(window, symbol) == "sell":
                        exit_price = close
                        reason = "opposite_signal"
                    if exit_price is not None:
                        balance, pnl, _, trade = _close_trade(balance, position["entry"], exit_price, position["quantity"], order_size * position.get("layers", 1), reason)
                        trade.update({"entry_time": position["entry_time"], "exit_time": data["times"][i],
                                      "entry_bar": position["entry_bar"], "exit_bar": i,
                                      "bars_held": i - position["entry_bar"] + 1})
                        trades.append(trade); wins += pnl > 0; losses += pnl <= 0; position = None
                    elif position.get("layers", 1) < config.MAX_POSITION_LAYERS and balance >= order_size:
                        result = fn(window, symbol)
                        if result == "buy":
                            fee = order_size * config.COMMISSION_PCT
                            balance -= order_size + fee
                            quantity = order_size / close
                            total_quantity = position["quantity"] + quantity
                            position["entry"] = ((position["entry"] * position["quantity"]) + (close * quantity)) / total_quantity
                            position["quantity"] = total_quantity
                            position["layers"] = position.get("layers", 1) + 1
                else:
                    window = {key: values[:i + 1] for key, values in data.items()}
                    result = fn(window, symbol)
                    if balance >= order_size and result == "buy":
                        entry_fee = order_size * config.COMMISSION_PCT
                        balance -= order_size + entry_fee
                        position = {"entry": close, "quantity": order_size / close,
                                    "entry_time": data["times"][i], "entry_bar": i, "layers": 1}
                marked = balance + (position["quantity"] * close if position else 0)
                equity_peak = max(equity_peak, marked)
                max_drawdown = max(max_drawdown, (equity_peak - marked) / equity_peak if equity_peak else 0)

            if position:
                open_at_end = True
                final_price = data["closes"][-1]
                unrealized_pnl = (final_price - position["entry"]) * position["quantity"]
                balance, pnl, _, trade = _close_trade(balance, position["entry"], final_price, position["quantity"], order_size * position.get("layers", 1), "open_at_end_mark_to_market")
                trade.update({"entry_time": position["entry_time"], "exit_time": data["times"][-1],
                              "entry_bar": position["entry_bar"], "exit_bar": len(data["closes"]) - 1,
                              "bars_held": len(data["closes"]) - position["entry_bar"]})
                trades.append(trade)

            total = len(trades)
            net = balance - config.INITIAL_BALANCE_TRY
            winning_pnls = [t["pnl"] for t in trades if t["pnl"] > 0]
            losing_pnls = [t["pnl"] for t in trades if t["pnl"] <= 0]
            gross_profit = sum(winning_pnls)
            gross_loss = abs(sum(losing_pnls))
            return {"symbol": symbol, "interval": interval, "strategy": strategy, "params": params, "days_back": days_back,
                    "initial_balance": config.INITIAL_BALANCE_TRY, "final_balance": round(balance, 2),
                    "net_pnl": round(net, 2), "net_pnl_pct": round(net / config.INITIAL_BALANCE_TRY * 100, 2),
                    "total_trades": total, "wins": int(wins), "losses": int(losses),
                    "win_rate": round(wins / total * 100, 2) if total else 0.0,
                    "avg_win": round(sum(winning_pnls) / len(winning_pnls), 2) if winning_pnls else 0.0,
                    "avg_loss": round(sum(losing_pnls) / len(losing_pnls), 2) if losing_pnls else 0.0,
                    "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (999.0 if gross_profit else 0.0),
                    "exit_reason_counts": dict(Counter(t["reason"] for t in trades)),
                    "max_drawdown_pct": round(max_drawdown * 100, 2), "commission_pct": config.COMMISSION_PCT,
                    "order_size": order_size, "stop_loss_pct": 0.0, "take_profit_pct": profit_target_pct,
                    "flow_model": "candle_orderflow_proxy_for_backtest",
                    "trailing_stop_pct": 0.0, "exit_model": "strategy_specific_sell_or_configured_profit_or_12h",
                    "open_position_at_end": open_at_end, "unrealized_pnl": round(unrealized_pnl, 8),
                    "trades": trades, "timestamp": time.time()}
        finally:
            for attr, value in {**saved, **saved_flags, **saved_tfs}.items():
                setattr(config, attr, value)


async def run_backtest(symbol: str, interval: str, days_back: int, strategy: str, params: dict | None = None,
                       order_size: float = 500.0, stop_pct: float = 0.005, tp_pct: float = 0.015,
                       trail_pct: float = 0.003) -> tuple[int, dict[str, Any]]:
    params = params or {}
    result = await asyncio.to_thread(_run_single, symbol, interval, days_back, strategy, params,
                                     order_size, stop_pct, tp_pct, trail_pct)
    return await database.save_backtest(result), result
