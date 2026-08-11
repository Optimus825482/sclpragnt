"""Binance TR symbol type 1 public market-data adapter."""

import asyncio
import json
import random
import time
from email.message import Message
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REST_BASE = "https://api.binance.me"
WS_BASE = "wss://stream-cloud.binance.tr"


REST_TIMEOUT_SEC = 15
REST_MAX_ATTEMPTS = 4
REST_BACKOFF_BASE_SEC = 0.35
REST_BACKOFF_MAX_SEC = 4.0


def _retry_delay(attempt: int, headers: Message | dict | None = None) -> float:
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after is not None:
        try:
            return min(REST_BACKOFF_MAX_SEC, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    exponential = min(REST_BACKOFF_MAX_SEC, REST_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))
    return exponential + random.uniform(0.0, exponential * 0.25)


def _decode_payload(raw: bytes):
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Binance TR public API geçersiz JSON döndürdü") from exc
    if not isinstance(payload, (dict, list)):
        raise RuntimeError("Binance TR public API beklenmeyen yanıt şeması döndürdü")
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise RuntimeError(str(payload.get("msg") or "Binance TR public API hatası"))
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if data is None:
        raise RuntimeError("Binance TR public API boş veri döndürdü")
    return data


def _get_json(path: str, params: dict):
    url = f"{REST_BASE}{path}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "scalperagent-v4", "Accept": "application/json"})
    last_error = None
    for attempt in range(1, REST_MAX_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=REST_TIMEOUT_SEC) as response:
                return _decode_payload(response.read())
        except HTTPError as exc:
            last_error = exc
            if exc.code != 429 and not 500 <= exc.code < 600:
                raise RuntimeError(f"Binance TR public API HTTP {exc.code}") from exc
            if attempt == REST_MAX_ATTEMPTS:
                break
            time.sleep(_retry_delay(attempt, exc.headers))
        except (URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt == REST_MAX_ATTEMPTS:
                break
            time.sleep(_retry_delay(attempt))
    raise RuntimeError(
        f"Binance TR public API {REST_MAX_ATTEMPTS} denemede yanıt vermedi: {last_error}"
    ) from last_error


async def klines(symbol: str, interval: str, limit: int = 500, start_time_ms: int | None = None,
                 end_time_ms: int | None = None):
    params = {"symbol": symbol.replace("_", "").upper(), "interval": interval, "limit": limit}
    if start_time_ms is not None:
        params["startTime"] = start_time_ms
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    return await asyncio.to_thread(_get_json, "/api/v1/klines", params)


async def historical_klines(symbol: str, interval: str, days_back: int, end_time_ms: int | None = None):
    end = min(int(end_time_ms), int(time.time() * 1000)) if end_time_ms is not None else int(time.time() * 1000)
    start = end - days_back * 86400 * 1000
    rows = []
    cursor = start
    while True:
        batch = await klines(symbol, interval, 1000, cursor, end)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1][0]) + 1
        if cursor >= end:
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
    normalized = symbol.replace("_", "").upper()
    # Liquidity is evaluated against the same top-five levels whether the
    # snapshot came from REST or the depth5 WebSocket stream.
    payload = await asyncio.to_thread(_get_json, "/api/v3/depth", {
        "symbol": normalized, "limit": min(5, max(1, int(limit)))
    })
    if not isinstance(payload, dict):
        raise RuntimeError("Binance TR order-book yanıtı nesne değil")
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list):
        raise RuntimeError("Binance TR order-book bid/ask alanları eksik")
    return {**payload, "symbol": normalized, "bids": bids[:5], "asks": asks[:5],
            "source": "binance_tr_public_rest", "received_at": time.time()}
