"""ATR filtresi + goreli guc (ret15) BIRLIKTE: kesismede kar var mi?

Onceki olcumler (ayri ayri):
  atr_pct >= 1.0            -> +0.320% (2 seed, gercek mum replay)
  ret15 ust ceyrek (goreli) -> +0.144% fark (TEST), ama mutlak -0.221% (zarar)
Bu betik IKISINI ayni anda uygular: ATR gecen adaylar ARASINDA ret15'e gore
ust ceyrek. Kesisme karli mi?
"""
from __future__ import annotations
import argparse, statistics as st
from collections import defaultdict
import psycopg

DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"
BUCKET = 30


def prior_return(cur, symbol, t0, minutes):
    t_ms = int(float(t0) * 1000)
    cur.execute("""SELECT close FROM historical_candles
        WHERE symbol=%s AND timeframe='1m' AND open_time <= %s AND open_time >= %s
        ORDER BY open_time ASC""", (symbol, t_ms, t_ms - minutes * 60_000))
    rows = cur.fetchall()
    if len(rows) < 2:
        return None
    f, l = float(rows[0][0]), float(rows[-1][0])
    return (l / f - 1) * 100 if f > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60000)
    ap.add_argument("--min-atr", type=float, default=1.0)
    ap.add_argument("--lookback", type=int, default=15)
    a = ap.parse_args()

    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("""SELECT symbol, created_at, price, coalesce(atr_pct,0), net_pct
            FROM velocity_candidates
            WHERE net_pct IS NOT NULL AND created_at > 0 AND price > 0
              AND coalesce(atr_pct,0) >= %s
            ORDER BY created_at LIMIT %s""", (a.min_atr, a.limit))
        rows = cur.fetchall()
        print(f"ATR>={a.min_atr} gecen aday: {len(rows)}")

        buckets = defaultdict(list)
        cache = {}
        for sym, t0, px, atr, net in rows:
            k = int(float(t0) // (BUCKET * 60))
            key = (sym, int(float(t0)))
            if key not in cache:
                cache[key] = prior_return(cur, sym, t0, a.lookback)
            r = cache[key]
            if r is not None:
                buckets[k].append((r, float(net)))

    keys = sorted(buckets)
    split = int(len(keys) * 0.70)

    def ev(sel):
        tops, bots, alls, ok = [], [], [], 0
        for k in sel:
            v = buckets[k]
            if len(v) < 4:
                continue
            v.sort(key=lambda x: x[0])
            q = max(1, len(v) // 2)   # yarim: ust/alt %50
            top = [n for _r, n in v[-q:]]
            bot = [n for _r, n in v[:q]]
            tops.append(st.mean(top)); bots.append(st.mean(bot))
            alls.extend(n for _r, n in v)
            if st.mean(top) > st.mean(bot):
                ok += 1
        if not alls:
            return None
        return {"n": len(alls), "ort": st.mean(alls), "med": st.median(alls),
                "kaz": 100 * sum(1 for x in alls if x > 0) / len(alls),
                "top": st.mean(tops) if tops else 0, "bot": st.mean(bots) if bots else 0,
                "yön": 100 * ok / len(tops) if tops else 0}

    for label, sel in (("TRAIN", keys[:split]), ("TEST", keys[split:])):
        r = ev(sel)
        if not r:
            print(f"  {label}: veri yok"); continue
        print(f"\n{label} (kova={len(sel)})")
        print(f"  ATR gecen TUMU : n={r['n']:>6} ort={r['ort']:>+7.3f}% med={r['med']:>+7.3f}% kaz={r['kaz']:.1f}%")
        print(f"  ret{a.lookback} UST yarim : {r['top']:>+7.3f}%")
        print(f"  ret{a.lookback} ALT yarim : {r['bot']:>+7.3f}%")
        print(f"  fark (ust-alt)  : {r['top']-r['bot']:>+7.3f}%  yon={r['yön']:.1f}%")


if __name__ == "__main__":
    main()
