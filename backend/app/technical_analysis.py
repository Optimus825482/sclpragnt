import math
import numpy as np


def _ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    value = float(np.mean(values[:period]))
    for item in values[period:]:
        value = alpha * float(item) + (1 - alpha) * value
    return value


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = np.mean(np.maximum(changes, 0)); losses = np.mean(np.maximum(-changes, 0))
    if losses == 0: return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses)))


def _atr(highs, lows, closes, period=14):
    if len(closes) < period + 1: return None
    h, l, prev = np.asarray(highs[-period:], float), np.asarray(lows[-period:], float), np.asarray(closes[-period-1:-1], float)
    return float(np.mean(np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))))


def calculate_snapshot(symbol, price, klines, orderflow=None, ticker_24h=0, order_value=500):
    """Calculate explainable, public-OHLCV technical context for one symbol."""
    flow = orderflow or {}; result = {"symbol": symbol, "price": price, "timeframes": {}, "data_ready": False}
    primary = klines.get("5m", {})
    closes = primary.get("closes", []); highs = primary.get("highs", []); lows = primary.get("lows", []); volumes = primary.get("volumes", [])
    if len(closes) < 55: return result
    def ret(n): return float(closes[-1] / closes[-n-1] - 1) if len(closes) > n else None
    ema9, ema21, ema50 = _ema(closes, 9), _ema(closes, 21), _ema(closes, 50)
    atr = _atr(highs, lows, closes)
    daily = klines.get("1d", {}); dclose, dhigh, dlow = daily.get("closes", []), daily.get("highs", []), daily.get("lows", [])
    adr = None
    if len(dclose) >= 15:
        ranges = [(h-l)/c for h,l,c in zip(dhigh[-15:-1], dlow[-15:-1], dclose[-15:-1]) if c]
        adr = float(np.mean(ranges)) if ranges else None
    vavg = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else None
    spread = flow.get("spread_pct"); depth = ((flow.get("bid_qty", 0) or 0) + (flow.get("ask_qty", 0) or 0)) * price
    result.update({"data_ready": True, "trend": {"ema_9": ema9, "ema_21": ema21, "ema_50": ema50, "alignment": "bullish" if ema9 and ema21 and ema50 and ema9 > ema21 > ema50 else "bearish" if ema9 and ema21 and ema50 and ema9 < ema21 < ema50 else "mixed"}, "momentum": {"return_5m": ret(1), "return_15m": ret(3), "return_1h": ret(12), "rsi_14": _rsi(closes), "roc_21": ret(21)}, "volatility": {"atr_14": atr, "atr_pct": atr / price if atr and price else None, "adr_14_pct": adr, "day_range_used_pct": None, "adr_utilization": None, "remaining_capacity_pct": None}, "volume": {"volume_ratio_20": volumes[-1] / vavg if vavg else None, "vwap": float(np.sum(((np.array(highs[-20:]) + np.array(lows[-20:]) + np.array(closes[-20:])) / 3) * np.array(volumes[-20:])) / np.sum(volumes[-20:])) if len(volumes) >= 20 and np.sum(volumes[-20:]) else None}, "liquidity": {"quote_volume_24h": ticker_24h, "spread_pct": spread, "orderbook_depth_try": depth, "depth_multiplier": depth / order_value if order_value else None, "orderflow_imbalance": ((flow.get("bid_qty", 0) - flow.get("ask_qty", 0)) / (flow.get("bid_qty", 0) + flow.get("ask_qty", 0))) if (flow.get("bid_qty", 0) + flow.get("ask_qty", 0)) else None}})
    if adr and len(dclose) and dclose[-1]:
        day_open = daily.get("opens", [])[-1] if daily.get("opens") else dclose[-1]
        used = max(price, day_open) / min(price, day_open) - 1 if price > 0 and day_open > 0 else 0
        result["volatility"].update({"day_range_used_pct": used, "adr_utilization": used / adr, "remaining_capacity_pct": adr - used})
    result["summary"] = "bullish" if result["trend"]["alignment"] == "bullish" and (result["momentum"]["rsi_14"] or 0) >= 50 else "mixed"
    return result
