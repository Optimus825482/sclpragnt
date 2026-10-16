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

# Binance TR resmi dokümantasyonu: IP başına 1 dakikada 1200 request weight sınırı.
REST_MAX_WEIGHT_1M = 1200
REST_WEIGHT_SOFT_LIMIT = 950  # 950'ye ulaşınca proaktif bekleme
REST_REQUEST_GAP_SEC = 0.08  # İki private istek arası min 80ms (istek patlamasını önler)

# B-14: imzalı istekler için sınırlı yeniden deneme + sunucu saati ofseti.
REST_MAX_ATTEMPTS = 5
REST_BACKOFF_BASE_SEC = 1.0
REST_BACKOFF_MAX_SEC = 10.0
REST_BAN_BACKOFF_BASE_SEC = 600.0
REST_BAN_BACKOFF_MAX_SEC = 3600.0
# #31: Retry-After'ı 4 sn'ye kırpmak, sunucunun "dakikalarca bekle" dediği anda
# isteği tekrar atmak demek. Tavan çok yüksek tutulur; sunucunun söylediği
# değer kırpılmaz.
REST_RETRY_AFTER_MAX_SEC = 300.0
# #33: private tarafta ortak eşzamanlılık sınırı.
PRIVATE_MAX_CONCURRENCY = 3
_PRIVATE_SEMAPHORE = threading.Semaphore(PRIVATE_MAX_CONCURRENCY)
# Emir POST'ları okuma yoğunluğunda (bakiye/sembol taraması) yuva beklemesin diye ayrı yuva.
ORDER_MAX_CONCURRENCY = 4
_ORDER_SEMAPHORE = threading.Semaphore(ORDER_MAX_CONCURRENCY)
_ORDER_PATHS = ("/open/v1/orders", "/open/v1/orders/oco")


def _semaphore_for(method: str, path: str) -> threading.Semaphore:
    return _ORDER_SEMAPHORE if method.upper() == "POST" and path in _ORDER_PATHS else _PRIVATE_SEMAPHORE
_SERVER_TIME_TTL_SEC = 60.0

_used_weight_1m = 0
_weight_reported_at = 0.0
_rate_limit_lock = threading.Lock()
_cooldown_until = 0.0
_last_request_time = [0.0]

_SYMBOLS_CACHE_TTL_SEC = 6 * 3600
_OPEN_ORDERS_CACHE_TTL_SEC = 30
# Sembol taraması akıllı ve sınırlı. Sadece kilitli veya ilgili varlıklar taranır.
_OPEN_ORDERS_SWEEP_MAX = 20
_OPEN_ORDERS_SWEEP_GAP_SEC = 0.10
# PERFORMANS (2026-09-27): 5→15 sn. Sayfa ilk yüklemesinde /account, /positions,
# /open-orders, /trades-day AYNI ANDA gelir; 5 sn TTL'de her biri ayrı harici
# çağrı yapıyordu. 15 sn = WS push döngüsü kadansı (binance_account_push_loop)
# → WS verisi eskisi kadar taze kalır, uçlar arası burst tek çağrıya iner.
# Emir yolları invalidate_account_balance_cache ile tazeler.
_BALANCE_CACHE_TTL_SEC = 15.0

_symbols_cache: dict = {"symbols": [], "underscore_by_concat": {}, "expires": 0.0, "filters": {}}
_symbols_lock = threading.Lock()
# B-14: sembol listesi yüklemesi TEK UÇUŞ olmalı; eskiden ağ çağrısı kilidin
# DIŞINDA yapıldığı için eşzamanlı çağrılar sürü hâlinde aynı isteği atıyordu.
_symbols_load_lock = threading.Lock()
# KULLANICIYA ÖZEL önbellek: anahtar = sha256(api_key)[:16]. Eskiden tek GLOBAL sözlüktü; `symbol` verilmeden
# çağrılınca önbellekte kimin emirleri varsa herkese dönüyordu (kullanıcılar birbirinin açık emirlerini görüyordu).
_open_orders_caches: dict[str, dict] = {}
_open_orders_lock = threading.Lock()


def _open_orders_cache_for(api_key: str) -> dict:
    """Bu API anahtarına ait açık-emir önbellek kaydı (yoksa boş oluşturur). Güncellemeyi çağıran kilit altında yapar."""
    key = hashlib.sha256(str(api_key or "").encode("utf-8")).hexdigest()[:16]
    with _open_orders_lock:
        return _open_orders_caches.setdefault(key, {"orders": [], "expires": 0.0, "partial": False})


def _invalidate_open_orders(api_key: str) -> None:
    """Yalnız bu kullanıcının açık-emir önbelleğini geçersiz kılar (emir/iptal sonrası)."""
    cache = _open_orders_cache_for(api_key)
    with _open_orders_lock:
        cache["expires"] = 0.0
_open_orders_load_lock = threading.Lock()

_balance_cache: dict[str, dict] = {}
_balance_lock = threading.Lock()

# İSTEMCİ İDEMPOTENCY (2026-10-15, denetim P0-2): UI her onay penceresi için
# tek bir `client_order_id` üretir ve emir POST'unda gönderir. Zaman aşımı /
# ağ hatası sonrası aynı kimlikle gelen tekrar isteği borsaya İKİNCİ kez
# gitmez; son 10 dakikanın yanıtı önbellekten döner. Anahtar kullanıcı
# anahtarına (api_key özeti) bağlıdır; farklı hesaplar birbirini göremez.
# Binance TR clientId benzersizlik garantisi vermediği için bu koruma
# borsada değil BURADA uygulanır.
_RECENT_CLIENT_ORDERS_TTL_SEC = 10 * 60
_recent_client_orders: dict[str, tuple[float, dict]] = {}
_recent_client_orders_lock = threading.Lock()

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


class BinanceTrAmbiguousOrderError(RuntimeError):
    """Emir POST cevabı belirsiz; emir gerçekleşmiş olabilir, tekrar gönderilmemelidir."""
    def __init__(self, message: str, *, client_order_id: str, symbol: str):
        super().__init__(message)
        self.client_order_id = client_order_id
        self.symbol = symbol


class BinanceTrPartialFillError(RuntimeError):
    """MARKET SELL kısmi doldu — istenen miktarın tamamı satılamadı (#36/P1-8).

    Emir borsada KABUL edilmiştir ve `executedQty` kadar dolmuştur; kalan
    miktar pozisyonda AÇIK kalır. Hata fırlatmak, çağıranı bunu sessizce tam
    dolum sayıp pozisyonu yanlış kapatmasından korur: `remaining_qty` ile
    mutabakat yapmalıdır (`reconcile_sell_fill`).
    """

    def __init__(self, message: str, *, requested_qty: float, executed_qty: float,
                 remaining_qty: float, result: dict | None = None):
        super().__init__(message)
        self.requested_qty = requested_qty
        self.executed_qty = executed_qty
        self.remaining_qty = remaining_qty
        # Borsa cevabından türetilen kısmi sonuç (order_id/avg_price/...).
        self.result = result or {}


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


def _record_used_weight(resp_headers) -> None:
    """X-MBX-USED-WEIGHT-1M başlığını yakalayarak global ağırlık durumunu günceller."""
    global _used_weight_1m, _weight_reported_at
    if not resp_headers:
        return
    used_val = None
    for k, v in resp_headers.items():
        if k.lower() in ("x-mbx-used-weight-1m", "x-mbx-used-weight"):
            try:
                used_val = int(v)
                break
            except (ValueError, TypeError):
                pass
    if used_val is not None:
        with _rate_limit_lock:
            _used_weight_1m = used_val
            _weight_reported_at = time.time()


def _update_cooldown(delay: float) -> None:
    """Aktif cooldown bitiş zamanını günceller."""
    global _cooldown_until
    with _rate_limit_lock:
        _cooldown_until = max(_cooldown_until, time.time() + delay)


def _throttle_private_request() -> None:
    """Sunucunun bildirdiği ağırlık tavana yaklaştıysa veya aktif cooldown varsa bekle."""
    now = time.time()

    # 1. Aktif cooldown (429/418 sonrası) kontrolü
    with _rate_limit_lock:
        cooldown = _cooldown_until - now
    if cooldown > 0:
        logger.info("Binance TR rate-limit cooldown devrede, %.2fs bekleniyor...", cooldown)
        time.sleep(min(cooldown, 60.0))
        return

    # 2. Akıllı ağırlık kontrolü ve dinamik pacing
    with _rate_limit_lock:
        age = now - _weight_reported_at
        current_weight = _used_weight_1m if (0 <= age < 60.0) else 0

    if current_weight >= 1100:
        # Gerçekten kritik tavan (1100/1200): IP ban riskini önlemek için pencerenin sıfırlanmasını bekle
        wait = min(max(1.0, 60.0 - age), 15.0)
        logger.warning(
            "Binance TR ağırlığı acil seviyede (%d/%d, yaş: %.1fs). Koruma beklemesi: %.1fs",
            current_weight, REST_MAX_WEIGHT_1M, age, wait
        )
        time.sleep(wait)
    elif current_weight >= REST_WEIGHT_SOFT_LIMIT:
        # Yumuşak sınır (950-1100): Sistemi 60s kitlemek yerine dinamik pacing uygula.
        # İstekler arasına mikro gecikme koyarak tüketim hızını düşür ve ağırlığın erimesini sağla.
        pacing = 0.25 + (0.5 * ((current_weight - REST_WEIGHT_SOFT_LIMIT) / 150.0))
        time.sleep(pacing)


def _http_get_json(url: str, headers: dict | None = None) -> dict | list:
    req = Request(url, headers=headers or {}, method="GET")
    with urlopen(req, timeout=REST_TIMEOUT_SEC) as resp:
        _record_used_weight(resp.headers)
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, headers: dict | None = None) -> dict | list:
    """Boş gövdeli POST — tüm parametreler query string'te (doküman: kabul edilir)."""
    req = Request(url, headers=headers or {}, method="POST", data=b"")
    with urlopen(req, timeout=REST_TIMEOUT_SEC) as resp:
        _record_used_weight(resp.headers)
        return json.loads(resp.read().decode("utf-8"))


def _private_retry_delay(attempt: int, headers=None, is_429: bool = False) -> float:
    """Üstel backoff + jitter + Retry-After (B-14, #31/#33).

    Binance TR resmi dakikalık (1200 weight/min) limitinde 429 alındığında
    0.35s yerine en az 8s-32s beklenir.
    """
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after is not None:
        try:
            return min(REST_RETRY_AFTER_MAX_SEC, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    if is_429:
        return min(60.0, 8.0 * (2 ** (attempt - 1))) + random.uniform(0.5, 2.0)

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

    Ofset `/open/v1/common/time` ile ölçülüp `timestamp`'a uygulanır. #35'in asıl
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
        payload = _http_get_json(f"{REST_BASE}/open/v1/common/time")
        data = _unwrap(payload)
        server_ms = int((data or {}).get("serverTime") or (data or {}).get("timestamp") or 0) if isinstance(data, dict) else 0
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
                    idempotent: bool = True,
                    idempotency_key: str | None = None) -> dict | list:
    """HMAC-SHA256 imzalı Binance TR isteği.

    Parametreler (recvWindow+timestamp+signature dahil) query string'te
    taşınır; POST için gövde boştur — dokümana göre toplam imza alanı
    "query string + body" olduğundan bu kombinasyon geçerlidir.

    B-14: `timestamp` sunucu saati ofsetiyle düzeltilir ve 429/5xx (ve ban
    sinyali 418) için sınırlı yeniden deneme yapılır; her denemede yeni
    timestamp + imza üretilir (eskiden hiç yeniden deneme yoktu).

    Emir POST'larında timeout, 5xx veya bozuk cevap sonucu belirsizse aynı
    istek tekrar gönderilmez. Binance TR clientId benzersizlik garantisi vermez.
    """
    base_params = dict(params or {})
    base_params["recvWindow"] = RECV_WINDOW_MS
    offset_ms = _server_time_offset_ms()
    headers = {"X-MBX-APIKEY": api_key}
    last_error: Exception | None = None
    is_post = method.upper() == "POST"
    # Geriye dönük parametre kabul edilir ama emir tekrarını açmaz.
    can_retry_post = False
    # #33: imzalı uçlara ortak eşzamanlılık sınırı. Sembol taraması gibi
    # yüzlerce çağrılık patlamalar bakiye/emir uçlarını tek anda doyuruyordu.
    with _semaphore_for(method, path):
        for attempt in range(1, REST_MAX_ATTEMPTS + 1):
            if attempt == 1:
                _throttle_private_request()
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
                    # Belirsiz emir POST sonucu hiçbir clientId ile tekrar edilmez.
                    if not idempotent and not can_retry_post:
                        if is_post and path in ("/open/v1/orders", "/open/v1/orders/oco"):
                            raise BinanceTrAmbiguousOrderError(
                                f"Emir sonucu belirsiz (Binance TR {exc.code}); tekrar gönderilmedi",
                                client_order_id=str(base_params.get("clientId") or ""),
                                symbol=str(base_params.get("symbol") or "")) from exc
                        raise exc
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    is_429 = ("1003" in str(exc.code)) or ("too many requests" in str(exc.msg).lower())
                    delay = _private_retry_delay(attempt, is_429=is_429)
                    if is_429:
                        _update_cooldown(delay)
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
                # Başlıklardaki ağırlık bilgisini her durumda güncelle
                _record_used_weight(exc.headers)
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
                    delay = _private_ban_delay(attempt, exc.headers)
                    _update_cooldown(delay)
                    time.sleep(delay)
                    continue
                if exc.code == 429 or (500 <= exc.code < 600) or binance_err.is_transient:
                    # 429 reddedilen istek olduğundan güvenle denenebilir.
                    # 5xx order POST sonucu belirsizdir ve yukarıda kesilir.
                    if exc.code != 429 and not idempotent and not can_retry_post:
                        if is_post and path in ("/open/v1/orders", "/open/v1/orders/oco") and exc.code >= 500:
                            raise BinanceTrAmbiguousOrderError(
                                f"Emir sonucu belirsiz (HTTP {exc.code}); tekrar gönderilmedi",
                                client_order_id=str(base_params.get("clientId") or ""),
                                symbol=str(base_params.get("symbol") or "")) from exc
                        raise binance_err
                    if attempt == REST_MAX_ATTEMPTS:
                        break
                    is_429 = (exc.code == 429) or ("429" in str(binance_err.code)) or ("too many requests" in str(binance_err.msg).lower())
                    delay = _private_retry_delay(attempt, exc.headers, is_429=is_429)
                    if is_429:
                        _update_cooldown(delay)
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
                    if is_post and path in ("/open/v1/orders", "/open/v1/orders/oco"):
                        raise BinanceTrAmbiguousOrderError(
                            f"Emir sonucu belirsiz; tekrar gönderilmedi: {exc}",
                            client_order_id=str(base_params.get("clientId") or ""),
                            symbol=str(base_params.get("symbol") or "")) from exc
                    raise RuntimeError(
                        f"Binance TR {method.upper()} {path} cevap vermedi; tekrar gönderilmedi: {exc}"
                    ) from exc
                if attempt == REST_MAX_ATTEMPTS:
                    break
                time.sleep(_private_retry_delay(attempt))
    raise RuntimeError(
        f"Binance TR imzalı istek {REST_MAX_ATTEMPTS} denemede başarısız: {last_error}"
    ) from last_error


def new_client_order_id(prefix: str = "sc") -> str:
    """Durum sorgusunda kullanılacak clientId üretir.

    Binance TR clientId alanı en fazla 36 karakterdir. ID mutabakat içindir;
    benzersizlik veya emir POST tekrar güvenliği sağlamaz.
    """
    return f"{prefix}{uuid.uuid4().hex}"[:36]


def sanitize_client_order_id(value) -> str | None:
    """İstemciden gelen clientId'yi Binance TR alan kurallarına indirger.

    2026-10-17: Binance TR `clientId` TİRE/ALT ÇİZGİ KABUL ETMİYOR — basit
    arayüzün `web-…` kimliği canlıda "3703: Invalid client ID" ile reddedildi;
    başarılı tüm emirler `sa…`/`bu…` + hex (yalnız harf/rakam, ≤36) biçimindeydi.
    Bu yüzden yalnız ASCII harf/rakam kalır, en fazla 36 karakter. Boş veya
    geçersiz değer `None` döner (sunucu kendi kimliğini üretir). Mutabakat
    (`order_requests`, order-status) aynı temizlenmiş kimliği kullanmalıdır.
    """
    raw = "".join(ch for ch in str(value or "").strip() if ch.isascii() and ch.isalnum())[:36]
    return raw or None


def _recent_order_key(api_key: str, client_order_id: str) -> str:
    return f"{hashlib.sha256(str(api_key or '').encode('utf-8')).hexdigest()[:16]}:{client_order_id}"


def _recent_order_lookup(api_key: str, client_order_id: str) -> dict | None:
    """Aynı istemci kimliğiyle son 10 dakikada verilmiş emrin yanıtını döndürür."""
    now = time.time()
    key = _recent_order_key(api_key, client_order_id)
    with _recent_client_orders_lock:
        expired = [k for k, (at, _) in _recent_client_orders.items()
                   if now - at > _RECENT_CLIENT_ORDERS_TTL_SEC]
        for k in expired:
            _recent_client_orders.pop(k, None)
        hit = _recent_client_orders.get(key)
    return dict(hit[1]) if hit else None


def _recent_order_remember(api_key: str, client_order_id: str, result: dict) -> None:
    with _recent_client_orders_lock:
        _recent_client_orders[_recent_order_key(api_key, client_order_id)] = (time.time(), dict(result))


def _qty_to_float(value) -> float:
    """`origQty`/`executedQty` gibi miktar alanlarını güvenle float'a çevir."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def reconcile_sell_fill(result: dict, symbol_underscore: str, requested_qty: float,
                        last_price: float | None = None, step_size: float | None = None,
                        client_order_id: str | None = None,
                        api_key: str = "", api_secret: str = "") -> dict:
    """Kısmi dolan bir satış emrinin kalanını mutabık kılar (#36/P1-8).

    Kalan miktar toz eşiğinin (min_notional) ALTINDA ise tekrar satılamaz;
    bu durum sonuçta `dust_remaining: True` olarak işaretlenir. Toz eşiği
    bilinmiyorsa (fiyat yoksa) güvenli tarafta kalınır ve kalan satılmaya
    çalışılır. Kalan emir, `remaining_qty` ile yeni bir MARKET SELL gönderir;
    bu yol `idempotent=False` olduğundan yalnızca gerçek bir dolum sonrası
    çağrılır (kısmi dolumun kendisi yeniden gönderilmez).
    """
    out = {
        "order_id": str(result.get("order_id") or ""),
        "symbol": symbol_underscore,
        "requested_qty": requested_qty,
        "executed_qty": float(result.get("executed_qty") or 0.0),
        "quantity": result.get("quantity") or f"{requested_qty:.8f}".rstrip("0").rstrip("."),
        "remaining_qty": float(result.get("remaining_qty") or 0.0),
        "partial": True,
        "dust_remaining": False,
        "client_order_id": client_order_id,
    }
    if result.get("avg_price") is not None:
        out["avg_price"] = result["avg_price"]
    if result.get("cummulative_quote_qty") is not None:
        out["cummulative_quote_qty"] = result["cummulative_quote_qty"]

    remaining = float(out["remaining_qty"] or 0.0)
    if step_size and step_size > 0:
        remaining = math.floor(remaining / float(step_size)) * float(step_size)
        remaining = round(remaining, 12)
    out["remaining_qty"] = remaining
    if remaining <= 0:
        return out

    min_notional = None
    with _symbols_lock:
        entry = _symbols_cache["filters"].get(symbol_underscore) or {}
        if not step_size:
            step_size = float(entry.get("step_size") or 0) or None
        min_notional = float(entry.get("min_notional") or 0) or None
    if step_size and step_size > 0:
        remaining = math.floor(remaining / float(step_size)) * float(step_size)
        remaining = round(remaining, 12)

    # Toz koruması: kalan miktar tekrar satılamayacak kadar küçükse yeni emir
    # göndermeyiz — yoksa borsa 400/minNotional hatası verir ve kısmi sonuç
    # kaybolur. Çağıran `dust_remaining=True` görür.
    if min_notional and min_notional > 0 and last_price and last_price > 0:
        if remaining * float(last_price) < float(min_notional):
            out["dust_remaining"] = True
            out["remaining_qty"] = remaining
            logger.warning(
                "Binance TR satış kısmi doldu ve kalan miktar toz eşiğinin altında: "
                "%s kalan=%s (tahmini %s < min %s) — yeni emir gönderilmedi",
                symbol_underscore, remaining, remaining * float(last_price), min_notional
            )
            return out

    try:
        retry = place_market_sell(
            api_key, api_secret, symbol_underscore, remaining, step_size=step_size,
            min_notional=min_notional, last_price=last_price,
            client_order_id=new_client_order_id("sa"))
        out["retry_order_id"] = retry.get("order_id")
        out["retried_qty"] = retry.get("quantity")
    except Exception as exc:
        # Kalan miktar satılamadı; çağıran bunu görüp pozisyonu mutabık kılmalı.
        out["retry_error"] = str(exc)
        logger.error("Binance TR kısmi satış kalanı satılamadı (%s, kalan=%s): %s",
                     symbol_underscore, remaining, exc)
    return out


def _resolve_live_price(symbol_underscore: str) -> float | None:
    """Sembol için canlı TR fiyatı (yoksa None) — min_notional toz kapısı için.

    Satış yolu fiyatı hiç geçmiyordu (#34/P1-8): bu yüzden toz koruması hep
    atlanıyor ve dust bakiyeler kalıcı olarak takılı kalıyordu. Fiyat ÖNCE
    bellekteki ticker'lardan okunur (ağ çağrısı yok, satış yolunu yeni bir ağ
    bağımlılığına sokmamak için); orada yoksa public REST ile hidratlanır.
    """
    symbol = str(symbol_underscore or "").upper()
    if not symbol:
        return None
    try:
        from app.state import market  # döngüsel importu önlemek için tembel
        ticker = market.get_ticker(symbol)
        if ticker and ticker.get("last_price"):
            price = float(ticker["last_price"])
            if price > 0:
                return price
    except Exception:
        pass
    try:
        from app.binance_tr_public import ticker_price  # tembel import
        rows = ticker_price([symbol])
        if isinstance(rows, list):
            for row in rows:
                if str(row.get("symbol") or "").upper() == symbol:
                    price = float(row.get("price") or 0)
                    if price > 0:
                        return price
    except Exception as exc:
        logger.debug("Binance TR canlı fiyat hidrasyonu başarısız (%s): %s", symbol, exc)
    return None


def _order_fill(data: dict, requested_qty: float | None) -> tuple[float, float | None, float | None, float | None]:
    """Emir cevabından (executed, remaining, avg_price, quote) türet.

    `executedQty` 0/eksikse (bazı proxy'ler yalnız orderId döner) istenen
    miktar dolu kabul edilir — aksi hâlde yanlışlıkla "kısmi dolum" sanılır.
    """
    if not isinstance(data, dict):
        return (float(requested_qty or 0.0), None, None, None)
    executed = _qty_to_float(data.get("executedQty"))
    quote = _qty_to_float(data.get("cummulativeQuoteQty") or data.get("cumulativeQuoteQty"))
    avg = None
    if executed > 0 and quote > 0:
        avg = quote / executed
    remaining = None
    if requested_qty is not None and executed > 0:
        remaining = max(0.0, float(requested_qty) - executed)
    if executed <= 0:
        # Dolum bilgisi yok → tam dolum varsay (eski davranış).
        return (float(requested_qty or 0.0), None, avg, quote or None)
    return (executed, remaining, avg, quote or None)


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
                "status": str(r.get("status") or "TRADING").upper(),
            }
            for f in r.get("filters", []) or []:
                ft = f.get("filterType")
                if ft == "LOT_SIZE":
                    entry["step_size"] = float(f.get("stepSize") or 0)
                    entry["min_qty"] = float(f.get("minQty") or 0)
                elif ft == "MARKET_LOT_SIZE":
                    entry["market_step_size"] = float(f.get("stepSize") or 0)
                    entry["market_min_qty"] = float(f.get("minQty") or 0)
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
    """Sembol filtreleri (LOT_SIZE/NOTIONAL, quoteAsset) — 6 saat cache'li liste."""
    _load_symbol_list(api_key, api_secret)
    with _symbols_lock:
        return _symbols_cache["filters"].get(symbol_underscore)


def get_all_valid_symbols(api_key: str = "", api_secret: str = "") -> set[str]:
    """Geçerli tüm alt çizgili sembollerin kümesini döndürür (cache'li)."""
    _load_symbol_list(api_key, api_secret)
    with _symbols_lock:
        return set(_symbols_cache.get("filters", {}).keys())


_ORDER_TYPE_CODES = {"LIMIT": 1, "MARKET": 2, "STOP_LOSS_LIMIT": 4}


def place_spot_order(api_key: str, api_secret: str, symbol: str, side: str, order_type: str,
                     *, quantity: float | None = None, quote_order_qty: float | None = None,
                     price: float | None = None, stop_price: float | None = None,
                     stop_limit_price: float | None = None, client_order_id: str | None = None) -> dict:
    """Doğrulamalı gerçek spot LIMIT/MARKET/STOP_LOSS_LIMIT emri gönderir.

    Belirsiz POST sonucu `BinanceTrAmbiguousOrderError` olarak yükseltilir;
    istemci aynı emri tekrar göndermemeli, clientId ile durumu sorgulamalıdır.

    `client_order_id` verilirse (UI onay penceresinde üretilir) ve aynı
    kimlikle son 10 dakikada bir emir zaten borsaya iletilmişse, emir TEKRAR
    gönderilmez; önceki yanıt `idempotent_replay=True` ile döner.
    """
    client_order_id = sanitize_client_order_id(client_order_id)
    if client_order_id:
        cached = _recent_order_lookup(api_key, client_order_id)
        if cached is not None:
            logger.warning("Binance TR emir tekrarı engellendi: clientId=%s zaten gönderilmiş", client_order_id)
            return {**cached, "idempotent_replay": True}
    symbol_u = _to_underscore_symbol(symbol)
    side_u, kind = str(side or "").upper(), str(order_type or "").upper()
    if side_u not in ("BUY", "SELL"):
        raise ValueError("side BUY veya SELL olmalı")
    if kind not in _ORDER_TYPE_CODES:
        raise ValueError("type LIMIT, MARKET veya STOP_LOSS_LIMIT olmalı")
    filters = get_symbol_filters(api_key, api_secret, symbol_u)
    if not filters or filters.get("status") != "TRADING":
        raise ValueError("Sembol bulunamadı veya işlemlere kapalı")
    declared = {str(x).upper() for x in (filters.get("order_types") or [])}
    declared_names = {"1": "LIMIT", "2": "MARKET", "4": "STOP_LOSS_LIMIT"}
    declared = {declared_names.get(x, x) for x in declared}
    if declared and kind not in declared:
        raise ValueError(f"{symbol_u} için {kind} emri Binance TR tarafından desteklenmiyor")

    step = float(filters.get("step_size") or 0) or None
    market_step = float(filters.get("market_step_size") or 0) or step
    tick = float(filters.get("tick_size") or 0) or None
    min_qty = float(filters.get("min_qty") or 0)
    min_notional = float(filters.get("min_notional") or 0)
    params: dict = {"symbol": symbol_u, "side": 0 if side_u == "BUY" else 1,
                    "type": _ORDER_TYPE_CODES[kind],
                    "clientId": (client_order_id or new_client_order_id("ui"))[:36]}

    def positive(v, label):
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{label} pozitif sayı olmalı")
        if not math.isfinite(n) or n <= 0:
            raise ValueError(f"{label} pozitif sayı olmalı")
        return n

    if kind == "MARKET" and side_u == "BUY" and quote_order_qty is not None:
        if quantity is not None:
            raise ValueError("MARKET BUY için quantity veya quote_order_qty alanlarından yalnız biri gönderilmeli")
        params["quoteOrderQty"] = _fmt_quantity(positive(quote_order_qty, "quote_order_qty"))
    else:
        if quantity is None or quote_order_qty is not None:
            raise ValueError("Bu emir için quantity zorunlu; quote_order_qty kullanılamaz")
        qty_step = market_step if kind == "MARKET" else step
        qty_min = float(filters.get("market_min_qty") or min_qty) if kind == "MARKET" else min_qty
        qty_s = _fmt_quantity(positive(quantity, "quantity"), qty_step)
        qty_n = float(qty_s or 0)
        if qty_n <= 0 or (qty_min and qty_n < qty_min):
            raise ValueError(f"Miktar minimum lotun altında (min {qty_min})")
        params["quantity"] = qty_s

    if kind == "LIMIT":
        if price is None or stop_price is not None or stop_limit_price is not None:
            raise ValueError("LIMIT için price zorunlu; stop alanları kullanılmaz")
        params.update({"price": _fmt_price(positive(price, "price"), tick), "timeInForce": 1})
    elif kind == "STOP_LOSS_LIMIT":
        if quantity is None or price is not None or stop_price is None or stop_limit_price is None:
            raise ValueError("STOP_LOSS_LIMIT için quantity, stop_price ve stop_limit_price zorunlu")
        params.update({"price": _fmt_price(positive(stop_limit_price, "stop_limit_price"), tick),
                       "stopPrice": _fmt_price(positive(stop_price, "stop_price"), tick),
                       "timeInForce": 1})
    elif price is not None or stop_price is not None or stop_limit_price is not None:
        raise ValueError("MARKET emrinde fiyat ve stop alanları kullanılamaz")

    # Miktar emirlerinde bilinen minNotional kontrolü; MARKET BUY quote tutarında doğrudan.
    if min_notional and "quantity" in params:
        px = float(params.get("price") or params.get("stopPrice") or 0)
        if not px:
            px = _resolve_live_price(symbol_u) or 0
        if px and float(params["quantity"]) * px < min_notional:
            raise ValueError(f"Emir tutarı minimum tutarın altında (min {min_notional})")
    if min_notional and "quoteOrderQty" in params and float(params["quoteOrderQty"]) < min_notional:
        raise ValueError(f"Emir tutarı minimum tutarın altında (min {min_notional})")

    try:
        data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                               idempotent=False)
    except BinanceTrAmbiguousOrderError:
        raise
    except RuntimeError as exc:
        # _signed_request eski genel hata metnini de belirsiz sonuç sayar.
        if "belirsiz" in str(exc).lower() or "cevap vermedi" in str(exc).lower():
            raise BinanceTrAmbiguousOrderError(str(exc), client_order_id=params["clientId"],
                                               symbol=symbol_u) from exc
        raise
    _invalidate_open_orders(api_key)
    invalidate_account_balance_cache(api_key)
    result = {**(data if isinstance(data, dict) else {}), "symbol": symbol_u,
              "client_id": params["clientId"], "order_id": str(data.get("orderId")) if isinstance(data, dict) and data.get("orderId") else None}
    if client_order_id:
        _recent_order_remember(api_key, client_order_id, result)
    return result


def get_order_detail(api_key: str, api_secret: str, symbol: str, *,
                     order_id: int | str | None = None, client_id: str | None = None) -> dict:
    """GET /open/v1/orders/detail; orderId veya clientId ile emir mutabakatı."""
    params: dict = {"symbol": _to_underscore_symbol(symbol)}
    if order_id not in (None, ""):
        params["orderId"] = str(order_id)
    elif client_id:
        # 2026-10-17: emir POST'unda temizlenen kimlikle aynı biçim (tire yok).
        params["clientId"] = sanitize_client_order_id(client_id) or str(client_id)
    else:
        raise ValueError("order_id veya client_id gerekli")
    data = _signed_request("GET", "/open/v1/orders/detail", params, api_key, api_secret)
    return data if isinstance(data, dict) else {}


def place_market_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                      step_size: float | None = None, client_order_id: str | None = None,
                      min_notional: float | None = None,
                      last_price: float | None = None) -> dict:
    """MARKET SELL emri gönderir (POST /open/v1/orders; side=1, type=2).

    Kullanıcı onayı UI katmanında alınır; bu fonksiyon doğrudan emir gönderir.
    Cevap: {"order_id": ..., "symbol": ..., "quantity": ...}.

    `clientId` yalnız durum sorgusu içindir; Binance TR emir POST tekrarını
    clientId ile tekilleştirmez.
    `idempotent=False` ile çağrılır → timeout/5xx/bozuk JSON'da emir ASLA
    tekrar atılmaz.

    #34: `min_notional` verilirse borsadaki NOTIONAL filtresi istemci tarafında
    da uygulanır. Kalan toz bakiyenin (ör. 5 TRY'lik BTC kesirinin tamamı)
    filtreye takılıp 502 üretmesi ve varlıkta kalıcı toz bırakması yerine
    çağıran açık bir hata alır. `last_price` ile kaba tahmin yapılır
    (bakiye endpoint'i fiyat döndürmez); emin değilsek borsa karar verir.

    #36/P1-8: (a) kısmi dolum doğrulanmadan "tam sattım" deniyordu — artık
    `executedQty` kontrol edilir; eksik dolum `BinanceTrPartialFillError` ile
    yükseltilir, çağıran `reconcile_sell_fill` ile kalanı mutabık kılar.
    (b) min_notional kapısı ÖLÜYDÜ çünkü `last_price` hiç geçilmiyordu
    (çağıran main.py satış yolu); artık verilmezse canlı ticker'dan türetilir.
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
        # Emir durumu mutabakatında kullanılır; dedupe anahtarı değildir.
        "clientId": sanitize_client_order_id(client_order_id) or new_client_order_id("sa"),
    }
    # #36/P1-8: fiyat geçilmediyse toz kapısı için canlı fiyatı TÜRET. Eskiden
    # çağıran last_price'ı hiç vermediği için bu kapı hiç ateşlenmiyor ve dust
    # bakiyeler kalıcı takılı kalıyordu.
    if min_notional and min_notional > 0 and (not last_price or last_price <= 0):
        last_price = _resolve_live_price(symbol_underscore)
    # #34: minimum işlem tutarı istemci tarafında da uygulanır. Fiyat hâlâ
    # bilinmiyorsa tahmin yapılmaz — borsanın kendi filtresi son sözü söyler.
    if min_notional and min_notional > 0 and last_price and last_price > 0:
        if (params["quantity"] and float(params["quantity"]) * float(last_price)) < min_notional:
            raise ValueError(
                f"Satış tutarı minimum emrin altında "
                f"(min {min_notional}, tahmini {float(params['quantity']) * float(last_price):.2f})"
            )
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                           idempotent=False)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    requested = float(params["quantity"])
    executed_qty, remaining_qty, avg_price, quote_qty = _order_fill(data, requested)
    logger.info("Binance TR MARKET SELL gönderildi: %s qty=%s executed=%s orderId=%s clientId=%s",
                symbol_underscore, params["quantity"], executed_qty, order_id,
                params["clientId"])
    invalidate_account_balance_cache(api_key)
    _invalidate_open_orders(api_key)
    result = {"order_id": str(order_id) if order_id is not None else None,
              "symbol": symbol_underscore, "quantity": params["quantity"],
              "client_order_id": params["clientId"],
              "requested_qty": requested, "executed_qty": executed_qty}
    if avg_price is not None:
        result["avg_price"] = avg_price
    if quote_qty is not None:
        result["cummulative_quote_qty"] = quote_qty
    # #36/P1-8: satış yolu kısmi dolumu sessizce tam sanıyordu → pozisyonun
    # bir kısmı açık kalırken "satıldı" deniyordu. Burada açıkça yükseltilir;
    # çağıran `BinanceTrPartialFillError.result`/`remaining_qty` ile mutabakat
    # yapmalıdır (bkz. `reconcile_sell_fill`).
    if remaining_qty is not None and remaining_qty > 0:
        result["remaining_qty"] = remaining_qty
        result["partial"] = True
        raise BinanceTrPartialFillError(
            f"MARKET SELL kısmi doldu: istenen {params['quantity']}, "
            f"gerçekleşen {executed_qty}, kalan {remaining_qty} ({symbol_underscore}).",
            requested_qty=requested, executed_qty=executed_qty,
            remaining_qty=remaining_qty, result=result,
        )
    result["remaining_qty"] = 0.0
    result["partial"] = False
    return result


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

    `client_order_id` durum sorgusu içindir; idempotency garantisi vermez.
    """
    if min_notional is not None and min_notional > 0 and quote_qty < min_notional:
        raise ValueError(f"Tutar minimum emrin altında (min {min_notional})")
    params = {
        "symbol": symbol_underscore,
        "side": 0,           # doküman: 0=BUY, 1=SELL
        "type": 2,           # doküman: 2=MARKET
        "quoteOrderQty": f"{float(quote_qty):.2f}",  # quote asset (TRY) büyüklüğü
        # Emir durumu mutabakatında kullanılır; dedupe anahtarı değildir.
        "clientId": sanitize_client_order_id(client_order_id) or new_client_order_id("bu"),
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                           idempotent=False)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR MARKET BUY gönderildi: %s quote=%s orderId=%s clientId=%s",
                symbol_underscore, params["quoteOrderQty"], order_id, params["clientId"])
    invalidate_account_balance_cache(api_key)
    _invalidate_open_orders(api_key)
    out = {"order_id": str(order_id) if order_id is not None else None,
           "symbol": symbol_underscore, "quote_qty": params["quoteOrderQty"],
           "client_order_id": params["clientId"]}
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

    `client_order_id` durum sorgusu içindir; idempotency garantisi vermez.
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
        # Emir durumu mutabakatında kullanılır; dedupe anahtarı değildir.
        "clientId": sanitize_client_order_id(client_order_id) or new_client_order_id("oc"),
    }
    data = _signed_request("POST", "/open/v1/orders/oco", params, api_key, api_secret,
                           idempotent=False)
    order_list_id = data.get("orderListId") if isinstance(data, dict) else None
    orders = data.get("orders") if isinstance(data, dict) else []
    logger.info("Binance TR OCO SELL gönderildi: %s qty=%s tp=%s sl=%s orderListId=%s",
                symbol_underscore, qty_str, price_str, stop_price_str, order_list_id)
    invalidate_account_balance_cache(api_key)
    _invalidate_open_orders(api_key)
    return {
        "order_list_id": str(order_list_id) if order_list_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "tp_price": price_str,
        "sl_price": stop_price_str,
        "sl_limit_price": stop_limit_price_str,
        "orders": orders,
        "client_order_id": params["clientId"],
    }


def place_stop_loss_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                         stop_price: float, stop_limit_price: float | None = None,
                         step_size: float | None = None, tick_size: float | None = None,
                         client_order_id: str | None = None) -> dict:
    """Tekil STOP_LOSS_LIMIT SELL emri gönderir (POST /open/v1/orders).

    clientId durum sorgusu içindir; Binance TR dedupe garantisi sunmaz.
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
        # Emir durumu mutabakatında kullanılır; dedupe anahtarı değildir.
        "clientId": sanitize_client_order_id(client_order_id) or new_client_order_id("sl"),
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                           idempotent=False)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR STOP_LOSS_LIMIT SELL gönderildi: %s qty=%s sl=%s orderId=%s",
                symbol_underscore, qty_str, stop_price_str, order_id)
    invalidate_account_balance_cache(api_key)
    _invalidate_open_orders(api_key)
    return {
        "order_id": str(order_id) if order_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "sl_price": stop_price_str,
        "sl_limit_price": stop_limit_price_str,
        "client_order_id": params["clientId"],
    }


def place_limit_sell(api_key: str, api_secret: str, symbol_underscore: str, quantity: float,
                     price: float, step_size: float | None = None, tick_size: float | None = None,
                     client_order_id: str | None = None) -> dict:
    """Tekil LIMIT (Take-Profit) SELL emri gönderir (POST /open/v1/orders).

    `client_order_id` durum sorgusu içindir; idempotency garantisi vermez.
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
        # Emir durumu mutabakatında kullanılır; dedupe anahtarı değildir.
        "clientId": sanitize_client_order_id(client_order_id) or new_client_order_id("tp"),
    }
    data = _signed_request("POST", "/open/v1/orders", params, api_key, api_secret,
                           idempotent=False)
    order_id = data.get("orderId") if isinstance(data, dict) else None
    logger.info("Binance TR LIMIT SELL gönderildi: %s qty=%s price=%s orderId=%s",
                symbol_underscore, qty_str, price_str, order_id)
    invalidate_account_balance_cache(api_key)
    _invalidate_open_orders(api_key)
    return {
        "order_id": str(order_id) if order_id is not None else None,
        "symbol": symbol_underscore,
        "quantity": qty_str,
        "price": price_str,
        "client_order_id": params["clientId"],
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
    _invalidate_open_orders(api_key)
    invalidate_account_balance_cache(api_key)
    logger.info("Binance TR emir iptal edildi: orderId=%s symbol=%s", order_id, symbol_underscore)
    return data if isinstance(data, dict) else {"order_id": str(order_id), "status": "CANCELED"}



def get_account_balance(api_key: str, api_secret: str, force_refresh: bool = False) -> list[dict]:
    """GET /open/v1/account/spot → data.accountAssets [{asset, free, locked}].

    Kısa süreli (15 sn, WS push kadansı) bellek önbelleği uygulanır: /account, /positions, /trades-day
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
    cache = _open_orders_cache_for(api_key)
    with _open_orders_lock:
        if not symbol and now < cache["expires"]:
            return list(cache["orders"])

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
                "clientOrderId": str(o.get("clientId") or o.get("clientOrderId") or ""),
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
            if now < cache["expires"]:
                return list(cache["orders"])

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
                cache.update({"orders": [], "partial": False,
                                           "expires": time.monotonic() + _OPEN_ORDERS_CACHE_TTL_SEC})
            return []

        # 2) Sembolsüz istek borsa tarafından kabul edilirse tek istekte tamamla
        try:
            rows = _signed_request("GET", "/open/v1/orders", {"type": 1, "limit": 100},
                                   api_key, api_secret)
            orders = _normalize(rows.get("list", []) if isinstance(rows, dict) else [])
            with _open_orders_lock:
                cache.update({"orders": orders, "partial": False,
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
            cache.update({"orders": orders, "partial": partial,
                                       "expires": time.monotonic() + _OPEN_ORDERS_CACHE_TTL_SEC})
        return orders


def get_open_orders_partial(api_key: str, api_secret: str) -> bool:
    """Son açık-emir sonucunun kısmi olup olmadığını döner (#33).

    Tarama sınırına takıldığında veya bir sembol sorgulanamadığında `True`.
    Çağıran (UI/API) bunu kullanıcıya "liste eksik olabilir" diye bildirmeli.
    """
    cache = _open_orders_cache_for(api_key)
    with _open_orders_lock:
        return bool(cache.get("partial"))


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
        raw_buyer = t.get("isBuyer")
        is_buyer = (
            raw_buyer is True
            or raw_buyer == 1
            or (isinstance(raw_buyer, str) and raw_buyer.strip().lower() in ("1", "true", "buy"))
        )
        raw_maker = t.get("isMaker")
        is_maker = (
            raw_maker is True
            or raw_maker == 1
            or (isinstance(raw_maker, str) and raw_maker.strip().lower() in ("1", "true"))
        )
        out.append({
            "id": int(t.get("tradeId") or 0),
            "orderId": str(t.get("orderId") or ""),
            "symbol": t.get("symbol", "").replace("_", ""),
            "price": t.get("price", "0"),
            "qty": t.get("qty", "0"),
            "quoteQty": t.get("quoteQty", "0"),
            "commission": t.get("commission", "0"),
            "commissionAsset": t.get("commissionAsset", ""),
            "isBuyer": is_buyer,
            "isMaker": is_maker,
            "time": int(t.get("time") or 0),
        })
    return out


def get_common_symbols(api_key: str = "", api_secret: str = "") -> dict:
    """GET /open/v1/common/symbols — sembol filtreleri, lot büyüklükleri vb. (public)."""
    payload = _http_get_json(f"{REST_BASE}/open/v1/common/symbols")
    return _unwrap(payload) if isinstance(payload, dict) else payload


# ---------------------------------------------------------------------------
# Komisyon modu (BNB ile komisyon indirimi) — salt okunur
# ---------------------------------------------------------------------------
# ARAŞTIRMA (2026-10-16, binance.tr/apidocs): Binance TR open/v1 API'sinde
# BNB-burn okuma/yazma ucu YOKTUR (global /sapi/v1/bnbBurn'ün TR karşılığı
# yok). Hesap komisyonu yalnız GET /open/v1/account/spot cevabındaki
# makerCommission / takerCommission / fiatMakerCommission / fiatTakerCommission
# alanlarından okunabilir; BNB bakiyesi accountAssets içinden gelir.
# Bu yüzden `spot_bnb_burn` her zaman None (bilinmiyor) döner ve mod
# değiştirilemez.
FEE_MODE_SOURCE = "/open/v1/account/spot"
BNB_BURN_UNSUPPORTED_MSG = (
    "Binance TR API'de BNB komisyon modu değiştirme ucu yok; "
    "Binance TR web ayarlarından değiştirin"
)


def _commission_to_fraction(value) -> float | None:
    """Komisyon alanını orana (0.001 = %0,1) çevirir.

    Doküman birim belirtmiyor: global API gibi baz puan tam sayısı (ör. 10 →
    %0,1) veya zaten ondalık oran (0.001) gelebilir. 1 ve üzeri değerler baz
    puan sayılır; 0 ≤ değer < 1 oran kabul edilir. Geçersiz/negatif → None.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return v / 10000.0 if v >= 1 else v


def get_fee_mode(api_key: str, api_secret: str) -> dict:
    """Hesabın komisyon bilgisi + BNB bakiyesi (GET /open/v1/account/spot).

    Döner: {bnb_burn_supported, spot_bnb_burn, maker_commission,
    taker_commission, fiat_maker_commission, fiat_taker_commission,
    bnb_balance, source}. Komisyonlar ORAN olarak (0.001 = %0,1).
    """
    data = _signed_request("GET", FEE_MODE_SOURCE, None, api_key, api_secret)
    if not isinstance(data, dict):
        data = {}
    bnb_balance: float | None = 0.0
    assets = data.get("accountAssets")
    if isinstance(assets, list):
        total = 0.0
        for a in assets:
            if isinstance(a, dict) and str(a.get("asset") or "").upper() == "BNB":
                total += _qty_to_float(a.get("free")) + _qty_to_float(a.get("locked"))
        bnb_balance = total
    else:
        bnb_balance = None
    return {
        "bnb_burn_supported": False,
        "spot_bnb_burn": None,
        "maker_commission": _commission_to_fraction(data.get("makerCommission")),
        "taker_commission": _commission_to_fraction(data.get("takerCommission")),
        "fiat_maker_commission": _commission_to_fraction(data.get("fiatMakerCommission")),
        "fiat_taker_commission": _commission_to_fraction(data.get("fiatTakerCommission")),
        "bnb_balance": bnb_balance,
        "source": FEE_MODE_SOURCE,
    }


def set_fee_mode(api_key: str, api_secret: str, spot_bnb_burn: bool) -> dict:
    """BNB ile komisyon modunu değiştirir — Binance TR'de böyle bir uç yok."""
    raise NotImplementedError(BNB_BURN_UNSUPPORTED_MSG)
