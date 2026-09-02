"""Kullanıcı adı+şifre auth ve admin kullanıcı yönetimi testleri (2026-09-03)."""
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SecurityUnitTests(unittest.TestCase):
    def test_hash_and_verify_roundtrip(self):
        from app import security
        h = security.hash_password("518518Erkan")
        self.assertTrue(h.startswith(("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
                                      "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
                                      "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
                                      "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
                                      "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "-", "_")))
        self.assertIn("$", h)
        self.assertTrue(security.verify_password("518518Erkan", h))
        self.assertFalse(security.verify_password("yanlis", h))
        self.assertFalse(security.verify_password("518518Erkan", "bozuk-format"))

    def test_session_token_carries_username_role_case_insensitive(self):
        from app import security
        with patch.dict("os.environ", {"SCALPER_SESSION_SECRET": "test-secret-32-bytes-min!!"}, clear=False):
            token = security.create_session_token("ADMIN", "admin")
            user = security.session_user(token)
            self.assertEqual(user, {"username": "admin", "role": "admin"})
            self.assertTrue(security.verify_session_token(token))
            self.assertIsNone(security.session_user("bozuk.token"))


class AdminUserEndpointTests(unittest.IsolatedAsyncioTestCase):
    """_require_admin ve login karar mantığını mock'larla doğrular."""

    async def test_login_matches_db_user_with_password(self):
        from app.main import auth_login
        from app import security

        user_row = {"username": "admin", "role": "admin", "is_active": True,
                    "password_hash": security.hash_password("518518Erkan")}
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="1.2.3.4")
        response = MagicMock()
        with patch.object(sys.modules["app.main"].database, "get_user_by_username",
                          AsyncMock(return_value=user_row)):
            result = await auth_login({"username": "ADMIN", "password": "518518Erkan"}, response, request)
        self.assertTrue(result["ok"])
        self.assertEqual(result["role"], "admin")
        response.set_cookie.assert_called_once()

    async def test_login_rejects_wrong_password(self):
        from app.main import auth_login
        from app import security
        from fastapi import HTTPException

        user_row = {"username": "admin", "role": "admin", "is_active": True,
                    "password_hash": security.hash_password("518518Erkan")}
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="1.2.3.4")
        response = MagicMock()
        with patch.object(sys.modules["app.main"].database, "get_user_by_username",
                          AsyncMock(return_value=user_row)), \
             patch.object(security, "login_allowed", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                await auth_login({"username": "admin", "password": "yanlis"}, response, request)
        self.assertEqual(ctx.exception.status_code, 401)
        response.set_cookie.assert_not_called()

    def test_require_admin_blocks_non_admin(self):
        from app.main import _require_admin
        from fastapi import HTTPException

        request = MagicMock()
        request.headers = {}
        request.cookies = {}
        token = None
        with patch("app.security.request_user", return_value={"username": "ali", "role": "user"}):
            with self.assertRaises(HTTPException) as ctx:
                _require_admin(request)
            self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
