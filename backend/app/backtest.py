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
from app.technical_analysis import (
    _adx, _macd, _bollinger, _stochastic, _mfi, _cci, _williams_r, _methodology_analysis,
    _confirmed_structure, _fair_value_gap, _td9_sequence, _volume_profile_proxy, _wick_rejection_zscore,
)
from app.binance_tr_public import historical_klines
from app.config import config

_ORIGINAL_BB_MFI_STRATEGY = ScalpAnalyzer.strategy_bb_mfi_mean_reversion

STRATEGIES = {
    "EMA_VWAP_PULLBACK": ("EMA_VWAP_ENABLED", "EMA_VWAP_TIMEFRAME", "strategy_ema_vwap"),
    "BB_SQUEEZE_ORDERFLOW": ("BB_SQUEEZE_ENABLED", "BB_SQUEEZE_TIMEFRAME", "strategy_bb_squeeze_orderflow"),
    "ORDERFLOW": ("ORDERFLOW_ENABLED", "ORDERFLOW_TIMEFRAME", "strategy_orderflow"),
    "MOMENTUM": ("MOMENTUM_ENABLED", "MOMENTUM_TIMEFRAME", "strategy_momentum"),
    "MOMENTUM_SCORED": ("MOMENTUM_ENABLED", "MOMENTUM_TIMEFRAME", "strategy_momentum_scored"),
    "MOMENTUM_SCORED_V2": ("MOMENTUM_ENABLED", "MOMENTUM_TIMEFRAME", "strategy_momentum_scored_v2"),
    "MOMENTUM_COST_AWARE": ("MOMENTUM_COST_AWARE_ENABLED", "MOMENTUM_TIMEFRAME", "strategy_momentum_cost_aware"),
    "OVERSOLD_TREND_REENTRY": ("OVERSOLD_TREND_REENTRY_ENABLED", "OVERSOLD_TREND_REENTRY_TIMEFRAME", "strategy_oversold_trend_reentry"),
    "ADAPTIVE_VOLATILITY_TREND": ("ADAPTIVE_VOLATILITY_TREND_ENABLED", "ADAPTIVE_VOLATILITY_TREND_TIMEFRAME", "strategy_adaptive_volatility_trend"),
    "REGIME_GATE_LOW_TURNOVER": ("REGIME_GATE_LOW_TURNOVER_ENABLED", "REGIME_GATE_LOW_TURNOVER_TIMEFRAME", "strategy_regime_gate_low_turnover"),
    "VWAP_MEAN_REVERSION": ("MEAN_REVERSION_ENABLED", "MEAN_REVERSION_TIMEFRAME", "strategy_mean_reversion"),
    "BB_MFI_MEAN_REVERSION": ("MEAN_REVERSION_ENABLED", "MEAN_REVERSION_TIMEFRAME", "strategy_bb_mfi_mean_reversion"),
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
    "bb_mfi_bb_period": "BB_MFI_BB_PERIOD", "bb_mfi_bb_std_dev": "BB_MFI_BB_STD_DEV",
    "bb_mfi_mfi_period": "BB_MFI_MFI_PERIOD", "bb_mfi_entry_mfi_max": "BB_MFI_ENTRY_MFI_MAX",
    "bb_mfi_exit_rsi_min": "BB_MFI_EXIT_RSI_MIN", "bb_mfi_exit_mfi_min": "BB_MFI_EXIT_MFI_MIN",
    "bb_mfi_rsi_period": "BB_MFI_RSI_PERIOD",
    "bb_mfi_v1_rsi_lower_level": "BB_MFI_V1_RSI_LOWER_LEVEL", "bb_mfi_v1_rsi_upper_level": "BB_MFI_V1_RSI_UPPER_LEVEL",
    "bb_mfi_v2_rsi_lower_level": "BB_MFI_V2_RSI_LOWER_LEVEL", "bb_mfi_v2_rsi_upper_level": "BB_MFI_V2_RSI_UPPER_LEVEL",
    "bb_mfi_stop_loss_pct": "BB_MFI_STOP_LOSS_PCT", "bb_mfi_take_profit_pct": "BB_MFI_TAKE_PROFIT_PCT",
}

# Analyzer stratejileri mevcut global config'i okuduğu için backtest config değişimini serileştir.
_CONFIG_LOCK = threading.RLock()
_KLINE_CACHE: dict[tuple[str, str, int, int | None], dict[str, list[float]]] = {}


def _fetch_klines(symbol: str, interval: str, days_back: int, end_time_ms: int | None = None) -> dict[str, list[float]]:
    """Read a fixed, completed-candle window from persisted public history.

    ``end_time_ms`` makes a historical fold reproducible and prevents a
    walk-forward run from silently reading candles after the fold boundary.
    """
    requested_end_ms = int(end_time_ms) if end_time_ms is not None else None
    cache_key = (symbol.upper(), interval, int(days_back), requested_end_ms)
    cached = _KLINE_CACHE.get(cache_key)
    if cached:
        return {key: list(values) for key, values in cached.items()}
    # Backtests are reproducible: they read only the persisted historical table.
    now_ms = int(time.time() * 1000)
    end_ms = min(requested_end_ms, now_ms) if requested_end_ms is not None else now_ms
    start_ms = end_ms - int(days_back) * 86400 * 1000
    cached_rows = asyncio.run(database.get_market_candles(symbol, interval, start_ms, end_ms))
    rows = [[r["open_time"], r["open"], r["high"], r["low"], r["close"], r["volume"], r["close_time"]] for r in cached_rows]
    if not rows:
        raise ValueError(f"{symbol} {interval} için historical_candles tablosunda veri yok; önce veri toplama çalıştırılmalı")
    if not rows:
        raise ValueError(f"{symbol} için tarihsel veri bulunamadı")
    result = {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": [], "times": []}
    seen_times = set()
    for row in rows:
        if len(row) < 6:
            continue
        close_ms = int(row[6]) if len(row) > 6 else int(row[0])
        if close_ms > end_ms or close_ms in seen_times:
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

def _close_partial(balance, exit_price, quantity, spread_pct=0.0, slippage_pct=None):
    """Sell part of a position; entry cost was already booked at entry."""
    slip = float(config.ESTIMATED_SLIPPAGE_PCT if slippage_pct is None else slippage_pct)
    fill = exit_price * max(0.0, 1 - max(0.0, float(spread_pct)) / 2 - slip)
    fee = fill * quantity * config.COMMISSION_PCT
    return balance + fill * quantity - fee, fill * quantity - fee


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
    "td9_up_count", "td9_down_count", "td9_up_exhaustion", "td9_down_exhaustion",
    "bos_bullish", "bos_bearish", "structure_volume_confirmed", "fvg_bullish", "fvg_bearish",
    "wick_bullish_rejection", "wick_bearish_rejection", "vp_poc_distance", "vp_inside_value_area",
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
    "research_structure": ["td9_up_count", "td9_down_count", "td9_up_exhaustion", "td9_down_exhaustion", "bos_bullish", "bos_bearish", "structure_volume_confirmed", "fvg_bullish", "fvg_bearish", "wick_bullish_rejection", "wick_bearish_rejection", "vp_poc_distance", "vp_inside_value_area"],
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
    if name in {"td9_up_count", "td9_down_count", "td9_up_exhaustion", "td9_down_exhaustion"}:
        td9 = _td9_sequence(closes)
        if not td9.get("ready"): return None
        if name == "td9_up_count": return td9["bullish_count"]
        if name == "td9_down_count": return td9["bearish_count"]
        return 1 if td9["exhaustion"] == ("uptrend_9" if name == "td9_up_exhaustion" else "downtrend_9") else 0
    if name in {"bos_bullish", "bos_bearish", "structure_volume_confirmed"}:
        structure = _confirmed_structure(highs, lows, closes, volumes)
        if not structure.get("ready"): return None
        if name == "structure_volume_confirmed": return 1 if structure.get("volume_confirmed") else 0
        return 1 if structure.get("break_of_structure") == ("bullish" if name == "bos_bullish" else "bearish") else 0
    if name in {"fvg_bullish", "fvg_bearish"}:
        gap = _fair_value_gap(highs, lows, closes, analyzer.calculate_atr(window, 14))
        if not gap.get("ready"): return None
        return 1 if gap.get("side") == ("bullish" if name == "fvg_bullish" else "bearish") else 0
    if name in {"wick_bullish_rejection", "wick_bearish_rejection"}:
        wick = _wick_rejection_zscore(window["opens"], highs, lows, closes)
        if not wick.get("ready"): return None
        return 1 if wick.get("signal") == ("bullish_rejection" if name == "wick_bullish_rejection" else "bearish_rejection") else 0
    if name in {"vp_poc_distance", "vp_inside_value_area"}:
        profile = _volume_profile_proxy(highs, lows, closes, volumes)
        if not profile.get("ready"): return None
        if name == "vp_poc_distance": return closes[-1] / profile["poc"] - 1 if profile["poc"] else None
        return 1 if profile["value_area_low"] <= closes[-1] <= profile["value_area_high"] else 0
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
                spread_pct=0.0, slippage_pct=None, start_ts=None, end_ts=None):
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
    end_time_ms = int(float(end_ts) * 1000) if end_ts is not None else None
    rows = _fetch_klines(symbol, interval, days_back, end_time_ms); analyzer = ScalpAnalyzer(None); balance = config.INITIAL_BALANCE_TRY; position = None; trades = []; entry_armed = True; cooldown_until = -1
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
        # Warm-up candles may inform indicators, but may never create a
        # position before a chronological OOS fold begins.
        entry_signal = (start_ts is None or now >= float(start_ts)) and _custom_conditions(analyzer, window, entry)
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
    return {"strategy":"CUSTOM","symbol":symbol,"interval":interval,"days_back":days_back,"definition":definition,"exit_policy":policy,"initial_balance":config.INITIAL_BALANCE_TRY,"final_balance":round(balance,2),"net_pnl":round(net,2),"total_trades":len(trades),"wins":wins,"losses":len(trades)-wins,"win_rate":round(wins/len(trades)*100,2) if trades else 0,"profit_factor":round(sum(gains)/abs(sum(losses)),3) if losses else None,"trades":trades,"exit_reason_counts":dict(Counter(t["reason"] for t in trades)),"data_quality":_data_quality(rows, interval),"fill_model":"next_bar_open_entry_executable_exit","spread_pct":spread_pct,"slippage_pct":config.ESTIMATED_SLIPPAGE_PCT if slippage_pct is None else slippage_pct,"paper_only":True,"custom_strategy":True,"exit_model":exit_mode,"exit_controls":{"stop_loss":use_stop,"take_profit":use_target,"trailing_stop":use_trailing,"max_hold":use_max_hold},"evaluation_start_ts":start_ts,"evaluation_end_ts":end_ts}

async def run_custom_backtest(symbol, interval, days_back, definition, order_size=500.0, stop_pct=None, tp_pct=None,
                              spread_pct=0.0, slippage_pct=None, start_ts=None, end_ts=None):
    return await asyncio.to_thread(_run_custom, symbol, interval, days_back, definition, order_size, stop_pct, tp_pct, spread_pct, slippage_pct, start_ts, end_ts)


async def run_custom_walk_forward(symbol: str, interval: str, definition: dict,
                                  train_days: int = 10, test_days: int = 5,
                                  folds: int = 4, order_size: float = 500.0,
                                  stop_pct: float | None = None, tp_pct: float | None = None,
                                  spread_pct: float = 0.0, slippage_pct: float | None = None):
    """Chronological, no-fit OOS validation for declarative custom strategies."""
    train_days = max(3, min(int(train_days), 90)); test_days = max(1, min(int(test_days), 30))
    folds = max(1, min(int(folds), 6)); now = time.time(); results = []
    for fold in range(folds):
        end_ts = now - (folds - fold - 1) * test_days * 86400
        start_ts = end_ts - test_days * 86400
        result = await asyncio.to_thread(
            _run_custom, symbol, interval, train_days + test_days, definition,
            order_size, stop_pct, tp_pct, spread_pct, slippage_pct, start_ts, end_ts)
        result["fold"] = fold + 1
        results.append(result)
    pnl = [float(row.get("net_pnl") or 0) for row in results]
    positive_folds = sum(value > 0 for value in pnl)
    total_pnl = sum(pnl)
    total_trades = sum(max(0, int(row.get("total_trades") or 0)) for row in results)
    reasons = []
    if len(results) < 3: reasons.append("insufficient_folds")
    if total_trades < 30: reasons.append("insufficient_trades")
    if positive_folds < len(results) // 2 + 1: reasons.append("insufficient_positive_fold_majority")
    if total_pnl <= 0: reasons.append("non_positive_total_net_pnl")
    return {"symbol": symbol, "interval": interval, "strategy": "CUSTOM", "definition": definition,
            "method": "chronological_oos_folds_without_parameter_training", "train_days": train_days,
            "warmup_context_days": train_days, "training_performed": False, "parameter_selection": "none",
            "test_days": test_days, "folds": len(results), "positive_oos_folds": positive_folds,
            "minimum_required_folds": 3, "minimum_required_trades": 30, "total_oos_trades": total_trades,
            "data_sufficient": len(results) >= 3 and total_trades >= 30,
            "oos_consistent": not reasons, "validation_status": "PASS" if not reasons else "FAIL",
            "validation_reasons": reasons, "net_pnl": round(total_pnl, 2),
            "average_fold_pnl": round(sum(pnl) / len(pnl), 2) if pnl else 0.0,
            "fold_results": results, "paper_only": True,
            "warning": "Parametre eğitimi veya seçimi yapılmadı. Warm-up yalnız geçmiş gösterge bağlamıdır; işlem yalnız OOS test döneminde açılabilir. Sonuç kârlılık garantisi değildir."}


def _bb_mfi_signal_series(data: dict[str, list[float]], analyzer: ScalpAnalyzer) -> list[str | None]:
    """Produce Pine-v3 BB/MFI decisions once per closed candle.

    The generic strategy path used to recompute RSI from bar zero for every
    candle.  Wilder RSI is recursive, so retaining its rolling state yields
    the same value without changing the strategy contract or using future
    candles.  This helper is used only by the deterministic backtest path.
    """
    closes, highs, lows, volumes = (data[key] for key in ("closes", "highs", "lows", "volumes"))
    size = len(closes); signals: list[str | None] = [None] * size
    period = config.BB_MFI_RSI_PERIOD
    rsi_values: list[float | None] = [None] * size
    if size > period:
        gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, size)]
        losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, size)]
        avg_gain = sum(gains[:period]) / period; avg_loss = sum(losses[:period]) / period
        for index in range(period, size):
            if index > period:
                avg_gain = (avg_gain * (period - 1) + gains[index - 1]) / period
                avg_loss = (avg_loss * (period - 1) + losses[index - 1]) / period
            rsi_values[index] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

    version = config.BB_MFI_PINE_VERSION
    min_history = max(config.BB_MFI_BB_PERIOD, period + 1,
                      config.BB_MFI_MFI_PERIOD + 1 if version == "v3" else 0)
    for index in range(min_history - 1, size):
        close = closes[index]; bb_values = closes[index - config.BB_MFI_BB_PERIOD + 1:index + 1]
        middle = sum(bb_values) / len(bb_values)
        variance = sum((value - middle) ** 2 for value in bb_values) / len(bb_values)
        lower_band = middle - math.sqrt(variance) * config.BB_MFI_BB_STD_DEV
        upper_band = middle + math.sqrt(variance) * config.BB_MFI_BB_STD_DEV
        rsi = rsi_values[index]
        if rsi is None:
            continue
        average_volume = sum(volumes[index - 20:index]) / 20 if index >= 20 else 0.0
        volume_ratio = volumes[index] / average_volume if average_volume else 0.0
        candle_range = highs[index] - lows[index]
        close_position = (close - lows[index]) / candle_range if candle_range > 0 else 0.0
        entry_volume_ok = volume_ratio >= config.BB_MFI_ENTRY_VOLUME_RATIO_MIN
        dip_confirmed = (not config.BB_MFI_DIP_CONFIRMATION_ENABLED or close_position >= config.BB_MFI_DIP_MIN_CLOSE_POSITION)
        if version == "v3":
            start = index - config.BB_MFI_MFI_PERIOD
            mfi = _mfi(highs[start:index + 1], lows[start:index + 1], closes[start:index + 1], volumes[start:index + 1], config.BB_MFI_MFI_PERIOD)
            previous_mfi = (_mfi(highs[start - 1:index], lows[start - 1:index], closes[start - 1:index], volumes[start - 1:index], config.BB_MFI_MFI_PERIOD)
                            if index >= config.BB_MFI_MFI_PERIOD + 1 else None)
            mfi_reversal_ok = (not config.BB_MFI_ENTRY_MFI_REVERSAL_ENABLED or
                               (previous_mfi is not None and mfi is not None and mfi >= previous_mfi + config.BB_MFI_ENTRY_MFI_REVERSAL_MIN_DELTA))
            mfi_slowdown_ok = (config.BB_MFI_ENTRY_MFI_SLOWDOWN_MAX_DROP < 0 or
                               (previous_mfi is not None and mfi is not None and mfi >= previous_mfi - config.BB_MFI_ENTRY_MFI_SLOWDOWN_MAX_DROP))
            bear_start = max(0, index - 28)
            bear_pressure = analyzer._bb_mfi_bear_pressure({"closes": closes[bear_start:index + 1], "highs": highs[bear_start:index + 1], "lows": lows[bear_start:index + 1], "volumes": volumes[bear_start:index + 1]})
            if close < lower_band and mfi is not None and mfi < config.BB_MFI_ENTRY_MFI_MAX and entry_volume_ok and dip_confirmed and mfi_reversal_ok and mfi_slowdown_ok and not bear_pressure:
                signals[index] = "buy"
            elif close > upper_band and rsi > config.BB_MFI_EXIT_RSI_MIN and mfi is not None and mfi > config.BB_MFI_EXIT_MFI_MIN:
                signals[index] = "sell"
        else:
            lower = config.BB_MFI_V1_RSI_LOWER_LEVEL if version == "v1" else config.BB_MFI_V2_RSI_LOWER_LEVEL
            upper = config.BB_MFI_V1_RSI_UPPER_LEVEL if version == "v1" else config.BB_MFI_V2_RSI_UPPER_LEVEL
            if close < lower_band and rsi > lower and entry_volume_ok and dip_confirmed:
                signals[index] = "buy"
            elif close > upper_band and rsi > upper:
                signals[index] = "sell"
    return signals


def _run_single(symbol, interval, days_back, strategy, params, order_size, stop_pct, tp_pct, trail_pct,
                start_ts=None, end_ts=None, spread_pct=0.0, slippage_pct=None, exit_profile=None,
                pyramiding_layers=3, order_pct=None, entry_filter=None):
    _validate(symbol, interval, days_back, strategy, params, order_size, stop_pct, tp_pct, trail_pct)
    # Historical candles have no bid/ask; use an explicit conservative spread
    # assumption unless a stress scenario supplies its own value.
    if spread_pct == 0.0:
        spread_pct = config.BACKTEST_ASSUMED_SPREAD_PCT
    with _CONFIG_LOCK:
        saved = {attr: getattr(config, attr) for attr in PARAM_FIELDS.values() if attr in {PARAM_FIELDS[k] for k in params}}
        saved_flags = {flag: getattr(config, flag) for flag, _, _ in STRATEGIES.values()}
        saved_tfs = {tf: getattr(config, tf) for _, tf, _ in STRATEGIES.values()}
        saved_position_layers = config.MAX_POSITION_LAYERS
        try:
            for key, attr in PARAM_FIELDS.items():
                if key in params:
                    setattr(config, attr, params[key])
            for name, (flag, tf, _) in STRATEGIES.items():
                setattr(config, flag, name == strategy)
                setattr(config, tf, interval)

            # A historical fold must fetch its own fixed endpoint; otherwise
            # older folds could accidentally read only the newest candles.
            data = _fetch_klines(symbol, interval, days_back,
                                 int(float(end_ts) * 1000) if end_ts is not None else None)
            profiles = {
                "conservative_v2": {"stages": [(0.0045, 0.25, 0.0008), (0.009, 0.25, 0.0035)], "trail_pct": 0.0055, "atr_mult": 0.8},
                "balanced_v2": {"stages": [(0.0055, 0.25, 0.0012), (0.011, 0.25, 0.0045)], "trail_pct": 0.0080, "atr_mult": 1.2},
                "runner_v2": {"stages": [(0.007, 0.15, 0.0015), (0.014, 0.15, 0.0050)], "trail_pct": 0.0100, "atr_mult": 1.4},
                "runner_a": {"stages": [(0.007, 0.20, 0.0015), (0.012, 0.20, 0.0045)], "trail_pct": 0.0140, "atr_mult": 1.4},
                "runner_b": {"stages": [(0.0085, 0.20, 0.0020), (0.016, 0.20, 0.0060)], "trail_pct": 0.0160, "atr_mult": 1.6},
                "runner_c": {"stages": [(0.007, 0.15, 0.0015), (0.014, 0.15, 0.0050)], "trail_pct": 0.0120, "atr_mult": 1.2},
                "runner_d": {"stages": [(0.010, 0.20, 0.0025), (0.020, 0.20, 0.0070)], "trail_pct": 0.0150, "atr_mult": 1.5},
                "state_based": {"stages": [(0.006, 0.20, 0.0010), (0.012, 0.20, 0.0040)], "trail_pct": 0.0090, "atr_mult": 1.0},
            }
            profile = profiles.get(str(exit_profile or "").lower())
            fixed_tv_exit = strategy == "BB_MFI_MEAN_REVERSION"
            if fixed_tv_exit:
                # Defaults mirror Pine v3, while this isolated run may use
                # an explicit user experiment without touching live config.
                config.MAX_POSITION_LAYERS = max(1, int(pyramiding_layers))
                order_pct = float(order_pct if order_pct is not None else config.ORDER_PCT)
                # UI/API defaults come from live configuration, but params are
                # applied only inside this lock and never mutate live settings.
                stop_pct = float(params.get("bb_mfi_stop_loss_pct", stop_pct if stop_pct is not None else config.BB_MFI_STOP_LOSS_PCT))
                tp_pct = float(params.get("bb_mfi_take_profit_pct", tp_pct if tp_pct is not None else config.BB_MFI_TAKE_PROFIT_PCT))
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
            use_fast_bb_mfi = fixed_tv_exit and getattr(fn, "__func__", fn) is _ORIGINAL_BB_MFI_STRATEGY
            cached_signals = _bb_mfi_signal_series(data, analyzer) if use_fast_bb_mfi else None

            def strategy_signal(index, window):
                return cached_signals[index] if cached_signals is not None else fn(window, symbol)
            entry_filter = list(entry_filter or [])
            entry_filter_stats = {"checked": 0, "allowed": 0, "blocked": 0}

            def entry_filter_allows(window):
                if not entry_filter:
                    return True
                entry_filter_stats["checked"] += 1
                allowed = _custom_conditions(analyzer, window, entry_filter)
                entry_filter_stats["allowed" if allowed else "blocked"] += 1
                return allowed

            for i, close in enumerate(data["closes"]):
                candle_time = data["times"][i]
                if start_ts is not None and candle_time < start_ts:
                    continue
                if end_ts is not None and candle_time > end_ts:
                    break
                last_eval_i = i
                high, low = data["highs"][i], data["lows"][i]
                # BB/MFI signals above are exact precomputed values. ATR and
                # the research-only filter use bounded causal lookbacks, so
                # copying the full history on every bar is unnecessary.
                window_start = max(0, i - 249) if use_fast_bb_mfi else 0
                if position:
                    window = {key: values[window_start:i + 1] for key, values in data.items()}
                    elapsed = max(0, data["times"][i] - position["entry_time"])
                    atr = analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD)
                    position["max_price"] = max(position.get("max_price", position["entry"]), high)
                    if profile:
                        peak_pct = position["max_price"] / position["entry"] - 1
                        for stage_index, (trigger, fraction, lock_pct) in enumerate(profile["stages"]):
                            if stage_index in position["stages_done"] or peak_pct < trigger or position["quantity"] <= 0:
                                continue
                            sell_qty = position["quantity"] * fraction
                            balance, partial_pnl = _close_partial(balance, position["entry"] * (1 + trigger), sell_qty, spread_pct, slippage_pct)
                            partial_pnl -= position["entry"] * sell_qty * config.COMMISSION_PCT + position["entry"] * sell_qty
                            position["realized_pnl"] = position.get("realized_pnl", 0.0) + partial_pnl
                            position["quantity"] -= sell_qty
                            position["remaining_order_size"] = position.get("invested_cost", order_size) + order_size
                            position["invested_cost"] = position["remaining_order_size"]
                            position["stop_price"] = max(position.get("stop_price", 0), position["entry"] * (1 + lock_pct))
                            position["stages_done"].add(stage_index)
                        if atr:
                            candidate = max(position["max_price"] - atr * profile["atr_mult"], position["max_price"] * (1 - profile["trail_pct"]))
                            if peak_pct >= profile["stages"][0][0]:
                                position["trailing_stop"] = max(position.get("trailing_stop", 0), candidate)
                    if atr and not fixed_tv_exit:
                        activation = atr * config.SYSTEM_ATR_TRAILING_ACTIVATION_ATR
                        if position["max_price"] - position["entry"] >= activation:
                            candidate = position["max_price"] - atr * config.SYSTEM_ATR_TRAILING_MULTIPLIER
                            position["trailing_stop"] = max(position.get("trailing_stop", 0), candidate)
                    if high >= position["target_price"]:
                        position["target_reached"] = True
                    stop_price = position.get("stop_price", 0) if fixed_tv_exit else max(position.get("stop_price", 0), position.get("trailing_stop", 0))
                    # RR hedefi bir minimum kâr eşiğidir; kapanışı ATR trailing belirler.
                    exit_price = stop_price if stop_price > 0 and low <= stop_price else None
                    reason = "fixed_stop_loss" if fixed_tv_exit else ("atr_trailing_stop" if position.get("trailing_stop", 0) and exit_price == stop_price else "system_stop_loss")
                    if fixed_tv_exit and exit_price is None and high >= position["target_price"]:
                        exit_price = position["target_price"]
                        reason = "fixed_take_profit"
                    elif fixed_tv_exit and exit_price is None and strategy_signal(i, window) == "sell" and i + 1 < len(data["opens"]):
                        # Pine's default broker model processes strategy.close
                        # from a confirmed bar at the next bar open.
                        exit_price = data["opens"][i + 1]
                        reason = "bb_mfi_v3_signal_exit"
                        exit_time_index = i + 1
                    else:
                        exit_time_index = i
                    if exit_price is None and (not fixed_tv_exit and config.STALE_POSITION_EXIT_BELOW_COST and
                          elapsed >= config.STALE_POSITION_SEC and
                          close < position["entry"] * (1 + config.min_net_exit_pct(order_size * position.get("layers", 1)))):
                        exit_price = close
                        reason = "stale_position_below_cost"
                    elif exit_price is None and config.EXIT_ON_OPPOSITE_SIGNAL and strategy_signal(i, window) == "sell":
                        exit_price = close
                        reason = "opposite_signal"
                    if exit_price is not None:
                        remaining_order_size = position.get("invested_cost", position.get("remaining_order_size", order_size * position.get("layers", 1)))
                        balance, pnl, _, trade = _close_trade(balance, position["entry"], exit_price, position["quantity"], remaining_order_size, reason, spread_pct, slippage_pct)
                        pnl += position.get("realized_pnl", 0.0)
                        trade["pnl"] = round(pnl, 8)
                        trade.update({"entry_time": position["entry_time"], "exit_time": data["times"][exit_time_index],
                                      "entry_bar": position["entry_bar"], "exit_bar": exit_time_index,
                                      "bars_held": exit_time_index - position["entry_bar"] + 1})
                        trades.append(trade); wins += pnl > 0; losses += pnl <= 0; position = None
                    elif position.get("layers", 1) < config.MAX_POSITION_LAYERS:
                        result = strategy_signal(i, window)
                        if result == "buy" and entry_filter_allows(window):
                            if i + 1 >= len(data["opens"]):
                                continue
                            # Pine percent_of_equity includes the marked value
                            # of an open layer, not just remaining cash.
                            equity_at_signal = balance + position["quantity"] * close
                            layer_order_size = (equity_at_signal * float(order_pct) if fixed_tv_exit else
                                                (balance * float(order_pct) if order_pct else order_size))
                            fee = layer_order_size * config.COMMISSION_PCT
                            if balance < layer_order_size + fee:
                                continue
                            balance -= layer_order_size + fee
                            entry_price = data["opens"][i + 1]
                            quantity = layer_order_size / entry_price
                            total_quantity = position["quantity"] + quantity
                            position["entry"] = ((position["entry"] * position["quantity"]) + (entry_price * quantity)) / total_quantity
                            position["quantity"] = total_quantity
                            position["layers"] = position.get("layers", 1) + 1
                            position["invested_cost"] = position.get("invested_cost", layer_order_size) + layer_order_size
                            position["remaining_order_size"] = position["invested_cost"]
                            atr_now = analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD) or position["entry"] * config.HARD_STOP_LOSS_PCT
                            stop_distance = (position["entry"] * float(stop_pct) if fixed_tv_exit else
                                             max(position["entry"] * config.HARD_STOP_LOSS_PCT, atr_now * config.SYSTEM_INITIAL_STOP_ATR_MULTIPLIER))
                            position["stop_price"] = position["entry"] - stop_distance
                            position["target_price"] = (position["entry"] * (1 + float(tp_pct)) if fixed_tv_exit else
                                                         position["entry"] + stop_distance * config.SYSTEM_RISK_REWARD)
                else:
                    window = {key: values[window_start:i + 1] for key, values in data.items()}
                    result = strategy_signal(i, window)
                    entry_order_size = balance * float(order_pct) if order_pct else order_size
                    if balance >= entry_order_size * (1 + config.COMMISSION_PCT) and result == "buy" and entry_filter_allows(window):
                        if i + 1 >= len(data["opens"]):
                            continue
                        entry_fee = entry_order_size * config.COMMISSION_PCT
                        balance -= entry_order_size + entry_fee
                        atr = analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD) or close * config.HARD_STOP_LOSS_PCT
                        entry_price = data["opens"][i + 1]
                        stop_distance = (entry_price * float(stop_pct) if fixed_tv_exit else
                                         max(entry_price * config.HARD_STOP_LOSS_PCT, atr * config.SYSTEM_INITIAL_STOP_ATR_MULTIPLIER))
                        position = {"entry": entry_price, "quantity": entry_order_size / entry_price,
                                    "entry_time": data["times"][i + 1], "entry_bar": i + 1, "layers": 1}
                        position["remaining_order_size"] = entry_order_size
                        position["invested_cost"] = entry_order_size
                        position["stages_done"] = set()
                        position["realized_pnl"] = 0.0
                        position["stop_price"] = entry_price - stop_distance
                        position["target_price"] = (entry_price * (1 + float(tp_pct)) if fixed_tv_exit else
                                                     entry_price + stop_distance * config.SYSTEM_RISK_REWARD)
                        position["max_price"] = entry_price
                marked = balance + (position["quantity"] * close if position else 0)
                equity_peak = max(equity_peak, marked)
                intrabar_marked = balance + (position["quantity"] * low if position else 0)
                max_drawdown = max(max_drawdown,
                                   (equity_peak - marked) / equity_peak if equity_peak else 0,
                                   (equity_peak - intrabar_marked) / equity_peak if equity_peak else 0)

            if position:
                open_at_end = True
                # Do not mark open positions to market: incomplete trades are
                # excluded from final PnL/win-rate statistics by request.
                # Restore their committed principal so it is not reported as
                # a fictitious loss merely because the position is unfinished.
                balance += float(position.get("invested_cost", position.get("remaining_order_size", order_size * position.get("layers", 1))))
                unrealized_pnl = 0.0

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
                    "exit_model": "pine_v3_signal_or_fixed_stop_take_profit" if fixed_tv_exit else "atr_trailing_after_rr_target",
                    "fill_model": "next_bar_open_entry_executable_exit",
                    "strategy_contract": ({"source": "Flawless Victory Strategy v3", "entry": "close < BB(20,1.0) lower and MFI(14) < 60", "signal_exit": "RSI(14) > 65 and MFI(14) > 64", "stop_loss_pct": 0.08882, "take_profit_pct": 0.02317, "order_pct_of_equity": 0.10, "pyramiding": 2} if fixed_tv_exit else None),
                    "spread_pct": spread_pct, "slippage_pct": config.ESTIMATED_SLIPPAGE_PCT if slippage_pct is None else slippage_pct,
                    "data_quality": _data_quality(data, interval),
                    "open_position_at_end": open_at_end, "unrealized_pnl": round(unrealized_pnl, 8),
                    "trades": trades, "timestamp": time.time(),
                    "evaluation_start": start_ts, "evaluation_end": end_ts, "exit_profile": exit_profile or "default",
                    "entry_filter": entry_filter, "entry_filter_stats": entry_filter_stats,
                    "entry_filter_history_bars": 250 if use_fast_bb_mfi and entry_filter else None}
        finally:
            for attr, value in {**saved, **saved_flags, **saved_tfs, "MAX_POSITION_LAYERS": saved_position_layers}.items():
                setattr(config, attr, value)


async def run_backtest(symbol: str, interval: str, days_back: int, strategy: str, params: dict | None = None,
                       order_size: float = 500.0, stop_pct: float = 0.005, tp_pct: float = 0.015,
                       trail_pct: float = 0.003, exit_profile: str | None = None,
                       pyramiding_layers: int = 3, order_pct: float | None = None) -> tuple[int, dict[str, Any]]:
    params = params or {}
    result = await asyncio.to_thread(_run_single, symbol, interval, days_back, strategy, params,
                                     order_size, stop_pct, tp_pct, trail_pct, None, None, 0.0, None, exit_profile, pyramiding_layers, order_pct)
    return await database.save_backtest(result), result


async def run_filtered_backtest(symbol: str, interval: str, days_back: int, strategy: str,
                                entry_filter: list[dict], params: dict | None = None,
                                order_size: float = 500.0, stop_pct: float = 0.005,
                                tp_pct: float = 0.015, spread_pct: float = 0.0,
                                slippage_pct: float | None = None,
                                pyramiding_layers: int = 3, order_pct: float | None = None):
    """Paper-only replay of an existing strategy with a causal entry filter."""
    return await asyncio.to_thread(
        _run_single, symbol, interval, days_back, strategy, params or {}, order_size,
        stop_pct, tp_pct, 0.0, None, None, spread_pct, slippage_pct, None,
        pyramiding_layers, order_pct, entry_filter)


async def run_walk_forward(symbol: str, interval: str, strategy: str,
                           train_days: int = 30, test_days: int = 7,
                           folds: int = 3, order_size: float = 500.0,
                           stop_pct: float = 0.005, tp_pct: float = 0.015,
                           params: dict | None = None, pyramiding_layers: int = 3,
                           order_pct: float | None = None):
    """Chronological OOS folds for classic system strategies only.

    LLM_PAPER cannot be replayed here because historical LLM decisions/plans
    are not reconstructed candle-by-candle. Its exact exit model belongs to
    run_custom_backtest with explicit TP/SL and exit conditions.

    ``train_days`` supplies pre-fold indicator/warm-up context. This function
    does not fit or select parameters, so the result must not imply training.
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
            _run_single, symbol, interval, train_days + test_days, strategy, params or {},
            order_size, stop_pct, tp_pct, 0.0, start_ts, end_ts, 0.0, None, None,
            pyramiding_layers, order_pct)
        result["fold"] = fold + 1
        results.append(result)
    pnl = [float(row.get("net_pnl") or 0) for row in results]
    positive_folds = sum(value > 0 for value in pnl)
    total_pnl = sum(pnl)
    total_trades = sum(max(0, int(row.get("total_trades") or 0)) for row in results)
    minimum_folds = 3
    minimum_trades = 30
    majority_required = len(results) // 2 + 1
    validation_reasons = []
    if len(results) < minimum_folds:
        validation_reasons.append("insufficient_folds")
    if total_trades < minimum_trades:
        validation_reasons.append("insufficient_trades")
    if positive_folds < majority_required:
        validation_reasons.append("insufficient_positive_fold_majority")
    if total_pnl <= 0:
        validation_reasons.append("non_positive_total_net_pnl")
    oos_consistent = not validation_reasons
    return {"symbol": symbol, "interval": interval, "strategy": strategy,
            "method": "chronological_oos_folds_without_parameter_training", "train_days": train_days,
            "warmup_context_days": train_days, "training_performed": False,
            "parameter_selection": "none",
            "test_days": test_days, "folds": len(results),
            "positive_oos_folds": positive_folds,
            "minimum_required_folds": minimum_folds,
            "minimum_required_trades": minimum_trades,
            "total_oos_trades": total_trades,
            "data_sufficient": len(results) >= minimum_folds and total_trades >= minimum_trades,
            "oos_consistent": oos_consistent,
            "validation_status": "PASS" if oos_consistent else "FAIL",
            "validation_reasons": validation_reasons,
            "net_pnl": round(total_pnl, 2),
            "average_fold_pnl": round(sum(pnl) / len(pnl), 2) if pnl else 0.0,
            "fold_results": results, "paper_only": True,
            "warning": "Bu değerlendirme parametre eğitimi/optimizasyonu yapmaz; train_days yalnız gösterge geçmişi sağlar. OOS sonucu kârlılık garantisi değildir; maliyet varsayımları ve örneklem büyüklüğü ayrıca incelenmelidir."}


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
