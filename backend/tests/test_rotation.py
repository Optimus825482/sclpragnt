"""app/rescan/rotation.py birim testleri (2026-10-17)."""
import math
import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rescan import rotation as R  # noqa: E402


class TestTopK(unittest.TestCase):
    def test_largest_and_smallest(self):
        score = np.array([[1.0, 5.0, 3.0, 4.0, 2.0]])
        valid = np.ones((1, 5), bool)
        w = R.topk_weights(score, valid, 2, largest=True, min_valid=1)
        np.testing.assert_allclose(w, [[0, 0.5, 0, 0.5, 0]])
        w = R.topk_weights(score, valid, 2, largest=False, min_valid=1)
        np.testing.assert_allclose(w, [[0.5, 0, 0, 0, 0.5]])

    def test_invalid_and_nan_excluded(self):
        score = np.array([[9.0, np.nan, 3.0, 4.0, 2.0]])
        valid = np.array([[False, True, True, True, True]])
        w = R.topk_weights(score, valid, 2, min_valid=1)
        np.testing.assert_allclose(w, [[0, 0, 0.5, 0.5, 0]])

    def test_fewer_candidates_than_k_leaves_cash(self):
        score = np.array([[np.nan, 1.0, np.nan, np.nan]])
        w = R.topk_weights(score, np.ones((1, 4), bool), 3, min_valid=1)
        np.testing.assert_allclose(w, [[0, 1 / 3, 0, 0]])

    def test_min_valid_gate_gives_cash(self):
        score = np.arange(6, dtype=float)[None, :]
        w = R.topk_weights(score, np.ones((1, 6), bool), 2, min_valid=7)
        self.assertEqual(w.sum(), 0.0)

    def test_rows_independent(self):
        rng = np.random.default_rng(3)
        sc = rng.normal(size=(50, 30))
        w = R.topk_weights(sc, np.ones((50, 30), bool), 5, min_valid=1)
        np.testing.assert_allclose(w.sum(axis=1), 1.0)
        self.assertTrue(((w > 0).sum(axis=1) == 5).all())
        top = np.argsort(-sc, axis=1)[:, :5]
        for i in range(50):
            self.assertEqual(set(np.flatnonzero(w[i])), set(top[i]))


class TestSimulateSleeve(unittest.TestCase):
    def test_no_cost_buy_and_hold_matches_price(self):
        # 2 sembol, 4 saat; saat 0'da %50/%50 al, sonra tut
        r = np.array([[0.0, 0.0], [0.10, -0.10], [0.10, 0.0], [0.0, 0.10]])
        wt = np.zeros((4, 2))
        wt[0] = [0.5, 0.5]
        rebal = np.array([True, False, False, False])
        net, gross, turn = R.simulate_sleeve(r, wt, rebal, 0.0)
        eq = np.prod(1 + gross)
        # A: 1.1*1.1*1.0 = 1.21 ; B: 0.9*1.0*1.1 = 0.99 ; 0.5*(1.21+0.99) = 1.10
        self.assertAlmostEqual(eq, 1.10, places=12)
        np.testing.assert_allclose(net, gross)
        self.assertAlmostEqual(turn[0], 1.0)
        self.assertEqual(turn[1:].sum(), 0.0)

    def test_cost_is_turnover_times_leg(self):
        r = np.zeros((3, 2))
        wt = np.zeros((3, 2))
        wt[0] = [1.0, 0.0]
        wt[2] = [0.0, 1.0]
        rebal = np.array([True, False, True])
        net, gross, turn = R.simulate_sleeve(r, wt, rebal, 0.005)
        self.assertAlmostEqual(net[0], -0.005)          # nakit → 1.0 : devir 1
        self.assertAlmostEqual(net[2], -0.010)          # A sat + B al : devir 2
        self.assertAlmostEqual(turn[2], 2.0)

    def test_rebalance_to_same_weights_after_drift_costs_only_drift(self):
        r = np.array([[0.0, 0.0], [0.2, 0.0], [0.0, 0.0]])
        wt = np.zeros((3, 2))
        wt[0] = [0.5, 0.5]
        wt[2] = [0.5, 0.5]
        rebal = np.array([True, False, True])
        net, gross, turn = R.simulate_sleeve(r, wt, rebal, 0.01)
        # sürükleme sonrası A payı = 0.6/1.1
        a = 0.6 / 1.1
        self.assertAlmostEqual(turn[2], abs(0.5 - a) + abs(0.5 - (1 - a)))

    def test_cash_when_target_empty_and_nan_returns(self):
        r = np.array([[np.nan, np.nan], [0.1, 0.1]])
        wt = np.zeros((2, 2))
        net, gross, turn = R.simulate_sleeve(r, wt, np.array([True, True]), 0.01)
        np.testing.assert_allclose(net, 0.0)
        np.testing.assert_allclose(turn, 0.0)

    def test_partial_cash_weights_not_inflated(self):
        # %50 pozisyon, %50 nakit; pozisyon %100 yükselir → portföy +%50, sonra pay 1/1.5·... = 2/3
        r = np.array([[0.0], [1.0], [0.0]])
        wt = np.zeros((3, 1))
        wt[0] = [0.5]
        wt[2] = [0.5]
        rebal = np.array([True, False, True])
        net, gross, turn = R.simulate_sleeve(r, wt, rebal, 0.0)
        self.assertAlmostEqual(gross[1], 0.5)
        self.assertAlmostEqual(turn[2], abs(0.5 - 1.0 / 1.5))


class TestSeries(unittest.TestCase):
    def test_daily_compound(self):
        r = np.full(48, 0.001)
        d = R.daily_compound(r)
        self.assertEqual(len(d), 2)
        self.assertAlmostEqual(d[0], 1.001 ** 24 - 1)
        self.assertEqual(len(R.daily_compound(np.zeros(47))), 1)

    def test_max_drawdown(self):
        self.assertAlmostEqual(R.max_drawdown(np.array([0.1, -0.5, 0.2])), -0.5)
        self.assertEqual(R.max_drawdown(np.array([0.1, 0.1])), 0.0)
        self.assertEqual(R.max_drawdown(np.array([])), 0.0)
        # başlangıçtan düşüş de sayılır
        self.assertAlmostEqual(R.max_drawdown(np.array([-0.2, 0.1])), -0.2)

    def test_total_return(self):
        self.assertAlmostEqual(R.total_return(np.array([0.1, 0.1])), 0.21)

    def test_sharpe_and_moments(self):
        self.assertTrue(math.isnan(R.sharpe(np.array([0.1]))))
        self.assertTrue(math.isnan(R.sharpe(np.array([0.1, 0.1, 0.1]))))
        self.assertAlmostEqual(R.sharpe(np.array([1.0, 3.0])), 2.0 / math.sqrt(2.0))
        rng = np.random.default_rng(0)
        x = rng.normal(size=200_000)
        sk, ku = R.moments(x)
        self.assertAlmostEqual(sk, 0.0, delta=0.03)
        self.assertAlmostEqual(ku, 3.0, delta=0.1)
        self.assertEqual(R.moments(np.zeros(10)), (0.0, 3.0))


class TestDSR(unittest.TestCase):
    def test_single_trial_zero_sr_is_half(self):
        self.assertAlmostEqual(R.deflated_sharpe(0.0, 100, 0.0, 3.0, 1, 0.0), 0.5)

    def test_single_trial_known_value(self):
        # PSR: z = 0.1·√99 / √(1 + 0.5·0.01) , Φ(z)
        z = 0.1 * math.sqrt(99) / math.sqrt(1.005)
        from scipy.stats import norm
        self.assertAlmostEqual(R.deflated_sharpe(0.1, 100, 0.0, 3.0, 1, 0.0), float(norm.cdf(z)), places=12)

    def test_more_trials_lowers_dsr(self):
        a = R.deflated_sharpe(0.15, 90, 0.0, 3.0, 1, 0.01)
        b = R.deflated_sharpe(0.15, 90, 0.0, 3.0, 10, 0.01)
        c = R.deflated_sharpe(0.15, 90, 0.0, 3.0, 100, 0.01)
        self.assertGreater(a, b)
        self.assertGreater(b, c)

    def test_more_obs_raises_dsr_and_negative_skew_lowers(self):
        self.assertGreater(R.deflated_sharpe(0.1, 400, 0.0, 3.0, 20, 0.0001), R.deflated_sharpe(0.1, 100, 0.0, 3.0, 20, 0.0001))
        self.assertLess(R.deflated_sharpe(0.1, 100, -1.0, 3.0, 1, 0.0), R.deflated_sharpe(0.1, 100, 0.0, 3.0, 1, 0.0))

    def test_expected_max_sr_grows_with_n(self):
        self.assertEqual(R.expected_max_sr(1, 0.04), 0.0)
        v = [R.expected_max_sr(n, 0.04) for n in (2, 10, 100, 1000)]
        self.assertTrue(all(v[i] < v[i + 1] for i in range(3)))
        ref = 0.2 * ((1 - R.EULER_GAMMA) * R.norm.ppf(0.99) + R.EULER_GAMMA * R.norm.ppf(1 - 1 / (100 * math.e)))
        self.assertAlmostEqual(R.expected_max_sr(100, 0.04), ref, places=12)

    def test_min_track_record_consistent_with_psr(self):
        sr, n = 0.1, R.min_track_record(0.1, 0.0, 3.0, 0.0, 0.95)
        # tam n gözlemde PSR = güven düzeyi
        self.assertAlmostEqual(R.deflated_sharpe(sr, int(round(n)), 0.0, 3.0, 1, 0.0), 0.95, places=2)
        self.assertTrue(math.isinf(R.min_track_record(0.0, 0.0, 3.0)))
        self.assertTrue(math.isinf(R.min_track_record(0.05, 0.0, 3.0, sr0=0.1)))
        self.assertGreater(R.min_track_record(0.05, 0.0, 3.0), R.min_track_record(0.1, 0.0, 3.0))

    def test_nan_inputs(self):
        self.assertTrue(math.isnan(R.deflated_sharpe(float("nan"), 100, 0.0, 3.0, 5, 0.01)))


if __name__ == "__main__":
    unittest.main()
