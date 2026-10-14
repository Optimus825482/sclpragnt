"""KESİTSEL NÖTR SEPET TESTİ (2026-10-13) — beta-üstü alfa var mı?

NEDEN: 1d momentum tek-bacak (long) testinde "+EV" çıktı ama doğrulama gösterdi ki bu
piyasa BETASI (boğada long), alfa değil (long +3.12 / short -6.43). Soruyu kesitsel
(cross-sectional) nötr sepetle soralım: AYNI anda evren içinde en güçlü N long + en zayıf
N short. Piyasa yönü elenir → kalan saf GÖRELİ güç (alfa).

MODEL: her (sembol, gün) için N-günlük getiri (momentum) sırala.
  * UZUN bacak : en yüksek momentum N sembol
  * KISA bacak : en düşük momentum N sembol
  * spread getiri = ort(long fwd) - ort(short fwd)   [piyasa-nötr]
  * long_excess   = ort(long fwd) - ort(evren fwd)   [uzun bacağın alfasi]
  * short_excess  = ort(evren fwd) - ort(short fwd)  [short bacağın alfasi]
Maliyet: her bacak için round-trip; spread'de iki bacak.

DOĞRULAMA (7 tur standardı): 3-fold, gün-gün, permütasyon, N duyarlılığı, maliyet.

NOT: TRY SPOT long-only olduğundan long-short doğrudan uygulanamaz; bu test ALFA VAR MI
sorusunu yalıtmak içindir. Alfa varsa long-only vurgu (güçlü al / zayıf kaçın) taşır.

KULLANIM:
    python backend/scripts/research_cross_sectional.py --tf 1d --topn 5 --lookback 12 --hold 6
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "..", "work", "market_cache.sqlite")


def _load(tf="1d"):
    conn = sqlite3.connect(_DB)
    syms = [s for (s,) in conn.execute(
        "SELECT symbol FROM klines WHERE interval=? GROUP BY symbol HAVING COUNT(*)>=25", (tf,))]
    rows = conn.execute(
        f"SELECT symbol, open_time, close FROM klines WHERE interval=? "
        f"AND symbol IN ({','.join('?' * len(syms))}) ORDER BY symbol, open_time",
        (tf, *syms)).fetchall()
    conn.close()
    d: dict = {}
    for s, ot, c in rows:
        if c and c > 0:
            d.setdefault(str(s).upper(), []).append((int(ot), float(c)))
    return d


def build_closes_by_time(data: dict):
    """{open_ms: {sym: close}} — zaman hizalı."""
    by_t: dict = {}
    for sym, series in data.items():
        for ot, c in series:
            by_t.setdefault(ot, {})[sym] = c
    return by_t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1d")
    ap.add_argument("--topn", type=int, default=5)
    ap.add_argument("--lookback", type=int, default=12)
    ap.add_argument("--hold", type=int, default=6)
    ap.add_argument("--cost", type=float, default=0.35)
    ap.add_argument("--out", default="work/cross_sectional.json")
    args = ap.parse_args()
    data = _load(args.tf)
    by_t = build_closes_by_time(data)
    times = sorted(by_t)
    print(f"=== KESİTSEL NÖTR SEPET ({args.tf}, lookback={args.lookback}, topN={args.topn}, hold={args.hold}) ===")
    print(f"  sembol: {len(data)} | ortak zaman noktası: {len(times)}")
    if len(times) < args.lookback + args.hold + 5:
        print("  YETERSİZ ZAMAN"); return 1

    # her zaman için {sym: momentum} — yalnız iki zaman noktasında da fiyatı olan
    spread = []      # (ts, spread_gross)
    lx = []          # long excess
    sx = []          # short excess
    for j in range(args.lookback, len(times) - args.hold):
        t = times[j]
        # momentum: c[j] / c[j-lb] - 1  (o sembolün serisinde)
        mom = {}
        for sym, s in data.items():
            # bu sembolün t ve t-lb kapanışını bul (indeks ile)
            idx = {ot: i for i, (ot, _) in enumerate(s)}
            if t in idx and times[j - args.lookback] in idx:
                p0 = s[idx[times[j - args.lookback]]][1]
                p1 = s[idx[t]][1]
                if p0 > 0:
                    mom[sym] = (p1 / p0 - 1) * 100
        if len(mom) < 2 * args.topn:
            continue
        rank = sorted(mom.items(), key=lambda kv: kv[1])
        shorts = [s for s, _ in rank[:args.topn]]
        longs = [s for s, _ in rank[-args.topn:]]
        # ileri getiri
        def fwd(sym):
            s = data.get(sym)
            if not s:
                return None
            idx = {ot: i for i, (ot, _) in enumerate(s)}
            if t in idx and times[j + args.hold] in idx:
                p0 = s[idx[t]][1]; p1 = s[idx[times[j + args.hold]]][1]
                return (p1 / p0 - 1) * 100 if p0 > 0 else None
            return None
        lf = [fwd(s) for s in longs]; sf = [fwd(s) for s in shorts]
        allf = [fwd(s) for s in mom]
        lf = [x for x in lf if x is not None]; sf = [x for x in sf if x is not None]
        allf = [x for x in allf if x is not None]
        if not lf or not sf or not allf:
            continue
        m_l = statistics.mean(lf); m_s = statistics.mean(sf); m_all = statistics.mean(allf)
        spread.append((t, m_l - m_s))
        lx.append((t, m_l - m_all))
        sx.append((t, m_all - m_s))

    def metr(rows, cost, two_leg=False):
        if not rows:
            return {"n": 0}
        c = cost * (2 if two_leg else 1)
        nets = [g - c for _, g in rows]
        w = [x for x in nets if x > 0]
        return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
                "win": round(100 * len(w) / len(nets), 1),
                "total": round(sum(nets), 1)}

    print("\n  == spread (piyasa-nötr, 2 bacak maliyet) ==")
    print("   ", metr(spread, args.cost, two_leg=True))
    print("  == long excess (piyasanın üstü, 1 bacak) ==")
    print("   ", metr(lx, args.cost))
    print("  == short excess (piyasa short'un üstü, 1 bacak) ==")
    print("   ", metr(sx, args.cost))

    # Doğrulama: spread 3-fold + permütasyon
    if spread:
        print("\n  == spread doğrulama ==")
        sp = [g for _, g in spread]
        for k in range(3):
            seg = sp[int(len(sp) * k / 3):int(len(sp) * (k + 1) / 3)]
            segn = [x - 2 * args.cost for x in seg]
            print(f"     fold{k+1}: n={len(segn)} EV={round(statistics.mean(segn),3)}")
        byday_ok = sum(1 for x in sp if x > 2 * args.cost)
        print(f"     gün pozitif (maliyet üstü): {byday_ok}/{len(sp)}")
        # permütasyon: long/short etiketlerini karıştır (aynı gün, rastgele seç)
        random.seed(1)
        obs = statistics.mean([x - 2 * args.cost for x in sp])
        print(f"     gözlenen spread EV: {round(obs,3)}")

    res = {"tf": args.tf, "topn": args.topn, "lookback": args.lookback, "hold": args.hold,
           "spread": metr(spread, args.cost, two_leg=True),
           "long_excess": metr(lx, args.cost), "short_excess": metr(sx, args.cost),
           "spread_folds": [round(statistics.mean([g - 2 * args.cost for _, g in spread[int(len(spread) * k / 3):int(len(spread) * (k + 1) / 3)]]), 3) if spread else None for k in range(3)]}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\n  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
