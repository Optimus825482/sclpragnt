"""Web push teslimat seçenekleri (mobil/PWA denetimi P3, 2026-10-18).

pywebpush varsayılanı ttl=0 + Urgency yok + timeout yok: telefon kısa süre erişilemezse
bildirim kaybolur, askıda bir uç nokta tüm turu bloke eder.
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from app import alerting


class PushTtlTests(unittest.TestCase):
    def test_horizon_maps_to_ttl_within_bounds(self):
        self.assertEqual(600, alerting.push_ttl_seconds({"horizon_minutes": 10}))
        self.assertEqual(900, alerting.push_ttl_seconds({"horizon_minutes": 15}))

    def test_ttl_is_clamped(self):
        self.assertEqual(300, alerting.push_ttl_seconds({"horizon_minutes": 1}))
        # sessiz saatten ertelenen alarm (24 sa ufuk) en çok 15 dk
        self.assertEqual(900, alerting.push_ttl_seconds({"horizon_minutes": 24 * 60}))

    def test_missing_or_bad_horizon_uses_default(self):
        for extra in (None, {}, {"horizon_minutes": None}, {"horizon_minutes": "x"}, {"horizon_minutes": 0}, {"horizon_minutes": -5}):
            self.assertEqual(alerting.PUSH_TTL_DEFAULT_SEC, alerting.push_ttl_seconds(extra), extra)


class PushTopicTests(unittest.TestCase):
    def test_topic_is_url_safe_and_max_32(self):
        topic = alerting.push_topic("scalper-radar:BTCTRY/çok uzun bir etiket 1234567890")
        self.assertLessEqual(len(topic), 32)
        self.assertRegex(topic, r"^[A-Za-z0-9_-]+$")

    def test_plain_tag_is_kept(self):
        self.assertEqual("alert-12", alerting.push_topic("alert-12"))

    def test_empty_tag_has_no_topic(self):
        self.assertIsNone(alerting.push_topic(None))
        self.assertIsNone(alerting.push_topic("///"))

    def test_headers_always_urgent(self):
        self.assertEqual({"Urgency": "high", "Topic": "alert-12"}, alerting.push_headers("alert-12"))
        self.assertEqual({"Urgency": "high"}, alerting.push_headers(None))


class DeliverWebPushOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_webpush_called_with_ttl_urgency_topic_timeout(self):
        async def fake_list(usernames=None):
            return [{"endpoint": "https://push.example/1"}, {"endpoint": "https://push.example/2"}]

        fake = MagicMock()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "test-key"}), \
             patch("app.database.list_push_subscriptions", new=fake_list), \
             patch("pywebpush.webpush", fake):
            result = await alerting.deliver_web_push(
                "BTCTRY radar", title="Radar", url="/charts?symbol=BTCTRY", tag="radar-BTCTRY",
                extra={"horizon_minutes": 10})
        self.assertTrue(result["ok"])
        self.assertEqual(2, fake.call_count)
        for call in fake.call_args_list:
            self.assertEqual(600, call.kwargs["ttl"])
            self.assertEqual({"Urgency": "high", "Topic": "radar-BTCTRY"}, call.kwargs["headers"])
            self.assertEqual(alerting.PUSH_TIMEOUT_SEC, call.kwargs["timeout"])
            # ölü alan (`/alarm.wav`) artık payload'da yok
            self.assertNotIn("sound", json.loads(call.kwargs["data"]))

    async def test_failing_endpoint_does_not_block_others_and_dead_one_is_removed(self):
        async def fake_list(usernames=None):
            return [{"endpoint": "https://push.example/dead"}, {"endpoint": "https://push.example/ok"}]

        def fake_webpush(subscription_info=None, **kwargs):
            if subscription_info["endpoint"].endswith("dead"):
                raise RuntimeError("Push failed: 410 Gone")
            return "ok"

        removed = []

        async def fake_remove(endpoints):
            removed.extend(endpoints)

        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "test-key"}), \
             patch("app.database.list_push_subscriptions", new=fake_list), \
             patch("app.database.remove_push_subscriptions", new=fake_remove), \
             patch("pywebpush.webpush", fake_webpush):
            result = await alerting.deliver_web_push("x", tag="t")
        self.assertEqual(1, result["count"])
        self.assertEqual(1, result["dead_count"])
        self.assertEqual(["https://push.example/dead"], removed)


if __name__ == "__main__":
    unittest.main()
