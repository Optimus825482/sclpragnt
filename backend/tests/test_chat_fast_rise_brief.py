"""Chat fast_rise_brief bloğu (2026-11-10).

Kilitlenen davranışlar (bkz. docs/CHAT_MODEL_HIZLI_YUKSELIS_VERI_ARASTIRMASI_2026-11-10.md):
  1. `get_cached_radar_candidates` salt-okunur kopya döner; çağıran state'i bozamaz.
  2. Radar son turun geçen adayları upside_rank'a göre sıralanır; açık pozisyon
     adayı kısa listeye girmez.
  3. Hiç kaynak yoksa blok yine döner (`data_ready=False` + not) — chat düşmez.
  4. Keşif katmanı (early_discovery) ayrı alandır; velocity listesine karışmaz.
  5. Sıfır REST: brief yalnız bellek-içi kaynaklardan kurulur (rest_calls=0).
"""
import asyncio
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                     # noqa: E402
from app.routers import llm_chat, monitoring      # noqa: E402


def _cand(sym: str, vel: float, target: float = 2.0, horizon: int = 5) -> dict:
    return {"symbol": sym, "price": 1.0, "velocity_score": vel, "target_pct": target,
            "horizon_minutes": horizon, "mode": "trend_devam", "ret3_pct": 1.0,
            "ret5_pct": 1.5, "atr_pct": 0.8, "bb_width_pct": 3.0, "rsi": 63.0,
            "mfi": 70.0, "linreg_slope10_pct": 0.3, "volume_ratio": 2.2,
            "spread_pct": 0.1, "pool_source": "test", "passes": True}


class FastRiseBriefTests(unittest.TestCase):
    def setUp(self):
        self._old_state = dict(monitoring._monitoring_state)

    def tearDown(self):
        monitoring._monitoring_state.clear()
        monitoring._monitoring_state.update(self._old_state)
        llm_chat.analyzer.positions.pop("OPENTRY", None)

    def test_flag_default_on(self):
        self.assertTrue(config.CHAT_FAST_RISE_BRIEF)
        self.assertGreaterEqual(config.CHAT_FAST_RISE_BRIEF_LIMIT, 1)

    def test_cached_radar_candidates_readonly_copy(self):
        monitoring._monitoring_state["last_candidates"] = [{"symbol": "XYZTRY"}]
        monitoring._monitoring_state["risk_off"] = True
        snap = monitoring.get_cached_radar_candidates()
        self.assertEqual(snap["candidates"], [{"symbol": "XYZTRY"}])
        self.assertTrue(snap["risk_off"])
        # Kopya: dönen listeyi boşaltmak state'i bozmamalı.
        snap["candidates"].clear()
        self.assertEqual(monitoring._monitoring_state["last_candidates"], [{"symbol": "XYZTRY"}])

    def test_brief_ranks_by_upside_and_skips_open_positions(self):
        monitoring._monitoring_state["last_scan_at"] = time.time()
        monitoring._monitoring_state["last_candidates"] = [
            _cand("LOWTRY", 10.0), _cand("HIGHTRY", 30.0), _cand("OPENTRY", 99.0)]
        llm_chat.analyzer.positions["OPENTRY"] = {"paper": True}
        brief = asyncio.run(llm_chat._build_fast_rise_brief())
        self.assertEqual(brief["rest_calls"], 0)
        self.assertEqual(brief["velocity_top"][0]["symbol"], "HIGHTRY")
        self.assertGreater(brief["velocity_top"][0]["upside_rank"],
                           brief["velocity_top"][1]["upside_rank"])
        self.assertNotIn("OPENTRY", [r["symbol"] for r in brief["velocity_top"]])
        self.assertLessEqual(brief["radar_age_sec"], 1.0)
        self.assertIn("instruction", brief)
        self.assertFalse(brief["risk_off"])

    def test_brief_without_any_source_still_returns_block(self):
        monitoring._monitoring_state["last_scan_at"] = None
        monitoring._monitoring_state["last_candidates"] = []
        with patch("app.early_discovery.top_candidates", return_value=[]):
            brief = asyncio.run(llm_chat._build_fast_rise_brief())
        self.assertFalse(brief.get("data_ready", True))
        self.assertIn("note", brief)
        self.assertNotIn("velocity_top", brief)

    def test_discovery_layer_is_separate_from_velocity(self):
        monitoring._monitoring_state["last_scan_at"] = None
        monitoring._monitoring_state["last_candidates"] = []
        disc = [{"symbol": "NEWTRY", "return_1m_pct": 0.9, "return_20s_pct": 0.4,
                 "volume_burst": 3.2, "price": 2.5, "sample_age_sec": 1.2}]
        with patch("app.early_discovery.top_candidates", return_value=disc):
            brief = asyncio.run(llm_chat._build_fast_rise_brief())
        self.assertEqual(brief["discovery_top"], disc)
        # Keşif satırı velocity listesine karışmaz (kaynaklar birleşmez).
        self.assertNotIn("velocity_top", brief)
        # Keşif varken blok 'veri yok' sayılmaz.
        self.assertTrue(brief.get("data_ready", True))


if __name__ == "__main__":
    unittest.main()
