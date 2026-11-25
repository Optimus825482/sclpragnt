"""TEK KANAL: süper tarama → push + otonom paper (2026-11-25, kullanıcı).

Kural: SUPER_SCAN_ONLY açıkken (varsayılan) radar bildirimleri üretilmez,
otonom paper yalnız source="super_scan" zarflarını kabul eder.
"""
import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from app.config import config
from app import super_scan_notify
from app.routers import auto_paper, monitoring


def test_defaults_enabled_single_channel():
    assert config.SUPER_SCAN_ONLY is True
    assert config.SUPER_SCAN_PUSH_TOP_N >= 1
    assert config.SUPER_SCAN_PUSH_MIN_SCORE > 0


def test_auto_paper_blocks_non_super_scan():
    src = inspect.getsource(auto_paper._entry_context)
    assert 'not_super_scan' in src
    assert 'SUPER_SCAN_ONLY' in src


def test_radar_notify_is_gated():
    src = inspect.getsource(monitoring._notify)
    assert "super_scan" in src
    assert "SUPER_SCAN_ONLY" in src


def test_envelope_marks_super_scan():
    notif = super_scan_notify._envelope({
        "symbol": "AAA_TRY", "super_score": 78.5, "score": 70, "price": 10.0,
        "target_pct": 3.0, "horizon_minutes": 15, "sources": ["velocity", "rising"],
        "tags": ["AI"], "cmc_flags": ["HACIM_PATLAMASI"],
    })
    assert notif["source"] == "super_scan"
    assert notif["super_scan"] is True
    assert notif["sent_via_push"] is True
    assert "AAA" in notif["title"] and "Süper Tarama" in notif["title"]


def test_run_once_pushes_top_n_and_opens_paper():
    items = [
        {"symbol": "AAA_TRY", "super_score": 90.0, "score": 80, "price": 10.0, "target_pct": 3.0,
         "horizon_minutes": 15, "sources": ["velocity", "rising"]},
        {"symbol": "BBB_TRY", "super_score": 70.0, "score": 65, "price": 5.0, "target_pct": 3.0,
         "horizon_minutes": 15, "sources": ["snapback"]},
        {"symbol": "CCC_TRY", "super_score": 40.0, "score": 35, "price": 1.0, "sources": []},
    ]
    pushed, opened = [], []

    async def fake_scan(limit=12, **kw):
        return {"scanned": 10, "eligible": 3, "items": items}

    async def fake_push(notif):
        pushed.append(notif["symbol"])
        return True

    async def fake_open(notif):
        opened.append(notif["symbol"])
        return {"status": "opened"}

    async def fake_recent(symbol, cooldown):
        return False

    async def fake_mark(symbol):
        return None

    with patch.object(monitoring, "radar_super_scan", fake_scan), \
         patch.object(monitoring, "_send_push", fake_push), \
         patch.object(auto_paper, "try_open_from_notification", fake_open), \
         patch.object(super_scan_notify, "_recently_pushed", fake_recent), \
         patch.object(super_scan_notify, "_mark_pushed", fake_mark), \
         patch.object(config, "SUPER_SCAN_PUSH_TOP_N", 2):
        stats = asyncio.run(super_scan_notify.run_once())

    assert pushed == ["AAA_TRY", "BBB_TRY"], "eşiği geçen ilk N aday"
    assert opened == pushed
    assert stats["pushed"] == 2 and stats["opened"] == 2


def test_notify_filter_blocks_non_super_when_enforced(monkeypatch):
    """Kanal kapısı AÇIKKEN (üretim varsayılanı) süper olmayan aday bildirilmez."""
    from app.config import config as cfg

    monkeypatch.setattr(monitoring, "NOTIFY_SOURCES_UNRESTRICTED", False, raising=False)
    monkeypatch.setattr(cfg, "SUPER_SCAN_ONLY", True, raising=False)

    async def run():
        return await monitoring._notify(
            [{"symbol": "PLAIN_TRY", "score": 99.0, "price": 1.0, "target_pct": 3.0,
              "mode": "trend_devam"}],
            {"enabled": True})

    out = asyncio.run(run())
    assert out == [], "süper tarama dışı aday bildirilmemeli"


def test_envelope_has_push_required_fields():
    """`_send_push` url/tag/title/message ZORUNLU okur; eksikse push düşer."""
    notif = super_scan_notify._envelope({"symbol": "AAA_TRY", "super_score": 70.0})
    for key in ("url", "tag", "title", "message"):
        assert notif.get(key), f"eksik alan: {key}"
    # hedef yoksa çökmemeli
    assert "hedef —" in notif["message"]


def test_envelope_target_formatting():
    notif = super_scan_notify._envelope({"symbol": "AAA_TRY", "super_score": 70.0,
                                         "target_pct": 3.0})
    assert "hedef %3.0" in notif["message"]
