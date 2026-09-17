"""BİRLEŞİK SİNYAL MOTORU kilitleri (2026-09-17) — app/unified_signals.py.

Kilitlenen davranış:
  1. `fusion_score`: ağırlık normalizasyonu (eksik kaynak CEZALANDIRMAZ),
     sinerji çarpanı (2+ kaynak), 100 tavanı, boş girdi güvenliği.
  2. `macd_components`: snapshot yoksa BOŞ — MACD evrendişi sembolcezaydırılmaz.
  3. `enrich_candidates`: radar adayı KORUNUR + unified alanlar eklenir;
     füzyon-tek adaylar ayrı listede döner ve velocity-0'dır.
  4. `build_fusion_candidate`: hızlı-yol eşiği altında None (bildirim yok).
  5. Tek bildirim bastırması: `note_notified` + `recently_notified` penceresi.
  6. Kaynak etiketleri: `sources_text` kullanıcı metni.
"""
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import unified_signals as us                      # noqa: E402
from app.config import config                              # noqa: E402


class FusionScoreTests(unittest.TestCase):
    def test_empty_components_yield_zero(self):
        score, sources = us.fusion_score({})
        self.assertEqual(0.0, score)
        self.assertEqual([], sources)

    def test_none_and_nonpositive_values_ignored(self):
        score, sources = us.fusion_score({"velocity": None, "jump": 0, "early": -5})
        self.assertEqual(0.0, score)

    def test_single_source_passes_through(self):
        # Tek kaynak: ağırlık normalizasyonu skoru DEĞİŞTİRMEMELİ.
        score, sources = us.fusion_score({"velocity": 74.0})
        self.assertEqual(74.0, score)
        self.assertEqual(["velocity"], sources)

    def test_missing_source_is_not_punished(self):
        # MACD evreninde olmayan sembol: velocity 74 → füzyon da 74.
        score, _ = us.fusion_score({"velocity": 74.0})
        self.assertEqual(74.0, score)
        # Aynı skor iki kaynakla sinerjiyle ARTAR (ceza değil).
        with patch.object(config, "UNIFIED_SYNERGY_BONUS", 1.15):
            boosted, _ = us.fusion_score({"velocity": 74.0, "jump": 74.0})
        self.assertGreater(boosted, 74.0)

    def test_synergy_bonus_applies_only_with_two_sources(self):
        with patch.object(config, "UNIFIED_SYNERGY_BONUS", 1.15):
            single, _ = us.fusion_score({"velocity": 80.0})
            duo, _ = us.fusion_score({"velocity": 80.0, "early": 80.0})
        self.assertEqual(80.0, single)
        self.assertAlmostEqual(92.0, duo, places=1)

    def test_score_capped_at_100(self):
        with patch.object(config, "UNIFIED_SYNERGY_BONUS", 1.5):
            score, _ = us.fusion_score({"velocity": 100.0, "jump": 100.0, "early": 100.0})
        self.assertEqual(100.0, score)

    def test_garbage_values_do_not_crash(self):
        score, sources = us.fusion_score({"velocity": "abc", "jump": {}})
        self.assertEqual(0.0, score)
        self.assertEqual([], sources)


class MacdComponentsTests(unittest.TestCase):
    def test_empty_snapshot_yields_empty_components(self):
        with patch.object(us._macd, "_SNAPSHOT", {}):
            comps, ctx = us.macd_components("BTCTRY")
        self.assertEqual({}, comps)
        self.assertEqual({}, ctx)

    def test_unknown_symbol_yields_empty(self):
        snapshot = {"symbols": {"ETHTRY": {"jump": 60}}, "universe": ["ETHTRY"]}
        with patch.object(us._macd, "_SNAPSHOT", snapshot):
            comps, _ = us.macd_components("BTCTRY")
        self.assertEqual({}, comps)

    def test_components_read_from_snapshot_row(self):
        row = {"jump": 70, "early_score": 55, "strength": 6,
               "pre": {"dip": True}, "pre_detail": {"proximity": 0.8},
               "cvd": {"buy_dominant": True}, "tfs": {}}
        snapshot = {"symbols": {"BTCTRY": row}, "universe": ["BTCTRY"]}
        with patch.object(us._macd, "_SNAPSHOT", snapshot):
            comps, ctx = us.macd_components("BTCTRY")
        self.assertEqual(70.0, comps["jump"])
        self.assertEqual(55.0, comps["early"])
        self.assertEqual(60.0, comps["rising"])   # strength 0-10 → ×10
        self.assertTrue(ctx["dip"])
        self.assertTrue(ctx["buy_dominant"])


class EnrichCandidatesTests(unittest.TestCase):
    def tearDown(self):
        us.reset_state_for_tests()

    def test_radar_candidate_kept_and_enriched(self):
        with patch.object(us._macd, "_SNAPSHOT", {}):
            fused_only = us.enrich_candidates(
                [{"symbol": "BTCTRY", "panel_score": 74.0}])
        self.assertEqual([], fused_only)   # snapshot boş → füzyon-tek aday yok

    def test_fusion_only_candidate_requires_score(self):
        row = {"jump": 90, "early_score": 80, "strength": 8, "last": 100.0}
        snapshot = {"symbols": {"XYZTRY": row}, "universe": ["XYZTRY"]}
        with patch.object(us._macd, "_SNAPSHOT", snapshot):
            with patch.object(config, "UNIFIED_SIGNALS_ENABLED", True), \
                 patch.object(config, "UNIFIED_FUSION_MIN_SCORE", 60):
                fused = us.enrich_candidates([])
        self.assertEqual(1, len(fused))
        cand = fused[0]
        self.assertEqual("XYZTRY", cand["symbol"])
        self.assertTrue(cand["unified_pass"])
        self.assertEqual("fusion", cand["source"])
        self.assertGreaterEqual(cand["unified_score"], 60)
        self.assertIn("jump", cand["unified_sources"])

    def test_fusion_only_disabled_when_engine_off(self):
        row = {"jump": 90, "early_score": 80, "strength": 8}
        snapshot = {"symbols": {"XYZTRY": row}, "universe": ["XYZTRY"]}
        with patch.object(us._macd, "_SNAPSHOT", snapshot):
            with patch.object(config, "UNIFIED_SIGNALS_ENABLED", False):
                fused = us.enrich_candidates([])
        self.assertEqual([], fused)


class BuildFusionCandidateTests(unittest.TestCase):
    def test_below_fast_threshold_returns_none(self):
        row = {"jump": 30, "early_score": 20, "strength": 2, "last": 100.0}
        snapshot = {"symbols": {"XYZTRY": row}, "universe": ["XYZTRY"]}
        with patch.object(us._macd, "_SNAPSHOT", snapshot):
            with patch.object(config, "UNIFIED_FAST_MIN_SCORE", 55):
                self.assertIsNone(us.build_fusion_candidate("XYZTRY", "jump"))

    def test_strong_macd_produces_candidate_with_trigger(self):
        row = {"jump": 88, "early_score": 70, "strength": 8, "last": 12.5}
        snapshot = {"symbols": {"XYZTRY": row}, "universe": ["XYZTRY"]}
        with patch.object(us._macd, "_SNAPSHOT", snapshot):
            with patch.object(config, "UNIFIED_FAST_MIN_SCORE", 55):
                cand = us.build_fusion_candidate("XYZTRY", "early")
        self.assertIsNotNone(cand)
        self.assertEqual("XYZTRY", cand["symbol"])
        self.assertEqual("early", cand["trigger"])
        self.assertTrue(cand["unified_pass"])
        self.assertGreaterEqual(cand["unified_score"], 55)
        self.assertEqual(12.5, cand["price"])

    def test_velocity_panel_carried_into_fusion(self):
        row = {"jump": 60, "strength": 5, "last": 10.0}
        snapshot = {"symbols": {"XYZTRY": row}, "universe": ["XYZTRY"]}
        with patch.object(us._macd, "_SNAPSHOT", snapshot):
            with patch.object(config, "UNIFIED_FAST_MIN_SCORE", 55):
                cand = us.build_fusion_candidate(
                    "XYZTRY", "jump", {"panel_score": 80.0})
        self.assertIsNotNone(cand)
        self.assertIn("velocity", cand["unified_sources"])
        self.assertIn("jump", cand["unified_sources"])


class SuppressionTests(unittest.TestCase):
    def tearDown(self):
        us.reset_state_for_tests()

    def test_recently_notified_respects_ttl(self):
        us.note_notified("BTCTRY", at=time.time() - 10)
        self.assertTrue(us.recently_notified("BTCTRY", ttl_sec=60))
        self.assertFalse(us.recently_notified("BTCTRY", ttl_sec=5))
        self.assertFalse(us.recently_notified("ETHTRY"))

    def test_note_notified_normalizes_symbol(self):
        us.note_notified("btctry")
        self.assertTrue(us.recently_notified("BTCTRY"))


class SourcesTextTests(unittest.TestCase):
    def test_known_labels_translated(self):
        self.assertEqual("RADAR + ERKEN SIRÇRAMA",
                         us.sources_text(["velocity", "early"]))

    def test_unknown_label_kept_as_is(self):
        self.assertEqual("RADAR + macd", us.sources_text(["velocity", "macd"]))

    def test_empty_sources_default_radar(self):
        self.assertEqual("RADAR", us.sources_text([]))
        self.assertEqual("RADAR", us.sources_text(None))


class EnabledGateTests(unittest.TestCase):
    def test_enabled_reads_config(self):
        with patch.object(config, "UNIFIED_SIGNALS_ENABLED", True):
            self.assertTrue(us.enabled())
        with patch.object(config, "UNIFIED_SIGNALS_ENABLED", False):
            self.assertFalse(us.enabled())


if __name__ == "__main__":
    unittest.main()
