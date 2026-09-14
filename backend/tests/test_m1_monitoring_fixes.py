"""M1 — MONITORING düzeltmeleri için KİLİT testleri.

Her test, ilgili düzeltme GERİ ALINIRSA BAŞARISIZ olacak şekilde yazılmıştır.
Kapsanan bulgular: R2-01/02/03/04/06/07/15/18/19, R3-01/04/10, R4-02/03/05/06/10/11/12/13, R5-C2.4.
Yalnızca `backend/app/routers/monitoring.py`, `config.py`, `api_common.py` davranışını test eder.
"""
import asyncio
import json
import os
import pathlib
import sys
import time
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_SETTINGS = {
    "enabled": True,
    "min_score": 70.0,
    "min_score_explicit": False,
    "min_target_pct": 0.0,
    "quiet_hours_start": None,
    "quiet_hours_end": None,
}


def _reset_state():
    from app.routers import monitoring
    monitoring._monitoring_state["notified_symbols"] = {}
    monitoring._monitoring_state["candidate_streak"] = {}
    monitoring._monitoring_state["pending_targets"] = {}
    monitoring._monitoring_state["history"] = []
    monitoring._monitoring_state["risk_off"] = False
    monitoring._monitoring_state["risk_off_unknown"] = False
    # D-07: yeniden tetikleme kapısı da sıfırlanır. Aksi halde aynı sembolü
    # aynı fiyatla kullanan ikinci test, kapı tarafından bastırılır
    # (kapı doğru çalışıyor; test izolasyonu eksikti).
    monitoring._monitoring_state["notified_prices"] = {}
    monitoring._monitoring_state["refire_blocked"] = 0
    monitoring._deferred_push.clear()


# ---------------------------------------------------------------------------
# M1-01 — Skor kapısı ham velocity_score'dan (cap'ten bağımsız)
# ---------------------------------------------------------------------------
class ScoreGateRawTests(unittest.TestCase):
    def test_min_raw_score_config_default(self):
        from app.config import config
        self.assertAlmostEqual(config.MONITORING_MIN_RAW_SCORE, 1400.0)

    def test_default_gate_is_raw_constant_independent_of_cap(self):
        from app.routers import monitoring
        from app.config import config
        # Admin panel eşiği set etmemişse kapı MUTLAK ham skordur.
        self.assertAlmostEqual(monitoring._effective_min_raw_score({"min_score_explicit": False}),
                               config.MONITORING_MIN_RAW_SCORE)
        orig = config.MONITORING_SCORE_NORM_CAP
        try:
            config.MONITORING_SCORE_NORM_CAP = 1000.0  # cap değişse bile kapı KAYMAZ
            self.assertAlmostEqual(monitoring._effective_min_raw_score({"min_score_explicit": False}),
                                   1400.0)
            # Eski panel-türetimli mantık 70/100*1000 = 700 verirdi → geri alma yakalanır.
        finally:
            config.MONITORING_SCORE_NORM_CAP = orig

    def test_explicit_admin_panel_overrides_default_raw(self):
        from app.routers import monitoring
        from app.config import config
        cap = config.MONITORING_SCORE_NORM_CAP
        # Açık admin paneli 50 → ham eşik 50/100*cap.
        self.assertAlmostEqual(
            monitoring._effective_min_raw_score({"min_score": 50, "min_score_explicit": True}),
            round(0.5 * cap, 4))

    def test_backward_compat_panel_key_without_marker(self):
        from app.routers import monitoring
        from app.config import config
        # `min_score` anahtarı varsa (testlerin/eski sözlüklerin) panel sayılır.
        self.assertAlmostEqual(
            monitoring._effective_min_raw_score({"min_score": 70.0}),
            round(0.70 * config.MONITORING_SCORE_NORM_CAP, 4))

    def test_run_scan_uses_raw_gate_source(self):
        from app.routers import monitoring
        src = __import__("inspect").getsource(monitoring._run_scan)
        self.assertIn("effective_min_raw_score", src, "aday kapısı ham skordan seçilmeli (R2-01)")
        self.assertIn('float(c.get("velocity_score", 0) or 0) >= effective_min_raw_score', src)


class NotifyRawGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_filters_by_raw_not_panel(self):
        """cap değişince panel-türetimli kapı ile ham kapı AYRIŞIR; ham kapı uygulanmalı."""
        from app.routers import monitoring
        from app.config import config
        from app import database

        _reset_state()
        orig = config.MONITORING_SCORE_NORM_CAP
        try:
            config.MONITORING_SCORE_NORM_CAP = 1000.0
            # raw=800 → panel 80 (panel kapısı 70'i GEÇER) ama ham kapı 1400 → ELENMELİ.
            settings = dict(BASE_SETTINGS)
            cand = [{"symbol": "RAWTEST", "velocity_score": 800.0, "target_pct": 5.0, "price": 10.0}]
            with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "k"}), \
                 patch.object(database, "save_monitoring_notifications", AsyncMock(return_value=0)), \
                 patch.object(database, "get_pending_monitoring_notifications", AsyncMock(return_value={})), \
                 patch.object(monitoring, "deliver_web_push", AsyncMock(return_value={"ok": True})), \
                 patch.object(monitoring.market, "get_ticker", return_value={"last_price": 10.0}), \
                 patch.object(monitoring, "ws_manager", SimpleNamespace(broadcast=AsyncMock())):
                res = await monitoring._notify([dict(c) for c in cand], settings)
            self.assertEqual(res, [], "ham kapı panel-türetimli kapıya kırpılmamalı (R2-01/R2-02)")
        finally:
            config.MONITORING_SCORE_NORM_CAP = orig


# ---------------------------------------------------------------------------
# M1-02 — Başarı tanımı: TAMAMEN BAŞARILI yalnızca GERÇEK dokunuş
# ---------------------------------------------------------------------------
class ReportSuccessDefinitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_half_target_is_kismi_not_success(self):
        from app.routers import monitoring
        from app import database
        from app.config import config
        since = config.MONITORING_SCORE_NORM_SINCE

        def row(**kw):
            d = {"id": 1, "symbol": "X", "message": "m", "title": "t", "score": 80.0,
                 "target_pct": 2.0, "price": 100.0, "expected_price": 102.0,
                 "detected_at": since + 100, "horizon_minutes": 5, "sent_via_push": False,
                 "candidate_id": "c", "mode": None, "ml_hit_probability": None,
                 "candidate_status": "evaluated", "mfe_pct": 3.0, "touched_target": True}
            d.update(kw)
            return d

        rows = [
            row(id=1, touched_target=True, mfe_pct=3.0),    # gerçek dokunuş
            row(id=2, touched_target=False, mfe_pct=1.2),   # yarım-hedef (2.0×0.5=1.0)
            row(id=3, touched_target=False, mfe_pct=0.0),   # hiç hareket
        ]
        with patch.object(database, "get_monitoring_velocity_matches", AsyncMock(return_value=rows)), \
             patch.object(database, "get_llm_setting", AsyncMock(return_value="{}")):
            res = await monitoring.report_notifications(limit=200)
        status = {n["id"]: n["status"] for n in res["notifications"]}
        self.assertEqual(status[1], "TAMAMEN BAŞARILI")
        self.assertEqual(status[2], "KISMİ", "yarım-hedef BAŞARILI değil KISMİ olmalı (R3-04)")
        self.assertEqual(status[3], "BAŞARISIZ")
        self.assertEqual(res["breakdown"]["success_count"], 1)
        self.assertEqual(res["breakdown"]["evaluated"], 3)
        self.assertEqual(res["overall"]["success_count"], 1, "genel toplam da gerçek dokunuş kuralına tabi")
        self.assertEqual(res["overall"]["evaluated"], 3)


# ---------------------------------------------------------------------------
# M1-03 — Debounce bandı varsayılanlarda BOŞ DEĞİL
# ---------------------------------------------------------------------------
class DebounceBandTests(unittest.IsolatedAsyncioTestCase):
    def test_fast_lane_strictly_above_default_gate(self):
        from app.routers import monitoring
        from app.config import config
        panel_min = monitoring._effective_min_score({"min_score": config.MONITORING_MIN_SCORE_DEFAULT})
        fast = float(config.MONITORING_FAST_LANE_SCORE)
        self.assertGreater(fast, panel_min,
                           "fast-lane varsayılan kapının KESİN üstünde olmalı, yoksa debounce bandı boş (R2-04)")

    async def test_mid_band_candidate_debounced_then_notified(self):
        from app.routers import monitoring
        from app import database
        _reset_state()
        settings = dict(BASE_SETTINGS)  # ham kapı 1400 → raw 1400 geçer; panel 70 < fast-lane
        cand = [{"symbol": "BANDTEST", "velocity_score": 1400.0, "target_pct": 5.0,
                 "price": 10.0, "horizon_minutes": 5}]
        with patch.object(database, "save_monitoring_notifications", AsyncMock(return_value=0)), \
             patch.object(database, "get_pending_monitoring_notifications", AsyncMock(return_value={})), \
             patch.object(monitoring, "deliver_web_push", AsyncMock(return_value={"ok": True})), \
             patch.object(monitoring.market, "get_ticker", return_value={"last_price": 10.0}), \
             patch.object(monitoring, "ws_manager", SimpleNamespace(broadcast=AsyncMock())):
            first = await monitoring._notify([dict(c) for c in cand], settings)
            second = await monitoring._notify([dict(c) for c in cand], settings)
        self.assertEqual(first, [], "bant içi aday ilk turda debounce edilmeli (band boş olamaz)")
        self.assertEqual(len(second), 1, "bant içi aday N ardışık turda bildirilmeli")


# ---------------------------------------------------------------------------
# M1-04 — Satır başına norm_cap
# ---------------------------------------------------------------------------
class NormCapPerRowTests(unittest.TestCase):
    def test_legacy_row_uses_row_norm_cap(self):
        from app.routers import monitoring
        from app.config import config
        since = config.MONITORING_SCORE_NORM_SINCE
        # cap=40 iken yazılmış eski kayıt: kendi norm_cap'i ile normalize edilirse 100.
        row = {"score": 40.0, "detected_at": since - 1000, "norm_cap": 40}
        self.assertAlmostEqual(monitoring._stored_panel_score(row), 100.0, places=1)
        # norm_cap yoksa güncel cap (2000) ile 2.0 → geri alma yakalanır.
        legacy_no_cap = {"score": 40.0, "detected_at": since - 1000}
        self.assertAlmostEqual(monitoring._stored_panel_score(legacy_no_cap), 2.0, places=1)


# ---------------------------------------------------------------------------
# M1-05 — Push dürüstlüğü + ertelenen push kuyruğu
# ---------------------------------------------------------------------------
class PushHonestyTests(unittest.IsolatedAsyncioTestCase):
    async def _notify_one(self, delivery_ok):
        from app.routers import monitoring
        from app import database
        _reset_state()
        saved = {}

        async def fake_save(entries):
            for i, e in enumerate(entries):
                e["id"] = 500 + i
            saved["entries"] = [dict(e) for e in entries]
            return len(entries)

        settings = dict(BASE_SETTINGS)
        cand = [{"symbol": "PUSHTRY", "velocity_score": 1800.0, "target_pct": 5.0,
                 "price": 10.0, "horizon_minutes": 5}]
        mark = AsyncMock()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "k"}), \
             patch.object(database, "save_monitoring_notifications", side_effect=fake_save), \
             patch.object(database, "get_pending_monitoring_notifications", AsyncMock(return_value={})), \
             patch.object(database, "mark_monitoring_push_sent", mark), \
             patch.object(monitoring, "deliver_web_push",
                          AsyncMock(return_value={"ok": delivery_ok, "reason": "x"})), \
             patch.object(monitoring.market, "get_ticker", return_value={"last_price": 10.0}), \
             patch.object(monitoring, "ws_manager", SimpleNamespace(broadcast=AsyncMock())):
            res = await monitoring._notify([dict(c) for c in cand], settings)
            # B5: push gönderimi teslim adımına taşındı; dürüstlük testi teslimi
            # de koşmalı (sent_via_push / mark_monitoring_push_sent davranışı).
            await monitoring._deliver_scan_notifications(res)
        return res, saved, mark

    async def test_delivery_failure_keeps_sent_via_push_false(self):
        res, saved, mark = await self._notify_one(False)
        self.assertEqual(len(res), 1)
        self.assertFalse(res[0]["sent_via_push"], "başarısız teslim 'gönderildi' DEMEMELİ (R2-06)")
        self.assertFalse(saved["entries"][0]["sent_via_push"])
        mark.assert_not_called()

    async def test_delivery_success_marks_true(self):
        res, saved, mark = await self._notify_one(True)
        self.assertTrue(res[0]["sent_via_push"])
        mark.assert_called_once_with(500)


class DeferredFlushTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _settings(enabled=True):
        return json.dumps({"enabled": enabled, "min_score": 70, "min_target_pct": 2.0,
                           "quiet_hours_start": None, "quiet_hours_end": None})

    async def test_expired_horizon_dropped(self):
        from app.routers import monitoring
        from app import database
        _reset_state()
        now = time.time()
        monitoring._deferred_push.append({
            "symbol": "OLDTRY", "message": "m", "title": "t", "url": "u", "tag": "x",
            "score": 90, "target_pct": 2.0, "price": 1.0, "expected_price": 1.02,
            "detected_at": now - 10000, "horizon_minutes": 5, "id": 1})
        send = AsyncMock(return_value=True)
        with patch.object(database, "get_llm_setting", AsyncMock(return_value=self._settings())), \
             patch.object(database, "mark_monitoring_push_sent", AsyncMock()) as mark, \
             patch.object(monitoring, "_send_push", send):
            await monitoring._flush_deferred_push()
        self.assertEqual(len(monitoring._deferred_push), 0, "TTL dolmuş push düşürülmeli (R2-07)")
        send.assert_not_called()
        mark.assert_not_called()

    async def test_disabled_settings_drop_queue(self):
        from app.routers import monitoring
        from app import database
        _reset_state()
        monitoring._deferred_push.append({
            "symbol": "A", "message": "m", "title": "t", "url": "u", "tag": "x",
            "score": 90, "target_pct": 2.0, "price": 1.0, "expected_price": 1.02,
            "detected_at": time.time(), "horizon_minutes": 60, "id": 2})
        send = AsyncMock(return_value=True)
        with patch.object(database, "get_llm_setting", AsyncMock(return_value=self._settings(enabled=False))), \
             patch.object(monitoring, "_send_push", send):
            await monitoring._flush_deferred_push()
        self.assertEqual(len(monitoring._deferred_push), 0)
        send.assert_not_called()

    async def test_vapid_unconfigured_does_not_latch_forever(self):
        """VAPID yokken: gönderilmez ama TTL dolunca atılır (kalıcı latch YOK, R4-12)."""
        from app.routers import monitoring
        from app import database
        _reset_state()
        now = time.time()
        fresh = {"symbol": "F", "message": "m", "title": "t", "url": "u", "tag": "x",
                 "score": 90, "target_pct": 2.0, "price": 1.0, "expected_price": 1.02,
                 "detected_at": now, "horizon_minutes": 60, "id": 3}
        expired = dict(fresh, symbol="E", id=4, detected_at=now - 100000)
        monitoring._deferred_push.append(fresh)
        monitoring._deferred_push.append(expired)
        send = AsyncMock(return_value=True)
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": ""}), \
             patch.object(database, "get_llm_setting", AsyncMock(return_value=self._settings())), \
             patch.object(monitoring, "_send_push", send):
            await monitoring._flush_deferred_push()
        send.assert_not_called()
        remaining = list(monitoring._deferred_push)
        self.assertEqual([n["symbol"] for n in remaining], ["F"],
                         "bayat öğe atılmalı; taze öğe TTL'e kadar kalır (latch yok)")


# ---------------------------------------------------------------------------
# M1-06 — Scan endpoint GET salt-okunur, POST tetikleyici
# ---------------------------------------------------------------------------
class ScanEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_scan_is_read_only(self):
        from app.routers import monitoring
        from app import database
        called = {"n": 0}

        async def fake_run():
            called["n"] += 1
            return {"settings": {}, "candidates": [], "watchlist": [], "new_notifications": []}

        monitoring._monitoring_state["last_scan_at"] = time.time()
        with patch.object(monitoring, "_run_scan", side_effect=fake_run), \
             patch.object(database, "get_llm_setting", AsyncMock(return_value="{}")):
            res = await monitoring.monitoring_scan(request=None)
        self.assertEqual(called["n"], 0, "GET /scan artık tarama ÇALIŞTIRMAMALI (R4-03)")
        self.assertTrue(res["cached"])
        for key in ("cached", "data_ready", "system_startup", "loop_active",
                    "monitoring_min_raw_score", "monitoring_min_score_panel"):
            self.assertIn(key, res)

    async def test_post_scan_is_admin_gated_and_triggers(self):
        from app.routers import monitoring
        from app import database, api_common
        api_common._rate_limiters.clear()
        called = {"n": 0}

        async def fake_run():
            called["n"] += 1
            return {"settings": dict(BASE_SETTINGS), "candidates": [], "watchlist": [],
                    "new_notifications": []}

        with patch.object(monitoring, "_run_scan", side_effect=fake_run), \
             patch.object(database, "get_llm_setting", AsyncMock(return_value="{}")), \
             patch("app.main._require_admin", return_value=None):
            res = await monitoring.monitoring_scan_trigger(request=None)
        self.assertEqual(called["n"], 1)
        self.assertFalse(res["cached"])
        for key in ("cached", "data_ready", "system_startup", "loop_active"):
            self.assertIn(key, res)

        api_common._rate_limiters.clear()
        with patch("app.main._require_admin", side_effect=HTTPException(status_code=403, detail="x")):
            with self.assertRaises(HTTPException):
                await monitoring.monitoring_scan_trigger(request=None)


# ---------------------------------------------------------------------------
# M1-07 — Loop liveness canlı görev kaydından
# ---------------------------------------------------------------------------
class LoopLivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_task_returns_live_task(self):
        from app import api_common

        async def forever():
            await asyncio.sleep(30)

        task = api_common._start_background(forever, "m1-test-loop")
        try:
            self.assertIs(api_common.get_task("m1-test-loop"), task)
            self.assertFalse(task.done())
        finally:
            task.cancel()

    def test_loop_active_prefers_registry_over_stale_handle(self):
        from app.routers import monitoring
        from app import api_common

        class _Alive:
            def done(self):
                return False

        class _Dead:
            def done(self):
                return True

        old_reg = dict(api_common._background_registry)
        old_task = monitoring._loop_task
        try:
            api_common._background_registry["monitoring-scan-loop"] = _Alive()
            monitoring._loop_task = _Dead()  # respawn sonrası BAYAT referans
            self.assertTrue(monitoring._loop_is_active(),
                            "liveness canlı kayıttan okunmalı (R4-02)")
            api_common._background_registry.pop("monitoring-scan-loop", None)
            self.assertFalse(monitoring._loop_is_active())
        finally:
            api_common._background_registry.clear()
            api_common._background_registry.update(old_reg)
            monitoring._loop_task = old_task


# ---------------------------------------------------------------------------
# M1-08 — Ayar doğrulama → 422
# ---------------------------------------------------------------------------
class SettingsValidationTests(unittest.IsolatedAsyncioTestCase):
    async def _put(self, payload):
        from app.routers import monitoring
        from app import database
        saved = {}

        async def fake_get(key, default=None):
            return '{"enabled": true, "min_score": 70, "min_target_pct": 2.0}'

        async def fake_set(key, value):
            saved[key] = value

        with patch.object(database, "get_llm_setting", side_effect=fake_get), \
             patch.object(database, "set_llm_setting", side_effect=fake_set), \
             patch("app.main._require_admin", return_value=None):
            result = await monitoring.update_monitoring_settings(payload, request=None)
        return result, saved

    async def test_bad_inputs_return_422(self):
        for bad in ({"min_score": "abc"}, {"min_score": 150}, {"min_target_pct": 10},
                    {"quiet_hours_start": "25:00"}, {"quiet_hours_end": "xx"},
                    {"enabled": "maybe"}):
            with self.assertRaises(HTTPException) as cm:
                await self._put(bad)
            self.assertEqual(cm.exception.status_code, 422, f"geçersiz girdi 422 olmalı: {bad}")

    async def test_bad_input_does_not_corrupt_state(self):
        from app import database
        with patch.object(database, "set_llm_setting", AsyncMock()) as setmock, \
             patch.object(database, "get_llm_setting",
                          AsyncMock(return_value='{"enabled": true, "min_score": 70, "min_target_pct": 2.0}')), \
             patch("app.main._require_admin", return_value=None):
            with self.assertRaises(HTTPException):
                from app.routers import monitoring
                await monitoring.update_monitoring_settings({"min_score": "abc"}, request=None)
            setmock.assert_not_called()

    async def test_valid_input_saves_and_exposes_thresholds(self):
        result, saved = await self._put({"min_score": 55, "min_target_pct": 3.0,
                                         "quiet_hours_start": "22:00", "quiet_hours_end": "06:00"})
        parsed = json.loads(saved["monitoring_notification_settings"])
        self.assertEqual(parsed["min_score"], 55)
        self.assertEqual(parsed["enabled"], True)
        self.assertEqual(parsed["quiet_hours_start"], "22:00")
        self.assertIn("monitoring_min_raw_score", result)
        self.assertIn("monitoring_min_score_panel", result)
        self.assertAlmostEqual(result["monitoring_min_score_panel"], 55.0)


class StatePayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_exposes_thresholds_and_loop_active(self):
        from app.routers import monitoring
        from app import database
        with patch.object(database, "get_llm_setting", AsyncMock(return_value="{}")):
            res = await monitoring.monitoring_state()
        for key in ("monitoring_min_raw_score", "monitoring_min_score_panel",
                    "loop_active", "data_ready", "system_startup"):
            self.assertIn(key, res)

    async def test_settings_endpoint_exposes_thresholds(self):
        from app.routers import monitoring
        from app import database
        with patch.object(database, "get_llm_setting", AsyncMock(return_value="{}")):
            res = await monitoring.get_monitoring_settings()
        self.assertIn("monitoring_min_raw_score", res)
        self.assertIn("monitoring_min_score_panel", res)


# ---------------------------------------------------------------------------
# M1-09 — active-notification skoru panel ölçeğinde
# ---------------------------------------------------------------------------
class ActiveNotificationScoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_score_is_panel_normalized(self):
        from app.routers import monitoring
        from app import database
        from app.config import config
        since = config.MONITORING_SCORE_NORM_SINCE
        row = {"id": 1, "symbol": "X", "score": 1500.0, "target_pct": 2.0, "price": 100.0,
               "expected_price": 102.0, "horizon_minutes": 10_000_000,
               "detected_at": since - 100, "mode": None}
        with patch.object(database, "get_pending_monitoring_notification", AsyncMock(return_value=dict(row))), \
             patch.object(monitoring.market, "get_ticker", return_value={"last_price": 101.0}):
            res = await monitoring.monitoring_active_notification("X")
        self.assertTrue(res["active"])
        self.assertAlmostEqual(res["score"], 75.0, places=1,
                               msg="ham 1500 → panel 75 normalize edilmeli (R4-05)")


# ---------------------------------------------------------------------------
# M1-10 — Sağlamlaştırma (cap guard, clamp, risk_off_unknown, quiet_hours_active)
# ---------------------------------------------------------------------------
class RobustnessTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_score_guards_zero_cap(self):
        from app.routers import monitoring
        from app.config import config
        orig = config.MONITORING_SCORE_NORM_CAP
        try:
            config.MONITORING_SCORE_NORM_CAP = 0
            self.assertEqual(monitoring.normalize_score(5.0), 5.0)  # ZeroDivisionError YOK
        finally:
            config.MONITORING_SCORE_NORM_CAP = orig

    def test_effective_min_score_lower_clamped(self):
        from app.routers import monitoring
        self.assertEqual(monitoring._effective_min_score({"min_score": -5}), 0.0)
        self.assertEqual(monitoring._effective_min_score({"min_score": 150}), 100.0)

    async def test_risk_off_unknown_persisted_and_restored(self):
        from app.routers import monitoring
        from app import database
        captured = {}

        async def fake_set(key, value):
            captured[key] = value

        _reset_state()
        monitoring._monitoring_state["risk_off_unknown"] = True
        with patch.object(database, "set_llm_setting", side_effect=fake_set):
            await monitoring._persist_runtime_state()
        payload = json.loads(captured[monitoring._STATE_SETTING_KEY])
        self.assertTrue(payload.get("risk_off_unknown"), "risk_off_unknown kalıcı olmalı (R4-11)")

        monitoring._monitoring_state["risk_off_unknown"] = False
        with patch.object(database, "get_llm_setting",
                          AsyncMock(return_value=json.dumps({"risk_off_unknown": True}))):
            await monitoring.restore_runtime_state()
        self.assertTrue(monitoring._monitoring_state["risk_off_unknown"])

    async def test_quiet_hours_active_helper_exported(self):
        from app.routers import monitoring
        import time as _time
        base = _time.localtime()
        fake = _time.struct_time((base.tm_year, base.tm_mon, base.tm_mday, 23, 30, 0,
                                  base.tm_wday, base.tm_yday, base.tm_isdst))
        with patch.object(monitoring.time, "localtime", return_value=fake):
            active = await monitoring.quiet_hours_active(
                {"quiet_hours_start": "22:00", "quiet_hours_end": "06:00"})
        self.assertTrue(active)
        with patch.object(monitoring.time, "localtime", return_value=fake):
            inactive = await monitoring.quiet_hours_active(
                {"quiet_hours_start": None, "quiet_hours_end": None})
        self.assertFalse(inactive)

    def test_record_history_wired_into_notify(self):
        from app.routers import monitoring
        src = __import__("inspect").getsource(monitoring._notify)
        self.assertIn("await _record_history(new_entries)", src,
                      "ölü _record_history bağlanmalı (R2-15)")


if __name__ == "__main__":
    unittest.main()
