"""ATR x trailing parametre izgarasi — ATR oynakligina gore trailing uyarlanmali mi?

MOTIVASYON: ATR calisan TEK boyut (docs/YUKSELIS_ARASTIRMASI §17). Ama trailing
parametreleri SABIT yuzde: `_trailing_params` ATR'ye hic bakmiyor
(trailing_trigger_pct=2.0, trailing_gap_pct=1.0).

SORU: gap/trigger ATR ile olceklenirse daha iyi mi? Oynak coin daha genis gap
(nefes alani), sakin coin daha dar gap (hizli kilit) isteyebilir.

YONTEM: Gercek 1m mum. Her aday icin ATR'ye gore bir gap sec, replay et.
  - sabit gap (mevcut davranis)
  - ATR-olcekli gap: gap = clamp(k * atr_pct, min, max)
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


def fetch(limit, seed, min_atr):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select symbol, created_at, price, coalesce(atr_pct,0)
            from velocity_candidates
            where net_pct is not null and price>0 and created_at>0
              and coalesce(atr_pct,0) >= %s
            order by random() limit %s""", (min_atr, limit))
        return cur.fetchall()


def bars_for(cur, symbol, t0, max_min, cache):
    key = (symbol, int(float(t0)))
    if key in cache:
        return cache[key]
    t_ms = int(float(t0) * 1000)
    cur.execute("""select high, low, close from historical_candles
        where symbol=%s and timeframe='1m' and open_time>=%s and open_time<=%s
        order by open_time limit %s""",
                (symbol, t_ms - 60_000, t_ms + max_min * 60_000, max_min + 2))
    b = cur.fetchall()
    cache[key] = b
    return b


def run(cur, cands, gap_fn, sl_pct, max_min, cache):
    nets = []
    for sym, t0, px, atr in cands:
        bars = bars_for(cur, sym, t0, max_min, cache)
        if len(bars) < 3:
            continue
        gap = gap_fn(float(atr))
        entry = float(px)
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
        nets.append((exit_px / entry - 1) * 100 - FEE)
    return nets


def summarize(nets):
    if len(nets) < 10:
        return None
    return {"n": len(nets), "ort": st.mean(nets), "med": st.median(nets),
            "kaz": 100 * sum(1 for x in nets if x > 0) / len(nets),
            "se": (st.stdev(nets) / len(nets) ** 0.5) if len(nets) > 1 else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min-atr", type=float, default=1.0, dest="min_atr")
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--max-min", type=int, default=240, dest="max_min")
    a = ap.parse_args()

    cands = fetch(a.limit, a.seed, a.min_atr)
    print(f"aday={len(cands)} (atr>={a.min_atr}) seed={a.seed} sl={a.sl}% "
          f"max={a.max_min}dk fee={FEE}%\n")

    schemes = [
        ("sabit 0.3%", lambda atr: 0.3),
        ("sabit 0.5%", lambda atr: 0.5),
        ("sabit 1.0% (mevcut)", lambda atr: 1.0),
        ("ATR*0.25", lambda atr: max(0.2, min(2.0, atr * 0.25))),
        ("ATR*0.35", lambda atr: max(0.2, min(2.5, atr * 0.35))),
        ("ATR*0.50", lambda atr: max(0.2, min(3.0, atr * 0.50))),
        ("ATR*0.75", lambda atr: max(0.3, min(4.0, atr * 0.75))),
    ]

    print(f"  {'gap semasi':>22} {'n':>5} {'ort_net':>9} {'medyan':>9} {'kazanan':>8} {'se':>7}")
    cache: dict = {}
    results = []
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for name, fn in schemes:
            s = summarize(run(cur, cands, fn, a.sl, a.max_min, cache))
            if not s:
                print(f"  {name:>22}  orneklem kucuk")
                continue
            results.append((name, s))
            print(f"  {name:>22} {s['n']:>5} {s['ort']:>+8.3f}% {s['med']:>+8.3f}% "
                  f"{s['kaz']:>7.1f}% {s['se']:>6.3f}")

    if results:
        best = max(results, key=lambda x: x[1]["ort"] - x[1]["se"])
        print(f"\n  EN IYI (ort-se): {best[0]} -> {best[1]['ort']:+.3f}%")
        fixed = next((s for n, s in results if n.startswith("sabit 0.3")), None)
        if fixed:
            print(f"  (sabit 0.3% referans: {fixed['ort']:+.3f}%)")


if __name__ == "__main__":
    main()
