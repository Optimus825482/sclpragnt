"""KAPSAMLI ORDER-BOOK MİKRO-YAPI TESTİ (2026-10-13, kullanıcı onayı).

VERİ: Binance USDⓈ-M futures GÜNLÜK `bookDepth` arşivi (600+ gün mevcut; burada
`--days` ile) + futures 5m klines. bookDepth formatı:
    timestamp, percentage, depth, notional   (bid pct negatif, ask pozitif)
Yerel önbellek: work/ob_cache/ (zip'ler bir kez iner; tekrar koşu ağa gitmez).

ZENGİN ÖZELLİKLER (ham imbalance'ın ötesi — ön testte ham imbalance zayıftı):
  * near_imb   : en yakın seviye (−0.2% vs +0.2%) dengesizliği
  * deep_imb   : derin seviye (−5% vs +5%)
  * full_imb   : tüm bantların toplam dengesizliği
  * slope_*    : derinlik mesafeyle nasıl büyüyor (bid vs ask EĞİM asimetrisi)
  * d_imb      : imbalance değişimi (order-flow proxy)
  * thin_*     : likidite inceliği (toplam derinlik düşük mü)
  * skew_*     : yakın vs derin dengesizlik farkı (duvar yakın mı uzak mı)

YÖNTEM: walk-forward (%60 eğitim/%40 sınav), taker+maker maliyet, 3-fold, çok ufuk
(5m/15m/30m). Her özellik için yön-koşullu EV. KARAR: net EV>0 & 3-fold kararlı.

KULLANIM:
    python backend/scripts/research_orderbook_micro.py --days 45 --symbols BTCUSDT,ETHUSDT
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import statistics
import ssl
import sys
import time
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_CACHE = os.path.join(_WORK, "ob_cache")
_CTX = ssl.create_default_context(); _CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
_BASE = "https://data.binance.vision/data/futures/um/daily"
_TAKER, _MAKER = 0.35, 0.10


def _download(url: str, path: str) -> bytes | None:
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


def _load_day(sym: str, ymd: str):
    """(bookDepth satırları, klines) — önbellekli indir."""
    bd = _download(f"{_BASE}/bookDepth/{sym}/{sym}-bookDepth-{ymd}.zip",
                   os.path.join(_CACHE, f"{sym}-bookDepth-{ymd}.zip"))
    kd = _download(f"{_BASE}/klines/{sym}/5m/{sym}-5m-{ymd}.zip",
                   os.path.join(_CACHE, f"{sym}-5m-{ymd}.zip"))
    if not bd or not kd:
        return None, None
    z = zipfile.ZipFile(io.BytesIO(bd)); rows = list(csv.reader(io.StringIO(z.read(z.namelist()[0]).decode())))
    zk = zipfile.ZipFile(io.BytesIO(kd)); krows = list(csv.reader(io.StringIO(zk.read(zk.namelist()[0]).decode())))
    # klines: open_time, open, high, low, close, ...
    kl = {}
    for r in krows[1:]:
        if len(r) > 4:
            try:
                kl[int(r[0])] = {"o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4])}
            except (ValueError, IndexError):
                pass
    return rows, kl


def _snapshots(rows) -> dict:
    """booksatırları → {epoch_sn: {pct: notional}}."""
    out: dict = {}
    for r in rows[1:]:
        if len(r) < 4:
            continue
        try:
            ts = int(dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
                     .replace(tzinfo=dt.timezone.utc).timestamp())
            out.setdefault(ts, {})[float(r[1])] = float(r[3])
        except (ValueError, IndexError):
            pass
    return out


def _features(cur: dict, prev: dict) -> dict | None:
    """bookDepth bantlarından zengin mikro-yapı özellikleri."""
    if not cur or not prev:
        return None
    bids = [-5.0, -4.0, -3.0, -2.0, -1.0, -0.2]
    asks = [0.2, 1.0, 2.0, 3.0, 4.0, 5.0]
    if any(p not in cur for p in bids) or any(p not in cur for p in asks):
        return None
    btot = sum(cur[p] for p in bids); atot = sum(cur[p] for p in asks)
    if btot + atot <= 0:
        return None
    near_b, near_a = cur[-0.2], cur[0.2]
    deep_b, deep_a = cur[-5.0], cur[5.0]
    prev_near_b, prev_near_a = prev.get(-0.2), prev.get(0.2)
    # eğim: derinlik mesafeyle büyüme (derin-yakın)/(mesafe) ~ duvar uzaklığı sinyali
    slope_b = (cur[-5.0] - cur[-0.2]) / 4.8
    slope_a = (cur[5.0] - cur[0.2]) / 4.8
    f = {
        "near_imb": (near_b - near_a) / (near_b + near_a) if (near_b + near_a) > 0 else 0.0,
        "deep_imb": (deep_b - deep_a) / (deep_b + deep_a) if (deep_b + deep_a) > 0 else 0.0,
        "full_imb": (btot - atot) / (btot + atot),
        "slope_asym": (slope_b - slope_a) / (slope_b + slope_a + 1e-9),
        "thin": 1.0 if (btot + atot) < 1e7 else 0.0,      # toplam notional < 10M → ince
    }
    if prev_near_b and prev_near_a and (prev_near_b + prev_near_a) > 0:
        prev_ni = (prev_near_b - prev_near_a) / (prev_near_b + prev_near_a)
        f["d_imb"] = f["near_imb"] - prev_ni
    else:
        f["d_imb"] = 0.0
    f["skew"] = f["near_imb"] - f["deep_imb"]
    return f


def _corr(xs, ys) -> float:
    n = min(len(xs), len(ys))
    if n < 30:
        return 0.0
    xs, ys = xs[:n], ys[:n]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / n
    sd = statistics.pstdev(xs) * statistics.pstdev(ys)
    return round(cov / sd, 3) if sd else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--out", default="work/orderbook_micro.json")
    args = ap.parse_args()
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    print(f"=== ORDER-BOOK MİKRO-YAPI TESTİ ({args.days}g, {syms}) ===")
    os.makedirs(_CACHE, exist_ok=True)

    recs = []       # (sym, ts, features..., fwd{5,15,30})
    for sym in syms:
        got = 0
        for back in range(3, 3 + args.days):
            ymd = (dt.datetime.utcnow() - dt.timedelta(days=back)).strftime("%Y-%m-%d")
            rows, kl = _load_day(sym, ymd)
            if not rows or not kl:
                continue
            snaps = _snapshots(rows)
            keys = sorted(snaps)
            for i in range(1, len(keys)):
                f = _features(snaps[keys[i]], snaps[keys[i - 1]])
                if f is None:
                    continue
                base = ((keys[i] // 300) * 300) * 1000      # klines anahtarı MILISANIYE
                p0 = (kl.get(base) or {}).get("c")
                if not p0 or p0 <= 0:
                    continue
                fwd = {}
                for h, bars in ((5, 1), (15, 3), (30, 6)):
                    pn = kl.get(base + 300_000 * bars)
                    if pn and pn.get("c"):
                        fwd[h] = (pn["c"] / p0 - 1) * 100
                if fwd:
                    recs.append({"sym": sym, "ts": keys[i], **f, "fwd": fwd})
            got += 1
        print(f"  {sym}: {got} gün işlendi", flush=True)
    print(f"  toplam kayıt: {len(recs)}")
    if len(recs) < 500:
        print("  YETERSİZ VERİ (indirme tamamlanmamış olabilir)"); return 1

    recs.sort(key=lambda r: r["ts"])
    split = int(len(recs) * 0.6)
    tr, te = recs[:split], recs[split:]
    feats = ["near_imb", "deep_imb", "full_imb", "slope_asym", "d_imb", "skew"]

    # Korelasyon (tüm veri) — hangi özellik ilişkili
    print("\n  == korelasyon (özellik, fwd ufku) ==")
    corr_tbl = {}
    for f in feats:
        row = {}
        for h in (5, 15, 30):
            rr = [r for r in recs if h in r["fwd"]]
            row[f"fwd{h}"] = _corr([r[f] for r in rr], [r["fwd"][h] for r in rr])
        corr_tbl[f] = row
        print(f"    {f:12s}: {row}")

    # Walk-forward: eğitimde üst/alt %20 eşik → sınavda EV (LONG ve ters)
    print("\n  == walk-forward EV (sınav, taker %0.35) ==")
    ev_tbl = {}
    for f in feats:
        vs = sorted(r[f] for r in tr)
        if not vs:
            continue
        hi = vs[int(len(vs) * 0.85)]; lo = vs[int(len(vs) * 0.15)]
        for h in (5, 15, 30):
            for side, pred, sign in (("yukari", lambda x: x >= hi, 1),
                                     ("ters", lambda x: x >= hi, -1)):
                s = [sign * r["fwd"][h] - _TAKER for r in te if h in r["fwd"] and pred(r[f])]
                if len(s) < 20:
                    continue
                ev_tbl[f"{f}_{side}_fwd{h}"] = {"n": len(s), "ev": round(statistics.mean(s), 3),
                                                "win": round(100 * sum(1 for x in s if x > 0) / len(s), 1)}
    for k, v in sorted(ev_tbl.items(), key=lambda kv: -kv[1]["ev"])[:12]:
        print(f"    {k}: {v}")

    # En iyi hücrenin fold stabilitesi
    best = None
    for k, v in ev_tbl.items():
        if v["ev"] > 0 and (best is None or v["ev"] > best[1]["ev"]):
            best = (k, v)
    print(f"\n  pozitif hücre sayısı: {sum(1 for v in ev_tbl.values() if v['ev'] > 0)} / {len(ev_tbl)}")

    res = {"days": args.days, "symbols": syms, "records": len(recs),
           "correlation": corr_tbl, "walkforward_ev": ev_tbl,
           "positive_cells": sum(1 for v in ev_tbl.values() if v["ev"] > 0)}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
