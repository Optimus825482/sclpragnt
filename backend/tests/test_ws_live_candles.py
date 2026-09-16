"""Canlı mum akışı (2026-09-16, grafik-canlı-düzeltmesi).

SORUN: Grafik sayfası mum verisini YALNIZCA doğrudan tarayıcı→Binance WS'ine
bağlıyordu. Bu adres browser'dan ERİŞİLEMEZ (backend sunucudan bağlanabiliyor ama
browser'dan TCP/TLS kurulamıyor → "WebSocket connection failed") → grafik hiç
canlı güncellenmiyordu.

ÇÖZÜM: `app/ws_live_candles.py` kapanmış mumları backend'in sağlıklı `liveSocket`
kanalı üzerinden yayınlar; grafik bu kanala abone olur.

Bu dosya yayın sözleşmesini ve mükerrer yayın bastırmasını kilitler.
"""
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ws_live_candles as candles       # noqa: E402


def _bar(time_ms=1_700_000_000_000, close=12.5):
    return {"symbol": "BTCTRY", "timeframe": "5m", "time": time_ms, "open": 12.0,
            "high": 13.0, "low": 11.5, "close": close, "volume": 42.0}


class BarListenerRegistrationTests(unittest.TestCase):
    def test_listener_registered_once(self):
        from app.state import market
        before = list(market._bar_listeners)
        try:
            market.add_bar_listener(candles._on_bar_close)
            market.add_bar_listener(candles._on_bar_close)
            self.assertEqual(1, market._bar_listeners.count(candles._on_bar_close),
                             "aynı dinleyici iki kez kaydedilmemeli")
        finally:
            market._bar_listeners[:] = before

    def test_remove_is_idempotent(self):
        from app.state import market
        before = list(market._bar_listeners)
        try:
            market.add_bar_listener(candles._on_bar_close)
            market.remove_bar_listener(candles._on_bar_close)
            market.remove_bar_listener(candles._on_bar_close)  # ikinci kez patlamamalı
            self.assertNotIn(candles._on_bar_close, market._bar_listeners)
        finally:
            market._bar_listeners[:] = before


class PublishContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        candles._last_published_ms.clear()
        candles._last_publish_at = 0.0

    async def _publish(self, bar_time):
        broadcast = AsyncMock(return_value=None)
        fake_ws = MagicMock(broadcast=broadcast)
        with patch("app.ws_runtime.ws_manager", fake_ws):
            candles._on_bar_close("BTCTRY", "5m", _bar(bar_time))
            # create_task ile atılan yayının çalışması için bir tur bekle
            import asyncio
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        return broadcast

    async def test_broadcasts_kline_message_shape(self):
        broadcast = await self._publish(1_700_000_000_000)
        broadcast.assert_awaited()
        payload = broadcast.await_args.args[0]
        self.assertEqual("kline", payload["type"])
        data = payload["data"]
        for field in ("symbol", "timeframe", "time", "open", "high", "low", "close", "volume"):
            self.assertIn(field, data, f"yayın zarfında eksik alan: {field}")
        self.assertEqual("BTCTRY", data["symbol"])
        self.assertEqual("5m", data["timeframe"])
        self.assertEqual(12.5, data["close"])

    async def test_duplicate_bar_is_not_republished(self):
        """Aynı mum zamanı tekrar gelirse (WS replay) yeniden yayınlanmamalı."""
        first = await self._publish(1_700_000_000_000)
        self.assertEqual(1, first.await_count)
        candles._last_publish_at = 0.0
        second = await self._publish(1_700_000_000_000)   # aynı zaman
        self.assertEqual(0, second.await_count, "aynı mum iki kez yayınlandı")

    async def test_newer_bar_is_published(self):
        await self._publish(1_700_000_000_000)
        candles._last_publish_at = 0.0
        newer = await self._publish(1_700_000_300_000)     # +5 dk
        self.assertEqual(1, newer.await_count)

    async def test_older_bar_is_ignored(self):
        await self._publish(1_700_000_300_000)
        candles._last_publish_at = 0.0
        older = await self._publish(1_700_000_000_000)     # eski zaman
        self.assertEqual(0, older.await_count, "eski mum yayınlanmamalı")

    async def test_broadcast_failure_does_not_raise(self):
        """Yayın hatası MarketData'nın WS döngüsünü bozmamalı."""
        fake_ws = MagicMock(broadcast=AsyncMock(side_effect=RuntimeError("boom")))
        with patch("app.ws_runtime.ws_manager", fake_ws):
            candles._on_bar_close("BTCTRY", "5m", _bar())   # istisna sızdırmamalı
            import asyncio
            await asyncio.sleep(0)
            await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
