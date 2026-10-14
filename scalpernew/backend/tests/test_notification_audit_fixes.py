"""Bildirim/otonom-işlem denetimi düzeltmeleri (2026-09-16).

Kapsam:
  W1  `auto_paper` boyutlandırma — `balance_pct` baypası (tüm bakiye riski)
  W3a alarm cooldown TABANI — `cooldown_seconds=0` ile saniyelik alarm fırtınası
  W3b alarm push'u sessiz saatlere SAYGILI (radar ile aynı sözleşme)
  W2  push zarfı dayanıklılığı (`_send_push` iki zarf şeklini de taşır)
"""
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import alerting                              # noqa: E402
from app.routers import auto_paper, monitoring        # noqa: E402


class AutoPaperSizingTests(unittest.IsolatedAsyncioTestCase):
    """W1 — risk bütçesi min emrin altındaysa AÇMA; tüm bakiyeyi riske atma."""

    async def test_risk_budget_below_min_order_blocks_full_balance(self):
        """bakiye 100 × %35 = 35 TRY < min 50 TRY → BLOKE (eskiden 100 TRY ile açılırdı)."""
        result = await auto_paper._open_new_trade(
            "AAA", {"target_pct": 2.0}, 10.0,
            {"balance_pct": 35, "min_order_try": 50},
            order_value=35.0, balance=100.0,
        )
        self.assertEqual("blocked", result["status"])
        self.assertEqual("order_below_min", result["reason"])
        # Engel NEDENİ görünür olmalı (operatör hangi ayarı hizalayacağını görsün).
        self.assertEqual(35.0, result["order_value"])
        self.assertEqual(50.0, result["min_order"])
        self.assertEqual(100.0, result["balance"])
        self.assertEqual(35.0, result["balance_pct"])

    async def test_sufficient_budget_does_not_trip_the_guard(self):
        """Bütçe min emri karşılıyorsa boyut kapısı DEVREYE GİRMEZ (kilit yanlış pozitif üretmesin)."""
        opened = AsyncMock(return_value=({"id": 7}, "opened"))
        with patch.object(auto_paper.database, "open_auto_paper_trade", opened), \
             patch.object(auto_paper, "_broadcast_trade", AsyncMock(return_value=None)):
            result = await auto_paper._open_new_trade(
                "AAA", {"target_pct": 2.0}, 10.0,
                {"balance_pct": 35, "min_order_try": 50},
                order_value=60.0, balance=200.0,
            )
        self.assertIsNotNone(result)
        self.assertNotEqual("order_below_min", (result or {}).get("reason"))


class AlertCooldownFloorTests(unittest.TestCase):
    """W3a — motor tarafında TABAN: hiçbir kural saniyede bir ateşleyemez."""

    def test_zero_cooldown_still_blocked_within_floor(self):
        rule = {"last_triggered_at": 1000.0, "cooldown_seconds": 0}
        # 0.5 sn sonra: eskiden SERBESTTİ (her saniye event + push + otonom deneme)
        self.assertTrue(alerting._cooldown_blocks(rule, 1000.5))
        # Taban dolunca serbest
        self.assertFalse(alerting._cooldown_blocks(rule, 1000.0 + alerting.ALERT_MIN_COOLDOWN_SEC))

    def test_configured_cooldown_above_floor_wins(self):
        rule = {"last_triggered_at": 1000.0, "cooldown_seconds": 7200}
        self.assertTrue(alerting._cooldown_blocks(rule, 1000.0 + 3600))
        self.assertFalse(alerting._cooldown_blocks(rule, 1000.0 + 7200))

    def test_never_triggered_is_not_blocked(self):
        self.assertFalse(alerting._cooldown_blocks({"cooldown_seconds": 0}, 5.0))

    def test_malformed_last_triggered_does_not_block(self):
        """Bozuk zaman damgası kuralı KALICI susturmamalı (fail-open)."""
        self.assertFalse(alerting._cooldown_blocks({"last_triggered_at": "bozuk", "cooldown_seconds": 60}, 5.0))


class AlertStormRegressionTests(unittest.IsolatedAsyncioTestCase):
    """W3a — uçtan uca: `cooldown_seconds=0` kuralı ART ARDA ateşleyemez."""

    def _market(self):
        market = MagicMock()
        market.get_ticker = MagicMock(return_value={"last_price": 90.0})
        return market

    async def test_zero_cooldown_rule_does_not_refire_immediately(self):
        now = 10_000.0
        rule = {
            "id": 3, "symbol": "BTCTRY", "timeframe": "5m", "rule_type": "price",
            "operator": "lte", "threshold": 95.0, "rearm_threshold": None,
            "armed": True, "cooldown_seconds": 0,
            "last_triggered_at": now - 0.5,   # YARIM SANİYE önce ateşledi
            "notify_channels": ["websocket"],
        }
        record = AsyncMock(return_value={"id": 1})
        # NOT: `_alert_rules_cache` modül-GLOBAL'idir; doğrudan yazmak diğer
        # testlere sızar (flaky). `patch.object` ile taze bir cache verilir ve
        # test sonunda otomatik geri alınır.
        with patch.object(alerting, "_alert_rules_cache", {"at": 0.0, "rules": []}), \
             patch("app.alerting.database.list_alert_rules", AsyncMock(return_value=[rule])), \
             patch("app.alerting.database.record_alert_trigger", record), \
             patch("app.alerting.time.time", return_value=now):
            events = await alerting.evaluate_rules(self._market())
        self.assertEqual([], events, "cooldown=0 kuralı saniyede bir ateşlememeli")
        record.assert_not_awaited()


class AlertPushDeliveryTests(unittest.IsolatedAsyncioTestCase):
    """W3b — alarm push'u sessiz saatte ERTELENİR; event yine üretilir."""

    def setUp(self):
        monitoring._deferred_push.clear()
        self.addCleanup(monitoring._deferred_push.clear)

    async def test_push_deferred_during_quiet_hours(self):
        with patch.object(monitoring, "quiet_hours_active", AsyncMock(return_value=True)), \
             patch.object(alerting, "deliver_web_push", AsyncMock(return_value={"ok": True})) as push:
            result = await alerting.deliver_alert_push("BTCTRY alarmı", tag="alert-3")
        self.assertTrue(result["deferred"])
        self.assertEqual("quiet_hours", result["reason"])
        push.assert_not_awaited()
        self.assertEqual(1, len(monitoring._deferred_push))
        queued = monitoring._deferred_push[-1]
        self.assertEqual("BTCTRY alarmı", queued["message"])
        self.assertEqual("alert-3", queued["tag"])
        # Ertelenen zarf flush yolunun beklediği TTL alanlarını taşımalı.
        self.assertIn("detected_at", queued)
        self.assertEqual(24 * 60, queued["horizon_minutes"])

    async def test_push_sent_when_not_quiet(self):
        with patch.object(monitoring, "quiet_hours_active", AsyncMock(return_value=False)), \
             patch.object(alerting, "deliver_web_push", AsyncMock(return_value={"ok": True})) as push:
            result = await alerting.deliver_alert_push("BTCTRY alarmı")
        self.assertTrue(result["ok"])
        push.assert_awaited()
        self.assertEqual(0, len(monitoring._deferred_push))

    async def test_push_sent_when_quiet_query_fails(self):
        """Sessizlik sorgusu arızalıysa ALARM SUSTURULMAZ (fail-open, açık kullanıcı niyeti)."""
        with patch.object(monitoring, "quiet_hours_active", AsyncMock(side_effect=RuntimeError("db"))), \
             patch.object(alerting, "deliver_web_push", AsyncMock(return_value={"ok": True})) as push:
            result = await alerting.deliver_alert_push("BTCTRY alarmı")
        self.assertTrue(result["ok"])
        push.assert_awaited()

    async def test_push_result_recorded_on_event(self):
        """Push sonucu olay yüküne yazılır → alarm tarafında da dürüstlük görünür."""
        now = 5_000.0
        rule = {
            "id": 9, "symbol": "BTCTRY", "timeframe": "5m", "rule_type": "price",
            "operator": "lte", "threshold": 95.0, "rearm_threshold": None,
            "armed": True, "cooldown_seconds": 1800, "last_triggered_at": None,
            "notify_channels": ["web_push"],
        }
        market = MagicMock()
        market.get_ticker = MagicMock(return_value={"last_price": 90.0})
        with patch.object(alerting, "_alert_rules_cache", {"at": 0.0, "rules": []}), \
             patch("app.alerting.database.list_alert_rules", AsyncMock(return_value=[rule])), \
             patch("app.alerting.database.record_alert_trigger",
                   AsyncMock(return_value={"id": 11, "triggered_at": now})), \
             patch("app.alerting.time.time", return_value=now), \
             patch.object(alerting, "deliver_alert_push",
                          AsyncMock(return_value={"ok": False, "reason": "vapid_not_configured"})):
            events = await alerting.evaluate_rules(market)
        self.assertEqual(1, len(events))
        self.assertEqual({"ok": False, "reason": "vapid_not_configured"},
                         events[0]["data"]["push_result"])


class PushEnvelopeRobustnessTests(unittest.IsolatedAsyncioTestCase):
    """W2 — `_send_push` artık İKİ zarfı taşır: radar bildirimi ve alarm push'u."""

    async def test_alert_envelope_does_not_raise(self):
        """Alarm zarfı skor/hedef taşımaz; eski `notif[\"...\"]` erişimi KeyError verirdi."""
        sender = AsyncMock(return_value={"ok": True})
        with patch.object(monitoring, "deliver_web_push", sender):
            ok = await monitoring._send_push({
                "message": "alarm", "title": "t", "url": "/alerts", "tag": "alert-1",
            })
        self.assertTrue(ok)
        extra = sender.await_args.kwargs["extra"]
        self.assertIsNone(extra["score"])
        self.assertIsNone(extra["target_pct"])
        self.assertEqual("monitoring", extra["source"])

    async def test_radar_envelope_still_carries_its_fields(self):
        sender = AsyncMock(return_value={"ok": True})
        with patch.object(monitoring, "deliver_web_push", sender):
            ok = await monitoring._send_push({
                "message": "radar", "title": "t", "url": "/charts", "tag": "radar-X",
                "symbol": "BTCTRY", "score": 88.0, "target_pct": 2.5, "price": 10.0,
                "expected_price": 10.25, "detected_at": 1.0, "horizon_minutes": 5,
            })
        self.assertTrue(ok)
        extra = sender.await_args.kwargs["extra"]
        self.assertEqual("BTCTRY", extra["symbol"])
        self.assertEqual(88.0, extra["score"])
        self.assertEqual(2.5, extra["target_pct"])


if __name__ == "__main__":
    unittest.main()
