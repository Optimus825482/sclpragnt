"""Binance TR private (authenticated) REST adapter.

https://www.binance.tr/apidocs/ dokümanına göre:
- Base URL: https://www.binance.tr (signed istekler /open/v1/... altında)
- Auth: X-MBX-APIKEY header + HMAC-SHA256 imza (query + recvWindow + timestamp)
- Cevap zarfı: {"code": 0, "msg": "...", "data": ...} — code != 0 hata demektir
- Semboller private endpoint'lerde alt çizgili (BTC_USDT), public/market data'da bitişik (BTCUSDT)

Okuma uçları salt-okunurdur; emir gönderimi yalnızca place_market_sell ile
yapılır (admin panelindeki kullanıcı onaylı satış akışı için). Asla otomatik
emir göndermeyin; alış/çekim/acil emir yoktur.
"""
import hashlib
import hmac
import json
import logging
import math
import random
import threading
import time
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

REST_BASE = "https://www.binance.tr"
REST_TIMEOUT_SEC = 15
RECV_WINDOW_MS = 5000
# B-14: imzalı istekler için sınırlı yeniden deneme + sunucu saati ofseti.
REST_MAX_ATTEMPTS = 4
REST_BACKOFF_BASE_SEC = 0.35
REST_BACKOFF_MAX_SEC = 4.0
REST_BAN_BACKOFF_BASE_SEC = 30.0
REST_BAN_BACKOFF_MAX_SEC = 120.0
_SERVER_TIME_TTL_SEC = 300.0

_SYMBOLS_CACHE_TTL_SEC = 6 * 3600
_OPEN_ORDERS_CACHE_TTL_SEC = 30

_symbols_cache: dict = {"symbols": [], "underscore_by_concat": {}, "expires": 0.0, "filters": {}}
_symbols_lock = threading.Lock()
# B-14: sembol listesi yüklemesi TEK UÇUŞ olmalı; eskiden ağ çağrısı kilidin
# DIŞINDA yapıldığı için eşzamanlı çağrılar sürü hâlinde aynı isteği atıyordu.
_symbols_load_lock = threading.Lock()
_open_orders_cache: dict = {"orders": [], "expires": 0.0}
_open_orders_lock = threading.Lock()
_server_time_cache: dict = {"at": 0.0, "offset": 0.0}
_server_time_lock = threading.Lock()


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


def _http_post_json(url: str, headers: dict | None = None) -> dict | list:
    """Boş gövdeli POST — tüm parametreler query string'te (doküman: kabul edilir)."""
    req = Request(url, headers=headers or {}, method="POST", data=b"")
    with urlopen(req, timeout=REST_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _private_retry_delay(attempt: int) -> float:
    """Üstel backoff + jitter (B-14)."""
    exponential = min(REST_BACKOFF_MAX_SEC, REST_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))
    return exponential + random.uniform(0.0, exponential * 0.25)


def _server_time_offset_ms() -> float:
    """Sunucu saati ile yerel saat farkı (ms) — TTL'li önbellek (B-14).

    `RECV_WINDOW_MS = 5000` olduğu için yerel saat 5 sn'den fazla kayarsa
    (`-1021 Timestamp outside recvWindow`) TÜM bakiye/açık emir/satış akışı
    tek noktadan kırılır. Ofset `/open/v1/time` ile ölçülüp `timestamp`'a
    uygulanır; ölçüm başarısız olursa ofset 0 kalır (eski davranış korunur).
    """
    now = time.time()
    with _server_time_lock:
        cached = dict(_server_time_cache)
    if cached.get("at") and now - float(cached["at"]) < _SERVER_TIME_TTL_SEC:
        return float(cached.get("offset") or 0.0)
    offset = 0.0
    try:
        payload = _http_get_json(f"{REST_BASE}/open/v1/time")
        data = _unwrap(payload)
        server_ms = int((data or {}).get("serverTime") or 0) if isinstance(data, dict) else 0
        if server_ms:
            offset = float(server_ms) - now * 1000
    except Exception as exc:
        logger.info("Binance TR sunucu saati alınamadı (%s); ofset 0 varsayıldı", exc)
    with _server_time_lock:
        _server_time_cache.update({"at": now, "offset": offset})
    return offset


def _signed_request(method: str, path: str, params: dict | None,
                    api_key: str, api_secret: str) -> dict | list:
    """HMAC-SHA256 imzalı Binance TR isteği.

    Parametreler (recvWindow+timestamp+signature dahil) query string'te
    taşınır; POST için gövde boştur — dokümana göre toplam imza alanı
    "query string + body" olduğundan bu kombinasyon geçerlidir.

    B-14: `timestamp` sunucu saati ofsetiyle düzeltilir ve 429/5xx (ve ban
    sinyali 418) için sınırlı yeniden deneme yapılır; her denemede yeni
    timestamp + imza üretilir (eskiden hiç yeniden deneme yoktu).
    """
    base_params = dict(params or {})
    base_params["recvWindow"] = RECV_WINDOW_MS
    offset_ms = _server_time_offset_ms()
    headers = {"X-MBX-APIKEY": api_key}
    last_error: Exception | None = None
    for attempt in range(1, REST_MAX_ATTEMPTS + 1):
        attempt_params = dict(base_params)
        attempt_params["timestamp"] = int(time.time() * 1000 + offset_ms)
        query = urlencode(sorted(attempt_params.items()))
        signature = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"),
                             hashlib.sha256).hexdigest()
        url = f"{REST_BASE}{path}?{query}&signature={signature}"
        try:
            payload = (_http_post_json(url, headers) if method.upper() == "POST"
                       else _http_get_json(url, headers))
            return _unwrap(payload)
        except HTTPError as exc:
            last_error = exc
            if exc.code == 418:
                # Ban sinyali: uzun geri çekilme, anında raise YOK.
                if attempt == REST_MAX_ATTEMPTS:
                    break
                time.sleep(min(REST_BAN_BACKOFF_MAX_SEC, REST_BAN_BACKOFF_BASE_SEC * attempt))
                continue
            if exc.code == 429 or 500 <= exc.code < 600:
                if attempt == REST_MAX_ATTEMPTS:
                    break
                time.sleep(_private_retry_delay(attempt))
                continue
            raise
        except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == REST_MAX_ATTEMPTS:
                break
            time.sleep(_private_retry_delay(attempt))
    raise RuntimeError(
        f"Binance TR imzalı istek {REST_MAX_ATTEMPTS} denemede başarısız: {last_error}"
    ) from last_error


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
    """GET /open/v1/common/symbols — sembol listesi + bitişik→alt çizgi eşlemesi (cache'li).

    B-14: yükleme TEK UÇUŞ (single-flight). Eskiden ağ çağrısı `_symbols_lock`
    DIŞINDA yapıldığı için eşzamanlı çağrılar sürü hâlinde aynı isteği atıyordu.
    """
    if time.monotonic() < _symbols_cache["expires"]:
        return
    with _symbols_load_lock:
        # Kilidi beklerken başka bir çağrı doldurmuş olabilir.
        if time.monotonic() < _symbols_cache["expires"]:
            return
        _load_symbol_list_locked(api_key, api_secret)


def _load_symbol_list_locked(api_key: str, api_secret: str) -> None:
    now = time.monotonic()
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
        filters = {}
        for r in rows:
            sym = r.get("symbol")
            if not sym:
                continue
            entry = {"quote_asset": str(r.get("quoteAsset") or "").upper()}
            for f in r.get("filters", []) or []:
                ft = f.get("filterType")
                if ft == "LOT_SIZE":
                    entry["step_size"] = float(f.get("stepSize") or 0)
                    entry["min_qty"] = float(f.get("minQty") or 0)
                elif ft == "NOTIONAL":
                    entry["min_notional"] = float(f.get("minNotional") or f.get("notional") or 0)
            filters[sym] = entry
        _symbols_cache.update({
            "symbols": symbols,
            "underscore_by_concat": underscore_by_concat,
            "filters": filters,
            "expires": now + _SYMBOLS_CACHE_TTL_SEC,
        })
        logger.info("Binance TR sembol listesi güncellendi: %d sembol", len(symbols))


def get_symbol_filters(api_key: str, api_secret: str, symbol_underscore: str) -> dict | None:
    """Sembol filtreleri (LOT_SIZE/NOTIONAL, quoteAsset) — 6 sn cache'li liste."""
    _load_symbol_list(api_key, api_secret)
    with _symbols_lock:
        return _symbols_cache["filters"].get(symbol_underscore)


def place_market_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                      step_size: float | None = None) -> dict:
    """MARKET SELL emri gönderir (POST /open/v1/orders; side=1, type=2).

    Kullanıcı onayı UI katmanında alınır; bu fonksiyon doğrudan emir gönderir.
    Cevap: {"order_id": ..., "symbol": ..., "quantity": ...}.
    """
    # B-14: lot adımı kütüphane düzeyinde uygulanır. Adım YALNIZCA zaten
    # yüklü filtre önbelleğinden okunur — burada ağ çağrısı tetiklenmez
    # (satış yolunu yeni bir ağ bağımlılığına sokmamak için).
    if step_size is None:
        with _symbols_lock:
            entry = _symbols_cache["filters"].get(symbol_underscore) or {}
        step_size = float(entry.get("step_size") or 0) or None
    params = {
        "symbol": symbol_underscore,
        "side": 1,       # doküman: 0=BUY, 1=SELL
        "type": 2,       # doküman: 2=MARKET (satış için quantity zorunlu)
        "quantity": _fmt_quantity(quantity, step_size),
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR MARKET SELL gönderildi: %s qty=%s orderId=%s", symbol_underscore, quantity, order_id)
    return {"order_id": str(order_id) if order_id is not None else None,
            "symbol": symbol_underscore, "quantity": params["quantity"]}


def _fmt_quantity(q: float, step_size: float | None = None) -> str:
    """Miktarı API'nin beklediği ondalık string'e çevir (bilimsel gösterim yok).

    B-14: `step_size` verilirse miktar lot adımına AŞAĞI yuvarlanır
    (`floor(q/step)*step`). Eskiden yalnız 8 basamağa sabitleniyordu ve
    yuvarlama tamamen çağırana bırakılmıştı; `place_market_sell`'i doğrudan
    çağıran yeni bir yol geçersiz miktar gönderebiliyordu.
    """
    if step_size and step_size > 0:
        q = math.floor(float(q) / float(step_size)) * float(step_size)
    return f"{q:.8f}".rstrip("0").rstrip(".")


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
