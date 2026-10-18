"""Gerçek `binance_tr_private` + yerel sahte sunucu ile uçtan uca akış. GERÇEK EMİR YOK."""
import asyncio

import pytest

from app import binance_tr_private as btp
from app import database, open_position
from app.open_position import execute_open_position
from app.routers.binance_trade import BinanceExchange
from tests.fake_binance_tr import FakeBinanceTR

RISK = {"max_position_pct": 50.0, "default_rr": 2.0}
KEY, SECRET = "k" * 20, "s" * 20


class FakeDB:
    def __init__(self):
        self.rows = {}

    async def claim(self, uid, cid, symbol, request):
        if (uid, cid) in self.rows:
            return False
        self.rows[(uid, cid)] = {"status": "in_progress", "symbol": symbol, "result": {}, "created_at": 0.0}
        return True

    async def finish(self, uid, cid, status, result):
        self.rows[(uid, cid)].update(status=status, result=result)

    async def get(self, uid, cid):
        return self.rows.get((uid, cid))


@pytest.fixture
def fake(monkeypatch):
    srv = FakeBinanceTR(api_key=KEY, secret=SECRET)
    base = srv.start()
    monkeypatch.setattr(btp, "REST_BASE", base)

    async def fake_ticker_price(symbols=None):
        return [{"symbol": "ADATRY", "price": str(srv.price)}]
    monkeypatch.setattr("app.binance_tr_public.ticker_price", fake_ticker_price)
    monkeypatch.setattr(btp, "_throttle_private_request", lambda: None)
    btp._symbols_cache["expires"] = 0
    btp._server_time_cache.clear()
    btp.invalidate_account_balance_cache(KEY)
    db = FakeDB()
    monkeypatch.setattr(database, "claim_order_request", db.claim)
    monkeypatch.setattr(database, "finish_order_request", db.finish)
    monkeypatch.setattr(database, "get_order_request", db.get)
    monkeypatch.setattr(open_position, "DETAIL_RETRY_SLEEP_SEC", 0.0)
    yield srv, db
    srv.stop()
    btp._symbols_cache["expires"] = 0
    btp._server_time_cache.clear()


def _payload(**kw):
    p = {"symbol": "ADATRY", "amount_try": 400.0, "sl_pct": 2.0, "rr": 2.0, "client_order_id": "e2e-0000001"}
    p.update(kw)
    return p


def _run(payload):
    return asyncio.run(execute_open_position(BinanceExchange(KEY, SECRET), 7, payload, RISK))


def test_full_flow_buy_detail_oco(fake):
    srv, _ = fake
    status, body = _run(_payload())
    assert status == 200 and body["protection"]["status"] == "placed"
    buys = srv.calls("POST", "/open/v1/orders")
    assert len(buys) == 1 and buys[0]["quoteOrderQty"] == "400.00" and buys[0]["side"] == "0" and buys[0]["type"] == "2"
    # 2026-10-17 (3703 Invalid client ID düzeltmesi): borsaya giden clientId yalnız harf+rakam; tire atılır.
    assert buys[0]["clientId"] == "e2e0000001"
    ocos = srv.calls("POST", "/open/v1/orders/oco")
    assert len(ocos) == 1 and ocos[0]["side"] == "1"
    assert float(ocos[0]["quantity"]) == pytest.approx(body["executed_qty"])
    assert float(ocos[0]["price"]) > float(ocos[0]["stopPrice"])          # TP > SL
    # Belgelenmiş OCO sözleşmesi (apidocs POST /open/v1/orders/oco): tekil `clientId`/`type` yok,
    # liste kimliği `listClientId`; stopLimitPrice zorunlu; stopLimitTimeInForce belgede yok.
    assert "clientId" not in ocos[0] and "type" not in ocos[0] and "stopLimitTimeInForce" not in ocos[0]
    assert ocos[0]["listClientId"].isalnum() and len(ocos[0]["listClientId"]) <= 36
    assert float(ocos[0]["stopLimitPrice"]) > 0
    # Belgelenmiş imzalı istek: X-MBX-APIKEY + timestamp + recvWindow<=60000 (imzayı fake doğrular).
    assert int(ocos[0]["recvWindow"]) <= 60000 and ocos[0]["timestamp"].isdigit()
    signed_hdrs = [h for (m, path, prm), h in zip(srv.requests, srv.headers) if "signature" in prm]
    assert signed_hdrs and all(h.get("x-mbx-apikey") == KEY for h in signed_hdrs)
    # Belgelenmiş ALIŞ: MARKET(type=2) + quoteOrderQty; quantity/price gönderilmez.
    assert "quantity" not in buys[0] and "price" not in buys[0]


def test_duplicate_request_hits_exchange_once(fake):
    srv, _ = fake
    _run(_payload())
    status, body = _run(_payload())
    assert body["idempotent_replay"] is True
    assert len(srv.calls("POST", "/open/v1/orders")) == 1


def test_oco_rejected_leaves_bought_but_flags_unprotected(fake):
    srv, db = fake
    srv.oco_error = {"code": 3210, "msg": "oco reddedildi"}
    status, body = _run(_payload())
    assert status == 200 and body["protection"]["status"] == "failed"
    assert db.rows[(7, "e2e0000001")]["status"] == "done"


def test_partial_fill_protects_only_filled_quantity(fake):
    srv, _ = fake
    srv.fill_fraction = 0.5
    status, body = _run(_payload())
    ocos = srv.calls("POST", "/open/v1/orders/oco")
    assert float(ocos[0]["quantity"]) == pytest.approx(body["executed_qty"]) and body["executed_qty"] < 2.0


def test_exchange_rejection_is_502_and_no_oco(fake):
    srv, db = fake
    srv.buy_error = {"code": 3210, "msg": "yetersiz bakiye"}
    with pytest.raises(open_position.OrderError) as e:
        _run(_payload())
    assert e.value.status_code == 502 and srv.calls("POST", "/open/v1/orders/oco") == []
    assert db.rows[(7, "e2e0000001")]["status"] == "failed"


def test_over_cap_never_reaches_exchange(fake):
    srv, _ = fake
    with pytest.raises(open_position.OrderError):
        _run(_payload(amount_try=900.0))
    assert srv.calls("POST", "/open/v1/orders") == []


def test_price_falls_back_to_public_ticker_when_not_in_memory(fake):
    srv, _ = fake
    assert asyncio.run(BinanceExchange(KEY, SECRET).price("ADA_TRY")) == srv.price
