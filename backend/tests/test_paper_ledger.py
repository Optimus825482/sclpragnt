"""`app.paper_ledger` testleri: dolum, tazelik kapısı ve komisyon sözleşmesi.

Eski satır-içi formüller (auto_paper / combined DB / analyzer) burada referans
olarak yeniden yazılır; ortak modelin bunlarla sayısal olarak aynı olduğu kilitlenir.
"""
import os
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SCALPER_ENV", "development")

from app.config import config  # noqa: E402
from app import paper_ledger as pl  # noqa: E402


class EntryFillTests(unittest.TestCase):

    def test_explicit_slippage(self):
        self.assertAlmostEqual(pl.entry_fill(100.0, 0.001), 100.1, places=12)

    def test_default_slippage_comes_from_config(self):
        with patch.object(config, "ESTIMATED_SLIPPAGE_PCT", 0.002):
            self.assertAlmostEqual(pl.entry_fill(100.0), 100.2, places=12)

    def test_zero_slippage_is_identity(self):
        self.assertEqual(pl.entry_fill(42.0, 0.0), 42.0)


class ExitFillTests(unittest.TestCase):

    def test_trigger_exits_take_worse_of_current_and_trigger(self):
        for kind in ("stop_loss", "breakeven_stop", "trailing_stop", "take_profit"):
            # gap aşağı: piyasa tetiğin altında → piyasadan dolar
            self.assertEqual(pl.exit_fill(kind, 95.0, 97.0), 95.0, kind)
            # piyasa tetiğin üstünde → tetik fiyatından dolar
            self.assertEqual(pl.exit_fill(kind, 99.0, 97.0), 97.0, kind)

    def test_trigger_exit_without_trigger_raises(self):
        with self.assertRaises(ValueError):
            pl.exit_fill("stop_loss", 95.0)

    def test_market_exits_use_current_price(self):
        for kind in ("max_duration", "no_profit_timeout", "symbol_deactivated", "stale_force_close"):
            self.assertEqual(pl.exit_fill(kind, 123.4), 123.4, kind)

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            pl.exit_fill("bilinmeyen", 1.0, 1.0)

    def test_exit_fill_is_pre_slippage(self):
        """Kayma kapanışta (settle_close) uygulanır; exit_fill onu içermez."""
        with patch.object(config, "ESTIMATED_SLIPPAGE_PCT", 0.01):
            self.assertEqual(pl.exit_fill("max_duration", 100.0), 100.0)


class SellFillAndMarkupTests(unittest.TestCase):

    def test_sell_fill_applies_slippage_down(self):
        self.assertAlmostEqual(pl.sell_fill(100.0, 0.001), 99.9, places=12)

    def test_round_trip_markup_is_two_commissions_plus_slippage(self):
        self.assertAlmostEqual(pl.round_trip_markup(0.0015, 0.00025), 0.00325, places=12)

    def test_defaults_follow_config(self):
        # 2026-10-16 (maliyet/çıkış): commission_pct() artık EFEKTİF oran (BNB
        # indirimi/override); ham taban testi için BNB modu ve override kapatılır.
        with patch.object(config, "COMMISSION_PCT", 0.002), \
             patch.object(config, "COMMISSION_BNB_MODE", False), \
             patch.object(config, "COMMISSION_PCT_OVERRIDE", None), \
             patch.object(config, "ESTIMATED_SLIPPAGE_PCT", 0.0005):
            self.assertAlmostEqual(pl.round_trip_markup(), 0.0045, places=12)
            self.assertAlmostEqual(pl.commission_pct(), 0.002, places=12)
            self.assertAlmostEqual(pl.slippage_pct(), 0.0005, places=12)


class FreshnessTests(unittest.TestCase):

    def test_zero_or_missing_timestamp_is_stale(self):
        self.assertFalse(pl.is_fresh(0))
        self.assertFalse(pl.is_fresh(None))

    def test_within_limit_is_fresh(self):
        now = 1_000_000.0
        self.assertTrue(pl.is_fresh((now - 5) * 1000, now_sec=now, max_age_sec=15))

    def test_beyond_limit_is_stale(self):
        now = 1_000_000.0
        self.assertFalse(pl.is_fresh((now - 16) * 1000, now_sec=now, max_age_sec=15))

    def test_default_limit_is_config_max_ticker_age(self):
        now = time.time()
        with patch.object(config, "MAX_TICKER_AGE_SEC", 10):
            self.assertTrue(pl.is_fresh((now - 9) * 1000, now_sec=now))
            self.assertFalse(pl.is_fresh((now - 11) * 1000, now_sec=now))


class SettleCloseTests(unittest.TestCase):

    def test_numbers_round_trip_net(self):
        out = pl.settle_close(100.0, 110.0, 2.0, commission=0.001, slippage=0.0)
        self.assertAlmostEqual(out["fill_price"], 110.0, places=12)
        self.assertAlmostEqual(out["commission"], 0.42, places=12)   # 0.2 giriş + 0.22 çıkış
        self.assertAlmostEqual(out["gross_pnl"], 20.0, places=12)
        self.assertAlmostEqual(out["pnl"], 19.58, places=12)
        self.assertAlmostEqual(out["pnl_pct"], 9.79, places=12)

    def test_zero_invested_gives_zero_pct(self):
        out = pl.settle_close(0.0, 5.0, 1.0, commission=0.001, slippage=0.0)
        self.assertEqual(out["pnl_pct"], 0.0)

    def test_matches_legacy_auto_paper_close_formula(self):
        """Eski `_close_trade` satır-içi muhasebesiyle birebir (kayma + iki bacak komisyon)."""
        import random
        rnd = random.Random(7)
        for _ in range(200):
            entry = rnd.uniform(0.5, 500.0)
            exit_px = entry * rnd.uniform(0.5, 1.5)
            qty = rnd.uniform(0.01, 1000.0)
            c = rnd.choice([0.0, 0.0015, 0.002])
            s = rnd.choice([0.0, 0.00025, 0.001])
            fill = exit_px * (1.0 - s)
            entry_commission = entry * qty * c
            exit_commission = fill * qty * c
            total = entry_commission + exit_commission
            pnl = (fill - entry) * qty - total
            invested = entry * qty
            legacy_pct = (pnl / invested * 100) if invested else 0.0

            out = pl.settle_close(entry, exit_px, qty, commission=c, slippage=s)
            self.assertAlmostEqual(out["fill_price"], fill, places=9)
            self.assertAlmostEqual(out["commission"], total, places=9)
            self.assertAlmostEqual(out["pnl"], pnl, places=9)
            self.assertAlmostEqual(out["pnl_pct"], legacy_pct, places=9)

    def test_matches_legacy_combined_db_formula(self):
        """Eski combined DB kapanışı: total = (entry·q + fill·q)·c, pnl = (fill-entry)·q - total."""
        entry, exit_px, qty, c, s = 100.0, 96.0, 3.0, 0.0015, 0.00025
        fill = exit_px * (1.0 - s)
        total = (entry * qty + fill * qty) * c
        pnl = (fill - entry) * qty - total
        out = pl.settle_close(entry, exit_px, qty, commission=c, slippage=s)
        self.assertAlmostEqual(out["fill_price"], fill, places=12)
        self.assertAlmostEqual(out["commission"], total, places=9)
        self.assertAlmostEqual(out["pnl"], pnl, places=9)


if __name__ == "__main__":
    unittest.main()
