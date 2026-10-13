"""M3 SuperTrend — ODAKLI DOĞRULAMA (17e). Tek adayın gerçek mi artefakt mı?

BAĞLAM: Maruz-bar düzeltilmiş ölçümde M3 SuperTrend (1h) hem al-ve-tut'u (0.0407 vs
0.0362) hem rastgele girişi (0.0371) hafifçe geçti. Ciddiye al: 4 test.

  1. ANLAMLILIK: işlem-bazlı bootstrap → gerçek vs rastgele fark t-değeri.
  2. MALİYET SONRASI maruz-bar getiri (0.0432/bar drag @0.35) → pozitif kalıyor mu?
  3. PLATO ŞEKLİ: trail × max_hold yüzeyi İÇ nokta mı (gerçek) yoksa sınıra monoton mu
     (beta işareti: stop'u gevşettikçe buy&hold'a yakınsıyor) → regresyon eğimi.
  4. SEMBOL DAĞILIMI: getiri tek/birkaç sembole mi yayılmış (kırılgan) yoksa geniş mi?

KULLANIM: python backend/scripts/research_tv_m3.py --tf 1h
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from research_tv_mechanisms import mech_signals  # noqa: E402
from research_tv_exits import _load, _htf_trend_map, _htf_at, _BAR_MS, _HTF  # noqa: E402
from research_tv_exposure import trade_path  # noqa: E402

_COST = 0.35


def _prep(data, htf, htf_ms, nm, hold=12):
    out = {}
    for sym, bars in data.items():
        sigs = [(i, d) for i, d in mech_signals(nm, bars) if d == +1]
        if htf.get(sym) and htf_ms:
            tr = htf[sym]
            sigs = [(i, d) for i, d in sigs if _htf_at(tr, bars[i]["t"], htf_ms) in (None, d)]
        kept = []; last_end = -1
        for i, d in sorted(sigs):
            if i <= last_end:
                continue
            kept.append((i, d)); last_end = i + hold
        out[sym] = (bars, kept)
    return out


def _trades(prep, sl, trail, mh, rev):
    rows = []   # (sym, ret, held)
    for sym, (bars, kept) in prep.items():
        sbi = {}
        for i, d in kept:
            sbi.setdefault(i, []).append(d)
        for i, d in kept:
            r = trade_path(bars, i, d, sl, trail, mh, rev, sbi)
            if r:
                rows.append((sym, r[0], r[1]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--minbars", type=int, default=300)
    args = ap.parse_args()
    tf = args.tf
    data = _load(tf, args.minbars)
    htf = _htf_trend_map(tf)
    htf_ms = _BAR_MS[_HTF[tf]] if _HTF[tf] else 0
    print(f"=== M3 SuperTrend ODAKLI ({tf}) | sembol {len(data)} ===")
    prep = _prep(data, htf, htf_ms, "M3_supertrend")
    real = _trades(prep, 2.0, 2.0, 48, True)
    real_gross = statistics.mean([r for _, r, _ in real])
    real_perbar = real_gross / statistics.mean([h for _, _, h in real])
    print(f"  gerçek: n {len(real)} | gross {round(real_gross,3)} | maruz-bar/get {round(real_perbar,4)}")

    # 3. PLATO + sınıra monotonluk
    print("\n  == PLATO (gross, long-only; satır=trail, kolon=max_hold) ==")
    grid = []
    for tr in (1.5, 2.0, 3.0, 4.0, 6.0):
        line = []
        for mh in (24, 48, 96, 200):
            rows = _trades(prep, 2.0, tr, mh, False)
            g = statistics.mean([r for _, r, _ in rows]) if rows else None
            line.append(round(g, 2) if g is not None else None)
        grid.append((tr, line))
        print(f"     tr{tr:<4} " + "".join(f"{str(x):>8}" for x in line))
    # monotonluk: trail boyunca en iyi değer sınıra mı kayıyor?
    tr_means = [statistics.mean([x for x in line if x is not None]) for _, line in grid]
    inc = sum(1 for k in range(1, len(tr_means)) if tr_means[k] > tr_means[k-1])
    print(f"     trail boyunca artış: {inc}/{len(tr_means)-1} adım → "
          f"{'SINIRA MONOTON (beta işareti)' if inc >= len(tr_means)-2 else 'İÇ OPTIMUM (sinyal)'}")

    # 1. anlamlılık (bootstrap): gerçek vs rastgele (aynı çıkış)
    rnd = random.Random(31)
    diffs = []
    real_mean = real_gross
    for _ in range(300):
        crows = []
        for sym, (bars, kept) in prep.items():
            nk = len(kept)
            if nk == 0 or len(bars) < 80:
                continue
            idxs = sorted(rnd.sample(range(60, len(bars) - 1), min(nk, len(bars) - 61)))
            sbi = {}
            for i in idxs:
                sbi.setdefault(i, []).append(+1)
            for i in idxs:
                r = trade_path(bars, i, +1, 2.0, 2.0, 48, True, sbi)
                if r:
                    crows.append(r)
        if crows:
            diffs.append(real_mean - statistics.mean([r for r, _ in crows]))
    if diffs:
        mu = statistics.mean(diffs); sd = statistics.pstdev(diffs)
        t = mu / (sd + 1e-9)
        pos = sum(1 for d in diffs if d > 0)
        print(f"\n  == ANLAMLILIK (gerçek − rastgele, 300 tekrar) ==")
        print(f"     fark ort {round(mu,3)} | sd {round(sd,3)} | t {round(t,2)} | gerçek>rastgele {pos}/300")
        print(f"     → {'ANLAMLI' if t > 2 else 'ANLAMSIZ (gürültü)'}")

    # 2. maliyet sonrası maruz-bar
    avg_held = statistics.mean([h for _, _, h in real])
    drag_per_bar = _COST / avg_held
    print(f"\n  == MALİYET SONRASI (işlem başı ~{round(avg_held,1)} bar) ==")
    print(f"     maruz-bar gross {round(real_perbar,4)} − maliyet/bar {round(drag_per_bar,4)} = "
          f"{round(real_perbar - drag_per_bar,4)} → {'POZİTİF' if real_perbar > drag_per_bar else 'NEGATİF'}")

    # 4. sembol dağılımı
    by_sym = {}
    for sym, r, _ in real:
        by_sym.setdefault(sym, []).append(r)
    sym_means = {s: statistics.mean(v) for s, v in by_sym.items() if len(v) >= 3}
    pos_sym = sum(1 for v in sym_means.values() if v > 0)
    top = sorted(sym_means.items(), key=lambda kv: -kv[1])
    total = sum(sym_means.values())
    top3_share = sum(v for _, v in top[:3]) / total * 100 if total else 0
    print(f"\n  == SEMBOL DAĞILIMI ({len(sym_means)} sembol) ==")
    print(f"     pozitif sembol {pos_sym}/{len(sym_means)} | en iyi 3 sembol toplamın %{round(top3_share,1)}'i")
    print(f"     en iyi: {[(s, round(v,2)) for s, v in top[:3]]}")

    out = {"tf": tf, "real_gross": round(real_gross, 3), "real_per_bar": round(real_perbar, 4),
           "combined_t": round(t, 2) if diffs else None,
           "cost_adjusted_per_bar": round(real_perbar - drag_per_bar, 4),
           "monotonic_to_boundary": inc >= len(tr_means) - 2,
           "pos_symbols": f"{pos_sym}/{len(sym_means)}"}
    with open(f"work/tv_m3_{tf}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  rapor: work/tv_m3_{tf}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
