"""2026-10-17 (basit arayuz): /api/binance/positions yanit cache'i ve FIFO maliyet cache'i.

Borsa cagrilari mock'lanir; ikinci cagrinin TTL icinde sifir trades (N+1) ve sifir
bakiye cagrisi yaptigi kanitlanir.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app import main


def _trades(symbol: str):
    return [{"id": 1, "time": 1000, "isBuyer": True, "qty": "10", "price": "100", "symbol": symbol}]


class PositionsCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._positions_cache.clear()
        main._binance_cost_cache.clear()
        self.balance_calls = 0
        self.trade_calls = 0
        self.trades_empty = False

        def balance(*_a, **_k):
            self.balance_calls += 1
            return [
                {"asset": "TRY", "free": "500", "locked": "0"},
                {"asset": "SOL", "free": "10", "locked": "0"},
                {"asset": "DOGE", "free": "100", "locked": "0"},
            ]

        def trades(_k, _s, symbol, *_a, **_kw):
            self.trade_calls += 1
            return [] if self.trades_empty else _trades(symbol)

        async def ticker(symbols):
            return [{"symbol": s, "price": "120"} for s in symbols if s.endswith("TRY")]

        self.patches = [
            patch("app.main._require_user", return_value={"username": "u1"}),
            patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 7, "username": "u1"})),
            patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("key-1234567890abcdef", "sec"))),
            patch("app.main._ensure_binance_user_stream", new=AsyncMock(return_value={"state": "ok"})),
            patch("app.main.get_account_balance", side_effect=balance),
            patch("app.main._load_seen_binance_assets", new=AsyncMock(return_value={"SOL", "DOGE", "TRY"})),
            patch("app.main._save_seen_binance_assets", new=AsyncMock()),
            patch("app.main.binance_tr_public.ticker_price", new=AsyncMock(side_effect=ticker)),
            patch("app.main.get_trade_history", side_effect=trades),
            patch("app.main.get_open_orders", return_value=[]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main._positions_cache.clear()
        main._binance_cost_cache.clear()

    async def test_second_call_within_ttl_makes_zero_exchange_calls(self):
        req = MagicMock()
        first = await main.binance_positions(req)
        self.assertEqual(self.balance_calls, 1)
        self.assertEqual(self.trade_calls, 2)  # SOL + DOGE, TRY atlanir
        sol = next(h for h in first["holdings"] if h["asset"] == "SOL")
        self.assertAlmostEqual(sol["avg_cost_try"], 100.0)
        before = (self.balance_calls, self.trade_calls)
        second = await main.binance_positions(req)
        self.assertEqual((self.balance_calls, self.trade_calls), before)
        self.assertEqual(first, second)
        # Cache'ten donen kopya degistirilirse sonraki cagriyi bozmamali
        second["holdings"].clear()
        third = await main.binance_positions(req)
        self.assertTrue(third["holdings"])

    async def test_after_response_ttl_cost_cache_avoids_trades_calls(self):
        req = MagicMock()
        await main.binance_positions(req)
        main._positions_cache.clear()  # 3 sn doldu gibi
        trades_before = self.trade_calls
        await main.binance_positions(req)
        self.assertEqual(self.trade_calls, trades_before)  # N+1 yok (300 sn maliyet cache'i)
        self.assertEqual(self.balance_calls, 2)

    async def test_invalidate_drops_both_caches(self):
        req = MagicMock()
        await main.binance_positions(req)
        main._invalidate_positions_cache(7)
        await main.binance_positions(req)
        self.assertEqual(self.balance_calls, 2)
        self.assertEqual(self.trade_calls, 4)

    async def test_invalidation_is_per_user(self):
        req = MagicMock()
        await main.binance_positions(req)
        main._invalidate_positions_cache(999)
        await main.binance_positions(req)
        self.assertEqual(self.balance_calls, 1)

    async def test_concurrent_calls_share_one_computation(self):
        req = MagicMock()
        results = await asyncio.gather(*[main.binance_positions(req) for _ in range(5)])
        self.assertEqual(self.balance_calls, 1)
        self.assertEqual(self.trade_calls, 2)
        self.assertTrue(all(r == results[0] for r in results))

    async def test_missing_cost_is_cached_only_briefly(self):
        self.trades_empty = True
        req = MagicMock()
        res = await main.binance_positions(req)
        sol = next(h for h in res["holdings"] if h["asset"] == "SOL")
        self.assertIsNone(sol["avg_cost_try"])
        exp, _info = main._binance_cost_cache[(7, "SOL")]
        import time
        self.assertLessEqual(exp - time.time(), main._COST_NEGATIVE_TTL_SEC + 1)
        self.assertLess(main._COST_NEGATIVE_TTL_SEC, 300)


if __name__ == "__main__":
    unittest.main()
