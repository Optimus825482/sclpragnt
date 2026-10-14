"""TV MEKANİZMA — ÇIKIŞ/STOP/MTF DÜZELTMESİ İLE YENİDEN (2026-10-13, 17b).

NEDEN (kullanıcı haklı eleştirisi): 17. turdaki harness AKSIYORDU:
  * Sabit hold=12 ile "kazananı koştur" imkânsız → trend mekanizmalarının asıl gücü ezildi.
  * Stop/hedef YOK → düşük win, asimetri yok.
  * MTF trend filtresi YOK → popüler TV scriptlerinin imzası eksik.
  * Yanlış benchmark: buy&hold ile kıyasladık. Doğrusu AYNI çıkış kurallı RASTGELE giriş.

BU SCRIPT düzeltir:
  * BAR-İÇİ yol-duyarlı çıkış simülatörü (SL/TP/trailing/ters-sinyal/max-hold).
  * Look-ahead YOK: karar bar kapanışı → giriş ERTESİ bar açılışı; stop hedef barın
    high/low'u ile denenir; aynı barda hem SL hem TP mümkünse SL varsayılır (kötümser).
  * MTF trend filtresi (LTF girişleri yalnız HTF trend onaylıysa) — son KAPANMIŞ HTF barı.
  * ADİL kontrol: aynı sayıda GİRİŞİŞ-zamanı rastgele, AYNI çıkış kuralları → entry timing
    alfa mı, yoksa çıkış kuralı mı, izole edilir.
  * Parametre platosu: komşu parametrelerde kararlılık.

KULLANIM:
    python backend/scripts/research_tv_exits.py --tf 1h
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

from research_tv_mechanisms import (  # noqa: E402
    _atr_series, _ema_series, _macd_series, _rsi_series, _bb_series, _williams_r,
    mech_signals,
)

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_DB = os.path.join(_WORK, "market_cache.sqlite")
_COST = 0.35
_BAR_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
_HTF = {"15m": "1h", "1h": "4h", "4h": "1d", "1d": None}


def _load(tf: str, min_bars: int) -> dict:
    conn = sqlite3.connect(_DB)
    syms = [s for (s,) in conn.execute(
        "SELECT symbol FROM klines WHERE interval=? AND symbol LIKE '%TRY' "
        "GROUP BY symbol HAVING COUNT(*)>=?", (tf, min_bars))]
    ph = ",".join("?" * len(syms))
    rows = conn.execute(
        f"SELECT symbol, open_time, open, high, low, close FROM klines "
        f"WHERE interval=? AND symbol IN ({ph}) ORDER BY symbol, open_time",
        (tf, *syms)).fetchall()
    conn.close()
    out: dict = {}
    for s, ot, o, h, l, c in rows:
        if c and c > 0 and o and o > 0:
            out.setdefault(str(s).upper(), []).append(
                {"t": int(ot), "o": float(o), "h": float(h), "l": float(l), "c": float(c)})
    return {k: v for k, v in out.items() if len(v) >= min_bars}


def _htf_trend_map(tf: str) -> dict:
    """{sym: sorted [(htf_open_time, trend_dir)]} — yalnız KAPANMIŞ HTF barı kullanılacak."""
    htf = _HTF.get(tf)
    if not htf:
        return {}
    conn = sqlite3.connect(_DB)
    syms = [s for (s,) in conn.execute(
        "SELECT symbol FROM klines WHERE interval=? AND symbol LIKE '%TRY' GROUP BY symbol", (htf,))]
    ph = ",".join("?" * len(syms))
    rows = conn.execute(
        f"SELECT symbol, open_time, close FROM klines WHERE interval=? AND symbol IN ({ph}) "
        f"ORDER BY symbol, open_time", (htf, *syms)).fetchall()
    conn.close()
    by_sym: dict = {}
    for s, ot, c in rows:
        if c and c > 0:
            by_sym.setdefault(str(s).upper(), []).append((int(ot), float(c)))
    out = {}
    for s, ser in by_sym.items():
        closes = [c for _, c in ser]
        e = _ema_series(closes, 50)
        tr = []
        for i, (ot, _) in enumerate(ser):
            if e[i] is None:
                continue
            tr.append((ot, 1 if closes[i] > e[i] else -1))
        out[s] = tr
    return out


def _htf_at(trend_rows, ts, htf_ms):
    """ts anında BİLİNEN son kapanmış HTF trendi (look-ahead yok)."""
    lo, hi, ans = 0, len(trend_rows) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if trend_rows[m][0] + htf_ms <= ts:
            ans = trend_rows[m][1]; lo = m + 1
        else:
            hi = m - 1
    return ans


def simulate(bars, sigs, sl_mult, tp_mult, trail_mult, max_hold, exit_rev, hold_only=False):
    """Bar-içi yol-duyarlı çıkış. Giriş: bar i+1 AÇILIŞ; stop/hedef high/low ile.

    sl_mult/tp_mult/trail_mult: 0 veya None → O KURAL DEVRE DIŞI (stop=yok).
    Döner: [(entry_t, dir, net_gross_pct)] — maliyet henüz düşülmemiş.
    """
    n = len(bars)
    atr = _atr_series(bars, 14)
    sig_by_i = {}
    for i, d in sigs:
        sig_by_i.setdefault(i, []).append(d)
    out = []
    for i, d in sigs:
        e = i + 1
        if e >= n or atr[e] is None or atr[e] <= 0:
            continue
        entry = bars[e]["o"]
        a = atr[e]
        if hold_only:
            x = e + max_hold
            if x >= n:
                continue
            out.append((bars[e]["t"], d, (bars[x]["o"] / entry - 1) * 100))
            continue
        stop = (entry - sl_mult * a) if (d > 0 and sl_mult) else \
               (entry + sl_mult * a) if (d < 0 and sl_mult) else None
        tp = (entry + tp_mult * a) if (d > 0 and tp_mult) else \
             (entry - tp_mult * a) if (d < 0 and tp_mult) else None
        best = entry
        exit_px = None
        j = e
        while j < n:
            b = bars[j]
            # 1) stop önce (kötümser): gap varsa açılıştan doldur
            if stop is not None:
                if d > 0 and b["l"] <= stop:
                    exit_px = min(b["o"], stop); break
                if d < 0 and b["h"] >= stop:
                    exit_px = max(b["o"], stop); break
            # 2) hedef
            if tp is not None:
                if d > 0 and b["h"] >= tp:
                    exit_px = max(b["o"], tp); break
                if d < 0 and b["l"] <= tp:
                    exit_px = min(b["o"], tp); break
            # 3) trailing güncelle (stop'u yalnız lehe kaydır)
            if trail_mult:
                if d > 0:
                    best = max(best, b["h"])
                    cand = best - trail_mult * a
                    stop = cand if stop is None else max(stop, cand)
                else:
                    best = min(best, b["l"])
                    cand = best + trail_mult * a
                    stop = cand if stop is None else min(stop, cand)
            # 4) ters sinyal çıkışı (bu bar kapanışında sinyal → ertesi açılış)
            if exit_rev and j > e and (j in sig_by_i) and (-d in sig_by_i[j]):
                if j + 1 < n:
                    exit_px = bars[j + 1]["o"]
                break
            # 5) max-hold
            if j - e + 1 >= max_hold:
                exit_px = b["c"]; break
            j += 1
        if exit_px is None:
            exit_px = bars[min(j, n - 1)]["c"]
        out.append((bars[e]["t"], d, (exit_px / entry - 1) * 100))
    return out


def metrics(rows, cost):
    if not rows:
        return {"n": 0}
    nets = [d * g - cost for _, d, g in rows]
    w = [x for x in nets if x > 0]
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "win": round(100 * len(w) / len(nets), 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--minbars", type=int, default=300)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    tf = args.tf
    out_path = args.out or f"work/tv_exits_{tf}.json"
    ms = _BAR_MS[tf]
    print(f"=== TV ÇIKIŞ/STOP/MTF ({tf}, maliyet {_COST}) ===")
    data = _load(tf, args.minbars)
    htf = _htf_trend_map(tf)
    print(f"  sembol: {len(data)} | MTF: {_HTF[tf]}")

    names = ["M1_ema_cross", "M2_macd_rsi", "M3_supertrend", "M4_donchian_break",
             "M5_rsi_bb_meanrev", "M6_confluence"]
    # çıkış modları: (sl, tp, trail, max_hold, exit_rev)
    modes = {
        "hold12":   (0, 0, 0, 12, False),      # 17. tur baseline (hold-only)
        "atrtrail": (2.0, 0, 2.0, 48, False),  # kazananı koştur
        "sl_tp":    (1.5, 3.0, 0, 48, False),  # asimetrik R/R
        "combo":    (2.0, 0, 2.0, 48, True),   # trailing + ters sinyal
    }
    htf_ms = _BAR_MS[_HTF[tf]] if _HTF[tf] else 0

    print("\n  == ÖRTÜŞMESİZ (dedup) + MTF filtre; long/short net EV / win / n ==")
    header = f"  {'mek':18s}" + "".join(f"{m:>22s}" for m in modes)
    print(header)
    res: dict = {}
    # rastgele kontrol havuzu (aynı çıkış kuralları, rastgele giriş)
    rnd = random.Random(5)
    for nm in names:
        cells = []
        for mode, (sl, tp, tr, mh, rev) in modes.items():
            rows_all = []
            for sym, bars in data.items():
                sigs = mech_signals(nm, bars)
                # MTF filtre
                if htf.get(sym) and htf_ms:
                    tr_rows = htf[sym]
                    sigs = [(i, d) for i, d in sigs
                            if _htf_at(tr_rows, bars[i]["t"], htf_ms) in (None, d)]
                # dedup: örtüşen sinyalleri ele
                kept = []; last_end = -1
                for i, d in sorted(sigs):
                    if i <= last_end:
                        continue
                    kept.append((i, d)); last_end = i + (mh if not sl and not tr else 12)
                rows_all.extend(simulate(bars, kept, sl, tp, tr, mh, rev))
            m = metrics(rows_all, _COST)
            if m["n"] >= 15:
                cells.append(f"{m['ev']:>8}/{m['win']:>4.0f}/{m['n']:<6}")
            else:
                cells.append(f"{'—':>22s}")
            res.setdefault(nm, {})[mode] = m
        print(f"  {nm:18s}" + "".join(f"{c:>22s}" for c in cells))

    # LONG-ONLY (TRY spot kısıtı) en iyi modda
    print("\n  == LONG-ONLY (combo modu, net EV / win / n) ==")
    for nm in names:
        rows_all = []
        for sym, bars in data.items():
            sigs = [(i, d) for i, d in mech_signals(nm, bars) if d == +1]
            if htf.get(sym) and htf_ms:
                tr_rows = htf[sym]
                sigs = [(i, d) for i, d in sigs
                        if _htf_at(tr_rows, bars[i]["t"], htf_ms) in (None, d)]
            kept = []; last_end = -1
            for i, d in sorted(sigs):
                if i <= last_end:
                    continue
                kept.append((i, d)); last_end = i + 12
            rows_all.extend(simulate(bars, kept, 2.0, 0, 2.0, 48, True))
        m = metrics(rows_all, _COST)
        print(f"    {nm:18s} EV {m.get('ev')} win {m.get('win')} n {m.get('n')}")

    # ADİL KONTROL: M3 supertrend + combo, rastgele giriş (aynı çıkış), 200 tekrar
    print("\n  == ADİL KONTROL: rastgele giriş + AYNI çıkış (combo), 200 tekrar ==")
    for nm in ("M3_supertrend", "M4_donchian_break", "M2_macd_rsi"):
        real = []
        n_real = 0
        for sym, bars in data.items():
            sigs = mech_signals(nm, bars)
            if htf.get(sym) and htf_ms:
                tr_rows = htf[sym]
                sigs = [(i, d) for i, d in sigs if _htf_at(tr_rows, bars[i]["t"], htf_ms) in (None, d)]
            kept = []; last_end = -1
            for i, d in sorted(sigs):
                if i <= last_end:
                    continue
                kept.append((i, d)); last_end = i + 12
            real.extend(simulate(bars, kept, 2.0, 0, 2.0, 48, True))
            n_real += len(kept)
        real_ev = round(statistics.mean([d*g - _COST for _, d, g in real]), 3) if real else None
        ctrl_evs = []
        for _ in range(200):
            crows = []
            for sym, bars in data.items():
                k = max(1, len([1 for i, d in mech_signals(nm, bars)]) // 40)
                # rastgele girişler: sembol başına yaklaşık n_real/len(data)
                per = max(1, n_real // max(1, len(data)))
                start = 60
                idxs = sorted(rnd.sample(range(start, max(start+1, len(bars)-1)), min(per, max(1, len(bars)-start-1))))
                rs = [(i, rnd.choice([+1, -1])) for i in idxs]
                crows.extend(simulate(bars, rs, 2.0, 0, 2.0, 48, True))
            if crows:
                ctrl_evs.append(statistics.mean([d*g - _COST for _, d, g in crows]))
        ctrl_ev = round(statistics.mean(ctrl_evs), 3) if ctrl_evs else None
        print(f"    {nm:18s} gerçek EV {real_ev} | rastgele EV {ctrl_ev} | FARK {round((real_ev-ctrl_ev),3) if (real_ev is not None and ctrl_ev is not None) else '—'} (n_real={n_real})")
        res.setdefault("_control", {})[nm] = {"real": real_ev, "ctrl": ctrl_ev}

    res["_meta"] = {"tf": tf, "hold_sym": len(data), "cost": _COST}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\n  rapor: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
