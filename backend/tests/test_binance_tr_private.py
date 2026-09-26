"""binance_tr_private adapter birim testleri (HTTP mock'lu)."""
import urllib.error
from unittest import mock

import pytest

from app import binance_tr_private as btp


@pytest.fixture(autouse=True)
def _reset_caches():
    btp._symbols_cache.update({"symbols": [], "underscore_by_concat": {}, "expires": 0.0,
                               "filters": {}})
    btp._open_orders_cache.update({"orders": [], "expires": 0.0, "partial": False})
    btp._server_time_cache.update({"at": 0.0, "offset": 0.0})
    btp._balance_cache.clear()
    yield
    btp._symbols_cache.update({"symbols": [], "underscore_by_concat": {}, "expires": 0.0,
                               "filters": {}})
    btp._open_orders_cache.update({"orders": [], "expires": 0.0, "partial": False})
    btp._server_time_cache.update({"at": 0.0, "offset": 0.0})
    btp._balance_cache.clear()


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

    def fake_signed(method, path, params, api_key, api_secret, **kwargs):
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
    # #30 idempotency: emir bir clientOrderId taşır ve POST idempotent=False ile
    # atılır (timeout sonrası ikinci emir gönderilmez).
    assert params["clientOrderId"]
    assert sr.call_args[1].get("idempotent") is False
    assert result == {"order_id": "42", "symbol": "BTC_USDT", "quantity": "0.16",
                      "client_order_id": params["clientOrderId"]}


def test_place_market_buy_is_idempotent_and_keeps_client_order_id():
    with mock.patch.object(btp, "_signed_request", return_value={"orderId": "77"}) as sr:
        btp.place_market_buy("k", "s", "BTC_TRY", 100.0, client_order_id="bu-fixed-1")
    params = sr.call_args[0][2]
    # Çağıranın verdiği anahtar korunur → aynı iş mantığının yeniden
    # denemesi borsada ikinci bir emir oluşturmaz.
    assert params["clientOrderId"] == "bu-fixed-1"
    assert sr.call_args[1].get("idempotent") is False


def test_signed_post_is_not_retried_after_a_timeout():
    """#30: borsa emri ALDIĞI HALDE cevap kaybolursa ikinci kez atılmaz."""
    calls = {"n": 0}

    def timeout(url, headers=None):
        calls["n"] += 1
        raise TimeoutError("read timed out")

    with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0), \
         mock.patch.object(btp, "_http_post_json", side_effect=timeout) as sleeper_spy, \
         mock.patch.object(btp.time, "sleep"):
        with pytest.raises(RuntimeError, match="TEKRAR GÖNDERİLMEDİ"):
            btp._signed_request("POST", "/open/v1/orders", {"symbol": "BTC_TRY"},
                                "k", "s", idempotent=False)
    assert calls["n"] == 1


def test_signed_post_is_not_retried_after_a_500():
    """#30: 5xx'te 'emri aldım ama cevabım bozuk' ayırt edilemez."""
    calls = {"n": 0}

    def server_error(url, headers=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)

    with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0), \
         mock.patch.object(btp, "_http_post_json", side_effect=server_error), \
         mock.patch.object(btp.time, "sleep") as sleeper:
        with pytest.raises(RuntimeError):
            btp._signed_request("POST", "/open/v1/orders", {"symbol": "BTC_TRY"},
                                "k", "s", idempotent=False)
    assert calls["n"] == 1
    assert not sleeper.called


def test_signed_post_retries_on_429_because_the_exchange_rejected_it():
    """#30: 429'da borsa isteği ALMAMIŞTIR → yeniden denemek güvenlidir."""
    calls = {"n": 0}

    def throttled(url, headers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(url, 429, "rate", {}, None)
        return {"code": 0, "data": {"orderId": "5"}}

    with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0), \
         mock.patch.object(btp, "_http_post_json", side_effect=throttled), \
         mock.patch.object(btp.time, "sleep"):
        result = btp._signed_request("POST", "/open/v1/orders", {"symbol": "BTC_TRY"},
                                     "k", "s", idempotent=False)
    assert result == {"orderId": "5"}
    assert calls["n"] == 2


def test_signed_get_is_still_retried_after_a_timeout():
    """#30: okuma (GET) idempotenttir — yeniden deneme korunur."""
    calls = {"n": 0}

    def flaky(url, headers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("read timed out")
        return {"code": 0, "data": {"ok": True}}

    with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0), \
         mock.patch.object(btp, "_http_get_json", side_effect=flaky), \
         mock.patch.object(btp.time, "sleep"):
        result = btp._signed_request("GET", "/open/v1/account/spot", None, "k", "s")
    assert result == {"ok": True}
    assert calls["n"] == 2


def test_retry_delay_honours_retry_after_without_truncating_it():
    """#31/#33: Retry-After 4 sn'ye kırpılmaz."""
    assert btp._private_retry_delay(1, {"Retry-After": "120"}) == 120.0
    assert btp._private_retry_delay(1, {"Retry-After": "99999"}) == btp.REST_RETRY_AFTER_MAX_SEC
    # Header yoksa üstel backoff + jitter.
    assert btp._private_retry_delay(1) < btp.REST_BACKOFF_MAX_SEC


def test_ban_backoff_is_minutes_not_seconds():
    """#32: 418 geri çekilmesi 30/60/90 sn değil, onlarca dakika."""
    first = btp._private_ban_delay(1)
    second = btp._private_ban_delay(2)
    assert first >= 600
    assert second > first
    # Sunucunun ipucu varsa esas alınır; ban ipucu 429 tavanından uzun
    # süre bildirebildiği için ban tavanı (1 saat) uygulanır.
    assert btp._private_ban_delay(1, {"Retry-After": "900"}) == 900.0
    assert btp._private_ban_delay(1, {"Retry-After": "999999"}) == btp.REST_BAN_BACKOFF_MAX_SEC


def test_recv_window_is_wide_enough_for_clock_drift():
    """#35: 5 sn'lik pencere saat kaymasında tüm imzalı akışı kırıyordu."""
    assert btp.RECV_WINDOW_MS >= 10000
    assert btp._SERVER_TIME_TTL_SEC <= btp.RECV_WINDOW_MS


def test_server_time_offset_keeps_the_last_known_value_on_failure():
    """#35: ölçüm başarısız olursa ofset 0'a DÜŞMEZ."""
    btp._server_time_cache.update({"at": 0.0, "offset": 1234.0})
    with mock.patch.object(btp, "_http_get_json", side_effect=TimeoutError("down")):
        offset = btp._server_time_offset_ms()
    assert offset == 1234.0
    btp._server_time_cache.update({"at": 0.0, "offset": 0.0})


def test_place_market_sell_rejects_dust_below_min_notional():
    """#34: 5 TRY'lik toz bakiye borsada filtreye takılıp 502 üretiyordu."""
    with mock.patch.object(btp, "_signed_request") as sr:
        with pytest.raises(ValueError, match="minimum emrin altında"):
            btp.place_market_sell("k", "s", "BTC_TRY", 0.00001,
                                  min_notional=50.0, last_price=1000.0)
    assert not sr.called


def test_place_market_sell_allows_orders_above_min_notional():
    with mock.patch.object(btp, "_signed_request", return_value={"orderId": "3"}) as sr:
        btp.place_market_sell("k", "s", "BTC_TRY", 0.5,
                              min_notional=50.0, last_price=1000.0)
    assert sr.call_args[0][2]["quantity"] == "0.5"


def test_open_orders_sweep_is_bounded_and_reports_partial(caplog):
    """#33: tarama sınırlıdır ve hatalar yutulmaz."""
    symbols = [f"C{i}_TRY" for i in range(btp._OPEN_ORDERS_SWEEP_MAX + 25)]
    btp._symbols_cache.update({"symbols": symbols, "underscore_by_concat": {},
                               "expires": 1e12, "filters": {}})
    btp._open_orders_cache.update({"orders": [], "expires": 0.0, "partial": False})
    seen = []

    def fake_signed(method, path, params, api_key, api_secret, **kwargs):
        if "symbol" not in params:
            raise RuntimeError("Binance TR API hatası 4012: symbol required")
        seen.append(params["symbol"])
        return {"list": []}

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        orders = btp.get_open_orders("k", "s")
    assert orders == []
    assert len(seen) == btp._OPEN_ORDERS_SWEEP_MAX
    assert btp.get_open_orders_partial("k", "s") is True
    assert any("KISMİ" in r.message for r in caplog.records)


def test_open_orders_sweep_reports_symbol_failures(caplog):
    """#33: `except Exception: continue` sessizce eksik liste üretiyordu."""
    btp._symbols_cache.update({"symbols": ["A_TRY", "B_TRY"], "underscore_by_concat": {},
                               "expires": 1e12, "filters": {}})
    btp._open_orders_cache.update({"orders": [], "expires": 0.0, "partial": False})

    def fake_signed(method, path, params, api_key, api_secret, **kwargs):
        if "symbol" not in params:
            raise RuntimeError("Binance TR API hatası 4012: symbol required")
        if params["symbol"] == "A_TRY":
            raise RuntimeError("Binance TR API hatası 4010: bilinmeyen sembol")
        return {"list": []}

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        btp.get_open_orders("k", "s")
    assert btp.get_open_orders_partial("k", "s") is True
    assert any("sorgulanamadı" in r.message for r in caplog.records)


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
    assert params["side"] == 1        # doküman: 1=SELL
    assert params["quantity"] == "10.5"
    assert params["price"] == "1200.00"
    assert params["stopPrice"] == "950.00"
    assert params["stopLimitPrice"] == "945.00"
    assert "stopLimitTimeInForce" not in params  # Binance TR OCO'da bu parametre yoktur
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
    assert params["side"] == 1        # doküman: 1=SELL
    assert params["type"] == 4        # doküman: 4=STOP_LOSS_LIMIT
    assert params["timeInForce"] == 1 # doküman: INT: 1=GTC
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
    assert params["side"] == 1        # doküman: 1=SELL
    assert params["type"] == 1        # doküman: 1=LIMIT
    assert params["timeInForce"] == 1 # doküman: INT: 1=GTC
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


def test_binance_tr_api_error_is_transient():
    err1008 = btp.BinanceTrApiError(1008, "Unknown error")
    assert err1008.is_transient is True

    err_busy = btp.BinanceTrApiError(-1008, "Server busy")
    assert err_busy.is_transient is True

    err_rate = btp.BinanceTrApiError(1003, "Too many requests")
    assert err_rate.is_transient is True

    err_auth = btp.BinanceTrApiError(2002, "API key expired")
    assert err_auth.is_transient is False


def test_signed_request_retries_on_transient_1008_error():
    attempts = [0]

    def fake_get(url, headers=None):
        attempts[0] += 1
        if attempts[0] == 1:
            # İlk denemede Binance TR 1008 Unknown error dönsün
            return {"code": 1008, "msg": "Unknown error", "data": None}
        return {"code": 0, "msg": "success", "data": {"serverTime": 1700000000000}}

    with mock.patch.object(btp, "_http_get_json", side_effect=fake_get), \
         mock.patch("time.sleep", return_value=None):
        res = btp._signed_request("GET", "/open/v1/time", None, "k", "s", idempotent=True)
    assert attempts[0] == 2
    assert res == {"serverTime": 1700000000000}


def test_get_account_balance_caches_and_deduplicates():
    calls = [0]
    payload = {
        "code": 0, "msg": "success",
        "data": {
            "accountAssets": [
                {"asset": "TRY", "free": "1000", "locked": "0"},
            ]
        }
    }

    def fake_signed(*args, **kwargs):
        calls[0] += 1
        return payload["data"]

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        b1 = btp.get_account_balance("key1", "sec1")
        b2 = btp.get_account_balance("key1", "sec1")
    assert len(b1) == 1
    assert len(b2) == 1
    # 5 sn cache sayesinde ikinci çağrı ağ isteği yapmaz
    assert calls[0] == 1


def test_invalidate_account_balance_cache():
    calls = [0]
    def fake_signed(*args, **kwargs):
        calls[0] += 1
        return {"accountAssets": [{"asset": "BTC", "free": "0.1", "locked": "0"}]}

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        btp.get_account_balance("key1", "sec1")
        assert calls[0] == 1
        btp.invalidate_account_balance_cache("key1")
        btp.get_account_balance("key1", "sec1")
        assert calls[0] == 2


def test_open_orders_with_zero_locked_assets_makes_zero_order_requests():
    # Bakiyede locked == 0 olduğunda /open/v1/orders'a HİÇ istek gitmemeli
    order_calls = []

    def fake_signed(method, path, params, *args, **kwargs):
        if path == "/open/v1/account/spot":
            return {
                "accountAssets": [
                    {"asset": "TRY", "free": "5000", "locked": "0"},
                    {"asset": "BTC", "free": "0.05", "locked": "0"},
                ]
            }
        if path == "/open/v1/orders":
            order_calls.append(params)
            return {"list": []}
        return {}

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        orders = btp.get_open_orders("k", "s")
    assert orders == []
    # /open/v1/orders'a hiç çağrı gitmedi çünkü locked == 0
    assert len(order_calls) == 0


