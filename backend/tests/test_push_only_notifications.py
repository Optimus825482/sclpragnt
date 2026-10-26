"""PANEL BİLDİRİMİ KALDIRILDI (2026-10-17) — "bildirim yalnız push'tur" kilitleri.

Kural: bir radar bildirimi `monitoring_notifications`'a yazılır, WS ile uygulamaya
yayınlanır, oturum geçmişine ve LLM ikinci göze girer YALNIZ web push gerçekten
DENENİRSE (şimdi gönderilir ya da sessiz saatte ertelenip flush'ta denenir).
Push denenmeyen adaylar bildirim üretmez ama ÖLÇÜM kaydı ve OTONOM PAPER yolu değişmez.
Teslimi başarısız ama denenmiş push yine bir push bildirimidir (`push_attempted`).
"""
import asyncio
import os
import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import notification_policy                      # noqa: E402
from app.routers import monitoring, auto_paper           # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _notif(symbol="BTCTRY", **kw):
    n = {"symbol": symbol, "message": "radar", "title": "radar", "url": f"/charts?symbol={symbol}",
         "tag": f"monitoring-{symbol}", "score": 74.0, "target_pct": 2.0, "price": 100.0,
         "horizon_minutes": 5, "detected_at": time.time(), "mode": "trend_devam",
         "quiet_hours": False, "updated": False, "id": None}
    n.update(kw)
    return n


class _Base(unittest.TestCase):
    """Teslim aşaması için ortak yamalar. `vapid` ortam değişkeni alt sınıfta seçilir."""
    vapid = "dummy-key"

    def setUp(self):
        monitoring._deferred_push.clear()
        monitoring._monitoring_state["history"] = []
        monitoring._monitoring_state["pending_targets"] = {}
        self.addCleanup(monitoring._deferred_push.clear)
        self.record = AsyncMock(side_effect=self._fake_record)
        self.send = AsyncMock(return_value=True)
        self.broadcast = AsyncMock(return_value=None)
        self.mark = AsyncMock(return_value=True)
        self.paper = AsyncMock(return_value=None)
        self.llm = MagicMock()
        self.whatsapp = AsyncMock(return_value=None)
        settings = {"enabled": True, "radar_unified_notify": True, "radar_combined_enabled": False}
        patches = [
            patch.object(monitoring, "get_user_notification_settings", new=AsyncMock(return_value=settings)),
            patch.object(monitoring, "_record_history", new=self.record),
            patch.object(monitoring, "_send_push", new=self.send),
            patch.object(monitoring, "ws_manager", new=MagicMock(broadcast=self.broadcast)),
            patch.object(monitoring.database, "mark_monitoring_push_sent", new=self.mark),
            patch.object(monitoring.database, "mark_rising_alert_notified", new=AsyncMock()),
            patch.object(auto_paper, "try_open_from_notification", new=self.paper),
            patch.object(monitoring, "_maybe_llm_second_eye", new=self.llm),
            patch.object(monitoring, "_broadcast_user_whatsapp", new=self.whatsapp),
            patch.dict(os.environ, {"VAPID_PRIVATE_KEY": self.vapid}, clear=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    async def _fake_record(entries):
        for i, e in enumerate(entries, start=1):
            if e.get("id") is None:
                e["id"] = 1000 + i


class PushAttemptedDeliveryTests(_Base):
    """VAPID tanımlı + sessiz saat değil: push denenir → kayıt + yayın + geçmiş + LLM."""

    def test_push_attempt_records_broadcasts_and_marks_delivery(self):
        n = _notif()
        _run(monitoring._deliver_scan_notifications([n]))
        self.record.assert_awaited_once()
        recorded = self.record.await_args.args[0][0]
        self.assertTrue(recorded["push_attempted"], "denenmiş push `push_attempted` taşımalı")
        self.send.assert_awaited_once()
        self.mark.assert_awaited_once_with(n["id"])
        self.assertTrue(n["sent_via_push"])
        self.broadcast.assert_awaited_once()
        self.assertEqual("monitoring_alert", self.broadcast.await_args.args[0]["type"])
        self.assertEqual([n], self.broadcast.await_args.args[0]["data"])
        self.assertEqual([n], monitoring._monitoring_state["history"])
        self.llm.assert_called_once_with([n])

    def test_failed_delivery_is_still_a_recorded_push_notification(self):
        """Teslimi başarısız push: kayıt + yayın VAR, `sent_via_push` dürüstçe False."""
        self.send.return_value = False
        n = _notif()
        _run(monitoring._deliver_scan_notifications([n]))
        self.record.assert_awaited_once()
        self.assertTrue(self.record.await_args.args[0][0]["push_attempted"])
        self.assertFalse(n["sent_via_push"])
        self.mark.assert_not_awaited()
        self.broadcast.assert_awaited_once()

    def test_updates_are_rebroadcast_but_not_re_recorded_or_pushed(self):
        upd = _notif("ETHTRY", id=55, updated=True)
        _run(monitoring._deliver_scan_notifications([upd]))
        self.record.assert_not_awaited()
        self.send.assert_not_awaited()
        self.broadcast.assert_awaited_once()
        self.llm.assert_called_once_with([])

    def test_policy_blocked_candidate_is_not_recorded_pushed_or_broadcast(self):
        n = _notif(mode="notr")  # varsayılan politikada devre dışı mod
        notification_policy.precheck([n])
        self.assertTrue(n.get("policy_blocked"))
        # `_notify` bloklananı teslim listesinden zaten çıkarır; teslim aşaması yine de kayda sokmaz.
        _run(monitoring._deliver_scan_notifications([n]))
        self.send.assert_not_awaited()


class NoPushNoNotificationTests(_Base):
    """VAPID yok: push denenemez → bildirim YOK; otonom paper yolu DEĞİŞMEZ."""
    vapid = ""

    def test_no_vapid_creates_no_record_no_broadcast_no_history_no_llm(self):
        n = _notif()
        _run(monitoring._deliver_scan_notifications([n]))
        self.record.assert_not_awaited()
        self.send.assert_not_awaited()
        self.broadcast.assert_not_awaited()
        self.assertEqual([], monitoring._monitoring_state["history"])
        self.llm.assert_called_once_with([])
        self.assertIsNone(n.get("id"))

    def test_autonomous_paper_still_runs_for_non_notified_candidate(self):
        """Kayıtsız (panel-only olacak) aday eskisi gibi otonom paper'a gider."""
        n = _notif()
        _run(monitoring._deliver_scan_notifications([n]))
        self.paper.assert_awaited_once()
        self.assertEqual("BTCTRY", self.paper.await_args.args[0]["symbol"])
        self.assertIsNone(self.paper.await_args.args[0].get("id"))


class QuietHoursDeferralTests(_Base):
    """Sessiz saat: ertele, kayıt/yayın YOK; flush'ta push denendiğinde kayıt+yayın."""

    def test_quiet_hours_defer_without_record_or_broadcast_but_paper_runs(self):
        n = _notif(quiet_hours=True)
        _run(monitoring._deliver_scan_notifications([n]))
        self.assertEqual(1, len(monitoring._deferred_push))
        self.record.assert_not_awaited()
        self.send.assert_not_awaited()
        self.broadcast.assert_not_awaited()
        self.assertEqual([], monitoring._monitoring_state["history"])
        self.paper.assert_awaited_once()   # otonom yol (kendi sessiz-saat kapısı auto_paper'da) korunur

    def test_flush_records_and_broadcasts_when_push_is_attempted(self):
        n = _notif()
        monitoring._deferred_push.append(n)
        with patch.object(monitoring, "_in_quiet_hours", return_value=False):
            _run(monitoring._flush_deferred_push())
        self.send.assert_awaited_once()
        self.record.assert_awaited_once()
        self.assertTrue(n["push_attempted"])
        self.assertTrue(n["sent_via_push"])
        self.broadcast.assert_awaited_once()
        self.assertEqual("monitoring_alert", self.broadcast.await_args.args[0]["type"])
        self.assertEqual([n], monitoring._monitoring_state["history"])
        self.assertEqual(0, len(monitoring._deferred_push))

    def test_flush_failed_push_is_recorded_once_and_retried_without_duplicates(self):
        n = _notif()
        monitoring._deferred_push.append(n)
        self.send.return_value = False
        with patch.object(monitoring, "_in_quiet_hours", return_value=False):
            _run(monitoring._flush_deferred_push())
            self.assertEqual(1, len(monitoring._deferred_push), "başarısız push TTL'e kadar kuyrukta kalır")
            self.assertEqual(1, self.record.await_count)
            self.assertFalse(n["sent_via_push"])
            self.assertEqual(1, self.broadcast.await_count)
            # İkinci tur: push bu sefer ulaşır → yalnız etiket düzelir, çift kayıt/yayın YOK.
            self.send.return_value = True
            _run(monitoring._flush_deferred_push())
        self.assertEqual(1, self.record.await_count)
        self.assertEqual(1, self.broadcast.await_count)
        self.mark.assert_awaited_once_with(n["id"])
        self.assertTrue(n["sent_via_push"])
        self.assertEqual(0, len(monitoring._deferred_push))

    def test_flush_drops_daily_symbol_limit_skip_without_requeue(self):
        """Günde-1-push atlaması kalıcıdır: kuyruğa geri konmaz (TTL'e kadar sonsuz deneme yok)."""
        n = _notif()
        monitoring._deferred_push.append(n)

        async def _skip(notif):
            notif["push_skip_reason"] = "daily_symbol_limit"
            return False
        self.send.side_effect = _skip
        with patch.object(monitoring, "_in_quiet_hours", return_value=False):
            _run(monitoring._flush_deferred_push())
        self.assertEqual(0, len(monitoring._deferred_push))
        self.assertEqual(1, self.send.await_count)

    def test_flush_drops_stale_without_record_or_broadcast(self):
        n = _notif(detected_at=time.time() - 3600)
        monitoring._deferred_push.append(n)
        with patch.object(monitoring, "_in_quiet_hours", return_value=False):
            _run(monitoring._flush_deferred_push())
        self.send.assert_not_awaited()
        self.record.assert_not_awaited()
        self.broadcast.assert_not_awaited()

    def test_flush_skips_alarm_envelopes_for_record_and_broadcast(self):
        alarm = {"message": "BTC alarmı", "title": "alarm", "url": "/monitoring", "tag": "alert-1",
                 "symbol": "ALERT", "detected_at": time.time(), "horizon_minutes": 1440,
                 "deferred_alert": True}
        monitoring._deferred_push.append(alarm)
        with patch.object(monitoring, "_in_quiet_hours", return_value=False):
            _run(monitoring._flush_deferred_push())
        self.send.assert_awaited_once()
        self.record.assert_not_awaited()
        self.broadcast.assert_not_awaited()


class QuietNoVapidFlushTests(_Base):
    vapid = ""

    def test_flush_without_vapid_attempts_nothing_and_records_nothing(self):
        monitoring._deferred_push.append(_notif())
        with patch.object(monitoring, "_in_quiet_hours", return_value=False):
            _run(monitoring._flush_deferred_push())
        self.send.assert_not_awaited()
        self.record.assert_not_awaited()
        self.broadcast.assert_not_awaited()
        self.assertEqual(1, len(monitoring._deferred_push), "TTL dolana kadar tutulur (latch yok)")


class FastPathTests(unittest.TestCase):
    """Birleşik hızlı yol: VAPID yoksa kayıt/WS yok ama ölçüm kaydı + otonom paper var."""

    def _call(self, vapid):
        settings = {"enabled": True, "min_score": 10.0, "min_target_pct": 0.0, "radar_unified_notify": True}
        self.record = AsyncMock(side_effect=lambda es: [e.__setitem__("id", 77) for e in es])
        self.send = AsyncMock(return_value=True)
        self.broadcast = AsyncMock(return_value=None)
        self.paper = AsyncMock(return_value=None)
        self.velocity_save = AsyncMock(return_value=1)
        self.llm = MagicMock()
        monitoring._monitoring_state["history"] = []
        monitoring._unified_fast_last.clear()
        monitoring._monitoring_state["notified_symbols"].pop("FASTTRY", None)
        with patch.object(monitoring, "get_user_notification_settings", new=AsyncMock(return_value=settings)), \
             patch.object(monitoring, "_radar_unified_enabled", new=AsyncMock(return_value=True)), \
             patch.object(monitoring.unified_signals, "enabled", return_value=True), \
             patch.object(monitoring.unified_signals, "recently_notified", return_value=False), \
             patch.object(monitoring.unified_signals, "build_fusion_candidate",
                          return_value={"symbol": "FASTTRY", "unified_score": 92.0, "target_pct": 3.0,
                                        "price": 10.0, "horizon_minutes": 5}), \
             patch.object(monitoring.database, "get_pending_monitoring_notification",
                          new=AsyncMock(return_value=None)), \
             patch.object(monitoring.database, "save_velocity_candidates", new=self.velocity_save), \
             patch.object(monitoring.database, "mark_monitoring_push_sent", new=AsyncMock()), \
             patch.object(monitoring, "_ticker_price", return_value=10.0), \
             patch.object(monitoring, "_in_quiet_hours", return_value=False), \
             patch.object(monitoring, "_master_surge_block_reason", return_value=None), \
             patch.object(monitoring, "_record_history", new=self.record), \
             patch.object(monitoring, "_send_push", new=self.send), \
             patch.object(monitoring, "_maybe_llm_second_eye", new=self.llm), \
             patch.object(monitoring, "ws_manager", new=MagicMock(broadcast=self.broadcast)), \
             patch.object(auto_paper, "try_open_from_notification", new=self.paper), \
             patch.dict(os.environ, {"VAPID_PRIVATE_KEY": vapid}, clear=False):
            return _run(monitoring._unified_fast_notify_impl("FASTTRY", "jump", 92.0))

    def test_fast_path_with_push_records_pushes_broadcasts(self):
        notif = self._call("dummy-key")
        self.assertIsNotNone(notif)
        self.record.assert_awaited_once()
        self.assertTrue(notif["push_attempted"])
        self.send.assert_awaited_once()
        self.broadcast.assert_awaited_once()
        self.paper.assert_awaited_once()
        self.llm.assert_called_once()
        self.velocity_save.assert_awaited_once()

    def test_fast_path_without_vapid_keeps_measurement_and_paper_only(self):
        notif = self._call("")
        self.assertIsNotNone(notif)
        self.record.assert_not_awaited()
        self.send.assert_not_awaited()
        self.broadcast.assert_not_awaited()
        self.llm.assert_not_called()
        self.assertEqual([], monitoring._monitoring_state["history"])
        self.velocity_save.assert_awaited_once()   # ölçüm kaydı korunur
        self.paper.assert_awaited_once()           # otonom paper korunur


class NotifyNoLongerPersistsTests(unittest.TestCase):
    """`_notify` artık bildirim satırı YAZMAZ (kayıt teslim aşamasında, push denenirken)."""

    def test_notify_does_not_record_or_touch_history(self):
        settings = {"enabled": True, "min_score": 1.0, "min_target_pct": 1.0,
                    "quiet_hours_start": None, "quiet_hours_end": None}
        candidates = [{"symbol": "NOREC", "velocity_score": 30.0, "target_pct": 5.0, "price": 2.0}]
        monitoring._monitoring_state["history"] = []
        monitoring._monitoring_state["candidate_streak"] = {}
        monitoring._monitoring_state["pending_targets"] = {}
        monitoring._monitoring_state["notified_prices"] = {}
        monitoring._monitoring_state["notified_scores"] = {}
        monitoring._monitoring_state["notified_symbols"] = {}
        monitoring._notify_last_sent_at.clear()
        monitoring._notify_daily_count.clear()
        rec = AsyncMock(return_value=None)
        with patch.object(monitoring.database, "get_pending_monitoring_notifications",
                          new=AsyncMock(return_value={})), \
             patch.object(monitoring, "_record_history", new=rec), \
             patch.object(monitoring.config, "MONITORING_RR_ENABLED", False), \
             patch.object(monitoring.config, "MONITORING_DEBOUNCE_SCANS", 0):
            result = _run(monitoring._notify(candidates, settings))
        self.assertEqual(1, len(result))
        rec.assert_not_awaited()
        self.assertEqual([], monitoring._monitoring_state["history"])
        # Ölçüm/tekilleştirme durumu AYNEN işlenir (aday yeniden bildirilmesin).
        self.assertIn("NOREC", monitoring._monitoring_state["pending_targets"])
        self.assertIn("NOREC", monitoring._monitoring_state["notified_symbols"])


class ReportsPushOnlyTests(unittest.TestCase):
    """/api/reports/notifications: yalnız push bildirimleri; `channel=panel` etkisiz."""

    @staticmethod
    def _row(i, **kw):
        since = time.time() - 600
        d = {"id": i, "symbol": f"S{i}TRY", "mode": "unified", "score": 80.0, "sources": None,
             "target_pct": 2.0, "price": 100.0, "expected_price": 102.0,
             "detected_at": since + i, "horizon_minutes": 5, "sent_via_push": True,
             "push_attempted": True, "candidate_id": f"c{i}", "ml_hit_probability": None,
             "candidate_status": "evaluated", "mfe_pct": 3.0, "touched_target": True}
        d.update(kw)
        return d

    def _report(self, rows, **kw):
        with patch.object(monitoring.database, "get_monitoring_velocity_matches",
                          AsyncMock(return_value=rows)), \
             patch.object(monitoring.database, "get_llm_setting", AsyncMock(return_value="{}")):
            return _run(monitoring.report_notifications(limit=200, **kw))

    def test_legacy_panel_rows_are_excluded_by_default(self):
        rows = [self._row(1),                                                     # teslim edildi
                self._row(2, sent_via_push=False, push_attempted=True),           # denendi, teslim yok
                self._row(3, sent_via_push=False, push_attempted=None),           # eski "yalnız panel"
                self._row(4, sent_via_push=False, push_attempted=False)]          # eski "yalnız panel"
        res = self._report(rows)
        ids = sorted(n["id"] for n in res["notifications"])
        self.assertEqual([1, 2], ids)

    def test_channel_panel_param_is_accepted_but_ignored(self):
        rows = [self._row(1), self._row(3, sent_via_push=False, push_attempted=None)]
        for ch in ("all", "push", "panel", "PANEL", "weird"):
            res = self._report(rows, channel=ch)
            self.assertEqual([1], [n["id"] for n in res["notifications"]], ch)

    def test_panel_stats_removed_from_breakdown(self):
        res = self._report([self._row(1)])
        self.assertNotIn("panel_stats", res["breakdown"])
        self.assertIn("confluence_stats", res["breakdown"])


class PolicyPrecheckTests(unittest.TestCase):
    def test_precheck_marks_blocked_without_counting_kept(self):
        notification_policy.reset_stats()
        a, b = {"symbol": "A", "mode": "notr", "score": 80}, {"symbol": "B", "mode": "trend_devam", "score": 80}
        blocked = notification_policy.precheck([a, b])
        self.assertEqual([a], [e for e, _ in blocked])
        self.assertIn("policy_blocked", a)
        self.assertNotIn("policy_blocked", b)
        stats = notification_policy.get_stats()
        self.assertEqual(0, stats["kept"])
        self.assertEqual(1, stats["blocked"])


if __name__ == "__main__":
    unittest.main()


class HeartbeatTests(unittest.TestCase):
    """2026-10-18 SESSİZLİK NABZI (düzeltilmiş): `_notify` içinde, tarama listesinin en yüksek skorlu adayı."""

    def setUp(self):
        from app.config import config
        for name, val in (("RADAR_NOTIFY_CONFIRM_RULE_ENABLED", True),
                          ("RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE", 0.0),
                          ("RADAR_NOTIFY_HEARTBEAT_MINUTES", 15),
                          ("MONITORING_RR_ENABLED", False),
                          ("MONITORING_DEBOUNCE_SCANS", 0)):
            p = patch.object(config, name, val)
            p.start()
            self.addCleanup(p.stop)
        for key in ("history", "candidate_streak", "pending_targets", "notified_prices", "notified_scores", "notified_symbols"):
            monitoring._monitoring_state[key] = {} if key != "history" else []
        monitoring._monitoring_state["_last_push_ts"] = time.time() - 16 * 60
        monitoring._monitoring_state.pop("_last_heartbeat_ts", None)
        monitoring._notify_last_sent_at.clear()
        monitoring._notify_daily_count.clear()
        self.last_push_db = AsyncMock(return_value=None)
        for p in (patch.object(monitoring.database, "get_pending_monitoring_notifications", new=AsyncMock(return_value={})),
                  patch.object(monitoring.database, "get_last_push_sent_at", new=self.last_push_db),
                  patch.object(monitoring, "_record_history", new=AsyncMock(return_value=None)),
                  patch.object(monitoring, "_vapid_configured", new=lambda: True)):
            p.start()
            self.addCleanup(p.stop)
        self.settings = {"enabled": True, "min_score": 99.0, "min_target_pct": 0.0,
                         "quiet_hours_start": None, "quiet_hours_end": None}

    @staticmethod
    def _cands():
        return [
            {"symbol": "LOWTRY", "velocity_score": 300.0, "target_pct": 1.0, "price": 2.0, "mode": "trend_devam", "sources": ["velocity"]},
            {"symbol": "TOPTRY", "velocity_score": 900.0, "target_pct": 1.0, "price": 3.0, "mode": "trend_devam", "sources": ["velocity"]},
            {"symbol": "NOTRTRY", "velocity_score": 5000.0, "target_pct": 1.0, "price": 4.0, "mode": "notr", "sources": ["velocity"]},
            {"symbol": "UNITRY", "velocity_score": 9000.0, "target_pct": 1.0, "price": 5.0, "mode": "unified", "sources": ["velocity", "jump"]},
        ]

    def test_due_heartbeat_emits_top_scoring_allowed_candidate(self):
        out = _run(monitoring._notify(self._cands(), self.settings))
        self.assertEqual(1, len(out))
        hb = out[0]
        self.assertEqual("TOPTRY", hb["symbol"])              # notr ve unified aday olmaz; eşik (min_score 99) aranmaz
        self.assertEqual("teyitsiz", hb["notify_tier"])
        self.assertTrue(hb["title"].startswith("TEYİTSİZ · "))
        self.assertFalse(hb.get("policy_blocked"))
        self.assertIsNone(notification_policy.evaluate(hb))     # lavabo yeniden bloklamaz
        self.assertIn("TOPTRY", monitoring._monitoring_state["notified_symbols"])

    def test_not_due_emits_nothing(self):
        monitoring._monitoring_state["_last_push_ts"] = time.time() - 5 * 60
        self.assertEqual([], _run(monitoring._notify(self._cands(), self.settings)))

    def test_attempt_throttles_next_cycle(self):
        self.assertEqual(1, len(_run(monitoring._notify(self._cands(), self.settings))))
        self.assertEqual([], _run(monitoring._notify(self._cands(), self.settings)))   # aynı tur tekrarı: nabız denemesi süreyi yeniler

    def test_counter_resumes_from_db_after_restart(self):
        monitoring._monitoring_state.pop("_last_push_ts", None)
        self.last_push_db.return_value = time.time() - 60          # 1 dk önce push gitmiş (DB)
        self.assertEqual([], _run(monitoring._notify(self._cands(), self.settings)))
        self.last_push_db.assert_awaited()
        monitoring._monitoring_state.pop("_last_push_ts", None)
        self.last_push_db.return_value = time.time() - 20 * 60     # 20 dk önce
        self.assertEqual(1, len(_run(monitoring._notify(self._cands(), self.settings))))

    def test_passing_notification_suppresses_heartbeat(self):
        from app.config import config
        settings = dict(self.settings, min_score=1.0)
        cands = [{"symbol": "OKTRY", "velocity_score": 900.0, "target_pct": 1.0, "price": 3.0,
                  "mode": "trend_devam", "sources": ["velocity", "jump"]}]
        # `_build_notification` kaynakları aday bayraklarından türetir (burada yalnız velocity) → teyit kuralı
        # bu test için kapatılır ki normal bildirim politikadan geçsin; nabız o zaman devreye girmemeli.
        with patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", False):
            out = _run(monitoring._notify(cands, settings))
        self.assertEqual(["OKTRY"], [n["symbol"] for n in out])
        self.assertNotIn("notify_tier", out[0])

    def test_quiet_hours_or_flag_off_emits_nothing(self):
        from app.config import config
        with patch.object(config, "RADAR_NOTIFY_HEARTBEAT_MINUTES", 0):
            self.assertEqual([], _run(monitoring._notify(self._cands(), self.settings)))
        with patch.object(monitoring, "_in_quiet_hours", new=lambda s: True):
            self.assertEqual([], _run(monitoring._notify(self._cands(), self.settings)))


class HeartbeatPoolTests(HeartbeatTests):
    """2026-10-18 (ikinci düzeltme): nabız adayı yalnız eşiği geçenlerden değil TARAMA İZLEME LİSTESİNDEN de seçilir."""

    @staticmethod
    def _watch(symbol, score, **kw):
        row = {"symbol": symbol, "velocity_score": score, "target_pct": 1.0, "price": 2.0,
               "mode": "trend_devam", "sources": ["velocity"], "passes": False}
        row.update(kw)
        return row

    def test_empty_candidate_list_uses_watchlist_pool(self):
        pool = [self._watch("WLOW", 400.0), self._watch("WTOP", 1500.0), self._watch("WNOTR", 9000.0, mode="notr")]
        out = _run(monitoring._notify([], self.settings, heartbeat_pool=pool))
        self.assertEqual(["WTOP"], [n["symbol"] for n in out])
        self.assertEqual("teyitsiz", out[0]["notify_tier"])

    def test_union_takes_best_of_candidates_and_pool(self):
        cands = [self._watch("CAND", 700.0)]
        pool = [self._watch("POOLTOP", 2500.0)]
        out = _run(monitoring._notify(cands, self.settings, heartbeat_pool=pool))
        self.assertEqual(["POOLTOP"], [n["symbol"] for n in out])

    def test_risk_blocked_rows_are_not_heartbeat_material(self):
        pool = [self._watch("SPREAD", 9000.0, block_reason="asiri_spread:1.2%>0.5%_siniri"),
                self._watch("WICK", 8000.0, block_reason="ust_fitil_tuzagi:wick_0.80_z2.1"),
                self._watch("OVERBOUGHT", 7000.0, block_reason="mfi_asiri_alim:85"),
                self._watch("ATRLOW", 600.0, block_reason="atr_yetersiz:0.20%<0.40%")]
        out = _run(monitoring._notify([], self.settings, heartbeat_pool=pool))
        self.assertEqual(["ATRLOW"], [n["symbol"] for n in out])     # eşik/yapı nedeni sorun değil, risk nedeni elenir

    def test_pending_symbol_in_pool_is_skipped(self):
        pool = [self._watch("PENDING", 5000.0), self._watch("FREE", 900.0)]
        with patch.object(monitoring.database, "get_pending_monitoring_notifications",
                          new=AsyncMock(return_value={"PENDING": {"id": 1}})):
            out = _run(monitoring._notify([], self.settings, heartbeat_pool=pool))
        self.assertEqual(["FREE"], [n["symbol"] for n in out])

    def test_nothing_eligible_logs_diagnostic_and_sets_note(self):
        pool = [self._watch("ONLYNOTR", 5000.0, mode="notr")]
        with self.assertLogs("scalper.monitoring", level="INFO") as cm:
            out = _run(monitoring._notify([], self.settings, heartbeat_pool=pool))
        self.assertEqual([], out)
        self.assertTrue(any("uygun aday yok" in m for m in cm.output), cm.output)
        self.assertEqual({"pool": 1, "picked": None}, {k: monitoring._monitoring_state["_heartbeat_note"][k] for k in ("pool", "picked")})

    def test_note_records_pick_and_status_exposes_it(self):
        _run(monitoring._notify([], self.settings, heartbeat_pool=[self._watch("WTOP", 1500.0)]))
        self.assertEqual("WTOP", monitoring._monitoring_state["_heartbeat_note"]["picked"])
        fields = monitoring._threshold_fields(self.settings)
        self.assertEqual(15, fields["heartbeat_minutes"])
        self.assertEqual("WTOP", fields["heartbeat_note"]["picked"])
        self.assertIsNotNone(fields["heartbeat_last_attempt_age_sec"])


class HeartbeatDeliveryTests(_Base):
    """Nabız bildirimi push + kayıt + yayın alır ama otonom paper girişi ve LLM ikinci göz maliyeti DOĞURMAZ."""

    def test_heartbeat_skips_autonomous_paper_and_llm(self):
        hb = _notif("HBTRY", notify_tier="teyitsiz", title="TEYİTSİZ · HBTRY", sources=["velocity"])
        normal = _notif("OKTRY", sources=["velocity", "jump"])
        _run(monitoring._deliver_scan_notifications([hb, normal]))
        self.send.assert_awaited()
        pushed = {c.args[0]["symbol"] for c in self.send.await_args_list}
        self.assertEqual({"HBTRY", "OKTRY"}, pushed)
        # 2026-10-18: nabız istisnası artık `try_open_from_notification` İÇİNDE (burada sahte); teslim her ikisini
        # de kapıya verir, nabzın engellendiği test_auto_paper.AutoPaperPushGateTests'te sınanır.
        paper_syms = {c.args[0]["symbol"] for c in self.paper.await_args_list}
        self.assertEqual({"HBTRY", "OKTRY"}, paper_syms)
        llm_arg = self.llm.call_args.args[0]
        self.assertEqual(["OKTRY"], [n["symbol"] for n in llm_arg])  # LLM ikinci göz yalnız normal bildirim


class RunScanPassesHeartbeatPoolTests(unittest.TestCase):
    """`_run_scan`: eşik altı izleme listesi nabız havuzu olarak `_notify`'a verilir (hata: yalnız eşiği geçenler gidiyordu)."""

    def test_watchlist_rows_reach_notify_as_pool(self):
        watch_row = {"symbol": "WATCHTRY", "velocity_score": 300.0, "target_pct": 1.0, "price": 2.0,
                     "upside_rank": 5.0, "mode": "trend_devam", "passes": False, "horizon_minutes": 5}

        async def fake_detect(_filters, horizon_minutes=5, extra_symbols=None, kline_cache=None):
            return {"candidates": [], "watchlist": [dict(watch_row)] if horizon_minutes == 5 else [],
                    "warm": [], "horizon_minutes": horizon_minutes}

        notify = AsyncMock(return_value=[])
        settings = {"enabled": True, "min_score": 99.0, "min_score_explicit": True, "min_target_pct": 0.0}
        with patch.object(monitoring, "detect_velocity_candidates", new=AsyncMock(side_effect=fake_detect)), \
             patch.object(monitoring, "_journal_touch_rates", new=AsyncMock(return_value={})), \
             patch.object(monitoring, "get_user_notification_settings", new=AsyncMock(return_value=settings)), \
             patch.object(monitoring, "_check_pending_targets", new=AsyncMock()), \
             patch.object(monitoring, "_persist_runtime_state", new=AsyncMock()), \
             patch.object(monitoring, "_notify", new=notify):
            _run(monitoring._run_scan())
        notify.assert_awaited_once()
        pool = notify.await_args.kwargs.get("heartbeat_pool")
        self.assertIsNotNone(pool)
        self.assertIn("WATCHTRY", {r["symbol"] for r in pool})
