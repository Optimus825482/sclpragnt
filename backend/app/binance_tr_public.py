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
# WS birincil ve yedek hostlar. Birincil (stream-cloud.binance.tr) canlı
# Binance TR market-data yayınıdır; bağlantı kurulamazsa stream.binance.me
# (dokümantasyondaki genel spot market-data yayını) denenir.
WS_BASE = "wss://stream-cloud.binance.tr"
WS_BASES = ("wss://stream-cloud.binance.tr", "wss://stream.binance.me")


REST_TIMEOUT_SEC = 15
REST_MAX_ATTEMPTS = 4
REST_BACKOFF_BASE_SEC = 0.35
REST_BACKOFF_MAX_SEC = 4.0

# Server-reported used request weight (X-MBX-USED-WEIGHT-1M), tracked per
# response. Without this the startup burst (~900 kline requests) has zero
# rate-limit visibility.
_rate_limit_used = {"total": 0, "by_endpoint": {}}
_rate_limit_last_reset = None


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
                # Track rate-limit headers; a malformed header must not fail
                # the response itself.
                try:
                    used = int(response.headers.get("X-MBX-USED-WEIGHT-1M", 0) or 0)
                    global _rate_limit_last_reset
                    _rate_limit_used["total"] = used
                    _rate_limit_used["by_endpoint"][path] = max(_rate_limit_used["by_endpoint"].get(path, 0), used)
                    _rate_limit_last_reset = time.time()
                except (TypeError, ValueError):
                    pass
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
    return await asyncio.to_thread(_get_json, "/api/v3/klines", params)


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

def _default_filters():
    """Güncel Binance TR exchangeInfo filtre şeması.

    Eski MIN_NOTIONAL filtre adı kaldırılmıştır; minimum işlem tutarı artık
    NOTIONAL altında döner. Yalnız gerçekten ilgili filtreler tutulur, tüm
    alanlar her zaman mevcut olmayabilir (ör. MARKET_LOT_SIZE yalnız market
    emri olan sembollerde bulunur).
    """
    return {
        "min_price": None, "tick_size": None,
        "min_qty": None, "step_size": None,
        "min_notional": None, "max_notional": None,
        "market_min_qty": None, "market_step_size": None,
    }


async def trading_symbols_with_filters(quote_asset: str = "TRY"):
    """TRADING sembollerini güncel PRICE/LOT/NOTIONAL/MARKET_LOT_SIZE limitleriyle döndürür."""
    payload = await asyncio.to_thread(_get_json, "/api/v3/exchangeInfo", {})
    result = {}
    for item in payload.get("symbols", []):
        if item.get("status") != "TRADING" or item.get("quoteAsset") != quote_asset.upper():
            continue
        sym = str(item["symbol"]).upper()
        filters = _default_filters()
        for f in item.get("filters", []):
            ft = f.get("filterType")
            if ft == "PRICE_FILTER":
                filters["min_price"] = float(f.get("minPrice") or 0)
                filters["tick_size"] = float(f.get("tickSize") or 0.01)
            elif ft == "LOT_SIZE":
                filters["min_qty"] = float(f.get("minQty") or 0)
                filters["step_size"] = float(f.get("stepSize") or 0)
            elif ft in ("NOTIONAL", "MIN_NOTIONAL"):
                filters["min_notional"] = float(f.get("minNotional") or f.get("notional") or 0)
                filters["max_notional"] = float(f.get("maxNotional") or 0) or None
            elif ft == "MARKET_LOT_SIZE":
                filters["market_min_qty"] = float(f.get("minQty") or 0)
                filters["market_step_size"] = float(f.get("stepSize") or 0)
            elif ft == "PERCENT_PRICE_BY_SIDE":
                filters["bid_multiplier_up"] = float(f.get("bidMultiplierUp") or 0)
                filters["ask_multiplier_down"] = float(f.get("askMultiplierDown") or 0)
            elif ft == "TRAILING_DELTA":
                filters["trailing_delta_min"] = float(f.get("minTrailingAboveDelta") or 0)
        result[sym] = filters
    return result


def _ticker_params(symbols: list | None) -> dict:
    """Binance TR symbol filtresi: ["BTCTRY","ETHTRY"] → {"symbols":"[""BTCTRY"",""ETHTRY""]"}"""
    if not symbols:
        return {}
    quoted = ",".join(f'"{s}"' for s in symbols[:50])
    return {"symbols": f"[{quoted}]"}
async def ticker_24h(symbols: list | None = None):
    return await asyncio.to_thread(_get_json, "/api/v3/ticker/24hr", _ticker_params(symbols))


async def ticker_price(symbols: list | None = None):
    """Son fiyat listesi (symbols verilmezse tüm semboller). Weight: 2-4."""
    return await asyncio.to_thread(_get_json, "/api/v3/ticker/price", _ticker_params(symbols))


async def book_tickers(symbols: list | None = None):
    """Tüm (veya seçili) semboller için best-bid/ask. Weight: 2-4."""
    return await asyncio.to_thread(_get_json, "/api/v3/ticker/bookTicker", _ticker_params(symbols))

# Web'deki https://www.binance.tr/en/markets/overview?tab=top-gaining listesiyle
# aynı kaynak: /api/v3/ticker/24hr, priceChangePercent'e göre azalan sıralama.
# quoteVolume tabanlı minimum hacim, ince/alakasız çiftleri elemek içindir.
MIN_TOP_GAINER_QUOTE_VOLUME_TRY = 5_000_000.0

async def top_gainers(symbol_count: int = 20, *, quote_asset: str = "TRY",
                      min_quote_volume: float | None = None,
                      _ticker_rows: list | None = None):
    """Top-gaining TRY pairs, 24h change descending, volume-filtered.

    Mirrors the website's top-gaining tab; the returned rows keep
    priceChangePercent and quoteVolume so callers can justify the pool.
    Delisted/suspended symbols are excluded: the 24h ticker still lists
    dead pairs with stale closes (BAKETRY kept trading data a year after
    delisting), so the pool is intersected with current TRADING symbols.

    ``_ticker_rows`` zaten elinde tüm 24h satırları olan çağıranların ikinci
    kez weight:80 istek atmasını önler.
    """
    rows = list(_ticker_rows) if _ticker_rows else await ticker_24h()
    info = await trading_symbols(quote_asset)
    trading = set(info)
    floor = (MIN_TOP_GAINER_QUOTE_VOLUME_TRY if min_quote_volume is None
             else float(min_quote_volume))
    suffix = quote_asset.upper()
    candidates = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol.endswith(suffix) or symbol not in trading:
            continue
        try:
            change = float(row.get("priceChangePercent") or 0)
            quote_volume = float(row.get("quoteVolume") or 0)
        except (TypeError, ValueError):
            continue
        if quote_volume < floor:
            continue
        candidates.append({"symbol": symbol, "priceChangePercent": change,
                           "quoteVolume": quote_volume, "lastPrice": row.get("lastPrice")})
    candidates.sort(key=lambda item: item["priceChangePercent"], reverse=True)
    return candidates[:max(1, min(int(symbol_count), 50))]

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


async def depth(symbol: str, limit: int = 5):
    """Read-only top-``limit`` order-book levels (all returned, not top-5 capped).

    The legacy ``orderbook`` adapter truncates to the top five levels even when
    a wider snapshot is requested; ``depth`` preserves the full returned depth
    so callers can measure wall size / ladder asymmetry from the same public
    REST endpoint. Same weight, same rate-limit headers as ``orderbook``.
    """
    normalized = symbol.replace("_", "").upper()
    payload = await asyncio.to_thread(_get_json, "/api/v3/depth", {
        "symbol": normalized, "limit": min(1000, max(1, int(limit)))
    })
    if not isinstance(payload, dict):
        raise RuntimeError("Binance TR order-book yanıtı nesne değil")
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list):
        raise RuntimeError("Binance TR order-book bid/ask alanları eksik")
    return {**payload, "symbol": normalized, "bids": bids, "asks": asks,
            "source": "binance_tr_public_rest", "received_at": time.time()}



def rate_limit_snapshot():
    """Public API rate-limit kullanım anlık görüntüsü."""
    return {
        "total_weight_used": _rate_limit_used["total"],
        "by_endpoint": dict(_rate_limit_used["by_endpoint"]),
        "last_reset_at": _rate_limit_last_reset,
    }