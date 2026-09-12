"""W11b — veritabanı bütünlüğü kilit testleri (V-07/08/09/10/11/12/15/17/18, MEM-01).

Testler Postgres gerektirmez: `_run_db` yamalanır ve op() sahte bir bağlantıyla
çalıştırılır. Böylece hem ÜRETİLEN SQL hem de dönen sonuç doğrulanır.
Mutasyon kanıtı: `outputs/denetim_2026-09-12/scratch/verify_w11b_mutations.py`.
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config as app_config  # noqa: E402
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
    """SQL metnine göre satır döndüren sahte bağlantı; ifadeleri kaydeder."""

    def __init__(self, routes=(), default=()):
        self.routes = list(routes)
        self.default = list(default)
        self.statements = []
        self.calls = []
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
        pass

    def rollback(self):
        pass


def _patched_run_db(conn):
    async def runner(operation):
        return operation(conn)
    return runner


class InitDbIndexTests(unittest.TestCase):
    """V-07 / V-08 — eksik index'ler her açılışta idempotent olarak kurulmalı."""

    async def _run_init_db(self):
        # `to_regclass` NULL -> "llm_settings yok" -> tam DDL yolu çalışır.
        conn = _RoutedConn(routes=[("to_regclass", [[None]])])

        async def _noop_backfill():
            return 0

        with mock.patch.object(database, "_run_db", _patched_run_db(conn)), \
                mock.patch.object(database, "backfill_position_trade_ids", _noop_backfill):
            await database.init_db()
        return conn

    def test_signals_trade_id_index_is_created(self):
        import asyncio

        conn = asyncio.run(self._run_init_db())
        assert any("idx_signals_trade_id ON signals(trade_id)" in s for s in conn.statements)

    def test_decision_logs_decision_index_is_created(self):
        import asyncio

        conn = asyncio.run(self._run_init_db())
        assert any("idx_decision_logs_decision ON decision_logs(decision, timestamp DESC)" in s
                   for s in conn.statements)

    def test_indexes_are_idempotent(self):
        import asyncio

        conn = asyncio.run(self._run_init_db())
        for statement in conn.statements:
            if "CREATE INDEX" in statement:
                assert "IF NOT EXISTS" in statement


class RepairScanComplexityTests(unittest.TestCase):
    """V-09 — onarım eşleştirmesi ikili arama ile aynı sonucu vermeli."""

    def test_has_timestamp_within_boundaries(self):
        index = [100.0, 130.0, 200.0]
        assert database._has_timestamp_within(index, 130.0, 30.0) is True
        assert database._has_timestamp_within(index, 100.0, 30.0) is True
        assert database._has_timestamp_within(index, 70.0, 30.0) is True
        assert database._has_timestamp_within(index, 69.9, 30.0) is False
        assert database._has_timestamp_within(index, 230.0, 30.0) is True   # 200 + 30
        assert database._has_timestamp_within(index, 230.1, 30.0) is False
        assert database._has_timestamp_within([], 100.0, 30.0) is False

    def test_matches_within_returns_all_hits(self):
        index = [(100.0, "A"), (110.0, "B"), (200.0, "C")]
        assert database._matches_within(index, 105.0, 30.0) == ["A", "B"]
        assert database._matches_within(index, 100.0, 5.0) == ["A"]
        assert database._matches_within(index, 150.0, 30.0) == []

    def test_preview_trade_repair_still_finds_unmatched_closes(self):
        import asyncio

        trades = [
            [1, "BTCUSDT", "LLM_PAPER", 100.0, 200.0, "t1"],
            [2, "ETHUSDT", "LLM_PAPER", 100.0, 500.0, "t2"],
        ]
        close_logs = [
            [9, "BTCUSDT", 215.0, None],     # |215-200| = 15  -> eslesir
            [10, "BTCUSDT", 240.0, None],    # |240-200| = 40  -> eslesmez
            [11, "ETHUSDT", 530.0, None],    # |530-500| = 30  -> sinirda eslesir
            [12, "SOLUSDT", 100.0, None],    # sembol yok      -> eslesmez
        ]
        conn = _RoutedConn(routes=[
            ("FROM trades WHERE trade_id IS NULL", []),
            ("FROM positions WHERE trade_id IS NULL", []),
            ("FROM trades ORDER BY exit_time", trades),
            ("FROM decision_logs", close_logs),
        ])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            result = asyncio.run(database.preview_trade_repair())
        assert [item["id"] for item in result["unmatched_close_logs"]] == [10, 12]

    def test_apply_trade_repair_enriches_only_single_matches(self):
        import asyncio

        # Iki farkli kapanis zamani ayni logun ±30 sn'sinde -> "tam 1 eslesme"
        # kurali geregi zenginlestirme YAPILMAZ.
        trades = [
            [1, "BTCUSDT", "LLM_PAPER", 200.0],
            [2, "BTCUSDT", "MOMENTUM", 220.0],
            [3, "ETHUSDT", "LLM_PAPER", 500.0],
        ]
        logs = [
            [9, "BTCUSDT", 215.0],
            [10, "ETHUSDT", 520.0],
        ]
        conn = _RoutedConn(routes=[
            ("FROM trades ORDER BY id", [[1, "BTCUSDT", 100.0, "t1"], [3, "ETHUSDT", 100.0, "t2"]]),
            ("FROM positions ORDER BY entry_time", []),
            ("FROM trades WHERE strategy IS NOT NULL", trades),
            ("FROM decision_logs WHERE decision='CLOSE_LONG'", logs),
        ])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            result = asyncio.run(database.apply_trade_repair())
        assert result["enriched_close_logs"] == 1
        updates = [sql for sql in conn.statements if sql.startswith("UPDATE decision_logs SET strategy=")]
        assert len(updates) == 1


class OverallocationOpenAutoPaperTests(unittest.TestCase):
    """V-10 — reset sonrası AÇIK auto-paper maliyeti aşırı-tahsis modeline girmeli."""

    def test_open_auto_paper_cost_is_included_when_cutoff_is_set(self):
        initial = float(app_config.config.INITIAL_BALANCE_TRY)
        auto_value = initial * 0.9
        positions = [["TESTUSDT", 2.0, initial * 0.1 / 10.0, 10.0]]
        conn = _RoutedConn(routes=[
            ("FROM trades", []),
            ("FROM auto_paper_trades", [[1.0, None, auto_value, 10.0, "open", None]]),
            ("FROM positions", positions),
        ])
        with mock.patch.object(database, "_get_reset_cutoff_sync", lambda _conn: 0.5):
            candidates = database._chronological_overallocation_candidates(conn)
        assert len(candidates) == 1
        assert candidates[0]["symbol"] == "TESTUSDT"
        assert candidates[0]["reason"] == "entry_cash_was_insufficient"

    def test_no_cutoff_keeps_everything_included(self):
        initial = float(app_config.config.INITIAL_BALANCE_TRY)
        conn = _RoutedConn(routes=[
            ("FROM trades", []),
            ("FROM auto_paper_trades", [[1.0, None, initial * 0.9, 10.0, "open", None]]),
            ("FROM positions", [["TESTUSDT", 2.0, initial * 0.1 / 10.0, 10.0]]),
        ])
        with mock.patch.object(database, "_get_reset_cutoff_sync", lambda _conn: 0.0):
            candidates = database._chronological_overallocation_candidates(conn)
        assert len(candidates) == 1

    def test_open_row_filter_sql_covers_null_exit_time(self):
        initial = float(app_config.config.INITIAL_BALANCE_TRY)
        conn = _RoutedConn(routes=[
            ("FROM trades", []),
            ("FROM auto_paper_trades", [[1.0, None, initial * 0.9, 10.0, "open", None]]),
            ("FROM positions", [["TESTUSDT", 2.0, initial * 0.1 / 10.0, 10.0]]),
        ])
        with mock.patch.object(database, "_get_reset_cutoff_sync", lambda _conn: 0.5):
            database._chronological_overallocation_candidates(conn)
        auto_sql = next(sql for sql in conn.statements if "FROM auto_paper_trades" in sql)
        assert "status='open' OR exit_time>" in auto_sql


class MonitoringVelocityMatchTests(unittest.TestCase):
    """V-11 — eşleştirme TEK sorguyla yapılmalı (N+1 yok), sonuç aynı kalmalı."""

    def _run(self, notifications, candidates):
        conn = _RoutedConn(routes=[
            ("FROM monitoring_notifications", notifications),
            ("FROM velocity_candidates", candidates),
        ])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            import asyncio
            matches = asyncio.run(database.get_monitoring_velocity_matches(limit=50, day=None))
        return matches, conn

    def test_matching_result_is_preserved(self):
        notifications = [
            {"id": 1, "symbol": "BTCUSDT", "detected_at": 1000.0, "target_pct": 2.0,
             "mode": "auto", "score": 1.0, "price": 100.0, "expected_price": 102.0,
             "horizon_minutes": 5, "sent_via_push": True, "message": "m", "title": "t"},
        ]
        candidates = [
            {"candidate_id": "c-btc", "symbol": "BTCUSDT", "target_pct": 2.0, "passes": True,
             "status": "evaluated", "mfe_pct": 1.5, "touched_target": True, "created_at": 1005.0,
             "ml_target_pct": 2.0, "ml_hit_probability": 0.7},
            {"candidate_id": "c-far", "symbol": "BTCUSDT", "target_pct": 2.0, "passes": True,
             "status": "evaluated", "mfe_pct": 9.9, "touched_target": True, "created_at": 1400.0,
             "ml_target_pct": 2.0, "ml_hit_probability": 0.9},
        ]
        matches, _ = self._run(notifications, candidates)
        assert matches[0]["target_match"] is True
        assert matches[0]["candidate_id"] == "c-btc"
        assert matches[0]["mfe_pct"] == 1.5

    def test_target_mismatch_stays_unmatched(self):
        notifications = [
            {"id": 1, "symbol": "SOLUSDT", "detected_at": 3000.0, "target_pct": 2.5,
             "mode": "auto", "score": 1.0, "price": 10.0, "expected_price": 10.25,
             "horizon_minutes": 5, "sent_via_push": True, "message": "m", "title": "t"},
        ]
        candidates = [
            {"candidate_id": "c-sol", "symbol": "SOLUSDT", "target_pct": 9.9, "passes": True,
             "status": "evaluated", "mfe_pct": 1.0, "touched_target": False, "created_at": 3010.0,
             "ml_target_pct": None, "ml_hit_probability": None},
        ]
        matches, _ = self._run(notifications, candidates)
        assert matches[0]["target_match"] is False
        assert matches[0]["candidate_id"] is None

    def test_candidates_are_fetched_in_one_query(self):
        notifications = [
            {"id": i, "symbol": f"S{i}USDT", "detected_at": 1000.0 + i, "target_pct": 2.0,
             "mode": "auto", "score": 1.0, "price": 1.0, "expected_price": 1.02,
             "horizon_minutes": 5, "sent_via_push": True, "message": "m", "title": "t"}
            for i in range(1, 9)
        ]
        candidates = [
            {"candidate_id": f"c{i}", "symbol": f"S{i}USDT", "target_pct": 2.0, "passes": True,
             "status": "evaluated", "mfe_pct": 1.0, "touched_target": True, "created_at": 1000.0 + i,
             "ml_target_pct": None, "ml_hit_probability": None}
            for i in range(1, 9)
        ]
        matches, conn = self._run(notifications, candidates)
        velocity_queries = [sql for sql in conn.statements if "FROM velocity_candidates" in sql]
        assert len(velocity_queries) == 1, f"N+1 geri geldi: {len(velocity_queries)} sorgu"
        assert all(item["target_match"] for item in matches)

    def test_window_uses_union_of_notification_times(self):
        notifications = [
            {"id": 1, "symbol": "AUSDT", "detected_at": 1000.0, "target_pct": 2.0,
             "mode": "auto", "score": 1.0, "price": 1.0, "expected_price": 1.02,
             "horizon_minutes": 5, "sent_via_push": True, "message": "m", "title": "t"},
            {"id": 2, "symbol": "BUSDT", "detected_at": 5000.0, "target_pct": 2.0,
             "mode": "auto", "score": 1.0, "price": 1.0, "expected_price": 1.02,
             "horizon_minutes": 5, "sent_via_push": True, "message": "m", "title": "t"},
        ]
        _, conn = self._run(notifications, [])
        query = next((sql, params) for sql, params in conn.calls if "FROM velocity_candidates" in sql)
        sql, params = query
        assert params[-2] == 940.0   # 1000 - 60
        assert params[-1] == 5060.0  # 5000 + 60
        assert "AUSDT" in params and "BUSDT" in params


class MacdAlertEventPathTests(unittest.TestCase):
    """V-12 — mum verisi sembol bazında TEK sorguda çekilmeli."""

    def _run(self, alerts, candles):
        conn = _RoutedConn(routes=[
            ("FROM macd_monitor_alerts", alerts),
            ("FROM historical_candles", candles),
        ])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)), \
                mock.patch.object(database, "_ensure_macd_evidence_schema", lambda _conn: None):
            import asyncio
            result = asyncio.run(database.macd_monitor_alert_event_paths(days=1, kind="early"))
        return result, conn

    def test_avg_path_is_unchanged(self):
        base = 1_000_000.0
        candles = [{"symbol": "BTCUSDT", "open_time": base + step * 300_000, "close": 100.0 + step}
                   for step in range(-3, 8)]
        alerts = [{"id": 1, "created_at": 1000.0, "symbol": "BTCUSDT", "kind": "early",
                   "price": None, "signals": None, "mfe_pct": None, "mae_pct": None}]
        result, _ = self._run(alerts, candles)
        assert result["n"] == 1
        assert result["avg_path"] == [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 6.0]

    def test_candles_are_fetched_in_one_query(self):
        base = 1_000_000.0
        candles = [{"symbol": "BTCUSDT", "open_time": base + step * 300_000, "close": 100.0 + step}
                   for step in range(-3, 8)]
        alerts = [{"id": index, "created_at": 1000.0, "symbol": "BTCUSDT", "kind": "early",
                   "price": None, "signals": None, "mfe_pct": None, "mae_pct": None}
                  for index in range(1, 21)]
        _, conn = self._run(alerts, candles)
        candle_queries = [sql for sql in conn.statements if "FROM historical_candles" in sql]
        assert len(candle_queries) == 1, f"N+1 geri geldi: {len(candle_queries)} sorgu"

    def test_alert_without_candles_is_skipped(self):
        alerts = [{"id": 1, "created_at": 1000.0, "symbol": "NOSUCHUSDT", "kind": "early",
                   "price": None, "signals": None, "mfe_pct": None, "mae_pct": None}]
        result, _ = self._run(alerts, [])
        assert result["n"] == 0


class PoolTimeoutTests(unittest.TestCase):
    """V-15 — kilit beklemesi sınırlanmalı; DDL'e özel statement_timeout verilmeli."""

    def test_pool_configure_sets_lock_timeout(self):
        conn = _RoutedConn()
        database._configure_pool_connection(conn)
        assert any("SET lock_timeout = '5s'" in sql for sql in conn.statements)

    def test_pool_configure_swallows_errors(self):
        class _Broken:
            def execute(self, sql, params=()):
                raise RuntimeError("boom")

            def commit(self):
                raise RuntimeError("boom")

        database._configure_pool_connection(_Broken())  # patlamamalı

    def test_init_db_bounds_the_ddl_statement(self):
        import asyncio

        conn = _RoutedConn(routes=[("to_regclass", [[None]])])

        async def _noop_backfill():
            return 0

        with mock.patch.object(database, "_run_db", _patched_run_db(conn)), \
                mock.patch.object(database, "backfill_position_trade_ids", _noop_backfill):
            asyncio.run(database.init_db())
        assert any("SET LOCAL statement_timeout = '300s'" in sql for sql in conn.statements)


class WalletBalanceNullTests(unittest.TestCase):
    """V-17 — NULL bakiye sayı sözleşmesini bozmamalı."""

    def _balance(self, rows):
        conn = _RoutedConn(routes=[("FROM virtual_wallet", rows)])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            import asyncio
            return asyncio.run(database.get_wallet_balance("TRY"))

    def test_null_amount_becomes_zero(self):
        assert self._balance([[None]]) == 0.0

    def test_missing_row_becomes_zero(self):
        assert self._balance([]) == 0.0

    def test_real_amount_is_returned(self):
        assert self._balance([[42.5]]) == 42.5

    def test_result_is_always_a_float(self):
        for rows in ([[None]], [], [[7]]):
            assert isinstance(self._balance(rows), float)


class AuditSearchEscapingTests(unittest.TestCase):
    """V-18 — LIKE jokerleri kaçırılmalı, normal arama bozulmamalı."""

    def test_wildcards_are_escaped(self):
        assert database._escape_like("100%") == "100\\%"
        assert database._escape_like("BUY_SIGNAL") == "BUY\\_SIGNAL"
        assert database._escape_like("a\\b") == "a\\\\b"

    def test_plain_text_is_unchanged(self):
        assert database._escape_like("BTCUSDT") == "BTCUSDT"

    def test_audit_filters_escape_the_needle(self):
        where, values = database._audit_filters(None, None, None, "50%_off")
        assert "ILIKE" in where
        assert all(value == "%50\\%\\_off%" for value in values)

    def test_audit_filters_keep_other_clauses(self):
        where, values = database._audit_filters("admin", "auth", "login", None)
        assert "actor_username=%s" in where
        assert "category=%s" in where
        assert "action=%s" in where
        assert values == ["admin", "auth", "LOGIN"]


class RetentionMemorySweepTests(unittest.TestCase):
    """MEM-01 — sohbet belleği ve ham telemetri temizlenmeli; öğrenme artefaktları DEĞİL."""

    def _run(self, **kwargs):
        conn = _RoutedConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            import asyncio
            deleted = asyncio.run(database.prune_retention(**kwargs))
        return deleted, conn

    def test_memory_documents_are_pruned(self):
        deleted, conn = self._run()
        assert "memory_documents" in deleted
        assert any("DELETE FROM memory_documents" in sql for sql in conn.statements)

    def test_agent_traces_are_pruned(self):
        deleted, conn = self._run()
        assert "agent_traces" in deleted
        assert any("DELETE FROM agent_traces" in sql for sql in conn.statements)

    def test_learning_artifacts_are_never_pruned(self):
        _, conn = self._run()
        joined = " ".join(conn.statements)
        assert "agent_experiences" not in joined
        assert "trading_instincts" not in joined

    def test_memory_window_is_separate_from_the_general_window(self):
        _, conn = self._run(days=30, memory_days=180)
        call = next(params for sql, params in conn.calls if "DELETE FROM memory_documents" in sql)
        age_days = (time.time() - call[0]) / 86400.0
        assert 179.9 < age_days < 180.1

    def test_general_tables_still_use_the_short_window(self):
        _, conn = self._run(days=30, memory_days=180)
        call = next(params for sql, params in conn.calls if "DELETE FROM monitoring_notifications" in sql)
        age_days = (time.time() - call[0]) / 86400.0
        assert 29.9 < age_days < 30.1

    def test_missing_table_does_not_abort_other_sweeps(self):
        class _Partial(_RoutedConn):
            def execute(self, sql, params=()):
                if "DELETE FROM memory_documents" in " ".join(str(sql).split()):
                    raise RuntimeError("relation does not exist")
                return super().execute(sql, params)

        conn = _Partial()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            import asyncio
            deleted = asyncio.run(database.prune_retention())
        assert deleted["memory_documents"] == 0
        assert "agent_traces" in deleted
