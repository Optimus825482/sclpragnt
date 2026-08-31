import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _stats_row(symbol, evaluated, touched, avg_mfe):
    return {"symbol": symbol, "evaluated": evaluated, "touched": touched,
            "average_mfe_pct": avg_mfe}


class VelocitySymbolQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_journal_quality_gate_blocks_zero_touch_symbol(self):
        """0 dokunuş + düşük MFE + yeterli ölçüm → açılış SKIPPED dönmeli."""
        from app.routers import velocity
        from app.config import config

        symbol = "TESTQTRY"
        stats = [_stats_row(symbol, 4, 0, 0.79), _stats_row("0GTRY", 4, 2, 7.94)]

        async def fake_trades(*a, **k):
            return []

        old_flag = config.VELOCITY_SYMBOL_QUALITY_FILTER
        config.VELOCITY_SYMBOL_QUALITY_FILTER = True
        try:
            with patch.object(velocity.database, "get_trades", side_effect=fake_trades), \
                 patch.object(velocity.database, "get_velocity_symbol_quality_stats",
                              return_value=stats):
                result = await velocity._open_velocity_position({
                    "symbol": symbol, "price": 1.0, "velocity_score": 5.0,
                    "mode": "trend_devam", "m5_pattern_ok": True,
                    "atr_pct": 0.5, "m5_pattern": None,
                })
            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("sembol_journal_kalitesi", result["reason"])
            self.assertEqual(result["journal_quality"]["touched"], 0)
            self.assertEqual(result["journal_quality"]["evaluated"], 4)
        finally:
            config.VELOCITY_SYMBOL_QUALITY_FILTER = old_flag

    async def test_journal_quality_gate_fail_open_on_good_symbol(self):
        """Dokunuşu olan sembol journal kapısından geçmeli (SKIPPED sebebi journal olmamalı)."""
        from app.routers import velocity
        from app.config import config

        symbol = "GOODTRY"
        stats = [_stats_row(symbol, 4, 2, 7.94)]

        async def fake_trades(*a, **k):
            return []

        old_flag = config.VELOCITY_SYMBOL_QUALITY_FILTER
        config.VELOCITY_SYMBOL_QUALITY_FILTER = True
        try:
            # Journal kapısından sonraki ilk kapı: açık pozisyon. Akışı orada
            # durdurup kapının journal sebebiyle engellemediğini doğruluyoruz —
            # test ağ/DB çağrısı yapmadan kalır.
            with patch.object(velocity.database, "get_trades", side_effect=fake_trades), \
                 patch.object(velocity.database, "get_velocity_symbol_quality_stats",
                              return_value=stats), \
                 patch.object(velocity.analyzer, "positions", {symbol: {"strategy": "CHAT_PREDICTION"}}):
                result = await velocity._open_velocity_position({
                    "symbol": symbol, "price": 1.0, "velocity_score": 5.0,
                    "mode": "trend_devam", "m5_pattern_ok": True,
                    "atr_pct": 0.5, "m5_pattern": None,
                })
            self.assertEqual(result["status"], "SKIPPED")
            self.assertEqual(result["reason"], "acik_pozisyon_var")
        finally:
            config.VELOCITY_SYMBOL_QUALITY_FILTER = old_flag

    async def test_journal_quality_helper_maps_stats(self):
        from app.routers import velocity

        symbol = "MAPTRY"
        stats = [_stats_row("OTHERTRY", 3, 0, 0.2), _stats_row(symbol, 5, 1, 2.5)]

        with patch.object(velocity.database, "get_velocity_symbol_quality_stats",
                          return_value=[]):
            self.assertIsNone(await velocity._velocity_journal_quality(symbol))
        with patch.object(velocity.database, "get_velocity_symbol_quality_stats",
                          return_value=stats):
            q = await velocity._velocity_journal_quality(symbol)
            self.assertEqual(q, {"evaluated": 5, "touched": 1, "avg_mfe_pct": 2.5})


if __name__ == "__main__":
    unittest.main()
