"""Monitoring page tests: notification thresholds, quiet hours, cooldown,
cooldown pruning, rich push payload and DB history helpers."""
import pathlib
import os
import sys
import time
import asyncio
import time
import unittest
from unittest.mock import patch, AsyncMock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MonitoringNotifyTests(unittest.IsolatedAsyncioTestCase):
    def _reset_state(self):
        from app.routers import monitoring
        monitoring._monitoring_state["notified_symbols"] = {}
        monitoring._monitoring_state["candidate_streak"] = {}
        monitoring._monitoring_state["pending_targets"] = {}
        # D-07: yeniden tetikleme kapısı da testler arasında sıfırlanır
        # (aksi halde bir testin fiyatı diğerinin kapısını kapatır).
        monitoring._monitoring_state["notified_prices"] = {}
        monitoring._monitoring_state["refire_blocked"] = 0
        # A5 (2026-09-14): skor hafızası da sıfırlanır. Histerezis kapısı varsayılan
        # AÇIK olduğu için bu olmadan testler BİRBİRİNİN kapısını kapatıyor
        # (sınıf tanım sırasına bağlı, kırılgan test sırası).
        monitoring._monitoring_state["notified_scores"] = {}
        monitoring._monitoring_state["rr_blocked"] = 0
        monitoring._monitoring_state["risk_off"] = False

    async def test_notify_respects_min_score_and_min_target(self):
        """Eşik altı adaylar bildirilmemeli; eşiği geçenler bildirilmeli.

        A3 (2026-09-14): `min_score` PANEL ölçeğindedir ve ham kapıya aktif
        haritanın tersiyle çevrilir. panel 20 → ham 6.58; bu yüzden ham 2.0 olan
        aday elenir, ham 50 olanlar geçer (eski lineer ölçekte panel 20 = ham 400
        idi — ankraj ham çalışma noktalarını korur, ham GİRDİ değerleri değişir).
        LOWTARGETTRY'nin HAM skoru yüksek tutulur ki tek elenme sebebi hedef olsun.
        """
        from app.routers import monitoring

        self._reset_state()
        settings = {"enabled": True, "min_score": 20.0, "min_target_pct": 2.0,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [
            {"symbol": "LOWTRY", "velocity_score": 2.0, "target_pct": 5.0, "price": 1.0},
            {"symbol": "LOWTARGETTRY", "velocity_score": 50.0, "target_pct": 0.5, "price": 1.0},
            {"symbol": "GOODTRY", "velocity_score": 50.0, "target_pct": 3.0, "price": 10.0},
        ]
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "test-key"}), \
             patch.object(monitoring.database, "save_monitoring_notifications", new_callable=AsyncMock, return_value=0), \
             patch.object(monitoring.database, "get_pending_monitoring_notifications", new_callable=AsyncMock, return_value={}), \
             patch.object(monitoring, "deliver_web_push", return_value={"ok": True}) as push, \
             patch.object(monitoring, "_record_history", return_value=None), \
             patch.object(monitoring.config, "MONITORING_RR_ENABLED", False), \
             patch.object(monitoring.config, "MONITORING_DEBOUNCE_SCANS", 0):
            result = await monitoring._notify(candidates, settings)
            # B5 refactoru: push gönderimi artık _deliver_scan_notifications'ta
            # (state kilidi dışı); _notify yalnızca bildirimleri üretir.
            await monitoring._deliver_scan_notifications(result)
        # LOWTRY: ham 2.0 < ham kapı 6.58 → elenir.
        # LOWTARGETTRY: ham 50 ≥ kapı ama target 0.5 < min_target 2.0 → elenir.
        # GOODTRY: ikisini de geçer.
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

        self._reset_state()
        settings = {"enabled": False, "min_score": 0.5, "min_target_pct": 0.5,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [{"symbol": "XTRY", "velocity_score": 9.0, "target_pct": 9.0, "price": 1.0}]
        with patch.object(monitoring, "deliver_web_push") as push:
            result = await monitoring._notify(candidates, settings)
        self.assertEqual(result, [])
        push.assert_not_called()

    async def test_notify_quiet_hours_defers_push_but_records(self):
        """Sessiz saatlerde push gönderilmez; aday DB'ye kaydedilir (kalıcılık)."""
        from app.routers import monitoring

        self._reset_state()
        now = time.time()
        lt = time.localtime(now)
        # Gece yarısına yakın bir "şu an" oluştur (23:50) — sessiz aralık 22:00-06:00
        quiet_start, quiet_end = "22:00", "06:00"
        with patch.object(time, "localtime", return_value=time.struct_time(
                (lt.tm_year, lt.tm_mon, lt.tm_mday, 23, 50, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))):
            settings = {"enabled": True, "min_score": 1.0, "min_target_pct": 1.0,
                        "quiet_hours_start": quiet_start, "quiet_hours_end": quiet_end}
            candidates = [{"symbol": "QUIETTRY", "velocity_score": 30.0, "target_pct": 5.0, "price": 2.0}]
            with patch.object(monitoring.database, "save_monitoring_notifications", new_callable=AsyncMock, return_value=0) as save_mock, \
                 patch.object(monitoring.database, "get_pending_monitoring_notification", new_callable=AsyncMock, return_value=None), \
                 patch.object(monitoring, "deliver_web_push") as push, \
                 patch.object(monitoring.config, "MONITORING_RR_ENABLED", False), \
                 patch.object(monitoring.config, "MONITORING_DEBOUNCE_SCANS", 0):
                monitoring._deferred_push.clear()
                result = await monitoring._notify(candidates, settings)
                # B5: erteleme artık teslim adımında (_deliver_scan_notifications)
                await monitoring._deliver_scan_notifications(result)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].get("quiet_hours"))
        push.assert_not_called()
        save_mock.assert_called_once()  # sessiz saatte DB kaydı (push değil) yapılır
        self.assertEqual(len(monitoring._deferred_push), 1,
                         "sessiz saatte push ertelenen kuyruğa düşmeli (B5)")

    async def test_notify_cooldown_prevents_resend(self):
        """Aynı sembol 5 dk içinde tekrar bildirilmemeli."""
        from app.routers import monitoring

        self._reset_state()
        settings = {"enabled": True, "min_score": 0.5, "min_target_pct": 0.5,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [{"symbol": "COOLTRY", "velocity_score": 15.0, "target_pct": 5.0, "price": 1.0}]
        with patch.object(monitoring.database, "save_monitoring_notifications", new_callable=AsyncMock, return_value=0), \
             patch.object(monitoring.database, "get_pending_monitoring_notification", new_callable=AsyncMock, return_value=None), \
             patch.object(monitoring, "deliver_web_push", return_value={"ok": True}), \
             patch.object(monitoring, "_record_history", return_value=None), \
             patch.object(monitoring.config, "MONITORING_RR_ENABLED", False), \
             patch.object(monitoring.config, "MONITORING_DEBOUNCE_SCANS", 0):
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

    async def test_normalize_score_maps_velocity_to_panel(self):
        """normalize_score ham velocity_score'u panel (0-100) ölçeğine haritalar.

        A3 (2026-09-14): harita log (`100×log1p(raw)/log1p(REF)`) — kırpma yok.
        Beklenen değerler kanonik haritadan türetilir (sabit gömülmez).
        """
        from app.routers import monitoring
        self.assertAlmostEqual(monitoring.normalize_score(0), 0.0)
        self.assertAlmostEqual(monitoring.normalize_score(-5), 0.0)  # clipped
        # monotonluk + kanonik harita tutarlılığı
        vals = [monitoring.normalize_score(r) for r in (10, 40, 150, 1400, 2000, 21388.94)]
        self.assertEqual(vals, sorted(vals))
        for raw in (10, 40, 150, 1400, 2000, 21388.94):
            self.assertAlmostEqual(monitoring._panel_from_raw(raw),
                                   monitoring.normalize_score(raw), places=9)
        # kırpma YOK: gözlenen max 100.00'a yığılmamalı
        self.assertLess(monitoring.normalize_score(21388.94), 100.0)
        # ve eski lineer değerle AYNI OLMAMALI (düzeltmenin özü: 150 → 7.5 idi)
        self.assertNotAlmostEqual(7.5, monitoring.normalize_score(150), places=1)

    async def test_min_target_filter_blocks_low_target(self):
        """min_target_pct不足の候補は通知されない"""
        from app.routers import monitoring

        self._reset_state()
        settings = {"enabled": True, "min_score": 0.0, "min_target_pct": 3.0,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [
            {"symbol": "LOWTRY", "velocity_score": 10.0, "target_pct": 1.5, "price": 1.0},
            {"symbol": "GOODTRY", "velocity_score": 10.0, "target_pct": 4.0, "price": 1.0},
        ]
        with patch.object(monitoring.database, "save_monitoring_notifications", new_callable=AsyncMock, return_value=0), \
             patch.object(monitoring.database, "get_pending_monitoring_notification", new_callable=AsyncMock, return_value=None), \
             patch.object(monitoring, "deliver_web_push", return_value={"ok": True}), \
             patch.object(monitoring, "_record_history", return_value=None), \
             patch.object(monitoring.config, "MONITORING_RR_ENABLED", False), \
             patch.object(monitoring.config, "MONITORING_DEBOUNCE_SCANS", 0):
            result = await monitoring._notify(candidates, settings)
        self.assertEqual([n["symbol"] for n in result], ["GOODTRY"])


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

            # D-05: tazelik dogrulamasi eklendigi icin fake market
            # `ticker_freshness` de saglamak zorunda.
            def ticker_freshness(self, sym, max_age_sec=None):
                return {"fresh": True, "age_sec": 0.0, "max_age_sec": max_age_sec}

        _fake_market = FakeMarket()
        with patch.object(market, "get_ticker", _fake_market.get_ticker), \
             patch.object(market, "ticker_freshness", _fake_market.ticker_freshness):
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

    def test_build_notification_uses_normalized_score(self):
        """_build_notification normalize_score ile panel skoru üretmeli."""
        from app.routers import monitoring
        from app.state import market

        class FakeMarket:
            def get_ticker(self, sym):
                return {"last_price": "1.0"}

        with patch.object(market, "get_ticker", FakeMarket().get_ticker):
            n = monitoring._build_notification(
                "TESTTRY", {"velocity_score": 20.0, "target_pct": 3.0, "price": 1.0,
                           "horizon_minutes": 5, "mode": "trend_devam"},
                {"min_score": 1.0, "min_target_pct": 0.5},
            )
        # A3: skor kanonik haritadan gelir (ham 20 → panel 30.1; eski lineer 1.0'dı).
        self.assertAlmostEqual(n["score"], monitoring._panel_from_raw(20.0), places=1)


class MonitoringSettingsTests(unittest.IsolatedAsyncioTestCase):
    def _reset_state(self):
        from app.routers import monitoring
        monitoring._monitoring_state["notified_symbols"] = {}
        monitoring._monitoring_state["candidate_streak"] = {}
        monitoring._monitoring_state["pending_targets"] = {}
        # D-07: yeniden tetikleme kapısı da testler arasında sıfırlanır
        # (aksi halde bir testin fiyatı diğerinin kapısını kapatır).
        monitoring._monitoring_state["notified_prices"] = {}
        monitoring._monitoring_state["refire_blocked"] = 0
        monitoring._monitoring_state["risk_off"] = False
        monitoring._deferred_push.clear()

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
        from app import security

        saved = {}

        async def fake_set(key, value):
            saved[key] = value

        # Mock _require_admin'ı pasif hale getir
        with patch.object(database, "set_llm_setting", side_effect=fake_set), \
             patch("app.main._require_admin", return_value=None):
            await monitoring.update_monitoring_settings(
                {"enabled": True, "min_score": 2.5, "min_target_pct": 4.0,
                 "quiet_hours_start": None, "quiet_hours_end": None},
                request=None)
        import json
        parsed = json.loads(saved["monitoring_notification_settings"])
        self.assertEqual(parsed["min_score"], 2.5)
        self.assertEqual(parsed["min_target_pct"], 4.0)

    async def test_settings_put_merges_partial_payload(self):
        """Sadece min_score gönderildiğinde diğer ayarlar korunmalı (merge).

        Önceki tam-değiştir davranışında eşiği kaydeden her istek
        min_target_pct/quiet_hours/enabled'ı varsayılana sıfırlıyordu
        (2026-09-04 teşhis).
        """
        from app.routers import monitoring
        from app import database

        saved = {}

        async def fake_get(key, default=None):
            return '{"enabled": false, "min_score": 60, "min_target_pct": 3.5, "quiet_hours_start": "23:00", "quiet_hours_end": "07:00"}'

        async def fake_set(key, value):
            saved[key] = value

        with patch.object(database, "get_llm_setting", side_effect=fake_get), \
             patch.object(database, "set_llm_setting", side_effect=fake_set), \
             patch("app.main._require_admin", return_value=None):
            result = await monitoring.update_monitoring_settings({"min_score": 80}, request=None)
        import json
        parsed = json.loads(saved["monitoring_notification_settings"])
        self.assertEqual(parsed["min_score"], 80)
        self.assertEqual(parsed["min_target_pct"], 3.5)
        self.assertEqual(parsed["enabled"], False)
        self.assertEqual(parsed["quiet_hours_start"], "23:00")
        self.assertEqual(result["min_score"], 80)

    async def test_stored_panel_score_scale_aware(self):
        """Eski ham kayıtlar tek kez normalize edilir; yeni panel kayıtları aynen kalır."""
        from app.routers import monitoring

        # Eski kayıt (cutoff öncesi): ham 20 -> normalize(20)=50
        old_row = {"score": 20, "detected_at": 1788534693 - 1}
        self.assertAlmostEqual(monitoring._stored_panel_score(old_row), 1.0, places=1)
        # Yeni kayıt (cutoff sonrası): panel skoru dokunulmaz — çift normalize edilmez
        new_row = {"score": 55, "detected_at": 1788534693 + 1}
        self.assertAlmostEqual(monitoring._stored_panel_score(new_row), 55.0, places=1)

    async def test_reset_notifications_requires_admin(self):
        """reset-notifications admin olmadan çalışmaz."""
        from app.routers import monitoring

        monitoring._monitoring_state["notified_symbols"] = {"TEST": time.time()}
        with patch("app.main._require_admin", side_effect=Exception("403")):
            try:
                await monitoring.reset_monitoring_notifications(request=None)
                self.fail("Should have raised")
            except Exception as e:
                self.assertIn("403", str(e))

    async def test_active_notification_returns_pending(self):
        """Ufku dolmamış bildirim: panel alanları + geri sayım pozitif."""
        from app.routers import monitoring
        from app import database

        row = {"id": 1, "symbol": "BTCTRY", "score": 62.5, "target_pct": 2.0,
               "price": 100.0, "expected_price": 102.0, "horizon_minutes": 5,
               "detected_at": time.time() - 60, "mode": "trend_devam"}

        async def fake_pending(sym):
            return dict(row)

        with patch.object(database, "get_pending_monitoring_notification", side_effect=fake_pending),              patch.object(monitoring.market, "get_ticker", return_value={"last_price": 102.5}),              patch.object(monitoring.market, "ticker_freshness",                           return_value={"fresh": True, "age_sec": 0.0}):
            result = await monitoring.monitoring_active_notification("BTCTRY")
        self.assertTrue(result["active"])
        self.assertEqual(result["score"], 62.5)
        self.assertAlmostEqual(result["target_gain_pct"], 2.0, places=2)
        self.assertGreater(result["remaining_sec"], 0)
        self.assertLessEqual(result["remaining_sec"], (5 + 2) * 60)
        self.assertEqual(result["current_price"], 102.5)
        self.assertTrue(result["target_hit"])

    async def test_active_notification_expired_returns_inactive(self):
        """Ufuk + tolerans dolmuş bildirim: active=False (grafik paneli söner)."""
        from app.routers import monitoring
        from app import database

        row = {"id": 1, "symbol": "ETHTRY", "score": 70.0, "target_pct": 2.0,
               "price": 50.0, "expected_price": 51.0, "horizon_minutes": 5,
               "detected_at": time.time() - (5 + 3) * 60, "mode": None}

        async def fake_pending(sym):
            return dict(row)

        with patch.object(database, "get_pending_monitoring_notification", side_effect=fake_pending):
            result = await monitoring.monitoring_active_notification("ETHTRY")
        self.assertFalse(result["active"])

    async def test_active_notification_no_row_returns_inactive(self):
        """Bildirim hiç yokken active=False döner (hata fırlatmaz)."""
        from app.routers import monitoring
        from app import database

        async def fake_pending(sym):
            return None

        with patch.object(database, "get_pending_monitoring_notification", side_effect=fake_pending):
            result = await monitoring.monitoring_active_notification("XYZTRY")
        self.assertFalse(result["active"])

    async def test_notify_update_keeps_first_price_reanchors_target(self):
        """Aktif bildirim güncellenirken giriş fiyatı İLK bildirimdekiler sabit kalır;
        hedef fiyat son taramanın hedef yüzdesiyle İLK girişten yeniden hesaplanır
        (2026-09-04 kullanıcı kararı: grafik giriş çizgisi sabit, hedef çizgisi güncel)."""
        from app.routers import monitoring

        settings = {"enabled": True, "min_score": 2.0, "min_target_pct": 0,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        existing = {"id": 42, "symbol": "GOODTRY", "score": 6.0, "target_pct": 2.0,
                    "price": 10.0, "expected_price": 10.2, "horizon_minutes": 5,
                    "detected_at": time.time() - 30}
        captured = {}

        async def fake_update(notif_id, **kwargs):
            captured["id"] = notif_id
            captured.update(kwargs)
            return True

        with patch.object(monitoring.database, "save_monitoring_notifications", new_callable=AsyncMock, return_value=0),              patch.object(monitoring.database, "get_pending_monitoring_notifications", new_callable=AsyncMock, return_value={"GOODTRY": existing}),              patch.object(monitoring.database, "update_monitoring_notification", side_effect=fake_update),              patch.object(monitoring, "deliver_web_push", return_value={"ok": True}),              patch.object(monitoring, "_record_history", return_value=None):
            candidates = [{"symbol": "GOODTRY", "velocity_score": 50.0, "target_pct": 5.0, "price": 12.0,
                           "horizon_minutes": 15}]
            result = await monitoring._notify(candidates, settings)
        self.assertTrue(result and result[0].get("updated"))
        self.assertEqual(captured["id"], 42)
        # Giriş fiyatı ilk bildirimdeki 10.0 olarak sabit; yeni hedef %5 ile
        # İLK girişten hesaplanır: 10.0 * 1.05 = 10.5 (yeni anlık 12.0 ile DEĞİL).
        self.assertEqual(captured["price"], 10.0)
        self.assertAlmostEqual(captured["expected_price"], 10.5, places=6)
        self.assertAlmostEqual(captured["target_pct"], 5.0, places=6)
        # Ufuk daralmasin: yeni tarama 15dk getirdiyse kayit 15dk olur (5 kalmaz)
        self.assertEqual(captured["horizon_minutes"], 15)

    async def test_notify_update_never_shrinks_horizon(self):
        """Kisa ufuklu yeni tarama (5dk), uzun ufuklu bildirimi (15dk) KISALTAMAZ:
        panel SON ufuk suresi dolana kadar takipte kalir (2026-09-04)."""
        from app.routers import monitoring

        settings = {"enabled": True, "min_score": 2.0, "min_target_pct": 0,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        existing = {"id": 7, "symbol": "LONGTRY", "score": 6.0, "target_pct": 2.0,
                    "price": 20.0, "expected_price": 20.4, "horizon_minutes": 15,
                    "detected_at": time.time() - 60}
        captured = {}

        async def fake_update(notif_id, **kwargs):
            captured.update(kwargs)
            return True

        with patch.object(monitoring.database, "save_monitoring_notifications", new_callable=AsyncMock, return_value=0),              patch.object(monitoring.database, "get_pending_monitoring_notifications", new_callable=AsyncMock, return_value={"LONGTRY": existing}),              patch.object(monitoring.database, "update_monitoring_notification", side_effect=fake_update),              patch.object(monitoring, "deliver_web_push", return_value={"ok": True}),              patch.object(monitoring, "_record_history", return_value=None):
            candidates = [{"symbol": "LONGTRY", "velocity_score": 50.0, "target_pct": 3.0,
                           "price": 21.0, "horizon_minutes": 5}]
            await monitoring._notify(candidates, settings)
        self.assertEqual(captured["horizon_minutes"], 15)



    async def test_locked_state_concurrent_access(self):
        """_locked_state context manager concurrent erisimde state tutarli kalmali."""
        from app.routers import monitoring
        self._reset_state()
        import asyncio
        async def writer(key, value):
            async with monitoring._locked_state():
                monitoring._monitoring_state[key] = value
                await asyncio.sleep(0.01)
                self.assertEqual(monitoring._monitoring_state[key], value)
        tasks = [writer(f"k{i}", f"v{i}") for i in range(10)]
        await asyncio.gather(*tasks)
        async with monitoring._locked_state():
            self.assertEqual(monitoring._monitoring_state.get("k3"), "v3")
            self.assertEqual(monitoring._monitoring_state.get("k7"), "v7")

    async def test_deferred_push_queue(self):
        """Ertelenen push kuyrugu _locked_state altinda guvenli sekilde yonetilmeli."""
        from app.routers import monitoring
        self._reset_state()
        import asyncio
        monitoring._deferred_push.clear()
        monitoring._deferred_push.append({"symbol": "TESTTRY", "message": "test"})
        async with monitoring._locked_state():
            self.assertEqual(len(monitoring._deferred_push), 1)
            item = monitoring._deferred_push.popleft()
            self.assertEqual(item["symbol"], "TESTTRY")
        self.assertEqual(len(monitoring._deferred_push), 0)

    async def test_diagnostics_includes_ws_metrics(self):
        """monitoring_diagnostics endpointi ws_health ve rate_limiter alanlarini icermeli.

        B7: uç artık admin kısıtlı — test admin kapısını pasifleştirir.
        """
        from app.routers import monitoring
        self._reset_state()
        settings = {"enabled": True, "min_score": 2.0, "min_target_pct": 2.0,
                    "quiet_hours_start": None, "quiet_hours_end": None}

        monitoring._monitoring_state["last_candidates"] = [
            {"symbol": "TESTTRY", "velocity_score": 5.0}
        ]
        with patch.object(monitoring.database, "get_monitoring_velocity_matches",
                          new_callable=AsyncMock, return_value=[]), \
             patch("app.main._require_admin", return_value=None):
            result = await monitoring.monitoring_diagnostics(request=None)

        self.assertIn("ws_health", result)
        self.assertIn("rate_limiter", result)
        self.assertIn("freshness_sample", result)
        self.assertEqual(result["paper_only"], True)

    async def test_diagnostics_requires_admin(self):
        """B7: diagnostics admin olmadan çalışmaz (altyapı iç metrikleri)."""
        from app.routers import monitoring
        self._reset_state()
        with patch("app.main._require_admin",
                   side_effect=Exception("403")):
            with self.assertRaises(Exception):
                await monitoring.monitoring_diagnostics(request=None)

    async def test_rate_limiter_acquire(self):
        """_velocity_rate_acquire token azalinca beklemeli."""
        with patch.object(asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:
            from app.routers import monitoring
            # Import the velocity rate functions
            import app.routers.velocity as velmod
            # Reset token count
            velmod._velocity_rate_tokens = 12
            velmod._velocity_rate_last_refill = 0
            await velmod._velocity_rate_acquire()
            self.assertLess(velmod._velocity_rate_tokens, 12)
            stats = velmod._rate_limit_stats()
            self.assertIn("tokens_remaining", stats)
            self.assertIn("burst", stats)

    async def test_notify_auto_paper_skips_updates(self):
        """Guncelleme bildirimlerinde auto_paper tetiklenmemeli (N+1 onlemi)."""
        from app.routers import monitoring
        self._reset_state()
        settings = {"enabled": True, "min_score": 1.0, "min_target_pct": 1.0,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [
            {"symbol": "UPDTRY", "velocity_score": 30.0, "target_pct": 3.0, "price": 10.0,
             "horizon_minutes": 5, "mode": "trend_devam"}
        ]
        # Simulate existing pending notification 
        existing = {"id": 123, "symbol": "UPDTRY", "price": 10.0, "detected_at": time.time() - 30,
                    "horizon_minutes": 5, "score": 12.5}
        # A4 R/R kapısı varsayılan AÇIK; bu test güncelleme yolunu ölçtüğü için
        # kapı ayrı bir context-manager girdisi olarak kapatılır. (Bu satır eskiden
        # `update_monitoring_notification` çağrısının argüman listesinin ORTASINA
        # girmişti → `new` konumsal + `new_callable` birlikte verilip mock
        # "Cannot use 'new' and 'new_callable' together" fırlatıyordu.)
        with patch.object(monitoring.database, "save_monitoring_notifications",
                          new_callable=AsyncMock, return_value=0), \
             patch.object(monitoring.database, "get_pending_monitoring_notifications",
                          new_callable=AsyncMock, return_value={"UPDTRY": existing}), \
             patch.object(monitoring.database, "update_monitoring_notification",
                          new_callable=AsyncMock, return_value=None), \
             patch.object(monitoring.config, "MONITORING_RR_ENABLED", False), \
             patch.object(monitoring, "deliver_web_push", return_value={"ok": True}), \
             patch.object(monitoring.config, "MONITORING_DEBOUNCE_SCANS", 0):
            result = await monitoring._notify(candidates, settings)
       
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].get("updated"))


class MonitoringTickerFreshnessTests(unittest.TestCase):
    """D-05 (2026-09-14): bildirim fiyatı BAYAT ticker'dan gelmemeli.

    Kök neden: `_build_notification`, `market.get_ticker()["last_price"]`'ı tazelik
    doğrulaması OLMADAN kullanıyordu → bayat fiyat + taze zaman damgası yazılıyordu
    (ölçüm: 13.09 ARKTRY tabloda 10,26, aynı anda gerçek mum ~7,0). Ayrıca
    MFE/touched adayın kendi fiyatıyla hesaplandığı için ekrandaki fiyat ile ölçüm
    tabanı ayrışıyordu. Düzeltme: tazeligi doğrulanmış ticker yoksa aday fiyatı.
    """

    @staticmethod
    def _fake_market(last_price, fresh):
        class _M:
            def get_ticker(self, symbol):
                return {"last_price": last_price}

            def ticker_freshness(self, symbol, max_age_sec=None):
                return {"fresh": fresh, "age_sec": 0.0 if fresh else 99_999.0,
                        "max_age_sec": max_age_sec}
        return _M()

    CANDIDATE = {"symbol": "ARKTRY", "velocity_score": 2500.0, "target_pct": 4.0,
                 "price": 7.0, "horizon_minutes": 5}

    def test_stale_ticker_is_not_used(self):
        from app.routers import monitoring
        with patch.object(monitoring, "market", self._fake_market(10.26, fresh=False)):
            notif = monitoring._build_notification("ARKTRY", dict(self.CANDIDATE), {})
        # Bayat ticker (10,26) DEĞİL adayın kendi fiyatı (7,0) yazılmalı.
        self.assertEqual(notif["price"], 7.0)
        self.assertAlmostEqual(notif["expected_price"], 7.0 * 1.04, places=6)

    def test_fresh_ticker_is_used(self):
        from app.routers import monitoring
        with patch.object(monitoring, "market", self._fake_market(7.05, fresh=True)):
            notif = monitoring._build_notification("ARKTRY", dict(self.CANDIDATE), {})
        self.assertEqual(notif["price"], 7.05)
        self.assertAlmostEqual(notif["expected_price"], 7.05 * 1.04, places=6)

    def test_missing_ticker_falls_back_to_candidate(self):
        from app.routers import monitoring
        with patch.object(monitoring, "market", None):
            notif = monitoring._build_notification("ARKTRY", dict(self.CANDIDATE), {})
        self.assertEqual(notif["price"], 7.0)

    def test_ticker_price_helper_gates_on_freshness(self):
        from app.routers import monitoring
        with patch.object(monitoring, "market", self._fake_market(10.26, fresh=False)):
            self.assertIsNone(monitoring._ticker_price("ARKTRY"))
        with patch.object(monitoring, "market", self._fake_market(7.05, fresh=True)):
            self.assertEqual(monitoring._ticker_price("ARKTRY"), 7.05)
        with patch.object(monitoring, "market", None):
            self.assertIsNone(monitoring._ticker_price("ARKTRY"))

    def test_first_price_still_wins_on_update_path(self):
        """Güncelleme yolunda ilk tespit fiyatı korunur (2026-09-06 davranışı)."""
        from app.routers import monitoring
        with patch.object(monitoring, "market", self._fake_market(9.99, fresh=True)):
            notif = monitoring._build_notification("ARKTRY", dict(self.CANDIDATE), {},
                                                   first_price=7.0)
        self.assertEqual(notif["price"], 7.0)


# ---------------------------------------------------------------------------
# A4 (2026-09-14) — R/R kapısı: kalibrasyon + gerçek SL dayanağı + sayaç
#
# Kanıt (gerçek DB): hedef bandı → dokunma oranı
#   %2.00 → %8.8 (n=13137), %3.00 → %11.5 (n=15889), %4.00 → %1.3 (n=204)
# Yani yüksek hedef daha kötü vuruyor → kapı "RR'yi yükselt" yönlü olamaz.
# ---------------------------------------------------------------------------
class RrGateTests(unittest.TestCase):
    def setUp(self):
        from app.routers import monitoring
        self.m = monitoring

    def test_sl_basis_matches_real_exit_stop(self):
        """R/R'nin SL dayanağı pozisyonun GERÇEK stop'uyla aynı olmalı.

        Pozisyonlar `stop_loss = fill_entry*(1-sl_pct)`, `sl_pct` =
        `AUTO_PAPER_SL_PCT_DEFAULT` ile açılır. İki sabit ayrışırsa RR ölçümü
        yanlış olur (gateletilen aday ile açılan pozisyon farklı risk taşır).
        """
        from app.config import config
        self.assertAlmostEqual(float(config.AUTO_PAPER_SL_PCT_DEFAULT),
                               float(config.MONITORING_RR_SL_PCT), places=9)

    def test_ratio_is_target_over_stop(self):
        from app.config import config
        self.assertAlmostEqual(2.0 / 3.0, self.m._rr_ratio(2.0), places=6)
        self.assertAlmostEqual(1.0, self.m._rr_ratio(float(config.MONITORING_RR_SL_PCT)), places=6)

    def test_ratio_none_when_unmeasurable(self):
        self.assertIsNone(self.m._rr_ratio(0))
        self.assertIsNone(self.m._rr_ratio(None))
        with patch.object(self.m.config, "MONITORING_RR_SL_PCT", 0.0):
            self.assertIsNone(self.m._rr_ratio(2.0))

    def test_gate_admits_typical_targets(self):
        """Kritik kalibrasyon kilidi: %2.0 ve %3.0 hedefleri GEÇMELİ, kapı boğmamalı.

        Eski varsayılan (RR_MIN=1.2, SL=%3 → hedef ≥ %3.6) bu iki bandı da
        eliyordu; oysa isabetin taşındığı bantlar tam olarak bunlar.
        """
        self.assertFalse(self.m._rr_gate_blocks(10.0, 2.0),
                         "hedef %2.0 (isabet %8.8) elenmemeli")
        self.assertFalse(self.m._rr_gate_blocks(10.0, 3.0),
                         "hedef %3.0 (isabet %11.5) elenmemeli")

    def test_gate_blocks_reward_below_stop_floor(self):
        """Ödülü riskinin `RR_MIN` katından küçük aday elenir (hedef < %1.8)."""
        self.assertTrue(self.m._rr_gate_blocks(10.0, 1.5))

    def test_gate_disabled_never_blocks(self):
        with patch.object(self.m.config, "MONITORING_RR_ENABLED", False):
            self.assertFalse(self.m._rr_gate_blocks(10.0, 1.5))

    def test_gate_fails_open_without_price(self):
        """Fiyat yoksa bastırma YOK (veri eksikliği sinyal öldürmemeli)."""
        self.assertFalse(self.m._rr_gate_blocks(0.0, 2.0))
        self.assertFalse(self.m._rr_gate_blocks(None, 2.0))

    def test_notification_carries_rr_and_sl_basis(self):
        """Frontend kendi SL sabitini varsaymasın: rr/sl_pct payload'da olmalı."""
        with patch.object(self.m, "_ticker_price", return_value=None):
            notif = self.m._build_notification(
                "AAAATRY", {"target_pct": 3.0, "price": 10.0, "velocity_score": 100.0}, {})
        self.assertAlmostEqual(1.0, notif["rr"], places=6)
        self.assertAlmostEqual(float(self.m.config.MONITORING_RR_SL_PCT),
                               notif["sl_pct"], places=6)

    def test_notification_rr_none_when_target_missing(self):
        with patch.object(self.m, "_ticker_price", return_value=None):
            notif = self.m._build_notification(
                "AAAATRY", {"target_pct": 0, "price": 10.0, "velocity_score": 100.0}, {})
        self.assertIsNone(notif["rr"])


class RrGateCounterTests(unittest.IsolatedAsyncioTestCase):
    """`rr_blocked` sayacı: kalibrasyon sonrası "kaç aday bastırıldı" görünmeli."""

    async def _notify(self, candidates):
        from app.routers import monitoring
        monitoring._monitoring_state["notified_symbols"] = {}
        monitoring._monitoring_state["pending_targets"] = {}
        monitoring._monitoring_state["notified_prices"] = {}
        monitoring._monitoring_state["refire_blocked"] = 0
        monitoring._monitoring_state["rr_blocked"] = 0
        monitoring._monitoring_state["notified_scores"] = {}
        settings = {"enabled": True, "min_score": 0.5, "min_target_pct": 0.5,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        with patch.object(monitoring.database, "save_monitoring_notifications",
                          new_callable=AsyncMock, return_value=0), \
             patch.object(monitoring.database, "get_pending_monitoring_notifications",
                          new_callable=AsyncMock, return_value={}), \
             patch.object(monitoring, "deliver_web_push", return_value={"ok": True}), \
             patch.object(monitoring, "_record_history", return_value=None), \
             patch.object(monitoring, "_ticker_price", return_value=None), \
             patch.object(monitoring.config, "MONITORING_DEBOUNCE_SCANS", 0):
            return await monitoring._notify(candidates, settings)

    async def test_low_rr_candidate_counted_and_not_notified(self):
        from app.routers import monitoring
        cands = [{"symbol": "WEAKTRY", "velocity_score": 50.0, "target_pct": 1.5,
                  "price": 10.0, "horizon_minutes": 5}]
        result = await self._notify(cands)
        self.assertEqual([], result, "hedef < %1.8 bildirilmemeli")
        self.assertEqual(1, monitoring._monitoring_state["rr_blocked"])

    async def test_typical_target_is_notified_and_counter_untouched(self):
        from app.routers import monitoring
        cands = [{"symbol": "GOODTRY", "velocity_score": 50.0, "target_pct": 2.0,
                  "price": 10.0, "horizon_minutes": 5}]
        result = await self._notify(cands)
        self.assertEqual(["GOODTRY"], [n["symbol"] for n in result])
        self.assertEqual(0, monitoring._monitoring_state["rr_blocked"])


# ---------------------------------------------------------------------------
# A5 (2026-09-14) — MACD teyitli histerezis: aynı sinyalin tekrarını kes
#
# MACD MONITOR'ün isabet-histerezisi: skor yükselmediği VE MACD teyidi zayıf
# olduğunda aynı sembol yeniden bildirilmez. Ayarlardan kapatılabilir.
# ---------------------------------------------------------------------------
class MacdRefireGateTests(unittest.IsolatedAsyncioTestCase):
    SETTINGS = {"enabled": True, "min_score": 0.5, "min_target_pct": 0.5,
                "quiet_hours_start": None, "quiet_hours_end": None}

    def setUp(self):
        from app.routers import monitoring
        self.m = monitoring
        # Test başına TÜM hafıza sıfırlanır (testler birbirinin kapısını kapatmasın).
        for key in ("notified_symbols", "pending_targets", "notified_prices",
                    "candidate_streak", "notified_scores"):
            monitoring._monitoring_state[key] = {}
        monitoring._monitoring_state["refire_blocked"] = 0
        monitoring._monitoring_state["rr_blocked"] = 0

    async def _notify(self, candidates, extra_settings=None):
        """Yalnız ZAMAN kapıları temizlenir; FİYAT ve SKOR hafızası KORUNUR.

        Histerezis tam olarak o hafızaya bakar (`notified_scores`); onu her
        çağrıda silmek testi anlamsız kılardı.
        """
        m = self.m
        m._monitoring_state["notified_symbols"] = {}
        m._monitoring_state["pending_targets"] = {}
        settings = {**self.SETTINGS, **(extra_settings or {})}
        with patch.object(m.database, "save_monitoring_notifications",
                          new_callable=AsyncMock, return_value=0), \
             patch.object(m.database, "get_pending_monitoring_notifications",
                          new_callable=AsyncMock, return_value={}), \
             patch.object(m, "deliver_web_push", return_value={"ok": True}), \
             patch.object(m, "_record_history", return_value=None), \
             patch.object(m, "_ticker_price", return_value=None), \
             patch.object(m.config, "MONITORING_DEBOUNCE_SCANS", 0):
            return await m._notify(candidates, settings)

    def _cand(self, price, score, macd_strong=False):
        return {"symbol": "HISTTRY", "velocity_score": score, "target_pct": 2.0,
                "price": price, "horizon_minutes": 5, "mode": "trend_devam",
                "macd_bullish": macd_strong, "macd_rising": macd_strong}

    async def test_refire_blocked_when_score_not_rising_and_macd_weak(self):
        """Fiyat kımıldasa bile skor yükselmiyorsa + MACD zayıfsa tekrar bildirilmez."""
        first = await self._notify([self._cand(10.0, 50.0)])
        self.assertEqual(["HISTTRY"], [n["symbol"] for n in first])
        second = await self._notify([self._cand(10.1, 45.0)])
        self.assertEqual([], second, "aynı sinyal tekrar bildirildi (histerezis yok)")

    async def test_refire_allowed_when_score_rises(self):
        """Skor yükseliyorsa yeni bilgi var → bildirim geçer."""
        await self._notify([self._cand(10.0, 50.0)])
        second = await self._notify([self._cand(10.1, 60.0)])
        self.assertEqual(["HISTTRY"], [n["symbol"] for n in second])

    async def test_refire_allowed_when_macd_confirms(self):
        """MACD teyidi güçlüyse skor sabit olsa da bildirim geçer."""
        await self._notify([self._cand(10.0, 50.0)])
        second = await self._notify([self._cand(10.1, 45.0, macd_strong=True)])
        self.assertEqual(["HISTTRY"], [n["symbol"] for n in second])

    async def test_gate_off_from_settings_allows_refire(self):
        """Ayarlardan kapatılınca (macd_refire_gate=false) tekrar bildirim geçer."""
        await self._notify([self._cand(10.0, 50.0)], {"macd_refire_gate": True})
        second = await self._notify([self._cand(10.1, 45.0)], {"macd_refire_gate": False})
        self.assertEqual(["HISTTRY"], [n["symbol"] for n in second])


class MacdRefireGateSettingsTests(unittest.IsolatedAsyncioTestCase):
    """Anahtarın settings sözleşmesi: varsayılan AÇIK + PUT ile değiştirilebilir."""

    async def test_default_is_enabled_from_config(self):
        from app.routers import monitoring
        from app.config import config
        self.assertTrue(bool(config.MONITORING_MACD_REFIRE_GATE),
                        "A5 varsayılanı AÇIK olmalı (hedef #1: başarı oranı)")
        with patch.object(monitoring.database, "get_llm_setting",
                          AsyncMock(return_value="{}")):
            settings = await monitoring.get_user_notification_settings()
        self.assertTrue(settings["macd_refire_gate"])

    async def test_explicit_setting_overrides_config(self):
        from app.routers import monitoring
        with patch.object(monitoring.database, "get_llm_setting",
                          AsyncMock(return_value='{"macd_refire_gate": false}')):
            settings = await monitoring.get_user_notification_settings()
        self.assertFalse(settings["macd_refire_gate"])

    async def test_editable_list_accepts_the_key(self):
        """`editable` demetinde olmazsa admin paneli anahtarı kaydedemez."""
        import inspect
        from app.routers import monitoring
        src = inspect.getsource(monitoring.update_monitoring_settings)
        self.assertIn("macd_refire_gate", src)


if __name__ == "__main__":
    unittest.main()
