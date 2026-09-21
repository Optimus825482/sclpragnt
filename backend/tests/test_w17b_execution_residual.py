"""W17b — İşlem yürütme / risk kalan bulgular (2026-09-12).

Kapsanan bulgular ve LOCK TESTİ ilkesi: her test, ilgili düzeltme GERİ ALINIRSA
KIRILACAK şekilde yazılmıştır. Bazıları davranışsal (mock'lu uçtan uca yol),
bazıları kaynak/AST sözleşmesidir (repo'daki `test_regressions.py` deseni):
davranışı tek başına gözlemlenemeyen (ör. sihirli sabit kaldırma) bulgular için
kaynak sözleşmesi meşru bir kilittir.

Bulgular:
  D-06  auto_paper reopen `notification_id=None` → churn baypası
  D-07  TP, trailing aktivasyonu yüzünden atlanıyor (default target==trigger)
  D-08  slippage fiilî doluma uygulanmıyor; TP/SL current_price'dan doluyor
  D-10  analyzer, auto_paper_trades'i sorgulamıyor (aynı sembol iki pozisyon)
  D-11  MAX_OPEN_POSITIONS / AUTO_PAPER_MAX_OPEN_POSITIONS varsayılanı 0
  D-12  velocity cap `<= 9999` sihirli sabiti
  D-13  token bucket: kilit altında uyku + token düşmeme + throttle'sız yollar
  D-14  breakeven_activated DB yazımı olmadan set ediliyor
  D-15  reopen kapanış zinciri içinde senkron
  D-16  yönetim döngüsünde backoff yok
  I-03  velocity özel 15-bar ATR (kanonik 14 ile değiştirildi)
  I-07  VELOCITY_MIN_ATR_PCT env'e kapalı + vestigial global
  G-16  /api/velocity `loop_running` yapışkan boolean
  G-17  zayıf admin parolası yalnızca uyarıyor
"""
from __future__ import annotations

import ast
import asyncio
import os
import pathlib
import re
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config, Config  # noqa: E402
import app.config as config_module  # noqa: E402
from app.routers import auto_paper  # noqa: E402
from app.routers import velocity  # noqa: E402

_BACKEND = ROOT
_VELOCITY_SRC = (_BACKEND / "app" / "routers" / "velocity.py").read_text(encoding="utf-8")
_AUTO_PAPER_SRC = (_BACKEND / "app" / "routers" / "auto_paper.py").read_text(encoding="utf-8")


def _coro(value):
    async def _inner(*_a, **_kw):
        return value
    return _inner()


# ---------------------------------------------------------------------------
# D-06 — reopen churn koruması (kararlı id + dedup + saatlik cap)
# ---------------------------------------------------------------------------
class ReopenChurnGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        auto_paper._reopen_last_attempt.clear()

    def tearDown(self):
        auto_paper._reopen_last_attempt.clear()

    def test_reopen_notification_id_is_stable_not_none(self):
        """Eski kod `id` alanı olmadan (None) gönderiyordu → churn baypası."""
        rid = auto_paper._reopen_notification_id("APTEST", 1_000_000.0)
        self.assertIsInstance(rid, str)
        self.assertTrue(rid.startswith("reopen:APTEST:"))
        # Aynı saat kovası → aynı (KARARLI) id; sonraki saat → farklı id.
        self.assertEqual(rid, auto_paper._reopen_notification_id("APTEST", 1_000_000.0 + 10))
        self.assertNotEqual(rid, auto_paper._reopen_notification_id("APTEST", 1_000_000.0 + 3600))

    async def test_reopen_sends_stable_id_and_enforces_dedup(self):
        captured = {}

        async def fake_open(notif):
            captured["notif"] = notif
            return {"status": "opened"}

        cand = {"panel_score": 80.0, "price": 100.0, "target_pct": 2.0, "horizon_minutes": 5}
        with patch.object(auto_paper, "get_auto_paper_settings",
                          AsyncMock(return_value={"reopen_after_protect_close": True})), \
             patch.object(auto_paper.database, "get_recent_auto_paper_trade_by_notification",
                          AsyncMock(return_value=None)), \
             patch("app.routers.monitoring.get_cached_radar_candidate", return_value=cand), \
             patch.object(auto_paper, "try_open_from_notification", fake_open):
            await auto_paper._maybe_reopen_after_protect_close("APTEST", 777)
            # 2. çağrı: in-memory saatlik deneme sınırı devrede → açılmaz.
            await auto_paper._maybe_reopen_after_protect_close("APTEST", 777)
        notif = captured["notif"]
        self.assertIsNotNone(notif.get("id"), "reopen bildirimi KARARLI id taşımalı (None DEĞİL)")
        self.assertTrue(str(notif["id"]).startswith("reopen:APTEST:"))

    async def test_reopen_second_attempt_same_hour_is_capped(self):
        calls = {"n": 0}

        async def fake_open(notif):
            calls["n"] += 1
            return {"status": "opened"}

        cand = {"panel_score": 80.0, "price": 100.0, "target_pct": 2.0}
        with patch.object(auto_paper, "get_auto_paper_settings",
                          AsyncMock(return_value={"reopen_after_protect_close": True})), \
             patch.object(auto_paper.database, "get_recent_auto_paper_trade_by_notification",
                          AsyncMock(return_value=None)), \
             patch("app.routers.monitoring.get_cached_radar_candidate", return_value=cand), \
             patch.object(auto_paper, "try_open_from_notification", fake_open):
            await auto_paper._maybe_reopen_after_protect_close("APTEST", 1)
            await auto_paper._maybe_reopen_after_protect_close("APTEST", 1)
            await auto_paper._maybe_reopen_after_protect_close("APTEST", 1)
        self.assertEqual(calls["n"], 1, "saatte en fazla 1 yeniden açma denemesi olmalı")

    async def test_reopen_skips_when_db_already_traded_this_hour(self):
        """DB churn kontrolü (notification_id) yeniden açmayı da kapsamalı."""
        calls = {"n": 0}

        async def fake_open(notif):
            calls["n"] += 1
            return {"status": "opened"}

        cand = {"panel_score": 80.0, "price": 100.0, "target_pct": 2.0}
        with patch.object(auto_paper, "get_auto_paper_settings",
                          AsyncMock(return_value={"reopen_after_protect_close": True})), \
             patch.object(auto_paper.database, "get_recent_auto_paper_trade_by_notification",
                          AsyncMock(return_value={"id": 1, "status": "open"})), \
             patch("app.routers.monitoring.get_cached_radar_candidate", return_value=cand), \
             patch.object(auto_paper, "try_open_from_notification", fake_open):
            await auto_paper._maybe_reopen_after_protect_close("APTEST", 1)
        self.assertEqual(calls["n"], 0, "aynı saat kovasında DB kaydı varsa açılmamalı")


# ---------------------------------------------------------------------------
# D-07 — TP, trailing aktivasyonundan bağımsız
# ---------------------------------------------------------------------------
class AutoPaperTakeProfitTests(unittest.IsolatedAsyncioTestCase):
    async def test_tp_fires_at_default_target_equal_to_trailing_trigger(self):
        """Varsayılan (target=2.0 == trailing_trigger=2.0) hedefte TP KAZANMALI.

        Eski kod: `trailing_devrede` gross >= trigger iken de True idi ve TP'yi
        atlıyordu → hedef hiç uygulanmıyordu.
        """
        now = time.time()
        trade = {
            "id": 1, "symbol": "APTEST", "status": "open",
            "entry_price": 100.0, "quantity": 1.0,
            "stop_loss": 97.0, "take_profit": 102.0, "peak_price": 100.0,
            "breakeven_activated": False, "breakeven_stop": None,
            "trailing_activated": False, "trailing_stop": None,
            "entry_time": now,
        }
        analyzer = MagicMock()
        analyzer.positions = {"APTEST": trade}
        market = MagicMock()
        # gross = +%2.0 == TP ve == trailing trigger
        market.get_ticker = MagicMock(return_value={"last_price": 102.0,
                                                    "timestamp": now * 1000})
        close = AsyncMock(return_value=None)
        settings = {"breakeven_trigger_pct": 1.5, "trailing_enabled": True,
                    "trailing_trigger_pct": 2.0, "trailing_gap_pct": 0.8}
        with patch("app.routers.auto_paper.market", market), \
             patch.object(auto_paper, "_close_trade", close):
            await auto_paper._manage_single_trade(trade, now, 1.5, settings)
        close.assert_awaited()
        self.assertEqual(close.await_args.args[4], "take_profit")


# ---------------------------------------------------------------------------
# B1-B3 (2026-09-14) — otonom çıkış merdiveni: TP birincil + dinamik koruma
#
# Plan: "TP'yi birincil çıkış yap; kâr korumasını trade'in GERÇEK hedefine bağla".
# Bu testler, ilgili düzeltmeler geri alınırsa KIRILACAK şekilde yazılmıştır.
# ---------------------------------------------------------------------------
class AutoPaperExitLadderTests(unittest.IsolatedAsyncioTestCase):
    """TP (B1) → breakeven (B2) → trailing (B2/B3) sırasının sözleşmesi."""

    def _trade(self, entry=100.0, tp=104.0, sl=97.0, peak=None, **extra):
        trade = {
            "id": 1, "symbol": "APTEST", "status": "open",
            "entry_price": entry, "quantity": 1.0,
            "stop_loss": sl, "take_profit": tp,
            "peak_price": entry if peak is None else peak,
            "breakeven_activated": False, "breakeven_stop": None,
            "trailing_activated": False, "trailing_stop": None,
        }
        trade.update(extra)
        return trade

    async def _manage(self, trade, price, settings):
        """Pozisyonu tek turda yönet; (close_mock, breakeven_mock, trailing_mock) döndür."""
        now = time.time()
        market = MagicMock()
        market.get_ticker = MagicMock(
            return_value={"last_price": price, "timestamp": now * 1000})
        close = AsyncMock(return_value=None)
        be = AsyncMock(return_value=None)
        trail = AsyncMock(return_value=None)
        with patch("app.routers.auto_paper.market", market), \
             patch.object(auto_paper, "_close_trade", close), \
             patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock(return_value=None)), \
             patch.object(auto_paper.database, "update_auto_paper_breakeven", be), \
             patch.object(auto_paper.database, "update_auto_paper_trailing", trail):
            await auto_paper._manage_single_trade(trade, now, 1.5, settings)
        return close, be, trail

    # ---- B1: TP birincil ------------------------------------------------
    async def test_tp_fill_uses_trigger_price_on_gap_through(self):
        """Fiyat TP'nin üstüne gap atsa bile dolum TP fiyatından (D-08 sözleşmesi)."""
        close, _, _ = await self._manage(self._trade(), 105.0, {})
        close.assert_awaited()
        self.assertEqual("take_profit", close.await_args.args[4])
        self.assertEqual(104.0, close.await_args.args[2],
                         "gap-through'da dolum TP tetik fiyatından olmalı")

    async def test_tp_fires_even_when_trailing_already_activated(self):
        """D-07 regresyonu: trailing devredeyken TP YİNE değerlendirilir.

        Eski kodda trailing aktifleşince TP bir daha bakılmıyordu → hedef hiç
        kullanılmıyordu. Şimdi TP her turda ilk kontrol.
        """
        trade = self._trade(tp=102.0, peak=103.0,
                            trailing_activated=True, trailing_stop=101.5)
        close, _, _ = await self._manage(trade, 105.0, {"trailing_enabled": True})
        close.assert_awaited()
        self.assertEqual("take_profit", close.await_args.args[4])
        self.assertEqual(102.0, close.await_args.args[2])

    async def test_tp_primary_can_be_disabled_from_settings(self):
        """`tp_primary_exit_enabled=false` → TP yolu kapanır (geri dönüş anahtarı)."""
        trade = self._trade(tp=102.0, peak=103.0,
                            trailing_activated=True, trailing_stop=101.5)
        close, _, _ = await self._manage(
            trade, 105.0, {"trailing_enabled": True, "tp_primary_exit_enabled": False})
        reasons = [c.args[4] for c in close.await_args_list] if close.await_count else []
        self.assertNotIn("take_profit", reasons, "kapalıyken TP kullanılmamalı")

    # ---- B2: koruma tavan korumalıdır (2026-09-21 düzeltmesi) ------------
    async def test_breakeven_trigger_deferred_to_tp_fraction(self):
        """Hedef %4 → 2026-09-21: breakeven kâr korumayı geciktirmez; +%2.0'de kilitler."""
        trade = self._trade()  # tp_gain = 4.0
        _, be, _ = await self._manage(trade, 102.0, {})  # gross +2.0 >= 1.5 baz eşik
        be.assert_awaited()

    async def test_breakeven_trigger_is_not_deferred_when_dynamic_disabled(self):
        """`dynamic_breakeven_enabled=false` → sabit eşik (%1.5) geçerli."""
        trade = self._trade()
        _, be, _ = await self._manage(
            trade, 102.0, {"dynamic_breakeven_enabled": False})
        be.assert_awaited()

    async def test_trailing_trigger_deferred_to_tp_fraction(self):
        """Hedef %4 → trailing 2026-09-21 güncellemesi ile tavan korumalıdır (gecikmez)."""
        trade = self._trade()
        _, _, trail = await self._manage(
            trade, 102.5, {"trailing_enabled": True})  # gross +2.5 >= 2.0 (tavan korumalı)
        trail.assert_awaited()

    # ---- B3: gap TP'ye yaklaşırken daralır --------------------------------
    async def test_trailing_gap_halves_near_tp(self):
        """gross >= hedefin %90'ı → gap yarılanır: kâr tepeye yakın kilitlenir."""
        settings = {"trailing_enabled": True,
                    "trailing_trigger_pct": 2.0, "trailing_gap_pct": 0.6}

        # gross +3.5 (< %3.6 eşiği) → gap 0.6 (kırpma zaten 0.6'da)
        trade = self._trade()
        _, _, trail = await self._manage(trade, 103.5, dict(settings))
        trail.assert_awaited()
        self.assertAlmostEqual(103.5 * (1 - 0.006), trail.await_args.args[2], places=6)

        # gross +3.7 (>= %3.6 eşiği) → gap 0.3 (0.6'nın yarısı)
        trade = self._trade()
        _, _, trail = await self._manage(trade, 103.7, dict(settings))
        trail.assert_awaited()
        self.assertAlmostEqual(103.7 * (1 - 0.003), trail.await_args.args[2], places=6)

    async def test_trailing_gap_cannot_be_looser_than_breakeven(self):
        """SHADOW KİLİDİ: gevşek ayar KIRPILIR, sıkı ayar etki eder.

        Neden: breakeven ratchet'i (BREAKEVEN_TRAIL_GAP_PCT = %0.60) hem daha sıkı
        hem bu bloktan ÖNCE değerlendiriliyor. 0.8'lik ayar pratikte hiç
        uygulanmıyordu (471 işlemlik gerçek replay'de `trailing_stop` 0 kez); ayar
        sessizce yok sayılmak yerine kırpılır. (Mutasyon: kırpma kaldırılırsa
        aşağıdaki ilk beklenti 103.5*(1-0.015) olurdu.)
        """
        loose = {"trailing_enabled": True, "trailing_trigger_pct": 2.0,
                 "trailing_gap_pct": 1.5}
        trade = self._trade()
        _, _, trail = await self._manage(trade, 103.5, dict(loose))
        trail.assert_awaited()
        self.assertAlmostEqual(103.5 * (1 - 0.006), trail.await_args.args[2], places=6)

        # Sıkı ayar GERÇEKTEN etki eder: 0.3 → tepeye daha yakın kilitler.
        tight = {"trailing_enabled": True, "trailing_trigger_pct": 2.0,
                 "trailing_gap_pct": 0.3}
        trade = self._trade()
        _, _, trail = await self._manage(trade, 103.5, dict(tight))
        trail.assert_awaited()
        self.assertAlmostEqual(103.5 * (1 - 0.003), trail.await_args.args[2], places=6)


# ---------------------------------------------------------------------------
# D-08 — slippage (giriş+çıkış) ve TP/SL tetik dolumu
# ---------------------------------------------------------------------------
class TriggerFillPriceTests(unittest.TestCase):
    def test_tp_fill_is_min_and_stop_fill_is_max(self):
        from app.analyzer import ScalpAnalyzer

        # TP: fiyat tetiğin üstüne gap atsa bile tetikten iyi iddia etme.
        self.assertEqual(102.0, ScalpAnalyzer._trigger_fill_price(105.0, 102.0, "take_profit"))
        self.assertEqual(102.0, ScalpAnalyzer._trigger_fill_price(102.0, 102.0, "take_profit"))
        # Stop: fiyat tetiğin altına gap atsa bile tetiği zararına kullan.
        self.assertEqual(98.0, ScalpAnalyzer._trigger_fill_price(95.0, 98.0, "stop"))
        self.assertEqual(98.0, ScalpAnalyzer._trigger_fill_price(98.0, 98.0, "stop"))
        # Geçersiz tetik → fiyat aynen.
        self.assertEqual(50.0, ScalpAnalyzer._trigger_fill_price(50.0, None, "stop"))


class AnalyzerSlippageTests(unittest.IsolatedAsyncioTestCase):
    def _analyzer_with_pos(self, entry=100.0, quantity=1.0, tp=None, stop=None):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer.__new__(ScalpAnalyzer)
        now = time.time()
        analyzer.market = MagicMock()
        analyzer.market.get_ticker = MagicMock(
            return_value={"last_price": entry, "timestamp": now * 1000})
        analyzer.market.get_ut_kline = MagicMock(return_value={})
        analyzer._open_position_lock = asyncio.Lock()
        analyzer._cooldown_until = {}
        analyzer._timeout_block_until = {}
        analyzer._hard_stop_block_until = {}
        analyzer._guard_persist_lock = asyncio.Lock()
        pos = {
            "symbol": "TESTTRY", "strategy": "CHAT_PREDICTION", "side": "LONG",
            "entry_price": entry, "quantity": quantity, "entry_time": now - 100,
            "max_price": entry, "min_price": entry, "system_stop_price": None,
            "system_take_profit_price": tp, "take_profit": tp,
            "entry_context": {"signal_context": {"no_initial_stop": True}},
        }
        analyzer.positions = {"TESTTRY": pos}
        return analyzer

    async def test_close_applies_exit_slippage_to_actual_fill(self):
        analyzer = self._analyzer_with_pos(entry=100.0)
        captured = {}

        async def fake_commit(symbol, base, cash, trade, sig):
            captured["trade"] = trade

        with patch("app.analyzer.database.get_wallet_balance", AsyncMock(return_value=1000.0)), \
             patch("app.analyzer.database.commit_close_position", AsyncMock(side_effect=fake_commit)), \
             patch("app.analyzer.database.save_signal", AsyncMock()), \
             patch("app.analyzer.database.upsert_llm_symbol_guard", AsyncMock()), \
             patch("app.analyzer.database.get_llm_setting", AsyncMock(return_value="{}")), \
             patch("app.analyzer.database.set_llm_setting", AsyncMock()), \
             patch("app.analyzer.agent_learning.record_paper_trade_outcome", AsyncMock()), \
             patch("app.analyzer.strategy_breaker.evaluate_after_close", AsyncMock()):
            await analyzer.close_position("TESTTRY", 110.0, "manual_close")
        slip = config.ESTIMATED_SLIPPAGE_PCT
        self.assertAlmostEqual(110.0 * (1 - slip), captured["trade"]["exit_price"], places=6)

    async def test_tp_fill_uses_trigger_price_not_current(self):
        analyzer = self._analyzer_with_pos(entry=100.0, tp=102.0)
        analyzer.positions["TESTTRY"]["velocity_protection_armed"] = True
        close = AsyncMock(return_value={"ok": True})
        with patch.object(analyzer, "close_position", close), \
             patch("app.analyzer.config.MAX_TICKER_AGE_SEC", 3600), \
             patch("app.analyzer.config.EARLY_FAILURE_SEC", 10 ** 9), \
             patch("app.analyzer.config.STALE_POSITION_SEC", 10 ** 9):
            await analyzer._manage_open_position("TESTTRY", 105.0, "CHAT_PREDICTION")
        close.assert_awaited_once()
        self.assertEqual("chat_plan_take_profit", close.await_args.args[2])
        self.assertAlmostEqual(102.0, close.await_args.args[1], places=6)

    async def test_open_applies_entry_slippage(self):
        from app.analyzer import ScalpAnalyzer

        class _M:
            def __init__(self):
                self.tickers = {}
                self.orderflow = {}
                self.klines = {}
                self.ticker_24h = {}
            def get_ticker(self, s):
                return {"last_price": 100.0, "timestamp": time.time() * 1000}
            def get_ut_kline(self, s, tf=None):
                return {}
            def get_orderflow(self, s):
                return {"bid_qty": 10.0, "ask_qty": 9.0, "spread_pct": 0.05,
                        "bid_price": 99.99, "ask_price": 100.01}
            def liquidity_status(self, s, v, **_k):
                return True, {"checks": {"q": True}}
            def data_freshness(self, s, tf):
                return {"orderbook": {"fresh": True}}

        analyzer = ScalpAnalyzer(_M())
        with patch("app.analyzer.database.load_positions", AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.database.get_open_auto_paper_trade", AsyncMock(return_value=None)), \
             patch("app.analyzer.database.save_signal", AsyncMock()), \
             patch("app.analyzer.database.commit_open_position", AsyncMock()), \
             patch("app.analyzer.config.CALIBRATION_SIZING_ENABLED", False), \
             patch("app.analyzer.config.REGIME_SIZING_ENABLED", False), \
             patch("app.analyzer.config.CORRELATION_CAP_ENABLED", False):
            await analyzer.open_position("BTCTRY", 100.0, "LONG", "CHAT_PREDICTION", 5_000.0,
                                         take_profit_pct=0.02,
                                         entry_context_extra={"no_initial_stop": True})
        pos = analyzer.positions["BTCTRY"]
        slip = config.ESTIMATED_SLIPPAGE_PCT
        self.assertAlmostEqual(100.0 * (1 + slip), pos["entry_price"], places=6)
        # Boyut raporu ile muhasebe tutarlı: quantity*entry_price == order_value.
        self.assertAlmostEqual(pos["quantity"] * pos["entry_price"], 5_000.0, places=6)


class AutoPaperSlippageTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_applies_exit_slippage(self):
        captured = {}
        trade = {"id": 1, "symbol": "APTEST", "status": "open", "entry_price": 100.0,
                 "quantity": 1.0, "entry_time": time.time() - 60}

        async def fake_close(trade_id, exit_price, exit_time, pnl, pnl_pct, commission, reason):
            captured["exit_price"] = exit_price
            return True

        with patch.object(auto_paper.database, "get_auto_paper_trade", AsyncMock(return_value=trade)), \
             patch.object(auto_paper.database, "close_auto_paper_trade", AsyncMock(side_effect=fake_close)), \
             patch.object(auto_paper, "_broadcast_trade", AsyncMock()):
            await auto_paper._close_trade(1, "APTEST", 110.0, time.time(), "manual_close")
        slip = config.ESTIMATED_SLIPPAGE_PCT
        self.assertAlmostEqual(110.0 * (1 - slip), captured["exit_price"], places=6)

    async def test_open_applies_entry_slippage(self):
        captured = {}
        trade = {"symbol": "APTEST", "entry_price": 100.0, "quantity": 1.0,
                 "entry_time": time.time()}

        async def fake_open(trade_data, signal):
            captured["trade_data"] = trade_data
            return ({"id": 1}, "opened")

        settings = {"balance_pct": 35.0, "min_order_try": 10.0, "stop_loss_pct": 3.0,
                    "default_target_pct": 2.0}
        with patch.object(auto_paper.database, "get_wallet_balance", AsyncMock(return_value=1000.0)), \
             patch.object(auto_paper.database, "open_auto_paper_trade", AsyncMock(side_effect=fake_open)), \
             patch.object(auto_paper, "_broadcast_trade", AsyncMock()):
            await auto_paper._open_new_trade("APTEST",
                                             {"symbol": "APTEST", "score": 80.0, "target_pct": 2.0},
                                             100.0, settings)
        slip = config.ESTIMATED_SLIPPAGE_PCT
        self.assertAlmostEqual(100.0 * (1 + slip), captured["trade_data"]["entry_price"], places=6)


# ---------------------------------------------------------------------------
# D-10 — analyzer, auto_paper_trades'i sorgular
# ---------------------------------------------------------------------------
class CrossSubsystemPositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_blocked_when_auto_paper_position_exists(self):
        from app.analyzer import ScalpAnalyzer

        class _M:
            def __init__(self):
                self.tickers = {}
                self.orderflow = {}
                self.klines = {}
                self.ticker_24h = {}
            def get_ticker(self, s):
                return {"last_price": 100.0, "timestamp": time.time() * 1000}
            def get_ut_kline(self, s, tf=None):
                return {}
            def get_orderflow(self, s):
                return {"bid_qty": 10.0, "ask_qty": 9.0, "spread_pct": 0.05,
                        "bid_price": 99.99, "ask_price": 100.01}
            def liquidity_status(self, s, v, **_k):
                return True, {"checks": {"q": True}}
            def data_freshness(self, s, tf):
                return {"orderbook": {"fresh": True}}

        analyzer = ScalpAnalyzer(_M())
        with patch("app.analyzer.database.load_positions", AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.database.get_open_auto_paper_trade",
                   AsyncMock(return_value={"id": 5, "symbol": "BTCTRY", "status": "open"})), \
             patch("app.analyzer.database.save_signal", AsyncMock()):
            result = await analyzer.open_position("BTCTRY", 100.0, "LONG", "CHAT_PREDICTION",
                                                  1_000.0, take_profit_pct=0.02,
                                                  entry_context_extra={"no_initial_stop": True})
        self.assertIsNotNone(result)
        self.assertEqual(result.get("reason"), "auto_paper_position_open")
        self.assertNotIn("BTCTRY", analyzer.positions)


# ---------------------------------------------------------------------------
# D-11 — sonlu güvenli varsayılan pozisyon limitleri
# ---------------------------------------------------------------------------
class PositionLimitDefaultTests(unittest.TestCase):
    def test_defaults_are_finite_not_unlimited(self):
        self.assertEqual(5, Config.MAX_OPEN_POSITIONS)
        # Erkan kararı (2026-09-18): otonom paper global limiti 3 -> 8
        # (UI'dan da değiştirilebilir: Ayarlar > Otonom Paper Trade).
        self.assertEqual(8, Config.AUTO_PAPER_MAX_OPEN_POSITIONS)

    def test_defaults_are_env_overridable(self):
        for key in ("MAX_OPEN_POSITIONS", "AUTO_PAPER_MAX_OPEN_POSITIONS"):
            self.assertIn(f'os.getenv("{key}"', (_BACKEND / "app" / "config.py").read_text(encoding="utf-8"))

    def test_analyzer_cap_is_finite_by_default(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer.__new__(ScalpAnalyzer)
        self.assertEqual(5.0, analyzer.max_open_positions())


# ---------------------------------------------------------------------------
# D-12 — sihirli `<= 9999` kaldırıldı
# ---------------------------------------------------------------------------
class VelocityCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_velocity_cap_applied_for_positive_value(self):
        fake_analyzer = MagicMock()
        fake_analyzer.positions = {
            "OTHERTRY": {"entry_context": {"signal_context": {"source": "velocity_auto"}}}
        }
        candidate = {"symbol": "TESTTRY", "velocity_score": 25.0, "mode": "trend_devam",
                     "m5_pattern_ok": True, "target_pct": 2.0, "horizon_minutes": 5,
                     "passes": True, "price": 100.0}
        with patch.object(velocity, "analyzer", fake_analyzer), \
             patch.object(config, "VELOCITY_AUTO_MAX_OPEN_POSITIONS", 1), \
             patch.object(config, "VELOCITY_PATTERN_FILTER_ENABLED", True), \
             patch.object(config, "VELOCITY_AUTO_MIN_SCORE", 0.0):  # skor kapısı bu testin konusu değil
            result = await velocity._open_velocity_position(candidate)
        self.assertEqual("SKIPPED", result["status"])
        self.assertEqual("pozisyon_limiti_dolu", result["reason"])

    def test_magic_9999_removed(self):
        self.assertNotIn("9999", _VELOCITY_SRC)
        self.assertIn("if vel_max > 0:", _VELOCITY_SRC)


# ---------------------------------------------------------------------------
# D-13 — token bucket doğru tüketim + throttle'sız REST yolları
# ---------------------------------------------------------------------------
class VelocityRateLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_acquire_consumes_exactly_one_token(self):
        with patch.object(velocity, "_velocity_rate_tokens", 5.0), \
             patch.object(velocity, "_velocity_rate_last_refill", time.time()):
            await velocity._velocity_rate_acquire()
            self.assertAlmostEqual(4.0, velocity._velocity_rate_tokens, delta=0.05)

    def test_no_token_reset_zero_after_sleep(self):
        """Eski hata: uyku sonrası `_velocity_rate_tokens = 0` (token DÜŞMEDEN geç)."""
        src = _VELOCITY_SRC
        # Fonksiyon gövdesini izole et.
        m = re.search(r"async def _velocity_rate_acquire\(\):(.*?)\n(?:async def|def )", src, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertNotIn("_velocity_rate_tokens = 0", body)
        self.assertIn("_velocity_rate_tokens -= 1.0", body)

    def test_sleep_is_outside_the_lock(self):
        """Eski hata: `await asyncio.sleep` `async with _velocity_rate_lock` İÇİNDE."""
        m = re.search(r"async def _velocity_rate_acquire\(\):(.*?)\n(?:async def|def )", _VELOCITY_SRC, re.S)
        body = m.group(1)
        with_idx = body.index("async with _velocity_rate_lock")
        # Docstring'de argümansız "await asyncio.sleep" geçebilir; kod satırını
        # (argümanlı) hedefle ve onun `async with` bloğundan SONRA olduğunu doğrula.
        sleep_idx = body.index("await asyncio.sleep(wait")
        self.assertGreater(sleep_idx, with_idx)
        self.assertIn("# Kilit DIŞINDA bekle", body)

    async def test_hydrate_market_cache_goes_through_limiter(self):
        acquire = AsyncMock(return_value=True)
        with patch.object(velocity, "_velocity_rate_acquire", acquire), \
             patch.object(velocity, "ticker_24h", AsyncMock(return_value=[])), \
             patch.object(velocity, "fetch_klines", AsyncMock(return_value=[])), \
             patch.object(velocity, "orderbook", AsyncMock(return_value={"bids": [], "asks": []})):
            await velocity._hydrate_market_cache_for("TESTTRY")
        self.assertGreaterEqual(acquire.await_count, 2)

    def test_learning_fetch_one_uses_limiter(self):
        self.assertRegex(_VELOCITY_SRC, r"bu REST yolu[\s\S]*?_velocity_rate_acquire")


# ---------------------------------------------------------------------------
# D-14 — breakeven bayrağı yalnızca DB yazımı bloğunda set edilir
# ---------------------------------------------------------------------------
class BreakevenFlagTests(unittest.TestCase):
    def test_flag_assignment_is_inside_db_write_block(self):
        tree = ast.parse(_AUTO_PAPER_SRC)
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "_manage_single_trade")
        target = None
        for node in ast.walk(func):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) \
                    and isinstance(node.test.left, ast.Name) \
                    and node.test.left.id == "applied_breakeven":
                target = node
                break
        self.assertIsNotNone(target, "applied_breakeven < current_price bloğu bulunamadı")
        assigns = [n for n in ast.walk(target)
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "breakeven_activated"
                           for t in n.targets)]
        self.assertTrue(assigns, "breakeven_activated = True DB yazımı bloğunun DIŞINDA")


# ---------------------------------------------------------------------------
# D-15 — reopen kapanış zinciri dışında (arka plan görevi)
# ---------------------------------------------------------------------------
class AsyncReopenTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_trade_schedules_reopen_in_background(self):
        trade = {"id": 1, "symbol": "APTEST", "status": "open", "entry_price": 100.0,
                 "quantity": 1.0, "entry_time": time.time() - 60, "notification_id": "nid-1"}
        started = MagicMock()
        with patch.object(auto_paper.database, "get_auto_paper_trade", AsyncMock(return_value=trade)), \
             patch.object(auto_paper.database, "close_auto_paper_trade", AsyncMock(return_value=True)), \
             patch.object(auto_paper, "_broadcast_trade", AsyncMock()), \
             patch.object(auto_paper, "_maybe_reopen_after_protect_close", AsyncMock()) as reopen_mock, \
             patch.object(auto_paper, "_start_background", started):
            await auto_paper._close_trade(1, "APTEST", 101.0, time.time(), "trailing_stop")
        started.assert_called_once()
        # 2. argüman görev adı olmalı.
        self.assertIn("reopen", started.call_args.args[1])
        self.assertTrue(started.call_args.kwargs.get("single_pass"))
        # _maybe_reopen doğrudan await EDİLMEMELİ (senkron değil).
        reopen_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# D-16 — yönetim döngüsünde üstel backoff + consecutive_errors
# ---------------------------------------------------------------------------
class ManagementLoopBackoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_backoff_grows_and_counter_tracks(self):
        auto_paper._AUTO_PAPER_STATE["consecutive_errors"] = 0
        delays = []

        async def fake_sleep(seconds):
            delays.append(seconds)
            if len(delays) >= 6:
                raise asyncio.CancelledError()

        async def boom():
            raise RuntimeError("db down")

        with patch.object(auto_paper, "_check_open_positions", boom), \
             patch.object(auto_paper.asyncio, "sleep", fake_sleep):
            with self.assertRaises(asyncio.CancelledError):
                await auto_paper.auto_paper_management_loop()
        self.assertEqual(30, delays[0])          # başlangıç uykusu
        self.assertEqual([5, 10, 20, 40, 60], delays[1:6])
        self.assertGreaterEqual(auto_paper._AUTO_PAPER_STATE["consecutive_errors"], 5)


# ---------------------------------------------------------------------------
# I-03 — velocity özel 15-bar ATR, kanonik _atr(14) ile değiştirildi
# ---------------------------------------------------------------------------
class VelocityAtrCanonicalTests(unittest.TestCase):
    def test_velocity_uses_canonical_atr(self):
        self.assertIn("_atr(highs, lows, closes, 14)", _VELOCITY_SRC)
        self.assertNotIn("range(max(1, i - 14), i + 1)", _VELOCITY_SRC)

    def test_canonical_and_old_definition_differ(self):
        from app.technical_analysis import _atr

        n = 40
        closes = [100 + (i % 7) for i in range(n)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        canonical = _atr(highs, lows, closes, 14) / closes[-1] * 100
        # Eski kopya: 15 true-range (i-14..i) basit ortalama
        i = n - 1
        trs = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]),
                   abs(lows[j] - closes[j - 1])) for j in range(max(1, i - 14), i + 1)]
        old = (sum(trs) / len(trs)) / closes[-1] * 100
        self.assertNotAlmostEqual(old, canonical, places=6)


# ---------------------------------------------------------------------------
# I-07 — VELOCITY_MIN_ATR_PCT env-overridable + vestigial global temizlendi
# ---------------------------------------------------------------------------
class VelocityMinAtrEnvTests(unittest.TestCase):
    def test_env_override_present(self):
        self.assertIn('os.getenv("VELOCITY_MIN_ATR_PCT"', _VELOCITY_SRC)

    def test_vestigial_global_removed_from_calibrate(self):
        tree = ast.parse(_VELOCITY_SRC)
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "velocity_calibrate")
        globals_ = [n for n in ast.walk(func)
                    if isinstance(n, ast.Global) and "VELOCITY_MIN_ATR_PCT" in n.names]
        self.assertFalse(globals_, "velocity_calibrate'te vestigial global kalmamalı")


# ---------------------------------------------------------------------------
# G-16 — loop_running gerçek göreve/heartbeat'e bağlı
# ---------------------------------------------------------------------------
class VelocityLoopRunningTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        velocity._VELOCITY_AUTO_LOOP_STARTED = False
        velocity._velocity_auto_state["last_heartbeat_at"] = None

    async def test_stale_heartbeat_reports_not_running(self):
        velocity._VELOCITY_AUTO_LOOP_STARTED = True
        velocity._velocity_auto_state["last_heartbeat_at"] = time.time() - 10_000
        self.assertFalse(velocity.velocity_loop_running())

    async def test_fresh_heartbeat_reports_running(self):
        velocity._VELOCITY_AUTO_LOOP_STARTED = True
        velocity._velocity_auto_state["last_heartbeat_at"] = time.time()
        self.assertTrue(velocity.velocity_loop_running())

    async def test_done_task_reports_not_running(self):
        task = asyncio.create_task(asyncio.sleep(0), name=velocity._VELOCITY_AUTO_TASK_NAME)
        await asyncio.sleep(0.01)
        velocity._background_tasks.add(task)
        velocity._VELOCITY_AUTO_LOOP_STARTED = True
        velocity._velocity_auto_state["last_heartbeat_at"] = time.time()
        try:
            self.assertTrue(task.done())
            self.assertFalse(velocity.velocity_loop_running())
        finally:
            velocity._background_tasks.discard(task)

    async def test_status_endpoint_reports_loop_running(self):
        velocity._VELOCITY_AUTO_LOOP_STARTED = True
        velocity._velocity_auto_state["last_heartbeat_at"] = time.time() - 10_000
        with patch.object(velocity.database, "get_llm_setting", AsyncMock(return_value="1")):
            stale = await velocity.velocity_status()
        self.assertFalse(stale["loop_running"])
        velocity._velocity_auto_state["last_heartbeat_at"] = time.time()
        with patch.object(velocity.database, "get_llm_setting", AsyncMock(return_value="1")):
            fresh = await velocity.velocity_status()
        self.assertTrue(fresh["loop_running"])


# ---------------------------------------------------------------------------
# G-17 — zayıf admin parolası üretimde zorunlu kılınır
# ---------------------------------------------------------------------------
class AdminPasswordPolicyTests(unittest.TestCase):
    def test_weak_passwords_flagged(self):
        for weak in ("12345678", "admin", "password", "short"):
            self.assertIsNotNone(config_module.admin_password_policy_message(weak), weak)

    def test_strong_password_accepted(self):
        self.assertIsNone(config_module.admin_password_policy_message("Str0ng-Pass-Word!"))
        self.assertIsNone(config_module.admin_password_policy_message(""))  # şifre yok → devre dışı

    def test_production_enforces_but_dev_only_warns(self):
        with self.assertRaises(RuntimeError):
            config_module.enforce_admin_password_policy("12345678", production=True)
        # Geliştirme: uyarı verir ama başlatmayı engellemez.
        self.assertIsNone(config_module.enforce_admin_password_policy("12345678", production=False))

    def test_production_mode_flag_exists(self):
        self.assertIsInstance(config_module.PRODUCTION_MODE, bool)


if __name__ == "__main__":
    unittest.main()
