"""Denetim düzeltmeleri 2026-10-15 — döngü/REST dayanıklılığı (rapor bölüm 2 + 3).

Kilitlenen bulgular
-------------------
4  binance_public/_tr_public: 429/418'de thread uyutmak yerine paylaşımlı soğuma
   penceresi + `BinanceCooldownError` ile anında düşme; geçici hata uykusu ≤5 sn.
8  velocity: `_last_m5_close_ms` yalnız BAŞARILI taramadan sonra ilerler.
9  market_data: WS temiz kapanışında da asgari bekleme (reconnect fırtınası yok).
10 market_data: grup başına tek `repair_history_gaps` görevi (dedup).
11 monitoring: günlük momentum günü başarıdan sonra işaretlenir; `>=` penceresi.
12 runtime: pozisyon yönetimi ardışık hata sayacı + eşikte tek alarm.
13 monitoring: LLM ikinci-göz eşzamanlılık tavanı (kuyruksuz atlama).
3  velocity manual-scan: `require_admin` + tek kilit (409).
"""
import asyncio
import inspect
import json
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from app import binance_public as gpub  # noqa: E402
from app import binance_tr_public as trpub  # noqa: E402
from app.market_data import MarketData  # noqa: E402


class _Resp:
    def __init__(self, status, headers=None, data=b"{}"):
        self.status = status
        self.headers = headers or {}
        self.data = data


class _FakeClock:
    """time ikamesi: uyku saati ilerletir, uyku listesini tutar."""

    def __init__(self, start=10_000.0):
        self.now = start
        self.sleeps: list[float] = []

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)


# ---------------------------------------------------------------- madde 4 (Global)
class GlobalCooldownShortCircuitTests(unittest.TestCase):
    def setUp(self):
        self._pool = gpub._HTTP_POOL
        self._time = gpub.time
        self.clock = _FakeClock()
        gpub.time = self.clock
        gpub.reset_cooldown()

    def tearDown(self):
        gpub._HTTP_POOL = self._pool
        gpub.time = self._time
        gpub.reset_cooldown()

    def _pool_returning(self, responses):
        calls = {"n": 0}

        class _Pool:
            def request(self, method, url, headers=None):
                calls["n"] += 1
                idx = min(calls["n"], len(responses)) - 1
                return responses[idx]

        gpub._HTTP_POOL = _Pool()
        return calls

    def test_429_opens_window_and_raises_without_sleeping(self):
        calls = self._pool_returning([_Resp(429, {"Retry-After": "30"})])
        with self.assertRaises(gpub.BinanceCooldownError) as ctx:
            gpub._get_json("/api/v3/klines", {"symbol": "BTCUSDT"})
        self.assertEqual(calls["n"], 1, "429 sonrası yeniden deneme olmamalı")
        self.assertEqual(self.clock.sleeps, [], "thread 429'da uyutulmamalı")
        self.assertAlmostEqual(ctx.exception.remaining, 30.0, places=3)
        self.assertAlmostEqual(gpub._cooldown_remaining(), 30.0, places=3)
        # Pencere açıkken yeni istek havuza HİÇ dokunmadan düşer.
        with self.assertRaises(gpub.BinanceCooldownError):
            gpub._get_json("/api/v3/ticker/price", {})
        self.assertEqual(calls["n"], 1)
        self.assertEqual(self.clock.sleeps, [])
        # Mevcut sözleşme: RuntimeError alt sınıfı.
        self.assertIsInstance(ctx.exception, RuntimeError)

    def test_window_expiry_lets_requests_through(self):
        calls = self._pool_returning([
            _Resp(429, {"Retry-After": "10"}),
            _Resp(200, {}, json.dumps({"ok": 1}).encode()),
        ])
        with self.assertRaises(gpub.BinanceCooldownError):
            gpub._get_json("/api/v3/klines", {})
        self.clock.now += 10.5
        self.assertEqual(gpub._get_json("/api/v3/klines", {}), {"ok": 1})
        self.assertEqual(calls["n"], 2)

    def test_418_window_is_capped(self):
        self._pool_returning([_Resp(418, {"Retry-After": "3600"})])
        with self.assertRaises(gpub.BinanceCooldownError) as ctx:
            gpub._get_json("/api/v3/klines", {})
        self.assertEqual(ctx.exception.reason, "418")
        self.assertLessEqual(gpub._cooldown_remaining(), gpub.REST_COOLDOWN_418_MAX_SEC + 1e-6)
        self.assertEqual(self.clock.sleeps, [])

    def test_5xx_retry_sleep_is_short_even_with_long_retry_after(self):
        calls = self._pool_returning([
            _Resp(503, {"Retry-After": "120"}),
            _Resp(200, {}, json.dumps({"ok": 2}).encode()),
        ])
        self.assertEqual(gpub._get_json("/api/v3/klines", {}), {"ok": 2})
        self.assertEqual(calls["n"], 2)
        self.assertEqual(len(self.clock.sleeps), 1)
        self.assertLessEqual(self.clock.sleeps[0], gpub.REST_TRANSIENT_SLEEP_MAX_SEC + 1e-6)
        self.assertEqual(gpub._cooldown_remaining(), 0.0, "5xx pencere açmamalı")


# ---------------------------------------------------------------- madde 4 (TR)
class TRCooldownShortCircuitTests(unittest.TestCase):
    def setUp(self):
        self._pool = trpub._HTTP_POOL
        self._time = trpub.time
        self._cooldown = trpub._cooldown_until
        self.clock = _FakeClock()
        trpub.time = self.clock
        trpub._cooldown_until = 0.0

    def tearDown(self):
        trpub._HTTP_POOL = self._pool
        trpub.time = self._time
        trpub._cooldown_until = self._cooldown

    def test_fresh_request_fails_fast_while_window_open(self):
        calls = {"n": 0}

        class _Pool:
            def request(self, method, url, retries=False):
                calls["n"] += 1
                return _Resp(200, {}, b"{}")

        trpub._HTTP_POOL = _Pool()
        trpub._note_global_cooldown(20.0)
        with self.assertRaises(trpub.BinanceCooldownError) as ctx:
            trpub._get_json("/api/v3/ticker/price", {})
        self.assertEqual(calls["n"], 0, "pencere açıkken havuza dokunulmamalı")
        self.assertEqual(self.clock.sleeps, [], "thread pencereyi beklememeli")
        self.assertIsInstance(ctx.exception, RuntimeError)

    def test_429_inline_sleep_is_capped(self):
        calls = {"n": 0}

        class _Pool:
            def request(self, method, url, retries=False):
                calls["n"] += 1
                if calls["n"] == 1:
                    return _Resp(429, {"Retry-After": "200"})
                return _Resp(200, {}, json.dumps({"ok": 3}).encode())

        trpub._HTTP_POOL = _Pool()
        self.assertEqual(trpub._get_json("/api/v3/ticker/price", {}), {"ok": 3})
        # İlk uyku kısa (≤5 sn); kalan pencere (≤60 sn) `_wait_global_cooldown`
        # dilimleriyle geçer — eskiden tek 200 sn'lik uyku vardı.
        self.assertLessEqual(self.clock.sleeps[0], trpub.REST_TRANSIENT_SLEEP_MAX_SEC + 1e-6)
        self.assertTrue(all(s <= 5.0 + 1e-6 for s in self.clock.sleeps))
        self.assertLessEqual(sum(self.clock.sleeps), trpub.GLOBAL_COOLDOWN_MAX_SEC + 5.0 + 1e-6)

    def test_repeated_429_inside_window_raises_instead_of_looping(self):
        calls = {"n": 0}

        class _Pool:
            def request(self, method, url, retries=False):
                calls["n"] += 1
                return _Resp(429, {"Retry-After": "30"})

        trpub._HTTP_POOL = _Pool()
        with self.assertRaises(trpub.BinanceCooldownError):
            trpub._get_json("/api/v3/ticker/price", {})
        self.assertEqual(calls["n"], 2, "pencere beklendi, yine 429 → üçüncü deneme yok")


# ---------------------------------------------------------------- madde 8
class VelocityM5CursorTests(unittest.TestCase):
    def test_cursor_advances_only_after_successful_scan(self):
        from app.routers import velocity

        src = inspect.getsource(velocity.autonomous_velocity_loop)
        scan_idx = src.index("scan15 = await detect_velocity_candidates({}, horizon_minutes=15)")
        cursor_idx = src.index("_last_m5_close_ms = latest_close_ms")
        self.assertGreater(cursor_idx, scan_idx,
                           "M5 imleci taramadan ÖNCE ilerlerse hata veren mum kalıcı atlanır (madde 8)")


# ---------------------------------------------------------------- madde 9 / 10
class WsCleanCloseBackoffTests(unittest.IsolatedAsyncioTestCase):
    def test_reconnect_delay_has_a_floor(self):
        for attempt in (0, 1, 2, 3, 6):
            d = MarketData._ws_reconnect_delay_sec(attempt)
            self.assertGreaterEqual(d, 1.0, f"attempt={attempt}: temiz kapanışta asgari 1 sn bekleme")
            self.assertLessEqual(d, 31.0)

    def test_run_ws_group_sleeps_after_clean_close(self):
        src = inspect.getsource(MarketData._run_ws_group)
        self.assertIn("_ws_reconnect_delay_sec", src,
                      "temiz kapanış dalı backoff'suz anında yeniden bağlanmamalı (madde 9)")

    async def test_schedule_repair_dedups_per_group(self):
        m = MarketData(["BTCTRY"])
        gate = asyncio.Event()
        runs = {"n": 0}

        async def fake_repair(symbols=None, timeframes=None):
            runs["n"] += 1
            await gate.wait()
            return {"requested": 0}

        with patch.object(m, "repair_history_gaps", fake_repair):
            t1 = m._schedule_repair(("btctry",), ("1m",), 1, 7)
            t2 = m._schedule_repair(("btctry",), ("1m",), 1, 7)
            t_other = m._schedule_repair(("ethtry",), ("1m",), 1, 8)
            await asyncio.sleep(0)
            self.assertIs(t1, t2, "aynı grup için çalışan onarım varken yenisi açılmamalı")
            self.assertIsNot(t1, t_other, "farklı gruplar bağımsız")
            self.assertEqual(runs["n"], 2)
            gate.set()
            await asyncio.wait_for(asyncio.gather(t1, t_other), timeout=1.0)
            await asyncio.sleep(0)
            self.assertNotIn(7, m._repair_tasks)
            t3 = m._schedule_repair(("btctry",), ("1m",), 1, 7)
            self.assertIsNot(t3, t1, "biten görevden sonra yeni onarım açılabilmeli")
            await asyncio.wait_for(t3, timeout=1.0)


# ---------------------------------------------------------------- madde 11 / 12 / 13 (monitoring)
class MonitoringLoopFixTests(unittest.IsolatedAsyncioTestCase):
    def test_daily_momentum_marks_day_after_success_and_uses_wide_window(self):
        from app.routers import monitoring

        src = inspect.getsource(monitoring.daily_momentum_loop)
        scan_idx = src.index("n = await _daily_momentum_scan_once()")
        mark_idx = src.index('_monitoring_state["daily_momentum_last_day"] = today_key')
        self.assertGreater(mark_idx, scan_idx, "gün işareti taramadan SONRA konmalı (madde 11)")
        self.assertIn("lt.hour > config.DAILY_MOMENTUM_SCAN_HOUR", src,
                      "kaçırılan tam saat aynı gün sonra da tetiklenmeli (madde 11)")

    def test_scan_loop_logs_traceback_and_alerts_on_threshold(self):
        from app.routers import monitoring

        src = inspect.getsource(monitoring.monitoring_background_loop)
        self.assertIn("monitoring loop turu başarısız (ardışık %d)", src)
        self.assertIn("SCAN_CONSECUTIVE_ERROR_ALERT_THRESHOLD", src)
        self.assertIn('_alert_system_event("MONITORING_LOOP_FAILING"', src)

    async def test_llm_second_eye_is_bounded_and_skips_when_full(self):
        from app.routers import monitoring

        gate = asyncio.Event()
        started = {"n": 0}

        async def fake_task(notif):
            started["n"] += 1
            await gate.wait()

        notifs = [{"id": i, "symbol": f"S{i}TRY"} for i in range(5)]
        monitoring._llm_second_eye_inflight = 0
        with patch.object(monitoring, "LLM_SECOND_EYE_MAX_CONCURRENCY", 2), \
             patch.object(monitoring.llm_second_eye, "eligible", return_value=True), \
             patch.object(monitoring, "_llm_second_eye_task", fake_task):
            monitoring._maybe_llm_second_eye(notifs)
            self.assertEqual(monitoring._llm_second_eye_inflight, 2, "tavan 2 iken 5 bildirim kuyruklanmamalı")
            await asyncio.sleep(0)
            self.assertEqual(started["n"], 2)
            gate.set()
            await asyncio.sleep(0.05)
            self.assertEqual(monitoring._llm_second_eye_inflight, 0, "biten görevler sayacı düşürmeli")
            # Tavan boşaldı → yeni bildirim yeniden kabul edilir.
            monitoring._maybe_llm_second_eye([{"id": 9, "symbol": "ZTRY"}])
            self.assertEqual(monitoring._llm_second_eye_inflight, 1)
            await asyncio.sleep(0.05)
        monitoring._llm_second_eye_inflight = 0

    async def test_llm_second_eye_skip_keeps_deferred_entry_fail_open(self):
        from app.routers import monitoring

        gate = asyncio.Event()

        async def fake_task(notif):
            await gate.wait()

        fallback = AsyncMock(return_value=None)
        monitoring._llm_second_eye_inflight = 0
        with patch.object(monitoring, "LLM_SECOND_EYE_MAX_CONCURRENCY", 1), \
             patch.object(monitoring.llm_second_eye, "eligible", return_value=True), \
             patch.object(monitoring, "_llm_second_eye_task", fake_task), \
             patch.object(monitoring, "_post_llm_second_eye_entry", fallback):
            monitoring._maybe_llm_second_eye([
                {"id": 1, "symbol": "ATRY", "_llm_entry_deferred": True},
                {"id": 2, "symbol": "BTRY", "_llm_entry_deferred": True},
            ])
            await asyncio.sleep(0.05)
            fallback.assert_awaited_once()
            self.assertEqual(fallback.await_args.args[0]["symbol"], "BTRY")
            gate.set()
            await asyncio.sleep(0.05)
        monitoring._llm_second_eye_inflight = 0


# ---------------------------------------------------------------- madde 12 (runtime)
class PositionManageErrorCounterTests(unittest.TestCase):
    def test_counter_alerts_once_at_threshold_and_resets(self):
        from app.routers import runtime

        runtime._position_manage_errors.clear()
        alert = MagicMock()
        with patch.object(runtime, "_alert_system_event", alert), \
             patch.object(runtime.logger, "warning") as warn, \
             patch.object(runtime.logger, "error") as err:
            for _ in range(runtime.POSITION_MANAGE_ERROR_ALERT_THRESHOLD + 20):
                runtime._note_position_manage_error("BTCTRY", RuntimeError("boom"))
        self.assertEqual(alert.call_count, 1, "eşikte TEK alarm")
        self.assertEqual(alert.call_args.args[0], "POSITION_MANAGE_FAILING")
        self.assertEqual(alert.call_args.kwargs.get("symbol"), "BTCTRY")
        self.assertEqual(err.call_count, 1)
        # Eşik altı uyarılar traceback taşır.
        self.assertTrue(all(c.kwargs.get("exc_info") for c in
                            warn.call_args_list[:runtime.POSITION_MANAGE_ERROR_ALERT_THRESHOLD - 1]))
        # Eşik sonrası log seli yok (25 hata → en fazla 2 seyrek satır).
        self.assertLessEqual(warn.call_count, runtime.POSITION_MANAGE_ERROR_ALERT_THRESHOLD - 1 + 3)
        runtime._position_manage_errors.pop("BTCTRY", None)
        self.assertNotIn("BTCTRY", runtime._position_manage_errors)

    def test_strategy_loop_no_longer_prints(self):
        from app.routers import runtime

        src = inspect.getsource(runtime.strategy_loop)
        self.assertNotIn("print(f\"[Strategy] {sym} pozisyon yönetimi hatası", src)
        self.assertIn("_note_position_manage_error(sym, exc)", src)
        self.assertIn("_position_manage_errors.pop(sym, None)", src)


# ---------------------------------------------------------------- bölüm 3: manual-scan
class ManualScanGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_scan_requires_admin_before_scanning(self):
        from app import api_common
        from app.routers import velocity

        def deny(_request):
            raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")

        scan = AsyncMock()
        with patch.object(api_common, "require_admin", deny), \
             patch.object(velocity, "detect_velocity_candidates", scan):
            with self.assertRaises(HTTPException) as ctx:
                await velocity.manual_velocity_scan(MagicMock())
        self.assertEqual(ctx.exception.status_code, 401)
        scan.assert_not_awaited()

    async def test_concurrent_manual_scans_do_not_overlap(self):
        from app import api_common
        from app.routers import velocity

        gate = asyncio.Event()

        async def slow_body():
            await gate.wait()
            return {"ok": True}

        with patch.object(api_common, "require_admin", lambda _r: {"role": "admin"}), \
             patch.object(velocity, "_manual_velocity_scan_body", slow_body):
            first = asyncio.create_task(velocity.manual_velocity_scan(MagicMock()))
            await asyncio.sleep(0)
            with self.assertRaises(HTTPException) as ctx:
                await velocity.manual_velocity_scan(MagicMock())
            self.assertEqual(ctx.exception.status_code, 409)
            gate.set()
            self.assertEqual(await asyncio.wait_for(first, timeout=1.0), {"ok": True})
            self.assertFalse(velocity._manual_scan_lock.locked())


if __name__ == "__main__":
    unittest.main()
