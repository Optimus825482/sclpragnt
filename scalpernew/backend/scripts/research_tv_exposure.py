"""TV MEKANİZMA — MARUZİYET/RİSK DÜZELTİLMİŞ KIYAS (17d, SON ADİL TEST).

NEDEN (kalan aksak nokta): Ham EV ile al-ve-tut kıyaslamak HAKSIZ. Mekanizma zamanın
yalnız ~%X'inde piyasada; geri kalanında nakitte. Nakit = düşük risk + boşta sermaye.
Adil ölçü: (i) maruziyet başına getiri (return per bar-in-market), (ii) equity eğrisi
max-drawdown. Bir mekanizma ham EV'de düşük ama maruziyet başına YÜKSEK getiri sağlıyorsa
bu GERÇEK bir kazançtır (aynı getiri, daha az risk/sermaye).

ÖLÇÜM: long-only combo; her sembol için equity eğrisi kur → toplam getiri, maruziyet
(bars in market), return/exposure, max drawdown. Buy&hold ile kıyasla.

KULLANIM: python backend/scripts/research_tv_exposure.py --tf 4h
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from research_tv_mechanisms import mech_signals, _atr_series  # noqa: E402
from research_tv_exits import _load, _htf_trend_map, _htf_at, _BAR_MS, _HTF  # noqa: E402

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_COST = 0.35


def trade_path(bars, i, d, sl_mult, trail_mult, max_hold, exit_rev, sig_by_i):
    """Tek işlemin (getiri%, bars_held) dönüşü — simulate ile aynı kurallar."""
    n = len(bars)
    atr = _atr_series(bars, 14)
    e = i + 1
    if e >= n or atr[e] is None or atr[e] <= 0:
        return None
    entry = bars[e]["o"]; a = atr[e]
    stop = (entry - sl_mult * a) if (d > 0 and sl_mult) else \
           (entry + sl_mult * a) if (d < 0 and sl_mult) else None
    best = entry
    j = e
    while j < n:
        b = bars[j]
        if stop is not None:
            if d > 0 and b["l"] <= stop:
                return ((min(b["o"], stop) / entry - 1) * 100, j - e + 1)
            if d < 0 and b["h"] >= stop:
                return ((max(b["o"], stop) / entry - 1) * 100, j - e + 1)
        if trail_mult:
            if d > 0:
                best = max(best, b["h"]); cand = best - trail_mult * a
                stop = cand if stop is None else max(stop, cand)
            else:
                best = min(best, b["l"]); cand = best + trail_mult * a
                stop = cand if stop is None else min(stop, cand)
        if exit_rev and j > e and (j in sig_by_i) and (-d in sig_by_i[j]) and j + 1 < n:
            return ((bars[j + 1]["o"] / entry - 1) * 100, j - e + 1)
        if j - e + 1 >= max_hold:
            return ((b["c"] / entry - 1) * 100, j - e + 1)
        j += 1
    return ((bars[min(j, n - 1)]["c"] / entry - 1) * 100, min(j, n - 1) - e + 1)


def max_dd(equity):
    peak = equity[0] if equity else 0; dd = 0
    for v in equity:
        peak = max(peak, v); dd = max(dd, peak - v)
    return dd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--minbars", type=int, default=200)
    args = ap.parse_args()
    tf = args.tf
    data = _load(tf, args.minbars)
    htf = _htf_trend_map(tf)
    htf_ms = _BAR_MS[_HTF[tf]] if _HTF[tf] else 0
    print(f"=== MARUZİYET/RİSK DÜZELTİLMİŞ ({tf}) | sembol {len(data)} ===")

    # buy&hold referansı: her sembol baştan sona long
    bh_rets = []
    for sym, bars in data.items():
        o = [b["o"] for b in bars]
        bh_rets.append((o[-1] / o[0] - 1) * 100)
    bh_avg = round(statistics.mean(bh_rets), 2)
    bh_bars = statistics.mean([len(v) for v in data.values()])
    bh_per_bar = round(bh_avg / bh_bars, 4)
    print(f"  AL-VE-TUT: ort toplam getiri {bh_avg}% | ort bar {round(bh_bars)} | bar başına {bh_per_bar}%")

    names = ["M1_ema_cross", "M2_macd_rsi", "M3_supertrend", "M4_donchian_break",
             "M5_rsi_bb_meanrev", "M6_confluence"]
    print(f"\n  b&h NOT: 'maruz getiri/bar' = ort işlem getirisi / ort bar (maruz kalırken bar başına)."
          f" b&h = {bh_per_bar}%/bar. ÜSTÜNDEYSE pozisyon zamanlaması bh'yi geçiyor.")
    print(f"\n  {'mek':18s}{'işlem':>6}{'gross%':>9}{'maruz%':>8}{'ort_bar':>8}{'maruz get/bar':>13}{'>bh?':>6}{'maxDD':>8}")
    res: dict = {}
    for nm in names:
        all_ret = []; total_exposure = 0; total_bars = 0; dds = []; total_held = 0
        for sym, bars in data.items():
            sigs = [(i, d) for i, d in mech_signals(nm, bars) if d == +1]
            if htf.get(sym) and htf_ms:
                tr = htf[sym]
                sigs = [(i, d) for i, d in sigs if _htf_at(tr, bars[i]["t"], htf_ms) in (None, d)]
            sig_by_i = {}
            for i, d in sigs:
                sig_by_i.setdefault(i, []).append(d)
            kept = []; last_end = -1
            for i, d in sorted(sigs):
                if i <= last_end:
                    continue
                kept.append((i, d)); last_end = i + 12
            exp = 0; eq = [1.0]; cum = 1.0
            for i, d in kept:
                r = trade_path(bars, i, d, 2.0, 2.0, 48, True, sig_by_i)
                if r is None:
                    continue
                ret, held = r
                all_ret.append(ret); exp += held; total_held += held
                cum *= (1 + (ret - _COST) / 100); eq.append(cum)
            total_exposure += exp; total_bars += len(bars)
            dds.append(max_dd(eq) * 100)
        if not all_ret:
            continue
        gross = round(statistics.mean(all_ret), 3)
        maruz = round(100 * total_exposure / max(1, total_bars), 1)
        avg_held = round(total_held / len(all_ret), 1)
        per_bar = round(gross / max(1e-9, avg_held), 4)     # maruz kalırken bar başına getiri
        dd_avg = round(statistics.mean(dds), 2)
        flag = "YES" if per_bar > bh_per_bar else "no"
        res[nm] = {"trades": len(all_ret), "gross": gross, "exposure_pct": maruz,
                   "avg_bars_held": avg_held, "return_per_bar_in_market": per_bar,
                   "maxdd_avg": dd_avg, "beats_bh_per_bar": per_bar > bh_per_bar}
        print(f"  {nm:18s}{len(all_ret):>6}{gross:>9}{maruz:>8}{avg_held:>8}{per_bar:>13}{flag:>6}{dd_avg:>8}")

    # RASTGELE KONTROL: aynı çıkış, rastgele long giriş → maruz-bar başına getiri
    import random as _r
    rnd = _r.Random(21)
    print(f"\n  == RASTGELE KONTROL (aynı çıkış, rastgele long giriş, maruz get/bar) ==")
    for nm in ("M2_macd_rsi", "M3_supertrend", "M4_donchian_break", "M6_confluence"):
        real_per_bar = res.get(nm, {}).get("return_per_bar_in_market")
        per_bars = []
        for _ in range(60):
            tot_ret = []; tot_held = 0
            for sym, bars in data.items():
                sigs = [(i, d) for i, d in mech_signals(nm, bars) if d == +1]
                if htf.get(sym) and htf_ms:
                    tr = htf[sym]
                    sigs = [(i, d) for i, d in sigs if _htf_at(tr, bars[i]["t"], htf_ms) in (None, d)]
                nk = len(sigs)
                if nk == 0 or len(bars) < 80:
                    continue
                idxs = sorted(rnd.sample(range(60, len(bars) - 1), min(nk, len(bars) - 61)))
                sig_by_i = {}
                for i in idxs:
                    sig_by_i.setdefault(i, []).append(+1)
                kept = []; last_end = -1
                for i in idxs:
                    if i <= last_end:
                        continue
                    kept.append((i, +1)); last_end = i + 12
                for i, d in kept:
                    r = trade_path(bars, i, d, 2.0, 2.0, 48, True, sig_by_i)
                    if r:
                        tot_ret.append(r[0]); tot_held += r[1]
            if tot_ret and tot_held:
                per_bars.append(statistics.mean(tot_ret) / (tot_held / len(tot_ret)))
        if per_bars:
            rb = round(statistics.mean(per_bars), 4)
            res.setdefault(nm, {})["ctrl_per_bar"] = rb
            verdict = ("GERÇEK>RASTGELE" if (real_per_bar and real_per_bar > rb) else "GERÇEK≤RASTGELE")
            print(f"    {nm:18s} gerçek/bar {real_per_bar} | rastgele/bar {rb} | {verdict}")

    res["_meta"] = {"tf": tf, "bh_avg": bh_avg, "bh_per_bar": bh_per_bar, "symbols": len(data)}
    out = f"work/tv_exposure_{tf}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\n  rapor: {out}")
    print(f"  NOT: 'getiri/maruz' = işlem başına getiri / maruziyet oranı. b&h referans: {bh_per_bar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
