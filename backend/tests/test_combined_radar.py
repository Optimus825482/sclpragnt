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
        self.assertIsNone(metrics["target_to_mfe_ratio"])

    def test_metrics_expose_target_to_mfe_geometry(self):
        """Hedef/MFE oranı raporlanır: hedef ortalamayı aşıyorsa TP ulaşılamaz.

        Gerçek koşum kanıtı (2026-09-16): velocity ort. hedef ~%3.4 / ort. MFE
        %1.96 → oran >1 → TP isabeti %12'de kaldı; rising hedef %2.0 / MFE %0.73
        → oran 2.7× → TP isabeti %4.4. Yani SL (%3) tipik harekete göre GENİŞ,
        TP ise ulaşılamaz yüksek: ters asimetri (negatif EV'nin kök nedeni).
        """
        signals = [
            {"net_pct": -0.16, "target_pct": 3.0, "mfe_pct": 1.5,
             "exit_reason": "horizon_end", "hold_minutes": 3.5},
            {"net_pct": 3.65, "target_pct": 4.0, "mfe_pct": 4.2,
             "exit_reason": "take_profit", "hold_minutes": 1.5},
        ]
        metrics = self.replay._metrics("velocity_only", signals)
        self.assertEqual(3.5, metrics["avg_target_pct"])
        self.assertEqual(2.85, metrics["avg_mfe_pct"])
        self.assertAlmostEqual(3.5 / 2.85, metrics["target_to_mfe_ratio"], places=2)

    def test_sl_override_changes_outcome_on_same_window(self):
        """TARAMA KANITI: aynı pencere, yalnız stop farklı → farklı çıkış.

        Sabit %3 stop'un neden ters asimetri ürettiğini gösterir: -2%'lik normal
        bir geri çekilme GENİŞ stopla atlatılır (işlem kâra döner), DAR stopla
        STOP olur. Taramayı bu yüzden istiyoruz. (Mutasyon: `sl_pct` dışarıdan
        verilmeyip sabit %3 kullanılsaydı iki sonuç birebir aynı olurdu.)
        """
        base = 1_700_000_000_000
        rows = [
            [base, 100.0, 100.2, 100.0, 100.1, 10.0],
            [base + 60_000, 100.1, 100.3, 98.0, 98.5, 10.0],
            [base + 120_000, 98.5, 105.0, 98.4, 104.0, 10.0],
        ]
        wide = self.replay._simulate_ladder(rows, 100.0, 4.0, 5.0, sl_pct=3.0)
        narrow = self.replay._simulate_ladder(rows, 100.0, 4.0, 5.0, sl_pct=1.0)
        self.assertEqual("take_profit", wide["exit_reason"])
        self.assertGreater(wide["net_pct"], 0)
        self.assertEqual("stop_loss", narrow["exit_reason"])
        self.assertLess(narrow["net_pct"], 0)

    def test_sweep_geometry_covers_grid_and_streams(self):
        """Izgara = hedef × stop × akış; her hücre için tam bir metrik satırı."""
        base = 1_700_000_000_000
        rows = [[base, 100.0, 100.5, 99.8, 100.0, 10.0],
                [base + 60_000, 100.0, 101.2, 99.9, 101.0, 10.0]]
        inputs = [
            {"stream": "combined", "rows": rows, "entry": 100.0,
             "horizon": 5.0, "signal_ms": base},
            {"stream": "combined", "rows": rows, "entry": 100.0,
             "horizon": 5.0, "signal_ms": base + 1_000},
            {"stream": "velocity_only", "rows": rows, "entry": 100.0,
             "horizon": 5.0, "signal_ms": base},
        ]
        out = self.replay._sweep_geometry(inputs, [1.0, 2.0], [1.0])
        self.assertEqual(4, len(out))   # 2 hedef × 1 stop × 2 akış
        self.assertEqual({1.0, 2.0}, {r["target_pct"] for r in out})
        self.assertEqual({"combined", "velocity_only"}, {r["stream"] for r in out})
        # Her hücre KENDİ akışının sinyallerini biriktirir (combined=2, velocity=1).
        counts = {r["stream"]: r["n"] for r in out}
        self.assertEqual({"combined": 2, "velocity_only": 1}, counts)
        for row in out:
            self.assertIsNotNone(row["avg_net_pct"])
            self.assertIsNotNone(row["win_rate"])

    def test_ratchet_gap_governs_mfe_capture(self):
        """RATCHET KANITI: aynı pencere, yalnız ratchet açıklığı farklı → farklı net.

        MFE'nin ne kadarının KORUNDUĞUNU ratchet açıklığı belirler. velocity
        ort.MFE %1.96 iken ort.net −0.16 → lehine hareketin neredeyse tamamı geri
        veriliyor; bu yüzden ratchet taranabilir olmalı. (Mutasyon: `be_gap_pct`
        yok sayılsaydı iki sonuç birebir aynı olurdu.)
        """
        base = 1_700_000_000_000
        rows = [
            [base, 100.0, 100.5, 99.9, 100.2, 10.0],
            [base + 60_000, 100.2, 102.5, 100.4, 102.0, 10.0],
        ]
        tight = self.replay._simulate_ladder(rows, 100.0, 3.0, 5.0, be_gap_pct=0.3)
        loose = self.replay._simulate_ladder(rows, 100.0, 3.0, 5.0, be_gap_pct=1.5)
        self.assertEqual("breakeven_stop", tight["exit_reason"])
        self.assertEqual("breakeven_stop", loose["exit_reason"])
        # Sıkı ratchet zirveye daha yakın kilitler → daha çok MFE korunur.
        self.assertGreater(tight["exit_price"], loose["exit_price"])
        self.assertGreater(tight["net_pct"], loose["net_pct"])

    def test_sweep_grid_includes_ratchet_dimension(self):
        """Izgara ratchet boyutunu da tarar (3. boyut)."""
        base = 1_700_000_000_000
        rows = [[base, 100.0, 100.5, 99.8, 100.0, 10.0],
                [base + 60_000, 100.0, 101.2, 99.9, 101.0, 10.0]]
        inputs = [{"stream": "combined", "rows": rows, "entry": 100.0,
                   "horizon": 5.0, "signal_ms": base}]
        out = self.replay._sweep_geometry(inputs, [1.0, 2.0], [1.0], gaps=[0.3, 1.5])
        self.assertEqual(4, len(out))   # 2 hedef × 1 stop × 2 gap × 1 akış
        self.assertEqual({0.3, 1.5}, {r["gap_pct"] for r in out})
        # Varsayılan (gaps verilmezse) üretim değeri 0.60 kullanılır.
        default_out = self.replay._sweep_geometry(inputs, [1.0], [1.0])
        self.assertEqual({0.6}, {r["gap_pct"] for r in default_out})

    def test_emit_survives_non_ascii_report_text(self):
        """Windows cp1254 konsolu rapordaki → ★ × ✗ karakterlerini basamıyordu.

        Gerçek olay: yerel CLI koşumu `UnicodeEncodeError ... '\\u2192'` ile
        çöküyordu. `_emit` artık asla UnicodeEncodeError sızdırmamalı.
        """
        captured: list[str] = []
        self.replay._emit(lambda m: captured.append(m), "→ ★ × ✗ çakışma ölçüldü")
        self.assertEqual(["→ ★ × ✗ çakışma ölçüldü"], captured)
        self.replay._emit(None, "→ ★ × ✗ çakışma ölçüldü")   # print yolu çökmemeli

    def test_report_text_contains_non_ascii_so_guard_is_needed(self):
        """Guard'ın NEDENİ: rapor ASCII dışı karakter içeriyor (cp1254'te patlar)."""
        text = self.replay._report_text({"streams": {}, "limitations": []})
        self.assertTrue(any(ord(ch) > 127 for ch in text))

    def test_sweep_verdict_flags_no_edge(self):
        rows = [
            {"target_pct": 1.0, "sl_pct": 1.0, "stream": "combined", "n": 10,
             "avg_net_pct": -0.20, "median_net_pct": -0.30,
             "total_net_pct": -2.0, "win_rate": 30.0},
            {"target_pct": 2.0, "sl_pct": 0.5, "stream": "combined", "n": 10,
             "avg_net_pct": -0.10, "median_net_pct": -0.20,
             "total_net_pct": -1.0, "win_rate": 35.0},
        ]
        text = "\n".join(self.replay._sweep_lines(rows))
        self.assertIn("HİÇBİR TP/SL kombinasyonu pozitif DEĞİL", text)

    def test_sweep_verdict_flags_edge_and_picks_best(self):
        """Pozitif hücre varsa EN İYİ açıkça yazılır (karar verisi)."""
        rows = [
            {"target_pct": 3.0, "sl_pct": 3.0, "stream": "combined", "n": 72,
             "avg_net_pct": -0.14, "median_net_pct": -0.30,
             "total_net_pct": -10.1, "win_rate": 26.39},
            {"target_pct": 1.5, "sl_pct": 1.0, "stream": "combined", "n": 72,
             "avg_net_pct": 0.42, "median_net_pct": 0.10,
             "total_net_pct": 30.2, "win_rate": 58.3},
        ]
        text = "\n".join(self.replay._sweep_lines(rows))
        self.assertIn("POZİTİF", text)
        self.assertIn("EN İYİ (combined): hedef %1.50 / stop %1.00", text)
        self.assertIn("+0.420%", text)
        # Referans özeti: olmayan akış için "yok" demeli (KeyError değil).
        self.assertEqual("yok", self.replay._sweep_best(rows, "rising_only"))


async def auto_paper_defaults() -> dict:
    from app.routers import auto_paper
    return await auto_paper.get_default_settings()


if __name__ == "__main__":
    unittest.main()
