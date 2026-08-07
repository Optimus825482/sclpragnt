"""Deterministic, public-data paper-trading backtest motoru."""

import asyncio
import math
import random
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
    "OVERSOLD_TREND_REENTRY": ("OVERSOLD_TREND_REENTRY_ENABLED", "OVERSOLD_TREND_REENTRY_TIMEFRAME", "strategy_oversold_trend_reentry"),
    "ADAPTIVE_VOLATILITY_TREND": ("ADAPTIVE_VOLATILITY_TREND_ENABLED", "ADAPTIVE_VOLATILITY_TREND_TIMEFRAME", "strategy_adaptive_volatility_trend"),
    "REGIME_GATE_LOW_TURNOVER": ("REGIME_GATE_LOW_TURNOVER_ENABLED", "REGIME_GATE_LOW_TURNOVER_TIMEFRAME", "strategy_regime_gate_low_turnover"),
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
_KLINE_CACHE: dict[tuple[str, str, int], dict[str, list[float]]] = {}


def _fetch_klines(symbol: str, interval: str, days_back: int) -> dict[str, list[float]]:
    cache_key = (symbol.upper(), interval, int(days_back))
    cached = _KLINE_CACHE.get(cache_key)
    if cached:
        return {key: list(values) for key, values in cached.items()}
    rows = asyncio.run(historical_klines(symbol, interval, days_back))
    if not rows:
        raise ValueError(f"{symbol} için tarihsel veri bulunamadı")
    result = {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": [], "times": []}
    now_ms = int(time.time() * 1000)
    seen_times = set()
    for row in rows:
        if len(row) < 6:
            continue
        close_ms = int(row[6]) if len(row) > 6 else int(row[0])
        if close_ms > now_ms or close_ms in seen_times:
            continue
        values = [float(row[i]) for i in range(1, 6)]
        if not all(v == v and abs(v) != float("inf") for v in values):
            continue
        result["opens"].append(values[0]); result["highs"].append(values[1])
        result["lows"].append(values[2]); result["closes"].append(values[3])
        result["volumes"].append(values[4])
        # Binance kline kapanış zamanı milisaniyedir; kullanıcıya saniye olarak verilir.
        seen_times.add(close_ms)
        result["times"].append(int(close_ms / 1000))
    if not result["closes"]:
        raise ValueError(f"{symbol} için kullanılabilir mum bulunamadı")
    _KLINE_CACHE[cache_key] = {key: list(values) for key, values in result.items()}
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


def _close_trade(balance, entry, exit_price, quantity, order_size, reason,
                 spread_pct=0.0, slippage_pct=None):
    """Close a long using executable prices, not ideal mid prices."""
    slip = float(config.ESTIMATED_SLIPPAGE_PCT if slippage_pct is None else slippage_pct)
    half_spread = max(0.0, float(spread_pct)) / 2
    entry_fill = entry * (1 + half_spread + slip)
    exit_fill = exit_price * max(0.0, 1 - half_spread - slip)
    gross = (exit_fill - entry_fill) * quantity
    entry_fee = entry_fill * quantity * config.COMMISSION_PCT
    exit_fee = exit_fill * quantity * config.COMMISSION_PCT
    pnl = gross - entry_fee - exit_fee
    return balance + order_size + gross - exit_fee, pnl, entry_fee + exit_fee, {
        "side": "LONG", "entry": entry_fill, "exit": exit_fill, "quoted_entry": entry,
        "quoted_exit": exit_price, "quantity": quantity,
        "pnl": round(pnl, 8), "commission": round(entry_fee + exit_fee, 8), "reason": reason,
        "spread_pct": round(float(spread_pct), 8), "slippage_pct": round(slip, 8),
    }


def _data_quality(data: dict[str, list[float]], interval: str) -> dict:
    interval_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
                        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
                        "8h": 28800, "12h": 43200, "1d": 86400}.get(interval, 300)
    times = data.get("times", [])
    gaps = [times[i] - times[i - 1] for i in range(1, len(times)) if times[i] - times[i - 1] > interval_seconds * 1.5]
    return {"candle_count": len(times), "duplicate_timestamps": len(times) != len(set(times)),
            "sorted": times == sorted(times), "missing_gap_count": len(gaps),
            "max_gap_seconds": max(gaps) if gaps else 0, "interval_seconds": interval_seconds,
            "data_ready": bool(times) and times == sorted(times) and not (len(times) != len(set(times)))}

CUSTOM_INDICATORS = {
    # Canonical candle/indicator identifiers. All values are numeric and work with {indicator, op, value}.
    "close", "open", "high", "low", "ema_9", "ema_21", "ema_50", "price_vs_ema_9", "price_vs_ema_21", "price_vs_ema_50",
    "rsi", "rsi_14", "macd_histogram", "macd_hist", "adx", "atr_pct", "atr_trailing_stop", "atr_trailing_stop_pct",
    "volume_ratio", "volume_ratio_20", "spread_pct", "orderflow_imbalance", "price_vs_vwap", "vwap", "vwap_distance_pct",
    "vwap_zone", "volume_profile_poc_distance", "return_5", "return_21", "chop", "stochastic_k", "bollinger_position",
    "mfi", "cci", "williams_r", "cmo", "crsi", "confluence_score", "regime_confidence", "mtf_alignment_score",
    "turtle_breakout", "turtle_breakout_confirmed", "wyckoff_score", "elliott_score", "fib_distance_support", "fib_distance_resistance",
    "rsi_bullish_divergence", "rsi_bearish_divergence", "macd_bullish_divergence", "macd_bearish_divergence",
    "data_ready", "stale", "liquidity_fresh",
}
CUSTOM_OPS = {"<", "<=", ">", ">=", "=="}
CUSTOM_OP_ALIASES = {
    "lt": "<", "lte": "<=", "less_than": "<", "less_than_or_equal": "<=",
    "gt": ">", "gte": ">=", "greater_than": ">", "greater_than_or_equal": ">=",
    "eq": "==", "equal": "==", "equals": "==",
}

CUSTOM_IDENTIFIER_SCHEMA = {
    "price": ["open", "high", "low", "close"],
    "trend": ["ema_9", "ema_21", "ema_50", "price_vs_ema_9", "price_vs_ema_21", "price_vs_ema_50", "mtf_alignment_score"],
    "momentum": ["rsi_14", "macd_hist", "adx", "stochastic_k", "mfi", "cci", "williams_r", "cmo", "crsi"],
    "volatility_exit": ["atr_pct", "atr_trailing_stop", "atr_trailing_stop_pct"],
    "volume_liquidity": ["volume_ratio_20", "spread_pct", "orderflow_imbalance", "vwap", "price_vs_vwap", "vwap_distance_pct", "vwap_zone", "volume_profile_poc_distance"],
    "structure": ["turtle_breakout", "turtle_breakout_confirmed", "confluence_score", "regime_confidence", "wyckoff_score", "elliott_score", "fib_distance_support", "fib_distance_resistance"],
    "divergence": ["rsi_bullish_divergence", "rsi_bearish_divergence", "macd_bullish_divergence", "macd_bearish_divergence"],
    "data_gate": ["data_ready", "stale", "liquidity_fresh"],
}

def _custom_value(analyzer, window, name):
    closes, highs, lows, volumes = window["closes"], window["highs"], window["lows"], window["volumes"]
    if name in {"open", "high", "low", "close"}:
        return {"open": window["opens"][-1], "high": highs[-1], "low": lows[-1], "close": closes[-1]}[name]
    if name in {"rsi", "rsi_14"}: return analyzer.calculate_rsi(closes, 14)
    if name == "ema_9": return analyzer.calculate_ema(closes, 9)
    if name == "ema_21": return analyzer.calculate_ema(closes, 21)
    if name == "ema_50": return analyzer.calculate_ema(closes, 50)
    if name == "price_vs_ema_9":
        ema = analyzer.calculate_ema(closes, 9); return closes[-1] / ema - 1 if ema else None
    if name == "price_vs_ema_50":
        ema = analyzer.calculate_ema(closes, 50); return closes[-1] / ema - 1 if ema else None
    if name == "adx":
        result = _adx(highs, lows, closes); return result.get("adx") if result else None
    if name in {"volume_ratio", "volume_ratio_20"}: return analyzer._volume_ratio(window)
    if name == "orderflow_imbalance": return analyzer.calculate_orderflow_proxy(window)
    if name == "spread_pct": return None  # historical candles do not contain bid/ask spread
    if name in {"price_vs_vwap", "vwap", "vwap_distance_pct", "vwap_zone"}:
        if len(closes) < 20 or not sum(volumes[-20:]): return None
        typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes)-20, len(closes))]
        vwap = sum(p*v for p,v in zip(typical, volumes[-20:])) / sum(volumes[-20:])
        distance = closes[-1] / vwap - 1
        if name == "vwap": return vwap
        if name == "vwap_zone": return 1 if distance > 0.002 else -1 if distance < -0.002 else 0
        return distance
    if name == "volume_profile_poc_distance":
        if len(closes) < 20: return None
        offset = max(range(len(volumes) - 20, len(volumes)), key=lambda i: volumes[i])
        return closes[-1] / closes[offset] - 1 if closes[offset] else None
    if name == "return_5": return closes[-1] / closes[-6] - 1 if len(closes) >= 6 else None
    if name == "return_21": return closes[-1] / closes[-22] - 1 if len(closes) >= 22 else None
    if name == "chop": return analyzer.calculate_chop(window, 14)
    if name in {"macd_histogram", "macd_hist"}:
        value = _macd(closes); return value.get("histogram") if value else None
    if name == "stochastic_k":
        value = _stochastic(highs, lows, closes); return value.get("k") if value else None
    if name == "bollinger_position":
        value = _bollinger(closes); return (closes[-1] - value["lower"]) / (value["upper"] - value["lower"]) if value and value["upper"] != value["lower"] else None
    if name in {"atr_pct", "atr_trailing_stop_pct"}:
        atr = analyzer.calculate_atr(window, 14); return atr / closes[-1] if atr and closes[-1] else None
    if name == "atr_trailing_stop":
        atr = analyzer.calculate_atr(window, 14)
        return max(closes) - atr * config.SYSTEM_ATR_TRAILING_MULTIPLIER if atr else None
    if name == "mfi": return _mfi(highs, lows, closes, volumes)
    if name == "cci": return _cci(highs, lows, closes)
    if name == "williams_r": return _williams_r(highs, lows, closes)
    if name == "price_vs_ema_21":
        ema = analyzer.calculate_ema(closes, 21); return closes[-1] / ema - 1 if ema else None
    if name == "cmo": return analyzer.calculate_cmo(closes, 9)
    if name == "crsi": return analyzer.calculate_crsi(closes)
    if name in {"confluence_score", "regime_confidence", "mtf_alignment_score", "turtle_breakout", "turtle_breakout_confirmed", "wyckoff_score", "elliott_score", "fib_distance_support", "fib_distance_resistance"}:
        methods = _methodology_analysis(window["opens"], highs, lows, closes, volumes, _adx(highs, lows, closes), "bullish" if analyzer.calculate_ema(closes, 9) and analyzer.calculate_ema(closes, 21) and analyzer.calculate_ema(closes, 9) > analyzer.calculate_ema(closes, 21) else "mixed")
        if name == "confluence_score": return methods["confluence"]["score"]
        if name == "regime_confidence": return methods["regime"]["confidence"]
        if name == "mtf_alignment_score":
            e9, e21, e50 = analyzer.calculate_ema(closes, 9), analyzer.calculate_ema(closes, 21), analyzer.calculate_ema(closes, 50)
            return 1 if e9 and e21 and e50 and e9 > e21 > e50 else -1 if e9 and e21 and e50 and e9 < e21 < e50 else 0
        if name == "turtle_breakout": return 1 if methods["turtle"]["breakout"] == "up_20" else -1 if methods["turtle"]["breakout"] == "down_20" else 0
        if name == "turtle_breakout_confirmed":
            return 1 if len(closes) > 20 and closes[-1] > max(highs[-21:-1]) else -1 if len(closes) > 20 and closes[-1] < min(lows[-21:-1]) else 0
        if name == "wyckoff_score": return methods["confluence"]["components"]["wyckoff"]
        if name == "elliott_score": return methods["elliott"]["confidence"]
        fib = methods["fibonacci"]
        return (closes[-1] / fib["0.786"] - 1) if name == "fib_distance_support" and fib["0.786"] else (closes[-1] / fib["0.236"] - 1) if fib["0.236"] else None
    if name in {"rsi_bullish_divergence", "rsi_bearish_divergence", "macd_bullish_divergence", "macd_bearish_divergence"}:
        if len(closes) < 40: return None
        midpoint = len(closes) // 2
        price_a, price_b = closes[midpoint - 10:midpoint], closes[-10:]
        if name.startswith("rsi_"):
            ind_a = [analyzer.calculate_rsi(closes[:midpoint - 10 + i + 1], 14) or 0 for i in range(10)]
            ind_b = [analyzer.calculate_rsi(closes[:len(closes) - 10 + i + 1], 14) or 0 for i in range(10)]
        else:
            ind_a = [_macd(closes[:midpoint - 10 + i + 1]).get("histogram", 0) if _macd(closes[:midpoint - 10 + i + 1]) else 0 for i in range(10)]
            ind_b = [_macd(closes[:len(closes) - 10 + i + 1]).get("histogram", 0) if _macd(closes[:len(closes) - 10 + i + 1]) else 0 for i in range(10)]
        higher_high = max(price_b) > max(price_a); lower_high = max(ind_b) < max(ind_a)
        lower_low = min(price_b) < min(price_a); higher_low = min(ind_b) > min(ind_a)
        bullish = lower_low and higher_low; bearish = higher_high and lower_high
        return 1 if (name.endswith("bullish_divergence") and bullish) or (name.endswith("bearish_divergence") and bearish) else 0
    if name in {"data_ready", "stale", "liquidity_fresh"}:
        if name == "data_ready": return 1 if len(closes) >= 50 else 0
        if name == "stale": return 0  # historical candle series is not a live ticker freshness source
        return 0  # bid/ask/order-book freshness is unavailable in historical candles
    return None

def _custom_conditions(analyzer, window, conditions):
    for condition in conditions or []:
        if not isinstance(condition, dict):
            raise ValueError("Her koşul nesne olmalı: {indicator, op, value}; metin koşulları desteklenmiyor")
        name = str(condition.get("indicator") or "").strip().lower()
        op = str(condition.get("op") or "").strip().lower()
        op = CUSTOM_OP_ALIASES.get(op, op)
        expected = condition.get("value")
        if name not in CUSTOM_INDICATORS or op not in CUSTOM_OPS:
            allowed = ", ".join(sorted(CUSTOM_INDICATORS))
            raise ValueError(f"Geçersiz custom koşul: {name} {op}; indicator/op şeması kullanılmalı, desteklenen indicator örnekleri: {allowed}")
        try: expected = float(expected)
        except (TypeError, ValueError): raise ValueError(f"Koşul değeri sayısal olmalıdır: {name}")
        actual = _custom_value(analyzer, window, name)
        if actual is None: return False
        ok = {"<": actual < expected, "<=": actual <= expected, ">": actual > expected, ">=": actual >= expected, "==": abs(actual - expected) < 1e-9}[op]
        if not ok: return False
    return bool(conditions)

def _run_custom(symbol, interval, days_back, definition, order_size=500.0, stop_pct=None, tp_pct=None,
                spread_pct=0.0, slippage_pct=None):
    if not isinstance(definition, dict): raise ValueError("strategy_definition nesne olmalıdır")
    entry = definition.get("entry") or []; exit_conditions = definition.get("exit") or []
    policy = definition.get("exit_policy") or {}
    if not isinstance(policy, dict):
        raise ValueError("exit_policy nesne olmalıdır")
    exit_mode = str(policy.get("mode", "conditions_plus_protection")).lower()
    if exit_mode not in {"conditions_only", "conditions_plus_protection", "protection_only"}:
        raise ValueError("exit_policy.mode: conditions_only, conditions_plus_protection veya protection_only olmalı")
    use_stop = bool(policy.get("use_stop_loss", exit_mode != "conditions_only"))
    use_target = bool(policy.get("use_take_profit", exit_mode != "conditions_only"))
    use_trailing = bool(policy.get("use_trailing_stop", False))
    use_max_hold = bool(policy.get("use_max_hold", False))
    max_hold_bars = int(policy.get("max_hold_bars", 0) or 0)
    trailing_pct = float(policy.get("trailing_stop_pct", 0) or 0)
    if use_max_hold and max_hold_bars < 1: raise ValueError("max_hold_bars pozitif olmalı")
    if use_trailing and not 0 < trailing_pct < 1: raise ValueError("trailing_stop_pct 0 ile 1 arasında olmalı")
    if len(entry) > 8 or len(exit_conditions) > 8: raise ValueError("En fazla 8 giriş ve 8 çıkış koşulu kullanılabilir")
    rows = _fetch_klines(symbol, interval, days_back); analyzer = ScalpAnalyzer(None); balance = config.INITIAL_BALANCE_TRY; position = None; trades = []; entry_armed = True; cooldown_until = -1
    stop_pct = float(stop_pct if stop_pct is not None else config.HARD_STOP_LOSS_PCT)
    tp_pct = float(tp_pct if tp_pct is not None else config.SPOT_PROFIT_TARGET_PCT)
    interval_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800, "12h": 43200, "1d": 86400}.get(interval, 300)
    for i, close in enumerate(rows["closes"]):
        window = {k:v[:i+1] for k,v in rows.items()}; now = rows["times"][i]
        if position:
            exit_price = None; reason = None
            position["max_price"] = max(position.get("max_price", position["entry"]), rows["highs"][i])
            stop_price = position.get("stop_price")
            target_price = position.get("target_price")
            trailing_price = position["max_price"] * (1 - trailing_pct) if use_trailing else None
            condition_hit = bool(exit_conditions) and _custom_conditions(analyzer, window, exit_conditions)
            if use_stop and stop_price is not None and rows["lows"][i] <= stop_price:
                exit_price=stop_price; reason="custom_stop_loss"
            elif use_target and target_price is not None and rows["highs"][i] >= target_price:
                exit_price=target_price; reason="custom_take_profit"
            elif use_trailing and trailing_price is not None and rows["lows"][i] <= trailing_price:
                exit_price=trailing_price; reason="custom_trailing_stop"
            elif use_max_hold and i - position["entry_bar"] >= max_hold_bars:
                exit_price=close; reason="custom_max_hold"
            elif exit_mode != "protection_only" and condition_hit:
                exit_price=close; reason="custom_exit_condition"
            if exit_price is not None:
                balance, pnl, _, trade = _close_trade(balance, position["entry"], exit_price, position["quantity"], order_size, reason, spread_pct, slippage_pct); trade.update({"entry_time":position["entry_time"],"exit_time":now}); trades.append(trade); position=None; cooldown_until = i + 1; entry_armed = False
        entry_signal = _custom_conditions(analyzer, window, entry)
        if not entry_signal: entry_armed = True
        if position is None and i >= cooldown_until and entry_armed and balance >= order_size and entry_signal:
            if i + 1 >= len(rows["opens"]):
                continue
            entry_price = rows["opens"][i + 1]
            fee=order_size*config.COMMISSION_PCT; balance-=order_size+fee
            position={"entry":entry_price,"quantity":order_size/entry_price,"entry_time":rows["times"][i + 1],
                      "entry_bar":i + 1, "stop_price":entry_price * (1 - stop_pct),
                      "target_price":entry_price * (1 + tp_pct), "max_price": entry_price}
            entry_armed = False
    if position:
        balance, pnl, _, trade = _close_trade(balance, position["entry"], rows["closes"][-1], position["quantity"], order_size, "open_at_end_mark_to_market", spread_pct, slippage_pct); trade.update({"entry_time":position["entry_time"],"exit_time":rows["times"][-1]}); trades.append(trade)
    wins=sum(t["pnl"]>0 for t in trades); net=balance-config.INITIAL_BALANCE_TRY; losses=[t["pnl"] for t in trades if t["pnl"]<=0]; gains=[t["pnl"] for t in trades if t["pnl"]>0]
    return {"strategy":"CUSTOM","symbol":symbol,"interval":interval,"days_back":days_back,"definition":definition,"exit_policy":policy,"initial_balance":config.INITIAL_BALANCE_TRY,"final_balance":round(balance,2),"net_pnl":round(net,2),"total_trades":len(trades),"wins":wins,"losses":len(trades)-wins,"win_rate":round(wins/len(trades)*100,2) if trades else 0,"profit_factor":round(sum(gains)/abs(sum(losses)),3) if losses else None,"trades":trades,"exit_reason_counts":dict(Counter(t["reason"] for t in trades)),"data_quality":_data_quality(rows, interval),"fill_model":"next_bar_open_entry_executable_exit","spread_pct":spread_pct,"slippage_pct":config.ESTIMATED_SLIPPAGE_PCT if slippage_pct is None else slippage_pct,"paper_only":True,"custom_strategy":True,"exit_model":exit_mode,"exit_controls":{"stop_loss":use_stop,"take_profit":use_target,"trailing_stop":use_trailing,"max_hold":use_max_hold}}

async def run_custom_backtest(symbol, interval, days_back, definition, order_size=500.0, stop_pct=None, tp_pct=None,
                              spread_pct=0.0, slippage_pct=None):
    return await asyncio.to_thread(_run_custom, symbol, interval, days_back, definition, order_size, stop_pct, tp_pct, spread_pct, slippage_pct)


def _run_single(symbol, interval, days_back, strategy, params, order_size, stop_pct, tp_pct, trail_pct,
                start_ts=None, end_ts=None, spread_pct=0.0, slippage_pct=None):
    _validate(symbol, interval, days_back, strategy, params, order_size, stop_pct, tp_pct, trail_pct)
    # Historical candles have no bid/ask; use an explicit conservative spread
    # assumption unless a stress scenario supplies its own value.
    if spread_pct == 0.0:
        spread_pct = config.BACKTEST_ASSUMED_SPREAD_PCT
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
            first_target_pct = float(tp_pct if tp_pct is not None else config.SPOT_PROFIT_TARGET_PCT)
            equity_peak = balance
            max_drawdown = 0.0
            position = None
            wins = losses = 0
            trades = []
            open_at_end = False
            unrealized_pnl = 0.0
            last_eval_i = None

            for i, close in enumerate(data["closes"]):
                candle_time = data["times"][i]
                if start_ts is not None and candle_time < start_ts:
                    continue
                if end_ts is not None and candle_time > end_ts:
                    break
                last_eval_i = i
                high, low = data["highs"][i], data["lows"][i]
                if position:
                    window = {key: values[:i + 1] for key, values in data.items()}
                    elapsed = max(0, data["times"][i] - position["entry_time"])
                    atr = analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD)
                    position["max_price"] = max(position.get("max_price", position["entry"]), high)
                    if atr:
                        activation = atr * config.SYSTEM_ATR_TRAILING_ACTIVATION_ATR
                        if position["max_price"] - position["entry"] >= activation:
                            candidate = position["max_price"] - atr * config.SYSTEM_ATR_TRAILING_MULTIPLIER
                            position["trailing_stop"] = max(position.get("trailing_stop", 0), candidate)
                    if high >= position["target_price"]:
                        position["target_reached"] = True
                    stop_price = max(position.get("stop_price", 0), position.get("trailing_stop", 0))
                    # RR hedefi bir minimum kâr eşiğidir; kapanışı ATR trailing belirler.
                    exit_price = stop_price if stop_price > 0 and low <= stop_price else None
                    reason = "atr_trailing_stop" if position.get("trailing_stop", 0) and exit_price == stop_price else "system_stop_loss"
                    if exit_price is None and (config.STALE_POSITION_EXIT_BELOW_COST and
                          elapsed >= config.STALE_POSITION_SEC and
                          close < position["entry"] * (1 + config.min_net_exit_pct(order_size * position.get("layers", 1)))):
                        exit_price = close
                        reason = "stale_position_below_cost"
                    elif exit_price is None and config.EXIT_ON_OPPOSITE_SIGNAL and fn(window, symbol) == "sell":
                        exit_price = close
                        reason = "opposite_signal"
                    if exit_price is not None:
                        balance, pnl, _, trade = _close_trade(balance, position["entry"], exit_price, position["quantity"], order_size * position.get("layers", 1), reason, spread_pct, slippage_pct)
                        trade.update({"entry_time": position["entry_time"], "exit_time": data["times"][i],
                                      "entry_bar": position["entry_bar"], "exit_bar": i,
                                      "bars_held": i - position["entry_bar"] + 1})
                        trades.append(trade); wins += pnl > 0; losses += pnl <= 0; position = None
                    elif position.get("layers", 1) < config.MAX_POSITION_LAYERS and balance >= order_size:
                        result = fn(window, symbol)
                        if result == "buy":
                            if i + 1 >= len(data["opens"]):
                                continue
                            fee = order_size * config.COMMISSION_PCT
                            balance -= order_size + fee
                            entry_price = data["opens"][i + 1]
                            quantity = order_size / entry_price
                            total_quantity = position["quantity"] + quantity
                            position["entry"] = ((position["entry"] * position["quantity"]) + (entry_price * quantity)) / total_quantity
                            position["quantity"] = total_quantity
                            position["layers"] = position.get("layers", 1) + 1
                            atr_now = analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD) or position["entry"] * config.HARD_STOP_LOSS_PCT
                            stop_distance = max(position["entry"] * config.HARD_STOP_LOSS_PCT, atr_now * config.SYSTEM_INITIAL_STOP_ATR_MULTIPLIER)
                            position["stop_price"] = position["entry"] - stop_distance
                            position["target_price"] = position["entry"] + stop_distance * config.SYSTEM_RISK_REWARD
                else:
                    window = {key: values[:i + 1] for key, values in data.items()}
                    result = fn(window, symbol)
                    if balance >= order_size and result == "buy":
                        if i + 1 >= len(data["opens"]):
                            continue
                        entry_fee = order_size * config.COMMISSION_PCT
                        balance -= order_size + entry_fee
                        atr = analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD) or close * config.HARD_STOP_LOSS_PCT
                        entry_price = data["opens"][i + 1]
                        stop_distance = max(entry_price * config.HARD_STOP_LOSS_PCT, atr * config.SYSTEM_INITIAL_STOP_ATR_MULTIPLIER)
                        position = {"entry": entry_price, "quantity": order_size / entry_price,
                                    "entry_time": data["times"][i + 1], "entry_bar": i + 1, "layers": 1}
                        position["stop_price"] = entry_price - stop_distance
                        position["target_price"] = entry_price + stop_distance * config.SYSTEM_RISK_REWARD
                        position["max_price"] = entry_price
                marked = balance + (position["quantity"] * close if position else 0)
                equity_peak = max(equity_peak, marked)
                intrabar_marked = balance + (position["quantity"] * low if position else 0)
                max_drawdown = max(max_drawdown,
                                   (equity_peak - marked) / equity_peak if equity_peak else 0,
                                   (equity_peak - intrabar_marked) / equity_peak if equity_peak else 0)

            if position:
                open_at_end = True
                final_i = last_eval_i if last_eval_i is not None else len(data["closes"]) - 1
                final_price = data["closes"][final_i]
                unrealized_pnl = (final_price - position["entry"]) * position["quantity"]
                balance, pnl, _, trade = _close_trade(balance, position["entry"], final_price, position["quantity"], order_size * position.get("layers", 1), "open_at_end_mark_to_market", spread_pct, slippage_pct)
                trade.update({"entry_time": position["entry_time"], "exit_time": data["times"][final_i],
                              "entry_bar": position["entry_bar"], "exit_bar": final_i,
                              "bars_held": final_i - position["entry_bar"] + 1})
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
                    "microstructure_model": "historical_bid_ask_unavailable_candle_proxy",
                    "cost_model": "round_trip_commission_spread_slippage",
                    "trailing_stop_pct": 0.0, "atr_trailing_multiplier": config.SYSTEM_ATR_TRAILING_MULTIPLIER,
                    "risk_reward": config.SYSTEM_RISK_REWARD,
                    "exit_model": "atr_trailing_after_rr_target",
                    "fill_model": "next_bar_open_entry_executable_exit",
                    "spread_pct": spread_pct, "slippage_pct": config.ESTIMATED_SLIPPAGE_PCT if slippage_pct is None else slippage_pct,
                    "data_quality": _data_quality(data, interval),
                    "open_position_at_end": open_at_end, "unrealized_pnl": round(unrealized_pnl, 8),
                    "trades": trades, "timestamp": time.time(),
                    "evaluation_start": start_ts, "evaluation_end": end_ts}
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


async def run_walk_forward(symbol: str, interval: str, strategy: str,
                           train_days: int = 30, test_days: int = 7,
                           folds: int = 3, order_size: float = 500.0,
                           stop_pct: float = 0.005, tp_pct: float = 0.015):
    """Chronological OOS folds for classic system strategies only.

    LLM_PAPER cannot be replayed here because historical LLM decisions/plans
    are not reconstructed candle-by-candle. Its exact exit model belongs to
    run_custom_backtest with explicit TP/SL and exit conditions.
    """
    if str(strategy).upper() == "LLM_PAPER":
        raise ValueError("LLM_PAPER walk-forward için explicit plan/exit koşulları gerekir; run_custom_backtest kullanın")
    train_days = max(7, min(int(train_days), 90)); test_days = max(1, min(int(test_days), 30))
    folds = max(1, min(int(folds), 6))
    now = time.time(); results = []
    for fold in range(folds):
        end_ts = now - (folds - fold - 1) * test_days * 86400
        start_ts = end_ts - test_days * 86400
        result = await asyncio.to_thread(
            _run_single, symbol, interval, train_days + test_days, strategy, {},
            order_size, stop_pct, tp_pct, 0.0, start_ts, end_ts)
        result["fold"] = fold + 1
        results.append(result)
    pnl = [float(row.get("net_pnl") or 0) for row in results]
    positive_folds = sum(value > 0 for value in pnl)
    return {"symbol": symbol, "interval": interval, "strategy": strategy,
            "method": "chronological_oos_folds", "train_days": train_days,
            "test_days": test_days, "folds": len(results),
            "positive_oos_folds": positive_folds,
            "oos_consistent": bool(results) and positive_folds >= max(1, len(results) // 2 + 1),
            "net_pnl": round(sum(pnl), 2),
            "average_fold_pnl": round(sum(pnl) / len(pnl), 2) if pnl else 0.0,
            "fold_results": results, "paper_only": True,
            "warning": "OOS sonucu kârlılık garantisi değildir; maliyet varsayımları ve örneklem büyüklüğü ayrıca incelenmelidir."}


async def run_execution_stress(symbol: str, interval: str, strategy: str, days_back: int = 30,
                               order_size: float = 500.0, scenarios: list[dict] | None = None):
    scenarios = scenarios or [{"name": "base", "spread_pct": 0.0, "slippage_pct": config.ESTIMATED_SLIPPAGE_PCT},
                               {"name": "normal", "spread_pct": 0.001, "slippage_pct": config.ESTIMATED_SLIPPAGE_PCT * 2},
                               {"name": "stress", "spread_pct": 0.003, "slippage_pct": config.ESTIMATED_SLIPPAGE_PCT * 4}]
    rows = []
    for scenario in scenarios[:5]:
        # _run_single already applies executable-price costs through _close_trade.
        result = await asyncio.to_thread(_run_single, symbol, interval, days_back, strategy, {}, order_size,
                                         config.HARD_STOP_LOSS_PCT, config.SPOT_PROFIT_TARGET_PCT, 0.0,
                                         None, None, float(scenario.get("spread_pct", 0.0)),
                                         float(scenario.get("slippage_pct", config.ESTIMATED_SLIPPAGE_PCT)))
        result["scenario"] = scenario.get("name", "custom")
        result["assumed_spread_pct"] = float(scenario.get("spread_pct", 0.0))
        result["assumed_slippage_pct"] = float(scenario.get("slippage_pct", config.ESTIMATED_SLIPPAGE_PCT))
        rows.append({key: result.get(key) for key in ("scenario", "net_pnl", "net_pnl_pct", "total_trades", "win_rate", "profit_factor", "max_drawdown_pct", "assumed_spread_pct", "assumed_slippage_pct")})
    return {"symbol": symbol, "interval": interval, "strategy": strategy, "days_back": days_back,
            "scenarios": rows, "paper_only": True,
            "warning": "Sonuçlar komisyon, spread ve slippage varsayımlarına duyarlıdır; gerçek dolum garantisi değildir."}


async def run_parameter_sensitivity(symbol: str, interval: str, strategy: str, days_back: int = 30,
                                    order_size: float = 500.0):
    variations = [("tight", 0.003, 1.0), ("base", config.HARD_STOP_LOSS_PCT, config.SYSTEM_RISK_REWARD),
                  ("wide", 0.01, 2.0)]
    rows = []
    for name, stop, rr in variations:
        result = await asyncio.to_thread(_run_single, symbol, interval, days_back, strategy, {}, order_size, stop, stop * rr, 0.0)
        rows.append({"variant": name, "stop_pct": stop, "risk_reward": rr, "net_pnl": result.get("net_pnl"),
                     "win_rate": result.get("win_rate"), "profit_factor": result.get("profit_factor"),
                     "max_drawdown_pct": result.get("max_drawdown_pct"), "trades": result.get("total_trades")})
    return {"symbol": symbol, "interval": interval, "strategy": strategy, "days_back": days_back,
            "variants": rows, "paper_only": True,
            "interpretation": "Tek bir parametre noktasının yerine komşu aralıkların tutarlılığı incelenmelidir."}


async def run_holdout_test(symbol: str, interval: str, strategy: str, train_days: int = 60,
                           holdout_days: int = 14, order_size: float = 500.0):
    train_days = max(30, min(int(train_days), 180)); holdout_days = max(3, min(int(holdout_days), 60))
    total_days = train_days + holdout_days
    end = time.time(); start = end - holdout_days * 86400
    result = await asyncio.to_thread(_run_single, symbol, interval, total_days, strategy, {}, order_size,
                                     config.HARD_STOP_LOSS_PCT, config.SPOT_PROFIT_TARGET_PCT, 0.0, start, end)
    return {"symbol": symbol, "interval": interval, "strategy": strategy, "train_days": train_days,
            "holdout_days": holdout_days, "holdout": result, "paper_only": True,
            "warning": "Holdout, seçim/optimizasyon tamamlandıktan sonra tek seferlik kullanılmalıdır."}


async def run_statistical_validation(symbol: str, interval: str, strategy: str, days_back: int = 60,
                                     order_size: float = 500.0, trials: int = 3, iterations: int = 2000):
    """Paper-only PBO/DSR-style report with explicit sample-size caveats."""
    variants = [("tight", 0.003, 1.0), ("base", config.HARD_STOP_LOSS_PCT, config.SYSTEM_RISK_REWARD),
                ("wide", 0.01, 2.0)]
    variant_results = []
    for name, stop, rr in variants:
        variant_results.append((name, await asyncio.to_thread(_run_single, symbol, interval, days_back, strategy, {}, order_size, stop, stop * rr, 0.0)))
    result = next((row for name, row in variant_results if name == "base"), variant_results[0][1])
    pnls = [float(t.get("pnl") or 0) for t in result.get("trades", [])]
    if not pnls:
        return {"symbol": symbol, "strategy": strategy, "sample_size": 0, "data_sufficient": False,
                "warning": "İstatistiksel doğrulama için işlem örneklemi yok.", "paper_only": True}
    rng = random.Random(42)
    block = max(2, int(math.sqrt(len(pnls))))
    samples = []
    for _ in range(max(100, min(iterations, 10000))):
        draw = []
        while len(draw) < len(pnls):
            start = rng.randrange(max(1, len(pnls) - block + 1))
            draw.extend(pnls[start:start + block])
        samples.append(sum(draw[:len(pnls)]))
    samples.sort()
    mean = sum(pnls) / len(pnls)
    variance = sum((x - mean) ** 2 for x in pnls) / max(1, len(pnls) - 1)
    sharpe_like = mean / math.sqrt(variance) if variance > 0 else 0.0
    n = len(pnls)
    centered = [(x - mean) / math.sqrt(variance) for x in pnls] if variance > 0 else [0.0]
    skew = sum(x ** 3 for x in centered) / n
    kurtosis = sum(x ** 4 for x in centered) / n
    sharpe_se = math.sqrt(max(1e-12, (1 - skew * sharpe_like + ((kurtosis - 1) / 4) * sharpe_like ** 2) / max(1, n - 1)))
    normal_cdf = lambda value: 0.5 * (1 + math.erf(value / math.sqrt(2)))
    expected_max = math.sqrt(2 * math.log(max(1, int(trials))))
    dsr = normal_cdf((sharpe_like - expected_max) / sharpe_se) if sharpe_se else 0.0
    # One chronological split across candidate variants: the selected IS winner's OOS rank.
    split = max(1, n // 2)
    ranked = []
    for name, candidate in variant_results:
        values = [float(t.get("pnl") or 0) for t in candidate.get("trades", [])]
        if len(values) >= 4:
            ranked.append((name, sum(values[:split]), sum(values[split:])))
    pbo = None
    if len(ranked) >= 2:
        selected = max(ranked, key=lambda row: row[1])
        median_oos = sorted(row[2] for row in ranked)[len(ranked) // 2]
        pbo = 1.0 if selected[2] < median_oos else 0.0
    return {"symbol": symbol, "interval": interval, "strategy": strategy, "sample_size": len(pnls),
            "bootstrap": {"iterations": len(samples), "p05": samples[int(len(samples) * .05)],
                          "median": samples[len(samples) // 2], "p95": samples[int(len(samples) * .95) - 1],
                          "probability_positive": round(sum(x > 0 for x in samples) / len(samples), 4)},
            "metrics": {"mean_trade_pnl": round(mean, 6), "sharpe_like": round(sharpe_like, 6),
                        "skewness": round(skew, 6), "kurtosis": round(kurtosis, 6),
                        "trial_count": int(trials), "deflated_sharpe_probability": round(dsr, 6),
                        "bootstrap_block_length": block},
            "pbo": {"estimate": pbo, "candidate_variants": len(ranked), "method": "one chronological IS/OOS split; directional screening"},
            "limitations": ["PBO sonucu anlamlı olmak için daha fazla bağımsız zaman bölmesi ve aday strateji geçmişi gerekir.",
                            "DSR olasılığı işlem getirileri için uygulanmış screening ölçüsüdür; yatırım başarısı garantisi değildir."],
            "paper_only": True}


async def get_backtest_data_quality(symbol: str, interval: str, days_back: int = 30):
    data = await asyncio.to_thread(_fetch_klines, symbol, interval, max(1, min(int(days_back), 365)))
    quality = _data_quality(data, interval)
    quality.update({"symbol": symbol, "interval": interval, "days_back": days_back,
                    "first_candle_time": data["times"][0] if data["times"] else None,
                    "last_candle_time": data["times"][-1] if data["times"] else None,
                    "paper_only": True})
    return quality
