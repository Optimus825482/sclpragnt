"""Binance TR doküman denetimi (apidocs 2026-08-28) — piyasa verisi hizalaması.

Kilitlenen davranışlar
----------------------
1. `!miniTicker@arr` satırları `market.mini_tickers` önbelleğine yazılır;
   izlenen sembollerin `tickers` fiyatı yalnız satır daha YENİYSE tazelenir.
2. WS stream listesi dokümanda olmayan `@ticker`/`@bookTicker` içermez.
3. REST yedeği yalnız WS tazeliği bayat sembolleri tazeler.
4. `depth` limiti doküman kümesine [5,10,20,50,100,500] yuvarlanır.
5. `_get_json` host'u yalnız bağlantı/5xx hatasında döndürür; 429/4xx aynı host.
6. `ticker_24h` alt küme çağrısı tam tablodan süzülür; tam tablo hatasında
   alt küme isteğine düşer.
7. `price_service` taze (<5 sn) `mini_tickers` satırını REST'ten önce kullanır.
"""
import asyncio
import time
import unittest
from unittest import mock

from app import binance_tr_public as pub
from app import early_discovery as ed
from app import price_service
from app.market_data import MarketData


def _row(symbol, price, q, event_ms):
    return {"e": "24hrMiniTicker", "E": event_ms, "s": symbol, "c": str(price), "q": str(q)}


class MiniTickerCacheTests(unittest.TestCase):
    def setUp(self):
        ed.reset()
        self.addCleanup(ed.reset)

    def test_arr_rows_fill_mini_tickers_for_all_symbols(self):
        market = MarketData(["BTCTRY"])
        market._process_ws_message({
            "stream": "!miniTicker@arr",
            "data": [_row("BTCTRY", 100.0, 1000.0, 5_000),
                     _row("ETH_TRY", 50.5, 20.0, 5_001),
                     {"s": "BADTRY", "c": "x"},          # bozuk satır atlanır
                     "dict-değil"],
        })
        self.assertEqual(market.mini_tickers["BTCTRY"], {
            "last_price": 100.0, "quote_volume": 1000.0, "timestamp": 5_000,
            "source": "ws:miniTicker@arr"})
        self.assertEqual(market.mini_tickers["ETHTRY"]["last_price"], 50.5)
        self.assertNotIn("BADTRY", market.mini_tickers)
        # izlenmeyen sembol `tickers`a yazılmaz
        self.assertIsNone(market.get_ticker("ETHTRY"))

    def test_tracked_ticker_refreshed_only_when_newer_and_fields_kept(self):
        market = MarketData(["BTCTRY"])
        market.tickers["BTCTRY"] = {"symbol": "BTCTRY", "last_price": 99.0,
                                    "timestamp": 10_000, "source": "x", "extra": 1}
        market._process_ws_message({"stream": "!miniTicker@arr",
                                    "data": [_row("BTCTRY", 98.0, 1.0, 9_000)]})
        self.assertEqual(market.get_ticker("BTCTRY")["last_price"], 99.0, "eski satır ezmemeli")
        market._process_ws_message({"stream": "!miniTicker@arr",
                                    "data": [_row("BTCTRY", 101.0, 1.0, 11_000)]})
        ticker = market.get_ticker("BTCTRY")
        self.assertEqual(ticker["last_price"], 101.0)
        self.assertEqual(ticker["timestamp"], 11_000)
        self.assertEqual(ticker["extra"], 1, "zengin alanlar korunmalı")
        self.assertEqual(ticker["source"], "binance_tr_public_ws:miniTicker@arr")


class StreamListTests(unittest.TestCase):
    def test_undocumented_streams_replaced(self):
        streams = MarketData._ws_stream_list(("btctry",), ("1m",)).split("/")
        self.assertIn("btctry@miniTicker", streams)
        self.assertIn("btctry@depth5@100ms", streams)
        self.assertNotIn("btctry@ticker", streams)
        self.assertNotIn("btctry@bookTicker", streams)

    def test_mini_ticker_stream_still_updates_price(self):
        market = MarketData(["BTCTRY"])
        market._process_ws_message({
            "stream": "btctry@miniTicker",
            "data": {"e": "24hrMiniTicker", "E": 2000, "s": "BTCTRY", "c": "103.0"},
        })
        self.assertEqual(market.get_ticker("BTCTRY")["last_price"], 103.0)

    def test_depth5_frame_without_symbol_feeds_orderbook(self):
        market = MarketData(["BTCTRY"])
        market._process_ws_message({
            "stream": "btctry@depth5@100ms",
            "data": {"lastUpdateId": 1, "bids": [["100", "2"]], "asks": [["101", "3"]]},
        })
        flow = market.get_orderflow("BTCTRY")
        self.assertEqual((flow["bid_price"], flow["ask_price"]), (100.0, 101.0))


class StaleOnlyRestRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_only_touches_stale_symbols(self):
        market = MarketData(["BTCTRY", "ETHTRY"])
        now = time.time()
        market.tickers["BTCTRY"] = {"symbol": "BTCTRY", "last_price": 10.0,
                                    "timestamp": int(now * 1000), "source": "ws"}
        market.orderflow["BTCTRY"].update({"bid_price": 9.9, "ask_price": 10.1, "bid_qty": 1.0,
                                           "ask_qty": 1.0, "spread_pct": 0.2, "updated_at": now})
        price_stale, book_stale = market._rest_stale_symbols()
        self.assertEqual(price_stale, ["ETHTRY"])
        self.assertEqual(book_stale, ["ETHTRY"])

        book_requests = []

        async def fake_ticker(_symbols):
            return [{"symbol": "BTCTRY", "quoteVolume": "5", "lastPrice": "9"},
                    {"symbol": "ETHTRY", "quoteVolume": "7", "lastPrice": "3"}]

        async def fake_book(symbols):
            book_requests.append(list(symbols))
            return []

        with mock.patch.object(pub, "ticker_24h", fake_ticker), \
                mock.patch.object(pub, "book_tickers", fake_book):
            await market.refresh_24h_tickers(price_symbols=price_stale, book_symbols=book_stale)
            await market.refresh_24h_tickers(price_symbols=[], book_symbols=[])
        self.assertEqual(market.get_ticker("BTCTRY")["last_price"], 10.0, "taze WS fiyatı ezilmemeli")
        self.assertEqual(market.get_ticker("ETHTRY")["last_price"], 3.0)
        self.assertEqual(market.ticker_24h["BTCTRY"], 5.0, "hacim tüm semboller için güncellenir")
        self.assertEqual(book_requests, [["ETHTRY"]], "boş bayat küme → bookTicker isteği yok")


class DepthLimitTests(unittest.IsolatedAsyncioTestCase):
    def test_clamp_rounds_up_to_documented_set(self):
        cases = {1: 5, 5: 5, 6: 10, 15: 20, 20: 20, 21: 50, 99: 100, 101: 500, 1000: 500, "x": 5}
        for given, expected in cases.items():
            self.assertEqual(pub._depth_limit(given), expected, given)

    async def test_depth_and_orderbook_send_clamped_limit(self):
        sent = []

        def fake(path, params):
            sent.append(params["limit"])
            return {"bids": [], "asks": []}

        with mock.patch.object(pub, "_get_json", side_effect=fake):
            await pub.depth("BTC_TRY", 30)
            await pub.depth("BTCTRY", 1000)
            await pub.orderbook("BTCTRY", 2)
        self.assertEqual(sent, [50, 500, 5])


class _Resp:
    def __init__(self, status, headers=None, data=b"[]"):
        self.status = status
        self.headers = headers or {}
        self.data = data


class HostRotationTests(unittest.TestCase):
    def setUp(self):
        self._saved = pub._cooldown_until
        pub._cooldown_until = 0.0
        self.addCleanup(self._restore)

    def _restore(self):
        pub._cooldown_until = self._saved

    def _run(self, responses):
        urls = []
        seq = iter(responses)

        class Pool:
            def request(self, method, url, retries=False):
                urls.append(url)
                item = next(seq)
                if isinstance(item, Exception):
                    raise item
                return item

        with mock.patch.object(pub, "_HTTP_POOL", Pool()), \
                mock.patch.object(pub.time, "sleep", lambda _s: None), \
                mock.patch.object(pub, "_wait_global_cooldown", lambda: None):
            try:
                result = pub._get_json("/api/v3/ping", {})
            except Exception as exc:  # noqa: BLE001
                result = exc
        hosts = [url.split("/api/")[0] for url in urls]
        return hosts, result

    def test_429_keeps_host_and_honors_retry_after(self):
        delays = []
        with mock.patch.object(pub, "_note_global_cooldown", lambda d: delays.append(d)):
            hosts, result = self._run([_Resp(429, {"Retry-After": "7"}), _Resp(200)])
        self.assertEqual(hosts, [pub.REST_BASES[0]] * 2)
        self.assertEqual(result, [])
        self.assertEqual(delays, [7.0])

    def test_4xx_does_not_rotate(self):
        hosts, _ = self._run([_Resp(400, data=b'{"code":-1121,"msg":"Invalid symbol."}')] * 4)
        self.assertEqual(set(hosts), {pub.REST_BASES[0]})

    def test_connection_error_and_5xx_rotate(self):
        hosts, result = self._run([OSError("dns"), _Resp(503), _Resp(200)])
        self.assertEqual(hosts, list(pub.REST_BASES[:3]))
        self.assertEqual(result, [])


class Ticker24hSubsetTests(unittest.TestCase):
    def setUp(self):
        pub._ticker_24h_cache.update({"key": None, "rows": None, "expires": 0.0})
        self.addCleanup(pub._ticker_24h_cache.update, {"key": None, "rows": None, "expires": 0.0})

    def test_subset_falls_back_when_full_table_fails(self):
        calls = []

        async def fake_paged(path, symbols):
            calls.append(symbols)
            if symbols is None:
                raise RuntimeError("tam tablo yok")
            return [{"symbol": s} for s in symbols]

        with mock.patch.object(pub, "_ticker_paged", fake_paged):
            rows = asyncio.run(pub.ticker_24h(["BTCTRY"]))
            with self.assertRaises(RuntimeError):
                asyncio.run(pub.ticker_24h())
        self.assertEqual(rows, [{"symbol": "BTCTRY"}])
        self.assertEqual(calls, [None, ["BTCTRY"], None])

    def test_returned_list_is_a_copy(self):
        async def fake_paged(path, symbols):
            return [{"symbol": "BTCTRY"}]

        with mock.patch.object(pub, "_ticker_paged", fake_paged):
            first = asyncio.run(pub.ticker_24h())
            first.clear()
            second = asyncio.run(pub.ticker_24h())
        self.assertEqual(second, [{"symbol": "BTCTRY"}])


class PriceServiceMiniTickerTests(unittest.TestCase):
    def _market(self, mini_age_sec):
        market = MarketData(["BTCTRY"])
        market.mini_tickers["BTCTRY"] = {
            "last_price": 42.0, "quote_volume": 1.0,
            "timestamp": int((time.time() - mini_age_sec) * 1000), "source": "ws:miniTicker@arr"}
        return market

    def test_fresh_mini_ticker_used_before_rest(self):
        market = self._market(1.0)

        async def boom(_symbol):
            raise AssertionError("REST'e gidilmemeli")

        with mock.patch.object(price_service, "rest_quote", boom):
            price, age, source = asyncio.run(price_service.get_price("BTC_TRY", market_obj=market))
        self.assertEqual(price, 42.0)
        self.assertLess(age, 5.0)
        self.assertEqual(source, price_service.SOURCE_WS_MINI_ARR)

    def test_stale_mini_ticker_falls_through_to_rest(self):
        market = self._market(30.0)

        async def fake_rest(_symbol):
            return 41.0, 0.0, "rest"

        with mock.patch.object(price_service, "rest_quote", fake_rest):
            self.assertEqual(asyncio.run(price_service.get_price("BTCTRY", market_obj=market)),
                             (41.0, 0.0, "rest"))


if __name__ == "__main__":
    unittest.main()
