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


@pytest.fixture(autouse=True)
def paper_settings(monkeypatch):
    monkeypatch.setattr(auto_paper, "get_auto_paper_settings", AsyncMock(return_value={
        "enabled": True, "min_score": 50,
    }))


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

    with patch.object(monitoring, "super_scan_for_paper", fake_scan), \
         patch.object(monitoring, "_send_push", fake_push), \
         patch.object(auto_paper, "try_open_from_notification", fake_open), \
         patch.object(super_scan_notify, "_recently_pushed", fake_recent), \
         patch.object(super_scan_notify, "_mark_pushed", fake_mark), \
         patch.object(config, "SUPER_SCAN_PUSH_TOP_N", 2):
        stats = asyncio.run(super_scan_notify.run_once())

    # 2026-11-25 (kullanıcı): varsayılan PUSH KAPALI → bildirim yok, işlem VAR.
    assert pushed == [], "push kapalıyken bildirim gitmemeli"
    assert opened == ["AAA_TRY", "BBB_TRY"], "eşiği geçen ilk N aday işlem açmalı"
    assert stats["pushed"] == 0 and stats["opened"] == 2
    assert stats["push_enabled"] is False


def test_push_mode_still_works_when_enabled():
    """SUPER_SCAN_PUSH_ENABLED=1 → önce push, sonra işlem."""
    items = [{"symbol": "AAA_TRY", "super_score": 90.0, "score": 80, "price": 10.0,
              "target_pct": 3.0, "horizon_minutes": 15, "sources": ["velocity"]}]
    pushed, opened = [], []

    async def fake_scan(limit=12, **kw):
        return {"scanned": 1, "eligible": 1, "items": items}

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

    with patch.object(monitoring, "super_scan_for_paper", fake_scan), \
         patch.object(monitoring, "_send_push", fake_push), \
         patch.object(auto_paper, "try_open_from_notification", fake_open), \
         patch.object(super_scan_notify, "_recently_pushed", fake_recent), \
         patch.object(super_scan_notify, "_mark_pushed", fake_mark), \
         patch.object(config, "SUPER_SCAN_PUSH_ENABLED", True):
        stats = asyncio.run(super_scan_notify.run_once())

    assert pushed == ["AAA_TRY"] and opened == ["AAA_TRY"]
    assert stats["push_enabled"] is True


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


def test_signal_key_deduplicates_one_window_and_allows_next():
    first = super_scan_notify._envelope({"symbol": "AAA_TRY", "detected_at": 600})
    repeat = super_scan_notify._envelope({"symbol": "AAATRY", "detected_at": 899})
    later = super_scan_notify._envelope({"symbol": "AAATRY", "detected_at": 900})
    assert first["notification_key"] == repeat["notification_key"] == "super:AAATRY:2"
    assert later["notification_key"] == "super:AAATRY:3"


def test_run_once_reports_top_score():
    async def fake_scan(limit=12, **kw):
        return {"scanned": 10, "eligible": 2,
                "items": [{"symbol": "AAA_TRY", "super_score": 72.5, "score": 60,
                           "price": 1.0, "sources": ["velocity"]}]}

    async def fake_push(notif):
        return True

    async def fake_open(notif):
        return {"status": "opened"}

    async def fake_recent(symbol, cooldown):
        return False

    async def fake_mark(symbol):
        return None

    with patch.object(monitoring, "super_scan_for_paper", fake_scan), \
         patch.object(monitoring, "_send_push", fake_push), \
         patch.object(auto_paper, "try_open_from_notification", fake_open), \
         patch.object(super_scan_notify, "_recently_pushed", fake_recent), \
         patch.object(super_scan_notify, "_mark_pushed", fake_mark):
        stats = asyncio.run(super_scan_notify.run_once())

    assert stats["top_score"] == 72.5
    # 2026-11-25: varsayılan push KAPALI → pushed 0, işlem yine açılır
    assert stats["pushed"] == 0
    assert stats["opened"] == 1


def test_super_scan_bypasses_radar_mode_whitelist():
    """`allowed_modes=["trend_devam"]` süper taramayı BLOKLAMAMALI.

    Varsayılan AUTO_PAPER_ALLOWED_MODES=trend_devam; zarf mode="super_scan"
    taşıdığı için mod kapısı tek kanal otonom işlemi tümden kilitliyordu
    (2026-11-25 canlı denetimi).
    """
    notif = super_scan_notify._envelope(
        {"symbol": "AAA_TRY", "super_score": 90.0, "score": 80.0, "price": 10.0,
         "target_pct": 3.0, "horizon_minutes": 15, "sources": ["velocity"]})

    settings = {"enabled": True, "min_score": 60.0, "allowed_modes": ["trend_devam"]}

    async def run():
        with patch.object(auto_paper, "get_auto_paper_settings", AsyncMock(return_value=settings)):
            return await auto_paper._entry_context(notif)

    _, rejection, symbol, _ = asyncio.run(run())
    assert symbol == "AAA_TRY"
    assert not rejection, f"süper tarama mod kapısına takılmamalı: {rejection}"


def test_open_position_candidates_do_not_starve_lower_ones():
    """Açık pozisyonu olan TOP_N aday deneme hakkını tüketmemeli.

    `attempted >= TOP_N` tavanı varken açık pozisyonlu ilk iki sembol her
    turda denenip tavanı dolduruyor, daha düşük skorlu fırsatlar hiç
    denenmiyordu (2026-11-25 denetimi).
    """
    items = [
        {"symbol": "AAA_TRY", "super_score": 90.0, "score": 80.0, "price": 10.0,
         "target_pct": 3.0, "horizon_minutes": 15, "sources": ["velocity"]},
        {"symbol": "BBB_TRY", "super_score": 80.0, "score": 75.0, "price": 5.0,
         "target_pct": 3.0, "horizon_minutes": 15, "sources": ["snapback"]},
        {"symbol": "CCC_TRY", "super_score": 70.0, "score": 70.0, "price": 2.0,
         "target_pct": 3.0, "horizon_minutes": 15, "sources": ["rising"]},
    ]
    tried = []

    async def fake_scan(limit=50, **kw):
        return {"scanned": 3, "eligible": 3, "items": items}

    async def fake_open(notif):
        tried.append(notif["symbol"])
        return {"status": "opened"}

    async def fake_recent(symbol, cooldown):
        return False

    async def fake_entry_context(notif):
        return {"enabled": True}, None, notif["symbol"], False

    async def fake_open_trade(symbol):
        return {"symbol": symbol} if symbol in ("AAA_TRY", "BBB_TRY") else None

    with patch.object(monitoring, "super_scan_for_paper", fake_scan), \
         patch.object(auto_paper, "_entry_context", fake_entry_context), \
         patch.object(auto_paper, "try_open_from_notification", fake_open), \
         patch.object(super_scan_notify.database, "get_open_auto_paper_trade", fake_open_trade), \
         patch.object(super_scan_notify, "_recently_pushed", fake_recent), \
         patch.object(super_scan_notify, "_mark_pushed", AsyncMock()):
        stats = asyncio.run(super_scan_notify.run_once())

    assert tried == ["CCC_TRY"]
    assert stats["opened"] == 1
    assert stats["blocked"]["already_open"] == 2


def test_paper_uses_base_score_and_bounds_attempts_after_skipping_conflicting_trend(monkeypatch):
    from unittest.mock import AsyncMock

    rows = [
        {"symbol": "DECLINETRY", "score": 99, "super_score": 110, "paper_block_reason": "trend_conflict"},
        {"symbol": "HIGHBONUSTRY", "score": 60, "super_score": 97},
        {"symbol": "ELIGIBLETRY", "score": 80, "super_score": 87, "oi_change_pct": 4.5},
        {"symbol": "NEXTTRY", "score": 75, "super_score": 75},
        {"symbol": "OVERLIMITTRY", "score": 74, "super_score": 74},
    ]
    open_position = AsyncMock(return_value={"status": "opened"})
    mark = AsyncMock()
    monkeypatch.setattr(config, "SUPER_SCAN_PUSH_TOP_N", 2)
    monkeypatch.setattr(config, "SUPER_SCAN_PUSH_ENABLED", False)
    monkeypatch.setattr(config, "AUTO_PAPER_ONLY_ON_PUSH", False)
    monkeypatch.setattr(config, "SUPER_SCAN_ONLY", True)
    monkeypatch.setattr(monitoring, "super_scan_for_paper", AsyncMock(return_value={"items": rows}))
    monkeypatch.setattr(super_scan_notify, "_recently_pushed", AsyncMock(return_value=False))
    monkeypatch.setattr(super_scan_notify, "_mark_pushed", mark)
    monkeypatch.setattr(auto_paper, "get_auto_paper_settings", AsyncMock(return_value={
        "enabled": True, "min_score": 70, "min_oi_change_pct": 3,
    }))

    async def open_after_gate(notification):
        _, rejection, _, _ = await auto_paper._entry_context(notification)
        return rejection or await open_position(notification)

    monkeypatch.setattr(auto_paper, "_try_open_impl", open_after_gate)
    stats = asyncio.run(super_scan_notify.run_once())
    assert stats["attempted"] == 2
    assert stats["opened"] == 2
    assert stats["blocked"] == {"trend_conflict": 1, "score_below_min": 1}
    opened = open_position.await_args_list[0].args[0]
    assert opened["symbol"] == "ELIGIBLETRY"
    assert opened["score"] == 80 and opened["oi_change_pct"] == 4.5
    assert [call.args[0] for call in mark.await_args_list] == ["ELIGIBLETRY", "NEXTTRY"]
