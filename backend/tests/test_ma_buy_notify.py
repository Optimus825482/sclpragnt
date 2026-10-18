"""MA BUY sinyali → TF etiketli push + otonom paper (app/ma_buy_notify.py, 2026-10-18)."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from app import ma_buy_notify
from app.routers import auto_paper, monitoring

PER = (7, 20, 99)


def _row(symbol="ABCTRY", tf="1m", age_ms=5_000, rules="fast_cross_mid", now_ms=None, price=10.0):
    now_ms = now_ms or int(time.time() * 1000)
    tf_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000}[tf]
    close = now_ms - age_ms
    return {"symbol": symbol, "timeframe": tf, "bar_open_ms": close - tf_ms, "bar_close_ms": close,
            "rules": rules, "signal_price": price}


class BuildNotificationTests(unittest.TestCase):
    def test_title_and_message_carry_timeframe_and_cross(self):
        n = ma_buy_notify.build_notification(_row(tf="5m", rules="fast_cross_mid,mid_cross_slow"), PER, now=1.0)
        self.assertEqual(n["title"], "📈 ABCTRY · MA BUY (M5)")
        self.assertIn("M5 grafikte BUY sinyali", n["message"])
        self.assertIn("EMA7 ↗ EMA20 + EMA20 ↗ EMA99", n["message"])
        self.assertEqual(n["url"], "/charts?symbol=ABCTRY&timeframe=5m")
        self.assertEqual((n["source"], n["mode"], n["timeframe"]), ("ma_buy", "ma_buy", "5m"))
        self.assertTrue(n["notification_key"].startswith("ma-5m-ABCTRY-"))
        self.assertNotIn("score", n)  # skorsuz kural sinyali: radar skor kapısı uygulanmaz

    def test_target_pct_per_timeframe_with_fallback(self):
        with patch.object(ma_buy_notify.config, "MA_BUY_TARGET_PCT", "1m:0.8,5m:1.6", create=True):
            self.assertEqual(ma_buy_notify.target_pct("1m"), 0.8)
            self.assertEqual(ma_buy_notify.target_pct("5m"), 1.6)
            self.assertEqual(ma_buy_notify.target_pct("15m"), float(ma_buy_notify.config.AUTO_PAPER_DEFAULT_TARGET_PCT))

    def test_only_fresh_bar_is_notified(self):
        now = int(time.time() * 1000)
        self.assertTrue(ma_buy_notify.is_fresh(_row(age_ms=5_000, now_ms=now), now))
        self.assertFalse(ma_buy_notify.is_fresh(_row(age_ms=10 * 60_000, now_ms=now), now))


class DeliverTests(unittest.TestCase):
    def setUp(self):
        ma_buy_notify._last_push.clear()
        self.claimed = iter(range(1, 100))
        self.pushes = []
        self.opened = []
        self.marks = []

    def _run(self, rows, *, push_ok=True, settings=None, quiet=False, claim=None, opened=None):
        async def send(n):
            self.pushes.append(n)
            return push_ok

        async def try_open(n):
            self.opened.append(n)
            return opened if opened is not None else {"trade_id": 55}

        async def mark(sid, **kw):
            self.marks.append((sid, kw))

        claim_mock = claim or AsyncMock(side_effect=lambda *a: next(self.claimed))
        with patch.object(monitoring, "get_user_notification_settings", AsyncMock(return_value=settings or {"enabled": True})), \
                patch.object(monitoring, "_in_quiet_hours", return_value=quiet), \
                patch.object(monitoring, "_vapid_configured", return_value=True), \
                patch.object(monitoring, "_send_push", side_effect=send), \
                patch.object(monitoring.ws_manager, "broadcast", AsyncMock()), \
                patch.object(ma_buy_notify.database, "claim_ma_buy_notify", claim_mock), \
                patch.object(ma_buy_notify.database, "mark_ma_buy_delivery", side_effect=mark), \
                patch.object(auto_paper, "try_open_from_notification", side_effect=try_open):
            return asyncio.run(ma_buy_notify.deliver(rows, PER))

    def test_m1_and_m5_push_and_open_paper(self):
        n = self._run([_row("AAATRY", "1m"), _row("BBBTRY", "5m", age_ms=20_000)])
        self.assertEqual(n, 2)
        self.assertEqual({p["title"] for p in self.pushes}, {"📈 AAATRY · MA BUY (M1)", "📈 BBBTRY · MA BUY (M5)"})
        self.assertTrue(all(o["sent_via_push"] for o in self.opened))
        self.assertIn((1, {"paper_status": "acildi", "paper_trade_id": 55}), self.marks)

    def test_same_symbol_both_timeframes_single_push_bigger_tf_first(self):
        self._run([_row("AAATRY", "1m"), _row("AAATRY", "5m", age_ms=20_000)])
        self.assertEqual([p["timeframe"] for p in self.pushes], ["5m"])

    def test_stale_or_untracked_timeframe_not_pushed(self):
        self._run([_row(age_ms=30 * 60_000), _row(tf="15m", age_ms=5_000)])
        self.assertEqual(self.pushes, [])

    def test_already_notified_bar_is_skipped(self):
        self._run([_row()], claim=AsyncMock(return_value=None))
        self.assertEqual(self.pushes, [])

    def test_failed_push_records_and_does_not_open_paper(self):
        self._run([_row()], push_ok=False)
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(self.opened, [])
        self.assertIn((1, {"push_ok": False}), self.marks)

    def test_disabled_notifications_or_quiet_hours_send_nothing(self):
        self._run([_row()], settings={"enabled": False})
        self._run([_row()], quiet=True)
        self.assertEqual(self.pushes, [])

    def test_cooldown_blocks_second_push_same_symbol(self):
        self._run([_row()])
        self._run([_row()])
        self.assertEqual(len(self.pushes), 1)

    def test_blocked_paper_reason_is_recorded(self):
        self._run([_row()], opened={"status": "blocked", "reason": "symbol_dedup"})
        self.assertIn((1, {"paper_status": "symbol_dedup", "paper_trade_id": None}), self.marks)


class RuleSignalGateTests(unittest.TestCase):
    """MA kural sinyali skor/mod kapısına takılmaz; kendi anahtarı kapalıysa açılmaz."""

    def _run(self, notification, settings):
        async def scenario():
            fake = {"enabled": True, **settings}
            with patch.object(auto_paper, "get_auto_paper_settings", AsyncMock(return_value=fake)):
                return await auto_paper.try_open_from_notification(notification)
        return asyncio.run(scenario())

    def _notif(self):
        n = ma_buy_notify.build_notification(_row("ZZZTRY", "5m"), PER)
        n["sent_via_push"] = True
        return n

    def test_score_and_mode_gates_do_not_apply(self):
        res = self._run(self._notif(), {"min_score": 99.0, "allowed_modes": ["unified"]})
        if res is not None:
            self.assertNotIn(res.get("reason"), ("score_below_min", "mode_not_allowed"))

    def test_own_switch_blocks_when_off(self):
        with patch.object(auto_paper.config, "MA_BUY_AUTO_PAPER_ENABLED", False, create=True):
            res = self._run(self._notif(), {"min_score": 0.0})
        self.assertEqual(res.get("reason"), "ma_buy_paper_kapali")


if __name__ == "__main__":
    unittest.main()
