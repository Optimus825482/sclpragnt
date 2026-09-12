"""M4 — monitoring veritabanı sözleşmeleri için kilit testleri.

Kapsam: norm_cap, sent_via_push varsayılanı, candidate_id ile kalıcı eşleşme,
`notification_key` (reopen), `limit=None` (cap'siz genel), `day` guard'ı.
Her test ilgili düzeltme geri alınırsa KIRILIR.
"""
import asyncio
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database  # noqa: E402


class _FakeCursor:
    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows) if rows else []
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _RoutedConn:
    def __init__(self, routes=(), default=()):
        self.routes = list(routes)
        self.default = list(default)
        self.statements = []
        self.calls = []
        self.commits = 0
        self.conn = self

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        self.statements.append(text)
        self.calls.append((text, params))
        for needle, rows in self.routes:
            if needle in text:
                return _FakeCursor(rows)
        return _FakeCursor(self.default)

    def commit(self):
        self.commits += 1


def _patched_run_db(conn):
    async def runner(operation):
        return operation(conn)
    return runner


def _notif_row(**overrides):
    row = {"symbol": "BTCUSDT", "created_at": 100.0, "target_pct": 2.0,
           "detected_at": 100.0, "score": 40.0, "mode": "auto", "price": 100.0,
           "expected_price": 102.0, "message": "m", "title": "t",
           "horizon_minutes": 5, "sent_via_push": False, "candidate_id": "c-1",
           "norm_cap": 40.0}
    row.update(overrides)
    return row


class SaveNotificationContractTests(unittest.TestCase):
    """norm_cap+candidate_id saklanır; sent_via_push varsayılanı False."""

    @staticmethod
    def _insert_columns(sql):
        match = re.search(r"INSERT INTO monitoring_notifications\s*\(([^)]+)", sql)
        return [c.strip() for c in match.group(1).split(",")]

    def test_default_sent_via_push_is_false(self):
        conn = _RoutedConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            asyncio.run(database.save_monitoring_notifications([_notif_row()]))
        sql, params = conn.calls[0]
        cols = self._insert_columns(sql)
        assert "sent_via_push" in cols
        assert params[cols.index("sent_via_push")] is False

    def test_norm_cap_and_candidate_id_are_stored(self):
        conn = _RoutedConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            asyncio.run(database.save_monitoring_notifications([_notif_row()]))
        sql, params = conn.calls[0]
        cols = self._insert_columns(sql)
        assert "norm_cap" in cols and "candidate_id" in cols
        assert float(params[cols.index("norm_cap")]) == 40.0
        assert params[cols.index("candidate_id")] == "c-1"


class VelocityMatchesContractTests(unittest.TestCase):
    """get_monitoring_velocity_matches: cap'siz genel + candidate_id önceliği."""

    def _run(self, conn, **kwargs):
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            return asyncio.run(database.get_monitoring_velocity_matches(**kwargs))

    def test_unbounded_limit_emits_no_limit_clause(self):
        conn = _RoutedConn(routes=[("FROM monitoring_notifications", [_notif_row()])])
        self._run(conn, limit=None)
        notifications_sql = next(s for s in conn.statements if "FROM monitoring_notifications" in s)
        assert "LIMIT" not in notifications_sql

    def test_invalid_day_raises_value_error(self):
        conn = _RoutedConn()
        with self.assertRaises(ValueError):
            self._run(conn, day="01-01-2020")

    def test_valid_day_parses(self):
        conn = _RoutedConn(routes=[("FROM monitoring_notifications", [])])
        result = self._run(conn, day="2026-09-12")
        assert result == []


class OpenAutoPaperKeyTests(unittest.TestCase):
    """notification_key saklama + churn dedup."""

    def _trade(self, notification_key="reopen:BTCUSDT:1", notification_id=None):
        return {
            "symbol": "BTCUSDT", "side": "LONG", "entry_price": 100.0, "quantity": 1.0,
            "order_value_try": 1000.0, "stop_loss": 98.0, "take_profit": 102.0,
            "entry_time": 100.0, "created_at": 100.0, "updated_at": 100.0,
            "notification_id": notification_id,
            **({"notification_key": notification_key} if notification_key else {}),
        }

    def test_notification_key_is_inserted(self):
        conn = _RoutedConn(routes=[
            ("SELECT amount FROM virtual_wallet", [[10000.0]]),
            ("SELECT COUNT(*) FROM auto_paper_trades WHERE notification_key", [[0]]),
        ])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            result, status = asyncio.run(database.open_auto_paper_trade(
                self._trade("reopen:BTCUSDT:5"), {"timestamp": 100.0}))
        assert status in ("opened", "error"), status
        insert_sql = next(s for s in conn.statements if "INSERT INTO auto_paper_trades" in s)
        assert "notification_key" in insert_sql

    def test_prior_notification_key_blocks_reopen(self):
        conn = _RoutedConn(routes=[
            ("SELECT amount FROM virtual_wallet", [[10000.0]]),
            ("SELECT COUNT(*) FROM auto_paper_trades WHERE notification_key", [[1]]),
        ])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            _result, status = asyncio.run(database.open_auto_paper_trade(
                self._trade("reopen:BTCUSDT:7"), {"timestamp": 100.0}))
        assert status == "already_traded"

    def test_notification_key_lookup_helper(self):
        conn = _RoutedConn(routes=[("WHERE notification_key=", [_notif_row()])])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            result = asyncio.run(
                database.get_recent_auto_paper_trade_by_notification_key("reopen:X:1"))
        assert result is not None
        assert any("notification_key" in s for s in conn.statements)


class InitDbSchemaTests(unittest.TestCase):
    """Yeni kolonlar init_db'de idempotent kurulur."""

    def test_schema_columns_are_created(self):
        conn = _RoutedConn(routes=[("to_regclass", [[None]])])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)), \
                mock.patch.object(database, "backfill_position_trade_ids",
                                  lambda *a: asyncio.sleep(0)):
            asyncio.run(database.init_db())
        joined = " ".join(conn.statements)
        assert "monitoring_notifications ADD COLUMN IF NOT EXISTS norm_cap" in joined
        assert "monitoring_notifications ADD COLUMN IF NOT EXISTS candidate_id" in joined
        assert "auto_paper_trades ADD COLUMN IF NOT EXISTS notification_key" in joined
        assert "uq_auto_paper_notification_key" in joined


if __name__ == "__main__":
    unittest.main()