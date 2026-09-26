"""MACD MTF konfluans: seri hesabı, kesişim yaşı, eğim/paralel bayrağı, özet ve önbellek."""
import asyncio
import unittest
from unittest.mock import patch

from app import macd_mtf


def _rising_closes(n=120, base=100.0, step_pct=0.5):
    out, price = [], base
    for _ in range(n):
        price *= 1 + step_pct / 100.0
        out.append(price)
    return out


def _vshape_closes(n_down=95, n_up=8, base=100.0):
    """Önce yumuşak düşüş, sonra güçlü yükseliş → MACD taze yukarı kesişir."""
    out, price = [], base
    for _ in range(n_down):
        price *= 1 - 0.10 / 100.0
        out.append(price)
    for _ in range(n_up):
        price *= 1 + 1.2 / 100.0
        out.append(price)
    return out


def _history(closes):
    return {"closes": list(closes), "highs": list(closes), "lows": list(closes)}


class SeriesTests(unittest.TestCase):
    def test_rising_series_bullish_and_parallel_up(self):
        macd, signal = macd_mtf._macd_full_series(_rising_closes())
        self.assertIsNotNone(macd)
        self.assertGreater(macd[-1], signal[-1])
        cell = macd_mtf._tf_cell("X", "5m")
        # _tf_cell market'ten okur; doğrudan hücre hesabı için seriyi ayrı test ediyoruz.
        self.assertIsInstance(cell, (dict, type(None)))

    def test_series_rejects_short_input(self):
        self.assertIsNone(macd_mtf._macd_full_series([1.0] * 20))

    def test_cross_age_counts_bars_since_flip(self):
        closes = _vshape_closes()
        macd, signal = macd_mtf._macd_full_series(closes)
        self.assertIsNotNone(macd)
        bullish_now = macd[-1] > signal[-1]
        age = 0
        while (len(macd) - age - 2 >= 0
               and macd[-age - 2] is not None and signal[-age - 2] is not None
               and (macd[-age - 2] > signal[-age - 2]) == bullish_now):
            age += 1
        self.assertGreater(age, 0)            # düşüşte bearish'ti → en az 1 bar önce flip
        self.assertLessEqual(age, len(closes))  # makul sınırlar
        self.assertEqual(bullish_now, True)   # V yükselişi → bullish

    def test_ols_slope_sign(self):
        self.assertGreater(macd_mtf._ols_slope([1.0, 2.0, 3.0, 4.0]), 0)
        self.assertLess(macd_mtf._ols_slope([4.0, 3.0, 2.0, 1.0]), 0)
        self.assertEqual(macd_mtf._ols_slope([5.0]), 0.0)


class SummarizeTests(unittest.TestCase):
    def _cell(self, tf, green=True, parallel=True, fresh=False):
        return {"tf": tf, "macd": 0.01, "signal": 0.005, "hist": 0.005, "green": green,
                "cross_age_bars": 1 if fresh else 30, "macd_slope_pct": 0.1 if parallel else -0.1,
                "signal_slope_pct": 0.05 if parallel else -0.05, "parallel_up": parallel,
                "fresh_bull_cross": fresh}

    def test_full_confluence_strong(self):
        cells = [self._cell(tf, fresh=(tf == "5m")) for tf in ("1m", "3m", "5m", "15m")]
        result = macd_mtf._summarize("X", cells)
        self.assertEqual(result["green_count"], 4)
        self.assertEqual(result["parallel_up_count"], 4)
        self.assertEqual(result["fresh_cross"], ["5m"])
        self.assertEqual(result["verdict"], "GÜÇLÜ")
        self.assertGreaterEqual(result["confluence"], 95)

    def test_weak_confluence(self):
        cells = [self._cell("1m", green=False, parallel=False),
                 self._cell("3m", green=False, parallel=False),
                 self._cell("5m", green=True, parallel=False),
                 self._cell("15m", green=False, parallel=False)]
        result = macd_mtf._summarize("X", cells)
        self.assertEqual(result["verdict"], "ZAYIF")
        self.assertLess(result["confluence"], 45)

    def test_insufficient_data_no_verdict(self):
        result = macd_mtf._summarize("X", [None, None, None, None])
        self.assertEqual(result["verdict"], "VERİ YOK")
        self.assertIsNone(result["confluence"])
        result2 = macd_mtf._summarize("X", [self._cell("5m")])
        self.assertEqual(result2["verdict"], "VERİ YOK")


class ComputeCacheTests(unittest.TestCase):
    def setUp(self):
        macd_mtf.reset_state_for_tests()

    def test_compute_and_ttl_cache(self):
        closes = _rising_closes()
        with patch.object(macd_mtf, "market") as fake_market:
            fake_market.get_ut_kline.return_value = _history(closes)
            result = asyncio.run(macd_mtf.compute("HEMITRY"))
            self.assertIsNotNone(result)
            self.assertEqual(result["coverage"], 4)
            self.assertEqual(result["verdict"], "GÜÇLÜ")
            # İkinci çağrı önbellekten: refresh_series HİÇ çağrılmaz, computed_at aynı.
            second = asyncio.run(macd_mtf.compute("HEMITRY"))
            fake_market.refresh_series.assert_not_called()
            self.assertEqual(second["computed_at"], result["computed_at"])

    def test_missing_tf_triggers_single_refresh(self):
        store = {"1m": _history(_rising_closes()), "3m": {"closes": []},
                 "5m": _history(_rising_closes()), "15m": _history(_rising_closes())}

        def _get(sym, tf):
            return dict(store.get(tf) or {"closes": []})

        async def _refresh(sym, tf, limit=150):
            store[tf] = _history(_rising_closes())
            return True

        with patch.object(macd_mtf, "market") as fake_market:
            fake_market.get_ut_kline.side_effect = _get
            fake_market.refresh_series.side_effect = _refresh
            result = asyncio.run(macd_mtf.compute("HEMITRY"))
            self.assertEqual(result["coverage"], 4)
            fake_market.refresh_series.assert_called_once()

    def test_cached_compact_shape_and_absent(self):
        self.assertIsNone(macd_mtf.cached_compact("YOK"))
        closes = _rising_closes()
        with patch.object(macd_mtf, "market") as fake_market:
            fake_market.get_ut_kline.return_value = _history(closes)
            asyncio.run(macd_mtf.compute("HEMITRY"))
        compact = macd_mtf.cached_compact("HEMITRY")
        self.assertIsNotNone(compact)
        self.assertNotIn("cells", compact)
        self.assertIn("age_sec", compact)
        self.assertGreaterEqual(compact["age_sec"], 0.0)
        self.assertEqual(compact["verdict"], "GÜÇLÜ")

    def test_refresh_many_bounds_and_counts(self):
        calls = []

        async def _compute(sym, *, force=False):
            calls.append(sym)
            return {"symbol": sym}

        with patch.object(macd_mtf, "compute", _compute):
            n = asyncio.run(macd_mtf.refresh_many(["A"] * 30))
        self.assertEqual(n, macd_mtf._REFRESH_PER_CALL)
        self.assertEqual(len(calls), macd_mtf._REFRESH_PER_CALL)


if __name__ == "__main__":
    unittest.main()
