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

def _macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal: return None
    line = _ema(closes, fast) - _ema(closes, slow)
    values = []
    for i in range(slow, len(closes) + 1):
        values.append(_ema(closes[:i], fast) - _ema(closes[:i], slow))
    sig = _ema(values, signal)
    return {"line": float(line), "signal": float(sig), "histogram": float(line - sig)} if sig is not None else None

def _bollinger(closes, period=20, std_mult=2.0):
    if len(closes) < period: return None
    window = np.asarray(closes[-period:], dtype=float); mid = float(np.mean(window)); std = float(np.std(window))
    upper, lower = mid + std_mult * std, mid - std_mult * std
    return {"upper": upper, "middle": mid, "lower": lower, "width_pct": (upper - lower) / mid if mid else None, "position": (closes[-1] - lower) / (upper - lower) if upper != lower else None}

def _stochastic(highs, lows, closes, period=14, smooth=3):
    if len(closes) < period + smooth - 1: return None
    values = []
    for i in range(period - 1, len(closes)):
        hi, lo = max(highs[i-period+1:i+1]), min(lows[i-period+1:i+1])
        values.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k = float(np.mean(values[-smooth:])); d = float(np.mean(values[-smooth*2:-smooth] if len(values) >= smooth*2 else values[-smooth:]))
    return {"k": k, "d": d}

def _obv(closes, volumes):
    if len(closes) < 2: return None
    obv = 0.0
    values = []
    for i in range(1, len(closes)):
        obv += volumes[i] if closes[i] > closes[i-1] else -volumes[i] if closes[i] < closes[i-1] else 0
        values.append(obv)
    return {"value": float(obv), "slope": float(obv - values[-min(5, len(values))]) if values else 0.0}

def _mfi(highs, lows, closes, volumes, period=14):
    if len(closes) < period + 1: return None
    typical = (np.asarray(highs) + np.asarray(lows) + np.asarray(closes)) / 3
    flow = typical * np.asarray(volumes)
    pos = neg = 0.0
    for i in range(-period + 1, 0):
        if typical[i] > typical[i-1]: pos += flow[i]
        elif typical[i] < typical[i-1]: neg += flow[i]
    return float(100 - (100 / (1 + pos / neg))) if neg else 100.0

def _adx(highs, lows, closes, period=14):
    if len(closes) < period * 2 + 1: return None
    tr, plus, minus = [], [], []
    for i in range(1, len(closes)):
        tr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
        up, down = highs[i]-highs[i-1], lows[i-1]-lows[i]
        plus.append(up if up > down and up > 0 else 0.0); minus.append(down if down > up and down > 0 else 0.0)
    atr = np.mean(tr[-period:]); pdi = 100*np.mean(plus[-period:])/atr if atr else 0; mdi = 100*np.mean(minus[-period:])/atr if atr else 0
    dx = 100*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi else 0
    return {"adx": float(dx), "plus_di": float(pdi), "minus_di": float(mdi)}

def _sma(values, period):
    return float(np.mean(values[-period:])) if len(values) >= period else None

def _cci(highs, lows, closes, period=20):
    if len(closes) < period: return None
    typical = (np.asarray(highs[-period:]) + np.asarray(lows[-period:]) + np.asarray(closes[-period:])) / 3
    mean = float(np.mean(typical)); deviation = float(np.mean(np.abs(typical - mean)))
    return float((typical[-1] - mean) / (0.015 * deviation)) if deviation else 0.0

def _awesome_oscillator(highs, lows, fast=5, slow=34):
    median = ((np.asarray(highs) + np.asarray(lows)) / 2).tolist()
    fast_value, slow_value = _sma(median, fast), _sma(median, slow)
    return float(fast_value - slow_value) if fast_value is not None and slow_value is not None else None

def _williams_r(highs, lows, closes, period=14):
    if len(closes) < period: return None
    hi, lo = max(highs[-period:]), min(lows[-period:])
    return float((hi - closes[-1]) / (hi - lo) * -100) if hi != lo else -50.0

def _bull_bear_power(highs, lows, closes, period=13):
    ema = _ema(closes, period)
    return {"bull": float(highs[-1] - ema), "bear": float(lows[-1] - ema)} if ema is not None else None

def _ultimate_oscillator(highs, lows, closes, periods=(7, 14, 28)):
    if len(closes) < max(periods) + 1: return None
    bp, tr = [], []
    for i in range(1, len(closes)):
        bp.append(closes[i] - min(lows[i], closes[i-1]))
        tr.append(max(highs[i], closes[i-1]) - min(lows[i], closes[i-1]))
    averages = [sum(bp[-p:]) / sum(tr[-p:]) if sum(tr[-p:]) else 0.5 for p in periods]
    return float(100 * (4 * averages[0] + 2 * averages[1] + averages[2]) / 7)

def _signal(value, buy, strong_buy, sell, strong_sell):
    if value is None: return "unknown"
    if value >= strong_buy: return "strong_buy"
    if value >= buy: return "buy"
    if value <= strong_sell: return "strong_sell"
    if value <= sell: return "sell"
    return "neutral"

def _pivots(high, low, close):
    p = (high + low + close) / 3
    return {"R3": 2*p - 2*low, "R2": p + (high-low), "R1": 2*p-low, "P": p,
            "S1": 2*p-high, "S2": p-(high-low), "S3": 2*p-2*high,
            "F_R3": p + 1.0*(high-low), "F_R2": p + 0.618*(high-low), "F_R1": p + 0.382*(high-low),
            "F_S1": p - 0.382*(high-low), "F_S2": p - 0.618*(high-low), "F_S3": p - 1.0*(high-low)}

def _candlestick_patterns(opens, highs, lows, closes):
    if len(closes) < 3: return []
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    po, pc = opens[-2], closes[-2]
    body, rng = abs(c-o), max(h-l, 1e-12)
    patterns = []
    if body / rng <= 0.1: patterns.append("doji")
    if min(o,c)-l > body*2 and h-max(o,c) < body: patterns.append("hammer")
    if max(o,c)-l < body and h-min(o,c) > body*2: patterns.append("shooting_star")
    if pc < po and c > o and c >= po and o <= pc: patterns.append("bullish_engulfing")
    if pc > po and c < o and c <= po and o >= pc: patterns.append("bearish_engulfing")
    if not patterns: patterns.append("none")
    return patterns


def calculate_snapshot(symbol, price, klines, orderflow=None, ticker_24h=0, order_value=500, primary_timeframe="5m"):
    """Calculate explainable, public-OHLCV technical context for one symbol."""
    flow = orderflow or {}; result = {"symbol": symbol, "price": price, "timeframes": {}, "data_ready": False}
    primary = klines.get(primary_timeframe, {})
    opens = primary.get("opens", []); closes = primary.get("closes", []); highs = primary.get("highs", []); lows = primary.get("lows", []); volumes = primary.get("volumes", [])
    result["timeframes"] = {primary_timeframe: {"candles": len(closes), "required": 55}}
    if len(closes) < 55:
        result["error"] = f"{primary_timeframe} timeframe için {len(closes)}/55 mum hazır"
        return result
    def ret(n): return float(closes[-1] / closes[-n-1] - 1) if len(closes) > n else None
    ema9, ema21, ema50, ema20 = _ema(closes, 9), _ema(closes, 21), _ema(closes, 50), _ema(closes, 20)
    atr = _atr(highs, lows, closes)
    macd = _macd(closes); bollinger = _bollinger(closes); stochastic = _stochastic(highs, lows, closes)
    adx = _adx(highs, lows, closes); obv = _obv(closes, volumes); mfi = _mfi(highs, lows, closes, volumes)
    cci = _cci(highs, lows, closes); ao = _awesome_oscillator(highs, lows); williams = _williams_r(highs, lows, closes)
    bull_bear = _bull_bear_power(highs, lows, closes); ultimate = _ultimate_oscillator(highs, lows, closes)
    moving_averages = {}
    for period in (10, 20, 30, 50, 100, 200):
        moving_averages[f"ema_{period}"] = _ema(closes, period)
        moving_averages[f"sma_{period}"] = _sma(closes, period)
    moving_averages["ichimoku_base"] = (max(highs[-26:]) + min(lows[-26:])) / 2 if len(closes) >= 26 else None
    moving_averages["vwma_20"] = float(np.sum(np.asarray(closes[-20:]) * np.asarray(volumes[-20:])) / np.sum(volumes[-20:])) if len(closes) >= 20 and np.sum(volumes[-20:]) else None
    moving_averages["hma_9"] = _sma(closes[-9:], 9)
    oscillator_values = {"rsi_14": _rsi(closes), "stochastic_k": stochastic.get("k") if stochastic else None, "cci_20": cci, "adx_14": adx.get("adx") if adx else None, "awesome": ao, "momentum_10": ret(10), "macd_histogram": macd.get("histogram") if macd else None, "stoch_rsi_fast": None, "williams_r": williams, "bull_bear": bull_bear.get("bull") if bull_bear else None, "ultimate": ultimate}
    oscillator_signals = {"rsi_14": _signal(oscillator_values["rsi_14"], 50, 70, 30, 20), "stochastic_k": _signal(oscillator_values["stochastic_k"], 50, 80, 20, 10), "cci_20": _signal(cci, 0, 100, -100, -200), "adx_14": "neutral" if adx is None else ("buy" if adx["plus_di"] > adx["minus_di"] else "sell"), "awesome": "buy" if (ao or 0) > 0 else "sell", "momentum_10": "buy" if (ret(10) or 0) > 0 else "sell", "macd": "buy" if macd and macd["histogram"] > 0 else "sell", "williams_r": _signal(None if williams is None else williams, -80, -20, -20, -5), "ultimate": _signal(ultimate, 50, 70, 30, 20)}
    daily = klines.get("1d", {}); dclose, dhigh, dlow = daily.get("closes", []), daily.get("highs", []), daily.get("lows", [])
    adr = None
    if len(dclose) >= 15:
        ranges = [(h-l)/c for h,l,c in zip(dhigh[-15:-1], dlow[-15:-1], dclose[-15:-1]) if c]
        adr = float(np.mean(ranges)) if ranges else None
    vavg = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else None
    spread = flow.get("spread_pct"); depth = ((flow.get("bid_qty", 0) or 0) + (flow.get("ask_qty", 0) or 0)) * price
    alignment = "bullish" if ema9 and ema21 and ema50 and ema9 > ema21 > ema50 else "bearish" if ema9 and ema21 and ema50 and ema9 < ema21 < ema50 else "mixed"
    result.update({"timeframe": primary_timeframe, "data_ready": True, "trend": {"ema_9": ema9, "ema_21": ema21, "ema_50": ema50, "alignment": alignment, "adx": adx}, "momentum": {"return_5m": ret(1), "return_15m": ret(3), "return_1h": ret(12), "rsi_14": _rsi(closes), "roc_21": ret(21), "macd": macd, "stochastic": stochastic, "mfi_14": mfi}, "oscillators": {"values": oscillator_values, "signals": oscillator_signals}, "moving_averages": moving_averages, "candlestick_patterns": _candlestick_patterns(opens, highs, lows, closes), "channels": {"bollinger": bollinger, "donchian": {"upper": max(highs[-20:]), "middle": _sma(closes, 20), "lower": min(lows[-20:])} if len(closes) >= 20 else None, "keltner": {"middle": ema20, "upper": ema20 + 2*atr if ema20 and atr else None, "lower": ema20 - 2*atr if ema20 and atr else None}}, "volatility": {"atr_14": atr, "atr_pct": atr / price if atr and price else None, "adr_14_pct": adr, "bollinger": bollinger, "day_range_used_pct": None, "adr_utilization": None, "remaining_capacity_pct": None}, "volume": {"volume_ratio_20": volumes[-1] / vavg if vavg else None, "vwap": float(np.sum(((np.array(highs[-20:]) + np.array(lows[-20:]) + np.array(closes[-20:])) / 3) * np.array(volumes[-20:])) / np.sum(volumes[-20:])) if len(volumes) >= 20 and np.sum(volumes[-20:]) else None, "obv": obv}, "pivots": _pivots(dhigh[-1], dlow[-1], dclose[-1]) if len(dclose) else None, "liquidity": {"quote_volume_24h": ticker_24h, "spread_pct": spread, "orderbook_depth_try": depth, "depth_multiplier": depth / order_value if order_value else None, "orderflow_imbalance": ((flow.get("bid_qty", 0) - flow.get("ask_qty", 0)) / (flow.get("bid_qty", 0) + flow.get("ask_qty", 0))) if (flow.get("bid_qty", 0) + flow.get("ask_qty", 0)) else None, "source": flow.get("source", "binance_tr_public_websocket"), "updated_at": flow.get("updated_at")}})
    if adr and len(dclose) and dclose[-1]:
        day_open = daily.get("opens", [])[-1] if daily.get("opens") else dclose[-1]
        used = max(price, day_open) / min(price, day_open) - 1 if price > 0 and day_open > 0 else 0
        result["volatility"].update({"day_range_used_pct": used, "adr_utilization": used / adr, "remaining_capacity_pct": adr - used})
    result["summary"] = "bullish" if result["trend"]["alignment"] == "bullish" and (result["momentum"]["rsi_14"] or 0) >= 50 else "mixed"
    return result
