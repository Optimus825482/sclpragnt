"""D-08 (2026-09-14): skor DOYGUNLUGU (cap'a kirpilma) — tespit + gorunurluk.

Bulgu: `normalize_score = min(100, raw/CAP*100)` SERT kirpar. Kirpilma REJIME
BAGLI: bu DB'de ham>=2000 orani %0.1 (medyan ham skor 3.0), kullanicinin
13-14.09 tablosunda ise 104 tespitin 100'u TAM 100.00 (%96.2). Ust kusur 100'a
yigildiginda skor siralama yetenegini tamamen kaybeder ve "SKOR >= 90" esigi
anlamsizlasir (her sey gecer).

BILINCLI KARAR — cap YUKSELTILMEDI: panel skoru yalnizca gosterim degil;
`MONITORING_TARGET_SCORE_TIERS` ('90:4.0,70:2.5,50:2.0') hedef bantlari PANEL
olceginde. Cap'i degistirmek her adayin hedefini degistirir = STRATEJI
DEGISTIRME. Proje kurali: OOS kaniti olmadan aktive edilmez.

YAPILAN (additive, sifir davranis degisimi): ham `velocity_score` rapor
API'sine tasindi + `saturated` bayragi. Boylece doygunlukta da SIRA gorunur.

Bu dosya iki seyi kilitler:
  1. `normalize_score` DAVRANISI degismedi (kirpma hâlâ var — bilincli).
  2. Doygunluk DOGRU tespit ediliyor (satir bazli `norm_cap` dahil).
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                    # noqa: E402
from app.routers.monitoring import (             # noqa: E402
    _row_norm_cap, _score_is_saturated, normalize_score,
)

CAP = float(config.MONITORING_SCORE_NORM_CAP)


class NormalizeScoreClipLockTests(unittest.TestCase):
    """Kirpma DAVRANISI korunur (bilincli; degisiklik strateji degisimidir)."""

    def test_cap_maps_to_exactly_100(self):
        self.assertEqual(100.0, normalize_score(CAP))

    def test_above_cap_is_clipped_not_scaled(self):
        """Cap ustu TAM 100 — bu yuzden siralama bilgisi kaybolur (bulgunun ozu)."""
        self.assertEqual(100.0, normalize_score(CAP * 2))
        self.assertEqual(100.0, normalize_score(CAP * 10))
        self.assertEqual(normalize_score(CAP * 2), normalize_score(CAP * 10),
                         "cap ustundeki her sey ayni -> siralama yok")

    def test_below_cap_is_linear(self):
        self.assertAlmostEqual(50.0, normalize_score(CAP / 2), places=9)
        self.assertAlmostEqual(25.0, normalize_score(CAP / 4), places=9)

    def test_zero_and_bad_input(self):
        self.assertEqual(0.0, normalize_score(0))
        self.assertEqual(0.0, normalize_score(None))
        self.assertEqual(0.0, normalize_score("abc"))


class SaturationFlagTests(unittest.TestCase):
    """`_score_is_saturated`: panel 100'a kirpildi mi? (yalnizca gorunurluk)."""

    def test_saturated_at_and_above_cap(self):
        self.assertTrue(_score_is_saturated({"raw_score": CAP}))
        self.assertTrue(_score_is_saturated({"raw_score": CAP * 5}))

    def test_not_saturated_below_cap(self):
        self.assertFalse(_score_is_saturated({"raw_score": CAP - 1}))
        self.assertFalse(_score_is_saturated({"raw_score": 0.0}))

    def test_unknown_raw_score_is_not_saturated(self):
        """Ham skor yoksa bayrak False — veri eksikligi 'kirpildi' demek degil."""
        self.assertFalse(_score_is_saturated({}))
        self.assertFalse(_score_is_saturated({"raw_score": None}))

    def test_per_row_norm_cap_is_respected(self):
        """Satir baska bir cap'le normalize edildiyse O cap kullanilir (R2-03)."""
        self.assertTrue(_score_is_saturated({"raw_score": 1200.0, "norm_cap": 1000.0}))
        self.assertFalse(_score_is_saturated({"raw_score": 1200.0, "norm_cap": 2000.0}))

    def test_malformed_norm_cap_falls_back(self):
        self.assertTrue(_score_is_saturated({"raw_score": CAP, "norm_cap": "bozuk"}))
        self.assertEqual(CAP, _row_norm_cap({"norm_cap": "bozuk"}))


class RankingValueTests(unittest.TestCase):
    """Duzeltmenin DEGERI: panel ayni olsa da ham skor siralar."""

    def test_raw_score_orders_where_panel_cannot(self):
        a, b = CAP * 1.25, CAP * 4.5
        self.assertEqual(normalize_score(a), normalize_score(b), "panel ikisini ayiramaz")
        self.assertLess(a, b, "ham skor hâlâ sıralar — raporda gösterilen değer budur")
        self.assertTrue(_score_is_saturated({"raw_score": a}))
        self.assertTrue(_score_is_saturated({"raw_score": b}))


# --------------------------------------------------------------------------
# Mutasyon notlari (dogrulandi):
#  1) `_score_is_saturated` -> `return False`          -> 4 test kirilir.
#  2) `raw >= cap` -> `raw > cap`                      -> test_saturated_at_and_above_cap kirilir.
#  3) Satir bazli norm_cap yoksayilirsa                -> test_per_row_norm_cap_is_respected kirilir.
#  4) normalize_score kirpmayi kaldirip olceklerse     -> test_above_cap_is_clipped_not_scaled kirilir.
# --------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
