"""binance_tr_private adapter birim testleri (HTTP mock'lu)."""
from unittest import mock

import pytest

from app import binance_tr_private as btp


@pytest.fixture(autouse=True)
def _reset_caches():
    btp._symbols_cache.update({"symbols": [], "underscore_by_concat": {}, "expires": 0.0})
    btp._open_orders_cache.update({"orders": [], "expires": 0.0})
    yield
    btp._symbols_cache.update({"symbols": [], "underscore_by_concat": {}, "expires": 0.0})
    btp._open_orders_cache.update({"orders": [], "expires": 0.0})


def _mock_http(payload):
    return mock.patch.object(btp, "_http_get_json", return_value=payload)


def test_unwrap_success_returns_data():
    assert btp._unwrap({"code": 0, "msg": "success", "data": {"a": 1}}) == {"a": 1}


def test_unwrap_error_raises():
    with pytest.raises(RuntimeError, match="2002"):
        btp._unwrap({"code": 2002, "msg": "Key iptal", "data": None})


def test_to_underscore_symbol_prefers_common_symbols_map():
    btp._symbols_cache.update({
        "symbols": ["BTC_USDT"],
        "underscore_by_concat": {"BTCUSDT": "BTC_USDT"},
        "expires": 1e12,
    })
    assert btp._to_underscore_symbol("BTCUSDT") == "BTC_USDT"


def test_to_underscore_symbol_fallback_quote_suffix():
    assert btp._to_underscore_symbol("SOLUSDT") == "SOL_USDT"
    assert btp._to_underscore_symbol("AVAX_TRY") == "AVAX_TRY"


def test_account_balance_maps_account_assets():
    payload = {
        "code": 0,
        "msg": "success",
        "data": {
            "canTrade": 1,
            "accountAssets": [
                {"asset": "ADA", "free": "272.55", "locked": "3.0"},
                {"asset": "USDT", "free": "10", "locked": "0"},
            ],
        },
    }
    with _mock_http(payload):
        balances = btp.get_account_balance("k", "s")
    assert balances[0] == {"asset": "ADA", "free": "272.55", "locked": "3.0"}
    assert len(balances) == 2


def test_trade_history_normalizes_fields():
    payload = {
        "code": 0,
        "msg": "success",
        "data": {
            "list": [
                {"tradeId": "301", "orderId": "21", "symbol": "BTC_USDT", "price": "7100",
                 "qty": "0.01", "quoteQty": "71", "commission": "0.00001",
                 "commissionAsset": "BTC", "isBuyer": True, "isMaker": False, "time": "1572862581000"},
            ]
        },
    }
    with _mock_http(payload):
        trades = btp.get_trade_history("k", "s", "BTCUSDT", 1000, 2000, 50, 0)
    t = trades[0]
    assert t["id"] == 301
    assert t["symbol"] == "BTCUSDT"
    assert t["isBuyer"] is True
    assert t["time"] == 1572862581000


def test_trade_history_uses_underscore_symbol_and_direct():
    btp._symbols_cache.update({
        "symbols": ["BTC_USDT"],
        "underscore_by_concat": {"BTCUSDT": "BTC_USDT"},
        "expires": 1e12,
    })
    payload = {"code": 0, "msg": "success", "data": {"list": []}}
    with mock.patch.object(btp, "_signed_request", return_value=payload) as sr:
        btp.get_trade_history("k", "s", "BTCUSDT", None, None, 50, 100)
    args = sr.call_args
    params = args[0][2]
    assert params["symbol"] == "BTC_USDT"
    assert params["fromId"] == 100
    assert params["direct"] == "prev"
    assert params["limit"] == 50


def test_open_orders_no_symbol_accepted():
    payload = {"code": 0, "msg": "success",
               "data": {"list": [{"orderId": "21", "symbol": "ADA_USDT", "side": "BUY",
                                   "type": "LIMIT", "price": "0.1", "origQty": "10",
                                   "executedQty": "0", "status": "NEW",
                                   "createTime": "1572862581000"}]}}
    with _mock_http(payload):
        orders = btp.get_open_orders("k", "s")
    assert orders == [{
        "orderId": 21, "symbol": "ADA_USDT", "side": "BUY", "type": "LIMIT",
        "price": "0.1", "stopPrice": "0", "origQty": "10", "executedQty": "0",
        "status": "NEW", "time": 1572862581000, "orderListId": -1, "clientOrderId": "",
    }]


def test_open_orders_falls_back_to_symbol_sweep():
    # Sembolsüz istek API hatası veriyor → sembol listesi çekilip tarama yapılır.
    calls = {"n": 0}

    def fake_http(url, headers=None):
        calls["n"] += 1
        if "common/symbols" in url:
            return {"code": 0, "msg": "success",
                    "data": {"list": [{"symbol": "BTC_USDT"}, {"symbol": "ADA_USDT"}]}}
        return {"code": 4012, "msg": "symbol required", "data": None}

    def fake_signed(method, path, params, api_key, api_secret):
        assert params["type"] == 1
        if "symbol" not in params:
            # Sembolsüz istek reddediliyor (doküman: symbol zorunlu).
            raise RuntimeError("Binance TR API hatası 4012: symbol required")
        if params["symbol"] == "ADA_USDT":
            return {"list": [{"orderId": "7", "symbol": "ADA_USDT", "side": "SELL",
                              "type": "LIMIT", "price": "1", "origQty": "5",
                              "executedQty": "0", "status": "NEW", "createTime": "1"}]}
        return {"list": []}

    with mock.patch.object(btp, "_http_get_json", side_effect=fake_http), \
         mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        orders = btp.get_open_orders("k", "s")
    assert len(orders) == 1
    assert orders[0]["symbol"] == "ADA_USDT"


def test_fmt_quantity_trims_trailing_zeros():
    assert btp._fmt_quantity(0.10000000) == "0.1"
    assert btp._fmt_quantity(1.0) == "1"
    assert btp._fmt_quantity(0.12345678) == "0.12345678"


def test_place_market_sell_sends_side_1_type_2():
    with mock.patch.object(btp, "_signed_request", return_value={"orderId": "42"}) as sr:
        result = btp.place_market_sell("k", "s", "BTC_USDT", 0.16)
    args = sr.call_args
    assert args[0][0] == "POST"
    assert args[0][1] == "/open/v1/orders"
    params = args[0][2]
    assert params["symbol"] == "BTC_USDT"
    assert params["side"] == 1
    assert params["type"] == 2
    assert params["quantity"] == "0.16"
    assert result == {"order_id": "42", "symbol": "BTC_USDT", "quantity": "0.16"}


def test_get_symbol_filters_parses_lot_size():
    def fake_http(url, headers=None):
        assert "common/symbols" in url
        return {"code": 0, "msg": "success",
                "data": {"list": [{"symbol": "BTC_USDT", "quoteAsset": "USDT",
                                   "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.00010000", "minQty": "0.00010000"},
                                               {"filterType": "NOTIONAL", "minNotional": "10"}]}]}}

    btp._symbols_cache.update({"symbols": [], "underscore_by_concat": {}, "expires": 0.0, "filters": {}})
    with mock.patch.object(btp, "_http_get_json", side_effect=fake_http):
        filters = btp.get_symbol_filters("k", "s", "BTC_USDT")
    assert filters["step_size"] == 0.0001
    assert filters["min_qty"] == 0.0001
    assert filters["min_notional"] == 10
    assert filters["quote_asset"] == "USDT"


def test_fmt_price_rounds_to_tick_size():
    assert btp._fmt_price(123.4567, 0.01) == "123.46"
    assert btp._fmt_price(0.001234, 0.0001) == "0.0012"
    assert btp._fmt_price(55.0, 0.5) == "55.0"


def test_place_oco_sell_sends_correct_payload():
    mock_resp = {
        "orderListId": "1001",
        "orders": [{"orderId": "1"}, {"orderId": "2"}],
    }
    with mock.patch.object(btp, "_signed_request", return_value=mock_resp) as sr:
        res = btp.place_oco_sell("k", "s", "AVAX_TRY", 10.5, price=1200.0, stop_price=950.0, stop_limit_price=945.0)
    args = sr.call_args
    assert args[0][0] == "POST"
    assert args[0][1] == "/open/v1/orders/oco"
    params = args[0][2]
    assert params["symbol"] == "AVAX_TRY"
    assert params["side"] == "SELL"
    assert params["quantity"] == "10.5"
    assert params["price"] == "1200.00"
    assert params["stopPrice"] == "950.00"
    assert params["stopLimitPrice"] == "945.00"
    assert res["order_list_id"] == "1001"
    assert len(res["orders"]) == 2


def test_place_stop_loss_sell_sends_correct_payload():
    mock_resp = {"orderId": "505"}
    with mock.patch.object(btp, "_signed_request", return_value=mock_resp) as sr:
        res = btp.place_stop_loss_sell("k", "s", "SOL_TRY", 2.0, stop_price=5000.0, stop_limit_price=4980.0)
    args = sr.call_args
    assert args[0][0] == "POST"
    assert args[0][1] == "/open/v1/orders"
    params = args[0][2]
    assert params["symbol"] == "SOL_TRY"
    assert params["side"] == "SELL"
    assert params["type"] == "STOP_LOSS_LIMIT"
    assert params["stopPrice"] == "5000.00"
    assert params["price"] == "4980.00"
    assert res["order_id"] == "505"


def test_place_limit_sell_sends_correct_payload():
    mock_resp = {"orderId": "606"}
    with mock.patch.object(btp, "_signed_request", return_value=mock_resp) as sr:
        res = btp.place_limit_sell("k", "s", "SOL_TRY", 1.5, price=6500.0)
    args = sr.call_args
    assert args[0][0] == "POST"
    assert args[0][1] == "/open/v1/orders"
    params = args[0][2]
    assert params["symbol"] == "SOL_TRY"
    assert params["side"] == "SELL"
    assert params["type"] == "LIMIT"
    assert params["price"] == "6500.00"
    assert res["order_id"] == "606"


def test_cancel_order_sends_cancel_request():
    mock_resp = {"orderId": 999, "status": "CANCELED"}
    with mock.patch.object(btp, "_signed_request", return_value=mock_resp) as sr:
        res = btp.cancel_order("k", "s", 999, "BTC_TRY")
    args = sr.call_args
    assert args[0][0] == "POST"
    assert args[0][1] == "/open/v1/orders/cancel"
    params = args[0][2]
    assert params["orderId"] == 999
    assert params["symbol"] == "BTC_TRY"
    assert res["status"] == "CANCELED"

