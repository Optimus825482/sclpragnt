"""Sinyal İzleme yalnız süper tarama işlemlerini sayar (2026-11-25)."""
from app.config import config
from app.routers import signal_insights
from app import super_scan_notify


def test_default_flag_on():
    assert config.SIGNAL_INSIGHTS_SUPER_ONLY is True


def test_clause_applied_by_default():
    clause = signal_insights._super_clause()
    assert "notification_key like 'super:%'" in clause


def test_clause_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "SIGNAL_INSIGHTS_SUPER_ONLY", False)
    assert signal_insights._super_clause() == ""


def test_envelope_sets_super_notification_key():
    notif = super_scan_notify._envelope({
        "symbol": "AAA_TRY", "super_score": 80.0, "score": 70, "price": 1.0,
        "target_pct": 3.0, "horizon_minutes": 15, "sources": ["velocity"],
    })
    assert notif["notification_key"] == "super:AAA_TRY"
