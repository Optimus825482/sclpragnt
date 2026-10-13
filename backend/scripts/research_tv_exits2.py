"""TV MEKANİZMA — LONG-ONLY ADİL KONTROL + PARAMETRE PLATOSU + MALİYET (17c).

NEDEN: 17b çıkış/stop/MTF ekledi; trend mekanizmaları kurtulmadı ve adil kontrol farkı ~0
çıktı. Bu script KALAN aksak noktaları kapatır (kullanıcı eleştirisi ciddiye alınarak):

  A. LONG-ONLY adil kontrol: TRY spot long-only olduğundan ASIL geçerli karşılaştırma budur.
     Aynı sayıda RASTGELE long giriş + AYNI çıkış kuralları → giriş zamanlaması alfa mı?
     Maliyetsiz (gross) fark, yalnız TIMING etkisini izole eder.
  B. Buy&hold'a karşı long-only GROSS EV → pozitif görünen şey beta mı?
  C. Parametre platosu: trail × max_hold grid → kararlı bölge mi, tek tepe (curve-fit) mi?
  D. Maliyet kırılma noktası: maker/limit maliyetiyle (0.15) hayatta kalıyor mu?

KULLANIM: python backend/scripts/research_tv_exits2.py --tf 4h
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
from research_tv_exits import _load, _htf_trend_map, _htf_at, simulate, _BAR_MS, _HTF  # noqa: E402

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")


def _prep(data, htf, htf_ms, nm, hold=12):
    """Sembol → (bars, dedup+MTF filtreli sinyaller) sözlüğü."""
    out = {}
    for sym, bars in data.items():
        sigs = mech_signals(nm, bars)
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


def _gross(rows):
    return statistics.mean([d * g for _, d, g in rows]) if rows else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--minbars", type=int, default=200)
    ap.add_argument("--reps", type=int, default=150)
    args = ap.parse_args()
    tf = args.tf
    ms = _BAR_MS[tf]
    data = _load(tf, args.minbars)
    htf = _htf_trend_map(tf)
    htf_ms = _BAR_MS[_HTF[tf]] if _HTF[tf] else 0
    print(f"=== LONG-ONLY ADİL + PLATO ({tf}) | sembol {len(data)} | MTF {_HTF[tf]} ===")
    names = ["M1_ema_cross", "M2_macd_rsi", "M3_supertrend", "M4_donchian_break",
             "M5_rsi_bb_meanrev", "M6_confluence"]
    rnd = random.Random(9)

    # A/B. LONG-ONLY: gerçek vs rastgele, AYNI çıkış (combo), gross (maliyetsiz)
    print("\n  == A. LONG-ONLY gross EV: gerçek vs rastgele (aynı çıkış) + buy&hold ==")
    print(f"  {'mek':18s}{'gerçek_gr':>11}{'rastgele_gr':>13}{'FARK':>9}{'b&h_gr':>9}{'5fold_fark':>13}")
    res: dict = {}
    # buy&hold gross (açık pozisyon ort getiri, hold bar ileri)
    bh_all = []
    for sym, bars in data.items():
        o = [b["o"] for b in bars]
        for i in range(0, len(bars) - 12):
            bh_all.append((o[i + 12] / o[i] - 1) * 100)
    bh_gross = round(statistics.mean(bh_all), 3)
    for nm in names:
        prep = _prep(data, htf, htf_ms, nm)
        real = []
        for sym, (bars, kept) in prep.items():
            real.extend(simulate(bars, [(i, d) for i, d in kept if d == +1], 2.0, 0, 2.0, 48, True))
        rg = _gross(real)
        # rastgele long-only kontrol
        diffs = []
        for _ in range(args.reps):
            crows = []
            for sym, (bars, kept) in prep.items():
                nk = len([1 for i, d in kept if d == +1])
                if nk == 0 or len(bars) < 80:
                    continue
                idxs = sorted(rnd.sample(range(60, max(61, len(bars) - 1)), min(nk, max(1, len(bars) - 61))))
                crows.extend(simulate(bars, [(i, +1) for i in idxs], 2.0, 0, 2.0, 48, True))
            cg = _gross(crows)
            if cg is not None and rg is not None:
                diffs.append(rg - cg)
        ctrl_gr = round(rg - statistics.mean(diffs), 3) if (diffs and rg is not None) else None
        # 5-fold fark (gerçek gross foldları − rastgele ortalama)
        real_sorted = sorted(real, key=lambda r: r[0])
        nets = [d * g for _, d, g in real_sorted]
        nf = 5
        folds = [round(statistics.mean(nets[int(len(nets)*k/nf):int(len(nets)*(k+1)/nf)]), 2) for k in range(nf)]
        fold_txt = f"{folds} p{sum(1 for f in folds if f>bh_gross)}"
        res[nm] = {"real_gross": rg, "ctrl_gross": ctrl_gr,
                   "diff": round(rg - ctrl_gr, 3) if (rg is not None and ctrl_gr is not None) else None,
                   "bh_gross": bh_gross, "real_gross_folds": folds}
        print(f"  {nm:18s}{(rg if rg is not None else 0):>11}{(ctrl_gr if ctrl_gr is not None else 0):>13}"
              f"{(round(rg-ctrl_gr,3) if (rg is not None and ctrl_gr is not None) else 0):>9}{bh_gross:>9}   {fold_txt}")

    # C. Parametre platosu (long-only, trailing × max_hold), M3 & M4
    print("\n  == C. PARAMETRE PLATOSU (long-only NET EV @0.35) — M3/M4 ==")
    for nm in ("M3_supertrend", "M4_donchian_break", "M2_macd_rsi"):
        print(f"     {nm}: trail ↓ / max_hold →")
        print("        " + "".join(f"{mh:>8}" for mh in (24, 48, 96)))
        prep = _prep(data, htf, htf_ms, nm)
        for tr in (1.5, 2.0, 3.0, 4.0):
            cell = []
            for mh in (24, 48, 96):
                rows = []
                for sym, (bars, kept) in prep.items():
                    rows.extend(simulate(bars, [(i, d) for i, d in kept if d == +1], 2.0, 0, tr, mh, False))
                if len(rows) >= 15:
                    ev = statistics.mean([d * g - 0.35 for _, d, g in rows])
                    cell.append(f"{round(ev,2):>8}")
                else:
                    cell.append(f"{'—':>8}")
            print(f"     tr{tr:<3} " + "".join(cell))

    # D. Maliyet kırılma noktası (long-only, combo) — en iyi 3
    print("\n  == D. MALİYET KIRILMA (long-only combo, gross→net) ==")
    print(f"  {'mek':18s}{'gross':>8}{'net@0.15':>10}{'net@0.25':>10}{'net@0.35':>10}")
    for nm in ("M2_macd_rsi", "M3_supertrend", "M4_donchian_break", "M6_confluence"):
        prep = _prep(data, htf, htf_ms, nm)
        rows = []
        for sym, (bars, kept) in prep.items():
            rows.extend(simulate(bars, [(i, d) for i, d in kept if d == +1], 2.0, 0, 2.0, 48, True))
        if len(rows) < 15:
            continue
        g = statistics.mean([d * gg for _, d, gg in rows])
        print(f"  {nm:18s}{round(g,3):>8}" + "".join(f"{round(g-c,3):>10}" for c in (0.15, 0.25, 0.35)))

    res["_meta"] = {"tf": tf, "bh_gross": bh_gross, "symbols": len(data)}
    out = f"work/tv_exits2_{tf}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\n  rapor: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
