"""Gölge kural kaydını GEÇMİŞ bildirimlerden doldurur (2026-10-17).

Canlı sistem `notification_shadow` tablosuna (migration 022) yalnız bugünden itibaren yazıyor. Ölçüm için
beklememek adına, `monitoring_notifications` geçmişinde gölge kurala (şu an: ≥2 farklı kaynak ∧ mod =
trend_devam; `notification_policy.shadow_match`) uyan her bildirim, BUGÜNKÜ canlı politikanın vereceği
kararla (`notification_policy.evaluate`, teyit kuralı açık) birlikte yazılır. Tekrar yazım yok
(ON CONFLICT DO NOTHING: aynı sembol + zaman + kural).

Not: geçmiş satırların `sources` alanı bazı dönemlerde NULL'dur (2026-09-26 → 10-11 arası ve LLM modu);
bunlar kurala uyamaz ve atlanır. Panel satırları da (eski sistem) aday oldukları için dahil edilir.

Kullanım (backend/):
  DATABASE_URL=... python scripts/backfill_notification_shadow.py [--since 2026-09-17] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TZ = timezone(timedelta(hours=3))


def build_rows(records: list[dict]) -> list[dict]:
    """Saf: geçmiş bildirim satırları → gölge kayıt satırları (canlı teyit kuralı AÇIK kabul edilir)."""
    from unittest import mock

    from app import notification_policy as np_
    from app.config import config
    with mock.patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", True), \
            mock.patch.object(config, "RADAR_NOTIFY_SHADOW_RULE_ENABLED", True):
        return np_.shadow_rows(records)


def load_records(db_url: str, since_ts: float) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row
    sql = ("SELECT symbol, price, target_pct, expected_price, horizon_minutes, mode, sources, score, detected_at "
           "FROM monitoring_notifications WHERE detected_at >= %s ORDER BY detected_at")
    with psycopg.connect(db_url, connect_timeout=10, row_factory=dict_row) as conn:
        return [dict(r) for r in conn.execute(sql, (since_ts,)).fetchall()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2026-09-17")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL gerekli", file=sys.stderr)
        return 2
    since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=TZ).timestamp()
    records = load_records(db_url, since)
    rows = build_rows(records)
    passed = sum(1 for r in rows if not r["live_blocked_reason"])
    print(f"[shadow] geçmiş bildirim {len(records)}, gölge kurala uyan {len(rows)} "
          f"(bugünkü canlı kuralla gidecek {passed}, kesilecek {len(rows) - passed})")
    reasons: dict[str, int] = {}
    for r in rows:
        if r["live_blocked_reason"]:
            key = r["live_blocked_reason"].split(" (")[0]
            reasons[key] = reasons.get(key, 0) + 1
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  kesilme nedeni: {k}: {v}")
    if args.dry_run or not rows:
        return 0
    from app import database
    written = asyncio.run(database.save_notification_shadow(rows))
    print(f"[shadow] yazılan {written} (tekrarlar atlandı)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
