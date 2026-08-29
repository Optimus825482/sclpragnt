"""Causal replay runner tests with synthetic closed-candle data (no network)."""
import unittest
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.chat_prediction_replay import ReplayRunner, _resample_1m, _candidate_score


def _synthetic_rows(start_ms: int, minutes: int, base_price: float = 100.0):
    """Deterministic 1m candles: steady 0.5/parite uptrend with tight ATR so the
    horizon return clearly clears the min_move_pct label threshold."""
    rows = []
    for index in range(minutes):
        open_time = start_ms + index * 60_000
        price = base_price + index * 0.5
        rows.append([open_time, price, price + 0.1, price - 0.1, price + 0.08, 500.0 + index])
    return rows


class ResampleTests(unittest.TestCase):
    def test_resample_1m_to_5m_buckets(self):
        rows = _synthetic_rows(0, 10)
        result = _resample_1m(rows, 5)
        self.assertEqual(len(result["closes"]), 2)
        self.assertEqual(result["highs"][0], max(float(row[2]) for row in rows[:5]))
        self.assertEqual(result["lows"][0], min(float(row[3]) for row in rows[:5]))
        self.assertEqual(result["closes"][0], float(rows[4][4]))
        self.assertEqual(result["last_closed_at_ms"], rows[5][0])

    def test_resample_factor_one_passthrough(self):
        rows = _synthetic_rows(0, 4)
        result = _resample_1m(rows, 1)
        self.assertEqual([float(value) for value in result["closes"]], [float(row[4]) for row in rows])


class CandidateScoreTests(unittest.TestCase):
    def test_bullish_snapshot_scores_positive(self):
        snapshot = {"timeframe": "5m", "trend": {"alignment": "bullish", "adx": 25},
                    "momentum": {"return_5m": 0.2, "return_15m": 0.4, "return_1h": 0.6},
                    "volume": {"volume_ratio_20": 1.4}, "liquidity": {},
                    "methodologies": {"5m": {"regime": {"name": "bull_trend"}}}}
        score, evidence, _ = _candidate_score(snapshot)
        self.assertGreater(score, 4.0)
        self.assertTrue(any("EMA" in item for item in evidence))

    def test_missing_microstructure_never_crashes(self):
        snapshot = {"timeframe": "5m", "trend": {}, "momentum": {}, "volume": {}, "liquidity": {}}
        score, _, risks = _candidate_score(snapshot)
        self.assertLessEqual(score, 0)
        self.assertTrue(risks)


class ReplayRunnerTests(unittest.TestCase):
    def _runner(self, rows, lookback_hours=6, horizons=(5, 15), step_minutes=15):
        async def fake_fetch(symbol, interval, limit, *args, **kwargs):
            return rows
        return ReplayRunner(["BTCTRY"], lookback_hours=lookback_hours, horizons=list(horizons),
                            step_minutes=step_minutes, fetch_klines=fake_fetch)

    def test_run_produces_horizon_stats(self):
        # 12 saatlik sentetik seri: pencere 6 saat, adım 15dk, ölçüm 5/15dk
        rows = _synthetic_rows(1_700_000_000_000, 60 * 12)
        runner = self._runner(rows)
        result = runner.loop_result = None
        import asyncio
        result = asyncio.run(runner.run())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["symbols_scanned"], 1)
        horizons = {row["horizon_minutes"]: row for row in result["horizons"]}
        self.assertIn(5, horizons)
        self.assertIn(15, horizons)
        self.assertGreater(horizons[5]["predictions"], 0)
        self.assertGreater(horizons[5]["evaluated"], 0)
        # Yükselen seri + sıkı ATR: sonuç asla aşağı yönlü olamaz; 'up' ya da
        # eşik altı 'range' etiketi beklenir (canlı journal ile aynı kural).
        self.assertEqual(horizons[5]["directional_accuracy"], 1.0)
        self.assertEqual(horizons[15]["directional_accuracy"], 1.0)
        self.assertEqual(horizons[5]["range_count"], 0)
        self.assertTrue(all(row["status"] in ("evaluated", "unmeasured") for row in result["picks"]))

    def test_no_data_returns_no_data_status(self):
        async def empty_fetch(symbol, interval, limit, *args, **kwargs):
            return []
        runner = ReplayRunner(["BTCTRY"], lookback_hours=6, horizons=[5], step_minutes=5, fetch_klines=empty_fetch)
        import asyncio
        result = asyncio.run(runner.run())
        self.assertEqual(result["status"], "no_data")

    def test_causal_snapshot_never_uses_future_candles(self):
        rows = _synthetic_rows(1_700_000_000_000, 60 * 12)
        runner = self._runner(rows)
        data = {"rows_1m": rows}
        decision_ms = int(rows[300][0]) + 59_999  # 300. mum kapandı
        snapshot = runner._snapshot_at("BTCTRY", data, decision_ms)
        self.assertIsNotNone(snapshot)
        last_index = snapshot["_entry_index"]
        self.assertLessEqual(int(rows[last_index][0]) + 59_999, decision_ms)
        # Snapshot fiyatı karar anındaki kapanış
        self.assertAlmostEqual(float(snapshot["price"]), float(rows[last_index][4]), places=6)
        # Ölçüm penceresi karar anından SONRA başlar
        outcome = runner._measure({"entry_price": snapshot["price"], "direction": "up", "confidence": 60,
                                   "min_move_pct": 0.1, "horizon_minutes": 5}, data, decision_ms)
        self.assertIsNotNone(outcome)
        self.assertGreater(outcome["outcome_price"], float(rows[last_index][4]) * 0.99)


if __name__ == "__main__":
    unittest.main()
