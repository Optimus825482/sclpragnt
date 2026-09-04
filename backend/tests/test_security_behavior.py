import os
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError


class SecurityBehavior(unittest.TestCase):
    def test_signed_session_expires_and_detects_tampering(self):
        from app import security

        with patch.dict(os.environ, {"SCALPER_SESSION_SECRET": "test-secret"}):
            token = security.create_session_token(60)
            self.assertTrue(security.verify_session_token(token))
            self.assertFalse(security.verify_session_token(token + "x"))
            # Negatif ttl_seconds token'ı üretildiği anda geçersiz kılar.
            # (Konumsal -1 username'e gider; ttl anahtar kelimeyle verilmeli.)
            expired = security.create_session_token(ttl_seconds=-1)
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
                security._validate_provider_url_sync("https://provider.example/v1")

    def test_plain_http_provider_is_rejected_by_default(self):
        from app import security

        with patch.dict(os.environ, {"LLM_ALLOW_PRIVATE_PROVIDER": "0"}):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                security._validate_provider_url_sync("http://provider.example/v1")

    def test_provider_redirects_are_rejected_before_forwarding_credentials(self):
        from app.security import _ValidatedRedirectHandler

        with self.assertRaisesRegex(HTTPError, "redirects are forbidden"):
            _ValidatedRedirectHandler().redirect_request(None, None, 302, "Found", {}, "https://other.example/v1")

    def test_private_provider_requires_explicit_opt_in(self):
        from app import security

        with patch.dict(os.environ, {"LLM_ALLOW_PRIVATE_PROVIDER": "1"}), \
             patch("app.security.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 8080))]):
            self.assertEqual(security._validate_provider_url_sync("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1")


class ConfigApiBehavior(unittest.IsolatedAsyncioTestCase):
    async def test_config_save_prunes_break_symbols_without_rejecting_valid_symbol(self):
        from app import main

        original = {
            "symbols": list(main.config.SYMBOLS), "ut_symbols": list(main.config.UT_SYMBOLS),
            "order_pct": dict(main.config.SYMBOL_ORDER_PCT),
            "layers": dict(main.config.SYMBOL_PYRAMIDING_LAYERS), "market_symbols": list(main.market.symbols),
        }
        try:
            main.config.SYMBOLS = ["HEMITRY", "ACXTRY", "VICTRY"]
            main.config.UT_SYMBOLS = list(main.config.SYMBOLS)
            main.config.SYMBOL_ORDER_PCT = {"HEMITRY": 0.1, "ACXTRY": 0.2}
            main.config.SYMBOL_PYRAMIDING_LAYERS = {"HEMITRY": 2, "VICTRY": 3}
            with patch("app.main.trading_symbols", new=AsyncMock(return_value=["HEMITRY"])), \
                 patch.object(main.market, "fetch_historical_data", new=AsyncMock()), \
                 patch("app.main.database.get_llm_setting", new=AsyncMock(return_value="{}")), \
                 patch("app.main.database.set_llm_setting", new=AsyncMock()), \
                 patch("app.main.get_config", new=AsyncMock(return_value={"symbols": ["HEMITRY"]})):
                result = await main._apply_config_update({"symbols": ["HEMITRY", "ACXTRY", "VICTRY"]})
            self.assertEqual(main.config.SYMBOLS, ["HEMITRY"])
            self.assertEqual(result["removed_invalid_symbols"], ["ACXTRY", "VICTRY"])
            self.assertEqual(main.config.SYMBOL_ORDER_PCT, {"HEMITRY": 0.1})
            self.assertEqual(main.config.SYMBOL_PYRAMIDING_LAYERS, {"HEMITRY": 2})
        finally:
            main.config.SYMBOLS = original["symbols"]
            main.config.UT_SYMBOLS = original["ut_symbols"]
            main.config.SYMBOL_ORDER_PCT = original["order_pct"]
            main.config.SYMBOL_PYRAMIDING_LAYERS = original["layers"]
            main.market.symbols = original["market_symbols"]

    async def test_config_validation_failure_is_a_json_response(self):
        from app.main import update_config

        response = await update_config({"max_open_positions": 501}, request=None)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.media_type, "application/json")
        self.assertIn(b'"code":"invalid_configuration"', response.body)
        self.assertIn(b'"detail":"max_open_positions 0 (s', response.body)

    async def test_config_runtime_failure_is_a_safe_json_response(self):
        from app.main import update_config

        with patch("app.main._apply_config_update", new=AsyncMock(side_effect=RuntimeError("exchangeInfo unavailable"))):
            response = await update_config({"symbols": ["BTCTRY"]}, request=None)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.media_type, "application/json")
        self.assertIn(b'"code":"settings_service_unavailable"', response.body)
        self.assertNotIn(b"exchangeInfo unavailable", response.body)


if __name__ == "__main__":
    unittest.main()
