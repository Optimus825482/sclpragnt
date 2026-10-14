"""KOMBİNE LİSTE KADANS — KAÇIRMA ÖLÇÜMÜ (2026-10-12).

SORU (kullanıcı): Radar/yükseliş taraması 30 sn'de bir ama kombine WhatsApp listesi
~15 dk'da bir. 15 dk'lık ızgara arada yakalanan yükseliş adaylarını KAÇIRIYOR mu?

YÖNTEM: Gerçek radar adaylarını (velocity_candidates, passes=true) zaman damgalarıyla
al. Kombine listenin 15 dk'lık ızgarasını simüle et: her aday, o an açık olan "slot"
gönderimine girer; adayın slot'a KADAR geçen gecikmesi + o gecikmede fiyatın KAÇAN
hareketi ölçülür. Sonra "olay-güdümlü" (aday belirince hemen gönder) senaryoyla kıyasla.

Ölçütler:
  * gecikme (sn): aday anı → bir sonraki slot gönderimi
  * kaçan getiri (%): aday anındaki fiyata göre slot anındaki fiyat farkı (gecikmede
    alınamayan kısım) — pozitifse "yükselmiş, kaçmış"
  * slot başına kaç aday biriktiği

KULLANIM:
    python backend/scripts/measure_list_lag.py --days 5 --list-min 15
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "..", "work", "market_cache.sqlite")


def load_candidates(days: float) -> list[dict]:
    import psycopg
    since = time.time() - days * 86400.0
    out = []
    with psycopg.connect("postgresql://postgres:518518Erkan@localhost:5432/scalper",
                         connect_timeout=8) as conn:
        for ts, sym, px, tgt, score in conn.execute(
            "SELECT created_at, symbol, price, target_pct, velocity_score FROM velocity_candidates "
            "WHERE passes=true AND created_at>=%s AND price>0 ORDER BY created_at", (since,)):
            try:
                out.append({"ts": float(ts), "sym": str(sym).upper(),
                            "price": float(px), "target": float(tgt or 3.0),
                            "score": float(score or 0.0)})
            except (TypeError, ValueError):
                continue
    return out


def load_prices(syms: set[str]) -> dict:
    """{sym: [(open_time_s, close), ...]} zaman artan (5m)."""
    conn = sqlite3.connect(_DB)
    out: dict = {}
    for sym, ot, cl in conn.execute(
        "SELECT symbol, open_time, close FROM klines WHERE interval='5m' ORDER BY symbol, open_time"):
        s = str(sym).upper()
        if s in syms and cl and cl > 0:
            out.setdefault(s, []).append((float(ot) / 1000.0, float(cl)))
    conn.close()
    return out


def price_at(prices: list, t: float) -> float | None:
    """t anında (veya en yakın sonraki bar) kapanış."""
    import bisect
    ts = [p[0] for p in prices]
    i = bisect.bisect_left(ts, t)
    if i >= len(prices):
        return None
    return prices[i][1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=5.0)
    ap.add_argument("--list-min", type=float, default=15.0)
    args = ap.parse_args()
    print("=== KOMBİNE LİSTE KADANS — KAÇIRMA ÖLÇÜMÜ ===")
    cands = load_candidates(args.days)
    if not cands:
        print("aday yok"); return 1
    t0, t1 = cands[0]["ts"], cands[-1]["ts"]
    import datetime as dt
    print(f"  aday: {len(cands)} | pencere: {dt.datetime.utcfromtimestamp(t0)} -> {dt.datetime.utcfromtimestamp(t1)}")
    syms = {c["sym"] for c in cands}
    prices = load_prices(syms)
    print(f"  fiyat bulunan sembol: {len(prices)}/{len(syms)}")

    grid = args.list_min * 60.0
    # Slot gönderimleri: pencerenin başından itibaren grid adımları (offset=0).
    slot0 = math_floor(t0, grid)
    def next_slot(t): return slot0 + grid * ((int((t - slot0) // grid)) + 1)

    # Her adayı slot'a ata
    lag_secs = []
    missed = []          # slot'a kadar fiyat farkı (%)
    per_slot: dict = {}
    for c in cands:
        slot = next_slot(c["ts"])
        lag = slot - c["ts"]
        lag_secs.append(lag)
        p0 = c["price"]
        p1 = price_at(prices.get(c["sym"], []), slot)
        if p0 and p1:
            missed.append((p1 / p0 - 1) * 100)
        per_slot.setdefault(int(slot), 0)
        per_slot[int(slot)] += 1

    print(f"\n  == 15 dk IZGARA ({args.list_min} dk) ==")
    print(f"  aday→slot GECİKME: ort={statistics.mean(lag_secs)/60:.1f} dk  "
          f"med={statistics.median(lag_secs)/60:.1f} dk  maks={max(lag_secs)/60:.1f} dk")
    if missed:
        pos = [x for x in missed if x > 0]
        big = [x for x in missed if x >= 2.0]
        print(f"  gecikmede fiyat KAÇAN ortalama: {statistics.mean(missed):+.3f}%  "
              f"med={statistics.median(missed):+.3f}%")
        print(f"  yükselip kaçan aday: {len(pos)}/{len(missed)} (%{100*len(pos)/len(missed):.0f})")
        print(f"  ≥%2 KAÇAN aday: {len(big)} ({100*len(big)/len(missed):.1f}%)  "
              f"en büyük: {max(missed):+.2f}%")
    slots = sorted(per_slot)
    print(f"  gönderim slotu: {len(slots)} | slot başına aday: ort {len(cands)/max(1,len(slots)):.1f}")

    # OLAY-GÜDÜMLÜ senaryo: her SLOT'ta o slot penceresindeki adaylar anında gider
    # → gecikme ≈ 0. Farkı ölç: kaç aday ≥%2 hareket ederken bekledi.
    # Ayrıca: sonraki slotta kaç aday ZATEN hedefe ulaşmış (yani liste gecikince
    # "tavanına ulaşan" aday gönderiliyor → işe yaramaz bilgi).
    reached = 0; total_checked = 0
    for c in cands:
        slot = next_slot(c["ts"])
        p1 = price_at(prices.get(c["sym"], []), slot)
        if c["price"] and p1 and c["price"] > 0:
            total_checked += 1
            if (p1 / c["price"] - 1) * 100 >= c["target"]:
                reached += 1
    if total_checked:
        print(f"  slot'a gelindiğinde HEDEFİ ÇOKTAN GÖRMÜŞ aday: {reached}/{total_checked} "
              f"(%{100*reached/total_checked:.1f}) — liste geç kalınca 'artık geç' bilgi")

    print(f"\n  KARAR İÇİN: ortalama gecikme {statistics.mean(lag_secs)/60:.1f} dk; "
          f"≥%2 kaçan {100*len([x for x in missed if x>=2])/max(1,len(missed)):.0f}% aday.")
    return 0


def math_floor(t: float, g: float) -> float:
    return t - (t % g)


if __name__ == "__main__":
    raise SystemExit(main())
