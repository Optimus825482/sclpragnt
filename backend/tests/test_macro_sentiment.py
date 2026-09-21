import asyncio
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import macro_sentiment_service


class MacroSentimentServiceTests(unittest.TestCase):
    def setUp(self):
        macro_sentiment_service._FNG_CACHE = None
        macro_sentiment_service._BTC_COMPASS_CACHE = None

    @patch("app.macro_sentiment_service._fetch_fng_sync")
    def test_get_fear_and_greed(self, mock_fng_sync):
        mock_fng_sync.return_value = {
            "score": 72,
            "classification": "Greed",
            "updated_at": macro_sentiment_service.time.time(),
        }

        res = asyncio.run(macro_sentiment_service.get_fear_and_greed())
        self.assertEqual(res["score"], 72)
        self.assertEqual(res["classification"], "Greed")

    @patch("app.binance_tr_public.klines", new_callable=AsyncMock)
    def test_get_btc_compass_bullish(self, mock_klines):
        # 5m klines returning rising closes
        mock_klines.return_value = [
            [0, 100, 105, 99, 100, 10],
            [0, 100, 106, 99, 101, 10],
            [0, 101, 107, 100, 102, 10],
            [0, 102, 108, 101, 103, 10],
        ]

        res = asyncio.run(macro_sentiment_service.get_btc_compass())
        self.assertEqual(res["btc_symbol"], "BTCTRY")
        self.assertFalse(res["is_panic_dump"])
        self.assertGreater(res["btc_15m_change_pct"], 0.0)

    @patch("app.binance_tr_public.klines", new_callable=AsyncMock)
    def test_get_btc_compass_panic_dump(self, mock_klines):
        # 5m klines returning sharp drop > 1%
        mock_klines.return_value = [
            [0, 100, 101, 99, 100, 10],
            [0, 100, 101, 98, 99.5, 10],
            [0, 99.5, 100, 97, 98.0, 10],
            [0, 98.0, 98.5, 96, 96.5, 50],  # from 100 to 96.5 (-3.5%)
        ]

        res = asyncio.run(macro_sentiment_service.get_btc_compass())
        self.assertTrue(res["is_panic_dump"])
        self.assertEqual(res["btc_trend_state"], "PANIC_DUMP")

    @patch("app.macro_sentiment_service.get_fear_and_greed", new_callable=AsyncMock)
    @patch("app.macro_sentiment_service.get_btc_compass", new_callable=AsyncMock)
    def test_get_macro_sentiment_combines(self, mock_btc, mock_fng):
        mock_fng.return_value = {"score": 25, "classification": "Fear"}
        mock_btc.return_value = {
            "btc_trend_state": "SIDEWAYS",
            "btc_15m_change_pct": -0.1,
            "is_panic_dump": False,
        }

        res = asyncio.run(macro_sentiment_service.get_macro_sentiment())
        self.assertEqual(res["fear_and_greed_score"], 25)
        self.assertFalse(res["is_btc_panic"])
        self.assertEqual(res["market_stress_level"], "HEALTHY")

    def test_cached_macro_sentiment(self):
        macro_sentiment_service._FNG_CACHE = (
            macro_sentiment_service.time.time(),
            {"score": 60, "classification": "Greed"},
        )
        macro_sentiment_service._BTC_COMPASS_CACHE = (
            macro_sentiment_service.time.time(),
            {"btc_trend_state": "MILD_BULLISH", "btc_15m_change_pct": 0.5, "is_panic_dump": False},
        )
        cached = macro_sentiment_service.get_cached_macro_sentiment()
        self.assertIsNotNone(cached)
        self.assertEqual(cached["fear_and_greed_score"], 60)
        self.assertEqual(cached["btc_trend_state"], "MILD_BULLISH")


if __name__ == "__main__":
    unittest.main()
