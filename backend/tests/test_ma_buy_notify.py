"""MA BUY sinyali → TF etiketli push + otonom paper (app/ma_buy_notify.py, 2026-10-18)."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from app import ma_buy_notify
from app.routers import auto_paper, monitoring

PER = (7, 20, 99)


def _row(symbol="ABCTRY", tf="15m", age_ms=5_000, rules="fast_cross_mid", now_ms=None, price=10.0):
    # 2026-10-26: varsayilan TF 15m (M5 push'u kaldirildi; mekanizma testleri TF'den bagimsiz).
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

    def test_notify_timeframes_excludes_5m_and_30m(self):
        # 2026-10-26: M5 ve M30 push'u kaldirildi; kayitli ayar icerse bile notify_timeframes disarida tutar.
        with patch.object(ma_buy_notify.config, "MA_BUY_NOTIFY_TIMEFRAMES", "1m,5m,15m,30m,1h,4h", create=True):
            self.assertEqual(ma_buy_notify.notify_timeframes(), {"1m", "15m", "1h", "4h"})

    def test_only_fresh_bar_is_notified(self):
        now = int(time.time() * 1000)
        self.assertTrue(ma_buy_notify.is_fresh(_row(age_ms=5_000, now_ms=now), now))
        self.assertFalse(ma_buy_notify.is_fresh(_row(age_ms=10 * 60_000, now_ms=now), now))


class DisabledTests(unittest.TestCase):
    """2026-11-25 (kullanıcı isteği): MA kesişim bildirimi KAPATILDI.

    Bildirim yolu kapalı olduğu için `deliver()` hiçbir push üretmez ve otonom
    paper açılmaz (paper push'a bağlıdır). Sinyal kaydı ve ölçüm döngüsü ayrı
    konulardır; burada yalnız bildirim sözleşmesi doğrulanır.
    """

    def test_notifications_are_disabled(self):
        self.assertFalse(ma_buy_notify.enabled())

    def test_deliver_is_noop_while_disabled(self):
        pushed = []
        opened = []

        async def send(n):
            pushed.append(n)

        async def paper(notification):
            opened.append(notification)
            return {"status": "opened"}

        with patch.object(monitoring, "_send_push", AsyncMock(side_effect=send)),              patch.object(auto_paper, "try_open_from_notification", AsyncMock(side_effect=paper)):
            sent = asyncio.run(ma_buy_notify.deliver([_row()], ("1m", "5m", "15m", "1h", "4h")))

        self.assertEqual(sent, 0)
        self.assertEqual(pushed, [], "bildirim kapalıyken push gitmemeli")
        self.assertEqual(opened, [], "bildirim kapalıyken otonom paper açılmamalı")


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
