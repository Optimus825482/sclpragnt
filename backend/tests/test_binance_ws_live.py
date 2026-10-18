"""2026-10-18 (Binance TR canlı akış): WS abonelik anlık görüntüsü, hedefli cache
geçersiz kılma ve bellek fiyat tazeliği."""
import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app import main


class UserEventInvalidationTests(unittest.TestCase):
    def setUp(self):
        main._binance_cost_cache.clear()
        main._positions_cache.clear()
        main._binance_cost_cache[(7, "BTC")] = (time.time() + 300, {"avg_price": 1.0})
        main._binance_cost_cache[(7, "ETH")] = (time.time() + 300, {"avg_price": 2.0})
        main._positions_cache[(7, "k")] = (time.monotonic() + 3, {}, None)

    def tearDown(self):
        main._binance_cost_cache.clear()
        main._positions_cache.clear()

    def test_account_position_event_keeps_cost_cache(self):
        main._invalidate_after_user_event(7, {"event_type": "outboundAccountPosition", "fields": {}})
        self.assertEqual(set(main._binance_cost_cache), {(7, "BTC"), (7, "ETH")})
        self.assertFalse(main._positions_cache)

    def test_new_order_event_keeps_cost_cache(self):
        main._invalidate_after_user_event(7, {"event_type": "executionReport",
                                              "fields": {"symbol": "BTC_TRY", "status": "NEW"}})
        self.assertIn((7, "BTC"), main._binance_cost_cache)

    def test_fill_drops_only_base_asset_cost(self):
        main._invalidate_after_user_event(7, {"event_type": "executionReport",
                                              "fields": {"symbol": "BTCTRY", "status": "FILLED"}})
        self.assertNotIn((7, "BTC"), main._binance_cost_cache)
        self.assertIn((7, "ETH"), main._binance_cost_cache)

    def test_partial_fill_from_raw_x_field(self):
        main._invalidate_after_user_event(7, {"event_type": "executionReport", "fields": {},
                                              "raw": {"s": "ETH_USDT", "X": "PARTIALLY_FILLED"}})
        self.assertNotIn((7, "ETH"), main._binance_cost_cache)
        self.assertIn((7, "BTC"), main._binance_cost_cache)


class WsSubscribeSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        main._account_snapshot.clear()

    async def test_subscribe_sends_cached_snapshot_to_that_socket(self):
        snap = {"type": "binance_account_update", "data": {"user_id": 7, "time": time.time(), "holdings": []}}
        main._account_snapshot[7] = snap
        ws = MagicMock()
        with patch.object(main.ws_manager, "send_to", new=AsyncMock()) as send_to, \
                patch("app.main._schedule_account_push") as sched:
            await main._handle_ws_client_frame(ws, 7, {"id": 7},
                                               json.dumps({"type": "subscribe", "topic": "binance_account"}))
        send_to.assert_awaited_once_with(ws, snap)
        sched.assert_not_called()

    async def test_subscribe_without_snapshot_schedules_one_off_push(self):
        with patch.object(main.ws_manager, "send_to", new=AsyncMock()) as send_to, \
                patch("app.main._schedule_account_push") as sched:
            await main._handle_ws_client_frame(MagicMock(), 7, {"id": 7},
                                               json.dumps({"type": "subscribe", "topic": "binance_account"}))
        send_to.assert_not_awaited()
        sched.assert_called_once()
        self.assertEqual(sched.call_args.args[0], 7)

    async def test_anonymous_or_garbage_frames_ignored(self):
        with patch("app.main._schedule_account_push") as sched:
            await main._handle_ws_client_frame(MagicMock(), None, None,
                                               json.dumps({"type": "subscribe", "topic": "binance_account"}))
            await main._handle_ws_client_frame(MagicMock(), 7, {"id": 7}, "not json")
            await main._handle_ws_client_frame(MagicMock(), 7, {"id": 7}, json.dumps({"type": "subscribe", "topic": "x"}))
        sched.assert_not_called()


class MemoryPriceTests(unittest.TestCase):
    def test_fresh_and_stale_memory_prices(self):
        now_ms = time.time() * 1000
        fake = MagicMock()
        fake.mini_tickers = {"BTCTRY": {"last_price": 100.0, "quote_volume": 5.0, "timestamp": now_ms}}
        fake.tickers = {"ETHTRY": {"symbol": "ETHTRY", "last_price": 50.0, "timestamp": now_ms - 60_000}}
        fake.ticker_24h = {}
        with patch("app.main.market", fake):
            fresh = main._fresh_memory_prices(["BTCTRY", "ETHTRY", "XTRY"])
        self.assertEqual(fresh, {"BTCTRY": 100.0})


if __name__ == "__main__":
    unittest.main()
