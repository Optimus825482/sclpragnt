"""Pattern replay unit tests: feature tags, mining, two-phase runner (offline)."""
import unittest
import sys
import os
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.chat_pattern_replay import rich_features, mine_patterns, tags_of_features, PatternReplayRunner
from app.chat_prediction_replay import _resample_1m


def _rows(start_ms, minutes, base=100.0, drift=0.0, spike_volume_at=None):
    rows = []
    for i in range(minutes):
        price = base + i * drift
        vol = 500.0
        if spike_volume_at is not None and i >= minutes - 5:
            vol = 1500.0
        rows.append([start_ms + i * 60_000, price, price + 0.1, price - 0.1, price + drift, vol])
    return rows


class RichFeatureTests(unittest.TestCase):
    def test_features_causal_and_numeric(self):
        rows = _rows(1_700_000_000_000, 400, drift=0.2, spike_volume_at=395)
        feat = rich_features("BTCTRY", rows, 5)
        self.assertIsNotNone(feat)
        self.assertEqual(feat["symbol"], "BTCTRY")
        self.assertGreater(feat["quote_volume_24h_est"], 0)  # kalite artışı: 0 değil artık
        self.assertIsInstance(feat["range_pos"], float)
        self.assertGreaterEqual(feat["range_pos"], 0.0)
        self.assertLessEqual(feat["range_pos"], 1.0)
        self.assertIsNotNone(feat["vol_ratio_1m20"])

    def test_insufficient_bars_returns_none(self):
        rows = _rows(0, 30)
        self.assertIsNone(rich_features("X", rows, 5))


class MiningTests(unittest.TestCase):
    def _feat(self, **kw):
        base = {"symbol": "X", "atr_pct": 0.05, "vol_ratio_1m20": 1.0, "quote_volume_24h_est": 10_000,
                "ret_5m": 0.0, "ret_15m": 0.0, "ret_1h": 0.0, "rsi_14": 50, "mfi_14": 50,
                "adx": 15, "chop_14": 70, "cmf_20": 0.0, "alignment": "mixed", "regime": "range",
                "range_pos": 0.5, "price": 100.0}
        base.update(kw)
        return base

    def test_winner_tag_lifts_out(self):
        rows = []
        # 10 kazanan: vol_spike + adx20; 40 kaybeden: bunlar yok
        for i in range(10):
            rows.append({"features": self._feat(adx=25, vol_ratio_1m20=2.0), "win": True})
        for i in range(40):
            rows.append({"features": self._feat(adx=15, vol_ratio_1m20=1.0), "win": False})
        patterns = mine_patterns(rows, min_support=4, lift_floor=1.25)
        tags = {p["tag"] for p in patterns}
        self.assertIn("vol_spike", tags)
        self.assertIn("adx20", tags)
        vol = next(p for p in patterns if p["tag"] == "vol_spike")
        self.assertGreater(vol["lift"], 2.0)

    def test_low_support_patterns_dropped(self):
        rows = [{"features": self._feat(adx=30), "win": True}]
        rows += [{"features": self._feat(adx=10), "win": False} for _ in range(20)]
        self.assertEqual(mine_patterns(rows, min_support=4), [])


class TwoPhaseRunnerTests(unittest.TestCase):
    def test_train_test_split_and_patterns_found(self):
        """Sentetik: WINTRY tüm train boyunca belirgin artar (yüksek hacim),
        FLATTRY yatay kalır. Faz A 'vol_spike/adx20' benzeri desen çıkarmalı,
        Faz B desen filtresi WINTRY'yi seçmeli."""
        start = 1_700_000_000_000
        winner = []
        for i in range(760):
            base = 100 + i * 0.3
            vol = 2000.0 if i >= 300 else 500.0
            winner.append([start + i * 60_000, base, base + 0.1, base - 0.1, base + 0.2, vol])
        flat = []
        for i in range(760):
            base = 200.0
            flat.append([start + i * 60_000, base, base + 0.05, base - 0.05, base, 400.0])

        async def fake_fetch(symbol, interval, limit, *a, **k):
            return winner if symbol == "WINTRY" else flat

        runner = PatternReplayRunner(["WINTRY", "FLATTRY"], train_hours=6, test_hours=6,
                                     horizons=[5], step_minutes=15, fetch_klines=fake_fetch,
                                     use_top_gainers=False, min_pattern_matches=1)
        result = asyncio.run(runner.run())
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["train_observations"], 0)
        self.assertGreater(result["train_risers"], 0)  # WINTRY train'de artıyor
        self.assertTrue(result["patterns"])
        self.assertGreater(result["test"][5]["picked"], 0)  # desen filtresi en az bir seçim üretti

    def test_no_data(self):
        async def empty(*a, **k):
            return []
        runner = PatternReplayRunner(["XTRY"], train_hours=6, test_hours=6, horizons=[5],
                                     step_minutes=15, fetch_klines=empty, use_top_gainers=False)
        result = asyncio.run(runner.run())
        self.assertEqual(result["status"], "no_data")


if __name__ == "__main__":
    unittest.main()
