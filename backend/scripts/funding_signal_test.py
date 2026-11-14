"""H3 testi: FUNDING RATE yukselisi ongoruyor mu? (ters sinyal hipotezi)

HIPOTEZ: Asiri POZITIF funding = kalabalik long = dusus riski.
         Asiri NEGATIF funding = kalabalik short = squeeze potansiyeli.
Sistemde funding SADECE "kotuyse engelle" filtresi olarak var; TERS SINYAL
olarak hic kullanilmiyor.

YONTEM: Her velocity adayi icin aday anindaki EN YAKIN funding degerini al.
        TRAIN/TEST ayrimiyla (70/30 kronolojik) news_pct'yi funding dilimine gore
        karsilastir.
NOT: net_pct = sabit TP/SL simulasyonu. Sonuclar cikis modeline bagimli olabilir
     (bkz. docs/YUKSELIS_ARASTIRMASI §10) — bu yuzden yon (isaret) yorumlanir,
     mutlak seviye degil.
"""
from __future__ import annotations

import argparse
import statistics as st

import psycopg

DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60000)
    ap.add_argument("--window-min", type=int, default=120, dest="window_min")
    a = ap.parse_args()

    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        print("funding eslestiriliyor (LATERAL join)...")
        cur.execute("""
            SELECT v.symbol, v.created_at, v.atr_pct, v.net_pct, f.rate
              FROM velocity_candidates v
              JOIN LATERAL (
                    SELECT rate FROM futures_funding ff
                     WHERE ff.symbol = v.symbol
                       AND ff.ts <= v.created_at * 1000
                       AND ff.ts >= (v.created_at - %s) * 1000
                     ORDER BY ff.ts DESC LIMIT 1
                   ) f ON TRUE
             WHERE v.net_pct IS NOT NULL AND v.created_at > 0
             ORDER BY v.created_at
             LIMIT %s""", (a.window_min * 60, a.limit))
        rows = cur.fetchall()

    print(f"eslesen aday: {len(rows)}\n")
    if not rows:
        print("KESISIM YOK — funding ile velocity ortusmuyor.")
        return

    split = int(len(rows) * 0.70)
    rate_of = lambda r: (float(r[4]) * 100)  # %'ye cevir
    all_rates = [rate_of(r) for r in rows]
    print(f"funding dagilimi (%): min={min(all_rates):+.4f} "
          f"med={st.median(all_rates):+.4f} max={max(all_rates):+.4f}\n")

    # 5 dilim (quintile) — TRAIN'e gore esikler
    train_rates = sorted(rate_of(r) for r in rows[:split])
    qs = [train_rates[int(len(train_rates) * p)] for p in (0.2, 0.4, 0.6, 0.8)]

    def bucket(x):
        for i, q in enumerate(qs):
            if x <= q:
                return i
        return 4

    for label, sub in (("TRAIN", rows[:split]), ("TEST", rows[split:])):
        print(f"{label} (n={len(sub)})")
        print(f"  {'funding dilimi':>22} {'n':>6} {'ort_net':>9} {'kazanan':>8}")
        groups = {}
        for r in sub:
            groups.setdefault(bucket(rate_of(r)), []).append(float(r[3]))
        for b in sorted(groups):
            v = groups[b]
            lo = "-inf" if b == 0 else f"{qs[b-1]:+.4f}"
            hi = "+inf" if b == 4 else f"{qs[b]:+.4f}"
            print(f"  [{lo:>8},{hi:>8}] {len(v):>6} {st.mean(v):>+8.3f}% "
                  f"{100*sum(1 for x in v if x>0)/len(v):>7.1f}%")
        if 0 in groups and 4 in groups:
            d = st.mean(groups[4]) - st.mean(groups[0])
            print(f"  en yuksek - en dusuk funding: {d:+.3f}% "
                  f"({'TERS sinyal calisiyor' if d < 0 else 'duz iliski'})")
        print()


if __name__ == "__main__":
    main()
