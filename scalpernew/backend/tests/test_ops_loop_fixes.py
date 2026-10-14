"""Rota/loop davranış düzeltmeleri (2026-09-16, backend log incelemesi).

Kapsanan hatalar:
  1. Top Gainers yenileme turu sembol seti DEĞİŞMEDEN `market.reconnect_requested`
     bayrağını koşulsuz True yapıyordu → her turda tüm WS grupları yıkılıp yeniden
     kuruluyordu (log: "generation=1" → "generation=2"). Artık yalnızca gerçek
     değişimde reconnect istenir.
  2. Kalibrasyon döngüsü ilk turda (trade yokken) 0 kova bulup 7 GÜN uyuyordu →
     trade'ler kapansa bile kalibrasyon bir hafta boş kalıyordu.
"""
import asyncio
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TopGainersReconnectTests(unittest.IsolatedAsyncioTestCase):
    """Değişmeyen sembol seti WS'i yeniden kurmamalı (gereksiz nesil churn'ü)."""

    async def _refresh(self, ticker_symbols, current_market_symbols):
        from app.routers import runtime

        # `refresh_top_gainer_symbols` sembolleri normalize eder: "BTC_TRY" -> "BTCTRY".
        normalized = [s.replace("_", "").upper() for s in ticker_symbols]
        tickers = [{"symbol": s, "priceChangePercent": "5.0", "quoteVolume": "1000"}
                   for s in ticker_symbols]
        market_stub = MagicMock(symbols=[s.lower() for s in current_market_symbols],
                                reconnect_requested=False)
        config_stub = MagicMock(TOP_GAINERS_AUTO_ACTIVATE=True, TOP_GAINERS_LIMIT=70,
                                SYMBOLS=list(current_market_symbols), PRIORITY_TIMEFRAMES=["5m"])
        dbmod = MagicMock(load_positions=AsyncMock(return_value={}),
                          get_llm_setting=AsyncMock(return_value="{}"),
                          set_llm_setting=AsyncMock(return_value=None))
        analyzer_stub = MagicMock(positions={})
        with patch.object(runtime, "market", market_stub), \
             patch.object(runtime, "config", config_stub), \
             patch.object(runtime, "database", dbmod), \
             patch.object(runtime, "analyzer", analyzer_stub), \
             patch.object(runtime, "ticker_24h", AsyncMock(return_value=tickers)), \
             patch.object(runtime, "trading_symbols", AsyncMock(return_value=set(normalized))), \
             patch.object(runtime, "universe_registry", MagicMock(record_universe=AsyncMock()), create=True):
            await runtime.refresh_top_gainer_symbols()
        return market_stub

    async def test_unchanged_symbol_set_does_not_reconnect(self):
        stub = await self._refresh(["BTC_TRY", "ETH_TRY"], ["BTCTRY", "ETHTRY"])
        self.assertFalse(stub.reconnect_requested,
                         "sembol seti değişmediği halde WS yeniden kuruldu (churn)")

    async def test_changed_symbol_set_reconnects(self):
        stub = await self._refresh(["BTC_TRY", "SOL_TRY"], ["BTCTRY", "ETHTRY"])
        self.assertTrue(stub.reconnect_requested,
                        "sembol seti değiştiği halde WS yeniden kurulmadı")


class CalibrationCadenceTests(unittest.IsolatedAsyncioTestCase):
    """Veri yoksa saatlik, veri varsa haftalık kadans (7 gün bekleme regresyonu)."""

    async def test_empty_buckets_retry_soon(self):
        from app import main as main_mod

        sleeps = []

        async def fake_sleep(sec):
            sleeps.append(sec)
            if len(sleeps) >= 3:            # 180 + 3600 + 3600 sonra dur
                raise asyncio.CancelledError()

        with patch.object(main_mod.asyncio, "sleep", side_effect=fake_sleep), \
             patch.object(main_mod.database, "get_trades", AsyncMock(return_value=[])), \
             patch.object(main_mod.calibration_service, "build_buckets", return_value={}), \
             patch.object(main_mod.calibration_service, "store_buckets", MagicMock()):
            with self.assertRaises(asyncio.CancelledError):
                await main_mod.calibration_refresh_loop()

        self.assertIn(3600, sleeps, "veri yokken saatlik yeniden deneme yok")
        self.assertNotIn(7 * 24 * 3600, sleeps, "veri yokken 7 gün uyunmamalı")

    async def test_informative_buckets_use_weekly_cadence(self):
        from app import main as main_mod

        sleeps = []

        async def fake_sleep(sec):
            sleeps.append(sec)
            if len(sleeps) >= 2:
                raise asyncio.CancelledError()

        informative = {"k": {"samples": 99, "win_rate": 0.6}}
        with patch.object(main_mod.asyncio, "sleep", side_effect=fake_sleep), \
             patch.object(main_mod.database, "get_trades", AsyncMock(return_value=[{"x": 1}])), \
             patch.object(main_mod.calibration_service, "build_buckets", return_value=informative), \
             patch.object(main_mod.calibration_service, "store_buckets", MagicMock()):
            with self.assertRaises(asyncio.CancelledError):
                await main_mod.calibration_refresh_loop()

        self.assertIn(7 * 24 * 3600, sleeps, "veri varken haftalık kadansa geçilmedi")


if __name__ == "__main__":
    unittest.main()
