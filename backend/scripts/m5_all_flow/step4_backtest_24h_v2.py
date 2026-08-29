#!/usr/bin/env python3
"""
24s backtest v2 - Zenginlestirilmis gostergeler + hatali sinyalleri engelleyen filtrel.

Lift v2 bulgularina gore agirliklandirma:
POZITIF
  m1_roc_up(+3), m1_move_10m_up(+2.5), m1_price_rising(+2.5), m1_atr_high(+2.5),
  m1_vortex_bull(+1.5), m1_rsi_strong(+1), m1_vol_spike_strong(+1.5), m1_cmf_positive(+1),
  m1_cmo_bull(+1), m1_fvg_bull(+1), m1_ao_bull(+0.5), m1_tsi_bull(+0.5)
ENGELLEYICILER (negatif)
  m1_atr_low(-2.5), m1_vol_low(-1), m1_vortex_bear(-1), m1_ao_bear(-0.5),
  m1_donchian_lower(-1), m1_keltner_lower(-0.5), m1_stochrsi_oversold(-0.5)
"""

import os
import sys
import time
import json
from collections import Counter
from datetime import datetime

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

DISCRIMINATING = {
    "m1_roc_up": 3.0, "m1_move_10m_up": 2.5, "m1_price_rising": 2.5, "m1_atr_high": 2.5,
    "m1_vortex_bull": 1.5, "m1_vol_spike_strong": 1.5, "m1_rsi_strong": 1.0,
    "m1_cmf_positive": 1.0, "m1_cmo_bull": 1.0, "m1_fvg_bull": 1.0,
    "m1_ao_bull": 0.5, "m1_tsi_bull": 0.5, "m1_psar_bull": 0.5, "m1_ema_bull": 0.5,
    "m1_roc_down": 0.5, "m1_move_10m_down": 0.5, "m1_price_falling": 0.5,
    # Engelleyiciler
    "m1_atr_low": -2.5, "m1_vol_low": -1.0, "m1_vortex_bear": -1.0,
    "m1_ao_bear": -0.5, "m1_donchian_lower": -1.0, "m1_keltner_lower": -0.5,
    "m1_stochrsi_oversold": -0.5, "m1_aroon_bear": -0.5,
}

MIN_SCORE_ENTRY = 3.0
SUCCESS_UPSIDE_PCT = 1.0
HOLD_CANDLES = 30
EXCLUDE_LAST_HOURS = 6
TEST_HOURS = 24
WARMUP_MS = 90 * 60 * 1000


# --- Gosterge fonksiyonlari (step3_lift_v2 ile ayni) ---

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
    return float(np.mean(out[-smooth:]))


def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    return float(np.mean(trs))


def aroon(highs, lows, period=25):
    if len(highs) < period + 1:
        return None
    win_h = highs[-(period + 1):]
    win_l = lows[-(period + 1):]
    hb = int(np.argmax(win_h))
    lb = int(np.argmin(win_l))
    return {"up": float((period - hb) / period * 100), "down": float((period - lb) / period * 100)}


def donchian(highs, lows, period=20):
    if len(highs) < period or len(lows) < period:
        return None
    upper, lower = max(highs[-period:]), min(lows[-period:])
    close = closes_ref[-1] if 'closes_ref' in globals() else highs[-1]
    pos = (close - lower) / (upper - lower) if upper != lower else 0.5
    return {"position": float(pos)}


closes_ref = None


def tsi(closes, long_period=25, short_period=13, signal_period=13):
    if len(closes) < long_period + short_period + signal_period:
        return None
    diffs = np.diff(np.asarray(closes, dtype=float))
    abs_diff = np.abs(diffs)
    d_ema = ema_series(list(diffs), long_period)
    ad_ema = ema_series(list(abs_diff), long_period)
    d2 = ema_series([v for v in d_ema if v is not None], short_period)
    ad2 = ema_series([v for v in ad_ema if v is not None], short_period)
    if not d2 or not ad2 or d2[-1] is None or ad2[-1] is None or ad2[-1] == 0:
        return None
    return float(d2[-1] / ad2[-1] * 100)


def cmf(highs, lows, closes, volumes, period=20):
    if len(closes) < period:
        return None
    mfm = []
    for i in range(len(closes)):
        hl = highs[i] - lows[i]
        mfm.append(((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl if hl else 0.0)
    mfv = [mfm[i] * volumes[i] for i in range(len(closes))]
    sum_vol = sum(volumes[-period:])
    return float(sum(mfv[-period:]) / sum_vol) if sum_vol > 0 else 0.0


def awesome(highs, lows, fast=5, slow=34):
    if len(highs) < slow:
        return None
    tp = [(highs[i] + lows[i]) / 2 for i in range(len(highs))]
    f, s = sma(tp, fast), sma(tp, slow)
    if f is None or s is None:
        return None
    return float(f - s)


def keltner(highs, lows, closes, period=20, mult=2.0):
    if len(closes) < period + 1:
        return None
    ema_center = ema_last(closes, period)
    atr_v = atr(highs, lows, closes, period)
    if ema_center is None or atr_v is None:
        return None
    upper, lower = ema_center + mult * atr_v, ema_center - mult * atr_v
    return (closes[-1] - lower) / (upper - lower) if upper != lower else 0.5


def psar(highs, lows, af_start=0.02, af_step=0.02, af_max=0.2):
    if len(highs) < 10:
        return None
    n = len(highs)
    uptrend = highs[1] > highs[0]
    ep = highs[0] if uptrend else lows[0]
    sar = lows[0] if uptrend else highs[0]
    af = af_start
    trend = uptrend
    for i in range(1, n):
        prev_sar = sar
        if uptrend:
            sar = prev_sar + af * (ep - prev_sar)
        else:
            sar = prev_sar + af * (ep - prev_sar)
        if uptrend and lows[i] < sar:
            uptrend = False; sar = ep; ep = lows[i]; af = af_start
        elif not uptrend and highs[i] > sar:
            uptrend = True; sar = ep; ep = highs[i]; af = af_start
        else:
            if uptrend and highs[i] > ep:
                ep = highs[i]; af = min(af + af_step, af_max)
            elif not uptrend and lows[i] < ep:
                ep = lows[i]; af = min(af + af_step, af_max)
        trend = uptrend
    return {"direction": "bullish" if trend else "bearish"}


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


def tags_m1(highs, lows, closes, volumes):
    tags = set()
    close = closes[-1]
    atr_v = atr(highs, lows, closes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    change10 = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 else 0

    def add(name):
        tags.add(name)

    if atr_v and close and atr_v / close * 100 >= 0.3: add("m1_atr_high")
    elif atr_v and close and atr_v / close * 100 < 0.15: add("m1_atr_low")
    if vol_ratio >= 1.5: add("m1_vol_spike_strong")
    elif vol_ratio < 0.7: add("m1_vol_low")
    if change5 >= 1: add("m1_price_rising")
    elif change5 <= -1: add("m1_price_falling")
    if change10 >= 2: add("m1_move_10m_up")
    if change10 <= -2: add("m1_move_10m_down")

    r = rsi(closes)
    if r is not None:
        if r >= 70: add("m1_rsi_overbought")
        elif r >= 55: add("m1_rsi_strong")
    sr = stoch_rsi(closes)
    if sr is not None:
        if sr >= 80: add("m1_stochrsi_overbought")
        elif sr <= 20: add("m1_stochrsi_oversold")
    ch = np.diff(closes[-(10):]) if len(closes) >= 10 else np.diff(closes)
    if len(ch):
        g = float(np.sum(np.maximum(ch, 0))); l = float(np.sum(np.maximum(-ch, 0)))
        cmo_v = float(100 * (g - l) / (g + l)) if (g + l) else 0.0
        if cmo_v >= 25: add("m1_cmo_bull")
        elif cmo_v <= -25: add("m1_cmo_bear")
    if len(closes) >= 11:
        roc_v = (closes[-1] - closes[-11]) / closes[-11] * 100
        if roc_v >= 5: add("m1_roc_up")
        elif roc_v <= -5: add("m1_roc_down")
    tsi_v = tsi(closes)
    if tsi_v is not None:
        add("m1_tsi_bull" if tsi_v > 0 else "m1_tsi_bear")
    ao_v = awesome(highs, lows)
    if ao_v is not None:
        add("m1_ao_bull" if ao_v > 0 else "m1_ao_bear")
    cmf_v = cmf(highs, lows, closes, volumes)
    if cmf_v is not None:
        if cmf_v > 0.05: add("m1_cmf_positive")
        elif cmf_v < -0.05: add("m1_cmf_negative")
    vw = vwap(highs, lows, closes, volumes)
    if vw:
        add("m1_vwap_above" if close > vw else "m1_vwap_below")
    vx = vortex(highs, lows, closes)
    if vx:
        add("m1_vortex_bull" if vx["plus_vi"] > vx["minus_vi"] else "m1_vortex_bear")
    e9, e21 = ema_last(closes, 9), ema_last(closes, 21)
    if e9 and e21:
        add("m1_ema_bull" if e9 > e21 else "m1_ema_bear")
    ar = aroon(highs, lows)
    if ar:
        if ar["up"] >= 70 and ar["up"] > ar["down"]: add("m1_aroon_bull")
        elif ar["down"] >= 70 and ar["down"] > ar["up"]: add("m1_aroon_bear")
    # Donchian
    if len(highs) >= 20 and len(lows) >= 20:
        upper, lower = max(highs[-20:]), min(lows[-20:])
        pos = (close - lower) / (upper - lower) if upper != lower else 0.5
        if pos >= 0.9: add("m1_donchian_upper")
        elif pos <= 0.1: add("m1_donchian_lower")
    k_pos = keltner(highs, lows, closes)
    if k_pos is not None:
        if k_pos >= 0.9: add("m1_keltner_upper")
        elif k_pos <= 0.1: add("m1_keltner_lower")
    ps = psar(highs, lows)
    if ps:
        add("m1_psar_bull" if ps["direction"] == "bullish" else "m1_psar_bear")
    fvg = fvg_detection(closes, highs, lows)
    if fvg["bull_fvg"]: add("m1_fvg_bull")
    if fvg["bear_fvg"]: add("m1_fvg_bear")
    return tags


def score_tags(tags):
    return sum(DISCRIMINATING.get(t, 0) for t in tags)


def get_pg():
    return psycopg.connect(os.environ["DATABASE_URL"])


def get_candles(conn, sym, start_ms, end_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, high, low, close, volume FROM historical_candles
        WHERE symbol=%s AND timeframe='1m' AND open_time>=%s AND open_time<=%s
        ORDER BY open_time ASC
    """, (sym, int(start_ms), int(end_ms)))
    return [{"ts": r[0], "h": r[1], "l": r[2], "c": r[3], "v": r[4]} for r in cur.fetchall()]


def run():
    print("=" * 70)
    print("24s BACKTEST v2 (PG) - zengin gostergeler + engelleyici filtreler")
    print("=" * 70)
    conn = get_pg()
    now_ms = int(time.time() * 1000)
    test_end = now_ms - EXCLUDE_LAST_HOURS * 3600000
    test_start = test_end - TEST_HOURS * 3600000
    print(f"Pencere: {datetime.fromtimestamp(test_start/1000)} -> {datetime.fromtimestamp(test_end/1000)}")

    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='1m' ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]
    print(f"Sembol: {len(symbols)}")

    results = []
    for si, sym in enumerate(symbols, 1):
        all_m1 = get_candles(conn, sym, test_start - WARMUP_MS - 600000, test_end)
        if len(all_m1) < 60:
            continue
        ts_list = [c["ts"] for c in all_m1]
        scans = []
        t = test_start
        while t <= test_end:
            scans.append((t // 300000) * 300000)
            t += 3600000

        for scan_ts in scans:
            try:
                i = ts_list.index(scan_ts)
            except ValueError:
                continue
            end_i = i - 1
            if end_i < 40:
                continue
            window = all_m1[max(0, end_i - 89):end_i + 1]
            if len(window) < 30:
                continue
            hs = [c["h"] for c in window]; ls = [c["l"] for c in window]
            cs = [c["c"] for c in window]; vs = [c["v"] for c in window]
            tags = tags_m1(hs, ls, cs, vs)
            score = score_tags(tags)
            if score < MIN_SCORE_ENTRY:
                continue
            future = [c for c in all_m1 if c["ts"] > scan_ts and c["ts"] <= scan_ts + HOLD_CANDLES * 60000]
            if len(future) < 10:
                continue
            entry = cs[-1]
            max_high = max(c["h"] for c in future)
            upside = (max_high - entry) / entry * 100 if entry else 0
            success = upside >= SUCCESS_UPSIDE_PCT
            results.append({
                "symbol": sym, "scan_ts": scan_ts,
                "time": datetime.fromtimestamp(scan_ts / 1000).strftime("%m-%d %H:%M"),
                "score": round(score, 1), "tags": sorted(tags), "entry": entry,
                "upside_pct": round(upside, 2), "success": success,
            })
        if si % 50 == 0:
            print(f"  {si}/{len(symbols)}")

    conn.close()
    total = len(results)
    succ = sum(1 for r in results if r["success"])
    rate = succ / total * 100 if total else 0
    print(f"""
+{"=" * 66}
| 24s BACKTEST v2 SONUCU
+{"=" * 66}
| Pencere: {datetime.fromtimestamp(test_start/1000).strftime('%m-%d %H:%M')} -> {datetime.fromtimestamp(test_end/1000).strftime('%m-%d %H:%M')}
| Sinyal : {total}  (MIN_SCORE={MIN_SCORE_ENTRY})
| Basari : {succ}
| ORAN   : %{rate:.1f}
+{"-" * 66}
""")

    if results:
        print("Skor bandi:")
        for lo, hi in [(3, 5), (5, 7), (7, 10), (10, 100)]:
            band = [r for r in results if lo <= r["score"] < hi]
            if band:
                s = sum(1 for r in band if r["success"])
                print(f"  skor[{lo}-{hi}): {len(band):>4} sin, %{s/len(band)*100:.1f}")

    # Engelleyici etkisi: negatif tag icerenler
    neg_tags = [t for t, w in DISCRIMINATING.items() if w < 0]
    neg = [r for r in results if any(t in neg_tags for t in r["tags"])]
    pos_only = [r for r in results if not any(t in neg_tags for t in r["tags"])]
    if neg:
        print(f"\nEngele takilan (hic olmamasi gerekirdi): {len(neg)}")
    if pos_only:
        print(f"Engelleyici olmayan (temiz pozitif): {len(pos_only)} sin, "
              f"%{sum(1 for r in pos_only if r['success'])/len(pos_only)*100:.1f} basari")

    # En iyi ikili kombinasyonlar
    from collections import defaultdict
    pairs = defaultdict(lambda: {"n": 0, "s": 0})
    for r in results:
        for a in range(len(r["tags"])):
            for b in range(a + 1, len(r["tags"])):
                key = tuple(sorted([r["tags"][a], r["tags"][b]]))
                if any(t in neg_tags for t in key):
                    continue
                pairs[key]["n"] += 1
                if r["success"]:
                    pairs[key]["s"] += 1
    combos = [(k, v["n"], v["s"]) for k, v in pairs.items() if v["n"] >= 20]
    combos.sort(key=lambda x: -x[2] / x[1])
    print("\nEn iyi temiz ikili kombinasyonlar:")
    for k, n, s in combos[:15]:
        print(f"  {k[0]:<24} + {k[1]:<24} {n:>4} sin, %{s/n*100:.1f}")

    # Desen bazli basari
    tag_total, tag_success = Counter(), Counter()
    for r in results:
        for t in r["tags"]:
            tag_total[t] += 1
            if r["success"]:
                tag_success[t] += 1
    print("\nDesen bazli basari (ilginc olanlar):")
    for t, cnt in tag_total.most_common(25):
        s = tag_success[t]
        print(f"  {t:<26} {cnt:>4} sin  %{s/cnt*100 if cnt else 0:>5.1f}")

    report = {"total": total, "success": succ, "rate": rate, "min_score": MIN_SCORE_ENTRY, "results": results}
    out = os.path.join(os.path.dirname(__file__), "..", "..", "..", "bt_24h_m1_v2_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, default=str)
    print(f"\nRapor: {out}")


if __name__ == "__main__":
    run()