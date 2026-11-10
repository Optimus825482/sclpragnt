"""Chat fast_rise_brief bloğu (2026-11-10, v2).

Kilitlenen davranışlar (bkz. docs/CHAT_MODEL_HIZLI_YUKSELIS_VERI_ARASTIRMASI_2026-11-10.md):
  1. `get_cached_radar_candidates` salt-okunur kopya döner; çağıran state'i bozamaz.
  2. Radar son turun geçen adayları upside_rank'a göre sıralanır; açık pozisyon
     adayı kısa listeye girmez.
  3. Hiç kaynak yoksa blok yine döner (`data_ready=False` + not) — chat düşmez.
  4. Keşif katmanı (early_discovery) ayrı alandır; velocity listesine karışmaz.
  5. Sıfır REST: brief yalnız bellek-içi kaynaklardan kurulur (rest_calls=0).
  6. v2: journal touch_rate TTL'li önbellekten gelir ve kalite çarpanıyla
     sıralamayı değiştirir (DB tam-tablo agregasyonu istek başına çalışmaz).
  7. v2: lead-lag aktif sinyalleri ayrı katman olarak eklenir.
  8. v2: `POST /api/llm/fast-risers` adayları `fast-risers-v1` etiketiyle
     journal'a yazar (chat lane A/B'sini kirletmez).
"""
import asyncio
import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                     # noqa: E402
from app.routers import global_radar, llm_chat, monitoring  # noqa: E402


def _cand(sym: str, vel: float, target: float = 2.0, horizon: int = 5) -> dict:
    return {"symbol": sym, "price": 1.0, "velocity_score": vel, "target_pct": target,
            "horizon_minutes": horizon, "mode": "trend_devam", "ret3_pct": 1.0,
            "ret5_pct": 1.5, "atr_pct": 0.8, "bb_width_pct": 3.0, "rsi": 63.0,
            "mfi": 70.0, "linreg_slope10_pct": 0.3, "volume_ratio": 2.2,
            "spread_pct": 0.1, "pool_source": "test", "passes": True}


class FastRiseBriefTests(unittest.TestCase):
    def setUp(self):
        self._old_state = dict(monitoring._monitoring_state)
        self._old_touch = dict(llm_chat._fast_rise_touch_cache)
        # DB'ye dokunma: cache taze → TTL dolmadıkça _journal_touch_rates çalışmaz.
        llm_chat._fast_rise_touch_cache.update({"at": time.time(), "rates": {}})

    def tearDown(self):
        monitoring._monitoring_state.clear()
        monitoring._monitoring_state.update(self._old_state)
        llm_chat._fast_rise_touch_cache.clear()
        llm_chat._fast_rise_touch_cache.update(self._old_touch)
        llm_chat.analyzer.positions.pop("OPENTRY", None)

    def test_flag_default_on(self):
        self.assertTrue(config.CHAT_FAST_RISE_BRIEF)
        self.assertGreaterEqual(config.CHAT_FAST_RISE_BRIEF_LIMIT, 1)
        self.assertGreaterEqual(config.CHAT_FAST_RISE_BRIEF_TOUCH_TTL_SEC, 30)

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

    def test_touch_rate_cache_drives_quality_ranking(self):
        # Ham upside'ı yüksek düşük-dokunuşlu sembol (×0.4) kalite çarpanıyla
        # geçilir: HIGHTRY dokunuşu %25 (×1.3) → öne çıkar (v2 davranışı).
        monitoring._monitoring_state["last_scan_at"] = time.time()
        monitoring._monitoring_state["last_candidates"] = [_cand("LOWTRY", 30.0), _cand("HIGHTRY", 10.0)]
        llm_chat._fast_rise_touch_cache.update(
            {"at": time.time(), "rates": {"LOWTRY": 0.03, "HIGHTRY": 0.25}})
        brief = asyncio.run(llm_chat._build_fast_rise_brief())
        rows = brief["velocity_top"]
        self.assertEqual(rows[0]["symbol"], "HIGHTRY")
        self.assertAlmostEqual(rows[0]["touch_rate"], 0.25)
        self.assertAlmostEqual(rows[1]["touch_rate"], 0.03)

    def test_brief_includes_leadlag_layer(self):
        monitoring._monitoring_state["last_scan_at"] = None
        monitoring._monitoring_state["last_candidates"] = []
        ll_sig = [{"ts": time.time(), "symbol": "GLBTRY", "residual_pct": 0.8,
                   "panel_score": 72.0, "horizon_minutes": 15, "target_pct": 2.0,
                   "age_sec": 12.0}]
        with patch("app.early_discovery.top_candidates", return_value=[]), \
             patch("app.routers.global_radar.get_recent_leadlag_signals", return_value=ll_sig):
            brief = asyncio.run(llm_chat._build_fast_rise_brief())
        self.assertEqual(brief["lead_lag_active"], ll_sig)

    def test_global_radar_recent_leadlag_accessor_filters_age(self):
        old = list(global_radar._RECENT_LEADLAG)
        try:
            global_radar._RECENT_LEADLAG.clear()
            global_radar._RECENT_LEADLAG.extend([
                {"ts": time.time(), "symbol": "GLBTRY", "residual_pct": 0.8,
                 "panel_score": 72.0, "horizon_minutes": 15, "target_pct": 2.0},
                {"ts": time.time() - 3600, "symbol": "OLDTRY", "residual_pct": 0.5,
                 "panel_score": 60.0, "horizon_minutes": 15, "target_pct": 2.0},
            ])
            out = global_radar.get_recent_leadlag_signals(max_age_sec=900)
            self.assertEqual([r["symbol"] for r in out], ["GLBTRY"])
            self.assertGreaterEqual(out[0]["age_sec"], 0.0)
        finally:
            global_radar._RECENT_LEADLAG.clear()
            global_radar._RECENT_LEADLAG.extend(old)

    def test_fast_risers_endpoint_journals_with_prompt_version(self):
        brief = {"generated_at": time.time(), "radar_age_sec": 1.0, "risk_off": False,
                 "velocity_top": [{"symbol": "HIGHTRY", "price": 10.0, "upside_rank": 5.2,
                                   "velocity_score": 10.0, "horizon_minutes": 5,
                                   "target_pct": 2.0, "atr_pct": 0.8}],
                 "discovery_top": []}
        saved: list[dict] = []

        async def _save(rows):
            saved.extend(rows)
            return len(rows)

        with patch.object(llm_chat, "_build_fast_rise_brief", AsyncMock(return_value=brief)), \
             patch.object(llm_chat.llm_analysis, "analyze",
                          AsyncMock(return_value={"enabled": True, "status": "ok",
                                                  "text": "Sembol: HIGHTRY\nAnlık fiyat: ₺10\n"
                                                          "Tahmini artış: %1.5\nTahmini süre ve hedef fiyat: 5 dk",
                                                  "model": "test-model"})), \
             patch.object(llm_chat.database, "save_llm_forecasts", _save):
            out = asyncio.run(llm_chat.llm_fast_risers())
        self.assertTrue(out["enabled"])
        self.assertTrue(out["paper_only"])
        self.assertEqual(out["prompt_version"], "fast-risers-v1")
        self.assertEqual(out["journal_saved"], 1)
        self.assertEqual(saved[0]["prompt_version"], "fast-risers-v1")
        self.assertEqual(saved[0]["symbol"], "HIGHTRY")
        self.assertEqual(saved[0]["direction"], "up")
        self.assertGreater(saved[0]["entry_price"], 0)
        self.assertIn("min_move_pct", saved[0])
        self.assertIn("snapshot_hash", saved[0])

    def test_fast_risers_endpoint_without_candidates(self):
        empty = {"generated_at": time.time(), "data_ready": False}
        with patch.object(llm_chat, "_build_fast_rise_brief", AsyncMock(return_value=empty)):
            out = asyncio.run(llm_chat.llm_fast_risers())
        self.assertFalse(out["enabled"])
        self.assertEqual(out["status"], "no_candidates")


if __name__ == "__main__":
    unittest.main()
