import asyncio
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import monitoring
from app import unified_signals


def _run(coro):
    return asyncio.run(coro)


class MonitoringScoreThresholdEnforcementTests(unittest.TestCase):
    def setUp(self):
        unified_signals.reset_state_for_tests()
        monitoring._monitoring_state["candidate_streak"].clear()
        monitoring._monitoring_state["notified_symbols"].clear()
        monitoring._monitoring_state["pending_targets"].clear()
        monitoring._monitoring_state["notified_prices"].clear()

    def test_notify_drops_unified_candidate_below_threshold(self):
        """min_score=90 iken unified_pass=True olsa bile score=74.4 olan aday bildirilmez."""
        settings = {
            "enabled": True,
            "min_score": 90.0,
            "min_score_explicit": True,
            "min_target_pct": 1.5,
        }
        cand_low = {
            "symbol": "SUITRY",
            "unified_pass": True,
            "unified_score": 74.4,
            "velocity_score": 0.0,
            "target_pct": 4.0,
            "price": 10.0,
            "horizon_minutes": 5,
        }
        cand_high = {
            "symbol": "MUBARAKTRY",
            "unified_pass": True,
            "unified_score": 97.0,
            "velocity_score": 0.0,
            "target_pct": 4.0,
            "price": 10.0,
            "horizon_minutes": 5,
        }
        with patch.object(monitoring.database, "get_pending_monitoring_notifications", new=AsyncMock(return_value={})), \
             patch.object(monitoring, "_record_history", new=AsyncMock(return_value=None)):
            notifs = _run(monitoring._notify([cand_low, cand_high], settings))

        symbols = [n["symbol"] for n in notifs]
        self.assertNotIn("SUITRY", symbols, "74.4 puanlı SUITRY 90 eşiğinde bildirilmemeli")
        self.assertIn("MUBARAKTRY", symbols, "97.0 puanlı MUBARAKTRY 90 eşiğinde bildirilmeli")

    def test_notify_drops_radar_candidate_below_threshold(self):
        """min_score=90 iken normal velocity adayı da 90 altındaysa bildirilmez."""
        settings = {
            "enabled": True,
            "min_score": 90.0,
            "min_score_explicit": True,
            "min_target_pct": 1.5,
        }
        # velocity_score 1200 -> normalize_score ~70 (90 eşiğinin altında)
        cand_low = {
            "symbol": "EDENTRY",
            "velocity_score": 1200.0,
            "target_pct": 3.0,
            "price": 5.0,
            "horizon_minutes": 5,
        }
        with patch.object(monitoring.database, "get_pending_monitoring_notifications", new=AsyncMock(return_value={})), \
             patch.object(monitoring, "_record_history", new=AsyncMock(return_value=None)):
            notifs = _run(monitoring._notify([cand_low], settings))

        symbols = [n["symbol"] for n in notifs]
        self.assertNotIn("EDENTRY", symbols)

    def test_unified_fast_notify_respects_threshold(self):
        """unified_fast_notify eşik 90 iken 70 puanlık sinyali göndermez, 95 puanlığı gönderir."""
        settings = {
            "enabled": True,
            "min_score": 90.0,
            "min_score_explicit": True,
            "min_target_pct": 1.5,
            "radar_unified_notify": True,
        }
        with patch.object(monitoring, "get_user_notification_settings", new=AsyncMock(return_value=settings)), \
             patch.object(monitoring, "_radar_unified_enabled", new=AsyncMock(return_value=True)), \
             patch.object(monitoring.unified_signals, "enabled", return_value=True), \
             patch.object(monitoring, "_ticker_price", return_value=10.0), \
             patch.object(monitoring, "_send_push", new=AsyncMock(return_value=True)), \
             patch.object(monitoring, "_record_history", new=AsyncMock(return_value=None)):

            # Düşük skorlu aday: 75.0
            with patch.object(monitoring.unified_signals, "build_fusion_candidate",
                              return_value={"symbol": "ARKMTRY", "unified_score": 75.0, "target_pct": 3.0, "price": 10.0}):
                res_low = _run(monitoring._unified_fast_notify_impl("ARKMTRY", "jump", 75.0))
                self.assertIsNone(res_low, "75.0 skorlu aday 90 eşiğinde push atamaz")

            # Yüksek skorlu aday: 92.0
            with patch.object(monitoring.unified_signals, "build_fusion_candidate",
                              return_value={"symbol": "ARKMTRY", "unified_score": 92.0, "target_pct": 3.0, "price": 10.0}):
                res_high = _run(monitoring._unified_fast_notify_impl("ARKMTRY", "jump", 92.0))
                self.assertIsNotNone(res_high, "92.0 skorlu aday 90 eşiğinde push gönderebilmeli")
                self.assertEqual(res_high["symbol"], "ARKMTRY")
