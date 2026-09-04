import asyncio
import json
import pathlib
import sys
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class BinanceTrPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_orderbook_is_limited_to_five_levels_and_carries_symbol(self):
        from app import binance_tr_public

        rows = [[str(100 - index), str(index + 1)] for index in range(8)]
        payload = {"lastUpdateId": 7, "bids": rows, "asks": rows}
        with mock.patch.object(binance_tr_public, "_get_json", return_value=payload) as getter:
            result = await binance_tr_public.orderbook("btc_try", limit=50)

        self.assertEqual(result["symbol"], "BTCTRY")
        self.assertEqual(len(result["bids"]), 5)
        self.assertEqual(len(result["asks"]), 5)
        self.assertEqual(getter.call_args.args[1]["limit"], 5)

    def test_public_rest_retries_rate_limit_using_retry_after(self):
        from app import binance_tr_public
        from urllib.error import HTTPError

        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"data": [{"symbol": "BTCTRY"}]}).encode()
        rate_limit = HTTPError("https://example", 429, "slow down", {"Retry-After": "0"}, None)
        with mock.patch.object(binance_tr_public, "urlopen", side_effect=[rate_limit, response]) as opener:
            with mock.patch.object(binance_tr_public.time, "sleep"):
                result = binance_tr_public._get_json("/api/v3/ticker/24hr", {})

        self.assertEqual(result, [{"symbol": "BTCTRY"}])
        self.assertEqual(opener.call_count, 2)


class MarketDataCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_keeps_only_closed_candles_and_deduplicates_timestamps(self):
        from app.market_data import MarketData

        now_ms = int(time.time() * 1000)
        closed = [now_ms - 120_000, "1", "2", "0.5", "1.5", "10", now_ms - 60_001]
        duplicate = [closed[0], "1", "2", "0.5", "1.6", "11", closed[6]]
        open_bar = [now_ms - 30_000, "1", "2", "0.5", "1.8", "12", now_ms + 29_999]
        market = MarketData(["BTCTRY"])
        with mock.patch("app.market_data.fetch_klines", return_value=[closed, duplicate, open_bar]):
            with mock.patch.object(market, "refresh_24h_tickers", return_value=None):
                await market.fetch_historical_data(["1m"])

        history = market.get_ut_kline("BTCTRY", "1m")
        self.assertEqual(history["timestamps"], [closed[0]])
        self.assertEqual(history["closes"], [1.6])
        self.assertEqual(history["last_closed_at_ms"], closed[6])

    def test_closed_ws_candle_replaces_same_timestamp_instead_of_appending(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        history = market.klines["1m"]["BTCTRY"]
        history.update({
            "timestamps": [1000], "opens": [1.0], "highs": [2.0],
            "lows": [0.5], "closes": [1.5], "volumes": [10.0],
            "last_closed_at_ms": 1999, "updated_at": time.time(),
        })
        market._process_kline({
            "e": "kline", "E": 2000,
            "k": {"s": "BTCTRY", "i": "1m", "t": 1000, "T": 1999,
                  "o": "1", "h": "2", "l": "0.5", "c": "1.7", "v": "12", "x": True},
        })

        self.assertEqual(history["timestamps"], [1000])
        self.assertEqual(history["closes"], [1.7])
        self.assertEqual(history["volumes"], [12.0])

    def test_combined_depth_stream_uses_stream_name_as_symbol(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        market._process_ws_message({
            "stream": "btctry@depth5@100ms",
            "data": {"lastUpdateId": 1,
                     "bids": [["100", "2"], ["99", "3"]],
                     "asks": [["101", "4"], ["102", "5"]]},
        })
        flow = market.get_orderflow("BTCTRY")
        self.assertEqual(flow["bid_qty"], 5.0)
        self.assertEqual(flow["ask_qty"], 9.0)
        self.assertEqual(flow["source"], "binance_tr_public_ws")

    def test_liquidity_fails_closed_for_missing_or_stale_inputs(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        ok, details = market.liquidity_status("BTCTRY", 1000)
        self.assertFalse(ok)
        self.assertIn("ticker", details["missing_or_stale"])
        self.assertIn("orderbook", details["missing_or_stale"])

        now = time.time()
        market.tickers["BTCTRY"] = {"symbol": "BTCTRY", "last_price": 100.0, "timestamp": int(now * 1000)}
        market.ticker_24h["BTCTRY"] = 10_000_000.0
        market.rest_ticker_updated_at = now
        market.orderflow["BTCTRY"].update({
            "bid_qty": 100.0, "ask_qty": 100.0, "spread_pct": 0.1,
            "updated_at": now - market.ORDERBOOK_MAX_AGE_SEC - 1,
        })
        history = market.klines["5m"]["BTCTRY"]
        history.update({"timestamps": list(range(21)), "closes": [100.0] * 21,
                        "volumes": [10.0] * 21,
                        "last_closed_at_ms": int(now * 1000), "updated_at": now})
        ok, details = market.liquidity_status("BTCTRY", 1000)
        self.assertFalse(ok)
        self.assertEqual(details["missing_or_stale"], ["orderbook"])

    def test_liquidity_warmup_bypass_is_explicit_and_time_bounded(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        ok, details = market.liquidity_status("BTCTRY", 1000, allow_warmup=True)
        self.assertTrue(ok)
        self.assertTrue(details["warmup_bypass"])
        market.created_at -= market.WARMUP_BYPASS_SEC + 1
        ok, details = market.liquidity_status("BTCTRY", 1000, allow_warmup=True)
        self.assertFalse(ok)
        self.assertFalse(details["warmup_bypass"])

    def test_websocket_plan_is_rebuilt_from_current_symbols_each_generation(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        first = market._build_ws_groups(1)
        market.symbols = ["ethtry", "soltry"]
        market.reconnect_requested = True
        second = market._build_ws_groups(2)

        self.assertIn("btctry@kline_", first[0]["url"])
        self.assertNotIn("btctry@kline_", second[0]["url"])
        self.assertIn("ethtry@kline_", second[0]["url"])
        self.assertEqual(second[0]["generation"], 2)

    async def test_connect_cancels_old_generation_and_launches_current_symbols(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        launched = []

        async def fake_group(plan):
            launched.append(plan)
            await asyncio.Event().wait()

        async def fake_rest_refresh():
            await asyncio.Event().wait()

        with mock.patch.object(market, "_run_ws_group", side_effect=fake_group):
            with mock.patch.object(market, "_rest_refresh_loop", side_effect=fake_rest_refresh):
                owner = asyncio.create_task(market.connect(skip_history=True))
                for _ in range(50):
                    if launched:
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(launched)
                first_generation = launched[-1]["generation"]
                market.symbols = ["ETHTRY"]
                market.reconnect_requested = True
                for _ in range(50):
                    if len(launched) >= 2:
                        break
                    await asyncio.sleep(0.01)
                self.assertGreaterEqual(len(launched), 2)
                self.assertGreater(launched[-1]["generation"], first_generation)
                self.assertEqual(launched[-1]["symbols"], ("ethtry",))
                market.stop()
                await asyncio.gather(owner, return_exceptions=True)
                self.assertFalse(market._ws_tasks)

    def test_rest_and_ws_health_are_reported_separately(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        market.rest_last_error = "rest unavailable"
        market.ws_last_error = "ws unavailable"
        status = market.data_freshness("BTCTRY", "1m")
        self.assertEqual(status["rest"]["last_error"], "rest unavailable")
        self.assertEqual(status["ws"]["last_error"], "ws unavailable")

    def test_bookticker_scalar_payload_updates_orderflow(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        market._process_ws_message({
            "stream": "btctry@bookTicker",
            "data": {"u": 1, "s": "BTCTRY", "b": "100", "B": "2", "a": "101", "A": "3"},
        })
        flow = market.get_orderflow("BTCTRY")
        self.assertEqual(flow["bid_price"], 100.0)
        self.assertEqual(flow["ask_price"], 101.0)
        self.assertEqual(flow["bid_qty"], 2.0)
        self.assertEqual(flow["ask_qty"], 3.0)
        self.assertAlmostEqual(flow["spread_pct"], 1.0)

    def test_24hr_ticker_and_mini_ticker_update_price_cache(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        market._process_ws_message({
            "stream": "btctry@ticker",
            "data": {"e": "24hrTicker", "E": 1000, "s": "BTCTRY", "c": "102.5"},
        })
        self.assertEqual(market.get_ticker("BTCTRY")["last_price"], 102.5)
        self.assertEqual(market.get_ticker("BTCTRY")["source"], "binance_tr_public_ws:ticker")

        market._process_ws_message({
            "stream": "btctry@miniTicker",
            "data": {"e": "24hrMiniTicker", "E": 2000, "s": "BTCTRY", "c": "103.0"},
        })
        self.assertEqual(market.get_ticker("BTCTRY")["last_price"], 103.0)

    def test_server_shutdown_requests_reconnect(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        market.reconnect_requested = False
        market._process_ws_message({
            "stream": "!serverShutdown",
            "data": {"e": "serverShutdown", "E": 1},
        })
        self.assertTrue(market.reconnect_requested)

    def test_ws_groups_include_ticker_stream_and_rotate_host(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        plan = market._build_ws_groups(1)[0]
        self.assertIn("btctry@ticker", plan["url"])
        self.assertIn("btctry@kline_", plan["url"])
        first_base = plan["base"]
        market.ws_host_index = 1
        second = market._build_ws_groups(2)[0]
        self.assertNotEqual(second["base"], first_base)

    def test_ws_groups_keep_streams_below_binance_ws_limit(self):
        from app.market_data import MarketData

        symbols = [f"SYM{i}TRY" for i in range(40)]
        market = MarketData(symbols)
        plans = market._build_ws_groups(1)
        self.assertGreaterEqual(len(plans), 2)
        for plan in plans:
            # Tek bir WS bağlantısındaki stream sayısı Binance limitinin (1024)
            # çok altında kalmalı; 180 kendi_CONFIG değeri yalnız
            # streams_per_symbol*için kullanılır.
            stream_count = plan["url"].count("@")
            self.assertLessEqual(stream_count, 1024)
            self.assertTrue(plan["url"].startswith(plan["base"]))


class WebsocketRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_fans_out_concurrently_and_removes_failures(self):
        from app.ws_runtime import ConnectionManager

        entered = 0
        all_entered = asyncio.Event()

        class Socket:
            def __init__(self, fail=False):
                self.fail = fail
                self.sent = []

            async def send_json(self, message):
                nonlocal entered
                entered += 1
                if entered == 3:
                    all_entered.set()
                await asyncio.wait_for(all_entered.wait(), timeout=0.1)
                if self.fail:
                    raise RuntimeError("closed")
                self.sent.append(message)

        manager = ConnectionManager()
        healthy_a, healthy_b, failed = Socket(), Socket(), Socket(fail=True)
        manager.active_connections[:] = [healthy_a, healthy_b, failed]
        await manager.broadcast({"ok": True})

        self.assertEqual(entered, 3)
        self.assertEqual(healthy_a.sent, [{"ok": True}])
        self.assertEqual(healthy_b.sent, [{"ok": True}])
        self.assertNotIn(failed, manager.active_connections)


if __name__ == "__main__":
    unittest.main()
