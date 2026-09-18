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
            # Binance TR 4xx hataları JSON body'sinde {code, msg} taşır.
            # Body'yi okuyup anlamlı bir mesaja çeviriyoruz; başarısız olursa ham HTTP hata kodu kullanılır.
            try:
                body = exc.read().decode("utf-8", errors="replace")
                parsed = json.loads(body)
                api_code = parsed.get("code") or parsed.get("status")
                api_msg = parsed.get("msg") or parsed.get("message") or body[:200]
                binance_err = RuntimeError(f"Binance TR API hatası {api_code}: {api_msg}")
                logger.error("Binance TR HTTP %s | path=%s | code=%s msg=%s | params=%s",
                             exc.code, path, api_code, api_msg, base_params)
            except Exception:
                binance_err = RuntimeError(f"Binance TR HTTP {exc.code}: {exc.reason}")
                logger.error("Binance TR HTTP %s | path=%s | reason=%s | params=%s",
                             exc.code, path, exc.reason, base_params)
            last_error = binance_err
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
            # 4xx hataları (400, 401, 403, vb.) — anlamlı hatayla raise
            raise binance_err
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
            entry = {
                "quote_asset": str(r.get("quoteAsset") or "").upper(),
                "oco_enable": bool(int(r.get("ocoEnable") if r.get("ocoEnable") is not None else 1)),
                "order_types": r.get("orderTypes") or [],
            }
            for f in r.get("filters", []) or []:
                ft = f.get("filterType")
                if ft == "LOT_SIZE":
                    entry["step_size"] = float(f.get("stepSize") or 0)
                    entry["min_qty"] = float(f.get("minQty") or 0)
                elif ft == "NOTIONAL":
                    entry["min_notional"] = float(f.get("minNotional") or f.get("notional") or 0)
                elif ft == "PRICE_FILTER":
                    entry["tick_size"] = float(f.get("tickSize") or 0)
                    entry["min_price"] = float(f.get("minPrice") or 0)
                    entry["max_price"] = float(f.get("maxPrice") or 0)
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


def place_market_buy(api_key: str, api_secret: str, symbol_underscore: str, quote_qty: float,
                     min_notional: float | None = None) -> dict:
    """MARKET BUY emri — harcanacak QUOTE miktarıyla (POST /open/v1/orders;
    side=0, type=2).

    Doküman (güncel hizalama, 2026-09-18): MARKET alışta `quoteOrderQty`
    = kullanıcı quote asset'te harcamak istediği miktar; doğru quantity
    piyasa likiditesinden belirlenir (quoteOrderQty KULLAN, quantity'yi
    DEĞİL — ikisi birden gönderilemez).
    Cevap: {"order_id": ..., "symbol": ..., "quote_qty": ..., "executed_qty": ...,
    "avg_price": ...} (son ikisi proxy cevabında taşıyorsa dolu).
    """
    if min_notional is not None and min_notional > 0 and quote_qty < min_notional:
        raise ValueError(f"Tutar minimum emrin altında (min {min_notional})")
    params = {
        "symbol": symbol_underscore,
        "side": 0,           # doküman: 0=BUY, 1=SELL
        "type": 2,           # doküman: 2=MARKET
        "quoteOrderQty": f"{float(quote_qty):.2f}",  # quote asset (TRY) büyüklüğü
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR MARKET BUY gönderildi: %s quote=%s orderId=%s", symbol_underscore, params["quoteOrderQty"], order_id)
    out = {"order_id": str(order_id) if order_id is not None else None,
           "symbol": symbol_underscore, "quote_qty": params["quoteOrderQty"]}
    # Full cevapta doldurma bilgisi varsa ortalamayı hesapla (confirm dialogu).
    try:
        executed = float(data.get("executedQty") or 0) if isinstance(data, dict) else 0.0
        filled_quote = float(data.get("cummulativeQuoteQty") or data.get("cumulativeQuoteQty") or 0) if isinstance(data, dict) else 0.0
        if executed > 0 and filled_quote > 0:
            out["executed_qty"] = executed
            out["avg_price"] = filled_quote / executed
    except (TypeError, ValueError):
        pass
    return out


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


def _fmt_price(p: float, tick_size: float | None = None) -> str:
    """Fiyatı sembolün tick_size adımına göre yuvarlar ve string formatlar."""
    p_val = float(p)
    if tick_size and tick_size > 0:
        p_val = round(p_val / tick_size) * tick_size
        tick_str = f"{tick_size:.10f}".rstrip("0")
        decimals = len(tick_str.split(".")[1]) if "." in tick_str else 0
        return f"{p_val:.{decimals}f}"
    if p_val >= 1:
        return f"{p_val:.2f}"
    return f"{p_val:.6f}".rstrip("0").rstrip(".")


def place_oco_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                   price: float, stop_price: float, stop_limit_price: float | None = None,
                   step_size: float | None = None, tick_size: float | None = None) -> dict:
    """Spot OCO SELL emri (Take-Profit LIMIT + Stop-Loss LIMIT).

    POST /open/v1/orders/oco
    Kural: price (TP) > son fiyat > stop_price (SL trigger).
    stop_limit_price verilmezse stop_price * 0.995 (slippage korumalı) kullanılır.
    """
    if step_size is None or tick_size is None:
        with _symbols_lock:
            entry = _symbols_cache["filters"].get(symbol_underscore) or {}
        step_size = step_size or float(entry.get("step_size") or 0) or None
        tick_size = tick_size or float(entry.get("tick_size") or 0) or None

    if stop_limit_price is None or stop_limit_price <= 0:
        stop_limit_price = stop_price * 0.995

    qty_str = _fmt_quantity(quantity, step_size)
    price_str = _fmt_price(price, tick_size)
    stop_price_str = _fmt_price(stop_price, tick_size)
    stop_limit_price_str = _fmt_price(stop_limit_price, tick_size)

    params = {
        "symbol": symbol_underscore,
        "side": 1,                       # doküman: 0=BUY, 1=SELL
        "quantity": qty_str,
        "price": price_str,              # Take-Profit limit fiyatı
        "stopPrice": stop_price_str,     # SL tetik fiyatı
        "stopLimitPrice": stop_limit_price_str,
    }
    data = _signed_request("POST", "/open/v1/orders/oco", params, api_key, api_secret)
    order_list_id = data.get("orderListId") if isinstance(data, dict) else None
    orders = data.get("orders") if isinstance(data, dict) else []
    logger.info("Binance TR OCO SELL gönderildi: %s qty=%s tp=%s sl=%s orderListId=%s",
                symbol_underscore, qty_str, price_str, stop_price_str, order_list_id)
    return {
        "order_list_id": str(order_list_id) if order_list_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "tp_price": price_str,
        "sl_price": stop_price_str,
        "sl_limit_price": stop_limit_price_str,
        "orders": orders,
    }


def place_stop_loss_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                         stop_price: float, stop_limit_price: float | None = None,
                         step_size: float | None = None, tick_size: float | None = None) -> dict:
    """Tekil STOP_LOSS_LIMIT SELL emri gönderir (POST /open/v1/orders)."""
    if step_size is None or tick_size is None:
        with _symbols_lock:
            entry = _symbols_cache["filters"].get(symbol_underscore) or {}
        step_size = step_size or float(entry.get("step_size") or 0) or None
        tick_size = tick_size or float(entry.get("tick_size") or 0) or None

    if stop_limit_price is None or stop_limit_price <= 0:
        stop_limit_price = stop_price * 0.995

    qty_str = _fmt_quantity(quantity, step_size)
    stop_price_str = _fmt_price(stop_price, tick_size)
    stop_limit_price_str = _fmt_price(stop_limit_price, tick_size)

    params = {
        "symbol": symbol_underscore,
        "side": 1,                  # doküman: 0=BUY, 1=SELL
        "type": 4,                  # doküman: 4=STOP_LOSS_LIMIT
        "quantity": qty_str,
        "price": stop_limit_price_str,
        "stopPrice": stop_price_str,
        "timeInForce": 1,           # doküman: INT: 1=GTC, 2=IOC, 3=FOK, 4=GTX
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR STOP_LOSS_LIMIT SELL gönderildi: %s qty=%s sl=%s orderId=%s",
                symbol_underscore, qty_str, stop_price_str, order_id)
    return {
        "order_id": str(order_id) if order_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "sl_price": stop_price_str,
        "sl_limit_price": stop_limit_price_str,
    }


def place_limit_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                     price: float, step_size: float | None = None, tick_size: float | None = None) -> dict:
    """Tekil LIMIT (Take-Profit) SELL emri gönderir (POST /open/v1/orders)."""
    if step_size is None or tick_size is None:
        with _symbols_lock:
            entry = _symbols_cache["filters"].get(symbol_underscore) or {}
        step_size = step_size or float(entry.get("step_size") or 0) or None
        tick_size = tick_size or float(entry.get("tick_size") or 0) or None

    qty_str = _fmt_quantity(quantity, step_size)
    price_str = _fmt_price(price, tick_size)

    params = {
        "symbol": symbol_underscore,
        "side": 1,           # doküman: 0=BUY, 1=SELL
        "type": 1,           # doküman: 1=LIMIT (Take-Profit için)
        "quantity": qty_str,
        "price": price_str,
        "timeInForce": 1,    # doküman: INT: 1=GTC
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR LIMIT SELL gönderildi: %s qty=%s price=%s orderId=%s",
                symbol_underscore, qty_str, price_str, order_id)
    return {
        "order_id": str(order_id) if order_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "price": price_str,
    }


def cancel_order(api_key: str, api_secret: str, order_id: int | str, symbol_underscore: str = "") -> dict:
    """POST /open/v1/orders/cancel — Belirtilen orderId'li emri iptal eder."""
    params: dict = {"orderId": int(order_id)}
    if symbol_underscore:
        params["symbol"] = symbol_underscore
    data = _signed_request("POST", "/open/v1/orders/cancel", params, api_key, api_secret)
    with _open_orders_lock:
        _open_orders_cache["expires"] = 0.0
    logger.info("Binance TR emir iptal edildi: orderId=%s symbol=%s", order_id, symbol_underscore)
    return data if isinstance(data, dict) else {"order_id": str(order_id), "status": "CANCELED"}



def get_account_balance(api_key: str, api_secret: str) -> list[dict]:
    """GET /open/v1/account/spot → data.accountAssets [{asset, free, locked}]."""
    data = _signed_request("GET", "/open/v1/account/spot", None, api_key, api_secret)
    assets = data.get("accountAssets", []) if isinstance(data, dict) else []
    return [
        {"asset": a.get("asset", ""), "free": a.get("free", "0"), "locked": a.get("locked", "0")}
        for a in assets
    ]


def get_spot_account_raw(api_key: str, api_secret: str) -> dict:
    """GET /open/v1/account/spot — TÜM ham veri (zarfsız).

    Doküman 2026-04-07 itibarıyla cevap TRY fiat çiftleri için
    fiatMakerCommission / fiatTakerCommission da taşıyor; LLM işlem
    değerlendirmesi gerçek komisyon oranını buradan okur.
    """
    data = _signed_request("GET", "/open/v1/account/spot", None, api_key, api_secret)
    return data if isinstance(data, dict) else {}


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
                "stopPrice": o.get("stopPrice") or "0",
                "origQty": o.get("origQty", "0"),
                "executedQty": o.get("executedQty", "0"),
                "status": o.get("status", ""),
                "time": int(o.get("createTime") or o.get("time") or 0),
                "orderListId": int(o.get("orderListId") or -1),
                "clientOrderId": str(o.get("clientOrderId") or ""),
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
