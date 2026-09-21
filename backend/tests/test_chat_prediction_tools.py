import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from app.routers.llm_chat import _get_master_surge_tool, _get_ml_forecast_tool, _get_surge_bias_tool

class TestChatPredictionTools(unittest.IsolatedAsyncioTestCase):
    async def test_get_master_surge_tool_empty_symbol(self):
        res = await _get_master_surge_tool({})
        self.assertFalse(res.get("ok"))
        self.assertIn("symbol parametresi gerekli", res.get("error", ""))

    async def test_get_ml_forecast_tool_empty_symbol(self):
        res = await _get_ml_forecast_tool({})
        self.assertFalse(res.get("ok"))

    async def test_get_surge_bias_tool_empty_symbol(self):
        res = await _get_surge_bias_tool({})
        self.assertFalse(res.get("ok"))

    @patch("app.master_surge.evaluate_master_surge")
    @patch("app.surge_learning.get_cached_surge_biases")
    async def test_get_master_surge_tool_success(self, mock_get_bias, mock_eval):
        mock_get_bias.return_value = {"BTCTRY": {"bias_pct": 5.0}}
        mock_eval.return_value = {
            "symbol": "BTCTRY",
            "passed": True,
            "composite_index": 82.5,
            "confluence_4way": True,
        }
        res = await _get_master_surge_tool({"symbol": "BTCTRY"})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("symbol"), "BTCTRY")
        self.assertEqual(res.get("surge", {}).get("composite_index"), 82.5)

    @patch("app.routers.chart_forecast.collect_forecast_features")
    @patch("app.ml_forecast.predict_target")
    async def test_get_ml_forecast_tool_success(self, mock_pred, mock_feat):
        mock_feat.return_value = {"close_price": 100.0}
        mock_pred.return_value = {
            "target_pct": 2.5,
            "target_price": 102.5,
            "hit_probability": 0.75,
        }
        res = await _get_ml_forecast_tool({"symbol": "BTCTRY"})
        self.assertTrue(res.get("ok"))
        self.assertIn("5m", res.get("forecasts", {}))
        self.assertEqual(res.get("forecasts", {})["5m"]["target_pct"], 2.5)
