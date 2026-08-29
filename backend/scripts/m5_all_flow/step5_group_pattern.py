#!/usr/bin/env python3
"""
GRUP-BAZLI desen analizi.

Kullanici ornegine gore yapi:
- %2+ M5 yukselisi tespit edilen an: M5[m] baslangici (ornek 11:25)
- M5 GRUPLARI (3'er mum, gecmis warmup ile gosterge degeri):
    G0: M5[m]     (yukseilisin basladigi mum grubu)
    G1: M5[m-1]   (onundeki mumlar, 11:20)
    G2: M5[m-2]   (bir onceki, 11:15)
  Her grup icin "o ana kadar gecmis (warmup)" ile gosterge hesabi.
- M1 GRUPLARI (10'ar mum):
    G1M1: yukselisin basindan onceki 10 M1 (11:15-11:25, rise-onsu pencere)
    G2M1: ondan onceki 10 M1 (11:05-11:15)
- Her grupta gostergelerin dagilimi (ortalama, p-crossover, medyan) analiz edilir
  ve her grubun ortak/ayirt edici desenleri raporlanir.

Cikti: grup_bazli_desen_raporu.json + konsol ozeti
"""

import json
import math
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


# ---- GOSTERGELER ----

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


def vwap(highs, lows, closes, volumes):
    if len(closes) < 2 or sum(volumes) == 0:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    return sum(tp[i] * volumes[i] for i in range(len(closes))) / sum(volumes)


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


def stochastic(highs, lows, closes, period=14):
    if len(closes) < period:
        return None
    hi, lo = max(highs[-period:]), min(lows[-period:])
    return (closes[-1] - lo) / (hi - lo) * 100 if hi != lo else 50.0


def group_snapshot(highs, lows, closes, volumes):
    """Bir grup icin gostergelerin 'o ana kadar gecmis' degeri."""
    snap = {}
    close = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0

    e9, e21 = ema_last(closes, 9), ema_last(closes, 21)
    if e9 and e21:
        align = "bullish" if e9 > e21 else "bearish"
    else:
        align = "unknown"

    snap["rsi"] = rsi(closes)
    snap["atr_pct"] = (atr_v / close * 100) if atr_v and close else None
    snap["vol_ratio"] = round(vol_ratio, 3)
    snap["change5"] = round(change5, 3)
    snap["cmo"] = cmo(closes)
    snap["roc"] = roc(closes)
    snap["stoch"] = stochastic(highs, lows, closes)
    snap["ema_align"] = align
    a = adx(highs, lows, closes)
    snap["adx"] = a["adx"] if a else None
    snap["pdi_mdi_gap"] = (a["pdi"] - a["mdi"]) if a else None
    vw = vwap(highs, lows, closes, volumes)
    snap["vwap_dist_pct"] = (close / vw - 1) * 100 if vw else None
    vx = vortex(highs, lows, closes)
    snap["vortex_bull"] = (vx["plus_vi"] > vx["minus_vi"]) if vx else None
    snap["mfi"] = mfi(highs, lows, closes, volumes)
    snap["bb_pos"] = bollinger_pos(closes)
    pr = psar(highs, lows)
    snap["psar_bull"] = (pr == "bullish") if pr else None
    return snap


# ---- DB ----

def get_pg():
    return psycopg.connect(os.environ["DATABASE_URL"])


def get_candles(conn, sym, tf, start_ms, end_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume FROM historical_candles
        WHERE symbol=%s AND timeframe=%s AND open_time>=%s AND open_time<=%s ORDER BY open_time ASC
    """, (sym, tf, int(start_ms), int(end_ms)))
    return [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]


def main():
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='5m' ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]

    # Rise anlarini bul
    risers = []
    for sym in symbols:
        cur.execute("""
            SELECT open_time, close FROM historical_candles
            WHERE symbol=%s AND timeframe='5m' ORDER BY open_time ASC
        """, (sym,))
        rows = cur.fetchall()
        for i in range(3, len(rows) - 1):
            prev_close = rows[i - 1][1]
            if not prev_close:
                continue
            rise = (rows[i][1] - prev_close) / prev_close * 100
            if rise >= RISE_PCT:
                risers.append({"symbol": sym, "ts": rows[i][0], "rise_pct": round(rise, 2)})
    print(f"Rise anlari: {len(risers)}")

    M5_WARMUP_MS = 3 * 60 * 60 * 1000
    M1_WARMUP_MS = 90 * 60 * 1000

    # Her grup icin toplanan degerler
    groups = {
        "m5_g0_rise": [], "m5_g1_prev": [], "m5_g2_prev2": [],
        "m1_g1_pre_10": [], "m1_g2_prev_10": [],
    }

    for n, r in enumerate(risers, 1):
        sym = r["symbol"]
        rise_ms = r["ts"]

        # M5 gruplari: rise, rise-5dk, rise-10dk
        # Warmup: rise-3 saat .. rise+5dk (g1 'o ana kadar' degisimi icin)
        m5_all = get_candles(conn, sym, "5m", rise_ms - M5_WARMUP_MS, rise_ms + 5 * 60 * 1000)
        if len(m5_all) < 30:
            continue
        # rise index
        rise_idx = None
        for j, c in enumerate(m5_all):
            if c["ts"] == rise_ms:
                rise_idx = j
                break
        if rise_idx is None:
            continue
        # 'o ana kadar gecmis' pencereleri
        # G1: rise oncesi (rise haric) tum gecmis
        g1_candles = m5_all[:rise_idx]
        # G2: g1'in bir mum oncesi (son eleman cikar)
        g2_candles = g1_candles[:-1] if len(g1_candles) > 1 else g1_candles
        # G0: rise baslangici dahil (o anki gorunum)
        g0_candles = m5_all[:rise_idx + 1]

        s_g0 = group_snapshot([c["h"] for c in g0_candles], [c["l"] for c in g0_candles],
                              [c["c"] for c in g0_candles], [c["v"] for c in g0_candles])
        s_g1 = group_snapshot([c["h"] for c in g1_candles], [c["l"] for c in g1_candles],
                              [c["c"] for c in g1_candles], [c["v"] for c in g1_candles])
        s_g2 = group_snapshot([c["h"] for c in g2_candles], [c["l"] for c in g2_candles],
                              [c["c"] for c in g2_candles], [c["v"] for c in g2_candles])
        groups["m5_g0_rise"].append(s_g0)
        groups["m5_g1_prev"].append(s_g1)
        groups["m5_g2_prev2"].append(s_g2)

        # M1 gruplari: rise oncesi 10 M1 (G1M1) ve ondan onceki 10 (G2M1)
        m1_all = get_candles(conn, sym, "1m", rise_ms - 30 * 60 * 1000, rise_ms - 1)
        if len(m1_all) < 20:
            continue
        last10 = m1_all[-10:]
        prev10 = m1_all[-20:-10] if len(m1_all) >= 20 else m1_all[:-10]
        # warmup ile gostergeler (M1: 90dk onceki + bu 10 mum)
        w1 = get_candles(conn, sym, "1m", rise_ms - 90 * 60 * 1000, rise_ms - 1)
        if len(w1) < 30:
            continue
        s_m1g1 = group_snapshot([c["h"] for c in w1], [c["l"] for c in w1],
                                [c["c"] for c in w1], [c["v"] for c in w1])
        # G2M1: onceki 10 mum penceresi icin warmup (90dk once + bu 10 haric)
        w2_end = rise_ms - 10 * 60 * 1000 - 1
        w2 = get_candles(conn, sym, "1m", rise_ms - 100 * 60 * 1000, w2_end)
        if len(w2) >= 30:
            s_m1g2 = group_snapshot([c["h"] for c in w2], [c["l"] for c in w2],
                                    [c["c"] for c in w2], [c["v"] for c in w2])
        else:
            s_m1g2 = None
        groups["m1_g1_pre_10"].append(s_m1g1)
        if s_m1g2:
            groups["m1_g2_prev_10"].append(s_m1g2)

        if n % 300 == 0:
            print(f"  {n}/{len(risers)}")

    conn.close()

    # ---- GRUP ANALIZI ----
    print("\n" + "=" * 78)
    print("GRUP-BAZLI DESEN ANALIZI")
    print("=" * 78)

    numeric_cols = ["rsi", "atr_pct", "vol_ratio", "change5", "cmo", "roc", "stoch",
                    "adx", "pdi_mdi_gap", "vwap_dist_pct", "mfi", "bb_pos"]

    def pct_cond(vals, cond):
        if not vals:
            return None
        return round(sum(1 for v in vals if v is not None and cond(v)) / len(vals) * 100, 1)

    for gname, gdata in groups.items():
        if not gdata:
            continue
        n_g = len([s for s in gdata if s])
        print(f"\n### GRUP: {gname}  (n={n_g})")
        # RSI <40
        rsi_vals = [s["rsi"] for s in gdata if s and s.get("rsi") is not None]
        rsi_lt40 = pct_cond(rsi_vals, lambda v: v < 40)
        rsi_lt30 = pct_cond(rsi_vals, lambda v: v < 30)
        rsi_gt60 = pct_cond(rsi_vals, lambda v: v > 60)
        print(f"  RSI<40: %{rsi_lt40} | RSI<30: %{rsi_lt30} | RSI>60: %{rsi_gt60}")

        atr_vals = [s["atr_pct"] for s in gdata if s and s.get("atr_pct") is not None]
        print(f"  ATR%>=0.3: %{pct_cond(atr_vals, lambda v: v >= 0.3)} | ATR%>=0.5: %{pct_cond(atr_vals, lambda v: v >= 0.5)}")

        vratio = [s["vol_ratio"] for s in gdata if s and s.get("vol_ratio") is not None]
        print(f"  VolRatio>=1.2: %{pct_cond(vratio, lambda v: v >= 1.2)} | >=1.5: %{pct_cond(vratio, lambda v: v >= 1.5)}")

        ema_bull = pct_cond([s for s in gdata if s], lambda s: s.get("ema_align") == "bullish")
        print(f"  EMA Bullish: %{ema_bull}")

        vx_bull = pct_cond([s for s in gdata if s], lambda s: s.get("vortex_bull") is True)
        print(f"  Vortex Bullish: %{vx_bull}")

        ps_bull = pct_cond([s for s in gdata if s], lambda s: s.get("psar_bull") is True)
        print(f"  PSAR Bullish: %{ps_bull}")

        adx_v = [s["adx"] for s in gdata if s and s.get("adx") is not None]
        print(f"  ADX>=25: %{pct_cond(adx_v, lambda v: v >= 25)}")

        cmo_v = [s["cmo"] for s in gdata if s and s.get("cmo") is not None]
        print(f"  CMO>25: %{pct_cond(cmo_v, lambda v: v > 25)} | CMO<-25: %{pct_cond(cmo_v, lambda v: v < -25)}")

        roc_v = [s["roc"] for s in gdata if s and s.get("roc") is not None]
        print(f"  ROC>=5: %{pct_cond(roc_v, lambda v: v >= 5)}")

        st_v = [s["stoch"] for s in gdata if s and s.get("stoch") is not None]
        print(f"  Stoch>80: %{pct_cond(st_v, lambda v: v > 80)} | <20: %{pct_cond(st_v, lambda v: v < 20)}")

        mfi_v = [s["mfi"] for s in gdata if s and s.get("mfi") is not None]
        print(f"  MFI<20: %{pct_cond(mfi_v, lambda v: v < 20)}")

        bb_v = [s["bb_pos"] for s in gdata if s and s.get("bb_pos") is not None]
        print(f"  BB_lower(<0.2): %{pct_cond(bb_v, lambda v: v < 0.2)} | BB_upper(>0.8): %{pct_cond(bb_v, lambda v: v > 0.8)}")

        vwap_v = [s["vwap_dist_pct"] for s in gdata if s and s.get("vwap_dist_pct") is not None]
        print(f"  VWAP alti(<0): %{pct_cond(vwap_v, lambda v: v < 0)}")

    # Ortalama tablolari
    print("\n=== ORTALAMALAR (her grubun medyan degerleri) ===")
    print(f"{'col':<16}" + "".join(f"{g:>12}" for g in groups.keys()))
    for col in ["rsi", "atr_pct", "cmo", "roc", "stoch", "adx", "mfi", "bb_pos"]:
        row = []
        for gname, gdata in groups.items():
            vals = [s[col] for s in gdata if s and s.get(col) is not None]
            row.append(f"{np.median(vals) if vals else 0:>12.1f}")
        print(f"{col:<16}" + "".join(row))

    # Raporu kaydet
    json_out = {}
    for gname, gdata in groups.items():
        json_out[gname] = [s for s in gdata if s]
    out = os.path.join(os.path.dirname(__file__), "..", "..", "..", "grup_bazli_desen_raporu.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(json_out, f, ensure_ascii=False, default=str)
    print(f"\nKaydedildi: {out}")


if __name__ == "__main__":
    main()