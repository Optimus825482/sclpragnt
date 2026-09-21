"""Yükseliş sinyali BAĞLANTISI (R3) — bildirim zarfı, kanıt, dialog, otonom.

KİLİT: `_build_rising_notification` zarfı, `auto_paper.try_open_from_notification`
ve `_send_push`'ın beklediği alanları TAŞIMAK ZORUNDA; aksi halde bildirim sessizce
gönderilemez ya da otonom giriş hiç denenmez.
"""
import contextlib
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                      # noqa: E402
from app.routers import monitoring                 # noqa: E402
from app import rising_signals as rs               # noqa: E402
from app import unified_signals                    # noqa: E402

SETTINGS = {"enabled": True, "min_score": 0.5, "min_target_pct": 0.5,
            "quiet_hours_start": None, "quiet_hours_end": None}


def _candidate(symbol="RISETRY", kind=rs.KIND_STRENGTH, score=80.0):
    return {
        "symbol": symbol,
        "kind": kind,
        "score": score,
        "early_score": int(score),
        "strength": 10.0,
        "green": 6,
        "tier": "GUCLU",
        "signals": {"dip": True, "proximity": 0.82, "gap_atr": 0.3, "transition": True,
                    "break5": True, "break15": None, "buy_dominant": True,
                    "approach": False, "m1": False, "pre_any": True},
        "target_pct": 2.0,
        "tf": "5m",
        "source": "macd_snapshot",
    }


def _early_candidate(symbol="RISETRY", score=80.0):
    """KIND_EARLY aday — push ÜRETMEZ, sadece kanıt + izleme listesi."""
    return {**_candidate(symbol=symbol, score=score), "kind": rs.KIND_EARLY}


class EnvelopeTests(unittest.TestCase):
    """Zarf sözleşmesi — push ve otonom girişin beklediği alanlar."""

    def test_envelope_has_push_fields(self):
        notif = monitoring._build_rising_notification(_candidate(), price=10.0)
        for field in ("message", "title", "url", "tag", "symbol", "score",
                      "target_pct", "price", "expected_price", "detected_at",
                      "horizon_minutes"):
            self.assertIn(field, notif, f"_send_push için eksik alan: {field}")
        self.assertEqual(10.2, round(notif["expected_price"], 6))
        self.assertEqual("rising-RISETRY", notif["tag"])

    def test_envelope_has_autonomous_fields(self):
        notif = monitoring._build_rising_notification(_candidate(), price=10.0)
        # `try_open_from_notification` notification_key + target_pct + price bekler.
        self.assertIn("notification_key", notif)
        self.assertTrue(str(notif["notification_key"]).startswith("rising-yukselis-RISETRY-"))
        self.assertEqual(2.0, notif["target_pct"])

    def test_label_differs_per_kind(self):
        early = monitoring._build_rising_notification(_candidate(kind=rs.KIND_EARLY), 10.0)
        strong = monitoring._build_rising_notification(_candidate(kind=rs.KIND_STRENGTH), 10.0)
        self.assertIn("ERKEN", early["title"])
        self.assertIn("YÜKSELİŞ", strong["title"])

    def test_message_includes_proximity_when_present(self):
        notif = monitoring._build_rising_notification(_candidate(), price=10.0)
        self.assertIn("yakınlık %82", notif["message"])

    def test_zero_price_does_not_crash(self):
        notif = monitoring._build_rising_notification(_candidate(), price=0.0)
        self.assertEqual(0.0, notif["expected_price"])


class RisingScanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        rs.reset_state_for_tests()
        self.addCleanup(rs.reset_state_for_tests)
        # Production default is False; tests verify notification wiring so force True.
        self._orig_notify = getattr(config, "RISING_NOTIFY_ENABLED", True)
        config.RISING_NOTIFY_ENABLED = True
        self.addCleanup(setattr, config, "RISING_NOTIFY_ENABLED", self._orig_notify)

    def _patches(self, candidates, price=10.0, record=None, deliver=None, cooldown=None):
        # Mock'lar yamalama bittikten SONRA da doğrulanabilsin diye self'e konur
        # (ExitStack kapanınca modül özniteliği gerçek fonksiyona döner).
        self.record_mock = AsyncMock(side_effect=record) if record else AsyncMock(return_value=501)
        self.deliver_mock = AsyncMock(side_effect=deliver) if deliver else AsyncMock(return_value=None)
        items = [
            patch.object(monitoring, "get_user_notification_settings",
                         AsyncMock(return_value=dict(SETTINGS))),
            patch.object(rs, "detect_rising_candidates", MagicMock(return_value=candidates)),
            patch.object(rs, "rising_is_stale", MagicMock(return_value=False)),
            patch.object(monitoring, "_ticker_price", MagicMock(return_value=price)),
            patch.object(monitoring.database, "record_rising_alert", self.record_mock),
            patch.object(monitoring, "_rising_deliver", self.deliver_mock),
        ]
        if cooldown is not None:
            items.append(patch.object(config, "RISING_COOLDOWN_SEC", cooldown))
        return items

    async def _scan(self, candidates, **kwargs):
        """Tek bir yamalama yığını içinde tarama koştur (sızıntı yok)."""
        with contextlib.ExitStack() as stack:
            for item in self._patches(candidates, **kwargs):
                stack.enter_context(item)
            return await monitoring._run_rising_scan()

    async def test_first_scan_records_evidence_but_arms_silently(self):
        """İlk gözlem = SESSİZ ARM: kanıt yazılır (panel/rapor), push/dialog YOK.

        Restart fırtınası koruması (MACD `first_observation` semantiği). Sinyalin
        KAYDEDİLMESİ şart — aksi halde canlı bir sinyal panelde hiç görünmezdi.
        """
        summary = await self._scan([_candidate()])
        self.assertEqual(1, summary["detected"])
        self.assertEqual(0, summary["notified"], "ilk gözlem bildirmemeli (sessiz arm)")
        self.record_mock.assert_awaited()
        self.deliver_mock.assert_not_awaited()

    async def test_rising_target_passes_through_learned_dynamic_target(self):
        """Madde 6: rising hedefi de dinamik/öğrenilmiş hedeften geçer.

        `panel_score=False` → bant YOK, taban 2.0. Öğrenilmiş hedef 1.2 (12 örnek)
        → harman 2.0*0.4 + 1.2*0.6 = 1.52. Maliyet tabanı (2026-09-19 net-kâr
        güvencesi): hedef en az SCALPING_NET_TARGET_PCT + spread + round_trip
        olacak — bu test config'i bilinçli olarak sade tutup tabanı kilitler.
        """
        state = {"symbol": "RISETRY", "target_pct": 1.2, "total_count": 12}
        with patch.object(monitoring.database, "get_symbol_target_state",
                          AsyncMock(return_value=state)), \
             patch.object(config, "SCALPING_NET_TARGET_PCT", 0.0), \
             patch.object(config, "DEFAULT_ESTIMATED_SPREAD_PCT", 0.0):
            await self._scan([_candidate(score=80.0)])
        recorded = self.record_mock.await_args.args[0]
        self.assertAlmostEqual(1.52, float(recorded["target_pct"]), places=3)

    async def test_rising_target_does_not_flex_panel_score_tiers(self):
        """§4/R3: `strength × 10` skoru PANEL bantlarına SOKULMAZ.

        Skor 80 olsa da (velocity panelinde bu 4.0 bant demekti) rising hedefi
        taban 2.0'da kalır — ölçek karışımı bilinçli olarak yapılmaz.
        """
        with patch.object(monitoring.database, "get_symbol_target_state",
                          AsyncMock(return_value=None)), \
             patch.object(config, "SCALPING_NET_TARGET_PCT", 0.0), \
             patch.object(config, "DEFAULT_ESTIMATED_SPREAD_PCT", 0.0):
            await self._scan([_candidate(score=80.0)])
        recorded = self.record_mock.await_args.args[0]
        self.assertAlmostEqual(2.0, float(recorded["target_pct"]), places=3)

    async def test_rising_target_untouched_below_minimum_samples(self):
        """LEARNED_TARGET_MIN_SAMPLES altında öğrenme rising hedefini DEĞİŞTİRMEZ."""
        state = {"symbol": "RISETRY", "target_pct": 1.2, "total_count": 2}
        with patch.object(monitoring.database, "get_symbol_target_state",
                          AsyncMock(return_value=state)), \
             patch.object(config, "SCALPING_NET_TARGET_PCT", 0.0), \
             patch.object(config, "DEFAULT_ESTIMATED_SPREAD_PCT", 0.0):
            await self._scan([_candidate(score=80.0)])
        recorded = self.record_mock.await_args.args[0]
        self.assertAlmostEqual(2.0, float(recorded["target_pct"]), places=3)

    async def test_rising_target_covers_costs_and_keeps_net_profit(self):
        """Kullanıcı kuralı (2026-09-19): hedef = net kâr + spread + komisyon.

        SCALPING_NET_TARGET_PCT=2.0, spread 0.65, round_trip %0.35 → taban
        hedef en az 2.0 + 0.65 + 0.35 = %3.00 olmalı (maliyet sonrası net %2.0).
        """
        with patch.object(monitoring.database, "get_symbol_target_state",
                          AsyncMock(return_value=None)):
            await self._scan([_candidate(score=80.0)])
        recorded = self.record_mock.await_args.args[0]
        expected_floor = round(config.SCALPING_NET_TARGET_PCT
                               + config.DEFAULT_ESTIMATED_SPREAD_PCT
                               + float(config.round_trip_cost()) * 100, 3)
        self.assertGreaterEqual(float(recorded["target_pct"]), expected_floor)

    async def test_new_precursor_after_arm_notifies(self):
        """Sessiz arm sonrası kümeye YENİ öncü eklenirse bildirim gider."""
        grown = _candidate()
        grown["signals"] = {**grown["signals"], "break15": True}
        deliver = AsyncMock(return_value=None)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(config, "RISING_COOLDOWN_SEC", 0))
            stack.enter_context(patch.object(monitoring, "get_user_notification_settings",
                                             AsyncMock(return_value=dict(SETTINGS))))
            stack.enter_context(patch.object(monitoring, "_ticker_price", MagicMock(return_value=10.0)))
            stack.enter_context(patch.object(monitoring.database, "record_rising_alert",
                                             AsyncMock(return_value=501)))
            stack.enter_context(patch.object(monitoring, "_rising_deliver", deliver))
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                            MagicMock(return_value=[_candidate()])))
            await monitoring._run_rising_scan()                  # sessiz arm
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=[grown])))
            summary = await monitoring._run_rising_scan()
        self.assertEqual(1, summary["notified"])
        deliver.assert_awaited()

    async def test_evidence_written_before_delivery(self):
        """Kanıt satırı bildirimden ÖNCE yazılmalı — her sinyal ölçülebilir olsun."""
        observed = {}
        async def record(item):
            observed["notified_flag"] = item.get("notified")
            return 777
        async def deliver(notified):
            observed["deliver_saw_alert_id"] = notified[0].get("alert_id")
        grown = _candidate()
        grown["signals"] = {**grown["signals"], "break15": True}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(config, "RISING_COOLDOWN_SEC", 0))
            stack.enter_context(patch.object(monitoring, "get_user_notification_settings",
                                             AsyncMock(return_value=dict(SETTINGS))))
            stack.enter_context(patch.object(monitoring, "_ticker_price", MagicMock(return_value=10.0)))
            stack.enter_context(patch.object(monitoring.database, "record_rising_alert",
                                             AsyncMock(side_effect=record)))
            stack.enter_context(patch.object(monitoring, "_rising_deliver",
                                             AsyncMock(side_effect=deliver)))
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=[_candidate()])))
            await monitoring._run_rising_scan()                  # arm
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=[grown])))
            summary = await monitoring._run_rising_scan()
        self.assertTrue(observed.get("notified_flag"), "bildirilen kayıt notified=TRUE olmalı")
        self.assertEqual(777, observed.get("deliver_saw_alert_id"))
        self.assertEqual(1, summary["notified"])

    async def test_no_candidates_produces_nothing(self):
        summary = await self._scan([])
        self.assertEqual(0, summary["notified"])
        self.deliver_mock.assert_not_awaited()

    async def test_missing_price_skips_signal(self):
        summary = await self._scan([_candidate()], price=None)
        self.assertEqual(0, summary["notified"])
        self.assertEqual(1, summary["skipped_price"])
        self.record_mock.assert_not_awaited()

    async def test_early_kind_records_evidence_but_no_push(self):
        """KIND_EARLY: kanıt kaydı yazılır ama push/deliver HİÇ ateşlenmez."""
        summary = await self._scan([_early_candidate()])
        self.assertEqual(0, summary["notified"],
                         "ERKEN sinyal push üretmemeli — öncelik izleme listesidir")
        self.record_mock.assert_awaited_once()  # kanıt yazıldı
        self.deliver_mock.assert_not_awaited()  # teslim olmadı

    async def test_early_kind_repeated_does_not_push_on_second_scan(self):
        """KIND_EARLY iki taramada da push üretmez (her koşulda sessiz)."""
        with contextlib.ExitStack() as stack:
            for item in self._patches([_early_candidate()]):
                stack.enter_context(item)
            await monitoring._run_rising_scan()
            # İkinci tarama için de aynı aday
            summary = await monitoring._run_rising_scan()
        self.assertEqual(0, summary["notified"])
        self.deliver_mock.assert_not_awaited()

    async def test_same_signal_key_is_not_recorded_again(self):
        """Aynı öncü kümesi sürüyorsa ne kayıt ne bildirim (tablo şişmez)."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(config, "RISING_COOLDOWN_SEC", 0))
            stack.enter_context(patch.object(monitoring, "get_user_notification_settings",
                                             AsyncMock(return_value=dict(SETTINGS))))
            stack.enter_context(patch.object(monitoring, "_ticker_price", MagicMock(return_value=10.0)))
            rec = AsyncMock(return_value=501)
            stack.enter_context(patch.object(monitoring.database, "record_rising_alert", rec))
            stack.enter_context(patch.object(monitoring, "_rising_deliver", AsyncMock(return_value=None)))
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=[_candidate()])))
            await monitoring._run_rising_scan()
            rec.reset_mock()
            second = await monitoring._run_rising_scan()
        self.assertEqual(0, second["notified"])
        rec.assert_not_awaited()

    async def test_max_per_scan_caps_notifications(self):
        many = [_candidate(symbol=f"R{i}TRY") for i in range(6)]
        grown = []
        for cand in many:
            item = dict(cand)
            item["signals"] = {**item["signals"], "break15": True}
            grown.append(item)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(config, "RISING_COOLDOWN_SEC", 0))
            stack.enter_context(patch.object(config, "RISING_MAX_PER_SCAN", 2))
            stack.enter_context(patch.object(monitoring, "get_user_notification_settings",
                                             AsyncMock(return_value=dict(SETTINGS))))
            stack.enter_context(patch.object(monitoring, "_ticker_price", MagicMock(return_value=10.0)))
            stack.enter_context(patch.object(monitoring.database, "record_rising_alert",
                                             AsyncMock(return_value=501)))
            stack.enter_context(patch.object(monitoring, "_rising_deliver", AsyncMock(return_value=None)))
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=many)))
            await monitoring._run_rising_scan()          # hepsi sessiz arm
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=grown)))
            summary = await monitoring._run_rising_scan()
        self.assertEqual(6, summary["detected"])
        self.assertEqual(2, summary["notified"], "tur başına bildirim tavanı uygulanmalı")

    async def test_disabled_sensor_returns_early(self):
        with patch.object(config, "RISING_SIGNALS_ENABLED", False):
            summary = await monitoring._run_rising_scan()
        self.assertEqual(0, summary["detected"])


class UnifiedCrossModeRisingTests(unittest.IsolatedAsyncioTestCase):
    """Çapraz bastırma MOD KİLİDİ (2026-09-17).

    `note_notified` kayıtları ≤30 dk bayat kalabilir; kullanıcı birleşik modu
    KAPATTIYSA bu bayat kayıtlar yükseliş push'unu engellememeli (mod değişimi
    anında 30 dk sessizleşme hatası). Birleşik mod AÇIKKEN bastırma çalışır ama
    kanıt kaydı (`rising_alerts`) her zaman yazılır — replay bunu kullanır.
    """

    def setUp(self):
        rs.reset_state_for_tests()
        self.addCleanup(rs.reset_state_for_tests)
        unified_signals._unified_notified_at.clear()
        self.addCleanup(unified_signals._unified_notified_at.clear)
        # Production default is False; notify tests need True.
        self._orig_notify = getattr(config, "RISING_NOTIFY_ENABLED", True)
        config.RISING_NOTIFY_ENABLED = True
        self.addCleanup(setattr, config, "RISING_NOTIFY_ENABLED", self._orig_notify)

    def _stack(self, settings, deliver, record=None):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(config, "RISING_COOLDOWN_SEC", 0))
        stack.enter_context(patch.object(monitoring, "get_user_notification_settings",
                                         AsyncMock(return_value=dict(settings))))
        stack.enter_context(patch.object(monitoring, "_ticker_price",
                                         MagicMock(return_value=10.0)))
        stack.enter_context(patch.object(monitoring.database, "record_rising_alert",
                                         record or AsyncMock(return_value=501)))
        stack.enter_context(patch.object(monitoring, "_rising_deliver", deliver))
        return stack

    async def _arm_then_grow(self, settings, deliver):
        grown = _candidate()
        grown["signals"] = {**grown["signals"], "break15": True}
        with self._stack(settings, deliver) as stack:
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=[_candidate()])))
            await monitoring._run_rising_scan()                  # sessiz arm
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=[grown])))
            return await monitoring._run_rising_scan()

    async def test_stale_unified_note_does_not_block_rising_in_legacy_mode(self):
        unified_signals.note_notified("RISETRY")   # birleşik moddan kalan bayat kayıt
        deliver = AsyncMock(return_value=None)
        summary = await self._arm_then_grow(SETTINGS, deliver)
        self.assertEqual(1, summary["notified"],
                         "legacy modda bayat birleşik kaydı push'u engellememeli")
        deliver.assert_awaited()

    async def test_unified_note_blocks_push_but_keeps_evidence(self):
        unified_signals.note_notified("RISETRY")   # radar/hızlı yol yeni bildirdi
        unified_settings = {**SETTINGS, "radar_unified_notify": True}
        deliver = AsyncMock(return_value=None)
        record = AsyncMock(return_value=501)
        grown = _candidate()
        grown["signals"] = {**grown["signals"], "break15": True}
        with self._stack(unified_settings, deliver, record) as stack:
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=[_candidate()])))
            await monitoring._run_rising_scan()                  # sessiz arm
            stack.enter_context(patch.object(rs, "detect_rising_candidates",
                                             MagicMock(return_value=[grown])))
            summary = await monitoring._run_rising_scan()
        self.assertEqual(0, summary["notified"],
                         "birleşik modda yakın bildirim push'u bastırmalı")
        deliver.assert_not_awaited()
        record.assert_awaited()
        self.assertFalse(record.await_args.args[0].get("notified"),
                         "bastırılan sinyalin kanıtı notified=FALSE ile yazılmalı")


class RisingDeliveryTests(unittest.IsolatedAsyncioTestCase):
    """TESLİMAT (legacy yol) kilitleri.

    NOT (2026-09-17): bu sınıf LEGACY teslimat yolunu (ayrı `rising_alert` WS
    kanalı, `rising-{sym}` tag) kilitler. Birleşik tek-bildirim modu artık
    VARSAYILAN (RADAR_UNIFIED_NOTIFY=true) olduğundan ayarlar mocked DEĞİL —
    bu yolu deterministik kılmak için `_radar_unified_enabled` burada AÇIKÇA
    kapatılır. Birleşik modun kilitleri `test_radar_unified_wiring.py`'dedir.
    """

    def setUp(self):
        monitoring._deferred_push.clear()
        self.addCleanup(monitoring._deferred_push.clear)
        unified_off = patch.object(monitoring, "_radar_unified_enabled",
                                   AsyncMock(return_value=False))
        unified_off.start()
        self.addCleanup(unified_off.stop)

    def _notif(self, score=80.0, quiet=False):
        notif = monitoring._build_rising_notification(_candidate(score=score), price=10.0)
        notif["alert_id"] = 900
        notif["quiet_hours"] = quiet
        return notif

    async def test_broadcasts_rising_alert_ws_type(self):
        broadcast = AsyncMock(return_value=None)
        with patch.dict("os.environ", {"VAPID_PRIVATE_KEY": "k"}), \
             patch.object(monitoring, "_send_push", AsyncMock(return_value=True)), \
             patch.object(monitoring, "ws_manager", MagicMock(broadcast=broadcast)), \
             patch.object(monitoring.database, "mark_rising_alert_notified", AsyncMock()), \
             patch.object(config, "RISING_AUTONOMOUS_ENABLED", False):
            await monitoring._rising_deliver([self._notif()])
        broadcast.assert_awaited()
        self.assertEqual("rising_alert", broadcast.await_args.args[0]["type"])

    async def test_quiet_hours_defers_push_not_dialog(self):
        """Sessiz saatte push ERTELENİR ama WS dialog yine yayınlanır."""
        broadcast = AsyncMock(return_value=None)
        push = AsyncMock(return_value=True)
        with patch.object(monitoring, "_send_push", push), \
             patch.object(monitoring, "ws_manager", MagicMock(broadcast=broadcast)), \
             patch.object(config, "RISING_AUTONOMOUS_ENABLED", False):
            await monitoring._rising_deliver([self._notif(quiet=True)])
        push.assert_not_awaited()
        self.assertEqual(1, len(monitoring._deferred_push))
        broadcast.assert_awaited()

    async def test_autonomous_entry_uses_existing_open_path(self):
        opened = AsyncMock(return_value={"status": "opened", "trade_id": 42, "symbol": "RISETRY"})
        link = AsyncMock(return_value=None)
        with patch.dict("os.environ", {"VAPID_PRIVATE_KEY": "k"}), \
             patch.object(monitoring, "_send_push", AsyncMock(return_value=True)), \
             patch.object(monitoring, "ws_manager", MagicMock(broadcast=AsyncMock(return_value=None))), \
             patch.object(monitoring.database, "mark_rising_alert_notified", AsyncMock()), \
             patch.object(monitoring.database, "mark_rising_alert_trade", link), \
             patch.object(config, "RISING_AUTONOMOUS_ENABLED", True), \
             patch.object(config, "RISING_AUTO_MIN_SCORE", 70), \
             patch("app.routers.auto_paper.try_open_from_notification", opened):
            await monitoring._rising_deliver([self._notif(score=80.0)])
        opened.assert_awaited()
        link.assert_awaited_with(900, 42)

    async def test_autonomous_skipped_below_score_threshold(self):
        opened = AsyncMock(return_value={"status": "opened", "trade_id": 42})
        with patch.dict("os.environ", {"VAPID_PRIVATE_KEY": "k"}), \
             patch.object(monitoring, "_send_push", AsyncMock(return_value=True)), \
             patch.object(monitoring, "ws_manager", MagicMock(broadcast=AsyncMock(return_value=None))), \
             patch.object(monitoring.database, "mark_rising_alert_notified", AsyncMock()), \
             patch.object(config, "RISING_AUTONOMOUS_ENABLED", True), \
             patch.object(config, "RISING_AUTO_MIN_SCORE", 90), \
             patch("app.routers.auto_paper.try_open_from_notification", opened):
            await monitoring._rising_deliver([self._notif(score=80.0)])
        opened.assert_not_awaited()

    async def test_autonomous_disabled_by_flag(self):
        opened = AsyncMock(return_value={"status": "opened", "trade_id": 42})
        with patch.dict("os.environ", {"VAPID_PRIVATE_KEY": "k"}), \
             patch.object(monitoring, "_send_push", AsyncMock(return_value=True)), \
             patch.object(monitoring, "ws_manager", MagicMock(broadcast=AsyncMock(return_value=None))), \
             patch.object(monitoring.database, "mark_rising_alert_notified", AsyncMock()), \
             patch.object(config, "RISING_AUTONOMOUS_ENABLED", False), \
             patch("app.routers.auto_paper.try_open_from_notification", opened):
            await monitoring._rising_deliver([self._notif(score=99.0)])
        opened.assert_not_awaited()


class StateExposureTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_endpoint_exposes_rising_block(self):
        """Panel sunucu verisini kullanır — state yanıtı `rising` içermeli."""
        with patch.object(monitoring, "get_user_notification_settings",
                          AsyncMock(return_value=dict(SETTINGS))), \
             patch.object(monitoring, "_rising_summary_safe",
                          MagicMock(return_value={"count": 2, "stale": False})):
            payload = await monitoring.monitoring_state()
        self.assertIn("rising", payload)
        self.assertEqual(2, payload["rising"]["count"])
        self.assertIn("rising_notified", payload)

    async def test_rising_summary_never_breaks_state(self):
        """Özet üretimi patlasa bile state yanıtı BOZULMAZ (None döner)."""
        with patch("app.rising_signals.rising_summary_payload",
                   MagicMock(side_effect=RuntimeError("boom"))):
            self.assertIsNone(monitoring._rising_summary_safe())


class RisingStatsTests(unittest.IsolatedAsyncioTestCase):
    """`get_rising_stats` — isabet oranı ÖLÇÜLMÜŞ satırlar üzerinden (uydurma yok)."""

    class _FakeConn:
        def __init__(self, rows):
            self.rows = rows
            self.statements = []

        def execute(self, sql, params=()):
            self.statements.append(sql)
            cur = MagicMock()
            cur.fetchall.return_value = self.rows if "SELECT" in sql.upper() else []
            cur.fetchone.return_value = None
            return cur

        def commit(self):
            pass

    async def _stats(self, rows, days=7.0):
        conn = self._FakeConn(rows)

        async def fake_run_db(op):
            return op(conn)

        from app import database
        with patch.object(database, "_run_db", fake_run_db):
            return await database.get_rising_stats(days=days)

    async def test_hit_rate_uses_only_measured_rows(self):
        rows = [
            # ölçülmüş + hedefe ulaşmış
            {"kind": "erken", "target_pct": 2.0, "mfe_pct": 2.5, "mae_pct": -1.0,
             "outcome_state": "filled", "created_at": 1.0, "peak_at": None},
            # ölçülmüş + hedefin ALTINDA
            {"kind": "erken", "target_pct": 2.0, "mfe_pct": 0.5, "mae_pct": -0.3,
             "outcome_state": "filled", "created_at": 2.0, "peak_at": None},
            # HENÜZ ÖLÇÜLMEMİŞ → orana GİRMEMELİ
            {"kind": "yukselis", "target_pct": 2.0, "mfe_pct": None, "mae_pct": None,
             "outcome_state": "pending", "created_at": 3.0, "peak_at": None},
        ]
        stats = await self._stats(rows)
        self.assertEqual(3, stats["total"])
        self.assertEqual(2, stats["measured"])
        self.assertEqual(1, stats["hits"])
        self.assertEqual(50.0, stats["hit_rate_pct"])
        self.assertEqual({"erken": 2, "yukselis": 1}, stats["by_kind"])
        self.assertEqual(1.5, stats["avg_mfe_pct"])

    async def test_no_measured_rows_yields_none_not_zero(self):
        """Ölçüm yoksa oran `None` — %0 göstermek 'hiç tutmadı' yanılsaması olurdu."""
        stats = await self._stats([
            {"kind": "erken", "target_pct": 2.0, "mfe_pct": None, "mae_pct": None,
             "outcome_state": "pending", "created_at": 1.0, "peak_at": None},
        ])
        self.assertEqual(1, stats["total"])
        self.assertEqual(0, stats["measured"])
        self.assertIsNone(stats["hit_rate_pct"])
        self.assertIsNone(stats["avg_mfe_pct"])

    async def test_empty_table_is_all_zero_and_none(self):
        stats = await self._stats([])
        self.assertEqual(0, stats["total"])
        self.assertIsNone(stats["hit_rate_pct"])


class RisingReportEndpointTests(unittest.IsolatedAsyncioTestCase):
    """`GET /api/reports/rising-signals` — Raporlar sekmesinin veri kaynağı."""

    async def test_envelope_shape(self):
        from app import database
        from app.routers import reports
        stats = {"total": 4, "measured": 3, "hits": 1, "hit_rate_pct": 33.33,
                 "by_kind": {"erken": 3, "yukselis": 1}}
        rows = [{"id": 1, "symbol": "RISETRY", "kind": "erken", "score": 80.0,
                 "proximity": 0.8, "target_pct": 2.0, "mfe_pct": 1.1,
                 "notified": True, "sent_via_push": True}]
        with patch.object(database, "get_rising_stats", AsyncMock(return_value=stats)), \
             patch.object(database, "list_rising_alerts", AsyncMock(return_value=rows)) as listed, \
             patch("app.rising_signals.rising_summary_payload", MagicMock(return_value={"count": 2})):
            payload = await reports.get_report_rising_signals(limit=10, kind="erken", days=3.0)
        self.assertTrue(payload["paper_only"])
        self.assertEqual(stats, payload["stats"])
        self.assertEqual("RISETRY", payload["signals"][0]["symbol"])
        self.assertEqual(2, payload["live"]["count"])
        # filtre DB'ye geçirilmeli (istemci değil sunucu süzer)
        self.assertEqual("erken", listed.await_args.kwargs.get("kind"))

    async def test_live_block_failure_does_not_break_report(self):
        """Canlı özet patlasa bile rapor (kanıt tablosu) dönmeli."""
        from app import database
        from app.routers import reports
        with patch.object(database, "get_rising_stats", AsyncMock(return_value={"total": 0})), \
             patch.object(database, "list_rising_alerts", AsyncMock(return_value=[])), \
             patch("app.rising_signals.rising_summary_payload",
                   MagicMock(side_effect=RuntimeError("boom"))):
            payload = await reports.get_report_rising_signals()
        self.assertIsNone(payload["live"])
        self.assertEqual([], payload["signals"])


if __name__ == "__main__":
    unittest.main()
