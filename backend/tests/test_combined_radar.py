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

    def test_trailing_gap_default_is_truthful(self):
        """Varsayılan, GERÇEKTEN uygulanan değeri söylemeli.

        Kanıt: breakeven ratchet'i (%0.60) hem daha sıkı hem önce değerlendirildiği
        için 0.80'lik varsayılan hiç uygulanmıyordu (471 işlemlik gerçek replay'de
        `trailing_stop` 0 kez). Etkin değer 0.60'tı; varsayılan artık onu söylüyor.
        """
        self.assertLessEqual(config.AUTO_PAPER_TRAILING_GAP_PCT, 0.6)

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

    # ------------------------------------------------------------------
    # RAPOR DÜRÜSTLÜĞÜ: yanlış etiketli sütun + verdict'ın aritmetikle
    # kanıtlanması. Gerçek koşumda tabloda `hedef%` başlığı altında
    # `target_hit_rate` (%11.52) basılıyordu ve ortalama hedef (%3.73)
    # sanılıyordu.
    # ------------------------------------------------------------------
    @staticmethod
    def _stream(**over) -> dict:
        """Gerçek koşumun velocity_only satırı (2026-09-16, 24h)."""
        base = {
            "signals": 217, "measured": 217, "target_hit_rate": 11.52,
            "win_rate": 42.86, "avg_net_pct": -0.19, "median_net_pct": -0.42,
            "total_net_pct": -41.3, "avg_target_pct": 3.73, "avg_mfe_pct": 1.90,
            "target_to_mfe_ratio": 1.96, "avg_mae_pct": -1.8,
            "avg_hold_minutes": 3.5, "confluence_count": 0,
            "confluence_win_rate": None, "exit_reasons": {},
        }
        base.update(over)
        return base

    def test_summary_table_labels_touch_rate_not_average_target(self):
        """Sütun, bastığı ŞEYİ söylemeli: bu `target_hit_rate`, ortalama hedef değil."""
        result = {"streams": {"velocity_only": self._stream()}, "limitations": []}
        text = self.replay._report_text(result)
        head = next(ln for ln in text.splitlines() if ln.startswith("akış"))
        self.assertIn("TP%", head)
        self.assertNotIn("hedef%", head)
        row = next(ln for ln in text.splitlines()
                   if ln.startswith("velocity_only") and "11.52" in ln)
        self.assertIn("  11.52", row)     # dokunma oranı tabloda
        self.assertNotIn("3.73", row)     # ortalama hedef tabloda DEĞİL

    def test_cost_wall_states_gross_edge_arithmetic(self):
        """Karar iddia değil ARİTMETİK: brüt = net + gidiş-dönüş maliyet."""
        cost = self.replay.round_trip_cost_pct()
        self.assertAlmostEqual(0.35, cost, places=9)   # YÜZDE ölçeği (kesir DEĞİL)
        result = {"streams": {"velocity_only": self._stream()}, "limitations": []}
        text = self.replay._report_text(result)
        self.assertIn("MALİYET DUVARI", text)
        self.assertIn(f"{-0.19 + cost:+.3f}%", text)   # brüt kenar
        self.assertIn(f"{cost:.3f}%", text)            # maliyetin kendisi

    def test_cost_wall_uses_configured_cost_not_a_hardcoded_number(self):
        """Mutasyon kilidi: maliyet config'ten HESAPLANMALI, sabit yazılmamalı.

        `config` bir ÖRNEK (`config = Config()`) ve `COMMISSION_PCT` SINIF
        niteliği; bu yüzden sınıfı yamalıyoruz. Rapor, `cost`'u ve bacak
        dökümünü AYNI sayıdan türetmeli — ayrı ayrı okurlarsa ayrışabilirler
        (ölçüldü: örneği yamalamak `cost`'u değiştirmiyor, dökümü değiştiriyordu).
        """
        with patch.object(type(config), "COMMISSION_PCT", 0.01):
            text = self.replay._report_text(
                {"streams": {"velocity_only": self._stream()}, "limitations": []})
        self.assertIn("2.050%", text)     # (0.01 + 0.00025) * 2 * 100
        self.assertIn("1.025%/bacak", text)   # döküm = cost/2 (ayrışamaz)
        self.assertNotIn("0.350%", text)      # varsayılan sabitlenmiş OLSAYDI burada çıkardı

    def test_sweep_ceiling_below_cost_is_declared_unfixable(self):
        """Tavan brütü maliyetin altındaysa: geometri değil SEÇİCİLİK denmeli."""
        cost = self.replay.round_trip_cost_pct()
        sweep = [{"target_pct": 4.0, "sl_pct": 1.5, "gap_pct": 0.3,
                  "stream": "velocity_only", "n": 217,
                  "avg_net_pct": -0.111, "median_net_pct": -1.5715,
                  "total_net_pct": -24.1, "win_rate": 37.79}]
        result = {"streams": {"velocity_only": self._stream()}, "sweep": sweep,
                  "limitations": []}
        text = self.replay._report_text(result)
        self.assertIn("TARAMA TAVANI", text)
        self.assertIn(f"{-0.111 + cost:+.3f}%", text)
        self.assertIn("açığı kapatamaz", text)
        self.assertIn("SEÇİCİLİK", text)

    def test_sweep_ceiling_above_cost_does_not_claim_hopelessness(self):
        """Tavan maliyeti AŞIYORSA 'kapatamaz' DENMEMELİ (üretimde doğrula demeli)."""
        cost = self.replay.round_trip_cost_pct()
        sweep = [{"target_pct": 3.0, "sl_pct": 1.5, "gap_pct": 0.3,
                  "stream": "velocity_only", "n": 217,
                  "avg_net_pct": 0.50, "median_net_pct": 0.10,
                  "total_net_pct": 108.5, "win_rate": 55.0}]
        result = {"streams": {"velocity_only": self._stream()}, "sweep": sweep,
                  "limitations": []}
        text = self.replay._report_text(result)
        self.assertIn("TARAMA TAVANI", text)
        self.assertIn(f"{0.50 + cost:+.3f}%", text)
        self.assertIn("AŞIYOR", text)
        self.assertNotIn("açığı kapatamaz", text)

    def test_report_without_sweep_omits_ceiling_but_keeps_cost_wall(self):
        """Tarama yokken (--sweep verilmedi) tavan satırı olmamalı, duvar kalmalı."""
        result = {"streams": {"combined": self._stream(avg_net_pct=-0.22)},
                  "limitations": []}
        text = self.replay._report_text(result)
        self.assertIn("MALİYET DUVARI", text)
        self.assertNotIn("TARAMA TAVANI", text)

    # ------------------------------------------------------------------
    # MFE/MAE İŞARET SÖZLEŞMESİ: gerçek 24h artefaktında `mfe_pct` −0.996%,
    # `mae_pct` +0.043% görüldü — ikisi de tanımları gereği imkânsız.
    # ------------------------------------------------------------------
    def test_mfe_is_never_negative_and_mae_never_positive(self):
        """MFE "en iyi lehte" ≥ 0, MAE "en kötü aleyhte" ≤ 0.

        Kök neden: pencere sinyal barını HARİÇ tutar (R5-C4.4), bu yüzden ham
        tepe/dip farkı işaret değiştirebilir. Kırpma REPLAY sınırında yapılır;
        ortak CANLI yardımcı `_mfe_from_window` değiştirilmez (ayrı test).
        """
        entry = 100.0
        falls = self.replay._simulate_ladder(_bars(T0_MS, [99.0, 98.0, 97.0]),
                                            entry, 4.0, 60.0)
        self.assertEqual(0.0, falls["mfe_pct"])       # hiç lehte gitmedi
        self.assertLess(falls["mae_pct"], 0.0)

        rises = self.replay._simulate_ladder(_bars(T0_MS, [101.0, 102.0]),
                                            entry, 4.0, 60.0)
        self.assertEqual(0.0, rises["mae_pct"])       # hiç aleyhte gitmedi
        self.assertGreater(rises["mfe_pct"], 0.0)

    def test_live_mfe_helper_still_returns_raw_signed_value(self):
        """Kırpma replay sınırındadır: ortak canlı yardımcı HAM değeri döndürür.

        Mutasyon kilidi: kırpma yanlışlıkla `_mfe_from_window`'a taşınırsa
        (canlı davranış değişir) bu test kırmızıya döner.
        """
        window = self.replay._post_signal_window(_bars(T0_MS, [99.0, 98.0]),
                                                 T0_MS, T0_MS + 5 * 60_000)
        self.assertLess(self.replay._mfe_from_window(window, 100.0), 0.0)

    def test_excursion_invariant_holds_on_mixed_windows(self):
        """Sıra değişmezi: her pencerede mae ≤ 0 ≤ mfe (kırpmadan sonra).

        Listede HER İKİ uç da var: tüm barları girişin altında kalan pencere
        (ham MFE < 0) ve tüm barları üstünde kalan pencere (ham MAE > 0) —
        böylece bu test tek başına da kırpmayı yakalar.
        """
        for prices in ([100.0, 101.0], [100.0, 99.0], [99.0, 101.0], [102.0, 97.0],
                       [99.0, 98.0],      # hiç lehte gitmedi → ham MFE < 0
                       [101.0, 102.0]):   # hiç aleyhte gitmedi → ham MAE > 0
            out = self.replay._simulate_ladder(_bars(T0_MS, prices), 100.0, 6.0, 60.0)
            self.assertIsNotNone(out["mfe_pct"], prices)
            self.assertIsNotNone(out["mae_pct"], prices)
            self.assertGreaterEqual(out["mfe_pct"], 0.0, prices)
            self.assertLessEqual(out["mae_pct"], 0.0, prices)
            self.assertLessEqual(out["mae_pct"], out["mfe_pct"], prices)

    # ------------------------------------------------------------------
    # ÇAKIŞMA (kesişim) ALT KÜMESİ: birleştirmenin tek savunulabilir gerekçesi
    # iki kaynağın hemfikir olduğu sinyallerdir. Akış ortalamaları negatifken
    # bu alt küme pozitif çıkabilir → karar "birleştirme kötü" değil
    # "birleştirmeyi KESİŞİME daralt" olur.
    # ------------------------------------------------------------------
    def _with_confluence(self, **over) -> dict:
        base = {"confluence_count": 10, "confluence_avg_net_pct": 0.983,
                "confluence_median_net_pct": 0.852, "confluence_win_rate": 70.0}
        base.update(over)
        return base

    def test_confluence_subset_prints_mean_and_median(self):
        """Kesişim getirisi basılmalı — ortalama VE medyan (kuyruk şişmesi)."""
        conf = self._stream(**self._with_confluence())
        text = self.replay._report_text({"streams": {"combined": conf},
                                        "limitations": []})
        self.assertIn("ÇAKIŞMA ALT KÜMESİ", text)
        self.assertIn("+0.983%", text)
        self.assertIn("+0.852%", text)
        self.assertIn("70.00", text)

    def test_small_confluence_sample_is_flagged_as_hypothesis(self):
        """n<30 iken aşırı iyimserliği engelleyen uyarı ZORUNLU."""
        conf = self._stream(**self._with_confluence())
        text = self.replay._report_text({"streams": {"combined": conf},
                                        "limitations": []})
        self.assertIn("HİPOTEZ", text)
        self.assertIn("MEDYANI oku", text)

    def test_large_confluence_sample_drops_the_hypothesis_warning(self):
        """n≥30 olunca uyarı DÜŞMELİ — yoksa uyarı anlamsızlaşır."""
        conf = self._stream(**self._with_confluence(
            confluence_count=42, confluence_avg_net_pct=0.40,
            confluence_median_net_pct=0.35, confluence_win_rate=58.0))
        text = self.replay._report_text({"streams": {"combined": conf},
                                        "limitations": []})
        self.assertIn("ÇAKIŞMA ALT KÜMESİ", text)
        self.assertNotIn("HİPOTEZ", text)

    def test_report_without_confluence_omits_subset_block(self):
        """Hiç çakışma yoksa bölüm çıkmamalı (boş gürültü üretmesin)."""
        text = self.replay._report_text(
            {"streams": {"velocity_only": self._stream()}, "limitations": []})
        self.assertNotIn("ÇAKIŞMA ALT KÜMESİ", text)

    def test_confluence_metrics_exclude_non_confluence_signals(self):
        """Kesişim istatistiği YALNIZ üyelerden hesaplanır.

        Mutasyon kilidi: çakışma süzgeci düşerse 9.0'lik yabancı sinyal
        ortalamaya girer ve bu test kırmızıya döner.
        """
        sigs = [
            {"net_pct": 1.0, "target_pct": 2.0, "mfe_pct": 1.5, "mae_pct": -0.5,
             "hold_minutes": 3.0, "confluence": True, "exit_reason": "take_profit"},
            {"net_pct": -0.5, "target_pct": 2.0, "mfe_pct": 0.2, "mae_pct": -1.0,
             "hold_minutes": 3.0, "confluence": True, "exit_reason": "horizon_end"},
            {"net_pct": 9.0, "target_pct": 2.0, "mfe_pct": 0.2, "mae_pct": -1.0,
             "hold_minutes": 3.0, "confluence": False, "exit_reason": "horizon_end"},
        ]
        m = self.replay._metrics("combined", sigs)
        self.assertEqual(2, m["confluence_count"])
        self.assertAlmostEqual(0.25, m["confluence_avg_net_pct"], places=4)
        self.assertAlmostEqual(0.25, m["confluence_median_net_pct"], places=4)
        self.assertAlmostEqual(50.0, m["confluence_win_rate"], places=2)

    # ------------------------------------------------------------------
    # KAPSAMA KAPISI: iki akış AYRI dönemleri kapsıyorsa akış-ötesi kıyas
    # (LIFT, kazanma, tarama referansı) GEÇERSİZ olmalı. Gerçek bir koşumda
    # velocity pencerenin başını, rising sonunu kapsıyordu (~25 saat boşluk):
    # çakışma yapısal olarak 0 çıktı ve "+0.2763 puan LIFT" iki farklı
    # piyasa dönemini kıyasladı.
    # ------------------------------------------------------------------
    V_SPAN = (1789344160.0, 1789459294.0)     # velocity: pencerenin BAŞI
    R_SPAN = (1789549758.0, 1789600922.0)     # rising: pencerenin SONU (boşluklu)

    def _coverage_result(self, v_span, r_span, **extra) -> dict:
        result = {
            "streams": {
                "velocity_only": self._stream(first_seen_at=v_span[0],
                                              last_seen_at=v_span[1]),
                "rising_only": self._stream(signals=197, measured=197,
                                            avg_net_pct=-0.38, win_rate=25.89,
                                            first_seen_at=r_span[0], last_seen_at=r_span[1]),
                "combined": self._stream(signals=107, measured=107,
                                         avg_net_pct=-0.35, win_rate=30.84,
                                         first_seen_at=v_span[0], last_seen_at=r_span[1]),
            },
            "limitations": [],
        }
        result.update(extra)
        return result

    def test_coverage_block_prints_each_stream_span(self):
        """Her akışın GERÇEKTEN kapsadığı dönem yazılmalı (kör nokta bırakmasın)."""
        text = self.replay._report_text(self._coverage_result(self.V_SPAN, self.R_SPAN))
        self.assertIn("KAPSAMA", text)
        self.assertIn("velocity_only", text)
        self.assertIn("saat", text)      # kapsama uzunluğu saat cinsinden yazılır

    def test_disjoint_coverage_invalidates_cross_stream_comparison(self):
        """Örtüşmeyen kapsamada LIFT ve kazanma kıyası GEÇERSİZ ilan edilmeli."""
        text = self.replay._report_text(self._coverage_result(self.V_SPAN, self.R_SPAN))
        self.assertIn("GEÇERSİZ (kapsamalar örtüşmüyor)", text)
        self.assertIn("KAPSAMA ÖRTÜŞMÜYOR", text)
        self.assertIn("ENTEGRASYON İÇİN UYGUN DEĞİL", text)

    def test_overlapping_coverage_keeps_comparison_valid(self):
        """Örtüşen kapsamada bu uyarı ÇIKMAMALI (aksi hâlde uyarı anlamsızlaşır)."""
        text = self.replay._report_text(self._coverage_result(
            self.V_SPAN, (self.V_SPAN[0] + 3600, self.V_SPAN[1])))
        self.assertIn("KAPSAMA", text)
        self.assertNotIn("GEÇERSİZ (kapsamalar örtüşmüyor)", text)

    def test_truncated_journal_is_reported_not_hidden(self):
        """Bütçesi dolan akış 'tam veri' gibi sunulmamalı."""
        result = self._coverage_result(self.V_SPAN, self.R_SPAN,
                                       truncated={"velocity": True, "rising": False})
        text = self.replay._report_text(result)
        self.assertIn("bütçesi DOLDU", text)

    def test_sweep_caveat_appears_when_coverage_is_disjoint(self):
        """Izgaradaki akış-ötesi referans da kapsama bozuksa geçersiz sayılmalı."""
        sweep = [{"target_pct": 4.0, "sl_pct": 1.0, "gap_pct": 0.3,
                  "stream": "velocity_only", "n": 400, "avg_net_pct": -0.2334,
                  "median_net_pct": -1.35, "total_net_pct": -93.3, "win_rate": 29.5}]
        text = self.replay._report_text(self._coverage_result(self.V_SPAN, self.R_SPAN,
                                                              sweep=sweep))
        self.assertIn("ızgaradaki akış-ötesi kıyaslar", text)

    def test_metrics_expose_stream_time_span(self):
        """`_metrics` ilk/son tespit anını raporlar (kapsama kapısının verisi)."""
        sigs = [{"net_pct": 0.1, "target_pct": 2.0, "mfe_pct": 0.2, "mae_pct": -0.1,
                 "hold_minutes": 3.0, "confluence": False, "exit_reason": "horizon_end",
                 "detected_at": t} for t in (100.0, 500.0, 300.0)]
        m = self.replay._metrics("velocity_only", sigs)
        self.assertEqual(100.0, m["first_seen_at"])
        self.assertEqual(500.0, m["last_seen_at"])

    # ------------------------------------------------------------------
    # BOŞ RAPOR: "0 sinyal" sessiz kalmamalı. Gerçek olay (2026-09-17):
    # 24 saatlik koşum yalnız BAŞLIK satırı içeren CSV üretti; huninin
    # neresinde düştüğü ve journal'ın son satır zamanı hiçbir yerde yoktu.
    # ------------------------------------------------------------------
    def test_zero_signal_report_explains_the_funnel(self):
        result = {
            "streams": {}, "signals": [], "limitations": [],
            "window": {"hours": 24, "since": 1.0, "until": 2.0},
            "funnel": {"journal_rows": {"velocity": 0, "rising": 0},
                       "velocity_events_after_gate": 0, "combined_events": 0,
                       "confluence_events": 0,
                       "after_price_target_filter": {"velocity": 0, "rising": 0,
                                                     "combined": 0}},
            "journal_coverage": {"velocity_latest": 1789459294.0, "velocity_count": 50000,
                                 "rising_latest": 1789600922.0, "rising_count": 1200},
        }
        text = self.replay._report_text(result)
        self.assertIn("HİÇ SİNYAL YOK", text)
        self.assertIn("journal son satır", text)
        self.assertIn("saat sayısını ARTIR", text)
        self.assertIn("velocity=0", text)

    def test_zero_signal_report_flags_a_completely_empty_journal(self):
        """Journal hiç yazılmamışsa bu, 'pencereyi büyüt' ile KARIŞTIRILMAMALI."""
        result = {
            "streams": {}, "signals": [], "limitations": [],
            "window": {"hours": 24},
            "funnel": {"journal_rows": {"velocity": 0, "rising": 0}},
            "journal_coverage": {"velocity_count": 0, "rising_count": 0,
                                 "velocity_latest": None, "rising_latest": None},
        }
        text = self.replay._report_text(result)
        self.assertIn("TAMAMEN BOŞ", text)

    def test_confluence_subset_is_measured_as_its_own_sweep_stream(self):
        """KESİŞİM AYNASI: `confluence` taramada AKIŞ olmalı, CSV'ye yazılmamalı.

        Gerçek koşum (2026-09-17): tek POZİTİF alt küme kesişimdi (n=11, ort
        +0.468%, medyan +0.530%, kazanma %72.7) ama geometri taramasında akış
        olarak YOKTU → "kesişim kârlı bir geometriye sahip mi" sorusu
        cevaplanamıyordu. Kesişim satırları `combined` satırlarının birebir
        kopyasıdır, bu yüzden CSV'ye (result["signals"]) yazılmaz: yazılsa
        örneklem ve net toplam ikiye katlanırdı.
        """
        import time
        from unittest.mock import patch
        replay = self.replay
        now = time.time()

        def _row(sym, offset, velocity):
            row = {"symbol": sym, "created_at": now - 3600 + offset, "price": 100.0,
                   "target_pct": 2.0}
            if velocity:
                row.update({"passes": True, "velocity_score": 1800.0,
                            "candidate_id": f"vel-5dk-{sym}"})
            else:
                row.update({"kind": "rising", "score": 70.0})
            return row

        vel = [_row("BTCTRY", 0, True), _row("ETHTRY", 0, True)]
        ris = [_row("BTCTRY", 60, False), _row("ETHTRY", 60, False)]

        async def _v(*_a, **_k):
            return vel

        async def _r(*_a, **_k):
            return ris

        async def _cov():
            return {"velocity_count": 2, "rising_count": 2}

        def _kline_rows(_symbol, _interval, _days, end_ms):
            out: list = []
            t = int((now - 7200) // 60 * 60)
            price = 100.0
            while t * 1000 <= end_ms:
                close = price * 1.004
                out.append([t * 1000, str(price), str(max(price, close)),
                            str(min(price, close)), str(close), "10",
                            t * 1000 + 59999, str(close), 1, "1", "1", "1"])
                price, t = close, t + 60
            return out

        async def _klines(*args, **kwargs):
            return _kline_rows(*args, **kwargs)

        with patch.object(replay.database, "list_velocity_candidates_since", _v), \
                patch.object(replay.database, "list_rising_alerts_since", _r), \
                patch.object(replay.database, "journal_coverage", _cov), \
                patch.object(replay, "historical_klines", _klines):
            # Izgara parametreleri KASTEN verilmez: `sweep=True` + None ızgaranın
            # çökmediğini de bu test kilitler (len(None) hatası burada yakalandı).
            result = asyncio.run(replay.build_report(
                hours=24, symbols=None, max_signals=400, confluence_window=None,
                skip_fetch=False, out_path=None, log=lambda _m: None, sweep=True))

        self.assertGreater(result["streams"]["confluence"]["signals"], 0,
                           "kesişim akışı ölçülmemiş")
        conf_rows = [r for r in result["sweep"] if r["stream"] == "confluence"]
        self.assertTrue(conf_rows, "kesişim geometri taramasında akış olarak yok")
        self.assertNotIn("confluence",
                         {s.get("stream") for s in result["signals"]},
                         "kesişim CSV'ye yazılmamalı (combined'in kopyası)")
        self.assertIn("KESİŞİM GEOMETRİSİ", result["report_text"])

    def test_sweep_region_separates_structural_edge_from_noise(self):
        """Tek hücre maksimumu kanıt DEĞİL: pozitif BÖLGENİN şekli raporlanmalı.

        192 hücrenin maksimumunu seçmek her zaman "pozitif bir şey" bulur. Asıl
        soru pozitiflerin YAPISAL olup olmadığı: stop ekseninde bir tavana kadar
        kümeleniyorsa ders "kaybedenleri kes" ve taşınabilir; tek hücreyse gürültü.
        """
        replay = self.replay
        cells = [{"stream": "v", "target_pct": t, "sl_pct": sl, "gap_pct": 0.6,
                  "n": 100, "avg_net_pct": 0.0}
                 for t in (1.0, 2.0, 3.0) for sl in (0.5, 1.0, 3.0)]

        # YAPISAL: dar stopların TAMAMI pozitif, geniş stop (3.0) negatif.
        structural = [dict(c, avg_net_pct=(0.3 if c["sl_pct"] <= 1.0 else -0.5))
                      for c in cells]
        text = "\n".join(replay._sweep_region_lines(structural, "v"))
        self.assertIn("6/9 hücre pozitif", text)
        self.assertIn("YAPISAL", text)
        self.assertNotIn("GÜRÜLTÜ", text)

        # GÜRÜLTÜ: tek bir hücre pozitif → maksimum güvenilmez.
        noise = [dict(c, avg_net_pct=(0.9 if (c["target_pct"] == 1.0
                                              and c["sl_pct"] == 0.5) else -0.4))
                 for c in cells]
        ntext = "\n".join(replay._sweep_region_lines(noise, "v"))
        self.assertIn("1/9 hücre pozitif", ntext)
        self.assertIn("GÜRÜLTÜ", ntext)

        # HİÇBİRİ: geometri çözüm değil.
        none = [dict(c, avg_net_pct=-0.4) for c in cells]
        self.assertIn("0/9 hücre pozitif",
                      "\n".join(replay._sweep_region_lines(none, "v")))

    def test_offset_hours_shifts_window_into_the_past(self):
        """OUT-OF-SAMPLE: pencere geçmişe kaymalı ve rapor bunu AÇIKÇA yazmalı.

        Pencere eskiden her zaman "şimdi"de bitiyordu → aynı ızgarayı BAŞKA bir
        dönemde koşmak imkânsızdı, yani tek dönemlik maksimum doğrulanamıyordu.
        """
        import time
        from unittest.mock import patch
        replay = self.replay
        before = time.time()

        async def _empty(*_a, **_k):
            return []

        async def _cov():
            return {}

        with patch.object(replay.database, "list_velocity_candidates_since", _empty), \
                patch.object(replay.database, "list_rising_alerts_since", _empty), \
                patch.object(replay.database, "journal_coverage", _cov):
            result = asyncio.run(replay.build_report(
                hours=6, symbols=None, max_signals=10, confluence_window=None,
                skip_fetch=True, out_path=None, log=lambda _m: None,
                offset_hours=24))

        period = result["period"]
        self.assertEqual(period["offset_hours"], 24.0)
        self.assertAlmostEqual(period["until"], before - 24 * 3600, delta=60)
        self.assertAlmostEqual(period["since"], period["until"] - 6 * 3600, delta=60)
        # "0 sinyal" dönüşünde de dönem taşınmalı (tanı erken dönüşte kaybolmasın).
        self.assertIn("DÖNEM:", result["report_text"])
        self.assertIn("OUT-OF-SAMPLE", result["report_text"])

    def test_oos_verdict_dayandi_only_when_cell_holds_and_region_structural(self):
        """OOS kararı ÖNCEDEN sabit kurala göre verilmeli, sonuca göre değil.

        Üç dal: DAYANDI (hücre pozitif + bölge yapısal), ZAYIF (hücre pozitif ama
        bölge yapısal değil), DAYANMADI (hücre OOS'ta negatif).
        """
        replay = self.replay

        def grid(neg_sl_from: float, best_net: float, sls=(0.5, 1.5, 3.0)):
            return [{"stream": "velocity_only", "target_pct": t, "sl_pct": sl,
                     "gap_pct": 0.3, "n": 100, "win_rate": 40.0,
                     "median_net_pct": 0.0, "total_net_pct": 2.0,
                     "avg_net_pct": (best_net if (t == 6.0 and sl == 1.5)
                                     else (0.2 if sl < neg_sl_from else -0.5))}
                    for t in (3.0, 6.0) for sl in sls]

        # Baz: en iyi hücre 6.00 / 1.50
        base = {"sweep": grid(neg_sl_from=3.0, best_net=0.206)}
        base["report_text"] = ""

        # (a) DAYANDI: aynı hücre pozitif + yapısal bölge (stop 3.00 tamamen negatif)
        oos_ok = {"sweep": grid(neg_sl_from=3.0, best_net=0.150), "period": {"offset_hours": 24}}
        text = "\n".join(replay.attach_oos_comparison(base, oos_ok))
        self.assertIn("DAYANDI", text)

        # (b) DAYANMADI: aynı hücre OOS'ta NEGATİF (bölge yapısal olsa bile)
        base2 = {"sweep": grid(neg_sl_from=3.0, best_net=0.206), "report_text": ""}
        oos_bad = {"sweep": grid(neg_sl_from=3.0, best_net=-0.180), "period": {}}
        self.assertIn("DAYANMADI",
                      "\n".join(replay.attach_oos_comparison(base2, oos_bad)))

        # (c) ZAYIF: hücre pozitif ama TÜM stoplar pozitif → bölge yapısal değil
        base3 = {"sweep": grid(neg_sl_from=3.0, best_net=0.206), "report_text": ""}
        oos_flat = {"sweep": grid(neg_sl_from=99.0, best_net=0.150), "period": {}}
        self.assertIn("ZAYIF",
                      "\n".join(replay.attach_oos_comparison(base3, oos_flat)))

    def test_oos_short_coverage_downgrades_the_verdict(self):
        """KISA OOS penceresi negatifi KESİNLEŞTİRMEMELİ.

        Gerçek koşumda baz 339 sinyal / OOS 193 sinyal çıktı: oran ~%57, yani OOS
        okuması 24 saatin ~11 saatini kapsıyor olabilir. Yarım pencere sessiz bir
        döneme denk gelirse "DAYANMADI" yanlış kesinlik taşır; karar bunu söylemeli.
        """
        replay = self.replay
        row = {"stream": "velocity_only", "target_pct": 6.0, "sl_pct": 1.5,
               "gap_pct": 0.3, "n": 100, "win_rate": 38.0, "median_net_pct": 0.0,
               "total_net_pct": 0.0, "avg_net_pct": 0.161}
        base = {"sweep": [dict(row)], "report_text": "",
                "streams": {"velocity_only": {"first_seen_at": 0.0, "last_seen_at": 72000.0}}}
        # OOS yalnız 11 saat kapsıyor (baz 20 saat) → kısa
        oos = {"sweep": [dict(row, avg_net_pct=-0.477)], "period": {},
               "window": {"hours": 24},
               "streams": {"velocity_only": {"first_seen_at": 0.0, "last_seen_at": 39600.0}}}
        text = "\n".join(replay.attach_oos_comparison(base, oos))
        self.assertIn("KAPSAMA KISA", text)
        self.assertIn("KESINLESTIRMEZ", text)
        self.assertIn("DAYANMADI", text)
        self.assertIn("KAPSAMA KISA", base["oos"]["verdict"])

    def test_oos_full_coverage_keeps_verdict_firm(self):
        """Kapsama tam ise karar etiketi KİRLETİLMEMELİ (yanlış alarm yok)."""
        replay = self.replay
        row = {"stream": "velocity_only", "target_pct": 6.0, "sl_pct": 1.5,
               "gap_pct": 0.3, "n": 100, "win_rate": 38.0, "median_net_pct": 0.0,
               "total_net_pct": 0.0, "avg_net_pct": 0.161}
        span = {"first_seen_at": 0.0, "last_seen_at": 72000.0}
        base = {"sweep": [dict(row)], "report_text": "",
                "streams": {"velocity_only": dict(span)}}
        oos = {"sweep": [dict(row, avg_net_pct=-0.477)], "period": {},
               "window": {"hours": 24}, "streams": {"velocity_only": dict(span)}}
        lines = replay.attach_oos_comparison(base, oos)
        self.assertNotIn("KAPSAMA KISA", "\n".join(lines))
        self.assertTrue(base["oos"]["verdict"].startswith("KARAR:"))

    def test_oos_validates_every_stream_the_report_calls_positive(self):
        """OOS bloğu raporun 'aday' işaretlediği akışları da yargılamalı.

        Gerçek koşumda yalnız velocity doğrulanıyordu; raporun tek POZİTİF bulgusu
        kesişimdi (n=12, ort +0.719%) ve o hiç doğrulanmadan "aday" olarak
        okunuyordu. Bir bulgu doğrulanmadan aday sayılmamalı.
        """
        replay = self.replay

        def rows(stream, net, n=10):
            out = []
            for t in (2.0, 4.0):
                for sl in (1.0, 3.0):
                    out.append({"stream": stream, "target_pct": t, "sl_pct": sl,
                                "gap_pct": 0.3, "n": n, "avg_net_pct": net,
                                "median_net_pct": net, "total_net_pct": net * n,
                                "win_rate": 60.0})
            return out

        base = {"report_text": "",
                "streams": {"velocity_only": {"measured": 300},
                            "combined": {"measured": 100},
                            "confluence": {"measured": 12},
                            "rising_only": {"measured": 200}},
                "sweep": rows("velocity_only", 0.2, n=300) + rows("combined", 0.05, n=100)
                         + rows("confluence", 0.7, n=12)}
        oos = {"period": {"offset_hours": 24}, "window": {"hours": 24},
               "streams": {"velocity_only": {"measured": 150},
                           "combined": {"measured": 50},
                           "confluence": {"measured": 6}},
               "sweep": rows("velocity_only", -0.5, n=150) + rows("combined", -0.3, n=50)
                        + rows("confluence", -0.9, n=6)}
        text = "\n".join(replay.attach_oos_comparison(base, oos))
        self.assertIn("velocity_only", text)
        self.assertIn("confluence", text)
        self.assertEqual(set(base["oos"]["streams"]),
                         {"velocity_only", "combined", "confluence"})
        # `rising_only` baz dönemde POZİTİF değil → doğrulama kapsamına alınmaz.
        self.assertNotIn("rising_only", base["oos"]["streams"])
        self.assertTrue(base["oos"]["streams"]["confluence"]["verdict"])

    def test_oos_says_unverifiable_when_oos_has_no_samples_for_the_stream(self):
        """OOS'ta kesişim sinyali YOKSA 'YAPILAMADI' demeli — sessizce atlamamalı.

        Sessiz atlama "doğrulandı" izlenimi verirdi; oysa n=0 ile karşılaştırma
        matematiksel olarak yapılamaz ve bulgu karar verisi değildir.
        """
        replay = self.replay
        vel = {"stream": "velocity_only", "target_pct": 6.0, "sl_pct": 1.5,
               "gap_pct": 0.3, "n": 345, "avg_net_pct": 0.117, "median_net_pct": 0.0,
               "total_net_pct": 40.0, "win_rate": 35.9}
        conf = {"stream": "confluence", "target_pct": 6.0, "sl_pct": 3.0,
                "gap_pct": 0.3, "n": 12, "avg_net_pct": 0.719, "median_net_pct": -0.096,
                "total_net_pct": 8.6, "win_rate": 50.0}
        base = {"report_text": "", "sweep": [vel, conf],
                "streams": {"velocity_only": {"measured": 345},
                            "confluence": {"measured": 12}}}
        oos = {"period": {}, "window": {"hours": 24},
               "streams": {"velocity_only": {"measured": 193},
                           "confluence": {"measured": 0}},
               "sweep": [dict(vel, n=193, avg_net_pct=-0.505)]}
        lines = replay.attach_oos_comparison(base, oos)
        text = "\n".join(lines)
        self.assertIn("YAPILAMADI", text)
        self.assertIn("KARAR VERISI DEGIL", text)
        self.assertEqual(base["oos"]["streams"]["confluence"]["oos_measured"], 0)

    def test_oos_verdict_does_not_invent_when_grid_missing(self):
        """Karşılaştırma yapılamıyorsa YAPILAMADI demeli, karar uydurmamalı."""
        replay = self.replay
        base = {"sweep": [{"stream": "velocity_only", "target_pct": 6.0, "sl_pct": 1.5,
                           "gap_pct": 0.3, "n": 10, "avg_net_pct": 0.2, "win_rate": 40.0,
                           "median_net_pct": 0.0, "total_net_pct": 2.0}],
                "report_text": ""}
        lines = replay.attach_oos_comparison(base, {"sweep": [], "period": {}})
        self.assertIn("YAPILAMADI", "\n".join(lines))
        self.assertIn("KARAR:",
                      "\n".join(replay.attach_oos_comparison(
                          {"sweep": base["sweep"], "report_text": ""},
                          {"sweep": base["sweep"], "period": {}})))

    def test_non_empty_report_has_no_zero_alarm(self):
        """Uyarı yalnız gerçekten boş raporda çıkmalı (aksi hâlde gürültü olur)."""
        result = self._coverage_result(self.V_SPAN, self.V_SPAN, signals=107)
        result["signals"] = [{"stream": "combined"}]
        text = self.replay._report_text(result)
        self.assertNotIn("HİÇ SİNYAL YOK", text)

    def test_empty_journal_run_still_carries_diagnostics(self):
        """ERKEN DÖNÜŞ KİLİDİ: `if not all_signals: return` yolu TANILARI taşımalı.

        Gerçek hata (2026-09-17): bu erken dönüş `funnel`/`journal_coverage`/`sweep`
        kurmuyordu — yani tanının EN ÇOK gerektiği yolda tanı yoktu. Kullanıcı
        sebebi olmayan başlık-only CSV indirdi ve "replay çalıştı ama sonuç boş"
        diye okudu. Bu test, boş koşumda bu alanların varlığını ZORUNLU kılar.
        """
        from unittest.mock import patch
        replay = self.replay

        async def _empty(*args, **kwargs):
            return []

        async def _cov():
            return {"velocity_count": 0, "rising_count": 0,
                    "velocity_latest": None, "rising_latest": None}

        with patch.object(replay.database, "list_velocity_candidates_since", _empty), \
                patch.object(replay.database, "list_rising_alerts_since", _empty), \
                patch.object(replay.database, "journal_coverage", _cov):
            result = asyncio.run(replay.build_report(
                hours=24, symbols=None, max_signals=400, confluence_window=None,
                skip_fetch=False, out_path=None, log=lambda _m: None, sweep=True))

        self.assertEqual([], result["signals"])
        for key in ("funnel", "journal_coverage", "truncated", "sweep"):
            self.assertIn(key, result, f"boş koşumda '{key}' tanısı kayıp")
        self.assertEqual([], result["sweep"])
        text = result.get("report_text") or replay._report_text(result)
        self.assertIn("HİÇ SİNYAL YOK", text)
        self.assertIn("TAMAMEN BOŞ", text)


class RisingReaderContractTests(unittest.TestCase):
    """`list_rising_alerts_since` velocity okuyucusuyla AYNI semantikte olmalı.

    Sözleşme: zaman pencereli + `created_at` ARTAN sırada. Eski okuyucu
    (`list_rising_alerts`) DESC + limit ile EN YENİ satırları döndürüyordu;
    velocity ise ARTAN ilk N. İki akış böylece ayrı dönemleri kapsıyordu.
    """

    def _capture(self, since=1000.0, until=2000.0, limit=50) -> dict:
        captured: dict = {"sqls": []}

        class _Cursor:
            def fetchall(self):
                return []

        class _Conn:
            def execute(self, sql, params):
                captured["sqls"].append(" ".join(str(sql).split()))
                captured["params"] = list(params)
                return _Cursor()

        async def _fake_run_db(operation):
            return operation(_Conn())

        from unittest.mock import patch
        from app import database
        with patch.object(database, "_ensure_rising_evidence_schema", lambda conn: None), \
                patch.object(database, "_run_db", _fake_run_db):
            asyncio.run(database.list_rising_alerts_since(since, until, limit=limit))
        return captured

    def test_reads_ascending_like_velocity(self):
        captured = self._capture()
        select = next(s for s in captured["sqls"] if "FROM rising_alerts" in s)
        self.assertTrue(select.endswith("ORDER BY created_at ASC LIMIT ?"),
                        f"ARTAN sıra bekleniyordu: {select}")

    def test_is_window_bounded(self):
        captured = self._capture(1000.0, 2000.0, limit=50)
        select = next(s for s in captured["sqls"] if "FROM rising_alerts" in s)
        self.assertIn("created_at >= ?", select)
        self.assertIn("created_at <= ?", select)
        self.assertEqual([1000.0, 2000.0, 50], captured["params"])

    def test_until_is_optional(self):
        captured = self._capture(until=None, limit=7)
        select = next(s for s in captured["sqls"] if "FROM rising_alerts" in s)
        self.assertNotIn("created_at <= ?", select)
        self.assertEqual([1000.0, 7], captured["params"])


class JournalCoverageContractTests(unittest.TestCase):
    """`journal_coverage` PENCERESİZ min/max/count okumalı.

    "0 sinyal" tanısının çekirdeği budur: pencereli sorgu "satır yok" der ama
    NEDEN'ini söylemez; penceresiz son satır zamanı ise "pencere veriyi kaçırıyor"
    ile "journal hiç yazılmamış" ayrımını yapar.
    """

    def _capture(self) -> dict:
        captured: dict = {"sqls": []}

        class _Cursor:
            def __init__(self, values):
                self._values = values

            def fetchone(self):
                return self._values

        class _Conn:
            def execute(self, sql, params=None):
                sql = " ".join(str(sql).split())
                captured["sqls"].append(sql)
                if "velocity_candidates" in sql:
                    return _Cursor({"a": 10.0, "b": 20.0, "n": 7})
                if "rising_alerts" in sql:
                    return _Cursor({"a": 11.0, "b": 21.0, "n": 3})
                return _Cursor(None)

        async def _fake_run_db(operation):
            return operation(_Conn())

        from unittest.mock import patch
        from app import database
        with patch.object(database, "_ensure_rising_evidence_schema", lambda conn: None), \
                patch.object(database, "_run_db", _fake_run_db):
            captured["result"] = asyncio.run(database.journal_coverage())
        return captured

    def test_reads_min_max_count_without_a_time_window(self):
        captured = self._capture()
        for table in ("velocity_candidates", "rising_alerts"):
            sql = next(s for s in captured["sqls"] if table in s)
            self.assertIn("MIN(created_at)", sql)
            self.assertIn("MAX(created_at)", sql)
            self.assertIn("COUNT(*)", sql)
            self.assertNotIn("WHERE", sql)   # pencere YOK — tüm aralık gerekir

    def test_returns_both_journals_span_and_count(self):
        cov = self._capture()["result"]
        self.assertEqual(10.0, cov["velocity_earliest"])
        self.assertEqual(20.0, cov["velocity_latest"])
        self.assertEqual(7, cov["velocity_count"])
        self.assertEqual(11.0, cov["rising_earliest"])
        self.assertEqual(21.0, cov["rising_latest"])
        self.assertEqual(3, cov["rising_count"])

    def test_one_broken_table_does_not_break_the_other(self):
        class _Cursor:
            def __init__(self, values):
                self._values = values

            def fetchone(self):
                return self._values

        class _Conn:
            def execute(self, sql, params=None):
                sql = " ".join(str(sql).split())
                if "velocity_candidates" in sql:
                    raise RuntimeError("tablo yok")
                return _Cursor({"a": 1.0, "b": 2.0, "n": 4})

        async def _fake_run_db(operation):
            return operation(_Conn())

        from unittest.mock import patch
        from app import database
        with patch.object(database, "_ensure_rising_evidence_schema", lambda conn: None), \
                patch.object(database, "_run_db", _fake_run_db):
            cov = asyncio.run(database.journal_coverage())
        self.assertIn("velocity_error", cov)
        self.assertEqual(4, cov["rising_count"])


async def auto_paper_defaults() -> dict:
    from app.routers import auto_paper
    return await auto_paper.get_default_settings()


if __name__ == "__main__":
    unittest.main()
