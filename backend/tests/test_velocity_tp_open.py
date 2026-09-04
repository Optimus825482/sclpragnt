"""Otonom hız avcısı açılışının TP'yi target_pct'ten kurduğunu doğrular."""
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import velocity  # noqa: E402
from app.config import config  # noqa: E402


def _candidate():
    return {"symbol": "TESTTRY", "velocity_score": 25.0, "mode": "trend_devam",
            "m5_pattern": ["g0_vol"], "m5_pattern_ok": True, "atr_pct": 1.2,
            "target_pct": 2.0, "horizon_minutes": 5, "passes": True, "price": 100.0}


class VelocityTPOpenTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_passes_take_profit_pct_from_target(self):
        opened = {"symbol": "TESTTRY", "action": "BUY_SIGNAL", "price": 100.0, "trade_id": "x"}
        captured = {}
        fake_analyzer = MagicMock()
        fake_analyzer.positions = {}

        async def fake_open(symbol, price, side, strat, order_value, **kw):
            captured.update(kw)
            return opened

        fake_analyzer.open_position = fake_open
        with patch.object(velocity, "analyzer", fake_analyzer), \
             patch.object(velocity, "database") as db, \
             patch.object(velocity, "microflow") as mf, \
             patch.object(velocity, "ws_manager") as ws, \
             patch.object(config, "VELOCITY_PATTERN_FILTER_ENABLED", True):
            db.get_llm_symbol_guard = AsyncMock(return_value=None)
            db.get_wallet_balance = AsyncMock(return_value=2000.0)
            db.get_chat_prediction_insights = AsyncMock(return_value=[])
            db.get_llm_forecast_lessons = AsyncMock(return_value=[])
            mf.get_snapshot = MagicMock(return_value={"data_ready": False})
            mf.start = AsyncMock(return_value=None)
            ws.broadcast = AsyncMock(return_value=None)
            with patch.object(velocity, "_velocity_rest_liquidity_ok", AsyncMock(return_value=(True, {}))), \
                 patch.object(velocity, "_hydrate_market_cache_for", AsyncMock(return_value=None)), \
                 patch.object(velocity, "_journal_touch_rates", AsyncMock(return_value={})), \
                 patch.object(velocity, "_fresh_public_price", AsyncMock(return_value=(100.0, {"symbol": "TESTTRY", "source": "test"}))):
                result = await velocity._open_velocity_position(_candidate())
        self.assertEqual(result["status"], "PAPER_OPENED")
        self.assertEqual(captured["take_profit_pct"], 0.02)  # target_pct 2.0 → 0.02
        self.assertEqual(result["take_profit_pct"], 2.0)
        ctx = captured["entry_context_extra"]
        self.assertEqual(ctx["target_pct"], 2.0)
        self.assertEqual(ctx["exit_model"], "plan_tp")
        self.assertEqual(ctx["no_initial_stop"], bool(config.VELOCITY_NO_INITIAL_STOP))


if __name__ == "__main__":
    unittest.main()
