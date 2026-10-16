"""Rescan çıktısı ↔ canlı `velocity_candidates` (passes=true) karşılaştırması.

Girdi: iki satır listesi {"symbol","created_at"(s),"horizon_minutes","velocity_score"}.
Çıktı: gün başına ve toplam metrikler:
  * live_n / rescan_n: geçen aday sayıları
  * jaccard: günün sembol kümeleri Jaccard'ı
  * reproduced: canlı adayların, aynı sembol+ufukta |tick-created_at| <= tol olan
    bir rescan adayıyla eşleşen payı (ANA sadakat ölçüsü)
  * precision: rescan adaylarının canlıda karşılığı olan payı
  * pearson / spearman: eşleşen çiftlerde (canlı aday -> en yakın rescan tick) skor korelasyonu
Zaman dilimi: Europe/Istanbul takvim günü.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math
from collections import defaultdict

import numpy as np

_TZ_FALLBACK = dt.timezone(dt.timedelta(hours=3))


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Istanbul")
    except Exception:
        return _TZ_FALLBACK


def day_key(ts_s: float) -> str:
    return dt.datetime.fromtimestamp(float(ts_s), _tz()).strftime("%Y-%m-%d")


def _corr(a, b) -> float | None:
    if len(a) < 3:
        return None
    a = np.asarray(a, float); b = np.asarray(b, float)
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _rankdata(x) -> np.ndarray:
    x = np.asarray(x, float)
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x), float)
    ranks[order] = np.arange(1, len(x) + 1)
    # bağlı değerler: ortalama sıra
    uniq, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.zeros(len(uniq)); np.add.at(sums, inv, ranks)
    return sums[inv] / cnt[inv]


def _match(live_rows, rescan_rows, tol_s: float):
    """Canlı aday -> en yakın rescan (aynı sembol+ufuk, |dt|<=tol). Eşleşme listesi + rescan eşleşen kümesi."""
    buckets: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rescan_rows:
        buckets[(str(r["symbol"]).upper(), int(r["horizon_minutes"]))].append(r)
    sorted_b = {}
    for key, rows in buckets.items():
        rows.sort(key=lambda x: float(x["created_at"]))
        sorted_b[key] = ([float(x["created_at"]) for x in rows], rows)
    pairs = []
    matched_rescan: set[int] = set()
    for lr in live_rows:
        key = (str(lr["symbol"]).upper(), int(lr["horizon_minutes"]))
        if key not in sorted_b:
            pairs.append((lr, None)); continue
        ts, rows = sorted_b[key]
        t = float(lr["created_at"])
        k = bisect.bisect_left(ts, t)
        best = None; best_d = None
        for j in (k - 1, k):
            if 0 <= j < len(ts):
                d = abs(ts[j] - t)
                if d <= tol_s and (best_d is None or d < best_d):
                    best, best_d = rows[j], d
        pairs.append((lr, best))
        if best is not None:
            matched_rescan.add(id(best))
    return pairs, matched_rescan


def validate(live_rows: list[dict], rescan_rows: list[dict], *, tol_s: float = 300.0,
             in_pool_fn=None) -> dict:
    """`in_pool_fn(symbol, created_at) -> bool|None`: canlı adayın sembolü o anda rescan
    havuzunda mıydı (evren sapmasını ayrıştırmak için; None -> bilinmiyor)."""
    pairs, matched_rescan = _match(live_rows, rescan_rows, tol_s)
    by_day: dict[str, dict] = defaultdict(lambda: {"live_n": 0, "rescan_n": 0, "live_syms": set(),
                                                   "rescan_syms": set(), "matched": 0,
                                                   "scores_live": [], "scores_rescan": [],
                                                   "rescan_matched": 0, "in_pool": 0, "pool_known": 0})
    for lr, rr in pairs:
        d = by_day[day_key(lr["created_at"])]
        d["live_n"] += 1
        d["live_syms"].add(str(lr["symbol"]).upper())
        if in_pool_fn is not None:
            p = in_pool_fn(str(lr["symbol"]).upper(), float(lr["created_at"]))
            if p is not None:
                d["pool_known"] += 1
                d["in_pool"] += int(bool(p))
        if rr is not None:
            d["matched"] += 1
            d["scores_live"].append(float(lr.get("velocity_score") or 0.0))
            d["scores_rescan"].append(float(rr.get("velocity_score") or 0.0))
    for r in rescan_rows:
        d = by_day[day_key(r["created_at"])]
        d["rescan_n"] += 1
        d["rescan_syms"].add(str(r["symbol"]).upper())
        if id(r) in matched_rescan:
            d["rescan_matched"] += 1

    def _finish(d):
        union = d["live_syms"] | d["rescan_syms"]
        inter = d["live_syms"] & d["rescan_syms"]
        sl, sr = d["scores_live"], d["scores_rescan"]
        return {"live_n": d["live_n"], "rescan_n": d["rescan_n"],
                "live_syms": len(d["live_syms"]), "rescan_syms": len(d["rescan_syms"]),
                "jaccard": (len(inter) / len(union)) if union else None,
                "in_pool": (d["in_pool"] / d["pool_known"]) if d["pool_known"] else None,
                "reproduced": (d["matched"] / d["live_n"]) if d["live_n"] else None,
                "precision": (d["rescan_matched"] / d["rescan_n"]) if d["rescan_n"] else None,
                "pearson": _corr(sl, sr),
                "spearman": _corr(_rankdata(sl), _rankdata(sr)) if len(sl) >= 3 else None,
                "matched": d["matched"]}

    days = {k: _finish(v) for k, v in sorted(by_day.items())}
    tot = {"live_n": 0, "rescan_n": 0, "live_syms": set(), "rescan_syms": set(), "matched": 0,
           "scores_live": [], "scores_rescan": [], "rescan_matched": 0, "in_pool": 0, "pool_known": 0}
    for v in by_day.values():
        for k in ("live_n", "rescan_n", "matched", "rescan_matched", "in_pool", "pool_known"):
            tot[k] += v[k]
        tot["live_syms"] |= v["live_syms"]; tot["rescan_syms"] |= v["rescan_syms"]
        tot["scores_live"] += v["scores_live"]; tot["scores_rescan"] += v["scores_rescan"]
    return {"days": days, "total": _finish(tot), "tol_s": tol_s}


def _fmt(x, pct=False, nd=2):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    if pct:
        return f"{100 * x:.1f}%"
    return f"{x:.{nd}f}"


def format_table(report: dict) -> str:
    hdr = (f"{'gün':<11}{'canlı':>7}{'rescan':>8}{'sym_c':>6}{'sym_r':>6}{'jaccard':>9}{'havuzda':>9}"
           f"{'yeniden':>9}{'kesinlik':>10}{'pearson':>9}{'spearman':>9}")
    lines = [hdr, "-" * len(hdr)]

    def row(name, d):
        return (f"{name:<11}{d['live_n']:>7}{d['rescan_n']:>8}{d['live_syms']:>6}{d['rescan_syms']:>6}"
                f"{_fmt(d['jaccard']):>9}{_fmt(d.get('in_pool'), pct=True):>9}"
                f"{_fmt(d['reproduced'], pct=True):>9}{_fmt(d['precision'], pct=True):>10}"
                f"{_fmt(d['pearson']):>9}{_fmt(d['spearman']):>9}")
    for day, d in report["days"].items():
        lines.append(row(day, d))
    lines.append("-" * len(hdr))
    lines.append(row("TOPLAM", report["total"]))
    lines.append(f"(eşleşme toleransı ±{int(report['tol_s'])} sn; 'havuzda' = canlı adayın sembolü o tick'te rescan "
                 f"havuzundaydı; 'yeniden' = canlı adayın rescan'de karşılığı; 'kesinlik' = rescan adayının canlıda karşılığı)")
    return "\n".join(lines)
