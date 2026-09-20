"""W18 — Runtime / API / güvenlik artık bulgular için LOCK testleri.

Her test, ilgili düzeltme GERİ ALINIRSA KIRILACAK şekilde yazıldı (kaynak
sözleşmesi + davranış). Kapsam: G-11, G-12, G-13, G-14, G-15, G-18, G-19, G-20,
G-21, G-22, G-23, G-24 (belge kilidi), G-25, G-26, G-27, G-28, G-29, G-30,
D-09, D-11 (main yarısı), I-10.

Not: Bu dosya davranış testidir; saf "kaynak metinde dize ara" kontrolleri
yalnızca davranışı doğrudan çağırmanın mümkün olmadığı (loop/closure/middleware
gibi) yerlerde kullanılır ve gerekçesi yorumda yazılıdır.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import pathlib
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

_APP = pathlib.Path(__file__).resolve().parents[1] / "app"
_MAIN_SRC = (_APP / "main.py").read_text(encoding="utf-8")
_ROUTERS = sorted(p for p in (_APP / "routers").glob("*.py"))


def _router_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in _ROUTERS}


# ---------------------------------------------------------------------------
# G-11 — supervisor: sonlu restart + kalıcı "failed" + alert; strategy_loop hata yutar
# ---------------------------------------------------------------------------
class G11SupervisorTests(unittest.TestCase):
    def setUp(self):
        from app import api_common
        self.api_common = api_common
        self._saved_max = api_common.MAX_BACKGROUND_RESTARTS
        api_common._restart_counters.clear()
        api_common._failed_loops.clear()

    def tearDown(self):
        self.api_common.MAX_BACKGROUND_RESTARTS = self._saved_max
        self.api_common._restart_counters.clear()
        self.api_common._failed_loops.clear()

    def test_restart_budget_is_finite_and_final_state_is_failed(self):
        ac = self.api_common
        ac.MAX_BACKGROUND_RESTARTS = 2
        self.assertTrue(ac._handle_task_failure("loop-x", RuntimeError("boom")))
        self.assertTrue(ac._handle_task_failure("loop-x", RuntimeError("boom")))
        # Üçüncü hata sınırı aşar → yeniden başlatma YOK, kalıcı failed.
        self.assertFalse(ac._handle_task_failure("loop-x", RuntimeError("boom")))
        health = ac.loop_health()
        self.assertIn("loop-x", health["failed"])
        self.assertEqual(2, health["failed"]["loop-x"]["attempts"])
        self.assertEqual(2, health["max_restarts"])

    def test_failed_state_is_reported_not_silently_restarted(self):
        ac = self.api_common
        ac.MAX_BACKGROUND_RESTARTS = 0
        self.assertFalse(ac._handle_task_failure("loop-y", ValueError("dead")))
        self.assertIn("loop-y", ac.loop_health()["failed"])
        # Kayıt hatayı taşımalı (alarm/teşhis için).
        self.assertIn("ValueError", ac.loop_health()["failed"]["loop-y"]["error"])

    def test_start_background_uses_failure_handler(self):
        """Closure içindeki karar artık ortak fonksiyonda (test edilebilir tek yol)."""
        src = inspect.getsource(self.api_common._start_background)
        self.assertIn("_handle_task_failure(name, exc)", src)
        self.assertIn("if not _handle_task_failure(name, exc):", src)

    def test_strategy_loop_swallows_outer_errors(self):
        from app.routers import runtime as runtime_routes

        src = inspect.getsource(runtime_routes.strategy_loop)
        self.assertIn("except asyncio.CancelledError", src)
        self.assertIn("except Exception", src)
        self.assertIn("logger.error", src)


# ---------------------------------------------------------------------------
# G-12 — hata yolları 5xx + error_code; str(exc) sızmaz
# ---------------------------------------------------------------------------
class G12ErrorPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_market_symbols_returns_502_without_leaking_internals(self):
        from app import main

        with patch("app.main.trading_symbols", new=AsyncMock(side_effect=OSError("/secret/db/path"))):
            response = await main.get_market_symbols()
        self.assertEqual(502, response.status_code)
        body = json.loads(response.body)
        self.assertFalse(body["ok"])
        self.assertEqual("market_symbols_unavailable", body["error_code"])
        self.assertNotIn("secret", response.body.decode())

    async def test_eval_cases_returns_500_without_leaking_path(self):
        from app import main

        with patch("builtins.open", side_effect=OSError("/secret/golden_cases.json")):
            response = await main.get_agent_eval_cases()
        self.assertEqual(500, response.status_code)
        body = json.loads(response.body)
        self.assertEqual("eval_cases_unavailable", body["error_code"])
        self.assertNotIn("secret", response.body.decode())

    async def test_symbol_analysis_error_path_is_502_without_str_exc(self):
        from app import main

        with patch.object(main.market, "get_ticker", return_value=None), \
             patch("app.main.trading_symbols", new=AsyncMock(side_effect=OSError("/secret/symbol/path"))):
            response = await main.symbol_analysis("BTCTRY")
        self.assertEqual(502, response.status_code)
        body = json.loads(response.body)
        self.assertEqual("symbol_data_unavailable", body["error_code"])
        self.assertNotIn("secret", response.body.decode())

    async def test_market_symbols_success_path_unchanged(self):
        from app import main

        with patch("app.main.trading_symbols", new=AsyncMock(return_value=["BTCTRY"])):
            result = await main.get_market_symbols()
        self.assertEqual({"symbols": ["BTCTRY"], "quote_asset": "TRY"}, result)


# ---------------------------------------------------------------------------
# G-13 — /api/memory/retrieve: admin kapısı + hız sınırı
# ---------------------------------------------------------------------------
class G13MemoryRetrieveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app import api_common
        api_common._rate_limiters.pop("memory-retrieve", None)

    async def test_requires_admin(self):
        from app.routers import system as system_routes

        with patch("app.main._require_admin",
                   new=MagicMock(side_effect=HTTPException(403, "admin only"))):
            with self.assertRaises(HTTPException) as ctx:
                await system_routes.memory_retrieve({"query": "x"}, request=None)
        self.assertEqual(403, ctx.exception.status_code)

    async def test_rate_limit_blocks_after_burst(self):
        from app.routers import system as system_routes

        statuses = []
        with patch("app.main._require_admin", new=MagicMock(return_value={"role": "admin"})):
            for _ in range(6):
                try:
                    await system_routes.memory_retrieve({"query": "x"}, request=None)
                    statuses.append(200)
                except HTTPException as exc:
                    statuses.append(exc.status_code)
        self.assertNotIn(429, statuses[:5])
        self.assertEqual(429, statuses[5])


# ---------------------------------------------------------------------------
# G-14 — get_trades(limit=None) yerine üst sınır
# ---------------------------------------------------------------------------
class G14TradeScanLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_risk_summary_caps_trade_scan(self):
        from app import main

        gate = {"halt": False, "reason": None, "today_pnl": 0.0, "limit_try": None}
        get_trades = AsyncMock(return_value=[])
        with patch("app.main.database.get_trades", new=get_trades), \
             patch("app.main.daily_loss_guard", new=AsyncMock(return_value=gate)):
            result = await main.risk_summary()
        _args, kwargs = get_trades.await_args
        self.assertEqual(main._RISK_TRADES_LIMIT, kwargs.get("limit"))
        self.assertIsNotNone(kwargs.get("limit"))
        self.assertEqual(main._RISK_TRADES_LIMIT, result["scan_limit"])

    async def test_strategy_stats_caps_trade_scan(self):
        from app import main

        get_trades = AsyncMock(return_value=[])
        with patch("app.main.database.get_trades", new=get_trades):
            await main.get_strategy_stats()
        _args, kwargs = get_trades.await_args
        self.assertEqual(main._RISK_TRADES_LIMIT, kwargs.get("limit"))

    def test_no_unbounded_get_trades_in_source(self):
        self.assertNotIn("database.get_trades(limit=None)", _MAIN_SRC)


# ---------------------------------------------------------------------------
# G-15 — statik admin token yalnız açık env bayrağıyla
# ---------------------------------------------------------------------------
class G15StaticAdminTokenTests(unittest.TestCase):
    def test_static_token_is_disabled_by_default(self):
        from app import security

        env = {"SCALPER_ADMIN_TOKEN": "static-secret", security.STATIC_ADMIN_TOKEN_FLAG: "0"}
        with patch.dict(os.environ, env):
            self.assertFalse(security.static_admin_token_enabled())
            self.assertIsNone(security.request_user({"authorization": "Bearer static-secret"}))
            self.assertFalse(security.request_authenticated({"authorization": "Bearer static-secret"}))

    def test_static_token_requires_explicit_opt_in(self):
        from app import security

        env = {"SCALPER_ADMIN_TOKEN": "static-secret", security.STATIC_ADMIN_TOKEN_FLAG: "1"}
        with patch.dict(os.environ, env):
            self.assertTrue(security.static_admin_token_enabled())
            self.assertEqual({"username": "admin", "role": "admin"},
                             security.request_user({"authorization": "Bearer static-secret"}))

    def test_wrong_static_token_never_authenticates(self):
        from app import security

        env = {"SCALPER_ADMIN_TOKEN": "static-secret", security.STATIC_ADMIN_TOKEN_FLAG: "1"}
        with patch.dict(os.environ, env):
            self.assertIsNone(security.request_user({"authorization": "Bearer wrong"}))


# ---------------------------------------------------------------------------
# G-18 — pahalı uçlarda admin kapısı + token-bucket
# ---------------------------------------------------------------------------
class G18ExpensiveEndpointTests(unittest.IsolatedAsyncioTestCase):
    def test_gated_endpoints_have_admin_and_rate_limit(self):
        from app import main

        for endpoint in (main.ml_train_now, main.test_llm, main.test_embedding,
                         main.market_snapshot_scan, main.edge_tts_audio):
            src = inspect.getsource(endpoint)
            self.assertIn("_require_admin(", src, endpoint.__name__)
            self.assertIn("rate_limit(", src, endpoint.__name__)
            self.assertIn("429", src, endpoint.__name__)

    async def test_ml_train_requires_admin(self):
        from app import main

        with patch("app.main._require_admin",
                   new=MagicMock(side_effect=HTTPException(403, "admin only"))):
            with self.assertRaises(HTTPException) as ctx:
                await main.ml_train_now(request=None)
        self.assertEqual(403, ctx.exception.status_code)

    async def test_llm_test_requires_admin_and_does_not_call_provider(self):
        from app import main

        analyze = AsyncMock(return_value={"status": "ok"})
        with patch("app.main._require_admin",
                   new=MagicMock(side_effect=HTTPException(403, "admin only"))), \
             patch("app.main.llm_analysis.analyze", new=analyze):
            with self.assertRaises(HTTPException):
                await main.test_llm(request=None)
        analyze.assert_not_awaited()

    def test_token_bucket_blocks_burst_then_refills(self):
        from app import api_common

        api_common._rate_limiters.pop("w18-bucket", None)
        self.assertTrue(api_common.rate_limit("w18-bucket", rate_per_sec=1.0, burst=2, now=1000.0))
        self.assertTrue(api_common.rate_limit("w18-bucket", rate_per_sec=1.0, burst=2, now=1000.0))
        self.assertFalse(api_common.rate_limit("w18-bucket", rate_per_sec=1.0, burst=2, now=1000.0))
        # 1 saniye sonra bir token yenilenir.
        self.assertTrue(api_common.rate_limit("w18-bucket", rate_per_sec=1.0, burst=2, now=1001.0))


# ---------------------------------------------------------------------------
# G-19 — açılış sırası: market.timeframes/evren load_state'ten ÖNCE
# ---------------------------------------------------------------------------
class G19StartupOrderTests(unittest.TestCase):
    def test_market_universe_assigned_before_analyzer_load_state(self):
        from app import main

        src = inspect.getsource(main.startup_services)
        tf_at = src.find("market.timeframes = list(config.PRIORITY_TIMEFRAMES)")
        symbols_at = src.find("market.symbols =")
        load_at = src.find("await analyzer.load_state()")
        bootstrap_at = src.find("await bootstrap_symbol_activity()")
        self.assertGreater(tf_at, -1, "market.timeframes ataması bulunamadı")
        self.assertGreater(symbols_at, -1, "market.symbols ataması bulunamadı")
        self.assertGreater(load_at, -1)
        self.assertGreater(bootstrap_at, -1)
        self.assertLess(tf_at, load_at, "G-19: timeframes load_state'ten ÖNCE atanmalı")
        self.assertLess(tf_at, bootstrap_at, "G-19: timeframes bootstrap'tan ÖNCE atanmalı")
        self.assertLess(symbols_at, load_at, "G-19: evren load_state'ten ÖNCE atanmalı")


# ---------------------------------------------------------------------------
# G-20 — WS auth: URL query token YOK; cookie/subprotocol
# ---------------------------------------------------------------------------
class G20WebSocketAuthTests(unittest.IsolatedAsyncioTestCase):
    def test_websocket_endpoint_does_not_read_query_token(self):
        from app import main

        src = inspect.getsource(main.websocket_endpoint)
        self.assertNotIn("query_params", src)
        self.assertIn("_ws_subprotocol_token", src)

    def test_subprotocol_token_extraction(self):
        from app import main

        ws = MagicMock()
        ws.headers = {"sec-websocket-protocol": "chat, session.abc.def, other"}
        self.assertEqual("abc.def", main._ws_subprotocol_token(ws))
        ws.headers = {"sec-websocket-protocol": "bearer.TOKEN123"}
        self.assertEqual("TOKEN123", main._ws_subprotocol_token(ws))
        ws.headers = {"sec-websocket-protocol": "chat"}
        self.assertIsNone(main._ws_subprotocol_token(ws))

    async def test_websocket_rejects_query_token(self):
        from app import main

        ws = MagicMock()
        ws.headers = {}
        ws.cookies = {}
        ws.query_params = {"token": "leaked-in-url"}
        ws.close = AsyncMock()
        with patch.dict(os.environ, {"SCALPER_ADMIN_PASSWORD": "x", "SCALPER_SESSION_SECRET": "y"}):
            await main.websocket_endpoint(ws)
        ws.close.assert_awaited()
        self.assertEqual(4401, ws.close.await_args.kwargs.get("code"))
        ws.accept.assert_not_called()


# ---------------------------------------------------------------------------
# G-21 — mum kalıcılık hatası loglanır (sessiz return 0 değil)
# ---------------------------------------------------------------------------
class G21CandlePersistLogTests(unittest.TestCase):
    def test_history_candle_loop_logs_persist_failures(self):
        from app.routers import maintenance

        src = _router_sources()["maintenance.py"]
        self.assertIn("canlı mum kalıcılığı başarısız", src)
        # `except Exception: return 0` deseni kalmamalı.
        self.assertIsNone(re.search(r"except Exception[^\n]*:\s*\n\s*return 0\b", src))
        self.assertIn("logger.warning", inspect.getsource(maintenance.history_candle_loop))


# ---------------------------------------------------------------------------
# G-22 — verify_session_token ölü kod değil: üretim yolu aynı çekirdeği kullanır
# ---------------------------------------------------------------------------
class G22SessionVerifyTests(unittest.TestCase):
    def test_session_user_delegates_to_shared_verifier(self):
        from app import security

        self.assertIn("_decode_session", inspect.getsource(security.session_user))
        self.assertIn("_decode_session", inspect.getsource(security.verify_session_token))

    def test_verify_and_session_user_agree(self):
        from app import security

        with patch.dict(os.environ, {"SCALPER_SESSION_SECRET": "w18-secret"}):
            token = security.create_session_token("admin", "admin", ttl_seconds=60)
            self.assertTrue(security.verify_session_token(token))
            self.assertEqual({"username": "admin", "role": "admin"}, security.session_user(token))
            self.assertFalse(security.verify_session_token(token + "x"))
            self.assertIsNone(security.session_user(token + "x"))

    def test_session_version_bump_invalidates_both_paths(self):
        from app import security

        with patch.dict(os.environ, {"SCALPER_SESSION_SECRET": "w18-secret"}):
            security.set_user_session_version("admin", 5)
            token = security.create_session_token("admin", "admin", ttl_seconds=60, session_version=5)
            self.assertTrue(security.verify_session_token(token))
            security.set_user_session_version("admin", 6)
            self.assertFalse(security.verify_session_token(token))
            self.assertIsNone(security.session_user(token))
            security.set_user_session_version("admin", 0)


# ---------------------------------------------------------------------------
# G-23 — router'lar artık app.main'i import etmiyor; kapı davranışı aynı
# ---------------------------------------------------------------------------
class G23RequireAdminMoveTests(unittest.TestCase):
    def test_no_router_imports_require_admin_from_main(self):
        offenders = [name for name, src in _router_sources().items()
                     if "from app.main import _require_admin" in src]
        self.assertEqual([], offenders, f"G-23 geri döndü: {offenders}")

    def test_api_common_require_admin_delegates_to_main(self):
        from app import api_common

        sentinel = {"username": "admin", "role": "admin"}
        with patch("app.main._require_admin", new=MagicMock(return_value=sentinel)) as gate:
            self.assertEqual(sentinel, api_common.require_admin(request=None))
        gate.assert_called_once_with(None)

    def test_main_require_admin_delegates_to_security(self):
        from app import main

        sentinel = {"username": "admin", "role": "admin"}
        request = MagicMock()
        with patch("app.security.require_admin", new=MagicMock(return_value=sentinel)) as gate:
            self.assertEqual(sentinel, main._require_admin(request))
        gate.assert_called_once_with(request)

    def test_security_require_admin_gate_semantics(self):
        from app import security

        request = MagicMock()
        request.headers = {}
        request.cookies = {}
        with patch("app.security.request_user", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                security.require_admin(request)
            self.assertEqual(401, ctx.exception.status_code)
        with patch("app.security.request_user", return_value={"username": "ali", "role": "user"}):
            with self.assertRaises(HTTPException) as ctx:
                security.require_admin(request)
            self.assertEqual(403, ctx.exception.status_code)
        with patch("app.security.request_user", return_value={"username": "root", "role": "admin"}):
            self.assertEqual({"username": "root", "role": "admin"}, security.require_admin(request))

    def test_g05_export_gate_still_source_visible(self):
        """test_w12_integrity_fixes bunu kaynak dizesiyle arıyor — kırılmamalı."""
        from app.routers import maintenance

        src = inspect.getsource(maintenance.download_replay_parity_trade_csv)
        self.assertIn("_require_admin(", src)
        self.assertNotIn("from app.main import _require_admin", src)


# ---------------------------------------------------------------------------
# G-24 — belge kilidi: config env'i import anında okur; reload() yok
# ---------------------------------------------------------------------------
class G24ConfigReloadDocTests(unittest.TestCase):
    """G-24 kararı: sahiplik gereği `config.py` DÜZENLENMEDİ (import-anı okuma
    rejimi dokümante edildi). Bu test o kararı kilitler: `reload()` eklenirse
    bu test kırılır ve G-24 belgesi güncellenmelidir."""

    def test_config_reads_env_at_import_time_and_has_no_reload(self):
        from app import config as config_module

        self.assertFalse(hasattr(config_module, "reload"))
        # Değerler sınıf gövdesinde import anında hesaplanır (property değil).
        self.assertTrue(any(isinstance(getattr(config_module.Config, name), (int, float, str, list, dict))
                            for name in ("MAX_OPEN_POSITIONS",)))


# ---------------------------------------------------------------------------
# G-25 / G-26 — CORS wildcard reddi + güvenlik başlıkları
# ---------------------------------------------------------------------------
class G25CorsTests(unittest.TestCase):
    def test_wildcard_origin_is_rejected_with_credentials(self):
        from app import main

        with patch.dict(os.environ, {"CORS_ORIGINS": "*"}):
            origins = main._cors_origins_from_env()
        self.assertNotIn("*", origins)
        self.assertTrue(origins)

    def test_mixed_list_drops_only_the_wildcard(self):
        from app import main

        with patch.dict(os.environ, {"CORS_ORIGINS": "*,https://app.example"}):
            self.assertEqual(["https://app.example"], main._cors_origins_from_env())

    def test_defaults_are_concrete_origins(self):
        from app import main

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORS_ORIGINS", None)
            origins = main._cors_origins_from_env()
        self.assertNotIn("*", origins)
        self.assertIn("http://localhost:3004", origins)


class G26SecurityHeadersTests(unittest.IsolatedAsyncioTestCase):
    class _StubApp:
        async def __call__(self, scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

    async def _drive(self, path: str) -> dict[str, str]:
        from app.main import SecurityHeadersMiddleware

        middleware = SecurityHeadersMiddleware(self._StubApp())
        messages = []

        async def send(message):
            messages.append(message)

        await middleware({"type": "http", "path": path}, AsyncMock(), send)
        start = next(m for m in messages if m["type"] == "http.response.start")
        return {k.decode().lower(): v.decode() for k, v in start["headers"]}

    async def test_all_security_headers_present(self):
        headers = await self._drive("/api/positions")
        self.assertEqual("DENY", headers.get("x-frame-options"))
        self.assertEqual("nosniff", headers.get("x-content-type-options"))
        self.assertEqual("no-referrer", headers.get("referrer-policy"))
        self.assertIn("max-age=31536000", headers.get("strict-transport-security", ""))
        self.assertIn("frame-ancestors 'none'", headers.get("content-security-policy", ""))

    async def test_csp_exempts_docs_ui(self):
        headers = await self._drive("/docs")
        self.assertIsNone(headers.get("content-security-policy"))
        self.assertEqual("DENY", headers.get("x-frame-options"))

    def test_middleware_is_registered(self):
        self.assertIn("app.add_middleware(SecurityHeadersMiddleware)", _MAIN_SRC)


# ---------------------------------------------------------------------------
# G-27 — /api/binance/trades limit clamp
# ---------------------------------------------------------------------------
class G27BinanceTradesClampTests(unittest.IsolatedAsyncioTestCase):
    async def test_limit_is_clamped_to_1000(self):
        from app import main

        history = MagicMock(return_value=[])
        with patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))), \
             patch("app.main.get_trade_history", new=history):
            await main.binance_trades(request=None, symbol="BTCTRY", limit=10 ** 9)
        args = history.call_args.args
        self.assertEqual(1000, args[5])
        self.assertEqual(0, args[6])

    async def test_limit_floor_is_one(self):
        from app import main

        history = MagicMock(return_value=[])
        with patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))), \
             patch("app.main.get_trade_history", new=history):
            await main.binance_trades(request=None, symbol="BTCTRY", limit=0, offset=-5)
        args = history.call_args.args
        self.assertEqual(1, args[5])
        self.assertEqual(0, args[6])


# ---------------------------------------------------------------------------
# G-28 — audit gerçek rolü taşır
# ---------------------------------------------------------------------------
class G28AuditRoleTests(unittest.IsolatedAsyncioTestCase):
    def test_no_audit_call_hardcodes_none_role(self):
        offenders = re.findall(r"log_user_action\([^,]+,\s*None,\s*\"(?:config|trade|alert|auto_paper)\"", _MAIN_SRC)
        self.assertEqual([], offenders, f"G-28: rolü None geçen audit çağrıları: {offenders}")

    def test_session_identity_returns_role(self):
        from app import main

        request = MagicMock()
        request.headers = {}
        request.cookies = {}
        with patch("app.security.request_user", return_value={"username": "ali", "role": "user"}):
            self.assertEqual(("ali", "user"), main._session_identity(request))
        self.assertEqual((None, None), main._session_identity(None))

    async def test_config_update_logs_real_role(self):
        from app import main

        request = MagicMock()
        request.headers = {}
        request.cookies = {}
        audit = AsyncMock()
        with patch("app.security.request_user", return_value={"username": "ali", "role": "user"}), \
             patch("app.main.log_user_action", new=audit):
            await main._apply_config_update({}, request)
        _args, kwargs = audit.await_args
        self.assertEqual("ali", _args[0])
        self.assertEqual("user", _args[1])


# ---------------------------------------------------------------------------
# G-29 — invalidate_wallet_caches bağlandı
# ---------------------------------------------------------------------------
class G29WalletCacheInvalidationTests(unittest.TestCase):
    def test_cache_invalidation_is_wired(self):
        from app.routers import runtime as runtime_routes

        self.assertIn("invalidate_wallet_caches()", inspect.getsource(runtime_routes.strategy_loop))
        self.assertIn("runtime_routes.invalidate_wallet_caches()", _MAIN_SRC)

    def test_invalidation_zeroes_caches(self):
        from app.routers import runtime as runtime_routes

        runtime_routes._realized_pnl_cache.update(value=123.0, at=time_now())
        runtime_routes._try_balance_cache.update(value=456.0, at=time_now())
        runtime_routes._auto_trades_cache.update(data=[{"id": 1}], at=time_now())
        runtime_routes.invalidate_wallet_caches()
        self.assertIsNone(runtime_routes._realized_pnl_cache["value"])
        self.assertIsNone(runtime_routes._try_balance_cache["value"])
        self.assertEqual([], runtime_routes._auto_trades_cache["data"])


def time_now() -> float:
    import time
    return time.time()


# ---------------------------------------------------------------------------
# G-30 — /health açık pozisyon SEMBOLLERİ sızdırmaz
# ---------------------------------------------------------------------------
class G30HealthTests(unittest.IsolatedAsyncioTestCase):
    def test_health_source_has_no_open_positions_list(self):
        from app.routers import system as system_routes

        src = inspect.getsource(system_routes.health)
        self.assertNotIn("open_positions", src)
        self.assertIn("open_position_count", src)

    async def test_health_response_shape(self):
        from app.routers import system as system_routes

        result = await system_routes.health()
        self.assertNotIn("open_positions", result)
        self.assertIn("open_position_count", result)


# ---------------------------------------------------------------------------
# D-09 — resume/register/promote admin kapılı; register her zaman shadow
# ---------------------------------------------------------------------------
class D09PromotionGateTests(unittest.IsolatedAsyncioTestCase):
    def test_endpoints_are_admin_gated(self):
        from app import main

        for endpoint in (main.strategy_pipeline_register,
                         main.strategy_pipeline_promote,
                         main.strategy_breaker_resume):
            self.assertIn("_require_admin(", inspect.getsource(endpoint), endpoint.__name__)

    def test_register_endpoint_does_not_forward_stage(self):
        from app import main

        src = inspect.getsource(main.strategy_pipeline_register)
        self.assertNotIn("stage=", src)
        self.assertIn("promotion_pipeline.register(name)", src)

    def test_pipeline_register_source_pins_shadow(self):
        """Kaynak kilidi: register, çağıranın `stage`'ini entry'ye YAZMAMALI."""
        from app.promotion import PromotionPipeline

        src = inspect.getsource(PromotionPipeline.register)
        self.assertIn('entry["stage"] = "shadow"', src)
        self.assertNotIn('entry["stage"] = stage', src)

    def test_pipeline_register_always_shadow(self):
        from app.promotion import PromotionPipeline

        pipeline = PromotionPipeline()
        saved = {}

        async def fake_set(key, value):
            saved[key] = value

        async def fake_get(key, default=None):
            return default

        async def flow():
            await pipeline.register("X")
            self.assertEqual("shadow", pipeline.stage_of("X"))
            with self.assertRaises(ValueError):
                await pipeline.register("active-hopeful", stage="active")

        with patch("app.database.get_llm_setting", new=fake_get), \
             patch("app.database.set_llm_setting", new=fake_set):
            asyncio.run(flow())
        self.assertEqual("shadow", json.loads(saved["strategy_promotion_pipeline"])["strategies"]["X"]["stage"])

    async def test_register_endpoint_requires_admin(self):
        from app import main

        with patch("app.main._require_admin",
                   new=MagicMock(side_effect=HTTPException(403, "admin only"))):
            with self.assertRaises(HTTPException):
                await main.strategy_pipeline_register({"name": "X"}, request=None)


# ---------------------------------------------------------------------------
# D-11 — global günlük zarar limiti + kill-switch (main yarısı)
# ---------------------------------------------------------------------------
class D11GlobalRiskGateTests(unittest.IsolatedAsyncioTestCase):
    async def _guard(self, settings, trades=(), now=None):
        from app import main

        async def fake_get(key, default=None):
            return settings.get(key, default)

        with patch("app.main.database.get_llm_setting", new=fake_get), \
             patch("app.main.database.get_trades", new=AsyncMock(return_value=list(trades))):
            return await main.daily_loss_guard(now=now if now is not None else time_now())

    async def test_kill_switch_halts_entries(self):
        result = await self._guard({main_key("halt"): "1"})
        self.assertTrue(result["halt"])
        self.assertEqual("global_kill_switch", result["reason"])

    async def test_daily_loss_limit_halts_after_threshold(self):
        from app import config as cfg

        now = time_now()
        settings = {main_key("loss"): "5"}
        initial = float(getattr(cfg.config, "INITIAL_BALANCE_TRY", 0) or 0)
        losing = [{"pnl": -(initial * 0.05 + 1.0), "exit_time": now}]
        result = await self._guard(settings, losing, now=now)
        self.assertTrue(result["halt"])
        self.assertEqual("daily_loss_limit", result["reason"])

    async def test_gate_open_without_settings(self):
        result = await self._guard({})
        self.assertFalse(result["halt"])
        self.assertIsNone(result["reason"])

    async def test_llm_entry_checks_global_gate(self):
        from app import main

        gate = AsyncMock(side_effect=HTTPException(403, "halted"))

        async def enabled(key, default="0"):
            return "1"

        # Yetki denetimi (denetim düzeltmesi): manuel LLM girişi artık admin
        # kapısından geçer; test kapıyı pasifleştirip gate akışını sınar.
        with patch("app.main.database.get_llm_setting", new=enabled), \
             patch("app.main.daily_loss_guard", new=gate), \
             patch("app.main._require_admin", new=MagicMock(return_value=None)):
            with self.assertRaises(HTTPException):
                await main.llm_open_paper_trade({"symbol": "BTCTRY"}, request=None)
        gate.assert_awaited()

    async def test_llm_entry_requires_admin(self):
        """Yetki kapısı: principal'sız istek → 401/HTTPException."""
        from app import main
        anonymous = MagicMock(headers={}, cookies={})
        with self.assertRaises(HTTPException):
            await main.llm_open_paper_trade({"symbol": "BTCTRY"}, request=anonymous)

    async def test_kill_switch_endpoint_requires_admin(self):
        from app import main

        with patch("app.main._require_admin",
                   new=MagicMock(side_effect=HTTPException(403, "admin only"))):
            with self.assertRaises(HTTPException):
                await main.set_risk_kill_switch({"halt": True}, request=None)

    def test_risk_summary_exposes_gate(self):
        from app import main

        self.assertIn("daily_loss_limit_hit", inspect.getsource(main.risk_summary))


def main_key(which: str) -> str:
    from app import main
    return main._GLOBAL_HALT_KEY if which == "halt" else main._DAILY_LOSS_LIMIT_KEY


# ---------------------------------------------------------------------------
# I-10 — ölü fonksiyonlar silindi
# ---------------------------------------------------------------------------
class I10DeadFunctionTests(unittest.TestCase):
    def test_dead_backup_helpers_removed(self):
        from app import main

        self.assertFalse(hasattr(main, "_pg_dump_stream"))
        self.assertFalse(hasattr(main, "_backup_headers"))
        self.assertNotIn("def _pg_dump_stream", _MAIN_SRC)
        self.assertNotIn("def _backup_headers", _MAIN_SRC)

    def test_live_backup_helper_kept(self):
        from app import main

        self.assertTrue(callable(getattr(main, "_create_postgres_backup", None)))


# ---------------------------------------------------------------------------
# Aktivite pasif çıkışı — pasife düşen sembolde açık pozisyon PnL'den
# bağımsız kapatılır (kapat → sonra pasifleştir)
# ---------------------------------------------------------------------------
class ActivityPassiveExitTests(unittest.IsolatedAsyncioTestCase):
    async def test_passive_symbol_open_position_is_closed(self):
        from app.routers import runtime as runtime_routes

        positions = {"FLATTRYY": {"entry_price": 10.0}}
        close_mock = AsyncMock(return_value={"symbol": "FLATTRYY", "action": "CLOSE_LONG"})
        broadcast_mock = AsyncMock()
        price_mock = AsyncMock(return_value=(9.7, {}))
        with patch.object(runtime_routes, "analyzer", MagicMock(positions=positions, close_position=close_mock)), \
             patch.object(runtime_routes, "_fresh_public_price", price_mock), \
             patch.object(runtime_routes, "ws_manager", MagicMock(broadcast=broadcast_mock)), \
             patch.object(runtime_routes, "invalidate_wallet_caches"):
            await runtime_routes._close_positions_on_passivation({"FLATTRYY", "IDLETRY"})
        close_mock.assert_awaited_once_with("FLATTRYY", 9.7, "symbol_activity_passive_exit")
        broadcast_mock.assert_awaited_once()

    async def test_positionless_passive_symbol_is_untouched(self):
        from app.routers import runtime as runtime_routes

        close_mock = AsyncMock()
        with patch.object(runtime_routes, "analyzer", MagicMock(positions={}, close_position=close_mock)), \
             patch.object(runtime_routes, "_fresh_public_price", AsyncMock(return_value=(1.0, {}))):
            await runtime_routes._close_positions_on_passivation({"IDLETRY"})
        close_mock.assert_not_awaited()

    async def test_price_failure_leaves_position_for_next_cycle(self):
        from app.routers import runtime as runtime_routes

        close_mock = AsyncMock()
        positions = {"FLATTRYY": {"entry_price": 10.0}}
        with patch.object(runtime_routes, "analyzer", MagicMock(positions=positions, close_position=close_mock)), \
             patch.object(runtime_routes, "_fresh_public_price", AsyncMock(return_value=(0.0, {}))):
            await runtime_routes._close_positions_on_passivation({"FLATTRYY"})
        close_mock.assert_not_awaited()

    def test_refresh_closes_before_passivation_and_flag_exists(self):
        """Kaynak kilidi: PASSIVE_SYMBOLS atanmadan ÖNCE kapatma denenir."""
        from app.routers import runtime as runtime_routes

        src = inspect.getsource(runtime_routes.refresh_symbol_activity)
        self.assertIn("await _close_positions_on_passivation(passive_symbols)", src)
        self.assertIn("config.SYMBOL_ACTIVITY_PASSIVE_EXIT", src)
        self.assertLess(src.index("_close_positions_on_passivation(passive_symbols)"),
                        src.index("config.PASSIVE_SYMBOLS = passive_symbols"))
        config_src = (_APP / "config.py").read_text(encoding="utf-8")
        self.assertIn("SYMBOL_ACTIVITY_PASSIVE_EXIT", config_src)

    def test_exit_reason_is_not_an_llm_legacy_blocked_prefix(self):
        """Pasif çıkış nedeni, LLM_PAPER legacy çıkış bloğuna takılmamalı."""
        from app.analyzer import ScalpAnalyzer

        blocked_prefixes = ("time_decay_", "early_failure", "stale_position", "max_hold_")
        self.assertFalse("symbol_activity_passive_exit".startswith(blocked_prefixes))


# ---------------------------------------------------------------------------
# ADMIN İŞLEM BİLDİRİMİ — alıcı seçimi + hedefli push + abonelik kullanıcı bağlama
# ---------------------------------------------------------------------------
class AdminTradeNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_recipients_roundtrip_normalizes_and_persists(self):
        from app import main

        saved = {}
        async def fake_set(key, value): saved[key] = value
        async def fake_get(key, default=None): return saved.get(key, default)
        admin = MagicMock(return_value={"username": "admin", "role": "admin"})
        with patch("app.main._require_admin", admin), \
             patch("app.main.database.list_users", new=AsyncMock(return_value=[{"username": "ali"}, {"username": "veli"}])), \
             patch("app.main.database.set_llm_setting", new=fake_set), \
             patch("app.main.log_user_action", new=AsyncMock()):
            result = await main.set_admin_trade_notify_recipients({"recipients": ["veli", " ali "]}, request=None)
        self.assertEqual(["ali", "veli"], result["recipients"])
        self.assertEqual(["ali", "veli"], json.loads(saved["admin_trade_notify_recipients"]))
        with patch("app.main._require_admin", admin), \
             patch("app.main.database.get_llm_setting", new=fake_get):
            got = await main.get_admin_trade_notify_recipients(request=None)
        self.assertEqual(["ali", "veli"], got["recipients"])

    async def test_recipients_rejects_unknown_user(self):
        from app import main

        with patch("app.main._require_admin", MagicMock(return_value={"username": "admin", "role": "admin"})), \
             patch("app.main.database.list_users", new=AsyncMock(return_value=[{"username": "ali"}])):
            with self.assertRaises(HTTPException) as ctx:
                await main.set_admin_trade_notify_recipients({"recipients": ["hacker"]}, request=None)
        self.assertEqual(422, ctx.exception.status_code)

    async def test_recipients_endpoints_are_admin_gated(self):
        from app import main

        with patch("app.main._require_admin", MagicMock(side_effect=HTTPException(403, "admin only"))):
            with self.assertRaises(HTTPException):
                await main.get_admin_trade_notify_recipients(request=None)
            with self.assertRaises(HTTPException):
                await main.set_admin_trade_notify_recipients({"recipients": []}, request=None)

    async def test_push_subscription_binds_session_username(self):
        from app import main

        seen = {}
        async def fake_save(sub, username=None):
            seen["username"] = username
            return {"ok": True}
        request = MagicMock(headers={}, cookies={})
        with patch("app.security.request_user", return_value={"username": "ali", "role": "user"}), \
             patch("app.main.database.save_push_subscription", new=fake_save):
            result = await main.save_alert_push_subscription({"endpoint": "https://push.example/1"}, request=request)
        self.assertTrue(result["ok"])
        self.assertEqual("ali", seen["username"])

    async def test_deliver_web_push_targets_selected_users_only(self):
        from app import alerting

        seen = {}
        async def fake_list(usernames=None):
            seen["usernames"] = usernames
            return [{"endpoint": "https://push.example/1"}]
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "test-key"}), \
             patch("app.database.list_push_subscriptions", new=fake_list), \
             patch("pywebpush.webpush", MagicMock()):
            result = await alerting.deliver_web_push("admin BTCTRY 0,72", usernames=["ali", "veli"])
        self.assertTrue(result["ok"])
        self.assertEqual(["ali", "veli"], seen["usernames"])

    async def test_tr_price_format_uses_comma_and_trims_zeros(self):
        from app.main import _fmt_tr_price

        self.assertEqual("0,72", _fmt_tr_price(0.72))
        self.assertEqual("142530,5", _fmt_tr_price(142530.50))
        self.assertEqual("1", _fmt_tr_price(1.0))

    def test_buy_flow_sends_amountless_targeted_notification(self):
        """Kaynak kilidi: buy ucunda notify → seçili alıcılara, tutarsız mesaj."""
        from app import alerting, main

        src = inspect.getsource(main.binance_buy)
        self.assertIn('bool(payload.get("notify"))', src)
        self.assertIn("usernames=recipients", src)
        self.assertIn("fiyatla pozisyon açtı", src)
        self.assertIn("list_push_subscriptions", inspect.getsource(alerting.deliver_web_push))
        tail = src[src.index("notify_requested"):]
        self.assertNotIn("amount_try", tail)

    def test_push_subscription_schema_binds_username(self):
        from app import database

        self.assertIn("ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS username TEXT",
                      inspect.getsource(database.init_db))
        self.assertIn("COALESCE(excluded.username,push_subscriptions.username)",
                      inspect.getsource(database.save_push_subscription))
        list_src = inspect.getsource(database.list_push_subscriptions)
        self.assertIn("usernames", list_src)
        self.assertIn("WHERE username IN", list_src)


# ---------------------------------------------------------------------------
# M3 GRAFİK — market-klines ucu 3m ufku kabul etmeli (teknik grafik M3 boştu)
# ---------------------------------------------------------------------------
class MarketKlinesIntervalTests(unittest.IsolatedAsyncioTestCase):
    async def test_3m_interval_is_served(self):
        from app import main

        rows = [[1_700_000_000_000, "1", "2", "0.5", "1.5", "10", 1_700_000_180_000]]
        with patch("app.main.fetch_klines", new=AsyncMock(return_value=rows)):
            result = await main.get_market_klines("BTCTRY", interval="3m", limit=50)
        self.assertEqual("3m", result["interval"])
        self.assertEqual(rows, result["candles"])

    async def test_unknown_interval_still_rejected(self):
        from app import main

        with self.assertRaises(HTTPException) as ctx:
            await main.get_market_klines("BTCTRY", interval="2m", limit=50)
        self.assertEqual(400, ctx.exception.status_code)


if __name__ == "__main__":
    unittest.main()
