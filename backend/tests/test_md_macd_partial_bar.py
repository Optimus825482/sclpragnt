"""MD — `_compute_cell` artık KAPANMIŞ mum MACD'si üzerinden hesaplanır.

A/B ölçümü: oluşan (canlı) barın seriye eklenmesi bar içinde ~%6-7 oranında
`green` işaretini yanlış çeviriyordu (girdi atan her flip). Bu test, hücrenin
canlı ticker'dan bağımsız (deterministik) ve kapanmış histogramın işaretine
bağlı olduğunu kilitler; eski davranış (live eklenmesi) testi KIRAR.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.routers import macd_monitor  # noqa: E402
from app.technical_analysis import _macd  # noqa: E402


def _hist_neg_closes():
    for step in (0.1, 0.3, 0.5, 0.7, 1.0, 1.5):
        closes = [100.0 - i * step for i in range(45)]
        m = _macd(closes)
        if m is not None and m["histogram"] < 0:
            return closes
    return None


def _positive_hist_closes():
    for step in (0.1, 0.3, 0.5, 0.7, 1.0, 1.5):
        closes = [100.0 + i * step for i in range(45)]
        m = _macd(closes)
        if m is not None and m["histogram"] > 0:
            return closes
    return None


class ClosedCellTests(unittest.TestCase):
    """_compute_cell deterministik ve canlı ticker'dan bağımsız olmalı."""

    def _cell(self, closes, live_price):
        history = {"closes": closes}
        ticker = {"last_price": live_price, "timestamp": 1_000_000_000_000}
        with mock.patch.object(macd_monitor.market, "get_ut_kline",
                               lambda *a, **k: history), \
                mock.patch.object(macd_monitor.market, "get_ticker",
                                  lambda *a, **k: ticker):
            return macd_monitor._compute_cell("XUSDT", "5m")

    def test_negative_hist_cell_is_deterministic_and_ignores_live_ticker(self):
        closes = _hist_neg_closes()
        if closes is None:
            self.skipTest("deterministik negatif-hist serisi bulunamadı")
        base = self._cell(closes, 0.0)
        assert base is not None and base["green"] is False, base
        # Canlı fiyatın aşırı uç değeri bile hücreyi değiştirmemeli (eski davranış
        # live barı ekleyip işareti çevirebiliyordu).
        loud = self._cell(closes, 1_000_000.0)
        assert loud == base, (loud, base)

    def test_positive_hist_cell_is_green(self):
        closes = _positive_hist_closes()
        if closes is None:
            self.skipTest("pozitif-hist serisi bulunamadı")
        assert self._cell(closes, 1.0)["green"] is True

    def test_repeated_calls_are_identical(self):
        closes = _hist_neg_closes()
        if closes is None:
            self.skipTest("negatif seri yok")
        a = self._cell(closes, 5.0)
        b = self._cell(closes, 7.0)
        assert a == b


if __name__ == "__main__":
    unittest.main()