"""1d MOMENTUM TİTİZ DOĞRULAMA (2026-10-13).

İLK POZİTİF sinyal: S1_mom12 (12-günlük momentum) 1d ufkunda hold=3 → EV +1.75%,
hold=6 → +2.83%. Ancak 12 turdur ilk kez pozitif çıktı → SAHTE olabilir. Bu script
acımasız doğrulama yapar (7 turun standardı):
  1. Walk-forward 3-fold (kronolojik) — kararlı mı?
  2. Gün-gün pozitiflik
  3. Sembol yoğunlaşması (tek coin sürüklüyor mu?) — leave-one-symbol-out
  4. Hem long hem short bacak ayrı ayrı
  5. Permütasyon testi (işaret karıştır → edge tesadüf mü?)
  6. Maliyet duyarlılığı (0 / 0.10 / 0.35)
  7. BTC rejim bağımlılığı (boğa döneminde mi çalışıyor?)

KULLANIM:
    python backend/scripts/verify_1d_momentum.py --hold 6
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
        "SELECT symbol FROM klines WHERE interval=? GROUP BY symbol HAVING COUNT(*)>=20", (tf,))]
    rows = conn.execute(
        f"SELECT symbol, open_time, high, low, close FROM klines WHERE interval=? "
        f"AND symbol IN ({','.join('?' * len(syms))}) ORDER BY symbol, open_time",
        (tf, *syms)).fetchall()
    conn.close()
    d: dict = {}
    for s, ot, h, l, c in rows:
        if c and c > 0:
            d.setdefault(str(s).upper(), []).append({"t": int(ot), "h": float(h), "l": float(l), "c": float(c)})
    return d


def signals(bars, hold, N=12):
    c = [b["c"] for b in bars]; n = len(c)
    out = []
    for i in range(N, n - hold):
        g = (c[i] / c[i - N] - 1) * 100
        if g > 0.5:
            out.append((bars[i]["t"], +1, (c[i + hold] / c[i] - 1) * 100, bars[i].get("_sym")))
        elif g < -0.5:
            out.append((bars[i]["t"], -1, (c[i + hold] / c[i] - 1) * 100, bars[i].get("_sym")))
    return out


def metrics(rows, cost):
    if not rows:
        return {"n": 0}
    nets = [d * g - cost for _, d, g, _ in rows]
    w = [x for x in nets if x > 0]
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "win": round(100 * len(w) / len(nets), 1),
            "total": round(sum(nets), 1)}


def paired_t(a, b):
    a = [x for x in a if x is not None]; b = [x for x in b if x is not None]
    if len(a) < 15 or len(b) < 15:
        return 0.0
    va = statistics.pvariance(a) / len(a); vb = statistics.pvariance(b) / len(b)
    se = (va + vb) ** 0.5
    return round((statistics.mean(a) - statistics.mean(b)) / se, 2) if se else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=6)
    ap.add_argument("--cost", type=float, default=0.35)
    args = ap.parse_args()
    data = _load("1d")
    for sym, bars in data.items():
        for b in bars:
            b["_sym"] = sym
    # Sinyalleri topla (sembol etiketli)
    allsig = []
    for sym, bars in data.items():
        allsig.extend(signals(bars, args.hold))
    allsig.sort(key=lambda x: x[0])
    print(f"=== 1d MOMENTUM DOĞRULAMA (hold={args.hold}, cost={args.cost}) ===")
    print(f"  toplam sinyal: {len(allsig)} | sembol: {len(data)}")
    m = metrics(allsig, args.cost)
    print(f"  TÜM: {m}")

    # 1) 3-fold
    print("\n  1) 3-FOLD:")
    for k in range(3):
        seg = allsig[int(len(allsig) * k / 3):int(len(allsig) * (k + 1) / 3)]
        print(f"     fold{k+1}: {metrics(seg, args.cost)}")

    # 2) gün-gün
    byday = {}
    for ts, d, g, _ in allsig:
        byday.setdefault(ts // 86400000, []).append(d * g - args.cost)
    pos = sum(1 for v in byday.values() if statistics.mean(v) > 0)
    print(f"\n  2) GÜN-GÜN pozitif: {pos}/{len(byday)}")

    # 3) sembol yoğunlaşması + leave-one-out
    from collections import Counter
    cc = Counter(s for _, _, _, s in allsig)
    tot = sum(cc.values())
    print(f"\n  3) SEMBOL: {len(cc)} | en büyük pay %{round(100*cc.most_common(1)[0][1]/tot,1)}")
    for drop in ([cc.most_common(1)[0][0]] + [s for s, _ in cc.most_common(3)]):
        sub = [(ts, d, g, s) for ts, d, g, s in allsig if s not in (drop if isinstance(drop, list) else [drop])]
        print(f"     çıkar {drop}: {metrics(sub, args.cost)['ev']}")
    top3 = [s for s, _ in cc.most_common(3)]
    sub3 = [r for r in allsig if r[3] not in top3]
    print(f"     ilk-3 sembol hariç: {metrics(sub3, args.cost)}")

    # 4) long/short bacak
    longs = [r for r in allsig if r[1] > 0]; shorts = [r for r in allsig if r[1] < 0]
    print(f"\n  4) LONG: {metrics(longs, args.cost)} | SHORT: {metrics(shorts, args.cost)}")

    # 5) permütasyon: yön işaretlerini karıştır
    random.seed(1)
    obs = metrics(allsig, args.cost)["ev"]
    sims = []
    dirs = [d for _, d, _, _ in allsig]; gs = [g for _, _, g, _ in allsig]
    for _ in range(300):
        random.shuffle(dirs)
        nets = [dirs[i] * gs[i] - args.cost for i in range(len(gs))]
        sims.append(statistics.mean(nets))
    pval = sum(1 for x in sims if x >= obs) / len(sims)
    print(f"\n  5) PERMÜTASYON: gözlenen {obs} | p(değer>=gözlem) = {round(pval,3)}")

    # 6) maliyet duyarlılığı
    print("\n  6) MALİYET: 0 ->", metrics(allsig, 0)["ev"],
          "| 0.10 ->", metrics(allsig, 0.10)["ev"],
          "| 0.35 ->", metrics(allsig, 0.35)["ev"])

    # 7) BTC rejim: BTC 1d EMA50 üstü/altı günlerde sinyal EV
    btc = data.get("BTCTRY") or []
    if btc:
        cs = [b["c"] for b in btc]
        k = 2 / 51; e = sum(cs[:50]) / 50; ema = {}
        for i in range(50, len(cs)):
            e = cs[i] * k + e * (1 - k); ema[i] = e
        ts_list = [b["t"] for b in btc]
        bull = set(); bear = set()
        for i in range(50, len(cs)):
            (bull if cs[i] > ema[i] else bear).add(ts_list[i] // 86400000)
        bnets = [(d * g - args.cost) for ts, d, g, _ in allsig if (ts // 86400000) in bull]
        rnets = [(d * g - args.cost) for ts, d, g, _ in allsig if (ts // 86400000) in bear]
        print(f"\n  7) BTC REJİM: boğa günleri EV {round(statistics.mean(bnets),3) if bnets else None} (n{len(bnets)})"
              f" | ayı {round(statistics.mean(rnets),3) if rnets else None} (n{len(rnets)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
