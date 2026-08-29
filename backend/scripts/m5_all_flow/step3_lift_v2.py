#!/usr/bin/env python3
"""
Zenginlestirilmis desen analizi (Adim 4-5 v2) - GOSTERGELER listesinden ek gostergeler.

Eklenen gostergeler (TradingView listesinden):
- Aroon             : trend baslangici/sonu + yatay ayirtimi
- Donchian          : kanal konum + breakout yakinligi
- StochRSI          : RSI'nin stokastigi (scalping icin hassas)
- TSI (True Strength): cift yumusatilmis momentum
- CMF (Chaikin MF)  : para akisi guveni
- Awesome (AO)      : orta fiyat momentumu (5/34)
- Keltner           : volatilite kanali (ATR tabanli, EMA ustune)
- Parabolic SAR     : trend yon + trailing seviyesi

Rise/control lift analizi: %2+ M5 yukselisi yapan anlar (rise) ile
yukselmeyen saat-basi anlar (control) karsilastirilir.
"""

import json
import math
import os
import sys
import time
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

_env = os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", ".env")
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

import psycopg

RISERS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "m5_risers.json")


# ---------------------------------------------------------------- CORE TAs (mevcut)

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


def sma(values, period):
    return float(np.mean(values[-period:])) if len(values) >= period else None


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    ch = np.diff(np.asarray(closes[-(period + 1):], dtype=float))
    gains = float(np.mean(np.maximum(ch, 0)))
    losses = float(np.mean(np.maximum(-ch, 0)))
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses)))


def stoch_rsi(closes, rsi_period=14, stoch_period=14, smooth=3):
    """RSI degerlerinin stokastigi (TradingView StochRSI benzeri)."""
    if len(closes) < rsi_period + stoch_period + 5:
        return None
    rsi_vals = []
    for i in range(rsi_period + 1, len(closes) + 1):
        r = rsi(closes[:i], rsi_period)
        if r is not None:
            rsi_vals.append(r)
    if len(rsi_vals) < stoch_period:
        return None
    out = []
    for i in range(stoch_period - 1, len(rsi_vals)):
        window = rsi_vals[i - stoch_period + 1:i + 1]
        lo, hi = min(window), max(window)
        out.append((rsi_vals[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k = float(np.mean(out[-smooth:]))
    return {"k": k}


def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    return float(np.mean(trs))


def aroon(highs, lows, period=25):
    """Aroon Up/Down (trend baslangici ve yatay tespit)."""
    if len(highs) < period + 1:
        return None
    win_h = highs[-(period + 1):]
    win_l = lows[-(period + 1):]
    hb = int(np.argmax(win_h))
    lb = int(np.argmin(win_l))
    aroon_up = (period - hb) / period * 100
    aroon_down = (period - lb) / period * 100
    return {"up": float(aroon_up), "down": float(aroon_down)}


def donchian(highs, lows, period=20):
    """Donchian Kanal (fiyatin kanal icindeki konumu)."""
    if len(highs) < period or len(lows) < period:
        return None
    upper = max(highs[-period:])
    lower = min(lows[-period:])
    close = highs[-1]  # referans
    pos = (close - lower) / (upper - lower) if upper != lower else 0.5
    return {"upper": upper, "lower": lower, "position": float(pos), "width_pct": (upper - lower) / lower * 100 if lower else 0}


def tsi(closes, long_period=25, short_period=13, signal_period=13):
    """True Strength Index (cift EMA yumusatilmis momentum)."""
    if len(closes) < long_period + short_period + signal_period:
        return None
    diffs = np.diff(np.asarray(closes, dtype=float))
    abs_diff = np.abs(diffs)
    d_ema = ema_series(list(diffs), long_period)
    ad_ema = ema_series(list(abs_diff), long_period)
    # ikinci yumusatma
    d2 = ema_series([v for v in d_ema if v is not None], short_period)
    ad2 = ema_series([v for v in ad_ema if v is not None], short_period)
    if not d2 or not ad2 or d2[-1] is None or ad2[-1] is None or ad2[-1] == 0:
        return None
    tsi_val = d2[-1] / ad2[-1] * 100
    return {"value": float(tsi_val)}


def cmf(highs, lows, closes, volumes, period=20):
    """Chaikin Money Flow (para akisi)."""
    if len(closes) < period:
        return None
    mfm = []
    for i in range(len(closes)):
        hl = highs[i] - lows[i]
        if hl == 0:
            mfm.append(0.0)
        else:
            mfm.append(((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl)
    mfv = [mfm[i] * volumes[i] for i in range(len(closes))]
    sum_mfv = sum(mfv[-period:])
    sum_vol = sum(volumes[-period:])
    return float(sum_mfv / sum_vol) if sum_vol > 0 else 0.0


def awesome(highs, lows, fast=5, slow=34):
    """Awesome Oscillator: ort (5) - ort (34)."""
    if len(highs) < slow:
        return None
    tp = [(highs[i] + lows[i]) / 2 for i in range(len(highs))]
    fast_v = sma(tp, fast)
    slow_v = sma(tp, slow)
    if fast_v is None or slow_v is None:
        return None
    return {"value": float(fast_v - slow_v)}


def keltner(highs, lows, closes, period=20, mult=2.0):
    """Keltner Kanal (EMA ort, ATR band)."""
    if len(closes) < period + 1:
        return None
    ema_center = ema_last(closes, period)
    atr_v = atr(highs, lows, closes, period)
    if ema_center is None or atr_v is None:
        return None
    upper, lower = ema_center + mult * atr_v, ema_center - mult * atr_v
    close = closes[-1]
    return {"position": (close - lower) / (upper - lower) if upper != lower else 0.5,
            "upper": upper, "lower": lower}


def psar(highs, lows, af_start=0.02, af_step=0.02, af_max=0.2):
    """Parabolic SAR (trend yon + seviye)."""
    if len(highs) < 10:
        return None
    uptrend = highs[-2] <= highs[1]  # baslangic yonunu tahmin
    trend = []
    sar_list = []
    af = af_start
    ep = highs[0] if True else lows[0]
    # basit ileri SAR
    n = len(highs)
    uptrend = highs[1] > highs[0]
    ep = highs[0] if uptrend else lows[0]
    sar = lows[0] if uptrend else highs[0]
    for i in range(1, n):
        prev_sar = sar
        if uptrend:
            sar = prev_sar + af * (ep - prev_sar)
            sar = min(sar, lows[i - 1] - (highs[i - 1] - lows[i - 1]) * 0.1) if i > 1 else sar
        else:
            sar = prev_sar + af * (ep - prev_sar)
            sar = max(sar, highs[i - 1] + (highs[i - 1] - lows[i - 1]) * 0.1) if i > 1 else sar
        if uptrend and lows[i] < sar:
            uptrend = False
            sar = ep
            ep = lows[i]
            af = af_start
        elif not uptrend and highs[i] > sar:
            uptrend = True
            sar = ep
            ep = highs[i]
            af = af_start
        else:
            if uptrend and highs[i] > ep:
                ep = highs[i]
                af = min(af + af_step, af_max)
            elif not uptrend and lows[i] < ep:
                ep = lows[i]
                af = min(af + af_step, af_max)
        sar_list.append(sar)
        trend.append(uptrend)
    return {"direction": "bullish" if trend[-1] else "bearish",
            "value": float(sar_list[-1])}


def vortex(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    pvm = [abs(highs[i] - lows[i - 1]) for i in range(1, len(highs))]
    mvm = [abs(lows[i] - highs[i - 1]) for i in range(1, len(lows))]
    atr_v = atr(highs, lows, closes, period) or 1
    return {"plus_vi": float(np.sum(pvm[-period:]) / atr_v), "minus_vi": float(np.sum(mvm[-period:]) / atr_v)}


def vwap(highs, lows, closes, volumes):
    if len(closes) < 2 or sum(volumes) == 0:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    return sum(tp[i] * volumes[i] for i in range(len(closes))) / sum(volumes)


def fvg_detection(closes, highs, lows):
    if len(closes) < 3:
        return {"bull_fvg": False, "bear_fvg": False}
    return {"bull_fvg": bool(lows[-1] > highs[-3]), "bear_fvg": bool(highs[-1] < lows[-3])}


# ---------------------------------------------------------------- BUILD SNAPSHOT (genisletilmis)

def build_snapshot(highs, lows, closes, volumes):
    out = {"price": {}, "trend": {}, "momentum": {}, "volume": {}, "extra": {}}
    close = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    change10 = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 else 0

    out["price"] = {
        "close": close, "atr_pct": (atr_v / close * 100) if atr_v and close else None,
        "vol_ratio": vol_ratio, "change5": change5, "change10": change10,
    }
    e9, e21 = ema_last(closes, 9), ema_last(closes, 21)
    if e9 and e21:
        out["trend"]["ema_alignment"] = "bullish" if e9 > e21 else "bearish"
    # Aroon
    ar = aroon(highs, lows)
    if ar:
        out["extra"]["aroon"] = {"up": round(ar["up"], 1), "down": round(ar["down"], 1)}
    # Donchian
    dc = donchian(highs, lows)
    if dc:
        out["extra"]["donchian"] = {"position": round(dc["position"], 3), "width_pct": round(dc["width_pct"], 2)}
    # Keltner
    kelt = keltner(highs, lows, closes)
    if kelt:
        out["extra"]["keltner"] = {"position": round(kelt["position"], 3)}
    # Parabolic SAR
    ps = psar(highs, lows)
    if ps:
        out["extra"]["psar"] = {"direction": ps["direction"]}
    # StochRSI
    srsi = stoch_rsi(closes)
    if srsi:
        out["momentum"]["stoch_rsi"] = round(srsi["k"], 1)
    # TSI
    tsi_v = tsi(closes)
    if tsi_v:
        out["momentum"]["tsi"] = round(tsi_v["value"], 2)
    # Awesome
    ao = awesome(highs, lows)
    if ao:
        out["momentum"]["awesome"] = round(ao["value"], 5)
    # CMF (volume)
    cmf_v = cmf(highs, lows, closes, volumes)
    if cmf_v is not None:
        out["volume"]["cmf"] = round(cmf_v, 4)
    # RSI, CMO, ROC
    r = rsi(closes)
    if r: out["momentum"]["rsi"] = round(r, 1)
    ch = np.diff(closes[-10:]) if len(closes) >= 10 else np.diff(closes)
    cmo_v = float(100 * (np.sum(np.maximum(ch, 0)) - np.sum(np.maximum(-ch, 0))) / (np.sum(np.maximum(ch, 0)) + np.sum(np.maximum(-ch, 0)))) if len(ch) else 0
    out["momentum"]["cmo"] = round(cmo_v, 1)
    if len(closes) >= 11:
        out["momentum"]["roc"] = round((closes[-1] - closes[-11]) / closes[-11] * 100, 2)
    vw = vwap(highs, lows, closes, volumes)
    if vw:
        out["volume"]["vwap_dist_pct"] = round((close / vw - 1) * 100, 2)
    vx = vortex(highs, lows, closes)
    if vx:
        out["volume"]["vortex_bull"] = vx["plus_vi"] > vx["minus_vi"]
    out["fvg"] = fvg_detection(closes, highs, lows)
    return out


# ---------------------------------------------------------------- TAG EXTRACTION (genisletilmis)

def extract_tags(snap):
    tags = set()
    p = snap.get("price", {})
    m = snap.get("momentum", {})
    v = snap.get("volume", {})
    t = snap.get("trend", {})
    ex = snap.get("extra", {})

    def add(name):
        tags.add(f"m1_{name}")

    # Fiyat / volatilite
    atr_pct = p.get("atr_pct")
    if atr_pct is not None and atr_pct >= 0.3: add("atr_high")
    elif atr_pct is not None and atr_pct < 0.15: add("atr_low")
    vr = p.get("vol_ratio")
    if vr is not None:
        if vr >= 1.5: add("vol_spike_strong")
        elif vr < 0.7: add("vol_low")
    ch5 = p.get("change5")
    if ch5 is not None:
        if ch5 >= 1: add("price_rising")
        elif ch5 <= -1: add("price_falling")
    ch10 = p.get("change10")
    if ch10 is not None and ch10 >= 2: add("move_10m_up")
    if ch10 is not None and ch10 <= -2: add("move_10m_down")

    # Momentum
    rsi_v = m.get("rsi")
    if rsi_v is not None:
        if rsi_v >= 70: add("rsi_overbought")
        elif rsi_v >= 55: add("rsi_strong")
        elif rsi_v <= 30: add("rsi_oversold")
    srsi_v = m.get("stoch_rsi")
    if srsi_v is not None:
        if srsi_v >= 80: add("stochrsi_overbought")
        elif srsi_v <= 20: add("stochrsi_oversold")
    cmo_v = m.get("cmo")
    if cmo_v is not None:
        if cmo_v >= 25: add("cmo_bull")
        elif cmo_v <= -25: add("cmo_bear")
    roc_v = m.get("roc")
    if roc_v is not None:
        if roc_v >= 5: add("roc_up")
        elif roc_v <= -5: add("roc_down")
    tsi_v = m.get("tsi")
    if tsi_v is not None:
        add("tsi_bull" if tsi_v > 0 else "tsi_bear")
    ao_v = m.get("awesome")
    if ao_v is not None:
        add("ao_bull" if ao_v > 0 else "ao_bear")

    # Volume / akis
    cmf_v = v.get("cmf")
    if cmf_v is not None:
        if cmf_v > 0.05: add("cmf_positive")
        elif cmf_v < -0.05: add("cmf_negative")
    vw = v.get("vwap_dist_pct")
    if vw is not None:
        add("vwap_above" if vw > 0 else "vwap_below")
    if v.get("vortex_bull") is not None:
        add("vortex_bull" if v["vortex_bull"] else "vortex_bear")

    # Trend / yapi
    if t.get("ema_alignment") == "bullish": add("ema_bull")
    elif t.get("ema_alignment") == "bearish": add("ema_bear")
    ar = ex.get("aroon")
    if ar:
        if ar["up"] >= 70 and ar["up"] > ar["down"]: add("aroon_bull")
        elif ar["down"] >= 70 and ar["down"] > ar["up"]: add("aroon_bear")
    dc = ex.get("donchian")
    if dc and dc["position"] is not None:
        if dc["position"] >= 0.9: add("donchian_upper")
        elif dc["position"] <= 0.1: add("donchian_lower")
    kelt = ex.get("keltner")
    if kelt and kelt["position"] is not None:
        if kelt["position"] >= 0.9: add("keltner_upper")
        elif kelt["position"] <= 0.1: add("keltner_lower")
    ps = ex.get("psar")
    if ps:
        add("psar_bull" if ps["direction"] == "bullish" else "psar_bear")
    if snap.get("fvg", {}).get("bull_fvg"): add("fvg_bull")
    if snap.get("fvg", {}).get("bear_fvg"): add("fvg_bear")
    return tags


# ---------------------------------------------------------------- DB

def get_pg():
    return psycopg.connect(os.environ["DATABASE_URL"])


def get_candles(conn, sym, tf, start_ms, end_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume
        FROM historical_candles WHERE symbol=%s AND timeframe=%s AND open_time>=%s AND open_time<=%s
        ORDER BY open_time ASC
    """, (sym, tf, int(start_ms), int(end_ms)))
    return [{"ts": r[0], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]


# ---------------------------------------------------------------- MAIN

def main():
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='1m' ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]
    print(f"Sembol sayisi: {len(symbols)}")

    # Rise anlari: %2+ M5 yukselisi (5m dataframe, onceki kapanisa gore)
    risers = []
    for sym in symbols:
        cur.execute("""
            SELECT open_time, high, low, close FROM historical_candles
            WHERE symbol=%s AND timeframe='5m' ORDER BY open_time ASC
        """, (sym,))
        rows = cur.fetchall()
        for i in range(3, len(rows) - 1):
            prev_close = rows[i - 1][3]
            if not prev_close:
                continue
            rise = (rows[i][3] - prev_close) / prev_close * 100
            if rise >= 2.0:
                risers.append({"symbol": sym, "ts": rows[i][0]})
    print(f"Rise ani: {len(risers)}")

    # Rise zamanlari seti (symbol, ts)
    rise_set = {(r["symbol"], r["ts"]) for r in risers}

    WARMUP_MS = 90 * 60 * 1000
    # M5 mumlarini da sym bazinda once cek (kontrol secimi icin)
    m5_by_sym = {}
    for sym in symbols:
        cur.execute("""
            SELECT open_time FROM historical_candles WHERE symbol=%s AND timeframe='5m' ORDER BY open_time
        """, (sym,))
        m5_by_sym[sym] = [r[0] for r in cur.fetchall()]

    counters = {"rise": Counter(), "control": Counter()}
    proc = {"rise": 0, "control": 0}
    sample_every = 12  # kontrol: saat basi

    for sym in symbols:
        # tum M1 (son 12 saat, warmup icin)
        cur.execute("""
            SELECT open_time, high, low, close, volume FROM historical_candles
            WHERE symbol=%s AND timeframe='1m' ORDER BY open_time ASC
        """, (sym,))
        m1_rows = [{"ts": r[0], "h": r[1], "l": r[2], "c": r[3], "v": r[4]} for r in cur.fetchall()]
        if len(m1_rows) < 60:
            continue
        ts_idx = {c["ts"]: i for i, c in enumerate(m1_rows)}

        # Rise anlari
        for r in risers:
            if r["symbol"] != sym:
                continue
            i = ts_idx.get(r["ts"])
            if i is None or i < 40:
                continue
            window = m1_rows[max(0, i - 89):i]
            if len(window) < 30:
                continue
            snap = build_snapshot([c["h"] for c in window], [c["l"] for c in window],
                                  [c["c"] for c in window], [c["v"] for c in window])
            tags = extract_tags(snap)
            for t in tags:
                counters["rise"][t] += 1
            proc["rise"] += 1

        # Kontrol anlari (rise degilse saat basi)
        ctrl_marks = [t for t in m5_by_sym.get(sym, []) if (sym, t) not in rise_set]
        for k, ctrl_ts in enumerate(ctrl_marks):
            if k % sample_every != 0:
                continue
            i = ts_idx.get(ctrl_ts)
            if i is None or i < 40:
                continue
            window = m1_rows[max(0, i - 89):i]
            if len(window) < 30:
                continue
            snap = build_snapshot([c["h"] for c in window], [c["l"] for c in window],
                                  [c["c"] for c in window], [c["v"] for c in window])
            tags = extract_tags(snap)
            for t in tags:
                counters["control"][t] += 1
            proc["control"] += 1

    print(f"Rise: {proc['rise']} | Control: {proc['control']}")

    # Lift hesapla
    r_total = proc["rise"]
    c_total = proc["control"]
    comp = []
    all_tags = set(counters["rise"]) | set(counters["control"])
    for tag in all_tags:
        r_cov = counters["rise"][tag] / r_total * 100 if r_total else 0
        c_cov = counters["control"][tag] / c_total * 100 if c_total else 0
        lift = (r_cov / c_cov) if c_cov > 0 else (99.0 if r_cov > 0 else 0)
        comp.append({"tag": tag, "rise_cov_pct": round(r_cov, 1), "control_cov_pct": round(c_cov, 1),
                     "lift": round(lift, 2), "abs_diff_pct": round(r_cov - c_cov, 1)})
    comp.sort(key=lambda x: -x["lift"])

    print("\n=== RISE vs CONTROL (yeni gostergelerle) ===")
    print(f"{'tag':<30}{'rise%':>8}{'ctrl%':>8}{'lift':>7}{'abs':>8}")
    print("-" * 60)
    for c in comp[:45]:
        print(f"{c['tag']:<30}{c['rise_cov_pct']:>8.1f}{c['control_cov_pct']:>8.1f}{c['lift']:>7.2f}{c['abs_diff_pct']:>8.1f}")

    out = {"rise_n": proc["rise"], "control_n": proc["control"], "comparison": comp}
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "pattern_lift_v2_report.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nKaydedildi: pattern_lift_v2_report.json")
    conn.close()


if __name__ == "__main__":
    main()