"""OI PENCERE OPTIMIZASYONU — 60 dk keyfi secilmisti, taranmadi.

ONCEKI BULGU (docs §19): onceki 60 dk OI degisimi, trailing cikisiyla 5 seed
pozitif, Q5-Q1 ortalama +0.917% (ATR'nin 2.5 kati). Ama 60 dk KEYFI bir secimdi.

SORU: hangi pencere en iyi ayristiriyor? Kisa pencere (15 dk) daha taze ama
gurultulu; uzun pencere (240 dk) daha kararli ama gec kalabilir.

YONTEM: Ayni adaylar, AYNI replay — yalniz OI penceresi degisir. Boylece
replay gurultusu sabit kalir, tek degisken pencere olur (kontrollu deney).
"""
from __future__ import annotations

import argparse
import os
import random
import statistics as st
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"
FEE = float(os.getenv("FEE", "0.30"))
WINDOWS = (5, 10, 15, 20, 30, 60, 120, 240)


def fetch(limit, seed):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""
            SELECT v.symbol, v.created_at, v.price, coalesce(v.atr_pct,0),
                   v.net_pct, sm.perp_symbol
              FROM velocity_candidates v
              JOIN futures_symbol_map sm ON sm.try_symbol = v.symbol
             WHERE v.net_pct IS NOT NULL AND v.price > 0 AND v.created_at > 0
             ORDER BY random() LIMIT %s""", (limit,))
        base = cur.fetchall()
    base.sort(key=lambda r: r[1])   # kronolojik (TRAIN/TEST gecerli)
    return base


def oi_change(cur, perp, t0, win_min):
    cur.execute("""select sum_open_interest_value from hist_futures_metrics
        where perp_symbol=%s and ts_ms >= (%s-%s)*1000 and ts_ms < %s*1000
        order by ts_ms""", (perp, t0, win_min * 60, t0))
    vals = [float(r[0]) for r in cur.fetchall() if r[0]]
    if len(vals) < 3 or vals[0] <= 0:
        return None
    return (vals[-1] / vals[0] - 1) * 100


def replay(cur, symbol, t0, price, gap, sl_pct, max_min):
    t_ms = int(float(t0) * 1000)
    cur.execute("""select high, low, close from historical_candles
        where symbol=%s and timeframe='1m' and open_time>=%s and open_time<=%s
        order by open_time limit %s""",
                (symbol, t_ms - 60_000, t_ms + max_min * 60_000, max_min + 2))
    bars = cur.fetchall()
    if len(bars) < 3:
        return None
    entry, best, exit_px = float(price), float(price), None
    for hi, _lo, cl in bars:
        if hi > best:
            best = hi
        lvl = max(best * (1 - gap / 100), entry * (1 - sl_pct / 100))
        if cl <= lvl:
            exit_px = lvl
            break
    if exit_px is None:
        exit_px = bars[-1][2]
    return (exit_px / entry - 1) * 100 - FEE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--max-min", type=int, default=240, dest="max_min")
    a = ap.parse_args()

    base = fetch(a.limit, a.seed)
    print(f"aday={len(base)} seed={a.seed} gap={a.gap}% sl={a.sl}% "
          f"max={a.max_min}dk fee={FEE}%\n")
    print("  Ayni adaylar, ayni replay; YALNIZ OI penceresi degisiyor.\n")

    print(f"  {'pencere':>8} {'n':>5} {'Q1 ort':>9} {'Q5 ort':>9} {'Q5-Q1':>9} "
          f"{'Q5 kaz':>7} {'Q1 kaz':>7}")
    results = {}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cache = {}
        for win in WINDOWS:
            pairs = []
            for sym, t0, px, atr, _net, perp in base:
                key = (sym, t0)
                if key not in cache:
                    cache[key] = replay(cur, sym, t0, px, a.gap, a.sl, a.max_min)
                net = cache[key]
                if net is None:
                    continue
                oi = oi_change(cur, perp, t0, win)
                if oi is not None:
                    pairs.append((oi, net))
            if len(pairs) < 200:
                print(f"  {win:>7}dk {len(pairs):>5}  orneklem kucuk")
                continue
            pairs.sort(key=lambda p: p[0])
            cut = max(1, len(pairs) // 5)
            q1 = [n for _, n in pairs[:cut]]
            q5 = [n for _, n in pairs[-cut:]]
            d = st.mean(q5) - st.mean(q1)
            results[win] = d
            print(f"  {win:>7}dk {len(pairs):>5} {st.mean(q1):>+8.3f}% "
                  f"{st.mean(q5):>+8.3f}% {d:>+8.3f}% "
                  f"{100*sum(1 for x in q5 if x>0)/len(q5):>6.1f}% "
                  f"{100*sum(1 for x in q1 if x>0)/len(q1):>6.1f}%")

    if results:
        best = max(results, key=results.get)
        print(f"\n  EN IYI PENCERE: {best} dk -> Q5-Q1 {results[best]:+.3f}%")
        print(f"  (60 dk mevcut varsayilan: {results.get(60, float('nan')):+.3f}%)")


if __name__ == "__main__":
    main()
