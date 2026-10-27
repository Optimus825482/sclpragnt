import asyncio
from unittest.mock import AsyncMock, patch

from app import notification_plan

PLAN = {"symbol": "XTRY", "bucket": "radar", "entry_ref_price": 1.0, "max_amount_try": 12345.0,
        "max_amount_binding": "slip", "target_net_pct": 3.0, "target_gross_pct": 3.5,
        "target_price": 1.035, "stop_pct": 2.0, "stop_price": 0.98, "eta_minutes": 20,
        "exit_at": None, "grace_minutes": None, "hit_rate": 0.6, "sample_n": 30,
        "profile_exit": False, "warnings": [], "created_at": 1000.0}
PLAN2 = {**PLAN, "max_amount_try": 99999.0}


def _run(coro):
    return asyncio.run(coro)


def _notif(**kw):
    return {"symbol": "XTRY", "message": "m", "price": 1.0, "target_pct": 3.0, **kw}


def test_attach_plan_appends_text_and_freezes():
    store = AsyncMock(return_value=PLAN)
    with patch.object(notification_plan, "build_plan", AsyncMock(return_value=PLAN)), \
            patch("app.database.save_trade_plan", store):
        n = _run(notification_plan.attach_plan(_notif(notification_key="k1"), "radar"))
    assert n["trade_plan"] == PLAN and "Maks:" in n["message"] and n["plan_key"] == "k1"
    assert store.await_args.args[0] == "k1"


def test_second_attach_keeps_first_plan():
    store = AsyncMock(return_value=PLAN)  # DB ilk planı döndürür
    with patch.object(notification_plan, "build_plan", AsyncMock(return_value=PLAN2)), \
            patch("app.database.save_trade_plan", store):
        n = _run(notification_plan.attach_plan(_notif(notification_key="k1"), "radar"))
    assert n["trade_plan"] == PLAN


def test_attach_plan_none_keeps_message():
    with patch.object(notification_plan, "build_plan", AsyncMock(return_value=None)):
        n = _run(notification_plan.attach_plan(_notif(notification_key="k2"), "radar"))
    # plan yoksa plan_key de None (push extra'sı var olmayan plana işaret etmez)
    assert n["message"] == "m" and n["trade_plan"] is None and n["plan_key"] is None


def test_key_falls_back_to_tag_detected_at():
    with patch.object(notification_plan, "build_plan", AsyncMock(return_value=PLAN)),             patch("app.database.save_trade_plan", AsyncMock(return_value=PLAN)):
        n = _run(notification_plan.attach_plan(
            _notif(tag="monitoring-XTRY", detected_at=1234.9), "radar"))
    assert n["plan_key"] == "monitoring-XTRY-1234"


def test_attach_plans_reuses_stored_plan_for_updated_notification():
    bp = AsyncMock(return_value=PLAN2)
    gp = AsyncMock(return_value={"k-upd": PLAN})
    save = AsyncMock(return_value=PLAN2)
    upd = _notif(notification_key="k-upd", updated=True)
    new = _notif(notification_key="k-new")
    with patch.object(notification_plan, "build_plan", bp),             patch("app.database.get_trade_plans", gp), patch("app.database.save_trade_plan", save):
        _run(notification_plan.attach_plans([upd, new], "radar"))
    assert gp.await_count == 1 and gp.await_args.args[0] == ["k-upd"]     # yalnız güncellenenler, tek sorgu
    assert bp.await_count == 1 and bp.await_args.args[0] == "XTRY"         # yalnız yeni bildirim kurulur
    assert upd["trade_plan"] == PLAN and upd["plan_key"] == "k-upd" and "Maks:" in upd["message"]
    assert new["trade_plan"] == PLAN2 and new["plan_key"] == "k-new"
    assert [c.args[0] for c in save.await_args_list] == ["k-new"]


def test_attach_plans_updated_without_stored_plan_builds():
    bp = AsyncMock(return_value=PLAN)
    with patch.object(notification_plan, "build_plan", bp),             patch("app.database.get_trade_plans", AsyncMock(return_value={})),             patch("app.database.save_trade_plan", AsyncMock(return_value=PLAN)):
        upd = _notif(notification_key="k-upd", updated=True)
        _run(notification_plan.attach_plans([upd], "radar"))
    assert bp.await_count == 1 and upd["trade_plan"] == PLAN


def test_attach_plans_without_updates_skips_lookup():
    gp = AsyncMock(return_value={})
    with patch("app.database.get_trade_plans", gp):
        _run(notification_plan.attach_plans([_notif(notification_key="a")], "radar"))
    gp.assert_not_awaited()


def test_attach_plans_lookup_failure_falls_back_to_build():
    bp = AsyncMock(return_value=None)
    with patch.object(notification_plan, "build_plan", bp),             patch("app.database.get_trade_plans", AsyncMock(side_effect=RuntimeError("db"))):
        upd = _notif(notification_key="k", updated=True)
        _run(notification_plan.attach_plans([upd], "radar"))
    assert bp.await_count == 1 and upd["plan_key"] is None


def test_db_failure_still_returns_plan():
    with patch.object(notification_plan, "build_plan", AsyncMock(return_value=PLAN)), \
            patch("app.database.save_trade_plan", AsyncMock(side_effect=RuntimeError("db"))):
        n = _run(notification_plan.attach_plan(_notif(notification_key="k3"), "radar"))
    assert n["trade_plan"] == PLAN and "Maks:" in n["message"]


def test_profile_passed_to_build_plan():
    bp = AsyncMock(return_value=None)
    prof = {"stop_loss_pct": 3, "max_hold_minutes": 240}
    with patch.object(notification_plan, "build_plan", bp):
        _run(notification_plan.attach_plan(_notif(notification_key="k4"), "ma_buy:4h", profile=prof))
    assert bp.await_args.kwargs["profile"] == prof
    assert bp.await_args.args[2] == 1.0 and bp.await_args.args[3] == 3.0


def test_trade_plan_endpoint():
    from fastapi import HTTPException
    from app.routers import monitoring
    with patch("app.database.get_trade_plan", AsyncMock(return_value=PLAN)):
        assert _run(monitoring.get_trade_plan(key="k1")) == {"plan": PLAN}
    with patch("app.database.get_trade_plan", AsyncMock(return_value=None)):
        try:
            _run(monitoring.get_trade_plan(key="zz"))
            assert False
        except HTTPException as e:
            assert e.status_code == 404


def test_send_push_payload_has_plan_key():
    from app.routers import monitoring
    dwp = AsyncMock(return_value={"ok": True})
    notif = {"symbol": "XTRY", "message": "m", "title": "t", "url": "/u", "tag": "tg", "plan_key": "k9"}
    with patch.object(monitoring, "deliver_web_push", dwp):
        _run(monitoring._send_push(notif))
    assert dwp.await_args.kwargs["extra"]["plan_key"] == "k9"


def test_save_timeout_keeps_plan():
    async def slow(*a, **k):
        await asyncio.sleep(5)
    with patch.object(notification_plan, "SAVE_TIMEOUT_SEC", 0.05), \
            patch.object(notification_plan, "build_plan", AsyncMock(return_value=PLAN)), \
            patch("app.database.save_trade_plan", slow):
        n = _run(notification_plan.attach_plan(_notif(notification_key="k5"), "radar"))
    assert n["trade_plan"] == PLAN and "Maks:" in n["message"]


def test_row_plan_keys_match_attach_time_keys():
    from app import notification_plan as np_
    # attach anındaki anahtar: plan_key_for(notif) -> f"{tag}-{int(detected_at)}"; tag=monitoring-{sym}
    notif = {"tag": "monitoring-XTRY", "detected_at": 1234.9}
    assert np_.radar_row_plan_key({"symbol": "XTRY", "detected_at": 1234.9}) == np_.plan_key_for(notif)
    # MA BUY: notification_key = ma-{tf}-{sym}-{bar_open_ms}
    assert np_.ma_buy_row_plan_key({"symbol": "xtry", "timeframe": "4h", "bar_open_ms": 99}) == "ma-4h-XTRY-99"
    assert np_.radar_row_plan_key({"symbol": None, "detected_at": 1}) is None


def test_enrich_rows_with_plans_single_batched_lookup():
    from app import notification_plan as np_
    rows = [{"symbol": "AAATRY", "detected_at": 10.2}, {"symbol": "BBBTRY", "detected_at": 20.0}]
    mock = AsyncMock(return_value={"monitoring-AAATRY-10": {"max_amount_try": 5000.0}})
    with patch("app.database.get_trade_plans", mock):
        _run(np_.enrich_rows_with_plans(rows, np_.radar_row_plan_key))
    assert mock.await_count == 1
    assert rows[0]["plan_key"] == "monitoring-AAATRY-10" and rows[0]["trade_plan"] == {"max_amount_try": 5000.0}
    # saklı planı olmayan satır: plan_key de null (var olmayan plana işaret etmez)
    assert rows[1]["plan_key"] is None and rows[1]["trade_plan"] is None


def test_enrich_rows_db_failure_gives_null_plans():
    from app import notification_plan as np_
    rows = [{"symbol": "AAATRY", "timeframe": "5m", "bar_open_ms": 7}]
    with patch("app.database.get_trade_plans", AsyncMock(side_effect=RuntimeError("db"))):
        _run(np_.enrich_rows_with_plans(rows, np_.ma_buy_row_plan_key))
    assert rows[0]["trade_plan"] is None


def test_enrich_skips_rows_with_plan_and_uses_own_key():
    from app import notification_plan as np_
    own = {"symbol": "AAATRY", "detected_at": 1.0, "trade_plan": {"x": 1}, "plan_key": "mine"}
    keyed = {"symbol": "BBBTRY", "detected_at": 2.0, "plan_key": "custom-key"}
    mock = AsyncMock(return_value={"custom-key": {"y": 2}})
    with patch("app.database.get_trade_plans", mock):
        _run(np_.enrich_rows_with_plans([own, keyed], np_.radar_row_plan_key))
    assert mock.await_args.args[0] == ["custom-key"]
    assert own["trade_plan"] == {"x": 1} and own["plan_key"] == "mine"
    assert keyed["trade_plan"] == {"y": 2} and keyed["plan_key"] == "custom-key"
