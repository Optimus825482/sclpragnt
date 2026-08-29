#!/usr/bin/env python3
"""6 Hour Historical LONG Pattern Backtest"""
import asyncio
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime

import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.binance_tr_public import historical_klines

def ema_calc(values, period):
    if len(values) < period: return None
    alpha = 2 / (period + 1)
    result = float(np.mean(values[:period]))
    for item in values[period:]:
        result = alpha * float(item) + (1 - alpha) * result
    return result

def atr_calc(highs, lows, closes, period=14):
    if len(closes) < period + 1: return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev))
        trs.append(tr)
    return float(np.mean(trs)) if trs else None

def rsi_calc(closes, period=14):
    if len(closes) < period + 1: return None
    changes = np.diff(closes[-period - 1:])
    gains = float(np.mean(np.maximum(changes, 0)))
    losses = float(np.mean(np.maximum(-changes, 0)))
    if losses == 0: return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses))

def adx_calc(highs, lows, closes, period=14):
    if len(closes) < period * 2: return None
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(closes)):
        hd = highs[i] - highs[i - 1]
        ld = lows[i - 1] - lows[i]
        plus_dm.append(hd if hd > ld and hd > 0 else 0)
        minus_dm.append(ld if ld > hd and ld > 0 else 0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
    if len(tr_list) < period: return None
    atr = float(np.mean(tr_list[-period:]))
    pdm = np.mean(plus_dm[-period:]) / atr * 100 if atr > 0 else 0
    mdm = np.mean(minus_dm[-period:]) / atr * 100 if atr > 0 else 0
    dx = abs(pdm - mdm) / (pdm + mdm) * 100 if (pdm + mdm) > 0 else 0
    return {"adx": float(dx), "plus_di": float(pdm), "minus_di": float(mdm)}

def stoch_calc(highs, lows, closes, period=14, smooth=3):
    if len(closes) < period + smooth - 1: return None
    values = []
    for i in range(period - 1, len(closes)):
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        values.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k = float(np.mean(values[-smooth:]))
    d = float(np.mean(values[-smooth * 2:-smooth])) if len(values) >= smooth * 2 else k
    return {"k": k, "d": d}

def cmo_calc(closes, period=9):
    if len(closes) < period + 1: return None
    changes = np.diff(closes[-period - 1:])
    gains = float(np.sum(np.maximum(changes, 0)))
    losses = float(np.sum(np.maximum(-changes, 0)))
    return float(100 * (gains - losses) / (gains + losses)) if (gains + losses) != 0 else 0.0

def mfi_calc(highs, lows, closes, volumes, period=14):
    if len(closes) < period + 1: return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    flow = [typical[i] * volumes[i] for i in range(len(typical))]
    pos = neg = 0.0
    for i in range(len(typical) - period, len(typical)):
        if typical[i] > typical[i - 1]: pos += flow[i]
        else: neg += flow[i]
    if neg == 0: return 100.0
    return float(100 - (100 / (1 + pos / neg))

def williams_calc(highs, lows, closes, period=14):
    if len(closes) < period: return None
    highest = max(highs[-period:])
    lowest = min(lows[-period:])
    if highest == lowest: return -50.0
    return float(-100 * (highest - closes[-1]) / (highest - lowest))

def vwap_calc(highs, lows, closes, volumes):
    if len(closes) < 2: return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    tpv = sum(typical[i] * volumes[i] for i in range(len(typical)))
    tv = sum(volumes)
    return tpv / tv if tv > 0 else None

def st_calc(highs, lows, closes, period=10, mult=3.0):
    if len(closes) < period + 1: return None
    atr_val = atr_calc(highs, lows, closes, period) or 0
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(len(closes))]
    upper, lower = [hl2[0] + mult * atr_val], [hl2[0] - mult * atr_val]
    trend = [1]
    for i in range(1, len(closes)):
        cu = hl2[i] + mult * atr_val
        cl = hl2[i] - mult * atr_val
        upper.append(max(upper[i-1], cu))
        lower.append(min(lower[i-1], cl))
        if closes[i] > upper[i-1]: trend.append(1)
        elif closes[i] < lower[i-1]: trend.append(-1)
        else: trend.append(trend[i-1])
    return {"trend": "bullish" if trend[-1] == 1 else "bearish", "changed": trend[-1] != trend[-2] if len(trend) > 1 else False}

def bb_calc(closes, period=20, mult=2.0):
    if len(closes) < period: return None
    window = np.asarray(closes[-period:], dtype=float)
    mid = float(np.mean(window))
    std = float(np.std(window))
    upper = mid + mult * std
    lower = mid - mult * std
    pos = (closes[-1] - lower) / (upper - lower) if upper != lower else None
    return {"upper": upper, "middle": mid, "lower": lower, "position": pos}

def snapshot(highs, lows, closes, volumes):
    snap = {"price": {}, "trend": {}, "momentum": {}, "volume": {}}
    atr_val = atr_calc(highs, lows, closes)
    atr_pct = (atr_val / closes[-1] * 100) if atr_val and closes[-1] else None
    vol_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes) if volumes else 1
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = ((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else None
    snap["price"]["atr_pct"] = atr_pct
    snap["price"]["vol_ratio"] = vol_ratio
    snap["price"]["change5"] = change5
    snap["price"]["vwap"] = vwap_calc(highs, lows, closes, volumes)
    snap["price"]["close"] = closes[-1]
    ema9 = ema_calc(closes, 9)
    ema21 = ema_calc(closes, 21)
    snap["trend"]["alignment"] = "bullish" if ema9 and ema21 and ema9 > ema21 else "bearish"
    snap["momentum"]["rsi"] = rsi_calc(closes)
    snap["momentum"]["stoch"] = stoch_calc(highs, lows, closes)
    snap["momentum"]["cmo"] = cmo_calc(closes)
    snap["momentum"]["williams"] = williams_calc(highs, lows, closes)
    snap["volume"]["mfi"] = mfi_calc(highs, lows, closes, volumes)
    snap["volume"]["vol_ratio"] = vol_ratio
    snap["adx"] = adx_calc(highs, lows, closes)
    snap["st"] = st_calc(highs, lows, closes)
    snap["bb"] = bb_calc(closes)
    return snap

def check_long(snap):
    pi = snap.get("price", {})
    mom = snap.get("momentum", {})
    vol = snap.get("volume", {})
    adx_d = snap.get("adx", {})
    st = snap.get("st", {})
    matches, score, warns = [], 0.0, []
    vr = vol.get("vol_ratio", 1)
    if vr >= 1.5: matches.append("vol_spike_strong"); score += 3.0
    elif vr >= 1.2: matches.append("vol_spike"); score += 1.5
    cmo_v = mom.get("cmo")
    if cmo_v is not None and cmo_v <= -25: matches.append("cmo_bearish"); score += 2.5
    if st.get("trend") == "bullish": matches.append("st_bull"); score += 2.0
    vwap_v = pi.get("vwap")
    price = pi.get("close")
    if vwap_v and price:
        if price < vwap_v: matches.append("below_vwap"); score += 1.5
        else: matches.append("above_vwap"); score += 0.5
    adx_v = adx_d.get("adx", 0)
    if adx_v >= 25: matches.append("adx_strong"); score += 1.5
    elif adx_v < 15: warns.append("adx_weak")
    atr_pct = pi.get("atr_pct")
    if atr_pct is not None and atr_pct >= 0.3: matches.append("atr_ok"); score += 1.0
    elif atr_pct is not None and atr_pct < 0.15: warns.append("atr_low")
    rsi_v = mom.get("rsi")
    if rsi_v is not None:
        if rsi_v < 70: matches.append("rsi_safe"); score += 0.5
        if rsi_v <= 30: matches.append("rsi_oversold"); score += 1.
