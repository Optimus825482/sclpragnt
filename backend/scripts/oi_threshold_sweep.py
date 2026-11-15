"""OI ESIGI TARAMASI — panel parametresi min_oi_change_pct icin GERCEK sayi.

DURUM: §24'te OI'nin ATR ile tamamlayici oldugu kanitlandi. Ama panel parametresi
`min_oi_change_pct` sayisal bir esik istiyor ve §19/§24 medyan kullandi
(analiz icin dogru, canli panel icin degil).

SORU: esik kac olmali? Ve en onemlisi: ATR>=1.0 ZATEN ACİKSA (mevcut varsayilan),
OI esigi EK katki yapiyor mu?

Bu ikinci soru kritik: canlida ATR zaten acik. OI'yi acmak icin ATR'nin ustune
GERCEK deger eklemesi lazim, yoksa gereksiz karmasiklik olur.

YONTEM: ayni adaylar, ayni replay. Iki rejim:
  A) ATR baz (filtresiz)     -> OI esigi tek basina ne yapiyor
  B) ATR>=1.0 ZATEN ACİK     -> OI esigi ATR'nin USTUNE ne ekliyor  <-- karar bu
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
OI_WIN = 15
THRESHOLDS = (-1.0, 0.0, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0)


def fetch(limit, seed):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""
            SELECT v.symbol, v.created_at, v.price, coalesce(v.atr_pct,0),
                   sm.perp_symbol
              FROM velocity_candidates v
              JOIN futures_symbol_map sm ON sm.try_symbol = v.symbol
             WHERE v.net_pct IS NOT NULL AND v.price > 0 AND v.created_at > 0
             ORDER BY random() LIMIT %s""", (limit,))
        base = cur.fetchall()
    base.sort(key=lambda r: r[1])
    return base


def oi_change(cur, perp, t0):
    cur.execute("""select sum_open_interest_value from hist_futures_metrics
        where perp_symbol=%s and ts_ms >= (%s-%s)*1000 and ts_ms < %s*1000
        order by ts_ms""", (perp, t0, OI_WIN * 60, t0))
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


def stat(vals):
    if len(vals) < 20:
        return None
    return (len(vals), st.mean(vals),
            100 * sum(1 for x in vals if x > 0) / len(vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1600)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--max-min", type=int, default=240, dest="max_min")
    a = ap.parse_args()

    base = fetch(a.limit, a.seed)
    rows = []
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for sym, t0, px, atr, perp in base:
            net = replay(cur, sym, t0, px, a.gap, a.sl, a.max_min)
            if net is None:
                continue
            oi = oi_change(cur, perp, t0)
            if oi is None:
                continue
            rows.append((float(atr), oi, net))

    print(f"aday={len(base)} eslesen={len(rows)} seed={a.seed} "
          f"OI penceresi={OI_WIN}dk fee={FEE}%\n")
    if len(rows) < 400:
        print("orneklem yetersiz")
        return

    atr_rows = [r for r in rows if r[0] >= 1.0]
    print(f"ATR>=1.0 alt kumesi: {len(atr_rows)} aday\n")

    for title, sub in (("A) ATR FILTRESI YOK", rows),
                       ("B) ATR>=1.0 ZATEN ACIK (canli varsayilan)", atr_rows)):
        print(f"=== {title} ===")
        if len(sub) < 100:
            print("  orneklem kucuk\n")
            continue
        base_m = st.mean(n for _a, _o, n in sub)
        print(f"  {'esik':>8} {'n':>5} {'ort':>9} {'kaz':>7} {'tabana gore':>12}")
        for th in THRESHOLDS:
            vals = [n for _a, o, n in sub if o > th]
            s = stat(vals)
            if not s:
                print(f"  {th:>+7.1f}% {'kucuk':>5}")
                continue
            print(f"  {th:>+7.1f}% {s[0]:>5} {s[1]:>+8.3f}% {s[2]:>6.1f}% "
                  f"{s[1]-base_m:>+11.3f}%")
        print(f"  {'(taban)':>8} {len(sub):>5} {base_m:>+8.3f}% "
              f"{100*sum(1 for _a,_o,n in sub if n>0)/len(sub):>6.1f}%")
        print()


if __name__ == "__main__":
    main()
