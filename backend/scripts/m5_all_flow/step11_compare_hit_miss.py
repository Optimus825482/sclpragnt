#!/usr/bin/env python3
"""
step11 - %28 basarili vs %72 hatali sinyallerin snapshot karsilastirmasi.

Hedef = +%1 (6dk icinde). Sinyal kriteri: skor>=2.5, engelleyici yok (step10 ile ayni).
Her sinyal icin TUM grup snapshot gosterge DEGERLERINI (tag degil, ham deger)
kaydet. Sonra basarili(308) vs hatali(778) grubu istatistiksel karsilastir:
  - ortalama/medyan farki
  - Cohen d (ayirt edicilik)
En ayirt edici gostergeleri filtre olarak test et: yeni basari orani + kac sinyal
eleniyor (recall kaybi).
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

TARGET = 1.0
MIN_SCORE = 2.5
TEST_HOURS = 24
EXCLUDE_LAST_HOURS = 6

WEIGHTS = {
    "m5g1_roc_up": 3.0, "m5g1_chg_up": 2.0, "m1g1_atr_high": 2.0, "m1g1_atr_very_high": 2.5,
    "m5g1_stoch_high": 1.0, "m5g1_cmo_pos": 1.0, "m5g1_vwap_above": 1.0,
    "m5g1_ema_bull": 1.0, "m5g1_vortex_bull": 1.0, "m5g1_psar_bull": 1.0,
    "m5g2_roc_up": 1.5, "m1g2_atr_high": 1.0, "m5g1_chg3_up": 1.5, "m5g1_atr_very_high": 1.5,
    "m1g1_chg_up": 1.0, "m5g2_chg_up": 1.0,
    "m1g1_macd_bull": 1.0, "m5g1_macd_bull": 1.0,
    "m1g1_fisher_bull": 1.0, "m5g1_fisher_bull": 1.0,
    "m5g1_st_bull": 1.0, "m1g1_st_bull": 1.0,
    "m5g1_obv_up": 0.5, "m1g1_obv_up": 0.5,
    "m5g1_volosc_pos": 0.5, "m1g1_volosc_pos": 0.5,
    "m5g0_chg_down": -3.0, "m5g0_bb_lower": -3.0, "m5g0_stoch_low": -3.0, "m5g0_rsi_low": -3.0,
    "m5g0_cmo_neg": -3.0, "m5g0_vol_low": -2.0, "m5g0_vortex_bear": -2.0, "m5g0_adx_weak": -2.0,
    "m5g0_vwap_below": -2.0, "m5g0_psar_bear": -2.0, "m5g0_chg3_down": -2.0, "m5g0_mfi_low": -2.0,
    "m1g1_mfi_low": -1.0, "m5g1_bb_lower": -1.0, "m5g1_stoch_low": -1.0,
    "m5g0_macd_bear": -1.0, "m5g0_fisher_bear": -1.0, "m5g0_st_bear": -1.0,
}


# ---- GOSTERGELER (deger donduren) ----

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


def macd_hist(closes):
    if len(closes) < 35:
        return None
    ef = ema_series(closes, 12)
    es = ema_series(closes, 26)
    line = [ef[i] - es[i] for i in range(len(closes)) if ef[i] is not None and es[i] is not None]
    if len(line) < 9:
        return None
    sig = ema_series(line, 9)
    cur = line[-1]
    s = sig[-1] if sig and sig[-1] is not None else cur
    return float(cur - s)


def fisher_v(highs, lows, length=9):
    if len(highs) < length + 1:
        return None
    prev = 0.0
    last = None
    for i in range(length - 1, len(highs)):
        hi = max(highs[i - length + 1:i + 1])
        lo = min(lows[i - length + 1:i + 1])
        mid = (highs[i] + lows[i]) / 2
        ratio = (mid - lo) / (hi - lo) - 0.5 if hi != lo else 0.0
        val = max(-0.999, min(0.999, 0.66 * ratio + 0.67 * prev))
        fisher_v = 0.5 * math.log((1 + val) / (1 - val)) + 0.5 * prev
        last = fisher_v
        prev = val
    return last


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
    return (s - l) / l * 100 if l else 0.0


def group_values(highs, lows, closes, volumes):
    """Bir grup icin HAM gosterge degerleri (son degerler)."""
    vals = {}
    close = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    change3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0
    vals["atr_pct"] = (atr_v / close * 100) if atr_v and close else None
    vals["vol_ratio"] = round(vol_ratio, 3)
    vals["chg5"] = round(change5, 3)
    vals["chg3"] = round(change3, 3)
    vals["rsi"] = rsi(closes)
    vals["cmo"] = cmo(closes)
    vals["roc"] = roc(closes)
    vals["stoch"] = stoch(highs, lows, closes)
    vals["adx"] = None
    vals["vortex_bull"] = None
    a = adx(highs, lows, closes)
    if a:
        vals["adx"] = a["adx"]
        vals["vortex_bull"] = 1.0 if vortex(highs, lows, closes)["plus_vi"] > vortex(highs, lows, closes)["minus_vi"] else 0.0
    vals["mfi"] = mfi(highs, lows, closes, volumes)
    vals["bb_pos"] = bollinger_pos(closes)
    vw = vwap(highs, lows, closes, volumes)
    vals["vwap_dist"] = (close / vw - 1) * 100 if vw else None
    vals["macd_hist"] = macd_hist(closes)
    vals["fisher"] = fisher_v(highs, lows)
    vals["obv_slope"] = obv_slope(closes, volumes)
    vals["volosc"] = vol_oscillator(volumes)
    return vals


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

            m5_b = [c for c in m5_all[:k] if c["ts"] <= cur_ms]
            if len(m5_b) < 35:
                continue
            g2_candles = m5_b[:-2] if len(m5_b) > 3 else m5_b
            g1_v = group_values([c["h"] for c in m5_b], [c["l"] for c in m5_b],
                                [c["c"] for c in m5_b], [c["v"] for c in m5_b])
            g2_v = group_values([c["h"] for c in g2_candles], [c["l"] for c in g2_candles],
                                [c["c"] for c in g2_candles], [c["v"] for c in g2_candles])
            g0_candles = m5_b + [m5_all[k]]
            g0_v = group_values([c["h"] for c in g0_candles], [c["l"] for c in g0_candles],
                                [c["c"] for c in g0_candles], [c["v"] for c in g0_candles])

            m1_all = get_candles(conn, sym, "1m", cur_ms - M1_WARMUP, cur_ms - 1)
            if len(m1_all) < 60:
                continue
            m1g1_v = group_values([c["h"] for c in m1_all], [c["l"] for c in m1_all],
                                  [c["c"] for c in m1_all], [c["v"] for c in m1_all])
            prev10 = m1_all[-20:-10] if len(m1_all) >= 20 else m1_all[:-10]
            m1g2_v = group_values([c["h"] for c in prev10], [c["l"] for c in prev10],
                                  [c["c"] for c in prev10], [c["v"] for c in prev10])

            # Skor (tag esikleri) - step10 ile ayni
            # dogrudan degerlerden skor uret
            score = 0.0
            neg = 0
            def chk(v, lo, hi=None, val=1.0, invert=False):
                nonlocal score, neg
                if v is None:
                    return
                if hi is None:
                    ok = v >= lo
                else:
                    ok = lo <= v <= hi
                if invert:
                    ok = not ok
                if ok:
                    if val < 0:
                        neg += 1
                    score += val
            # pozitif ongoru
            chk(m1g1_v["atr_pct"], 0.3, val=2.0)
            chk(m1g1_v["atr_pct"], 0.5, val=0.5)
            chk(g1_v["roc"], 5, val=3.0)
            chk(g1_v["chg5"], 1, val=2.0)
            chk(g1_v["chg3"], 0.5, val=1.5)
            chk(g1_v["stoch"], 80, val=1.0)
            chk(g1_v["cmo"], 25, val=1.0)
            chk(g1_v["vwap_dist"], 0, val=1.0)
            chk(g1_v["macd_hist"], 0, val=1.0)
            chk(g1_v["fisher"], 0, val=1.0)
            chk(g1_v["obv_slope"], 0, val=0.5)
            chk(g1_v["volosc"], 0, val=0.5)
            chk(g2_v["roc"], 5, val=1.5)
            chk(m1g2_v["atr_pct"], 0.3, val=1.0)
            # engelleyiciler (m5g0)
            chk(g0_v["chg5"], -1, val=-3.0, invert=True)  # chg5 <= -1
            chk(g0_v["bb_pos"], 0.2, val=-3.0, invert=True)
            chk(g0_v["stoch"], 20, val=-3.0, invert=True)
            chk(g0_v["rsi"], 40, val=-3.0, invert=True)
            chk(g0_v["cmo"], -25, val=-3.0, invert=True)
            chk(g0_v["vol_ratio"], 0.8, val=-2.0, invert=True)
            if neg > 0 or score < MIN_SCORE:
                continue

            fut = get_candles(conn, sym, "1m", cur_ms, cur_ms + 6 * 60000)
            if len(fut) < 3:
                continue
            max_h = max(c["h"] for c in fut)
            upside = (max_h / prev_close - 1) * 100 if prev_close else 0
            hit = upside >= TARGET

            records.append({
                "symbol": sym, "ts": cur_ms, "score": round(score, 2), "upside": round(upside, 3), "hit": hit,
                "g0": g0_v, "g1": g1_v, "g2": g2_v, "m1g1": m1g1_v, "m1g2": m1g2_v,
            })

    conn.close()
    total = len(records)
    hits = [r for r in records if r["hit"]]
    misses = [r for r in records if not r["hit"]]
    print(f"\n=== BASARILI vs HATALI SINYAL KARSILASTIRMASI ===")
    print(f"Toplam: {total} | Basarili(+%{TARGET}): {len(hits)} (%{len(hits)/total*100:.1f}) | Hatali: {len(misses)}")

    # ---- Grup bazinda gosterge deger karsilastirmasi ----
    features = {}
    for gname in ("g0", "g1", "g2", "m1g1", "m1g2"):
        for f in ("atr_pct", "vol_ratio", "chg5", "chg3", "rsi", "cmo", "roc", "stoch", "adx", "mfi", "bb_pos", "vwap_dist", "macd_hist", "fisher", "obv_slope", "volosc"):
            key = f"{gname}_{f}"
            hv = [r[gname][f] for r in hits if r[gname].get(f) is not None]
            mv = [r[gname][f] for r in misses if r[gname].get(f) is not None]
            if len(hv) < 10 or len(mv) < 10:
                continue
            hmean = float(np.mean(hv))
            mmean = float(np.mean(mv))
            hstd = float(np.std(hv)) + 1e-9
            mstd = float(np.std(mv)) + 1e-9
            pooled = math.sqrt((len(hv) * hstd**2 + len(mv) * mstd**2) / (len(hv) + len(mv)))
            d = (hmean - mmean) / pooled
            features[key] = {"h_mean": round(hmean, 4), "m_mean": round(mmean, 4),
                             "d": round(d, 3), "diff": round(hmean - mmean, 4)}

    print("\n=== EN AYIRT EDICI GOSTERGELER (|Cohen d| > 0.15) ===")
    ranked = sorted(features.items(), key=lambda kv: -abs(kv[1]["d"]))
    for k, v in ranked:
        if abs(v["d"]) >= 0.15:
            bar = "+" * int(abs(v["d"]) * 20)
            print(f"  {k:<22} hit_ort={v['h_mean']:>8}  miss_ort={v['m_mean']:>8}  d={v['d']:>7.2f} {bar}")

    # ---- Filtre onerileri ----
    print("\n=== BASARILI GRUBU BUYUTEN FILTRE ADAYLARI ===")
    # Her aday filtreyi uygula: kac sinyal kalir, yeni basari
    filters = []
    # Ornek filtreler: en ayirt edici gostergelerden esikler
    # (d pozitif = basarili grubun degeri yuksek -> alt sinir; d negatif -> ust sinir)
    for k, v in ranked:
        if abs(v["d"]) < 0.3:
            continue
        gname, f = k.split("_", 1)
        val_h = v["h_mean"]
        val_m = v["m_mean"]
        if v["d"] > 0:
            # basarililar daha yuksek -> alt sinir (h ve m arasi)
            thr = round((val_h + val_m) / 2, 4)
            flt = lambda r, f=f, gname=gname, thr=thr: (r[gname].get(f) or -999) >= thr
            desc = f"{k} >= {thr}"
        else:
            thr = round((val_h + val_m) / 2, 4)
            flt = lambda r, f=f, gname=gname, thr=thr: (r[gname].get(f) if r[gname].get(f) is not None else 999) <= thr
            desc = f"{k} <= {thr}"
        filters.append((desc, flt))

    # her filtreyi ayri uygula
    for desc, flt in filters[:12]:
        keep = [r for r in records if flt(r)]
        if not keep:
            continue
        h = sum(1 for r in keep if r["hit"])
        print(f"  {desc:<44} {len(keep):>4} sinyal  %{h/len(keep)*100:.1f}  (recall %{len(keep)/total*100:.0f})")

    # En iyi 3 filtreyi birlikte uygula
    print("\n=== COKLU FILTRE (en iyi 3 ayni anda) ===")
    best = [desc for desc, flt in filters[:6]]
    keep = records
    for desc, flt in filters[:6]:
        keep = [r for r in keep if flt(r)]
    if keep:
        h = sum(1 for r in keep if r["hit"])
        print(f"  filtreler: {best}")
        print(f"  {len(keep)} sinyal kaldi  %{h/len(keep)*100:.1f} basari")

    # Rapor kaydet
    out = {"total": total, "hit": len(hits), "rate": len(hits)/total*100, "features": {k: v for k, v in ranked}}
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "basarili_vs_hatali_raporu.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print("\nKaydedildi: basarili_vs_hatali_raporu.json")


if __name__ == "__main__":
    main()