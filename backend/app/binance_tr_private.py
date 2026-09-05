"""Binance TR private (authenticated, read-only) REST adapter.

https://www.binance.tr/apidocs/ dokümanına göre:
- Base URL: https://www.binance.tr (signed istekler /open/v1/... altında)
- Auth: X-MBX-APIKEY header + HMAC-SHA256 imza (query + recvWindow + timestamp)
- Cevap zarfı: {"code": 0, "msg": "...", "data": ...} — code != 0 hata demektir
- Semboller private endpoint'lerde alt çizgili (BTC_USDT), public/market data'da bitişik (BTCUSDT)

Paper-only felsefesi: asla emir gönderme, çekim veya trade yapma (yalnız GET).
"""
import hashlib
import hmac
import json
import logging
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

REST_BASE = "https://www.binance.tr"
REST_TIMEOUT_SEC = 15
RECV_WINDOW_MS = 5000

_SYMBOLS_CACHE_TTL_SEC = 6 * 3600
_OPEN_ORDERS_CACHE_TTL_SEC = 30

_symbols_cache: dict = {"symbols": [], "underscore_by_concat": {}, "expires": 0.0}
_symbols_lock = threading.Lock()
_open_orders_cache: dict = {"orders": [], "expires": 0.0}
_open_orders_lock = threading.Lock()


def _unwrap(payload: dict) -> dict | list:
    """Binance TR zarfını aç: code != 0 ise hata, yoksa data'yı döndür."""
    if not isinstance(payload, dict):
        return payload
    code = payload.get("code", payload.get("status"))
    if code not in (None, 0, "0"):
        raise RuntimeError(
            f"Binance TR API hatası {code}: {payload.get('msg') or payload.get('message') or 'bilinmiyor'}"
        )
    data = payload.get("data")
    return data if data is not None else payload


def _http_get_json(url: str, headers: dict | None = None) -> dict | list:
    req = Request(url, headers=headers or {}, method="GET")
    with urlopen(req, timeout=REST_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _signed_request(method: str, path: str, params: dict | None,
                    api_key: str, api_secret: str) -> dict | list:
    """HMAC-SHA256 imzalı Binance TR isteği (yalnız okuma, emir yok)."""
    params = dict(params or {})
    params["recvWindow"] = RECV_WINDOW_MS
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(sorted(params.items()))
    signature = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    query += f"&signature={signature}"
    url = f"{REST_BASE}{path}?{query}"
    return _unwrap(_http_get_json(url, headers={"X-MBX-APIKEY": api_key}))


def _to_underscore_symbol(symbol: str) -> str:
    """BTCUSDT → BTC_USDT (doküman: private endpoint'ler alt çizgili sembol ister)."""
    symbol = (symbol or "").upper().replace("_", "")
    if not symbol:
        return symbol
    with _symbols_lock:
        mapped = _symbols_cache["underscore_by_concat"].get(symbol)
    if mapped:
        return mapped
    for quote in ("USDT", "USDC", "USDTRY", "TRY", "BTC", "ETH", "BNB"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[:-len(quote)]}_{quote}"
    return symbol


def _load_symbol_list(api_key: str, api_secret: str) -> None:
    """GET /open/v1/common/symbols — sembol listesi + bitişik→alt çizgi eşlemesi (cache'li)."""
    now = time.monotonic()
    if now < _symbols_cache["expires"]:
        return
    with _symbols_lock:
        if now < _symbols_cache["expires"]:
            return
    try:
        payload = _http_get_json(f"{REST_BASE}/open/v1/common/symbols")
        data = _unwrap(payload)
    except Exception:
        if not api_key or not api_secret:
            raise
        # Endpoint imza istiyorsa yedek olarak signed dene.
        data = _signed_request("GET", "/open/v1/common/symbols", None, api_key, api_secret)
    rows = data.get("list", []) if isinstance(data, dict) else []
    symbols = [r.get("symbol", "") for r in rows if r.get("symbol")]
    with _symbols_lock:
        underscore_by_concat = {s.replace("_", ""): s for s in symbols}
        _symbols_cache.update({
            "symbols": symbols,
            "underscore_by_concat": underscore_by_concat,
            "expires": now + _SYMBOLS_CACHE_TTL_SEC,
        })
        logger.info("Binance TR sembol listesi güncellendi: %d sembol", len(symbols))


def get_account_balance(api_key: str, api_secret: str) -> list[dict]:
    """GET /open/v1/account/spot → data.accountAssets [{asset, free, locked}]."""
    data = _signed_request("GET", "/open/v1/account/spot", None, api_key, api_secret)
    assets = data.get("accountAssets", []) if isinstance(data, dict) else []
    return [
        {"asset": a.get("asset", ""), "free": a.get("free", "0"), "locked": a.get("locked", "0")}
        for a in assets
    ]


def get_open_orders(api_key: str, api_secret: str, symbol: str = "") -> list[dict]:
    """Açık emirler (type=1). Dokümanda /open/v1/orders için symbol zorunlu;
    sembolsüz çağrı önce denenir, reddedilirse tüm semboller taranır (30 sn cache)."""
    now = time.monotonic()
    with _open_orders_lock:
        if not symbol and now < _open_orders_cache["expires"]:
            return _open_orders_cache["orders"]

    def _normalize(rows: list) -> list[dict]:
        out = []
        for o in rows:
            out.append({
                "orderId": int(o.get("orderId") or 0),
                "symbol": o.get("symbol", ""),
                "side": o.get("side", ""),
                "type": o.get("type", ""),
                "price": o.get("price", "0"),
                "origQty": o.get("origQty", "0"),
                "executedQty": o.get("executedQty", "0"),
                "status": o.get("status", ""),
                "time": int(o.get("createTime") or 0),
            })
        return out

    if symbol:
        rows = _signed_request(
            "GET", "/open/v1/orders",
            {"symbol": _to_underscore_symbol(symbol), "type": 1, "limit": 100},
            api_key, api_secret)
        return _normalize(rows.get("list", []) if isinstance(rows, dict) else [])

    # 1) Sembolsüz deneme — API kabul ederse tek istekte tüm açık emirler.
    try:
        rows = _signed_request("GET", "/open/v1/orders", {"type": 1, "limit": 100},
                               api_key, api_secret)
        orders = _normalize(rows.get("list", []) if isinstance(rows, dict) else [])
        with _open_orders_lock:
            _open_orders_cache.update({"orders": orders, "expires": time.monotonic() + _OPEN_ORDERS_CACHE_TTL_SEC})
        return orders
    except RuntimeError as exc:
        logger.info("Sembolsüz açık emir isteği reddedildi (%s), sembol taramasına geçiliyor", exc)
    except Exception as exc:
        logger.warning("Sembolsüz açık emir isteği başarısız: %s", exc)

    # 2) Tüm spot sembollerini tek tek tara (tip=1). Hatalı sembol atlanır.
    _load_symbol_list(api_key, api_secret)
    with _symbols_lock:
        symbols = list(_symbols_cache["symbols"])
    orders: list[dict] = []
    for sym in symbols:
        try:
            rows = _signed_request(
                "GET", "/open/v1/orders",
                {"symbol": sym, "type": 1, "limit": 50},
                api_key, api_secret)
        except Exception:
            continue
        if isinstance(rows, dict) and rows.get("list"):
            orders.extend(_normalize(rows["list"]))
    with _open_orders_lock:
        _open_orders_cache.update({"orders": orders, "expires": time.monotonic() + _OPEN_ORDERS_CACHE_TTL_SEC})
    return orders


def get_trade_history(api_key: str, api_secret: str, symbol: str,
                      start_time: int | None = None, end_time: int | None = None,
                      limit: int = 100, offset: int = 0) -> list[dict]:
    """GET /open/v1/orders/trades → data.list[] geçmiş işlemler (salt okunur).

    fromId bir tradeId'dir (sayfa ofseti değil); direct=prev ile fromId'den
    yukarı doğru artan sırada döner. UI'nin beklediği alanlara (id, time)
    normalize edilir.
    """
    params: dict = {
        "symbol": _to_underscore_symbol(symbol),
        "limit": min(max(1, limit), 1000),
    }
    if start_time:
        params["startTime"] = int(start_time)
    if end_time:
        params["endTime"] = int(end_time)
    if offset > 0:
        params["fromId"] = int(offset)
        params["direct"] = "prev"
    rows = _signed_request("GET", "/open/v1/orders/trades", params, api_key, api_secret)
    items = rows.get("list", []) if isinstance(rows, dict) else []
    out = []
    for t in items:
        out.append({
            "id": int(t.get("tradeId") or 0),
            "orderId": str(t.get("orderId") or ""),
            "symbol": t.get("symbol", "").replace("_", ""),
            "price": t.get("price", "0"),
            "qty": t.get("qty", "0"),
            "quoteQty": t.get("quoteQty", "0"),
            "commission": t.get("commission", "0"),
            "commissionAsset": t.get("commissionAsset", ""),
            "isBuyer": bool(t.get("isBuyer")),
            "isMaker": bool(t.get("isMaker")),
            "time": int(t.get("time") or 0),
        })
    return out


def get_common_symbols(api_key: str = "", api_secret: str = "") -> dict:
    """GET /open/v1/common/symbols — sembol filtreleri, lot büyüklükleri vb. (public)."""
    payload = _http_get_json(f"{REST_BASE}/open/v1/common/symbols")
    return _unwrap(payload) if isinstance(payload, dict) else payload
