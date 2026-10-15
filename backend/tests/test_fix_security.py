"""Denetim düzeltmeleri (2026-10-15, bölüm 3 güvenlik) için testler.

A: X-Forwarded-For zinciri güvenilir proxy'ler atlanarak çözülür; kilit anahtarı kullanıcı+IP.
D: env-admin logout oturum sürümünü yükseltir (eski token geçersiz).
E: var olmayan kullanıcı için sahte hash doğrulaması hata fırlatmaz, 401 döner.
F: DB kullanıcısı şifre politikası (min 12 + yaygın şifre reddi).
H: admin DB tarayıcısı hassas sütun maskeleme.
"""
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _request(peer: str, headers: dict | None = None):
    request = MagicMock()
    request.headers = dict(headers or {})
    request.cookies = {}
    request.client = MagicMock(host=peer)
    return request


class ClientIpResolutionTests(unittest.TestCase):
    """A — XFF sağdan sola yürünür, güvenilir proxy'ler atlanır."""

    def test_xff_behind_trusted_proxy_returns_first_untrusted_hop(self):
        from app import security
        with patch.dict("os.environ", {"SCALPER_TRUSTED_PROXIES": "10.0.0.0/8,172.16.0.0/12"}, clear=False):
            req = _request("10.0.0.5", {"X-Forwarded-For": "203.0.113.7, 172.17.0.3"})
            self.assertEqual(security.trusted_client_ip(req), "203.0.113.7")

    def test_xff_spoofed_left_values_are_ignored(self):
        from app import security
        with patch.dict("os.environ", {"SCALPER_TRUSTED_PROXIES": "10.0.0.0/8,172.16.0.0/12"}, clear=False):
            # İstemci sol tarafa sahte değer ekledi; sağdan ilk güvenilmeyen gerçek IP'dir.
            req = _request("10.0.0.5", {"X-Forwarded-For": "1.1.1.1, 203.0.113.7, 172.17.0.3, 10.0.0.9"})
            self.assertEqual(security.trusted_client_ip(req), "203.0.113.7")

    def test_untrusted_peer_ignores_headers(self):
        from app import security
        with patch.dict("os.environ", {"SCALPER_TRUSTED_PROXIES": "10.0.0.0/8"}, clear=False):
            req = _request("198.51.100.9", {"X-Forwarded-For": "203.0.113.7", "X-Real-IP": "203.0.113.8"})
            self.assertEqual(security.trusted_client_ip(req), "198.51.100.9")

    def test_trusted_peer_without_xff_falls_back_to_real_ip_then_socket(self):
        from app import security
        with patch.dict("os.environ", {"SCALPER_TRUSTED_PROXIES": "10.0.0.0/8"}, clear=False):
            self.assertEqual(security.trusted_client_ip(_request("10.0.0.5", {"X-Real-IP": "203.0.113.8"})),
                             "203.0.113.8")
            self.assertEqual(security.trusted_client_ip(_request("10.0.0.5")), "10.0.0.5")

    def test_all_hops_trusted_falls_back_to_socket(self):
        from app import security
        with patch.dict("os.environ", {"SCALPER_TRUSTED_PROXIES": "10.0.0.0/8"}, clear=False):
            req = _request("10.0.0.5", {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"})
            self.assertEqual(security.trusted_client_ip(req), "10.0.0.5")

    def test_lockout_key_combines_username_and_ip(self):
        from app import security
        with patch.dict("os.environ", {"SCALPER_TRUSTED_PROXIES": "10.0.0.0/8"}, clear=False):
            req = _request("10.0.0.5", {"X-Forwarded-For": "203.0.113.7"})
            self.assertEqual(security.login_lockout_key("Ali", req), "ali|203.0.113.7")
            self.assertNotEqual(security.login_lockout_key("ali", req),
                                security.login_lockout_key("veli", req))


class EnvAdminSessionVersionTests(unittest.TestCase):
    """D — env-admin logout sonrası eski token geçersiz."""

    def test_bump_invalidates_old_token(self):
        from app import security
        with patch.dict("os.environ", {"SCALPER_SESSION_SECRET": "test-secret-32-bytes-min!!"}, clear=False):
            before = security.get_user_session_version("admin")
            token = security.create_session_token("admin", "admin")
            self.assertTrue(security.verify_session_token(token))
            security.bump_env_admin_session_version()
            try:
                self.assertFalse(security.verify_session_token(token))
                self.assertTrue(security.verify_session_token(security.create_session_token("admin", "admin")))
            finally:
                security.set_user_session_version("admin", before)


class UnknownUserTimingTests(unittest.IsolatedAsyncioTestCase):
    """E — var olmayan kullanıcı: sahte hash yolu hata fırlatmaz, 401 döner."""

    def test_dummy_hash_verifies_false_without_raising(self):
        from app import security
        self.assertIn("$", security.DUMMY_PASSWORD_HASH)
        self.assertFalse(security.verify_password("herhangi-bir-sey", security.DUMMY_PASSWORD_HASH))
        self.assertFalse(security.verify_password("", security.DUMMY_PASSWORD_HASH))

    async def test_login_unknown_user_returns_401(self):
        from app.main import auth_login
        from app import security
        from fastapi import HTTPException

        request = _request("1.2.3.4")
        response = MagicMock()
        with patch.dict("os.environ", {"SCALPER_ADMIN_PASSWORD": "env-admin-pass",
                                       "SCALPER_SESSION_SECRET": "test-secret-32-bytes-min!!"}, clear=False), \
             patch.object(sys.modules["app.main"].database, "get_user_by_username",
                          AsyncMock(return_value=None)), \
             patch.object(security, "login_allowed", return_value=True), \
             patch("app.main._verify_password", wraps=security.verify_password) as verify:
            with self.assertRaises(HTTPException) as ctx:
                await auth_login({"username": "yok-boyle-biri", "password": "x"}, response, request)
        self.assertEqual(ctx.exception.status_code, 401)
        # Sahte hash'e karşı doğrulama GERÇEKTEN çalıştı (timing eşitleme).
        self.assertGreaterEqual(verify.call_count, 1)
        response.set_cookie.assert_not_called()


class PasswordPolicyTests(unittest.IsolatedAsyncioTestCase):
    """F — DB kullanıcıları için min 12 karakter + yaygın şifre reddi."""

    def test_policy_helper(self):
        from app import security
        self.assertIsNotNone(security.password_policy_error("kisa123"))
        self.assertIsNotNone(security.password_policy_error("12345678901"))      # 11 karakter
        self.assertIsNotNone(security.password_policy_error("123456789012"))     # yaygın listede
        self.assertIsNotNone(security.password_policy_error("Qwertyuiop"))       # kısa + yaygın
        self.assertIsNone(security.password_policy_error("Guclu-Sifre-2026!"))

    async def test_admin_create_user_rejects_weak_password(self):
        from app.main import admin_create_user
        from fastapi import HTTPException

        request = _request("1.2.3.4")
        with patch("app.main._require_admin", return_value={"username": "admin", "role": "admin"}), \
             patch.object(sys.modules["app.main"].database, "get_user_by_username",
                          AsyncMock(return_value=None)) as lookup:
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_user({"username": "yeni", "password": "kisa"}, request)
            self.assertEqual(ctx.exception.status_code, 422)
            with self.assertRaises(HTTPException) as ctx2:
                await admin_create_user({"username": "yeni", "password": "123456789012"}, request)
            self.assertEqual(ctx2.exception.status_code, 422)
        lookup.assert_not_awaited()


class SensitiveColumnMaskingTests(unittest.TestCase):
    """H — admin DB tarayıcısı/CSV hassas sütunları `***` yapar."""

    def test_sensitive_column_detection(self):
        from app import security
        for col in ("password_hash", "api_key", "client_secret", "binance_secret", "encrypted_key",
                    "phone", "ip", "ip_address", "client_ip", "user_agent", "token", "access_token",
                    "token_hash", "private_key", "credentials"):
            self.assertTrue(security.is_sensitive_column(col), col)
        for col in ("id", "username", "key", "symbol", "total_tokens", "prompt_tokens", "tokens_used",
                    "created_at", "description", "zip", "shipment"):
            self.assertFalse(security.is_sensitive_column(col), col)

    def test_mask_row_keeps_nonsensitive_and_nulls(self):
        from app import security
        row = {"id": 1, "username": "ali", "password_hash": "abc$def", "phone": None, "api_key": "k"}
        masked = security.mask_sensitive_row(row)
        self.assertEqual(masked["id"], 1)
        self.assertEqual(masked["username"], "ali")
        self.assertEqual(masked["password_hash"], "***")
        self.assertEqual(masked["api_key"], "***")
        self.assertIsNone(masked["phone"])
        # Orijinal satır değişmez.
        self.assertEqual(row["password_hash"], "abc$def")


if __name__ == "__main__":
    unittest.main()
