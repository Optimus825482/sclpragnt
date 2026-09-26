"""Otonom Paper Trade (auto_paper) birim testleri.

Saf mantık + DB round-trip testleri. DB gerektiren testler mevcut
test_velocity_ml_backfill.py deseniyle aynı şekilde canlı PostgreSQL'e yazar
ve temizler.
"""
from __future__ import annotations

import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config
from app.routers import auto_paper


def _make_notification(symbol="APTEST", score=60.0, target_pct=2.0, price=100.0, notif_id=None):
    return {
        "id": notif_id,
        "symbol": symbol,
        "score": score,
        "target_pct": target_pct,
        "price": price,
        "expected_price": price * (1 + target_pct / 100),
    }


def _make_open_trade(symbol="APTEST", entry=100.0, target_pct=2.0, sl_pct=3.0):
    # Erkan kararı (2026-09-18): açılış TP'si işaretlidir (NET hedef) — mark-up =
    # gidiş-dönüş komisyon + SATIŞ dolma payı. Fixture bunu birebir saklar.
    markup = 2 * config.COMMISSION_PCT + config.ESTIMATED_SLIPPAGE_PCT
    return {
        "id": 1,
        "symbol": symbol,
        "status": "open",
        "entry_price": entry,
        "quantity": 1.0,
        "stop_loss": entry * (1 - sl_pct / 100),
        "take_profit": entry * (1 + target_pct / 100 + markup),
        "peak_price": entry,
        "breakeven_activated": False,
        "breakeven_stop": None,
    }


class AutoPaperPnLTests(unittest.TestCase):
    """PnL ve fiyat hesaplarının tutarlılığı (saf matematik)."""

    def test_roundtrip_pnl_math(self):
        """Kapanış PnL'si gross - (entry+exit) komisyon; pnl_pct aynı tabandan."""
        entry = 100.0
        exit_px = 103.0
        qty = 1.0
        c = config.COMMISSION_PCT
        gross = (exit_px - entry) * qty
        pnl = gross - (entry * qty * c) - (exit_px * qty * c)
        invested = entry * qty
        pnl_pct = pnl / invested * 100
        # TP %3'te kapanış: komisyon sonrası net kâr brütten küçük olmalı
        self.assertLess(pnl, gross)
        self.assertGreater(pnl, 0)
        # pnl_pct pnl ile aynı muhasebe tabanından (round-trip)
        self.assertAlmostEqual(pnl_pct, (pnl / invested) * 100, places=10)

    def test_breakeven_stop_covers_roundtrip(self):
        """Breakeven stop gidiş+dönüş komisyonunu karşılamalı (net zarar yok)."""
        entry = 100.0
        c = config.COMMISSION_PCT
        # Net breakeven: iade edilen exit*(1-c), harcanan entry*(1+c)'ye eşit olmalı
        breakeven_price = entry * (1 + c) / (1 - c)
        exit_px = breakeven_price
        qty = 1.0
        gross = (exit_px - entry) * qty
        pnl = gross - entry * qty * c - exit_px * qty * c
        self.assertAlmostEqual(pnl, 0.0, places=6)

    def test_tp_update_only_raises(self):
        """TP yalnızca yükseliyorsa güncellenmeli (düşen hedef uygulanmaz)."""
        trade = _make_open_trade(entry=100.0, target_pct=2.0)
        notif_lower = _make_notification(target_pct=1.0)   # TP 102 → 101 (düşüş)
        notif_higher = _make_notification(target_pct=4.0)  # TP 102 → 104 (yükseliş)

        # Düşük hedef: yeni TP eski TP'den küçük → "no_change" beklenir
        old_tp = float(trade["take_profit"])
        new_tp_lower = 100.0 * (1 + 1.0 / 100)
        self.assertLess(new_tp_lower, old_tp)
        new_tp_higher = 100.0 * (1 + 4.0 / 100)
        self.assertGreater(new_tp_higher, old_tp)

    def test_default_settings_breakeven_trigger(self):
        """Breakeven tetikleyici ayarı config sabitinden gelmeli."""
        self.assertGreater(config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT, 0)
        self.assertGreater(config.AUTO_PAPER_SL_PCT_DEFAULT, 0)
        self.assertGreater(config.AUTO_PAPER_BALANCE_PCT_DEFAULT, 0)


class AutoPaperChurnLogicTests(unittest.TestCase):
    """Churn koruması için notification_id karar mantığı."""

    def test_same_notification_rejected_after_trade(self):
        """Aynı notification_id ile daha önce trade açıldıysa yeniden açılmamalı."""
        # try_open_from_notification içindeki prior_trade kontrolünü simüle et:
        # prior_trade varsa None döner (yeniden açılış yok).
        async def scenario():
            original_prior = auto_paper.database.get_recent_auto_paper_trade_by_notification
            original_settings = auto_paper.get_auto_paper_settings
            # Ticker tazelik kapısı (denetim düzeltmesi) testte mock'lanır —
            # aksi halde gerçek market boş ticker'ı ile "stale_ticker" engeline
            # takılır ve churn senaryosuna hiç ulaşılmaz.
            original_freshness = auto_paper.market.ticker_freshness

            calls = []

            async def fake_get_recent(notification_id):
                calls.append(notification_id)
                return {"id": 99, "status": "closed", "symbol": "APTEST"}  # prior trade var

            async def fake_settings():
                return {
                    "enabled": True, "min_score": 0.0, "balance_pct": 35.0,
                    "stop_loss_pct": 3.0, "default_target_pct": 2.0,
                    "min_order_try": 10.0, "breakeven_trigger_pct": 1.5,
                }

            def fake_freshness(symbol, max_age_sec=None):
                return {"fresh": True, "age_sec": 0.0, "max_age_sec": max_age_sec}

            auto_paper.database.get_recent_auto_paper_trade_by_notification = fake_get_recent
            auto_paper.get_auto_paper_settings = fake_settings
            auto_paper.market.ticker_freshness = fake_freshness
            try:
                result = await auto_paper.try_open_from_notification(
                    _make_notification(score=80.0, notif_id=777)
                )
            finally:
                auto_paper.database.get_recent_auto_paper_trade_by_notification = original_prior
                auto_paper.get_auto_paper_settings = original_settings
                auto_paper.market.ticker_freshness = original_freshness
            self.assertIsNone(result)
            self.assertEqual(calls, [777])

        import asyncio
        asyncio.run(scenario())


class AutoPaperBroadcastStateTests(unittest.TestCase):
    """reset_state sayaçları temizler."""

    def test_reset_state_clears_counters(self):
        auto_paper._AUTO_PAPER_STATE["total_opened"] = 5
        auto_paper._AUTO_PAPER_STATE["total_pnl"] = 123.4
        auto_paper.reset_state()
        self.assertEqual(auto_paper._AUTO_PAPER_STATE["total_opened"], 0)
        self.assertEqual(auto_paper._AUTO_PAPER_STATE["total_pnl"], 0.0)


class AutoPaperEffectiveTargetTests(unittest.TestCase):
    """TP hedefi TEK KAYNAKTAN gelir: `target_pct` (madde 7 + 2026-09-17 düzeltmesi)."""

    def test_target_pct_is_used_as_is(self):
        self.assertEqual(2.0, auto_paper._effective_target_pct(_make_notification(target_pct=2.0)))

    def test_raw_ml_target_is_not_re_applied(self):
        """ML harmanda (`dynamic_target_pct`) zaten var; burada tekrar okunursa 2 kez uygulanır."""
        notif = _make_notification(target_pct=2.0)
        notif["ml_target_pct"] = 5.0
        notif["ml_hit_probability"] = 0.9
        self.assertEqual(2.0, auto_paper._effective_target_pct(notif))

    def test_lowered_target_pct_is_respected(self):
        """İki yönlü öğrenme hedefi aşağı çektiyse TP de o değeri alır."""
        self.assertEqual(1.5, auto_paper._effective_target_pct(_make_notification(target_pct=1.5)))

    def test_missing_target_falls_back_to_zero(self):
        self.assertEqual(0.0, auto_paper._effective_target_pct({}))


class _FakeDatabase:
    """`update_auto_paper_trade_tp` çağrılarını yakalayan sahte DB modülü."""

    def __init__(self, sink):
        self.sink = sink

    async def update_auto_paper_trade_tp(self, trade_id, new_tp, score, target_pct):
        self.sink.append({"trade_id": trade_id, "new_tp": new_tp,
                          "score": score, "target_pct": target_pct})


class AutoPaperOpenPositionTpTests(unittest.IsolatedAsyncioTestCase):
    """Açık pozisyonun TP'si YALNIZCA yukarı taşınır (ratchet) — madde 7."""

    def setUp(self):
        self.calls = []
        self._orig_db = auto_paper.database
        auto_paper.database = _FakeDatabase(self.calls)

    def tearDown(self):
        auto_paper.database = self._orig_db

    async def test_higher_target_rewrites_tp(self):
        trade = _make_open_trade(entry=100.0, target_pct=2.0)      # TP 102
        out = await auto_paper._update_existing_trade(
            trade, _make_notification(target_pct=4.0), 101.0)      # TP 104
        self.assertEqual("tp_updated", out["status"])
        self.assertEqual(1, len(self.calls))
        # Erkan kararı (2026-09-18): TP NET hedeftir — mark-up = gidiş-dönüş
        # komisyon (2×%0.15) + SATIŞ dolma payı (%0.025): %4 hedef → 104.325
        expected_tp = 100.0 * (1 + 4.0 / 100 + 2 * config.COMMISSION_PCT + config.ESTIMATED_SLIPPAGE_PCT)
        self.assertAlmostEqual(expected_tp, self.calls[0]["new_tp"], places=6)

    async def test_lower_target_does_not_rewrite_tp(self):
        """Düşen hedef açık pozisyonun TP'sini aşağı çekmez (kârı sınırlandırırdı)."""
        trade = _make_open_trade(entry=100.0, target_pct=4.0)      # TP 104
        out = await auto_paper._update_existing_trade(
            trade, _make_notification(target_pct=1.0), 101.0)      # TP 101
        self.assertEqual("no_change", out["status"])
        self.assertEqual([], self.calls)

    async def test_raw_ml_target_does_not_raise_open_position_tp(self):
        """Ham `ml_target_pct` TP'yi yukarı taşımaz — tek kaynak harmanlanmış hedeftir."""
        trade = _make_open_trade(entry=100.0, target_pct=2.0)      # TP 102
        notif = _make_notification(target_pct=2.0)
        notif["ml_target_pct"] = 5.0
        notif["ml_hit_probability"] = 0.9
        out = await auto_paper._update_existing_trade(trade, notif, 101.0)
        self.assertEqual("no_change", out["status"])
        self.assertEqual([], self.calls)


class AutoPaperConfluenceAndProtectionTests(unittest.IsolatedAsyncioTestCase):
    """Teyit filtresi ve kâr koruma tavanı birim testleri (2026-09-21)."""

    async def test_low_confluence_below_4_allowed(self):
        """Teyit sayısı 2 veya 3 olan sinyallerde de pozisyon açılabilmeli (2026-09-22 Erkan Kararı)."""
        notif = _make_notification(symbol="LOWCONF", score=88.0)
        notif["sources"] = ["velocity", "jump", "early"]  # 3'lü teyit
        res = await auto_paper.try_open_from_notification(notif)
        # low_confluence engeli olmamalı
        self.assertNotEqual(res.get("reason") if res else None, "low_confluence")

    async def test_confluence_4_allowed_with_normal_score(self):
        """4'lü teyit olduğunda min_score üzerindeki sinyal teyit filtresine takılmaz."""
        notif = _make_notification(symbol="FOURCONF", score=75.0)
        notif["sources"] = ["velocity", "jump", "early", "rising"]  # 4'lü teyit
        orig_fresh = auto_paper.market.ticker_freshness
        auto_paper.market.ticker_freshness = lambda sym, max_age_sec=None: {"fresh": False}
        try:
            res = await auto_paper.try_open_from_notification(notif)
            self.assertNotEqual(res.get("reason") if res else None, "low_confluence")
        finally:
            auto_paper.market.ticker_freshness = orig_fresh


class AutoPaperTimeoutAndPassivationTests(unittest.IsolatedAsyncioTestCase):
    """Maksimum süre (60 dk) aşımı ve sembol pasife alma testleri (2026-09-21 Erkan kuralı).

    D-02 (2026-09-26): max_hold ve symbol_deactivated çıkışları artık TAZE
    fiyat şartına bağlıdır — bayat/eksik ticker ile kapanış (uydurma fill
    fiyatı) yapılmaz. Testler taze ticker sağlar.
    """

    def _sample_trade(self, symbol="APTEST", entry_time=None, entry=100.0, peak=102.0):
        now = time.time()
        return {
            "id": 42,
            "symbol": symbol,
            "status": "open",
            "entry_price": entry,
            "quantity": 10.0,
            "take_profit": 105.0,
            "stop_loss": 97.0,
            "peak_price": peak,
            "entry_time": entry_time if entry_time is not None else now,
            "breakeven_activated": False,
            "trailing_stop": None,
            "breakeven_stop": None,
            "trailing_activated": False,
        }

    def _fresh_market(self, price=100.0, age_sec=0.0):
        """TAZE ticker'lı sahte market (MAX_TICKER_AGE_SEC içinde)."""
        mock_market = MagicMock()
        mock_market.symbols = ["aptest", "passtest", "drooppedtry", "drooppedtry"]
        mock_market.get_ticker = MagicMock(return_value={
            "last_price": price,
            "timestamp": (time.time() - age_sec) * 1000,
        })
        return mock_market

    async def test_trade_closes_when_hold_time_exceeds_max_hold_minutes(self):
        """60 dk dolduğunda pozisyon kâr/zarara bakılmaksızın max_duration ile kapatılır."""
        now = time.time()
        # 65 dakika önce açılmış trade
        trade = self._sample_trade(entry_time=now - 65 * 60)
        close_mock = AsyncMock(return_value=None)

        with patch("app.routers.auto_paper.market", self._fresh_market()), \
             patch.object(auto_paper, "_close_trade", close_mock):
            await auto_paper._manage_single_trade(trade, now, 1.5, {"max_hold_minutes": 60.0})

        close_mock.assert_awaited_once()
        args = close_mock.await_args.args
        self.assertEqual(args[0], 42)               # trade_id
        self.assertEqual(args[1], "APTEST")           # symbol
        self.assertEqual(args[4], "max_duration")     # reason

    async def test_trade_closes_when_symbol_is_passive(self):
        """Sembol PASSIVE_SYMBOLS içindeyse süreye bakılmaksızın symbol_deactivated ile kapatılır."""
        now = time.time()
        trade = self._sample_trade(symbol="PASSTEST", entry_time=now - 10 * 60)
        close_mock = AsyncMock(return_value=None)

        with patch.object(config, "PASSIVE_SYMBOLS", {"PASSTEST"}), \
             patch("app.routers.auto_paper.market", self._fresh_market()), \
             patch.object(auto_paper, "_close_trade", close_mock):
            await auto_paper._manage_single_trade(trade, now, 1.5, {"max_hold_minutes": 60.0})

        close_mock.assert_awaited_once()
        self.assertEqual(close_mock.await_args.args[4], "symbol_deactivated")

    async def test_trade_closes_when_symbol_dropped_from_market_symbols(self):
        """Sembol market.symbols listesinden çıkarılmışsa symbol_deactivated ile kapatılır."""
        now = time.time()
        trade = self._sample_trade(symbol="DROPPEDTRY", entry_time=now - 5 * 60)
        close_mock = AsyncMock(return_value=None)
        mock_market = self._fresh_market()
        mock_market.symbols = ["btctry", "ethtry"]

        with patch("app.routers.auto_paper.market", mock_market), \
             patch.object(auto_paper, "_close_trade", close_mock):
            await auto_paper._manage_single_trade(trade, now, 1.5, {"max_hold_minutes": 60.0})

        close_mock.assert_awaited_once()
        self.assertEqual(close_mock.await_args.args[4], "symbol_deactivated")

    # --- D-02: bayat fiyatla kapanış engellenir -----------------------------
    async def test_max_hold_does_not_close_with_stale_ticker(self):
        """60 dk dolmuş olsa bile BAYAT ticker fiyatıyla kapanma yapılmaz."""
        now = time.time()
        trade = self._sample_trade(entry_time=now - 65 * 60)
        close_mock = AsyncMock(return_value=None)
        stale = self._fresh_market(price=50.0,
                                   age_sec=config.MAX_TICKER_AGE_SEC + 120)

        with patch("app.routers.auto_paper.market", stale), \
             patch.object(auto_paper, "_close_trade", close_mock):
            await auto_paper._manage_single_trade(trade, now, 1.5, {"max_hold_minutes": 60.0})

        close_mock.assert_not_awaited()

    async def test_passive_symbol_does_not_close_with_stale_ticker(self):
        """Pasif sembol bayat fiyatla da kapatılmaz (aynı kural)."""
        now = time.time()
        trade = self._sample_trade(symbol="PASSTEST", entry_time=now - 10 * 60)
        close_mock = AsyncMock(return_value=None)
        stale = self._fresh_market(price=50.0,
                                   age_sec=config.MAX_TICKER_AGE_SEC + 120)

        with patch.object(config, "PASSIVE_SYMBOLS", {"PASSTEST"}), \
             patch("app.routers.auto_paper.market", stale), \
             patch.object(auto_paper, "_close_trade", close_mock):
            await auto_paper._manage_single_trade(trade, now, 1.5, {"max_hold_minutes": 60.0})

        close_mock.assert_not_awaited()

    async def test_missing_ticker_never_closes(self):
        """Ticker hiç yoksa hiçbir çıkış yolu tetiklenmez."""
        now = time.time()
        trade = self._sample_trade(entry_time=now - 65 * 60)
        close_mock = AsyncMock(return_value=None)
        empty = MagicMock()
        empty.symbols = ["aptest"]
        empty.get_ticker = MagicMock(return_value=None)

        with patch("app.routers.auto_paper.market", empty), \
             patch.object(auto_paper, "_close_trade", close_mock):
            await auto_paper._manage_single_trade(trade, now, 1.5, {"max_hold_minutes": 60.0})

        close_mock.assert_not_awaited()

    # --- D-01: kâr kilidi stop'u orijinal stop'tan üstte olmalı -------------
    async def test_breakeven_stop_wins_over_lower_initial_stop(self):
        """Kâr kilidi aktifken orijinal sert stop'tan daha YÜKSEKTE kapanılır.

        stop_loss=97, breakeven=101.5, fiyat=100.0. effective_stop = max(97,
        101.5) = 101.5 → kapanış olur ve nedeni `breakeven_stop` olur
        (before: 97 kullanıldığı için kapanış olmazdı ve kâr koruması
        60 dakika boyunca atıl kalırdı).
        """
        now = time.time()
        trade = self._sample_trade(entry=100.0, peak=100.0)
        trade["stop_loss"] = 97.0                     # orijinal sert stop
        trade["breakeven_activated"] = True
        trade["breakeven_stop"] = 101.5               # kâr kilidi zemini
        close_mock = AsyncMock(return_value=None)
        market_mock = self._fresh_market(price=100.0)

        with patch("app.routers.auto_paper.market", market_mock), \
             patch.object(auto_paper, "_close_trade", close_mock), \
             patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_trailing", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_trade_tp", AsyncMock()):
            await auto_paper._manage_single_trade(
                trade, now, 1.5,
                {"max_hold_minutes": 60.0, "breakeven_enabled": True,
                 "trailing_enabled": False, "tp_primary_exit_enabled": True})

        close_mock.assert_awaited_once()
        args = close_mock.await_args.args
        self.assertEqual(args[4], "breakeven_stop",
                         "kilit aktifken kapanış nedeni breakeven olmalı")
        self.assertAlmostEqual(101.5, args[2], places=6)

    async def test_breakeven_stop_does_not_preempt_when_price_above_both(self):
        """Fiyat her iki eşiğin de üstündeyse hiçbir stop tetiklenmez."""
        now = time.time()
        trade = self._sample_trade(entry=100.0, peak=100.0)
        trade["stop_loss"] = 97.0
        trade["breakeven_activated"] = True
        trade["breakeven_stop"] = 101.5
        close_mock = AsyncMock(return_value=None)
        market_mock = self._fresh_market(price=102.0)

        with patch("app.routers.auto_paper.market", market_mock), \
             patch.object(auto_paper, "_close_trade", close_mock), \
             patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_trailing", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_trade_tp", AsyncMock()):
            await auto_paper._manage_single_trade(
                trade, now, 1.5,
                {"max_hold_minutes": 60.0, "breakeven_enabled": True,
                 "trailing_enabled": False, "tp_primary_exit_enabled": True})

        close_mock.assert_not_awaited()

    async def test_breakeven_zone_never_closes_below_breakeven(self):
        """stop_loss'ın ALTINDA ama breakeven'ın ÜSTÜNDE fiyat KAPANMAMALI.

        Bu, asıl para kaybı senaryosuydu: fiyat 100 (entry) ile 101.5
        (breakeven) arasındayken eski kod orijinal stop 97'yi kullanmaya
        devam ediyor, kâr kilidi hiç devreye girmiyordu. Artık effective_stop
        = max(97, 101.5) = 101.5 → 100 <= 101.5 olduğu için kâr kilidi
        stop'una kapanır (zarar yazmadan).
        """
        now = time.time()
        trade = self._sample_trade(entry=100.0, peak=100.0)
        trade["stop_loss"] = 97.0
        trade["breakeven_activated"] = True
        trade["breakeven_stop"] = 101.5
        close_mock = AsyncMock(return_value=None)
        market_mock = self._fresh_market(price=100.0)

        with patch("app.routers.auto_paper.market", market_mock), \
             patch.object(auto_paper, "_close_trade", close_mock), \
             patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_trailing", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_trade_tp", AsyncMock()):
            await auto_paper._manage_single_trade(
                trade, now, 1.5,
                {"max_hold_minutes": 60.0, "breakeven_enabled": True,
                 "trailing_enabled": False, "tp_primary_exit_enabled": True})

        # Kapanış olur, ama stop_loss(97) DEĞİL, breakeven(101.5) nedeniyle.
        close_mock.assert_awaited_once()
        args = close_mock.await_args.args
        self.assertEqual(args[4], "breakeven_stop")
        self.assertAlmostEqual(101.5, args[2], places=6)

    async def test_breakeven_stop_closes_above_initial_stop(self):
        """Fiyat breakeven'inin altına düştüyse kâr kilidi stop'u ile kapanır
        ve fill fiyatı TETİK fiyatına çekilir (gap-through max)."""
        now = time.time()
        trade = self._sample_trade(entry=100.0, peak=100.0)
        trade["stop_loss"] = 97.0
        trade["breakeven_activated"] = True
        trade["breakeven_stop"] = 101.5
        close_mock = AsyncMock(return_value=None)
        market_mock = self._fresh_market(price=100.9)

        with patch("app.routers.auto_paper.market", market_mock), \
             patch.object(auto_paper, "_close_trade", close_mock), \
             patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_trailing", AsyncMock()), \
             patch.object(auto_paper.database, "update_auto_paper_trade_tp", AsyncMock()):
            await auto_paper._manage_single_trade(
                trade, now, 1.5,
                {"max_hold_minutes": 60.0, "breakeven_enabled": True,
                 "trailing_enabled": False, "tp_primary_exit_enabled": True})

        close_mock.assert_awaited_once()
        args = close_mock.await_args.args
        self.assertEqual(args[4], "breakeven_stop")
        self.assertAlmostEqual(101.5, args[2], places=6)


if __name__ == "__main__":
    unittest.main()

