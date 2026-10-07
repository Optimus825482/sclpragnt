"""P1-4/P1-5/P1-7 güvenlik düzeltmeleri için odaklı testler (2026-10-07).

Kapsam:
- P1-4: /api/alerts (POST/PATCH/DELETE), /api/radar/execute,
  /api/symbol-activity/refresh uçlarında yönetici kapısı; LLM paper işlem
  araçlarının (place/cancel/modify_paper_order, create_market_alert) nazik reddi.
- P1-5: login rate-limit IP'nin spoof edilemez olması (trusted_client_ip),
  WebSocket Origin allowlist, oturumun cihaz parmak izine bağlanması.
- P1-7: SSE kuyruk poll'ünün zamanında dönmesi (thread sızıntısı yok).
"""
import os
import pathlib
import queue
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _request(headers=None, cookies=None, peer="203.0.113.5", ua=None):
    request = MagicMock()
    request.headers = dict(headers or {})
    if ua is not None:
        request.headers.setdefault("user-agent", ua)
    request.cookies = dict(cookies or {})
    request.client = MagicMock(host=peer)
    return request


class AdminGateRouteTests(unittest.IsolatedAsyncioTestCase):
    """P1-4: mutasyon uçları admin olmayan oturumda 403 döner."""

    async def _assert_403(self, coro):
        with patch("app.security.request_user", return_value={"username": "ali", "role": "user"}):
            with self.assertRaises(HTTPException) as ctx:
                await coro
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_create_alert_requires_admin(self):
        from app import main
        await self._assert_403(main.create_alert(
            {"symbol": "BTCTRY", "operator": "gt", "threshold": 1}, _request()))

    async def test_update_alert_requires_admin(self):
        from app import main
        await self._assert_403(main.update_alert(5, {"threshold": 2}, _request()))

    async def test_delete_alert_requires_admin(self):
        from app import main
        await self._assert_403(main.delete_alert(5, _request()))

    async def test_radar_execute_requires_admin(self):
        from app import main
        await self._assert_403(main.execute_gainers_radar(_request()))

    async def test_symbol_activity_refresh_requires_admin(self):
        from app import main
        await self._assert_403(main.refresh_symbol_activity_manual(_request()))

    async def test_admin_passes_gate_on_delete_alert(self):
        """Admin oturum kapıyı geçer (403 FIRLATMAZ; DB çağrısı mock'lanır)."""
        from app import main
        with patch("app.security.request_user", return_value={"username": "admin", "role": "admin"}), \
             patch.object(sys.modules["app.main"].database, "delete_alert_rule",
                          AsyncMock(return_value=True)):
            result = await main.delete_alert(5, _request())
        self.assertTrue(result["ok"])


class LlmToolAdminGuardTests(unittest.TestCase):
    """P1-4: LLM araç reddi — admin değilse nazik hata, admin ise izin (None)."""

    def test_non_admin_denied_with_graceful_error(self):
        from app.routers.llm_chat import _llm_admin_denied
        denied = _llm_admin_denied({"username": "ali", "role": "user"})
        self.assertIsInstance(denied, dict)
        self.assertFalse(denied["ok"])
        self.assertIn("error", denied)
        self.assertFalse(denied["retryable"])

    def test_missing_principal_denied(self):
        from app.routers.llm_chat import _llm_admin_denied
        self.assertIsInstance(_llm_admin_denied(None), dict)
        self.assertIsInstance(_llm_admin_denied({}), dict)

    def test_admin_allowed(self):
        from app.routers.llm_chat import _llm_admin_denied
        self.assertIsNone(_llm_admin_denied({"username": "admin", "role": "admin"}))
        # Rol büyük harfle gelse de izin verilir (normalize).
        self.assertIsNone(_llm_admin_denied({"role": "ADMIN"}))


class TrustedClientIpTests(unittest.TestCase):
    """P1-5: X-Real-IP YALNIZ güvenilir proxy peer'ından gelirse kabul edilir."""

    def test_spoofed_header_from_untrusted_peer_is_ignored(self):
        from app import security
        request = _request(headers={"X-Real-IP": "1.1.1.1"}, peer="203.0.113.5")
        self.assertEqual("203.0.113.5", security.trusted_client_ip(request))

    def test_header_trusted_when_peer_is_proxy(self):
        from app import security
        request = _request(headers={"X-Real-IP": "1.1.1.1"}, peer="172.18.0.5")
        self.assertEqual("1.1.1.1", security.trusted_client_ip(request))

    def test_no_header_returns_peer(self):
        from app import security
        request = _request(peer="198.51.100.7")
        self.assertEqual("198.51.100.7", security.trusted_client_ip(request))

    def test_custom_trusted_proxy_env(self):
        from app import security
        with patch.dict(os.environ, {"SCALPER_TRUSTED_PROXIES": "203.0.113.5"}):
            request = _request(headers={"X-Real-IP": "1.1.1.1"}, peer="203.0.113.5")
            self.assertEqual("1.1.1.1", security.trusted_client_ip(request))


class WebSocketOriginTests(unittest.TestCase):
    """P1-5: cross-site WebSocket hijacking koruması (Origin allowlist)."""

    def test_absent_origin_allowed(self):
        from app import security
        self.assertTrue(security.origin_allowed(None, "app.example.com"))

    def test_same_origin_allowed(self):
        from app import security
        self.assertTrue(security.origin_allowed("https://app.example.com", "app.example.com"))

    def test_cross_origin_rejected(self):
        from app import security
        self.assertFalse(security.origin_allowed("https://evil.example", "app.example.com"))

    def test_explicit_allowlist_permits(self):
        from app import security
        with patch.dict(os.environ, {"SCALPER_WS_ALLOWED_ORIGINS": "https://extra.example"}):
            self.assertTrue(security.origin_allowed("https://extra.example", "app.example.com"))


class SessionFingerprintTests(unittest.TestCase):
    """P1-5: oturum token'ı cihaz (User-Agent) parmak izine bağlanır."""

    def test_fingerprint_bound_token_rejected_on_mismatch(self):
        from app import security
        with patch.dict(os.environ, {"SCALPER_SESSION_SECRET": "p1-secret"}):
            security.set_user_session_version("admin", 0)
            token = security.create_session_token("admin", "admin", ttl_seconds=60,
                                                  client_fingerprint="Mozilla/5.0")
            self.assertTrue(security.verify_session_token(token, "Mozilla/5.0"))
            self.assertFalse(security.verify_session_token(token, "curl/8"))
            self.assertIsNone(security.session_user(token, "curl/8"))

    def test_unbound_token_still_valid_without_fingerprint(self):
        from app import security
        with patch.dict(os.environ, {"SCALPER_SESSION_SECRET": "p1-secret"}):
            security.set_user_session_version("admin", 0)
            token = security.create_session_token("admin", "admin", ttl_seconds=60)
            self.assertTrue(security.verify_session_token(token))

    def test_client_fingerprint_reads_user_agent(self):
        from app import security
        self.assertEqual("TestAgent/9", security.client_fingerprint(_request(ua="TestAgent/9")))
        self.assertEqual("", security.client_fingerprint(_request()))


class SseQueuePollTests(unittest.TestCase):
    """P1-7: kuyruk poll'ü deadline'de zamaninda döner (thread sizintisi yok)."""

    def test_returns_item_when_present(self):
        from app import llm_analysis
        q = queue.Queue()
        q.put(("line", "data: x"))
        self.assertEqual(("line", "data: x"),
                         llm_analysis._poll_queue_until(q, time.monotonic() + 1.0))

    def test_returns_none_after_deadline(self):
        from app import llm_analysis
        q = queue.Queue()
        start = time.monotonic()
        self.assertEqual((None, None), llm_analysis._poll_queue_until(q, start + 0.05))
        # Blok süresi makul (sonsuz bekleme yok).
        self.assertLess(time.monotonic() - start, 1.0)


if __name__ == "__main__":
    unittest.main()
