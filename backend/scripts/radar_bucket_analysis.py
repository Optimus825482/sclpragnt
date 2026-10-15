"""RADAR KOVA ANALİZİ (2026-10-15, iyileştirme 7 ve 8).

SORU 7 - Geç faz: Sinyaller "fiyat aralığı konumunun" (24s ve 60 barlık aralığın
neresinde olduğu) hangi bölgesinde çalışmayı bırakıyor? Konum kovalarına göre
isabet oranı, MFE/MAE ve Wilson %95 güven aralığı raporlanır; isabet oranının
üst güven sınırı genel isabetin altında kalan en düşük kova "geç faz" sayılır.

SORU 8 - Likidite: Likit ve likit olmayan TRY çiftleri farklı mı davranıyor?
24s hacim üzerinden üç tersil (illikit / orta / likit) kurulur; her tersil için
devam (MFE > |MAE|) ile geri dönüş (MFE <= |MAE|) payları ve isabet oranları
karşılaştırılır.

VERİ KAYNAKLARI:
  * `unified_candidate_outcomes` tablosu (ortam değişkeni DATABASE_URL, psycopg)
    veya `--csv` ile verilen dışa aktarım.
  * Journal, aralık konumunu ve 24s hacmi tutmaz. Bu yüzden isteğe bağlı
    `--features` CSV'si (symbol, detected_at, range_pos_60, pos24, quote_vol_24h)
    sembol başına en yakın zamanlı kayda (±120 s) birleştirilir.

KISITLAR: Betik SALT OKUNURDUR (veritabanına yazmaz, üretim kodunu içe aktarmaz).
DATABASE_URL yalnızca main() içinde okunur; modül import edilirken ortam denetlenmez.

KULLANIM:
    python backend/scripts/radar_bucket_analysis.py --days 14 --features feats.csv
    python backend/scripts/radar_bucket_analysis.py --csv outcomes.csv --features feats.csv --min-n 30
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Any, Optional

import numpy as np

TERTILE_LABELS = ("illikit", "orta", "likit")
FEATURE_KEYS = ("range_pos_60", "pos24", "quote_vol_24h")
DEFAULT_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0001]
JOIN_TOL_SEC = 120.0
_Z95 = 1.959963984540054
_TRUE_TEXT = {"1", "true", "t", "yes", "y"}
_FALSE_TEXT = {"0", "false", "f", "no", "n"}
_DB_COLUMNS = ("symbol", "horizon_minutes", "scan_score", "entry_price",
               "ceiling_pct", "target_pct", "detected_at", "mfe_pct",
               "mae_pct", "hit")


# ---------------------------------------------------------------------------
# Ayrıştırma yardımcıları (saf fonksiyonlar)
# ---------------------------------------------------------------------------

def _f(value: Any) -> Optional[float]:
    """Değeri float'a çevirir; boş, NaN veya çevrilemeyen değer için None döner."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        x = float(value)
        return None if math.isnan(x) else x
    text = str(value).strip()
    if not text or text.lower() in ("none", "nan", "null"):
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    return None if math.isnan(x) else x


def _hit(value: Any) -> Optional[bool]:
    """İsabet alanını bool'a çevirir; bilinmeyen (boş) değer için None döner."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE_TEXT:
        return True
    if text in _FALSE_TEXT:
        return False
    return None


def _epoch(value: Any) -> Optional[float]:
    """Zamanı epoch saniyeye çevirir (sayı, datetime veya ISO metni)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    x = _f(value)
    if x is not None:
        return x
    try:
        return datetime.fromisoformat(str(value).strip()).timestamp()
    except ValueError:
        return None


def _sym(value: Any) -> str:
    """Sembol anahtarını büyük harfli ve kırpılmış olarak döner."""
    return str(value).strip().upper() if value is not None else ""


def _normalize_row(raw: dict) -> dict:
    """Ham journal satırını analiz için sabit alanlı sözlüğe çevirir."""
    return {
        "symbol": _sym(raw.get("symbol")),
        "horizon_minutes": _f(raw.get("horizon_minutes")),
        "scan_score": _f(raw.get("scan_score")),
        "entry_price": _f(raw.get("entry_price")),
        "ceiling_pct": _f(raw.get("ceiling_pct")),
        "target_pct": _f(raw.get("target_pct")),
        "detected_at": _epoch(raw.get("detected_at")),
        "mfe_pct": _f(raw.get("mfe_pct")),
        "mae_pct": _f(raw.get("mae_pct")),
        "hit": _hit(raw.get("hit")),
    }


def _normalize_feature(raw: dict) -> dict:
    """Özellik satırını (symbol, detected_at, üç özellik) sözlüğe çevirir."""
    return {
        "symbol": _sym(raw.get("symbol")),
        "detected_at": _epoch(raw.get("detected_at")),
        "range_pos_60": _f(raw.get("range_pos_60")),
        "pos24": _f(raw.get("pos24")),
        "quote_vol_24h": _f(raw.get("quote_vol_24h")),
    }


# ---------------------------------------------------------------------------
# Birleştirme ve istatistik (saf fonksiyonlar, G/Ç yok)
# ---------------------------------------------------------------------------

def join_features(rows: list[dict], features: list[dict],
                  tol_sec: float = JOIN_TOL_SEC) -> list[dict]:
    """Her satıra, aynı sembolde zamanca en yakın özellik kaydını ekler.

    Eşleşme `tol_sec` saniye içindeyse range_pos_60 / pos24 / quote_vol_24h
    değerleri kopyalanır; aksi halde üçü de None olur. Girdi satırları
    değiştirilmez; yeni sözlükler döner.
    """
    tmp: dict[str, list[tuple[float, dict]]] = {}
    for feat in features:
        t = _epoch(feat.get("detected_at"))
        sym = _sym(feat.get("symbol"))
        if t is None or not sym:
            continue
        tmp.setdefault(sym, []).append((t, feat))
    index: dict[str, tuple[list[float], list[dict]]] = {}
    for sym, items in tmp.items():
        items.sort(key=lambda pair: pair[0])
        index[sym] = ([t for t, _ in items], [feat for _, feat in items])

    out: list[dict] = []
    for row in rows:
        new = dict(row)
        for key in FEATURE_KEYS:
            new[key] = None
        t = _epoch(row.get("detected_at"))
        entry = index.get(_sym(row.get("symbol")))
        if t is not None and entry is not None:
            times, feats = entry
            pos = bisect.bisect_left(times, t)
            best_idx, best_dt = None, None
            for j in (pos - 1, pos):
                if 0 <= j < len(times):
                    dt = abs(times[j] - t)
                    if best_dt is None or dt < best_dt:
                        best_idx, best_dt = j, dt
            if best_idx is not None and best_dt <= tol_sec:
                match = feats[best_idx]
                for key in FEATURE_KEYS:
                    new[key] = _f(match.get(key))
        out.append(new)
    return out


def wilson_ci(successes: int, n: int, z: float = _Z95) -> tuple[Optional[float], Optional[float]]:
    """Wilson güven aralığı (alt, üst). n == 0 ise (None, None) döner."""
    if n <= 0:
        return (None, None)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _summarize(rows: list[dict]) -> dict:
    """Çözümlenmiş satırlar için n, isabet, güven aralığı ve MFE/MAE özetini üretir."""
    n = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    mfe = [r["mfe_pct"] for r in rows if r["mfe_pct"] is not None]
    mae = [r["mae_pct"] for r in rows if r["mae_pct"] is not None]
    ci_low, ci_high = wilson_ci(hits, n)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": (hits / n) if n else None,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "mean_mfe": float(np.mean(mfe)) if mfe else None,
        "median_mfe": float(np.median(mfe)) if mfe else None,
        "mean_mae": float(np.mean(mae)) if mae else None,
    }


def liquidity_edges(values) -> Optional[list[float]]:
    """24s hacim değerlerinden üç eşit-olasılıklı tersil sınırı üretir.

    Dönüş: [min, q1/3, q2/3, nextafter(max)]; üst sınır max değerini de kapsar.
    Değer yoksa None.
    """
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    q1, q2 = np.quantile(vals, [1.0 / 3.0, 2.0 / 3.0])
    return [float(min(vals)), float(q1), float(q2), float(np.nextafter(max(vals), np.inf))]


def bucket_stats(rows: list[dict], key: str, edges: Optional[list[float]] = None,
                 label: Optional[str] = None, names: Optional[list[str]] = None) -> list[dict]:
    """`key` alanına göre [edges[i], edges[i+1]) kovalarını özetler.

    Yalnızca çözümlenmiş (hit bilinen) ve `key` değeri olan satırlar sayılır.
    `edges` verilmezse: quote_vol_24h için veriden tersiller, diğerleri için
    DEFAULT_EDGES kullanılır. Her kova: n, hits, hit_rate, ci_low/ci_high
    (Wilson %95), mean_mfe, median_mfe, mean_mae ve lo/hi/bucket alanlarını taşır.
    """
    label = label or key
    resolved = [r for r in rows if r.get("hit") is not None and r.get(key) is not None]
    if edges is None:
        if key == "quote_vol_24h":
            edges = liquidity_edges([r[key] for r in resolved]) or [0.0, 0.0, 0.0, 0.0]
            names = names or list(TERTILE_LABELS)
        else:
            edges = DEFAULT_EDGES
    edges = [float(e) for e in edges]
    if len(edges) < 2:
        raise ValueError("edges en az iki sınır içermelidir")
    if names is not None and len(names) != len(edges) - 1:
        raise ValueError("names sayısı kova sayısıyla eşleşmelidir")

    out: list[dict] = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        group = [r for r in resolved if lo <= r[key] < hi]
        stats = _summarize(group)
        stats.update(feature=label, lo=lo, hi=hi,
                     bucket=names[i] if names else f"[{lo:g}, {hi:g})")
        out.append(stats)
    return out


def _tertile_index(value: float, edges: list[float]) -> int:
    """Değerin tersil indeksini (0=illikit, 1=orta, 2=likit) bucket_stats ile aynı kuralla bulur."""
    return bisect.bisect_right([edges[1], edges[2]], value)


def continuation_vs_reversal(rows: list[dict], edges: Optional[list[float]] = None) -> dict:
    """Her likidite tersili için devam ve geri dönüş paylarını hesaplar.

    Devam: mfe_pct > |mae_pct|. Geri dönüş: bunun dışındaki satırlar (eşitlik dahil).
    Yalnızca quote_vol_24h, mfe_pct ve mae_pct değeri olan satırlar kullanılır.
    `edges` verilmezse tersiller bu satırların hacminden hesaplanır.
    """
    usable = [r for r in rows
              if r.get("quote_vol_24h") is not None
              and r.get("mfe_pct") is not None and r.get("mae_pct") is not None]
    result = {label: {"n": 0, "continuation_n": 0, "reversal_n": 0,
                      "continuation_share": None, "reversal_share": None}
              for label in TERTILE_LABELS}
    if edges is None:
        edges = liquidity_edges([r["quote_vol_24h"] for r in usable])
    if not edges:
        return result
    for r in usable:
        bucket = result[TERTILE_LABELS[_tertile_index(r["quote_vol_24h"], edges)]]
        bucket["n"] += 1
        if r["mfe_pct"] > abs(r["mae_pct"]):
            bucket["continuation_n"] += 1
        else:
            bucket["reversal_n"] += 1
    for bucket in result.values():
        if bucket["n"]:
            bucket["continuation_share"] = bucket["continuation_n"] / bucket["n"]
            bucket["reversal_share"] = bucket["reversal_n"] / bucket["n"]
    return result


def recommend_cutoff(bucket_rows: list[dict], min_n: int = 30) -> Optional[float]:
    """Geç faz eşiğini önerir.

    Genel isabet = toplam hits / toplam n. Kovalar alt sınıra göre artan sırada
    taranır; n >= min_n ve isabet oranının Wilson üst sınırı genel isabetin
    altındaysa o kovanın alt sınırı döner. Hiçbiri uymazsa None.
    """
    total_n = sum(b["n"] for b in bucket_rows)
    if total_n <= 0:
        return None
    overall = sum(b["hits"] for b in bucket_rows) / total_n
    for b in sorted(bucket_rows, key=lambda item: item["lo"]):
        if b["n"] >= min_n and b["ci_high"] is not None and b["ci_high"] < overall:
            return float(b["lo"])
    return None


def compare_liquidity(quote_buckets: list[dict], min_n: int = 30) -> dict:
    """Likit (son tersil) ile illikit (ilk tersil) isabet oranlarını karşılaştırır.

    Fark, iki kovanın Wilson yarı-genişlik toplamından büyükse "farklı", değilse
    "ayırt edilemiyor". Kovalardan biri min_n'in altındaysa "veri yetersiz".
    """
    illiquid, liquid = quote_buckets[0], quote_buckets[-1]
    if illiquid["n"] < min_n or liquid["n"] < min_n or illiquid["hit_rate"] is None:
        return {"verdict": "veri yetersiz", "diff": None, "half_width_sum": None}
    diff = liquid["hit_rate"] - illiquid["hit_rate"]
    half_sum = ((illiquid["ci_high"] - illiquid["ci_low"]) / 2.0
                + (liquid["ci_high"] - liquid["ci_low"]) / 2.0)
    verdict = "farklı" if abs(diff) > half_sum else "ayırt edilemiyor"
    return {"verdict": verdict, "diff": diff, "half_width_sum": half_sum}


# ---------------------------------------------------------------------------
# Yükleme (G/Ç) ve komut satırı
# ---------------------------------------------------------------------------

def _db_url() -> Optional[str]:
    """DATABASE_URL değerini döner; tanımlı değilse None. Yalnızca main() çağırır."""
    url = os.getenv("DATABASE_URL", "").strip()
    return url or None


def _load_outcomes_db(url: str, since: float) -> list[dict]:
    """unified_candidate_outcomes satırlarını `since` (epoch) sonrası için çeker."""
    import psycopg
    cols = ", ".join(_DB_COLUMNS)
    rows: list[dict] = []
    with psycopg.connect(url, connect_timeout=8) as conn:
        cur = conn.execute(
            f"SELECT {cols} FROM unified_candidate_outcomes "
            "WHERE detected_at >= %s ORDER BY detected_at",
            (since,))
        for record in cur.fetchall():
            rows.append(_normalize_row(dict(zip(_DB_COLUMNS, record))))
    return rows


def load_outcomes_csv(path: str) -> list[dict]:
    """Sonuç CSV'sini okur (BOM'lu UTF-8 dahil)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [_normalize_row(raw) for raw in csv.DictReader(fh)]


def load_features_csv(path: str) -> list[dict]:
    """Özellik CSV'sini okur: symbol, detected_at, range_pos_60, pos24, quote_vol_24h."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [_normalize_feature(raw) for raw in csv.DictReader(fh)]


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{100.0 * x:.1f}%"


def _num(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.3f}"


def _md_table(headers: list[str], body: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _bucket_table(buckets: list[dict]) -> str:
    headers = ["Kova", "n", "İsabet", "%95 GA", "Ort. MFE %", "Medyan MFE %", "Ort. MAE %"]
    body = []
    for b in buckets:
        ci = "-" if b["ci_low"] is None else f"[{_pct(b['ci_low'])}, {_pct(b['ci_high'])}]"
        body.append([b["bucket"], str(b["n"]), _pct(b["hit_rate"]), ci,
                     _num(b["mean_mfe"]), _num(b["median_mfe"]), _num(b["mean_mae"])])
    return _md_table(headers, body)


def _print_overall(rows: list[dict]) -> None:
    resolved = [r for r in rows if r["hit"] is not None]
    stats = _summarize(resolved)
    ci = "-" if stats["ci_low"] is None else f"[{_pct(stats['ci_low'])}, {_pct(stats['ci_high'])}]"
    print("## Genel istatistik")
    print(_md_table(["Toplam satır", "Çözümlenmiş", "İsabet", "%95 GA",
                     "Ort. MFE %", "Medyan MFE %", "Ort. MAE %"],
                    [[str(len(rows)), str(stats["n"]), _pct(stats["hit_rate"]), ci,
                      _num(stats["mean_mfe"]), _num(stats["median_mfe"]),
                      _num(stats["mean_mae"])]]))
    horizons = Counter(_f_label(r["horizon_minutes"]) for r in rows)
    if horizons:
        summary = ", ".join(f"{h} dk: {c}" for h, c in sorted(horizons.items()))
        print(f"\nUfuklar: {summary}. Kovalar tüm ufuklar birlikte hesaplanır.")
    print()


def _f_label(value: Optional[float]) -> str:
    return "bilinmiyor" if value is None else f"{value:g}"


def main(argv: Optional[list[str]] = None) -> int:
    """Komut satırı girişi. Çıkış kodu döner (0 başarı, 1 okuma hatası, 2 kullanım hatası)."""
    parser = argparse.ArgumentParser(
        description="Radar geç faz (range/pos24) ve likidite kova analizi.")
    parser.add_argument("--days", type=float, default=14.0,
                        help="Son kaç gün (varsayılan 14)")
    parser.add_argument("--csv", default=None,
                        help="Sonuç CSV'si; verilmezse DATABASE_URL'den okunur")
    parser.add_argument("--features", default=None,
                        help="symbol,detected_at,range_pos_60,pos24,quote_vol_24h CSV'si")
    parser.add_argument("--min-n", type=int, default=30,
                        help="Bir kovanın karar için gereken en az satır sayısı")
    args = parser.parse_args(argv)

    if args.days <= 0 or args.min_n < 1:
        _err("HATA: --days pozitif ve --min-n en az 1 olmalıdır.")
        return 2

    since = time.time() - args.days * 86400.0
    if args.csv:
        if not os.path.isfile(args.csv):
            _err(f"HATA: sonuç CSV dosyası bulunamadı: {args.csv}")
            return 2
        try:
            rows = load_outcomes_csv(args.csv)
        except Exception as exc:  # noqa: BLE001 - traceback yerine Türkçe mesaj
            _err(f"HATA: sonuç CSV dosyası okunamadı: {exc}")
            return 1
        source = f"CSV ({args.csv})"
    else:
        url = _db_url()
        if not url:
            _err("HATA: DATABASE_URL ortam değişkeni tanımlı değil "
                 "(veya --csv ile dosya verin).")
            return 2
        try:
            rows = _load_outcomes_db(url, since)
        except Exception as exc:  # noqa: BLE001 - traceback yerine Türkçe mesaj
            _err(f"HATA: veritabanından okunamadı: {exc}")
            return 1
        source = "veritabanı (unified_candidate_outcomes)"

    features: Optional[list[dict]] = None
    if args.features:
        if not os.path.isfile(args.features):
            _err(f"HATA: özellik CSV dosyası bulunamadı: {args.features}")
            return 2
        try:
            features = load_features_csv(args.features)
        except Exception as exc:  # noqa: BLE001
            _err(f"HATA: özellik CSV dosyası okunamadı: {exc}")
            return 1

    rows = [r for r in rows if r["detected_at"] is not None and r["detected_at"] >= since]
    print(f"# Radar kova analizi\n\nKaynak: {source} | Pencere: son {args.days:g} gün "
          f"| Minimum n: {args.min_n}\n")
    if not rows:
        print("Analiz edilecek satır yok.")
        return 0
    _print_overall(rows)

    if features is None:
        print("NOT: Geç faz (kova 7) ve likidite (kova 8) analizi için --features CSV'si "
              "gerekir (symbol, detected_at, range_pos_60, pos24, quote_vol_24h). "
              "Bu çalıştırmada yalnızca genel istatistikler gösterilmektedir.")
        return 0

    joined = join_features(rows, features, tol_sec=JOIN_TOL_SEC)
    matched = sum(1 for r in joined if any(r[k] is not None for k in FEATURE_KEYS))
    print(f"Özellik eşleşmesi: {matched}/{len(joined)} satır (±{JOIN_TOL_SEC:g} s).\n")

    range_buckets = bucket_stats(joined, "range_pos_60", DEFAULT_EDGES, "range_pos_60")
    pos24_buckets = bucket_stats(joined, "pos24", DEFAULT_EDGES, "pos24")
    quote_edges = liquidity_edges(
        [r["quote_vol_24h"] for r in joined
         if r["quote_vol_24h"] is not None and r["hit"] is not None]) or [0.0, 0.0, 0.0, 0.0]
    quote_buckets = bucket_stats(joined, "quote_vol_24h", quote_edges, "quote_vol_24h",
                                 names=list(TERTILE_LABELS))
    cvr = continuation_vs_reversal(joined, edges=quote_edges)

    print("## (a) range_pos_60 kovaları (60 bar aralık konumu)\n")
    print(_bucket_table(range_buckets) + "\n")
    print("## (b) pos24 kovaları (24s aralık konumu)\n")
    print(_bucket_table(pos24_buckets) + "\n")
    print("## (c) Likidite tersilleri (quote_vol_24h)\n")
    print(f"Hacim sınırları: illikit < {quote_edges[1]:,.0f} <= orta < "
          f"{quote_edges[2]:,.0f} <= likit\n")
    print(_bucket_table(quote_buckets) + "\n")
    cvr_body = []
    for label in TERTILE_LABELS:
        c = cvr[label]
        cvr_body.append([label, str(c["n"]), _pct(c["continuation_share"]),
                         _pct(c["reversal_share"])])
    print(_md_table(["Tersil", "n", "Devam (MFE > |MAE|)", "Geri dönüş"], cvr_body) + "\n")

    cut_range = recommend_cutoff(range_buckets, args.min_n)
    cut_pos24 = recommend_cutoff(pos24_buckets, args.min_n)
    cutoff_parts = []
    if cut_range is not None:
        cutoff_parts.append(f"range_pos_60 >= {cut_range:.2f}")
    if cut_pos24 is not None:
        cutoff_parts.append(f"pos24 >= {cut_pos24:.2f}")
    cutoff_text = " | ".join(cutoff_parts) if cutoff_parts else "veri yetersiz"
    liq = compare_liquidity(quote_buckets, args.min_n)
    if liq["diff"] is None:
        liq_text = "veri yetersiz"
    else:
        liq_text = (f"{liq['verdict']} (likit - illikit isabet farkı "
                    f"{100 * liq['diff']:+.1f} puan, yarı-GA toplamı "
                    f"{100 * liq['half_width_sum']:.1f} puan)")
    print("ÖNERİ:")
    print(f"- Geç faz eşiği: {cutoff_text}")
    print(f"- Likit vs illikit: {liq_text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
