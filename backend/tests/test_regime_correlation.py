"""Tests for S4 (regime-gated sizing) and S5 (dynamic correlation control)."""
import unittest


class RegimeSizingTests(unittest.TestCase):
    def test_mean_reversion_shrinks_in_trends(self):
        from app.calibration import regime_size_multiplier

        self.assertEqual(regime_size_multiplier("mean_reversion", "bull_quiet", 0.7), 0.5)
        self.assertEqual(regime_size_multiplier("mean_reversion", "bear_volatile", 0.7), 0.5)
        # Range regimes keep full size for mean reversion.
        self.assertEqual(regime_size_multiplier("mean_reversion", "range_transition", 0.6), 1.0)

    def test_continuation_shrinks_in_ranges(self):
        from app.calibration import regime_size_multiplier

        self.assertEqual(regime_size_multiplier("continuation", "range_transition", 0.6), 0.7)
        self.assertEqual(regime_size_multiplier("continuation", "bull_quiet", 0.7), 1.0)

    def test_unknown_or_low_confidence_stays_neutral(self):
        from app.calibration import regime_size_multiplier

        self.assertEqual(regime_size_multiplier("mean_reversion", None, None), 1.0)
        self.assertEqual(regime_size_multiplier("mean_reversion", "bull_quiet", 0.4), 1.0)
        self.assertEqual(regime_size_multiplier("unknown_style", "bull_quiet", 0.8), 1.0)

    def test_strategy_style_mapping(self):
        from app.calibration import strategy_style_of

        self.assertEqual(strategy_style_of("BB_MFI_MEAN_REVERSION"), "mean_reversion")
        self.assertEqual(strategy_style_of("PUMP_MONITOR"), "continuation")
        self.assertEqual(strategy_style_of("LLM_PAPER"), "unknown")


class CorrelationModuleTests(unittest.TestCase):
    def test_pearson_perfect_and_inverse(self):
        from app.correlation import _pearson

        xs = [0.01 * ((i % 5) + 1) for i in range(40)]
        self.assertAlmostEqual(_pearson(xs, xs), 1.0, places=6)
        ys = [-x for x in xs]
        self.assertAlmostEqual(_pearson(xs, ys), -1.0, places=6)

    def test_thin_data_defaults_high(self):
        from app.correlation import _pearson

        xs = [0.01, -0.02, 0.03]
        self.assertEqual(_pearson(xs, xs), 0.75)

    def test_cluster_exposure_weights_by_correlation(self):
        from app.correlation import cluster_exposure, CorrelationMonitor

        monitor = CorrelationMonitor()
        monitor._corr = {"AAATRY": {"BTC": 0.9, "ETH": 0.7}, "BBBTRY": {"BTC": 0.2, "ETH": 0.3}}
        positions = {
            "AAATRY": {"entry_price": 100, "quantity": 5},   # 500 * 0.9 = 450
            "BBBTRY": {"entry_price": 100, "quantity": 5},   # 500 * 0.2 = 100
        }
        result = cluster_exposure(positions, None, 0.0, monitor, "BTC", 2000.0)
        self.assertAlmostEqual(result["weighted_exposure"], 550.0, places=1)
        self.assertAlmostEqual(result["exposure_pct"], 27.5, places=1)

        # Adding a new correlated position pushes past a 30% cap.
        capped = cluster_exposure(positions, "CCCTRY", 300.0, monitor, "BTC", 2000.0)
        self.assertGreater(capped["exposure_pct"], 30.0)

    def test_conservative_default_for_unknown_symbol(self):
        from app.correlation import CorrelationMonitor

        m = CorrelationMonitor()
        self.assertAlmostEqual(m.correlation_of("UNKNOWNTRY", "BTC"), 0.75)


if __name__ == "__main__":
    unittest.main()
