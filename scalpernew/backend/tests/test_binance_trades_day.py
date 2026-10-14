import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from app import main


class BinanceTradesDayTests(unittest.IsolatedAsyncioTestCase):
    async def test_trades_day_fifo_matches_historical_buys(self):
        # Setup: Buy yesterday, Sell today
        day = "2026-09-21"
        from datetime import datetime, timezone, timedelta
        day_start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=3)))
        start_ms = int(day_start.timestamp() * 1000)
        end_ms = start_ms + 86400 * 1000

        # Fill today: SELL 10 SAGA at 50 TRY, time = start_ms + 1000
        today_fill = {
            "id": 201,
            "symbol": "SAGATRY",
            "price": "50.0",
            "qty": "10.0",
            "commission": "0.5",
            "commissionAsset": "TRY",
            "isBuyer": False,
            "time": start_ms + 1000,
        }

        # Historical buy yesterday: BUY 10 SAGA at 40 TRY, time = start_ms - 10000
        hist_buy = {
            "id": 101,
            "symbol": "SAGATRY",
            "price": "40.0",
            "qty": "10.0",
            "commission": "0.4",
            "commissionAsset": "TRY",
            "isBuyer": True,
            "time": start_ms - 10000,
        }

        req = MagicMock()
        with patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))), \
             patch("app.main._require_user", return_value={"username": "testuser"}), \
             patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 1, "username": "testuser"})), \
             patch("app.main.get_account_balance", return_value=[{"asset": "SAGA", "free": "10", "locked": "0"}]), \
             patch("app.main._load_seen_binance_assets", new=AsyncMock(return_value={"SAGA"})), \
             patch("app.main._save_seen_binance_assets", new=AsyncMock()), \
             patch("app.main.get_symbol_filters", return_value={"filterType": "PRICE_FILTER"}), \
             patch("app.main.binance_tr_public.ticker_price", new=AsyncMock(return_value=[{"symbol": "USDTTRY", "price": "35.0"}])):

            def mock_get_trade_history(api_key, api_secret, sym, start, end, limit, offset):
                if not (sym.startswith("SAGA_TRY") or sym == "SAGATRY"):
                    return []
                if start is not None:
                    # Daily fetch
                    return [dict(today_fill)]
                else:
                    # Historical fetch (start is None)
                    return [dict(hist_buy), dict(today_fill)]

            with patch("app.main.get_trade_history", side_effect=mock_get_trade_history):
                # Clear cache
                main._binance_day_trades_cache.clear()
                result = await main.binance_trades_day(req, date=day)

                # Net profit should be: (50 - 40) * 10 - 0.5 (sell comm) - 0.4 (buy comm) = 99.1 TRY
                self.assertEqual(result["count"], 1)
                daily = result["daily"]
                self.assertAlmostEqual(daily["realized_pnl_try"], 99.1, places=2)
                self.assertEqual(daily["wins"], 1)
                self.assertEqual(daily["losses"], 0)
                self.assertEqual(daily["unmatched"], 0)

                saga_summary = [s for s in result["symbol_summary"] if "SAGA" in s["symbol"]][0]
                self.assertAlmostEqual(saga_summary["realized_pnl_try"], 99.1, places=2)
                self.assertAlmostEqual(saga_summary["sell_qty"], 10.0)
                self.assertAlmostEqual(saga_summary["sell_revenue_try"], 500.0)

    async def test_trades_day_usdt_pair_and_bnb_fee(self):
        day = "2026-09-21"
        from datetime import datetime, timezone, timedelta
        day_start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=3)))
        start_ms = int(day_start.timestamp() * 1000)

        # USDT pair: Buy at 100 USDT, Sell at 110 USDT, qty = 2.
        # Commission in BNB: 0.01 BNB.
        # USDTTRY = 35.0, BNBTRY = 2000.0
        # Gross profit in USDT = (110 - 100) * 2 = 20 USDT -> 700 TRY.
        # Commission in BNB: 0.01 * 2000 = 20 TRY.
        # Net TRY = 700 - 20 = 680 TRY.
        today_buy = {
            "id": 301,
            "symbol": "SOLUSDT",
            "price": "100.0",
            "qty": "2.0",
            "commission": "0.0",
            "commissionAsset": "TRY",
            "isBuyer": True,
            "time": start_ms + 1000,
        }
        today_sell = {
            "id": 302,
            "symbol": "SOLUSDT",
            "price": "110.0",
            "qty": "2.0",
            "commission": "0.01",
            "commissionAsset": "BNB",
            "isBuyer": False,
            "time": start_ms + 5000,
        }

        req = MagicMock()
        with patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))), \
             patch("app.main._require_user", return_value={"username": "testuser"}), \
             patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 1, "username": "testuser"})), \
             patch("app.main.get_account_balance", return_value=[{"asset": "SOL", "free": "2", "locked": "0"}]), \
             patch("app.main._load_seen_binance_assets", new=AsyncMock(return_value={"SOL"})), \
             patch("app.main._save_seen_binance_assets", new=AsyncMock()), \
             patch("app.main.get_symbol_filters", return_value={"filterType": "PRICE_FILTER"}), \
             patch("app.main.binance_tr_public.ticker_price", new=AsyncMock(return_value=[
                 {"symbol": "USDTTRY", "price": "35.0"},
                 {"symbol": "BNBTRY", "price": "2000.0"},
             ])):

            def mock_get_trade_history(api_key, api_secret, sym, start, end, limit, offset):
                if not (sym.startswith("SOL_USDT") or sym == "SOLUSDT"):
                    return []
                return [dict(today_buy), dict(today_sell)]

            with patch("app.main.get_trade_history", side_effect=mock_get_trade_history):
                main._binance_day_trades_cache.clear()
                result = await main.binance_trades_day(req, date=day)

                daily = result["daily"]
                self.assertAlmostEqual(daily["realized_pnl_try"], 680.0, places=1)
                sol_summary = [s for s in result["symbol_summary"] if "SOL" in s["symbol"]][0]
                self.assertAlmostEqual(sol_summary["realized_pnl_try"], 680.0, places=1)
                self.assertAlmostEqual(sol_summary["commission_try"], 20.0, places=1)

