"""W10 kilit testleri — borsa adaptörleri & evren kaydı (B-11, B-13, B-14, B-20)."""
import json
import pathlib
import sys
import threading
import time
import unittest
import urllib.error
from unittest import mock
from urllib.parse import urlparse, parse_qs

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeResponse:
    """urlopen bağlam yöneticisi taklidi."""

    def __init__(self, payload: bytes, headers=None):
        self._payload = payload
        self.headers = headers if headers is not None else {}

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _RecordingSemaphore:
    def __init__(self):
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------- B-11
class PublicConcurrencyAndWeightTests(unittest.TestCase):
    def test_every_request_goes_through_the_shared_limit(self):
        from app import binance_tr_public as pub

        recorder = _RecordingSemaphore()
        with mock.patch.object(pub, "_REQUEST_SEMAPHORE", recorder), \
             mock.patch.object(pub, "urlopen", return_value=_FakeResponse(b"[1,2,3]")):
            result = pub._get_json("/api/v3/klines", {"symbol": "BTCTRY"})
        self.assertEqual([1, 2, 3], result)
        # Eski hâlde çağrı noktaları kendi Semaphore(8)'ini kuruyordu; ortak
        # sınır yoktu → 3 çağrı noktası × 8 = 24 eşzamanlı istek.
        self.assertEqual(1, recorder.entered)

    def test_throttle_waits_when_reported_weight_is_high(self):
        from app import binance_tr_public as pub

        saved = (pub._rate_limit_used["total"], pub._weight_reported_at)
        try:
            pub._rate_limit_used["total"] = pub.REST_WEIGHT_SOFT_LIMIT + 500
            pub._weight_reported_at = time.time()
            with mock.patch.object(pub.time, "sleep") as sleeper:
                pub._throttle_for_weight()
            self.assertTrue(sleeper.called, "ağırlık tavanda → beklemeli")
            delay = sleeper.call_args[0][0]
            self.assertGreater(delay, 0.0)
            self.assertLessEqual(delay, 60.0)
        finally:
            pub._rate_limit_used["total"], pub._weight_reported_at = saved

    def test_throttle_is_a_noop_when_weight_is_low(self):
        from app import binance_tr_public as pub

        saved = (pub._rate_limit_used["total"], pub._weight_reported_at)
        try:
            pub._rate_limit_used["total"] = 10
            pub._weight_reported_at = time.time()
            with mock.patch.object(pub.time, "sleep") as sleeper:
                pub._throttle_for_weight()
            self.assertFalse(sleeper.called)
        finally:
            pub._rate_limit_used["total"], pub._weight_reported_at = saved

    def test_snapshot_reports_client_side_limits(self):
        from app import binance_tr_public as pub
        snap = pub.rate_limit_snapshot()
        for key in ("total_weight_used", "by_endpoint", "last_reset_at",
                    "soft_limit", "max_concurrency", "weight_reported_at"):
            self.assertIn(key, snap)
        self.assertEqual(pub.REST_MAX_CONCURRENCY, snap["max_concurrency"])


# ---------------------------------------------------------------- B-13
class PublicRetryPolicyTests(unittest.TestCase):
    def test_418_is_backed_off_and_retried_not_raised_immediately(self):
        from app import binance_tr_public as pub

        def always_418(*_args, **_kwargs):
            raise urllib.error.HTTPError("https://api.binance.me", 418, "banned", {}, None)

        with mock.patch.object(pub, "urlopen", side_effect=always_418), \
             mock.patch.object(pub.time, "sleep") as sleeper:
            with self.assertRaises(RuntimeError) as ctx:
                pub._get_json("/api/v3/klines", {})
        # Eski hâl: `HTTP 418` ANINDA yükseltiliyordu (deneme yok).
        self.assertIn("denemede yanıt vermedi", str(ctx.exception))
        self.assertEqual(pub.REST_MAX_ATTEMPTS - 1, sleeper.call_count)

    def test_truncated_json_body_is_retried(self):
        from app import binance_tr_public as pub

        calls = {"n": 0}

        def flaky(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse(b'{"code":0,"data":[{"sym')
            return _FakeResponse(b'{"code":0,"data":[{"symbol":"BTCTRY"}]}')

        with mock.patch.object(pub, "urlopen", side_effect=flaky), \
             mock.patch.object(pub.time, "sleep"):
            result = pub._get_json("/api/v3/klines", {})
        self.assertEqual([{"symbol": "BTCTRY"}], result)
        self.assertEqual(2, calls["n"])

    def test_business_error_is_permanent_and_not_retried(self):
        from app import binance_tr_public as pub

        calls = {"n": 0}

        def business_error(*_args, **_kwargs):
            calls["n"] += 1
            return _FakeResponse(b'{"code":2002,"msg":"Key iptal"}')

        with mock.patch.object(pub, "urlopen", side_effect=business_error), \
             mock.patch.object(pub.time, "sleep") as sleeper:
            with self.assertRaises(RuntimeError):
                pub._get_json("/api/v3/klines", {})
        # Geçici (gövde) hataları yeniden denenir, iş kuralı hatası DENENMEZ.
        self.assertEqual(1, calls["n"])
        self.assertFalse(sleeper.called)

    def test_retry_after_is_not_truncated_to_four_seconds(self):
        """#31: `Retry-After: 120` 4 sn'ye kırpılınca 418'e tırmanılıyordu."""
        from app import binance_tr_public as pub

        self.assertEqual(120.0, pub._retry_delay(1, {"Retry-After": "120"}))
        # Yalnız çok yüksek tavan (5 dk) uygulanır.
        self.assertEqual(pub.REST_RETRY_AFTER_MAX_SEC,
                         pub._retry_delay(1, {"Retry-After": "999999"}))
        # Header yoksa üstel backoff + jitter korunur.
        self.assertLess(pub._retry_delay(1), pub.REST_BACKOFF_MAX_SEC)

    def test_429_backoff_uses_the_server_retry_after(self):
        from app import binance_tr_public as pub

        slept = []

        def throttled(*_args, **_kwargs):
            raise urllib.error.HTTPError("https://api.binance.me", 429, "slow down",
                                         {"Retry-After": "90"}, None)

        with mock.patch.object(pub, "urlopen", side_effect=throttled), \
             mock.patch.object(pub.time, "sleep", side_effect=slept.append):
            with self.assertRaises(RuntimeError):
                pub._get_json("/api/v3/klines", {})
        self.assertTrue(slept)
        self.assertTrue(all(delay >= 90.0 for delay in slept),
                        f"sunucu 90 sn dedi, istemci {slept} bekledi")

    def test_ban_backoff_is_minutes_not_30_60_90_seconds(self):
        """#32: 418 dakikalar-günler sürer; 30/60/90 sn banı garanti ederdi."""
        from app import binance_tr_public as pub

        self.assertGreaterEqual(pub._ban_delay(1), 600)
        self.assertGreater(pub._ban_delay(2), pub._ban_delay(1))
        self.assertLessEqual(pub._ban_delay(9), pub.REST_BAN_BACKOFF_MAX_SEC)
        # Sunucunun ipucu (Retry-After / Ban) varsa esas alınır; ban ipucu
        # 429 tavanından (5 dk) uzun süre bildirebilir, o yüzden ban tavanı
        # (1 saat) uygulanır.
        self.assertEqual(pub.REST_BAN_BACKOFF_MAX_SEC,
                         pub._ban_delay(1, {"Retry-After": "7200"}))
        self.assertEqual(1800.0, pub._ban_delay(1, {"Ban": "1800"}))

    def test_418_backoff_uses_the_ban_header(self):
        from app import binance_tr_public as pub

        slept = []

        def banned(*_args, **_kwargs):
            raise urllib.error.HTTPError("https://api.binance.me", 418, "banned",
                                         {"Retry-After": "1200"}, None)

        with mock.patch.object(pub, "urlopen", side_effect=banned), \
             mock.patch.object(pub.time, "sleep", side_effect=slept.append):
            with self.assertRaises(RuntimeError):
                pub._get_json("/api/v3/klines", {})
        self.assertEqual(pub.REST_MAX_ATTEMPTS - 1, len(slept))
        # Sunucu 1200 sn dedi → 1200 sn beklendi. 4 sn'e (eskiden kullanılan
        # tavan) kırpılmadığı gibi 1 saatlik ban tavanına da takılmadı.
        self.assertTrue(all(delay == 1200.0 for delay in slept),
                        f"418 geri çekilmesi sunucunun dediğinden saptı: {slept}")


# ---------------------------------------------------------------- #32 exchangeInfo cache
class ExchangeInfoCacheTests(unittest.TestCase):
    def setUp(self):
        from app import binance_tr_public as pub
        self.pub = pub
        pub._exchange_info_cache.update({"payload": None, "expires": 0.0})

    def tearDown(self):
        self.pub._exchange_info_cache.update({"payload": None, "expires": 0.0})

    def test_both_symbol_helpers_share_one_fetch(self):
        import asyncio

        payload = {"symbols": [
            {"symbol": "BTCTRY", "status": "TRADING", "quoteAsset": "TRY",
             "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                         {"filterType": "NOTIONAL", "minNotional": "10"}]},
        ]}
        calls = {"n": 0}

        def fake_get(path, params):
            calls["n"] += 1
            return payload

        with mock.patch.object(self.pub, "_get_json", side_effect=fake_get):
            symbols = asyncio.run(self.pub.trading_symbols("TRY"))
            filters = asyncio.run(self.pub.trading_symbols_with_filters("TRY"))
            # Üçüncü çağrı da (radar döngüsü tekrarı) ağa gitmemeli.
            again = asyncio.run(self.pub.trading_symbols("TRY"))

        self.assertEqual(1, calls["n"], "exchangeInfo üç kez çekildi")
        self.assertEqual(["BTCTRY"], symbols)
        self.assertEqual(10.0, filters["BTCTRY"]["min_notional"])
        self.assertEqual(again, symbols)

    def test_cache_expires_and_refetches(self):
        import asyncio

        calls = {"n": 0}

        def fake_get(path, params):
            calls["n"] += 1
            return {"symbols": []}

        with mock.patch.object(self.pub, "_get_json", side_effect=fake_get):
            asyncio.run(self.pub.trading_symbols("TRY"))
            self.pub._exchange_info_cache["expires"] = 0.0   # TTL doldu
            asyncio.run(self.pub.trading_symbols("TRY"))
        self.assertEqual(2, calls["n"])


# ---------------------------------------------------------------- #30 radar ticker_24h
class Ticker24hCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app import binance_tr_public as pub
        self.pub = pub
        pub._ticker_24h_cache.update({"key": None, "rows": None, "expires": 0.0})

    def tearDown(self):
        self.pub._ticker_24h_cache.update({"key": None, "rows": None, "expires": 0.0})

    async def test_back_to_back_calls_hit_the_network_once(self):
        """radar_loop 60 sn'de iki kez ticker_24h() çağırıyordu (weight 160)."""
        calls = {"n": 0}

        def fake(path, params):
            calls["n"] += 1
            if path == "/api/v3/exchangeInfo":
                return {"symbols": [
                    {"symbol": "BTCTRY", "status": "TRADING", "quoteAsset": "TRY",
                     "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001"}]}]}
            return [{"symbol": "BTCTRY", "priceChangePercent": "1.2",
                     "quoteVolume": "9000000", "lastPrice": "10", "highPrice": "11",
                     "lowPrice": "9", "count": "900"}]

        with mock.patch.object(self.pub, "_get_json", side_effect=fake):
            first = await self.pub.ticker_24h()
            second = await self.pub.ticker_24h()
            movers = await self.pub.top_gainers(5)
            pool = await self.pub.active_movers_pool(5)
        # 1 × ticker_24hr (weight 80) + 1 × exchangeInfo (önbellekli) = 2 istek.
        self.assertEqual(2, calls["n"], f"ticker_24h önbelleği atlandı: {calls['n']} istek")
        self.assertEqual(first, second)
        self.assertTrue(movers)
        self.assertTrue(pool)

    async def test_different_symbol_sets_are_not_served_from_the_same_cache(self):
        calls = {"n": 0}

        def fake(path, params):
            calls["n"] += 1
            return [{"symbol": params.get("symbols", "ALL")}]

        with mock.patch.object(self.pub, "_get_json", side_effect=fake):
            await self.pub.ticker_24h()
            await self.pub.ticker_24h(["BTCTRY"])
        self.assertEqual(2, calls["n"])

    async def test_cache_expires_and_refetches(self):
        calls = {"n": 0}

        def fake(path, params):
            calls["n"] += 1
            return []

        with mock.patch.object(self.pub, "_get_json", side_effect=fake):
            await self.pub.ticker_24h()
            self.pub._ticker_24h_cache["expires"] = 0.0
            await self.pub.ticker_24h()
        self.assertEqual(2, calls["n"])


# ---------------------------------------------------------------- B-14
class PrivateAdapterTests(unittest.TestCase):
    def setUp(self):
        from app import binance_tr_private as btp
        self.btp = btp
        self._saved_filters = dict(btp._symbols_cache.get("filters") or {})
        btp._symbols_cache["filters"] = {}

    def tearDown(self):
        self.btp._symbols_cache["filters"] = self._saved_filters

    def test_signed_request_applies_the_server_time_offset(self):
        btp = self.btp
        captured = {}

        def fake_get(url, headers=None):
            captured["url"] = url
            return {"code": 0, "data": {"ok": True}}

        before = int(time.time() * 1000)
        with mock.patch.object(btp, "_server_time_offset_ms", return_value=5000.0), \
             mock.patch.object(btp, "_http_get_json", side_effect=fake_get):
            result = btp._signed_request("GET", "/open/v1/account/spot", None, "k", "s")
        after = int(time.time() * 1000)

        query = parse_qs(urlparse(captured["url"]).query)
        timestamp = int(query["timestamp"][0])
        self.assertEqual({"ok": True}, result)
        self.assertGreaterEqual(timestamp, before + 5000 - 50)
        self.assertLessEqual(timestamp, after + 5000 + 50)

    def test_signed_request_retries_429(self):
        btp = self.btp
        attempts = {"n": 0}

        def flaky(url, headers=None):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                raise urllib.error.HTTPError(url, 429, "rate", {}, None)
            return {"code": 0, "data": {"ok": True}}

        with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0), \
             mock.patch.object(btp, "_http_get_json", side_effect=flaky), \
             mock.patch.object(btp.time, "sleep") as sleeper:
            result = btp._signed_request("GET", "/open/v1/account/spot", None, "k", "s")
        # Eski hâl: imzalı isteklerde HİÇ yeniden deneme yoktu.
        self.assertEqual({"ok": True}, result)
        self.assertEqual(3, attempts["n"])
        self.assertEqual(2, sleeper.call_count)

    def test_signed_request_does_not_retry_business_errors(self):
        btp = self.btp
        attempts = {"n": 0}

        def business_error(url, headers=None):
            attempts["n"] += 1
            return {"code": 2002, "msg": "Key iptal", "data": None}

        with mock.patch.object(btp, "_server_time_offset_ms", return_value=0.0), \
             mock.patch.object(btp, "_http_get_json", side_effect=business_error), \
             mock.patch.object(btp.time, "sleep") as sleeper:
            with self.assertRaises(RuntimeError):
                btp._signed_request("GET", "/open/v1/account/spot", None, "k", "s")
        self.assertEqual(1, attempts["n"])
        self.assertFalse(sleeper.called)

    def test_fmt_quantity_rounds_down_to_the_lot_step(self):
        btp = self.btp
        self.assertEqual("0.1234", btp._fmt_quantity(0.123456789, 0.0001))
        self.assertEqual("1", btp._fmt_quantity(1.9, 1.0))
        # Adım verilmezse eski davranış korunur.
        self.assertEqual("0.1", btp._fmt_quantity(0.10000000))
        self.assertEqual("0.12345678", btp._fmt_quantity(0.12345678))

    def test_place_market_sell_applies_the_cached_lot_step(self):
        btp = self.btp
        btp._symbols_cache["filters"] = {"BTC_USDT": {"step_size": 0.001}}
        with mock.patch.object(btp, "_signed_request", return_value={"orderId": "9"}) as sr:
            result = btp.place_market_sell("k", "s", "BTC_USDT", 0.1234)
        self.assertEqual("0.123", sr.call_args[0][2]["quantity"])
        self.assertEqual("0.123", result["quantity"])

    def test_place_market_sell_honours_an_explicit_step(self):
        btp = self.btp
        with mock.patch.object(btp, "_signed_request", return_value={"orderId": "9"}) as sr:
            btp.place_market_sell("k", "s", "BTC_USDT", 0.1234, step_size=0.01)
        self.assertEqual("0.12", sr.call_args[0][2]["quantity"])

    def test_symbol_list_loading_is_single_flight(self):
        btp = self.btp
        calls = {"n": 0}

        def slow_http(url, headers=None):
            calls["n"] += 1
            time.sleep(0.15)
            return {"code": 0, "data": {"list": [{"symbol": "BTC_USDT"}]}}

        btp._symbols_cache.update({"symbols": [], "underscore_by_concat": {},
                                   "expires": 0.0, "filters": {}})
        with mock.patch.object(btp, "_http_get_json", side_effect=slow_http):
            threads = [threading.Thread(target=btp._load_symbol_list, args=("k", "s"))
                       for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        # Eski hâlde ağ çağrısı kilidin DIŞINDAYDI → 5 eşzamanlı istek.
        self.assertEqual(1, calls["n"])


# ---------------------------------------------------------------- B-20
class UniverseRegistryPointInTimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_picks_the_latest_eligible_entry_not_the_first_one(self):
        import app.database as database
        from app import universe_registry

        history = [
            {"ts": 200.0, "source": "top_gainers", "symbols": ["B"]},
            {"ts": 100.0, "source": "top_gainers", "symbols": ["A"]},
            {"ts": 300.0, "source": "top_gainers", "symbols": ["C"]},
        ]

        async def fake_get(key, default=None):
            return json.dumps(history)

        with mock.patch.object(database, "get_llm_setting", new=fake_get):
            result = await universe_registry.universe_at(250.0)
        # Eski hâl ilk `ts > hedef` kaydında `break` ediyordu → sırasız
        # geçmişte yanlış kaydı (ts=100) döndürüyordu.
        self.assertEqual(["B"], result["symbols"])
        self.assertEqual(3, result["entries"])

    async def test_empty_history_returns_no_symbols(self):
        import app.database as database
        from app import universe_registry

        async def fake_get(key, default=None):
            return default

        with mock.patch.object(database, "get_llm_setting", new=fake_get):
            result = await universe_registry.universe_at(time.time())
        self.assertEqual([], result["symbols"])
        self.assertIsNone(result["as_of"])

    def test_research_endpoint_is_registered(self):
        from app.routers import reports
        paths = {getattr(route, "path", None) for route in reports.router.routes}
        self.assertIn("/api/research/universe-at", paths)

    async def test_research_endpoint_is_read_only(self):
        import app.database as database
        from app.routers import reports

        written = []

        async def fake_get(key, default=None):
            return json.dumps([{"ts": 50.0, "source": "top_gainers",
                                "symbols": ["BTCTRY", "ETHTRY"]}])

        async def fake_set(key, value):
            written.append(key)

        with mock.patch.object(database, "get_llm_setting", new=fake_get), \
             mock.patch.object(database, "set_llm_setting", new=fake_set):
            out = await reports.research_universe_at(ts=100.0)
        self.assertEqual(["BTCTRY", "ETHTRY"], out["symbols"])
        self.assertEqual([], written, "okuma ucu hiçbir şey yazmamalı")
        self.assertTrue(out["paper_only"])


if __name__ == "__main__":
    unittest.main()
