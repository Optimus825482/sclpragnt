"""LLM salt-okunur SQL koruması: AST doğrulayıcı, çalıştırma sınırları ve araç filtresi.

Denetim 2026-10-15 (P0): regex tabanlı `FROM|JOIN <ad>` denetimi virgüllü join ile
`users.password_hash` sızdırıyordu; non-admin sohbet mutasyon araçlarını da
çalıştırabiliyordu. Bu testler bilinen bypass denemelerini ve meşru sorguları
kilitler.
"""
import asyncio
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import database, sql_guard
from app.routers import llm_chat


# Bypass denemeleri: her biri reddedilmeli. Gerekçe, saldırının ne sızdırmaya
# çalıştığını anlatır.
BYPASS_ATTEMPTS = [
    # Denetimdeki asıl bulgu: virgüllü join ile users tablosu
    ("SELECT u.* FROM positions p, users u", "users.* genişletme"),
    ("SELECT p.symbol, u.password_hash FROM positions p, users u", "users tablosu"),
    ("SELECT symbol FROM positions p, user_preferences up", "user_preferences tablosu"),
    ("SELECT symbol FROM positions, audit_logs", "audit_logs tablosu"),
    ("SELECT symbol FROM positions p, user_binance_keys k", "API anahtarı tablosu"),
    ("SELECT password_hash FROM users", "doğrudan users"),
    ("SELECT * FROM positions", "yıldız ile sütun genişletme"),
    ("SELECT p.* FROM positions p", "tablo.* genişletme"),
    ("SELECT (SELECT password_hash FROM users LIMIT 1) AS x FROM trades", "skaler alt sorgu"),
    ("SELECT x.a FROM (SELECT * FROM users) x", "türetilmiş tablo içinde *"),
    ("SELECT id FROM trades UNION SELECT id FROM users", "UNION ile users"),
    ("SELECT symbol FROM pg_catalog.pg_class", "şema nitelikli sistem tablosu"),
    ("SELECT * FROM pg_read_file('/etc/passwd')", "pg_read_file tablo fonksiyonu"),
    ("SELECT pg_sleep(10)", "pg_sleep yan etkisi"),
    ("SELECT dblink('host=x', 'select 1')", "bilinmeyen fonksiyon"),
    ("SELECT symbol FROM positions WHERE entry_context->>'k' = 'x'", "JSONB opak sütun"),
    ("SELECT metadata FROM decision_logs", "opak sütun (niteliksiz)"),
    ("SELECT trades.entry_context FROM trades", "opak sütun (nitelikli)"),
    ("SELECT payload FROM analysis_snapshots", "opak payload sütunu"),
    ("SELECT arguments FROM llm_tool_logs", "opak arguments sütunu"),
    ("SELECT symbol FROM positions p WHERE p.nonexist = 1", "bilinmeyen sütun"),
    ("SELECT symbol FROM positions p JOIN trades p ON true", "belirsiz takma ad"),
    ("SELECT symbol FROM positions; DROP TABLE trades", "çoklu ifade"),
    ("SELECT symbol FROM positions;", "noktalı virgül"),
    ("INSERT INTO trades (id) VALUES (1)", "yazma"),
    ("SELECT 1 FROM trades FOR UPDATE", "satır kilidi"),
    ("SELECT * INTO leak FROM trades", "SELECT INTO"),
    ("WITH d AS (DELETE FROM trades RETURNING id) SELECT id FROM d", "veri değiştiren CTE"),
    ("SELECT 1 FROM trades WHERE id IN (SELECT id FROM users)", "WHERE alt sorgusunda users"),
    ("", "boş sorgu"),
]


class ReadOnlySqlGuardTests(unittest.TestCase):
    def test_bypass_attempts_are_rejected(self):
        for sql, reason in BYPASS_ATTEMPTS:
            with self.subTest(reason=reason, sql=sql):
                with self.assertRaises(ValueError):
                    sql_guard.validate_read_only_select(sql, 50)

    def test_legitimate_queries_are_accepted_and_bounded(self):
        allowed = [
            "SELECT symbol, pnl FROM trades WHERE symbol = 'BTCTRY' ORDER BY pnl DESC",
            "SELECT p.symbol, t.pnl FROM positions p JOIN trades t ON t.symbol = p.symbol",
            "SELECT symbol FROM positions p, trades t",
            "SELECT COUNT(*) FROM trades",
            "WITH c AS (SELECT symbol AS s FROM positions) SELECT c.s FROM c",
            "SELECT id, pnl AS total FROM trades ORDER BY total",
            "SELECT symbol FROM positions UNION SELECT symbol FROM trades",
            "SELECT symbol FROM positions WHERE symbol LIKE '%token%'",
        ]
        for sql in allowed:
            with self.subTest(sql=sql):
                wrapped = sql_guard.validate_read_only_select(sql, 50)
                self.assertTrue(wrapped.startswith("SELECT * FROM ("), wrapped)
                self.assertTrue(wrapped.endswith("LIMIT 50"), wrapped)

    def test_outer_limit_is_capped_regardless_of_inner_limit(self):
        wrapped = sql_guard.validate_read_only_select("SELECT id FROM trades LIMIT 1000000", 9999)
        self.assertTrue(wrapped.endswith(f"LIMIT {sql_guard.MAX_ROWS}"), wrapped)
        self.assertNotIn("1000000", wrapped.split("AS llm_read_only_result")[-1])

    def test_limit_floor_is_one(self):
        wrapped = sql_guard.validate_read_only_select("SELECT id FROM trades", 0)
        self.assertTrue(wrapped.endswith("LIMIT 1"), wrapped)


class _Cursor:
    def __init__(self, rows, description=None):
        self._rows = rows
        self.description = description or [("x",)]

    def fetchall(self):
        return self._rows


class _FakeConn:
    """`_PostgresCompat` taklidi: yalnız raw_execute; çalıştırılan SQL'i kaydeder."""

    def __init__(self, role_exists):
        self.role_exists = role_exists
        self.statements = []

    def raw_execute(self, sql, params=()):
        self.statements.append(sql)
        if "pg_roles" in sql:
            return _Cursor([[1]] if self.role_exists else [])
        return _Cursor([[7]])

    def execute(self, sql, params=()):  # V-19: compat execute kullanılmamalı
        raise AssertionError("read_only_query compat execute kullandı")


def _run_with(conn, coro_factory):
    async def runner(op):
        return op(conn)

    with patch.object(database, "_run_db", runner):
        return asyncio.run(coro_factory())


class ReadOnlyExecutionTests(unittest.TestCase):
    def test_transaction_is_read_only_and_time_limited_before_query(self):
        conn = _FakeConn(role_exists=True)
        rows = _run_with(conn, lambda: database.read_only_query("SELECT symbol FROM positions", 10))
        self.assertEqual([{"x": 7}], rows)
        self.assertEqual("SET TRANSACTION READ ONLY", conn.statements[0])
        self.assertIn(f"statement_timeout = '{sql_guard.STATEMENT_TIMEOUT}'", conn.statements[1])
        self.assertIn("SET LOCAL ROLE llm_readonly", conn.statements)
        self.assertTrue(conn.statements[-1].startswith("SELECT * FROM ("))
        self.assertTrue(conn.statements[-1].endswith("LIMIT 10"))

    def test_role_switch_is_skipped_when_role_is_missing(self):
        conn = _FakeConn(role_exists=False)
        _run_with(conn, lambda: database.read_only_query("SELECT symbol FROM positions", 10))
        self.assertFalse(any("SET LOCAL ROLE" in s for s in conn.statements))
        self.assertEqual("SET TRANSACTION READ ONLY", conn.statements[0])

    def test_invalid_sql_never_reaches_the_connection(self):
        conn = _FakeConn(role_exists=True)
        with self.assertRaises(ValueError):
            _run_with(conn, lambda: database.read_only_query("SELECT u.* FROM positions p, users u"))
        self.assertEqual([], conn.statements)

    def test_question_mark_literal_is_not_rewritten(self):
        conn = _FakeConn(role_exists=False)
        _run_with(conn, lambda: database.read_only_query("SELECT symbol FROM trades WHERE symbol = '?'", 5))
        self.assertIn("'?'", conn.statements[-1])


class NonAdminToolFilterTests(unittest.TestCase):
    @staticmethod
    def _tool(name):
        return {"type": "function", "function": {"name": name}}

    def _all_tools(self):
        names = set(llm_chat.LLM_NON_ADMIN_TOOL_ALLOWLIST) | set(llm_chat.LLM_ADMIN_ONLY_TOOLS)
        return [self._tool(n) for n in sorted(names)]

    def test_non_admin_sees_only_allowlisted_tools(self):
        tools = self._all_tools()
        for user in ({"role": "user"}, {}, None):
            with self.subTest(user=user):
                kept = {t["function"]["name"] for t in llm_chat._filter_tools_for_role(tools, user)}
                self.assertTrue(kept <= llm_chat.LLM_NON_ADMIN_TOOL_ALLOWLIST)
                self.assertFalse(kept & llm_chat.LLM_ADMIN_ONLY_TOOLS)

    def test_unknown_tool_is_hidden_from_non_admin_by_default(self):
        tools = [self._tool("brand_new_mutating_tool")]
        self.assertEqual([], llm_chat._filter_tools_for_role(tools, {"role": "user"}))

    def test_admin_keeps_full_tool_list(self):
        tools = self._all_tools() + [self._tool("brand_new_mutating_tool")]
        self.assertEqual(tools, llm_chat._filter_tools_for_role(tools, {"role": "admin"}))

    def test_mutating_tools_are_not_in_allowlist(self):
        for name in ("close_llm_position", "update_llm_position_plan", "set_llm_symbol_guard",
                     "remove_llm_symbol_guard", "deactivate_coin", "reconcile_portfolio",
                     "place_paper_order", "open_llm_paper_trade", "cancel_paper_order",
                     "modify_paper_order", "create_market_alert", "activate_coin"):
            with self.subTest(name=name):
                self.assertNotIn(name, llm_chat.LLM_NON_ADMIN_TOOL_ALLOWLIST)

    def test_execution_gate_denies_admin_only_tools_for_non_admin(self):
        for name in llm_chat.LLM_ADMIN_ONLY_TOOLS:
            with self.subTest(name=name):
                denied = llm_chat._admin_only_denied(name, {"role": "user"})
                self.assertIsNotNone(denied)
                self.assertFalse(denied["ok"])
                self.assertIsNone(llm_chat._admin_only_denied(name, {"role": "admin"}))
        self.assertIsNone(llm_chat._admin_only_denied("get_trades", {"role": "user"}))

    def test_allowlist_names_exist_in_chat_source(self):
        source = (ROOT / "app" / "routers" / "llm_chat.py").read_text(encoding="utf-8")
        for name in sorted(llm_chat.LLM_NON_ADMIN_TOOL_ALLOWLIST):
            with self.subTest(name=name):
                self.assertIn(f'"{name}"', source, "allowlist'te yazım hatası veya kaldırılmış araç")


if __name__ == "__main__":
    unittest.main()
