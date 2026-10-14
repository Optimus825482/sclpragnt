"""Velocity ML geri doldurma (backfill) ve yardıfonksiyon testleri."""
from __future__ import annotations

import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers.velocity import (_velocity_ml_feature_dict,
                                  _velocity_horizon_from_candidate_id)
from app import database


def _synth_candles(n: int, price: float = 50.0, step: float = 0.01):
    """Binance TR klines formatı: [open_t,o,h,l,c,v,...]."""
    rows = []
    p = price
    for i in range(n):
        o = p
        c = p + step
        h = c + 0.005
        l = o - 0.005
        rows.append([float(i * 60_000), o, h, l, c, 1000.0])
        p = c
    return rows


class VelocityMlBackfillTests(unittest.IsolatedAsyncioTestCase):
    def test_horizon_from_candidate_id(self):
        self.assertEqual(_velocity_horizon_from_candidate_id("vel-5dk-%2-1700000000-ABC"), 5)
        self.assertEqual(_velocity_horizon_from_candidate_id("vel-15dk-%3-1700000000-ABC"), 15)
        self.assertEqual(_velocity_horizon_from_candidate_id("garbage"), 5)
        self.assertEqual(_velocity_horizon_from_candidate_id(""), 5)

    def test_ml_feature_dict_shape_and_keys(self):
        candles = _synth_candles(60)
        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        vols = [c[5] for c in candles]
        f = _velocity_ml_feature_dict(closes, highs, lows, vols)
        for k in ("ret3_pct", "atr_pct", "bb_width_pct", "rsi", "mfi",
                  "linreg_slope10_pct", "aroon_up", "aroon_down"):
            self.assertIn(k, f)
        self.assertIsNotNone(f["atr_pct"])
        self.assertGreater(f["atr_pct"], 0)
        self.assertIsNotNone(f["rsi"])
        # ret3_pct kesir (scan_one ile aynı sözleşme), küçük mutlak değer
        self.assertIsNotNone(f["ret3_pct"])
        self.assertLess(abs(f["ret3_pct"]), 1)

    def test_ml_feature_dict_too_short(self):
        candles = _synth_candles(10)
        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        vols = [c[5] for c in candles]
        f = _velocity_ml_feature_dict(closes, highs, lows, vols)
        self.assertIsInstance(f, dict)

    async def test_missing_ml_and_set_ml_roundtrip(self):
        cid = f"vel-5dk-%2-{int(time.time())}-mlfixtest"
        rows = [{
            "candidate_id": cid, "created_at": time.time(), "symbol": "TESTUSDT",
            "price": 1.0, "target_pct": 2.0, "atr_pct": 0.5, "volume_ratio": 0.0,
            "ret3_pct": 1.5, "velocity_score": 1.2, "passes": True, "rank": 1,
            "ml_target_pct": None, "ml_hit_probability": None,
        }]
        await database.save_velocity_candidates(rows)
        try:
            # Sorgu en eski satırları getirdiği için yeni satır LIMIT'in
            # dışında kalabilir; doğrudan candidate_id ile doğrula.
            missing = await database.get_velocity_candidates_missing_ml(limit=200000)
            self.assertTrue(any(r["candidate_id"] == cid for r in missing))
            written = await database.set_velocity_candidates_ml([
                {"candidate_id": cid, "ml_target_pct": 2.4, "ml_hit_probability": 0.65}
            ])
            self.assertEqual(written, 1)
            # İkinci yazım idempotent: hâlâ boş olan yoksa 0 döner.
            written2 = await database.set_velocity_candidates_ml([
                {"candidate_id": cid, "ml_target_pct": 9.9, "ml_hit_probability": 0.99}
            ])
            self.assertEqual(written2, 0)
        finally:
            await database.delete_velocity_candidates([cid])
