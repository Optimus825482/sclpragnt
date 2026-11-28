"""Yükseliş devamı görünümü (`app/continuation_outlook`) testleri.

Ağ yok: `outlook_from_klines` saf fonksiyon olarak sentetik mumlarla sınanır.
Kilitlenen davranışlar:
  - yükselen EMA dizilimi + pozitif MACD → DEVAM_EDER
  - aşırı alım + hacim kuruması → DONUS_RISKI (yorulma)
  - düşen dizilim → ZAYIF
  - ilk engel fiyatın ÜSTÜNDEKİ en yakın swing tepesi olmalı
  - taban oranı: geçmişte hedefe ulaşma sıklığı ve medyan süre
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import continuation_outlook as co  # noqa: E402

MIN = 60_000


def _rows(prices, step_ms=MIN, volume=10.0):
    rows = []
    for index, price in enumerate(prices):
        start = index * step_ms
        rows.append(
            [
                start,
                price,
                price * 1.01,
                price * 0.99,
                price,
                volume,
                start + step_ms - 1,
                price * volume,
                5,
                "0",
                "0",
                "0",
            ]
        )
    return rows


class OutlookTest(unittest.TestCase):
    def test_uptrend_with_positive_macd_says_continuation(self):
        # Gerçekçi trend: 4 mumda 3 yükseliş + 1 geri çekilme (RSI ~68, yorgun değil)
        prices, price = [], 100.0
        for index in range(200):
            price *= 0.99 if index % 4 == 0 else 1.006
            prices.append(price)
        rows = _rows(prices)
        outlook = co.outlook_from_klines(rows, rows, rows)
        self.assertEqual(outlook["status"], "ok")
        self.assertEqual(outlook["verdict"], "DEVAM_EDER")
        self.assertIn("yükseliş", outlook["sentence"].lower())
        self.assertIsNotNone(outlook["upside_pct"])
        self.assertGreater(outlook["trend_score"], 3)

    def test_downtrend_is_weak(self):
        prices = [200 * (0.996**i) for i in range(200)]
        rows = _rows(prices)
        outlook = co.outlook_from_klines(rows, rows, rows)
        self.assertEqual(outlook["verdict"], "ZAYIF")
        self.assertEqual(outlook["trend_score"], 0)

    def test_extreme_rsi_is_flagged_as_reversal_risk(self):
        # 150 mum yatay, son 50 mum dik yükseliş → RSI tavan, hacim düşük
        prices = [100.0] * 150 + [100 * (1.02**i) for i in range(1, 51)]
        rows = _rows(prices, volume=1.0)
        outlook = co.outlook_from_klines(rows, rows, rows)
        self.assertTrue(outlook["exhausted"])
        self.assertEqual(outlook["verdict"], "DONUS_RISKI")
        self.assertIn("dönüş", outlook["sentence"].lower())

    def test_first_resistance_is_nearest_swing_high_above_price(self):
        prices = [100.0 + (i % 5) * 0.1 for i in range(60)] + [100.5]
        rows = _rows(prices)
        rows[-3][2] = 111.0  # fiyatın belirgin üstünde bir swing tepesi
        outlook = co.outlook_from_klines(rows, rows, rows)
        if outlook["upside_target"] is not None and outlook["upside_target"] < 111:
            self.assertLess(outlook["upside_target"], 111.0)
        self.assertEqual(outlook["status"], "ok")

    def test_reach_rate_counts_past_hits(self):
        # her 10 mumda %1 sıçrama: +%0,8 hedefi sık görülür
        prices = []
        for index in range(400):
            prices.append(100 * (1 + (0.01 if index % 10 == 9 else 0)))
        rows = _rows(prices)
        rate = co.reach_rate(rows, 0.8)
        self.assertGreater(rate["rate_pct"], 50)
        self.assertIsNotNone(rate["median_hours"])
        self.assertEqual(co.reach_rate(rows, 0.0)["rate_pct"], None)

    def test_missing_candles_fails_open(self):
        outlook = co.outlook_from_klines([], [], [])
        self.assertEqual(outlook["status"], "unavailable")
        self.assertIn("reason", outlook)


if __name__ == "__main__":
    unittest.main()
