import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import master_surge, unified_signals
from app.config import config


class MasterSurgeLayer1Tests(unittest.TestCase):
    def test_layer1_passes_with_tight_spread_and_good_liquidity(self):
        ticker = {"last_price": 100.0}
        flow = {
            "bid_price": 99.9,
            "ask_price": 100.1,
            "spread_pct": 0.20,
            "bid_qty": 50.0,
            "ask_qty": 50.0,
        }
        fake_market = MagicMock()
        fake_market.get_ticker.return_value = ticker
        fake_market.get_orderflow.return_value = flow
        fake_market.ticker_24h = {"TESTTRY": 500_000.0}

        res = master_surge.evaluate_layer1_liquidity("TESTTRY", market_instance=fake_market)
        self.assertTrue(res["passed"])
        self.assertGreaterEqual(res["score"], 70.0)
        self.assertEqual(res["spread_pct"], 0.20)

    def test_layer1_fails_when_spread_too_wide(self):
        ticker = {"last_price": 100.0}
        flow = {
            "bid_price": 99.0,
            "ask_price": 101.0,
            "spread_pct": 2.0,
            "bid_qty": 50.0,
            "ask_qty": 50.0,
        }
        fake_market = MagicMock()
        fake_market.get_ticker.return_value = ticker
        fake_market.get_orderflow.return_value = flow
        fake_market.ticker_24h = {"TESTTRY": 500_000.0}

        res = master_surge.evaluate_layer1_liquidity("TESTTRY", market_instance=fake_market)
        self.assertFalse(res["passed"])
        self.assertIn("spread_too_wide", res["reason"])

    def test_layer1_fails_when_24h_volume_too_low(self):
        ticker = {"last_price": 100.0}
        flow = {
            "bid_price": 99.9,
            "ask_price": 100.1,
            "spread_pct": 0.20,
            "bid_qty": 50.0,
            "ask_qty": 50.0,
        }
        fake_market = MagicMock()
        fake_market.get_ticker.return_value = ticker
        fake_market.get_orderflow.return_value = flow
        fake_market.ticker_24h = {"TESTTRY": 20_000.0}  # Below 150_000

        res = master_surge.evaluate_layer1_liquidity("TESTTRY", market_instance=fake_market)
        self.assertFalse(res["passed"])
        self.assertIn("low_24h_volume", res["reason"])

    def test_layer1_fails_when_depth_too_shallow(self):
        ticker = {"last_price": 10.0}
        flow = {
            "bid_price": 9.99,
            "ask_price": 10.01,
            "spread_pct": 0.20,
            "bid_qty": 5.0,  # 5 * 10 = 50 TRY depth
            "ask_qty": 5.0,
        }
        fake_market = MagicMock()
        fake_market.get_ticker.return_value = ticker
        fake_market.get_orderflow.return_value = flow
        fake_market.ticker_24h = {"TESTTRY": 500_000.0}

        res = master_surge.evaluate_layer1_liquidity("TESTTRY", market_instance=fake_market)
        self.assertFalse(res["passed"])
        self.assertIn("shallow_depth", res["reason"])


class MasterSurgeLayer2Tests(unittest.TestCase):
    def test_layer2_passes_with_dip_and_squeeze_transition(self):
        row = {
            "pre": {"dip": True},
            "pre_detail": {"proximity": 0.85, "squeeze_now": False, "transition": True},
        }
        res = master_surge.evaluate_layer2_volatility("TESTTRY", macd_row=row)
        self.assertTrue(res["passed"])
        self.assertTrue(res["is_dip"])
        self.assertTrue(res["transition"])
        self.assertGreaterEqual(res["score"], 70.0)

    def test_layer2_fails_when_no_dip_and_no_squeeze(self):
        row = {
            "pre": {"dip": False},
            "pre_detail": {"proximity": 0.1, "squeeze_now": False, "transition": False, "expand_now": False},
        }
        res = master_surge.evaluate_layer2_volatility("TESTTRY", macd_row=row)
        self.assertFalse(res["passed"])
        self.assertLess(res["score"], 35.0)


class MasterSurgeLayer3Tests(unittest.TestCase):
    def test_layer3_passes_with_whale_cvd_and_volume_surge(self):
        row = {
            "cvd": {"buy_dominant": True, "whale_net": 25000.0, "buy_ratio": 0.65},
        }
        cand = {"volume_ratio": 2.1}
        res = master_surge.evaluate_layer3_orderflow("TESTTRY", macd_row=row, velocity_candidate=cand)
        self.assertTrue(res["passed"])
        self.assertTrue(res["buy_dominant"])
        self.assertEqual(res["whale_net"], 25000.0)
        self.assertGreaterEqual(res["score"], 75.0)

    def test_layer3_fails_when_bearish_flow_and_flat_volume(self):
        row = {
            "cvd": {"buy_dominant": False, "whale_net": -5000.0, "buy_ratio": 0.40},
        }
        cand = {"volume_ratio": 0.8}
        res = master_surge.evaluate_layer3_orderflow("TESTTRY", macd_row=row, velocity_candidate=cand)
        self.assertFalse(res["passed"])


class MasterSurgeLayer4Tests(unittest.TestCase):
    def test_layer4_passes_with_4_of_4_green_and_high_strength(self):
        row = {
            "tfs": {
                "1m": {"green": True},
                "3m": {"green": True},
                "5m": {"green": True},
                "15m": {"green": True},
            },
            "strength": 8.5,
            "dir": 1,
        }
        res = master_surge.evaluate_layer4_mtf("TESTTRY", macd_row=row)
        self.assertTrue(res["passed"])
        self.assertEqual(res["green_count"], 4)
        self.assertGreaterEqual(res["score"], 80.0)

    def test_layer4_fails_when_only_1_green_and_weak_strength(self):
        row = {
            "tfs": {
                "1m": {"green": True},
                "3m": {"green": False},
                "5m": {"green": False},
                "15m": {"green": False},
            },
            "strength": 3.0,
            "dir": -1,
        }
        res = master_surge.evaluate_layer4_mtf("TESTTRY", macd_row=row)
        self.assertFalse(res["passed"])
        self.assertEqual(res["green_count"], 1)


class MasterSurgeAdaptiveTargetsTests(unittest.TestCase):
    def test_adaptive_targets_within_user_specs(self):
        # ATR 1.5%
        res = master_surge.calculate_adaptive_targets(score=85.0, atr_pct=1.5, base_target_pct=3.5)
        self.assertGreaterEqual(res["tp1_scalp_pct"], 1.2)
        self.assertLessEqual(res["tp1_scalp_pct"], 1.8)
        self.assertGreaterEqual(res["tp2_runner_pct"], 3.0)
        self.assertLessEqual(res["tp2_runner_pct"], 6.5)
        self.assertLess(res["breakeven_trigger_pct"], res["tp1_scalp_pct"])
        self.assertEqual(res["trailing_gap_pct"], 0.40)

    def test_adaptive_targets_clamp_bounds(self):
        # Extreme high ATR
        res_high = master_surge.calculate_adaptive_targets(score=95.0, atr_pct=5.0, base_target_pct=10.0)
        self.assertEqual(res_high["tp1_scalp_pct"], 1.8)
        self.assertEqual(res_high["tp2_runner_pct"], 6.5)

        # Extreme low ATR
        res_low = master_surge.calculate_adaptive_targets(score=40.0, atr_pct=0.2, base_target_pct=1.0)
        self.assertEqual(res_low["tp1_scalp_pct"], 1.2)
        self.assertEqual(res_low["tp2_runner_pct"], 3.0)


class MasterSurgeConfluenceTests(unittest.TestCase):
    def test_4way_confluence_succeeds_with_synergy_boost(self):
        with patch.object(master_surge, "evaluate_layer1_liquidity", return_value={"passed": True, "score": 90.0}), \
             patch.object(master_surge, "evaluate_layer2_volatility", return_value={"passed": True, "score": 85.0}), \
             patch.object(master_surge, "evaluate_layer3_orderflow", return_value={"passed": True, "score": 85.0}), \
             patch.object(master_surge, "evaluate_layer4_mtf", return_value={"passed": True, "score": 90.0}):
            eval_res = master_surge.evaluate_master_surge("TESTTRY")
            self.assertTrue(eval_res["passed"])
            self.assertTrue(eval_res["confluence_4way"])
            self.assertEqual(eval_res["confluence_count"], 4)
            self.assertGreaterEqual(eval_res["composite_index"], 85.0)

    def test_3way_confluence_rejected_when_4way_required(self):
        with patch.object(master_surge, "evaluate_layer1_liquidity", return_value={"passed": True, "score": 90.0}), \
             patch.object(master_surge, "evaluate_layer2_volatility", return_value={"passed": True, "score": 85.0}), \
             patch.object(master_surge, "evaluate_layer3_orderflow", return_value={"passed": True, "score": 85.0}), \
             patch.object(master_surge, "evaluate_layer4_mtf", return_value={"passed": False, "score": 20.0}):
            eval_res = master_surge.evaluate_master_surge("TESTTRY")
            # When 4-way is required ( Erkan kararı: 3'lü teyitler gürültü ürettiği için reddedilir)
            self.assertFalse(eval_res["confluence_4way"])
            self.assertEqual(eval_res["confluence_count"], 3)
            self.assertFalse(eval_res["passed"])

    def test_layer1_failure_immediately_rejects(self):
        with patch.object(master_surge, "evaluate_layer1_liquidity", return_value={"passed": False, "reason": "spread_too_wide"}):
            eval_res = master_surge.evaluate_master_surge("TESTTRY")
            self.assertFalse(eval_res["passed"])
            self.assertEqual(eval_res["composite_index"], 0.0)
            self.assertEqual(eval_res["failed_layer"], 1)

    def test_is_4way_confluence_helper(self):
        self.assertTrue(master_surge.is_4way_confluence(["velocity", "jump", "early", "rising"]))
        self.assertFalse(master_surge.is_4way_confluence(["velocity", "jump", "early"]))
        self.assertFalse(master_surge.is_4way_confluence([]))
        self.assertFalse(master_surge.is_4way_confluence(None))


class UnifiedSignalsMasterSurgeIntegrationTests(unittest.TestCase):
    def test_enrich_candidates_includes_master_surge_and_adaptive_targets(self):
        cand = {
            "symbol": "BTC_TRY",
            "velocity_score": 500,
            "panel_score": 75.0,
            "price": 2_000_000.0,
            "target_pct": 2.5,
            "atr_pct": 1.4,
        }
        with patch.object(master_surge, "evaluate_layer1_liquidity", return_value={"passed": True, "score": 80.0}), \
             patch.object(master_surge, "evaluate_layer2_volatility", return_value={"passed": True, "score": 80.0}), \
             patch.object(master_surge, "evaluate_layer3_orderflow", return_value={"passed": True, "score": 80.0}), \
             patch.object(master_surge, "evaluate_layer4_mtf", return_value={"passed": True, "score": 80.0}):
            unified_signals.enrich_candidates([cand])
            self.assertIn("master_surge", cand)
            self.assertIn("adaptive_targets", cand)
            self.assertGreaterEqual(cand.get("tp1_scalp_pct", 0), 1.2)
            self.assertLessEqual(cand.get("tp1_scalp_pct", 0), 1.8)
            self.assertGreaterEqual(cand.get("tp2_runner_pct", 0), 3.0)

    def test_fusion_only_rejects_liquidity_failures(self):
        """Katman 1'i (likidite) geçemeyen adaylar fusion_only listesine giremez."""
        with patch.object(unified_signals, "enabled", return_value=True), \
             patch.object(unified_signals, "macd_components", return_value=({"jump": 80.0, "early": 75.0}, {})), \
             patch.object(unified_signals._macd, "_SNAPSHOT", {"symbols": {"SHITCOIN": {"last": 1.0}}, "universe": ["SHITCOIN"]}), \
             patch.object(master_surge, "evaluate_master_surge", return_value={"passed": False, "failed_layer": 1}):
            fusion = unified_signals.enrich_candidates([], min_fusion_score=50.0)
            self.assertEqual(len(fusion), 0)


class AutoPaperMasterSurgeIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_master_surge_trade_uses_tight_gap_and_tp1_trigger(self):
        from app.routers import auto_paper
        now = time.time()
        trade = {
            "id": 99,
            "symbol": "MSTEST",
            "entry_price": 100.0,
            "quantity": 1.0,
            "stop_loss": 97.0,
            "take_profit": 105.0,
            "peak_price": 101.5,
            "entry_time": now,
            "breakeven_activated": False,
            "breakeven_stop": None,
            "tp1_scalp_pct": 1.3,
            "confluence_4way": True,
        }
        mock_market = MagicMock()
        mock_market.get_ticker.return_value = {"last_price": 101.4, "timestamp": now * 1000}
        mock_market.symbols = None
        with patch.object(auto_paper, "market", mock_market), \
             patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock()) as mock_be, \
             patch.object(auto_paper, "_close_trade", AsyncMock()):
            # gross_pnl = +1.4% >= tp1_scalp (+1.3%) -> breakeven stop tetiklenmeli
            await auto_paper._manage_single_trade(
                trade=trade,
                now=now,
                breakeven_trigger_pct=2.0,  # Standart tetikleyici 2.0 olsa bile tp1 1.3 devreye girer
                settings={"trailing_enabled": False},
            )
            mock_be.assert_awaited_once()
            # Stop seviyesi zirvenin (%101.5) %0.40 gerisinden takip etmeli: 101.5 * (1 - 0.0040) = 101.094
            called_stop = mock_be.await_args.args[2]
            self.assertAlmostEqual(called_stop, 101.5 * (1 - 0.004), places=3)

    async def test_standard_trade_preserves_standard_gap_without_master_surge(self):
        from app.routers import auto_paper
        now = time.time()
        trade = {
            "id": 100,
            "symbol": "STDTEST",
            "entry_price": 100.0,
            "quantity": 1.0,
            "stop_loss": 97.0,
            "take_profit": 104.0,
            "peak_price": 103.5,
            "entry_time": now,
            "breakeven_activated": False,
            "breakeven_stop": None,
            # tp1_scalp_pct YOK, confluence_4way YOK
        }
        mock_market = MagicMock()
        mock_market.get_ticker.return_value = {"last_price": 103.0, "timestamp": now * 1000}
        mock_market.symbols = None
        with patch.object(auto_paper, "market", mock_market), \
             patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock()) as mock_be, \
             patch.object(auto_paper, "_close_trade", AsyncMock()):
            await auto_paper._manage_single_trade(
                trade=trade,
                now=now,
                breakeven_trigger_pct=2.0,
                settings={"trailing_enabled": False},
            )
            mock_be.assert_awaited_once()
            # Standart işlemde taban açıklık 0.60 korunmalı: 103.5 * (1 - 0.0060) = 102.879
            called_stop = mock_be.await_args.args[2]
            self.assertAlmostEqual(called_stop, 103.5 * (1 - 0.006), places=3)


if __name__ == "__main__":
    unittest.main()
