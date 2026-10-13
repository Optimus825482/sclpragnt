"""DERİN ARAŞTIRMA — 5 YENİ TEST ADAYI (2026-10-13).

12 turda denenen sınıflardan FARKLI, veriyle TEST EDİLEBİLİR yeni adaylar:
  B1 OI DEĞİŞİMİ     : open interest artışı → fiyat yönü (futures metrics, 15dk)
  B2 TOP-TRADER L/S  : büyük trader long/short oranı → ters/momentum
  B3 TAKER BUY/SELL  : agresif alıcı/satıcı oranı → order-flow yönü
  B4 SPOT-FUTURES BASIS : futures premium (fut-spot)/spot → taşıma/dönüş sinyali
  B5 OPSİYON VOL (BVOL): BTC implied vol seviyesi/değişimi → risk iştahı

Veri kaynakları (doğrulandı): futures metrics (OI/LS/taker, 15dk, 600+gün),
spot+futures klines (basis), BVOL index. Yerel önbellek work/dc2_cache/.

YÖNTEM: ham korelasyon + walk-forward EV (taker/maker), gerçek futures 5m klines
ile ileri getiri. KARAR: |corr| ve EV>0 kontrolü.

KULLANIM:
    python backend/scripts/research_new_derived_signals.py --days 30 --symbol BTCUSDT
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
_CACHE = os.path.join(_WORK, "dc2_cache")
_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
_B = "https://data.binance.vision/data"
_TAKER, _MAKER = 0.35, 0.10


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
        time.sleep(0.05)
        return raw
    except Exception:
        return None


def _ziprows(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    return list(csv.reader(io.StringIO(z.read(z.namelist()[0]).decode())))


def _fut_klines(sym: str, days: int) -> dict:
    """{open_ms: close} — futures 5m kapanışları."""
    out = {}
    for back in range(3, 3 + days):
        ymd = (dt.datetime.utcnow() - dt.timedelta(days=back)).strftime("%Y-%m-%d")
        raw = _dl(f"{_B}/futures/um/daily/klines/{sym}/5m/{sym}-5m-{ymd}.zip",
                  os.path.join(_CACHE, f"fut_{sym}_5m_{ymd}.zip"))
        if not raw:
            continue
        for r in _ziprows(raw)[1:]:
            if len(r) > 4:
                try:
                    out[int(r[0])] = float(r[4])
                except (ValueError, IndexError):
                    pass
    return out


def _metrics(sym: str, days: int) -> list[dict]:
    """futures metrics satırları (15dk): OI, LS oranları, taker oranı."""
    out = []
    for back in range(3, 3 + days):
        ymd = (dt.datetime.utcnow() - dt.timedelta(days=back)).strftime("%Y-%m-%d")
        raw = _dl(f"{_B}/futures/um/daily/metrics/{sym}/{sym}-metrics-{ymd}.zip",
                  os.path.join(_CACHE, f"met_{sym}_{ymd}.zip"))
        if not raw:
            continue
        for r in _ziprows(raw)[1:]:
            if len(r) < 8:
                continue
            try:
                t = int(dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
                        .replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
                out.append({"t": t, "oi": float(r[2]), "ls_top": float(r[4]),
                            "ls_acct": float(r[6]), "taker": float(r[7])})
            except (ValueError, IndexError):
                pass
    out.sort(key=lambda x: x["t"])
    return out


def _spot_klines(sym: str, days: int) -> dict:
    out = {}
    for back in range(3, 3 + days):
        ymd = (dt.datetime.utcnow() - dt.timedelta(days=back)).strftime("%Y-%m-%d")
        raw = _dl(f"{_B}/spot/daily/klines/{sym}/5m/{sym}-5m-{ymd}.zip",
                  os.path.join(_CACHE, f"spot_{sym}_5m_{ymd}.zip"))
        if not raw:
            continue
        for r in _ziprows(raw)[1:]:
            if len(r) > 4:
                try:
                    ms = int(r[0])
                    if ms > 1e14:          # SPOT arşivi MİKROSANİYE → ms'e indir
                        ms //= 1000
                    out[ms] = float(r[4])
                except (ValueError, IndexError):
                    pass
    return out


def _corr(xs, ys):
    n = min(len(xs), len(ys))
    if n < 30:
        return 0.0
    xs, ys = xs[:n], ys[:n]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / n
    sd = statistics.pstdev(xs) * statistics.pstdev(ys)
    return round(cov / sd, 3) if sd else 0.0


def _ev(feature_rows, key_fn, fwd_key, thr_hi, sign, cost):
    s = []
    for r in feature_rows:
        if fwd_key not in r:
            continue
        v = key_fn(r)
        if v is None:
            continue
        if (sign > 0 and v >= thr_hi) or (sign < 0 and v <= thr_hi):
            s.append(sign * r[fwd_key] - cost)
    if len(s) < 20:
        return None
    return {"n": len(s), "ev": round(statistics.mean(s), 3),
            "win": round(100 * sum(1 for x in s if x > 0) / len(s), 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--out", default="work/new_derived_signals.json")
    args = ap.parse_args()
    sym = args.symbol
    print(f"=== DERİN ARAŞTIRMA: 5 YENİ ADAY ({sym}, {args.days}g) ===")
    os.makedirs(_CACHE, exist_ok=True)
    fut = _fut_klines(sym, args.days)
    spot = _spot_klines(sym, args.days)
    met = _metrics(sym, args.days)
    print(f"  futures klines: {len(fut)} | spot klines: {len(spot)} | metrics: {len(met)}")
    if len(fut) < 200 or len(met) < 100:
        print("  YETERSİZ VERİ"); return 1

    fkeys = sorted(fut)

    def _fwd(ts_ms, h_bars):
        base = (ts_ms // 300000) * 300000
        import bisect
        i = bisect.bisect_left(fkeys, base)
        if i < 0 or i >= len(fkeys) - h_bars:
            return None
        p0 = fut[fkeys[i]]
        p1 = fut[fkeys[i + h_bars]]
        return (p1 / p0 - 1) * 100 if p0 > 0 else None

    # B1-B3: metrics tabanlı
    rows = []
    for j, m in enumerate(met):
        d_oi = None
        if j > 0 and met[j - 1]["oi"] > 0:
            d_oi = (m["oi"] / met[j - 1]["oi"] - 1) * 100
        r = {"t": m["t"], "d_oi": d_oi, "ls_top": m["ls_top"],
             "ls_acct": m["ls_acct"], "taker": m["taker"]}
        for h, hb in ((15, 3), (30, 6), (60, 12)):
            fw = _fwd(m["t"], hb)
            if fw is not None:
                r[f"fwd{h}"] = fw
        rows.append(r)

    # B4: basis = (fut - spot)/spot
    brows = []
    for ts in fkeys:
        base = (ts // 300000) * 300000
        s = spot.get(base); f = fut.get(base)
        if s and f and s > 0:
            b = (f / s - 1) * 100
            r = {"t": ts, "basis": b}
            for h, hb in ((15, 3), (30, 6)):
                fw = _fwd(ts, hb)
                if fw is not None:
                    r[f"fwd{h}"] = fw
            brows.append(r)

    res = {"symbol": sym, "days": args.days,
           "n_metrics": len(rows), "n_basis": len(brows)}

    # Ön korelasyon + walk-forward EV
    def analyze(name, data, feas, keyfn):
        rr = [r for r in data if all((f in r and r[f] is not None) for f in feas)]
        corr = {}
        for f in feas:
            for k in ("fwd15", "fwd30"):
                sub = [r for r in rr if k in r]
                if len(sub) >= 30:
                    corr[f"{f}_{k}"] = _corr([r[f] for r in sub], [r[k] for r in sub])
        # walk-forward: eğitim eşik (üst/alt %20) → sınav EV
        split = int(len(rr) * 0.6)
        tr, te = rr[:split], rr[split:]
        out = {"corr": corr, "ev": {}}
        for f in feas:
            vs = sorted(r[f] for r in tr if r[f] is not None)
            if not vs:
                continue
            hi = vs[int(len(vs) * 0.8)]; lo = vs[int(len(vs) * 0.2)]
            for k in ("fwd15", "fwd30"):
                for side, thr, sign in (("hi", hi, 1), ("hi_ters", hi, -1),
                                        ("lo", lo, 1), ("lo_ters", lo, -1)):
                    r = _ev(te, lambda x, f=f: x[f], k, thr, sign, _TAKER)
                    if r:
                        out["ev"][f"{f}_{side}_{k}"] = r
        return out

    print("\n  B1-B3 (metrics):")
    a123 = analyze("metrics", rows, ["d_oi", "ls_top", "ls_acct", "taker"], None)
    for k, v in a123["corr"].items():
        print(f"    corr {k}: {v}")
    best = sorted(a123["ev"].items(), key=lambda kv: -kv[1]["ev"])[:6]
    for k, v in best:
        print(f"    EV {k}: {v}")

    print("\n  B4 (basis):")
    a4 = analyze("basis", brows, ["basis"], None)
    for k, v in a4["corr"].items():
        print(f"    corr {k}: {v}")
    for k, v in sorted(a4["ev"].items(), key=lambda kv: -kv[1]["ev"])[:6]:
        print(f"    EV {k}: {v}")

    res["metrics"] = a123
    res["basis"] = a4
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
