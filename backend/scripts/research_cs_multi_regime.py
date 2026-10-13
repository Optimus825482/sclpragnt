"""KESİTSEL MOMENTUM — ÇOK-REJİMLİ DOĞRULAMA (600+ gün, 2026-10-13).

NEDEN: 15. turda 4h kesitsel momentum sepeti İLK anlamlı beta-elimine sinyali verdi
(4h spread brüt +2.52, t=3.23 vs rastgele sepet) AMA 90 günlük veri TEK rejimdi ve
3-fold ortası (momentum crash) negatifti. Kararlılık iddiası için ÇOK-REJİMLİ veri şart.

Bu script: futures MONTHLY klines arşivi (~600+ gün) ile top-N likit USDT perpetual
üzerinde aynı kesitsel momentum testini koşar. Momentum crash'i içerip içermediğini
ve long-only excess'in sürdürülebilirliğini ölçer.

VERİ: data.binance.vision futures/um/monthly/klines. Yerel önbellek work/cs_fut_cache/.
Ölçüm: kesitsel spread (long en güçlü topN − short en zayıf topN), walk-forward çok fold,
long-only excess, maliyet duyarlılığı, sembol evreni.

KULLANIM:
    python backend/scripts/research_cs_multi_regime.py --tf 1d --months 20 --top-syms 60
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import ssl
import statistics
import sys
import time
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_CACHE = os.path.join(_WORK, "cs_fut_cache")
_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
_BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
_TAKER = 0.35


def _dl(url, path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
            raw = r.read()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(raw)
        time.sleep(0.04)
        return raw
    except Exception:
        return None


def _top_symbols(n: int) -> list[str]:
    """Hacme göre top-N USDT perpetual (ticker/24hr)."""
    try:
        req = urllib.request.Request("https://fapi.binance.com/fapi/v1/ticker/24hr",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25, context=_CTX) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return []
    rows = [(d["symbol"], float(d.get("quoteVolume") or 0)) for d in data
            if d["symbol"].endswith("USDT")]
    rows.sort(key=lambda x: -x[1])
    out = []
    for s, v in rows[:n * 3]:
        if v <= 0:
            continue
        out.append(s)
        if len(out) >= n:
            break
    return out


def _load_monthly(sym: str, tf: str, months: int) -> list[tuple[int, float]]:
    """Son `months` aylık (open_ms, close) — artan."""
    out = []
    now = dt.datetime.utcnow()
    for k in range(months):
        d = (now - dt.timedelta(days=30 * k))
        ym = d.strftime("%Y-%m")
        raw = _dl(f"{_BASE}/{sym}/{tf}/{sym}-{tf}-{ym}.zip",
                  os.path.join(_CACHE, f"{sym}-{tf}-{ym}.zip"))
        if not raw:
            continue
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
            rows = list(csv.reader(io.StringIO(z.read(z.namelist()[0]).decode())))
        except Exception:
            continue
        for r in rows[1:]:
            if len(r) > 4:
                try:
                    out.append((int(r[0]), float(r[4])))
                except (ValueError, IndexError):
                    pass
    out.sort()
    return out


def _cross_sectional(series: dict, lookback: int, hold: int, topn: int):
    """Kesitsel momentum: her zaman noktasında long/short sepet. spread+excess döner."""
    by_t: dict = {}
    for sym, s in series.items():
        for ot, c in s:
            by_t.setdefault(ot, {})[sym] = c
    times = sorted(by_t)
    idx = {sym: {ot: i for i, (ot, _) in enumerate(s)} for sym, s in series.items()}
    rows = []
    for j in range(lookback, len(times) - hold):
        t = times[j]; t0 = times[j - lookback]; t1 = times[j + hold]
        mom = {}
        for sym, s in series.items():
            im = idx[sym]
            if t in im and t0 in im and s[im[t0]][1] > 0:
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
            ml, ms, ma = statistics.mean(lf), statistics.mean(sf), statistics.mean(af)
            rows.append({"t": t, "spread": ml - ms, "long_exc": ml - ma, "short_exc": ma - ms})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1d")
    ap.add_argument("--months", type=int, default=20)
    ap.add_argument("--top-syms", type=int, default=60)
    ap.add_argument("--lookback", type=int, default=12)
    ap.add_argument("--hold", type=int, default=6)
    ap.add_argument("--topn", type=int, default=5)
    ap.add_argument("--out", default="work/cs_multi_regime.json")
    args = ap.parse_args()
    print(f"=== KESİTSEL MOMENTUM ÇOK-REJİM ({args.tf}, {args.months} ay, {args.top_syms} sembol) ===")
    os.makedirs(_CACHE, exist_ok=True)
    syms = _top_symbols(args.top_syms)
    print(f"  sembol: {len(syms)}")
    series = {}
    for s in syms:
        rows = _load_monthly(s, args.tf, args.months)
        if len(rows) >= args.lookback + args.hold + 10:
            series[s] = rows
    print(f"  yeterli veri: {len(series)} sembol")
    if len(series) < 10:
        print("  YETERSİZ"); return 1

    rows = _cross_sectional(series, args.lookback, args.hold, args.topn)
    print(f"  kesitsel nokta: {len(rows)}")
    if len(rows) < 50:
        print("  YETERSİZ NOKTA"); return 1
    rows.sort(key=lambda r: r["t"])
    c2 = 2 * _TAKER
    sp = [r["spread"] - c2 for r in rows]
    lx = [r["long_exc"] - _TAKER for r in rows]
    print(f"\n  SPREAD (2 bacak, net): EV {round(statistics.mean(sp),3)} win {round(100*sum(1 for x in sp if x>0)/len(sp),1)} n {len(sp)}")
    print(f"  LONG-only excess (net): EV {round(statistics.mean(lx),3)} win {round(100*sum(1 for x in lx if x>0)/len(lx),1)}")

    # 4 fold (çok rejim)
    print("\n  == 4-FOLD (çok-rejim) ==")
    folds = []
    for k in range(4):
        seg = rows[int(len(rows) * k / 4):int(len(rows) * (k + 1) / 4)]
        if not seg:
            continue
        d0 = dt.datetime.utcfromtimestamp(seg[0]["t"] / 1000).date()
        d1 = dt.datetime.utcfromtimestamp(seg[-1]["t"] / 1000).date()
        ev = round(statistics.mean([r["spread"] - c2 for r in seg]), 3)
        lev = round(statistics.mean([r["long_exc"] - _TAKER for r in seg]), 3)
        folds.append(ev)
        print(f"     fold{k+1} ({d0}..{d1}): spread {ev} | long_exc {lev}")

    # aylık spread (rejim görünümü)
    bym = {}
    for r in rows:
        m = dt.datetime.utcfromtimestamp(r["t"] / 1000).strftime("%Y-%m")
        bym.setdefault(m, []).append(r["spread"] - c2)
    print("\n  == AYLIK SPREAD (net) ==")
    for m in sorted(bym):
        print(f"     {m}: {round(statistics.mean(bym[m]),2)} (n{len(bym[m])})")

    # maliyet duyarlılığı
    print("\n  == MALİYET (spread) ==")
    for c in (0.0, 0.10, 0.20, 0.35):
        print(f"     2 bacak {2*c}: EV {round(statistics.mean([r['spread']-2*c for r in rows]),3)}")

    pos_folds = sum(1 for f in folds if f > 0)
    verdict = ("KARARLI" if pos_folds == len(folds) and statistics.mean(sp) > 0
               else "KISMEN/ANLAMLI AMA TUM FOLDLAR POZITIF DEGIL" if statistics.mean(sp) > 0
               else "NEGATIF")
    print(f"\n  KARAR: {verdict} | pozitif fold {pos_folds}/{len(folds)}")
    res = {"tf": args.tf, "months": args.months, "symbols": len(series), "points": len(rows),
           "spread_net": round(statistics.mean(sp), 3), "long_exc_net": round(statistics.mean(lx), 3),
           "folds": folds, "positive_folds": pos_folds, "verdict": verdict,
           "monthly": {m: round(statistics.mean(v), 2) for m, v in sorted(bym.items())}}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
