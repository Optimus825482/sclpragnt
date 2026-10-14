"""_json_safe_positions regresyon testleri (2026-09-28).

Üretim hatası: /api/reports/overview payload'ında Infinity/NaN float
kaldığında Starlette JSONResponse (allow_nan=False) 500 döndürüyor
("Out of range float values are not JSON compliant"). Bu testler
recursive temizleyicinin tüm payload tiplerini kapsadığını doğrular.
"""
import json
import math
import unittest
from datetime import datetime

from app.api_common import _json_safe_positions


class TestJsonSafePositions(unittest.TestCase):
    def _assert_json_safe(self, payload):
        # Starlette JSONResponse.render ile birebir aynı koşul
        json.dumps(payload, allow_nan=False)

    def test_nonfinite_floats_become_none(self):
        self.assertIsNone(_json_safe_positions(float("nan")))
        self.assertIsNone(_json_safe_positions(float("inf")))
        self.assertIsNone(_json_safe_positions(float("-inf")))

    def test_finite_values_untouched(self):
        self.assertEqual(_json_safe_positions(3.14), 3.14)
        self.assertEqual(_json_safe_positions(7), 7)
        self.assertEqual(_json_safe_positions("x"), "x")
        self.assertIsNone(_json_safe_positions(None))
        self.assertTrue(_json_safe_positions(True) is True)
        # datetime str()'lenebilir ama helper dokunmaz (json encoder'ın işi)
        ts = datetime(2026, 9, 28)
        self.assertEqual(_json_safe_positions(ts), ts)

    def test_nested_payload_sanitized(self):
        payload = {
            "overall": {"net_pnl": float("nan"), "try_balance": 12.5},
            "symbols": [{"symbol": "BTCTRY", "avg_pnl": float("inf"), "count": 3}],
            "deep": {"a": [{"b": float("-inf")}]},
        }
        safe = _json_safe_positions(payload)
        self.assertIsNone(safe["overall"]["net_pnl"])
        self.assertEqual(safe["overall"]["try_balance"], 12.5)
        self.assertIsNone(safe["symbols"][0]["avg_pnl"])
        self.assertEqual(safe["symbols"][0]["symbol"], "BTCTRY")
        self.assertIsNone(safe["deep"]["a"][0]["b"])
        self._assert_json_safe(safe)
        self.assertTrue(math.isnan(payload["overall"]["net_pnl"]))  # orijinal bozulmaz

    def test_learning_bias_inf_case_reproduces_production_bug(self):
        """Soğuk learning önbelleği üretimindeki inf'li payload artık temizlenir."""
        payload = {"learning_bias": {"enabled": False, "cache_age_s": float("inf")}}
        safe = _json_safe_positions(payload)
        self.assertIsNone(safe["learning_bias"]["cache_age_s"])
        self._assert_json_safe(safe)


if __name__ == "__main__":
    unittest.main()
