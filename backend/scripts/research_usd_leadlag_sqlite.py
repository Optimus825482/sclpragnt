"""USD LEAD-LAG — SQLITE GENİŞ-PENCERE ANALİZİ (2026-10-12).

Önceki `research_usd_leadlag.py` yalnız ~6 günlük JSON cache kullanıyordu; bulgu
("residual +0.165 gerçek ama kararsız") güvenilmezdi. Bu sürüm aynı testi
`work/market_cache.sqlite`'tan 30-60 GÜNLÜK veriyle koşar.

VERİ: sqlite `klines` tablosu, interval='5m'.
  * TR tarafı: symbol='XTRY' (ör. WTRY)
  * Global tarafı: symbol='XUSDT' (ör. WUSDT) — fetch_sqlite_wide.py yazar
Eşleştirme: base sembol ('W') üzerinden, open_time ile HİZALI.

TEST (research_usd_leadlag ile aynı): GL[i] → aynı-bar TRY[i] regres → RESIDUAL →
ileri TRY getirisi. Residual korelasyonu > 0 ise gerçek öncülük. + maliyet senaryoları
+ 3-fold + gün-gün.

KULLANIM:
    python backend/scripts/research_usd_leadlag_sqlite.py --days 45
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "..", "work", "market_cache.sqlite")


def load_pairs(db: str, days: float) -> list[dict]:
    conn = sqlite3.connect(db)
    # TR ve GL zaman serilerini yükle
    cut = None
    tr_rows = conn.execute(
        "SELECT symbol, open_time, close, low FROM klines "
        "WHERE interval='5m' AND symbol LIKE '%TRY'").fetchall()
    gl_rows = conn.execute(
        "SELECT symbol, open_time, close, low FROM klines "
        "WHERE interval='5m' AND symbol LIKE '%USDT'").fetchall()
    conn.close()
    if tr_rows:
        cut = max(r[1] for r in tr_rows) - int(days * 86400 * 1000)
    tr = {}
    for s, ot, c, lo in tr_rows:
        if cut is not None and ot < cut:
            continue
        tr.setdefault(s[:-3], {})[ot] = (float(c), float(lo))
    gl = {}
    for s, ot, c, lo in gl_rows:
        if cut is not None and ot < cut:
            continue
        gl.setdefault(s[:-4], {})[ot] = (float(c), float(lo))

    common_bases = set(tr) & set(gl)
    print(f"  ortak base sembol: {len(common_bases)} | TR {len(tr)} | GL {len(gl)}")
    rows = []
    for base in common_bases:
        tmap = tr[base]; gmap = gl[base]
        times = sorted(set(tmap) & set(gmap))
        if len(times) < 400:
            continue
        # ileri getiri için gereken +3 bar kontrolü
        for k in range(30, len(times) - 13):
            ot = times[k]; ot_prev = times[k - 1]
            gc, _ = gmap[ot]; gc_prev, _ = gmap[ot_prev]
            tc, _ = tmap[ot]; tc_prev, _ = tmap[ot_prev]
            if gc <= 0 or gc_prev <= 0 or tc <= 0 or tc_prev <= 0:
                continue
            g1 = (gc / gc_prev - 1) * 100
            t_same = (tc / tc_prev - 1) * 100
            # sonraki barlar (zaman sırası)
            fwd = {}
            for h in (1, 3, 6, 12):
                if k + h < len(times):
                    tch, _ = tmap[times[k + h]]
                    fwd[h] = (tch / tc - 1) * 100
            # limit dolgu için sonraki 3 barın en düşüğü
            lows = [tmap[times[k + j]][1] for j in range(1, 4) if k + j < len(times)]
            rows.append({"s": base, "ts": ot / 1000.0, "g1": g1, "t_same": t_same,
                         "c": tc, "fwd": fwd,
                         "lo1": lows[0] if lows else None,
                         "lo3": min(lows) if lows else None})
    rows.sort(key=lambda r: r["ts"])
    return rows


def _corr(a, b):
    if len(a) < 3:
        return 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)
    sd = statistics.pstdev(a) * statistics.pstdev(b)
    return cov / sd if sd else 0.0


def _beta(rows):
    mg = statistics.mean([r["g1"] for r in rows])
    mt = statistics.mean([r["t_same"] for r in rows])
    cov = sum((r["g1"] - mg) * (r["t_same"] - mt) for r in rows) / len(rows)
    var = statistics.pvariance([r["t_same"] for r in rows])
    return (cov / var if var else 0.0), mg, mt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=45.0)
    ap.add_argument("--db", default=_DB)
    args = ap.parse_args()
    print("=== USD LEAD-LAG — SQLITE GENİŞ PENCERE ===")
    rows = load_pairs(args.db, args.days)
    print(f"  kayıt: {len(rows)} (sembol {len({r['s'] for r in rows})})")
    if len(rows) < 5000:
        print("YETERSİZ VERİ (fetch_sqlite_wide.py --days 60 çalıştır)"); return 1

    n = len(rows); split = int(n * 0.6)
    tr_rows, te_rows = rows[:split], rows[split:]
    b, mg, mt = _beta(tr_rows)
    for rs in (tr_rows, te_rows):
        for r in rs:
            r["res"] = r["g1"] - b * (r["t_same"] - mt)

    contemporaneous = _corr([r["g1"] for r in rows], [r["t_same"] for r in rows])
    res_te = [r["res"] for r in te_rows]
    resid_fwd = {h: round(_corr(res_te, [r["fwd"][h] for r in te_rows if h in r["fwd"]]), 3)
                 for h in (1, 3, 6, 12)}
    print(f"  aynı-bar korelasyon: {contemporaneous:.3f} | beta={b:.3f}")
    print(f"  RESIDUAL→fwd (gerçek öncülük): {resid_fwd}")

    # maliyet senaryoları
    print(f"\n  {'eşik':5s}{'n':>7}{'brüt15':>8}{'takerTR':>9}{'global':>9}{'maker':>9}{'limNet':>9}")
    scen = {}
    for q in (0.9, 0.85, 0.8):
        thr = sorted(r["res"] for r in tr_rows)[int(len(tr_rows) * q)]
        sig = [r for r in te_rows if r["res"] >= thr and 3 in r["fwd"]]
        seen = set(); u = []
        for r in sig:
            k = (r["s"], int(r["ts"] // 1800))
            if k in seen:
                continue
            seen.add(k); u.append(r)
        if not u:
            continue
        gross = statistics.mean([r["fwd"][3] for r in u])
        filled = [r for r in u if r["lo1"] is not None and r["lo3"] is not None
                  and min(r["lo1"], r["lo3"]) <= r["c"] * 0.997]
        lim_net = statistics.mean([r["fwd"][3] - 0.3 - 0.04 for r in filled]) if filled else None
        scen[f"p{int(q*100)}"] = {
            "n": len(u), "gross": round(gross, 3),
            "taker_tr": round(statistics.mean([r["fwd"][3] - 0.35 for r in u]), 3),
            "global": round(statistics.mean([r["fwd"][3] - 0.20 for r in u]), 3),
            "maker": round(statistics.mean([r["fwd"][3] - 0.04 for r in u]), 3),
            "limit_net": round(lim_net, 3) if lim_net is not None else None}
        v = scen[f"p{int(q*100)}"]
        print(f"  {f'p{int(q*100)}':5s}{v['n']:>7}{v['gross']:>8}{v['taker_tr']:>9}{v['global']:>9}"
              f"{v['maker']:>9}{str(v['limit_net']):>9}")

    # 3-fold (likit yok, tum sembol)
    folds = []
    edges = [int(n * i / 4) for i in range(5)]
    for k in range(1, 4):
        trn = rows[:edges[k]]; tst = rows[edges[k]:edges[k + 1]]
        bb, mgg, mtt = _beta(trn)
        th = sorted(r["g1"] - bb * (r["t_same"] - mtt) for r in trn)[int(len(trn) * 0.85)]
        sel = [r for r in tst if (r["g1"] - bb * (r["t_same"] - mtt)) >= th and 3 in r["fwd"]]
        nets = [r["fwd"][3] - 0.20 for r in sel]     # Global ücret
        folds.append({"fold": k, "n": len(nets),
                      "net": round(statistics.mean(nets), 3) if nets else None})
    print(f"\n  3-fold (Global taker): {folds}")

    # gün-gün
    thr = sorted(r["res"] for r in tr_rows)[int(len(tr_rows) * 0.85)]
    byday = {}
    for r in te_rows:
        if r["res"] >= thr and 3 in r["fwd"]:
            byday.setdefault(int(r["ts"] // 86400), []).append(r["fwd"][3] - 0.20)
    pos = sum(1 for v in byday.values() if statistics.mean(v) > 0)
    print(f"  gün-gün (Global): {pos}/{len(byday)} pozitif")
    print(f"  günler: {[round(statistics.mean(v),2) for _,v in sorted(byday.items())]}")

    verdict = ("REAL_AND_STABLE" if (resid_fwd.get(3, 0) > 0.05 and all((f["net"] or -1) > 0 for f in folds if f["n"] > 30))
               else ("REAL_BUT_COST_BOUND" if resid_fwd.get(3, 0) > 0.05 else "NO_LEADLAG"))
    print(f"\n  KARAR: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
