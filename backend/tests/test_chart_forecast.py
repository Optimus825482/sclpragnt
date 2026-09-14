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


class _FakeClock:
    """`chart_forecast` icindeki `time` modulunun yerine gecer (salt okunur)."""

    def __init__(self, value: float) -> None:
        self.value = value

    def time(self) -> float:
        return self.value

    def __getattr__(self, name):
        return getattr(time, name)


class ChartForecastFreshnessTests(unittest.TestCase):
    """Tazelik kapisi 5m seriye gore olceklenmeli.

    collect_forecast_features() D-04 geregi olusmakta olan 5m bari dusr, sonra
    son KAPANMIS barin yasini olcer. 5m grid'de bu yas DOGAL OLARAK 0..300 sn
    arasinda degisir. Sabit 180 sn esigiyle 5 dakikalik pencerenin yaklasik
    2 dakikasinda canli sembolde bile None donuyor -> endpoint 503 (olculdu:
    ~%40). Kapı artik bir bar araligi + pay (300 + 120) tolerans verir; amaci
    yalnizca "olu sembol" yakalamaktir.
    """

    BAR_MS = 300_000

    @classmethod
    def _rows_for(cls, now_ms: int, n: int = 40, shift_ms: int = 0):
        """`now_ms` anindaki 5m seri (son satir olusmakta olan bar)."""
        last_open = now_ms - (now_ms % cls.BAR_MS) + shift_ms
        rows = []
        for i in range(n):
            t = last_open - (n - 1 - i) * cls.BAR_MS
            p = 100.0 + i * 0.01
            rows.append([t, p, p + 0.2, p - 0.2, p, 1.0])
        return rows

    def test_live_symbol_passes_across_full_5m_window(self):
        base = int(time.time() * 1000)
        base -= base % self.BAR_MS
        for offset in range(0, self.BAR_MS + 1, 10_000):
            now_ms = base + offset + 1_000  # 5m barin icinde bir an
            rows = self._rows_for(now_ms)
            with patch.object(chart_forecast, "fetch_klines", new=_async_klines(rows)), \
                    patch.object(chart_forecast, "time", new=_FakeClock(now_ms / 1000.0)):
                features = _run(chart_forecast.collect_forecast_features("TESTTRY"))
            self.assertIsNotNone(
                features, f"offset={offset}ms: canli sembolde tazelik kapisi 503 uretti")

    def test_dead_symbol_still_rejected(self):
        now_ms = int(time.time() * 1000)
        stale = self._rows_for(now_ms, shift_ms=-3 * 3600_000)  # 3 saat bayat
        with patch.object(chart_forecast, "fetch_klines", new=_async_klines(stale)), \
                patch.object(chart_forecast, "time", new=_FakeClock(now_ms / 1000.0)):
            features = _run(chart_forecast.collect_forecast_features("TESTTRY"))
        self.assertIsNone(features, "olu sembolde tahmin uretilmemeli")

    def test_threshold_scales_with_bar_interval(self):
        self.assertGreater(chart_forecast.INFERENCE_BAR_MS // 1000, 180)
        self.assertEqual(chart_forecast.INFERENCE_BAR_MS, 300_000)


if __name__ == "__main__":
    unittest.main()
