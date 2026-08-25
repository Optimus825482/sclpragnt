"""Tests for S3 (calibration buckets) and S6 (volatility sizing)."""
import unittest


class CalibrationBucketTests(unittest.TestCase):
    def _trades(self, n, pnl_fn, strategy="PUMP_MONITOR", vr=1.2, hour=10):
        from datetime import datetime, timezone
        base = datetime(2026, 8, 20, hour, 0, tzinfo=timezone.utc).timestamp()
        return [{"strategy": strategy, "pnl": pnl_fn(i), "entry_time": base,
                 "entry_context": {"liquidity": {"volume_ratio": vr}}}
                for i in range(n)]

    def test_bucket_key_bands(self):
        from app.calibration import hour_band, volume_band

        self.assertEqual(hour_band(6), "early_eu")
        self.assertEqual(hour_band(15), "us_overlap")
        self.assertEqual(hour_band(23), "late_night")
        self.assertEqual(volume_band(0.3), "very_low")
        self.assertEqual(volume_band(1.5), "normal")
        self.assertEqual(volume_band(3.2), "chasing")
        self.assertEqual(volume_band(None), "unknown")

    def test_build_buckets_counts_and_winrate(self):
        from app.calibration import build_buckets

        trades = self._trades(8, lambda i: 10 if i < 6 else -4)  # 6/8 win
        buckets = build_buckets(trades)
        key = next(iter(buckets))
        stats = buckets[key]
        self.assertEqual(stats["samples"], 8)
        self.assertAlmostEqual(stats["win_rate"], 0.75)

    def test_multiplier_anchors(self):
        from app.calibration import build_buckets, confidence_multiplier, MIN_BUCKET_SAMPLES

        good = build_buckets(self._trades(12, lambda i: 9 if i % 3 else -1))   # ~66% win
        bad = build_buckets(self._trades(12, lambda i: -8 if i % 3 else 1))    # ~33% win
        ctx = dict(strategy="PUMP_MONITOR", hour=10, volume_ratio=1.2)
        self.assertEqual(confidence_multiplier(good, **ctx), 1.0)
        self.assertEqual(confidence_multiplier(bad, **ctx), 0.5)
        # Thin-sample bucket stays neutral.
        thin = build_buckets(self._trades(MIN_BUCKET_SAMPLES - 1, lambda i: -8))
        self.assertEqual(confidence_multiplier(thin, **ctx), 1.0)
        # Unknown bucket stays neutral.
        self.assertEqual(confidence_multiplier({}, **ctx), 1.0)

    def test_summarize_sorts_by_expectancy(self):
        from app.calibration import build_buckets, summarize_for_ui

        bad = self._trades(10, lambda i: -9, hour=15)    # us_overlap bucket
        good = self._trades(10, lambda i: 9, hour=6)     # early_eu bucket
        rows = summarize_for_ui(build_buckets(bad + good))
        self.assertGreaterEqual(len(rows), 2)
        self.assertLessEqual(rows[0]["expectancy"], rows[-1]["expectancy"])

    def test_config_flag_exists(self):
        from app.config import config

        self.assertTrue(hasattr(config, "CALIBRATION_SIZING_ENABLED"))
        self.assertTrue(hasattr(config, "VOLATILITY_SIZING_ENABLED"))


class VolatilitySizingMathTests(unittest.TestCase):
    def test_scale_bounds_logic(self):
        # Mirror of the analyzer formula: high ATR% shrinks toward min scale;
        # low ATR% grows but is clamped at 1.0; floor respected.
        baseline = 0.006
        clamp_min = 0.35

        def scale_of(atr_pct):
            if atr_pct > baseline:
                s = baseline / atr_pct
            else:
                s = min(1.0, baseline / max(atr_pct, baseline * 0.25))
            return max(clamp_min, min(1.0, s))

        self.assertAlmostEqual(scale_of(0.006), 1.0)
        self.assertAlmostEqual(scale_of(0.012), 0.5)
        self.assertAlmostEqual(scale_of(0.030), clamp_min)     # deep clamp
        self.assertAlmostEqual(scale_of(0.001), 1.0)           # quiet -> full size


if __name__ == "__main__":
    unittest.main()
