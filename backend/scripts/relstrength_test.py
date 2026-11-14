"""H1 testi: GÖRELİ GÜÇ (cross-sectional rank) yükselişi öngörüyor mu?

SORU: Aynı anda taranan adaylar arasında, geçmiş fiyat hareketi en güçlü olan
      gerçekten diğerlerinden daha mı iyi performans gösteriyor?

NEDEN FARKLI: Mevcut sistem `velocity_score` kullanıyor (r=0.0002 ile ÖLÜ).
Bu test skoru DEĞİL, GERÇEK fiyat getirisini sıralama ölçütü yapar:
  ret15 = aday anından 15 dk önceki getiri (%)
  ret30 = 30 dk önceki getiri

YÖNTEM (sızıntısız):
  • Her 30 dk kovada adayları ret15'e göre sırala
  • Üst çeyrek vs alt çeyrek GERÇEK net_pct ortalamalarını karşılaştır
  • Doğru yön oranı: kaç kovada üst çeyrek > alt çeyrek
  • TRAIN/TEST: kovaların ilk %70 / son %30

ÖLÇÜT (başarı): fark > +0.20% VE doğru yön > %55
"""
from __future__ import annotations

import argparse
import statistics as st
from collections import defaultdict

import psycopg

DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"


def load(limit: int | None = None):
    sql = """
        SELECT symbol, created_at, price, coalesce(velocity_score,0),
               coalesce(atr_pct,0), net_pct
          FROM velocity_candidates
         WHERE net_pct IS NOT NULL AND created_at > 0 AND price > 0
         ORDER BY created_at
    """
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        if limit:
            cur.execute(sql + " LIMIT %s", (limit,))
        else:
            cur.execute(sql)
        return cur.fetchall()


def prior_return(cur, symbol: str, t0: float, minutes: int) -> float | None:
    """t0 anından `minutes` dk ÖNCEki fiyata göre getiri (%). Sızıntısız."""
    t_ms = int(float(t0) * 1000)
    cur.execute(
        """SELECT close FROM historical_candles
            WHERE symbol=%s AND timeframe='1m'
              AND open_time <= %s AND open_time >= %s
            ORDER BY open_time ASC""",
        (symbol, t_ms, t_ms - minutes * 60_000))
    rows = cur.fetchall()
    if len(rows) < 2:
        return None
    first, last = float(rows[0][0]), float(rows[-1][0])
    if first <= 0:
        return None
    return (last / first - 1) * 100


def evaluate(cands_by_bucket: dict, lookback: int, cur) -> dict:
    """Kovaları sırala, üst/alt çeyrek karşılaştır."""
    diffs, details = [], []
    cache: dict = {}
    for k, rows in sorted(cands_by_bucket.items()):
        scored = []
        for sym, t0, px, sc, atr, net in rows:
            key = (sym, int(float(t0)))
            if key not in cache:
                cache[key] = prior_return(cur, sym, t0, lookback)
            r = cache[key]
            if r is None:
                continue
            scored.append((r, float(net)))
        if len(scored) < 8:
            continue
        scored.sort(key=lambda x: x[0])
        q = max(1, len(scored) // 4)
        top = [n for _r, n in scored[-q:]]
        bot = [n for _r, n in scored[:q]]
        diffs.append(st.mean(top) - st.mean(bot))
        details.append((st.mean(top), st.mean(bot), len(scored)))
    if not details:
        return {}
    return {
        "n_bucket": len(details),
        "top": st.mean(d[0] for d in details),
        "bot": st.mean(d[1] for d in details),
        "diff": st.mean(diffs),
        "signed": 100 * sum(1 for d in diffs if d > 0) / len(diffs),
        "avg_size": st.mean(d[2] for d in details),
    }


def show(name: str, r: dict, verdict: bool = True) -> None:
    if not r:
        print(f"  {name:>22} VERI YOK")
        return
    ok = r["diff"] > 0.20 and r["signed"] > 55.0
    mark = "  GECTI" if (verdict and ok) else ""
    print(f"  {name:>22} {r['n_bucket']:>5} {r['top']:>+8.3f}% {r['bot']:>+8.3f}% "
          f"{r['diff']:>+8.3f}% {r['signed']:>6.1f}%{mark}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--bucket-min", type=int, default=30, dest="bucket_min")
    ap.add_argument("--lookbacks", type=str, default="15,30,60,120")
    a = ap.parse_args()

    rows = load(a.limit)
    print(f"aday: {len(rows)} | kova: {a.bucket_min}dk | fee yok (net_pct hazir)\n")

    buckets = defaultdict(list)
    for r in rows:
        buckets[int(float(r[1]) // (a.bucket_min * 60))].append(r)
    keys = sorted(buckets)
    split = int(len(keys) * 0.70)

    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for label, sub in (("TRAIN(%d)", keys[:split]), ("TEST(%d)", keys[split:])):
            print(label % len(sub))
            print(f"  {'sinyal':>22} {'kova':>5} {'ust':>9} {'alt':>9} {'FARK':>9} {'yön':>7}")
            for lb in (int(x) for x in a.lookbacks.split(",")):
                sel = {k: buckets[k] for k in sub}
                r = evaluate(sel, lb, cur)
                show(f"ret{lb} (göreli güç)", r)
            print()

        print("KARŞILAŞTIRMA — mevcut skor (aynı yöntemle):")
        print(f"  {'sinyal':>22} {'kova':>5} {'ust':>9} {'alt':>9} {'FARK':>9} {'yön':>7}")

        def by_score(cands_by_bucket):
            diffs, details = [], []
            for _k, rs in sorted(cands_by_bucket.items()):
                if len(rs) < 8:
                    continue
                s = sorted(((float(x[3]), float(x[5])) for x in rs), key=lambda t: t[0])
                q = max(1, len(s) // 4)
                top = [n for _v, n in s[-q:]]
                bot = [n for _v, n in s[:q]]
                diffs.append(st.mean(top) - st.mean(bot))
                details.append((st.mean(top), st.mean(bot), len(s)))
            return {"n_bucket": len(details), "top": st.mean(d[0] for d in details),
                    "bot": st.mean(d[1] for d in details), "diff": st.mean(diffs),
                    "signed": 100 * sum(1 for d in diffs if d > 0) / len(diffs)} if details else {}

        show("velocity_score", by_score({k: buckets[k] for k in keys[:split]}), False)
        show("velocity_score", by_score({k: buckets[k] for k in keys[split:]}), False)

    print("\nBAŞARI ÖLÇÜTÜ: FARK > +0.20% VE yön > %55")


if __name__ == "__main__":
    main()
