import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from app.routers import maintenance
from app import database

class RadarOutcomesBackfillTests(unittest.TestCase):
    def setUp(self):
        maintenance._radar_outcomes_backfill.clear()
        maintenance._radar_outcomes_backfill.update({
            "running": False, "status": "idle", "phase": "idle",
            "progress": 0, "total": 0, "completed": 0, "updated": 0,
            "skipped": 0, "current_symbol": "", "message": "",
            "started_at": None, "finished_at": None, "error": None,
            "result": None,
        })

    def test_status_endpoint(self):
        res = asyncio.run(maintenance.radar_outcomes_backfill_status())
        self.assertFalse(res["running"])
        self.assertEqual(res["status"], "idle")

    def test_backfill_calculation_and_upsert(self):
        sample_notif = {
            "id": 101,
            "symbol": "BTCUSDT",
            "detected_at": 1700000000.0,
            "target_pct": 2.0,
            "price": 50000.0,
            "horizon_minutes": 5,
            "candidate_id": None,
            "candidate_status": None,
            "mfe_pct": None,
        }
        # Binance kline format: [open_time, open, high, low, close, volume, close_time, ...]
        klines = [
            [1700000000000, "50000", "50500", "49900", "50200", "100", 1700000059999],
            [1700000060000, "50200", "51500", "50100", "51200", "120", 1700000119999],
            [1700000120000, "51200", "51300", "50800", "51000", "90", 1700000179999],
            [1700000180000, "51000", "51100", "50700", "50900", "80", 1700000239999],
            [1700000240000, "50900", "51000", "50800", "50950", "70", 1700000299999],
        ]

        with patch.object(database, "get_monitoring_velocity_matches", AsyncMock(return_value=[sample_notif])), \
             patch.object(maintenance, "fetch_klines", AsyncMock(return_value=klines)), \
             patch.object(database, "upsert_evaluated_velocity_candidate", AsyncMock(return_value=True)) as mock_upsert:

            asyncio.run(maintenance._run_radar_outcomes_backfill({"day": "2026-09-19"}))

            status = maintenance._radar_outcomes_backfill
            self.assertEqual(status["status"], "complete")
            self.assertEqual(status["total"], 1)
            self.assertEqual(status["completed"], 1)
            self.assertEqual(status["updated"], 1)
            self.assertEqual(status["skipped"], 0)

            self.assertTrue(mock_upsert.called)
            call_kwargs = mock_upsert.call_args[1]
            self.assertEqual(call_kwargs["notification_id"], 101)
            self.assertEqual(call_kwargs["symbol"], "BTCUSDT")
            self.assertTrue(call_kwargs["touched_target"])
            self.assertAlmostEqual(call_kwargs["mfe_pct"], 3.0, places=2)
