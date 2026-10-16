"""BTC rejim kalkanı (ve diğer kapılar) ölçümü: engellenen adaylar sonradan hedefe ulaştı mı?

Soru: `BTC_BEAR_REGIME_SHIELD` bildirimleri durdururken, engellenen adaylar KAÇIRILAN fırsat mıydı
yoksa kalkan haklı mıydı? Veri: `unified_candidate_outcomes` (`blocked_by` kolonu, migration 016).

ÖN KAYITLI KARAR KURALI (veri görülmeden sabitlendi — docs/DENEY_KAYDI.md):
  her iki grupta (geçen / kalkan) n >= min_n iken
    hit(kalkan) >= hit(geçen) - 5 puan   -> KALKAN_FAZLA_SIKI   (yumuşatma adayı)
    hit(kalkan) <  hit(geçen) - 10 puan  -> KALKAN_ISE_YARIYOR  (olduğu gibi bırak)
    aksi                                  -> BELIRSIZ
  yetersiz n -> YETERSIZ_VERI
Bu betik KARAR VERMEZ; kuralı uygular ve sayıları gösterir. Kalkan yumuşatma ayrı bir değişikliktir.

`blocked_by`: '' = kapıdan geçti · dolu = engel nedeni · NULL = eski satır (kayıt öncesi; DIŞLANIR).

Kullanım (backend/ içinden):
    DATABASE_URL=postgresql://... python scripts/radar_shield_analysis.py --days 14
    python scripts/radar_shield_analysis.py --csv journal.csv --min-n 30
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts.radar_lift_analysis import _to_bool, wilson_interval  # noqa: E402

# 2026-10-17: "shield_badge" = RADAR_SHIELD_MODE=badge ile kalkan açıkken ROZETLE GİDEN bildirimler
# (blocked_by='' ama regime_badge dolu); "passed" artık yalnız kalkan kapalıyken geçenler.
GROUPS = ("passed", "shield_badge", "shield", "layer1", "other_gate")
DEFAULT_MIN_N = 30
TIGHT_MARGIN = 0.05     # hit(kalkan) >= hit(geçen) - 5 puan  -> fazla sıkı
WORKING_MARGIN = 0.10   # hit(kalkan) <  hit(geçen) - 10 puan -> işe yarıyor


def classify_block(raw: Any, regime_badge: Any = None) -> str:
    """blocked_by -> grup. None = eski satır ('legacy'), '' = geçti ('passed'; rozetliyse 'shield_badge')."""
    if raw is None:
        return "legacy"
    text = str(raw).strip()
    if not text:
        return "shield_badge" if str(regime_badge or "").strip() else "passed"
    if text == "BTC_BEAR_REGIME_SHIELD":
        return "shield"
    if text.startswith("master_surge_katman1"):
        return "layer1"
    return "other_gate"


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _blocked_value(row: dict) -> Any:
    """CSV'de boş hücre '' gelir (geçti); DB'de NULL None gelir (eski). Anahtar yoksa eski sayılır."""
    if "blocked_by" not in row:
        return None
    return row["blocked_by"]


def _empty_group() -> dict:
    return {"n": 0, "hits": 0, "hit_rate": None, "ci": None, "mean_mfe": None, "mean_mae": None}


def compute_shield_report(rows: list[dict], min_n: int = DEFAULT_MIN_N) -> dict:
    """Grup başına n, isabet, Wilson aralığı, ortalama MFE/MAE; ufuk kırılımı; eski satır sayısı."""
    legacy = 0
    acc: dict[str, list[tuple[bool, float | None, float | None, int]]] = {g: [] for g in GROUPS}
    for row in rows:
        group = classify_block(_blocked_value(row), row.get("regime_badge"))
        if group == "legacy":
            legacy += 1
            continue
        hit = _to_bool(row.get("hit"))
        if hit is None:  # ölçülmemiş satır
            continue
        try:
            horizon = int(float(row.get("horizon_minutes") or 0))
        except (TypeError, ValueError):
            horizon = 0
        acc[group].append((hit, _float(row.get("mfe_pct")), _float(row.get("mae_pct")), horizon))

    def summarize(items: list[tuple[bool, float | None, float | None, int]]) -> dict:
        out = _empty_group()
        n = len(items)
        if not n:
            return out
        hits = sum(1 for it in items if it[0])
        mfes = [it[1] for it in items if it[1] is not None]
        maes = [it[2] for it in items if it[2] is not None]
        out.update(n=n, hits=hits, hit_rate=hits / n, ci=wilson_interval(hits, n),
                   mean_mfe=(sum(mfes) / len(mfes)) if mfes else None,
                   mean_mae=(sum(maes) / len(maes)) if maes else None)
        return out

    report: dict[str, Any] = {g: summarize(acc[g]) for g in GROUPS}
    report["legacy_excluded"] = legacy
    report["min_n"] = min_n
    horizons = sorted({it[3] for g in ("passed", "shield") for it in acc[g]})
    report["by_horizon"] = {
        h: {g: summarize([it for it in acc[g] if it[3] == h]) for g in ("passed", "shield")}
        for h in horizons
    }
    return report


def verdict(report: dict, min_n: int = DEFAULT_MIN_N) -> str:
    """Ön kayıtlı karar kuralını uygular (bkz. modül başı)."""
    passed = report["passed"]
    # 2026-10-17: badge modunda kalkan satırı üretilmez; kıyas rozetle geçenlerle (kalkan açıkken giden) yapılır.
    shield = report["shield"] if report["shield"].get("n", 0) >= min_n else report.get("shield_badge", report["shield"])
    if passed["n"] < min_n or shield["n"] < min_n:
        return "YETERSIZ_VERI"
    diff = shield["hit_rate"] - passed["hit_rate"]
    if diff >= -TIGHT_MARGIN:
        return "KALKAN_FAZLA_SIKI"
    if diff < -WORKING_MARGIN:
        return "KALKAN_ISE_YARIYOR"
    return "BELIRSIZ"


# ------------------------------------------------------------ veri yükleme

def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL ortam değişkeni tanımlı değil "
                           "(örn. postgresql://kullanici:sifre@host:5432/scalper)")
    return url


def _load_from_db(url: str, days: float) -> list[dict]:
    import psycopg

    since = time.time() - days * 86400.0
    cols = ("blocked_by", "hit", "mfe_pct", "mae_pct", "horizon_minutes", "detected_at", "regime_badge")
    sql = (f"SELECT {', '.join(cols)} FROM unified_candidate_outcomes "
           "WHERE outcome_filled_at IS NOT NULL AND detected_at >= %s ORDER BY detected_at")
    with psycopg.connect(url, connect_timeout=8) as conn:
        rows = conn.execute(sql, (since,)).fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _load_from_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------ çıktı

def _pct(v: float | None) -> str:
    return "-" if v is None else f"{100.0 * v:.1f}"


def _num(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f}"


def _row_md(name: str, g: dict) -> str:
    ci = "-" if not g["ci"] else f"[{100 * g['ci'][0]:.1f}, {100 * g['ci'][1]:.1f}]"
    return f"| {name} | {g['n']} | {_pct(g['hit_rate'])} | {ci} | {_num(g['mean_mfe'])} | {_num(g['mean_mae'])} |"


def _print_report(report: dict, label: str, min_n: int) -> None:
    print("# BTC rejim kalkanı ölçümü")
    print(f"Kaynak: {label} | min_n: {min_n} | eski satır (blocked_by NULL, dışlandı): {report['legacy_excluded']}")
    print()
    print("| Grup | n | hit % | 95% CI | ort. MFE % | ort. MAE % |")
    print("|---|---:|---:|---|---:|---:|")
    names = {"passed": "geçti (bildirim, kalkan kapalı)", "shield_badge": "rozetle geçti (kalkan açık, RADAR_SHIELD_MODE=badge)",
             "shield": "kalkan (BTC_BEAR_REGIME_SHIELD, block modu)",
             "layer1": "katman 1 (likidite)", "other_gate": "diğer kapılar"}
    for g in GROUPS:
        print(_row_md(names[g], report[g]))
    if report["by_horizon"]:
        print()
        print("## Ufuk kırılımı (geçti vs kalkan)")
        print("| Ufuk (dk) | n geçti | hit % geçti | n kalkan | hit % kalkan |")
        print("|---:|---:|---:|---:|---:|")
        for h, d in report["by_horizon"].items():
            print(f"| {h} | {d['passed']['n']} | {_pct(d['passed']['hit_rate'])} "
                  f"| {d['shield']['n']} | {_pct(d['shield']['hit_rate'])} |")
    print()
    print(f"## Karar (ön kayıtlı kural): {verdict(report, min_n)}")
    print("Not: bu kural yalnız isabet oranına bakar; yumuşatma kararı öncesi maliyet ve MAE de incelenmeli.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BTC rejim kalkanı ölçümü (engellenen adaylar hedefe ulaştı mı?)")
    ap.add_argument("--days", type=float, default=14.0, help="DB'den son N gün (varsayılan 14)")
    ap.add_argument("--min-n", type=int, default=DEFAULT_MIN_N, help="grup başına minimum örnek (varsayılan 30)")
    ap.add_argument("--csv", help="DB yerine CSV (sütunlar: blocked_by,hit,mfe_pct,mae_pct,horizon_minutes)")
    args = ap.parse_args(argv)
    if args.csv:
        rows, label = _load_from_csv(args.csv), f"csv:{args.csv}"
    else:
        rows, label = _load_from_db(_db_url(), args.days), f"db (son {args.days:g} gün)"
    _print_report(compute_shield_report(rows, args.min_n), label, args.min_n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
