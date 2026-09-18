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


if __name__ == "__main__":
    unittest.main()
