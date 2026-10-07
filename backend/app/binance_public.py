"""Binance Global public market-data adapter (v4 port).

Global erken-tespit entegrasyonu (2026-10-07) için `D:\\scalperagent_global`
reposundan port edildi. v4 bu adaptörü AYRI bir veri motoru olarak çalıştırır
(`state.global_market`) ve yalnızca **görünmez bir erken-tespit girdisi** olarak
kullanır: Global piyasa TR'den daha likit olduğu için TR'de de listeli bir
sembolün yükselişini daha erken gösterir. Bu adaptör asla emir göndermez
(salt-okunur public).

ÖNEMLİ (v4'e özgü): `is_binance_tr_symbol` kapısı BURADA KORUNUR. Amaç yalnızca
Binance TR'de işlem gören sembollerin erken tespitidir; TR'de karşılığı olmayan
bir Global coin için sinyal üretmenin faydası yoktur ve Global rate-limit'ini
israf ederdi. (Global repo'da da bu filtre vardı; kullanıcı gereksinimi: "TR'de
olmayan semboller için tarama/bildirim üretilmesin".)
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time
from urllib.parse import urlencode

import urllib3

from app.config import config
from app.binance_tr_symbols import is_binance_tr_symbol

# REST Base URL & çoklu host fallback havuzu (Binance Global Standartları).
# v4 config tek doğru kaynaktır (GLOBAL_REST_BASES); TR adaptörünün havuzundaki
# `api.binance.com` ile karışmaması için ayrı tutulur.
REST_BASES = tuple(config.GLOBAL_REST_BASES)
REST_BASE = REST_BASES[0]

# WS birincil ve yedek hostlar (Global Standartları).
WS_BASES = tuple(config.GLOBAL_WS_BASES)
WS_BASE = WS_BASES[0]

# Kalıcı HTTPS bağlantı havuzu (TLS handshake gecikmesini 350ms'den 30ms'ye indirir)
_HTTP_POOL = urllib3.PoolManager(
    maxsize=32,
    timeout=urllib3.Timeout(connect=5.0, read=15.0),
    retries=False,
)

REST_TIMEOUT_SEC = 15
REST_MAX_ATTEMPTS = 4
REST_BACKOFF_BASE_SEC = 0.35
REST_BACKOFF_MAX_SEC = 4.0
REST_RETRY_AFTER_MAX_SEC = 300.0
REST_BAN_BACKOFF_BASE_SEC = 600.0
REST_BAN_BACKOFF_MAX_SEC = 3600.0
REST_MAX_CONCURRENCY = 8
REST_WEIGHT_SOFT_LIMIT = 5000
REST_WEIGHT_PACING_START = 950
REST_WEIGHT_EMERGENCY_LIMIT = 1100
REST_EMERGENCY_WAIT_MAX_SEC = 15.0
REST_WEIGHT_WINDOW_SEC = 60.0

# Global kendi bütçesine sahiptir; TR adaptörünün semaphore/pool'uyla
# PAYLAŞILMAZ (paylaşılan sayaç varsayımı Global'i 429'a sürükler).
_REQUEST_SEMAPHORE = threading.Semaphore(REST_MAX_CONCURRENCY)

_rate_limit_used = {"total": 0, "by_endpoint": {}}
_rate_limit_last_reset = None
_weight_lock = threading.Lock()
_weight_reported_at = 0.0

EXCHANGE_INFO_CACHE_TTL_SEC = 600.0
_exchange_info_cache: dict = {"payload": None, "expires": 0.0}
_exchange_info_lock = threading.Lock()
_exchange_info_load_lock = threading.Lock()

TICKER_24H_CACHE_TTL_SEC = float(os.getenv("TICKER_24H_CACHE_TTL_SEC", "15"))
_ticker_24h_cache: dict = {"key": None, "rows": None, "expires": 0.0}
_ticker_24h_lock = threading.Lock()
_ticker_24h_load_locks: dict[int, asyncio.Lock] = {}


def _ticker_24h_loop_lock() -> asyncio.Lock:
    """Çalışan event loop'a ait yükleme kilidi (döngü başına bir adet)."""
    loop = asyncio.get_running_loop()
    lock = _ticker_24h_load_locks.get(id(loop))
    if lock is None:
        lock = asyncio.Lock()
        _ticker_24h_load_locks[id(loop)] = lock
    return lock


class TransientDecodeError(RuntimeError):
    """Gövde geçici olarak bozuk/eksik — yeniden denenebilir."""


def _throttle_for_weight() -> None:
    """Akıllı Dinamik Pacing (60s Kaba Blokaj Yerine):

    - used < 950: 0ms gecikme (tam hızda akış).
    - 950 <= used < 1100: İstekler arasına 200-400ms mikro gecikme koyarak harcamayı yavaşlatır.
    - used >= 1100: Yalnızca acil durumda maksimum 15 saniyelik koruma beklemesi uygular.
    """
    with _weight_lock:
        used = int(_rate_limit_used.get("total") or 0)
        reported_at = _weight_reported_at

    if used < REST_WEIGHT_PACING_START or not reported_at:
        return

    now = time.time()
    elapsed = now - reported_at
    if elapsed >= REST_WEIGHT_WINDOW_SEC:
        return

    if used < REST_WEIGHT_EMERGENCY_LIMIT:
        # 950 - 1100 aralığında 200ms - 400ms kademeli mikro gecikme
        progress = (used - REST_WEIGHT_PACING_START) / float(REST_WEIGHT_EMERGENCY_LIMIT - REST_WEIGHT_PACING_START)
        micro_delay = 0.20 + (progress * 0.20) + random.uniform(0.01, 0.04)
        time.sleep(micro_delay)
    else:
        # Acil durum: 1100+ üzeri, kaba 60s yerine maksimum 15s tavanlı bekleme
        wait = REST_WEIGHT_WINDOW_SEC - elapsed
        if wait > 0:
            time.sleep(min(wait, REST_EMERGENCY_WAIT_MAX_SEC))


def _retry_delay(attempt: int, headers=None) -> float:
    """Üstel backoff + jitter, öncelikle sunucunun Retry-After'ı."""
    retry_after = None
    if headers:
        for k in ("Retry-After", "retry-after"):
            val = headers.get(k)
            if val is not None:
                retry_after = val
                break
    if retry_after is not None:
        try:
            return min(REST_RETRY_AFTER_MAX_SEC, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    exponential = min(REST_BACKOFF_MAX_SEC, REST_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))
    return exponential + random.uniform(0.0, exponential * 0.25)


def _ban_delay(attempt: int, headers=None) -> float:
    """418 (kademeli IP ban) geri çekilmesi."""
    for header in ("Retry-After", "retry-after", "Ban", "ban"):
        value = headers.get(header) if headers else None
        if value is not None:
            try:
                return min(REST_BAN_BACKOFF_MAX_SEC, max(0.0, float(value)))
            except (TypeError, ValueError):
                pass
    return min(REST_BAN_BACKOFF_MAX_SEC, REST_BAN_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))


def _decode_payload(raw: bytes):
    """Gövdeyi çöz ve zarfla."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransientDecodeError("Binance public API geçersiz JSON döndürdü") from exc
    if not isinstance(payload, (dict, list)):
        raise TransientDecodeError("Binance public API beklenmeyen yanıt şeması döndürdü")
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise RuntimeError(str(payload.get("msg") or "Binance public API hatası"))
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if data is None:
        raise TransientDecodeError("Binance public API boş veri döndürdü")
    return data


def _get_json(path: str, params: dict):
    """urllib3 connection pool and multi-host fallback execution."""
    query_str = f"?{urlencode(params)}" if params else ""
    headers = {
        "User-Agent": "scalperagent-v4-global-public",
        "Accept": "application/json",
    }
    last_error = None
    for attempt in range(1, REST_MAX_ATTEMPTS + 1):
        _throttle_for_weight()
        # Host fallback: her denemede sırayla havuzdaki hostu dene
        base_url = REST_BASES[(attempt - 1) % len(REST_BASES)]
        url = f"{base_url}{path}{query_str}"
        try:
            with _REQUEST_SEMAPHORE:
                response = _HTTP_POOL.request(
                    "GET",
                    url,
                    headers=headers,
                )
            # X-MBX-USED-WEIGHT-1M izleme
            try:
                used_val = (
                    response.headers.get("X-MBX-USED-WEIGHT-1M")
                    or response.headers.get("x-mbx-used-weight-1m")
                )
                if used_val is not None:
                    used = int(used_val or 0)
                    global _rate_limit_last_reset, _weight_reported_at
                    with _weight_lock:
                        _rate_limit_used["total"] = used
                        _rate_limit_used["by_endpoint"][path] = max(
                            _rate_limit_used["by_endpoint"].get(path, 0), used
                        )
                        _rate_limit_last_reset = time.time()
                        _weight_reported_at = _rate_limit_last_reset
            except (TypeError, ValueError):
                pass

            status = response.status
            if status == 200:
                raw = response.data
                try:
                    return _decode_payload(raw)
                except TransientDecodeError as exc:
                    last_error = exc
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    time.sleep(_retry_delay(attempt, response.headers))
                    continue
            elif status == 418:
                msg = response.data.decode("utf-8", "ignore")
                last_error = RuntimeError(f"Binance IP Ban (HTTP 418): {msg}")
                if attempt == REST_MAX_ATTEMPTS:
                    break
                time.sleep(_ban_delay(attempt, response.headers))
                continue
            elif status == 429:
                msg = response.data.decode("utf-8", "ignore")
                last_error = RuntimeError(f"Binance Rate Limit (HTTP 429): {msg}")
                if attempt == REST_MAX_ATTEMPTS:
                    break
                time.sleep(_retry_delay(attempt, response.headers))
                continue
            elif 500 <= status < 600:
                last_error = RuntimeError(f"Binance Server Error (HTTP {status}) from {base_url}")
                if attempt == REST_MAX_ATTEMPTS:
                    break
                time.sleep(_retry_delay(attempt, response.headers))
                continue
            else:
                msg = response.data.decode("utf-8", "ignore")
                raise RuntimeError(f"Binance public API HTTP {status}: {msg}")

        except (urllib3.exceptions.HTTPError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            if attempt == REST_MAX_ATTEMPTS:
                break
            time.sleep(_retry_delay(attempt))

    raise RuntimeError(
        f"Binance public API {REST_MAX_ATTEMPTS} denemede yanıt vermedi: {last_error}"
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


def _exchange_info_payload() -> dict:
    """`/api/v3/exchangeInfo` gövdesi — 10 dakikalık modül önbelleğiyle."""
    now = time.monotonic()
    with _exchange_info_lock:
        payload = _exchange_info_cache.get("payload")
        if payload is not None and now < float(_exchange_info_cache.get("expires") or 0.0):
            return payload
    with _exchange_info_load_lock:
        now = time.monotonic()
        with _exchange_info_lock:
            payload = _exchange_info_cache.get("payload")
            if payload is not None and now < float(_exchange_info_cache.get("expires") or 0.0):
                return payload
        fetched = _get_json("/api/v3/exchangeInfo", {})
        with _exchange_info_lock:
            _exchange_info_cache.update({
                "payload": fetched,
                "expires": time.monotonic() + EXCHANGE_INFO_CACHE_TTL_SEC,
            })
        return fetched


def exchange_info_cache_snapshot() -> dict:
    """Önbellek durumu (gözlemlenebilirlik)."""
    now = time.monotonic()
    expires = float(_exchange_info_cache.get("expires") or 0.0)
    return {
        "cached": _exchange_info_cache.get("payload") is not None,
        "ttl_sec": EXCHANGE_INFO_CACHE_TTL_SEC,
        "expires_in_sec": max(0.0, expires - now) if expires else 0.0,
    }


async def trading_symbols(quote_asset: str = ""):
    """Binance Global'de işlem gören (ve Binance TR'de karşılığı olan) semboller."""
    quote_asset = quote_asset or "USDT"
    payload = await asyncio.to_thread(_exchange_info_payload)
    return sorted({
        str(item["symbol"]).upper()
        for item in payload.get("symbols", [])
        if item.get("status") == "TRADING" and item.get("quoteAsset") == quote_asset.upper()
        and is_binance_tr_symbol(str(item["symbol"]))
    })


def _default_filters():
    """Binance exchangeInfo filtre şeması."""
    return {
        "min_price": None, "tick_size": None,
        "min_qty": None, "step_size": None,
        "min_notional": None, "max_notional": None,
        "market_min_qty": None, "market_step_size": None,
    }


async def trading_symbols_with_filters(quote_asset: str = ""):
    """TRADING sembollerini güncel limitlerle döndürür."""
    quote_asset = quote_asset or "USDT"
    payload = await asyncio.to_thread(_exchange_info_payload)
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


TICKER_SYMBOL_BATCH = 50


def _chunked(items, size: int = TICKER_SYMBOL_BATCH):
    items = list(items or [])
    for index in range(0, len(items), size):
        yield items[index:index + size]


def _ticker_params(symbols: list | None) -> dict:
    if not symbols:
        return {}
    quoted = ",".join(f'"{s}"' for s in symbols)
    return {"symbols": f"[{quoted}]"}


async def _ticker_paged(path: str, symbols: list | None):
    if not symbols:
        return await asyncio.to_thread(_get_json, path, {})
    merged: list = []
    for batch in _chunked(symbols):
        rows = await asyncio.to_thread(_get_json, path, _ticker_params(batch))
        if isinstance(rows, list):
            merged.extend(rows)
    return merged


async def ticker_24h(symbols: list | None = None):
    """24 saatlik ticker satırları — weight:80."""
    key = tuple(symbols) if symbols else None
    now = time.monotonic()
    with _ticker_24h_lock:
        if (_ticker_24h_cache.get("key") == key
                and _ticker_24h_cache.get("rows") is not None
                and now < float(_ticker_24h_cache.get("expires") or 0.0)):
            return list(_ticker_24h_cache["rows"])
    async with _ticker_24h_loop_lock():
        now = time.monotonic()
        with _ticker_24h_lock:
            if (_ticker_24h_cache.get("key") == key
                    and _ticker_24h_cache.get("rows") is not None
                    and now < float(_ticker_24h_cache.get("expires") or 0.0)):
                return list(_ticker_24h_cache["rows"])
        rows = await _ticker_paged("/api/v3/ticker/24hr", symbols)
        with _ticker_24h_lock:
            _ticker_24h_cache.update({
                "key": key, "rows": list(rows or []),
                "expires": time.monotonic() + TICKER_24H_CACHE_TTL_SEC,
            })
        return rows


def ticker_24h_cache_snapshot() -> dict:
    """Kısa ömürlü ticker önbelleğinin durumu."""
    now = time.monotonic()
    expires = float(_ticker_24h_cache.get("expires") or 0.0)
    return {
        "cached": _ticker_24h_cache.get("rows") is not None,
        "ttl_sec": TICKER_24H_CACHE_TTL_SEC,
        "expires_in_sec": max(0.0, expires - now) if expires else 0.0,
    }


async def ticker_price(symbols: list | None = None):
    """Son fiyat listesi."""
    return await _ticker_paged("/api/v3/ticker/price", symbols)


async def book_tickers(symbols: list | None = None):
    """Tüm (veya seçili) semboller için best-bid/ask."""
    return await _ticker_paged("/api/v3/ticker/bookTicker", symbols)


_MIN_QUOTE_VOLUME = {
    "TRY": float(config.MIN_24H_QUOTE_VOLUME_TRY),
    "USDT": float(config.MIN_QUOTE_VOLUME_USDT),
}
_DEFAULT_QUOTE_ASSET = "USDT"


def _min_quote_volume(quote_asset: str) -> float:
    key = str(quote_asset).upper()
    if key in _MIN_QUOTE_VOLUME:
        return _MIN_QUOTE_VOLUME[key]
    return _MIN_QUOTE_VOLUME.get(_DEFAULT_QUOTE_ASSET, _MIN_QUOTE_VOLUME["USDT"])


async def top_gainers(symbol_count: int = 20, *, quote_asset: str = "",
                      min_quote_volume: float | None = None,
                      _ticker_rows: list | None = None):
    """Top-gaining pairs, 24h change descending, volume-filtered (TR'de listeliler)."""
    quote_asset = quote_asset or _DEFAULT_QUOTE_ASSET
    rows = list(_ticker_rows) if _ticker_rows else await ticker_24h()
    info = await trading_symbols(quote_asset)
    trading = set(info)
    floor = (_min_quote_volume(quote_asset) if min_quote_volume is None
             else float(min_quote_volume))
    suffix = quote_asset.upper()
    candidates = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol.endswith(suffix) or symbol not in trading or not is_binance_tr_symbol(symbol):
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


async def active_movers_pool(symbol_count: int = 15, *, quote_asset: str = "",
                             min_quote_volume: float | None = None,
                             _ticker_rows: list | None = None):
    """Aktif, akışı olan ve gün içi yükseliş/volatilite gösteren çiftler."""
    quote_asset = quote_asset or _DEFAULT_QUOTE_ASSET
    rows = list(_ticker_rows) if _ticker_rows else await ticker_24h()
    info = await trading_symbols(quote_asset)
    trading = set(info)
    floor = (_min_quote_volume(quote_asset) * 0.5 if min_quote_volume is None
             else float(min_quote_volume))
    suffix = quote_asset.upper()
    movers = []

    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol.endswith(suffix) or symbol not in trading or not is_binance_tr_symbol(symbol):
            continue
        try:
            last_p = float(row.get("lastPrice") or 0)
            high_p = float(row.get("highPrice") or 0)
            low_p = float(row.get("lowPrice") or 0)
            q_vol = float(row.get("quoteVolume") or 0)
            trades = float(row.get("count") or 0)
            change = float(row.get("priceChangePercent") or 0)
        except (TypeError, ValueError):
            continue

        if q_vol < floor or last_p <= 0 or high_p <= low_p:
            continue

        range_pos = (last_p - low_p) / (high_p - low_p)
        day_range_pct = ((high_p - low_p) / low_p) * 100.0

        if day_range_pct < 1.0 or range_pos < 0.40:
            continue

        activity_score = (
            (range_pos * 40.0) +
            (min(1.0, q_vol / (_min_quote_volume(quote_asset) * 5.0)) * 30.0) +
            (min(1.0, trades / 5_000.0) * 30.0)
        ) * (1.0 + min(1.0, day_range_pct / 10.0))

        movers.append({
            "symbol": symbol,
            "activity_score": round(activity_score, 2),
            "range_pos": round(range_pos, 3),
            "day_range_pct": round(day_range_pct, 2),
            "priceChangePercent": change,
            "quoteVolume": q_vol,
            "trades": trades,
            "lastPrice": last_p
        })

    movers.sort(key=lambda item: item["activity_score"], reverse=True)
    return movers[:max(1, min(int(symbol_count), 50))]


async def orderbook(symbol: str, limit: int = 5):
    """Read-only best bid/ask depth from Binance public API."""
    normalized = symbol.replace("_", "").upper()
    payload = await asyncio.to_thread(_get_json, "/api/v3/depth", {
        "symbol": normalized, "limit": min(5, max(1, int(limit)))
    })
    if not isinstance(payload, dict):
        raise RuntimeError("Binance order-book yanıtı nesne değil")
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list):
        raise RuntimeError("Binance order-book bid/ask alanları eksik")
    return {**payload, "symbol": normalized, "bids": bids[:5], "asks": asks[:5],
            "source": "binance_public_rest", "received_at": time.time()}


async def depth(symbol: str, limit: int = 5):
    """Read-only top-limit order-book levels."""
    normalized = symbol.replace("_", "").upper()
    payload = await asyncio.to_thread(_get_json, "/api/v3/depth", {
        "symbol": normalized, "limit": min(1000, max(1, int(limit)))
    })
    if not isinstance(payload, dict):
        raise RuntimeError("Binance order-book yanıtı nesne değil")
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list):
        raise RuntimeError("Binance order-book bid/ask alanları eksik")
    return {**payload, "symbol": normalized, "bids": bids, "asks": asks,
            "source": "binance_public_rest", "received_at": time.time()}


def rate_limit_snapshot():
    """Public API rate-limit kullanım anlık görüntüsü."""
    return {
        "total_weight_used": _rate_limit_used["total"],
        "by_endpoint": dict(_rate_limit_used["by_endpoint"]),
        "last_reset_at": _rate_limit_last_reset,
        "soft_limit": REST_WEIGHT_SOFT_LIMIT,
        "max_concurrency": REST_MAX_CONCURRENCY,
        "weight_reported_at": _weight_reported_at,
        "retry_after_max_sec": REST_RETRY_AFTER_MAX_SEC,
        "ban_backoff_max_sec": REST_BAN_BACKOFF_MAX_SEC,
        "exchange_info_cache": exchange_info_cache_snapshot(),
        "ticker_24h_cache": ticker_24h_cache_snapshot(),
    }
