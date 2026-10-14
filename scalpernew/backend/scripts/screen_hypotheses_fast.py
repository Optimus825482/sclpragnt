"""FARKLI HİPOTEZ TARAMASI — hızlı sürüm (2026-10-12).

Yedi turda denenenlerden (tek-coin momentum, order-flow, lead-lag, ADX rejim,
zıt-yön dönüş, maker maliyet) BAĞIMSIZ yeni hipotezleri tarar. Amaç: maliyeti
(%0.35 taker) AŞAN aday bulmak; sonra en iyi 2'yi derin test etmek.

HİPOTEZLER:
  H1 KESİTSEL GÖRELİ GÜÇ : sepette 24-bar en güçlü/zayıf %20 (LONG/SHORT), 12-bar ileri
  H2 VOLATİLİTE SIKIŞMASI: düşük ATR (alt %25) + 20-bar zirve kırılımı → LONG
  H3 AŞIRI HAREKET DÖNÜŞ : tek bar |z|>=2 → ters yön (reversal)
  H4 HACİM-FİYAT UYUMSUZ  : fiyat yükseldi ama hacim zayıf → ters (fade)
  H5 SAATSEL SEZONLUK     : saatlere göre ortalama ileri getiri

HIZ: numpy ile vektörel (bar-başı python döngüsü yok).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "..", "work", "market_cache.sqlite")
_COST = 0.35


def load(db: str, days: float, min_bars: int = 5000) -> dict:
    conn = sqlite3.connect(db)
    syms = [s for (s,) in conn.execute(
        "SELECT symbol FROM klines WHERE interval='5m' AND symbol LIKE '%TRY' "
        "GROUP BY symbol HAVING COUNT(*)>=?", (min_bars,))]
    out = {}
    cutoff = None
    for s in syms:
        rows = conn.execute(
            "SELECT open_time,open,high,low,close,volume FROM klines "
            "WHERE interval='5m' AND symbol=? ORDER BY open_time", (s,)).fetchall()
        if not rows:
            continue
        if cutoff is None:
            cutoff = max(r[0] for r in rows) - int(days * 86400 * 1000)
        sel = [r for r in rows if r[0] >= cutoff and (r[4] or 0) > 0]
        if len(sel) >= 400:
            out[s] = {
                "t": np.array([r[0] for r in sel], dtype=np.int64),
                "h": np.array([r[2] for r in sel], dtype=np.float64),
                "l": np.array([r[3] for r in sel], dtype=np.float64),
                "c": np.array([r[4] for r in sel], dtype=np.float64),
                "v": np.array([(r[5] or 0.0) for r in sel], dtype=np.float64),
            }
    conn.close()
    return out


def _stats(nets):
    nets = [x for x in nets if x is not None]
    if not nets:
        return {"n": 0, "net": None}
    a = np.array(nets)
    return {"n": len(nets), "net": round(float(a.mean()), 3),
            "wr": round(100 * float((a > 0).mean()), 1)}


def screen(data: dict) -> dict:
    res = {}
    print(f"  sembol: {len(data)}", flush=True)

    # ---- H3 aşırı hareket dönüşü + H2 sıkışma + H4 (hepsi VEKTÖREL) ----
    h3_nets, h2_nets, h4_nets = [], [], []
    hour_sum = {}
    for s, d in data.items():
        c, h, l, v, t = d["c"], d["h"], d["l"], d["v"], d["t"]
        n = len(c)
        if n < 130:
            continue
        r1 = np.zeros(n); r1[1:] = (c[1:] / c[:-1] - 1) * 100
        fwd = np.full(n, np.nan); fwd[:n - 12] = (c[12:] / c[:n - 12] - 1) * 100

        # H3: rolling 30-bar std → z-skor (vektörel)
        win = 30
        rm = np.convolve(r1, np.ones(win) / win, mode="valid")          # len n-win+1
        r2 = np.convolve(r1 * r1, np.ones(win) / win, mode="valid")
        std = np.sqrt(np.maximum(r2 - rm * rm, 0.0))
        z = np.full(n, np.nan)
        z[win - 1:] = np.where(std > 0, r1[win - 1:] / std, 0.0)
        mask = (~np.isnan(z)) & (~np.isnan(fwd)) & (np.abs(z) >= 2.0)
        idx = np.where(mask)[0]
        if len(idx):
            g = fwd[idx]; zz = z[idx]
            nets = np.where(zz > 0, -g, g) - _COST
            h3_nets.extend(nets.tolist())

        # H2: ATR(14) sıkışma (son 100 bar alt %25) + 20-bar zirve kırılımı (vektörel)
        tr = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
        atr = np.convolve(tr, np.ones(14) / 14, mode="valid")           # atr[k] ~ tr[k..k+13], bar (k+14)
        # bar i için atr index = i - 14
        prior_hi = np.full(n, np.nan)
        prior_hi[20:] = np.array([h[i - 20:i].max() for i in range(20, n)])
        for i in range(120, n - 12):
            ai = i - 14
            if ai < 20 or ai >= len(atr) or np.isnan(fwd[i]) or np.isnan(prior_hi[i]):
                continue
            hist = atr[max(0, ai - 100):ai]
            if len(hist) < 20:
                continue
            if atr[ai] <= np.percentile(hist, 25) and c[i] > prior_hi[i]:
                h2_nets.append(float(fwd[i]) - _COST)
        # (H2 döngüsü kısa: yalnız sıkışma adayı barlar; n=17k için ihmal edilebilir)

        # H4: 3-bar yükseliş + zayıf hacim → ters (vektörel)
        vavg = np.convolve(v, np.ones(20) / 20, mode="valid"); voff = 19
        vv = np.full(n, np.nan); vv[voff:] = vavg
        up3 = np.full(n, np.nan); up3[3:] = (c[3:] / c[:-3] - 1)
        m_up = (~np.isnan(fwd)) & (~np.isnan(up3)) & (~np.isnan(vv)) & (vv > 0) & \
               (up3 > 0.005) & (v < vv * 0.8)
        m_dn = (~np.isnan(fwd)) & (~np.isnan(up3)) & (~np.isnan(vv)) & (vv > 0) & \
               (up3 < -0.005) & (v > vv * 1.5)
        h4_nets.extend((-fwd[m_up] - _COST).tolist())
        h4_nets.extend((-fwd[m_dn] - _COST).tolist())

        # H5: saat bazlı (vektörel)
        hrs = ((t // 1000 // 3600) % 24).astype(int)
        fin = ~np.isnan(fwd)
        for hh in np.unique(hrs[fin]):
            sel = fwd[fin & (hrs == hh)]
            hour_sum.setdefault(int(hh), []).extend(sel.tolist())

    res["H3_asiri_donus"] = _stats(h3_nets)
    res["H2_vol_sikismasi"] = _stats(h2_nets)
    res["H4_hacim_uyumsuz"] = _stats(h4_nets)

    # ---- H1 kesitsel göreli güç (zaman-hizalı, numpy) ----
    print("  H1 hesaplanıyor...", flush=True)
    # ortak zaman ekseni: tüm sembollerin zamanlarını birleştir
    all_t = np.unique(np.concatenate([d["t"] for d in data.values()]))
    # her sembol için t->c eşlemesi
    cmaps = {s: (d["t"], d["c"]) for s, d in data.items()}
    # zaman -> {s: c}
    t_index = {}
    for s, (tt, cc) in cmaps.items():
        for j in range(len(tt)):
            t_index.setdefault(int(tt[j]), {})[s] = j
    h1_long, h1_short = [], []
    for tv in all_t:
        m = t_index.get(int(tv))
        if not m or len(m) < 15:
            continue
        scored = []
        for s, j in m.items():
            tt, cc = cmaps[s]
            if j < 24 or j + 12 >= len(cc):
                continue
            mom = cc[j] / cc[j - 24] - 1
            fwd = cc[j + 12] / cc[j] - 1
            scored.append((mom, fwd))
        if len(scored) < 15:
            continue
        scored.sort(key=lambda x: x[0])
        k = max(1, int(len(scored) * 0.2))
        for _, fw in scored[-k:]:
            h1_long.append(fw * 100 - _COST)
        for _, fw in scored[:k]:
            h1_short.append(-fw * 100 - _COST)
    res["H1_kesitsel"] = {
        "long": _stats(h1_long), "short": _stats(h1_short),
        "spread_gross": round((np.mean(h1_long) if h1_long else 0) -
                              (np.mean(h1_short) if h1_short else 0), 3)}

    # H5 saat
    hs = {hh: float(np.mean(v)) for hh, v in hour_sum.items() if len(v) > 50}
    if hs:
        best = max(hs.items(), key=lambda kv: kv[1]); worst = min(hs.items(), key=lambda kv: kv[1])
        res["H5_saatsel"] = {"best_hour": best[0], "best_gross": round(best[1], 3),
                             "best_net": round(best[1] - _COST, 3),
                             "worst_hour": worst[0], "worst_gross": round(worst[1], 3),
                             "range": round(best[1] - worst[1], 3)}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=45.0)
    ap.add_argument("--db", default=_DB)
    args = ap.parse_args()
    print("=== FARKLI HİPOTEZ TARAMASI (net = taker %0.35 düşülmüş) ===")
    data = load(args.db, args.days)
    res = screen(data)
    for k, v in res.items():
        print(f"  {k}: {v}")
    cands = []
    for k, v in res.items():
        if "net" in v and isinstance(v.get("net"), (int, float)):
            cands.append((v["net"], k))
        elif "long" in v:
            cands.append((max(v["long"]["net"] or -9, v["short"]["net"] or -9), k))
        elif "best_net" in v:
            cands.append((v["best_net"], k))
    cands.sort(reverse=True)
    print("\n  == EN İYİ 2 ADAY (net EV) ==")
    for nv, k in cands[:2]:
        print(f"  {k}: net~{nv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
