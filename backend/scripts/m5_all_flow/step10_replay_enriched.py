#!/usr/bin/env python3
"""
step10 - Zengin cok-gostergeli desen + coklu hedef (%1/1.5/2) 24s replay.

On bulgulara ek GOSTERGELER.HTML'den eklenenler:
  MACD (histogram)      : momentum teyidi (GP'de kullaniliyor)
  Fisher Transform      : keskin donus sinyali
  SuperTrend            : ATR tabanli trend + trailing seviye
  OBV (slope)           : hacim akisi guveni
  Volume Oscillator     : kisa/uzun hacim ort farki (hacim momentumu)
+ onceki: ATR%, Bollinger, RSI, CMO, ROC, Stoch, ADX, Vortex, MFI, VWAP, PSAR, EMA

Hedefler: sinyal anindan sonraki 6dk icinde max high >= giris*(1+target).
Bagimsiz olarak %1.0, %1.5, %2.0 icin basari orani + lift.
Engelleyiciler dahil (negatif agirlik). 24s replay, son 6s haric.
"""

import json
import math
import os
import sys
import time
from collections import defaultdict

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

TARGETS = (1.0, 1.5, 2.0)
MIN_SCORE = 2.5
TEST_HOURS = 24
EXCLUDE_LAST_HOURS = 6

# Genisletilmis desen agirliklari
WEIGHTS = {
    # Pozitif / ongoru
    "m5g1_roc_up": 3.0, "m5g1_chg_up": 2.0, "m1g1_atr_high": 2.0, "m1g1_atr_very_high": 2.5,
    "m5g1_stoch_high": 1.0, "m5g1_cmo_pos": 1.0, "m5g1_vwap_above": 1.0,
    "m5g1_ema_bull": 1.0, "m5g1_vortex_bull": 1.0, "m5g1_psar_bull": 1.0,
    "m5g2_roc_up": 1.5, "m1g2_atr_high": 1.0, "m5g1_chg3_up": 1.5, "m5g1_atr_very_high": 1.5,
    "m1g1_chg_up": 1.0, "m5g2_chg_up": 1.0,
    # YENI: MACD, Fisher, SuperTrend, OBV, VolOsc
    "m1g1_macd_bull": 1.0, "m5g1_macd_bull": 1.0,
    "m1g1_fisher_bull": 1.0, "m5g1_fisher_bull": 1.0,
    "m5g1_st_bull": 1.0, "m1g1_st_bull": 1.0,
    "m5g1_obv_up": 0.5, "m1g1_obv_up": 0.5,
    "m5g1_volosc_pos": 0.5, "m1g1_volosc_pos": 0.5,
    # Engelleyiciler
    "m5g0_chg_down": -3.0, "m5g0_bb_lower": -3.0, "m5g0_stoch_low": -3.0, "m5g0_rsi_low": -3.0,
    "m5g0_cmo_neg": -3.0, "m5g0_vol_low": -2.0, "m5g0_vortex_bear": -2.0, "m5g0_adx_weak": -2.0,
    "m5g0_vwap_below": -2.0, "m5g0_psar_bear": -2.0, "m5g0_chg3_down": -2.0, "m5g0_mfi_low": -2.0,
    "m1g1_mfi_low": -1.0, "m5g1_bb_lower": -1.0, "m5g1_stoch_low": -1.0,
    # YENI engelleyiciler
    "m5g0_macd_bear": -1.0, "m5g0_fisher_bear": -1.0, "m5g0_st_bear": -1.0,
}


# ---------- TEMEL GOSTERGELER ----------

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
    g = float(np.mean(np.maximum(ch, 0)))
    l = float(np.mean(np.maximum(-ch, 0)))
    if l == 0:
        return 100.0 if g > 0 else 50.0
    return float(100 - (100 / (1 + g / l)))


def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    return float(np.mean(trs))


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


def stoch(highs, lows, closes, period=14):
    if len(closes) < period:
        return None
    hi, lo = max(highs[-period:]), min(lows[-period:])
    return (closes[-1] - lo) / (hi - lo) * 100 if hi != lo else 50.0


def vortex(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    pvm = [abs(highs[i] - lows[i - 1]) for i in range(1, len(highs))]
    mvm = [abs(lows[i] - highs[i - 1]) for i in range(1, len(lows))]
    atr_v = atr(highs, lows, closes, period) or 1
    return {"plus_vi": float(np.sum(pvm[-period:]) / atr_v), "minus_vi": float(np.sum(mvm[-period:]) / atr_v)}


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


def bollinger_pos(closes, period=20):
    if len(closes) < period:
        return None
    w = np.asarray(closes[-period:], dtype=float)
    mid, std = float(np.mean(w)), float(np.std(w))
    upper, lower = mid + 2 * std, mid - 2 * std
    return (closes[-1] - lower) / (upper - lower) if upper != lower else 0.5


def vwap(highs, lows, closes, volumes):
    if len(closes) < 2 or sum(volumes) == 0:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    return sum(tp[i] * volumes[i] for i in range(len(closes))) / sum(volumes)


def psar(highs, lows):
    if len(highs) < 10:
        return None
    n = len(highs)
    uptrend = highs[1] > highs[0]
    ep = highs[0] if uptrend else lows[0]
    sar = lows[0] if uptrend else highs[0]
    af = 0.02
    for i in range(1, n):
        prev = sar
        sar = prev + af * (ep - prev)
        if uptrend and lows[i] < sar:
            uptrend = False; sar = ep; ep = lows[i]; af = 0.02
        elif not uptrend and highs[i] > sar:
            uptrend = True; sar = ep; ep = highs[i]; af = 0.02
        else:
            if uptrend and highs[i] > ep:
                ep = highs[i]; af = min(af + 0.02, 0.2)
            elif not uptrend and lows[i] < ep:
                ep = lows[i]; af = min(af + 0.02, 0.2)
    return "bullish" if uptrend else "bearish"


# ---------- YENI GOSTERGELER ----------

def macd_hist(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    line = [ef[i] - es[i] for i in range(len(closes)) if ef[i] is not None and es[i] is not None]
    if len(line) < signal:
        return None
    sig = ema_series(line, signal)
    cur = line[-1]
    s = sig[-1] if sig and sig[-1] is not None else cur
    return float(cur - s)


def fisher(highs, lows, length=9):
    """Fisher Transform (he: basitlestirilmis) - deger 0'un ustundeyse bull donem."""
    if len(highs) < length + 1:
        return None
    values = []
    prev = 0.0
    for i in range(length - 1, len(highs)):
        hi = max(highs[i - length + 1:i + 1])
        lo = min(lows[i - length + 1:i + 1])
        mid = (highs[i] + lows[i]) / 2
        ratio = (mid - lo) / (hi - lo) - 0.5 if hi != lo else 0.0
        val = max(-0.999, min(0.999, 0.66 * ratio + 0.67 * prev))
        fisher_v = 0.5 * math.log((1 + val) / (1 - val)) + 0.5 * prev
        values.append(fisher_v)
        prev = val
    return values[-1] if values else None


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
    return "bullish" if trend[-1] == 1 else "bearish"


def obv_slope(closes, volumes, period=5):
    if len(closes) < 2:
        return None
    obv = 0.0
    vals = []
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
        vals.append(obv)
    if len(vals) < period:
        return None
    return float(vals[-1] - vals[-period])


def vol_oscillator(volumes, short_p=10, long_p=20):
    if len(volumes) < long_p:
        return None
    s = float(np.mean(volumes[-short_p:]))
    l = float(np.mean(volumes[-long_p:]))
    if l == 0:
        return 0.0
    return (s - l) / l * 100


# ---------- SNAPSHOT + TAG ----------

def snapshot_tags(highs, lows, closes, volumes, gtag):
    tags = set()
    close = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    change3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0

    def add(n): tags.add(f"{gtag}_{n}")

    r = rsi(closes)
    if r is not None:
        if r >= 60: add("rsi_high")
        elif r <= 40: add("rsi_low")
        elif r <= 30: add("rsi_oversold")
    atp = (atr_v / close * 100) if atr_v and close else None
    if atp is not None and atp >= 0.5: add("atr_very_high")
    if atp is not None and atp >= 0.3: add("atr_high")
    if vol_ratio >= 1.2: add("vol_up")
    elif vol_ratio < 0.8: add("vol_low")
    if change5 >= 1: add("chg_up")
    elif change5 <= -1: add("chg_down")
    if change3 >= 0.5: add("chg3_up")
    elif change3 <= -0.5: add("chg3_down")
    cm = cmo(closes)
    if cm is not None:
        if cm >= 25: add("cmo_pos")
        elif cm <= -25: add("cmo_neg")
    rc = roc(closes)
    if rc is not None:
        if rc >= 5: add("roc_up")
        elif rc <= -5: add("roc_down")
    st = stoch(highs, lows, closes)
    if st is not None:
        if st >= 80: add("stoch_high")
        elif st <= 20: add("stoch_low")
    e9, e21 = ema_last(closes, 9), ema_last(closes, 21)
    if e9 and e21:
        add("ema_bull" if e9 > e21 else "ema_bear")
    a = adx(highs, lows, closes)
    if a:
        if a["adx"] >= 25: add("adx_trend")
        elif a["adx"] < 15: add("adx_weak")
    vx = vortex(highs, lows, closes)
    if vx:
        add("vortex_bull" if vx["plus_vi"] > vx["minus_vi"] else "vortex_bear")
    mf = mfi(highs, lows, closes, volumes)
    if mf is not None and mf >= 80: add("mfi_up")
    if mf is not None and mf <= 20: add("mfi_low")
    bp = bollinger_pos(closes)
    if bp is not None:
        if bp >= 0.8: add("bb_upper")
        elif bp <= 0.2: add("bb_lower")
    vw = vwap(highs, lows, closes, volumes)
    if vw:
        add("vwap_above" if close > vw else "vwap_below")
    pr = psar(highs, lows)
    if pr:
        add("psar_bull" if pr == "bullish" else "psar_bear")
    # YENI
    mh = macd_hist(closes)
    if mh is not None:
        add("macd_bull" if mh > 0 else "macd_bear")
    fv = fisher(highs, lows)
    if fv is not None:
        add("fisher_bull" if fv > 0 else "fisher_bear")
    st2 = supertrend(highs, lows, closes)
    if st2:
        add("st_bull" if st2 == "bullish" else "st_bear")
    ob = obv_slope(closes, volumes)
    if ob is not None:
        add("obv_up" if ob > 0 else "obv_down")
    vo = vol_oscillator(volumes)
    if vo is not None:
        add("volosc_pos" if vo > 0 else "volosc_neg")
    return tags


def get_pg():
    return psycopg.connect(os.environ["DATABASE_URL"])


def get_candles(conn, sym, tf, start_ms, end_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume FROM historical_candles
        WHERE symbol=%s AND timeframe=%s AND open_time>=%s AND open_time<=%s ORDER BY open_time ASC
    """, (sym, tf, int(start_ms), int(end_ms)))
    return [{"ts": r[0], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]


def main():
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='5m' ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]

    now_ms = int(time.time() * 1000)
    test_end = now_ms - EXCLUDE_LAST_HOURS * 3600000
    test_start = test_end - TEST_HOURS * 3600000
    print(f"Replay: {time.strftime('%m-%d %H:%M', time.localtime(test_start/1000))} -> "
          f"{time.strftime('%m-%d %H:%M', time.localtime(test_end/1000))} (son {EXCLUDE_LAST_HOURS}s haric)")

    M5_WARMUP = 3 * 3600000
    M1_WARMUP = 150 * 60000

    records = []
    for sym in symbols:
        m5_all = get_candles(conn, sym, "5m", test_start - M5_WARMUP - 600000, test_end)
        if len(m5_all) < 80:
            continue
        for k in range(30, len(m5_all) - 1):
            cur_ms = m5_all[k]["ts"]
            if not (test_start <= cur_ms <= test_end):
                continue
            prev_close = m5_all[k - 1]["c"]
            if not prev_close:
                continue
            entry_ref = prev_close

            m5_b = [c for c in m5_all[:k] if c["ts"] <= cur_ms]
            if len(m5_b) < 35:
                continue
            g2_candles = m5_b[:-2] if len(m5_b) > 3 else m5_b
            t1 = snapshot_tags([c["h"] for c in m5_b], [c["l"] for c in m5_b],
                               [c["c"] for c in m5_b], [c["v"] for c in m5_b], "m5g1")
            t2 = snapshot_tags([c["h"] for c in g2_candles], [c["l"] for c in g2_candles],
                               [c["c"] for c in g2_candles], [c["v"] for c in g2_candles], "m5g2")
            g0_candles = m5_b + [m5_all[k]]
            t0 = snapshot_tags([c["h"] for c in g0_candles], [c["l"] for c in g0_candles],
                               [c["c"] for c in g0_candles], [c["v"] for c in g0_candles], "m5g0")

            m1_all = get_candles(conn, sym, "1m", cur_ms - M1_WARMUP, cur_ms - 1)
            if len(m1_all) < 60:
                continue
            tm1 = snapshot_tags([c["h"] for c in m1_all], [c["l"] for c in m1_all],
                                [c["c"] for c in m1_all], [c["v"] for c in m1_all], "m1g1")
            prev10 = m1_all[-20:-10] if len(m1_all) >= 20 else m1_all[:-10]
            tm2 = snapshot_tags([c["h"] for c in prev10], [c["l"] for c in prev10],
                                [c["c"] for c in prev10], [c["v"] for c in prev10], "m1g2")

            all_tags = t1 | t2 | t0 | tm1 | tm2
            score = sum(WEIGHTS.get(t, 0) for t in all_tags)
            neg = sum(1 for t in all_tags if WEIGHTS.get(t, 0) < 0)
            if score < MIN_SCORE or neg > 0:
                continue

            # HEDEFLER: sonraki 6dk max high
            fut = get_candles(conn, sym, "1m", cur_ms, cur_ms + 6 * 60000)
            if len(fut) < 3:
                continue
            max_h = max(c["h"] for c in fut)
            upside = (max_h / entry_ref - 1) * 100 if entry_ref else 0
            rec = {"symbol": sym, "ts": cur_ms, "score": round(score, 2), "upside": round(upside, 3)}
            for tg in TARGETS:
                rec[f"hit{tg}"] = upside >= tg
            records.append(rec)

    conn.close()
    total = len(records)
    print(f"\n=== ZENGIN GOSTERGELI DESEN - 24s REPLAY ===")
    print(f"Sinyal: {total} (skor>={MIN_SCORE}, engelleyici yok)")

    # Baz oranlar (tum noktalarda hedef olasiligi)
    # Basit baz: bu pencere icindeki rise orani yukarida bilinmiyor; hesapla
    for tg in TARGETS:
        hits = sum(1 for r in records if r[f"hit{tg}"])
        print(f"\nHEDEF +%{tg}:  {hits}/{total} = %{hits/total*100:.2f}")
        # skor bandi
        for lo, hi in [(2.5, 4), (4, 6), (6, 9), (9, 100)]:
            band = [r for r in records if lo <= r["score"] < hi]
            if band:
                h = sum(1 for r in band if r[f"hit{tg}"])
                print(f"   skor[{lo}-{hi}): {len(band):>5} sin  %{h/len(band)*100:.2f}")

    # En iyi sinyaller
    print("\nTop sinyaller (upside sirali ilk 12):")
    top = sorted(records, key=lambda r: -r["upside"])[:12]
    for r in top:
        print(f"  {time.strftime('%m-%d %H:%M', time.localtime(r['ts']/1000))} {r['symbol']:<12} "
              f"skor={r['score']}  upside={r['upside']:+.2f}%")

    out = {"window": {"start": test_start, "end": test_end}, "n": total,
           "targets": {str(tg): {"hit": sum(1 for r in records if r[f"hit{tg}"]),
                                  "rate": sum(1 for r in records if r[f"hit{tg}"])/total*100 if total else 0} for tg in TARGETS}}
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "replay_zengin_desen_raporu.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nKaydedildi: replay_zengin_desen_raporu.json")


if __name__ == "__main__":
    main()