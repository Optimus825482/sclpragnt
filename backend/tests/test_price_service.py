"""`app.price_service` testleri: WS → REST sırası, tazelik, salt-okunur davranış.

Ağ çağrısı yok: `binance_tr_public.ticker_price` / `klines` yamalanır.
"""
import os
import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SCALPER_ENV", "development")

from app.config import config  # noqa: E402
from app import price_service  # noqa: E402
from app import api_common  # noqa: E402


def _market(last_price=None, age_sec=0.0, source=None, ticker=None) -> MagicMock:
    """Sahte market: `tickers` sözlüğü + `get_ticker`. ticker verilirse aynen kullanılır."""
    m = MagicMock()
    if ticker is None and last_price is not None:
        ticker = {"symbol": "BTCTRY", "last_price": last_price,
                  "timestamp": (time.time() - age_sec) * 1000}
        if source:
            ticker["source"] = source
    m.tickers = {"BTCTRY": ticker} if ticker else {}
    m.get_ticker = MagicMock(side_effect=lambda s: m.tickers.get(str(s).upper()))
    return m


class WsQuoteTests(unittest.TestCase):

    def test_fresh_ws_ticker_is_returned_with_age(self):
        m = _market(last_price=100.0, age_sec=2.0)
        price, age, source = price_service.ws_quote("BTCTRY", market_obj=m)
        self.assertEqual(price, 100.0)
        self.assertAlmostEqual(age, 2.0, delta=0.5)
        self.assertEqual(source, price_service.SOURCE_WS)

    def test_ws_source_label_is_kept(self):
        m = _market(last_price=100.0, source="custom_src")
        self.assertEqual(price_service.ws_quote("BTCTRY", market_obj=m)[2], "custom_src")

    def test_stale_ticker_is_none(self):
        m = _market(last_price=100.0, age_sec=config.MAX_TICKER_AGE_SEC + 120)
        self.assertIsNone(price_service.ws_quote("BTCTRY", market_obj=m))

    def test_zero_timestamp_is_stale(self):
        m = _market(ticker={"last_price": 100.0, "timestamp": 0})
        self.assertIsNone(price_service.ws_quote("BTCTRY", market_obj=m))

    def test_non_positive_price_is_none(self):
        m = _market(ticker={"last_price": 0, "timestamp": time.time() * 1000})
        self.assertIsNone(price_service.ws_quote("BTCTRY", market_obj=m))

    def test_missing_ticker_is_none(self):
        self.assertIsNone(price_service.ws_quote("BTCTRY", market_obj=_market()))

    def test_symbol_is_normalized(self):
        m = _market(last_price=100.0)
        self.assertIsNotNone(price_service.ws_quote("btc_try", market_obj=m))


class GetPriceTests(unittest.IsolatedAsyncioTestCase):

    async def test_fresh_ws_wins_and_no_rest_call(self):
        m = _market(last_price=101.0)
        rest = AsyncMock(return_value=[{"symbol": "BTCTRY", "price": "999"}])
        with patch("app.binance_tr_public.ticker_price", rest):
            price, age, source = await price_service.get_price("BTCTRY", market_obj=m)
        self.assertEqual(price, 101.0)
        self.assertEqual(source, price_service.SOURCE_WS)
        rest.assert_not_awaited()

    async def test_stale_ws_falls_back_to_rest_ticker(self):
        m = _market(last_price=101.0, age_sec=config.MAX_TICKER_AGE_SEC + 60)
        rest = AsyncMock(return_value=[{"symbol": "BTCTRY", "price": "95.5"}])
        with patch("app.binance_tr_public.ticker_price", rest):
            price, age, source = await price_service.get_price("BTCTRY", market_obj=m)
        self.assertEqual((price, age, source), (95.5, 0.0, price_service.SOURCE_REST_TICKER))
        rest.assert_awaited_once_with(["BTCTRY"])

    async def test_rest_ticker_error_falls_back_to_kline(self):
        m = _market()
        ticker_mock = AsyncMock(side_effect=RuntimeError("rest down"))
        kline_mock = AsyncMock(return_value=[[0, 0, 0, 0, "88.25", 0]])
        with patch("app.binance_tr_public.ticker_price", ticker_mock), \
             patch("app.binance_tr_public.klines", kline_mock):
            price, _age, source = await price_service.get_price("BTCTRY", market_obj=m)
        self.assertEqual(price, 88.25)
        self.assertEqual(source, price_service.SOURCE_REST_KLINE)
        kline_mock.assert_awaited_once_with("BTCTRY", "1m", 2)

    async def test_rest_ticker_missing_symbol_falls_back_to_kline(self):
        m = _market()
        ticker_mock = AsyncMock(return_value=[{"symbol": "ETHTRY", "price": "1"}])
        kline_mock = AsyncMock(return_value=[[0, 0, 0, 0, "77", 0]])
        with patch("app.binance_tr_public.ticker_price", ticker_mock), \
             patch("app.binance_tr_public.klines", kline_mock):
            price, _age, source = await price_service.get_price("BTCTRY", market_obj=m)
        self.assertEqual((price, source), (77.0, price_service.SOURCE_REST_KLINE))

    async def test_everything_fails_returns_all_none(self):
        m = _market()
        with patch("app.binance_tr_public.ticker_price", AsyncMock(side_effect=RuntimeError("x"))), \
             patch("app.binance_tr_public.klines", AsyncMock(side_effect=RuntimeError("y"))):
            self.assertEqual(await price_service.get_price("BTCTRY", market_obj=m),
                             (None, None, None))

    async def test_get_price_never_writes_market_tickers(self):
        """Salt-okunur sözleşme: REST'ten fiyat gelse bile `market.tickers` değişmez."""
        m = _market(last_price=101.0, age_sec=config.MAX_TICKER_AGE_SEC + 60)
        before = dict(m.tickers)
        with patch("app.binance_tr_public.ticker_price",
                   AsyncMock(return_value=[{"symbol": "BTCTRY", "price": "95.5"}])):
            await price_service.get_price("BTCTRY", market_obj=m)
        self.assertEqual(m.tickers, before)

    async def test_rest_quote_skips_ws(self):
        rest = AsyncMock(return_value=[{"symbol": "BTCTRY", "price": "50"}])
        with patch("app.binance_tr_public.ticker_price", rest):
            quote = await price_service.rest_quote("BTCTRY")
        self.assertEqual(quote[0], 50.0)
        rest.assert_awaited_once()


class LegacyFreshPublicPriceWrapperTests(unittest.IsolatedAsyncioTestCase):
    """`api_common._fresh_public_price` geriye dönük sözleşmesi: REST fiyatı önbelleğe yazılır."""

    async def test_rest_price_repairs_cache_like_before(self):
        m = _market(last_price=101.0, age_sec=config.MAX_TICKER_AGE_SEC + 60)
        with patch.object(api_common, "market", m), \
             patch("app.binance_tr_public.ticker_price",
                   AsyncMock(return_value=[{"symbol": "BTCTRY", "price": "95.5"}])):
            price, info = await api_common._fresh_public_price("BTCTRY")
        self.assertEqual(price, 95.5)
        self.assertEqual(info["source"], price_service.SOURCE_REST_TICKER)
        self.assertEqual(m.tickers["BTCTRY"]["last_price"], 95.5)

    async def test_ws_price_returns_ticker_copy_without_write(self):
        m = _market(last_price=101.0)
        before = dict(m.tickers)
        with patch.object(api_common, "market", m):
            price, info = await api_common._fresh_public_price("BTCTRY")
        self.assertEqual(price, 101.0)
        self.assertEqual(info["source"], price_service.SOURCE_WS)
        self.assertEqual(m.tickers, before)

    async def test_no_price_returns_none_pair(self):
        m = _market()
        with patch.object(api_common, "market", m), \
             patch("app.binance_tr_public.ticker_price", AsyncMock(side_effect=RuntimeError("x"))), \
             patch("app.binance_tr_public.klines", AsyncMock(side_effect=RuntimeError("y"))):
            self.assertEqual(await api_common._fresh_public_price("BTCTRY"), (None, None))


if __name__ == "__main__":
    unittest.main()
