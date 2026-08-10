import os
import sqlite3
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


class SecurityBehavior(unittest.TestCase):
    def test_signed_session_expires_and_detects_tampering(self):
        from app import security

        with patch.dict(os.environ, {"SCALPER_SESSION_SECRET": "test-secret"}):
            token = security.create_session_token(60)
            self.assertTrue(security.verify_session_token(token))
            self.assertFalse(security.verify_session_token(token + "x"))
            expired = security.create_session_token(-1)
            self.assertFalse(security.verify_session_token(expired))

    def test_login_rate_limit_clears_after_success(self):
        from app import security

        security._login_failures.clear()
        for index in range(5):
            security.record_login_result("client", False, now=100 + index)
        self.assertFalse(security.login_allowed("client", now=200))
        security.record_login_result("client", True, now=200)
        self.assertTrue(security.login_allowed("client", now=200))

    def test_private_provider_url_is_rejected_by_default(self):
        from app import security

        with patch.dict(os.environ, {"LLM_ALLOW_PRIVATE_PROVIDER": "0"}), \
             patch("app.security.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaisesRegex(ValueError, "özel/yerel"):
                security.validate_provider_url("https://provider.example/v1")

    def test_plain_http_provider_is_rejected_by_default(self):
        from app import security

        with patch.dict(os.environ, {"LLM_ALLOW_PRIVATE_PROVIDER": "0"}):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                security.validate_provider_url("http://provider.example/v1")

    def test_provider_redirects_are_rejected_before_forwarding_credentials(self):
        from app.security import _ValidatedRedirectHandler

        with self.assertRaisesRegex(HTTPError, "redirects are forbidden"):
            _ValidatedRedirectHandler().redirect_request(None, None, 302, "Found", {}, "https://other.example/v1")

    def test_private_provider_requires_explicit_opt_in(self):
        from app import security

        with patch.dict(os.environ, {"LLM_ALLOW_PRIVATE_PROVIDER": "1"}), \
             patch("app.security.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 8080))]):
            self.assertEqual(security.validate_provider_url("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1")

    def test_a2a_route_requires_configured_secret(self):
        source = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('if not secret:\n        raise HTTPException(status_code=503', source)
        self.assertIn('and os.getenv("A2A_SHARED_SECRET", "").strip()', source)


class A2AReplayBehavior(unittest.IsolatedAsyncioTestCase):
    async def test_inbound_message_id_is_inserted_only_once(self):
        from app import database

        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("""CREATE TABLE a2a_messages(message_id TEXT PRIMARY KEY, correlation_id TEXT,
          direction TEXT, message_type TEXT, sender TEXT, recipient TEXT, status TEXT, payload TEXT,
          created_at REAL, delivered_at REAL, acknowledged_at REAL, last_error TEXT, attempts INTEGER)""")
        async def run(operation): return operation(conn)
        message = {"message_id": "m1", "type": "research_result", "from": "peer", "to": "scalper",
                   "created_at": time.time(), "paper_only": True}
        with patch("app.database._run_db", new=run):
            first = await database.save_a2a_message(message, direction="inbound", status="received", insert_only=True)
            second = await database.save_a2a_message(message, direction="inbound", status="received", insert_only=True)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM a2a_messages").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
