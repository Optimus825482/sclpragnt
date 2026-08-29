#!/usr/bin/env python3
"""
ONGORUCU (predictive) desen analizi: rise-1dk ONCESI M5+M1 birlikte.

Kullanici istegi: rise anini degil, O NCEKISINI analiz et (en az 1dk oncesi).
Ayrica M5 ve M1 snapshotlarini BIRLIKTE (confluence) degerlendir.

Yaklasim:
- %2+ M5 yukselis ani tespit: M5[m] baslangici
- ONGORU anı: rise - 1 dk (M1 mumu kapanisi, M5[m] acilmadan onceki son kapanis)
- M5 snapshot: rise mumu DACILMADAN onceki kapanis durumu = M5[m-1] dahil butun gecmis
  (M5[m] acilmamamis sayilir -> lookahead yok)
- M1 snapshot: rise-1dk oncesine kadar kapanan M1'ler (warmup ile)
- Her grup icin: rise+1dk icinde >=%1 artis var mi (hedef) ve
  M5&M1 birlikte (AND, OR) kombinasyonlarinin ongoru gucu (accuracy, lift)
"""

import json
import os
import sys
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
TARGET_UP_PCT = 1.0       # rise-1dk sonrasinda 1dk icinde +%1 hedef
FORECAST_WINDOW_MS = 6 * 60 * 1000  # rise+6dk icinde max yukseklik


# ---- GOSTERGELER (ortak set, M5 ve M1 icin) ----

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
    """'o ana kadar kapanmis gecmis' ile gosterge degeri (lookahead yok)."""
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


def tags_from(snap, prefix):
    tags = set()
    p = snap
    def add(n): tags.add(f"{prefix}_{n}")
    r = p["rsi"]
    if r is not None:
        if r >= 60: add("rsi_high")
        elif r <= 40: add("rsi_low")
        elif r <= 30: add("rsi_oversold")
    at = p["atr_pct"]
    if at is not None and at >= 0.3: add("atr_high")
    vr = p["vol_ratio"]
    if vr is not None:
        if vr >= 1.2: add("vol_up")
        elif vr < 0.8: add("vol_low")
    c5 = p["change5"]
    if c5 is not None:
        if c5 >= 1: add("chg_up")
        elif c5 <= -1: add("chg_down")
    c3 = p["change3"]
    if c3 is not None and c3 >= 0.5: add("chg3_up")
    cm = p["cmo"]
    if cm is not None:
        if cm >= 25: add("cmo_pos")
        elif cm <= -25: add("cmo_neg")
    rc = p["roc"]
    if rc is not None and rc >= 5: add("roc_up")
    st = p["stoch"]
    if st is not None:
        if st >= 80: add("stoch_high")
        elif st <= 20: add("stoch_low")
    if p["ema_align"] == "bullish": add("ema_bull")
    elif p["ema_align"] == "bearish": add("ema_bear")
    ad = p["adx"]
    if ad is not None:
        if ad >= 25: add("adx_trend")
        elif ad < 15: add("adx_weak")
    vb = p["vortex_bull"]
    if vb is not None: add("vortex_bull" if vb else "vortex_bear")
    mf = p["mfi"]
    if mf is not None and mf >= 80: add("mfi_up")
    if mf is not None and mf <= 20: add("mfi_low")
    bp = p["bb_pos"]
    if bp is not None:
        if bp >= 0.8: add("bb_upper")
        elif bp <= 0.2: add("bb_lower")
    vw = p["vwap_dist_pct"]
    if vw is not None: add("vwap_above" if vw > 0 else "vwap_below")
    pb = p["psar_bull"]
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

    # Rise anlari
    risers = []
    for sym in symbols:
        cur.execute("""
            SELECT open_time, close FROM historical_candles
            WHERE symbol=%s AND timeframe='5m' ORDER BY open_time ASC
        """, (sym,))
        rows = cur.fetchall()
        for i in range(3, len(rows) - 1):
            pc = rows[i - 1][1]
            if pc and (rows[i][1] - pc) / pc * 100 >= RISE_PCT:
                risers.append({"symbol": sym, "ts": rows[i][0]})
    print(f"Rise anlari: {len(risers)}")

    M5_WARMUP = 3 * 3600000
    M1_WARMUP = 90 * 60000

    # Sonuclar: her rise oncesi 1dk icin M5 ve M1 tag seti + hedef
    records = []
    for sym in set(r["symbol"] for r in risers):
        # O semboldeki tum M5 rise anlari
        sym_risers = [r for r in risers if r["symbol"] == sym]
        for r in sym_risers:
            rise_ms = r["ts"]
            # ONGORU ani: rise - 1dk (M1 kapanisi)
            forecast_ms = rise_ms - 60000
            # M5 snapshot: rise mumundan ONCEKI kapanis durumu (M5[m-1] dahil)
            m5 = get_candles(conn, sym, "5m", rise_ms - M5_WARMUP, rise_ms - 1000)
            if len(m5) < 30:
                continue
            # rise haric: M5[m-1]'e kadar (rise-5dk onceki mum dahil)
            m5_before = [c for c in m5 if c["ts"] < rise_ms]
            if not m5_before:
                continue
            # M1 snapshot: forecast_ms oncesine kadar kapanan M1'ler
            m1 = get_candles(conn, sym, "1m", rise_ms - M1_WARMUP, forecast_ms - 1)
            if len(m1) < 30:
                continue
            snap_m5 = snapshot_for([c["h"] for c in m5_before], [c["l"] for c in m5_before],
                                   [c["c"] for c in m5_before], [c["v"] for c in m5_before])
            snap_m1 = snapshot_for([c["h"] for c in m1], [c["l"] for c in m1],
                                   [c["c"] for c in m1], [c["v"] for c in m1])
            tags_m5 = tags_from(snap_m5, "m5")
            tags_m1 = tags_from(snap_m1, "m1")

            # HEDEF: rise+6dk icinde max high >= +%1 (rise oncesi forecast_ms fiyata gore)
            f_price = m1[-1]["c"]
            fut = get_candles(conn, sym, "1m", rise_ms, rise_ms + FORECAST_WINDOW_MS)
            if len(fut) < 3:
                continue
            max_h = max(c["h"] for c in fut)
            upside = (max_h - f_price) / f_price * 100 if f_price else 0
            hit = upside >= TARGET_UP_PCT
            records.append({
                "symbol": sym, "rise_ts": rise_ms, "f_ts": forecast_ms,
                "tags_m5": tags_m5, "tags_m1": tags_m1, "upside": upside, "hit": hit,
            })

    print(f"Kayit: {len(records)} | hedef isabet: {sum(1 for r in records if r['hit'])} "
          f"(%{sum(1 for r in records if r['hit'])/len(records)*100:.1f} baz oran)")

    # ---- TEK BASINA TAG ANALIZI (M5 ve M1) ----
    print("\n=== TEK TAG ONGORU GUCU (accuracy, min 30 ornek) ===")
    tag_stats = {}
    for r in records:
        for t in r["tags_m5"] | r["tags_m1"]:
            s = tag_stats.setdefault(t, {"n": 0, "hit": 0})
            s["n"] += 1
            s["hit"] += 1 if r["hit"] else 0
    sorted_tags = sorted(tag_stats.items(), key=lambda kv: -(kv[1]["hit"] / kv[1]["n"] if kv[1]["n"] else 0))
    total_n = len(records)
    for t, s in sorted_tags:
        if s["n"] < 30:
            continue
        acc = s["hit"] / s["n"] * 100
        if acc >= 35 or acc <= 20:  # anlamli farklar
            print(f"  {t:<26} {s['n']:>4} ornek  %{acc:>5.1f} isabet")

    # ---- M5 & M1 BIRLIKTE (AND) ----
    print("\n=== M5 AND M1 BIRLIKTE (confluence) ===")
    # En iyi M5 tagi x en iyi M1 tagi kombinasyonlari
    combo_stats = defaultdict(lambda: {"n": 0, "hit": 0})
    for r in records:
        for t5 in r["tags_m5"]:
            for t1 in r["tags_m1"]:
                key = (t5, t1)
                combo_stats[key]["n"] += 1
                if r["hit"]:
                    combo_stats[key]["hit"] += 1
    combos = [(k, v["n"], v["hit"]) for k, v in combo_stats.items() if v["n"] >= 40]
    combos.sort(key=lambda x: -(x[2] / x[1]))
    print(f"{'M5':<24}{'M1':<24}{'n':>6}{'acc%':>8}")
    print("-" * 62)
    for (t5, t1), n, h in combos[:25]:
        print(f"{t5:<24}{t1:<24}{n:>6}{h/n*100:>8.1f}")

    # ---- HEDEF: rise-1dk oncesi (yani ongoru) icin en iyi OR-sekil ~---
    # Baz oranla karsilastirma
    print(f"\nBaz (hedef 1dk-oncesinde +%1, 6dk icinde): %{sum(1 for r in records if r['hit'])/len(records)*100:.1f}")

    # KAYIT
    out = {
        "n": len(records), "base_rate_pct": round(sum(1 for r in records if r["hit"]) / len(records) * 100, 2),
        "tag_stats": {k: v for k, v in tag_stats.items()},
        "combo_stats": {f"{k[0]}__{k[1]}": v for k, v in combo_stats.items()},
    }
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "ongoru_confluence_raporu.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("Kaydedildi: ongoru_confluence_raporu.json")
    conn.close()


if __name__ == "__main__":
    main()