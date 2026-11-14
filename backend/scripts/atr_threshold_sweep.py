"""ATR esik taramasi — GERCEK 1m mum + trailing cikisi (uretim modeli).

SORU: min_atr_pct icin en iyi esik kac? (su an 1.0)
NOT: net_pct KULLANILMAZ (sabit TP/SL simulasyonu; ATR ile ters calisir).
     Gercek mum yolu + trailing (uretim cikis modeli) kullanilir.

Cikis modeli: trailing gap (tepeden) + sabit SL, azami sure.
Her esik icin: kabul orani, ort net, medyan, kazanan orani.
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
        cur.execute("""select symbol, created_at, price, coalesce(atr_pct,0), net_pct
            from velocity_candidates
            where net_pct is not null and price>0 and created_at>0
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

    thresholds = [0.0, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]
    print(f"  {'atr>=':>6} {'kabul':>6} {'n':>5} {'ort_net':>9} {'medyan':>9} {'kazanan':>8}")
    results = []
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for t in thresholds:
            nets = []
            for sym, t0, px, atr, _np in cands:
                if float(atr) < t:
                    continue
                r = replay(cur, sym, t0, px, a.gap, a.sl, a.max_min)
                if r is not None:
                    nets.append(r)
            if len(nets) < 15:
                print(f"  {t:>6.1f} {'':>6} {len(nets):>5}  orneklem kucuk")
                continue
            m, md = st.mean(nets), st.median(nets)
            k = 100 * sum(1 for x in nets if x > 0) / len(nets)
            sd = st.stdev(nets) if len(nets) > 1 else 0.0
            se = sd / (len(nets) ** 0.5)
            results.append((t, len(nets), m, se, md, k))
            print(f"  {t:>6.1f} {100*len(nets)/len(cands):>5.1f}% {len(nets):>5} "
                  f"{m:>+8.3f}% {md:>+8.3f}% {k:>7.1f}%  (se={se:.3f})")

    if results:
        best = max(results, key=lambda x: x[2] - x[3])  # muhafazakar: ort - se
        print(f"\n  EN IYI (ort-se bazli, muhafazakar): atr>={best[0]:.1f} "
              f"-> {best[2]:+.3f}% (n={best[1]})")


if __name__ == "__main__":
    main()
