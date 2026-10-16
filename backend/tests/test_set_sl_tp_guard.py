"""/api/binance/set-sl-tp: geçersiz fiyat ilişkisi mevcut korumayı İPTAL ETMEDEN reddedilir. Sahte borsa."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import main

FILTERS = {"quote_asset": "TRY", "min_notional": 10.0, "step_size": 0.01, "min_qty": 0.01, "tick_size": 0.01, "oco_enable": True}


@pytest.fixture
def env():
    calls = {"cancel": [], "oco": [], "limit": [], "stop": []}

    async def price(self, symbol_u):
        return 100.0

    patches = [
        patch("app.main._require_user", MagicMock(return_value={"username": "ali", "role": "user"})),
        patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 7})),
        patch("app.main._real_sell_state_for", new=AsyncMock(return_value=(True, "panel"))),
        patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))),
        patch("app.main.get_symbol_filters", MagicMock(return_value=FILTERS)),
        patch("app.routers.binance_trade.BinanceExchange.price", price),
        patch("app.main.get_open_orders", MagicMock(return_value=[{"side": "SELL", "orderId": 5, "stopPrice": "90", "origQty": "5"}])),
        patch("app.main.cancel_order", MagicMock(side_effect=lambda *a: calls["cancel"].append(a))),
        patch("app.main.get_account_balance", MagicMock(return_value=[{"asset": "ADA", "free": "5", "locked": "0"}])),
        patch("app.main.place_oco_sell", MagicMock(side_effect=lambda *a, **k: calls["oco"].append(a) or {"order_list_id": "1"})),
        patch("app.main.place_limit_sell", MagicMock(side_effect=lambda *a, **k: calls["limit"].append(a) or {"order_id": "2"})),
        patch("app.main.place_stop_loss_sell", MagicMock(side_effect=lambda *a, **k: calls["stop"].append(a) or {"order_id": "3"})),
        patch("app.main.log_user_action", new=AsyncMock()),
        patch("app.main._session_identity", MagicMock(return_value=("ali", "user"))),
    ]
    for p in patches:
        p.start()
    yield calls
    for p in patches:
        p.stop()


def call(payload):
    base = {"asset": "ADA", "quantity": 5, "cancel_existing": True}
    base.update(payload)
    return asyncio.run(main.binance_set_sl_tp(base, request=MagicMock()))


def test_tp_below_last_price_rejected_and_existing_protection_kept(env):
    with pytest.raises(HTTPException) as e:
        call({"mode": "TP_ONLY", "tp_price": 99})
    assert e.value.status_code == 422 and "üstünde" in e.value.detail
    assert env["cancel"] == [] and env["limit"] == []


def test_sl_above_last_price_rejected_without_cancelling(env):
    with pytest.raises(HTTPException) as e:
        call({"mode": "SL_ONLY", "sl_price": 101})
    assert e.value.status_code == 422 and env["cancel"] == []


def test_oco_with_both_prices_valid(env):
    res = call({"mode": "OCO", "tp_price": 110, "sl_price": 95})
    assert res["ok"] and len(env["oco"]) == 1 and len(env["cancel"]) == 1


def test_oco_missing_one_price_rejected_before_cancel(env):
    with pytest.raises(HTTPException):
        call({"mode": "OCO", "tp_price": 110})
    assert env["cancel"] == []
