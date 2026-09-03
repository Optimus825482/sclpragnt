"""Olay kayıtları (audit trail) testleri — mock tabanlı, DB'siz (2026-09-03)."""
import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AuditRowAndFiltersTests(unittest.TestCase):
    def test_audit_row_parses_db_row(self):
        from app.database import _audit_row
        row = {"id": 7, "actor_username": "admin", "actor_role": "admin", "category": "auth",
               "action": "LOGIN_SUCCESS", "target": "admin", "details": {"ok": True}, "ip": "1.2.3.4",
               "user_agent": "Mozilla", "accept_language": "tr", "created_at": 1234.5}
        out = _audit_row(row)
        self.assertEqual(out["id"], 7)
        self.assertEqual(out["details"], {"ok": True})
        self.assertEqual(out["created_at"], 1234.5)
        self.assertIsNone(_audit_row(None))

    def test_audit_filters_builds_where_and_values(self):
        from app.database import _audit_filters
        where, values = _audit_filters("Admin", "auth", "login_success", "BTC")
        self.assertIn("actor_username=%s", where)
        self.assertIn("category=%s", where)
        self.assertIn("action=%s", where)
        self.assertIn("ILIKE", where)
        # kategori/aksiyon normalize edilir; arama değeri parametrizedir.
        self.assertEqual(values[0], "admin")
        self.assertEqual(values[1], "auth")
        self.assertEqual(values[2], "LOGIN_SUCCESS")
        self.assertEqual(values[3], "%BTC%")

    def test_json_safe_details_no_nan(self):
        from app.database import _json_safe_dumps
        payload = _json_safe_dumps({"x": float("nan"), "nested": [float("inf")]}, allow_nan=False)
        import json
        loaded = json.loads(payload)
        # NaN/Inf yok; _json_safe bunları None'a çevirir.
        self.assertIsNone(loaded["x"])
        self.assertIsNone(loaded["nested"][0])


class AuditDbHelpersTests(unittest.IsolatedAsyncioTestCase):
    """database.save_audit_log / list / count / delete _run_db op'larını doğrular."""

    async def test_save_audit_log_inserts_and_commits(self):
        from app import database
        fake_cur = MagicMock()
        fake_cur.fetchone.return_value = {"id": 1, "actor_username": "admin", "actor_role": "admin",
                                          "category": "auth", "action": "LOGIN_SUCCESS", "target": "admin",
                                          "details": {"ok": True}, "ip": "1.2.3.4", "user_agent": "UA",
                                          "accept_language": "tr", "created_at": 100.0}
        fake_conn = MagicMock()
        fake_conn.execute.return_value = fake_cur
        with patch.object(database, "_run_db", new=AsyncMock()) as run_db:
            run_db.side_effect = lambda op: op(fake_conn)
            result = await database.save_audit_log(
                "admin", "admin", "auth", "login_success", target="admin",
                details={"ok": True}, ip="1.2.3.4", user_agent="UA", accept_language="tr")
        self.assertEqual(result["category"], "auth")
        self.assertEqual(result["action"], "LOGIN_SUCCESS")
        fake_conn.execute.assert_called_once()
        fake_conn.commit.assert_called_once()

    async def test_list_audit_logs_orders_desc_and_bounds_limit(self):
        from app import database
        fake_cur = MagicMock()
        fake_cur.fetchall.return_value = []
        fake_conn = MagicMock()
        fake_conn.execute.return_value = fake_cur
        with patch.object(database, "_run_db", new=AsyncMock()) as run_db:
            run_db.side_effect = lambda op: op(fake_conn)
            rows = await database.list_audit_logs(limit=9999, offset=0, category="auth")
        self.assertEqual(rows, [])
        sql = fake_conn.execute.call_args.args[0]
        self.assertIn("ORDER BY created_at DESC, id DESC", sql)
        self.assertIn("LIMIT %s OFFSET %s", sql)
        # limit üst sınır 500'e çekilir.
        self.assertEqual(fake_conn.execute.call_args.args[1][-2], 500)

    async def test_delete_audit_logs_before_returns_rowcount(self):
        from app import database
        fake_cur = MagicMock()
        fake_cur.rowcount = 12
        fake_conn = MagicMock()
        fake_conn.execute.return_value = fake_cur
        with patch.object(database, "_run_db", new=AsyncMock()) as run_db:
            run_db.side_effect = lambda op: op(fake_conn)
            deleted = await database.delete_audit_logs_before(time.time())
        self.assertEqual(deleted, 12)
        fake_conn.commit.assert_called_once()


class ClientContextAndLoginAuditTests(unittest.IsolatedAsyncioTestCase):
    """client_context + log_user_action + login'de audit kaydı."""

    def test_client_context_prefers_x_real_ip(self):
        from app.api_common import client_context
        request = MagicMock()
        request.headers = {"X-Real-IP": "203.0.113.9", "user-agent": "TestAgent/1.0", "accept-language": "tr-TR,tr;q=0.9"}
        ctx = client_context(request)
        self.assertEqual(ctx["ip"], "203.0.113.9")
        self.assertEqual(ctx["user_agent"], "TestAgent/1.0")
        self.assertEqual(ctx["accept_language"], "tr-TR,tr;q=0.9")

    def test_client_context_falls_back_to_socket_host(self):
        from app.api_common import client_context
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="10.0.0.5")
        ctx = client_context(request)
        self.assertEqual(ctx["ip"], "10.0.0.5")

    async def test_log_user_action_never_raises(self):
        from app import api_common
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="1.2.3.4")
        with patch.object(api_common.database, "save_audit_log",
                          AsyncMock(side_effect=RuntimeError("db down"))):
            # Hata yutulur, çağrı asla fırlatmaz.
            await api_common.log_user_action("admin", "admin", "auth", "LOGIN_SUCCESS", request=request)

    async def test_successful_login_writes_audit(self):
        from app.main import auth_login
        from app import security
        user_row = {"username": "admin", "role": "admin", "is_active": True,
                    "password_hash": security.hash_password("518518Erkan")}
        request = MagicMock()
        request.headers = {"X-Real-IP": "203.0.113.9"}
        request.client = MagicMock(host="10.0.0.5")
        response = MagicMock()
        with patch.object(sys.modules["app.main"].database, "get_user_by_username",
                          AsyncMock(return_value=user_row)), \
             patch.object(sys.modules["app.main"], "log_user_action", AsyncMock()) as audit:
            result = await auth_login({"username": "ADMIN", "password": "518518Erkan"}, response, request)
        self.assertTrue(result["ok"])
        audit.assert_awaited_once()
        args, kwargs = audit.await_args
        self.assertEqual(kwargs.get("action") or (args[3] if len(args) > 3 else None), "LOGIN_SUCCESS")
        response.set_cookie.assert_called_once()

    async def test_failed_login_writes_audit(self):
        from app.main import auth_login
        from app import security
        from fastapi import HTTPException
        user_row = {"username": "admin", "role": "admin", "is_active": True,
                    "password_hash": security.hash_password("518518Erkan")}
        request = MagicMock()
        request.headers = {"X-Real-IP": "203.0.113.9"}
        request.client = MagicMock(host="10.0.0.5")
        response = MagicMock()
        with patch.object(sys.modules["app.main"].database, "get_user_by_username",
                          AsyncMock(return_value=user_row)), \
             patch.object(security, "login_allowed", return_value=True), \
             patch.object(sys.modules["app.main"], "log_user_action", AsyncMock()) as audit:
            with self.assertRaises(HTTPException) as ctx:
                await auth_login({"username": "admin", "password": "yanlis"}, response, request)
        self.assertEqual(ctx.exception.status_code, 401)
        audit.assert_awaited_once()
        args, kwargs = audit.await_args
        self.assertEqual(kwargs.get("action") or (args[3] if len(args) > 3 else None), "LOGIN_FAILED")
        response.set_cookie.assert_not_called()

    def test_require_admin_blocks_non_admin(self):
        from app.main import _require_admin
        from fastapi import HTTPException
        request = MagicMock()
        request.headers = {}
        request.cookies = {}
        with patch("app.security.request_user", return_value={"username": "ali", "role": "user"}):
            with self.assertRaises(HTTPException) as ctx:
                _require_admin(request)
            self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
