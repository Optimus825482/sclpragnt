"""N7 saatlik otomatik tarama: sıra 1-2 push (skor > eşik) ve saat başı hesabı (2026-10-26)."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import n7_scan_job  # noqa: E402
from app.config import config  # noqa: E402
from app import database  # noqa: E402
from app.routers import auto_paper, monitoring  # noqa: E402


def _rows(*scores):
    return {"picked": [{"sym": f"C{i}TRY", "px": 1.5, "score": s} for i, s in enumerate(scores, start=1)]}


class _Sink:
    """2026-10-28 tek teslim kuralı: push sonrası kayıt / uygulama içi yayın / otonom paper çağrılarını toplar."""

    def __init__(self, monkeypatch):
        self.saved, self.broadcasts, self.papers = [], [], []

        async def save(rows):
            self.saved.extend(rows)

        async def broadcast(msg):
            self.broadcasts.append(msg)

        async def paper(notif):
            self.papers.append(notif)
            return {"trade_id": 7}

        class _Ws:
            pass
        ws = _Ws()
        ws.broadcast = broadcast
        monkeypatch.setattr(database, "save_monitoring_notifications", save)
        monkeypatch.setattr(monitoring, "ws_manager", ws)
        monkeypatch.setattr(auto_paper, "try_open_from_notification", paper)
        monkeypatch.setitem(monitoring._monitoring_state, "history", [])


def _setup(monkeypatch, *, enabled=True, quiet=False, vapid=True, ok=True):
    sent = []
    _setup.sink = _Sink(monkeypatch)

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

    sink = _Sink(monkeypatch)
    monkeypatch.setattr(monitoring, "get_user_notification_settings", settings)
    monkeypatch.setattr(monitoring, "_in_quiet_hours", lambda s: False)
    monkeypatch.setattr(monitoring, "_vapid_configured", lambda: True)
    monkeypatch.setattr(monitoring, "_send_push", send)
    monkeypatch.setattr(config, "N7_PUSH_MIN_SCORE", 10.0, raising=False)
    monkeypatch.setattr(config, "N7_PUSH_TOP", 2, raising=False)
    assert asyncio.run(n7_scan_job.push_top(_rows(20.0, 15.0))) == 0
    assert len(sent) == 2
    assert all(s["push_skip_reason"] == "daily_symbol_limit" for s in sent)
    # Push gitmedi → kayıt, uygulama içi bildirim ve otonom paper YOK.
    assert sink.saved == [] and sink.broadcasts == [] and sink.papers == []
    assert monitoring._monitoring_state["history"] == []


def test_delivered_push_records_shows_in_app_and_opens_paper(monkeypatch):
    sent = _setup(monkeypatch)
    sink = _setup.sink
    assert asyncio.run(n7_scan_job.push_top(_rows(15.0))) == 1
    notif = sent[0]
    assert notif["sent_via_push"] is True and notif["push_attempted"] is True
    assert notif["mode"] == "n7" and notif["source"] == "n7"
    assert notif["notification_key"] == f"monitoring-C1TRY-{int(notif['detected_at'])}"
    assert sink.saved == [notif]
    assert sink.broadcasts == [{"type": "monitoring_alert", "data": [notif]}]
    assert sink.papers == [notif]
    assert monitoring._monitoring_state["history"][0] is notif


def test_failed_push_creates_nothing_in_app(monkeypatch):
    _setup(monkeypatch, ok=False)
    sink = _setup.sink
    assert asyncio.run(n7_scan_job.push_top(_rows(15.0, 14.0))) == 0
    assert sink.saved == [] and sink.broadcasts == [] and sink.papers == []


def test_n7_is_rule_signal_with_own_switch():
    assert "n7" in auto_paper._RULE_SIGNAL_SOURCES
    assert auto_paper._RULE_SIGNAL_SWITCHES["n7"] == "N7_AUTO_PAPER_ENABLED"
    assert hasattr(config, "N7_AUTO_PAPER_ENABLED")


def test_empty_result():
    assert asyncio.run(n7_scan_job.push_top(None)) == 0
    assert asyncio.run(n7_scan_job.push_top({"picked": []})) == 0


def test_seconds_until_next_hour():
    assert n7_scan_job.seconds_until_next_hour(3600.0 * 5) == 3600.0
    assert n7_scan_job.seconds_until_next_hour(3600.0 * 5 + 1) == 3599.0
    assert abs(n7_scan_job.seconds_until_next_hour(3600.0 * 5 + 3599.5) - 0.5) < 1e-6
