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

def _stoch_rsi(closes, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    if len(closes) < rsi_period + stoch_period + k_period + d_period:
        return None
    values = [_rsi(closes[:end], rsi_period) for end in range(rsi_period + 1, len(closes) + 1)]
    raw = []
    for i in range(stoch_period - 1, len(values)):
        window = values[i - stoch_period + 1:i + 1]; lo, hi = min(window), max(window)
        raw.append((values[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    if len(raw) < k_period + d_period - 1: return None
    k_values = [float(np.mean(raw[i-k_period+1:i+1])) for i in range(k_period - 1, len(raw))]
    return {"k": k_values[-1], "d": float(np.mean(k_values[-d_period:]))}

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

def _methodology_analysis(opens, highs, lows, closes, volumes, adx=None, alignment="mixed"):
    """Deterministic, explainable methodology layer; never uses future candles."""
    if len(closes) < 55:
        return {"regime": {"name": "unknown", "confidence": 0.0}, "elliott": {"structure": "insufficient_data", "confidence": 0.0}, "wyckoff": {"phase": "unknown", "confidence": 0.0}, "turtle": {"breakout": "none"}, "fibonacci": {"0.236": None, "0.786": None}, "confluence": {"score": 0.0, "label": "unknown", "components": {"trend": 0.0, "turtle": 0.0, "wyckoff": 0.0, "elliott": 0.0}}, "methodology_version": "methodology-v1"}
    price = float(closes[-1]); atr = _atr(highs, lows, closes, 14) or 0.0
    atr_pct = atr / price if price else 0.0
    adx_value = float((adx or {}).get("adx") or 0.0); plus = float((adx or {}).get("plus_di") or 0.0); minus = float((adx or {}).get("minus_di") or 0.0)
    volume_avg = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else 0.0
    volume_ratio = float(volumes[-1] / volume_avg) if volume_avg else None
    recent_return = closes[-1] / closes[-21] - 1 if len(closes) >= 22 and closes[-21] else 0.0
    vol_change = (np.std(np.diff(np.log(np.asarray(closes[-30:], dtype=float)))) if len(closes) >= 30 else 0.0)
    if abs(recent_return) > max(atr_pct * 8, 0.03) and atr_pct > 0.01:
        regime_name = "bull_volatile" if recent_return > 0 else "bear_volatile"
    elif adx_value >= 25 and plus > minus:
        regime_name = "bull_quiet"
    elif adx_value >= 25 and minus > plus:
        regime_name = "bear_quiet"
    elif volume_ratio is not None and volume_ratio > 1.8 and abs(recent_return) < max(atr_pct * 2, 0.01):
        regime_name = "distribution" if price >= max(closes[-55:]) * 0.96 else "accumulation"
    else:
        regime_name = "range_transition"
    regime_confidence = min(0.95, max(0.35, 0.45 + min(adx_value, 50) / 100 + (0.1 if volume_ratio and volume_ratio > 1.2 else 0)))
    fib_high, fib_low = max(highs[-55:]), min(lows[-55:]); span = fib_high - fib_low
    fib = {"0.236": fib_high - span * 0.236, "0.382": fib_high - span * 0.382, "0.5": fib_high - span * 0.5, "0.618": fib_high - span * 0.618, "0.786": fib_high - span * 0.786, "swing_high": fib_high, "swing_low": fib_low}
    turtle = {"entry_high_20": max(highs[-21:-1]), "entry_low_20": min(lows[-21:-1]), "exit_high_10": max(highs[-11:-1]), "exit_low_10": min(lows[-11:-1]), "entry_high_55": max(highs[-56:-1]), "entry_low_55": min(lows[-56:-1])}
    turtle["breakout"] = "up_20" if price > turtle["entry_high_20"] else "down_20" if price < turtle["entry_low_20"] else "none"
    body = abs(closes[-1] - opens[-1]); range_value = max(highs[-1] - lows[-1], 1e-12); close_location = (closes[-1] - lows[-1]) / range_value
    effort = (volume_ratio or 1.0); wyckoff_event = "none"
    if price <= fib_high - span * 0.786 and close_location > 0.7 and effort > 1.2: wyckoff_event = "spring_candidate"
    elif price >= fib_low + span * 0.786 and close_location < 0.3 and effort > 1.2: wyckoff_event = "upthrust_candidate"
    elif turtle["breakout"] == "up_20" and effort > 1.2: wyckoff_event = "sign_of_strength_candidate"
    elif turtle["breakout"] == "down_20" and effort > 1.2: wyckoff_event = "sign_of_weakness_candidate"
    wyckoff = {"phase": "accumulation" if regime_name == "accumulation" else "distribution" if regime_name == "distribution" else "unknown", "event": wyckoff_event, "volume_confirmation": bool(volume_ratio and volume_ratio >= 1.2), "confidence": min(0.9, 0.4 + (0.2 if wyckoff_event != "none" else 0) + (0.15 if volume_ratio and volume_ratio > 1.2 else 0))}
    swing_up = sum(1 for i in range(max(1, len(closes)-8), len(closes)) if closes[i] > closes[i-1]); swing_down = 8 - swing_up
    elliott_structure = "impulse_candidate" if swing_up >= 6 or swing_down >= 6 else "correction_or_range"
    elliott = {"structure": elliott_structure, "wave_hint": "possible_wave_3" if swing_up >= 6 else "possible_wave_c" if swing_down >= 6 else "unconfirmed", "confidence": round(min(0.7, 0.35 + abs(swing_up - swing_down) * 0.05), 3), "confirmed": False}
    trend_score = 0.8 if alignment == "bullish" else 0.2 if alignment == "bearish" else 0.5
    turtle_score = 0.9 if turtle["breakout"] == "up_20" else 0.1 if turtle["breakout"] == "down_20" else 0.5
    wyckoff_score = 0.75 if wyckoff_event in {"spring_candidate", "sign_of_strength_candidate"} else 0.25 if wyckoff_event in {"upthrust_candidate", "sign_of_weakness_candidate"} else 0.5
    score = round(0.25 * trend_score + 0.15 * min(1, adx_value / 40) + 0.15 * min(1, (volume_ratio or 0) / 2) + 0.15 * turtle_score + 0.15 * wyckoff_score + 0.10 * elliott["confidence"] + 0.05 * (1 if regime_name in {"bull_quiet", "accumulation"} else 0.5), 4)
    return {"regime": {"name": regime_name, "confidence": round(regime_confidence, 3), "method": "deterministic_v1", "atr_pct": atr_pct, "volatility_change": vol_change}, "elliott": elliott, "wyckoff": wyckoff, "fibonacci": fib, "turtle": turtle, "confluence": {"score": score, "label": "high" if score >= 0.7 else "moderate" if score >= 0.4 else "low", "components": {"trend": trend_score, "turtle": turtle_score, "wyckoff": wyckoff_score, "elliott": elliott["confidence"]}}, "methodology_version": "methodology-v1"}

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
    # Strong, common multi-candle confirmations. These are deliberately
    # conservative and require body/range relationships rather than names
    # inferred from a single candle.
    avg_body = float(np.mean([abs(closes[i]-opens[i]) for i in range(max(0, len(closes)-20), len(closes))])) or 1e-12
    if len(closes) >= 3:
        a,b = len(closes)-3, len(closes)-2
        if closes[a] < opens[a] and abs(closes[b]-opens[b]) <= avg_body*.6 and closes[-1] > opens[-1] and closes[-1] > (opens[a]+closes[a])/2: patterns.append("morning_star")
        if closes[a] > opens[a] and abs(closes[b]-opens[b]) <= avg_body*.6 and closes[-1] < opens[-1] and closes[-1] < (opens[a]+closes[a])/2: patterns.append("evening_star")
    if len(closes) >= 4:
        last4 = range(len(closes)-4, len(closes)-1)
        if all(closes[i] > opens[i] and closes[i] > closes[i-1] for i in last4): patterns.append("three_white_soldiers")
        if all(closes[i] < opens[i] and closes[i] < closes[i-1] for i in last4): patterns.append("three_black_crows")
    if len(closes) >= 2:
        prev_mid = (opens[-2]+closes[-2])/2
        if closes[-2] < opens[-2] and opens[-1] <= closes[-2] and closes[-1] > prev_mid: patterns.append("piercing_line")
        if closes[-2] > opens[-2] and opens[-1] >= closes[-2] and closes[-1] < prev_mid: patterns.append("dark_cloud_cover")
        if closes[-2] < opens[-2] and abs(closes[-1]-opens[-1]) < abs(closes[-2]-opens[-2])*.6 and min(opens[-1],closes[-1]) > min(opens[-2],closes[-2]) and max(opens[-1],closes[-1]) < max(opens[-2],closes[-2]): patterns.append("bullish_harami")
        if closes[-2] > opens[-2] and abs(closes[-1]-opens[-1]) < abs(closes[-2]-opens[-2])*.6 and min(opens[-1],closes[-1]) > min(opens[-2],closes[-2]) and max(opens[-1],closes[-1]) < max(opens[-2],closes[-2]): patterns.append("bearish_harami")
        if abs(highs[-1]-highs[-2]) <= max(highs[-1], highs[-2])*.001: patterns.append("tweezer_top")
        if abs(lows[-1]-lows[-2]) <= max(lows[-1], lows[-2])*.001: patterns.append("tweezer_bottom")
    if not patterns: patterns.append("none")
    return patterns

def _price_action_setup(opens, highs, lows, closes):
    """Conservative, non-repainting price-action labels from closed candles."""
    if len(closes) < 4:
        return {"setup": "none", "direction": "neutral", "confirmed": False, "reason": "insufficient_data"}
    i = len(closes) - 2  # exclude the currently forming candle
    o, h, l, c = map(float, (opens[i], highs[i], lows[i], closes[i]))
    rng = max(h - l, 1e-12); body = abs(c - o)
    upper = h - max(o, c); lower = min(o, c) - l
    direction = "bullish" if c > o else "bearish" if c < o else "neutral"
    setup = "none"; reason = "no_confirmed_setup"
    if lower >= body * 2 and lower >= upper * 1.5 and c >= l + rng * .6:
        setup, reason = "bullish_pin_bar", "closed candle rejected lower prices"
    elif upper >= body * 2 and upper >= lower * 1.5 and c <= l + rng * .4:
        setup, direction, reason = "bearish_pin_bar", "bearish", "closed candle rejected higher prices"
    mother_range = highs[i-1] - lows[i-1]
    inside = highs[i] < highs[i-1] and lows[i] > lows[i-1] if mother_range > 0 else False
    if inside:
        setup, reason = "inside_bar", "closed candle compressed inside the prior candle"
    # Fakey: prior inside bar, then the confirmed candle breaks and closes back
    # inside the mother range. This is a setup label, not an entry signal.
    if i >= 2 and highs[i-1] < highs[i-2] and lows[i-1] > lows[i-2]:
        if highs[i] > highs[i-2] and c < highs[i-2]:
            setup, direction, reason = "bearish_fakey", "bearish", "false upside break returned below mother high"
        elif lows[i] < lows[i-2] and c > lows[i-2]:
            setup, direction, reason = "bullish_fakey", "bullish", "false downside break returned above mother low"
    return {"setup": setup, "direction": direction, "confirmed": setup != "none",
            "candle_index": i, "entry_confirmation_required": setup != "none", "reason": reason,
            "data_policy": "confirmed candle only; no future bars"}

CANDLESTICK_PATTERN_INFO = {
    "bullish_engulfing": {"direction": "bullish", "strength": "strong", "tr": "Güçlü boğa yutan formasyonu; alıcı baskısında artış."},
    "bearish_engulfing": {"direction": "bearish", "strength": "strong", "tr": "Güçlü ayı yutan formasyonu; satıcı baskısında artış."},
    "morning_star": {"direction": "bullish", "strength": "strong", "tr": "Üç mumlu boğa dönüşü; düşüş momentumunun zayıfladığına işaret eder."},
    "evening_star": {"direction": "bearish", "strength": "strong", "tr": "Üç mumlu ayı dönüşü; yükseliş momentumunun zayıfladığına işaret eder."},
    "three_white_soldiers": {"direction": "bullish", "strength": "strong", "tr": "Üç beyaz asker; ardışık güçlü alıcı devamlılığı."},
    "three_black_crows": {"direction": "bearish", "strength": "strong", "tr": "Üç siyah karga; ardışık güçlü satıcı devamlılığı."},
    "piercing_line": {"direction": "bullish", "strength": "medium", "tr": "Delici çizgi; düşüş sonrası boğa toparlanması."},
    "dark_cloud_cover": {"direction": "bearish", "strength": "medium", "tr": "Kara bulut örtüsü; yükseliş sonrası satıcı baskısı."},
    "bullish_harami": {"direction": "bullish", "strength": "medium", "tr": "Boğa haramisi; düşüş momentumunda yavaşlama."},
    "bearish_harami": {"direction": "bearish", "strength": "medium", "tr": "Ayı haramisi; yükseliş momentumunda yavaşlama."},
    "tweezer_top": {"direction": "bearish", "strength": "medium", "tr": "Cımbız tepe; dirençte başarısızlık işareti."},
    "tweezer_bottom": {"direction": "bullish", "strength": "medium", "tr": "Cımbız dip; destekte tepki işareti."},
}


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
    macd = _macd(closes); bollinger = _bollinger(closes); stochastic = _stochastic(highs, lows, closes); stoch_rsi = _stoch_rsi(closes)
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
    oscillator_values = {"rsi_14": _rsi(closes), "stochastic_k": stochastic.get("k") if stochastic else None, "cci_20": cci, "adx_14": adx.get("adx") if adx else None, "awesome": ao, "momentum_10": ret(10), "macd_histogram": macd.get("histogram") if macd else None, "stoch_rsi_fast": stoch_rsi.get("k") if stoch_rsi else None, "stoch_rsi_signal": stoch_rsi.get("d") if stoch_rsi else None, "williams_r": williams, "bull_bear": bull_bear.get("bull") if bull_bear else None, "ultimate": ultimate}
    oscillator_signals = {"rsi_14": _signal(oscillator_values["rsi_14"], 50, 70, 30, 20), "stochastic_k": _signal(oscillator_values["stochastic_k"], 50, 80, 20, 10), "cci_20": _signal(cci, 0, 100, -100, -200), "adx_14": "neutral" if adx is None else ("buy" if adx["plus_di"] > adx["minus_di"] else "sell"), "awesome": "buy" if (ao or 0) > 0 else "sell", "momentum_10": "buy" if (ret(10) or 0) > 0 else "sell", "macd": "buy" if macd and macd["histogram"] > 0 else "sell", "williams_r": _signal(None if williams is None else williams, -80, -20, -20, -5), "ultimate": _signal(ultimate, 50, 70, 30, 20)}
    daily = klines.get("1d", {}); dclose, dhigh, dlow = daily.get("closes", []), daily.get("highs", []), daily.get("lows", [])
    adr = None
    if len(dclose) >= 15:
        ranges = [(h-l)/c for h,l,c in zip(dhigh[-15:-1], dlow[-15:-1], dclose[-15:-1]) if c]
        adr = float(np.mean(ranges)) if ranges else None
    vavg = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else None
    spread = flow.get("spread_pct"); depth = ((flow.get("bid_qty", 0) or 0) + (flow.get("ask_qty", 0) or 0)) * price
    candle_patterns = _candlestick_patterns(opens, highs, lows, closes)
    alignment = "bullish" if ema9 and ema21 and ema50 and ema9 > ema21 > ema50 else "bearish" if ema9 and ema21 and ema50 and ema9 < ema21 < ema50 else "mixed"
    methodologies = _methodology_analysis(opens, highs, lows, closes, volumes, adx, alignment)
    result.update({"timeframe": primary_timeframe, "data_ready": True, "trend": {"ema_9": ema9, "ema_21": ema21, "ema_50": ema50, "alignment": alignment, "adx": adx}, "momentum": {"return_5m": ret(1), "return_15m": ret(3), "return_1h": ret(12), "rsi_14": _rsi(closes), "roc_21": ret(21), "macd": macd, "stochastic": stochastic, "mfi_14": mfi}, "oscillators": {"values": oscillator_values, "signals": oscillator_signals}, "moving_averages": moving_averages, "candlestick_patterns": _candlestick_patterns(opens, highs, lows, closes), "channels": {"bollinger": bollinger, "donchian": {"upper": max(highs[-20:]), "middle": _sma(closes, 20), "lower": min(lows[-20:])} if len(closes) >= 20 else None, "keltner": {"middle": ema20, "upper": ema20 + 2*atr if ema20 and atr else None, "lower": ema20 - 2*atr if ema20 and atr else None}}, "volatility": {"atr_14": atr, "atr_pct": atr / price if atr and price else None, "adr_14_pct": adr, "adr_basis": "1d", "bollinger": bollinger, "day_range_used_pct": None, "adr_utilization": None, "remaining_capacity_pct": None}, "volume": {"volume_ratio_20": volumes[-1] / vavg if vavg else None, "volume_quality": "insufficient_history" if len(volumes) < 21 else "low_volume" if vavg and volumes[-1] / vavg < 0.2 else "valid", "volume_timeframe": primary_timeframe, "vwap": float(np.sum(((np.array(highs[-20:]) + np.array(lows[-20:]) + np.array(closes[-20:])) / 3) * np.array(volumes[-20:])) / np.sum(volumes[-20:])) if len(volumes) >= 20 and np.sum(volumes[-20:]) else None, "obv": obv}, "pivots": _pivots(dhigh[-1], dlow[-1], dclose[-1]) if len(dclose) else None, "liquidity": {"quote_volume_24h": ticker_24h, "spread_pct": spread, "orderbook_depth_try": depth, "depth_multiplier": depth / order_value if order_value else None, "orderflow_imbalance": ((flow.get("bid_qty", 0) - flow.get("ask_qty", 0)) / (flow.get("bid_qty", 0) + flow.get("ask_qty", 0))) if (flow.get("bid_qty", 0) + flow.get("ask_qty", 0)) else None, "scope": "realtime_market", "timeframe_independent": True, "source": flow.get("source", "binance_tr_public_websocket"), "updated_at": flow.get("updated_at")}, "methodologies": methodologies})
    result["candlestick_patterns"] = candle_patterns
    result["price_action"] = _price_action_setup(opens, highs, lows, closes)
    result["candlestick_pattern_details"] = [CANDLESTICK_PATTERN_INFO.get(name, {"direction": "neutral", "strength": "info", "tr": name}) for name in candle_patterns]
    result["candlestick_pattern_status"] = "calculated_no_pattern" if candle_patterns == ["none"] else "detected"
    if adr and len(dclose) and dclose[-1]:
        day_open = daily.get("opens", [])[-1] if daily.get("opens") else dclose[-1]
        used = max(price, day_open) / min(price, day_open) - 1 if price > 0 and day_open > 0 else 0
        result["volatility"].update({"day_range_used_pct": used, "adr_utilization": used / adr, "remaining_capacity_pct": adr - used})
    result["summary"] = "bullish" if result["trend"]["alignment"] == "bullish" and (result["momentum"]["rsi_14"] or 0) >= 50 else "mixed"
    return result
