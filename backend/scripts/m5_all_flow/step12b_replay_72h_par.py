#!/usr/bin/env python3
"""
step12b - %65 filtre seti 72s replay (PARALEL - 12 worker).

Her sembol ayri thread'de islenir, her thread kendi PG baglantisi alir.
Sonuclar ana surecte toplanir. GPU/sinir yok, IO-bound; 12 worker ideal.
"""

import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_env = os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", ".env")
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

TARGET = 1.0
MIN_SCORE = 2.5
TEST_HOURS = 72
EXCLUDE_LAST_HOURS = 6
WORKERS = 16

FILTERS = [
    ("g0_chg5", 1.2177), ("g0_chg3", 0.8834), ("g0_roc", 1.6839),
    ("g0_atr", 0.5779), ("g1_atr", 0.5432), ("g2_atr", 0.5097),
]


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


def group_values(highs, lows, closes, volumes):
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
    a = adx(highs, lows, closes)
    vals["adx"] = a["adx"] if a else None
    vals["mfi"] = mfi(highs, lows, closes, volumes)
    vals["bb_pos"] = bollinger_pos(closes)
    vw = vwap(highs, lows, closes, volumes)
    vals["vwap_dist"] = (close / vw - 1) * 100 if vw else None
    return vals


def get_candles(conn, sym, tf, start_ms, end_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume FROM historical_candles
        WHERE symbol=%s AND timeframe=%s AND open_time>=%s AND open_time<=%s ORDER BY open_time ASC
    """, (sym, tf, int(start_ms), int(end_ms)))
    return [{"ts": r[0], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]


def process_symbol(sym, test_start, test_end, M5_WARMUP, M1_WARMUP):
    import psycopg
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    try:
        m5_all = get_candles(conn, sym, "5m", test_start - M5_WARMUP - 600000, test_end)
        if len(m5_all) < 100:
            return []
        recs = []
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

            score = 0.0
            neg = 0
            def chk(v, lo, val=1.0, invert=False):
                nonlocal score, neg
                if v is None:
                    return
                ok = v >= lo
                if invert:
                    ok = v <= lo
                if ok:
                    if val < 0:
                        neg += 1
                    score += val
            chk(m1g1_v["atr_pct"], 0.3, 2.0)
            chk(m1g1_v["atr_pct"], 0.5, 0.5)
            chk(g1_v["roc"], 5, 3.0)
            chk(g1_v["chg5"], 1, 2.0)
            chk(g1_v["chg3"], 0.5, 1.5)
            chk(g1_v["stoch"], 80, 1.0)
            chk(g1_v["cmo"], 25, 1.0)
            chk(g1_v["vwap_dist"], 0, 1.0)
            chk(g2_v["roc"], 5, 1.5)
            chk(m1g1_v["atr_pct"], 0.3, 1.0)
            chk(g0_v["chg5"], -1, -3.0, invert=True)
            chk(g0_v["bb_pos"], 0.2, -3.0, invert=True)
            chk(g0_v["stoch"], 20, -3.0, invert=True)
            chk(g0_v["rsi"], 40, -3.0, invert=True)
            chk(g0_v["cmo"], -25, -3.0, invert=True)
            chk(g0_v["vol_ratio"], 0.8, -2.0, invert=True)
            if neg > 0 or score < MIN_SCORE:
                continue

            fut = get_candles(conn, sym, "1m", cur_ms, cur_ms + 6 * 60000)
            if len(fut) < 3:
                continue
            max_h = max(c["h"] for c in fut)
            upside = (max_h / prev_close - 1) * 100 if prev_close else 0
            hit = upside >= TARGET

            passes_f65 = True
            for fname, thr in FILTERS:
                grp, var = fname.split("_", 1)
                # g0_v/g1_v/g2_v anahtarları: atr_pct (filtre adındaki "atr" → atr_pct)
                real_key = "atr_pct" if var == "atr" else var
                vv = {"g0": g0_v, "g1": g1_v, "g2": g2_v}.get(grp, {}).get(real_key)
                if vv is None or vv < thr:
                    passes_f65 = False
                    break

            recs.append({"symbol": sym, "ts": cur_ms, "score": round(score, 2),
                         "upside": round(upside, 3), "hit": hit, "f65": passes_f65,
                         "g0_chg5": g0_v["chg5"], "g0_chg3": g0_v["chg3"], "g0_roc": g0_v["roc"],
                         "g0_atr": g0_v["atr_pct"], "g1_atr": g1_v["atr_pct"], "g2_atr": g2_v["atr_pct"]})
        return recs
    finally:
        conn.close()


def main():
    import psycopg
    conn0 = psycopg.connect(os.environ["DATABASE_URL"])
    cur = conn0.cursor()
    cur.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='5m' ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]
    conn0.close()

    now_ms = int(time.time() * 1000)
    test_end = now_ms - EXCLUDE_LAST_HOURS * 3600000
    test_start = test_end - TEST_HOURS * 3600000
    M5_WARMUP = 3 * 3600000
    M1_WARMUP = 150 * 60000

    print(f"PARALEL 72s replay ({WORKERS} worker): {len(symbols)} sembol")
    print(f"Pencere: {time.strftime('%m-%d %H:%M', time.localtime(test_start/1000))} -> "
          f"{time.strftime('%m-%d %H:%M', time.localtime(test_end/1000))}")

    t0 = time.time()
    all_records = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process_symbol, sym, test_start, test_end, M5_WARMUP, M1_WARMUP): sym for sym in symbols}
        done = 0
        for fut in as_completed(futures):
            try:
                recs = fut.result()
                all_records.extend(recs)
            except Exception as e:
                print(f"  hata {futures[fut]}: {type(e).__name__} {e}")
            done += 1
            if done % 20 == 0 or done == len(symbols):
                print(f"  {done}/{len(symbols)} sembol, {time.time()-t0:.0f}s")

    records = all_records
    conn0 = psycopg.connect(os.environ["DATABASE_URL"])
    conn0.close()
    total = len(records)
    hits = sum(1 for r in records if r["hit"])
    print(f"\n=== 72s REPLAY - TEMEL DESEN ===")
    print(f"Sinyal: {total} | Basarili(+%{TARGET}): {hits} (%{hits/total*100:.1f})")

    f65 = [r for r in records if r["f65"]]
    f65h = sum(1 for r in f65 if r["hit"])
    print(f"\n=== %65 FILTRE SETI (6 esik) ===")
    print(f"Sinyal: {len(f65)} | Basarili: {f65h} (%{f65h/len(f65)*100 if f65 else 0:.1f}) | recall %{len(f65)/total*100:.1f}")
    print(f"Süre: {time.time()-t0:.0f}s")

    print("\n=== ALT PENCERELER (tutarlilik) ===")
    for hi_h, lo_h in [(72, 48), (48, 24), (24, 0)]:
        lo_ms = test_end - hi_h * 3600000
        hi_ms = test_end - lo_h * 3600000
        sub = [r for r in records if lo_ms <= r["ts"] <= hi_ms]
        if sub:
            h = sum(1 for r in sub if r["hit"])
            print(f"  T-{hi_h}h..T-{lo_h}h: {len(sub)} sin, %{h/len(sub)*100:.1f}")
        sub_f = [r for r in sub if r["f65"]]
        if sub_f:
            hf = sum(1 for r in sub_f if r["hit"])
            print(f"    [+filtre]: {len(sub_f)} sin, %{hf/len(sub_f)*100:.1f}")

    # f65 ile ilgili ilginc: miss ornekleri
    print("\nFiltre sonrasi HATALI ornekler (ilk 8):")
    for r in [x for x in f65 if not x["hit"]][:8]:
        print(f"  {time.strftime('%m-%d %H:%M', time.localtime(r['ts']/1000))} {r['symbol']:<12} "
              f"skor={r['score']}  upside={r['upside']:+.2f}%")
    print("Filtre sonrasi BASARILI ornekler (ilk 5):")
    for r in [x for x in f65 if x["hit"]][:5]:
        print(f"  {time.strftime('%m-%d %H:%M', time.localtime(r['ts']/1000))} {r['symbol']:<12} "
              f"skor={r['score']}  upside={r['upside']:+.2f}%")

    out = {"total": total, "hit": hits, "rate": hits/total*100,
           "f65_n": len(f65), "f65_hit": f65h, "f65_rate": f65h/len(f65)*100 if f65 else 0,
           "workers": WORKERS, "duration_sec": round(time.time()-t0, 1)}
    # ---- FILTRE ARA: farkli esik kombinasyonlarini tek veri setinde dene ----
    if records:
        # ---- F65 sinyallerinin UPSIDE DAGILIMI ----
        f65_all = [r for r in records if r["f65"]]
        if f65_all:
            ups = sorted(r["upside"] for r in f65_all)
            arr = np.array(ups)
            print("\n=== F65 FILTRELI SINYAL UPSIDE DAGILIMI ===")
            print(f"  N={len(f65_all)}")
            print(f"  min={arr.min():.2f}  p10={np.percentile(arr,10):.2f}  p25={np.percentile(arr,25):.2f}  "
                  f"medyan={np.median(arr):.2f}  p75={np.percentile(arr,75):.2f}  p90={np.percentile(arr,90):.2f}  max={arr.max():.2f}")
            for lo, hi in [(-10, 0), (0, 0.5), (0.5, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 100)]:
                band = [r for r in f65_all if lo <= r["upside"] < hi]
                if band:
                    print(f"  upside[{lo}..{hi}): {len(band):>4} sinyal (%{len(band)/len(f65_all)*100:.1f})")
            hits = [r for r in f65_all if r["hit"]]
            miss = [r for r in f65_all if not r["hit"]]
            if hits:
                h_arr = np.array([r["upside"] for r in hits])
                print(f"  BASARILI(+%1): {len(hits)} sin  ort={h_arr.mean():.2f}  medyan={np.median(h_arr):.2f}  "
                      f"p90={np.percentile(h_arr,90):.2f}  max={h_arr.max():.2f}")
            if miss:
                m_arr = np.array([r["upside"] for r in miss])
                print(f"  HATALI: {len(miss)} sin  ort={m_arr.mean():.2f}  p25={np.percentile(m_arr,25):.2f}  min={m_arr.min():.2f}")
            top = sorted(f65_all, key=lambda r: -r["upside"])[:10]
            print("  En iyi 10:")
            for r in top:
                print(f"    {time.strftime('%m-%d %H:%M', time.localtime(r['ts']/1000))} {r['symbol']:<10} upside={r['upside']:+.2f}%")
        print("\n=== FILTRE KOMBINASYON ARA (72s gercekci esikler) ===")
        def test_filters(fs):
            keep = [r for r in records if all(r.get(k) is not None and r.get(k) >= v for k, v in fs)]
            if not keep:
                return None
            h = sum(1 for r in keep if r["hit"])
            return (len(keep), h / len(keep) * 100)

        alpha_sets = {
            "tek-g0_atr>=0.30": [("g0_atr", 0.30)],
            "tek-g0_atr>=0.40": [("g0_atr", 0.40)],
            "tek-g0_chg5>=1.0": [("g0_chg5", 1.0)],
            "ikili-g0_atr+g0_chg5": [("g0_atr", 0.30), ("g0_chg5", 1.0)],
            "ikili-g0_atr+g0_roc": [("g0_atr", 0.30), ("g0_roc", 1.5)],
            "ikili-g0_chg5+g1_atr": [("g0_chg5", 1.0), ("g1_atr", 0.30)],
            "uclu-atr+chg5+roc": [("g0_atr", 0.30), ("g0_chg5", 1.0), ("g0_roc", 1.5)],
            "uclu-atr+chg3+roc": [("g0_atr", 0.30), ("g0_chg3", 0.8), ("g0_roc", 1.5)],
            "4lu-atr3x+chg5": [("g0_atr", 0.30), ("g1_atr", 0.30), ("g2_atr", 0.30), ("g0_chg5", 1.0)],
            "4lu-atr+g1atr+chg5+roc": [("g0_atr", 0.30), ("g1_atr", 0.30), ("g0_chg5", 1.0), ("g0_roc", 1.0)],
            "6lu-tamam-orijinal": [("g0_chg5", 1.2177), ("g0_chg3", 0.8834), ("g0_roc", 1.6839),
                                   ("g0_atr", 0.5779), ("g1_atr", 0.5432), ("g2_atr", 0.5097)],
        }
        for name, fs in alpha_sets.items():
            res = test_filters(fs)
            if res:
                print(f"  {name:<28} {res[0]:>5} sinyal  %{res[1]:.1f}  recall %{res[0]/total*100:.1f}")
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "replay_f65_upside_raporu.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nKaydedildi: replay_f65_upside_raporu.json")


if __name__ == "__main__":
    main()