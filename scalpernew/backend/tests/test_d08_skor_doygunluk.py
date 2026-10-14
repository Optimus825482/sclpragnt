"""A3 (2026-09-14): panel skor ölçeği — DOYGUNLUK GİDERİLDİ (D-08'in devamı).

D-08 bulgusu: `normalize_score = min(100, raw/CAP×100)` HAM 2000'de SERT kırpar.
Gerçek dağılım (n=42773): p50=3.0, p90=18.3, p99=159, p99.9=1024, max=21389.
Tüm tabloda yalnız %0.06 satır kırpılır AMA BİLDİRİLEN bant (ham ≥1400) tamamen
kırpılan bölgede olduğu için kullanıcının tablosunda 104 tespitin 100'ü tam
100.00 görünüyordu → sıralama bilgisi sıfır, "SKOR ≥ 90" eşiği anlamsız.

D-08 kararı "cap YÜKSELTİLMEDİ" idi (hedef bantları panel ölçeğinde olduğu için
ölçek değişimi = strateji değişimi). A3 bunu BİLİNÇLİ OLARAK DEĞİŞTİRİR: kırpma
yerine monoton log haritası uygulanır. Strateji kaymasını önlemek için panel
ölçeğindeki TÜM eşikler HAM çalışma noktaları korunarak yeniden ankrajlandı.

Bu dosya iki şeyi kilitler:
  1. `log` modda kırpma YOK + monotonluk (asıl düzeltme).
  2. `linear` modda eski davranış AYNEN durur (geri dönüş yolu).
  3. Ölçek sürümü (`norm_version`) farkındalığı + panel↔ham ters dönüşümü.
"""
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                    # noqa: E402
from app.routers import monitoring               # noqa: E402
from app.routers.monitoring import (             # noqa: E402
    _panel_from_raw, _raw_from_panel, _row_norm_cap, _score_is_saturated,
    _stored_panel_score, normalize_score,
)

REF = float(config.MONITORING_SCORE_NORM_LOG_REF)
CAP = float(config.MONITORING_SCORE_NORM_CAP)
# Ölçülen dağılımdan kritik noktalar (2026-09-14 DB taraması).
OBSERVED = (0.27, 3.0, 18.26, 158.95, 1023.91, 1400.0, 2000.0, 21388.94)


class LogScaleDeSaturationTests(unittest.TestCase):
    """Asıl düzeltme: kırpma bitsin, sıralama korunsun."""

    def test_default_mode_is_log(self):
        self.assertEqual("log", str(config.MONITORING_SCORE_NORM_MODE).lower())

    def test_no_clipping_below_ref(self):
        """Gözlenen maksimum (21389) bile REF altında → kırpma YOK, skor sıralar."""
        self.assertLess(21388.94, REF, "REF gözlenen max'ın üstünde seçilmeli")
        top = normalize_score(21388.94)
        self.assertLess(top, 100.0, "gözlenen max 100.00'a kırpılmamalı")
        # Eski davranışta bu iki değer AYNIYDI (ikisi de 100.00) — düzeltmenin özü.
        self.assertNotEqual(normalize_score(21388.94), normalize_score(4000.0))

    def test_strictly_monotonic_across_observed_range(self):
        """Monotonluk: farklı ham skorlar farklı panel skoru vermeli."""
        scores = [normalize_score(r) for r in OBSERVED]
        self.assertEqual(scores, sorted(scores), "panel skor ham skorla birlikte artmalı")
        self.assertEqual(len(scores), len(set(scores)), "gözlenen bantta yığılma olmamalı")

    def test_bildirilen_band_ayrisir(self):
        """Bildirilen bant (ham 1400-21389) artık sıralanabilir (D-08 şikâyeti)."""
        band = [1400.0, 2000.0, 5000.0, 10000.0, 21388.94]
        panel = [normalize_score(r) for r in band]
        self.assertEqual(len(panel), len(set(panel)))
        self.assertGreater(panel[-1] - panel[0], 10.0, "bant içi ayrışma anlamlı olmalı")

    def test_zero_and_bad_input(self):
        for bad in (0, None, "abc", -5):
            self.assertEqual(0.0, normalize_score(bad))


class LinearModeRollbackTests(unittest.TestCase):
    """`MONITORING_SCORE_NORM_MODE=linear` eski davranışı AYNEN korur."""

    def test_linear_clips_at_cap(self):
        with patch.object(config, "MONITORING_SCORE_NORM_MODE", "linear"):
            self.assertEqual(100.0, normalize_score(CAP))
            self.assertEqual(100.0, normalize_score(CAP * 2))
            self.assertEqual(100.0, normalize_score(CAP * 10))
            self.assertAlmostEqual(50.0, normalize_score(CAP / 2), places=9)

    def test_linear_zero_cap_guard(self):
        """cap<=0 → ZeroDivisionError değil, ham skor 0-100'e kelepçelenir."""
        with patch.object(config, "MONITORING_SCORE_NORM_MODE", "linear"), \
             patch.object(config, "MONITORING_SCORE_NORM_CAP", 0.0):
            self.assertEqual(60.0, normalize_score(60.0))
            self.assertEqual(100.0, normalize_score(1000.0))


class InverseTransformTests(unittest.TestCase):
    """Panel ↔ ham ters dönüşümü: admin eşiği sessizce kaymasın."""

    def test_roundtrip_preserves_raw_operating_point(self):
        """Panel→ham→panel turu ham noktayı korur (log ters fonksiyonu doğru)."""
        for raw in (200.0, 1000.0, 1400.0, 1700.0, 1800.0, 5000.0):
            panel = _panel_from_raw(raw)
            self.assertAlmostEqual(raw, _raw_from_panel(panel), delta=raw * 0.02,
                                   msg=f"ham {raw} turda kayboldu")

    def test_log_inverse_is_not_linear(self):
        """Regresyon: log modda panel→ham DOĞRUSAL olamaz (aksi halde eşik kayar)."""
        panel = _panel_from_raw(1400.0)
        linear_wrong = panel / 100.0 * CAP
        self.assertNotAlmostEqual(1400.0, linear_wrong, delta=1.0,
                                  msg="doğrusal ters çevirme ham 1400'ü tutmamalı")
        self.assertAlmostEqual(1400.0, _raw_from_panel(panel), delta=20.0)


class ReanchoredThresholdTests(unittest.TestCase):
    """Panel ölçeğindeki eşikler HAM çalışma noktalarını koruyacak şekilde ankrajlı."""

    def _assert_anchor(self, panel_value, expected_raw, tol=0.05):
        got = _raw_from_panel(float(panel_value))
        self.assertAlmostEqual(expected_raw, got, delta=expected_raw * tol,
                               msg=f"panel {panel_value} ham {expected_raw} noktasını tutmalı")

    def test_monitoring_min_score_default_anchors_raw_1400(self):
        self._assert_anchor(config.MONITORING_MIN_SCORE_DEFAULT, 1400.0)

    def test_fast_lane_anchors_raw_1700(self):
        self._assert_anchor(config.MONITORING_FAST_LANE_SCORE, 1700.0)

    def test_velocity_auto_min_score_anchors_raw_200(self):
        self._assert_anchor(config.VELOCITY_AUTO_MIN_SCORE, 200.0)

    def test_auto_paper_min_score_anchors_raw_1000(self):
        self._assert_anchor(config.AUTO_PAPER_MIN_SCORE_DEFAULT, 1000.0)

    def test_tier_thresholds_anchor_previous_raw_points(self):
        """Hedef merdiveni: eski 90/70/50 = ham 1800/1400/1000 noktaları korunur."""
        tiers = {}
        for part in config.MONITORING_TARGET_SCORE_TIERS.split(","):
            score, pct = part.split(":")
            tiers[float(pct)] = float(score)
        self._assert_anchor(tiers[4.0], 1800.0)
        self._assert_anchor(tiers[2.5], 1400.0)
        self._assert_anchor(tiers[2.0], 1000.0)

    def test_fast_lane_stays_above_gate(self):
        """Fast-lane eşiği kapının üstünde kalmalı (debounce bandı boş kalmasın)."""
        self.assertGreater(float(config.MONITORING_FAST_LANE_SCORE),
                           float(config.MONITORING_MIN_SCORE_DEFAULT))


class ScaleParityTests(unittest.TestCase):
    """`velocity._panel_score` kanonik `monitoring` haritasının BİREBİR kopyasıdır."""

    def test_velocity_panel_score_matches_canonical(self):
        from app.routers.velocity import _panel_score, _panel_to_raw_score
        for raw in (0, 1.0, 100, 500, 1000, 1400, 1800, 2000, 4000, 21388.94, 161709.0):
            self.assertEqual(normalize_score(raw), _panel_score(raw),
                             msg=f"raw={raw} için panel skor ayrıştı")
        for bad in (None, "", "abc"):
            self.assertEqual(normalize_score(bad), _panel_score(bad),
                             msg=f"bozuk girdi {bad!r} için parite yok")
        # ters harita paritesi
        for panel in (0.0, 10.0, 52.37, 68.22, 71.54, 90.0, 100.0):
            self.assertAlmostEqual(_raw_from_panel(panel), _panel_to_raw_score(panel),
                                   places=6, msg=f"panel={panel} ters harita ayrıştı")


class SaturationFlagTests(unittest.TestCase):
    """`_score_is_saturated` yalnızca GÖRÜNÜRLÜK; ölçek moduna duyarlı."""

    def test_log_mode_saturates_only_at_ref(self):
        self.assertTrue(_score_is_saturated({"raw_score": REF}))
        self.assertTrue(_score_is_saturated({"raw_score": REF * 2}))
        self.assertFalse(_score_is_saturated({"raw_score": REF - 1}))
        self.assertFalse(_score_is_saturated({"raw_score": 21388.94}),
                         "gözlenen max artık 'kırpıldı' SAYILMAMALI")

    def test_linear_mode_keeps_cap_semantics(self):
        with patch.object(config, "MONITORING_SCORE_NORM_MODE", "linear"):
            self.assertTrue(_score_is_saturated({"raw_score": CAP}))
            self.assertTrue(_score_is_saturated({"raw_score": CAP * 5}))
            self.assertFalse(_score_is_saturated({"raw_score": CAP - 1}))

    def test_unknown_raw_score_is_not_saturated(self):
        self.assertFalse(_score_is_saturated({}))
        self.assertFalse(_score_is_saturated({"raw_score": None}))

    def test_per_row_norm_cap_is_respected_in_linear_mode(self):
        with patch.object(config, "MONITORING_SCORE_NORM_MODE", "linear"):
            self.assertTrue(_score_is_saturated({"raw_score": 1200.0, "norm_cap": 1000.0}))
            self.assertFalse(_score_is_saturated({"raw_score": 1200.0, "norm_cap": 2000.0}))
            self.assertTrue(_score_is_saturated({"raw_score": CAP, "norm_cap": "bozuk"}))
            self.assertEqual(CAP, _row_norm_cap({"norm_cap": "bozuk"}))


class StoredPanelScoreVersionTests(unittest.TestCase):
    """A3: sürüm etiketsiz (A3 öncesi lineer) satırlar ham skordan YENİDEN hesaplanır."""

    def setUp(self):
        self.since = float(config.MONITORING_SCORE_NORM_SINCE)

    def test_current_version_row_used_as_is(self):
        row = {"score": normalize_score(2000.0), "detected_at": self.since + 1000,
               "norm_version": monitoring.MONITORING_SCORE_NORM_VERSION,
               "raw_score": 2000.0}
        self.assertAlmostEqual(normalize_score(2000.0), _stored_panel_score(row), places=6)

    def test_legacy_linear_row_recomputed_from_raw(self):
        """Etiketsiz (lineer) satır ham skordan aktif haritayla yeniden hesaplanır."""
        row = {"score": 100.0, "detected_at": self.since + 1000, "raw_score": 2000.0}
        expected = _panel_from_raw(2000.0)
        self.assertAlmostEqual(expected, _stored_panel_score(row), places=6)
        self.assertLess(expected, 100.0, "lineer 100.00 yerine ayrışan değer gelmeli")

    def test_legacy_row_without_raw_keeps_stored_value(self):
        """Ham skor yoksa kırpılmış değer geri alınamaz → eski değer korunur."""
        row = {"score": 100.0, "detected_at": self.since + 1000}
        self.assertAlmostEqual(100.0, _stored_panel_score(row), places=6)

    def test_pre_since_rows_stay_linear_raw(self):
        """SINCE öncesi kayıtlar HAM skordur → yazıldıkları lineer ölçek + satırın cap'i."""
        row = {"score": 40.0, "detected_at": self.since - 1000, "norm_cap": 40}
        self.assertAlmostEqual(100.0, _stored_panel_score(row), places=1)
        legacy_no_cap = {"score": 40.0, "detected_at": self.since - 1000}
        self.assertAlmostEqual(2.0, _stored_panel_score(legacy_no_cap), places=1)


# --------------------------------------------------------------------------
# Mutasyon notları (doğrulandı):
#  1) log modu kaldırıp lineer'e dönmek        -> no_clipping + monotonic testleri kırılır.
#  2) `_raw_from_panel` log tersini bozmak     -> ReanchoredThreshold + roundtrip kırılır.
#  3) `velocity._panel_score` senkrondan çıkmak-> ScaleParityTests kırılır.
#  4) `_stored_panel_score` sürüm kontrolünü silmek -> legacy_linear testi kırılır.
#  5) Eşikleri eski panel değerlerine (70/85/50/10) döndürmek -> Reanchored testleri kırılır.
# --------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
