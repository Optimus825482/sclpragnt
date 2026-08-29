#!/usr/bin/env python3
"""
Adim 5b: Kontrol grubu karsilastirmasi (lift / ayirt edicilik).

%2+ yukselis yapan sembollerin M1 oncesi desenleri ile,
%2+ yukselis YAPMAMIS kontrol noktalarinda ayni desenlerin gorulme
sikligi karsilastirilir. Yeterli lift yoksa desen "her yerde var"
demektir ve trade sineyali olarak degeri dusuktur.

Yontem:
- Tum aktif sembollerin M5 verisi taranir
- %2+ yukselis yapilan anlar 'rise' etiketi (bunlar ana veri)
- Diğer butun anlar 'control' olarak ayni gosterge seti ile hesaplanir
- Her desen icin: rise_cov vs control_cov, lift = rise_cov/control_cov
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


# --- Ayni gosterge fonksiyonlari (step2'den kopyalanir) ---

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


def macd(closes, fast=12, slow=26, signal=9):
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
    return {"line": float(cur), "signal": float(s), "histogram": float(cur - s)}


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
    if len(closes) < 3:
        return {"bull_fvg": False, "bear_fvg": False}
    return {"bull_fvg": bool(lows[-1] > highs[-3]), "bear_fvg": bool(highs[-1] < lows[-3])}


def build_snapshot(highs, lows, closes, volumes, tf_label):
    out = {"timeframe": tf_label, "n_candles": len(closes)}
    if len(closes) < 5:
        return out
    close = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0

    out["price"] = {
        "close": close,
        "atr_pct": (atr_v / close * 100) if atr_v and close else None,
        "volume_ratio": round(vol_ratio, 3),
        "change_5": round((closes[-1] - closes[-6]) / closes[-6] * 100, 3) if len(closes) >= 6 else None,
    }
    e9, e21 = ema_last(closes, 9), ema_last(closes, 21)
    if e9 and e21:
        align = "bullish" if e9 > e21 else "bearish"
    else:
        align = "unknown"
    out["trend"] = {"ema_alignment": align}
    adx_d = adx(highs, lows, closes)
    if adx_d:
        out["adx"] = {"adx": round(adx_d["adx"], 1)}
    st = supertrend(highs, lows, closes)
    if st:
        out["supertrend"] = st
    bb = bollinger(closes)
    if bb and bb["position"] is not None:
        out["bollinger"] = {"position": round(bb["position"], 3)}
    out["fvg"] = fvg_detection(closes, highs, lows)

    out["momentum"] = {
        "rsi": round(rsi(closes), 1) if rsi(closes) is not None else None,
        "stoch_k": (stochastic(highs, lows, closes) or {}).get("k"),
        "williams_r": round(williams_r(highs, lows, closes), 1) if williams_r(highs, lows, closes) is not None else None,
        "cci": round(cci(highs, lows, closes), 1) if cci(highs, lows, closes) is not None else None,
        "cmo": round(cmo(closes), 1) if cmo(closes) is not None else None,
        "roc": round(roc(closes), 2) if roc(closes) is not None else None,
    }
    macd_d = macd(closes)
    if macd_d:
        out["macd"] = {"histogram": round(macd_d["histogram"], 5)}
    out["volume"] = {
        "mfi": round(mfi(highs, lows, closes, volumes), 1) if mfi(highs, lows, closes, volumes) is not None else None,
        "vwap_dist_pct": round((close / vwap(highs, lows, closes, volumes) - 1) * 100, 2) if vwap(highs, lows, closes, volumes) else None,
    }
    ch = choppiness(highs, lows, closes)
    out["choppiness"] = round(ch, 1) if ch is not None else None
    vx = vortex(highs, lows, closes)
    if vx:
        out["vortex"] = {"plus_vi": round(vx["plus_vi"], 2), "minus_vi": round(vx["minus_vi"], 2)}
    return out


def extract_tags(snap, prefix):
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
    vwap_d = v.get("vwap_dist_pct")
    if vwap_d is not None:
        add("vwap_below" if vwap_d < 0 else "vwap_above")
    if ch is not None:
        if ch <= 38.2: add("chop_trending")
        elif ch >= 61.8: add("chop_range")
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
    vx_d = snap.get("vortex")
    if vx_d and vx_d.get("plus_vi") is not None and vx_d.get("minus_vi") is not None:
        add("vortex_bull" if vx_d["plus_vi"] > vx_d["minus_vi"] else "vortex_bear")
    return tags


# ---------------------------------------------------------------- MAIN

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
    with open(RISERS_PATH, encoding="utf-8") as f:
        risers = json.load(f)
    rise_times = defaultdict(set)
    for r in risers:
        rise_times[r["symbol"]].add(r["rise_start_ms"])

    M1_WARMUP_MS = 90 * 60 * 1000

    # Tamamini tekrar tek cekmek yerine: rise anindan 20dk sonrasindaki M1
    # hareketine bakip sinif belirle, ama once kontrol "an"larini sec:
    # her sembolde rise anlarinin DISINDA rastgele/duzenli ornekleme.
    sample_interval_ms = 60 * 60 * 1000  # her sembolde saat basi kontrol

    counters = {"rise": Counter(), "control": Counter()}
    n_diff = {"rise": 0, "control": 0}
    # rise anlari icin de tagleri tekrar hesapla (step2 ile ayni sonuc),
    # kontrol icin rise-disindaki anlar.

    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM market_candles WHERE timeframe='5m'")
    symbols = [r[0] for r in cur.fetchall()]
    rise_set = set()
    for sym, times in rise_times.items():
        for t in times:
            rise_set.add((sym, t))

    processed = {"rise": 0, "control": 0}
    for sym in symbols:
        # sembolun tum M1 verisi (mie: warmup 90dk gerekiyor, son 2 saatlik veri)
        cur.execute("""
            SELECT open_time, open, high, low, close, volume
            FROM market_candles WHERE symbol=? AND timeframe='1m' ORDER BY open_time ASC
        """, (sym,))
        all_m1 = [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]
        if len(all_m1) < 60:
            continue

        # Rise anlari (bu sembol)
        rise_marks = rise_times.get(sym, set())

        idx_by_ts = {c["ts"]: i for i, c in enumerate(all_m1)}

        # 1) Rise anlari icin snapshot
        for rise_ts in rise_marks:
            i = idx_by_ts.get(rise_ts)
            if i is None:
                continue
            end_i = i - 1  # bir mum once
            if end_i < 40:
                continue
            start_i = max(0, end_i - 89)
            window = all_m1[start_i:end_i + 1]
            if len(window) < 30:
                continue
            snap = build_snapshot([c["h"] for c in window], [c["l"] for c in window],
                                  [c["c"] for c in window], [c["v"] for c in window], "m1")
            tags = extract_tags(snap, "m1")
            for t in tags:
                counters["rise"][t] += 1
            processed["rise"] += 1

        # 2) Control anlari: rise-disindaki M5 kapanis anlari (bu sembolde)
        # M5 kapanis zamanlari M1 time-line ile hizali; rise olmayan her 5dk
        # noktasindan her 12. noktayi (saat basi) kontrol sec.
        cur.execute("""
            SELECT open_time FROM market_candles
            WHERE symbol=? AND timeframe='5m' ORDER BY open_time ASC
        """, (sym,))
        m5_open_times = [r[0] for r in cur.fetchall()]
        control_marks = [t for t in m5_open_times if t not in rise_marks]
        for k, ctrl_ts in enumerate(control_marks):
            if k % 12 != 0:
                continue  # saat basi
            i = idx_by_ts.get(ctrl_ts)
            if i is None:
                continue
            end_i = i - 1
            if end_i < 40:
                continue
            start_i = max(0, end_i - 89)
            window = all_m1[start_i:end_i + 1]
            if len(window) < 30:
                continue
            snap = build_snapshot([c["h"] for c in window], [c["l"] for c in window],
                                  [c["c"] for c in window], [c["v"] for c in window], "m1")
            tags = extract_tags(snap, "m1")
            for t in tags:
                counters["control"][t] += 1
            processed["control"] += 1

    print(f"Rise oncesi nokta: {processed['rise']} | Control nokta: {processed['control']}")

    # Lift hesapla
    r_total = processed["rise"]
    c_total = processed["control"]
    comparison = []
    all_tags = set(counters["rise"]) | set(counters["control"])
    for tag in all_tags:
        r_cov = counters["rise"][tag] / r_total * 100 if r_total else 0
        c_cov = counters["control"][tag] / c_total * 100 if c_total else 0
        lift = (r_cov / c_cov) if c_cov > 0 else (float("inf") if r_cov > 0 else 0)
        comparison.append({
            "tag": tag,
            "rise_cov_pct": round(r_cov, 1),
            "control_cov_pct": round(c_cov, 1),
            "lift": round(lift, 2) if lift != float("inf") else 99.0,
            "abs_diff_pct": round(r_cov - c_cov, 1),
        })

    # Lift'e gore sirala, sadece yeterince yaygin olanlari goster
    comparison.sort(key=lambda x: -x["lift"])
    print("\n" + "=" * 80)
    print("DESEN AYIRT EDICILIGI (RISE vs CONTROL) - M1 oncesi 10 mum")
    print("=" * 80)
    print(f"{'tag':<26}{'rise%':>8}{'ctrl%':>8}{'lift':>7}{'abs diff':>10}")
    print("-" * 62)
    for c in comparison[:35]:
        print(f"{c['tag']:<26}{c['rise_cov_pct']:>8.1f}{c['control_cov_pct']:>8.1f}{c['lift']:>7.2f}{c['abs_diff_pct']:>10.1f}")

    # Rapor
    out = {
        "processed": processed,
        "comparison": comparison,
        "top_discriminating": [c for c in comparison if c["lift"] >= 1.3 and c["rise_cov_pct"] >= 20],
    }
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "pattern_lift_report.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nKaydedildi: pattern_lift_report.json")
    conn.close()


if __name__ == "__main__":
    main()