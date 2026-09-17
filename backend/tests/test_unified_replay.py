"""BİRLEŞİK SİNYAL REPLAY akışı kilitleri (2026-09-17).

`build_unified_events`: canlı füzyon motorunun (velocity + MACD jump/early +
rising) journal üzerindeki karşılığı. Kilitlenen davranış:
  1. Aynı sembolün farklı kaynak olayları pencere içinde TEK kümeye iner.
  2. Füzyon skoru CANLI motorun `fusion_score` fonksiyonudur (parite şartı —
     replay başka formülü ölçerse sonuç ölüdür).
  3. Zaman = kümenin İLK olayı (önceden-bildirim semantiği).
  4. Fiyat/hedef önceliği velocity > rising > macd.
  5. Farklı semboller/ayaklar asla birbirine karışmaz.
"""
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import maintenance                        # noqa: E402
from app.config import config                              # noqa: E402

script = maintenance._load_replay_module()


def _velocity(sym="TLMTRY", ts=1000.0, price=0.0702, target=4.0, score=11021.0):
    return {"symbol": sym, "velocity_score": score, "created_at": ts,
            "price": price, "target_pct": target, "horizon_minutes": 5.0,
            "candidate_id": f"vel-5dk-%{target}-{sym}"}


def _rising(sym="TLMTRY", ts=1300.0, price=0.0764, target=2.0, score=55.0):
    return {"symbol": sym, "score": score, "created_at": ts,
            "price": price, "target_pct": target, "kind": "yukselis"}


def _macd(sym="TLMTRY", ts=1100.0, kind="jump", score=72, price=0.0710):
    return {"symbol": sym, "kind": kind, "score": score, "price": price,
            "created_at": ts, "early_score": score if kind == "early" else None}


class BuildUnifiedEventsTests(unittest.TestCase):
    def test_multi_source_cluster_fuses_into_one_event(self):
        velocity_row = dict(_velocity())
        velocity_row["score"] = 74.0   # replay, journal satırına panel skoru yazar
        out = script.build_unified_events(
            [velocity_row],
            [_rising()],
            [_macd()],
            confluence_window_sec=1800)
        self.assertEqual(1, len(out))
        event = out[0]
        self.assertTrue(event["confluence"])
        self.assertIn("velocity", event["sources"])
        self.assertIn("rising", event["sources"])
        self.assertIn("jump", event["sources"])
        # Zaman: İLK olay (velocity t=1000) — sonraki teyitler zamanı KAYDIRMAZ.
        self.assertEqual(1000.0, event["detected_at"])
        # Fiyat: İLK olayın fiyatı (velocity bu kümede en erken) — bildirim anı.
        self.assertAlmostEqual(0.0702, event["price"], places=6)
        # Hedef: velocity hedefi (canlı bildirim velocity hedefini taşır).
        self.assertEqual(4.0, event["target_pct"])

    def test_price_is_first_event_not_velocity_priority(self):
        """MACD tetiklemesi velocity'den ÖNCE geldiyse fiyat MACD'ninkidir.

        Canlı fast-path bildirimi İLK tetik anındaki ticker fiyatıyla gider;
        sonradan gelen velocity fiyatı bildirim anında henüz YOKTU. Eski
        velocity-öncelikli seçim t=900 girişini t=1200 fiyatıyla ölçüyordu.
        """
        out = script.build_unified_events(
            [_velocity(ts=1200.0, price=0.0702)],
            [],
            [_macd(kind="early", score=70, price=0.0710, ts=900.0)],
            confluence_window_sec=1800)
        self.assertEqual(1, len(out))
        self.assertEqual(900.0, out[0]["detected_at"])
        self.assertAlmostEqual(0.0710, out[0]["price"], places=6)
        # Hedef yine velocity'den (bildirimin taşıdığı hedef).
        self.assertEqual(4.0, out[0]["target_pct"])

    def test_events_outside_window_form_separate_clusters(self):
        out = script.build_unified_events(
            [_velocity(ts=1000.0)], [_rising(ts=1000.0 + 3600)],
            [], confluence_window_sec=1800)
        self.assertEqual(2, len(out))
        self.assertFalse(out[0]["confluence"])
        self.assertFalse(out[1]["confluence"])

    def test_early_alerts_use_early_score_component(self):
        macd_row = _macd(kind="early", score=None)
        macd_row["early_score"] = 68
        out = script.build_unified_events([], [], [macd_row],
                                          confluence_window_sec=1800)
        self.assertEqual(1, len(out))
        self.assertIn("early", out[0]["sources"])

    def test_same_source_duplicate_takes_best_score(self):
        macd_rows = [_macd(kind="jump", score=50, ts=1000.0),
                     _macd(kind="jump", score=80, ts=1100.0)]
        out = script.build_unified_events([], [], macd_rows,
                                          confluence_window_sec=1800)
        self.assertEqual(1, len(out))
        # Aynı kaynaktan küme içi en iyi skor geçerli (teyit skoru düşürmesin).
        best_single = 80.0
        self.assertGreaterEqual(out[0]["score"], best_single)

    def test_distinct_symbols_never_merge(self):
        out = script.build_unified_events(
            [_velocity(sym="AAATRY")], [_rising(sym="BBBTRY")],
            [_macd(sym="CCCTRY")], confluence_window_sec=1800)
        self.assertEqual(3, len(out))
        self.assertEqual({"AAATRY", "BBBTRY", "CCCTRY"},
                         {e["symbol"] for e in out})

    def test_fusion_score_matches_live_engine(self):
        """PARİTE: replay skoru canlı `fusion_score` çıktısıyla BİREBİR aynı."""
        from app.unified_signals import fusion_score
        from app.routers.velocity import _panel_score
        # Journal satırı gibi: ham `velocity_score` + replay'in yazdığı panel `score`.
        panel = _panel_score(1400.0)
        velocity_row = _velocity(score=1400.0)
        velocity_row["score"] = panel
        out = script.build_unified_events(
            [velocity_row], [_rising(score=60.0)],
            [_macd(kind="jump", score=72.0)], confluence_window_sec=1800)
        expected, _ = fusion_score({"velocity": panel, "rising": 60.0, "jump": 72.0})
        self.assertAlmostEqual(expected, out[0]["score"], places=1)

    def test_velocity_price_falls_back_to_rising_then_macd(self):
        no_price = _velocity(price=None)
        out = script.build_unified_events([no_price], [_rising(price=0.0764)],
                                          [], confluence_window_sec=1800)
        self.assertAlmostEqual(0.0764, out[0]["price"], places=6)
        macd_only = script.build_unified_events([], [],
                                                [_macd(price=0.0710)],
                                                confluence_window_sec=1800)
        self.assertAlmostEqual(0.0710, macd_only[0]["price"], places=6)

    def test_target_defaults_to_config_when_missing(self):
        macd_row = _macd()
        macd_row["target_pct"] = None
        out = script.build_unified_events([], [], [macd_row],
                                          confluence_window_sec=1800)
        self.assertEqual(float(config.RISING_TARGET_PCT or 2.0),
                         out[0]["target_pct"])


if __name__ == "__main__":
    unittest.main()
