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
        "price": "0.1", "origQty": "10", "executedQty": "0", "status": "NEW",
        "time": 1572862581000,
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
