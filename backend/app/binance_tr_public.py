"""Binance TR symbol type 1 public market-data adapter."""

import asyncio
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REST_BASE = "https://api.binance.me"
WS_BASE = "wss://stream-cloud.binance.tr"


def _get_json(path: str, params: dict):
    url = f"{REST_BASE}{path}?{urlencode(params)}"
    with urlopen(Request(url, headers={"User-Agent": "scalperagent-v4"}), timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise RuntimeError(payload.get("msg", "Binance TR public API hatası"))
    return payload.get("data", payload) if isinstance(payload, dict) else payload


async def klines(symbol: str, interval: str, limit: int = 500, start_time_ms: int | None = None):
    params = {"symbol": symbol.replace("_", "").upper(), "interval": interval, "limit": limit}
    if start_time_ms is not None:
        params["startTime"] = start_time_ms
    return await asyncio.to_thread(_get_json, "/api/v1/klines", params)


async def historical_klines(symbol: str, interval: str, days_back: int):
    start = int((time.time() - days_back * 86400) * 1000)
    rows = []
    cursor = start
    while True:
        batch = await klines(symbol, interval, 1000, cursor)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1][0]) + 1
        if cursor >= int(time.time() * 1000):
            break
    return rows


async def trading_symbols(quote_asset: str = "TRY"):
    """Binance TR'de işlem gören, seçilebilir sembolleri public exchangeInfo'dan getirir."""
    payload = await asyncio.to_thread(_get_json, "/api/v3/exchangeInfo", {})
    return sorted({
        str(item["symbol"]).upper()
        for item in payload.get("symbols", [])
        if item.get("status") == "TRADING" and item.get("quoteAsset") == quote_asset.upper()
    })


async def ticker_24h():
    return await asyncio.to_thread(_get_json, "/api/v3/ticker/24hr", {})

async def orderbook(symbol: str, limit: int = 5):
    """Read-only best bid/ask depth from Binance TR public API."""
    return await asyncio.to_thread(_get_json, "/api/v3/depth", {
        "symbol": symbol.replace("_", "").upper(), "limit": limit
    })
