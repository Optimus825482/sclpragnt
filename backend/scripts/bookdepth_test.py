"""H6: EMIR DEFTERI DERINLIK DENGESIZLIGI (order book imbalance) yukselisi ongoruyor mu?

VERI: hist_futures_bookdepth — 7.332.621 satir, 290 perp sembol, 5 dk aralik,
      2026-07-19 -> 2026-10-16. Kolonlar bid_d1..bid_d5 / ask_d1..ask_d5 =
      her seviyeye kadar KUMULATIF derinlik (notional).

TEORI (literatur): bid/ask dengesizligi kisa vadeli yon tahmininde en guclu
mikro-yapi sinyallerinden biridir (Cont/Kukanov/Stoikov; cartea-jaimungal).
Alis duvari satis duvarindan kalinsa fiyat yukari baskilanir.

ONCEKI BULGULAR (bu proje): tum FIYAT turevi sinyaller olu; ATR (genlik) ve OI
(para girisi) calisiyor. Order flow (historical_trade_flow) AYRISTIRMADI ve
asiri ucu TERS calisti. Bu test emir defterini (niyet) olcuyor — akistan (gerceklesen)
farkli bir bilgi.

HIPOTEZ: onekli 15 dk pencerede ortalama bid/ask derinlik dengesizligi yuksekse
          (alis baskisi) yukselis devam eder.

YONTEM: TRAIN/TEST 70/30 KRONOLOJIK (random ornekleme + created_at sirasi;
tek-gun tuzagina dusmemek icin). Sabit net_pct + trailing dogrulama.
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
WIN_MIN = 15
LEVELS = (1, 5)


def fetch(limit, seed):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""
            SELECT v.symbol, v.created_at, v.price, coalesce(v.atr_pct,0), v.net_pct,
                   sm.perp_symbol
              FROM velocity_candidates v
              JOIN futures_symbol_map sm ON sm.try_symbol = v.symbol
             WHERE v.net_pct IS NOT NULL AND v.price > 0 AND v.created_at > 0
             ORDER BY random() LIMIT %s""", (limit,))
        base = cur.fetchall()

        out = []
        for r in base:
            sym, t0, px, atr, net, perp = r
            cur.execute("""
                SELECT avg(bid_d1), avg(ask_d1), avg(bid_d5), avg(ask_d5), count(*)
                  FROM hist_futures_bookdepth
                 WHERE perp_symbol = %s
                   AND ts_ms >= (%s - %s) * 1000 AND ts_ms < %s * 1000""",
                        (perp, t0, WIN_MIN * 60, t0))
            row = cur.fetchone()
            if row and row[4] and row[4] >= 2:
                out.append((sym, t0, px, atr, net) + row[:4])
        # KRONOLOJIK sirala (TRAIN/TEST gecerli olsun)
        out.sort(key=lambda r: r[1])
        return out


def feats(r):
    bid1, ask1, bid5, ask5 = (float(x or 0) for x in r[5:9])
    def imb(b, a):
        t = b + a
        return (b - a) / t if t > 0 else None
    return {
        "imb_d1": imb(bid1, ask1),
        "imb_d5": imb(bid5, ask5),
    }


def quintile(rows, key):
    vals = [(f[key], float(r[4])) for r in rows
            if (f := feats(r))[key] is not None]
    if len(vals) < 400:
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
        res[label] = {k: (len(v), st.mean(v)) for k, v in g.items() if len(v) >= 30}
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
    ap.add_argument("--limit", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--sl", type=float, default=2.0)
    ap.add_argument("--max-min", type=int, default=240, dest="max_min")
    ap.add_argument("--replay-n", type=int, default=400, dest="replay_n")
    a = ap.parse_args()

    rows = fetch(a.limit, a.seed)
    print(f"emir defteri eslesen aday: {len(rows)} (pencere {WIN_MIN} dk)\n")
    if len(rows) < 400:
        print("orneklem yetersiz")
        return

    for key, desc in (("imb_d1", "derinlik dengesizligi d1 (en iyi fiyat)"),
                      ("imb_d5", "derinlik dengesizligi d5 (5 seviye)")):
        r = quintile(rows, key)
        if not r:
            print(f"--- {desc}: orneklem kucuk ---\n")
            continue
        res, edges = r
        print(f"--- {desc} (esikler {[round(e,4) for e in edges]}) ---")
        for label in ("TRAIN", "TEST"):
            g = res[label]
            if not g:
                continue
            line = "  ".join(f"Q{k+1}={v[1]:+.3f}%(n{v[0]})"
                             for k, v in sorted(g.items()))
            print(f"  {label}: {line}")
            if 0 in g and 4 in g:
                d = g[4][1] - g[0][1]
                print(f"    Q5-Q1 = {d:+.3f}%  "
                      f"{'AYRISTIRIYOR' if abs(d) > 0.20 else 'zayif'}")
        print()

    # Trailing dogrulama (d5 dengesizligi)
    print(f"--- trailing dogrulama: imb_d5 (n={a.replay_n}, gap {a.gap}%, "
          f"SL {a.sl}%, {a.max_min}dk) ---")
    vals = [(f["imb_d5"], r) for r in rows[: a.replay_n]
            if (f := feats(r))["imb_d5"] is not None]
    if len(vals) >= 150:
        tv = sorted(v for v, _ in vals)
        edges = [tv[int(len(tv) * p)] for p in (0.2, 0.4, 0.6, 0.8)]
        buckets = {i: [] for i in range(5)}
        with psycopg.connect(DB) as conn, conn.cursor() as cur:
            for v, r in vals:
                i = next((k for k, e in enumerate(edges) if v <= e), 4)
                net = replay(cur, r[0], r[1], r[2], a.gap, a.sl, a.max_min)
                if net is not None:
                    buckets[i].append(net)
        for i in range(5):
            b = buckets[i]
            if len(b) < 15:
                print(f"  Q{i+1}: kucuk ({len(b)})")
                continue
            print(f"  Q{i+1}: n={len(b):>4} ort={st.mean(b):+.3f}% "
                  f"med={st.median(b):+.3f}% "
                  f"kaz={100*sum(1 for x in b if x>0)/len(b):.1f}%")
        if buckets[0] and buckets[4]:
            print(f"  Q5-Q1 (trailing) = "
                  f"{st.mean(buckets[4])-st.mean(buckets[0]):+.3f}%")


if __name__ == "__main__":
    main()
