"""binance_tr_private adapter birim testleri (HTTP mock'lu)."""
import time
import urllib.error
from unittest import mock

import pytest

from app import binance_tr_private as btp


_REAL_POLL_FILL = btp._poll_fill


@pytest.fixture(autouse=True)
def _no_fill_poll(monkeypatch):
    """Tek dönüş değerli `_signed_request` mock'ları POST ile detay GET'ini ayırmaz; dolum
    yoklaması varsayılan olarak 'detay okunamadı' ({}) döner. Yoklamayı sınayan testler
    `_REAL_POLL_FILL`'i geri takar."""
    monkeypatch.setattr(btp, "_poll_fill", lambda *a, **k: {})
    monkeypatch.setattr(btp, "DETAIL_RETRY_SLEEP_SEC", 0.0)


@pytest.fixture(autouse=True)
def _reset_caches():
    btp._symbols_cache.update({"symbols": [], "underscore_by_concat": {}, "expires": 0.0,
                               "filters": {}})
    btp._open_orders_caches.clear()
    btp._server_time_cache.update({"at": 0.0, "offset": 0.0, "failed_at": 0.0})
    btp._balance_cache.clear()
    btp._cooldown_until = 0.0
    btp._used_weight_1m = 0
    btp._weight_reported_at = 0.0
    yield
    btp._symbols_cache.update({"symbols": [], "underscore_by_concat": {}, "expires": 0.0,
                               "filters": {}})
    btp._open_orders_caches.clear()
    btp._server_time_cache.update({"at": 0.0, "offset": 0.0, "failed_at": 0.0})
    btp._balance_cache.clear()
    btp._cooldown_until = 0.0
    btp._used_weight_1m = 0
    btp._weight_reported_at = 0.0


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


def test_open_orders_never_sends_symbolless_request():
    """Doküman: GET /open/v1/orders için symbol ZORUNLU → sembolsüz deneme yapılmaz."""
    payload = {"code": 0, "msg": "success",
               "data": {"list": [{"orderId": "21", "symbol": "ADA_USDT", "side": "BUY",
                                   "type": "LIMIT", "price": "0.1", "origQty": "10",
                                   "executedQty": "0", "status": "NEW",
                                   "createTime": "1572862581000"}]}}
    urls = []

    def fake_http(url, headers=None):
        urls.append(url)
        return payload

    with mock.patch.object(btp, "_http_get_json", side_effect=fake_http):
        orders = btp.get_open_orders("k", "s")
    order_urls = [u for u in urls if "/open/v1/orders?" in u]
    assert order_urls and all("symbol=" in u for u in order_urls)
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
    # Güncel sözleşme (7057253c, resmi /open/v1 API): emir `clientId` taşır —
    # yalnız durum sorgusu/mutabakat içindir, dedupe anahtarı DEĞİLDİR. Tekrar
    # güvenliği `idempotent=False` ile sağlanır (belirsiz sonuçta ikinci emir yok).
    assert params["clientId"]
    assert "clientOrderId" not in params
    assert sr.call_args[1].get("idempotent") is False
    # #36/P1-8: dolum doğrulaması dönen sözlükte raporlanır (cevap executedQty
    # taşımadığında istenen miktar tam dolum kabul edilir).
    assert {k: result[k] for k in ("order_id", "symbol", "quantity", "client_order_id")} == {
        "order_id": "42", "symbol": "BTC_USDT", "quantity": "0.16",
        "client_order_id": params["clientId"]}
    assert result["executed_qty"] == 0.16
    assert result["remaining_qty"] == 0.0
    assert result["partial"] is False


def test_place_market_sell_raises_on_partial_fill():
    """#36/P1-8: kısmi dolum 'tam satıldı' sanılmamalı — açıkça yükseltilir."""
    resp = {"orderId": "42", "executedQty": "0.10", "cummulativeQuoteQty": "160"}
    with mock.patch.object(btp, "_signed_request", return_value=resp):
        with pytest.raises(btp.BinanceTrPartialFillError) as ctx:
            btp.place_market_sell("k", "s", "BTC_USDT", 0.16)
    err = ctx.value
    assert err.requested_qty == pytest.approx(0.16)
    assert err.executed_qty == pytest.approx(0.10)
    assert err.remaining_qty == pytest.approx(0.06)
    # Kısmi sonuç, çağıranın mutabakat yapabilmesi için hatada taşınır.
    assert err.result["order_id"] == "42"
    assert err.result["avg_price"] == pytest.approx(1600.0)
    assert err.result["remaining_qty"] == pytest.approx(0.06)


def test_place_market_sell_no_partial_when_fully_filled():
    """Tam dolumda kısmi hata YÜKSELTİLMEZ."""
    resp = {"orderId": "42", "executedQty": "0.16", "cummulativeQuoteQty": "256"}
    with mock.patch.object(btp, "_signed_request", return_value=resp):
        result = btp.place_market_sell("k", "s", "BTC_USDT", 0.16)
    assert result["executed_qty"] == pytest.approx(0.16)
    assert result["remaining_qty"] == 0.0
    assert result["partial"] is False
    assert result["avg_price"] == pytest.approx(1600.0)


def test_place_market_sell_derives_live_price_for_dust_guard(monkeypatch):
    """#36/P1-8: last_price geçilmese bile toz kapısı için fiyat TÜRETİLMELİ."""
    btp._symbols_cache["filters"] = {"BTC_TRY": {"min_notional": 50.0}}
    monkeypatch.setattr(btp, "_resolve_live_price", lambda sym: 1000.0)
    with mock.patch.object(btp, "_signed_request") as sr:
        with pytest.raises(ValueError, match="minimum emrin altında"):
            btp.place_market_sell("k", "s", "BTC_TRY", 0.00001)
    assert not sr.called


def test_reconcile_sell_fill_retries_the_remainder():
    """Kısmi dolumun kalanı yeni bir MARKET SELL ile satılır."""
    result = {"order_id": "42", "quantity": "0.16", "executed_qty": 0.10,
              "remaining_qty": 0.06, "partial": True}
    with mock.patch.object(btp, "place_market_sell",
                           return_value={"order_id": "99", "quantity": "0.06"}) as pms:
        out = btp.reconcile_sell_fill(result, "BTC_USDT", 0.16)
    assert out["partial"] is True
    assert out["dust_remaining"] is False
    assert out["retry_order_id"] == "99"
    assert out["retried_qty"] == "0.06"
    # Kalan miktar kayan nokta artığından arındırılmış olarak gönderildi.
    assert pms.call_args[0][3] == pytest.approx(0.06)


def test_reconcile_sell_fill_flags_dust_remainder():
    """Kalan miktar toz eşiğinin altındaysa tekrar satılmaz (dust_remaining)."""
    btp._symbols_cache["filters"] = {"BTC_USDT": {"min_notional": 10.0}}
    result = {"order_id": "42", "executed_qty": 0.10, "remaining_qty": 0.000001,
              "partial": True}
    with mock.patch.object(btp, "place_market_sell") as pms:
        out = btp.reconcile_sell_fill(result, "BTC_USDT", 0.10, last_price=1000.0)
    assert out["dust_remaining"] is True
    assert not pms.called


def test_signed_post_is_not_retried_after_a_500_even_with_client_id():
    """Binance TR clientId benzersizlik garantisi vermez (7057253c): clientId
    veya `idempotency_key` varlığı 5xx sonrası emir tekrarını AÇMAZ; sonuç
    belirsiz sayılır ve çağıran clientId ile durumu sorgular."""
    calls = {"n": 0}

    def flaky(url, headers=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)

    with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0), \
         mock.patch.object(btp, "_http_post_json", side_effect=flaky), \
         mock.patch.object(btp.time, "sleep") as sleeper:
        with pytest.raises(btp.BinanceTrAmbiguousOrderError) as ei:
            btp._signed_request(
                "POST", "/open/v1/orders",
                {"symbol": "BTC_TRY", "clientId": "sa-fixed-1"},
                "k", "s", idempotent=False, idempotency_key="sa-fixed-1")
    assert calls["n"] == 1
    assert not sleeper.called
    assert ei.value.client_order_id == "sa-fixed-1"
    assert ei.value.symbol == "BTC_TRY"


def test_place_market_buy_keeps_client_id_and_disables_post_retry():
    with mock.patch.object(btp, "_signed_request", return_value={"orderId": "77"}) as sr:
        out = btp.place_market_buy("k", "s", "BTC_TRY", 100.0, client_order_id="bufixed1")
    params = sr.call_args[0][2]
    # Çağıranın verdiği id `clientId` olarak korunur (durum sorgusu/mutabakat
    # için); dedupe değildir, bu yüzden POST tekrarı kapalıdır.
    assert params["clientId"] == "bufixed1"
    assert "clientOrderId" not in params
    assert out["client_order_id"] == "bufixed1"
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
        with pytest.raises(btp.BinanceTrAmbiguousOrderError, match="tekrar gönderilmedi") as ei:
            btp._signed_request("POST", "/open/v1/orders",
                                {"symbol": "BTC_TRY", "clientId": "sa-fixed-2"},
                                "k", "s", idempotent=False)
    assert calls["n"] == 1
    assert ei.value.client_order_id == "sa-fixed-2"


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
    btp._open_orders_caches.clear()
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
    btp._open_orders_caches.clear()

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
    # Resmi doküman (POST /open/v1/orders/oco): tekil `clientId`/`type` YOK; liste kimliği `listClientId`.
    assert "clientId" not in params and "type" not in params
    assert params["listClientId"].isalnum() and len(params["listClientId"]) <= 36
    assert res["client_order_id"] == params["listClientId"]
    assert res["order_list_id"] == "1001"
    assert len(res["orders"]) == 2


def test_place_oco_sell_custom_id_goes_to_list_client_id_and_doc_response_shape():
    # Doküman OCO cevabı: data.orderId + createTime (orderListId yok) → order_id döner, order_list_id None.
    with mock.patch.object(btp, "_signed_request", return_value={"orderId": "900", "createTime": 1}) as sr:
        res = btp.place_oco_sell("k", "s", "AVAX_TRY", 1.0, price=12.0, stop_price=9.0,
                                 stop_limit_price=8.9, client_order_id="oco-abc_123")
    params = sr.call_args[0][2]
    assert params["listClientId"] == "ocoabc123" and "clientId" not in params
    assert res["order_id"] == "900" and res["order_list_id"] is None
    assert res["client_order_id"] == "ocoabc123"


def test_ambiguous_oco_error_carries_list_client_id():
    def boom(url, headers=None):
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)

    with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0),          mock.patch.object(btp, "_http_post_json", side_effect=boom):
        with pytest.raises(btp.BinanceTrAmbiguousOrderError) as ei:
            btp._signed_request("POST", "/open/v1/orders/oco",
                                {"symbol": "ADA_TRY", "listClientId": "oclist1"},
                                "k", "s", idempotent=False)
    assert ei.value.client_order_id == "oclist1" and ei.value.symbol == "ADA_TRY"


def test_signed_request_matches_documented_signature_scheme():
    """Doküman: HMAC SHA256(secret, totalParams=query string); timestamp ms; recvWindow<=60000;
    X-MBX-APIKEY başlığı; POST parametreleri query string'te, gövde boş."""
    import hashlib
    import hmac
    seen = {}

    def fake_post(url, headers=None):
        seen["url"], seen["headers"] = url, headers
        return {"code": 0, "data": {"orderId": "1"}}

    with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0),          mock.patch.object(btp, "_http_post_json", side_effect=fake_post):
        btp._signed_request("POST", "/open/v1/orders", {"symbol": "BTC_TRY", "side": 0, "type": 2,
                                                         "quantity": "1"}, "KEY", "SECRET", idempotent=False)
    path, query = seen["url"].split("?", 1)
    assert path.endswith("/open/v1/orders") and seen["headers"] == {"X-MBX-APIKEY": "KEY"}
    total, sig = query.rsplit("&signature=", 1)
    assert hmac.new(b"SECRET", total.encode(), hashlib.sha256).hexdigest() == sig
    qs = dict(p.split("=") for p in total.split("&"))
    assert 0 < int(qs["recvWindow"]) <= 60000 and len(qs["timestamp"]) == 13


def test_documented_order_codes():
    # apidocs: side 0=BUY 1=SELL; type 1 LIMIT 2 MARKET 4 STOP_LOSS_LIMIT; timeInForce 1 GTC (INT)
    assert btp._ORDER_TYPE_CODES == {"LIMIT": 1, "MARKET": 2, "STOP_LOSS_LIMIT": 4}


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


def test_record_used_weight_updates_state():
    headers = {"X-Mbx-Used-Weight-1m": "850", "Content-Type": "application/json"}
    btp._record_used_weight(headers)
    assert btp._used_weight_1m == 850
    assert btp._weight_reported_at > 0


def test_throttle_private_request_sleeps_on_high_weight():
    btp._used_weight_1m = 1000
    btp._weight_reported_at = time.time()
    with mock.patch.object(btp.time, "sleep") as sleeper:
        btp._throttle_private_request()
    assert sleeper.called
    # Cleanup
    btp._used_weight_1m = 0
    btp._weight_reported_at = 0.0


def test_get_all_valid_symbols_from_cache():
    btp._symbols_cache["filters"] = {"BTC_TRY": {}, "ETH_USDT": {}}
    btp._symbols_cache["expires"] = time.monotonic() + 3600
    symbols = btp.get_all_valid_symbols("k", "s")
    assert "BTC_TRY" in symbols
    assert "ETH_USDT" in symbols






def test_sanitize_client_order_id_strips_dash_and_caps_36():
    # 2026-10-17: Binance TR 3703 "Invalid client ID" — tire kabul edilmiyor.
    assert btp.sanitize_client_order_id("web-0123456789abcdef0123456789abcdef") == "web0123456789abcdef0123456789abcdef"
    assert btp.sanitize_client_order_id("a_b-c d") == "abcd"
    assert btp.sanitize_client_order_id("x" * 50) == "x" * 36
    assert btp.sanitize_client_order_id("") is None
    assert btp.sanitize_client_order_id("---") is None


def test_place_market_sell_sanitizes_client_id():
    with mock.patch.object(btp, "_signed_request", return_value={"orderId": "42"}) as sr:
        result = btp.place_market_sell("k", "s", "BTC_USDT", 0.16, None, "web-abc123def456")
    params = sr.call_args[0][2]
    assert params["clientId"] == "webabc123def456"
    assert result["client_order_id"] == "webabc123def456"


def test_place_market_buy_sanitizes_client_id():
    with mock.patch.object(btp, "_signed_request", return_value={"orderId": "43"}) as sr:
        btp.place_market_buy("k", "s", "BTC_TRY", 500.0, None, "web-abc123def456")
    assert sr.call_args[0][2]["clientId"] == "webabc123def456"


# 2026-10-18: 3703 "Invalid client ID" → sunucu kimliğiyle BİR kez yeniden deneme (emir yerleştirilmemiştir, tekrar riski yok).
def _api_err(code, msg="Invalid client ID"):
    return btp.BinanceTrApiError(code, msg, http_code=200, raw={"code": code, "msg": msg})


def test_market_sell_retries_once_with_server_client_id_on_3703():
    calls = []

    def fake_signed(method, path, params, *a, **k):
        calls.append(dict(params))
        if len(calls) == 1:
            raise _api_err(3703)
        return {"orderId": "77"}

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        result = btp.place_market_sell("k", "s", "BTC_TRY", 0.5, None, "wb0123456789abcdef0123456789abcdef")
    assert len(calls) == 2
    assert calls[0]["clientId"] == "wb0123456789abcdef0123456789abcdef"
    assert calls[1]["clientId"].startswith("sa") and len(calls[1]["clientId"]) == 34
    assert calls[1]["quantity"] == calls[0]["quantity"] and calls[1]["symbol"] == "BTC_TRY"
    assert result["client_order_id"] == calls[1]["clientId"]
    assert result["order_id"] == "77"


def test_market_buy_and_limit_retry_prefixes_on_3703():
    seen = []

    def fake_signed(method, path, params, *a, **k):
        seen.append(dict(params))
        if len(seen) % 2 == 1:
            raise _api_err("3703")
        return {"orderId": "78"}

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        btp.place_market_buy("k", "s", "BTC_TRY", 500.0, None, "wbdeadbeef00000000000000000000000000")
        btp.place_limit_sell("k", "s", "BTC_TRY", 0.5, 101.0, None, None, client_order_id="wbdeadbeef00000000000000000000000001")
    assert seen[1]["clientId"].startswith("bu")
    assert seen[3]["clientId"].startswith("tp")


def test_second_3703_propagates_and_other_codes_do_not_retry():
    with mock.patch.object(btp, "_signed_request", side_effect=_api_err(3703)) as sr:
        with pytest.raises(btp.BinanceTrApiError):
            btp.place_market_sell("k", "s", "BTC_TRY", 0.5, None, "wbaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert sr.call_count == 2
    with mock.patch.object(btp, "_signed_request", side_effect=_api_err(-2010, "insufficient balance")) as sr:
        with pytest.raises(btp.BinanceTrApiError):
            btp.place_market_sell("k", "s", "BTC_TRY", 0.5, None, "wbaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert sr.call_count == 1


def test_oco_retries_with_server_list_client_id_on_3703():
    calls = []

    def fake_signed(method, path, params, *a, **k):
        calls.append(dict(params))
        if len(calls) == 1:
            raise _api_err(3703)
        return {"orderId": "79", "createTime": 1}

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed), \
            mock.patch.object(btp, "get_symbol_filters", return_value=None), \
            mock.patch.object(btp, "_resolve_live_price", return_value=100.0):
        res = btp.place_oco_sell("k", "s", "BTC_TRY", 0.5, 105.0, 95.0, client_order_id="wb0000000000000000000000000000000000")
    assert calls[1]["listClientId"].startswith("oc")
    assert res["client_order_id"] == calls[1]["listClientId"]


# ---------------------------------------------------------------- 2026-10-18 doküman denetimi

def test_step_rounding_is_exact_decimal():
    # math.floor(1.15/0.01) float kaymasıyla 114 → "1.14" veriyordu.
    assert btp._fmt_quantity(1.15, 0.01) == "1.15"
    assert btp._fmt_quantity(0.3, 0.1) == "0.3"
    assert btp._fmt_quantity(0.129, 0.01) == "0.12"          # aşağı yuvarlama korunur
    assert btp._fmt_price(1.005, 0.01) == "1.01"              # tick: en yakına (Decimal, kayma yok)


def test_reconcile_keeps_exact_remainder_on_step():
    result = {"order_id": "42", "executed_qty": 0.7, "remaining_qty": 0.3, "partial": True}
    with mock.patch.object(btp, "place_market_sell", return_value={"order_id": "9", "quantity": "0.3"}) as pms:
        out = btp.reconcile_sell_fill(result, "X_TRY", 1.0, step_size=0.1)
    assert out["remaining_qty"] == 0.3
    assert pms.call_args[0][3] == 0.3


def _post_then_detail(post_resp, *details):
    """POST cevabı ile GET /orders/detail cevaplarını ayıran sahte _signed_request."""
    seq = list(details)
    calls = []

    def fake(method, path, params, *a, **k):
        calls.append((method, path, dict(params or {})))
        if method == "POST":
            return post_resp
        assert path == "/open/v1/orders/detail"
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return fake, calls


def test_market_sell_verifies_fill_via_order_detail(monkeypatch):
    monkeypatch.setattr(btp, "_poll_fill", _REAL_POLL_FILL)
    fake, calls = _post_then_detail({"orderId": 42, "createTime": 1},
                                    {"orderId": 42, "status": 2, "executedQty": "0.16", "executedQuoteQty": "256"})
    with mock.patch.object(btp, "_signed_request", side_effect=fake):
        res = btp.place_market_sell("k", "s", "BTC_TRY", 0.16)
    assert [c[0] for c in calls] == ["POST", "GET"]            # FILLED → tek detay çağrısı yeter
    assert calls[1][2]["orderId"] == "42"
    assert res["fill_verified"] is True and res["order_status"] == 2
    assert res["executed_qty"] == pytest.approx(0.16) and res["avg_price"] == pytest.approx(1600.0)


def test_market_sell_partial_fill_from_detail_raises(monkeypatch):
    monkeypatch.setattr(btp, "_poll_fill", _REAL_POLL_FILL)
    fake, _ = _post_then_detail({"orderId": 42}, {"status": 6, "executedQty": "0.10", "executedQuoteQty": "160"})
    with mock.patch.object(btp, "_signed_request", side_effect=fake):
        with pytest.raises(btp.BinanceTrPartialFillError) as ei:
            btp.place_market_sell("k", "s", "BTC_TRY", 0.16)
    assert ei.value.remaining_qty == pytest.approx(0.06)
    assert ei.value.result["fill_verified"] is True


def test_market_sell_expired_without_fill_raises_price_range_error(monkeypatch):
    monkeypatch.setattr(btp, "_poll_fill", _REAL_POLL_FILL)
    fake, _ = _post_then_detail({"orderId": 42}, {"status": 6, "executedQty": "0", "executedQuoteQty": "0"})
    with mock.patch.object(btp, "_signed_request", side_effect=fake):
        with pytest.raises(btp.BinanceTrApiError) as ei:
            btp.place_market_sell("k", "s", "BTC_TRY", 0.16)
    assert ei.value.code == "EXPIRED" and "Price Range" in ei.value.msg


@pytest.mark.parametrize("status,code", [(3, "CANCELED"), (5, "REJECTED")])
def test_market_sell_final_without_fill_is_not_reported_as_filled(monkeypatch, status, code):
    monkeypatch.setattr(btp, "_poll_fill", _REAL_POLL_FILL)
    fake, _ = _post_then_detail({"orderId": 42}, {"status": status, "executedQty": "0", "executedQuoteQty": "0"})
    with mock.patch.object(btp, "_signed_request", side_effect=fake):
        with pytest.raises(btp.BinanceTrApiError) as ei:
            btp.place_market_sell("k", "s", "BTC_TRY", 0.16)
    assert ei.value.code == code and "satış yapılmadı" in ei.value.msg


def test_poll_fill_retries_until_final_status_then_stops(monkeypatch):
    monkeypatch.setattr(btp, "_poll_fill", _REAL_POLL_FILL)
    fake, calls = _post_then_detail({"orderId": 42}, {"status": 0, "executedQty": "0"},
                                    {"status": 2, "executedQty": "0.16", "executedQuoteQty": "256"})
    with mock.patch.object(btp, "_signed_request", side_effect=fake):
        res = btp.place_market_sell("k", "s", "BTC_TRY", 0.16)
    assert len([c for c in calls if c[0] == "GET"]) == 2
    assert res["order_status"] == 2 and res["partial"] is False


def test_poll_fill_is_bounded_and_unverified_when_detail_fails(monkeypatch):
    monkeypatch.setattr(btp, "_poll_fill", _REAL_POLL_FILL)
    gets = []

    def fake(method, path, params, *a, **k):
        if method == "POST":
            return {"orderId": 42}
        gets.append(path)
        raise RuntimeError("detay yok")

    with mock.patch.object(btp, "_signed_request", side_effect=fake):
        res = btp.place_market_sell("k", "s", "BTC_TRY", 0.16)
    assert len(gets) == btp.DETAIL_TRIES
    assert res["fill_verified"] is False and res["executed_qty"] == pytest.approx(0.16)   # eski varsayım


def test_market_sell_skips_poll_when_post_carries_fill():
    with mock.patch.object(btp, "_poll_fill") as pf, \
            mock.patch.object(btp, "_signed_request", return_value={"orderId": "1", "executedQty": "0.16"}):
        res = btp.place_market_sell("k", "s", "BTC_TRY", 0.16)
    assert not pf.called and res["fill_verified"] is False


def test_order_fill_prefers_executed_quote_qty():
    assert btp._order_fill({"executedQty": "2", "executedQuoteQty": "10", "cummulativeQuoteQty": "99"}, 2.0)[2] == 5.0
    assert btp._order_fill({"executedQty": "2", "cummulativeQuoteQty": "12"}, 2.0)[2] == 6.0


def test_market_buy_reads_documented_fill_fields():
    with mock.patch.object(btp, "_signed_request",
                           return_value={"orderId": "7", "executedQty": "4", "executedQuoteQty": "400"}):
        out = btp.place_market_buy("k", "s", "ADA_TRY", 400.0)
    assert out["executed_qty"] == 4.0 and out["avg_price"] == 100.0


def _symbols_payload(**extra):
    row = {"symbol": "ADA_TRY", "quoteAsset": "TRY", "orderTypes": ["MARKET"],
           "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.01", "minQty": "0.01"}]}
    row.update(extra)
    return {"code": 0, "msg": "success", "data": {"list": [row]}}


def test_symbol_status_derived_from_spot_trading_enable():
    with _mock_http(_symbols_payload(spotTradingEnable=1)):
        assert btp.get_symbol_filters("k", "s", "ADA_TRY")["status"] == "TRADING"
    btp._symbols_cache["expires"] = 0.0
    with _mock_http(_symbols_payload()):                          # alan yok → TRADING (geriye dönük)
        assert btp.get_symbol_filters("k", "s", "ADA_TRY")["status"] == "TRADING"
    btp._symbols_cache["expires"] = 0.0
    with _mock_http(_symbols_payload(spotTradingEnable=0, status="TRADING")):   # açık status önceliklidir
        assert btp.get_symbol_filters("k", "s", "ADA_TRY")["status"] == "TRADING"


def test_spot_trading_disabled_blocks_place_spot_order():
    with _mock_http(_symbols_payload(spotTradingEnable=0)), \
            mock.patch.object(btp, "_signed_request") as sr:
        with pytest.raises(ValueError, match="işlemlere kapalı"):
            btp.place_spot_order("k", "s", "ADA_TRY", "SELL", "MARKET", quantity=1.0)
    assert not sr.called


def test_trade_history_uses_its_own_semaphore():
    assert btp._semaphore_for("GET", "/open/v1/orders/trades") is btp._HISTORY_SEMAPHORE
    assert btp._semaphore_for("GET", "/open/v1/account/spot") is btp._PRIVATE_SEMAPHORE
    assert btp._semaphore_for("POST", "/open/v1/orders") is btp._ORDER_SEMAPHORE


def test_retry_sleep_happens_outside_the_semaphore():
    """Geri çekilme uykusu yuvayı tutmaz: uyku sırasında semafor tam kapasitede olmalı."""
    sem = btp._PRIVATE_SEMAPHORE
    seen = []
    attempts = [0]

    def fake_get(url, headers=None):
        attempts[0] += 1
        if attempts[0] == 1:
            raise TimeoutError("yavaş")
        return {"code": 0, "data": {"ok": True}}

    def spy_sleep(_sec):
        free = 0
        while sem.acquire(blocking=False):
            free += 1
        for _ in range(free):
            sem.release()
        seen.append(free)

    with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0), \
            mock.patch.object(btp, "_http_get_json", side_effect=fake_get), \
            mock.patch.object(btp.time, "sleep", side_effect=spy_sleep):
        assert btp._signed_request("GET", "/open/v1/account/spot", None, "k", "s") == {"ok": True}
    assert seen == [btp.PRIVATE_MAX_CONCURRENCY]


def test_server_time_failure_is_retried_at_most_every_few_seconds():
    btp._server_time_cache.update({"at": 0.0, "offset": 77.0, "failed_at": 0.0})
    with mock.patch.object(btp, "_http_get_json", side_effect=TimeoutError("down")) as http:
        assert btp._server_time_offset_ms() == 77.0
        assert btp._server_time_offset_ms() == 77.0
    assert http.call_count == 1
    btp._server_time_cache["failed_at"] = time.time() - btp._SERVER_TIME_RETRY_SEC - 1
    with mock.patch.object(btp, "_http_get_json", side_effect=TimeoutError("down")) as http:
        btp._server_time_offset_ms()
    assert http.call_count == 1


def test_account_balance_concurrent_calls_single_flight():
    import threading as _t
    calls = [0]
    gate = _t.Event()

    def slow(*a, **k):
        calls[0] += 1
        gate.wait(2)
        return {"accountAssets": [{"asset": "TRY", "free": "1", "locked": "0"}]}

    out = []
    with mock.patch.object(btp, "_signed_request", side_effect=slow):
        threads = [_t.Thread(target=lambda: out.append(btp.get_account_balance("keyX", "s"))) for _ in range(4)]
        for th in threads:
            th.start()
        time.sleep(0.2)
        gate.set()
        for th in threads:
            th.join(3)
    assert calls[0] == 1 and len(out) == 4


def test_open_orders_load_lock_is_per_api_key():
    assert btp._open_orders_load_lock_for("a") is btp._open_orders_load_lock_for("a")
    assert btp._open_orders_load_lock_for("a") is not btp._open_orders_load_lock_for("b")


def test_open_orders_parallel_sweep_preserves_order():
    btp._symbols_cache.update({"symbols": ["A_TRY", "B_TRY", "C_TRY"], "underscore_by_concat": {},
                               "expires": 1e12, "filters": {}})

    def fake_signed(method, path, params, *a, **k):
        if path == "/open/v1/account/spot":
            raise RuntimeError("bakiye yok")
        sym = params["symbol"]
        if sym == "A_TRY":
            time.sleep(0.05)                      # ilk sembol en geç dönse de sıra korunur
        return {"list": [{"orderId": {"A_TRY": 1, "B_TRY": 2, "C_TRY": 3}[sym], "symbol": sym}]}

    with mock.patch.object(btp, "_signed_request", side_effect=fake_signed):
        orders = btp.get_open_orders("k", "s")
    assert [o["orderId"] for o in orders] == [1, 2, 3]


def test_symbols_for_asset_helper():
    assert btp._symbols_for_asset("BTC", {"BTC_TRY", "ETH_TRY"}) == ["BTC_TRY"]
    assert btp._symbols_for_asset("BTC", {"BTC_TRY", "BTC_USDT"}) == ["BTC_TRY", "BTC_USDT"]
