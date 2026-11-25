"""Radar "Yükselenler" ucu (2026-11-25): TR 24s ticker'ından ilk 20, hacim filtreli."""
import asyncio
from unittest.mock import patch

from app.routers import monitoring


def test_top_gainers_filters_and_sorts():
    rows = [
        {"symbol": "AAA_TRY", "lastPrice": "10", "priceChangePercent": "25.0", "quoteVolume": "90000000"},
        {"symbol": "BBB_TRY", "lastPrice": "5", "priceChangePercent": "8.0", "quoteVolume": "20000000"},
        {"symbol": "CCC_TRY", "lastPrice": "1", "priceChangePercent": "-12.0", "quoteVolume": "8000000"},
        {"symbol": "DUST_TRY", "lastPrice": "1", "priceChangePercent": "300.0", "quoteVolume": "1000"},
    ]

    async def fake_ticker(symbols=None):
        return rows

    with patch("app.binance_tr_public.ticker_24h", fake_ticker):
        out = asyncio.run(monitoring.radar_top_gainers(limit=20))

    symbols = [x["symbol"] for x in out["items"]]
    assert symbols == ["AAA_TRY", "BBB_TRY"], "düşen ve düşük hacimli elenmeli"
    assert out["source"] == "binance_tr"
    assert out["items"][0]["change_24h"] == 25.0


def test_top_gainers_limit_is_clamped():
    rows = [
        {"symbol": f"S{i}_TRY", "lastPrice": "1", "priceChangePercent": str(i + 1),
         "quoteVolume": "10000000"}
        for i in range(80)
    ]

    async def fake_ticker(symbols=None):
        return rows

    with patch("app.binance_tr_public.ticker_24h", fake_ticker):
        out = asyncio.run(monitoring.radar_top_gainers(limit=500))

    assert len(out["items"]) == 50, "üst sınır 50"
    assert out["items"][0]["change_24h"] > out["items"][-1]["change_24h"]
