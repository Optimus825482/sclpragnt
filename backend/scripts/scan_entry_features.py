"""BAĞIMSIZ ÖNGÖRÜCÜ TARAMASI (2026-10-12).

NEDEN: Çıkış kalibrasyonu (SL 3.0→1.0) kaybı azalttı ama portföy pozitife
dönmedi; giriş filtresi taraması da `velocity_score`'un (ve skor/rank/ATR/ML)
edge taşımadığını — hatta tersine çalıştığını — gösterdi (`NO_ENTRY_EDGE`).
Kalan soru: FİYAT/MUM verisinden türetilebilen BAŞKA bir öngörücü edge verir mi?

YÖNTEM: Her aday sinyali için, YALNIZ sinyal anından ÖNCEKİ kapanmış barlardan
hesaplanan feature'lar çıkarılır (look-ahead YOK):
  * Öncü momentum: r1/r3/r6/r12 (son 5/15/30/60 dk getiri)
  * Hacim patlaması: vol_r (son bar hacmi / son 20 bar ort.)
  * Volatilite: rng (son bar aralığı), atr14
  * KONUM (kritik hipotez): hi24 / lo24 / pos24 — fiyat 24s zirve-dip bandının
    neresinde? "Hareket zaten olmuş, zirveye geç giriyoruz" iddiasını ölçer.
  * Konum teyidi: green_run (ardışık yeşil bar), saat (UTC)
Sonra her feature için: medyan/percentil eşiği EĞİTİM kümesinde seçilir, SINAV
kümesinde EV + eşleştirilmiş t-testi ölçülür (walk-forward). Çıkış sabit: SL=1.0.

ÇIKTI: hangi feature'lar (varsa) sınavda pozitif ve ANLAMLI EV verir → uygulanabilir
giriş filtresi adayı. Yoksa: "sinyal uzayında edge yok" bulgusu kayıt altına alınır.

KULLANIM:
    python backend/scripts/scan_entry_features.py --hours 3600
    python backend/scripts/scan_entry_features.py --hours 3600 --fetch
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import os
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app.paper_sim import simulate_exit, tp_pct_for  # noqa: E402

# 2026-10-15 (denetim düzeltmesi): sabit DB kimlik bilgisi kaldırıldı; DATABASE_URL zorunlu.
# Import anında değil, bağlantı anında kontrol edilir (testler modülü DB'siz import eder).
def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        sys.exit("HATA: DATABASE_URL ortam değişkeni tanımlı değil "
                 "(örn. postgresql://kullanici:sifre@host:5432/scalper)")
    return url
_SQLITE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "..", "work", "market_cache.sqlite")
_BAR_SEC = 300.0
_BARS_24H = int(24 * 3600 / _BAR_SEC)   # 288


# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------
def _load_candidates(hours: float) -> list[dict]:
    import psycopg
    since = time.time() - hours * 3600.0
    out = []
    with psycopg.connect(_db_url(), connect_timeout=8) as conn:
        for ts, sym, px, tgt in conn.execute(
            "SELECT created_at, symbol, price, target_pct FROM velocity_candidates "
            "WHERE passes=true AND created_at >= %s AND price > 0 ORDER BY created_at",
            (since,)):
            try:
                out.append({"ts": float(ts), "symbol": str(sym).upper(),
                            "price": float(px), "target_pct": float(tgt or 3.0)})
            except (TypeError, ValueError):
                continue
    return out


def _bars_from_sqlite(symbols: set[str]) -> dict:
    """Yerel sqlite'tan 5m mumlar (hacim dahil) → {symbol: {"t":[],"h":[],"l":[],"c":[],"v":[]}}."""
    out: dict = {}
    if not os.path.exists(_SQLITE):
        return out
    c = sqlite3.connect(_SQLITE)
    try:
        for sym, ot, h, lo, cl, vol in c.execute(
            "SELECT symbol, open_time, high, low, close, volume FROM klines "
            "WHERE interval='5m' ORDER BY symbol, open_time"):
            s = str(sym).upper()
            if s not in symbols:
                continue
            d = out.setdefault(s, {"t": [], "h": [], "l": [], "c": [], "v": []})
            d["t"].append(float(ot) / 1000.0); d["h"].append(float(h))
            d["l"].append(float(lo)); d["c"].append(float(cl)); d["v"].append(float(vol or 0))
    finally:
        c.close()
    return out


async def _fetch_and_cache(symbols: set[str], have: set[str], days: int) -> dict:
    """Eksik sembolleri Binance TR'den çek + sqlite'a YAZ (kalıcı önbellek)."""
    from app.binance_tr_public import historical_klines
    out: dict = {}
    missing = sorted(symbols - have)
    print(f"  REST'ten çekilecek: {len(missing)} sembol")
    rows_to_write = []
    for i, sym in enumerate(missing):
        try:
            rows = await historical_klines(sym, "5m", days)
        except Exception as exc:
            print(f"    {sym}: {type(exc).__name__}"); continue
        d = {"t": [], "h": [], "l": [], "c": [], "v": []}
        for r in rows or []:
            ot, _o, h, lo, cl, vol = r[0], r[1], r[2], r[3], r[4], r[5]
            d["t"].append(float(ot) / 1000.0); d["h"].append(float(h))
            d["l"].append(float(lo)); d["c"].append(float(cl)); d["v"].append(float(vol or 0))
            rows_to_write.append((sym, "5m", int(ot), float(_o), float(h), float(lo), float(cl), float(vol or 0)))
        if d["t"]:
            out[sym] = d
        if (i + 1) % 20 == 0:
            print(f"    ... {i + 1}/{len(missing)}")
            await asyncio.sleep(0.2)
    if rows_to_write and os.path.exists(_SQLITE):
        try:
            c = sqlite3.connect(_SQLITE)
            c.executemany("INSERT OR REPLACE INTO klines"
                          "(symbol, interval, open_time, open, high, low, close, volume) "
                          "VALUES(?,?,?,?,?,?,?,?)", rows_to_write)
            c.commit(); c.close()
            print(f"  sqlite'a yazıldı: {len(rows_to_write)} bar")
        except Exception as exc:
            print(f"  sqlite yazma atlandı: {exc}")
    return out


# ---------------------------------------------------------------------------
# Feature'lar (sadece GEÇMİŞ barlardan — look-ahead yok)
# ---------------------------------------------------------------------------
def _features(bars: dict, ts: float) -> dict | None:
    """`ts` anında bilinebilen feature'lar — SADECE kapanmış barlardan.

    LOOK-AHEAD KORUMASI (2026-10-12 düzeltmesi): bir bar `open_time` anında açılır
    ve `open_time+300`'de KAPANIR. `ts` anında yalnız kapanışı `ts`'ten ÖNCE olan
    barlar bilinir → indeks `bisect_right(t, ts - bar_sec) - 1`. Eski sürüm
    `bisect_left(t, ts)-1` kullanıyordu ve ts'te hâlâ AÇIK olan barın (kapanışı
    gelecekte) high/low/close'unu okuyordu → yapay yüksek t'li yanlış "edge".
    """
    t = bars["t"]
    idx = bisect.bisect_right(t, ts - _BAR_SEC) - 1   # kapanışı ts'ten önce olan son bar
    if idx < 30:
        return None
    c = bars["c"]; h = bars["h"]; l = bars["l"]; v = bars["v"]

    def ret(k):
        if idx - k < 0 or c[idx - k] <= 0:
            return 0.0
        return (c[idx] / c[idx - k] - 1) * 100.0

    win = slice(max(0, idx - 19), idx + 1)
    vwin = v[win]
    avg_v = statistics.mean(vwin) if vwin else 0.0
    vol_r = (v[idx] / avg_v) if avg_v > 0 else 0.0
    rng = ((h[idx] - l[idx]) / c[idx] * 100) if c[idx] > 0 else 0.0
    aw = slice(max(0, idx - 13), idx + 1)
    atr14 = statistics.mean([(h[i] - l[i]) / c[i] * 100 for i in range(aw.start, aw.stop) if c[i] > 0]) \
        if idx >= 13 else rng
    w24 = slice(max(0, idx - _BARS_24H + 1), idx + 1)
    hi24 = max(h[w24]); lo24 = min(l[w24])
    hi24d = (c[idx] - hi24) / c[idx] * 100 if c[idx] > 0 else 0.0     # <=0, 0'a yakın=zirvede
    lo24d = (c[idx] - lo24) / c[idx] * 100 if c[idx] > 0 else 0.0     # >=0
    span = hi24 - lo24
    pos24 = ((c[idx] - lo24) / span) if span > 0 else 0.5
    gr = 0
    i = idx
    while i > 0 and c[i] >= c[i - 1]:
        gr += 1; i -= 1
    hour = int((ts % 86400) // 3600)
    return {"r1": ret(1), "r3": ret(3), "r6": ret(6), "r12": ret(12),
            "vol_r": vol_r, "rng": rng, "atr14": atr14,
            "hi24d": hi24d, "lo24d": lo24d, "pos24": pos24,
            "green_run": float(gr), "hour": float(hour)}


def _sim(cd: dict, bars: dict, *, commission_pct: float, slippage_pct: float):
    t = bars["t"]
    lo = bisect.bisect_left(t, cd["ts"])
    win = []
    for i in range(lo, len(t)):
        if t[i] > cd["ts"] + 125 * 60:
            break
        win.append({"open_time": t[i], "high": bars["h"][i],
                    "low": bars["l"][i], "close": bars["c"][i]})
    if not win:
        return None
    o = simulate_exit(win, cd["price"], entry_time=cd["ts"],
                      tp_pct=tp_pct_for(cd["target_pct"], 3.0), sl_pct=1.0,
                      trail_trigger_pct=2.0, trail_gap_pct=1.0, no_profit_min=30,
                      max_hold_min=120, commission_pct=commission_pct,
                      slippage_pct=slippage_pct, bar_seconds=_BAR_SEC)
    return o.get("sim_pct")


# ---------------------------------------------------------------------------
# Analiz
# ---------------------------------------------------------------------------
def _ev(nets: list[float]) -> dict:
    nets = [n for n in nets if n is not None]
    if not nets:
        return {"n": 0, "ev": None}
    w = [x for x in nets if x > 0]
    l = [x for x in nets if x <= 0]
    aw = statistics.mean(w) if w else 0.0
    al = statistics.mean(l) if l else 0.0
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "wr": round(100 * len(w) / len(nets), 1),
            "pf": round(aw / abs(al), 2) if al else None}


def _pctile(vals, p):
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * p))] if s else 0.0


def _paired(sel: list[float], rest: list[float]) -> float:
    import math
    sel = [x for x in sel if x is not None]; rest = [x for x in rest if x is not None]
    if not sel or not rest:
        return 0.0
    ms, mr = statistics.mean(sel), statistics.mean(rest)
    sd = statistics.pstdev(sel + rest)
    se = sd * math.sqrt(1 / len(sel) + 1 / len(rest))
    return (ms - mr) / se if se else 0.0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=3600.0)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--commission", type=float, default=0.0015)
    ap.add_argument("--slippage", type=float, default=0.00025)
    ap.add_argument("--out", default="work/entry_feature_scan.json")
    args = ap.parse_args()

    print("=== BAĞIMSIZ ÖNGÖRÜCÜ TARAMASI ===")
    cands = _load_candidates(args.hours)
    print(f"aday: {len(cands)}")
    if len(cands) < 200:
        print("YETERSİZ VERİ"); return 1

    symbols = {c["symbol"] for c in cands}
    bars = _bars_from_sqlite(symbols)
    have = {s for s, b in bars.items() if b["t"]}
    print(f"sqlite kapsamı: {len(have)}/{len(symbols)}")
    if args.fetch:
        rest = await _fetch_and_cache(symbols, have, max(2, int(_span_days(cands)) + 2))
        bars.update(rest)

    # Feature + sonuç çiftleri
    recs = []
    for cd in cands:
        b = bars.get(cd["symbol"])
        if not b or not b["t"]:
            continue
        f = _features(b, cd["ts"])
        if f is None:
            continue
        net = _sim(cd, b, commission_pct=args.commission, slippage_pct=args.slippage)
        if net is None:
            continue
        recs.append({"ts": cd["ts"], "features": f, "net": net})
    print(f"feature+sonuç üretilen: {len(recs)}")
    if len(recs) < 200:
        print("KAPSAM YETERSİZ"); return 1

    recs.sort(key=lambda r: r["ts"])
    split = int(len(recs) * 0.6)
    train, test = recs[:split], recs[split:]
    base_te = _ev([r["net"] for r in test])
    print(f"eğitim {len(train)} | sınav {len(test)} | baz SINAV EV {base_te['ev']}")

    # Her feature için: yüksek/ALÇAK yarı (eşik egitimde) → sınav EV + t
    keys = list(train[0]["features"].keys())
    print("\n== FEATURE TARAMASI (eşik EĞİTİMDE, ölçüm SINAVDA) ==")
    results = []
    for k in keys:
        tv = [r["features"][k] for r in train]
        for side, p, better in (("high", 0.7, "ge"), ("low", 0.3, "le")):
            thr = _pctile(tv, p)
            sel_te = [r["net"] for r in test if (r["features"][k] >= thr if better == "ge" else r["features"][k] <= thr)]
            rest_te = [r["net"] for r in test if not (r["features"][k] >= thr if better == "ge" else r["features"][k] <= thr)]
            m = _ev(sel_te); t = _paired(sel_te, rest_te)
            results.append({"feature": k, "side": side, "thr": round(thr, 4),
                            "test": m, "t": round(t, 2)})
    results.sort(key=lambda x: (x["test"]["ev"] if x["test"]["ev"] is not None else 9))
    print(f"  {'feature':10s}{'side':5s}{'thr':>12} {'EV':>8} {'n':>6} {'pf':>6} {'t':>7}")
    for r in results:
        print(f"  {r['feature']:10s}{r['side']:5s}{r['thr']:>12} {r['test']['ev']:>8} "
              f"{r['test']['n']:>6} {str(r['test'].get('pf')):>6} {r['t']:>7}")

    positives = [r for r in results if r["test"]["ev"] is not None and r["test"]["ev"] > 0 and r["t"] > 1.65]
    out = {"generated_at": time.time(), "hours": args.hours, "records": len(recs),
           "train_n": len(train), "test_n": len(test), "baseline_test": base_te,
           "features": results, "positive_significant": positives,
           "verdict": "FEATURE_EDGE_FOUND" if positives else "NO_FEATURE_EDGE"}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nrapor: {args.out}")
    if positives:
        print(f"KARAR: FEATURE_EDGE_FOUND — {len(positives)} anlamlı pozitif feature:")
        for p_ in positives:
            print(f"  {p_['feature']} ({p_['side']}) thr {p_['thr']} → EV {p_['test']['ev']}% t={p_['t']}")
    else:
        print("KARAR: NO_FEATURE_EDGE — hiçbir feature sınavda anlamlı pozitif EV vermedi")
    return 0


def _span_days(cands: list[dict]) -> float:
    if not cands:
        return 2.0
    return (max(c["ts"] for c in cands) - min(c["ts"] for c in cands)) / 86400.0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
