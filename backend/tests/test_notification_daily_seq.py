"""Bildirim kartı "Bugün #N" rozeti (2026-10-24): `daily_seq` hesabı.

Kilitler:
  * sıra, kalıcı `monitoring_notifications` tablosundan TEK pencere sorgusuyla gelir
  * sembol başına, 00:00 Europe/Istanbul'dan beri, zaman dilimi/mod ayırt etmeden sayılır
  * sembol normalize edilir (`BTC_TRY` ve `BTCTRY` aynı coin)
  * sıra `detected_at`, eşitlikte `id` ile verilir
  * dünkü satır → None; sorgu hatası uç noktayı bozmaz (alan eklenmez, uyarı loglanır)
"""
import asyncio
import logging
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app import database, push_daily_counter
from app.routers import monitoring

# 2026-10-24 00:00 Europe/Istanbul (UTC+3) = 2026-10-23 21:00 UTC
DAY_START = datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc).timestamp()


def _memory_db_with_rows(rows):
    """Gerçek SQL'i çalıştırmak için bellek içi sqlite (pencere fonksiyonu destekli).

    `_PostgresCompat` gibi `?` yer tutucu kullanılır; satırlar indeksle okunur.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE monitoring_notifications("
        "id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, detected_at REAL NOT NULL,"
        "sent_via_push INTEGER NOT NULL DEFAULT 0, push_attempted INTEGER)")
    conn.executemany(
        "INSERT INTO monitoring_notifications(id, symbol, detected_at, sent_via_push, push_attempted) "
        "VALUES(?,?,?,?,?)", rows)
    conn.commit()
    return conn


class DayStartTests(unittest.TestCase):
    def test_day_start_is_istanbul_midnight(self):
        # 2026-10-24 22:30 UTC = 25 Ekim 01:30 İstanbul → gün başı 25 Ekim 00:00 İstanbul (24 Ekim 21:00 UTC)
        ts = datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc).timestamp()
        expected = datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(expected, push_daily_counter.day_start(ts))
        # day_key ile aynı gün sınırı
        self.assertEqual("2026-10-25", push_daily_counter.day_key(push_daily_counter.day_start(ts)))


class DailySeqQueryTests(unittest.TestCase):
    def _run(self, rows, since=DAY_START, push_only=True):
        conn = _memory_db_with_rows(rows)

        async def fake_run_db(operation):
            return operation(conn)

        try:
            with patch.object(database, "_run_db", fake_run_db):
                return asyncio.run(database.get_monitoring_notification_daily_seq(since, push_only=push_only))
        finally:
            conn.close()

    def test_two_symbols_counted_independently_since_midnight(self):
        rows = [
            # (id, symbol, detected_at, sent_via_push, push_attempted)
            (1, "TREETRY", DAY_START - 3600, 1, 1),   # dün → sayılmaz
            (2, "TREETRY", DAY_START + 60, 1, 1),     # TREE #1
            (3, "BTCTRY", DAY_START + 120, 1, 1),     # BTC #1
            (4, "TREETRY", DAY_START + 180, 1, 1),    # TREE #2
            (5, "TREETRY", DAY_START + 240, 0, 1),    # push denenmiş (başarısız) → TREE #3
            (6, "BTCTRY", DAY_START + 300, 1, 1),     # BTC #2
        ]
        seq = self._run(rows)
        self.assertEqual({2: 1, 3: 1, 4: 2, 5: 3, 6: 2}, seq)
        self.assertNotIn(1, seq)

    def test_symbol_is_normalized_like_push_counter(self):
        rows = [
            (1, "BTC_TRY", DAY_START + 10, 1, 1),
            (2, "btctry", DAY_START + 20, 1, 1),
            (3, "BTCTRY", DAY_START + 30, 1, 1),
        ]
        self.assertEqual({1: 1, 2: 2, 3: 3}, self._run(rows))

    def test_ties_broken_by_id_and_order_not_by_insert_order(self):
        rows = [
            (9, "SOLTRY", DAY_START + 50, 1, 1),   # aynı an, büyük id → #3
            (7, "SOLTRY", DAY_START + 50, 1, 1),   # aynı an, küçük id → #2
            (8, "SOLTRY", DAY_START + 5, 1, 1),    # daha erken → #1
        ]
        self.assertEqual({8: 1, 7: 2, 9: 3}, self._run(rows))

    def test_panel_only_rows_excluded_by_default(self):
        rows = [
            (1, "ETHTRY", DAY_START + 10, 0, None),  # yalnız panel (eski) → sayılmaz
            (2, "ETHTRY", DAY_START + 20, 1, 1),
        ]
        self.assertEqual({2: 1}, self._run(rows))
        self.assertEqual({1: 1, 2: 2}, self._run(rows, push_only=False))


class HistoryEndpointDailySeqTests(unittest.IsolatedAsyncioTestCase):
    def _rows(self):
        # 2026-10-28: geçmiş yalnız push'u GİTMİŞ satırları gösterir (`_delivered`).
        return [dict(r, sent_via_push=True) for r in self._raw_rows()]

    def _raw_rows(self):
        return [
            {"id": 6, "symbol": "BTCTRY", "detected_at": DAY_START + 300, "score": 50.0},
            {"id": 4, "symbol": "TREETRY", "detected_at": DAY_START + 180, "score": 50.0},
            {"id": 2, "symbol": "TREETRY", "detected_at": DAY_START + 60, "score": 50.0},
            {"id": 1, "symbol": "TREETRY", "detected_at": DAY_START - 3600, "score": 50.0},  # dün
            {"symbol": "XRPTRY", "detected_at": DAY_START + 400, "score": 50.0},  # id yok
        ]

    async def test_history_rows_get_daily_seq(self):
        seq_map = {2: 1, 4: 2, 6: 1}
        with patch.object(monitoring.database, "list_monitoring_notifications",
                          new_callable=AsyncMock, return_value=self._rows()), \
             patch.object(monitoring.database, "get_monitoring_notification_daily_seq",
                          new_callable=AsyncMock, return_value=seq_map) as q, \
             patch.object(push_daily_counter, "day_start", new=lambda now=None: DAY_START):
            payload = await monitoring.monitoring_notification_history()
        by_id = {r.get("id"): r for r in payload["history"]}
        self.assertEqual(1, by_id[6]["daily_seq"])
        self.assertEqual(2, by_id[4]["daily_seq"])
        self.assertEqual(1, by_id[2]["daily_seq"])
        self.assertIsNone(by_id[1]["daily_seq"])       # dünkü satır
        self.assertIsNone(by_id[None]["daily_seq"])    # id'siz satır
        # Tek sorgu, gün başı alt sınırıyla
        q.assert_awaited_once()
        self.assertEqual(DAY_START, q.await_args.args[0])

    async def test_query_failure_does_not_break_endpoint(self):
        with patch.object(monitoring.database, "list_monitoring_notifications",
                          new_callable=AsyncMock, return_value=self._rows()), \
             patch.object(monitoring.database, "get_monitoring_notification_daily_seq",
                          new_callable=AsyncMock, side_effect=RuntimeError("db yok")), \
             patch.object(push_daily_counter, "day_start", new=lambda now=None: DAY_START), \
             self.assertLogs("scalper.monitoring", level=logging.WARNING) as logs:
            payload = await monitoring.monitoring_notification_history()
        self.assertEqual(5, len(payload["history"]))
        self.assertTrue(all("daily_seq" not in r for r in payload["history"]))
        self.assertTrue(any("daily_seq" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
