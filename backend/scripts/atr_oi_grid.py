"""ATR x OI IZGARASI — §19'daki "birbirini iptal ediyor" bulgusu 60 dk ile olculmustu.

SORU: 15 dk OI penceresiyle bu iptal HALA gecerli mi?
  1) hala iptal  -> biri secilmeli, ikisi birden ACILMAMALI
  2) tamamlayici -> ikisi birden acilinca daha iyi (en degerli ihtimal)
  3) kismen ortusur -> esikler ayarlanmali

YONTEM: ayni adaylar, ayni replay. 2x2 izgara:
  ATR  {<1.0, >=1.0}  x  OI {dusuk (<=median), yuksek (>median)}
Ayrica ATR'yi ve OI'yi TEK BASINA olcup FLIP (tekrarli bilgi) testi yapilir:
  - OI'nin ATR ICINDE kalan katkisi (ATR sabitken OI'nin ayristirmasi)
  - ATR'nin OI ICINDE kalan katkisi
Biri digerini yutuyorsa ic-dilim katki sifira yaklasir.
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


def oi_change(cur, perp, t0, win_min=OI_WIN):
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


def cell(vals):
    if len(vals) < 15:
        return None
    return (len(vals), st.mean(vals),
            100 * sum(1 for x in vals if x > 0) / len(vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1500)
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

    med_oi = st.median(r[1] for r in rows)
    print(f"OI medyan esigi: {med_oi:+.3f}%\n")

    # 2x2 izgara
    grid: dict = {}
    for atr, oi, net in rows:
        k = ("ATR>=1" if atr >= 1.0 else "ATR<1", "OI yuk" if oi > med_oi else "OI dus")
        grid.setdefault(k, []).append(net)

    print("=== 2x2 IZGARA ===")
    print(f"  {'hucre':>22} {'n':>5} {'ort':>9} {'kaz':>7}")
    for atr_k in ("ATR<1", "ATR>=1"):
        for oi_k in ("OI dus", "OI yuk"):
            c = cell(grid.get((atr_k, oi_k), []))
            if c:
                print(f"  {atr_k+' / '+oi_k:>22} {c[0]:>5} {c[1]:>+8.3f}% {c[2]:>6.1f}%")
            else:
                print(f"  {atr_k+' / '+oi_k:>22} {'kucuk':>5}")
        if all(cell(grid.get((atr_k, o), [])) for o in ("OI dus", "OI yuk")):
            d = (cell(grid[(atr_k, "OI yuk")])[1]
                 - cell(grid[(atr_k, "OI dus")])[1])
            print(f"    -> OI etkisi (ATR sabit): {d:+.3f}%")
    print()
    for oi_k in ("OI dus", "OI yuk"):
        if all(cell(grid.get((k, oi_k), [])) for k in ("ATR<1", "ATR>=1")):
            d = (cell(grid[("ATR>=1", oi_k)])[1]
                 - cell(grid[("ATR<1", oi_k)])[1])
            print(f"  -> ATR etkisi (OI={oi_k}): {d:+.3f}%")

    # Tek basina + flip
    print("\n=== TEK BASINA vs FLIP (tekrarli bilgi testi) ===")
    hi_atr = [n for at_, _o, n in rows if at_ >= 1.0]
    hi_oi = [n for _a, o, n in rows if o > med_oi]
    both = [n for a_, o, n in rows if a_ >= 1.0 and o > med_oi]
    for name, v in (("ATR>=1 tek basina", hi_atr), ("OI yuk tek basina", hi_oi),
                    ("IKISI BIRDEN", both)):
        c = cell(v)
        if c:
            print(f"  {name:>22}: n={c[0]:>4} ort={c[1]:>+8.3f}% kaz={c[2]:>5.1f}%")
    base_m = st.mean(n for _a, _o, n in rows)
    print(f"  {'Filtresiz':>22}: n={len(rows):>4} ort={base_m:>+8.3f}%")


if __name__ == "__main__":
    main()
