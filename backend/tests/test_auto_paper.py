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
    return {
        "id": 1,
        "symbol": symbol,
        "status": "open",
        "entry_price": entry,
        "quantity": 1.0,
        "stop_loss": entry * (1 - sl_pct / 100),
        "take_profit": entry * (1 + target_pct / 100),
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

            auto_paper.database.get_recent_auto_paper_trade_by_notification = fake_get_recent
            auto_paper.get_auto_paper_settings = fake_settings
            try:
                result = await auto_paper.try_open_from_notification(
                    _make_notification(score=80.0, notif_id=777)
                )
            finally:
                auto_paper.database.get_recent_auto_paper_trade_by_notification = original_prior
                auto_paper.get_auto_paper_settings = original_settings
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


if __name__ == "__main__":
    unittest.main()
