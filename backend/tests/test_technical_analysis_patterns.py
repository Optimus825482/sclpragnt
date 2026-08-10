import unittest

from app.technical_analysis import CANDLESTICK_PATTERN_INFO, _candlestick_patterns


REQUESTED_PATTERNS = {
    "bullish_engulfing", "bearish_engulfing", "bullish_harami", "bearish_harami",
    "hammer", "hanging_man", "shooting_star", "inverted_hammer", "piercing_line",
    "dark_cloud_cover", "three_inside_up", "three_inside_down", "morning_star", "evening_star",
}


class CandlestickPatternBehaviorTests(unittest.TestCase):
    def assert_pattern(self, expected, opens, highs, lows, closes):
        self.assertIn(expected, _candlestick_patterns(opens, highs, lows, closes))

    def test_requested_pattern_metadata_is_complete(self):
        self.assertEqual(set(CANDLESTICK_PATTERN_INFO), REQUESTED_PATTERNS)
        self.assertTrue(all(info["direction"] in {"bullish", "bearish"} for info in CANDLESTICK_PATTERN_INFO.values()))

    def test_engulfing_and_harami_patterns_require_directional_bodies(self):
        self.assert_pattern("bullish_engulfing", [11, 10.5, 9.7], [11.1, 10.6, 10.8], [10.5, 9.7, 9.6], [10.6, 9.8, 10.7])
        self.assert_pattern("bearish_engulfing", [9, 9.5, 10.3], [9.1, 10.2, 10.4], [8.9, 9.4, 9.3], [9.4, 10.1, 9.3])
        self.assert_pattern("bullish_harami", [11, 10.5, 10.15], [11.1, 10.6, 10.35], [10.5, 9.9, 10.1], [10.6, 10, 10.3])
        self.assert_pattern("bearish_harami", [9, 9.5, 10.25], [9.1, 10.6, 10.3], [8.9, 9.4, 10.05], [9.4, 10.5, 10.1])

    def test_single_candle_shapes_use_preceding_trend_for_their_meaning(self):
        self.assert_pattern("hammer", [11, 10.5, 10], [11.1, 10.6, 10.2], [10.5, 9.9, 8.7], [10.6, 10, 10.15])
        self.assert_pattern("hanging_man", [9, 9.5, 10], [9.1, 10.1, 10.2], [8.9, 9.4, 8.7], [9.4, 10, 10.15])
        self.assert_pattern("shooting_star", [9, 9.5, 10], [9.1, 10.1, 11.5], [8.9, 9.4, 9.7], [9.4, 10, 9.8])
        self.assert_pattern("inverted_hammer", [11, 10.5, 10], [11.1, 10.6, 11.5], [10.5, 9.9, 9.85], [10.6, 10, 10.2])

    def test_piercing_and_dark_cloud_require_midpoint_reversal(self):
        self.assert_pattern("piercing_line", [11, 10.5, 9.7], [11.1, 10.6, 10.4], [10.5, 9.7, 9.6], [10.6, 9.8, 10.25])
        self.assert_pattern("dark_cloud_cover", [9, 9.5, 10.3], [9.1, 10.6, 10.4], [8.9, 9.4, 9.5], [9.4, 10.5, 9.75])

    def test_three_candle_reversals_are_confirmed_by_the_latest_closed_candle(self):
        self.assert_pattern("three_inside_up", [12, 11.5, 10.5, 10.15, 10.3], [12.1, 11.6, 10.6, 10.35, 10.8], [11.9, 11.4, 9.9, 10.1, 10.2], [11.8, 11, 10, 10.3, 10.7])
        self.assert_pattern("morning_star", [12, 11.5, 10.5, 10.05, 10.1], [12.1, 11.6, 10.6, 10.2, 10.9], [11.9, 11.4, 9.9, 9.9, 10.0], [11.8, 11, 10, 10.1, 10.8])
        self.assert_pattern("three_inside_down", [8, 8.5, 9.5, 9.85, 9.7], [8.1, 8.6, 10.1, 9.9, 9.8], [7.9, 8.4, 9.4, 9.65, 9.2], [8.2, 9, 10, 9.7, 9.3])
        self.assert_pattern("evening_star", [8, 8.5, 9.5, 9.95, 9.9], [8.1, 8.6, 10.1, 10.1, 10.0], [7.9, 8.4, 9.4, 9.8, 9.1], [8.2, 9, 10, 9.9, 9.2])

    def test_no_reversal_label_without_required_trend_or_confirmation(self):
        # The newest bullish body engulfs the previous body, but price was not
        # declining beforehand; it is continuation, not a bullish reversal.
        patterns = _candlestick_patterns([9, 9.5, 9.3], [9.1, 9.6, 10.4], [8.9, 9.2, 9.2], [9.4, 9.3, 10.3])
        self.assertNotIn("bullish_engulfing", patterns)
        # A three-inside-like sequence without a third-candle breakout fails closed.
        patterns = _candlestick_patterns([12, 11.5, 10.5, 10.15, 10.25], [12.1, 11.6, 10.6, 10.35, 10.45], [11.9, 11.4, 9.9, 10.1, 10.1], [11.8, 11, 10, 10.3, 10.35])
        self.assertNotIn("three_inside_up", patterns)

    def test_misaligned_ohlc_input_fails_closed(self):
        self.assertEqual(_candlestick_patterns([1, 2, 3], [2, 3], [0, 1, 2], [1.5, 2.5, 3.5]), ["none"])
