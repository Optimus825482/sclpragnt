"""H5: TAKER BUY VOLUME / ORDER FLOW yukselisi ongoruyor mu?

ONCEKI BULGU (docs/YUKSELIS_ARASTIRMASI §15) "veri yok" idi — YANLISTI.
`historical_trade_flow` tablosu dakika bazinda gercek taker akisini sakliyor:
  13.9M satir, 310 sembol, 2026-07-19 -> 2026-10-17
  buy_quote / sell_quote / big_buy / big_sell / whale_* / max_trade_quote

BOYLELIKLE literaturun en guclu destekledigi boyut ILK KEZ olculebilir.

HIPOTEZLER (aday anindan ONCEKI 15 dk pencerede):
  H5a  taker buy orani (agresif alim payi) yuksek -> yukselis devam eder
  H5b  buy/sell orani (notional) yuksek -> devam eder
  H5c  BUYUK alim baskinligi (big_buy - big_sell) -> devam eder
  H5d  islem sayisi (n_trades) yogunlugu -> devam eder

YONTEM: Aday anindan onceki 15 dakikalik akis ozeti -> dilimlere bol ->
        TRAIN/TEST (70/30 kronolojik) -> net_pct karsilastir.
        Ayrica gercek 1m mum + trailing ile dogrulama (ATR'de cikis modeli
        farki cikmisti — burada da kontrol edilir).
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
WINDOW_MIN = 15


def fetch(limit, seed):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""
            SELECT v.symbol, v.created_at, v.price, coalesce(v.atr_pct,0), v.net_pct,
                   f.buy_q, f.sell_q, f.big_buy, f.big_sell, f.n_tr
              FROM velocity_candidates v
              JOIN LATERAL (
                    SELECT sum(buy_quote) buy_q, sum(sell_quote) sell_q,
                           sum(big_buy_quote) big_buy, sum(big_sell_quote) big_sell,
                           sum(n_trades) n_tr
                      FROM historical_trade_flow h
                     WHERE h.symbol = v.symbol
                       AND h.minute_open_ms >= (v.created_at - %s) * 1000
                       AND h.minute_open_ms <  v.created_at * 1000
                   ) f ON (f.buy_q + f.sell_q) > 0
             WHERE v.net_pct IS NOT NULL AND v.price > 0 AND v.created_at > 0
             ORDER BY v.created_at, random()
             LIMIT %s""", (WINDOW_MIN * 60, limit))
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
        lvl = max(best * (1 - gap / 100), entry * (1 - sl_pct / 100))
        if cl <= lvl:
            exit_px = lvl
            break
    if exit_px is None:
        exit_px = bars[-1][2]
    return (exit_px / entry - 1) * 100 - FEE


def metrics(r):
    buy_q, sell_q, big_buy, big_sell, n_tr = (float(x or 0) for x in r[5:10])
    tot = buy_q + sell_q
    return {
        "taker_buy_pct": 100 * buy_q / tot if tot else None,
        "buy_sell_ratio": buy_q / sell_q if sell_q else None,
        "big_net_share": (big_buy - big_sell) / tot if tot else None,
        "n_trades": n_tr,
    }


def quintile_report(rows, key, fixed_edges=None):
    vals = [(m[key], float(r[4]), r) for r in rows if (m := metrics(r))[key] is not None]
    if len(vals) < 200:
        return None
    split = int(len(vals) * 0.70)
    train = sorted(v for v, _, _ in vals[:split])
    edges = fixed_edges or [train[int(len(train) * p)] for p in (0.2, 0.4, 0.6, 0.8)]

    def b(x):
        for i, e in enumerate(edges):
            if x <= e:
                return i
        return 4

    out = {}
    for label, sub in (("TRAIN", vals[:split]), ("TEST", vals[split:])):
        g = {}
        for v, net, _ in sub:
            g.setdefault(b(v), []).append(net)
        out[label] = {k: (len(v), st.mean(v)) for k, v in g.items() if len(v) >= 20}
    return out, edges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--replay-n", type=int, default=600, dest="replay_n")
    a = ap.parse_args()

    rows = fetch(a.limit, a.seed)
    print(f"order flow eslesen aday: {len(rows)} (pencere {WINDOW_MIN} dk)\n")
    if not rows:
        print("ESLESME YOK")
        return

    for key, desc in (("taker_buy_pct", "taker buy orani (agresif alim %)"),
                      ("buy_sell_ratio", "buy/sell notional orani"),
                      ("big_net_share", "buyuk alim net payi"),
                      ("n_trades", "islem sayisi (yogunluk)")):
        res = quintile_report(rows, key)
        if not res:
            print(f"--- {desc}: orneklem kucuk ---\n")
            continue
        out, edges = res
        print(f"--- {desc} ---")
        for label in ("TRAIN", "TEST"):
            g = out[label]
            if not g:
                continue
            line = "  ".join(f"Q{k+1}={v[1]:+.3f}%(n{v[0]})" for k, v in sorted(g.items()))
            print(f"  {label}: {line}")
            if 0 in g and 4 in g:
                d = g[4][1] - g[0][1]
                print(f"    Q5-Q1 = {d:+.3f}%  {'AYRISTIRIYOR' if d > 0.20 else 'zayif/ters'}")
        print()

    # Trailing ile dogrulama (cikis modeli bagimliligi kontrolu)
    print(f"--- trailing dogrulama (n={a.replay_n}, gap 1.0, SL 2.0, 240dk) ---")
    sample = rows[: a.replay_n]
    buckets = {i: [] for i in range(5)}
    vals = [(m["taker_buy_pct"], r) for r in sample if (m := metrics(r))["taker_buy_pct"] is not None]
    if len(vals) >= 100:
        tv = sorted(v for v, _ in vals)
        edges = [tv[int(len(tv) * p)] for p in (0.2, 0.4, 0.6, 0.8)]
        with psycopg.connect(DB) as conn, conn.cursor() as cur:
            for v, r in vals:
                idx = next((i for i, e in enumerate(edges) if v <= e), 4)
                net = replay(cur, r[0], r[1], r[2], 1.0, 2.0, 240)
                if net is not None:
                    buckets[idx].append(net)
        for i in range(5):
            b = buckets[i]
            if len(b) < 15:
                print(f"  Q{i+1}: orneklem kucuk ({len(b)})")
                continue
            print(f"  Q{i+1}: n={len(b):>4} ort={st.mean(b):+.3f}% med={st.median(b):+.3f}% "
                  f"kaz={100*sum(1 for x in b if x>0)/len(b):.1f}%")
        if buckets[0] and buckets[4]:
            d = st.mean(buckets[4]) - st.mean(buckets[0])
            print(f"  Q5-Q1 (trailing) = {d:+.3f}%  "
                  f"{'AYRISTIRIYOR' if d > 0.20 else 'ayristirmiyor'}")


if __name__ == "__main__":
    main()
