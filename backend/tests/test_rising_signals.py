"""Yükseliş sinyalleri (R1) — tespit, bayatlık, histerezis, kapı paritesi.

KİLİT İLKESİ: her test, ilgili davranış geri alınırsa KIRILACAK şekilde yazıldı.
En kritik iki kilit:
  1. **Kapı paritesi** — `RISING_DIP_GAP_ATR`, MACD MONITOR'ün `DIP_APPROACH_GAP_ATR`
     ile aynı olmalı (reçete 1.47-1.67× lift bu eşikte kalibre edildi).
  2. **Tanımlayıcı öncüler AKTİVE OLMAMALI** — `approach`/`m1` kanıtta TERS yönlü
     (OOS −0.082/−0.094); tek başlarına aday ÜRETMEMELİ.
"""
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                       # noqa: E402
from app.routers import macd_monitor as _macd       # noqa: E402
from app import rising_signals as rs                # noqa: E402


def _row(strength=None, greens=(), dip=False, approach=False, m1=False,
         proximity=None, gap_atr=None, transition=False, break5=None,
         break15=None, buy_dominant=False, early_score=None):
    """Snapshot satırı kur — MACD'in yazdığı alan adlarıyla BİREBİR.

    `greens` = yeşil olacak İLK N zaman dilimi (okunabilirlik için): `greens=(5,)`.
    """
    n_green = int(greens[0]) if greens else 0
    tfs = {tf: {"green": (i < n_green)} for i, tf in enumerate(_macd.TF_LIST)}
    sigs = {"5m": {"break": break5, "state": "expand" if transition else None, "vol": False},
            "15m": {"break": break15, "state": None, "vol": False}}
    return {
        "strength": strength,
        "tier": "GUCLU" if strength else None,
        "tfs": tfs,
        "sigs": sigs,
        "cvd": {"buy_dominant": buy_dominant, "buy_ratio": 0.6 if buy_dominant else 0.4},
        "pre": {"approach": approach, "m1": m1, "dip": dip},
        "pre_any": bool(approach or m1 or dip),
        "pre_detail": {"proximity": proximity, "gap_atr": gap_atr, "transition": transition,
                       "squeeze_now": False, "expand_now": bool(transition),
                       "dip_hist": -0.02 if dip else None, "dip_delta": 0.005 if dip else None},
        "early_score": early_score if early_score is not None else (25 if dip else 0),
    }


def _snapshot(rows: dict, age_sec: float = 1.0):
    return {"universe": list(rows), "symbols": rows,
            "generated_at": time.time() - age_sec}


class RisingStateResetMixin:
    def setUp(self):
        rs.reset_state_for_tests()
        self.addCleanup(rs.reset_state_for_tests)


class GateParityTests(unittest.TestCase):
    """Reçete eşiği tek kaynaktan: MACD MONITOR ile aynı olmalı."""

    def test_dip_gap_atr_matches_macd_monitor(self):
        self.assertAlmostEqual(float(_macd.DIP_APPROACH_GAP_ATR),
                               float(config.RISING_DIP_GAP_ATR), places=9,
                               msg="yakınlık kapısı MACD ile ayrıştı → reçete geçersiz")

    def test_thresholds_match_previous_client_side_values(self):
        """Eski istemci sabitleri (9.8 / 5) korunmalı — davranış sessizce kaymasın."""
        self.assertAlmostEqual(9.8, float(config.RISING_MIN_STRENGTH), places=9)
        self.assertEqual(5, int(config.RISING_MIN_GREEN))


class StalenessTests(RisingStateResetMixin, unittest.TestCase):
    def test_stale_snapshot_yields_no_candidates(self):
        rows = {"AAA": _row(strength=10.0, greens=(6,), dip=True)}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(rows, age_sec=10_000)):
            self.assertTrue(rs.rising_is_stale())
            self.assertEqual([], rs.detect_rising_candidates())

    def test_empty_snapshot_yields_no_candidates(self):
        with patch.object(_macd, "_SNAPSHOT", {"universe": [], "symbols": {}, "generated_at": 0.0}):
            self.assertTrue(rs.rising_is_stale())
            self.assertEqual([], rs.detect_rising_candidates())

    def test_fresh_snapshot_is_not_stale(self):
        rows = {"AAA": _row(dip=True)}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(rows, age_sec=1.0)):
            self.assertFalse(rs.rising_is_stale())
            self.assertEqual(1, len(rs.detect_rising_candidates()))

    def test_disabled_flag_yields_nothing(self):
        rows = {"AAA": _row(dip=True)}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(rows)), \
             patch.object(config, "RISING_SIGNALS_ENABLED", False):
            self.assertEqual([], rs.detect_rising_candidates())


class DetectionTests(RisingStateResetMixin, unittest.TestCase):
    def test_early_class_from_combined_gate(self):
        rows = {"AAA": _row(dip=True, proximity=0.9, gap_atr=0.4, early_score=72)}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(rows)):
            found = rs.detect_rising_candidates()
        self.assertEqual(1, len(found))
        self.assertEqual(rs.KIND_EARLY, found[0]["kind"])
        self.assertEqual(72.0, found[0]["score"])
        self.assertTrue(found[0]["signals"]["dip"])

    def test_descriptive_precursors_alone_do_not_qualify(self):
        """`approach`/`m1` TERS yönlü (OOS −0.082/−0.094) → tek başına ADAY OLMAZ."""
        rows = {"AAA": _row(approach=True, m1=True, strength=1.0, greens=(1,))}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(rows)):
            self.assertEqual([], rs.detect_rising_candidates(),
                             "tanımlayıcı öncü aktive edilmiş (kanıtta ters yönlü)")

    def test_strength_class_requires_both_thresholds(self):
        """GÜÇ yüksek ama yeşil yetersiz → aday yok; ikisi de tamam → aday var."""
        weak_green = {"AAA": _row(strength=10.0, greens=(4,))}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(weak_green)):
            self.assertEqual([], rs.detect_rising_candidates())

        ok = {"AAA": _row(strength=10.0, greens=(5,))}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(ok)):
            found = rs.detect_rising_candidates()
        self.assertEqual(1, len(found))
        self.assertEqual(rs.KIND_STRENGTH, found[0]["kind"])
        self.assertEqual(100.0, found[0]["score"], "strength 0-10 → 0-100 ölçeklenmeli")

    def test_early_preferred_over_strength(self):
        rows = {"AAA": _row(dip=True, strength=10.0, greens=(6,))}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(rows)):
            found = rs.detect_rising_candidates()
        self.assertEqual(1, len(found))
        self.assertEqual(rs.KIND_EARLY, found[0]["kind"],
                         "iki koşul da sağlanınca daha spesifik ERKEN seçilmeli")

    def test_sorted_by_score_desc(self):
        rows = {"AAA": _row(dip=True, early_score=30), "BBB": _row(dip=True, early_score=90)}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(rows)):
            found = rs.detect_rising_candidates()
        self.assertEqual(["BBB", "AAA"], [c["symbol"] for c in found])

    def test_green_count_ignores_missing_and_false_cells(self):
        row = {"tfs": {"5m": {"green": True}, "15m": {"green": False}, "1m": None}}
        self.assertEqual(1, rs.green_count(row))
        self.assertEqual(0, rs.green_count({}))

    def test_summary_payload_has_thresholds_and_count(self):
        rows = {"AAA": _row(dip=True, early_score=50)}
        with patch.object(_macd, "_SNAPSHOT", _snapshot(rows)):
            payload = rs.rising_summary_payload()
        self.assertEqual(1, payload["count"])
        self.assertAlmostEqual(float(config.RISING_DIP_GAP_ATR), payload["thresholds"]["dip_gap_atr"])


class HysteresisTests(RisingStateResetMixin, unittest.TestCase):
    def test_edge_trigger_semantics(self):
        # 0 → 1: ateşle
        self.assertTrue(rs.rising_edge_trigger((), ("dip",)))
        # aynı küme sürüyor: ATEŞLEME
        self.assertFalse(rs.rising_edge_trigger(("dip",), ("dip",)))
        # kümeye YENİ üye: ateşle
        self.assertTrue(rs.rising_edge_trigger(("dip",), ("dip", "transition")))
        # küme küçüldü: yeni bilgi değil
        self.assertFalse(rs.rising_edge_trigger(("dip", "transition"), ("dip",)))
        # ilk gözlem: SESSİZ ARM
        self.assertFalse(rs.rising_edge_trigger(None, ("dip",), first_observation=True))
        # öncü yok
        self.assertFalse(rs.rising_edge_trigger(("dip",), ()))

    def test_signal_key_order_independent(self):
        a = {"kind": rs.KIND_EARLY, "signals": {"dip": True, "transition": True, "buy_dominant": True}}
        b = {"kind": rs.KIND_EARLY, "signals": {"buy_dominant": True, "dip": True, "transition": True}}
        self.assertEqual(rs.signal_key(a), rs.signal_key(b))

    def test_cooldown_blocks_then_allows(self):
        cand = {"symbol": "AAA", "kind": rs.KIND_EARLY, "signals": {"dip": True}}
        now = 1_000.0
        with patch.object(_macd, "_SNAPSHOT", _snapshot({"AAA": _row(dip=True)})):
            self.assertFalse(rs.should_fire(cand, now), "ilk gözlem sessiz arm")
            rs.mark_fired(cand, now)
            self.assertTrue(rs.cooldown_active("AAA", now + 10))
            self.assertFalse(rs.should_fire(cand, now + 10), "cooldown içinde ateşlememeli")
            self.assertFalse(rs.should_fire(cand, now + config.RISING_COOLDOWN_SEC + 1),
                             "aynı öncü kümesi sürüyorsa cooldown sonrası da ateşlemez")
            # kümeye yeni sinyal → yeni bilgi, cooldown sonrası ateşler
            fresh = {"symbol": "AAA", "kind": rs.KIND_EARLY,
                     "signals": {"dip": True, "transition": True}}
            self.assertTrue(rs.should_fire(fresh, now + config.RISING_COOLDOWN_SEC + 1))

    def test_second_observation_with_new_precursor_fires(self):
        first = {"symbol": "AAA", "kind": rs.KIND_EARLY, "signals": {"dip": True}}
        now = 5_000.0
        rs.mark_fired(first, now)
        # cooldown'ı aş, YENİ öncü ekle
        later = now + float(config.RISING_COOLDOWN_SEC) + 1
        grown = {"symbol": "AAA", "kind": rs.KIND_EARLY,
                 "signals": {"dip": True, "buy_dominant": True}}
        self.assertTrue(rs.should_fire(grown, later))


if __name__ == "__main__":
    unittest.main()
