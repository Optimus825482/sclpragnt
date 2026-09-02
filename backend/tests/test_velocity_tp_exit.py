"""Otonom hız avcısı çıkışı: trailing yok, hedef TP'de chat_plan_take_profit."""
import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.analyzer import ScalpAnalyzer  # noqa: E402


def _velocity_pos(entry=100.0, max_price=100.0, tp_pct=2.0, entry_time=None):
    """no_initial_stop + plan TP'li otonom hız avcısı pozisyonu."""
    return {
        "symbol": "TESTTRY", "strategy": "CHAT_PREDICTION", "side": "LONG",
        "entry_price": entry, "quantity": 1.0,
        "entry_time": entry_time if entry_time is not None else time.time(),
        "max_price": max_price, "min_price": entry,
        "system_stop_price": None,
        "system_take_profit_price": entry * (1 + tp_pct / 100.0),
        "take_profit": entry * (1 + tp_pct / 100.0),
        "entry_context": {"signal_context": {"no_initial_stop": True,
                                             "target_pct": tp_pct,
                                             "exit_model": "plan_tp"}},
    }


def _make_analyzer(pos, price, closed=None):
    analyzer = ScalpAnalyzer.__new__(ScalpAnalyzer)
    analyzer.positions = {"TESTTRY": pos}
    analyzer.market = MagicMock()
    now_ms = time.time() * 1000
    analyzer.market.get_ticker = MagicMock(
        return_value={"last_price": price, "timestamp": now_ms})
    analyzer.market.get_ut_kline = MagicMock(return_value=None)
    close = AsyncMock(return_value=closed or {"ok": True, "reason": "x"})
    return analyzer, close


class VelocityTPExitTests(unittest.IsolatedAsyncioTestCase):
    async def test_tp_hit_closes_with_chat_plan_take_profit(self):
        """Fiyat hedef TP'ye ulaşınca trailing değil take_profit ile kapanır."""
        pos = _velocity_pos(entry=100.0, tp_pct=2.0)  # TP = 102.0
        analyzer, close = _make_analyzer(pos, 102.0,
                                         closed={"ok": True, "reason": "chat_plan_take_profit"})
        with patch.object(analyzer, "close_position", close), \
             patch("app.analyzer.config.MAX_TICKER_AGE_SEC", 3600), \
             patch("app.analyzer.config.VELOCITY_MAX_HOLD_MIN", 30):
            await analyzer._manage_open_position("TESTTRY", 102.0, "CHAT_PREDICTION")
        close.assert_awaited_once()
        reason = close.await_args.args[2]
        self.assertEqual(reason, "chat_plan_take_profit")

    async def test_price_below_tp_but_above_lock_stays_open(self):
        """Kâr kilidi (+%0.5) stop'u maliyet üstüne çeker ama TP'ye ulaşılmadıysa
        trailing olmadığı için pozisyon açık kalır (erken kapanış yok)."""
        pos = _velocity_pos(entry=100.0, max_price=103.0, tp_pct=2.0)  # TP=102
        # max 103 görüldü → kâr kilidi devrede; fiyat 101.5 (TP altı, lock-stop üstü)
        analyzer, close = _make_analyzer(pos, 101.5)
        with patch.object(analyzer, "close_position", close), \
             patch("app.analyzer.config.MAX_TICKER_AGE_SEC", 3600), \
             patch("app.analyzer.config.VELOCITY_MAX_HOLD_MIN", 30):
            result = await analyzer._manage_open_position("TESTTRY", 101.5, "CHAT_PREDICTION")
        # Kapanış çağrılmamalı (ne trailing ne TP ne stop)
        close.assert_not_awaited()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

