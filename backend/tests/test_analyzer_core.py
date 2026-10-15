"""ScalpAnalyzer saf (ağ/DB'siz) yardımcıları için odaklı birim testleri.

Denetim 2026-10-15 bölüm 6: `analyzer.py` (1600 satır) için çekirdek saf
fonksiyonların (EMA / hacim patlaması oranı / trend-kilit kapıları / TP-SL dolum
fiyatı) doğrudan testi yoktu. Burada yalnızca ağ ve veritabanı gerektirmeyen
metotlar kullanılır; `market` sahte bir nesnedir.
"""
import time
import unittest
from unittest.mock import patch

from app.analyzer import ScalpAnalyzer


class _FakeMarket:
    def __init__(self, klines=None):
        self._klines = klines or {}

    def get_ut_kline(self, symbol, timeframe):
        return self._klines.get((symbol, timeframe), {})


def _analyzer(market=None):
    return ScalpAnalyzer(market)


class EmaTests(unittest.TestCase):
    def test_ema_of_constant_series_is_constant(self):
        self.assertAlmostEqual(_analyzer().calculate_ema([5.0] * 20, 9), 5.0)

    def test_ema_too_short_series_returns_none(self):
        self.assertIsNone(_analyzer().calculate_ema([1, 2, 3], 9))

    def test_ema_rising_series_trails_last_price(self):
        prices = [float(i) for i in range(1, 31)]
        ema = _analyzer().calculate_ema(prices, 9)
        # Yükselen seride EMA son fiyatın altında ama SMA başlangıcının üstünde kalır.
        self.assertLess(ema, prices[-1])
        self.assertGreater(ema, sum(prices[:9]) / 9)

    def test_trend_up_gate_price_above_ema(self):
        # README kuralı: "fiyat > 9 periyotluk EMA" => trend yukarı.
        a = _analyzer()
        rising = [float(i) for i in range(1, 31)]
        falling = list(reversed(rising))
        self.assertGreater(rising[-1], a.calculate_ema(rising, 9))
        self.assertLess(falling[-1], a.calculate_ema(falling, 9))


class VolumeRatioTests(unittest.TestCase):
    def _ratio(self, vols, details=None, market_has_kline=True):
        klines = {("BTCTRY", "5m"): {"volumes": vols}} if market_has_kline else {}
        return _analyzer(_FakeMarket(klines))._entry_volume_ratio("BTCTRY", details)

    def test_spike_is_last_over_mean_of_prior_20(self):
        vols = [100.0] * 20 + [300.0]
        self.assertAlmostEqual(self._ratio(vols), 3.0)

    def test_spike_threshold_1_5x_distinguishes_breakout(self):
        self.assertGreater(self._ratio([100.0] * 20 + [160.0]), 1.5)
        self.assertLess(self._ratio([100.0] * 20 + [120.0]), 1.5)

    def test_short_history_falls_back_to_details_volume_ratio(self):
        self.assertAlmostEqual(self._ratio([1.0] * 5, {"volume_ratio": "2.5"}), 2.5)

    def test_no_data_returns_none(self):
        self.assertIsNone(self._ratio([1.0] * 5))
        self.assertIsNone(_analyzer(None)._entry_volume_ratio("BTCTRY", {"volume_ratio": 3}))


class ProfitLockTests(unittest.TestCase):
    def test_lock_armed_from_memory_or_persisted_runtime(self):
        self.assertFalse(ScalpAnalyzer._lock_armed({}))
        self.assertTrue(ScalpAnalyzer._lock_armed({"velocity_protection_armed": True}))
        persisted = {"entry_context": {"_runtime": {"velocity_protection_armed": True}}}
        self.assertTrue(ScalpAnalyzer._lock_armed(persisted))

    def test_lock_stop_prefers_memory_and_ignores_invalid(self):
        pos = {"system_stop_price": "101.5",
               "entry_context": {"_runtime": {"system_stop_price": 99.0}}}
        self.assertEqual(ScalpAnalyzer._lock_stop(pos), 101.5)
        self.assertEqual(ScalpAnalyzer._lock_stop({"system_stop_price": 0,
                         "entry_context": {"_runtime": {"system_stop_price": 99.0}}}), 99.0)
        self.assertIsNone(ScalpAnalyzer._lock_stop({"system_stop_price": "abc"}))
        self.assertIsNone(ScalpAnalyzer._lock_stop({}))


class FillPriceTests(unittest.TestCase):
    def test_take_profit_never_fills_better_than_trigger(self):
        self.assertEqual(ScalpAnalyzer._trigger_fill_price(105.0, 102.0, "take_profit"), 102.0)
        self.assertEqual(ScalpAnalyzer._trigger_fill_price(101.0, 102.0, "take_profit"), 101.0)

    def test_stop_never_fills_better_than_trigger(self):
        self.assertEqual(ScalpAnalyzer._trigger_fill_price(95.0, 98.0, "stop"), 98.0)
        self.assertEqual(ScalpAnalyzer._trigger_fill_price(99.0, 98.0, "stop"), 99.0)

    def test_invalid_trigger_returns_price_unchanged(self):
        for trigger in (None, "x", 0, -1):
            self.assertEqual(ScalpAnalyzer._trigger_fill_price(100.0, trigger, "take_profit"), 100.0)


class HoldAndReasonTests(unittest.TestCase):
    def test_explicit_hold_is_kept_and_invalid_falls_back_to_config(self):
        self.assertEqual(ScalpAnalyzer._planned_max_hold_sec(900), 900)
        with patch("app.analyzer.config") as cfg:
            cfg.VELOCITY_MAX_HOLD_MIN = 30
            for bad in (None, 0, -5, "x"):
                self.assertEqual(ScalpAnalyzer._planned_max_hold_sec(bad), 1800)
            cfg.VELOCITY_MAX_HOLD_MIN = 0
            self.assertIsNone(ScalpAnalyzer._planned_max_hold_sec(None))

    def test_liquidity_reason_lists_failed_checks(self):
        details = {"checks": {"spread": False, "volume": True, "depth": False}}
        self.assertEqual(ScalpAnalyzer._liquidity_reason(details), "entry_ineligible:spread,depth")
        self.assertEqual(ScalpAnalyzer._liquidity_reason({}), "entry_ineligible:unknown")


class ReentryGuardTests(unittest.TestCase):
    def test_timeout_and_hard_stop_blocks_expire(self):
        a = _analyzer()
        a._timeout_block_until["X"] = time.time() + 60
        self.assertEqual(a._reentry_block_reason("X", "1m"), "timeout_reentry_block")
        a._timeout_block_until["X"] = time.time() - 1
        self.assertIsNone(a._reentry_block_reason("X", "1m"))
        self.assertNotIn("X", a._timeout_block_until)
        a._hard_stop_block_until["Y"] = time.time() + 60
        self.assertEqual(a._reentry_block_reason("Y", "1m"), "hard_stop_reentry_block")

    def test_bar_cooldown_blocks_until_bar_advances(self):
        market = _FakeMarket({("Z", "1m"): {"closes": [1, 2, 3]}})  # current_bar == 2
        a = _analyzer(market)
        a._cooldown_until["Z"] = 5
        self.assertEqual(a._reentry_block_reason("Z", "1m"), "bar_cooldown")
        a._cooldown_until["Z"] = 2
        self.assertIsNone(a._reentry_block_reason("Z", "1m"))
        self.assertNotIn("Z", a._cooldown_until)


if __name__ == "__main__":
    unittest.main()
