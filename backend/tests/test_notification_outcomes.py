"""Bildirimlerin KENDİ sonuç ölçümü (candidate_id'si olmayan, ör. Global lead-lag bildirimleri).

Sorun (2026-10-16, canlı veritabanı kopyasında ölçüldü): 13 Ekim'den beri bildirimlerin ~%65-70'i
`candidate_id` olmadan yazılıyor (global_lead_lag.py bildirimi doğrudan kaydeder). Sonucu hiç
eşleşmediği için başarı KPI'ı bu bildirimleri sayamıyordu.

Güvenlik: ölçüm `velocity_candidates`'a YAZMAZ (sembol kalite filtresini ve hedef öğrenmeyi beslerdi);
yalnız bildirimin kendi sütunlarına (outcome_status/mfe_pct/mae_pct) yazar ve yalnız RAPOR ucu okur.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

from app import database
from app.notification_outcomes import (
    STATUS_HIT,
    STATUS_NO_DATA,
    STATUS_TIMEOUT,
    apply_own_outcome,
    outcome_from_window,
)


def _bar(high, low):  # [open_time, open, high, low, close]
    return [0, 100.0, high, low, 100.0]


# ------------------------------------------------------------------ outcome_from_window

def test_hit_when_mfe_reaches_target():
    out = outcome_from_window([_bar(101.0, 99.5), _bar(103.2, 100.0)], entry=100.0, target_pct=3.0)
    assert out["status"] == STATUS_HIT
    assert out["mfe_pct"] == pytest.approx(3.2)
    assert out["mae_pct"] == pytest.approx(-0.5)


def test_timeout_when_target_not_reached():
    out = outcome_from_window([_bar(101.0, 99.0)], entry=100.0, target_pct=3.0)
    assert out["status"] == STATUS_TIMEOUT
    assert out["mfe_pct"] == pytest.approx(1.0)


def test_mae_is_never_positive():
    out = outcome_from_window([_bar(102.0, 100.5)], entry=100.0, target_pct=5.0)
    assert out["mae_pct"] == 0.0           # fiyat girişin altına hiç inmedi


def test_empty_window_or_bad_entry_returns_none():
    assert outcome_from_window([], entry=100.0, target_pct=2.0) is None
    assert outcome_from_window([_bar(101, 99)], entry=0.0, target_pct=2.0) is None


# ------------------------------------------------------------------ apply_own_outcome

def _row(**kw):
    base = {"candidate_status": None, "mfe_pct": None, "touched_target": None, "target_pct": 3.0,
            "outcome_status": None, "own_mfe_pct": None}
    base.update(kw)
    return base


def test_fallback_applies_when_no_candidate_match():
    row = _row(outcome_status=STATUS_HIT, own_mfe_pct=3.4)
    assert apply_own_outcome(row) is True
    assert row["candidate_status"] == "evaluated"
    assert row["mfe_pct"] == pytest.approx(3.4)
    assert row["touched_target"] is True


def test_fallback_marks_untouched_when_mfe_below_target():
    row = _row(outcome_status=STATUS_TIMEOUT, own_mfe_pct=1.2)
    assert apply_own_outcome(row) is True
    assert row["touched_target"] is False


def test_candidate_evaluation_wins_over_own_outcome():
    row = _row(candidate_status="evaluated", mfe_pct=0.4, touched_target=False,
               outcome_status=STATUS_HIT, own_mfe_pct=9.9)
    assert apply_own_outcome(row) is False
    assert row["mfe_pct"] == 0.4 and row["touched_target"] is False


def test_no_data_marker_is_ignored():
    row = _row(outcome_status=STATUS_NO_DATA, own_mfe_pct=None)
    assert apply_own_outcome(row) is False
    assert row["candidate_status"] is None


def test_missing_mfe_is_ignored():
    assert apply_own_outcome(_row(outcome_status=STATUS_HIT, own_mfe_pct=None)) is False


# ------------------------------------------------------------------ DB sorgusu (sahte bağlantı)

def test_list_unmeasured_sql_placeholders_match(monkeypatch):
    captured = {}

    class _Conn:
        def execute(self, sql, params=()):
            captured["sql"], captured["params"] = sql, params
            return MagicMock(fetchall=lambda: [])

    async def fake_run_db(op):
        return op(_Conn())

    monkeypatch.setattr(database, "_run_db", fake_run_db)
    asyncio.run(database.list_unmeasured_notifications(now=1_000_000.0, max_age_sec=3600.0, limit=40))
    sql, params = captured["sql"], captured["params"]
    assert sql.count("%s") == len(params)
    assert "candidate_id" in sql and "outcome_status IS NULL" in sql
    assert "velocity_candidates" not in sql        # yan etki yok: aday tablosuna dokunulmaz


# ------------------------------------------------------------------ rapor ucu bayrağı

def test_report_endpoint_passes_include_own_outcomes_to_both_queries(monkeypatch):
    """Rapor ucu (liste + genel özet) bildirimin kendi sonucunu kullanmalı; diğer çağıranlar değil."""
    from unittest.mock import AsyncMock

    from app.routers import monitoring

    seen = []

    async def fake_matches(**kw):
        seen.append(kw)
        return []

    monkeypatch.setattr(database, "get_monitoring_velocity_matches", fake_matches)
    monkeypatch.setattr(database, "_run_db", AsyncMock(return_value=[]))
    monkeypatch.setattr(monitoring, "get_user_notification_settings", AsyncMock(return_value={}))
    asyncio.run(monitoring.report_notifications(limit=5, day="all"))
    assert len(seen) == 2
    assert all(kw.get("include_own_outcomes") is True for kw in seen)


def test_default_callers_keep_old_behaviour():
    import inspect

    sig = inspect.signature(database.get_monitoring_velocity_matches)
    assert sig.parameters["include_own_outcomes"].default is False
