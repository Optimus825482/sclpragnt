#!/usr/bin/env python3
"""
%2+ M5 RISE ONGORU - tum snapshot gruplarinda desen analizi.

Hedef: "Bir sonraki M5 mumunun kapanisi, bir onceki M5 kapanisina gore
en az %2 yukselecek mi?" - rise +5dk oncesine kadar OLAN verilerle
(lookahead yok) tahmin.

Gruplar (her biri 'o ana kadar kapanmis gecmis' ile gosterge):
  m5_g0: rise M5 mumu baslangici (rise-5dk .. rise anina kadar) - PRATIKTE SINYAL ANI
  m5_g1: rise oncesi (rise-10dk .. rise-5dk) - ONGORU
  m5_g2: rise oncesi iki mum (rise-15dk .. rise-10dk) - ONGORU
  m1_g1: rise-10dk .. rise-5dk arasi 10 M1 (rise-1dk oncesi) - ONGORU
  m1_g2: ondan onceki 10 M1 - ONGORU

Her grup:tag icin tum M5 kapanislarinda sinyal ara ve hedef rise P(dogruluk)
baz orana gore lift raporla. Rise-disi kontrol ile karsilastir.
"""

import json
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

RISE_PCT = 2.0
MIN_SAMPLES = 60


# ---- GOSTERGELER (ortak set) ----

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

    M5_WARMUP = 3 * 3600000
    M1_WARMUP = 150 * 60000
    SAMPLE_EVERY = 1  # tum M5 kapanislari

    records = []
    for sym in symbols:
        m5_all = get_candles(conn, sym, "5m", int(time.time() * 1000) - 12 * 3600000, int(time.time() * 1000))
        if len(m5_all) < 80:
            continue
        for k in range(30, len(m5_all) - 1, SAMPLE_EVERY):
            cur_ms = m5_all[k]["ts"]
            # HEDEF: bu M5 (k) kapanisina gore bir SONRAKI M5 (k+1) kapanisinda %2+?
            prev_close = m5_all[k - 1]["c"]
            next_close = m5_all[k + 1]["c"]
            if not prev_close:
                continue
            rise = (next_close - prev_close) / prev_close * 100
            # her M5 kapanisinda sinyal: cur_ms + sonraki 10dk ongoru
            # Goruntuleme: cur_ms+5dk (bir sonraki mum) hedef; cur_ms'ye kadar veri kullan
            m5 = get_candles(conn, sym, "5m", cur_ms - M5_WARMUP, cur_ms)
            if len(m5) < 35:
                continue
            m5_b = [c for c in m5 if c["ts"] <= cur_ms]
            # G1 (ongoru): cur_ms oncesi butun gecmis; G2: son 2 cikar; G0: cur_ms+5dk (near-real sinyal ani)
            g1_candles = m5_b
            g2_candles = m5_b[:-2] if len(m5_b) > 3 else m5_b
            g0_candles = m5_b + [{"ts": cur_ms + 300000, "h": m5_all[k + 1]["h"], "l": m5_all[k + 1]["l"],
                                  "c": m5_all[k + 1]["c"], "v": m5_all[k + 1]["v"]}]
            s_g0 = snapshot_for([c["h"] for c in g0_candles], [c["l"] for c in g0_candles],
                                [c["c"] for c in g0_candles], [c["v"] for c in g0_candles])
            s_g1 = snapshot_for([c["h"] for c in g1_candles], [c["l"] for c in g1_candles],
                                [c["c"] for c in g1_candles], [c["v"] for c in g1_candles])
            s_g2 = snapshot_for([c["h"] for c in g2_candles], [c["l"] for c in g2_candles],
                                [c["c"] for c in g2_candles], [c["v"] for c in g2_candles])

            m1_all = get_candles(conn, sym, "1m", cur_ms - M1_WARMUP, cur_ms - 1)
            if len(m1_all) < 60:
                continue
            s_m1g1 = snapshot_for([c["h"] for c in m1_all], [c["l"] for c in m1_all],
                                  [c["c"] for c in m1_all], [c["v"] for c in m1_all])
            prev10 = m1_all[-20:-10] if len(m1_all) >= 20 else m1_all[:-10]
            s_m1g2 = snapshot_for([c["h"] for c in prev10], [c["l"] for c in prev10],
                                  [c["c"] for c in prev10], [c["v"] for c in prev10])

            tags = {
                "m5g0": {f"m5g0_{t}" for t in tags_from(s_g0)},
                "m5g1": {f"m5g1_{t}" for t in tags_from(s_g1)},
                "m5g2": {f"m5g2_{t}" for t in tags_from(s_g2)},
                "m1g1": {f"m1g1_{t}" for t in tags_from(s_m1g1)},
                "m1g2": {f"m1g2_{t}" for t in tags_from(s_m1g2)},
            }
            hit = rise >= RISE_PCT
            records.append({"symbol": sym, "ts": cur_ms, "tags": tags, "hit": hit, "rise": rise})

    print(f"Nokta: {len(records)} | baz rise orani: %{sum(1 for r in records if r['hit'])/len(records)*100:.2f}")

    base = sum(1 for r in records if r["hit"]) / len(records) * 100 if records else 0

    # ---- GRUP x TAG accuracy/lift ----
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
        results.append({"tag": t, "n": s["n"], "acc_pct": round(acc, 2), "lift": round(lift, 2)})
    results.sort(key=lambda x: -x["lift"])

    print(f"\n=== GRUP x TAG (RISE %2 FONKSIYONUNDAN ONCE) ===")
    print(f"{'tag':<26}{'n':>7}{'acc%':>8}{'lift':>7}")
    print("-" * 48)
    for x in results[:40]:
        print(f"{x['tag']:<26}{x['n']:>7}{x['acc_pct']:>8.2f}{x['lift']:>7.2f}")

    print("\n=== EN DUSUK (engelleyici) ===")
    for x in results[-20:]:
        print(f"{x['tag']:<26}{x['n']:>7}{x['acc_pct']:>8.2f}{x['lift']:>7.2f}")

    # ---- M5 & M1 BIRLIKTE (confluence) ----
    print("\n=== M5 AND M1 BIRLIKTE (ongoru gruplari) ===")
    combo = defaultdict(lambda: {"n": 0, "hit": 0})
    for r in records:
        # ongoru gruplari: m5g1, m5g2, m1g1, m1g2 (g0 disi)
        for t5 in r["tags"]["m5g1"] | r["tags"]["m5g2"]:
            for t1 in r["tags"]["m1g1"] | r["tags"]["m1g2"]:
                key = (t5, t1)
                combo[key]["n"] += 1
                if r["hit"]:
                    combo[key]["hit"] += 1
    combos = [(k, v["n"], v["hit"]) for k, v in combo.items() if v["n"] >= 50]
    combos.sort(key=lambda x: -(x[2] / x[1]))
    print(f"{'M5':<24}{'M1':<24}{'n':>6}{'acc%':>8}")
    print("-" * 62)
    for (t5, t1), n, h in combos[:30]:
        print(f"{t5:<24}{t1:<24}{n:>6}{h/n*100:>8.2f}")

    # ---- GRUP ONCELIKLI skor (2+ tag) ----
    print("\n=== GRUP YOGUNLUK (2+ tag) ===")
    for gname in ("m5g0", "m5g1", "m5g2", "m1g1", "m1g2"):
        both = [r for r in records if len(r["tags"][gname]) >= 2]
        if not both:
            continue
        acc = sum(1 for r in both if r["hit"]) / len(both) * 100
        print(f"  {gname:<8} (2+ tag) {len(both):>5} ornek  %{acc:.2f}  (baz %{base:.2f})")

    # Rapor
    out = {"base_rate_pct": round(base, 2), "n": len(records),
           "tag_results": results, "combos": {f"{k[0]}__{k[1]}": {"n": v["n"], "hit": v["hit"]} for k, v in combo.items()}}
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "rise2_oneri_raporu.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nKaydedildi: rise2_oneri_raporu.json")
    conn.close()


if __name__ == "__main__":
    main()