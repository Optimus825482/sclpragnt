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
    """Hedef esnetme: bantlar yüksekten düşüğe; learned/ML yalnız YUKARI çeker."""

    def test_top_tier_wins(self):
        self.assertEqual(4.0, dynamic_target_pct(95.0, 1.0))

    def test_middle_and_low_tiers(self):
        self.assertEqual(2.5, dynamic_target_pct(75.0, 1.0))
        self.assertEqual(2.0, dynamic_target_pct(55.0, 1.0))

    def test_below_all_tiers_clamps_to_min(self):
        self.assertEqual(config.MONITORING_TARGET_PCT_MIN, dynamic_target_pct(10.0, 1.0))

    def test_learned_only_raises(self):
        self.assertEqual(5.0, dynamic_target_pct(95.0, 1.0, learned_pct=5.0))
        self.assertEqual(4.0, dynamic_target_pct(95.0, 1.0, learned_pct=2.0))

    def test_ml_only_raises_and_must_be_positive(self):
        self.assertEqual(4.0, dynamic_target_pct(95.0, 1.0, ml_pct=0.5))
        self.assertEqual(4.5, dynamic_target_pct(95.0, 1.0, ml_pct=4.5))
        self.assertEqual(4.0, dynamic_target_pct(95.0, 1.0, ml_pct=-3.0))

    def test_result_is_clamped_to_max(self):
        self.assertEqual(config.MONITORING_TARGET_PCT_MAX,
                         dynamic_target_pct(95.0, 1.0, learned_pct=99.0))


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
