import unittest

from app.technical_analysis import _candlestick_patterns


class CandlestickPatternBehaviorTests(unittest.TestCase):
    def test_three_soldiers_must_include_the_last_confirmed_candle(self):
        # The first three candles are bullish, but the newest closed candle is
        # bearish.  The former implementation incorrectly inspected only the
        # three preceding candles and painted a stale bullish marker.
        opens = [10.0, 10.1, 10.8, 11.5]
        highs = [10.7, 11.2, 11.8, 11.7]
        lows = [9.9, 10.0, 10.7, 10.7]
        closes = [10.6, 11.1, 11.7, 10.9]

        self.assertNotIn("three_white_soldiers", _candlestick_patterns(opens, highs, lows, closes))

    def test_three_soldiers_requires_body_and_open_progression(self):
        opens = [9.8, 10.0, 10.4, 10.9]
        highs = [10.1, 10.7, 11.2, 11.8]
        lows = [9.7, 9.9, 10.3, 10.8]
        closes = [10.0, 10.6, 11.1, 11.7]

        self.assertIn("three_white_soldiers", _candlestick_patterns(opens, highs, lows, closes))

    def test_doji_is_not_mislabelled_as_hammer(self):
        opens = [11.0, 10.5, 10.0]
        highs = [11.2, 10.7, 10.2]
        lows = [10.7, 10.1, 8.0]
        closes = [10.6, 10.0, 10.01]

        patterns = _candlestick_patterns(opens, highs, lows, closes)
        self.assertIn("doji", patterns)
        self.assertNotIn("hammer", patterns)

    def test_hammer_requires_prior_downtrend_and_material_body(self):
        opens = [11.0, 10.6, 10.0]
        highs = [11.1, 10.7, 10.18]
        lows = [10.5, 9.9, 8.7]
        closes = [10.6, 10.0, 10.15]

        self.assertIn("hammer", _candlestick_patterns(opens, highs, lows, closes))

    def test_misaligned_ohlc_input_fails_closed(self):
        self.assertEqual(
            _candlestick_patterns([1, 2, 3], [2, 3], [0, 1, 2], [1.5, 2.5, 3.5]),
            ["none"],
        )

