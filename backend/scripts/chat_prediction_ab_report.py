"""Chat tahmin A/B raporu — prompt_version bazlı isabet karşılaştırması.

SORU: `llm_forecasts` journal'ında farklı prompt aileleri (ör. DENEY_KAYDI
2026-11-10: `fast-risers-v1` [fast_rise_brief'li] vs `upside-scout-%`
[bağlamsız harman]) ölçülmüş isabet ve getiri açısından nasıl ayrışıyor?

ÖLÇÜ (salt-okunur; `llm_forecasts`):
  * n / evaluated       : toplam ve değerlendirilmiş tahmin sayısı.
  * hit %               : `direction_correct` (kanonik label_policy etiketi,
                          maliyet+ATR farkındalıklı min_move eşiği).
  * ort. sonuç getirisi : `outcome_return_pct` (brüt; maliyet dahil DEĞİL).
  * ort. MFE / MAE      : ufuk içi en iyi / en kötü hareket.
  * medyan ufuk         : horizon_minutes.

DİKKAT: Bu rapor işlem EV'si DEĞİLDİR — yön isabeti + brüt getiridir.
Karar için en az 2 hafta ve yeterli n gerekir (bkz. docs/DENEY_KAYDI.md
2026-11-10 satırı; "Karar" kuralı: min 2 haftalık journal verisi).

KULLANIM (backend klasöründen, DATABASE_URL gerekir):
    PYTHONIOENCODING=utf-8 python scripts/chat_prediction_ab_report.py --days 14
    PYTHONIOENCODING=utf-8 python scripts/chat_prediction_ab_report.py --days 14 --out rapor.md
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3))  # İstanbul (DST yok)

# DENEY_KAYDI 2026-11-10 A/B çifti: brief'li yeni yol vs mevcut scout harmanı.
AB_PAIR = ("fast-risers-%", "upside-scout-%")

_FORECAST_SQL = (
    "SELECT prompt_version, status, direction_correct::float8, outcome_return_pct::float8, "
    "max_favorable_pct::float8, max_adverse_pct::float8, created_at::float8, horizon_minutes "
    "FROM llm_forecasts WHERE created_at >= %s ORDER BY created_at ASC"
)


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        sys.exit("HATA: DATABASE_URL ortam değişkeni tanımlı değil "
                 "(örn. postgresql://kullanici:sifre@host:5432/scalper)")
    return url


def load_rows(conn, since_ts: float) -> list[dict]:
    rows = conn.execute(_FORECAST_SQL, (since_ts,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "prompt_version": str(r[0] or ""), "status": str(r[1] or ""),
            "direction_correct": r[2], "outcome_return_pct": r[3],
            "max_favorable_pct": r[4], "max_adverse_pct": r[5],
            "created_at": r[6], "horizon_minutes": r[7],
        })
    return out


def aggregate(rows: list[dict]) -> dict:
    evaluated = [r for r in rows if r["status"] == "evaluated"]
    hits = [r for r in evaluated if r["direction_correct"]]
    rets = [float(r["outcome_return_pct"]) for r in evaluated if r["outcome_return_pct"] is not None]
    mfe = [float(r["max_favorable_pct"]) for r in evaluated if r["max_favorable_pct"] is not None]
    mae = [float(r["max_adverse_pct"]) for r in evaluated if r["max_adverse_pct"] is not None]
    horizons = [int(r["horizon_minutes"] or 0) for r in rows if r["horizon_minutes"]]
    return {
        "n": len(rows), "evaluated": len(evaluated),
        "hit_pct": (100.0 * len(hits) / len(evaluated)) if evaluated else None,
        "avg_ret_pct": (statistics.fmean(rets) if rets else None),
        "avg_mfe_pct": (statistics.fmean(mfe) if mfe else None),
        "avg_mae_pct": (statistics.fmean(mae) if mae else None),
        "median_horizon": (statistics.median(horizons) if horizons else None),
        "last_created_at": max((r["created_at"] for r in rows), default=None),
    }


def _fmt_cell(value, fmt="{:.1f}") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return fmt.format(value)
    return str(value)


def generate_report(rows: list[dict], since_ts: float, days: int) -> tuple[str, dict]:
    """Saf: satırlar -> (markdown, özet). DB'ye dokunmaz."""
    by_version: dict[str, list[dict]] = {}
    for r in rows:
        by_version.setdefault(r["prompt_version"], []).append(r)
    stats = {v: aggregate(rs) for v, rs in by_version.items()}

    md: list[str] = []
    md.append(f"# Chat tahmin A/B raporu ({datetime.fromtimestamp(since_ts, TZ):%Y-%m-%d} .. "
              f"bugün, son {days} gün, İstanbul)")
    md.append("")
    md.append("Kaynak: `llm_forecasts` (salt-okunur). Hit = `direction_correct` "
              "(kanonik label_policy eşiği). Getiriler BRÜTTÜR — maliyet (~%0.35 gidiş-dönüş) "
              "dahil değildir; EV yorumu yapılmaz.")
    md.append("")
    md.append("## A/B çifti (DENEY_KAYDI 2026-11-10)")
    md.append("")
    md.append("| prompt_version | n | evaluated | hit % | ort. getiri % | ort. MFE % | ort. MAE % | medyan ufuk dk |")
    md.append("|---|---|---|---|---|---|---|---|")
    summary = {"window_days": days, "versions": {}}
    for pattern in AB_PAIR:
        matches = {v: s for v, s in stats.items()
                   if (pattern.endswith("-%") and (v.startswith(pattern[:-2]) or v == pattern[:-2]))
                   or v == pattern}
        if not matches:
            md.append(f"| `{pattern}` | 0 | 0 | — | — | — | — | — |")
            continue
        for v, s in sorted(matches.items()):
            md.append(f"| `{v}` | {s['n']} | {s['evaluated']} | {_fmt_cell(s['hit_pct'])} | "
                      f"{_fmt_cell(s['avg_ret_pct'], '{:.3f}')} | {_fmt_cell(s['avg_mfe_pct'], '{:.3f}')} | "
                      f"{_fmt_cell(s['avg_mae_pct'], '{:.3f}')} | {_fmt_cell(s['median_horizon'], '{:.0f}')} |")
            summary["versions"][v] = s
    md.append("")
    md.append("## Tüm prompt aileleri")
    md.append("")
    md.append("| prompt_version | n | evaluated | hit % | ort. getiri % | medyan ufuk dk | son kayıt |")
    md.append("|---|---|---|---|---|---|---|")
    for v in sorted(stats, key=lambda k: -stats[k]["n"]):
        s = stats[v]
        last = (datetime.fromtimestamp(s["last_created_at"], TZ).strftime("%m-%d %H:%M")
                if s["last_created_at"] else "—")
        md.append(f"| `{v}` | {s['n']} | {s['evaluated']} | {_fmt_cell(s['hit_pct'])} | "
                  f"{_fmt_cell(s['avg_ret_pct'], '{:.3f}')} | {_fmt_cell(s['median_horizon'], '{:.0f}')} | {last} |")
        if v not in summary["versions"]:
            summary["versions"][v] = s
    md.append("")
    md.append("## Uyarılar")
    md.append("")
    md.append("- `n` ve `evaluated` küçükse yön yoktur; DENEY_KAYDI kuralı: en az 2 hafta + "
              "sembol-dışı-bırakma kontrolü.")
    md.append("- `fast-risers-v1` yalnız `POST /api/llm/fast-risers` düğmesi çağrıldığında birikir; "
              "chat lane'inin kendi ölçümü `chat_predictions`'tadır (bkz. rapor sekmesi).")
    md.append("- Ort. getiri brüttür; pozitif bile görünse maliyet sonrası EV'yi ima ETMEZ.")
    md.append("")
    return "\n".join(md), summary


def main() -> int:
    parser = argparse.ArgumentParser(description="llm_forecasts prompt_version A/B raporu")
    parser.add_argument("--days", type=int, default=14, help="geriye dönük pencere (gün)")
    parser.add_argument("--out", type=str, default=None, help="markdown çıktı dosyası (yoksa stdout)")
    parser.add_argument("--json", action="store_true", help="özet JSON da yaz")
    args = parser.parse_args()

    url = _db_url()
    since_ts = (datetime.now(tz=TZ) - timedelta(days=args.days)).timestamp()
    import psycopg  # import anında değil, main'de (script düzeni)

    with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
        rows = load_rows(conn, since_ts)
    md, summary = generate_report(rows, since_ts, args.days)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md + "\n")
        print(f"rapor yazıldı: {args.out}")
    else:
        print(md)
    if args.json:
        json_path = (args.out or "chat_ab_rapor") + ".json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)
        print(f"özet yazıldı: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
