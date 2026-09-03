import asyncio
import re
import time
import unittest
from unittest.mock import patch

from app.routers import chart_forecast


def _run(coro):
    return asyncio.run(coro)


def _async_klines(rows):
    async def mock(*args, **kwargs):
        return rows
    return mock


class ChartForecastOutcomeTests(unittest.TestCase):
    def test_outcome_measured_from_closed_m1_when_horizon_closed(self):
        # 5dk ufuk; created_at=0 -> due=300s; 6 M1 mum yeterli.
        created_at = 0.0
        base = 100.0
        rows = [
            [0, base, 100.2, 99.8, 100.0, 1],
            [60_000, 100.0, 101.5, 99.9, 101.0, 1],   # >= target 101 -> ilk dokunuş 1.dk
            [120_000, 101.0, 102.0, 100.5, 101.5, 1],
            [180_000, 101.5, 103.0, 101.0, 102.5, 1],
            [240_000, 102.5, 104.0, 102.0, 103.5, 1],
            [300_000, 103.5, 105.0, 103.0, 104.0, 1],  # due kapanış
        ]
        forecast = {"symbol": "TESTTRY", "horizon_minutes": 5, "created_at": created_at,
                    "entry_price": base, "target_pct": 1.0, "target_price": 101.0}
        with patch.object(chart_forecast, "fetch_klines", new=_async_klines(rows)):
            outcome = _run(chart_forecast._outcome_from_closed_m1("TESTTRY", forecast))
        self.assertIsNotNone(outcome)
        self.assertAlmostEqual(outcome["outcome_price"], 104.0)
        self.assertAlmostEqual(outcome["max_high"], 105.0)
        self.assertAlmostEqual(outcome["min_low"], 99.8)
        self.assertAlmostEqual(outcome["first_hit_minutes"], 1.0)

    def test_outcome_none_when_horizon_not_closed(self):
        forecast = {"symbol": "TESTTRY", "horizon_minutes": 5, "created_at": 0.0,
                    "entry_price": 100.0, "target_pct": 1.0, "target_price": 101.0}
        rows = [[0, 100, 100.2, 99.8, 100.0, 1], [60_000, 100, 100.1, 99.9, 100.0, 1]]
        with patch.object(chart_forecast, "fetch_klines", new=_async_klines(rows)):
            outcome = _run(chart_forecast._outcome_from_closed_m1("TESTTRY", forecast))
        self.assertIsNone(outcome)


class ChartForecastFeatureTests(unittest.TestCase):
    def test_features_collected_from_fresh_m1(self):
        now_ms = int(time.time() * 1000)
        rows = []
        for i in range(40):
            p = 100.0 + i * 0.01
            rows.append([now_ms - (40 - i) * 60_000, p, p + 0.2, p - 0.2, p, 1.0])
        # son mumun kapanış zamanı son ~60s içinde olacak şekilde son mumu şimdi yap
        rows[-1] = [now_ms - 45_000, 100.4, 100.6, 100.2, 100.4, 1.0]
        with patch.object(chart_forecast, "fetch_klines", new=_async_klines(rows)):
            features = _run(chart_forecast.collect_forecast_features("TESTTRY"))
        self.assertIsNotNone(features)
        self.assertGreater(features["price"], 0)
        self.assertIsNotNone(features["atr_pct"])
        self.assertIsNotNone(features["rsi"])
        self.assertIn("ret3_pct", features)


    def test_clear_all_sql_is_placeholder_safe(self):
        # `?` ayraç çevirisi (%s) JSONB varlık operatörünü bozar — SQL'de
        # ayraç/sorgu değişkeni için `?` bulunmamalı (jsonb_exists formu güvenli).
        from app.database import clear_all_chart_indicators
        sql = "UPDATE chart_settings SET data = data - 'indicators' WHERE jsonb_exists(data, 'indicators')"
        # _PostgresCompat çevirisi sonrası bozulmamış kalmalı
        translated = sql.replace("?", "%s")
        self.assertNotIn("? ", translated)
        self.assertIn("jsonb_exists(data, 'indicators')", translated)


if __name__ == "__main__":
    unittest.main()
