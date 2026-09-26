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
import uuid
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

REST_BASE = "https://www.binance.tr"
REST_TIMEOUT_SEC = 15
# #35: 5 sn'lik recvWindow, saniyede birkaç kez ölçülen ofsetin yarısı kadar
# bir emniyet payı bırakıyordu. Kilitlenen yol imzalı isteklerin TAMAMI
# (bakiye / açık emir / satış) olduğu için pencere iki katına çıkarıldı:
# 10 sn, ofset ölçümü 60 sn'de bir tazelendiğinden fazlasıyla yeterli.
RECV_WINDOW_MS = 10000
# B-14: imzalı istekler için sınırlı yeniden deneme + sunucu saati ofseti.
REST_MAX_ATTEMPTS = 4
REST_BACKOFF_BASE_SEC = 0.35
REST_BACKOFF_MAX_SEC = 4.0
REST_BAN_BACKOFF_BASE_SEC = 600.0
REST_BAN_BACKOFF_MAX_SEC = 3600.0
# #31: Retry-After'ı 4 sn'ye kırpmak, sunucunun "dakikalarca bekle" dediği anda
# isteği tekrar atmak demek. Tavan çok yüksek tutulur; sunucunun söylediği
# değer kırpılmaz.
REST_RETRY_AFTER_MAX_SEC = 300.0
# #33: private tarafta ortak eşzamanlılık sınırı yoktu. Public taraftaki desen
# (Semaphore(8)) uygulanır: sembol taraması gibi 300 çağrılık patlamalar
# imzalı uçları (bakiye, emir) tek bir anda doyurmamalı.
PRIVATE_MAX_CONCURRENCY = 4
_PRIVATE_SEMAPHORE = threading.Semaphore(PRIVATE_MAX_CONCURRENCY)
_SERVER_TIME_TTL_SEC = 60.0

_SYMBOLS_CACHE_TTL_SEC = 6 * 3600
_OPEN_ORDERS_CACHE_TTL_SEC = 30
# Sembol taraması akıllı ve sınırlı. Sadece kilitli veya ilgili varlıklar taranır.
_OPEN_ORDERS_SWEEP_MAX = 20
_OPEN_ORDERS_SWEEP_GAP_SEC = 0.10
_BALANCE_CACHE_TTL_SEC = 5.0

_symbols_cache: dict = {"symbols": [], "underscore_by_concat": {}, "expires": 0.0, "filters": {}}
_symbols_lock = threading.Lock()
# B-14: sembol listesi yüklemesi TEK UÇUŞ olmalı; eskiden ağ çağrısı kilidin
# DIŞINDA yapıldığı için eşzamanlı çağrılar sürü hâlinde aynı isteği atıyordu.
_symbols_load_lock = threading.Lock()
_open_orders_cache: dict = {"orders": [], "expires": 0.0, "partial": False}
_open_orders_lock = threading.Lock()
_open_orders_load_lock = threading.Lock()

_balance_cache: dict[str, dict] = {}
_balance_lock = threading.Lock()

_server_time_cache: dict = {"at": 0.0, "offset": 0.0}
_server_time_lock = threading.Lock()


class BinanceTrApiError(RuntimeError):
    """Binance TR API hata zarfı veya HTTP hatası."""
    def __init__(self, code: int | str, msg: str, http_code: int | None = None, raw: dict | None = None):
        super().__init__(f"Binance TR API hatası {code}: {msg}")
        self.code = code
        self.msg = msg
        self.http_code = http_code
        self.raw = raw

    @property
    def is_transient(self) -> bool:
        """1008 (Server Busy / Request Throttled) ve benzeri geçici sunucu/yoğunluk hataları."""
        c = str(self.code or "").strip()
        m = str(self.msg or "").lower()
        if c in ("1008", "-1008", "1002", "-1002", "1003", "-1003", "1007", "-1007", "1016", "-1016"):
            return True
        if "server busy" in m or "unknown error" in m or "too many requests" in m or "service unavailable" in m:
            return True
        return False


def _unwrap(payload: dict) -> dict | list:
    """Binance TR zarfını aç: code != 0 ise hata, yoksa data'yı döndür."""
    if not isinstance(payload, dict):
        return payload
    code = payload.get("code", payload.get("status"))
    if code not in (None, 0, "0"):
        msg = payload.get("msg") or payload.get("message") or "bilinmiyor"
        raise BinanceTrApiError(code=code, msg=msg, raw=payload)
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


def _private_retry_delay(attempt: int, headers=None) -> float:
    """Üstel backoff + jitter + Retry-After (B-14, #31/#33).

    #33: eskiden `exc.headers` HİÇ okunmuyordu; sunucu 429'da dakikalarca
    "bekle" dese bile istemci 0.35 sn sonra tekrar atıyordu. Public taraftaki
    mantık buraya da birebir uygulanır: sunucunun Retry-After değeri kırpılmadan
    (yalnız `REST_RETRY_AFTER_MAX_SEC` tavanına) kullanılır.
    """
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after is not None:
        try:
            return min(REST_RETRY_AFTER_MAX_SEC, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    exponential = min(REST_BACKOFF_MAX_SEC, REST_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))
    return exponential + random.uniform(0.0, exponential * 0.25)


def _private_ban_delay(attempt: int, headers=None) -> float:
    """418 (IP ban) geri çekilmesi — saniyeler değil, ONLARCA DAKİKA.

    #32: 418 kademeli IP banıdır ve dakikalar–günler sürer. 30/60/90 sn'lik
    lineer bir dizi 4 denemelik bir döngüde banı tırmandırmak demektir. Burada
    sunucunun Retry-After/Ban ipucu varsa o esas alınır, yoksa üstel geri
    çekilme en az 10 dakikadan başlar.
    """
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after is not None:
        try:
            # Ban ipucu 429 tavanından (5 dk) DAHA UZUN süre bildirebilir;
            # o yüzden ban tavanı (1 saat) kullanılır.
            return min(REST_BAN_BACKOFF_MAX_SEC, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    # #32: sunucu ipucu vermediyse üstel geri çekilme EN AZ 10 dakikadan
    # başlar (600/1200/2400 sn) ve 1 saatte tavanlanır. 4 denemelik bir
    # döngü bu ölçekte banı tırmandıramaz.
    return min(REST_BAN_BACKOFF_MAX_SEC, REST_BAN_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))


def _server_time_offset_ms() -> float:
    """Sunucu saati ile yerel saat farkı (ms) — TTL'li önbellek (B-14, #35).

    Ofset `/open/v1/time` ile ölçülüp `timestamp`'a uygulanır. #35'in asıl
    hatası: ölçüm BAŞARISIZ olduğunda ofset 0'a düşüyordu, yani sunucu saati
    ölçülemeyen bir anda 5 sn'yi aşan bir kayma TÜM bakiye/açık emir/satış
    akışını `-1021 Timestamp outside recvWindow` ile tek noktadan kırıyordu.
    Artık **son bilinen ofset korunur**; TTL 60 sn'dir (pencere 10 sn olduğu
    için bu yeterli) ve kısa aralıklarla yeniden ölçülür.
    """
    now = time.time()
    with _server_time_lock:
        cached = dict(_server_time_cache)
    if cached.get("at") and now - float(cached["at"]) < _SERVER_TIME_TTL_SEC:
        return float(cached.get("offset") or 0.0)
    measured: float | None = None
    try:
        payload = _http_get_json(f"{REST_BASE}/open/v1/time")
        data = _unwrap(payload)
        server_ms = int((data or {}).get("serverTime") or 0) if isinstance(data, dict) else 0
        if server_ms:
            measured = float(server_ms) - now * 1000
    except Exception as exc:
        logger.info("Binance TR sunucu saati alınamadı (%s); son bilinen ofset korunuyor", exc)
    with _server_time_lock:
        if measured is not None:
            _server_time_cache.update({"at": now, "offset": measured})
        # Ölçüm yoksa önceki (at, offset) ÇİZİLMEDEN bırakılır; eski ofset
        # bir sonraki başarılı ölçüme kadar geçerli kalır.
        return float(_server_time_cache.get("offset") or 0.0)


def _signed_request(method: str, path: str, params: dict | None,
                    api_key: str, api_secret: str,
                    idempotent: bool = True) -> dict | list:
    """HMAC-SHA256 imzalı Binance TR isteği.

    Parametreler (recvWindow+timestamp+signature dahil) query string'te
    taşınır; POST için gövde boştur — dokümana göre toplam imza alanı
    "query string + body" olduğundan bu kombinasyon geçerlidir.

    B-14: `timestamp` sunucu saati ofsetiyle düzeltilir ve 429/5xx (ve ban
    sinyali 418) için sınırlı yeniden deneme yapılır; her denemede yeni
    timestamp + imza üretilir (eskiden hiç yeniden deneme yoktu).

    #30 — KRİTİK (idempotency): `idempotent=False` ile çağrılan POST'lar
    (emir gönderme) timeout / 5xx / bozuk JSON sonrası **YENİDEN
    GÖNDERİLMEZ**. Aksi hâlde ağ zaman aşımında borsa emri ALDIĞI HALDE
    cevap kaybolursa aynı MARKET SELL ikinci kez atılır ve varlığın iki katı
    satılır. Yeniden deneme yalnız **418/429** için yapılır; 429'da borsa
    isteği ALMAMIŞTIR (ağırlık penceresi dolu), 429 dışı 5xx'te ise "emri
    aldım ama cevabım bozuk" durumu ayırt edilemez. `place_*` fonksiyonları
    ayrıca benzersiz bir `clientOrderId` (UUID) gönderir; borsa tarafında aynı
    anahtarı taşıyan ikinci gönderim reddedilir (bkz. `new_client_order_id`).
    """
    base_params = dict(params or {})
    base_params["recvWindow"] = RECV_WINDOW_MS
    offset_ms = _server_time_offset_ms()
    headers = {"X-MBX-APIKEY": api_key}
    last_error: Exception | None = None
    is_post = method.upper() == "POST"
    # #33: imzalı uçlara ortak eşzamanlılık sınırı. Sembol taraması gibi
    # yüzlerce çağrılık patlamalar bakiye/emir uçlarını tek anda doyuruyordu.
    with _PRIVATE_SEMAPHORE:
        for attempt in range(1, REST_MAX_ATTEMPTS + 1):
            attempt_params = dict(base_params)
            attempt_params["timestamp"] = int(time.time() * 1000 + offset_ms)
            query = urlencode(sorted(attempt_params.items()))
            signature = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"),
                                 hashlib.sha256).hexdigest()
            url = f"{REST_BASE}{path}?{query}&signature={signature}"
            try:
                payload = (_http_post_json(url, headers) if is_post
                           else _http_get_json(url, headers))
                return _unwrap(payload)
            except BinanceTrApiError as exc:
                last_error = exc
                if exc.is_transient:
                    # 1008 / -1008 (Server Busy / Request Throttled) / 1003 (Rate limit)
                    if not idempotent:
                        raise exc
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    delay = max(1.0, _private_retry_delay(attempt))
                    logger.warning(
                        "Binance TR geçici sunucu/yoğunluk yanıtı (kod %s, %s) | path=%s | %.2f sn beklenip yeniden denenecek (%d/%d)",
                        exc.code, exc.msg, path, delay, attempt, REST_MAX_ATTEMPTS
                    )
                    time.sleep(delay)
                    continue
                if str(exc.code) in ("1021", "-1021"):
                    # Timestamp outside recvWindow — saat ofsetini sıfırlayıp tazele
                    with _server_time_lock:
                        _server_time_cache["at"] = 0.0
                    offset_ms = _server_time_offset_ms()
                    if attempt < REST_MAX_ATTEMPTS:
                        time.sleep(0.5)
                        continue
                raise exc
            except HTTPError as exc:
                # Binance TR 4xx hataları JSON body'sinde {code, msg} taşır.
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                    parsed = json.loads(body)
                    api_code = parsed.get("code") or parsed.get("status") or exc.code
                    api_msg = parsed.get("msg") or parsed.get("message") or body[:200]
                    binance_err = BinanceTrApiError(api_code, api_msg, http_code=exc.code, raw=parsed)
                    logger.error("Binance TR HTTP %s | path=%s | code=%s msg=%s | params=%s",
                                 exc.code, path, api_code, api_msg, base_params)
                except Exception:
                    binance_err = BinanceTrApiError(exc.code, exc.reason, http_code=exc.code)
                    logger.error("Binance TR HTTP %s | path=%s | reason=%s | params=%s",
                                 exc.code, path, exc.reason, base_params)
                last_error = binance_err
                if exc.code == 418:
                    # #32: Ban sinyali.
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    time.sleep(_private_ban_delay(attempt, exc.headers))
                    continue
                if exc.code == 429 or (500 <= exc.code < 600) or binance_err.is_transient:
                    if not idempotent and exc.code != 429 and not binance_err.is_transient:
                        raise binance_err
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    delay = max(1.0, _private_retry_delay(attempt, exc.headers)) if binance_err.is_transient else _private_retry_delay(attempt, exc.headers)
                    logger.warning(
                        "Binance TR HTTP %s geçici hata (kod %s) | %.2f sn sonra yeniden denenecek (%d/%d)",
                        exc.code, binance_err.code, delay, attempt, REST_MAX_ATTEMPTS
                    )
                    time.sleep(delay)
                    continue
                # 4xx hataları (400, 401, 403, vb.) — anlamlı hatayla raise
                raise binance_err
            except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                # #30: bu kolon "istek borsaya ULAŞTI mı?" sorusunun cevabı
                # OLMAYAN durumlardır. Okuma için yeniden denemek zararsızdır;
                # POST (emir) için ASLA — çağıranın durum sorgulaması gerekir.
                last_error = exc
                if not idempotent:
                    raise RuntimeError(
                        f"Binance TR {method.upper()} {path} cevap vermedi; emir gönderilmiş "
                        f"olabilir, TEKRAR GÖNDERİLMEDİ: {exc}"
                    ) from exc
                if attempt == REST_MAX_ATTEMPTS:
                    break
                time.sleep(_private_retry_delay(attempt))
    raise RuntimeError(
        f"Binance TR imzalı istek {REST_MAX_ATTEMPTS} denemede başarısız: {last_error}"
    ) from last_error


def new_client_order_id(prefix: str = "sc") -> str:
    """Emirlere iliştirilecek benzersiz `clientOrderId` (#30 idempotency).

    Binance `clientOrderId` alanı en fazla 36 karakter kabul eder; UUID hex'i
    güvenle sığar. Anahtar BORSADA saklanır: ağ zaman aşımı sonrası aynı
    anahtarla yapılan ikinci gönderim "duplicate" olarak reddedilir → varlık
    iki kez satılmaz. Çağıran, aynı iş mantığı için aynı `id`'yi saklayıp
    yeniden denediğinde borsa iki ayrı emir oluşturmaz.
    """
    return f"{prefix}{uuid.uuid4().hex}"[:36]


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
                      step_size: float | None = None, client_order_id: str | None = None,
                      min_notional: float | None = None,
                      last_price: float | None = None) -> dict:
    """MARKET SELL emri gönderir (POST /open/v1/orders; side=1, type=2).

    Kullanıcı onayı UI katmanında alınır; bu fonksiyon doğrudan emir gönderir.
    Cevap: {"order_id": ..., "symbol": ..., "quantity": ...}.

    #30: `client_order_id` verilmezse deterministik olmayan bir UUID üretilir;
    bu anahtar borsada emirle birlikte saklanır, böylece timeout sonrası
    yapılan ikinci gönderim "duplicate" olarak reddedilir. `_signed_request`
    `idempotent=False` ile çağrılır → timeout/5xx/bozuk JSON'da emir ASLA
    tekrar atılmaz.

    #34: `min_notional` verilirse borsadaki NOTIONAL filtresi istemci tarafında
    da uygulanır. Kalan toz bakiyenin (ör. 5 TRY'lik BTC kesirinin tamamı)
    filtreye takılıp 502 üretmesi ve varlıkta kalıcı toz bırakması yerine
    çağıran açık bir hata alır. `last_price` ile kaba tahmin yapılır
    (bakiye endpoint'i fiyat döndürmez); emin değilsek borsa karar verir.
    """
    # B-14: lot adımı kütüphane düzeyinde uygulanır. Adım YALNIZCA zaten
    # yüklü filtre önbelleğinden okunur — burada ağ çağrısı tetiklenmez
    # (satış yolunu yeni bir ağ bağımlılığına sokmamak için).
    entry: dict = {}
    if step_size is None or min_notional is None:
        with _symbols_lock:
            entry = _symbols_cache["filters"].get(symbol_underscore) or {}
        if step_size is None:
            step_size = float(entry.get("step_size") or 0) or None
        if min_notional is None:
            min_notional = float(entry.get("min_notional") or 0) or None
    params = {
        "symbol": symbol_underscore,
        "side": 1,       # doküman: 0=BUY, 1=SELL
        "type": 2,       # doküman: 2=MARKET (satış için quantity zorunlu)
        "quantity": _fmt_quantity(quantity, step_size),
        # #30 idempotency anahtarı (aynı iş mantığı için aynı id saklanırsa
        # borsa ikinci gönderimi duplicate olarak reddeder).
        "clientOrderId": client_order_id or new_client_order_id("sa"),
    }
    # #34: minimum işlem tutarı istemci tarafında da uygulanır. Fiyat bilinmiyorsa
    # tahmin yapılmaz — borsanın kendi filtresi son sözü söyler.
    if min_notional and min_notional > 0 and last_price and last_price > 0:
        if (params["quantity"] and float(params["quantity"]) * float(last_price)) < min_notional:
            raise ValueError(
                f"Satış tutarı minimum emrin altında "
                f"(min {min_notional}, tahmini {float(params['quantity']) * float(last_price):.2f})"
            )
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                           idempotent=False)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR MARKET SELL gönderildi: %s qty=%s orderId=%s clientOrderId=%s",
                symbol_underscore, quantity, order_id, params["clientOrderId"])
    invalidate_account_balance_cache(api_key)
    with _open_orders_lock:
        _open_orders_cache["expires"] = 0.0
    return {"order_id": str(order_id) if order_id is not None else None,
            "symbol": symbol_underscore, "quantity": params["quantity"],
            "client_order_id": params["clientOrderId"]}


def place_market_buy(api_key: str, api_secret: str, symbol_underscore: str, quote_qty: float,
                     min_notional: float | None = None,
                     client_order_id: str | None = None) -> dict:
    """MARKET BUY emri — harcanacak QUOTE miktarıyla (POST /open/v1/orders;
    side=0, type=2).

    Doküman (güncel hizalama, 2026-09-18): MARKET alışta `quoteOrderQty`
    = kullanıcı quote asset'te harcamak istediği miktar; doğru quantity
    piyasa likiditesinden belirlenir (quoteOrderQty KULLAN, quantity'yi
    DEĞİL — ikisi birden gönderilemez).
    Cevap: {"order_id": ..., "symbol": ..., "quote_qty": ..., "executed_qty": ...,
    "avg_price": ...} (son ikisi proxy cevabında taşıyorsa dolu).

    #30: `client_order_id` (UUID) idempotency anahtarıdır; `_signed_request`
    `idempotent=False` ile çağrılır.
    """
    if min_notional is not None and min_notional > 0 and quote_qty < min_notional:
        raise ValueError(f"Tutar minimum emrin altında (min {min_notional})")
    params = {
        "symbol": symbol_underscore,
        "side": 0,           # doküman: 0=BUY, 1=SELL
        "type": 2,           # doküman: 2=MARKET
        "quoteOrderQty": f"{float(quote_qty):.2f}",  # quote asset (TRY) büyüklüğü
        # #30 idempotency anahtarı.
        "clientOrderId": client_order_id or new_client_order_id("bu"),
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                           idempotent=False)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR MARKET BUY gönderildi: %s quote=%s orderId=%s clientOrderId=%s",
                symbol_underscore, params["quoteOrderQty"], order_id, params["clientOrderId"])
    invalidate_account_balance_cache(api_key)
    with _open_orders_lock:
        _open_orders_cache["expires"] = 0.0
    out = {"order_id": str(order_id) if order_id is not None else None,
           "symbol": symbol_underscore, "quote_qty": params["quoteOrderQty"],
           "client_order_id": params["clientOrderId"]}
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
                   step_size: float | None = None, tick_size: float | None = None,
                   client_order_id: str | None = None,
                   min_notional: float | None = None,
                   last_price: float | None = None) -> dict:
    """Spot OCO SELL emri (Take-Profit LIMIT + Stop-Loss LIMIT).

    POST /open/v1/orders/oco
    Kural: price (TP) > son fiyat > stop_price (SL trigger).
    stop_limit_price verilmezse stop_price * 0.995 (slippage korumalı) kullanılır.

    #30: `client_order_id` (UUID) idempotency anahtarıdır; timeout sonrası aynı
    mantıkla yeniden denemek borsada ikinci bir OCO listesi oluşturmaz.
    #34: `min_notional` + `last_price` verilirse minimum tutar istemci tarafında
    da uygulanır (bakiye endpoint'i fiyat döndürmediği için tahmindir).
    """
    if step_size is None or tick_size is None or min_notional is None:
        with _symbols_lock:
            entry = _symbols_cache["filters"].get(symbol_underscore) or {}
        step_size = step_size or float(entry.get("step_size") or 0) or None
        tick_size = tick_size or float(entry.get("tick_size") or 0) or None
        min_notional = min_notional or float(entry.get("min_notional") or 0) or None

    if stop_limit_price is None or stop_limit_price <= 0:
        stop_limit_price = stop_price * 0.995

    qty_str = _fmt_quantity(quantity, step_size)
    price_str = _fmt_price(price, tick_size)
    stop_price_str = _fmt_price(stop_price, tick_size)
    stop_limit_price_str = _fmt_price(stop_limit_price, tick_size)

    if min_notional and min_notional > 0 and last_price and last_price > 0:
        if float(qty_str or 0) * float(last_price) < min_notional:
            raise ValueError(
                f"Emir tutarı minimum emrin altında "
                f"(min {min_notional}, tahmini {float(qty_str or 0) * float(last_price):.2f})"
            )

    params = {
        "symbol": symbol_underscore,
        "side": 1,                       # doküman: 0=BUY, 1=SELL
        "quantity": qty_str,
        "price": price_str,              # Take-Profit limit fiyatı
        "stopPrice": stop_price_str,     # SL tetik fiyatı
        "stopLimitPrice": stop_limit_price_str,
        # #30 idempotency anahtarı.
        "clientOrderId": client_order_id or new_client_order_id("oc"),
    }
    data = _signed_request("POST", "/open/v1/orders/oco", params, api_key, api_secret,
                           idempotent=False)
    order_list_id = data.get("orderListId") if isinstance(data, dict) else None
    orders = data.get("orders") if isinstance(data, dict) else []
    logger.info("Binance TR OCO SELL gönderildi: %s qty=%s tp=%s sl=%s orderListId=%s",
                symbol_underscore, qty_str, price_str, stop_price_str, order_list_id)
    invalidate_account_balance_cache(api_key)
    with _open_orders_lock:
        _open_orders_cache["expires"] = 0.0
    return {
        "order_list_id": str(order_list_id) if order_list_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "tp_price": price_str,
        "sl_price": stop_price_str,
        "sl_limit_price": stop_limit_price_str,
        "orders": orders,
        "client_order_id": params["clientOrderId"],
    }


def place_stop_loss_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                         stop_price: float, stop_limit_price: float | None = None,
                         step_size: float | None = None, tick_size: float | None = None,
                         client_order_id: str | None = None) -> dict:
    """Tekil STOP_LOSS_LIMIT SELL emri gönderir (POST /open/v1/orders).

    #30: `client_order_id` (UUID) idempotency anahtarıdır; `_signed_request`
    `idempotent=False` ile çağrılır (timeout sonrası ikinci emir atılmaz).
    """
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
        # #30 idempotency anahtarı.
        "clientOrderId": client_order_id or new_client_order_id("sl"),
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                           idempotent=False)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR STOP_LOSS_LIMIT SELL gönderildi: %s qty=%s sl=%s orderId=%s",
                symbol_underscore, qty_str, stop_price_str, order_id)
    invalidate_account_balance_cache(api_key)
    with _open_orders_lock:
        _open_orders_cache["expires"] = 0.0
    return {
        "order_id": str(order_id) if order_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "sl_price": stop_price_str,
        "sl_limit_price": stop_limit_price_str,
        "client_order_id": params["clientOrderId"],
    }


def place_limit_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                     price: float, step_size: float | None = None, tick_size: float | None = None,
                     client_order_id: str | None = None) -> dict:
    """Tekil LIMIT (Take-Profit) SELL emri gönderir (POST /open/v1/orders).

    #30: `client_order_id` (UUID) idempotency anahtarıdır; `_signed_request`
    `idempotent=False` ile çağrılır.
    """
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
        # #30 idempotency anahtarı.
        "clientOrderId": client_order_id or new_client_order_id("tp"),
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                           idempotent=False)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR LIMIT SELL gönderildi: %s qty=%s price=%s orderId=%s",
                symbol_underscore, qty_str, price_str, order_id)
    invalidate_account_balance_cache(api_key)
    with _open_orders_lock:
        _open_orders_cache["expires"] = 0.0
    return {
        "order_id": str(order_id) if order_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "price": price_str,
        "client_order_id": params["clientOrderId"],
    }


def invalidate_account_balance_cache(api_key: str = "") -> None:
    """Hesap bakiye önbelleğini sıfırlar (emir sonrası taze veri için)."""
    with _balance_lock:
        if api_key:
            _balance_cache.pop(api_key[:16], None)
        else:
            _balance_cache.clear()


def cancel_order(api_key: str, api_secret: str, order_id: int | str, symbol_underscore: str = "") -> dict:
    """POST /open/v1/orders/cancel — Belirtilen orderId'li emri iptal eder."""
    params: dict = {"orderId": int(order_id)}
    if symbol_underscore:
        params["symbol"] = symbol_underscore
    data = _signed_request("POST", "/open/v1/orders/cancel", params, api_key, api_secret)
    with _open_orders_lock:
        _open_orders_cache["expires"] = 0.0
    invalidate_account_balance_cache(api_key)
    logger.info("Binance TR emir iptal edildi: orderId=%s symbol=%s", order_id, symbol_underscore)
    return data if isinstance(data, dict) else {"order_id": str(order_id), "status": "CANCELED"}



def get_account_balance(api_key: str, api_secret: str, force_refresh: bool = False) -> list[dict]:
    """GET /open/v1/account/spot → data.accountAssets [{asset, free, locked}].

    Kısa süreli (5 sn) bellek önbelleği uygulanır: /account, /positions, /trades-day
    ve açık emir kontrolleri aynı anda çağrıldığında Binance TR API'sine tek istek atılır.
    """
    cache_key = (api_key or "")[:16]
    now = time.monotonic()
    if not force_refresh and cache_key:
        with _balance_lock:
            cached = _balance_cache.get(cache_key)
            if cached and now < cached["expires"]:
                return cached["data"]

    data = _signed_request("GET", "/open/v1/account/spot", None, api_key, api_secret)
    assets = data.get("accountAssets", []) if isinstance(data, dict) else []
    result = [
        {"asset": a.get("asset", ""), "free": a.get("free", "0"), "locked": a.get("locked", "0")}
        for a in assets
    ]
    if cache_key:
        with _balance_lock:
            _balance_cache[cache_key] = {"data": result, "expires": now + _BALANCE_CACHE_TTL_SEC}
    return result


def get_spot_account_raw(api_key: str, api_secret: str) -> dict:
    """GET /open/v1/account/spot — TÜM ham veri (zarfsız).

    Doküman 2026-04-07 itibarıyla cevap TRY fiat çiftleri için
    fiatMakerCommission / fiatTakerCommission da taşıyor; LLM işlem
    değerlendirmesi gerçek komisyon oranını buradan okur.
    """
    data = _signed_request("GET", "/open/v1/account/spot", None, api_key, api_secret)
    return data if isinstance(data, dict) else {}


def get_open_orders(api_key: str, api_secret: str, symbol: str = "",
                    candidate_symbols: list[str] | None = None) -> list[dict]:
    """Açık emirler (type=1). Dokümanda /open/v1/orders için symbol zorunlu.

    Akıllı tarama mimarisi:
    1. Sembol verilmişse doğrudan o sembol sorgulanır.
    2. Sembol verilmemişse önce mevcut önbelleğe bakılır.
    3. Önbellek yoksa tek uçuş kilidi (_open_orders_load_lock) altında bakiyedeki
       kilitli (locked) varlıklara bakılır:
       - Hiçbir varlık kilitli değilse açık emir bulunması imkânsızdır -> 0 istek.
       - Kilitli varlıklar varsa yalnızca o varlıkların TRY/USDT çiftleri taranır.
       - Bu sayede 40-50 rasgele sembol taranarak borsa rate limitlerine takılınmaz (kod 1008).
    """
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

    with _open_orders_load_lock:
        now = time.monotonic()
        with _open_orders_lock:
            if now < _open_orders_cache["expires"]:
                return _open_orders_cache["orders"]

        # 1) Akıllı hedef belirleme: Kilitli varlık analizi
        # Spot borsada açık emir varsa varlık MUTLAKA locked > 0 durumundadır.
        # Hiçbir varlık kilitli değilse açık emir bulunması imkânsızdır -> 0 istek.
        locked_assets: set[str] = set()
        active_assets: set[str] = set()
        has_balance_info = False
        try:
            balances = get_account_balance(api_key, api_secret)
            if isinstance(balances, list) and len(balances) > 0:
                has_balance_info = True
                for b in balances:
                    free = float(b.get("free", 0) or 0)
                    locked = float(b.get("locked", 0) or 0)
                    asset = str(b.get("asset") or "").upper()
                    if not asset:
                        continue
                    if locked > 0:
                        locked_assets.add(asset)
                    if free > 0 or locked > 0:
                        active_assets.add(asset)
        except Exception as exc:
            logger.debug("Açık emir ön kontrolünde bakiye okunamadı: %s", exc)

        # Kilitli hiçbir varlık yoksa açık emir bulunması imkânsızdır
        if has_balance_info and len(locked_assets) == 0:
            with _open_orders_lock:
                _open_orders_cache.update({"orders": [], "partial": False,
                                           "expires": time.monotonic() + _OPEN_ORDERS_CACHE_TTL_SEC})
            return []

        # 2) Sembolsüz istek borsa tarafından kabul edilirse tek istekte tamamla
        try:
            rows = _signed_request("GET", "/open/v1/orders", {"type": 1, "limit": 100},
                                   api_key, api_secret)
            orders = _normalize(rows.get("list", []) if isinstance(rows, dict) else [])
            with _open_orders_lock:
                _open_orders_cache.update({"orders": orders, "partial": False,
                                           "expires": time.monotonic() + _OPEN_ORDERS_CACHE_TTL_SEC})
            return orders
        except Exception as exc:
            logger.debug("Sembolsüz açık emir isteği kabul edilmedi (%s); akıllı taramaya geçiliyor", exc)

        _load_symbol_list(api_key, api_secret)
        with _symbols_lock:
            valid_symbols = set(_symbols_cache.get("symbols", []))

        target_symbols: list[str] = []
        if has_balance_info and locked_assets:
            # Kilitli coin'lerin satış çiftleri (örn. BTC kilitliyse BTC_TRY, BTC_USDT)
            for asset in (locked_assets - {"TRY", "USDT"}):
                for quote in ("TRY", "USDT"):
                    cand = f"{asset}_{quote}"
                    if cand in valid_symbols and cand not in target_symbols:
                        target_symbols.append(cand)

            # TRY veya USDT kilitliyse (alış emri var): kullanıcının aktif varlıkları ve adaylar
            if "TRY" in locked_assets or "USDT" in locked_assets:
                for asset in (active_assets - {"TRY", "USDT"}):
                    for quote in ("TRY", "USDT"):
                        cand = f"{asset}_{quote}"
                        if cand in valid_symbols and cand not in target_symbols:
                            target_symbols.append(cand)
                if candidate_symbols:
                    for s in candidate_symbols:
                        u_s = _to_underscore_symbol(s)
                        if u_s in valid_symbols and u_s not in target_symbols:
                            target_symbols.append(u_s)

        # Bakiye bilgisi alınamadıysa veya hedef boş kaldıysa genel sembol listesinden sınırla
        if not target_symbols:
            with _symbols_lock:
                all_symbols = list(_symbols_cache.get("symbols", []))
            target_symbols = all_symbols

        scanned = target_symbols[:_OPEN_ORDERS_SWEEP_MAX]
        skipped = len(target_symbols) - len(scanned)
        orders = []
        failures = []
        for index, sym in enumerate(scanned):
            try:
                rows = _signed_request(
                    "GET", "/open/v1/orders",
                    {"symbol": sym, "type": 1, "limit": 50},
                    api_key, api_secret)
            except Exception as exc:
                failures.append((sym, exc))
                continue
            if isinstance(rows, dict) and rows.get("list"):
                orders.extend(_normalize(rows["list"]))
            if index < len(scanned) - 1:
                time.sleep(_OPEN_ORDERS_SWEEP_GAP_SEC)

        partial = bool(failures) or skipped > 0
        if failures:
            logger.warning("Açık emir taramasında %d/%d sembol sorgulanamadı: %s",
                           len(failures), len(scanned),
                           ", ".join(f"{sym}({type(exc).__name__})" for sym, exc in failures[:10]))
        if skipped:
            logger.warning("Açık emir taraması KISMİ: %d/%d sembol tarandı (sınır %d)",
                           len(scanned), len(target_symbols), _OPEN_ORDERS_SWEEP_MAX)
        with _open_orders_lock:
            _open_orders_cache.update({"orders": orders, "partial": partial,
                                       "expires": time.monotonic() + _OPEN_ORDERS_CACHE_TTL_SEC})
        return orders


def get_open_orders_partial(api_key: str, api_secret: str) -> bool:
    """Son açık-emir sonucunun kısmi olup olmadığını döner (#33).

    Tarama sınırına takıldığında veya bir sembol sorgulanamadığında `True`.
    Çağıran (UI/API) bunu kullanıcıya "liste eksik olabilir" diye bildirmeli.
    """
    with _open_orders_lock:
        return bool(_open_orders_cache.get("partial"))


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
