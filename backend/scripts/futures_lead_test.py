"""YUKSELIS ONCU GOSTERGELERI: OI / long-short orani / taker hacmi.

MOTIVASYON: Simdiye kadar test edilen TUM sinyaller FIYAT turevi (velocity_score,
ret15, ATR, ML prob, funding, order flow) ve yalniz ATR calisiyor. Ama asil soru
"hangi sembol YUKSELECEK" — bunun icin fiyattan ONCE olusan pozisyonlanma
gostergeleri gerekir. Futures verisi tam bunu tasiyor:

  hist_futures_metrics (7.5M satir, 291 perp, 5 dk, 2026-07-19 -> 10-16):
    sum_open_interest            toplam acik pozisyon (OI)
    sum_open_interest_value      OI degeri (USDT)
    count_toptrader_long_short_ratio  ust trader long/short (hesap sayisi)
    sum_toptrader_long_short_ratio    ust trader long/short (pozisyon)
    count_long_short_ratio            genel long/short (hesap)
    sum_taker_long_short_vol_ratio    taker alim/satim hacim orani

HIPOTEZLER (aday anindan ONCEKI pencere):
  H-A  OI ARTIYORSA (yeni para giriyor) + fiyat yukseliyorsa -> devam eder
  H-B  OI ARTMIYORSA (short covering ile yukseliyor) -> tukenir
  H-C  TOP TRADER long orani yuksekse -> devam eder (akilli para takibi)
  H-D  TOP TRADER long orani ASIRI yuksekse -> donus (kalabalik)
  H-E  taker long/short hacim orani yuksekse -> devam eder

YONTEM: Her aday icin onceki 60 dk'nin OI degisimi (%) ve ortalamalari.
        TRAIN/TEST 70/30 kronolojik. net_pct (sabit model) + trailing dogrulama.
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
WIN_MIN = 60


def fetch(limit, seed):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""
            SELECT v.symbol, v.created_at, v.price, coalesce(v.atr_pct,0), v.net_pct,
                   m.perp_symbol
              FROM velocity_candidates v
              JOIN futures_symbol_map sm ON sm.try_symbol = v.symbol
              JOIN LATERAL (
                    SELECT DISTINCT hm.perp_symbol FROM hist_futures_metrics hm
                     WHERE hm.perp_symbol = sm.perp_symbol LIMIT 1
                   ) m ON TRUE
             WHERE v.net_pct IS NOT NULL AND v.price > 0 AND v.created_at > 0
             ORDER BY random()
             LIMIT %s""", (limit,))
        base = cur.fetchall()

        # KRITIK: ornekleme random, ama TRAIN/TEST KRONOLOJIK olmali.
        base.sort(key=lambda r: r[1])
        out = []
        for r in base:
            sym, t0, px, atr, net, perp = r
            cur.execute("""
                SELECT min(sum_open_interest_value), max(sum_open_interest_value),
                       avg(count_toptrader_long_short_ratio),
                       avg(sum_toptrader_long_short_ratio),
                       avg(count_long_short_ratio),
                       avg(sum_taker_long_short_vol_ratio),
                       count(*)
                  FROM hist_futures_metrics
                 WHERE perp_symbol = %s
                   AND ts_ms >= (%s - %s) * 1000 AND ts_ms < %s * 1000""",
                        (perp, t0, WIN_MIN * 60, t0))
            row = cur.fetchone()
            if row and row[6] and row[6] >= 6 and row[0] and row[1]:
                out.append((sym, t0, px, atr, net, perp) + row[:6])
        return out


def feats(r):
    oi_lo, oi_hi, top_cnt, top_sum, gen_ls, taker = r[6:12]
    oi_chg = (oi_hi / oi_lo - 1) * 100 if oi_lo and oi_hi else None
    return {
        "oi_chg_pct": oi_chg,
        "top_trader_ls": float(top_sum) if top_sum else None,
        "top_trader_ls_cnt": float(top_cnt) if top_cnt else None,
        "global_ls": float(gen_ls) if gen_ls else None,
        "taker_ls_vol": float(taker) if taker else None,
    }


def analyse(rows, key, higher_is_better=True):
    vals = [(f[key], float(r[4])) for r in rows if (f := feats(r))[key] is not None]
    if len(vals) < 300:
        return None
    split = int(len(vals) * 0.70)
    train = sorted(v for v, _ in vals[:split])
    edges = [train[int(len(train) * p)] for p in (0.2, 0.4, 0.6, 0.8)]

    def b(x):
        for i, e in enumerate(edges):
            if x <= e:
                return i
        return 4

    res = {}
    for label, sub in (("TRAIN", vals[:split]), ("TEST", vals[split:])):
        g = {}
        for v, net in sub:
            g.setdefault(b(v), []).append(net)
        res[label] = {k: (len(v), st.mean(v)) for k, v in g.items() if len(v) >= 25}
    return res, edges


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
    ap.add_argument("--limit", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--replay-n", type=int, default=400, dest="replay_n")
    a = ap.parse_args()

    rows = fetch(a.limit, a.seed)
    print(f"futures metrigi eslesen aday: {len(rows)} (pencere {WIN_MIN} dk)\n")
    if len(rows) < 300:
        print("orneklem yetersiz")
        return

    keys = [("oi_chg_pct", "OI degisimi % (yeni para girisi)"),
            ("top_trader_ls", "UST TRADER long/short (pozisyon)"),
            ("global_ls", "genel long/short (hesap)"),
            ("taker_ls_vol", "taker alim/satim hacim orani")]
    for key, desc in keys:
        r = analyse(rows, key)
        if not r:
            print(f"--- {desc}: orneklem kucuk ---\n")
            continue
        res, edges = r
        print(f"--- {desc} (esikler {[round(e,3) for e in edges]}) ---")
        for label in ("TRAIN", "TEST"):
            g = res[label]
            if not g:
                continue
            line = "  ".join(f"Q{k+1}={v[1]:+.3f}%(n{v[0]})" for k, v in sorted(g.items()))
            print(f"  {label}: {line}")
            if 0 in g and 4 in g:
                d = g[4][1] - g[0][1]
                print(f"    Q5-Q1 = {d:+.3f}%  {'AYRISTIRIYOR' if abs(d) > 0.20 else 'zayif'}")
        print()

    # Trailing dogrulama: OI degisimi en umut verici
    print(f"--- trailing dogrulama: OI degisimi (n={a.replay_n}) ---")
    vals = [(f["oi_chg_pct"], r) for r in rows[: a.replay_n]
            if (f := feats(r))["oi_chg_pct"] is not None]
    if len(vals) >= 150:
        tv = sorted(v for v, _ in vals)
        edges = [tv[int(len(tv) * p)] for p in (0.2, 0.4, 0.6, 0.8)]
        buckets = {i: [] for i in range(5)}
        with psycopg.connect(DB) as conn, conn.cursor() as cur:
            for v, r in vals:
                i = next((k for k, e in enumerate(edges) if v <= e), 4)
                net = replay(cur, r[0], r[1], r[2], 1.0, 2.0, 240)
                if net is not None:
                    buckets[i].append(net)
        for i in range(5):
            b = buckets[i]
            if len(b) < 15:
                print(f"  Q{i+1}: kucuk ({len(b)})")
                continue
            print(f"  Q{i+1}: n={len(b):>4} ort={st.mean(b):+.3f}% med={st.median(b):+.3f}% "
                  f"kaz={100*sum(1 for x in b if x>0)/len(b):.1f}%")
        if buckets[0] and buckets[4]:
            print(f"  Q5-Q1 (trailing) = {st.mean(buckets[4])-st.mean(buckets[0]):+.3f}%")


if __name__ == "__main__":
    main()
