"""N7 saatlik otomatik tarama: sıra 1-2 push (skor > eşik) ve saat başı hesabı (2026-10-26)."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import n7_scan_job  # noqa: E402
from app.config import config  # noqa: E402
from app.routers import monitoring  # noqa: E402


def _rows(*scores):
    return {"picked": [{"sym": f"C{i}TRY", "px": 1.5, "score": s} for i, s in enumerate(scores, start=1)]}


def _setup(monkeypatch, *, enabled=True, quiet=False, vapid=True, ok=True):
    sent = []

    async def settings():
        return {"enabled": enabled}

    async def send(notif):
        sent.append(notif)
        return ok

    monkeypatch.setattr(monitoring, "get_user_notification_settings", settings)
    monkeypatch.setattr(monitoring, "_in_quiet_hours", lambda s: quiet)
    monkeypatch.setattr(monitoring, "_vapid_configured", lambda: vapid)
    monkeypatch.setattr(monitoring, "_send_push", send)
    monkeypatch.setattr(config, "N7_PUSH_MIN_SCORE", 10.0, raising=False)
    monkeypatch.setattr(config, "N7_PUSH_TOP", 2, raising=False)
    return sent


def test_rank1_and_2_pushed(monkeypatch):
    sent = _setup(monkeypatch)
    n = asyncio.run(n7_scan_job.push_top(_rows(15.0, 12.5, 30.0)))
    assert n == 2
    assert [s["symbol"] for s in sent] == ["C1TRY", "C2TRY"]
    assert sent[0]["title"] == "🚀 C1TRY · N7 #1 · skor 15.0"
    assert sent[1]["url"] == "/charts?symbol=C2TRY&timeframe=15m"
    assert sent[0]["tag"] == "n7-C1TRY" and sent[0]["source"] == "n7" and sent[0]["horizon_minutes"] == 60


def test_score_exactly_threshold_not_pushed(monkeypatch):
    sent = _setup(monkeypatch)
    n = asyncio.run(n7_scan_job.push_top(_rows(10.0, 11.0)))
    assert n == 1
    assert [s["symbol"] for s in sent] == ["C2TRY"]
    assert sent[0]["title"].startswith("🚀 C2TRY · N7 #2")


def test_rank3_never_backfilled(monkeypatch):
    sent = _setup(monkeypatch)
    n = asyncio.run(n7_scan_job.push_top(_rows(5.0, 4.0, 99.0)))
    assert n == 0 and sent == []


def test_disabled_settings_and_quiet_and_no_vapid(monkeypatch):
    for kw in ({"enabled": False}, {"quiet": True}, {"vapid": False}):
        sent = _setup(monkeypatch, **kw)
        assert asyncio.run(n7_scan_job.push_top(_rows(20.0, 20.0))) == 0
        assert sent == []


def test_daily_limit_not_counted(monkeypatch):
    sent = []

    async def send(notif):
        # Günlük sembol sınırı: push atlanır, zarfa neden işaretlenir (gerçek _send_push davranışı).
        sent.append(notif)
        notif["push_skip_reason"] = "daily_symbol_limit"
        return False

    async def settings():
        return {"enabled": True}

    monkeypatch.setattr(monitoring, "get_user_notification_settings", settings)
    monkeypatch.setattr(monitoring, "_in_quiet_hours", lambda s: False)
    monkeypatch.setattr(monitoring, "_vapid_configured", lambda: True)
    monkeypatch.setattr(monitoring, "_send_push", send)
    monkeypatch.setattr(config, "N7_PUSH_MIN_SCORE", 10.0, raising=False)
    monkeypatch.setattr(config, "N7_PUSH_TOP", 2, raising=False)
    assert asyncio.run(n7_scan_job.push_top(_rows(20.0, 15.0))) == 0
    assert len(sent) == 2
    assert all(s["push_skip_reason"] == "daily_symbol_limit" for s in sent)


def test_empty_result():
    assert asyncio.run(n7_scan_job.push_top(None)) == 0
    assert asyncio.run(n7_scan_job.push_top({"picked": []})) == 0


def test_seconds_until_next_hour():
    assert n7_scan_job.seconds_until_next_hour(3600.0 * 5) == 3600.0
    assert n7_scan_job.seconds_until_next_hour(3600.0 * 5 + 1) == 3599.0
    assert abs(n7_scan_job.seconds_until_next_hour(3600.0 * 5 + 3599.5) - 0.5) < 1e-6
