"""ret3_pct olu bolgesi (0..1%) arastirmasi — GERCEK 1m mum replay ile.

Backtest'te U-sekli goruldu (MFE proxy): dip (<-2%) ve momentum (>+2%) iyi,
0..1% OLU BOLGE (en kalabalik grup, 207k aday) en kotu. Proxy MFE yaniltici
oldugu icin (bkz. trail_replay) burada GERCEK mumlarla dogrulaniyor.

Olcumler:
  A) ret3 bolgelerinin gercek replay performansi
  B) "olu bolgeyi disla" filtresinin etkisi (tek basina ve atr ile birlikte)
  C) uretim kapisi (auto_paper._entry_context) uzerinden ayni sonuc mu
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics as st
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"
FEE = float(os.getenv("FEE", "0.30"))


def fetch(limit: int, seed: int):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select symbol, created_at, price,
                              coalesce(atr_pct,0), coalesce(ret3_pct,0),
                              coalesce(velocity_score,0), coalesce(target_pct,0)
                       from velocity_candidates
                       where net_pct is not null and price > 0 and ret3_pct is not null
                       order by random() limit %s""", (limit,))
        return cur.fetchall()


def replay(cands, gap: float, sl: float, max_min: int) -> list[float]:
    nets = []
    with psycopg.connect(DB) as c, c.cursor() as cur:
        for sym, t0, entry, _a, _r, _s, _t in cands:
            t0 = int(t0)
            cur.execute("""select high, low, close from historical_candles
                           where symbol=%s and timeframe='1m'
                             and open_time >= %s and open_time <= %s
                           order by open_time limit %s""",
                        (sym, (t0 - 60) * 1000, (t0 + max_min * 60) * 1000, max_min + 2))
            bars = cur.fetchall()
            if len(bars) < 3:
                continue
            best = entry
            exit_px = None
            for hi, _lo, cl in bars:
                if hi > best:
                    best = hi
                lvl = max(best * (1 - gap / 100), entry * (1 - sl / 100))
                if cl <= lvl:
                    exit_px = lvl
                    break
            if exit_px is None:
                exit_px = bars[-1][2]
            nets.append((exit_px / entry - 1) * 100 - FEE)
    return nets


def stats(nets):
    if not nets:
        return None
    return {
        "n": len(nets),
        "ort": st.mean(nets),
        "med": st.median(nets),
        "kaz": 100 * sum(1 for x in nets if x > 0) / len(nets),
    }


BUCKETS = [(-99, -2), (-2, -1), (-1, 0), (0, 1), (1, 2), (2, 99)]


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=3000)
    p.add_argument("--gap", type=float, default=0.3)
    p.add_argument("--sl", type=float, default=2.0)
    p.add_argument("--max-min", type=int, default=240, dest="max_min")
    p.add_argument("--seed", type=int, default=11)
    a = p.parse_args()

    print(f"ret3_pct arastirmasi | gap={a.gap}% sl={a.sl}% max={a.max_min}dk fee={FEE}%")
    print(f"ornek={a.limit} seed={a.seed}\n")

    cands = fetch(a.limit, a.seed)
    print(f"cekilen aday: {len(cands)}\n")

    # ── A) Bolge bazli gercek replay ────────────────────────────────────────
    print("A) ret3 bolgeleri — GERCEK 1m mum replay")
    print(f"  {'bolge':>12} {'n':>6} {'ort_net':>9} {'medyan':>9} {'kazanan':>8}")
    for lo, hi in BUCKETS:
        sub = [c for c in cands if lo <= c[4] < hi]
        s = stats(replay(sub, a.gap, a.sl, a.max_min))
        if s:
            print(f"  [{lo:>4},{hi:>3}) {s['n']:>6} {s['ort']:>+8.3f}% "
                  f"{s['med']:>+8.3f}% {s['kaz']:>7.1f}%")

    # ── B) Olu bolgeyi disla ────────────────────────────────────────────────
    print("\nB) 'Olu bolgeyi disla' filtresinin etkisi")
    variants = {
        "filtre yok": lambda c: True,
        "ret3 DISLA (0..1)": lambda c: not (0 <= c[4] < 1),
        "ret3 DISLA (0..1.5)": lambda c: not (0 <= c[4] < 1.5),
    }
    print(f"  {'varyant':>22} {'gecen':>7} {'n':>6} {'ort_net':>9} {'medyan':>9} {'kazanan':>8}")
    for name, keep in variants.items():
        sub = [c for c in cands if keep(c)]
        s = stats(replay(sub, a.gap, a.sl, a.max_min))
        if s:
            print(f"  {name:>22} {len(sub):>7} {s['n']:>6} {s['ort']:>+8.3f}% "
                  f"{s['med']:>+8.3f}% {s['kaz']:>7.1f}%")

    print("\n   ATR + olu bolge birlesimi (min_atr=1.0):")
    for name, keep in variants.items():
        sub = [c for c in cands if c[3] >= 1.0 and keep(c)]
        s = stats(replay(sub, a.gap, a.sl, a.max_min))
        if s:
            print(f"  {name:>22} {len(sub):>7} {s['n']:>6} {s['ort']:>+8.3f}% "
                  f"{s['med']:>+8.3f}% {s['kaz']:>7.1f}%")

    # ── C) Uretim kapisi ────────────────────────────────────────────────────
    print("\nC) URETIM KAPISI (auto_paper._entry_context) ile ayni sonuc mu?")
    from gate_replay import decide
    for atr in (0.0, 1.0):
        acc = []
        for sym, t0, price, a_v, r_v, sc, tp in cands:
            notif = {"symbol": sym, "score": sc or 80.0, "mode": "trend_devam",
                     "source": "velocity", "atr_pct": (a_v or None),
                     "price": price, "target_pct": tp}
            ok, _r = await decide(notif, atr)
            if ok:
                acc.append((sym, t0, price, a_v, r_v, sc, tp))
        s = stats(replay(acc, a.gap, a.sl, a.max_min))
        if s:
            print(f"  min_atr={atr:>3} kabul={len(acc):>5} n={s['n']:>5} "
                  f"ort={s['ort']:>+8.3f}% med={s['med']:>+8.3f}% kaz={s['kaz']:>5.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
