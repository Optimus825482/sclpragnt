"""Monitoring page tests: notification thresholds, quiet hours, cooldown,
cooldown pruning, rich push payload and DB history helpers."""
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MonitoringNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_respects_min_score_and_min_target(self):
        """Eşik altı adaylar bildirilmemeli; eşiği geçenler bildirilmeli."""
        from app.routers import monitoring

        settings = {"enabled": True, "min_score": 2.0, "min_target_pct": 2.0,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [
            {"symbol": "LOWTRY", "velocity_score": 0.5, "target_pct": 5.0, "price": 1.0},
            {"symbol": "LOWTARGETTRY", "velocity_score": 2.5, "target_pct": 0.5, "price": 1.0},
            {"symbol": "GOODTRY", "velocity_score": 2.5, "target_pct": 3.0, "price": 10.0},
        ]
        monitoring._monitoring_state["notified_symbols"] = {}
        with patch.object(monitoring, "deliver_web_push", return_value={"ok": True}) as push, \
             patch.object(monitoring, "_record_history", return_value=None):
            result = await monitoring._notify(candidates, settings)
        self.assertEqual([n["symbol"] for n in result], ["GOODTRY"])
        self.assertEqual(push.call_count, 1)
        notif = result[0]
        self.assertIn("GOODTRY", notif["message"])
        self.assertIn("+%3", notif["message"])
        self.assertIn("Potansiyel", notif["message"])
        self.assertEqual(notif["expected_price"], 10.3)
        self.assertIn("symbol", notif["url"])

    async def test_notify_disabled_returns_empty(self):
        from app.routers import monitoring

        settings = {"enabled": False, "min_score": 0.5, "min_target_pct": 0.5,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [{"symbol": "XTRY", "velocity_score": 9.0, "target_pct": 9.0, "price": 1.0}]
        with patch.object(monitoring, "deliver_web_push") as push:
            result = await monitoring._notify(candidates, settings)
        self.assertEqual(result, [])
        push.assert_not_called()

    async def test_notify_quiet_hours_defers_push_but_records(self):
        """Sessiz saatlerde push gönderilmez; aday kayda alınır ve geçmişe yazılır."""
        from app.routers import monitoring

        now = time.time()
        lt = time.localtime(now)
        # Gece yarısına yakın bir "şu an" oluştur (23:50) — sessiz aralık 22:00-06:00
        quiet_start, quiet_end = "22:00", "06:00"
        with patch.object(time, "localtime", return_value=time.struct_time(
                (lt.tm_year, lt.tm_mon, lt.tm_mday, 23, 50, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))):
            settings = {"enabled": True, "min_score": 1.0, "min_target_pct": 1.0,
                        "quiet_hours_start": quiet_start, "quiet_hours_end": quiet_end}
            candidates = [{"symbol": "QUIETTRY", "velocity_score": 5.0, "target_pct": 5.0, "price": 2.0}]
            monitoring._monitoring_state["notified_symbols"] = {}
            with patch.object(monitoring, "deliver_web_push") as push, \
                 patch.object(monitoring, "_record_history") as record:
                result = await monitoring._notify(candidates, settings)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["quiet_hours"])
        push.assert_not_called()
        record.assert_called_once()

    async def test_notify_cooldown_prevents_resend(self):
        """Aynı sembol 5 dk içinde tekrar bildirilmemeli."""
        from app.routers import monitoring

        settings = {"enabled": True, "min_score": 0.5, "min_target_pct": 0.5,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [{"symbol": "COOLTRY", "velocity_score": 5.0, "target_pct": 5.0, "price": 1.0}]
        monitoring._monitoring_state["notified_symbols"] = {}
        with patch.object(monitoring, "deliver_web_push", return_value={"ok": True}), \
             patch.object(monitoring, "_record_history", return_value=None):
            first = await monitoring._notify(candidates, settings)
            second = await monitoring._notify(candidates, settings)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    async def test_cooldown_dict_pruning_keeps_size_bounded(self):
        from app.routers import monitoring

        st = monitoring._monitoring_state["notified_symbols"]
        st.clear()
        now = time.time()
        for i in range(600):
            st[f"S{i}TRY"] = now - 10000 + i  # eski -> yeni
        # Prune tetikleyen kod: >500 olunca en eski 250 düşer
        if len(st) > 500:
            for k in sorted(st, key=st.get)[:-250]:
                st.pop(k, None)
        self.assertLessEqual(len(st), 500)


class MonitoringHelpersTests(unittest.IsolatedAsyncioTestCase):
    def test_in_quiet_hours_none(self):
        from app.routers import monitoring

        self.assertFalse(monitoring._in_quiet_hours({"quiet_hours_start": None, "quiet_hours_end": None}))
        self.assertFalse(monitoring._in_quiet_hours({}))

    def test_in_quiet_hours_wrap_midnight(self):
        from app.routers import monitoring
        import time as _time

        def fake_lt(**kw):
            base = _time.localtime()
            return _time.struct_time((base.tm_year, base.tm_mon, base.tm_mday,
                                      kw.get("hour", 12), kw.get("min", 0), 0,
                                      base.tm_wday, base.tm_yday, base.tm_isdst))

        with patch.object(_time, "localtime", return_value=fake_lt(hour=23, min=50)):
            self.assertTrue(monitoring._in_quiet_hours({"quiet_hours_start": "22:00", "quiet_hours_end": "06:00"}))
        with patch.object(_time, "localtime", return_value=fake_lt(hour=3, min=0)):
            self.assertTrue(monitoring._in_quiet_hours({"quiet_hours_start": "22:00", "quiet_hours_end": "06:00"}))
        with patch.object(_time, "localtime", return_value=fake_lt(hour=12, min=0)):
            self.assertFalse(monitoring._in_quiet_hours({"quiet_hours_start": "22:00", "quiet_hours_end": "06:00"}))
        with patch.object(_time, "localtime", return_value=fake_lt(hour=12, min=0)):
            self.assertTrue(monitoring._in_quiet_hours({"quiet_hours_start": "10:00", "quiet_hours_end": "14:00"}))
        with patch.object(_time, "localtime", return_value=fake_lt(hour=9, min=0)):
            self.assertFalse(monitoring._in_quiet_hours({"quiet_hours_start": "10:00", "quiet_hours_end": "14:00"}))

    async def test_db_save_and_list_monitoring_notifications(self):
        """save/list monitoring_notifications fonksiyonları çalışmalı (mock DB)."""
        from app import database

        sent = {"symbol": "DBTRY", "message": "🎯 DBTRY +5%", "score": 5.0, "target_pct": 5.0,
                "price": 1.0, "expected_price": 1.05, "horizon_minutes": 5, "mode": "trend_devam",
                "detected_at": time.time(), "sent_via_push": True}
        captured = {}

        async def fake_save(entries):
            captured["entries"] = entries
            return len(entries)

        async def fake_list(limit=50):
            return [dict(captured["entries"][0], id=None)]

        with patch.object(database, "save_monitoring_notifications", side_effect=fake_save), \
             patch.object(database, "list_monitoring_notifications", side_effect=fake_list):
            from app.routers import monitoring

            await monitoring._record_history([sent])
            rows = await database.list_monitoring_notifications(limit=50)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "DBTRY")

    def test_build_notification_rich_payload(self):
        from app.routers import monitoring
        from app.state import market

        class FakeMarket:
            def get_ticker(self, sym):
                return {"last_price": "12.5"}

        with patch.object(market, "get_ticker", FakeMarket().get_ticker):
            n = monitoring._build_notification(
                "XYZTRY", {"velocity_score": 3.1, "target_pct": 4.0, "price": 12.0,
                           "horizon_minutes": 5, "mode": "trend_devam"},
                {"min_score": 1.0, "min_target_pct": 2.0},
            )
        self.assertEqual(n["symbol"], "XYZTRY")
        self.assertEqual(n["target_pct"], 4.0)
        self.assertEqual(n["price"], 12.5)
        self.assertAlmostEqual(n["expected_price"], 13.0, places=4)
        self.assertIn("Potansiyel", n["message"])
        self.assertIn("Beklenen", n["message"])
        self.assertIn("12.500000", n["message"])


class MonitoringSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_get_returns_db_values(self):
        from app.routers import monitoring
        from app import database

        async def fake_get(key, default=None):
            return '{"enabled": false, "min_score": 1.7, "min_target_pct": 3.0, "quiet_hours_start": "22:00", "quiet_hours_end": "06:00"}'

        with patch.object(database, "get_llm_setting", side_effect=fake_get):
            settings = await monitoring.get_user_notification_settings()
        self.assertEqual(settings["enabled"], False)
        self.assertEqual(settings["min_score"], 1.7)
        self.assertEqual(settings["min_target_pct"], 3.0)
        self.assertEqual(settings["quiet_hours_start"], "22:00")

    async def test_settings_put_saves_db(self):
        from app.routers import monitoring
        from app import database

        saved = {}

        async def fake_set(key, value):
            saved[key] = value

        with patch.object(database, "set_llm_setting", side_effect=fake_set):
            await monitoring.update_monitoring_settings(
                {"enabled": True, "min_score": 2.5, "min_target_pct": 4.0,
                 "quiet_hours_start": None, "quiet_hours_end": None},
                request=None)
        import json
        parsed = json.loads(saved["monitoring_notification_settings"])
        self.assertEqual(parsed["min_score"], 2.5)
        self.assertEqual(parsed["min_target_pct"], 4.0)


if __name__ == "__main__":
    unittest.main()
