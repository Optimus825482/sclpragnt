"""Binance TR Lead-Lag (Öncü-Artçı) Sinyal Alıcısı Birim ve Entegrasyon Testleri.

Binance Global'den gelen sinyallerin doğrulanması, sembol dönüşümü,
cooldown deduplikasyonu, risk kapıları, paper trade tetikleyicisi ve
FastAPI REST API uç noktalarının uçtan uca doğrulanması.
"""
import asyncio
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import config
from app import database
from app import tr_bridge_receiver
from app.routers import bridge as bridge_routes
from app.main import app


class TestBridgeReceiverCore(unittest.IsolatedAsyncioTestCase):
    """tr_bridge_receiver çekirdek fonksiyonları testi."""

    async def asyncSetUp(self):
        # Ayarları test ortamına göre sıfırla
        await database.set_llm_setting("bridge_receiver_enabled", "1")
        await database.set_llm_setting("bridge_secret", "test-gizli-anahtar-123")
        await database.set_llm_setting("bridge_auto_trade", "1")
        await database.set_llm_setting("bridge_min_score", "0.0")
        await database.set_llm_setting("bridge_cooldown_sec", "10.0")

        tr_bridge_receiver._last_signal_times.clear()
        tr_bridge_receiver._history.clear()
        tr_bridge_receiver._stats = {
            "total_received": 0,
            "pings_received": 0,
            "signals_received": 0,
            "trades_opened": 0,
            "trades_blocked": 0,
            "cooldown_skips": 0,
            "auth_failures": 0,
            "last_received_at": None,
            "total_latency_ms": 0.0,
            "latency_count": 0,
        }

    def test_map_to_tr_symbol(self):
        """Global sembollerini TR karşılığına çevirme testi."""
        # 1. global_symbol (USDT -> TRY)
        self.assertEqual(tr_bridge_receiver.map_to_tr_symbol(global_symbol="SOLUSDT"), "SOLTRY")
        self.assertEqual(tr_bridge_receiver.map_to_tr_symbol(global_symbol="BTCUSDT"), "BTCTRY")
        self.assertEqual(tr_bridge_receiver.map_to_tr_symbol(global_symbol="PEPEUSDT"), "PEPETRY")
        self.assertEqual(tr_bridge_receiver.map_to_tr_symbol(global_symbol="AVAXTRY"), "AVAXTRY")

        # 2. base_asset
        self.assertEqual(tr_bridge_receiver.map_to_tr_symbol(base_asset="SOL"), "SOLTRY")
        self.assertEqual(tr_bridge_receiver.map_to_tr_symbol(base_asset="BTC"), "BTCTRY")

        # 3. Doğrudan tr_symbol
        self.assertEqual(tr_bridge_receiver.map_to_tr_symbol(tr_symbol="SOLTRY"), "SOLTRY")
        self.assertEqual(tr_bridge_receiver.map_to_tr_symbol(tr_symbol="SOL"), "SOLTRY")

    async def test_verify_bridge_secret(self):
        """X-Bridge-Secret başlığı doğrulama testi."""
        # Geçerli anahtar
        self.assertTrue(await tr_bridge_receiver.verify_bridge_secret("test-gizli-anahtar-123"))

        # Geçersiz anahtar
        self.assertFalse(await tr_bridge_receiver.verify_bridge_secret("yanlis-anahtar"))

        # Eksik anahtar
        self.assertFalse(await tr_bridge_receiver.verify_bridge_secret(None))
        self.assertFalse(await tr_bridge_receiver.verify_bridge_secret(""))

    async def test_ping_pong_latency(self):
        """Ping isteğinin gecikme hesaplayıp pong dönmesi testi."""
        sent_ts = time.time() - 0.050  # 50ms önce gönderilmiş
        payload = {
            "source": "binance_global",
            "timestamp": sent_ts,
            "signal_type": "ping",
            "action": "PING",
        }
        res = await tr_bridge_receiver.process_global_signal(payload)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "pong")
        self.assertGreaterEqual(res["lead_lag_latency_ms"], 40.0)
        self.assertEqual(tr_bridge_receiver._stats["pings_received"], 1)

    async def test_receiver_disabled_setting(self):
        """Alıcı kapalıyken sinyalin reddedilmesi testi."""
        await database.set_llm_setting("bridge_receiver_enabled", "0")

        payload = {
            "source": "binance_global",
            "timestamp": time.time(),
            "global_symbol": "SOLUSDT",
            "tr_symbol": "SOLTRY",
            "signal_type": "radar",
            "action": "BUY_SIGNAL",
            "score": 85.0,
            "price": 140.0,
        }
        res = await tr_bridge_receiver.process_global_signal(payload)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "disabled")

    async def test_score_filtering(self):
        """Minimum skorun altındaki sinyallerin atlanması testi."""
        await database.set_llm_setting("bridge_min_score", "75.0")

        payload = {
            "source": "binance_global",
            "timestamp": time.time(),
            "global_symbol": "SOLUSDT",
            "tr_symbol": "SOLTRY",
            "signal_type": "radar",
            "action": "BUY_SIGNAL",
            "score": 65.0,  # 75.0'ın altında
            "price": 140.0,
        }
        res = await tr_bridge_receiver.process_global_signal(payload)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "score_below_minimum")
        self.assertEqual(res["score"], 65.0)
        self.assertEqual(res["min_score"], 75.0)

    async def test_cooldown_deduplication(self):
        """Belirlenen cooldown süresi içinde mükerrer sinyallerin engellenmesi testi."""
        await database.set_llm_setting("bridge_cooldown_sec", "10.0")

        with patch("app.state.analyzer.open_position", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = {"action": "BUY_SIGNAL", "trade_id": "test_trade_1"}

            with patch("app.state.market.get_ticker") as mock_ticker:
                mock_ticker.return_value = {"symbol": "SOLTRY", "last_price": 5000.0}

                payload = {
                    "source": "binance_global",
                    "timestamp": time.time(),
                    "global_symbol": "SOLUSDT",
                    "tr_symbol": "SOLTRY",
                    "signal_type": "radar",
                    "action": "BUY_SIGNAL",
                    "score": 88.0,
                    "price": 140.0,
                }

                # İlk sinyal kabul edilir
                res1 = await tr_bridge_receiver.process_global_signal(payload)
                self.assertTrue(res1["ok"])
                self.assertEqual(res1["status"], "executed")

                # Hemen ardından gelen 2. sinyal cooldown nedeniyle atlanır
                res2 = await tr_bridge_receiver.process_global_signal(payload)
                self.assertTrue(res2["ok"])
                self.assertEqual(res2["status"], "cooldown_skipped")
                self.assertEqual(tr_bridge_receiver._stats["cooldown_skips"], 1)

                # force=True ile gönderilen 3. sinyal cooldown'u bypass eder
                payload_force = dict(payload, force=True)
                res3 = await tr_bridge_receiver.process_global_signal(payload_force)
                self.assertTrue(res3["ok"])
                self.assertEqual(res3["status"], "executed")

    async def test_paper_trade_execution(self):
        """BUY_SIGNAL geldiğinde open_position çağrılması ve DB kaydı testi."""
        with patch("app.state.analyzer.open_position", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = {"action": "BUY_SIGNAL", "trade_id": "trade_lead_lag_101"}

            with patch("app.state.market.get_ticker") as mock_ticker:
                mock_ticker.return_value = {"symbol": "SOLTRY", "last_price": 4950.0}

                with patch("app.ws_runtime.ws_manager.broadcast", new_callable=AsyncMock) as mock_ws:
                    payload = {
                        "source": "binance_global",
                        "timestamp": time.time() - 0.025,
                        "global_symbol": "SOLUSDT",
                        "base_asset": "SOL",
                        "tr_symbol": "SOLTRY",
                        "signal_type": "radar",
                        "action": "BUY_SIGNAL",
                        "score": 92.5,
                        "price": 145.20,
                        "title": "Radar Kırılımı",
                        "message": "SOL momentum kırılımı",
                        "data": {
                            "target_pct": 3.0,
                            "horizon_minutes": 10,
                        },
                    }
                    res = await tr_bridge_receiver.process_global_signal(payload)

                    self.assertTrue(res["ok"])
                    self.assertEqual(res["status"], "executed")
                    self.assertEqual(res["trade"]["status"], "opened")
                    self.assertEqual(res["trade"]["trade_id"], "trade_lead_lag_101")
                    self.assertEqual(res["tr_price"], 4950.0)

                    # open_position parametrelerinin doğrulanması
                    mock_open.assert_awaited_once()
                    call_kwargs = mock_open.await_args.kwargs
                    self.assertEqual(call_kwargs["symbol"], "SOLTRY")
                    self.assertEqual(call_kwargs["entry_price"], 4950.0)
                    self.assertEqual(call_kwargs["strat_name"], "GLOBAL_LEAD_LAG")
                    self.assertEqual(call_kwargs["take_profit_pct"], 0.03)  # %3.0
                    self.assertEqual(call_kwargs["max_hold_sec"], 600)  # 10 dk * 60

                    # WebSocket yayınının yapıldığının doğrulanması
                    mock_ws.assert_awaited()

    async def test_daily_loss_guard_blocks_trade(self):
        """Günlük zarar limiti devredeyken yeni pozisyon açılışının engellenmesi testi."""
        async def mock_guard():
            return {"halt": True, "reason": "daily_loss_limit_reached"}

        tr_bridge_receiver.set_daily_loss_guard_fn(mock_guard)

        with patch("app.state.market.get_ticker") as mock_ticker:
            mock_ticker.return_value = {"symbol": "BTCTRY", "last_price": 2300000.0}

            payload = {
                "source": "binance_global",
                "timestamp": time.time(),
                "global_symbol": "BTCUSDT",
                "tr_symbol": "BTCTRY",
                "signal_type": "velocity_auto",
                "action": "BUY_SIGNAL",
                "score": 95.0,
                "price": 65000.0,
            }
            res = await tr_bridge_receiver.process_global_signal(payload)

            self.assertTrue(res["ok"])
            self.assertEqual(res["status"], "blocked")
            self.assertEqual(res["trade"]["status"], "blocked")
            self.assertIn("daily_loss_limit_reached", res["trade"]["reason"])
            self.assertEqual(tr_bridge_receiver._stats["trades_blocked"], 1)

        tr_bridge_receiver.set_daily_loss_guard_fn(None)


class TestBridgeRestEndpoints(unittest.IsolatedAsyncioTestCase):
    """FastAPI REST uç noktaları testi."""

    async def asyncSetUp(self):
        await database.set_llm_setting("bridge_secret", "super-guclu-kopru-anahtari")
        await database.set_llm_setting("bridge_receiver_enabled", "1")
        await database.set_llm_setting("bridge_auto_trade", "1")

    async def test_endpoint_missing_secret_returns_401(self):
        """Secret başlığı olmadan istek atıldığında 401 dönmesi."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post("/api/bridge/global-signal", json={"action": "PING"})
            self.assertEqual(res.status_code, 401)

    async def test_endpoint_invalid_secret_returns_401(self):
        """Yanlış secret ile istek atıldığında 401 dönmesi."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"X-Bridge-Secret": "hatali-anahtar"}
            res = await ac.post("/api/bridge/global-signal", json={"action": "PING"}, headers=headers)
            self.assertEqual(res.status_code, 401)

    async def test_endpoint_valid_secret_ping(self):
        """Geçerli secret ile ping gönderildiğinde 200 ve pong dönmesi."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"X-Bridge-Secret": "super-guclu-kopru-anahtari"}
            payload = {
                "source": "binance_global",
                "timestamp": time.time(),
                "signal_type": "ping",
                "action": "PING",
            }
            res = await ac.post("/api/bridge/global-signal", json=payload, headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["status"], "pong")

    async def test_status_endpoint_with_secret(self):
        """X-Bridge-Secret ile /api/bridge/status sorgulanabilmesi."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"X-Bridge-Secret": "super-guclu-kopru-anahtari"}
            res = await ac.get("/api/bridge/status", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "active")
            self.assertIn("settings", data)
            self.assertIn("statistics", data)
            # Maskelenmiş secret kontrolü
            self.assertIn("***", data["settings"]["masked_secret"])

    async def test_test_ping_endpoint(self):
        """/api/bridge/test-ping uç noktasıyla tanı testi."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"X-Bridge-Secret": "super-guclu-kopru-anahtari"}
            res = await ac.post("/api/bridge/test-ping", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["status"], "pong")

    async def test_performance_endpoint(self):
        """/api/bridge/performance uç noktası testi."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"X-Bridge-Secret": "super-guclu-kopru-anahtari"}
            res = await ac.get("/api/bridge/performance?day=all", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["ok"])
            self.assertIn("summary", data)
            self.assertIn("win_rate", data["summary"])
            self.assertIn("open_positions", data)
            self.assertIn("closed_trades", data)
            self.assertIn("recent_signals", data)

