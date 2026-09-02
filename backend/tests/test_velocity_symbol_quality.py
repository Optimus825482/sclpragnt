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
    async def test_journal_quality_gate_removed_zero_touch_symbol_opens(self):
        """Sembol kalite filtresi kaldırıldı (2026-09-03): 0 dokunuş + düşük MFE
        artık açılışı engellemez; akış sonraki kapıya (açık pozisyon) ilerler."""
        from app.routers import velocity

        symbol = "TESTQTRY"

        async def fake_trades(*a, **k):
            return []

        # Filtre kapısı artık yok: yalnızca min-skor ve desen kapısından sonra
        # açık-pozisyon kapısına gelir. Pozisyon yoksa likidite/bakiye kapısına
        # gider — onu da mock'layıp PAPER_OPENED'a ulaşmasını beklemek yerine
        # açık-pozisyon kapısını simüle edip filtre sebebiyle SKIPPED dönmediğini
        # doğruluyoruz.
        with patch.object(velocity.database, "get_trades", side_effect=fake_trades), \
             patch.object(velocity.analyzer, "positions", {symbol: {"strategy": "CHAT_PREDICTION"}}):
            result = await velocity._open_velocity_position({
                "symbol": symbol, "price": 1.0, "velocity_score": 20.0,
                "mode": "trend_devam", "m5_pattern_ok": True,
                "atr_pct": 0.5, "m5_pattern": None,
            })
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "acik_pozisyon_var")

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

    async def test_min_score_gate_skips_low_score_candidates(self):
        """Skor eşiği altındaki adaylar tüm kapılardan önce SKIPPED dönmeli."""
        from app.routers import velocity
        from app.config import config

        old_min = config.VELOCITY_AUTO_MIN_SCORE
        config.VELOCITY_AUTO_MIN_SCORE = 10.0
        try:
            result = await velocity._open_velocity_position({
                "symbol": "LOWSCTRY", "price": 1.0, "velocity_score": 5.0,
                "mode": "trend_devam", "m5_pattern_ok": True, "atr_pct": 0.5,
            })
            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("skor_esigi_alti", result["reason"])
        finally:
            config.VELOCITY_AUTO_MIN_SCORE = old_min

    async def test_quality_multiplier_steps(self):
        from app.routers.velocity import _quality_multiplier

        self.assertEqual(_quality_multiplier(None), 1.0)   # veri yok → nötr
        self.assertEqual(_quality_multiplier(0.30), 1.3)   # iyi sembol
        self.assertEqual(_quality_multiplier(0.15), 1.1)
        self.assertEqual(_quality_multiplier(0.08), 0.7)
        self.assertEqual(_quality_multiplier(0.0), 0.4)    # hiç tutmayan sembol

    async def test_journal_touch_rates_uses_min_sample(self):
        from app.routers import velocity
        from app.config import config

        stats = [
            _stats_row("GOODTRY", 10, 5, 3.0),   # %50 → dahil
            _stats_row("THINTRY", 2, 2, 3.0),    # örneklem altı → hariç
        ]
        old_min = config.VELOCITY_SYMBOL_QUALITY_JOURNAL_MIN_EVALUATED
        config.VELOCITY_SYMBOL_QUALITY_JOURNAL_MIN_EVALUATED = 3
        try:
            with patch.object(velocity.database, "get_velocity_symbol_quality_stats",
                              return_value=stats):
                rates = await velocity._journal_touch_rates()
            self.assertEqual(rates, {"GOODTRY": 0.5})

            # Sıralama entegrasyonu: düşük skorlu iyi sembol, yüksek skorlu
            # veri-siz sembolü geçemez ama kalitesi onu öne taşır.
            base = velocity._rank_score({"symbol": "GOODTRY", "velocity_score": 10.0}, rates)
            neutral = velocity._rank_score({"symbol": "NEWTRY", "velocity_score": 10.0}, rates)
            self.assertGreater(base, neutral)
        finally:
            config.VELOCITY_SYMBOL_QUALITY_JOURNAL_MIN_EVALUATED = old_min


if __name__ == "__main__":
    unittest.main()
