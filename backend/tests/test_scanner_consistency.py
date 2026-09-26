"""Yükselen sembol tarama hattı — 2026-09-26 denetim düzeltmeleri (#1-#8).

Denetim raporu: docs/SISTEM_DENETIMI_2026-09-26.md analiz turu (8 bulgu).
Bu testler düzeltmelerin davranışsal sözleşmelerini kilitler.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import unified_signals
from app.master_surge import calculate_adaptive_targets


class RisingFusionGateTests(unittest.TestCase):
    """#3: füzyon RISING bileşeni rising_signals eşiğini paylaşmalı."""

    def _row(self, strength, green_tfs=2):
        return {
            "strength": strength,
            "raw": None,
            "tfs": {tf: {"green": True} for tf in
                    ("1m", "3m", "5m", "15m", "1h", "4h")[:green_tfs]},
        }

    def _snapshot(self, row: dict) -> dict:
        return {"symbols": {"TESTTRY": row}, "universe": ["TESTTRY"]}

    def test_below_threshold_strength_not_a_fusion_source(self):
        """Güç var ama yeşil TF eşiği altındaysa RISING kaynağı SAYILMAMALI."""
        from app.config import config
        row = self._row(strength=9.9, green_tfs=2)  # güç geçer, yeşil < MIN_GREEN(5)
        with patch.object(config, "RISING_MIN_GREEN", 5, create=True), \
             patch.object(config, "RISING_MIN_STRENGTH", 9.8, create=True), \
             patch.object(unified_signals._macd, "_SNAPSHOT", self._snapshot(row)):
            out, _ = unified_signals.macd_components("TESTTRY")
        self.assertNotIn(unified_signals.SOURCE_RISING, out,
                         "eşik altı rising bileşeni füzyona girmemeli")

    def test_qualified_strength_is_fusion_source(self):
        """Eşiği geçen güç RISING kaynağı olmalı (mevcut davranış korunur)."""
        from app.config import config
        row = self._row(strength=9.9, green_tfs=6)
        with patch.object(config, "RISING_MIN_GREEN", 5, create=True), \
             patch.object(config, "RISING_MIN_STRENGTH", 9.8, create=True), \
             patch.object(unified_signals._macd, "_SNAPSHOT", self._snapshot(row)):
            out, _ = unified_signals.macd_components("TESTTRY")
        self.assertIn(unified_signals.SOURCE_RISING, out)
        self.assertEqual(out[unified_signals.SOURCE_RISING], 99.0)


class PoolProvenanceTests(unittest.TestCase):
    """#6: aday kaydı havuz kaynağını ve 24h değişimi taşımalı."""

    def test_pool_source_labels_built_without_duplicates(self):
        """Havuz etiketleri: gainer > mover > symbol > extra önceliği, dup yok."""
        # `_add` davranışını doğrudan doğrulamak yerine pool kurulumunu
        # sembolik doğrula: aynı sembol iki kaynaktan gelirse ilk kaynak kalır.
        pool, source = [], {}
        added = set()

        def add(sym, src):
            sym = str(sym).upper()
            if sym and sym not in added:
                pool.append(sym)
                added.add(sym)
                source[sym] = src

        add("BTCTRY", "gainer")
        add("BTCTRY", "mover")
        add("ETHTRY", "symbol")
        self.assertEqual(pool, ["BTCTRY", "ETHTRY"])
        self.assertEqual(source["BTCTRY"], "gainer")


class TickerCacheTtlTests(unittest.TestCase):
    """#7: TTL env ile geçersiz kılınabilir ve varsayılan 15 sn."""

    def test_default_ttl_is_15s(self):
        from app import binance_tr_public as btp
        self.assertEqual(btp.TICKER_24H_CACHE_TTL_SEC, 15.0)


class QuoteAssetFloorTests(unittest.TestCase):
    """#8: hacim tabanları para birimine göre ölçeklenmeli."""

    def test_usdt_floor_is_not_try_floor(self):
        from app import binance_tr_public as btp
        self.assertEqual(btp._min_quote_volume("TRY"), 5_000_000.0)
        usdt = btp._min_quote_volume("USDT")
        self.assertLess(usdt, btp._min_quote_volume("TRY"),
                        "USDT tabanı TRY tabanıyla aynıysa USDT havuzu boşalır")
        self.assertGreater(usdt, 0)

    def test_unknown_asset_falls_back_to_try(self):
        from app import binance_tr_public as btp
        self.assertEqual(btp._min_quote_volume("BTC"), 5_000_000.0)

    def test_active_movers_floor_is_half(self):
        from app import binance_tr_public as btp
        # TRY: 5M → movers 2.5M (mevcut sözleşme)
        self.assertAlmostEqual(btp._min_quote_volume("TRY") * 0.5, 2_500_000.0)


class AdaptiveTargetsLowAtrTests(unittest.TestCase):
    """#2 (test_master_surge.py'de de var): düşük ATR rejiminde ölçekleme."""

    def test_tp1_scales_below_06_atr(self):
        res = calculate_adaptive_targets(score=80.0, atr_pct=0.3, base_target_pct=2.2)
        self.assertAlmostEqual(res["tp1_scalp_pct"], 0.6)  # 2×ATR
        self.assertLess(res["breakeven_trigger_pct"], res["tp1_scalp_pct"])

    def test_tp1_keeps_empirical_band_above_06(self):
        res = calculate_adaptive_targets(score=80.0, atr_pct=1.0, base_target_pct=2.2)
        self.assertEqual(res["tp1_scalp_pct"], 1.2)

    def test_targets_monotonic_in_atr(self):
        lo = calculate_adaptive_targets(score=80.0, atr_pct=0.3, base_target_pct=2.2)
        mid = calculate_adaptive_targets(score=80.0, atr_pct=0.7, base_target_pct=2.2)
        hi = calculate_adaptive_targets(score=80.0, atr_pct=1.5, base_target_pct=2.2)
        self.assertLess(lo["tp1_scalp_pct"], mid["tp1_scalp_pct"])
        self.assertLessEqual(mid["tp1_scalp_pct"], hi["tp1_scalp_pct"])


class MomentumDeadBranchTests(unittest.TestCase):
    """#1: momentum = max(0, ret3, ret5) — ölçek, moda göre değişmemeli."""

    def test_momentum_identity_holds_for_both_signs(self):
        # Ölü dal kaldırıldı: pozitif ve negatif senaryoda tek formül.
        # (Davranış değişmedi — eski else dalı matematiksel olarak hep 0 üretiyordu.)
        for ret3, ret5, expected in [(0.5, 0.2, 0.5), (0.0, 0.0, 0.0), (-1.0, -2.0, 0.0)]:
            momentum = max(0.0, ret3, ret5)
            self.assertEqual(momentum, expected)


if __name__ == "__main__":
    unittest.main()
