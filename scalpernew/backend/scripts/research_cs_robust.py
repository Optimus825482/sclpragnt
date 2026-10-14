"""KESİTSEL MOMENTUM — SAĞLAMLIK (sabit evren + örtüşme) (2026-10-13).

NEDEN: research_cs_verify.py gösterdi ki "KARARLI +2.04" örtüşen pencerelerden geliyor:
bağımsız (adım=hold) koşuda EV +0.95, t=0.85 (anlamsız). Ayrıca evren 31→59 sembole BÜYÜYOR
(survivorship/listing yanlılığı). Bu script iki kontrolü kesinleştirir:

  D. SABİT EVREN: yalnız baştan beri veri olan semboller → buyüme etkisi kalkar.
  E. ÖRTÜŞEN serinin blok-bootstrap t'si → script1'in "KARARLI" iddiası anlamlı mı?

KULLANIM: python backend/scripts/research_cs_robust.py --tf 1d --top-syms 60
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research_cs_verify import _load_minimal, _top_symbols, _spreads, _tstat, _block_tstat  # noqa: E402

_TAKER = 0.35


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

    firsts = {s: dt.datetime.utcfromtimestamp(r[0][0] / 1000).strftime("%Y-%m-%d") for s, r in series.items()}
    earliest = min(firsts.values())
    print(f"=== SAĞLAMLIK ({args.tf}, top{args.topn}) | evren {len(series)} | en eski {earliest} ===")

    # --- E. ÖRTÜŞEN seri blok-bootstrap t (script1'in rakamı anlamlı mı?) ---
    over = _spreads(series, args.lookback, args.hold, args.topn, step=1)
    over_net = [r["spread"] - c2 for r in over]
    over_lx = [r["long_exc"] - _TAKER for r in over]
    print("\n  == E. TAM EVREN, ÖRTÜŞEN (script1 ile aynı) ==")
    print(f"     spread net EV {round(statistics.mean(over_net),3)} n {len(over_net)}")
    print(f"     t (düz, YANILTICI) {round(_tstat(over_net),2)} | t (blok-boot hold=6) {round(_block_tstat(over_net,args.hold),2)}")
    print(f"     long_exc net EV {round(statistics.mean(over_lx),3)} | t(blok) {round(_block_tstat(over_lx,args.hold),2)}")

    # --- D. SABİT EVREN: baştan beri var olan semboller ---
    # ilk 45 gün içinde başlayanlar
    cutoff = (dt.datetime.strptime(earliest, "%Y-%m-%d") + dt.timedelta(days=45)).strftime("%Y-%m-%d")
    const = {s: r for s, r in series.items() if firsts[s] <= cutoff}
    print(f"\n  == D. SABİT EVREN (ilk veri ≤{cutoff}) → {len(const)} sembol ==")
    for step, tag in ((1, "örtüşen"), (args.hold, "bağımsız")):
        rows = _spreads(const, args.lookback, args.hold, args.topn, step=step)
        net = [r["spread"] - c2 for r in rows]
        lx = [r["long_exc"] - _TAKER for r in rows]
        if not net:
            print(f"     {tag}: veri yok"); continue
        nf = 4
        folds = [round(statistics.mean(net[int(len(net)*k/nf):int(len(net)*(k+1)/nf)]), 3) for k in range(nf)]
        print(f"     {tag}: spread EV {round(statistics.mean(net),3)} win {round(100*sum(1 for x in net if x>0)/len(net),1)} "
              f"n {len(net)} | t(düz) {round(_tstat(net),2)} t(blok) {round(_block_tstat(net,args.hold),2)}")
        print(f"              long_exc EV {round(statistics.mean(lx),3)} | foldlar {folds} | pozitif {sum(1 for f in folds if f>0)}/{nf}")

    # --- Rastgele kontrol (sabit evren) ---
    rconst = _spreads(const, args.lookback, args.hold, args.topn, step=args.hold, control=True)
    rnet = [r["spread"] - c2 for r in rconst]
    irows = _spreads(const, args.lookback, args.hold, args.topn, step=args.hold)
    inet = [r["spread"] - c2 for r in irows]
    m = min(len(rnet), len(inet))
    diff = [inet[i] - rnet[i] for i in range(m)]
    print(f"\n  == RASTGELE KONTROL (sabit evren, bağımsız) ==")
    print(f"     gerçek {round(statistics.mean(inet),3)} | rastgele {round(statistics.mean(rnet),3)} | fark {round(statistics.mean(diff),3)} t {round(_tstat(diff),2)} (n{m})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
