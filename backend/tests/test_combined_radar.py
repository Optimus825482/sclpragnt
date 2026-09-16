"""BİRLEŞİK RADAR (app/combined_radar.py) + replay merdiven simülasyonu kilitleri.

Kapsam:
  1. Birleşim = BİRLEŞİM + çakışma işareti; YENİ EŞİK YOK (zayıf aday bile düşürülmez).
  2. Çakışma bir KAPISI değil, METADATA'dır — pencere dışı olaylar ayrı kalır.
  3. Skor ölçekleri KARIŞTIRILMAZ (velocity panel ≠ yükseliş early_score).
  4. Tek tip zarf sözleşmesi: tag `radar-{sym}`, çift push üreten `rising-{sym}` YOK.
  5. Replay merdiveni auto_paper'ın ÜRETİM varsayılanlarıyla aynı sayıları kullanır
     (parite) ve TP/SL/breakeven/u fork-dolu çıkışlarını doğru üretir.
"""
import asyncio
import importlib.util
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import combined_radar as cr          # noqa: E402
from app.config import config                 # noqa: E402

T0_S = 1_700_000_000.0
T0_MS = int(T0_S * 1000)


def _vel(symbol="BTCTRY", score=1500.0, at=None, price=100.0, target=2.0):
    """Journal satırı biçiminde velocity olayı (created_at + velocity_score)."""
    return {"symbol": symbol, "velocity_score": score, "created_at": (T0_S if at is None else at),
            "price": price, "target_pct": target, "passes": True, "rank": 1,
            "candidate_id": f"vel-5dk-%2-{symbol}-{int(at or T0_S)}"}


def _ris(symbol="ETHTRY", score=72.0, at=None, price=50.0, target=2.0):
    """rising_alerts satırı biçiminde yükseliş olayı (created_at + score)."""
    return {"symbol": symbol, "score": score, "created_at": (T0_S if at is None else at),
            "price": price, "target_pct": target, "kind": "yukselis",
            "strength": 7.2, "green": 5, "early_score": 72.0}


def _bars(base_ms, prices):
    """Basit 1m mum dizisi: [(openTime, o, h, l, c, v), ...] — ham Binance düzeni."""
    rows = []
    for index, price in enumerate(prices):
        o = base_ms + index * 60_000
        rows.append([o, price, max(price, price * 1.001), min(price, price * 0.999), price, 10.0])
    return rows


class UnionTests(unittest.TestCase):
    """Birleşim birleşimdir: her kaynağın tek başına adayı YAYINLANMALI."""

    def test_velocity_only_symbol_is_emitted(self):
        out = cr.build_combined_candidates([_vel("BTCTRY")], [])
        self.assertEqual(1, len(out))
        self.assertEqual(["velocity"], out[0]["sources"])
        self.assertFalse(out[0]["confluence"])

    def test_rising_only_symbol_is_emitted(self):
        out = cr.build_combined_candidates([], [_ris("ETHTRY")])
        self.assertEqual(1, len(out))
        self.assertEqual(["rising"], out[0]["sources"])
        self.assertEqual("ETHTRY", out[0]["symbol"])

    def test_weak_candidate_is_not_dropped(self):
        """D1 KİLİDİ: birleşim yeni eşik İCAT ETMEZ — düşük skorlu aday bile yayınlanır.

        Budama/yayın kararı her kaynağın KENDİ kapısındadır; bu modül yalnız
        birleştirir. Buraya bir eşik eklenirse recall sessizce düşer.
        """
        out = cr.build_combined_candidates([_vel("BTCTRY", score=1.0)], [])
        self.assertEqual(1, len(out), "birleşim katmanı skora göre aday SİLMEMELİ")


class ConfluenceTests(unittest.TestCase):
    def test_same_window_marks_confluence(self):
        vel = _vel("BTCTRY", at=T0_S)
        ris = _ris("BTCTRY", at=T0_S + 300)          # 5 dk sonra → pencere içinde
        out = cr.build_combined_candidates([vel], [ris], confluence_window_sec=1800)
        self.assertEqual(1, len(out))
        self.assertTrue(out[0]["confluence"])
        self.assertEqual(["velocity", "rising"], out[0]["sources"])

    def test_outside_window_stays_separate_in_event_stream(self):
        """Aynı sembol, 2 saat arayla → İKİ ayrı olay (replay gerçek davranışı ölçmeli)."""
        vel = _vel("BTCTRY", at=T0_S)
        ris = _ris("BTCTRY", at=T0_S + 7200)
        out = cr.build_combined_events([vel], [ris], confluence_window_sec=1800)
        self.assertEqual(2, len(out), "pencere dışı olaylar birleştirilmemeli")
        self.assertTrue(all(not c["confluence"] for c in out))

    def test_candidates_layer_dedupes_to_one_per_symbol(self):
        vel = _vel("BTCTRY", at=T0_S)
        ris = _ris("BTCTRY", at=T0_S + 7200)
        out = cr.build_combined_candidates([vel], [ris], confluence_window_sec=1800)
        self.assertEqual(1, len(out), "canlı bildirim için sembol başına TEK aday")
        self.assertFalse(out[0]["confluence"])
        # En iyi skorlu küme seçilmiş olmalı (velocity 1500 > rising 72).
        self.assertEqual("velocity", out[0]["primary_source"])

    def test_confluence_requires_both_sources_within_window(self):
        vel = _vel("BTCTRY", at=T0_S)
        ris = _ris("BTCTRY", at=T0_S + 2400)          # 40 dk > 30 dk pencere
        out = cr.build_combined_candidates([vel], [ris], confluence_window_sec=1800)
        self.assertFalse(out[0]["confluence"])


class ScoreScaleTests(unittest.TestCase):
    """D1/ölçek kuralı: velocity panel ile yükseliş skoru SAYISAL olarak karıştırılmaz."""

    def test_scores_kept_separate(self):
        out = cr.build_combined_candidates(
            [_vel("BTCTRY", score=1500.0)], [_ris("BTCTRY", score=72.0)])
        self.assertEqual(1, len(out))
        self.assertEqual(1500.0, out[0]["scores"]["velocity"])
        self.assertEqual(72.0, out[0]["scores"]["rising"])
        # `score` tetikleyen kaynağın skoru (max) — ortalama DEĞİL.
        self.assertEqual(1500.0, out[0]["score"])
        self.assertIsNotNone(out[0]["evidence"]["velocity"])
        self.assertIsNotNone(out[0]["evidence"]["rising"])

    def test_rising_falls_back_to_strength_times_ten(self):
        raw = {"symbol": "ETHTRY", "strength": 9.9, "green": 6, "price": 50.0,
               "target_pct": 2.0, "created_at": T0_S}
        item = cr.normalize_rising_evidence(raw)
        self.assertEqual(99.0, item["score"], "early_score yoksa strength×10 kullanılmalı")


class NormalizationTests(unittest.TestCase):
    def test_journal_row_and_live_envelope_both_work(self):
        journal = cr.normalize_velocity_candidate(_vel("BTCTRY"))
        live = cr.normalize_velocity_candidate(
            {"symbol": "BTCTRY", "score": 74.0, "detected_at": T0_S,
             "price": 100.0, "target_pct": 2.0})
        self.assertIsNotNone(journal)
        self.assertIsNotNone(live)
        self.assertEqual(T0_S, journal["detected_at"])
        self.assertEqual(T0_S, live["detected_at"])

    def test_millisecond_timestamps_are_coerced_to_seconds(self):
        item = cr.normalize_velocity_candidate(
            {"symbol": "BTCTRY", "velocity_score": 10.0, "created_at": T0_MS})
        self.assertEqual(T0_S, item["detected_at"], "ms → sn dönüşümü yapılmadı")

    def test_underscore_symbols_are_normalised(self):
        item = cr.normalize_rising_evidence({"symbol": "ETH_TRY", "score": 70.0})
        self.assertEqual("ETHTRY", item["symbol"])

    def test_garbage_rows_are_ignored(self):
        self.assertIsNone(cr.normalize_velocity_candidate(None))
        self.assertIsNone(cr.normalize_velocity_candidate({}))
        self.assertIsNone(cr.normalize_velocity_candidate({"symbol": " ", "velocity_score": 1.0}))
        self.assertIsNone(cr.normalize_rising_evidence({"symbol": "ETHTRY"}))


class UnifiedEnvelopeContractTests(unittest.TestCase):
    def test_envelope_is_single_type(self):
        candidate = cr.build_combined_candidates([_vel("BTCTRY")], [_ris("BTCTRY", at=T0_S + 60)])[0]
        envelope = cr.build_unified_envelope(candidate)
        self.assertEqual("radar-BTCTRY", envelope["tag"])
        self.assertNotIn("rising-", envelope["tag"], "çift push üreten eski tag DÖNMEMELİ")
        for field in ("symbol", "message", "title", "url", "score", "target_pct",
                      "price", "expected_price", "horizon_minutes", "detected_at",
                      "sources", "confluence", "paper_only"):
            self.assertIn(field, envelope, f"birleşik zarfta eksik alan: {field}")
        self.assertTrue(envelope["paper_only"])
        self.assertIs(False, envelope["updated"])

    def test_envelope_price_and_target_are_consistent(self):
        candidate = cr.build_combined_candidates([_vel("BTCTRY", price=100.0, target=2.0)])[0]
        envelope = cr.build_unified_envelope(candidate)
        self.assertAlmostEqual(102.0, envelope["expected_price"], places=6)


class LadderParityTests(unittest.TestCase):
    """Replay merdiveni üretimin (auto_paper B1-B4) SAYILARIYLA çalışmalı."""

    @classmethod
    def setUpClass(cls):
        script = ROOT / "scripts" / "combined_radar_replay_24h.py"
        spec = importlib.util.spec_from_file_location("combined_radar_replay_24h", str(script))
        cls.replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.replay)

    def test_simulator_uses_production_default_numbers(self):
        """PARİTE KİLİDİ: auto_paper varsayılanı değişirse simülatör de uymalı."""
        defaults = asyncio.run(auto_paper_defaults())
        self.assertEqual(defaults["stop_loss_pct"], config.AUTO_PAPER_SL_PCT_DEFAULT)
        self.assertEqual(defaults["breakeven_trigger_pct"], config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT)
        self.assertEqual(defaults["trailing_trigger_pct"], config.AUTO_PAPER_TRAILING_TRIGGER_PCT)
        self.assertEqual(defaults["trailing_gap_pct"], config.AUTO_PAPER_TRAILING_GAP_PCT)
        self.assertEqual(defaults["breakeven_buffer_pct"], config.AUTO_PAPER_BREAKEVEN_BUFFER_PCT)

    def test_take_profit_is_detected(self):
        entry = 100.0
        rows = _bars(T0_MS, [100.0, 100.4, 103.0])       # 3. bar TP'yi aşar
        out = self.replay._simulate_ladder(rows, entry, 2.0, 60.0)
        self.assertEqual("take_profit", out["exit_reason"])
        self.assertGreaterEqual(out["exit_price"], entry)
        self.assertGreater(out["net_pct"], 0)

    def test_stop_loss_is_detected(self):
        rows = _bars(T0_MS, [100.0, 96.0])               # %4 düşüş → SL (%3)
        out = self.replay._simulate_ladder(rows, 100.0, 2.0, 60.0)
        self.assertEqual("stop_loss", out["exit_reason"])
        self.assertLess(out["net_pct"], 0)

    def test_breakeven_protects_after_run_up(self):
        """Fiyat yükselip geri dönerse zemin kârı korumalı (kayba dönüşmemeli)."""
        entry = 100.0
        # 1. bar +2.6%'ya çıkar (breakeven trigger 1.5 üstü), sonra geri düşer.
        rows = [[T0_MS, 100.0, 102.6, 100.0, 101.0, 10.0],
                [T0_MS + 60_000, 101.0, 101.4, 100.2, 100.3, 10.0]]
        out = self.replay._simulate_ladder(rows, entry, 6.0, 60.0)
        self.assertIn(out["exit_reason"], ("breakeven_stop", "trailing_stop", "horizon_end"))
        if out["exit_reason"] != "horizon_end":
            self.assertGreaterEqual(out["net_pct"], 0, "koruma zeminini geçen çıkış zarar üretmemeli")

    def test_horizon_end_closes_at_last_closed_bar(self):
        """Ufuk dolunca çıkış SON KAPANMIŞ barın kapanışından olur (D-06 ölçümü).

        `horizon=2dk` → T0 ve T0+1dk barları kapanmış sayılır; T0+2dk'da açılan
        bar pencere DIŞIDIR (`_post_signal_window` ile aynı tanım).
        """
        rows = _bars(T0_MS, [100.0, 100.2, 100.1])
        out = self.replay._simulate_ladder(rows, 100.0, 2.0, 2.0)
        self.assertEqual("horizon_end", out["exit_reason"])
        self.assertAlmostEqual(100.2, out["exit_price"], places=6)

    def test_empty_rows_do_not_raise(self):
        out = self.replay._simulate_ladder([], 100.0, 2.0, 5.0)
        self.assertEqual("no_data", out["exit_reason"])
        self.assertIsNone(out["net_pct"])

    def test_metrics_handle_empty_stream(self):
        metrics = self.replay._metrics("combined", [])
        self.assertEqual(0, metrics["signals"])
        self.assertIsNone(metrics["win_rate"])


async def auto_paper_defaults() -> dict:
    from app.routers import auto_paper
    return await auto_paper.get_default_settings()


if __name__ == "__main__":
    unittest.main()
