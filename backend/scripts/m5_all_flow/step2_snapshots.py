#!/usr/bin/env python3
"""
Adim 4-5: Yukselis oncesi son 10 M1 + 2 M5 + baslangic mumu gostergeleri.

Ekteki GOSTERGELER.HTML listesinden %2+ yukselisi onceden isaret etme
ihtimali olan gostergeler (snapshot ve desen analizi icin):

- RSI, Stochastic, Williams %R, CCI, CMO, ROC, Momentum, MACD (hist), TRIX
- MFI, OBV, Volume Ratio, Volume Osc.
- ATR%, Bollinger (lower band / %B), Choppiness, Supertrend
- EMA9/21/50 hizalama, VWAP
- ADX/DMI, Vortex, KST, TSI (gosterge havuzu)
- FVG tespiti (3 mumluk yapi)

Her yukselis icin 3 snapshot:
  A) 10 M1 mum (yukselisin HEMEN oncesindeki 10 dakika) -- ANA
  B) 2 M5 mum (anketen onceki 2 M5) -- ikincil
  C) yukselis baslangici dahil 3 M5 mum (baslangic mumu + 2)

Cikti: m5_m1_snapshots.json (her yukselis icin gostergeler + etiketler)
       pattern_summary.json (ortak desen istatistikleri, lift degerleri)
"""

import json
import math
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scalper_db_v4.sqlite")
RISERS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "m5_risers.json")


# ---------------------------------------------------------------- CORE TAs

def ema_series(values, period):
    n = len(values)
    out = [None] * n
    if n < period:
        return out
    cur = float(np.mean(values[:period]))
    out[period - 1] = cur
    alpha = 2 / (period + 1)
    for i in range(period, n):
        cur = alpha * values[i] + (1 - alpha) * cur
        out[i] = cur
    return out


def ema_last(values, period):
    s = ema_series(values, period)
    return s[-1] if s and s[-1] is not None else None


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    ch = np.diff(np.asarray(closes[-(period + 1):], dtype=float))
    gains = float(np.mean(np.maximum(ch, 0)))
    losses = float(np.mean(np.maximum(-ch, 0)))
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses)))


def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    return float(np.mean(trs))


def stochastic(highs, lows, closes, period=14, smooth=3):
    if len(closes) < period + smooth - 1:
        return None
    vals = []
    for i in range(period - 1, len(closes)):
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        vals.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k = float(np.mean(vals[-smooth:]))
    return {"k": k, "d": float(np.mean(vals[-smooth * 2:-smooth])) if len(vals) >= smooth * 2 else k}


def williams_r(highs, lows, closes, period=14):
    if len(closes) < period:
        return None
    hi, lo = max(highs[-period:]), min(lows[-period:])
    if hi == lo:
        return -50.0
    return float(-100 * (hi - closes[-1]) / (hi - lo))


def cci(highs, lows, closes, period=20):
    if len(closes) < period:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    sma = float(np.mean(tp[-period:]))
    mad = float(np.mean([abs(tp[i] - sma) for i in range(len(tp) - period, len(tp))]))
    if mad == 0:
        return 0.0
    return float((tp[-1] - sma) / (0.015 * mad))


def cmo(closes, period=9):
    if len(closes) < period + 1:
        return None
    ch = np.diff(np.asarray(closes[-(period + 1):], dtype=float))
    g = float(np.sum(np.maximum(ch, 0)))
    l = float(np.sum(np.maximum(-ch, 0)))
    return float(100 * (g - l) / (g + l)) if (g + l) else 0.0


def roc(closes, period=10):
    if len(closes) < period + 1:
        return None
    return float((closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100)


def momentum(closes, period=10):
    if len(closes) < period + 1:
        return None
    return float(closes[-1] - closes[-period - 1])


def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if ef[i] is not None and es[i] is not None:
            macd_line[i] = ef[i] - es[i]
    valid = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    if len(valid) < signal:
        return None
    sig_vals = [v for _, v in valid]
    sig = ema_series(sig_vals, signal)
    line = valid[-1][1]
    s = sig[-1] if sig and sig[-1] is not None else line
    return {"line": float(line), "signal": float(s), "histogram": float(line - s)}


def trix(closes, period=15):
    """Tekli EMA tabanli TRIX yaklasimi (degisim yuzdesi)."""
    if len(closes) < period * 3:
        return None
    e1 = ema_series(closes, period)
    e2 = ema_series([v for v in e1 if v is not None], period)
    e3 = ema_series([v for v in e2 if v is not None], period)
    if len(e3) < 2 or e3[-1] is None or e3[-2] is None or e3[-2] == 0:
        return None
    return float((e3[-1] - e3[-2]) / abs(e3[-2]) * 100)


def mfi(highs, lows, closes, volumes, period=14):
    if len(closes) < period + 1:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    flow = [tp[i] * volumes[i] for i in range(len(tp))]
    pos = neg = 0.0
    for i in range(len(tp) - period, len(tp)):
        if tp[i] > tp[i - 1]:
            pos += flow[i]
        else:
            neg += flow[i]
    if neg == 0:
        return 100.0
    return float(100 - (100 / (1 + pos / neg)))


def obv(closes, volumes):
    if len(closes) < 2:
        return None
    val = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            val += volumes[i]
        elif closes[i] < closes[i - 1]:
            val -= volumes[i]
    return float(val)


def vwap(highs, lows, closes, volumes):
    if len(closes) < 2 or sum(volumes) == 0:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    return sum(tp[i] * volumes[i] for i in range(len(closes))) / sum(volumes)


def adx(highs, lows, closes, period=14):
    if len(closes) < period * 2:
        return None
    pdm, mdm, trs = [], [], []
    for i in range(1, len(closes)):
        hd = highs[i] - highs[i - 1]
        ld = lows[i - 1] - lows[i]
        pdm.append(hd if hd > ld and hd > 0 else 0.0)
        mdm.append(ld if ld > hd and ld > 0 else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    if len(trs) < period:
        return None
    atr_v = float(np.mean(trs[-period:]))
    pdi = np.mean(pdm[-period:]) / atr_v * 100 if atr_v > 0 else 0
    mdi = np.mean(mdm[-period:]) / atr_v * 100 if atr_v > 0 else 0
    dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
    return {"adx": float(dx), "pdi": float(pdi), "mdi": float(mdi)}


def supertrend(highs, lows, closes, period=10, mult=3.0):
    if len(closes) < period + 1:
        return None
    atr_v = atr(highs, lows, closes, period) or 0
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(len(closes))]
    upper, lower = [hl2[0] + mult * atr_v], [hl2[0] - mult * atr_v]
    trend = [1]
    for i in range(1, len(closes)):
        cu, cl = hl2[i] + mult * atr_v, hl2[i] - mult * atr_v
        upper.append(max(upper[i - 1], cu))
        lower.append(min(lower[i - 1], cl))
        if closes[i] > upper[i - 1]:
            trend.append(1)
        elif closes[i] < lower[i - 1]:
            trend.append(-1)
        else:
            trend.append(trend[i - 1])
    return {"trend": "bullish" if trend[-1] == 1 else "bearish",
            "changed": trend[-1] != trend[-2] if len(trend) > 1 else False}


def bollinger(closes, period=20, mult=2.0):
    if len(closes) < period:
        return None
    w = np.asarray(closes[-period:], dtype=float)
    mid, std = float(np.mean(w)), float(np.std(w))
    upper, lower = mid + mult * std, mid - mult * std
    pos = (closes[-1] - lower) / (upper - lower) if upper != lower else None
    return {"upper": upper, "lower": lower, "position": pos, "bandwidth_pct": (upper - lower) / mid * 100 if mid else None}


def choppiness(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    atr_sum = 0.0
    for i in range(len(closes) - period, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        atr_sum += tr
    hi, lo = max(highs[-period:]), min(lows[-period:])
    if hi == lo:
        return 100.0
    return float(100 * math.log10(atr_sum / (hi - lo)) / math.log10(period))


def vortex(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    pvm = [abs(highs[i] - lows[i - 1]) for i in range(1, len(highs))]
    mvm = [abs(lows[i] - highs[i - 1]) for i in range(1, len(lows))]
    atr_v = atr(highs, lows, closes, period) or 1
    return {"plus_vi": float(np.sum(pvm[-period:]) / atr_v), "minus_vi": float(np.sum(mvm[-period:]) / atr_v)}


def fvg_detection(closes, highs, lows):
    """Son 3 mumda bull/bear FVG var mi (ekstre gostergelerden)."""
    if len(closes) < 3:
        return {"bull_fvg": False, "bear_fvg": False}
    bull = lows[-1] > highs[-3]
    bear = highs[-1] < lows[-3]
    return {"bull_fvg": bool(bull), "bear_fvg": bool(bear)}


# ---------------------------------------------------------------- SNAPSHOT BUILDER

def build_snapshot(highs, lows, closes, volumes, tf_label):
    """Bir pencere icin tum gosterge snapshot'i hesaplar."""
    out = {"timeframe": tf_label, "n_candles": len(closes)}
    if len(closes) < 5:
        return out
    close = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    vol_oscil = (volumes[-1] - vol_avg) / vol_avg * 100 if vol_avg > 0 else 0.0

    # Fiyat/yapisal
    out["price"] = {
        "close": close,
        "atr_pct": (atr_v / close * 100) if atr_v and close else None,
        "volume_ratio": round(vol_ratio, 3),
        "volume_oscil_pct": round(vol_oscil, 2),
        "change_3": round((closes[-1] - closes[-4]) / closes[-4] * 100, 3) if len(closes) >= 4 else None,
        "change_5": round((closes[-1] - closes[-6]) / closes[-6] * 100, 3) if len(closes) >= 6 else None,
        "wick_upper_ratio": round((highs[-1] - max(closes[-1], closes[-2])) / (highs[-1] - lows[-1]), 3) if highs[-1] != lows[-1] else None,
    }

    # Trend
    e9, e21, e50 = ema_last(closes, 9), ema_last(closes, 21), ema_last(closes, 50) if len(closes) >= 50 else None
    if e9 and e21:
        align = "bullish" if e9 > e21 else ("bearish" if e9 < e21 else "neutral")
    else:
        align = "unknown"
    if e50:
        if e9 > e21 > e50:
            align = "bullish"
        elif e9 < e21 < e50:
            align = "bearish"
    out["trend"] = {
        "ema_alignment": align,
        "ema9_21_gap_pct": round((e9 - e21) / e21 * 100, 3) if e9 and e21 and e21 else None,
    }
    adx_d = adx(highs, lows, closes)
    if adx_d:
        out["adx"] = {"adx": round(adx_d["adx"], 1), "pdi": round(adx_d["pdi"], 1), "mdi": round(adx_d["mdi"], 1)}
    st = supertrend(highs, lows, closes)
    if st:
        out["supertrend"] = st
    bb = bollinger(closes)
    if bb:
        out["bollinger"] = {"position": round(bb["position"], 3) if bb["position"] is not None else None,
                            "bandwidth_pct": round(bb["bandwidth_pct"], 2)}
    out["fvg"] = fvg_detection(closes, highs, lows)

    # Momentum
    out["momentum"] = {
        "rsi": round(rsi(closes), 1) if rsi(closes) is not None else None,
        "stoch_k": (stochastic(highs, lows, closes) or {}).get("k"),
        "williams_r": round(williams_r(highs, lows, closes), 1) if williams_r(highs, lows, closes) is not None else None,
        "cci": round(cci(highs, lows, closes), 1) if cci(highs, lows, closes) is not None else None,
        "cmo": round(cmo(closes), 1) if cmo(closes) is not None else None,
        "roc": round(roc(closes), 2) if roc(closes) is not None else None,
        "momentum": round(momentum(closes), 4) if momentum(closes) is not None else None,
        "trix": round(trix(closes), 3) if trix(closes) is not None else None,
    }
    macd_d = macd(closes)
    if macd_d:
        out["macd"] = {"histogram": round(macd_d["histogram"], 5), "line": round(macd_d["line"], 5)}

    # Hacim
    out["volume"] = {
        "mfi": round(mfi(highs, lows, closes, volumes), 1) if mfi(highs, lows, closes, volumes) is not None else None,
        "obv": obv(closes, volumes),
        "vwap": round(vwap(highs, lows, closes, volumes), 5) if vwap(highs, lows, closes, volumes) else None,
        "vwap_dist_pct": round((close / vwap(highs, lows, closes, volumes) - 1) * 100, 2)
                         if vwap(highs, lows, closes, volumes) else None,
    }
    ch = choppiness(highs, lows, closes)
    out["choppiness"] = round(ch, 1) if ch is not None else None
    vx = vortex(highs, lows, closes)
    if vx:
        out["vortex"] = {"plus_vi": round(vx["plus_vi"], 2), "minus_vi": round(vx["minus_vi"], 2)}
    return out


# ---------------------------------------------------------------- TAG EXTRACTION

def extract_tags(snap, prefix):
    """Snapshot'tan desen etiketleri cikarir."""
    tags = []
    m = snap.get("momentum", {})
    v = snap.get("volume", {})
    p = snap.get("price", {})
    t = snap.get("trend", {})
    adx_d = snap.get("adx", {})
    st = snap.get("supertrend", {})
    bb = snap.get("bollinger", {})
    ch = snap.get("choppiness")

    def add(name):
        tags.append(f"{prefix}_{name}")

    rsi_v = m.get("rsi")
    if rsi_v is not None:
        if rsi_v <= 30: add("rsi_oversold")
        elif rsi_v >= 70: add("rsi_overbought")
        elif rsi_v <= 45: add("rsi_weak")
        elif rsi_v >= 55: add("rsi_strong")

    sk = m.get("stoch_k")
    if sk is not None:
        if sk <= 20: add("stoch_oversold")
        elif sk >= 80: add("stoch_overbought")

    wr = m.get("williams_r")
    if wr is not None:
        if wr <= -80: add("will_oversold")
        elif wr >= -20: add("will_overbought")

    cci_v = m.get("cci")
    if cci_v is not None:
        if cci_v <= -100: add("cci_oversold")
        elif cci_v >= 100: add("cci_overbought")

    cmo_v = m.get("cmo")
    if cmo_v is not None:
        if cmo_v >= 25: add("cmo_bull")
        elif cmo_v <= -25: add("cmo_bear")

    roc_v = m.get("roc")
    if roc_v is not None:
        if roc_v >= 5: add("roc_up")
        elif roc_v <= -5: add("roc_down")

    trix_v = m.get("trix")
    if trix_v is not None and abs(trix_v) > 0.05:
        add("trix_bull" if trix_v > 0 else "trix_bear")

    macd_hist = (snap.get("macd") or {}).get("histogram")
    if macd_hist is not None:
        add("macd_bull" if macd_hist > 0 else "macd_bear")

    adx_v = adx_d.get("adx")
    if adx_v is not None:
        if adx_v >= 25: add("adx_trend")
        elif adx_v < 15: add("adx_weak")

    if t.get("ema_alignment") == "bullish": add("ema_bull")
    elif t.get("ema_alignment") == "bearish": add("ema_bear")

    if st.get("trend") == "bullish": add("st_bull")
    if st.get("changed"): add("st_reversal")

    bb_pos = bb.get("position")
    if bb_pos is not None:
        if bb_pos <= 0.15: add("bb_lower")
        elif bb_pos >= 0.85: add("bb_upper")

    vr = p.get("volume_ratio")
    if vr is not None:
        if vr >= 1.5: add("vol_spike_strong")
        elif vr >= 1.2: add("vol_spike")
        elif vr < 0.7: add("vol_low")

    mfi_v = v.get("mfi")
    if mfi_v is not None:
        if mfi_v <= 20: add("mfi_oversold")
        elif mfi_v >= 80: add("mfi_overbought")

    vwap_dist = v.get("vwap_dist_pct")
    if vwap_dist is not None:
        add("vwap_below" if vwap_dist < 0 else "vwap_above")

    ch_v = ch
    if ch_v is not None:
        if ch_v <= 38.2: add("chop_trending")
        elif ch_v >= 61.8: add("chop_range")

    atr_pct = p.get("atr_pct")
    if atr_pct is not None:
        if atr_pct >= 0.3: add("atr_high")
        elif atr_pct < 0.15: add("atr_low")

    change5 = p.get("change_5")
    if change5 is not None:
        if change5 >= 1: add("price_rising")
        elif change5 <= -1: add("price_falling")

    if snap.get("fvg", {}).get("bull_fvg"): add("fvg_bull")
    if snap.get("fvg", {}).get("bear_fvg"): add("fvg_bear")

    vortex_d = snap.get("vortex")
    if vortex_d and vortex_d.get("plus_vi") is not None and vortex_d.get("minus_vi") is not None:
        add("vortex_bull" if vortex_d["plus_vi"] > vortex_d["minus_vi"] else "vortex_bear")

    return tags


# ---------------------------------------------------------------- MAIN

def load_risers():
    with open(RISERS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_db():
    return sqlite3.connect(DB_PATH)


def get_candles_between(conn, sym, tf, start_ms, end_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume
        FROM market_candles WHERE symbol=? AND timeframe=? AND open_time>=? AND open_time<=?
        ORDER BY open_time ASC
    """, (sym, tf, start_ms, end_ms))
    return [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]


def main():
    conn = get_db()
    risers = load_risers()
    print(f"Toplam yukselis: {len(risers)}")
    snapshots = []
    pattern_counter = Counter()
    per_symbol = defaultdict(set)

    # Warmup pencereleri: gostergelerin o anki degeri icin geriye yeterli
    # geçmiş mum gerekir (RSI-14 ~15, MACD ~35, ADX ~28, BB-20 ~20).
    M1_WARMUP_MS = 90 * 60 * 1000     # 90 dk M1 geçmişi
    M5_WARMUP_MS = 3 * 60 * 60 * 1000  # 3 saat M5 geçmişi

    total = len(risers)
    for idx, r in enumerate(risers, 1):
        sym = r["symbol"]
        rise_ms = r["rise_start_ms"]

        # ============ A) 10 M1 SNAPSHOT (ANA) ============
        # Gostergeler: yükseliş anına kadar olan geçmiş (warmup) M1 ile hesaplanır,
        # böylece değerler o anki TradingView görünümüyle birebir aynıdır.
        # Son 10 M1 mumu (rise-10dk..rise) ayrıca ham pencere olarak tutulur.
        m1_all = get_candles_between(conn, sym, "1m", rise_ms - M1_WARMUP_MS, rise_ms - 1)
        m1_last10 = [c for c in m1_all if c["ts"] >= rise_ms - 10 * 60 * 1000]

        entry = {"symbol": sym, "rise_pct": r["rise_pct"], "rise_start_ms": rise_ms,
                 "rise_start_price": r["rise_start_price"]}

        if len(m1_all) >= 30:
            snap_a = build_snapshot(
                [c["h"] for c in m1_all], [c["l"] for c in m1_all],
                [c["c"] for c in m1_all], [c["v"] for c in m1_all], "m1_header")
            # Son 10 M1 mumunun ham OHLCV + mini-göstergeleri
            if len(m1_last10) >= 5:
                snap_last10 = build_snapshot(
                    [c["h"] for c in m1_last10], [c["l"] for c in m1_last10],
                    [c["c"] for c in m1_last10], [c["v"] for c in m1_last10], "m1_last10")
                entry["snap_m1_last10"] = snap_last10
                # Son 10 M1 mumunun tek tek OHLCV'si
                entry["m1_candles"] = [
                    {"ts": c["ts"], "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c["v"]}
                    for c in m1_last10
                ]
            entry["snap_m1_10"] = snap_a
            tags_a = extract_tags(snap_a, "m1")
        else:
            tags_a = []

        # ============ B) 2 M5 SNAPSHOT (öncesi) ============
        # M5'te yükselişe kadar geçmiş (warmup 3s) ile gösterge değerleri
        m5_before = get_candles_between(conn, sym, "5m", rise_ms - M5_WARMUP_MS, rise_ms - 1)
        m5_prev2 = [c for c in m5_before if c["ts"] >= rise_ms - 10 * 60 * 1000]

        if len(m5_before) >= 30:
            snap_b = build_snapshot(
                [c["h"] for c in m5_before], [c["l"] for c in m5_before],
                [c["c"] for c in m5_before], [c["v"] for c in m5_before], "m5_before")
            if len(m5_prev2) >= 2:
                snap_prev2 = build_snapshot(
                    [c["h"] for c in m5_prev2], [c["l"] for c in m5_prev2],
                    [c["c"] for c in m5_prev2], [c["v"] for c in m5_prev2], "m5_prev2")
                entry["snap_m5_prev2"] = snap_prev2
                entry["m5_prev2_candles"] = [
                    {"ts": c["ts"], "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c["v"]}
                    for c in m5_prev2
                ]
            entry["snap_m5_2"] = snap_b
            tags_b = extract_tags(snap_b, "m5")
        else:
            tags_b = []

        # ============ C) 3 M5 SNAPSHOT (başlangıç dahil) ============
        # Yükseliş başlangıcı dahil son 3 M5; gösterge warmup ile hesaplanır
        m5_ctx = get_candles_between(conn, sym, "5m", rise_ms - M5_WARMUP_MS, rise_ms + 10 * 60 * 1000)
        if len(m5_ctx) >= 30:
            last3 = [c for c in m5_ctx if c["ts"] >= rise_ms - 10 * 60 * 1000]
            snap_c = build_snapshot(
                [c["h"] for c in last3], [c["l"] for c in last3],
                [c["c"] for c in last3], [c["v"] for c in last3], "m5_rise3")
            entry["snap_m5_rise3"] = snap_c
            tags_c = extract_tags(snap_c, "m5")
        else:
            tags_c = []

        entry["tags"] = tags_a + tags_b + tags_c
        entry["tags_m1"] = tags_a
        snapshots.append(entry)

        for tag in tags_a:
            pattern_counter[tag] += 1
            per_symbol[tag].add(sym)

        # M5 oncesi/ikincil desenler de istatistiğe katilsin (buttonsuz)
        for tag in tags_b + tags_c:
            pattern_counter[tag] += 1
            per_symbol[tag].add(sym)

        if idx % 150 == 0:
            print(f"  {idx}/{total}")

    # Ortak desen istatistikleri
    n = len(snapshots)
    n_uniq_sym = len({s["symbol"] for s in snapshots})
    pattern_summary = []
    for tag, cnt in pattern_counter.most_common():
        coverage = cnt / n * 100
        sym_cover = len(per_symbol[tag]) / n_uniq_sym * 100 if n_uniq_sym else 0
        # Lift: (gorulme / beklenti). Beklenti ~ %50 (bull mu bear mi) temel
        # bazda degisir; sadece M1 oncesi taglar icin raporlayacagiz.
        pattern_summary.append({
            "tag": tag, "count": cnt, "coverage_pct": round(coverage, 1),
            "symbol_coverage_pct": round(sym_cover, 1),
            "symbols_sample": sorted(per_symbol[tag])[:8],
        })

    # M1-oncelikli desenler ilk sirada
    m1_tags = [p for p in pattern_summary if p["tag"].startswith("m1_")]
    other_tags = [p for p in pattern_summary if not p["tag"].startswith("m1_")]

    print("\n" + "=" * 70)
    print(f"M1 ONCESI (10 M1) DESENLER - {n} yukselis, {n_uniq_sym} sembol")
    print("=" * 70)
    for p in m1_tags[:30]:
        bar = "█" * int(p["coverage_pct"] / 4)
        print(f"  {p['tag']:<30} %{p['coverage_pct']:>5.1f} cov | sembol %{p['symbol_coverage_pct']:>4.1f} {bar}")

    print("\n" + "=" * 70)
    print("M5 ONCESI/IKINCIL DESENLER")
    print("=" * 70)
    for p in other_tags[:20]:
        bar = "█" * int(p["coverage_pct"] / 4)
        print(f"  {p['tag']:<30} %{p['coverage_pct']:>5.1f} cov | sembol %{p['symbol_coverage_pct']:>4.1f} {bar}")

    # Rapor kismi olarak kaydet
    summary_out = {
        "n_risers": n,
        "n_symbols": n_uniq_sym,
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "patterns": pattern_summary,
        "top_m1": m1_tags[:40],
        "top_m5": other_tags[:30],
    }
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "pattern_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary_out, f, ensure_ascii=False, indent=1)
    # Snapshotlari da kaydet (buyuk olabilir)
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "m5_m1_snapshots.json"), "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, default=str)
    print(f"\nKaydedildi: pattern_summary.json, m5_m1_snapshots.json")
    conn.close()


if __name__ == "__main__":
    main()