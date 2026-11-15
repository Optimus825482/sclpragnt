"""CIKIS TARAFI IZGARASI — trailing_tetigi x trailing_gap. Hic taranmadi.

DURUM: tum bulgular GIRIS tarafinda (ATR, OI). Cikis parametreleri
(trailing_trigger_pct=2.0, trailing_gap_pct=1.0) bugune kadar HIC taranmadi.
Giris kadar buyuk olabilir: ayni aday, farkli cikis -> tamamen farkli sonuc.

IKI PARAMETRE:
  trigger : karin %X'e ulasmasini bekle, sonra trailing baslat
  gap     : tepeden %Y dusunce cik

DIKKAT — BILINEN TUZAK (§18, 2026-10-11 canli geri bildirim):
  gap 0.30 bar replay'de iyi gorunuyor AMA canlida 5 sn ticker gurultusunde
  pozisyon ANINDA kapaniyor. Bu yuzden bar replay gap'i OPTIMISTIK gosterir.
  -> gap taramasinda KUCUK degerleri "kazanan" cikarsa GUVENME.
  Bunu gormek icin "erken kapanma orani" da olculur.

YONTEM: ayni adaylar (ATR>=1.0 + OI>=1.2 filtresinden gecenler = canli
varsayilan), ayni replay, yalniz cikis parametreleri degisir.
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
MIN_ATR = 1.0
MIN_OI = 1.2

TRIGGERS = (0.5, 1.0, 1.5, 2.0, 3.0)
GAPS = (0.3, 0.5, 0.75, 1.0, 1.5)


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


def bars_for(cur, symbol, t0, max_min):
    t_ms = int(float(t0) * 1000)
    cur.execute("""select high, low, close from historical_candles
        where symbol=%s and timeframe='1m' and open_time>=%s and open_time<=%s
        order by open_time limit %s""",
                (symbol, t_ms - 60_000, t_ms + max_min * 60_000, max_min + 2))
    return cur.fetchall()


def replay(bars, price, trigger, gap, sl_pct=2.0):
    """Trailing tetigi + gap. Doner: (net_pct, erken_kapandi_mi, mfe)."""
    if len(bars) < 3:
        return None
    entry = float(price)
    best = entry
    armed = False
    exit_px = None
    mfe = 0.0
    for hi, _lo, cl in bars:
        if hi > best:
            best = hi
        gain = (best / entry - 1) * 100
        if gain > mfe:
            mfe = gain
        if not armed and gain >= trigger:
            armed = True
        floor = max(best * (1 - gap / 100), entry * (1 - sl_pct / 100)) if armed \
            else entry * (1 - sl_pct / 100)
        if cl <= floor:
            exit_px = floor
            break
    if exit_px is None:
        exit_px = bars[-1][2]
    net = (exit_px / entry - 1) * 100 - FEE
    # "erken kapanma": trailing devreye girdikten sonra <=0.5% ile cikti
    early = bool(armed and net <= 0.5)
    return net, early, mfe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1800)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-min", type=int, default=240, dest="max_min")
    a = ap.parse_args()

    base = fetch(a.limit, a.seed)
    cands = []
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for sym, t0, px, atr, perp in base:
            if float(atr) < MIN_ATR:
                continue
            oi = oi_change(cur, perp, t0)
            if oi is None or oi < MIN_OI:
                continue
            b = bars_for(cur, sym, t0, a.max_min)
            if b:
                cands.append((sym, t0, px, b))

    print(f"aday={len(base)} filtre gecen (ATR>={MIN_ATR}, OI>={MIN_OI}%)="
          f"{len(cands)} seed={a.seed} fee={FEE}%")
    if len(cands) < 60:
        print("orneklem yetersiz")
        return

    # 3D onbellek: (trigger, gap) -> listeler
    print(f"\n  Ayni {len(cands)} aday, yalniz cikis parametreleri degisir.\n")
    print(f"  {'trigger':>8} {'gap':>6} {'ort':>9} {'med':>9} {'kaz':>7} "
          f"{'erken':>7} {'MFE':>7}")
    res = {}
    for trig in TRIGGERS:
        for gap in GAPS:
            nets, earlies, mfes = [], [], []
            for _s, _t, px, b in cands:
                r = replay(b, px, trig, gap)
                if r is None:
                    continue
                nets.append(r[0])
                earlies.append(1 if r[1] else 0)
                mfes.append(r[2])
            if len(nets) < 40:
                continue
            res[(trig, gap)] = (st.mean(nets), st.median(nets),
                                100 * sum(1 for x in nets if x > 0) / len(nets),
                                100 * sum(earlies) / len(earlies),
                                st.mean(mfes), len(nets))
            m, md, wr, ea, mfe, n = res[(trig, gap)]
            print(f"  {trig:>7.1f}% {gap:>5.2f}% {m:>+8.3f}% {md:>+8.3f}% "
                  f"{wr:>6.1f}% {ea:>6.1f}% {mfe:>+6.2f}%")

    if not res:
        return
    # mevcut varsayilan (2.0, 1.0)
    cur_v = res.get((2.0, 1.0))
    best = max(res, key=lambda k: res[k][0])
    print(f"\n  MEVCUT varsayilan (trigger 2.0%, gap 1.0%): "
          f"{cur_v[0]:+.3f}% (kaz {cur_v[2]:.1f}%, erken {cur_v[3]:.1f}%, n={cur_v[5]})"
          if cur_v else "\n  MEVCUT varsayilan olculemedi")
    print(f"  EN IYI (trigger {best[0]}%, gap {best[1]}%): "
          f"{res[best][0]:+.3f}% (kaz {res[best][2]:.1f}%, "
          f"erken {res[best][3]:.1f}%, n={res[best][5]})")
    print("\n  NOT: gap kucukse 'erken kapanma' yuksekse CANLIDA DAHA KOTU olur")
    print("       (5 sn ticker gurultusu). Erken orani %30'un uzerindeyse guvenme.")


if __name__ == "__main__":
    main()
