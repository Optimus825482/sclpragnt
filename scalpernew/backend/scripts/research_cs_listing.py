"""KESİTSEL MOMENTUM — LİSTİNG-YAŞI TESTİ (2026-10-13).

SORU: script1'in +2.04 spread'i yeni-listing pump'ı mı? Her sembolün ilk N gününü
hariç tut (henüz listelenmiş taze coin'ler) → edge sürüyor mu, çöküyor mu?
Sabit evrende (32 sembol) zaten edge kalmadığına göre, kalan izin mekanizmasını netleştirir.

KULLANIM: python backend/scripts/research_cs_listing.py --tf 1d --top-syms 60
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research_cs_verify import _load_minimal, _top_symbols, _tstat, _block_tstat  # noqa: E402

_TAKER = 0.35


def _spreads_minhist(series, lookback, hold, topn, step, min_hist):
    """Kesitsel spread; her sembol için t anında en az min_hist bar geçmişi şart."""
    by_t: dict = {}
    for sym, s in series.items():
        for ot, c in s:
            by_t.setdefault(ot, {})[sym] = c
    times = sorted(by_t)
    idx = {sym: {ot: i for i, (ot, _) in enumerate(s)} for sym, s in series.items()}
    rows = []
    for j in range(lookback, len(times) - hold, step):
        t = times[j]; t0 = times[j - lookback]; t1 = times[j + hold]
        mom = {}
        for sym, s in series.items():
            im = idx[sym]
            if t in im and t0 in im and im[t] >= min_hist and s[im[t0]][1] > 0:
                mom[sym] = (s[im[t]][1] / s[im[t0]][1] - 1) * 100
        if len(mom) < 2 * topn:
            continue
        rank = sorted(mom.items(), key=lambda kv: kv[1])
        shorts = [x for x, _ in rank[:topn]]; longs = [x for x, _ in rank[-topn:]]

        def fwd(sym):
            s = series[sym]; im = idx[sym]
            if t in im and t1 in im and s[im[t]][1] > 0:
                return (s[im[t1]][1] / s[im[t]][1] - 1) * 100
            return None
        lf = [x for x in (fwd(s) for s in longs) if x is not None]
        sf = [x for x in (fwd(s) for s in shorts) if x is not None]
        af = [x for x in (fwd(s) for s in mom) if x is not None]
        if lf and sf and af:
            ml, ms = statistics.mean(lf), statistics.mean(sf)
            rows.append({"t": t, "spread": ml - ms, "univ": len(mom)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1d")
    ap.add_argument("--top-syms", type=int, default=60)
    ap.add_argument("--lookback", type=int, default=12)
    ap.add_argument("--hold", type=int, default=6)
    ap.add_argument("--topn", type=int, default=5)
    args = ap.parse_args()
    c2 = 2 * _TAKER
    syms = _top_symbols(args.top_syms)
    series = {}
    for s in syms:
        rows = _load_minimal(s, args.tf)
        if len(rows) >= args.lookback + args.hold + 10:
            series[s] = rows
    print(f"=== LİSTİNG-YAŞI TESTİ ({args.tf}, top{args.topn}) | evren {len(series)} ===")
    print("  min_hist = bir sembolün t anında gereken asgari bar sayısı (taze listing hariç)")
    for mh in (0, 15, 30, 60, 90):
        for step, tag in ((1, "örtüşen"), (args.hold, "bağımsız")):
            rows = _spreads_minhist(series, args.lookback, args.hold, args.topn, step, mh)
            net = [r["spread"] - c2 for r in rows]
            if not net:
                print(f"     mh={mh:3d} {tag}: veri yok"); continue
            avgu = statistics.mean([r["univ"] for r in rows])
            print(f"     mh={mh:3d} {tag}: EV {round(statistics.mean(net),3)} win {round(100*sum(1 for x in net if x>0)/len(net),1)} "
                  f"n {len(net)} ort-evren {round(avgu,1)} | t(düz) {round(_tstat(net),2)} t(blok) {round(_block_tstat(net,args.hold),2)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
