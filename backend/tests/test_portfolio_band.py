import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.routers import portfolio_band as pb


def _positions_payload():
    return {
        "holdings": [
            {"asset": "TRY", "total": 1500.0, "value_try": 1500.0, "pnl_try": None, "avg_cost_try": None},
            {"asset": "SAGA", "total": 10.0, "value_try": 600.0, "pnl_try": 100.0, "avg_cost_try": 50.0},
            {"asset": "ABC", "total": 5.0, "value_try": 400.0, "pnl_try": -20.0, "avg_cost_try": 84.0},
            {"asset": "DUST", "total": 1.0, "value_try": 2.0, "pnl_try": 0.5, "avg_cost_try": 1.5},
            {"asset": "NOCOST", "total": 2.0, "value_try": 50.0, "pnl_try": None, "avg_cost_try": None},
        ],
        "balances": [{"asset": "TRY", "free": "1200.5", "locked": "299.5"}],
        "total_value_try": 2552.0,
    }


class BuildBinanceBandTests(unittest.TestCase):
    def test_aggregates_real_values(self):
        out = pb.build_binance_band(_positions_payload(), {"daily": {"realized_pnl_try": 35.256}}, now=1.0)
        self.assertEqual(out["source"], "binance")
        self.assertEqual(out["total_try"], 2552.0)
        self.assertEqual(out["free_try"], 1200.5)
        # TRY ve toz hariç: SAGA, ABC, NOCOST
        self.assertEqual(out["open_count"], 3)
        # maliyeti bilinenler: +100 -20 = 80; maliyet tabanı 10*50 + 5*84 = 920
        self.assertEqual(out["unrealized_try"], 80.0)
        self.assertAlmostEqual(out["unrealized_pct"], 80 / 920 * 100, places=3)
        self.assertEqual(out["daily_pnl_try"], 35.26)
        self.assertEqual(out["updated_at"], 1.0)

    def test_holdings_for_live_ticks(self):
        # 2026-10-17: istemci WS fiyat tikleriyle canlı yeniden hesap yapsın diye taban değerler.
        p = _positions_payload()
        for h in p["holdings"]:
            if h["asset"] != "TRY":
                h["price_try"] = h["value_try"] / h["total"]
        out = pb.build_binance_band(p, None, now=1.0)
        by = {h["asset"]: h for h in out["holdings"]}
        self.assertNotIn("TRY", by)
        self.assertEqual(by["SAGA"]["qty"], 10.0)
        self.assertEqual(by["SAGA"]["price_try"], 60.0)
        self.assertEqual(by["SAGA"]["avg_cost_try"], 50.0)
        self.assertTrue(by["SAGA"]["counted"])
        self.assertEqual(by["SAGA"]["symbol"], "SAGATRY")
        self.assertFalse(by["DUST"]["counted"])  # toz: toplam değere girer, açık işlem sayılmaz
        self.assertIsNone(by["NOCOST"]["avg_cost_try"])

    def test_holdings_skip_rows_without_price(self):
        out = pb.build_binance_band(_positions_payload(), None, now=1.0)
        self.assertEqual(out["holdings"], [])

    def test_no_positions_is_zero_pnl_not_none(self):
        out = pb.build_binance_band({"holdings": [{"asset": "TRY", "total": 5, "value_try": 5}],
                                     "balances": [], "total_value_try": 5.0}, None)
        self.assertEqual(out["open_count"], 0)
        self.assertEqual(out["unrealized_try"], 0.0)
        self.assertEqual(out["free_try"], 0.0)
        self.assertIsNone(out["daily_pnl_try"])

    def test_positions_without_cost_basis_give_none(self):
        out = pb.build_binance_band({"holdings": [
            {"asset": "XYZ", "total": 2, "value_try": 100.0, "pnl_try": None, "avg_cost_try": None}],
            "balances": [], "total_value_try": 100.0}, {"daily": {}})
        self.assertEqual(out["open_count"], 1)
        self.assertIsNone(out["unrealized_try"])
        self.assertIsNone(out["unrealized_pct"])
        self.assertIsNone(out["daily_pnl_try"])


class BuildPaperBandTests(unittest.TestCase):
    def test_net_round_trip_unrealized_over_main_and_auto_positions(self):
        snap = {
            "try": 4000.0, "total_value": 5100.0, "commission_pct": 0.001,
            "positions": [{"symbol": "AAATRY", "entry": 100.0, "current": 110.0, "quantity": 5.0, "side": "LONG"}],
            "auto_paper_positions": [{"symbol": "BBBTRY", "entry": 10.0, "current": 9.0, "quantity": 10.0}],
        }
        out = pb.build_paper_band(snap, -12.345, now=2.0)
        self.assertEqual(out["source"], "paper")
        self.assertEqual(out["open_count"], 2)
        a = (110 - 100) * 5 - 0.001 * 5 * 210
        b = (9 - 10) * 10 - 0.001 * 10 * 19
        self.assertAlmostEqual(out["unrealized_try"], round(a + b, 2), places=2)
        self.assertAlmostEqual(out["unrealized_pct"], (a + b) / (500 + 100) * 100, places=3)
        self.assertEqual(out["total_try"], 5100.0)
        self.assertEqual(out["free_try"], 4000.0)
        self.assertEqual(out["daily_pnl_try"], -12.35)
        self.assertEqual(len(out["positions"]), 2)

    def test_empty_snapshot_is_none_values_but_zero_unrealized(self):
        out = pb.build_paper_band(None, None)
        self.assertIsNone(out["total_try"])
        self.assertIsNone(out["free_try"])
        self.assertEqual(out["open_count"], 0)
        self.assertEqual(out["unrealized_try"], 0.0)
        self.assertIsNone(out["daily_pnl_try"])

    def test_short_side_and_missing_price(self):
        snap = {"commission_pct": 0.001, "positions": [
            {"entry": 100.0, "current": 90.0, "quantity": 1.0, "side": "SHORT"},
            {"entry": 100.0, "current": None, "quantity": 1.0}]}
        out = pb.build_paper_band(snap, 0.0)
        self.assertEqual(out["open_count"], 2)
        self.assertAlmostEqual(out["unrealized_try"], 10.0 - 0.001 * 190, places=2)


class BandEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pb._binance_cache.clear()

    async def test_binance_when_keys_configured_and_cached(self):
        req = MagicMock()
        positions = AsyncMock(return_value=_positions_payload())
        day = AsyncMock(return_value={"daily": {"realized_pnl_try": 10}})
        with patch("app.main._require_user", return_value={"username": "Erkan"}), \
             patch("app.main.get_binance_settings", new=AsyncMock(return_value={"configured": True})), \
             patch("app.main.binance_positions", new=positions), \
             patch("app.main.binance_trades_day", new=day):
            first = await pb.portfolio_band(req)
            second = await pb.portfolio_band(req)
        self.assertEqual(first["source"], "binance")
        self.assertEqual(first["daily_pnl_try"], 10.0)
        self.assertIs(first, second)
        positions.assert_awaited_once()
        day.assert_awaited_once()

    async def test_binance_failure_does_not_fall_back_to_paper(self):
        req = MagicMock()
        with patch("app.main._require_user", return_value={"username": "u2"}), \
             patch("app.main.get_binance_settings", new=AsyncMock(return_value={"configured": True})), \
             patch("app.main.binance_positions", new=AsyncMock(side_effect=HTTPException(status_code=502, detail="x"))), \
             patch("app.main.binance_trades_day", new=AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                await pb.portfolio_band(req)
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_daily_failure_keeps_binance_values(self):
        req = MagicMock()
        with patch("app.main._require_user", return_value={"username": "u3"}), \
             patch("app.main.get_binance_settings", new=AsyncMock(return_value={"configured": True})), \
             patch("app.main.binance_positions", new=AsyncMock(return_value=_positions_payload())), \
             patch("app.main.binance_trades_day", new=AsyncMock(side_effect=RuntimeError("boom"))):
            out = await pb.portfolio_band(req)
        self.assertEqual(out["source"], "binance")
        self.assertIsNone(out["daily_pnl_try"])

    async def test_paper_when_no_keys(self):
        req = MagicMock()
        snap = {"try": 100.0, "total_value": 100.0, "positions": [], "auto_paper_positions": []}
        with patch("app.main._require_user", return_value={"username": "u4"}), \
             patch("app.main.get_binance_settings", new=AsyncMock(return_value={"configured": False})), \
             patch.dict("app.routers.runtime._ws_snapshot_cache", {"portfolio": snap}), \
             patch("app.routers.portfolio_band.database.get_trades", new=AsyncMock(return_value=[])), \
             patch("app.routers.portfolio_band.database.get_auto_paper_stats",
                   new=AsyncMock(return_value={"total_pnl_try": 7.5})):
            out = await pb.portfolio_band(req)
        self.assertEqual(out["source"], "paper")
        self.assertEqual(out["total_try"], 100.0)
        self.assertEqual(out["daily_pnl_try"], 7.5)


if __name__ == "__main__":
    unittest.main()
