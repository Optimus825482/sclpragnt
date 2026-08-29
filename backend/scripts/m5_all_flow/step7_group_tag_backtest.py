#!/usr/bin/env python3
"""
TUM GRUPLARDA desen tespiti + her deseni ayri ayri backtest.

Gruplar:
  M5 G0: yukselisin basladigi M5 (rise aninda butun gecmis - AYNI AN)
  M5 G1: rise oncesi M5 (rise-5dk'ya kadar) - ONGORU ADAYI
  M5 G2: rise oncesi 10dk (rise-10dk'ya kadar) - ONGORU ADAYI
  M1 G1: rise oncesi 10 M1 (rise-10dk..rise) - ONGORU ADAYI
  M1 G2: rise oncesi 20-10 M1 (rise-20dk..rise-10dk) - ONGORU ADAYI

Her grup icin snapshot tagleri cikarilir. Sonra HER TAG ayri ayri backtest edilir:
  - O tag, rise-1dk oncesinde TRUE ise sinyal
  - Hedef: sonraki 6dk icinde +%1 yukselme
  - Basari orani, sinyal sayisi, baz orana gore lift raporlanir
  - Gurp adiyla etiketlenir (m5g1_rsi_low gibi)

Ayrica GRUP-ONCELIKLI desenler: 'o grupta AYNI ANDA kac tag aktif' skoru da test edilir.
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

RISE_PCT = 2.0
TARGET_UP_PCT = 1.0
FORECAST_WINDOW_MS = 6 * 60 * 1000
MIN_SAMPLES = 40


# ---- GOSTERGELER (ortak, M5/M1) ----

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


def snapshot_for(highs, lows, closes, volumes):
    snap = {}
    close = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    change3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0
    e9, e21 = ema_last(closes, 9), ema_last(closes, 21)
    align = "bullish" if (e9 and e21 and e9 > e21) else ("bearish" if (e9 and e21) else "unknown")
    snap["rsi"] = rsi(closes)
    snap["atr_pct"] = (atr_v / close * 100) if atr_v and close else None
    snap["vol_ratio"] = round(vol_ratio, 3)
    snap["change5"] = round(change5, 3)
    snap["change3"] = round(change3, 3)
    snap["cmo"] = cmo(closes)
    snap["roc"] = roc(closes)
    snap["stoch"] = stoch(highs, lows, closes)
    snap["ema_align"] = align
    a = adx(highs, lows, closes)
    snap["adx"] = a["adx"] if a else None
    vx = vortex(highs, lows, closes)
    snap["vortex_bull"] = (vx["plus_vi"] > vx["minus_vi"]) if vx else None
    snap["mfi"] = mfi(highs, lows, closes, volumes)
    snap["bb_pos"] = bollinger_pos(closes)
    vw = vwap(highs, lows, closes, volumes)
    snap["vwap_dist_pct"] = (close / vw - 1) * 100 if vw else None
    pr = psar(highs, lows)
    snap["psar_bull"] = (pr == "bullish") if pr else None
    return snap


def tags_from(snap):
    tags = set()
    def add(n): tags.add(n)
    r = snap["rsi"]
    if r is not None:
        if r >= 60: add("rsi_high")
        elif r <= 40: add("rsi_low")
        elif r <= 30: add("rsi_oversold")
    at = snap["atr_pct"]
    if at is not None and at >= 0.3: add("atr_high")
    if at is not None and at >= 0.5: add("atr_very_high")
    vr = snap["vol_ratio"]
    if vr is not None:
        if vr >= 1.2: add("vol_up")
        elif vr < 0.8: add("vol_low")
    c5 = snap["change5"]
    if c5 is not None:
        if c5 >= 1: add("chg_up")
        elif c5 <= -1: add("chg_down")
    c3 = snap["change3"]
    if c3 is not None and c3 >= 0.5: add("chg3_up")
    if c3 is not None and c3 <= -0.5: add("chg3_down")
    cm = snap["cmo"]
    if cm is not None:
        if cm >= 25: add("cmo_pos")
        elif cm <= -25: add("cmo_neg")
    rc = snap["roc"]
    if rc is not None and rc >= 5: add("roc_up")
    if rc is not None and rc <= -5: add("roc_down")
    st = snap["stoch"]
    if st is not None:
        if st >= 80: add("stoch_high")
        elif st <= 20: add("stoch_low")
    if snap["ema_align"] == "bullish": add("ema_bull")
    elif snap["ema_align"] == "bearish": add("ema_bear")
    ad = snap["adx"]
    if ad is not None:
        if ad >= 25: add("adx_trend")
        elif ad < 15: add("adx_weak")
    vb = snap["vortex_bull"]
    if vb is not None: add("vortex_bull" if vb else "vortex_bear")
    mf = snap["mfi"]
    if mf is not None and mf >= 80: add("mfi_up")
    if mf is not None and mf <= 20: add("mfi_low")
    bp = snap["bb_pos"]
    if bp is not None:
        if bp >= 0.8: add("bb_upper")
        elif bp <= 0.2: add("bb_lower")
    vw = snap["vwap_dist_pct"]
    if vw is not None: add("vwap_above" if vw > 0 else "vwap_below")
    pb = snap["psar_bull"]
    if pb is not None: add("psar_bull" if pb else "psar_bear")
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

    # RISE yok: tum M5 kapanislarinda (2 saat pencerede 5dk aralik) ornekle
    # Her M5 kapanisi icin grup snapshot'lari + hedef (+%1, 6dk icinde)
    print("TUM M5 kapanislarinda ornekleme (rise sarti yok)")

    M5_WARMUP = 3 * 3600000
    M1_WARMUP = 150 * 60000
    SAMPLE_EVERY = 6  # her 6. M5 (30dk) -> kontrol yogunlugu

    records = []
    total_scanned = 0
    for sym in symbols:
        # M5 kapanislarini cek (son 12 saat)
        m5_all = get_candles(conn, sym, "5m", int(time.time() * 1000) - 12 * 3600000, int(time.time() * 1000))
        if len(m5_all) < 60:
            continue
        # ornekle
        for k in range(20, len(m5_all) - 2, SAMPLE_EVERY):
            rise_ms = m5_all[k]["ts"]
            total_scanned += 1
            # M5 gecmisi (warmup)
            m5 = get_candles(conn, sym, "5m", rise_ms - M5_WARMUP, rise_ms - 1000)
            if len(m5) < 35:
                continue
            m5_before = [c for c in m5 if c["ts"] < rise_ms]
            if not m5_before:
                continue
            g1_m5 = m5_before
            g2_m5 = m5_before[:-2] if len(m5_before) > 3 else m5_before
            m5_rise = get_candles(conn, sym, "5m", rise_ms - M5_WARMUP, rise_ms + 300000)
            m5_g0 = [c for c in m5_rise if c["ts"] <= rise_ms]
            if len(m5_g0) < 30:
                continue

            s_g0 = snapshot_for([c["h"] for c in m5_g0], [c["l"] for c in m5_g0],
                                [c["c"] for c in m5_g0], [c["v"] for c in m5_g0])
            s_g1 = snapshot_for([c["h"] for c in g1_m5], [c["l"] for c in g1_m5],
                                [c["c"] for c in g1_m5], [c["v"] for c in g1_m5])
            s_g2 = snapshot_for([c["h"] for c in g2_m5], [c["l"] for c in g2_m5],
                                [c["c"] for c in g2_m5], [c["v"] for c in g2_m5])

            forecast_ms = rise_ms - 60000
            m1_all = get_candles(conn, sym, "1m", rise_ms - M1_WARMUP, forecast_ms - 1)
            if len(m1_all) < 60:
                continue
            s_m1g1 = snapshot_for([c["h"] for c in m1_all], [c["l"] for c in m1_all],
                                  [c["c"] for c in m1_all], [c["v"] for c in m1_all])
            s_m1g2 = snapshot_for([c["h"] for c in m1_all[:-10]], [c["l"] for c in m1_all[:-10]],
                                  [c["c"] for c in m1_all[:-10]], [c["v"] for c in m1_all[:-10]])

            tags = {
                "m5g0": {f"m5g0_{t}" for t in tags_from(s_g0)},
                "m5g1": {f"m5g1_{t}" for t in tags_from(s_g1)},
                "m5g2": {f"m5g2_{t}" for t in tags_from(s_g2)},
                "m1g1": {f"m1g1_{t}" for t in tags_from(s_m1g1)},
                "m1g2": {f"m1g2_{t}" for t in tags_from(s_m1g2)},
            }

            f_price = m1_all[-1]["c"]
            fut = get_candles(conn, sym, "1m", rise_ms, rise_ms + FORECAST_WINDOW_MS)
            if len(fut) < 3:
                continue
            max_h = max(c["h"] for c in fut)
            upside = (max_h - f_price) / f_price * 100 if f_price else 0
            hit = upside >= TARGET_UP_PCT
            # rise bilgisi (bu nokta bir %2 rise miydi? tanim)
            is_rise = (m5_g0[-1]["c"] - m5_g0[-2]["c"]) / m5_g0[-2]["c"] * 100 >= RISE_PCT if len(m5_g0) >= 2 and m5_g0[-2]["c"] else False
            records.append({"symbol": sym, "ts": rise_ms, "tags": tags, "hit": hit,
                            "upside": upside, "is_rise": is_rise})

    print(f"Tarama: {total_scanned} | Kayit: {len(records)}")

    base = sum(1 for r in records if r["hit"]) / len(records) * 100 if records else 0
    print(f"Baz oran (tum noktalarda +%1 6dk): %{base:.1f}")

    # Rise olan/olmayan alt kume
    rise_recs = [r for r in records if r["is_rise"]]
    nonrise = [r for r in records if not r["is_rise"]]
    if rise_recs:
        print(f"Rise alt kume: {len(rise_recs)} | isabet %{sum(1 for r in rise_recs if r['hit'])/len(rise_recs)*100:.1f}")
    if nonrise:
        print(f"Rise-disi alt kume: {len(nonrise)} | isabet %{sum(1 for r in nonrise if r['hit'])/len(nonrise)*100:.1f}")

    # ---- HER GRUP x TAG ----
    print("\n=== GRUP x TAG (tum noktalarda) ===")
    tag_stats = defaultdict(lambda: {"n": 0, "hit": 0})
    for r in records:
        for gtags in r["tags"].values():
            for t in gtags:
                tag_stats[t]["n"] += 1
                if r["hit"]:
                    tag_stats[t]["hit"] += 1

    results = []
    for t, s in tag_stats.items():
        if s["n"] < MIN_SAMPLES:
            continue
        acc = s["hit"] / s["n"] * 100
        lift = acc / base if base else 0
        results.append({"tag": t, "n": s["n"], "acc_pct": round(acc, 1), "lift": round(lift, 2)})
    results.sort(key=lambda x: -x["lift"])

    print(f"{'dashboard':<24}{'n':>6}{'acc%':>8}{'lift':>7}")
    print("-" * 46)
    for x in results[:30]:
        print(f"{x['tag']:<24}{x['n']:>6}{x['acc_pct']:>8.1f}{x['lift']:>7.2f}")

    print("\n=== EN KOTU ===")
    for x in results[-15:]:
        print(f"{x['tag']:<24}{x['n']:>6}{x['acc_pct']:>8.1f}{x['lift']:>7.2f}")

    out = {"base_rate_pct": round(base, 2), "n": len(records), "tag_results": results}
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "grup_desen_backtest_raporu.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nKaydedildi: grup_desen_backtest_raporu.json")
    conn.close()


if __name__ == "__main__":
    main()