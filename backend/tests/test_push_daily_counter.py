"""Sembol başına GÜNLÜK push sayacı (2026-10-24): "bu coin için bugün N. bildirim".

Kilitler:
  * sayaç sembol + Europe/Istanbul günü başına artar; semboller birbirinden bağımsız
  * gün dönünce (00:00 İstanbul) sıfırlanır
  * payload başlığı `#N · ` öneki (en başta) ve `daily_count` alanı alır
  * sembolsüz / "ALERT" / hedefli yönetici push'u sayaç almaz
  * sayaç arızası push'u durdurmaz (sayaçsız gider)
  * yeniden denemede (ertelenen kuyruk) atanmış sayaç yeniden kullanılır
"""
import asyncio
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app import alerting, database, push_daily_counter
from app.config import config
from app.routers import monitoring


class _MemoryCounter:
    """`database.bump_push_daily_count` yerine bellek içi upsert (aynı sözleşme: yeni değeri döndür)."""

    def __init__(self):
        self.rows: dict[tuple[str, str], int] = {}
        self.calls: list[tuple[str, str]] = []

    async def release(self, symbol, day_key):
        self.rows[(symbol, day_key)] = max(self.rows.get((symbol, day_key), 0) - 1, 0)
        return self.rows[(symbol, day_key)]

    async def __call__(self, symbol, day_key, now=None):
        self.calls.append((symbol, day_key))
        self.rows[(symbol, day_key)] = self.rows.get((symbol, day_key), 0) + 1
        return self.rows[(symbol, day_key)]


class DayKeyTests(unittest.TestCase):
    def test_day_key_is_istanbul_calendar_day(self):
        # 2026-10-24 22:30 UTC = 2026-10-25 01:30 İstanbul → gün İstanbul'a göre dönmüş olmalı
        ts = datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc).timestamp()
        self.assertEqual("2026-10-25", push_daily_counter.day_key(ts))

    def test_normalize_symbol(self):
        self.assertEqual("BTCTRY", push_daily_counter.normalize_symbol(" btc_try "))
        self.assertIsNone(push_daily_counter.normalize_symbol(""))
        self.assertIsNone(push_daily_counter.normalize_symbol(None))
        self.assertIsNone(push_daily_counter.normalize_symbol("ALERT"))

    def test_counter_label_turkish(self):
        self.assertEqual("#3", push_daily_counter.counter_label(3))


class NextCountTests(unittest.IsolatedAsyncioTestCase):
    async def test_increments_per_symbol_and_symbols_are_independent(self):
        mem = _MemoryCounter()
        with patch.object(database, "bump_push_daily_count", new=mem), \
             patch.object(push_daily_counter, "day_key", new=lambda now=None: "2026-10-24"):
            self.assertEqual(1, await push_daily_counter.next_count("BTCTRY"))
            self.assertEqual(2, await push_daily_counter.next_count("BTCTRY"))
            self.assertEqual(1, await push_daily_counter.next_count("ETHTRY"))
            self.assertEqual(3, await push_daily_counter.next_count("btc_try"))  # normalize → aynı anahtar
        self.assertEqual({("BTCTRY", "2026-10-24"): 3, ("ETHTRY", "2026-10-24"): 1}, mem.rows)

    async def test_day_rollover_resets(self):
        mem = _MemoryCounter()
        day = {"v": "2026-10-24"}
        with patch.object(database, "bump_push_daily_count", new=mem), \
             patch.object(push_daily_counter, "day_key", new=lambda now=None: day["v"]):
            self.assertEqual(1, await push_daily_counter.next_count("BTCTRY"))
            self.assertEqual(2, await push_daily_counter.next_count("BTCTRY"))
            day["v"] = "2026-10-25"
            self.assertEqual(1, await push_daily_counter.next_count("BTCTRY"))

    async def test_non_coin_symbol_is_not_counted(self):
        mem = _MemoryCounter()
        with patch.object(database, "bump_push_daily_count", new=mem):
            self.assertIsNone(await push_daily_counter.next_count("ALERT"))
            self.assertIsNone(await push_daily_counter.next_count(None))
        self.assertEqual([], mem.calls)


class BumpSqlTests(unittest.TestCase):
    """`database.bump_push_daily_count` tek atomik upsert + RETURNING kullanmalı."""

    def test_upsert_returning_and_prune(self):
        captured = {"sqls": [], "params": []}

        class _Cursor:
            def fetchone(self):
                return (4,)

        class _Conn:
            def execute(self, sql, params=()):
                captured["sqls"].append(" ".join(str(sql).split()))
                captured["params"].append(tuple(params))
                return _Cursor()

            def commit(self):
                captured["commit"] = True

        async def _fake_run_db(operation):
            return operation(_Conn())

        with patch.object(database, "_run_db", _fake_run_db):
            value = asyncio.run(database.bump_push_daily_count("BTCTRY", "2026-10-24", now=1000.0))
        self.assertEqual(4, value)
        upsert = captured["sqls"][0]
        self.assertIn("INSERT INTO push_daily_counter", upsert)
        self.assertIn("ON CONFLICT(symbol, day_key) DO UPDATE SET count = push_daily_counter.count + 1", upsert)
        self.assertTrue(upsert.endswith("RETURNING count"))
        self.assertEqual(("BTCTRY", "2026-10-24", 1000.0), captured["params"][0])
        self.assertTrue(any("DELETE FROM push_daily_counter" in s for s in captured["sqls"]))
        self.assertTrue(captured.get("commit"))


def _subs(n=1):
    async def fake_list(usernames=None):
        return [{"endpoint": f"https://push.example/{i}"} for i in range(n)]
    return fake_list


class DeliverWebPushCounterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mem = _MemoryCounter()
        self.webpush = MagicMock()
        patches = [
            patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "test-key"}),
            patch("app.database.list_push_subscriptions", new=_subs(1)),
            patch("pywebpush.webpush", self.webpush),
            patch.object(database, "bump_push_daily_count", new=self.mem),
            patch.object(database, "release_push_daily_count", new=self.mem.release),
            patch.object(push_daily_counter, "day_key", new=lambda now=None: "2026-10-24"),
            # Bu sınıf SAYAÇ davranışını sınar; günde-1-push kapısı kapalı (kapı: OnePerSymbolPerDayTests).
            patch.object(config, "PUSH_ONE_PER_SYMBOL_PER_DAY", False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _payload(self, idx=-1):
        return json.loads(self.webpush.call_args_list[idx].kwargs["data"])

    async def test_symbol_from_extra_gets_title_suffix_and_daily_count(self):
        for expected in (1, 2):
            result = await alerting.deliver_web_push(
                "BTCTRY radar", title="🚀 BTCTRY radar", url="/charts?symbol=BTCTRY",
                tag="radar-BTCTRY", extra={"symbol": "BTCTRY", "horizon_minutes": 10})
            self.assertTrue(result["ok"])
            self.assertEqual(expected, result["daily_count"])
            payload = self._payload()
            self.assertEqual(f"#{expected} · 🚀 BTCTRY radar", payload["title"])
            self.assertEqual(expected, payload["daily_count"])
            self.assertEqual("BTCTRY radar", payload["body"])  # gövde değişmez

    async def test_symbol_kwarg_wins_and_timeframe_source_do_not_matter(self):
        # Aynı coin: farklı tag/kaynak/zaman dilimi tek sayaçta birikir.
        await alerting.deliver_web_push("a", tag="ma-buy-ETHTRY-1m", symbol="ETHTRY", extra={"source": "ma_buy"})
        await alerting.deliver_web_push("b", tag="radar-ETHTRY", extra={"symbol": "ETHTRY", "source": "monitoring"})
        await alerting.deliver_web_push("c", tag="macd-jump-ETHTRY", extra={"symbol": "eth_try", "source": "macd_monitor"})
        self.assertEqual(3, self._payload()["daily_count"])
        self.assertEqual({("ETHTRY", "2026-10-24"): 3}, self.mem.rows)

    async def test_no_counter_without_symbol_or_for_alert_or_admin_push(self):
        await alerting.deliver_web_push("Test bildirimi", title="Scalper Agent · TEST", tag="scalper-test",
                                        extra={"source": "settings_test"})
        await alerting.deliver_web_push("alarm", tag="alert-1", extra={"symbol": "ALERT"})
        await alerting.deliver_web_push("admin BTCTRY", tag="admin-trade",
                                        extra={"source": "admin_real_buy", "symbol": "BTC_TRY"}, usernames=["ali"])
        self.assertEqual(3, self.webpush.call_count)
        for i in range(3):
            payload = self._payload(i)
            self.assertNotIn("daily_count", payload)
            self.assertNotIn("bildirim", payload["title"])
        self.assertEqual([], self.mem.calls)

    async def test_counter_failure_still_sends_without_counter(self):
        boom = AsyncMock(side_effect=RuntimeError("db down"))
        with patch.object(database, "bump_push_daily_count", new=boom):
            result = await alerting.deliver_web_push("BTCTRY radar", title="Radar", tag="radar-BTCTRY",
                                                     extra={"symbol": "BTCTRY"})
        self.assertTrue(result["ok"])
        self.assertNotIn("daily_count", result)
        payload = self._payload()
        self.assertEqual("Radar", payload["title"])
        self.assertNotIn("daily_count", payload)

    async def test_preassigned_daily_count_is_reused_not_incremented(self):
        # Yeniden deneme: zarf daha önce atanmış sayacı taşır → sayaç bir daha artmaz.
        result = await alerting.deliver_web_push("BTCTRY radar", title="Radar", tag="radar-BTCTRY",
                                                 extra={"symbol": "BTCTRY", "daily_count": 5})
        self.assertEqual(5, result["daily_count"])
        self.assertEqual("#5 · Radar", self._payload()["title"])
        self.assertEqual([], self.mem.calls)

    async def test_no_subscribers_does_not_count(self):
        with patch("app.database.list_push_subscriptions", new=_subs(0)):
            result = await alerting.deliver_web_push("x", tag="radar-BTCTRY", extra={"symbol": "BTCTRY"})
        self.assertFalse(result["ok"])
        self.assertEqual([], self.mem.calls)


class OnePerSymbolPerDayTests(unittest.IsolatedAsyncioTestCase):
    """2026-10-26: sembol başına günde en fazla 1 push (PUSH_ONE_PER_SYMBOL_PER_DAY, varsayılan açık)."""

    _payload = DeliverWebPushCounterTests._payload

    def setUp(self):
        DeliverWebPushCounterTests.setUp(self)  # aynı sahte sayaç / webpush / abonelik düzeneği
        p = patch.object(config, "PUSH_ONE_PER_SYMBOL_PER_DAY", True)
        p.start()
        self.addCleanup(p.stop)

    async def test_first_sends_second_same_symbol_skipped(self):
        first = await alerting.deliver_web_push("a", tag="radar-BTCTRY", extra={"symbol": "BTCTRY"})
        self.assertTrue(first["ok"])
        self.assertEqual(1, first["daily_count"])
        second = await alerting.deliver_web_push("b", tag="ma-buy-BTCTRY", symbol="BTCTRY", extra={"source": "ma_buy"})
        self.assertFalse(second["ok"])
        self.assertTrue(second["skipped"])
        self.assertEqual("daily_symbol_limit", second["reason"])
        self.assertEqual("BTCTRY", second["symbol"])
        self.assertNotIn("daily_count", second)
        self.assertEqual(1, self.webpush.call_count)

    async def test_different_symbol_sends(self):
        await alerting.deliver_web_push("a", tag="r-BTCTRY", extra={"symbol": "BTCTRY"})
        other = await alerting.deliver_web_push("b", tag="r-ETHTRY", extra={"symbol": "ETHTRY"})
        self.assertTrue(other["ok"])
        self.assertEqual(2, self.webpush.call_count)

    async def test_retry_with_count_one_still_sends_but_legacy_higher_is_blocked(self):
        ok = await alerting.deliver_web_push("a", tag="r-BTCTRY", extra={"symbol": "BTCTRY", "daily_count": 1})
        self.assertTrue(ok["ok"])
        blocked = await alerting.deliver_web_push("a", tag="r-BTCTRY", extra={"symbol": "BTCTRY", "daily_count": 3})
        self.assertEqual("daily_symbol_limit", blocked["reason"])
        self.assertEqual(1, self.webpush.call_count)

    async def test_usernames_targeted_and_symbolless_unaffected(self):
        for _ in range(2):
            r = await alerting.deliver_web_push("admin", tag="admin-trade", usernames=["ali"],
                                                extra={"source": "admin_real_buy", "symbol": "BTC_TRY"})
            self.assertTrue(r["ok"])
            r = await alerting.deliver_web_push("t", tag="scalper-test", extra={"source": "settings_test"})
            self.assertTrue(r["ok"])
        self.assertEqual(4, self.webpush.call_count)

    async def test_flag_off_restores_old_behavior(self):
        with patch.object(config, "PUSH_ONE_PER_SYMBOL_PER_DAY", False):
            await alerting.deliver_web_push("a", tag="r-BTCTRY", extra={"symbol": "BTCTRY"})
            second = await alerting.deliver_web_push("b", tag="r-BTCTRY", extra={"symbol": "BTCTRY"})
        self.assertTrue(second["ok"])
        self.assertEqual("#2 · Scalper Agent alarmı", self._payload()["title"])


class ReleaseAndFailOpenTests(unittest.IsolatedAsyncioTestCase):
    """Teslim edilemeyen push sayacı tüketmez; sayaç arızası ve abonesizlik kapıyı etkilemez."""

    _payload = DeliverWebPushCounterTests._payload

    def setUp(self):
        OnePerSymbolPerDayTests.setUp(self)

    async def test_failed_first_delivery_releases_count(self):
        self.webpush.side_effect = RuntimeError("push servisi çöktü")
        if True:
            failed = await alerting.deliver_web_push("a", tag="r-BTCTRY", extra={"symbol": "BTCTRY"})
            self.assertFalse(failed["ok"])
            self.assertNotIn("daily_count", failed)
            self.assertEqual(0, self.mem.rows[("BTCTRY", "2026-10-24")])
            self.webpush.side_effect = None
            nxt = await alerting.deliver_web_push("b", tag="r-BTCTRY", extra={"symbol": "BTCTRY"})
        self.assertTrue(nxt["ok"])
        self.assertEqual("#1 · Scalper Agent alarmı", self._payload()["title"])

    async def test_release_failure_is_swallowed(self):
        self.webpush.side_effect = RuntimeError("x")
        boom = AsyncMock(side_effect=RuntimeError("db down"))
        with patch.object(database, "release_push_daily_count", new=boom):
            result = await alerting.deliver_web_push("a", tag="r-BTCTRY", extra={"symbol": "BTCTRY"})
        self.assertFalse(result["ok"])
        boom.assert_awaited()

    async def test_counter_raises_fails_open(self):
        boom = AsyncMock(side_effect=RuntimeError("db down"))
        with patch.object(database, "bump_push_daily_count", new=boom):
            result = await alerting.deliver_web_push("a", tag="r-BTCTRY", extra={"symbol": "BTCTRY"})
        self.assertTrue(result["ok"])
        self.assertEqual(1, self.webpush.call_count)

    async def test_no_subscribers_gate_on_no_bump_no_skip(self):
        with patch("app.database.list_push_subscriptions", new=_subs(0)):
            for _ in range(2):
                result = await alerting.deliver_web_push("x", tag="r-BTCTRY", extra={"symbol": "BTCTRY"})
                self.assertNotEqual("daily_symbol_limit", result.get("reason"))
        self.assertEqual([], self.mem.calls)


class MonitoringSendPushRetryTests(unittest.IsolatedAsyncioTestCase):
    """`monitoring._send_push` atanan sayacı zarfa yazar; başarısız push'un yeniden denemesi aynı sayıyı taşır."""

    async def test_retry_reuses_count(self):
        calls = []

        async def fake_deliver(message, **kw):
            calls.append(kw["extra"].get("daily_count"))
            # İlk deneme: sayaç atanır ama teslim başarısız; ikinci deneme başarılı.
            return {"ok": len(calls) > 1, "daily_count": 7, "count": 0, "total": 1}

        notif = {"symbol": "BTCTRY", "message": "m", "title": "t", "url": "/x", "tag": "radar-BTCTRY"}
        with patch.object(monitoring, "deliver_web_push", new=fake_deliver):
            self.assertFalse(await monitoring._send_push(notif))
            self.assertEqual(7, notif["daily_count"])
            self.assertTrue(await monitoring._send_push(notif))
        self.assertEqual([None, 7], calls)


if __name__ == "__main__":
    unittest.main()
