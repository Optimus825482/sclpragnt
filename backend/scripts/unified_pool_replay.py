"""BİRLEŞİK HAVUZ REPLAY (Aşama B, 2026-10-13) — karar verici backtest.

AMAÇ: "Tüm motorlardan beslenen tek havuz + ortak karar kapısı" yaklaşımı, mevcut
radar tek başına yaklaşımından DAHA İYİ mi? Canlıya almadan ÖNCE ölçer.

KARŞILAŞTIRILAN İKİ AKIŞ (aynı simülatör, adil kıyas):
  * MEVCUT: radarın `passes=true` adayları (velocity journal) — bugünkü davranış.
  * BİRLEŞİK: aynı adaylara ORTAK KARAR kapısı (`is_genuinely_rising`: fiyat yukarı
    + composite_index + confluence_count) uygulanmış hâli. Bu, havuzun canlıda
    üreteceği alt kümenin replay'deki vekilidir.

Not: `master_surge` composite/confluence canlı `_SNAPSHOT` gerektirir; tarihsel
yeniden üretilemez. Bu yüzden replay'de ortak-karar vekili olarak **çok-kaynak
teyidi** kullanılır: aynı sembolün aynı pencerede birden çok motor/ufuk tarafından
işaretlenmesi (velocity ufukları + rising + Global). Bu, `confluence` kavramının
tarihsel karşılığıdır ve dürüstçe raporlanır.

YÖNTEM: walk-forward (kronolojik %60 eğitim / %40 sınav), gün-gün, sembol
yoğunlaşması, taker+maliyet net EV, MAE>MFE kontrolü.

KULLANIM:
    python backend/scripts/unified_pool_replay.py --days 15
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import sqlite3
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORK = os.path.join(_HERE, "..", "work")
_DB = os.path.join(_WORK, "market_cache.sqlite")

# Round-trip maliyet (taker): komisyon×2 + kayma×2.
_TAKER_COST = 0.35
_MAKER_COST = 0.10


def _load_candidates(days: float, db_url: str) -> list[dict]:
    import psycopg
    since = time.time() - days * 86400.0
    out = []
    with psycopg.connect(db_url, connect_timeout=8) as conn:
        for ts, sym, px, tgt, profile, ret3, atr in conn.execute(
            "SELECT created_at, symbol, price, target_pct, candidate_id, ret3_pct, atr_pct "
            "FROM velocity_candidates "
            "WHERE passes=true AND created_at>=%s AND price>0 ORDER BY created_at", (since,)):
            try:
                from app.routers.velocity import _velocity_horizon_from_candidate_id as _h
                out.append({"ts": float(ts), "sym": str(sym).upper(), "price": float(px),
                            "target": float(tgt or 2.0), "h": _h(str(profile or "")),
                            "ret3": float(ret3 or 0.0), "atr": float(atr or 0.0)})
            except (TypeError, ValueError):
                continue
    return out


_PRICE_SOURCES = ("auto", "sqlite", "postgres", "rest")


def _load_prices_sqlite(syms: set[str]) -> dict:
    """work/market_cache.sqlite (`klines`, 5m). Dosya yoksa boş döner."""
    if not os.path.exists(_DB):
        return {}
    conn = sqlite3.connect(_DB)
    out: dict = {}
    try:
        for sym, ot, h, l, c in conn.execute(
            "SELECT symbol, open_time, high, low, close FROM klines "
            "WHERE interval='5m' ORDER BY symbol, open_time"):
            s = str(sym).upper()
            if s in syms and c and c > 0:
                out.setdefault(s, []).append((float(ot) / 1000.0, float(h), float(l), float(c)))
    finally:
        conn.close()
    return out


def _load_prices_postgres(syms: set[str], db_url: str) -> dict:
    """2026-10-16 (harness onarımı): Postgres `historical_candles` (5m, open_time ms)."""
    if not db_url or not syms:
        return {}
    import psycopg
    out: dict = {}
    with psycopg.connect(db_url, connect_timeout=8) as conn:
        for sym, ot, h, l, c in conn.execute(
            "SELECT symbol, open_time, high, low, close FROM historical_candles "
            "WHERE timeframe='5m' AND symbol = ANY(%s) ORDER BY symbol, open_time",
            (sorted(syms),)):
            s = str(sym).upper()
            if c and c > 0:
                out.setdefault(s, []).append((float(ot) / 1000.0, float(h), float(l), float(c)))
    return out


def _bars_from_klines(rows) -> list:
    """Binance kline satırları [open_ms, open, high, low, close, ...] → (ts, high, low, close)."""
    bars = []
    for k in rows or []:
        try:
            bars.append((float(k[0]) / 1000.0, float(k[2]), float(k[3]), float(k[4])))
        except (TypeError, ValueError, IndexError):
            continue
    return bars


def _load_prices_rest(syms: set[str], days: float) -> dict:
    """Binance TR REST (son çare; ağ gerektirir). `klines()` sembolü kendisi normalize eder."""
    if not syms:
        return {}
    import asyncio
    from app.binance_tr_public import historical_klines

    async def _one(sym: str):
        try:
            rows = await historical_klines(sym, "5m", max(1, int(days) + 1))
        except Exception as exc:  # ağ/limit hatası: sembol atlanır, replay sürer
            print(f"  REST {sym}: {exc}")
            return sym, []
        return sym, _bars_from_klines(rows)

    async def _all():
        res = await asyncio.gather(*[_one(s) for s in sorted(syms)])
        return {s: b for s, b in res if b}

    return asyncio.run(_all())


def _load_prices(syms: set[str], *, source: str = "auto", db_url: str = "",
                 days: float = 15.0) -> dict:
    """Mum kaynağı seçimi (2026-10-16 harness onarımı).

    `auto`: sqlite → postgres → REST; her adım yalnız EKSİK sembolleri tamamlar.
    Eski davranış yalnız sqlite idi ve dosya yoksa `unable to open database file`
    ile düşüyordu.
    """
    if source not in _PRICE_SOURCES:
        raise ValueError(f"bilinmeyen fiyat kaynağı: {source!r} (geçerli: {_PRICE_SOURCES})")
    out: dict = {}
    coverage: dict[str, int] = {}
    order = ["sqlite", "postgres", "rest"] if source == "auto" else [source]
    for step in order:
        missing = {s for s in syms if s not in out}
        if not missing:
            break
        try:
            if step == "sqlite":
                got = _load_prices_sqlite(missing)
            elif step == "postgres":
                got = _load_prices_postgres(missing, db_url)
            else:
                got = _load_prices_rest(missing, days)
        except Exception as exc:
            print(f"  fiyat kaynağı {step} başarısız: {exc}")
            got = {}
        got = {s: b for s, b in got.items() if s in missing and b}
        out.update(got)
        coverage[step] = len(got)
    print("  fiyat kaynakları: " + ", ".join(f"{k}={v}" for k, v in coverage.items()))
    return out


def _simulate(bars: list, entry: float, target_pct: float, horizon_min: float,
              cost_pct: float, *, time_stop_min: float | None = None,
              time_stop_min_profit_pct: float = 0.0, entry_ts: float = 0.0) -> dict | None:
    """Basit ama gerçekçi çıkış: TP / SL(%3) / ufuk sonu. Bar-içi kötümser (SL önce).

    2026-10-15 (radar iyileştirme): `time_stop_min` verilirse, TP'den SONRA, bar
    kapanış süresi `entry_ts + time_stop_min*60`'a ulaştığında kâr% < eşik ise
    bar kapanışından `reason="time_stop"` ile çıkılır. None iken davranış aynıdır.
    """
    if not bars or entry <= 0:
        return None
    tp = entry * (1 + target_pct / 100.0)
    sl = entry * (1 - 3.0 / 100.0)
    end = bars[0][0] + horizon_min * 60.0
    peak = entry
    exit_px = None
    reason = "horizon_end"
    for ot, hi, lo, cl in bars:
        if ot > end:
            break
        if lo <= sl:                       # kötümser: SL önce
            exit_px, reason = sl, "stop_loss"; break
        peak = max(peak, hi)
        if hi >= tp:
            exit_px, reason = tp, "take_profit"; break
        # 2026-10-15 (radar iyileştirme): zaman-durdurma (5m mum kapanışı = ot + 300 sn).
        if (time_stop_min is not None and entry_ts > 0
                and (ot + 300.0 - entry_ts) >= time_stop_min * 60.0
                and (cl / entry - 1.0) * 100.0 < time_stop_min_profit_pct):
            exit_px, reason = cl, "time_stop"; break
        exit_px = cl
    if exit_px is None:
        return None
    gross = (exit_px / entry - 1) * 100
    return {"net_pct": round(gross - cost_pct, 4), "reason": reason,
            "mfe": round((peak / entry - 1) * 100, 3)}


def _metrics(signals: list[dict]) -> dict:
    nets = [s["net_pct"] for s in signals if s.get("net_pct") is not None]
    if not nets:
        return {"n": 0, "ev": None}
    w = [x for x in nets if x > 0]
    l = [x for x in nets if x <= 0]
    aw = statistics.mean(w) if w else 0.0
    al = statistics.mean(l) if l else 0.0
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "median": round(statistics.median(nets), 3),
            "win": round(100 * len(w) / len(nets), 1),
            "payoff": round(aw / abs(al), 2) if al else None}


def _paired_t(a: list[float], b: list[float]) -> float:
    a = [x for x in a if x is not None]; b = [x for x in b if x is not None]
    if len(a) < 20 or len(b) < 20:
        return 0.0
    va = statistics.pvariance(a) / len(a); vb = statistics.pvariance(b) / len(b)
    se = (va + vb) ** 0.5
    return round((statistics.mean(a) - statistics.mean(b)) / se, 2) if se else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=15.0)
    # 2026-10-15 (denetim düzeltmesi): sabit DB kimlik bilgisi kaldırıldı; DATABASE_URL zorunlu.
    ap.add_argument("--db-url", default=os.getenv("DATABASE_URL", "").strip())
    ap.add_argument("--out", default="work/unified_pool_replay.json")
    # 2026-10-16 (harness onarımı): mum kaynağı seçimi; auto = sqlite → postgres → REST.
    ap.add_argument("--price-source", choices=_PRICE_SOURCES, default="auto",
                    help="5m mum kaynağı: auto (sqlite→postgres→rest), sqlite, postgres, rest")
    # 2026-10-15 (radar iyileştirme): zaman-durdurma ölçümü. Verilmezse (None) eski davranış.
    ap.add_argument("--time-stop-min", type=float, default=None,
                    help="bu dk sonra kâr eşiğin altındaysa kapat (boş = kapalı)")
    ap.add_argument("--time-stop-min-profit-pct", type=float, default=0.0,
                    help="time-stop için minimum kâr %% (varsayılan 0.0)")
    args = ap.parse_args()
    if not args.db_url:
        sys.exit("HATA: --db-url verilmedi ve DATABASE_URL ortam değişkeni tanımlı değil")
    print("=== BİRLEŞİK HAVUZ REPLAY (Aşama B) ===")
    cands = _load_candidates(args.days, args.db_url)
    print(f"  aday (passes=true): {len(cands)}")
    if not cands:
        print("aday yok"); return 1
    syms = {c["sym"] for c in cands}
    prices = _load_prices(syms, source=args.price_source, db_url=args.db_url, days=args.days)
    print(f"  fiyat kapsamı: {len(prices)}/{len(syms)} sembol")

    # Çok-kaynak teyidi vekili: aynı sembol ±15 dk pencerede >=2 kez işaretlendiyse
    # "confluence" say (farklı ufuk/motor aynı sembolü görmüş). Zaman sıralı.
    cands.sort(key=lambda c: c["ts"])
    marks: dict[str, list[float]] = defaultdict(list)
    for c in cands:
        marks[c["sym"]].append(c["ts"])

    def _confluence(c) -> bool:
        ts_list = marks[c["sym"]]
        i = bisect.bisect_left(ts_list, c["ts"])
        lo = bisect.bisect_left(ts_list, c["ts"] - 900)
        hi = bisect.bisect_right(ts_list, c["ts"] + 900)
        return (hi - lo) >= 2      # ±15 dk içinde en az 2 işaret

    def _sim_stream(rows, cost):
        out = []
        for c in rows:
            bars = prices.get(c["sym"])
            if not bars:
                continue
            i = bisect.bisect_left([b[0] for b in bars], c["ts"])
            win = [b for b in bars[i:i + 40] if b[0] <= c["ts"] + c["h"] * 60 + 300]
            r = _simulate(win, c["price"], c["target"], c["h"], cost,
                          time_stop_min=args.time_stop_min,
                          time_stop_min_profit_pct=args.time_stop_min_profit_pct,
                          entry_ts=c["ts"])
            if r is None:
                continue
            r["ts"] = c["ts"]; r["sym"] = c["sym"]
            out.append(r)
        out.sort(key=lambda r: r["ts"])
        return out

    # Katmanlı skor vekili (replay): velocity panel + çok-kaynak + trend + likidite.
    from app.rising_pool import score_candidate

    def _pool_score(c) -> float:
        return score_candidate({
            "panel_score": None,
            "velocity_score": (c["target"] / max(1, c["h"])) * 1000.0,  # panel vekili (replay)
            "unified_sources": (["velocity", "rising"] if _confluence(c) else ["velocity"]),
            "master_surge": {"confluence_count": (2 if _confluence(c) else 1)},
            "ret3_pct": c.get("ret3", 0.0),
            "atr_pct": c.get("atr", 0.0),
        })

    # Walk-forward: %60 eğitim / %40 sınav
    split = int(len(cands) * 0.6)
    tr, te = cands[:split], cands[split:]

    results = {}
    for cost_name, cost in (("taker", _TAKER_COST), ("maker", _MAKER_COST)):
        # MEVCUT: tüm passes adayları
        cur_te = _sim_stream(te, cost)
        # BİRLEŞİK: confluence vekili kapısı
        uni_te = _sim_stream([c for c in te if _confluence(c)], cost)
        # SKOR-TOP-N: eğitimde eşik (üst %50 skor) → sınavda uygula
        tr_scores = sorted(_pool_score(c) for c in tr)
        thr = tr_scores[int(len(tr_scores) * 0.5)] if tr_scores else 0.0
        sc_te = _sim_stream([c for c in te if _pool_score(c) >= thr], cost)
        results[f"mevcut_{cost_name}"] = _metrics(cur_te)
        results[f"birlesik_{cost_name}"] = _metrics(uni_te)
        results[f"skortop_{cost_name}"] = _metrics(sc_te)
        # 3-fold stabilite
        for tag, stream in (("birlesik", uni_te), ("skortop", sc_te)):
            folds = []
            for k in range(3):
                a, b = int(len(stream) * k / 3), int(len(stream) * (k + 1) / 3)
                folds.append(_metrics(stream[a:b])["ev"])
            results[f"{tag}_{cost_name}_folds"] = folds
        # Gün-gün
        for tag, stream in (("birlesik", uni_te), ("skortop", sc_te)):
            byday = defaultdict(list)
            for r in stream:
                byday[int(r["ts"] // 86400)].append(r["net_pct"])
            results[f"{tag}_{cost_name}_daily_pos"] = (
                f"{sum(1 for v in byday.values() if statistics.mean(v) > 0)}/{len(byday)}")

    # t-testi: her iki aday akışı vs mevcut (taker)
    cur = [r["net_pct"] for r in _sim_stream(te, _TAKER_COST)]
    uni = [r["net_pct"] for r in _sim_stream([c for c in te if _confluence(c)], _TAKER_COST)]
    sc = [r["net_pct"] for r in _sim_stream([c for c in te if _pool_score(c) >= thr], _TAKER_COST)]
    results["paired_t_birlesik_vs_mevcut"] = _paired_t(uni, cur)
    results["paired_t_skortop_vs_mevcut"] = _paired_t(sc, cur)

    # Sembol yoğunlaşması (skor-top)
    sc_rows = _sim_stream([c for c in te if _pool_score(c) >= thr], _TAKER_COST)
    cnt = defaultdict(int)
    for r in sc_rows:
        cnt[r["sym"]] += 1
    tot = sum(cnt.values()) or 1
    results["skortop_concentration"] = {
        "symbols": len(cnt),
        "top_share_pct": round(100 * max(cnt.values()) / tot, 1) if cnt else None}

    print("\n  == SONUÇLAR ==")
    for k, v in results.items():
        print(f"  {k}: {v}")
    # Karar
    uni_ev = results.get("birlesik_taker", {}).get("ev")
    sc_ev = results.get("skortop_taker", {}).get("ev")
    folds = results.get("skortop_taker_folds", [])
    stable = all((f or -9) > 0 for f in folds if f is not None)
    best = max([x for x in (uni_ev, sc_ev) if x is not None] or [-9])
    print(f"\n  KARAR: birleşik EV={uni_ev} | skortop EV={sc_ev} | fold stabil={stable} | "
          f"eşik(net EV>0 & 3-fold>0)={'GEÇTİ' if best > 0 and stable else 'GEÇMEDİ'}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
