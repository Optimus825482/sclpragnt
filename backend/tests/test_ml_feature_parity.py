"""Eğitim (vektörel) ve çıkarım (skaler) gösterge tanımlarının parity testi.

2026-09-10 (E6): Aynı isimli ML özellikleri eğitim ve çıkarımda FARKLI
tanımlarla hesaplanıyordu:

  | Özellik              | Eğitim (öncesi)          | Çıkarım (öncesi)        |
  |----------------------|--------------------------|-------------------------|
  | rsi14                | SMA ortalamalı RSI       | Wilder RSI              |
  | aroon_up25/down25    | kapanış, periyot 14      | high/low, periyot 25    |
  | linreg_slope10_pct   | 10 bar, kesir/bar        | 20 bar, yüzde/bar×10    |

Bu test, modelin gölge tahminlerinin sessizce anlamsızlaşmasını önleyen
kalıcı garddır: vektörel eğitim hesabı ile kanonik skaler (`technical_analysis`)
hesabı AYNI girdi penceresinde AYNI sonucu vermelidir.
"""
import numpy as np
import unittest

from app.ml_forecast import build_symbol_dataset, _wilder_rsi_series
from app.technical_analysis import _aroon, _linreg_slope_pct, _rsi


def _synthetic_series(n=2500, seed=42):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.0015, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.0008, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0008, n)))
    volume = np.abs(rng.normal(1000, 200, n))
    open_time = (np.arange(n, dtype=np.int64) * 300_000) + 1_700_000_000_000
    return open_time, high, low, close, volume


class FeatureParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n = 2500
        cls.ot, cls.h, cls.l, cls.c, cls.v = _synthetic_series(cls.n)
        # 5m bar verisi (üretimde kullanılan yol)
        cls.ds = build_symbol_dataset(cls.ot, cls.h, cls.l, cls.c, cls.v, 0, bar_minutes=5)
        cls.feats = cls.ds["features"]

    def test_wilder_rsi_vectorized_matches_canonical_scalar(self):
        series = _wilder_rsi_series(self.c, 14)
        checked = 0
        for t in range(200, self.n, 37):
            ref = _rsi(self.c[:t + 1], 14)
            if ref is None:
                continue
            checked += 1
            self.assertAlmostEqual(ref, float(series[t]), places=9,
                                   msg=f"RSI parity bozuldu t={t}")
        self.assertGreater(checked, 40, "yeterli örnek karşılaştırılmadı")

    def test_aroon_vectorized_matches_canonical_scalar(self):
        up_col, down_col = self.feats[:, 9], self.feats[:, 10]
        checked = 0
        for t in range(200, self.n, 41):
            ref = _aroon(self.h[:t + 1], self.l[:t + 1], 25)
            if ref is None:
                continue
            checked += 1
            self.assertAlmostEqual(ref["up"], float(up_col[t]), places=3,
                                   msg=f"Aroon up parity bozuldu t={t}")
            self.assertAlmostEqual(ref["down"], float(down_col[t]), places=3,
                                   msg=f"Aroon down parity bozuldu t={t}")
        self.assertGreater(checked, 40, "yeterli örnek karşılaştırılmadı")

    def test_aroon_uses_high_and_low_not_close(self):
        """Kanonik tanım: Up=HIGH, Down=LOW. Kapanış tabanlı hesap regresyon sayılır."""
        diverged = 0
        for t in range(60, self.n, 17):
            ref = _aroon(self.h[:t + 1], self.l[:t + 1], 25)
            if ref is None:
                continue
            # model kolonu HER ZAMAN kanonik high/low tanımıyla eşleşmeli
            self.assertAlmostEqual(ref["up"], float(self.feats[t, 9]), places=3,
                                   msg=f"Aroon up kanonik tanımdan saptı t={t}")
            self.assertAlmostEqual(ref["down"], float(self.feats[t, 10]), places=3,
                                   msg=f"Aroon down kanonik tanımdan saptı t={t}")
            close_only = _aroon(self.c[:t + 1], self.c[:t + 1], 25)
            if close_only is not None and (
                    abs(close_only["up"] - ref["up"]) > 1e-6
                    or abs(close_only["down"] - ref["down"]) > 1e-6):
                diverged += 1
        # Kapanış ve high/low tanımları bu seride ayrışmalı; aksi halde test
        # yanlış tanıma geri dönüşü yakalayamaz (boş gard olurdu).
        self.assertGreater(diverged, 0,
                           "kapanış ve high/low Aroon'u hiç ayrışmadı — test zayıf")

    def test_linreg_slope_vectorized_matches_canonical_scalar(self):
        col = self.feats[:, 8]  # eğitim sütunu KESİR tutar
        checked = 0
        for t in range(200, self.n, 53):
            ref = _linreg_slope_pct(self.c[:t + 1], 10)
            if ref is None:
                continue
            checked += 1
            # sözleşme: *_pct alanı YÜZDE; eğitim sütunu kesir (= yüzde/100)
            self.assertAlmostEqual(ref / 100.0, float(col[t]), places=9,
                                   msg=f"LinReg parity bozuldu t={t}")
        self.assertGreater(checked, 30, "yeterli örnek karşılaştırılmadı")

    def test_feature_names_reflect_canonical_indicators(self):
        """Özellik adları kanonik periyotları yansıtmalı (aroon 25)."""
        from app.ml_forecast import FEATURE_NAMES, FEATURE_VERSION
        self.assertIn("aroon_up25", FEATURE_NAMES)
        self.assertIn("aroon_down25", FEATURE_NAMES)
        self.assertNotIn("aroon_up14", FEATURE_NAMES)
        self.assertNotIn("aroon_down14", FEATURE_NAMES)
        self.assertEqual("v3", FEATURE_VERSION, "gösterge tanımı değişti → sürüm artmalı")


class AroonDefinitionTests(unittest.TestCase):
    """Aroon tanımının standart ve tek olduğunu kilitler (E6 / OOS doğrulaması)."""

    def test_aroon_covers_full_0_100_range(self):
        """Standart tanım: pencere period+1 → değer tam 0..100 aralığını kapsar."""
        # Zirve en eski barda → up = 0; en yeni barda → up = 100
        highs_old = [10.0] + [1.0] * 25
        lows_old = [1.0] + [5.0] * 25
        res_old = _aroon(highs_old, lows_old, 25)
        self.assertAlmostEqual(res_old["up"], 0.0, places=6)
        highs_new = [1.0] * 25 + [10.0]
        lows_new = [5.0] * 25 + [1.0]
        res_new = _aroon(highs_new, lows_new, 25)
        self.assertAlmostEqual(res_new["up"], 100.0, places=6)
        self.assertAlmostEqual(res_new["down"], 100.0, places=6)

    def test_aroon_tie_break_prefers_most_recent(self):
        """Eşit zirvelerde SON oluşum esas alınır ('zirveyi şimdi test ediyor' = 0 bar)."""
        # Aynı zirve değeri hem 25 bar önce hem SON barda
        highs = [10.0] + [1.0] * 24 + [10.0]
        lows = [1.0] * 26
        res = _aroon(highs, lows, 25)
        self.assertAlmostEqual(res["up"], 100.0, places=6,
                               msg="eşitlikte ilk oluşum alınmış (kanonik: son)")

    def test_velocity_aroon_matches_canonical_on_tie_heavy_data(self):
        """Velocity ve kanonik Aroon birebir aynı olmalı (eşik kayması olmasın)."""
        from app.routers.velocity import _velocity_aroon
        # Düşük fiyatlı/stablecoin benzeri: çok sayıda tekrar eden fiyat
        rng = np.random.default_rng(3)
        base = np.round(rng.normal(1.0, 0.0005, 400), 6)
        highs = list(base * 1.0002)
        lows = list(base * 0.9998)
        for t in range(30, 400, 7):
            canonical = _aroon(highs[:t], lows[:t], 25)
            legacy_named = _velocity_aroon(highs[:t], lows[:t])
            if canonical is None:
                self.assertIsNone(legacy_named)
                continue
            self.assertAlmostEqual(canonical["up"], legacy_named["up"], places=9)
            self.assertAlmostEqual(canonical["down"], legacy_named["down"], places=9)


class MfiParityTests(unittest.TestCase):
    """D-10 (2026-09-26) — MFI eğitim/çıkarım sapması.

    ``ml_forecast.build_symbol_dataset`` MFI'yı ``neg_sum == 0`` iken NaN
    üretiyordu; çıkarımda aynı özellik (``technical_analysis._mfi`` ve
    ``routers/velocity._velocity_mfi``) 100.0 / 50.0 dönüyordu. Aynı ad,
    iki farklı dağılım: modelin öğrendiği "MFI yok" deseni çıkarımda hiç
    üretilmiyor, çıkarımdaki nötr/extrem değerler eğitimde hiç görünmüyordu.

    Bu test GERÇEK referans dizilerle eğitim sütununu kanonik skaler MFI'ye
    karşı karşılaştırır (parity listesinde MFI kolonu yoktu).
    """

    def _series(self, n, seed):
        rng = np.random.default_rng(seed)
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
        high = close * (1 + np.abs(rng.normal(0, 0.001, n)))
        low = close * (1 - np.abs(rng.normal(0, 0.001, n)))
        volume = np.abs(rng.normal(1000, 250, n))
        open_time = (np.arange(n, dtype=np.int64) * 300_000) + 1_700_000_000_000
        return open_time, high, low, close, volume

    def test_mfi_vectorized_matches_canonical_scalar_on_real_data(self):
        from app.technical_analysis import _mfi

        n = 800
        ot, h, l, c, v = self._series(n, seed=11)
        feats = build_symbol_dataset(ot, h, l, c, v, 0, bar_minutes=5)["features"]
        col = feats[:, 6]  # mfi14
        checked = 0
        for t in range(20, n, 7):
            ref = _mfi(list(h[:t + 1]), list(l[:t + 1]), list(c[:t + 1]), list(v[:t + 1]), 14)
            if ref is None:
                continue
            got = float(col[t])
            self.assertTrue(np.isfinite(got), f"eğitim MFI'si NaN üretti t={t} (çıkarımda değil)")
            # Özellik matrisi float32; tolerans float32 hassasiyetine göre.
            self.assertAlmostEqual(ref, got, places=4,
                                   msg=f"MFI parity bozuldu t={t} (kanonik={ref}, eğitim={got})")
            checked += 1
        self.assertGreater(checked, 60, "yeterli örnek karşılaştırılmadı")

    def test_mfi_never_emits_nan_after_warmup(self):
        """neg_sum == 0 iken NaN yerine 100.0 (pozitif akış) / 50.0 (yok)."""
        n = 400
        ot, h, l, c, v = self._series(n, seed=12)
        feats = build_symbol_dataset(ot, h, l, c, v, 0, bar_minutes=5)["features"]
        col = feats[:, 6]
        warm = col[14:]
        self.assertTrue(np.isfinite(warm).all(),
                        f"ısınma sonrası MFI NaN üretti: {int((~np.isfinite(warm)).sum())} bar")
        self.assertGreaterEqual(float(np.nanmin(warm)), 0.0)
        self.assertLessEqual(float(np.nanmax(warm)), 100.0)

    def test_monotonic_uptrend_is_mfi_100_and_downtrend_is_0(self):
        """Tek yönlü akış: yalnız yükseliş → 100.0, yalnız düşüş → ~0.0."""
        n = 60
        up_c = 100 + np.arange(n) * 0.5
        up_h, up_l = up_c + 0.2, up_c - 0.2
        up_v = np.full(n, 1000.0)
        ot = (np.arange(n, dtype=np.int64) * 300_000) + 1_700_000_000_000
        up = build_symbol_dataset(ot, up_h, up_l, up_c, up_v, 0, bar_minutes=5)["features"][:, 6]
        self.assertAlmostEqual(float(up[-1]), 100.0, places=6,
                               msg="tek yönlü yükselişte MFI 100 olmalı (NaN değil)")

        dn_c = 200 - np.arange(n) * 0.5
        dn_h, dn_l = dn_c + 0.2, dn_c - 0.2
        dn = build_symbol_dataset(ot, dn_h, dn_l, dn_c, up_v, 0, bar_minutes=5)["features"][:, 6]
        self.assertAlmostEqual(float(dn[-1]), 0.0, places=6,
                               msg="tek yönlü düşüşte MFI 0 olmalı")

    def test_flat_prices_give_neutral_50_not_nan(self):
        """Düz fiyat + sıfır hacim → akış yok → kanonik nötr 50.0."""
        n = 40
        c = np.full(n, 100.0)
        h, l = c + 0.1, c - 0.1
        v = np.zeros(n)
        ot = (np.arange(n, dtype=np.int64) * 300_000) + 1_700_000_000_000
        got = build_symbol_dataset(ot, h, l, c, v, 0, bar_minutes=5)["features"][:, 6]
        self.assertAlmostEqual(float(got[-1]), 50.0, places=6,
                               msg="akış yokken nötr 50.0 beklenir (NaN değil)")

    def test_velocity_mfi_matches_canonical_on_real_data(self):
        """velocity'nin kendi MFI kopyası kanonikle aynı olmalı (eşik kayması)."""
        from app.routers.velocity import _velocity_mfi
        from app.technical_analysis import _mfi

        n = 500
        ot, h, l, c, v = self._series(n, seed=13)
        checked = 0
        for t in range(20, n, 11):
            ref = _mfi(list(h[:t + 1]), list(l[:t + 1]), list(c[:t + 1]), list(v[:t + 1]), 14)
            got = _velocity_mfi(list(h[:t + 1]), list(l[:t + 1]), list(c[:t + 1]), list(v[:t + 1]))
            if ref is None or got is None:
                continue
            self.assertAlmostEqual(ref, float(got), places=4,
                                   msg=f"velocity MFI kanonikten saptı t={t}")
            checked += 1
        self.assertGreater(checked, 20, "yeterli örnek karşılaştırılmadı")


if __name__ == "__main__":
    unittest.main()
