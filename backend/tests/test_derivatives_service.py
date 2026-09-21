import asyncio
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import derivatives_service


class DerivativesServiceTests(unittest.TestCase):
    def setUp(self):
        derivatives_service._DERIVATIVES_CACHE.clear()

    def test_symbol_to_futures(self):
        self.assertEqual(derivatives_service.symbol_to_futures("BTCTRY"), "BTCUSDT")
        self.assertEqual(derivatives_service.symbol_to_futures("SOLTRY"), "SOLUSDT")
        self.assertEqual(derivatives_service.symbol_to_futures("ETHUSDT"), "ETHUSDT")
        self.assertEqual(derivatives_service.symbol_to_futures("RENDERTRY"), "RENDERUSDT")

    @patch("app.derivatives_service._fetch_fapi_json")
    def test_get_derivatives_intel_healthy(self, mock_fapi):
        # mock premiumIndex and openInterest responses
        mock_fapi.side_effect = [
            {"lastFundingRate": "0.00010000", "markPrice": "65000.0"},
            {"openInterest": "15000.0"},
        ]

        res = asyncio.run(derivatives_service.get_derivatives_intel("BTCTRY"))
        self.assertTrue(res["futures_available"])
        self.assertEqual(res["futures_symbol"], "BTCUSDT")
        self.assertEqual(res["funding_rate"], 0.0001)
        self.assertEqual(res["funding_state"], "HEALTHY")
        self.assertEqual(res["surge_score_bonus"], 5)
        self.assertFalse(res["crowded_long_danger"])

    @patch("app.derivatives_service._fetch_fapi_json")
    def test_get_derivatives_intel_extreme_long(self, mock_fapi):
        mock_fapi.side_effect = [
            {"lastFundingRate": "0.00095000", "markPrice": "65000.0"},
            {"openInterest": "20000.0"},
        ]

        res = asyncio.run(derivatives_service.get_derivatives_intel("BTCTRY"))
        self.assertTrue(res["futures_available"])
        self.assertEqual(res["funding_state"], "EXTREME_LONG")
        self.assertTrue(res["crowded_long_danger"])
        self.assertEqual(res["surge_score_bonus"], -15)

    @patch("app.derivatives_service._fetch_fapi_json")
    def test_get_derivatives_intel_short_squeeze(self, mock_fapi):
        mock_fapi.side_effect = [
            {"lastFundingRate": "-0.00045000", "markPrice": "65000.0"},
            {"openInterest": "12000.0"},
        ]

        res = asyncio.run(derivatives_service.get_derivatives_intel("BTCTRY"))
        self.assertTrue(res["futures_available"])
        self.assertEqual(res["funding_state"], "CROWDED_SHORT")
        self.assertTrue(res["short_squeeze_potential"])
        self.assertEqual(res["surge_score_bonus"], 10)

    @patch("app.derivatives_service._fetch_fapi_json")
    def test_get_derivatives_intel_unavailable(self, mock_fapi):
        mock_fapi.side_effect = [None, None]

        res = asyncio.run(derivatives_service.get_derivatives_intel("UNKNOWNTRY"))
        self.assertFalse(res["futures_available"])
        self.assertEqual(res["funding_state"], "UNKNOWN")
        self.assertEqual(res["surge_score_bonus"], 0)

    def test_cached_derivatives_intel(self):
        derivatives_service._DERIVATIVES_CACHE["BTCUSDT"] = (
            derivatives_service.time.time(),
            {"futures_available": True, "funding_state": "HEALTHY", "surge_score_bonus": 5},
        )
        cached = derivatives_service.get_cached_derivatives_intel("BTCTRY")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["funding_state"], "HEALTHY")


if __name__ == "__main__":
    unittest.main()
