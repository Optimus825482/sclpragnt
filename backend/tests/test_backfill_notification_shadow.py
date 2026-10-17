"""2026-10-17: gölge kural geçmiş doldurma — saf satır üretimi."""
from scripts.backfill_notification_shadow import build_rows


def test_only_shadow_matches_with_live_decision():
    recs = [
        {"symbol": "ERATRY", "mode": "trend_devam", "sources": '["velocity","jump"]', "detected_at": 10.0,
         "price": 3.4, "target_pct": 2.5, "horizon_minutes": 15, "score": 90},
        {"symbol": "ATRY", "mode": "trend_devam", "sources": '["jump","early"]', "detected_at": 11.0},
        {"symbol": "BTRY", "mode": "unified", "sources": '["velocity","jump"]', "detected_at": 12.0},
        {"symbol": "CTRY", "mode": "trend_devam", "sources": None, "detected_at": 13.0},
        {"symbol": "DTRY", "mode": "trend_devam", "sources": '["velocity"]', "detected_at": 14.0},
    ]
    rows = build_rows(recs)
    assert [r["symbol"] for r in rows] == ["ERATRY", "ATRY"]
    assert rows[0]["live_blocked_reason"] == ""                       # canlıda da giderdi
    assert rows[1]["live_blocked_reason"].startswith("teyit kuralı")  # velocity yok → canlıda kesilir
    assert all(r["shadow_rule"] == "ge2_trend_devam" for r in rows)
