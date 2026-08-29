#!/usr/bin/env python3
"""
Adim 6 (PG): 24 saat backtest - M1 oncesi desen eslestirme.

- Veri kaynagi: PostgreSQL historical_candles (uygulamayla ayni)
- Pencere: son 6 saat DISARIDA (desen analiz penceresi), 24 saat test
- Saat basi tarama, warmup 90dk, skor >= MIN_SCORE_ENTRY
- Basari: 30dk icinde >= %1 upside
"""

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# .env yukle
_env = os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", ".env")
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

import psycopg

# Lift analizinden ayirt edici desenler ve agirliklar
DISCRIMINATING = {
    "m1_roc_up": 3.0,
    "m1_price_rising": 2.5,
    "m1_price_falling": 2.0,
    "m1_atr_high": 2.5,
    "m1_vol_spike_strong": 2.0,
    "m1_vortex_bull": 1.5,
    "m1_bb_upper": 1.0,
    "m1_cci_overbought": 1.0,
    "m1_st_bull": 1.0,
    "m1_cmo_bull": 1.0,
    "m1_fvg_bull": 1.0,
    "m1_macd_bull": 0.5,
    "m1_ema_bull": 0.5,
    "m1_vwap_above": 0.5,
    "m1_vol_low": -0.5,
    "m1_adx_weak": -0.5,
    "m1_macd_bear": -0.5,
    "m1_vwap_below": -0.5,
    "m1_ema_bear": -0.5,
    "m1_mfi_overbought": -0.5,
}

MIN_SCORE_ENTRY = 2.0
SUCCESS_UPSIDE_PCT = 1.0
HOLD_CANDLES = 30  # 30 dk
WARMUP_MS = 90 * 60 * 1000
TEST_HOURS = 24
EXCLUDE_LAST_HOURS = 6


# --- Gosterge fonksiyonlari ---

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


def cmo(closes, period=9):
    if len(closes) < period + 1:
        return None
    ch = np.diff(np.asarray(closes[-(period + 1):], dtype=float))
    g = float(np.sum(np.maximum(ch, 0)))
    l = float(np.sum(np.maximum(-ch, 0)))
    return float(100 * (g - l) / (g + l)) if (g + l) else 0.0


def roc10(closes):
    if len(closes) < 11:
        return None
    return float((closes[-1] - closes[-11]) / closes[-11] * 100)


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
    return {"upper": upper, "lower": lower, "position": pos}


def cci(highs, lows, closes, period=20):
    if len(closes) < period:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    sma = float(np.mean(tp[-period:]))
    mad = float(np.mean([abs(tp[i] - sma) for i in range(len(tp) - period, len(tp))]))
    if mad == 0:
        return 0.0
    return float((tp[-1] - sma) / (0.015 * mad))


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
    return cur - s


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


def vortex(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    pvm = [abs(highs[i] - lows[i - 1]) for i in range(1, len(highs))]
    mvm = [abs(lows[i] - highs[i - 1]) for i in range(1, len(lows))]
    atr_v = atr(highs, lows, closes, period) or 1
    return {"plus_vi": float(np.sum(pvm[-period:]) / atr_v), "minus_vi": float(np.sum(mvm[-period:]) / atr_v)}


def fvg_detection(closes, highs, lows):
    if len(closes) < 3:
        return {"bull_fvg": False, "bear_fvg": False}
    return {"bull_fvg": bool(lows[-1] > highs[-3]), "bear_fvg": bool(highs[-1] < lows[-3])}


def tags_m1(highs, lows, closes, volumes):
    tags = set()
    c = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0

    rsi_v = rsi(closes)
    if rsi_v is not None:
        if rsi_v >= 70: tags.add("m1_rsi_overbought")
        elif rsi_v >= 55: tags.add("m1_rsi_strong")
    cmo_v = cmo(closes)
    if cmo_v is not None and cmo_v >= 25: tags.add("m1_cmo_bull")
    roc_v = roc10(closes)
    if roc_v is not None and roc_v >= 5: tags.add("m1_roc_up")
    if roc_v is not None and roc_v <= -5: tags.add("m1_roc_down")
    if change5 >= 1: tags.add("m1_price_rising")
    elif change5 <= -1: tags.add("m1_price_falling")
    if atr_v and c and atr_v / c * 100 >= 0.3: tags.add("m1_atr_high")
    if vol_ratio >= 1.5: tags.add("m1_vol_spike_strong")
    elif vol_ratio < 0.7: tags.add("m1_vol_low")
    adx_d = adx(highs, lows, closes)
    if adx_d:
        if adx_d["adx"] >= 25: tags.add("m1_adx_trend")
        elif adx_d["adx"] < 15: tags.add("m1_adx_weak")
    st = supertrend(highs, lows, closes)
    if st and st["trend"] == "bullish": tags.add("m1_st_bull")
    bb = bollinger(closes)
    if bb and bb["position"] is not None and bb["position"] >= 0.85: tags.add("m1_bb_upper")
    cci_v = cci(highs, lows, closes)
    if cci_v is not None and cci_v >= 100: tags.add("m1_cci_overbought")
    mh = macd_hist(closes)
    if mh is not None:
        tags.add("m1_macd_bull" if mh > 0 else "m1_macd_bear")
    e9 = ema_last(closes, 9)
    e21 = ema_last(closes, 21)
    if e9 and e21:
        tags.add("m1_ema_bull" if e9 > e21 else "m1_ema_bear")
    vw = vwap(highs, lows, closes, volumes)
    if vw:
        tags.add("m1_vwap_above" if c > vw else "m1_vwap_below")
    mfi_v = mfi(highs, lows, closes, volumes)
    if mfi_v is not None and mfi_v >= 80: tags.add("m1_mfi_overbought")
    vx = vortex(highs, lows, closes)
    if vx and vx["plus_vi"] > vx["minus_vi"]: tags.add("m1_vortex_bull")
    fvg = fvg_detection(closes, highs, lows)
    if fvg["bull_fvg"]: tags.add("m1_fvg_bull")
    return tags


def score_tags(tags):
    return sum(DISCRIMINATING.get(t, 0) for t in tags)


def get_pg():
    return psycopg.connect(os.environ["DATABASE_URL"])


def get_symbols(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='1m' ORDER BY symbol")
    return [r[0] for r in cur.fetchall()]


def get_candles_between(conn, sym, tf, start_ms, end_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume
        FROM historical_candles WHERE symbol=%s AND timeframe=%s AND open_time>=%s AND open_time<=%s
        ORDER BY open_time ASC
    """, (sym, tf, int(start_ms), int(end_ms)))
    return [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]


def run_backtest():
    print("=" * 70)
    print("24 SAAT BACKTEST (PG) - M1 desen eslestirme, son 6 saat hariç")
    print("=" * 70)
    conn = get_pg()
    now_ms = int(time.time() * 1000)
    test_end = now_ms - EXCLUDE_LAST_HOURS * 3600000
    test_start = test_end - TEST_HOURS * 3600000
    print(f"Test penceresi: {datetime.fromtimestamp(test_start/1000)} -> {datetime.fromtimestamp(test_end/1000)}")

    symbols = get_symbols(conn)
    print(f"Sembol: {len(symbols)}")
    results = []

    for si, sym in enumerate(symbols, 1):
        all_m1 = get_candles_between(conn, sym, "1m",
                                     test_start - WARMUP_MS - 10 * 60 * 1000, test_end)
        if len(all_m1) < 60:
            continue
        ts_list = [c["ts"] for c in all_m1]

        # Saat basi tarama noktaları (5dk mum sinirina yuvarla)
        scans = []
        t = test_start
        while t <= test_end:
            t5 = (t // 300000) * 300000
            scans.append(t5)
            t += 3600000

        for scan_ts in scans:
            try:
                i = ts_list.index(scan_ts)
            except ValueError:
                continue
            end_i = i - 1
            if end_i < 40:
                continue
            start_i = max(0, end_i - 89)
            window = all_m1[start_i:end_i + 1]
            if len(window) < 30:
                continue
            hs = [c["h"] for c in window]
            ls = [c["l"] for c in window]
            cs = [c["c"] for c in window]
            vs = [c["v"] for c in window]
            tags = tags_m1(hs, ls, cs, vs)
            score = score_tags(tags)
            if score < MIN_SCORE_ENTRY:
                continue

            # Sonraki 30 dk
            future = [c for c in all_m1 if c["ts"] > scan_ts and c["ts"] <= scan_ts + HOLD_CANDLES * 60000]
            if len(future) < 10:
                continue
            entry = cs[-1]
            max_high = max(c["h"] for c in future)
            upside = (max_high - entry) / entry * 100 if entry else 0
            success = upside >= SUCCESS_UPSIDE_PCT
            results.append({
                "symbol": sym,
                "scan_ts": scan_ts,
                "time": datetime.fromtimestamp(scan_ts / 1000).strftime("%m-%d %H:%M"),
                "score": round(score, 1),
                "tags": sorted(tags),
                "entry": entry,
                "upside_pct": round(upside, 2),
                "success": success,
            })

        if si % 50 == 0:
            print(f"  {si}/{len(symbols)} sembol")

    conn.close()

    total = len(results)
    success_n = sum(1 for r in results if r["success"])
    rate = success_n / total * 100 if total else 0
    print(f"""
+{"=" * 66}
| 24 SAAT BACKTEST SONUCU (PG)
+{"=" * 66}
| Test penceresi : {datetime.fromtimestamp(test_start/1000).strftime('%m-%d %H:%M')} -> {datetime.fromtimestamp(test_end/1000).strftime('%m-%d %H:%M')}
| Toplam eslesme : {total}
| Basarili       : {success_n}
| Basarisiz      : {total - success_n}
| BASARI ORANI   : %{rate:.1f}
+{"-" * 66}
""")

    if results:
        print("Skor bandina gore basari:")
        for lo, hi in [(2, 4), (4, 6), (6, 100)]:
            band = [r for r in results if lo <= r["score"] < hi]
            if band:
                s = sum(1 for r in band if r["success"])
                print(f"  skor[{lo}-{hi}): {len(band):>4} sinyal, %{s/len(band)*100:.1f} basari")

    print("\nDesen bazli basari (eslesen taglar):")
    tag_total, tag_success = Counter(), Counter()
    for r in results:
        for t in r["tags"]:
            tag_total[t] += 1
            if r["success"]:
                tag_success[t] += 1
    for t, cnt in tag_total.most_common(20):
        s = tag_success[t]
        print(f"  {t:<26} {cnt:>4} sinyal  %{s/cnt*100 if cnt else 0:>5.1f}")

    print("\nOrnek sinyaller:")
    for r in results[:25]:
        mark = "BASARILI" if r["success"] else "basarisiz"
        print(f"  {r['time']} {r['symbol']:<12} skor{r['score']:>4.1f} +%{r['upside_pct']:.2f} {mark}")

    report = {
        "type": "24h_backtest_m1_pattern_pg",
        "window": {"start": test_start, "end": test_end},
        "total": total, "success": success_n, "failed": total - success_n, "rate": rate,
        "min_score": MIN_SCORE_ENTRY,
        "results": results,
    }
    out = os.path.join(os.path.dirname(__file__), "..", "..", "..", "bt_24h_m1_report_pg.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nRapor: {out}")


if __name__ == "__main__":
    run_backtest()