"""Radar sinyal ailesi kaldıraç (lift) analizi.

SORU: Bir sinyal ailesi (ör. "velocity", "pulse") ya da bir skor bandı, aday
hit oranını GERÇEKTEN yükseltiyor mu; yoksa yalnızca o ailenin bulunduğu
satırlarda hit oranı yüksek mi görünüyor?

    lift = hit_oranı(aile VAR) / hit_oranı(aile YOK)

  * lift > 1  -> aile hit oranını yükseltiyor (filtre/bonus lehine kanıt)
  * lift < 1  -> aile hit oranını düşürüyor (filtre/bonus şüpheli)
  * lift ~ 1  -> aile ayırt edici değil

VERİ: `unified_candidate_outcomes` tablosu. Yalnız `outcome_filled_at IS NOT NULL`
satırlar ölçülmüştür; `hit` boş (NULL) olan satırlar analiz dışı bırakılır.
Kaynak PostgreSQL (varsayılan) veya aynı kolon adlarına sahip bir CSV (`--csv`).

Bu modül import anında DATABASE_URL okumaz; kontrol yalnız main() içindedir.

KULLANIM (backend klasöründen):
    python -m scripts.radar_lift_analysis --days 14
    python -m scripts.radar_lift_analysis --csv work/outcomes.csv --min-n 30
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import numpy as np

ISTANBUL = ZoneInfo("Europe/Istanbul")

# (ad, alt sınır dahil, üst sınır hariç). None = sınırsız.
SCORE_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("score<70", None, 70.0),
    ("70-85", 70.0, 85.0),
    ("85-95", 85.0, 95.0),
    ("95-100", 95.0, None),
)


# ---------------------------------------------------------------- yardımcılar

def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Oran için Wilson güven aralığı. n=0 ise None."""
    if n <= 0:
        return None
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _to_bool(value: Any) -> bool | None:
    """CSV ve DB değerlerini bool'a çevirir; tanınmayan/boş değer None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "t", "1", "yes", "y"}:
        return True
    if text in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _to_float(value: Any) -> float | None:
    """Sayısal değer; boş, NaN/inf veya çevrilemeyen değer None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text or text.lower() in {"none", "null", "nan"}:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _parse_sources(value: Any) -> set[str] | None:
    """`sources` JSON dizisini küme olarak döndürür.

    Bozuk JSON, dizi olmayan değer -> None (satır aile analizinden atlanır).
    Aynı satırda tekrarlanan kaynak tek sayılır.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    if not isinstance(value, list):
        return None
    return {item.strip() for item in value if isinstance(item, str) and item.strip()}


def _normalize(row: dict) -> dict | None:
    """Ham satırı analiz biçimine çevirir. `hit` boşsa None (satır dışlanır)."""
    hit = _to_bool(row.get("hit"))
    if hit is None:
        return None
    return {
        "hit": hit,
        "sources": _parse_sources(row.get("sources")),
        "score": _to_float(row.get("scan_score")),
        "mfe": _to_float(row.get("mfe_pct")),
        "detected_at": _to_float(row.get("detected_at")),
    }


def _normalized_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        item = _normalize(row)
        if item is not None:
            out.append(item)
    return out


def _lift_entry(name: str, kind: str, pool: list[dict],
                member: Callable[[dict], bool], min_n: int) -> dict:
    """Bir aile/bant için VAR ve YOK gruplarının hit istatistikleri ve lift."""
    with_rows = [r for r in pool if member(r)]
    without_rows = [r for r in pool if not member(r)]
    n_with = len(with_rows)
    n_without = len(without_rows)
    hit_with = sum(1 for r in with_rows if r["hit"])
    hit_without = sum(1 for r in without_rows if r["hit"])
    rate_with = hit_with / n_with if n_with else None
    rate_without = hit_without / n_without if n_without else None

    lift = None
    if (n_with >= min_n and n_without >= min_n
            and rate_without is not None and rate_without > 0.0):
        lift = rate_with / rate_without

    ci = wilson_interval(hit_with, n_with)
    return {
        "family": name,
        "kind": kind,
        "n_with": n_with,
        "hit_with": hit_with,
        "hit_rate_with": rate_with,
        "n_without": n_without,
        "hit_without": hit_without,
        "hit_rate_without": rate_without,
        "lift": lift,
        "ci_low": ci[0] if ci else None,
        "ci_high": ci[1] if ci else None,
    }


# ------------------------------------------------------------ analiz fonksiyonları

def compute_family_lift(rows: list[dict], min_n: int = 30) -> list[dict]:
    """Her sinyal ailesi ve skor bandı için hit oranı kaldıracı.

    Aile = `sources` JSON dizisindeki her farklı kaynak adı (kind="source").
    Skor bandı = `scan_score` aralığı (kind="score_bucket"; ad: "score<70",
    "70-85", "85-95", "95-100").

    lift = hit_oranı(VAR) / hit_oranı(YOK). Hem VAR hem YOK grubu en az
    `min_n` satır içermiyorsa ya da YOK grubunun hit oranı 0 ise lift None.
    Sonuç lift'e göre azalan sırada döner (None'lar sonda).
    """
    data = _normalized_rows(rows)

    family_pool = [r for r in data if r["sources"] is not None]
    families = sorted({src for r in family_pool for src in r["sources"]})
    results: list[dict] = []
    for fam in families:
        results.append(_lift_entry(
            fam, "source", family_pool,
            lambda r, f=fam: f in r["sources"], min_n))

    score_pool = [r for r in data if r["score"] is not None]
    for label, lo, hi in SCORE_BUCKETS:
        results.append(_lift_entry(
            label, "score_bucket", score_pool,
            lambda r, lo=lo, hi=hi: ((lo is None or r["score"] >= lo)
                                     and (hi is None or r["score"] < hi)),
            min_n))

    results.sort(key=lambda e: (e["lift"] is None,
                                -(e["lift"] or 0.0), e["family"]))
    return results


def precision_at_k(rows: list[dict],
                   k_values: tuple[int, ...] = (5, 10, 20)) -> dict[int, float | None]:
    """Gün içi en yüksek `scan_score`'lu k adayın ortalama hit oranı.

    Gün sınırı İstanbul saatine göre alınır. Bir gün k'dan az satır içeriyorsa
    o gün o k için atlanır (eksik günle top-k ölçülmez). Hiç uygun gün yoksa None.
    Dönen değerler [0, 1] aralığındadır.
    """
    by_day: dict[Any, list[dict]] = defaultdict(list)
    for r in _normalized_rows(rows):
        if r["score"] is None or r["detected_at"] is None:
            continue
        day = datetime.fromtimestamp(r["detected_at"], ISTANBUL).date()
        by_day[day].append(r)

    out: dict[int, float | None] = {}
    for k in k_values:
        k = int(k)
        if k < 1:
            raise ValueError("k en az 1 olmalı")
        per_day = []
        for day_rows in by_day.values():
            if len(day_rows) < k:
                continue
            top = sorted(day_rows, key=lambda r: -r["score"])[:k]
            per_day.append(sum(1 for r in top if r["hit"]) / k)
        out[k] = float(np.mean(per_day)) if per_day else None
    return out


def _rankdata(values: list[float]) -> np.ndarray:
    """Ortalama bağlı (average tie) sıra değerleri, 1-tabanlı."""
    arr = np.asarray(values, dtype=float)
    order = np.argsort(arr, kind="mergesort")
    sorted_vals = arr[order]
    ranks = np.empty(arr.size, dtype=float)
    i = 0
    n = arr.size
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman_score_mfe(rows: list[dict]) -> float | None:
    """`scan_score` ile `mfe_pct` arasındaki Spearman korelasyonu.

    En az 3 çift ve iki tarafta da değişkenlik gerekir; aksi halde None.
    """
    pairs = [(r["score"], r["mfe"]) for r in _normalized_rows(rows)
             if r["score"] is not None and r["mfe"] is not None]
    if len(pairs) < 3:
        return None
    x = _rankdata([p[0] for p in pairs])
    y = _rankdata([p[1] for p in pairs])
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    rho = float(np.corrcoef(x, y)[0, 1])
    return rho if math.isfinite(rho) else None


# ------------------------------------------------------------ veri yükleme

def _db_url() -> str:
    """DATABASE_URL okur. Yalnız main() çağırır; import anında çağrılmaz."""
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL ortam değişkeni tanımlı değil "
                           "(örn. postgresql://kullanici:sifre@host:5432/scalper)")
    return url


def _load_from_db(url: str, days: float) -> list[dict]:
    import psycopg

    since = time.time() - days * 86400.0
    cols = ("symbol", "horizon_minutes", "sources", "scan_score", "mfe_pct",
            "mae_pct", "hit", "detected_at")
    sql = (f"SELECT {', '.join(cols)} FROM unified_candidate_outcomes "
           "WHERE outcome_filled_at IS NOT NULL AND detected_at >= %s "
           "ORDER BY detected_at")
    with psycopg.connect(url, connect_timeout=8) as conn:
        rows = conn.execute(sql, (since,)).fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _load_from_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------ çıktı

def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100.0 * value:.1f}"


def _num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _print_report(rows: list[dict], label: str, min_n: int) -> None:
    fams = compute_family_lift(rows, min_n=min_n)
    usable = _normalized_rows(rows)

    print("# Radar sinyal kaldıraç analizi")
    print(f"Kaynak: {label} | ölçülmüş satır: {len(usable)} | min_n: {min_n}")
    print()
    print("| Aile | Tür | n (var) | hit % (var) | hit % (yok) | lift | 95% CI (var, %) |")
    print("|---|---|---:|---:|---:|---:|---|")
    for e in fams:
        ci = ("-" if e["ci_low"] is None
              else f"[{100 * e['ci_low']:.1f}, {100 * e['ci_high']:.1f}]")
        kind = "kaynak" if e["kind"] == "source" else "skor"
        print(f"| {e['family']} | {kind} | {e['n_with']} | {_pct(e['hit_rate_with'])} "
              f"| {_pct(e['hit_rate_without'])} | {_num(e['lift'])} | {ci} |")
    print()

    print("## Precision@k (gün içi en yüksek skorlu k aday, İstanbul günü)")
    for k, value in precision_at_k(rows).items():
        print(f"- P@{k}: {_num(value, 3)}")
    print()
    print(f"## Spearman (scan_score vs mfe_pct): {_num(spearman_score_mfe(rows), 3)}")
    print()

    # Karar yalnız sinyal aileleri (kaynaklar) üzerinden verilir.
    low = [e["family"] for e in fams
           if e["kind"] == "source" and e["lift"] is not None and e["lift"] < 1.0]
    print(f"KARAR: lift<1.0 olan aileler: {low}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Radar sinyal ailelerinin hit oranı kaldıracını ölçer.")
    ap.add_argument("--days", type=float, default=14.0,
                    help="DB modunda geriye dönük gün sayısı (varsayılan 14)")
    ap.add_argument("--csv", default=None,
                    help="DB yerine bu CSV dosyasını oku (aynı kolon adları)")
    ap.add_argument("--min-n", type=int, default=30,
                    help="lift için VAR ve YOK gruplarında asgari satır (varsayılan 30)")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    if args.days <= 0:
        print("HATA: --days pozitif olmalı.", file=sys.stderr)
        return 2
    if args.min_n < 1:
        print("HATA: --min-n en az 1 olmalı.", file=sys.stderr)
        return 2

    if args.csv:
        try:
            raw = _load_from_csv(args.csv)
        except FileNotFoundError:
            print(f"HATA: CSV dosyası bulunamadı: {args.csv}", file=sys.stderr)
            return 1
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            print(f"HATA: CSV okunamadı ({args.csv}): {exc}", file=sys.stderr)
            return 1
        label = f"CSV: {args.csv}"
    else:
        try:
            raw = _load_from_db(_db_url(), args.days)
        except RuntimeError as exc:
            print(f"HATA: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - CLI sınırı: veritabanı hatası
            print(f"HATA: veritabanından okunamadı ({type(exc).__name__}): {exc}",
                  file=sys.stderr)
            return 1
        label = f"PostgreSQL, son {args.days:g} gün"

    if not _normalized_rows(raw):
        print("HATA: ölçülmüş satır yok (hit değeri dolu satır bulunamadı).",
              file=sys.stderr)
        return 1

    _print_report(raw, label, args.min_n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
