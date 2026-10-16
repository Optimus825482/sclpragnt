"""2026-10-16 (maliyet/çıkış): komisyon modeli (BNB indirimi) ve çıkış profili testleri.

DB gerektirmez. Kilitlenenler:
  * `paper_ledger.commission_pct()` önceliği: OVERRIDE > BNB modu > taban.
  * `config.round_trip_cost()` efektif oranı kullanır.
  * analyzer kapanış muhasebesi (`_record_trade`) efektif oranla hesaplar.
  * `AUTO_PAPER_EXIT_PROFILE` eşlemesi (mevcut / kalibre / bilinmeyen).
  * DB'ye kaydedilmiş admin ayarı profil varsayılanını EZER.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SCALPER_ENV", "development")

from app.config import config  # noqa: E402
from app import paper_ledger as pl  # noqa: E402

BASE = 0.0015
SLIP = 0.00025


def _model(base=BASE, bnb=True, discount=25.0, override=None, slip=SLIP):
    """Komisyon modelini belirli bir duruma sabitleyen patch yığını."""
    return [
        patch.object(config, "COMMISSION_PCT", base),
        patch.object(config, "COMMISSION_BNB_MODE", bnb),
        patch.object(config, "COMMISSION_BNB_DISCOUNT_PCT", discount),
        patch.object(config, "COMMISSION_PCT_OVERRIDE", override),
        patch.object(config, "ESTIMATED_SLIPPAGE_PCT", slip),
    ]


class _Patched(unittest.TestCase):
    def _enter(self, patches):
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class CommissionPrecedenceTests(_Patched):

    def test_base_when_bnb_off_and_no_override(self):
        self._enter(_model(bnb=False))
        self.assertAlmostEqual(pl.commission_pct(), BASE, places=12)
        self.assertAlmostEqual(config.effective_commission_pct(), BASE, places=12)

    def test_bnb_discount_applies_to_base(self):
        self._enter(_model(bnb=True, discount=25.0))
        self.assertAlmostEqual(pl.commission_pct(), BASE * 0.75, places=12)   # 0.001125
        self.assertAlmostEqual(pl.commission_pct(), 0.001125, places=12)

    def test_override_wins_over_bnb_and_base(self):
        self._enter(_model(bnb=True, discount=25.0, override=0.00075))
        self.assertAlmostEqual(pl.commission_pct(), 0.00075, places=12)

    def test_override_wins_even_when_bnb_off(self):
        self._enter(_model(bnb=False, override=0.0005))
        self.assertAlmostEqual(pl.commission_pct(), 0.0005, places=12)

    def test_discount_is_clamped_to_0_100(self):
        self._enter(_model(bnb=True, discount=250.0))
        self.assertAlmostEqual(pl.commission_pct(), 0.0, places=12)
        self._enter(_model(bnb=True, discount=-10.0))
        self.assertAlmostEqual(pl.commission_pct(), BASE, places=12)

    def test_defaults_from_env_are_bnb_on_25pct_no_override(self):
        """Repo varsayılanları: BNB açık, %25 indirim, override yok (env değiştirilmemişse)."""
        if os.getenv("COMMISSION_BNB_MODE") or os.getenv("COMMISSION_PCT_OVERRIDE") \
                or os.getenv("COMMISSION_BNB_DISCOUNT_PCT") or os.getenv("COMMISSION_PCT"):
            self.skipTest("env komisyon bayrakları set edilmiş")
        self.assertTrue(config.COMMISSION_BNB_MODE)
        self.assertEqual(config.COMMISSION_BNB_DISCOUNT_PCT, 25.0)
        self.assertIsNone(config.COMMISSION_PCT_OVERRIDE)
        self.assertAlmostEqual(pl.commission_pct(), 0.001125, places=12)

    def test_commission_model_dict(self):
        self._enter(_model(bnb=True, discount=25.0))
        m = pl.commission_model()
        self.assertEqual(set(m), {"base", "bnb_mode", "discount_pct", "override", "effective", "round_trip"})
        self.assertAlmostEqual(m["base"], BASE, places=12)
        self.assertTrue(m["bnb_mode"])
        self.assertEqual(m["discount_pct"], 25.0)
        self.assertIsNone(m["override"])
        self.assertAlmostEqual(m["effective"], 0.001125, places=12)
        self.assertAlmostEqual(m["round_trip"], 2 * 0.001125 + 2 * SLIP, places=12)


class RoundTripHelperTests(_Patched):

    def test_round_trip_cost_uses_effective_rate(self):
        self._enter(_model(bnb=True, discount=25.0))
        self.assertAlmostEqual(config.round_trip_cost(), 2 * 0.001125 + 2 * SLIP, places=12)  # 0.00275
        self.assertAlmostEqual(config.round_trip_cost(), 0.00275, places=12)

    def test_round_trip_cost_without_bnb_is_legacy_035(self):
        self._enter(_model(bnb=False))
        self.assertAlmostEqual(config.round_trip_cost(), 0.0035, places=12)

    def test_round_trip_markup_follows_effective(self):
        self._enter(_model(bnb=True, discount=50.0))
        self.assertAlmostEqual(pl.round_trip_markup(), 2 * BASE * 0.5 + SLIP, places=12)

    def test_min_net_exit_pct_builds_on_effective(self):
        self._enter(_model(bnb=True, discount=25.0))
        with patch.object(config, "MIN_EXPECTED_NET_PNL_TRY", 0.5):
            self.assertAlmostEqual(config.min_net_exit_pct(1000.0), 0.00275 + 0.5 / 1000.0, places=12)


class AnalyzerUsesEffectiveRateTests(_Patched):

    def test_record_trade_uses_effective_commission(self):
        from app.analyzer import ScalpAnalyzer
        self._enter(_model(bnb=True, discount=25.0))
        an = ScalpAnalyzer.__new__(ScalpAnalyzer)  # __init__ (market) gerekmez; saf muhasebe
        pos = {"entry_price": 100.0, "quantity": 2.0, "strategy": "CHAT_PREDICTION",
               "entry_time": 0.0, "max_price": 103.0, "min_price": 99.0}
        eff = pl.commission_pct()
        exit_commission = 103.0 * 2.0 * eff
        trade = asyncio.run(an._record_trade("XTRY", pos, 103.0, "take_profit", exit_commission))
        expected_total = 100.0 * 2.0 * eff + exit_commission
        self.assertAlmostEqual(trade["commission"], expected_total, places=10)
        self.assertAlmostEqual(trade["pnl"], (103.0 - 100.0) * 2.0 - expected_total, places=10)
        # Ham taban oranla (BNB yokmuş gibi) hesaplanmadığını kilitle.
        self.assertNotAlmostEqual(trade["commission"], 100.0 * 2.0 * BASE + 103.0 * 2.0 * BASE, places=10)

    def test_record_trade_honours_override(self):
        from app.analyzer import ScalpAnalyzer
        self._enter(_model(bnb=True, override=0.0))  # override 0 → komisyonsuz
        an = ScalpAnalyzer.__new__(ScalpAnalyzer)
        pos = {"entry_price": 50.0, "quantity": 1.0, "entry_time": 0.0}
        trade = asyncio.run(an._record_trade("XTRY", pos, 51.0, "trailing_stop", 0.0))
        self.assertAlmostEqual(trade["commission"], 0.0, places=12)
        self.assertAlmostEqual(trade["pnl"], 1.0, places=12)


class ExitProfileTests(_Patched):

    def _base(self):
        return [
            patch.object(config, "AUTO_PAPER_SL_PCT_DEFAULT", 5.0),
            patch.object(config, "AUTO_PAPER_TRAILING_TRIGGER_PCT", 2.0),
            patch.object(config, "AUTO_PAPER_TRAILING_GAP_PCT", 1.0),
            patch.object(config, "AUTO_PAPER_TP_PRIMARY_ENABLED", False),
        ]

    def test_mevcut_profile_returns_config_constants(self):
        self._enter(self._base() + [patch.object(config, "AUTO_PAPER_EXIT_PROFILE", "mevcut")])
        d = config.auto_paper_exit_defaults()
        self.assertEqual(d["profile"], "mevcut")
        self.assertEqual((d["stop_loss_pct"], d["trailing_trigger_pct"], d["trailing_gap_pct"],
                          d["tp_primary_exit_enabled"]), (5.0, 2.0, 1.0, False))

    def test_kalibre_profile_maps_to_calibrated_cell(self):
        self._enter(self._base() + [patch.object(config, "AUTO_PAPER_EXIT_PROFILE", "kalibre")])
        d = config.auto_paper_exit_defaults()
        self.assertEqual(d["profile"], "kalibre")
        self.assertEqual((d["stop_loss_pct"], d["trailing_trigger_pct"], d["trailing_gap_pct"],
                          d["tp_primary_exit_enabled"]), (0.8, 1.0, 0.8, False))
        # Kural: trailing tetik > gap (stop girişin altına düşmesin).
        self.assertGreater(d["trailing_trigger_pct"], d["trailing_gap_pct"])

    def test_kalibre_profile_does_not_touch_other_constants(self):
        self._enter(self._base() + [patch.object(config, "AUTO_PAPER_EXIT_PROFILE", "kalibre")])
        config.auto_paper_exit_defaults()
        self.assertEqual(config.AUTO_PAPER_SL_PCT_DEFAULT, 5.0)  # sabitler değişmez, yalnız dönen dict

    def test_unknown_profile_falls_back_to_mevcut(self):
        self._enter(self._base() + [patch.object(config, "AUTO_PAPER_EXIT_PROFILE", "yok_boyle")])
        d = config.auto_paper_exit_defaults()
        self.assertEqual(d["profile"], "mevcut")
        self.assertEqual(d["stop_loss_pct"], 5.0)

    def test_default_profile_is_mevcut(self):
        if os.getenv("AUTO_PAPER_EXIT_PROFILE"):
            self.skipTest("env AUTO_PAPER_EXIT_PROFILE set edilmiş")
        self.assertEqual(config.AUTO_PAPER_EXIT_PROFILE, "mevcut")

    def test_auto_paper_exit_defaults_helper_mirrors_config(self):
        from app.routers import auto_paper
        self._enter(self._base() + [patch.object(config, "AUTO_PAPER_EXIT_PROFILE", "kalibre")])
        d = auto_paper._exit_defaults()
        self.assertEqual(d["stop_loss_pct"], 0.8)
        self.assertEqual(d["trailing_trigger_pct"], 1.0)
        self.assertEqual(d["trailing_gap_pct"], 0.8)
        self.assertFalse(d["tp_primary_exit_enabled"])


class DbSettingsOverrideProfileTests(_Patched):
    """DB'ye kaydedilmiş admin ayarı (auto_paper_settings) profil varsayılanını EZER."""

    def _patches(self, saved: dict):
        return [
            patch.object(config, "AUTO_PAPER_SL_PCT_DEFAULT", 5.0),
            patch.object(config, "AUTO_PAPER_TRAILING_TRIGGER_PCT", 2.0),
            patch.object(config, "AUTO_PAPER_TRAILING_GAP_PCT", 1.0),
            patch.object(config, "AUTO_PAPER_TP_PRIMARY_ENABLED", False),
            patch.object(config, "AUTO_PAPER_EXIT_PROFILE", "kalibre"),
            patch("app.routers.auto_paper.database.get_llm_setting",
                  AsyncMock(return_value=json.dumps(saved))),
        ]

    def test_saved_values_win_over_profile(self):
        from app.routers import auto_paper
        self._enter(self._patches({"stop_loss_pct": 3.0, "trailing_gap_pct": 1.5}))
        s = asyncio.run(auto_paper.get_auto_paper_settings())
        self.assertEqual(s["stop_loss_pct"], 3.0)          # DB kazanır
        self.assertEqual(s["trailing_gap_pct"], 1.5)       # DB kazanır
        self.assertEqual(s["trailing_trigger_pct"], 1.0)   # DB'de yok → profil (kalibre)
        self.assertEqual(s["exit_profile"], "kalibre")

    def test_empty_db_row_gives_profile_defaults(self):
        from app.routers import auto_paper
        self._enter(self._patches({}))
        s = asyncio.run(auto_paper.get_auto_paper_settings())
        self.assertEqual((s["stop_loss_pct"], s["trailing_trigger_pct"], s["trailing_gap_pct"]), (0.8, 1.0, 0.8))
        self.assertFalse(s["tp_primary_exit_enabled"])

    def test_mevcut_profile_with_empty_db_gives_legacy_defaults(self):
        from app.routers import auto_paper
        self._enter(self._patches({}) + [patch.object(config, "AUTO_PAPER_EXIT_PROFILE", "mevcut")])
        s = asyncio.run(auto_paper.get_auto_paper_settings())
        self.assertEqual((s["stop_loss_pct"], s["trailing_trigger_pct"], s["trailing_gap_pct"]), (5.0, 2.0, 1.0))
        self.assertEqual(s["exit_profile"], "mevcut")


if __name__ == "__main__":
    unittest.main()
