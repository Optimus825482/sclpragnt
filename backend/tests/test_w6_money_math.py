"""W6 — para matematiği testleri (I-08) + katmanlar arası komisyon tutarlılığı.

Neden var
---------
Denetim (2026-09-12, I-08): **para matematiğinin hiç testi yoktu**. Kritik
fonksiyonlar — `config.min_net_exit_pct`, `market_intelligence.trade_economics`,
`calibration.multiplier_for`, `velocity.dynamic_target_pct` — hiçbir testle
sabitlenmemişti. Bu fonksiyonlar emir boyutunu, kâr hedefini ve kâr kilidi
zeminini belirlediği için sessiz bir regresyon doğrudan para kaybı demektir.

Ayrıca H-01'in kalıcı çözümü frontend/backend komisyon oranının AYNI kalmasına
bağlı: oran iki yerde ayrı sabit olarak tutulursa zamanla ayrışır. Bu yüzden
`COMMISSION_PCT` varsayılanı, WS payload'ı ve `/api/config` alanı burada
kaynak düzeyinde çivilenir.
"""
import pathlib
import re
import unittest

from app import calibration
from app import market_intelligence as mi
from app.config import Config, config
from app.routers.velocity import dynamic_target_pct

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent


class MinNetExitPctTests(unittest.TestCase):
    """D-01'in zemin formülü: gidiş-dönüş maliyet + asgari net kâr."""

    def test_zero_or_missing_value_uses_default_order_proxy(self):
        """`0` (bilinmeyen notional) DEFAULT_ORDER_TRY vekiline düşer.

        `value = float(order_value or DEFAULT_ORDER_TRY)` — 0 falsy olduğu için
        vekile düşer. Bu BİLİNÇLİ korunur: eksik miktarda asgari-net terimini
        tamamen düşürmek eşiği gereksiz yere zayıflatırdı. Davranış burada
        çivilenir ki sessizce değişmesin.
        """
        proxy = Config.min_net_exit_pct(Config.DEFAULT_ORDER_TRY)
        self.assertAlmostEqual(proxy, Config.min_net_exit_pct(0), places=12)
        self.assertAlmostEqual(proxy, Config.min_net_exit_pct(None), places=12)

    def test_negative_value_uses_pure_round_trip_cost(self):
        """Negatif notional anlamsızdır → asgari-net terimi uygulanmaz."""
        expected = Config.COMMISSION_PCT * 2 + Config.ESTIMATED_SLIPPAGE_PCT * 2
        self.assertAlmostEqual(expected, Config.min_net_exit_pct(-5), places=12)

    def test_value_adds_min_expected_net_per_notional(self):
        value = 1000.0
        expected = (Config.COMMISSION_PCT * 2 + Config.ESTIMATED_SLIPPAGE_PCT * 2
                    + Config.MIN_EXPECTED_NET_PNL_TRY / value)
        self.assertAlmostEqual(expected, Config.min_net_exit_pct(value), places=12)

    def test_none_falls_back_to_default_order(self):
        self.assertAlmostEqual(Config.min_net_exit_pct(None),
                               Config.min_net_exit_pct(Config.DEFAULT_ORDER_TRY), places=12)

    def test_covers_both_commission_legs(self):
        """Tek bacak unutulursa (eski D-01 hatası) kilit çıkışı zarar yazardı."""
        self.assertGreaterEqual(Config.min_net_exit_pct(1000.0), Config.COMMISSION_PCT * 2)


class TradeEconomicsTests(unittest.TestCase):
    def test_round_trip_cost_and_break_even(self):
        out = mi.trade_economics(100.0, stop_price=99.0, take_profit=101.0, quantity=10.0)
        expected_cost_pct = 0.0015 * 2 + 0.0 + 0.00025 * 2
        self.assertAlmostEqual(expected_cost_pct, out["round_trip_cost_pct"], places=8)
        self.assertAlmostEqual(1000.0 * expected_cost_pct, out["round_trip_cost"], places=6)
        self.assertAlmostEqual(100.0 * (1 + expected_cost_pct), out["break_even_price"], places=6)
        # +%1 hedef, %0.35 maliyet → net 6,5 TRY
        self.assertAlmostEqual(6.5, out["expected_net_pnl"], places=4)
        self.assertTrue(out["economically_viable"])
        self.assertTrue(out["paper_only"])

    def test_thin_edge_is_not_viable(self):
        """%0,2 hedef maliyeti karşılamaz → viable olmamalı."""
        out = mi.trade_economics(100.0, take_profit=100.2, quantity=10.0)
        self.assertLess(out["expected_net_pnl"], 0)
        self.assertFalse(out["economically_viable"])

    def test_matches_canonical_round_trip_basis(self):
        """`trade_economics` ile `min_net_exit_pct` AYNI maliyet tabanını kullanmalı."""
        value = 1000.0
        econ = mi.trade_economics(100.0, quantity=value / 100.0, spread_pct=0.0)
        canonical = Config.min_net_exit_pct(value) - Config.MIN_EXPECTED_NET_PNL_TRY / value
        self.assertAlmostEqual(canonical, econ["round_trip_cost_pct"], places=8)

    def test_missing_target_leaves_expected_net_none(self):
        out = mi.trade_economics(100.0, quantity=10.0)
        self.assertIsNone(out["expected_net_pnl"])
        self.assertFalse(out["economically_viable"])


class ConfidenceMultiplierTests(unittest.TestCase):
    def _key(self, **kwargs):
        return calibration.bucket_key(**kwargs)

    def test_unknown_bucket_is_neutral(self):
        self.assertEqual(calibration.MAX_MULTIPLIER,
                         calibration.confidence_multiplier({}, strategy="X", hour=10, volume_ratio=1.0))

    def test_thin_sample_is_neutral(self):
        key = self._key(strategy="X", hour=10, volume_ratio=1.0)
        buckets = {key: {"samples": calibration.MIN_BUCKET_SAMPLES - 1, "win_rate": 0.10}}
        self.assertEqual(calibration.MAX_MULTIPLIER,
                         calibration.confidence_multiplier(buckets, strategy="X", hour=10, volume_ratio=1.0))

    def test_win_rate_anchors(self):
        key = self._key(strategy="X", hour=10, volume_ratio=1.0)
        good = {key: {"samples": 50, "win_rate": calibration.GOOD_WIN_RATE}}
        bad = {key: {"samples": 50, "win_rate": calibration.BAD_WIN_RATE}}
        self.assertEqual(calibration.MAX_MULTIPLIER,
                         calibration.confidence_multiplier(good, strategy="X", hour=10, volume_ratio=1.0))
        self.assertEqual(calibration.MIN_MULTIPLIER,
                         calibration.confidence_multiplier(bad, strategy="X", hour=10, volume_ratio=1.0))

    def test_linear_interpolation_between_anchors(self):
        key = self._key(strategy="X", hour=10, volume_ratio=1.0)
        mid = (calibration.GOOD_WIN_RATE + calibration.BAD_WIN_RATE) / 2
        buckets = {key: {"samples": 50, "win_rate": mid}}
        expected = round((calibration.MIN_MULTIPLIER + calibration.MAX_MULTIPLIER) / 2, 3)
        self.assertAlmostEqual(expected,
                               calibration.confidence_multiplier(buckets, strategy="X", hour=10, volume_ratio=1.0),
                               places=3)

    def test_multiplier_for_is_never_below_floor(self):
        self.assertGreaterEqual(calibration.multiplier_for("VELOCITY", volume_ratio=0.2),
                                calibration.MIN_MULTIPLIER)


class DynamicTargetPctTests(unittest.TestCase):
    """Hedef esnetme: bantlar yüksekten düşüğe; learned/ML İKİ YÖNLÜ harmanlanır.

    2026-09-17 sözleşme değişikliği (kullanıcı kararı): öğrenilmiş
    (``learned_pct``) ve ML (``ml_pct``) hedefleri artık ``max()`` ile yalnız
    yukarı çekmiyor; ağırlıklı harmanla AŞAĞI da çekebiliyor. Gerçekleşen MFE'si
    banttan düşük sembollerde hedef düşer — bu bir strateji değişikliğidir,
    testler onu burada çiviliyor.
    """

    def test_top_tier_wins(self):
        self.assertEqual(4.0, dynamic_target_pct(95.0, 1.0))

    def test_middle_and_low_tiers(self):
        # A3 (2026-09-14): bant eşikleri ham çalışma noktaları korunarak yeniden
        # ankrajlandı → 74.0/71.5/68.2 (eski 90/70/50).
        self.assertEqual(2.5, dynamic_target_pct(72.5, 1.0))
        self.assertEqual(2.0, dynamic_target_pct(69.5, 1.0))

    def test_below_all_tiers_clamps_to_min(self):
        self.assertEqual(config.MONITORING_TARGET_PCT_MIN, dynamic_target_pct(10.0, 1.0))

    def test_learned_moves_target_both_ways(self):
        """12 örnek → ağırlık 0.6; learned banttan yüksekse yukarı, DÜŞÜKSE AŞAĞI."""
        # 4.0*0.4 + 5.0*0.6 = 4.60   (yukarı)
        self.assertAlmostEqual(
            4.6, dynamic_target_pct(95.0, 1.0, learned_pct=5.0, learned_count=12), places=3)
        # 4.0*0.4 + 2.0*0.6 = 2.80   (aşağı — eski sözleşmede 4.0 kalırdı)
        self.assertAlmostEqual(
            2.8, dynamic_target_pct(95.0, 1.0, learned_pct=2.0, learned_count=12), places=3)

    def test_learned_weight_grows_with_sample_count(self):
        """Ağırlık min(0.6, count/20): 3 örnekte 0.15, 12 örnekte 0.60."""
        # 4.0*0.85 + 5.0*0.15 = 4.15
        self.assertAlmostEqual(
            4.15, dynamic_target_pct(95.0, 1.0, learned_pct=5.0, learned_count=3), places=3)
        self.assertLess(
            dynamic_target_pct(95.0, 1.0, learned_pct=5.0, learned_count=3),
            dynamic_target_pct(95.0, 1.0, learned_pct=5.0, learned_count=12))

    def test_learned_ignored_below_minimum_samples(self):
        """3 örnekten az → öğrenme uygulanmaz (tek örnek hedefi zıplatmasın)."""
        self.assertEqual(4.0, dynamic_target_pct(95.0, 1.0, learned_pct=5.0, learned_count=2))

    def test_ml_requires_minimum_probability(self):
        """Olasılık eşiğinin (ML_TARGET_MIN_PROB) altında ML hedefe girmez."""
        self.assertEqual(4.0, dynamic_target_pct(
            95.0, 1.0, ml_pct=6.0, ml_prob=config.ML_TARGET_MIN_PROB - 0.1))
        # Olasılık hiç verilmezse de uygulanmaz.
        self.assertEqual(4.0, dynamic_target_pct(95.0, 1.0, ml_pct=6.0))

    def test_ml_moves_target_both_ways(self):
        """Yüksek güven (>=ML_TARGET_HIGH_PROB) → ağırlık 0.5."""
        # 4.0*0.5 + 6.0*0.5 = 5.00   (yukarı)
        self.assertAlmostEqual(
            5.0, dynamic_target_pct(95.0, 1.0, ml_pct=6.0, ml_prob=0.9), places=3)
        # 4.0*0.5 + 2.0*0.5 = 3.00   (aşağı)
        self.assertAlmostEqual(
            3.0, dynamic_target_pct(95.0, 1.0, ml_pct=2.0, ml_prob=0.9), places=3)

    def test_ml_weight_is_lower_between_threshold_and_high_confidence(self):
        """Eşik ile yüksek güven eşiği arası → ağırlık 0.25 (4.0*0.75 + 6.0*0.25 = 4.5)."""
        mid = (config.ML_TARGET_MIN_PROB + config.ML_TARGET_HIGH_PROB) / 2
        self.assertAlmostEqual(
            4.5, dynamic_target_pct(95.0, 1.0, ml_pct=6.0, ml_prob=mid), places=3)

    def test_ml_must_be_positive(self):
        """Negatif/düşüş tahmini hedefi aşağı çekemez (kanal yalnız pozitif)."""
        self.assertEqual(4.0, dynamic_target_pct(95.0, 1.0, ml_pct=-3.0, ml_prob=0.9))

    def test_result_is_clamped_to_max(self):
        self.assertEqual(config.MONITORING_TARGET_PCT_MAX,
                         dynamic_target_pct(95.0, 1.0, learned_pct=99.0, learned_count=12))

    def test_weak_score_cap_beats_learned_target(self):
        """Zayıf skor kelepçesi (score*0.3) öğrenilmiş hedefi de sınırlar."""
        # skor 5 → tavan 1.5; harman 4.6 üretse de cap 1.5'e iner → MIN'e kırpılır.
        self.assertEqual(config.MONITORING_TARGET_PCT_MIN,
                         dynamic_target_pct(5.0, 4.0, learned_pct=5.0, learned_count=12))

    def test_panel_score_false_skips_tiers_and_weak_score_cap(self):
        """`panel_score=False` (rising): PANEL ölçeğine bağlı iki kural da atlanır.

        Rising skoru `strength × 10` ile sentezlenir, velocity PANEL skoru
        değildir → bant seçimi ve zayıf-skor kelepçesi uygulanmaz (plan §4/R3).
        """
        # Bant devre dışı: skor 95 olsa bile hedef tabanda kalır → MIN'e kırpılır.
        self.assertEqual(config.MONITORING_TARGET_PCT_MIN,
                         dynamic_target_pct(95.0, 1.0, panel_score=False))
        # Zayıf-skor kelepçesi devre dışı: skor 5 olsa da harman uygulanır.
        # 4.0*0.4 + 5.0*0.6 = 4.6 (panel_score=True olsaydı 1.5'e inerdi)
        self.assertAlmostEqual(4.6, dynamic_target_pct(
            5.0, 4.0, learned_pct=5.0, learned_count=12, panel_score=False), places=3)


class CommissionCrossLayerTests(unittest.TestCase):
    """H-01 kalıcılığı: komisyon oranı iki katmanda AYNI kalmalı."""

    def test_frontend_fallback_matches_backend_default(self):
        config_src = (_BACKEND / "app" / "config.py").read_text(encoding="utf-8")
        m = re.search(r'COMMISSION_PCT\s*=\s*float\(\s*os\.getenv\(\s*"COMMISSION_PCT"\s*,\s*"([0-9.]+)"',
                      config_src)
        self.assertIsNotNone(m, "config.py'de COMMISSION_PCT varsayılanı bulunamadı")
        backend_default = float(m.group(1))

        pnl_ts = (_ROOT / "frontend" / "app" / "lib" / "pnl.ts").read_text(encoding="utf-8")
        m2 = re.search(r"COMMISSION_PCT_FALLBACK\s*=\s*([0-9.]+)", pnl_ts)
        self.assertIsNotNone(m2, "lib/pnl.ts içinde COMMISSION_PCT_FALLBACK bulunamadı")
        self.assertAlmostEqual(backend_default, float(m2.group(1)), places=12,
                               msg="Frontend komisyon varsayılanı backend'den ayrışmış")

    def test_ws_portfolio_payload_exposes_commission_pct(self):
        src = (_BACKEND / "app" / "routers" / "runtime.py").read_text(encoding="utf-8")
        self.assertRegex(src, r'"commission_pct"\s*:\s*config\.COMMISSION_PCT')

    def test_get_config_exposes_commission_pct(self):
        src = (_BACKEND / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"commission_pct": config.COMMISSION_PCT', src)

    def test_frontend_syncs_commission_from_ws(self):
        src = (_ROOT / "frontend" / "app" / "lib" / "liveSocket.ts").read_text(encoding="utf-8")
        self.assertIn("applyCommissionPct", src)


if __name__ == "__main__":
    unittest.main()
