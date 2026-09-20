"""M2 — velocity hedef-bant / MFE penceresi düzeltmelerinin kilit testleri.

Kapsanan bulgular (2026-09-12 denetimi):
  * R2-01 / R3-03 (P0) — hedef bantları PANEL ölçeğinde; çağrıya ham skor
    veriliyordu → her bildirim 4.0%. Fix: ``_panel_score`` ile normalize et.
  * R5-C3.4 / R2-12 (P2) — tier ayrıştırıcı ilk eşleşmede duruyordu; artan
    sıralı liste monoton olmayan hedef üretiyordu. Fix: TÜM bantları ayrıştır,
    en yüksek eşleşen eşiği seç.
  * R5-C4.4 (P0) — sinyal anını içeren parsiyel mum MFE penceresine dahildi
    (sinyal-öncesi hareket şişiriyordu). Fix: ``_post_signal_window``.
  * R3-14 (P2) — hedef, gidiş-dönüş maliyetinin altına inmemeli.
  * R5-C3.4 (P2) — determinizm + monotonicity.

Bu dosya salt-okunur/hesap testleri içerir; ağ/DB/sunucu yok (paper-only).
"""
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                     # noqa: E402
from app.routers import velocity                  # noqa: E402
from app.routers.monitoring import normalize_score  # noqa: E402  (kanonik panel formülü)
from app.routers.velocity import (                # noqa: E402
    _mfe_from_window, _panel_score, _parse_target_tiers, _post_signal_window,
    _velocity_raw_score_gate, _velocity_mfi, dynamic_target_pct, upside_rank_score,
)
from app.technical_analysis import _mfi           # noqa: E402

_DEFAULT_TIERS = "90:4.0,70:2.5,50:2.0"


def _raw_for_panel(panel: float) -> float:
    """Panel skorunu (0-100) ham velocity_score'a çevirir — AKTİF haritanın tersi.

    A3 (2026-09-14): harita log olduğundan ters dönüşüm doğrusal DEĞİL
    (monitoring._raw_from_panel kanonik kaynak).
    """
    from app.routers.monitoring import _raw_from_panel
    return float(_raw_from_panel(panel))


class PanelScoreLockTests(unittest.TestCase):
    """R2-01/R3-03: ``_panel_score`` kanonik ``monitoring.normalize_score`` ile eşit."""

    def test_panel_score_matches_monitoring_normalize_score(self):
        for raw in (0, 1.0, 100, 500, 1000, 1399, 1400, 1800, 2000, 4000, 161709.0):
            self.assertEqual(normalize_score(raw), _panel_score(raw),
                             msg=f"raw={raw} için panel skor ayrıştı")
        # bozuk girdi paritesi
        for bad in (None, "", "abc"):
            self.assertEqual(normalize_score(bad), _panel_score(bad),
                             msg=f"bozuk girdi {bad!r} için parite yok")

    def test_raw_to_target_mapping_uses_panel_scale(self):
        """Ham skorun PANEL karşılığı doğru banda düşmeli (base 1.5 ile ayrışır).

        A3 (2026-09-14) sonrası bant eşikleri: 74.0 → 4.0 | 71.5 → 2.5 | 68.2 → 2.0
        (eski 90/70/50'nin ham çalışma noktaları korunarak yeniden ankrajlandı).
        Maliyet tabanı (2026-09-19) bant ayrışmasını gölgelemesin diye
        maliyet bileşenleri sıfırlanır — bu test bant haritasını kilitler.
        """
        base = float(config.MONITORING_TARGET_PCT_MIN)  # 1.5
        with patch.object(config, "SCALPING_NET_TARGET_PCT", 0.0), \
             patch.object(config, "DEFAULT_ESTIMATED_SPREAD_PCT", 0.0):
            # panel 95 → üst bant (4.0)
            self.assertEqual(4.0, dynamic_target_pct(_panel_score(_raw_for_panel(95)), base))
            # panel 72.5 → orta bant (2.5)
            self.assertEqual(2.5, dynamic_target_pct(_panel_score(_raw_for_panel(72.5)), base))
            # panel 69.5 → alt bant (2.0)
            self.assertEqual(2.0, dynamic_target_pct(_panel_score(_raw_for_panel(69.5)), base))
            # panel 30 → hiçbir bant → baz (1.5'e kelepçeli taban)
            self.assertEqual(base, dynamic_target_pct(_panel_score(_raw_for_panel(30)), base))

    def test_gate_passing_raw_no_longer_always_hits_top_band(self):
        """Kapıyı geçen (ham≥1400) ama panel<74.0 olan aday artık 4.0 ALMAZ.

        Eski kod ham skoru geçirdiğinden 1400 → 4.0 veriyordu; yeni kodda
        ham 1400 = panel 71.5 → orta bant (2.5).
        """
        with patch.object(config, "SCALPING_NET_TARGET_PCT", 0.0), \
             patch.object(config, "DEFAULT_ESTIMATED_SPREAD_PCT", 0.0):
            self.assertEqual(2.5, dynamic_target_pct(_panel_score(1400), 2.0))
            # ham 1800 = panel 74.0 → üst bant
            self.assertEqual(4.0, dynamic_target_pct(_panel_score(1800), 2.0))


class TierParserRobustnessTests(unittest.TestCase):
    """R5-C3.4 / R2-12: tüm bantlar ayrıştırılır; seçim sıradan bağımsız."""

    def setUp(self):
        # A3 (2026-09-14): tearDown'a SABİT bir varsayılan yazmak, `config`
        # paylaşılan modül nesnesi olduğu için diğer test dosyalarına sızıyordu
        # (varsayılan 90/70/50 → 74.0/71.5/68.2 değişti). Orijinali saklayıp
        # geri koymak testleri SIRADAN BAĞIMSIZ yapar.
        self._orig_tiers = config.MONITORING_TARGET_SCORE_TIERS
        # Maliyet tabanı (2026-09-19 net-kâr güvencesi) bant ayrışmasını
        # gölgelemesin: bu testler yalnız tier/bant davranışını kilitler.
        self._orig_net = config.SCALPING_NET_TARGET_PCT
        self._orig_spread = config.DEFAULT_ESTIMATED_SPREAD_PCT
        config.SCALPING_NET_TARGET_PCT = 0.0
        config.DEFAULT_ESTIMATED_SPREAD_PCT = 0.0

    def tearDown(self):
        config.MONITORING_TARGET_SCORE_TIERS = self._orig_tiers
        config.SCALPING_NET_TARGET_PCT = self._orig_net
        config.DEFAULT_ESTIMATED_SPREAD_PCT = self._orig_spread

    def test_all_bands_parsed(self):
        self.assertEqual([(90.0, 4.0), (70.0, 2.5), (50.0, 2.0)],
                         _parse_target_tiers(_DEFAULT_TIERS))

    def test_malformed_pairs_skipped(self):
        self.assertEqual([(70.0, 2.5), (50.0, 2.0)],
                         _parse_target_tiers("70:2.5,oops,50:2.0,80,abc:"))

    def test_empty_and_garbage_yield_base(self):
        for tiers in ("", "abc", "90", None):
            with patch.object(config, "MONITORING_TARGET_SCORE_TIERS", tiers):
                self.assertEqual(2.0, dynamic_target_pct(95.0, 2.0))

    def test_ascending_tiers_select_highest_matching_threshold(self):
        """Artan sıralı liste ARTIK monoton ve doğru (eski `break` bozuyordu)."""
        with patch.object(config, "MONITORING_TARGET_SCORE_TIERS",
                          "50:2.0,70:2.5,90:4.0"):
            base = 1.5
            self.assertEqual(2.0, dynamic_target_pct(60.0, base))   # yalnız 50 eşiği
            self.assertEqual(2.5, dynamic_target_pct(80.0, base))   # en yüksek: 70
            self.assertEqual(4.0, dynamic_target_pct(95.0, base))   # en yüksek: 90

    def test_order_independent_descending_vs_ascending(self):
        """Aynı bant kümesi, farklı sıra → aynı sonuç (determinizm)."""
        for score in (30.0, 55.0, 75.0, 95.0):
            with patch.object(config, "MONITORING_TARGET_SCORE_TIERS",
                              "90:4.0,70:2.5,50:2.0"):
                desc = dynamic_target_pct(score, 2.0)
            with patch.object(config, "MONITORING_TARGET_SCORE_TIERS",
                              "50:2.0,70:2.5,90:4.0"):
                asc = dynamic_target_pct(score, 2.0)
            self.assertEqual(desc, asc, msg=f"score={score} sıraya bağlı!")


class MfePartialBarTests(unittest.TestCase):
    """R5-C4.4: sinyal anını içeren parsiyel mum MFE penceresinden HARİÇ."""

    # Sinyal anı bir dakikanın 50. saniyesinde: bar 10:00'da açıldı, sinyal 10:00:50.
    BAR0_OPEN = 600_000
    CREATED_MS = BAR0_OPEN + 50_000
    DUE_MS = CREATED_MS + 5 * 60_000

    def _rows(self):
        # [open_ms, open, high, low, close, volume]
        return [
            # Parsiyel mum: sinyal anını İÇERİR; sinyal-öncesi 105 spike'ı.
            [self.BAR0_OPEN, 100.0, 105.0, 99.5, 100.2, 10.0],
            # Sinyal sonrası dürüst barlar: en yüksek 100.5.
            [660_000, 100.2, 100.5, 100.0, 100.3, 10.0],
            [720_000, 100.3, 100.5, 100.1, 100.4, 10.0],
            [780_000, 100.4, 100.5, 100.2, 100.4, 10.0],
            [840_000, 100.4, 100.5, 100.2, 100.4, 10.0],
            # Kapanışı due_ms'i AŞAN bar (900000+59999 > 950000) → hariç.
            [900_000, 100.4, 100.5, 100.2, 100.4, 10.0],
        ]

    def test_partial_bar_excluded_exact_scenario(self):
        rows = self._rows()
        window = _post_signal_window(rows, self.CREATED_MS, self.DUE_MS)
        opens = [int(r[0]) for r in window]
        # parsiyel mum (600000) ve due'yu aşan mum (900000) pencerede OLMAMALI
        self.assertNotIn(self.BAR0_OPEN, opens)
        self.assertNotIn(900_000, opens)
        self.assertEqual([660_000, 720_000, 780_000, 840_000], opens)

        entry = 100.0
        mfe = _mfe_from_window(window, entry)
        self.assertAlmostEqual(0.5, mfe, places=6)
        target_pct = 2.0
        self.assertFalse(mfe >= target_pct, "sahte 'hedefe dokundu' (R5-C4.4) nüksetti")

    def test_old_filter_would_have_inflated_mfe(self):
        """Regresyon kontrastı: eski filtre parsiyel mumu dahil edip MFE'yi şişiriyordu."""
        rows = self._rows()
        old_window = [r for r in rows
                      if int(r[0]) + 59_999 > self.CREATED_MS and int(r[0]) + 59_999 <= self.DUE_MS]
        old_mfe = _mfe_from_window(old_window, 100.0)
        self.assertAlmostEqual(5.0, old_mfe, places=6)   # sinyal-öncesi spike
        self.assertTrue(old_mfe >= 2.0)                  # yanlış "touched"

    def test_bar_opening_exactly_at_signal_is_included(self):
        created = 660_000  # dakika başında sinyal → bar tamamen sinyal-sonrası
        rows = [[660_000, 100.0, 101.0, 99.9, 100.5, 1.0],
                [720_000, 100.5, 100.6, 100.4, 100.5, 1.0]]
        window = _post_signal_window(rows, created, created + 5 * 60_000)
        self.assertEqual([660_000, 720_000], [int(r[0]) for r in window])

    def test_empty_and_bad_entry_are_safe(self):
        self.assertIsNone(_mfe_from_window([], 100.0))
        self.assertIsNone(_mfe_from_window(self._rows()[1:2], 0.0))


class TargetCostFloorTests(unittest.TestCase):
    """R3-14: hedef, gidiş-dönüş maliyet + slippage'ın altına inmez."""

    def test_target_never_below_roundtrip_cost_default_order(self):
        floor = config.min_net_exit_pct(config.DEFAULT_ORDER_USDT) * 100
        self.assertLess(floor, config.MONITORING_TARGET_PCT_MIN)  # belgelenmiş marj
        for base in (1.5, 2.0, 3.0):
            for score in [s / 2.0 for s in range(0, 201)]:  # 0..100 adım 0.5
                self.assertGreaterEqual(dynamic_target_pct(score, base), floor,
                                        msg=f"base={base} score={score} maliyet altı!")

    def test_target_never_below_roundtrip_cost_smallest_order(self):
        """En küçük otonom emir (AUTO_PAPER_MIN_ORDER_TRY) maliyeti de aşılmamalı."""
        smallest = config.min_net_exit_pct(config.AUTO_PAPER_MIN_ORDER_TRY) * 100
        for base in (1.5, 2.0, 3.0):
            for score in (0.0, 10.0, 55.0, 75.0, 95.0, 100.0):
                self.assertGreaterEqual(dynamic_target_pct(score, base), smallest,
                                        msg=f"base={base} score={score} < {smallest}")


class DeterminismMonotonicityTests(unittest.TestCase):
    """R5-C3.4: tekrarlı çağrı deterministik; varsayılan tier'da skorla monoton.

    Not: `patch.object` zaten geri alır; tearDown'a SABİT varsayılan yazmak
    paylaşılan `config` nesnesi üzerinden diğer test dosyalarına sızıyordu
    (A3 sonrası varsayılan 74.0/71.5/68.2 oldu).
    """

    def test_repeated_calls_deterministic(self):
        with patch.object(config, "MONITORING_TARGET_SCORE_TIERS", _DEFAULT_TIERS):
            first = [dynamic_target_pct(score, 2.0) for score in range(0, 101)]
            for _ in range(5):
                again = [dynamic_target_pct(score, 2.0) for score in range(0, 101)]
                self.assertEqual(first, again)

    def test_monotonic_non_decreasing_under_default_tiers(self):
        with patch.object(config, "MONITORING_TARGET_SCORE_TIERS", _DEFAULT_TIERS):
            for base in (1.5, 2.0, 3.0):
                prev = None
                for score in [s / 2.0 for s in range(0, 301)]:  # 0..150 adım 0.5
                    val = dynamic_target_pct(score, base)
                    if prev is not None:
                        self.assertGreaterEqual(val, prev,
                                                msg=f"base={base} score={score} azaldı!")
                    prev = val


class UpsideRankClampTests(unittest.TestCase):
    """upside_rank_score kelepçe sırası: upside_rate KELEPLENMİŞ target'tan.

    Eski hata: ``upside_rate = target / horizon`` kelempeden ÖNCE hesaplanıp
    dönüşte KELEMPSİZ değer kullanılıyordu → clamp ölü koddu ve zayıf skorlu
    adayın şişirilmiş ML hedefi sıralamayı haksız şişiriyordu.
    """

    def test_weak_score_inflated_ml_target_ranks_lower(self):
        cand = {"symbol": "WEAKTRY", "horizon_minutes": 5,
                "target_pct": 5.0, "velocity_score": 8.0}  # skor<10, target>4 → clamp
        clamped = upside_rank_score(cand)
        # Kelepçe: target = min(5.0, 8*0.3=2.4) = 2.4 → rate = 2.4/5 = 0.48
        self.assertAlmostEqual(0.48 * 8.0, clamped, places=9)
        # Eski (bozuk) davranış kelempsiz 5/5=1.0 rate kullanıyordu:
        unclamped_legacy = (5.0 / 5) * 8.0
        self.assertLess(clamped, unclamped_legacy,
                        "şişirilmiş ML hedefi zayıf adayı hâlâ öne taşıyor!")

    def test_strong_score_target_not_clamped(self):
        cand = {"symbol": "STRGTRY", "horizon_minutes": 5,
                "target_pct": 5.0, "velocity_score": 30.0}
        self.assertAlmostEqual((5.0 / 5) * 30.0, upside_rank_score(cand), places=9)


class DynamicTargetWeakScoreClampTests(unittest.TestCase):
    """dynamic_target_pct aynı zayıf-skor kelepçesini uygulamalı (TP enflasyonu).

    Zayıf skorlarda kelepçe maliyet tabanının %75'ine sabitlenir (floor*0.75);
    TP, tabanın ÜSTÜNE taşamaz ama taban*0.75 altına da inmez (R3-14 korunur).
    """

    def setUp(self):
        self._floor = round(config.SCALPING_NET_TARGET_PCT + config.DEFAULT_ESTIMATED_SPREAD_PCT
                            + float(config.round_trip_cost()) * 100, 3)

    def test_weak_score_ml_target_clamped(self):
        # panel skor 5 + şişirilmiş ML hedefi 6.0 (güven yüksek) → kelepçe
        # floor*0.75; eski davranış 6.0 (TP enflasyonu) ya da 1.5 verirdi.
        self.assertEqual(round(self._floor * 0.75, 3),
                         dynamic_target_pct(5.0, 2.0, ml_pct=6.0, ml_prob=0.9))

    def test_weak_score_learned_target_clamped(self):
        # Yeterli örnek sayısıyla öğrenilmiş hedef uygulanır ve zayıf skorda
        # kelepçelenir — kelepçe yine maliyet tabanının altına inmez.
        self.assertEqual(round(self._floor * 0.75, 3),
                         dynamic_target_pct(5.0, 2.0, learned_pct=5.0, learned_count=3))

    def test_strong_score_not_clamped(self):
        self.assertEqual(4.0, dynamic_target_pct(95.0, 2.0, ml_pct=4.0, ml_prob=0.9))


class NetProfitFloorTests(unittest.TestCase):
    """Kullanıcı kuralı (2026-09-19): maliyet sonrası NET kâr garantili hedef.

    Brüt hedef (TP) = SCALPING_NET_TARGET_PCT + spread + round_trip maliyet.
    Varsayılan: 2.0 + 0.65 + 0.35 = %3.00 → maliyet sonrası net %2.00 kalır.
    """

    def test_floor_equals_net_plus_costs_in_mid_band(self):
        # Skor 70 → alt bant 2.0 seçilir ama net-kâr tabanı (3.0) onu AŞAR →
        # dönen hedef birebir taban olmalı.
        expected = round(config.SCALPING_NET_TARGET_PCT + config.DEFAULT_ESTIMATED_SPREAD_PCT
                         + float(config.round_trip_cost()) * 100, 3)
        self.assertEqual(expected, dynamic_target_pct(70.0, 1.0))

    def test_strong_band_stays_above_floor(self):
        # Üst bant (4.0) tabanın üstünde kalır — floor yalnız taban, tavan değil.
        self.assertGreaterEqual(
            dynamic_target_pct(95.0, 1.0),
            round(config.SCALPING_NET_TARGET_PCT + config.DEFAULT_ESTIMATED_SPREAD_PCT
                  + float(config.round_trip_cost()) * 100, 3))

    def test_spread_is_used_when_provided(self):
        # Gerçek spread daha genişse taban da büyür (spread maliyeti gerçekten alınır).
        expected = round(config.SCALPING_NET_TARGET_PCT + 1.20
                         + float(config.round_trip_cost()) * 100, 3)
        self.assertEqual(expected, dynamic_target_pct(70.0, 1.0, spread_pct=1.20))

    def test_floor_never_below_panel_min(self):
        # Taban MONITORING_TARGET_PCT_MIN'den küçük olamaz (R3-14 korunur).
        self.assertGreaterEqual(
            dynamic_target_pct(30.0, 1.0), float(config.MONITORING_TARGET_PCT_MIN))


class MfiBothZeroNeutralTests(unittest.TestCase):
    """MFI: pos == 0 VE neg == 0 (sıfır hacim / düz tipik fiyat) → nötr 50.0."""

    N = 15

    def _flat(self, volumes):
        n = self.N
        return ([100.0] * n, [100.0] * n, [100.0] * n, volumes)

    def test_canonical_mfi_all_zero_volume_is_neutral(self):
        highs, lows, closes, vols = self._flat([0.0] * self.N)
        self.assertEqual(50.0, _mfi(highs, lows, closes, vols))

    def test_velocity_mfi_all_zero_volume_is_neutral(self):
        highs, lows, closes, vols = self._flat([0.0] * self.N)
        self.assertEqual(50.0, _velocity_mfi(highs, lows, closes, vols))

    def test_one_sided_flow_still_returns_100(self):
        # Düz tipik fiyat yerine YÜKSELEN seri + sıfır olmayan hacim → pos>0, neg=0
        n = self.N
        closes = [100.0 + i for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        vols = [10.0] * n
        self.assertEqual(100.0, _mfi(highs, lows, closes, vols))
        self.assertEqual(100.0, _velocity_mfi(highs, lows, closes, vols))


class VelocityRawScoreGateTests(unittest.IsolatedAsyncioTestCase):
    """VELOCITY_AUTO_MIN_SCORE panel (0-100) → ham ölçek dönüşümü."""

    def test_default_panel_maps_to_previous_raw_anchor(self):
        """A3 ankrajı: varsayılan panel eşiği ESKİ ham 200 noktasını korur.

        Eski (lineer) panel 10 = ham 200. Log haritada panel 10 = ham ~1.8 olurdu
        (kapı fiilen ölürdü) → varsayılan 52.4'e yeniden ankrajlandı.
        """
        self.assertAlmostEqual(200.0, _velocity_raw_score_gate(), delta=200.0 * 0.05)

    def test_conversion_uses_inverse_transform_not_linear(self):
        """Log modda panel→ham DOĞRUSAL olamaz (aksi halde eşik sessizce kayardı)."""
        from app.routers.monitoring import _raw_from_panel
        with patch.object(config, "VELOCITY_AUTO_MIN_SCORE", 25.0), \
             patch.object(config, "MONITORING_SCORE_NORM_CAP", 1000.0):
            linear_wrong = 250.0
            self.assertNotAlmostEqual(linear_wrong, _velocity_raw_score_gate(), delta=1.0,
                                      msg="cap tabanlı doğrusal dönüşüm kullanılmamalı")
            self.assertAlmostEqual(_raw_from_panel(25.0), _velocity_raw_score_gate(), places=6)

    async def test_gate_blocks_mid_band_raw_score(self):
        """Ham 150 (eski ölçekte 'yüksek') varsayılan kapının (ham 200) altında."""
        from app.routers import velocity as _v

        with patch.object(_v.analyzer, "positions", {}):
            result = await _v._open_velocity_position(
                {"symbol": "MIDTRY", "price": 1.0, "velocity_score": 150.0,
                 "mode": "trend_devam", "m5_pattern_ok": True, "atr_pct": 0.5})
        self.assertEqual(result["status"], "SKIPPED")
        self.assertIn("skor_esigi_alti", result["reason"])

    async def test_gate_passes_raw_score_above_threshold(self):
        """Ham 250 ≥ kapı (200) → skor kapısı geçilir, sonraki kapıya düşer."""
        from app.routers import velocity as _v

        with patch.object(_v.analyzer, "positions",
                          {"PASSTRY": {"strategy": "CHAT_PREDICTION"}}):
            result = await _v._open_velocity_position(
                {"symbol": "PASSTRY", "price": 1.0, "velocity_score": 250.0,
                 "mode": "trend_devam", "m5_pattern_ok": True, "atr_pct": 0.5})
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "acik_pozisyon_var")


if __name__ == "__main__":
    unittest.main()
