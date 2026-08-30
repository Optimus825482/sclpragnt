"""Causal per-bar indicator series for pump-pattern research.

Every feature at bar ``i`` only uses candles up to and including bar ``i``
(closed candles). Formulas mirror ``app/technical_analysis.py`` exactly
(SMA-style RSI/ATR/ADX, same seeds, same windows) so values are comparable
with the live ``calculate_snapshot`` pipeline.
"""

import math

import numpy as np


# ---------------------------------------------------------------------------
# base series helpers
# ---------------------------------------------------------------------------

def ema_series(values, period):
    """Same seed (mean of first ``period``) as app _ema_series; None before warmup."""
    out = [None] * len(values)
    if len(values) < period:
        return out
    current = float(np.mean(np.asarray(values[:period], dtype=float)))
    out[period - 1] = current
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        current = alpha * float(values[i]) + (1 - alpha) * current
        out[i] = current
    return out


def _ema_of_valid(series, period):
    """EMA over the non-None tail of ``series``, mapped back to original indices."""
    first = next((i for i, v in enumerate(series) if v is not None), None)
    if first is None:
        return [None] * len(series)
    valid = [v for v in series[first:] if v is not None]
    ema = ema_series(valid, period)
    return [None] * first + ema


def rolling_mean(values, period):
    out = [None] * len(values)
    arr = np.asarray(values, dtype=float)
    if len(arr) >= period:
        c = np.cumsum(np.insert(arr, 0, 0.0))
        out[period - 1:] = ((c[period:] - c[:-period]) / period).tolist()
    return out


def _rolling_extreme(values, period, fn):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = fn(values[i - period + 1:i + 1])
    return out


# ---------------------------------------------------------------------------
# indicator series (mirror app/technical_analysis.py formulas)
# ---------------------------------------------------------------------------

def rsi_series(closes, period=14):
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    arr = np.asarray(closes, dtype=float)
    changes = np.diff(arr)
    gains = np.maximum(changes, 0.0)
    losses = np.maximum(-changes, 0.0)
    cg, cl = np.cumsum(np.insert(gains, 0, 0.0)), np.cumsum(np.insert(losses, 0, 0.0))
    for i in range(period, len(closes)):
        g = (cg[i] - cg[i - period]) / period
        l = (cl[i] - cl[i - period]) / period
        if l == 0:
            out[i] = 100.0 if g > 0 else 50.0
        else:
            out[i] = float(100 - 100 / (1 + g / l))
    return out


def atr_series(highs, lows, closes, period=14):
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    sma = rolling_mean(tr, period)
    for i in range(period, len(closes)):
        out[i] = sma[i]
    return out


def true_range_series(highs, lows, closes):
    out = [None] * len(closes)
    for i in range(1, len(closes)):
        out[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    return out


def macd_series(closes, fast=12, slow=26, signal=9):
    e_fast, e_slow = ema_series(closes, fast), ema_series(closes, slow)
    line = [None if (a is None or b is None) else a - b for a, b in zip(e_fast, e_slow)]
    sig = _ema_of_valid(line, signal)
    hist = [None if (a is None or b is None) else a - b for a, b in zip(line, sig)]
    return {"line": line, "signal": sig, "histogram": hist}


def bollinger_series(closes, period=20, std_mult=2.0):
    n = len(closes)
    pos = [None] * n
    width = [None] * n
    if n < period:
        return {"position": pos, "width_pct": width}
    arr = np.asarray(closes, dtype=float)
    c = np.cumsum(np.insert(arr, 0, 0.0))
    c2 = np.cumsum(np.insert(arr * arr, 0, 0.0))
    for i in range(period - 1, n):
        s = c[i + 1] - c[i + 1 - period]
        s2 = c2[i + 1] - c2[i + 1 - period]
        mean = s / period
        var = max(s2 / period - mean * mean, 0.0)
        std = math.sqrt(var)
        upper, lower = mean + std_mult * std, mean - std_mult * std
        width[i] = (upper - lower) / mean if mean else None
        pos[i] = (arr[i] - lower) / (upper - lower) if upper != lower else None
    return {"position": pos, "width_pct": width}


def stochastic_series(highs, lows, closes, period=14, smooth=3):
    n = len(closes)
    k = [None] * n
    d = [None] * n
    raw = []
    for i in range(period - 1, n):
        hi, lo = max(highs[i - period + 1:i + 1]), min(lows[i - period + 1:i + 1])
        raw.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    for i in range(period - 1, n):
        idx = i - (period - 1)
        if idx >= smooth - 1:
            k[i] = float(np.mean(raw[idx - smooth + 1:idx + 1]))
        if idx >= smooth * 2 - 1:
            d[i] = float(np.mean(raw[idx - smooth * 2 + 1:idx - smooth + 1]))
    return {"k": k, "d": d}


def stoch_rsi_series(closes, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    n = len(closes)
    k = [None] * n
    d = [None] * n
    rsi = rsi_series(closes, rsi_period)
    raw = []
    for i in range(n):
        if rsi[i] is None:
            continue
        window = [v for v in rsi[max(0, i - stoch_period + 1):i + 1] if v is not None]
        if len(window) < stoch_period:
            continue
        lo, hi = min(window), max(window)
        raw.append((i, (rsi[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0))
    for j, (i, value) in enumerate(raw):
        if j >= k_period - 1:
            k[i] = float(np.mean([v for _, v in raw[j - k_period + 1:j + 1]]))
        if j >= k_period + d_period - 2:
            d[i] = float(np.mean([k[ki] for ki, _ in raw[j - d_period + 1:j + 1]]))
    return {"k": k, "d": d}


def cmo_series(closes, period=9):
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    arr = np.asarray(closes, dtype=float)
    changes = np.diff(arr)
    gains = np.maximum(changes, 0.0)
    losses = np.maximum(-changes, 0.0)
    cg, cl = np.cumsum(np.insert(gains, 0, 0.0)), np.cumsum(np.insert(losses, 0, 0.0))
    for i in range(period, len(closes)):
        g = cg[i] - cg[i - period]
        l = cl[i] - cl[i - period]
        out[i] = float(100 * (g - l) / (g + l)) if g + l else 0.0
    return out


def cci_series(highs, lows, closes, period=20):
    out = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        typical = [(h + l + c) / 3 for h, l, c in zip(highs[i - period + 1:i + 1], lows[i - period + 1:i + 1], closes[i - period + 1:i + 1])]
        mean = float(np.mean(typical))
        dev = float(np.mean(np.abs(np.asarray(typical) - mean)))
        out[i] = float((typical[-1] - mean) / (0.015 * dev)) if dev else 0.0
    return out


def williams_series(highs, lows, closes, period=14):
    out = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        hi, lo = max(highs[i - period + 1:i + 1]), min(lows[i - period + 1:i + 1])
        out[i] = float((hi - closes[i]) / (hi - lo) * -100) if hi != lo else -50.0
    return out


def awesome_series(highs, lows, fast=5, slow=34):
    median = [(h + l) / 2 for h, l in zip(highs, lows)]
    f, s = rolling_mean(median, fast), rolling_mean(median, slow)
    return [None if (a is None or b is None) else a - b for a, b in zip(f, s)]


def adx_series(highs, lows, closes, period=14):
    n = len(closes)
    out = {"adx": [None] * n, "plus_di": [None] * n, "minus_di": [None] * n}
    if n < period * 2 + 1:
        return out
    tr, plus, minus = true_range_series(highs, lows, closes), [], []
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
    for i in range(period * 2, n):
        atr = float(np.mean([v for v in tr[i - period + 1:i + 1] if v is not None]))
        if not atr:
            continue
        pdi = 100 * float(np.mean(plus[i - period:i])) / atr
        mdi = 100 * float(np.mean(minus[i - period:i])) / atr
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0
        out["adx"][i], out["plus_di"][i], out["minus_di"][i] = dx, pdi, mdi
    return out


def vortex_series(highs, lows, closes, period=14):
    n = len(closes)
    plus_out, minus_out = [None] * n, [None] * n
    if n < period + 1:
        return plus_out, minus_out
    tr = true_range_series(highs, lows, closes)
    vp, vm = [0.0], [0.0]
    for i in range(1, n):
        vp.append(abs(highs[i] - lows[i - 1]))
        vm.append(abs(lows[i] - highs[i - 1]))
    for i in range(period, n):
        tr_sum = sum(v for v in tr[i - period + 1:i + 1] if v is not None)
        if not tr_sum:
            continue
        plus_out[i] = sum(vp[i - period + 1:i + 1]) / tr_sum
        minus_out[i] = sum(vm[i - period + 1:i + 1]) / tr_sum
    return plus_out, minus_out


def supertrend_series(highs, lows, closes, period=10, factor=3.0):
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    atr_values = [None] * n
    tr = true_range_series(highs, lows, closes)
    for i in range(period - 1, n):
        atr_values[i] = float(np.mean([v for v in tr[max(1, i - period + 1):i + 1] if v is not None]))
    direction, line = 1, None
    for i in range(n):
        atr = atr_values[i]
        if atr is None:
            continue
        midpoint = (highs[i] + lows[i]) / 2
        upper, lower = midpoint + factor * atr, midpoint - factor * atr
        direction = 1 if closes[i] >= (line if line is not None else lower) else -1
        if direction == 1:
            line = max(lower, line) if line is not None else lower
        else:
            line = min(upper, line) if line is not None else upper
        out[i] = direction
    return out


def aroon_series(highs, lows, period=25):
    n = len(highs)
    up, down = [None] * n, [None] * n
    for i in range(period - 1, n):
        hw, lw = highs[i - period + 1:i + 1], lows[i - period + 1:i + 1]
        hb = period - 1 - int(np.argmax(hw))
        lb = period - 1 - int(np.argmin(lw))
        up[i] = 100 * (period - hb) / period
        down[i] = 100 * (period - lb) / period
    return up, down


def ichimoku_above_cloud_series(highs, lows, closes, conversion=9, base=26, span=52):
    n = len(closes)
    out = [None] * n
    for i in range(span - 1, n):
        mid = lambda length: (max(highs[i - length + 1:i + 1]) + min(lows[i - length + 1:i + 1])) / 2
        tenkan, kijun = mid(conversion), mid(base)
        span_a, span_b = (tenkan + kijun) / 2, mid(span)
        out[i] = closes[i] > max(span_a, span_b)
    return out


def choppiness_series(highs, lows, closes, period=14):
    out = [None] * len(closes)
    tr = true_range_series(highs, lows, closes)
    for i in range(period, len(closes)):
        total = sum(v for v in tr[i - period + 1:i + 1] if v is not None)
        price_range = max(highs[i - period + 1:i + 1]) - min(lows[i - period + 1:i + 1])
        if total > 0 and price_range > 0:
            out[i] = float(100 * math.log10(total / price_range) / math.log10(period))
    return out


def trix_series(closes, period=15):
    e1 = ema_series(closes, period)
    e2 = _ema_of_valid(e1, period)
    e3 = _ema_of_valid(e2, period)
    return [None if (a is None or b in (None, 0)) else (a - b) / abs(b) * 100 for a, b in zip(e3[1:], e3[:-1])[:0]] if False else \
        [None] + [None if (e3[i] is None or e3[i - 1] in (None, 0)) else (e3[i] - e3[i - 1]) / abs(e3[i - 1]) * 100 for i in range(1, len(e3))]


def tsi_series(closes, long_period=25, short_period=13):
    n = len(closes)
    out = [None] * n
    if n < long_period + short_period + 2:
        return out
    momentum = [closes[i] - closes[i - 1] for i in range(1, n)]
    sm = _ema_of_valid([None] + ema_series(momentum, short_period), short_period)
    sm = [None] + sm  # align: momentum[i-1] belongs to bar i
    sm_abs = _ema_of_valid([None] + ema_series([abs(m) for m in momentum], short_period), short_period)
    sm_abs = [None] + sm_abs
    dbl = ema_series([v if v is not None else np.nan for v in sm], long_period) if all(v is not None for v in sm[long_period - 1:]) else None
    if dbl is None:
        return out
    dbl_abs = ema_series([v if v is not None else np.nan for v in sm_abs], long_period)
    for i in range(n):
        if i >= long_period + short_period and dbl[i] is not None and dbl_abs[i]:
            out[i] = float(100 * dbl[i] / dbl_abs[i])
    return out


def mfi_series(highs, lows, closes, volumes, period=14):
    out = [None] * len(closes)
    for i in range(period, len(closes)):
        pos = neg = 0.0
        for j in range(i - period + 1, i + 1):
            typical = (highs[j] + lows[j] + closes[j]) / 3
            prev = (highs[j - 1] + lows[j - 1] + closes[j - 1]) / 3
            flow = typical * volumes[j]
            if typical > prev:
                pos += flow
            elif typical < prev:
                neg += flow
        out[i] = 100.0 if not neg else float(100 - 100 / (1 + pos / neg))
    return out


def obv_series(closes, volumes):
    out = [0.0] * len(closes)
    for i in range(1, len(closes)):
        delta = volumes[i] if closes[i] > closes[i - 1] else -volumes[i] if closes[i] < closes[i - 1] else 0.0
        out[i] = out[i - 1] + delta
    return out


def cmf_series(highs, lows, closes, volumes, period=20):
    out = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        mfv_sum, vol_sum = 0.0, 0.0
        for j in range(i - period + 1, i + 1):
            span = highs[j] - lows[j]
            mfv_sum += ((2 * closes[j] - highs[j] - lows[j]) / span * volumes[j]) if span else 0.0
            vol_sum += volumes[j]
        out[i] = float(mfv_sum / vol_sum) if vol_sum else None
    return out


def pvt_series(closes, volumes):
    out = [0.0] * len(closes)
    for i in range(1, len(closes)):
        if closes[i - 1]:
            out[i] = out[i - 1] + (closes[i] - closes[i - 1]) / closes[i - 1] * volumes[i]
    return out


def volume_oscillator_series(volumes, fast=5, slow=20):
    f, s = ema_series(volumes, fast), ema_series(volumes, slow)
    return [None if (a is None or not b) else (a - b) / b * 100 for a, b in zip(f, s)]


def vwap_series(highs, lows, closes, volumes, period=20):
    out = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        pv = sum((highs[j] + lows[j] + closes[j]) / 3 * volumes[j] for j in range(i - period + 1, i + 1))
        vv = sum(volumes[i - period + 1:i + 1])
        out[i] = float(pv / vv) if vv else None
    return out


def connors_rsi_series(closes, rsi_period=3, streak_period=2, rank_period=100):
    n = len(closes)
    out = [None] * n
    if n < rank_period + rsi_period + 2:
        return out
    r3 = rsi_series(closes, rsi_period)
    streaks = [0]
    for i in range(1, n):
        prev = streaks[-1]
        if closes[i] > closes[i - 1]:
            streaks.append(prev + 1 if prev > 0 else 1)
        elif closes[i] < closes[i - 1]:
            streaks.append(prev - 1 if prev < 0 else -1)
        else:
            streaks.append(0)
    for i in range(rank_period + rsi_period + 1, n):
        recent = np.asarray(streaks[i - streak_period + 1:i + 1], dtype=float)
        up, down = float(np.sum(np.maximum(recent, 0))), float(np.sum(np.maximum(-recent, 0)))
        streak_rsi = 100.0 if down == 0 and up else 50.0 if down == 0 else 100 - 100 / (1 + up / down)
        changes = [closes[j] - closes[j - 1] for j in range(i - rank_period, i)]
        rank = 100 * sum(1 for ch in changes if ch < closes[i] - closes[i - 1]) / len(changes)
        out[i] = float((r3[i] + streak_rsi + rank) / 3)
    return out
