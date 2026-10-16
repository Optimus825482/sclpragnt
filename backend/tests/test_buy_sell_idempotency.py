"""/api/binance/buy ve /sell: aynı client_order_id ikinci gerçek emir üretmez. Sahte borsa; GERÇEK EMİR YOK."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import database, main
from app.binance_tr_private import BinanceTrAmbiguousOrderError

FILTERS = {"quote_asset": "TRY", "min_notional": 10.0, "step_size": 0.01, "min_qty": 0.01}


class FakeDB:
    def __init__(self):
        self.rows = {}

    async def claim(self, uid, cid, symbol, request):
        if (uid, cid) in self.rows:
            return False
        self.rows[(uid, cid)] = {"status": "in_progress", "result": {}}
        return True

    async def finish(self, uid, cid, status, result):
        self.rows[(uid, cid)].update(status=status, result=result)

    async def get(self, uid, cid):
        return self.rows.get((uid, cid))


@pytest.fixture
def env(monkeypatch):
    fdb = FakeDB()
    monkeypatch.setattr(database, "claim_order_request", fdb.claim)
    monkeypatch.setattr(database, "finish_order_request", fdb.finish)
    monkeypatch.setattr(database, "get_order_request", fdb.get)
    calls = {"buy": [], "sell": []}

    def buy(k, s, sym, q, min_notional=None, client_order_id=None):
        calls["buy"].append(client_order_id)
        if calls.get("buy_error"):
            raise calls["buy_error"]
        return {"order_id": "1", "symbol": sym, "client_order_id": client_order_id}

    def sell(k, s, sym, qty, step_size=None, client_order_id=None, min_notional=None, last_price=None):
        calls["sell"].append(client_order_id)
        return {"order_id": "2", "symbol": sym, "client_order_id": client_order_id}

    patches = [
        patch("app.main._require_user", MagicMock(return_value={"username": "ali", "role": "user"})),
        patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 7})),
        patch("app.main._real_sell_state_for", new=AsyncMock(return_value=(True, "panel"))),
        patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))),
        patch("app.main.get_symbol_filters", MagicMock(return_value=FILTERS)),
        patch("app.main.get_account_balance", MagicMock(return_value=[
            {"asset": "TRY", "free": "1000", "locked": "0"}, {"asset": "ADA", "free": "50", "locked": "0"}])),
        patch("app.main.place_market_buy", buy),
        patch("app.main.place_market_sell", sell),
        patch("app.main.log_user_action", new=AsyncMock()),
        patch("app.main._invalidate_binance_cost_cache", MagicMock()),
        patch("app.main._session_identity", MagicMock(return_value=("ali", "user"))),
    ]
    for p in patches:
        p.start()
    yield calls, fdb
    for p in patches:
        p.stop()


def run(c):
    return asyncio.run(c)


def buy_payload(**kw):
    p = {"asset": "ADA", "amount_try": 100, "confirmation": "REAL_BUY", "client_order_id": "web-12345678"}
    p.update(kw)
    return p


def test_buy_duplicate_id_sends_one_order(env):
    calls, _ = env
    first = run(main.binance_buy(buy_payload(), request=MagicMock()))
    second = run(main.binance_buy(buy_payload(), request=MagicMock()))
    assert calls["buy"] == ["web-12345678"]
    assert first["ok"] and second["idempotent_replay"] is True


def test_buy_without_id_still_works_for_old_clients(env):
    calls, _ = env
    p = buy_payload()
    del p["client_order_id"]
    assert run(main.binance_buy(p, request=MagicMock()))["ok"]
    assert len(calls["buy"]) == 1


def test_buy_invalid_id_is_422(env):
    with pytest.raises(HTTPException) as e:
        run(main.binance_buy(buy_payload(client_order_id="x"), request=MagicMock()))
    assert e.value.status_code == 422


def test_ambiguous_buy_blocks_blind_retry(env):
    calls, fdb = env
    calls["buy_error"] = BinanceTrAmbiguousOrderError("belirsiz", client_order_id="web-12345678", symbol="ADA_TRY")
    with pytest.raises(HTTPException) as e:
        run(main.binance_buy(buy_payload(), request=MagicMock()))
    assert e.value.status_code == 502 and fdb.rows[(7, "web-12345678")]["status"] == "unknown"
    calls["buy_error"] = None
    resp = run(main.binance_buy(buy_payload(), request=MagicMock()))
    assert resp.status_code == 202 and len(calls["buy"]) == 1


def test_sell_duplicate_id_sends_one_order(env):
    calls, _ = env
    p = {"asset": "ADA", "quantity": 10, "confirmation": "REAL_SELL", "client_order_id": "web-87654321"}
    run(main.binance_sell(dict(p), request=MagicMock()))
    again = run(main.binance_sell(dict(p), request=MagicMock()))
    assert calls["sell"] == ["web-87654321"] and again["idempotent_replay"] is True
