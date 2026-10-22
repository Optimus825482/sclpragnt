import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from app import main


def _day_bounds(day: str) -> tuple[int, int]:
    from datetime import datetime, timezone, timedelta
    day_start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=3)))
    start_ms = int(day_start.timestamp() * 1000)
    return start_ms, start_ms + 86400 * 1000


def _patch_env(asset: str):
    """Ortak yamalar: kimlik, bakiye, varlık havuzu, sembol filtresi ve kur."""
    from contextlib import ExitStack
    stack = ExitStack()
    for p in (
        patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))),
        patch("app.main._require_user", return_value={"username": "testuser"}),
        patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 1, "username": "testuser"})),
        patch("app.main.get_account_balance", return_value=[{"asset": asset, "free": "10", "locked": "0"}]),
        patch("app.main._load_seen_binance_assets", new=AsyncMock(return_value={asset})),
        patch("app.main._save_seen_binance_assets", new=AsyncMock()),
        patch("app.main.get_symbol_filters", return_value={"filterType": "PRICE_FILTER"}),
        patch("app.main.binance_tr_public.ticker_price", new=AsyncMock(return_value=[{"symbol": "USDTTRY", "price": "35.0"}])),
    ):
        stack.enter_context(p)
    return stack


def _history_mock(symbol_prefix: str, fills: list[dict]):
    """Gün sorgusu (start verilir) aralıktaki fill'leri, geçmiş sorgusu (start None) hepsini döner."""
    def mock_get_trade_history(api_key, api_secret, sym, start, end, limit, offset):
        if not (sym.startswith(symbol_prefix) or sym.replace("_", "") == symbol_prefix.replace("_", "")):
            return []
        if start is not None:
            return [dict(f) for f in fills if start <= f["time"] < end]
        return [dict(f) for f in fills]
    return mock_get_trade_history


class BinanceTradesDayTests(unittest.IsolatedAsyncioTestCase):
    async def test_sell_listed_on_day_of_last_buy_not_sale_day(self):
        """Erkan kararı (2026-10-22): dün alınıp bugün satılan coin, satış günü değil ALIM günü
        görünümünde listelenir; K/Z de o güne yazılır. Satış günü görünümü boş kalır."""
        buy_day, sell_day = "2026-09-20", "2026-09-21"
        buy_start, _ = _day_bounds(buy_day)
        sell_start, _ = _day_bounds(sell_day)
        fills = [
            {"id": 101, "symbol": "SAGATRY", "price": "40.0", "qty": "10.0", "commission": "0.4",
             "commissionAsset": "TRY", "isBuyer": True, "time": buy_start + 3600_000},
            {"id": 201, "symbol": "SAGATRY", "price": "50.0", "qty": "10.0", "commission": "0.5",
             "commissionAsset": "TRY", "isBuyer": False, "time": sell_start + 1000},
        ]
        req = MagicMock()
        with _patch_env("SAGA"), patch("app.main.get_trade_history", side_effect=_history_mock("SAGA_TRY", fills)):
            main._binance_day_trades_cache.clear()
            sold = await main.binance_trades_day(req, date=sell_day)
            bought = await main.binance_trades_day(req, date=buy_day)

        # Satış günü: satış buraya ait değil → hiç satır yok, K/Z 0.
        self.assertEqual(sold["count"], 0)
        self.assertEqual(sold["symbol_summary"], [])
        self.assertEqual(sold["daily"]["realized_pnl_try"], 0)
        self.assertEqual(sold["daily"]["wins"], 0)

        # Alım günü: alım + ertesi günkü satış birlikte; net = (50-40)*10 - 0.5 - 0.4 = 99.1
        self.assertEqual(bought["count"], 2)
        self.assertAlmostEqual(bought["daily"]["realized_pnl_try"], 99.1, places=2)
        self.assertEqual(bought["daily"]["wins"], 1)
        saga = bought["symbol_summary"][0]
        self.assertEqual(saga["fills"], 2)
        self.assertAlmostEqual(saga["buy_qty"], 10.0)
        self.assertAlmostEqual(saga["sell_qty"], 10.0)
        self.assertAlmostEqual(saga["sell_revenue_try"], 500.0)
        self.assertAlmostEqual(saga["realized_pnl_try"], 99.1, places=2)
        self.assertAlmostEqual(saga["realized_pnl_pct"], 99.1 / 400.4 * 100, places=3)
        sell_row = [t for t in bought["trades"] if not t["isBuyer"]][0]
        self.assertAlmostEqual(sell_row["realized_pnl_try"], 99.1, places=2)

    async def test_sell_follows_latest_buy_when_bought_on_several_days(self):
        """Son alım hangi günse satış oraya gider: 20'sinde ve 21'inde alım, 22'sinde satış → 21'e."""
        d20, d21, d22 = "2026-09-20", "2026-09-21", "2026-09-22"
        s20, _ = _day_bounds(d20)
        s21, _ = _day_bounds(d21)
        s22, _ = _day_bounds(d22)
        fills = [
            {"id": 1, "symbol": "SAGATRY", "price": "40.0", "qty": "5.0", "commission": "0",
             "commissionAsset": "TRY", "isBuyer": True, "time": s20 + 1000},
            {"id": 2, "symbol": "SAGATRY", "price": "44.0", "qty": "5.0", "commission": "0",
             "commissionAsset": "TRY", "isBuyer": True, "time": s21 + 1000},
            {"id": 3, "symbol": "SAGATRY", "price": "50.0", "qty": "10.0", "commission": "0",
             "commissionAsset": "TRY", "isBuyer": False, "time": s22 + 1000},
        ]
        req = MagicMock()
        with _patch_env("SAGA"), patch("app.main.get_trade_history", side_effect=_history_mock("SAGA_TRY", fills)):
            main._binance_day_trades_cache.clear()
            r20 = await main.binance_trades_day(req, date=d20)
            r21 = await main.binance_trades_day(req, date=d21)
            r22 = await main.binance_trades_day(req, date=d22)

        self.assertEqual([t["id"] for t in r20["trades"]], [1])
        self.assertEqual(r20["daily"]["realized_pnl_try"], 0)
        self.assertEqual(sorted(t["id"] for t in r21["trades"]), [2, 3])
        # FIFO taban: 5×40 + 5×44 = 420 → (500 - 420) = 80 TRY, 21'ine yazılır.
        self.assertAlmostEqual(r21["daily"]["realized_pnl_try"], 80.0, places=2)
        self.assertEqual(r22["count"], 0)

    async def test_sell_without_any_buy_stays_on_sale_day(self):
        """Geçmişte alımı bulunmayan (eşleşmeyen) satış kendi gününde kalır."""
        day = "2026-09-21"
        start_ms, _ = _day_bounds(day)
        fills = [{"id": 9, "symbol": "SAGATRY", "price": "50.0", "qty": "1.0", "commission": "0",
                  "commissionAsset": "TRY", "isBuyer": False, "time": start_ms + 1000}]
        req = MagicMock()
        with _patch_env("SAGA"), patch("app.main.get_trade_history", side_effect=_history_mock("SAGA_TRY", fills)):
            main._binance_day_trades_cache.clear()
            r = await main.binance_trades_day(req, date=day)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["daily"]["unmatched"], 1)
        self.assertEqual(r["symbol_summary"][0]["fills"], 1)

    async def test_fill_event_invalidates_every_cached_day_of_user(self):
        """Bugünkü satış dünkü alımın gününü değiştirir → fill olayı kullanıcının tüm gün cache'lerini düşürür."""
        main._binance_day_trades_cache.clear()
        main._binance_day_trades_cache[(1, "2026-09-20")] = (9e12, {})
        main._binance_day_trades_cache[(1, "2026-09-21")] = (9e12, {})
        main._binance_day_trades_cache[(2, "2026-09-20")] = (9e12, {})
        event = {"event_type": "executionReport", "fields": {"status": "FILLED", "symbol": "SAGA_TRY"}}
        with patch("app.main._invalidate_positions_cache"), patch("app.main._invalidate_binance_cost_cache"):
            main._invalidate_after_user_event(1, event, "")
        self.assertEqual(set(main._binance_day_trades_cache), {(2, "2026-09-20")})

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
                # USDT çifti: taban 100 USDT × 2 × 35 = 7000 TRY (quoteQty değil) → 680 / 7000
                self.assertAlmostEqual(sol_summary["realized_pnl_pct"], 680.0 / 7000.0 * 100, places=2)

