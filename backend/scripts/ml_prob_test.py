"""ML hit probability: kazanmayi ongoruyor MU, KAR ETTIRIYOR mu?

ON BULGU (velocity_candidates, 370.867 aday):
  korelasyon(ml_hit_probability, kazandi) = +0.1709   (GUCLU)
  korelasyon(ml_hit_probability, net_pct) = -0.0277   (sifir)
  prob 0.0-0.2 -> WR %36.8, SL orani %47.1
  prob 0.8-1.0 -> WR %57.9, SL orani %29.4   <- model AYRISTIRIYOR

SORU: bu ayrisma TRAILING cikisiyla KARA donusuyor mu?
      (net_pct = sabit TP/SL; ATR'de oldugu gibi cikis modeline bagimli olabilir)
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


def fetch(limit, seed):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select symbol, created_at, price, coalesce(atr_pct,0),
                              ml_hit_probability, net_pct
            from velocity_candidates
            where net_pct is not null and price>0 and created_at>0
              and ml_hit_probability is not null
            order by random() limit %s""", (limit,))
        return cur.fetchall()


def replay(cur, symbol, t0, price, gap, sl_pct, max_min):
    t_ms = int(float(t0) * 1000)
    cur.execute("""select high, low, close from historical_candles
        where symbol=%s and timeframe='1m' and open_time>=%s and open_time<=%s
        order by open_time limit %s""",
                (symbol, t_ms - 60_000, t_ms + max_min * 60_000, max_min + 2))
    bars = cur.fetchall()
    if len(bars) < 3:
        return None
    entry = float(price)
    best, exit_px = entry, None
    for hi, _lo, cl in bars:
        if hi > best:
            best = hi
        trail = best * (1 - gap / 100)
        hard = entry * (1 - sl_pct / 100)
        lvl = max(trail, hard)
        if cl <= lvl:
            exit_px = lvl
            break
    if exit_px is None:
        exit_px = bars[-1][2]
    return (exit_px / entry - 1) * 100 - FEE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--gap", type=float, default=0.3)
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--max-min", type=int, default=240, dest="max_min")
    a = ap.parse_args()

    cands = fetch(a.limit, a.seed)
    print(f"aday={len(cands)} seed={a.seed} gap={a.gap}% sl={a.sl}% "
          f"max={a.max_min}dk fee={FEE}%\n")

    # Her adayi BIR kez replay et, prob dilimine gore grupla
    buckets = {i: [] for i in range(5)}
    labels = ["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for sym, t0, px, atr, prob, _np in cands:
            p = float(prob)
            idx = min(4, int(p * 5)) if p < 1.0 else 4
            r = replay(cur, sym, t0, px, a.gap, a.sl, a.max_min)
            if r is not None:
                buckets[idx].append((r, float(atr), p))

    print(f"  {'prob dilimi':>13} {'n':>5} {'ort_net':>9} {'medyan':>9} {'kazanan':>8} {'ort_atr':>8}")
    alln = []
    for i, lbl in enumerate(labels):
        v = buckets[i]
        if len(v) < 10:
            print(f"  {lbl:>13} {len(v):>5}  orneklem kucuk")
            continue
        nets = [x[0] for x in v]
        alln.extend(nets)
        print(f"  {lbl:>13} {len(nets):>5} {st.mean(nets):>+8.3f}% {st.median(nets):>+8.3f}% "
              f"{100*sum(1 for x in nets if x>0)/len(nets):>7.1f}% "
              f"{st.mean(x[1] for x in v):>7.2f}%")

    print()
    if buckets[4] and buckets[0]:
        d = st.mean(x[0] for x in buckets[4]) - st.mean(x[0] for x in buckets[0])
        print(f"  prob 0.8-1.0 eksi 0.0-0.2 (trailing): {d:+.3f}%")
        print(f"  {'AYRISTIRIYOR' if d > 0.20 else 'ayristirmiyor (esik +0.20)'}")
    if alln:
        print(f"  TUMU (trailing): {st.mean(alln):+.3f}% (n={len(alln)})")


if __name__ == "__main__":
    main()
