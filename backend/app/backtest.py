"""Deterministic, public-data paper-trading backtest motoru."""

import asyncio
import threading
import time
from collections import Counter
from typing import Any

from app import database
from app.analyzer import ScalpAnalyzer
from app.technical_analysis import _adx, _macd, _bollinger, _stochastic, _mfi, _cci, _williams_r, _methodology_analysis
from app.binance_tr_public import historical_klines
from app.config import config

STRATEGIES = {
    "EMA_VWAP_PULLBACK": ("EMA_VWAP_ENABLED", "EMA_VWAP_TIMEFRAME", "strategy_ema_vwap"),
    "BB_SQUEEZE_ORDERFLOW": ("BB_SQUEEZE_ENABLED", "BB_SQUEEZE_TIMEFRAME", "strategy_bb_squeeze_orderflow"),
    "ORDERFLOW": ("ORDERFLOW_ENABLED", "ORDERFLOW_TIMEFRAME", "strategy_orderflow"),
    "MOMENTUM": ("MOMENTUM_ENABLED", "MOMENTUM_TIMEFRAME", "strategy_momentum"),
    "MOMENTUM_COST_AWARE": ("MOMENTUM_COST_AWARE_ENABLED", "MOMENTUM_TIMEFRAME", "strategy_momentum_cost_aware"),
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
    # Spot backtest, canlıdaki hard-stop/time-decay/timeout modelini kullanır.
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

CUSTOM_INDICATORS = {"rsi", "ema_9", "ema_21", "ema_50", "adx", "volume_ratio", "price_vs_vwap", "return_5", "return_21", "chop", "macd_histogram", "stochastic_k", "bollinger_position", "atr_pct", "mfi", "cci", "williams_r", "price_vs_ema_21", "cmo", "crsi", "confluence_score", "regime_confidence", "turtle_breakout", "wyckoff_score", "elliott_score", "fib_distance_support", "fib_distance_resistance"}
CUSTOM_OPS = {"<", "<=", ">", ">=", "=="}

def _custom_value(analyzer, window, name):
    closes, highs, lows, volumes = window["closes"], window["highs"], window["lows"], window["volumes"]
    if name == "rsi": return analyzer.calculate_rsi(closes, 14)
    if name == "ema_9": return analyzer.calculate_ema(closes, 9)
    if name == "ema_21": return analyzer.calculate_ema(closes, 21)
    if name == "ema_50": return analyzer.calculate_ema(closes, 50)
    if name == "adx":
        result = _adx(highs, lows, closes); return result.get("adx") if result else None
    if name == "volume_ratio": return analyzer._volume_ratio(window)
    if name == "price_vs_vwap":
        if len(closes) < 20 or not sum(volumes[-20:]): return None
        typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes)-20, len(closes))]
        vwap = sum(p*v for p,v in zip(typical, volumes[-20:])) / sum(volumes[-20:])
        return closes[-1] / vwap - 1
    if name == "return_5": return closes[-1] / closes[-6] - 1 if len(closes) >= 6 else None
    if name == "return_21": return closes[-1] / closes[-22] - 1 if len(closes) >= 22 else None
    if name == "chop": return analyzer.calculate_chop(window, 14)
    if name == "macd_histogram":
        value = _macd(closes); return value.get("histogram") if value else None
    if name == "stochastic_k":
        value = _stochastic(highs, lows, closes); return value.get("k") if value else None
    if name == "bollinger_position":
        value = _bollinger(closes); return (closes[-1] - value["lower"]) / (value["upper"] - value["lower"]) if value and value["upper"] != value["lower"] else None
    if name == "atr_pct":
        atr = analyzer.calculate_atr(window, 14); return atr / closes[-1] if atr and closes[-1] else None
    if name == "mfi": return _mfi(highs, lows, closes, volumes)
    if name == "cci": return _cci(highs, lows, closes)
    if name == "williams_r": return _williams_r(highs, lows, closes)
    if name == "price_vs_ema_21":
        ema = analyzer.calculate_ema(closes, 21); return closes[-1] / ema - 1 if ema else None
    if name == "cmo": return analyzer.calculate_cmo(closes, 9)
    if name == "crsi": return analyzer.calculate_crsi(closes)
    if name in {"confluence_score", "regime_confidence", "turtle_breakout", "wyckoff_score", "elliott_score", "fib_distance_support", "fib_distance_resistance"}:
        methods = _methodology_analysis(window["opens"], highs, lows, closes, volumes, _adx(highs, lows, closes), "bullish" if analyzer.calculate_ema(closes, 9) and analyzer.calculate_ema(closes, 21) and analyzer.calculate_ema(closes, 9) > analyzer.calculate_ema(closes, 21) else "mixed")
        if name == "confluence_score": return methods["confluence"]["score"]
        if name == "regime_confidence": return methods["regime"]["confidence"]
        if name == "turtle_breakout": return 1 if methods["turtle"]["breakout"] == "up_20" else -1 if methods["turtle"]["breakout"] == "down_20" else 0
        if name == "wyckoff_score": return methods["confluence"]["components"]["wyckoff"]
        if name == "elliott_score": return methods["elliott"]["confidence"]
        fib = methods["fibonacci"]
        return (closes[-1] / fib["0.786"] - 1) if name == "fib_distance_support" and fib["0.786"] else (closes[-1] / fib["0.236"] - 1) if fib["0.236"] else None
    return None

def _custom_conditions(analyzer, window, conditions):
    for condition in conditions or []:
        name, op, expected = condition.get("indicator"), condition.get("op"), condition.get("value")
        if name not in CUSTOM_INDICATORS or op not in CUSTOM_OPS:
            raise ValueError(f"Geçersiz custom koşul: {name} {op}")
        try: expected = float(expected)
        except (TypeError, ValueError): raise ValueError(f"Koşul değeri sayısal olmalıdır: {name}")
        actual = _custom_value(analyzer, window, name)
        if actual is None: return False
        ok = {"<": actual < expected, "<=": actual <= expected, ">": actual > expected, ">=": actual >= expected, "==": abs(actual - expected) < 1e-9}[op]
        if not ok: return False
    return bool(conditions)

def _run_custom(symbol, interval, days_back, definition, order_size=500.0, stop_pct=None, tp_pct=None):
    if not isinstance(definition, dict): raise ValueError("strategy_definition nesne olmalıdır")
    entry = definition.get("entry") or []; exit_conditions = definition.get("exit") or []
    if len(entry) > 8 or len(exit_conditions) > 8: raise ValueError("En fazla 8 giriş ve 8 çıkış koşulu kullanılabilir")
    rows = _fetch_klines(symbol, interval, days_back); analyzer = ScalpAnalyzer(None); balance = config.INITIAL_BALANCE_TRY; position = None; trades = []; entry_armed = True; cooldown_until = -1
    stop_pct = float(stop_pct if stop_pct is not None else config.HARD_STOP_LOSS_PCT); tp_pct = float(tp_pct if tp_pct is not None else config.TIME_DECAY_TP_1_PCT)
    for i, close in enumerate(rows["closes"]):
        window = {k:v[:i+1] for k,v in rows.items()}; now = rows["times"][i]
        if position:
            exit_price = None; reason = None
            atr_stop = position.get("atr_stop")
            hard_stop = position["entry"] * (1-stop_pct)
            stop_price = max(hard_stop, atr_stop) if atr_stop else hard_stop
            if rows["lows"][i] <= stop_price: exit_price=stop_price; reason="atr_stop_loss" if atr_stop and stop_price == atr_stop else "hard_stop_loss"
            elif rows["highs"][i] >= position["entry"] * (1+tp_pct): exit_price=position["entry"]*(1+tp_pct); reason="take_profit"
            elif _custom_conditions(analyzer, window, exit_conditions): exit_price=close; reason="custom_exit"
            elif now-position["entry_time"] >= 20 * 60 and close < position["entry"] + position.get("min_net_exit", 0.0): exit_price=close; reason="early_failure_no_progress"
            elif now-position["entry_time"] >= config.MAX_POSITION_HOLD_SEC: exit_price=close; reason="max_hold_4h"
            if exit_price is not None:
                balance, pnl, _, trade = _close_trade(balance, position["entry"], exit_price, position["quantity"], order_size, reason); trade.update({"entry_time":position["entry_time"],"exit_time":now}); trades.append(trade); position=None; cooldown_until = i + 1; entry_armed = False
        entry_signal = _custom_conditions(analyzer, window, entry)
        if not entry_signal: entry_armed = True
        if position is None and i >= cooldown_until and entry_armed and balance >= order_size and entry_signal:
            fee=order_size*config.COMMISSION_PCT; balance-=order_size+fee
            atr_entry = analyzer.calculate_atr(window, 14) or 0.0
            position={"entry":close,"quantity":order_size/close,"entry_time":now,"atr_stop":close - atr_entry * 2.5 if atr_entry else None,"min_net_exit":close * config.min_net_exit_pct(order_size)}
            entry_armed = False
    if position:
        balance, pnl, _, trade = _close_trade(balance, position["entry"], rows["closes"][-1], position["quantity"], order_size, "open_at_end_mark_to_market"); trade.update({"entry_time":position["entry_time"],"exit_time":rows["times"][-1]}); trades.append(trade)
    wins=sum(t["pnl"]>0 for t in trades); net=balance-config.INITIAL_BALANCE_TRY; losses=[t["pnl"] for t in trades if t["pnl"]<=0]; gains=[t["pnl"] for t in trades if t["pnl"]>0]
    return {"strategy":"CUSTOM","symbol":symbol,"interval":interval,"days_back":days_back,"definition":definition,"initial_balance":config.INITIAL_BALANCE_TRY,"final_balance":round(balance,2),"net_pnl":round(net,2),"total_trades":len(trades),"wins":wins,"losses":len(trades)-wins,"win_rate":round(wins/len(trades)*100,2) if trades else 0,"profit_factor":round(sum(gains)/abs(sum(losses)),3) if losses else None,"trades":trades,"exit_reason_counts":dict(Counter(t["reason"] for t in trades)),"paper_only":True,"custom_strategy":True}

async def run_custom_backtest(symbol, interval, days_back, definition, order_size=500.0, stop_pct=None, tp_pct=None):
    return await asyncio.to_thread(_run_custom, symbol, interval, days_back, definition, order_size, stop_pct, tp_pct)


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
            first_target_pct = float(tp_pct if tp_pct is not None else config.TIME_DECAY_TP_1_PCT)
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
                    elapsed = max(0, data["times"][i] - position["entry_time"])
                    if elapsed < config.TIME_DECAY_TP_STAGE_2_SEC:
                        target_pct = first_target_pct
                        target_reason = "time_decay_target_1_0pct"
                    elif elapsed < config.TIME_DECAY_TP_STAGE_3_SEC:
                        target_pct = config.TIME_DECAY_TP_2_PCT
                        target_reason = "time_decay_target_0_75pct"
                    elif elapsed < config.TIME_DECAY_BREAKEVEN_SEC:
                        target_pct = config.TIME_DECAY_TP_3_PCT
                        target_reason = "time_decay_target_0_5pct"
                    else:
                        target_pct = config.min_net_exit_pct(order_size * position.get("layers", 1))
                        target_reason = "breakeven_exit"
                    target_price = position["entry"] * (1 + target_pct)
                    effective_stop_pct = float(stop_pct) if stop_pct and stop_pct > 0 else config.HARD_STOP_LOSS_PCT
                    stop_price = position["entry"] * (1 - effective_stop_pct) if effective_stop_pct > 0 else None
                    # Pozisyon yalnızca kendi stratejisinin sell sinyaliyle kapanır.
                    exit_price = stop_price if stop_price is not None and low <= stop_price else (target_price if high >= target_price else None)
                    reason = "hard_stop_loss" if exit_price == stop_price and stop_price is not None else target_reason
                    if data["times"][i] - position["entry_time"] >= config.MAX_POSITION_HOLD_SEC:
                        exit_price = close
                        reason = "max_hold_4h"
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
                    "order_size": order_size, "stop_loss_pct": float(stop_pct), "take_profit_pct": first_target_pct,
                    "flow_model": "candle_orderflow_proxy_for_backtest",
                    "trailing_stop_pct": 0.0, "exit_model": "time_decay_profit_or_hard_stop_or_4h_timeout",
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
