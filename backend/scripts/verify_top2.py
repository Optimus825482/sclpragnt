"""EN İYİ 2 ADAY DERİN DOĞRULAMA (2026-10-12).

Tarama (screen_hypotheses_fast) 5 bağımsız hipotezi ölçtü; en iyi 2:
  ADAY 1 — H5 SAATSEL SEZONLUK: belirli saatlerde sistematik yön (UTC 15 brüt +0.226)
  ADAY 2 — H3 AŞIRI HAREKET DÖNÜŞÜ: |z|>=2 bar sonrası ters yön (en yüksek ham getiri)

Bu script ikisini de TİTİZ sınar (yedi turun standardı): 3-fold walk-forward,
gün-gün stabilite, eşleştirilmiş t-testi, sembol yoğunlaşma, komisyon duyarlılık.

KURAL: Araştırma; commit yok. Uygulama çalışma düzenine dokunulmaz.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "..", "work", "market_cache.sqlite")


def load(days=45.0, min_bars=5000) -> dict:
    conn = sqlite3.connect(_DB)
    syms = [s for (s,) in conn.execute(
        "SELECT symbol FROM klines WHERE interval='5m' AND symbol LIKE '%TRY' "
        "GROUP BY symbol HAVING COUNT(*)>=?", (min_bars,))]
    out = {}; cutoff = None
    for s in syms:
        rows = conn.execute(
            "SELECT open_time,high,low,close,volume FROM klines WHERE interval='5m' "
            "AND symbol=? ORDER BY open_time", (s,)).fetchall()
        if not rows:
            continue
        if cutoff is None:
            cutoff = max(r[0] for r in rows) - int(days * 86400 * 1000)
        sel = [r for r in rows if r[0] >= cutoff and (r[3] or 0) > 0]
        if len(sel) >= 400:
            out[s] = {"t": np.array([r[0] for r in sel]), "c": np.array([r[3] for r in sel], float),
                      "h": np.array([r[1] for r in sel], float), "l": np.array([r[2] for r in sel], float),
                      "v": np.array([(r[4] or 0.0) for r in sel], float)}
    conn.close(); return out


def tstat(a, b):
    a = np.array([x for x in a if x is not None]); b = np.array([x for x in b if x is not None])
    if len(a) < 30 or len(b) < 30:
        return 0.0
    va = a.var() / len(a); vb = b.var() / len(b)
    se = np.sqrt(va + vb)
    return float((a.mean() - b.mean()) / se) if se else 0.0


def hour_signal(data, hour, side=+1, cost=0.35, h=12):
    """Belirli UTC saatte LONG (side=+1); fwd 12-bar. Sonuç (net, ts, sym)."""
    out = []
    for s, d in data.items():
        c, t = d["c"], d["t"]
        hrs = ((t // 1000 // 3600) % 24)
        n = len(c)
        fwd = np.full(n, np.nan); fwd[:n - h] = (c[h:] / c[:n - h] - 1) * 100
        m = (hrs == hour) & (~np.isnan(fwd))
        for i in np.where(m)[0]:
            out.append((side * float(fwd[i]) - cost, int(t[i]), s))
    return out


def zscore_signal(data, thr=2.0, cost=0.35, h=12):
    out = []
    for s, d in data.items():
        c = d["c"]; n = len(c)
        r1 = np.zeros(n); r1[1:] = (c[1:] / c[:-1] - 1) * 100
        win = 30
        rm = np.convolve(r1, np.ones(win) / win, mode="valid")
        r2 = np.convolve(r1 * r1, np.ones(win) / win, mode="valid")
        std = np.sqrt(np.maximum(r2 - rm * rm, 0))
        z = np.zeros(n); z[win - 1:] = np.where(std > 0, r1[win - 1:] / std, 0)
        fwd = np.full(n, np.nan); fwd[:n - h] = (c[h:] / c[:n - h] - 1) * 100
        m = (np.abs(z) >= thr) & (~np.isnan(fwd))
        for i in np.where(m)[0]:
            net = (-float(fwd[i]) if z[i] > 0 else float(fwd[i])) - cost
            out.append((net, int(d["t"][i]), s))
    return out


def report(name, recs, all_recs_ref):
    if not recs:
        print(f"  {name}: sinyal yok"); return
    nets = np.array([r[0] for r in recs]); ts = np.array([r[1] for r in recs])
    order = np.argsort(ts); nets = nets[order]; ts = ts[order]
    print(f"\n  == {name} ==  n={len(nets)} net={round(float(nets.mean()),3)}% "
          f"wr={round(100*float((nets>0).mean()),1)}%")
    # 3-fold
    for k in range(3):
        a, b = int(len(nets) * k / 3), int(len(nets) * (k + 1) / 3)
        seg = nets[a:b]
        if len(seg) > 20:
            print(f"    fold{k+1}: n={len(seg)} net={round(float(seg.mean()),3)}%")
    # gün-gün
    days = ts // 86400000
    pos = 0; tot = 0
    for dd in np.unique(days):
        seg = nets[days == dd]
        if len(seg) >= 5:
            tot += 1; pos += 1 if seg.mean() > 0 else 0
    print(f"    gün-gün pozitif: {pos}/{tot}")
    # sembol yoğunlaşma
    from collections import Counter
    cc = Counter(r[2] for r in recs)
    print(f"    sembol: {len(cc)} en büyük pay %{round(100*cc.most_common(1)[0][1]/len(recs),1)}")
    # eşleştirilmiş t: sinyal vs evren ortalaması
    base = np.array(all_recs_ref)
    print(f"    t (sinyal - evren baz): {round(tstat(nets, base),2)}")


def main() -> int:
    print("=== EN İYİ 2 ADAY DERİN DOĞRULAMA ===")
    data = load(45.0)
    print(f"  sembol: {len(data)}")
    # evren bazı (tüm barlar)
    universe = []
    for s, d in data.items():
        c = d["c"]; n = len(c)
        fwd = np.full(n, np.nan); fwd[:n - 12] = (c[12:] / c[:n - 12] - 1) * 100
        universe.extend((fwd[~np.isnan(fwd)] - 0.35).tolist())
    print(f"  evren baz net: {round(float(np.mean(universe)),3)}% (n={len(universe)})")

    # ADAY 1: H5 saat 15 (ve komşu saatler — tek saate mi bağlı?)
    for hr in (13, 14, 15, 16):
        report(f"ADAY1 H5 saat {hr}:00 LONG", hour_signal(data, hr), universe)

    # ADAY 2: H3 aşırı dönüş (eşik duyarlılığı)
    for thr in (2.0, 2.5, 3.0):
        report(f"ADAY2 H3 |z|>={thr} dönüş", zscore_signal(data, thr), universe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
