"""Shared API runtime helpers used by main.py and every router module."""
import asyncio
import logging
import math
import time

from app.config import config
from app import database
from app.correlation import cluster_exposure
from app.binance_tr_public import orderbook, ticker_price
from app.binance_tr_public import klines as fetch_klines
from app.state import market, analyzer

logger = logging.getLogger("scalper.api_common")

# Radar paylaşılan durumu: /api/radar/gainers (main.py) ve radar döngüsü
# (routers/runtime.py) aynı nesneyi okur/yazar. Rebind yerine mutasyon
# (clear/update) kullanılır; aksi halde iki modül ayrı kopyalarda çalışır.
_radar_snapshot = {"generated_at": 0.0, "items": {}}
_radar_response_cache = {"generated_at": 0.0, "result": None}

# deque maxlen ile bounded ama async-safe değil — concurrent await noktalarında
# tutarsız davranabilir. logging modülü thread-safe olduğu için print logları
# yerine structured logging kullanılmalıdır.

_background_tasks = set()
# Her background görev için kalıcı restart sayacı — _respawn içinde tekrar
# _start_background çağrıldığında sıfırlanmaması için modül seviyesinde tutulur.
_restart_counters: dict[str, int] = {}
# Tek seferlik (single-pass) görev isimleri seti: bunlar tamamlandığında
# yeniden başlatılmırlar, sıfırlama görev bitiminde yapılır.
_single_pass_tasks: set[str] = set()

# G-11 (2026-09-12): sonsuz restart yerine sonlu deneme + KALICI "failed" durumu.
# Eskiden deneme sayısı sınırsızdı ve gecikme 30 sn'de sabitleniyordu; kalıcı
# bozuk bir döngü (örn. strategy_loop) 30 sn'de bir crash-loop'a giriyor ve hiç
# alarm üretmiyordu. Artık MAX_BACKGROUND_RESTARTS aşılırsa görev "failed"
# olarak işaretlenir, kritik loglanır ve (best-effort) alarm kaydı yazılır.
MAX_BACKGROUND_RESTARTS = 10
_failed_loops: dict[str, dict] = {}

# M1/P1 (R4-02): süpervizörlü görevlerin İSİM→canlı görev kaydı. `_start_background`
# görevi oluşturduğunda ve respawn ettiğinde bu kayıt güncellenir; böylece çağıranlar
# (örn. monitoring) bayat bir görev referansı yerine HER ZAMAN canlı görevi görür.
_background_registry: dict[str, "asyncio.Task"] = {}

# DENETİM 3.4 #36 (2026-09-26): kapanış sırasında respawn yarışı.
#
# `_restart_if_failed` bir done-callback'tir; `shutdown_services` görevleri
# iptal edip `gather` ile beklerken bu callback `gather` TAMAMLANMADAN
# çalışabilir. O an `_respawn()` 2-30 sn sonra yeni `market.connect()` /
# `strategy_loop` görevleri yaratır; bunlar `_background_tasks` kümesine
# eklendiği için iptal listesinde bulunmaz. Sonuç: `microflow.stop()`,
# `market.stop()` ve `database.close_db()` ÇALIŞMIŞKEN yeni WS açılır ve
# kapalı DB havuzu kullanılır; process'in kapanması gecikir.
#
# Çözüm: kapanış başladığında bu bayrak `True` yapılır; `_restart_if_failed`
# erken çıkar, `_respawn` hiç oluşmaz. `begin_shutdown()` /
# `end_shutdown()` main.py'deki kapanış akışını sarar.
_shutting_down = False


def begin_shutdown() -> None:
    """Kapanış başladı: supervisor YENİ görev üretmesin (denetim 3.4 #36).

    Idempotenttir. Kapanış sırasında `_start_background` hâlâ çağrılabilir
    (örn. kapanışta tetiklenen tek seferlik görevler) — bu görevler normalde
    döngüsel izleme üretmez, bu yüzden burada reddedilmez; yalnızca HATA
    üzerinden yeniden doğma yolu kapatılır.
    """
    global _shutting_down
    _shutting_down = True


def end_shutdown() -> None:
    """Kapanış bitti (ya da hiç başlamadı): supervisor normale döner.

    Test izolasyonu ve embedding-worker yeniden başlatma gibi "kapanış
    sonrası süreç devam ediyor" senaryoları için gereklidir.
    """
    global _shutting_down
    _shutting_down = False


def is_shutting_down() -> bool:
    """Kapanış sırasında mıyız? (tanılayıcı/test yüzeyi)"""
    return _shutting_down


def clear_background_registry() -> None:
    """Kapanış sonunda isim→görev kaydını ve sayaçları temizle.

    Registry `.clear()` olmadan bir sonraki süreç başlangıcında (aynı
    interpreter içinde yeniden başlatmada) bayat görev referansları kalır ve
    `get_task(name)` liveness kontrolü YANLIŞ "canlı" der.
    """
    _background_registry.clear()
    _restart_counters.clear()
    _single_pass_tasks.clear()
    _failed_loops.clear()


def get_task(name: str):
    """İsimle kayıtlı CANLI background görevini döndür (yoksa None).

    Süpervizör respawn ettiğinde kayıt yeni göreve yönlendirilir; bu nedenle
    ``get_task(name)`` üzerinden yapılan liveness kontrolü çöküş-respawn
    sonrasında da doğrudur (R4-02).
    """
    return _background_registry.get(name)


def loop_health() -> dict:
    """Diagnostik: kalıcı olarak başarısız olan döngüler + deneme sayaçları (G-11)."""
    return {"failed": {name: dict(info) for name, info in _failed_loops.items()},
            "restart_counters": dict(_restart_counters),
            "max_restarts": MAX_BACKGROUND_RESTARTS}


def _alert_failed_loop(name: str, exc: BaseException) -> None:
    """Kalıcı olarak düşen döngü için en iyi çaba alarmı (DB/gözetim)."""
    message = (f"Arka plan döngüsü '{name}' {MAX_BACKGROUND_RESTARTS} denemede "
               f"kalıcı olarak başarısız oldu: {type(exc).__name__}: {exc}")

    async def _record():
        try:
            await database.save_signal({
                "symbol": "*", "action": "BACKGROUND_LOOP_FAILED", "reason": message,
                "strategy": "system", "timestamp": time.time()})
        except Exception as record_exc:  # noqa: BLE001 - alarm ana akışı bozmamalı
            logger.warning("failed-loop alarmı kaydedilemedi (%s): %s", name, record_exc)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        task = asyncio.create_task(_record(), name=f"{name}-failed-alert")
    except RuntimeError:
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _handle_task_failure(name: str, exc: BaseException) -> bool:
    """Bir background görev hata ile düştüğünde yeniden başlatma kararını verir.

    Dönüş: ``True`` → yeniden başlatılmalı (deneme sınırı içinde),
    ``False`` → kalıcı "failed" durumuna geçildi (yeniden başlatılmaz, alarm verilir).
    """
    current = _restart_counters.get(name, 0) + 1
    _restart_counters[name] = current
    if current > MAX_BACKGROUND_RESTARTS:
        _failed_loops[name] = {"failed_at": time.time(),
                               "error": f"{type(exc).__name__}: {exc}",
                               "attempts": current - 1}
        logger.critical(
            "background görev '%s' %d denemede kalıcı olarak başarısız; "
            "yeniden başlatılmayacak. Hata: %s", name, MAX_BACKGROUND_RESTARTS, exc,
            exc_info=True)
        _alert_failed_loop(name, exc)
        return False
    _failed_loops.pop(name, None)
    delay = min(2 * current, 30)
    logger.error("background görev '%s' hata ile düştü (%s); deneme %d, %.0fs sonra yeniden deneniyor.",
                 name, exc, current, delay, exc_info=True)
    return True


class _TokenBucket:
    """Basit token-bucket hız sınırlayıcı (G-13/G-18). Tek process, tek event loop."""

    def __init__(self, rate_per_sec: float, burst: float):
        self.rate = float(rate_per_sec)
        self.burst = float(burst)
        self._tokens = float(burst)
        self._at = time.monotonic()

    def allow(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else float(now)
        elapsed = max(0.0, now - self._at)
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._at = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


_rate_limiters: dict[str, "_TokenBucket"] = {}


def rate_limit(name: str, *, rate_per_sec: float, burst: float, now: float | None = None) -> bool:
    """``name`` için token-bucket kontrolü. ``True`` → istek geçebilir.

    Aynı isim aynı kovayı kullanır; kova ilk çağrıda oluşturulup süreç boyunca
    yaşar. Testler ``_rate_limiters`` üzerinden sıfırlayabilir.
    """
    bucket = _rate_limiters.get(name)
    if bucket is None:
        bucket = _rate_limiters[name] = _TokenBucket(rate_per_sec, burst)
    return bucket.allow(now)


def require_admin(request) -> dict:
    """Router'ların kullandığı yönetici kapısı (G-23).

    Kanonik uygulama ``app.security.require_admin``; ``main._require_admin`` da
    ona delege eder. Burada çağrı ANINDA ``app.main._require_admin`` çözülür,
    böylece (a) router modülleri ``from app.main import ...`` YAPMAZ (gizli
    router→main döngüsü kalkar) ve (b) testlerin/operatörün
    ``app.main._require_admin`` üzerinden yaptığı override birebir çalışmaya
    devam eder. Davranış aynı: eksik principal → 401, admin değil → 403.
    """
    from app import main
    return main._require_admin(request)

def _start_background(coro_factory, name, single_pass=False):
    """Başlat ve supervisor, hata ile biterse sınırlı geri alımla yeniden başlat.

    ``coro_factory`` bir coroutine DEĞİL, coroutine üreten sıfır argümanlı bir
    callable olmalıdır (örn. ``strategy_loop`` veya ``lambda: market.connect(...)``).
    Çünkü yeniden başlatma, coroutine'i yeniden üretmeyi gerektirir: tüketilmiş
    bir coroutine nesnesi tekrar await edilemez ve respawn anında
    ``RuntimeError: cannot reuse already awaited coroutine`` ile ölür.

    Uzun ömürlü background döngüleri (strategy, radar, broadcast, ...) iç
    try/except ile kendi hatalarını yutacak şekilde yazılır. Yine de beklenmeyen
    bir istisna düşürülürse görev, CancelledError dışındaki hatalarda sonlu bir
    geri alımla (backoff) yeniden oluşturulur; böylece tek seferlik görevlerin
    doğal tamamlanması yeniden başlatılmaz.

    single_pass=True olan görevler bittiğinde restart sayacı sıfırlanır ve
    yeniden başlatılmaz.
    """
    if not callable(coro_factory):
        raise TypeError(
            f"_start_background('{name}'): coroutine değil, coroutine üreten "
            "callable bekleniyor. Örn: _start_background(strategy_loop, 'strategy-loop')"
        )
    if single_pass:
        _single_pass_tasks.add(name)

    def _restart_if_failed(task):
        _background_tasks.discard(task)
        if task.cancelled():
            return
        # DENETİM 3.4 #36: kapanış sırasında yeniden doğma YASAK. Bu callback
        # `shutdown_services`'in `gather`'ı bitmeden çalışabilir; devam edersek
        # iptal listesinde olmayan yeni görevler (market.connect, strategy_loop)
        # kapanmış WS/DB üzerinde doğar. Önce `discard` edilip burada durulur.
        if _shutting_down:
            return
        exc = task.exception()
        if not exc:
            # Normal tamamlama: tek seferlik görev ise sayacı sıfırla, değilse de sıfırla.
            _restart_counters.pop(name, None)
            return
        # Beklenmeyen hata: sonlu geri alımla yeniden başlat.
        if name in _single_pass_tasks:
            _single_pass_tasks.discard(name)
            _restart_counters.pop(name, None)
            logger.warning("tek seferlik görev '%s' hata ile düştü, yeniden başlatılmıyor: %s", name, exc, exc_info=True)
            return
        # G-11: sonlu deneme + kalıcı "failed" durumu. Sınır aşılırsa
        # yeniden başlatma YOK; görev failed olarak raporlanır ve alarm verilir.
        if not _handle_task_failure(name, exc):
            return
        delay = min(2 * _restart_counters.get(name, 1), 30)
        async def _respawn():
            await asyncio.sleep(delay)
            _start_background(coro_factory, name)
        respawn_task = asyncio.create_task(_respawn(), name=f"{name}-respawn")
        _background_tasks.add(respawn_task)

    task = asyncio.create_task(coro_factory(), name=name)
    _background_tasks.add(task)
    # M1/P1 (R4-02): canlı görev kaydı — respawn bu kaydı güncellesin diye
    # `_start_background` yeniden çağrıldığında da kayıt tazelenir.
    _background_registry[name] = task
    task.add_done_callback(_restart_if_failed)
    return task

async def _fresh_public_price(symbol: str):
    """Return a fresh public price, repairing stale websocket state via REST.

    Public price endpoint (``/ticker/price``) weight:2 olmasına rağmen 1m
    kline'tan daha yüksek frekanslı ve doğrudan güncel fiyatı döndürür;
    kline yerine tercih edilir. Erişilemezse en son kapanıştan geriye dönülür.
    """
    normalized = str(symbol or "").replace("_", "").upper()
    now_ms = time.time() * 1000
    ticker = market.get_ticker(normalized) or {}
    price = float(ticker.get("last_price") or 0)
    timestamp = float(ticker.get("timestamp") or 0)
    if price > 0 and timestamp > 0 and now_ms - timestamp <= config.MAX_TICKER_AGE_SEC * 1000:
        return price, {**ticker, "source": ticker.get("source", "binance_tr_public_websocket")}
    try:
        rows = await ticker_price([normalized])
        row = next((r for r in rows if str(r.get("symbol", "")).upper() == normalized), None)
        price = float((row or {}).get("price") or 0)
        if price > 0:
            repaired = {"symbol": normalized, "last_price": price, "timestamp": int(now_ms),
                        "source": "binance_tr_public_rest_ticker_price"}
            market.tickers[normalized] = repaired
            return price, repaired
    except Exception as exc:
        print(f"[Public price fallback] {normalized}: {exc}")
    try:
        latest = await fetch_klines(normalized, "1m", 2)
        if latest:
            price = float(latest[-1][4])
            repaired = {"symbol": normalized, "last_price": price, "timestamp": int(now_ms), "source": "binance_tr_public_rest_kline"}
            market.tickers[normalized] = repaired
            return price, repaired
    except Exception as exc:
        print(f"[Public price final kline fallback] {normalized}: {exc}")
    return None, None

def _json_safe_positions(value):
    """Recursively replace NaN/±Infinity floats with None (JSON-safe)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe_positions(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe_positions(v) for v in value]
    return value


def _llm_guard_block_reason(guard):
    if not guard or guard.get("status") != "active":
        return None
    blocked_until = guard.get("blocked_until")
    if blocked_until is not None and float(blocked_until) <= time.time():
        return None
    return "llm_guard:cooldown"


from app.correlation import CorrelationMonitor

correlation_monitor = CorrelationMonitor()


def _main_pg_pool():
    """Live asyncpg pool accessor; the pool is created by app startup."""
    from app import main
    return main._pg_pool


def _client_ip(request) -> str | None:
    """Caller IP: trusted nginx X-Real-IP first, raw socket host as fallback."""
    if request is None:
        return None
    trusted = (request.headers.get("X-Real-IP") or "").strip() if request.headers else ""
    if trusted:
        return trusted
    try:
        if request.client is not None and request.client.host:
            return str(request.client.host)
    except Exception:
        pass
    return None


def client_context(request) -> dict:
    """IP + device fingerprint for audit rows. Never raises; best effort."""
    try:
        ip = _client_ip(request)
        user_agent = (request.headers.get("user-agent") or "").strip()[:512] if request.headers else ""
        accept_language = (request.headers.get("accept-language") or "").strip()[:256] if request.headers else ""
        return {"ip": ip, "user_agent": user_agent or None, "accept_language": accept_language or None}
    except Exception:
        return {"ip": None, "user_agent": None, "accept_language": None}


async def log_user_action(actor_username: str | None, actor_role: str | None, category: str, action: str,
                          *, target: str | None = None, details: dict | None = None,
                          request=None) -> None:
    """Append one audit row without ever breaking the caller's main flow.

    Logging is best-effort: a DB hiccup must not fail a login, config save or
    manual close. The synchronous database call runs in its own thread via the
    shared _run_db executor; awaiting here is cheap and preserves ordering.
    """
    ctx = client_context(request)
    try:
        await database.save_audit_log(
            actor_username, actor_role, category, action,
            target=target, details=details or {},
            ip=ctx.get("ip"), user_agent=ctx.get("user_agent"),
            accept_language=ctx.get("accept_language"))
    except Exception as exc:  # noqa: BLE001 - audit must never break the action
        logger.warning("audit kaydı yazılamadı (%s/%s): %s", category, action, exc)
