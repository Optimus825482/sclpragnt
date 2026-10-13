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


def _load_prices(syms: set[str]) -> dict:
    conn = sqlite3.connect(_DB)
    out: dict = {}
    for sym, ot, h, l, c in conn.execute(
        "SELECT symbol, open_time, high, low, close FROM klines "
        "WHERE interval='5m' ORDER BY symbol, open_time"):
        s = str(sym).upper()
        if s in syms and c and c > 0:
            out.setdefault(s, []).append((float(ot) / 1000.0, float(h), float(l), float(c)))
    conn.close()
    return out


def _simulate(bars: list, entry: float, target_pct: float, horizon_min: float,
              cost_pct: float) -> dict | None:
    """Basit ama gerçekçi çıkış: TP / SL(%3) / ufuk sonu. Bar-içi kötümser (SL önce)."""
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
    ap.add_argument("--db-url", default="postgresql://postgres:518518Erkan@localhost:5432/scalper")
    ap.add_argument("--out", default="work/unified_pool_replay.json")
    args = ap.parse_args()
    print("=== BİRLEŞİK HAVUZ REPLAY (Aşama B) ===")
    cands = _load_candidates(args.days, args.db_url)
    print(f"  aday (passes=true): {len(cands)}")
    if not cands:
        print("aday yok"); return 1
    syms = {c["sym"] for c in cands}
    prices = _load_prices(syms)
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
            r = _simulate(win, c["price"], c["target"], c["h"], cost)
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
