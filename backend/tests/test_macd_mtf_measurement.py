"""MACD MTF konfluans ölçüm kablosu: bildirim snapshot'ı + sonuç kalıcılığı + rapor agregasyonu."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.routers import monitoring
from app.routers import reports as reports_router
from app import database


class BuildNotificationSnapshotTests(unittest.TestCase):
    def test_build_notification_carries_mtf_snapshot(self):
        from app.state import market

        class FakeMarket:
            def get_ticker(self, sym):
                return {"last_price": "12.5"}

            def ticker_freshness(self, sym, max_age_sec=None):
                return {"fresh": True, "age_sec": 0.0, "max_age_sec": max_age_sec}

        mtf = {"verdict": "GÜÇLÜ", "confluence": 85.0}
        with patch.object(market, "get_ticker", FakeMarket().get_ticker), \
             patch.object(market, "ticker_freshness", FakeMarket().ticker_freshness), \
             patch.object(monitoring.macd_mtf, "cached_compact", return_value=mtf):
            n = monitoring._build_notification(
                "XYZTRY", {"velocity_score": 3.1, "target_pct": 4.0, "price": 12.0,
                           "horizon_minutes": 5},
                {"min_score": 1.0, "min_target_pct": 2.0},
            )
        self.assertEqual(n["macd_mtf_verdict"], "GÜÇLÜ")
        self.assertEqual(n["macd_mtf_confluence"], 85.0)

    def test_build_notification_without_mtf_cache_is_none(self):
        from app.state import market

        class FakeMarket:
            def get_ticker(self, sym):
                return {"last_price": "12.5"}

            def ticker_freshness(self, sym, max_age_sec=None):
                return {"fresh": True, "age_sec": 0.0, "max_age_sec": max_age_sec}

        with patch.object(market, "get_ticker", FakeMarket().get_ticker), \
             patch.object(market, "ticker_freshness", FakeMarket().ticker_freshness), \
             patch.object(monitoring.macd_mtf, "cached_compact", return_value=None):
            n = monitoring._build_notification(
                "XYZTRY", {"velocity_score": 3.1, "target_pct": 4.0, "price": 12.0,
                           "horizon_minutes": 5},
                {"min_score": 1.0, "min_target_pct": 2.0},
            )
        self.assertIsNone(n["macd_mtf_verdict"])
        self.assertIsNone(n["macd_mtf_confluence"])

    def test_build_rising_notification_carries_mtf_snapshot(self):
        mtf = {"verdict": "ZAYIF", "confluence": 30.0}
        with patch.object(monitoring.macd_mtf, "cached_compact", return_value=mtf):
            n = monitoring._build_rising_notification(
                {"symbol": "ABCTRY", "kind": "erken", "score": 61.0, "target_pct": 2.0,
                 "signals": {}}, 1.0)
        self.assertEqual(n["macd_mtf_verdict"], "ZAYIF")
        self.assertEqual(n["macd_mtf_confluence"], 30.0)


class PendingOutcomeTests(unittest.TestCase):
    def setUp(self):
        monitoring._monitoring_state["pending_targets"] = {}

    def tearDown(self):
        monitoring._monitoring_state["pending_targets"] = {}

    def _pending(self, **over):
        base = {
            "expected": 103.0, "entry_price": 100.0, "sl_pct": 1.5,
            "horizon_minutes": 5, "set_at": time.time(),
            "max_price": 104.0, "min_price": 99.5, "notification_id": 42,
        }
        base.update(over)
        return base

    def test_hit_persists_outcome_with_mfe_mae(self):
        monitoring._monitoring_state["pending_targets"]["XYZTRY"] = self._pending()
        record = AsyncMock()
        outcome = AsyncMock()
        with patch.object(monitoring, "_ticker_price", return_value=105.0), \
             patch.object(database, "record_symbol_target_outcome", record), \
             patch.object(database, "update_monitoring_notification_outcome", outcome):
            asyncio.run(monitoring._check_pending_targets())
        # MFE: max(104, 105) → +5.0% ; MAE: min(99.5, 105) → -0.5%
        outcome.assert_awaited_once()
        args = outcome.await_args.args
        self.assertEqual(args[0], 42)
        self.assertEqual(args[1], "HEDEFE_ULTI")
        self.assertAlmostEqual(args[2], 5.0, places=6)
        self.assertAlmostEqual(args[3], -0.5, places=6)
        record.assert_awaited_once_with("XYZTRY", success=True)
        self.assertNotIn("XYZTRY", monitoring._monitoring_state["pending_targets"])

    def test_stop_persists_negative_mae(self):
        monitoring._monitoring_state["pending_targets"]["XYZTRY"] = self._pending()
        outcome = AsyncMock()
        with patch.object(monitoring, "_ticker_price", return_value=98.0), \
             patch.object(database, "record_symbol_target_outcome", AsyncMock()), \
             patch.object(database, "update_monitoring_notification_outcome", outcome):
            asyncio.run(monitoring._check_pending_targets())
        args = outcome.await_args.args
        self.assertEqual(args[1], "STOP")
        # MFE: max(104, 98) → +4.0% ; MAE: min(99.5, 98) → -2.0%
        self.assertAlmostEqual(args[2], 4.0, places=6)
        self.assertAlmostEqual(args[3], -2.0, places=6)

    def test_expired_without_ticker_uses_tracked_extremes(self):
        monitoring._monitoring_state["pending_targets"]["XYZTRY"] = self._pending(
            set_at=time.time() - 10_000)
        outcome = AsyncMock()
        with patch.object(monitoring, "_ticker_price", return_value=None), \
             patch.object(database, "record_symbol_target_outcome", AsyncMock()), \
             patch.object(database, "update_monitoring_notification_outcome", outcome):
            asyncio.run(monitoring._check_pending_targets())
        args = outcome.await_args.args
        self.assertEqual(args[1], "SURE_DOLDU")
        self.assertAlmostEqual(args[2], 4.0, places=6)     # max_price 104
        self.assertAlmostEqual(args[3], -0.5, places=6)    # min_price 99.5

    def test_missing_notification_id_skips_outcome_write(self):
        monitoring._monitoring_state["pending_targets"]["XYZTRY"] = self._pending(
            notification_id=None)
        outcome = AsyncMock()
        with patch.object(monitoring, "_ticker_price", return_value=105.0), \
             patch.object(database, "record_symbol_target_outcome", AsyncMock()), \
             patch.object(database, "update_monitoring_notification_outcome", outcome):
            asyncio.run(monitoring._check_pending_targets())
        outcome.assert_not_awaited()


class ReportAggregationTests(unittest.TestCase):
    def test_macd_mtf_report_groups(self):
        rows = [
            {"id": 1, "symbol": "A", "macd_mtf_verdict": "GÜÇLÜ", "macd_mtf_confluence": 90.0,
             "outcome_status": "HEDEFE_ULTI", "mfe_pct": 4.0, "mae_pct": -0.5,
             "score": 80.0, "target_pct": 2.0, "detected_at": time.time(), "mode": "x"},
            {"id": 2, "symbol": "B", "macd_mtf_verdict": "GÜÇLÜ", "macd_mtf_confluence": 80.0,
             "outcome_status": "HEDEFE_ULTI", "mfe_pct": 6.0, "mae_pct": -0.2,
             "score": 75.0, "target_pct": 2.0, "detected_at": time.time(), "mode": "x"},
            {"id": 3, "symbol": "C", "macd_mtf_verdict": "GÜÇLÜ", "macd_mtf_confluence": 76.0,
             "outcome_status": None, "mfe_pct": None, "mae_pct": None,
             "score": 70.0, "target_pct": 2.0, "detected_at": time.time(), "mode": "x"},
            {"id": 4, "symbol": "D", "macd_mtf_verdict": "ZAYIF", "macd_mtf_confluence": 20.0,
             "outcome_status": "SURE_DOLDU", "mfe_pct": 0.3, "mae_pct": -2.0,
             "score": 60.0, "target_pct": 2.0, "detected_at": time.time(), "mode": "x"},
            {"id": 5, "symbol": "E", "macd_mtf_verdict": "ZAYIF", "macd_mtf_confluence": 10.0,
             "outcome_status": "STOP", "mfe_pct": 0.1, "mae_pct": -3.0,
             "score": 55.0, "target_pct": 2.0, "detected_at": time.time(), "mode": "x"},
            {"id": 6, "symbol": "F", "macd_mtf_verdict": "ORTA", "macd_mtf_confluence": 50.0,
             "outcome_status": None, "mfe_pct": None, "mae_pct": None,
             "score": 65.0, "target_pct": 2.0, "detected_at": time.time(), "mode": "x"},
            {"id": 7, "symbol": "G", "macd_mtf_verdict": None, "macd_mtf_confluence": None,
             "outcome_status": "HEDEFE_ULTI", "mfe_pct": 2.0, "mae_pct": -0.1,
             "score": 90.0, "target_pct": 2.0, "detected_at": time.time(), "mode": "x"},
        ]
        with patch.object(database, "list_macd_mtf_report", AsyncMock(return_value=rows)):
            result = asyncio.run(reports_router.get_macd_mtf_report(days=14))
        groups = {g["verdict"]: g for g in result["groups"]}
        self.assertEqual([g["verdict"] for g in result["groups"]], ["GÜÇLÜ", "ORTA", "ZAYIF", "YOK"])
        guclu = groups["GÜÇLÜ"]
        self.assertEqual(guclu["count"], 3)
        self.assertEqual(guclu["measured"], 2)
        self.assertEqual(guclu["touched"], 2)
        self.assertAlmostEqual(guclu["touch_rate_pct"], 100.0)
        self.assertAlmostEqual(guclu["avg_mfe_pct"], 5.0)   # (4 + 6) / 2
        zayif = groups["ZAYIF"]
        self.assertEqual(zayif["measured"], 2)
        self.assertAlmostEqual(zayif["touch_rate_pct"], 0.0)
        self.assertAlmostEqual(zayif["fake_rate_pct"], 100.0)  # iki MAE de ≤ -1.5
        yok = groups["YOK"]
        self.assertEqual(yok["count"], 1)
        self.assertAlmostEqual(yok["touch_rate_pct"], 100.0)
        self.assertEqual(len(result["recent"]), 7)


if __name__ == "__main__":
    unittest.main()
