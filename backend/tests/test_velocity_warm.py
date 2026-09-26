"""Warm ("ısınıyor") şeridi testleri — eşiği kıl payı kaçıran aday görünürlüğü.

Kapsam (2026-09-26):
  * ``velocity._warm_gate`` — SAF yardımcı: (a) tüm kapılar geçerse warm False;
    (b) ATR %90 bandında + MACD teyidi → warm True, reason "atr_yaklas",
    proximity ≈ 0.9; (c) en zayıf oran < 0.6 → False; (d) destek sinyali yok →
    False; (e) leading_ok (M1/M3 öncü) → sabit "m1_m3_oncu_atr" / 0.75.
  * ``velocity._warm_list_build`` — warm listesi türetimi (yalnız warm=True,
    proximity desc, ``MONITORING_WARM_LIST_LIMIT`` limiti, kopyasız öğeler).
  * detect_velocity_candidates dönüşünde ``"warm"`` anahtarı KABLOJ duman
    testi: tam entegrasyon ağ/DB gerektirdiği için PAHALI — kaynakta return
    sözlüğüne bağlandığı doğrulanır (davranış testleri mevcut entegrasyon
    testleriyle korunur).

Bu şerit auto-entry'ye HİÇ BAĞLI DEĞİLDİR; testler de yalnız görünürlük
sözleşmesini kilitler. Ağ/DB/sunucu yok (paper-only).
"""
import inspect
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import velocity                    # noqa: E402
from app.routers.velocity import _warm_gate, _warm_list_build  # noqa: E402


def _kapilar(**over) -> dict:
    """TÜM kapıları geçen taban girdi; her test yalnız ilgilendiği kapıyı ezer.

    Oranlar: atr 0.35/0.25=1.4, bb 3.0/2.5=1.2, struct max(0.30/0.20, 60/50)=1.5
    → hepsi ≥ 1.0, failed kümesi boş.
    """
    base = dict(
        prof_atr=0.25,
        atr_pct=0.35,
        bb_width=3.0,
        slope=0.30,
        aroon_up=60.0,
        macd_bullish=True,
        macd_rising=False,
        ret3=0.6,
        volume_ratio=1.5,
        leading_ok=False,
    )
    base.update(over)
    return base


class WarmGateSafTestleri(unittest.TestCase):
    """_warm_gate: saf dönüşüm — (warm, warm_reason, warm_proximity)."""

    def test_a_tum_kapilar_gecerse_warm_false(self):
        """(a) Hiç kapı kaçırılmadıysa warm işareti KONMAZ (geçenler normal akış)."""
        warm, reason, prox = _warm_gate(**_kapilar())
        self.assertFalse(warm)
        self.assertIsNone(reason)
        self.assertEqual(prox, 0.0)

    def test_b_atr_90_bandinda_macd_destekli_warm_true(self):
        """(b) Yalnız ATR eşiğin %90'ında + macd_bullish → "atr_yaklas", ≈0.9."""
        warm, reason, prox = _warm_gate(**_kapilar(atr_pct=0.225))  # 0.225/0.25 = 0.90
        self.assertTrue(warm)
        self.assertEqual(reason, "atr_yaklas")
        self.assertAlmostEqual(prox, 0.9, places=6)

    def test_b2_bb_en_zayif_ise_bb_yaklas(self):
        """En zayıf kapı BB ise reason o kapının adıdır."""
        warm, reason, prox = _warm_gate(**_kapilar(bb_width=1.75))  # 1.75/2.5 = 0.70
        self.assertTrue(warm)
        self.assertEqual(reason, "bb_yaklas")
        self.assertAlmostEqual(prox, 0.7, places=6)

    def test_b3_struct_en_zayif_ise_struct_yaklas(self):
        """struct_oran = max(slope oranı, aroon oranı); ikisi de 0.7 → struct_yaklas."""
        warm, reason, prox = _warm_gate(**_kapilar(slope=0.14, aroon_up=35.0))
        self.assertTrue(warm)
        self.assertEqual(reason, "struct_yaklas")
        self.assertAlmostEqual(prox, 0.7, places=6)

    def test_c_min_oran_06_altinda_warm_false(self):
        """(c) En zayıf kapı eşiğin %60'ının bile altındaysa ısınma yok."""
        warm, reason, prox = _warm_gate(**_kapilar(atr_pct=0.10))  # 0.10/0.25 = 0.40
        self.assertFalse(warm)
        self.assertIsNone(reason)
        self.assertEqual(prox, 0.0)

    def test_c2_bb_verisi_yok_sahte_yakinlik_uretmez(self):
        """bb_width=None → bb oranı 0.0 sayılır → min_oran < 0.6 → warm False."""
        warm, reason, prox = _warm_gate(**_kapilar(bb_width=None))
        self.assertFalse(warm)
        self.assertIsNone(reason)
        self.assertEqual(prox, 0.0)

    def test_d_destek_sinyali_yok_warm_false(self):
        """(d) macd yok, ret3 < 0.5, volume_ratio < 2.0 → destek yok, warm False."""
        warm, reason, prox = _warm_gate(**_kapilar(
            atr_pct=0.225, macd_bullish=False, macd_rising=False,
            ret3=0.3, volume_ratio=1.5))
        self.assertFalse(warm)
        self.assertIsNone(reason)
        self.assertEqual(prox, 0.0)

    def test_d2_hacim_patlamasi_tek_basina_destek_sayar(self):
        """Destek sinyali MACD'siz de kurulabilir: volume_ratio ≥ 2.0 → warm."""
        warm, reason, _ = _warm_gate(**_kapilar(
            atr_pct=0.225, macd_bullish=False, macd_rising=False,
            ret3=0.2, volume_ratio=2.4))
        self.assertTrue(warm)
        self.assertEqual(reason, "atr_yaklas")

    def test_e_leading_ok_sabit_yuksek_guven(self):
        """(e) M1/M3 öncü kesişim → "m1_m3_oncu_atr", 0.75; kapı durumundan bağımsız."""
        warm, reason, prox = _warm_gate(**_kapilar(
            leading_ok=True, atr_pct=0.05, bb_width=0.5, slope=-1.0, aroon_up=0.0))
        self.assertTrue(warm)
        self.assertEqual(reason, "m1_m3_oncu_atr")
        self.assertAlmostEqual(prox, 0.75, places=6)

    def test_f_negatif_egim_proximityyi_negatif_yapmaz(self):
        """Aşağı eğim (negatif oran) 0'a kırpılır; proximity negatif çıkamaz."""
        warm, _, prox = _warm_gate(**_kapilar(
            slope=-0.5, aroon_up=0.0, macd_bullish=True))
        # struct kapısı 0.0 oranla kaçırıldı → min_oran 0.0 < 0.6 → warm False,
        # ama proximity değeri her koşulda 0..1 bandında kalmalı.
        self.assertGreaterEqual(prox, 0.0)
        self.assertLessEqual(prox, 1.0)
        self.assertFalse(warm)


class WarmListTuretimiTestleri(unittest.TestCase):
    """_warm_list_build: warm listesi = candidates+watchlist ∩ warm=True, proximity desc."""

    def test_sadece_warm_true_ve_yakinliga_gore_sirali(self):
        cand = {"symbol": "AAA", "warm": True, "warm_proximity": 0.7}
        w_close = {"symbol": "BBB", "warm": True, "warm_proximity": 0.95}
        w_cold = {"symbol": "CCC", "warm": False, "warm_proximity": 0.9}
        w_spread = {"symbol": "DDD"}  # asiri_spread return'u gibi warm alanı yok
        out = _warm_list_build([cand], [w_close, w_cold, w_spread])
        self.assertEqual([r["symbol"] for r in out], ["BBB", "AAA"])
        # Öğe KOPYA DEĞİL: aday sözlüğünün kendisi döner (aynı nesne kimliği).
        self.assertIs(out[0], w_close)
        self.assertIs(out[1], cand)

    def test_limit_monitring_ayarindan_alinir(self):
        rows = [{"symbol": f"S{i}", "warm": True, "warm_proximity": 0.6 + i / 100}
                for i in range(5)]
        with patch.object(velocity.config, "MONITORING_WARM_LIST_LIMIT", 2):
            out = _warm_list_build([], rows)
        self.assertEqual(len(out), 2)
        # proximity desc: en yakın ilk ikisi kalır.
        self.assertEqual([r["symbol"] for r in out], ["S4", "S3"])

    def test_bozuk_limit_degeri_varsayilana_duser(self):
        rows = [{"symbol": f"S{i}", "warm": True, "warm_proximity": 0.6} for i in range(3)]
        with patch.object(velocity.config, "MONITORING_WARM_LIST_LIMIT", "bozuk"):
            out = _warm_list_build([], rows)
        self.assertEqual(len(out), 3)  # getattr varsayılanı 12 → tümü


class WarmKablojDumanTesti(unittest.TestCase):
    """detect_velocity_candidates → "warm" anahtarı kabloj doğrulaması.

    Tam entegrasyon (ticker_24h + klines + DB) ağ gerektirdiği için test
    PAHALI; burada yalnız kablajın VARLIĞI kilitlenir: return sözlüğünde
    "warm" listesi, scan_one return'lerinde warm alanları ve _warm_gate
    çağrısı kaynakta bulunmalı. Davranışsal regresyon mevcut entegrasyon
    testleriyle (test_m2_velocity_fixes vb.) yakalanır.
    """

    def test_detect_return_ve_scan_one_warm_alanlari_bagli(self):
        src = inspect.getsource(velocity.detect_velocity_candidates)
        # Dönüş sözlüğündeki warm listesi:
        self.assertIn('"warm": warm_list', src)
        # scan_one _warm_gate'i çağırıyor ve return'lerine warm alanlarını
        # yazıyor (ML kapısı + ana return; asiri_spread return'ü bilinçli
        # olarak warm'suz kalır):
        self.assertIn("_warm_gate(", src)
        self.assertIn('"warm": warm,', src)
        self.assertIn('"warm_reason": warm_reason,', src)
        self.assertIn('"warm_proximity": round(warm_proximity, 3)', src)
        # passes=True adaylar ısınmaz (auto-entry'ye dokunma garantisi):
        self.assertIn("if not passes and exhausted is None and not rejection_wick:", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
