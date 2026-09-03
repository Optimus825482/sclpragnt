"""Shared API runtime helpers used by main.py and every router module."""
import asyncio
import logging
import math
import time

from app.config import config
from app import database
from app.correlation import cluster_exposure
from app.binance_tr_public import orderbook
from collections import deque
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
_strategy_scan_logs = deque(maxlen=5000)

_background_tasks = set()

def _start_background(coro, name):
    """Başlat ve supervisors manual da olsa, hata ile biterse sınırlı geri alımla yeniden başlat.

    Uzun ömürlü background döngüleri (strategy, radar, broadcast, a2a, ...) iç
    try/except ile kendi hatalarını yutacak şekilde yazılır. Yine de beklenmeyen
    bir istisna düşürülürse görev, CancelledError dışındaki hatalarda sonlu bir
    geri alımla (backoff) yeniden oluşturulur; böylece tek seferlik görevlerin
    doğal tamamlanması yeniden başlatılmaz.
    """
    restart_attempt = {"count": 0}

    def _restart_if_failed(task):
        _background_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if not exc:
            # normal tamamlama (single-pass görevleri); yeniden başlatma yok.
            restart_attempt["count"] = 0
            return
        # Beklenmeyen hata: sonlu geri alımla yeniden başlat.
        restart_attempt["count"] += 1
        delay = min(2 * restart_attempt["count"], 30)
        logger.error("background görev '%s' hata ile düştü (%s); %.0fs sonra yeniden deneniyor.",
                     name, exc, delay, exc_info=True)
        async def _respawn():
            await asyncio.sleep(delay)
            _start_background(coro, name)
        asyncio.create_task(_respawn(), name=f"{name}-respawn")

    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_restart_if_failed)
    return task

def _record_strategy_scan_log(scan_type: str, symbol: str, status: str, **details):
    """Keep a bounded UI log and durable replay-parity evidence.

    The durable record is observational only.  It does not alter an entry,
    exit, portfolio balance, or strategy setting; it gives a later replay the
    exact decision context that public historical candles cannot otherwise
    reconstruct (universe, M1 activity and current portfolio state).
    """
    entry = {
        "timestamp": time.time(),
        "scan_type": scan_type,
        "symbol": symbol,
        "status": status,
        **details,
    }
    _strategy_scan_logs.appendleft(entry)
    if scan_type in {"automatic", "manual", "pump_monitor"}:
        try:
            from app.routers.maintenance import _persist_replay_parity_observation
            asyncio.get_running_loop().create_task(
                _persist_replay_parity_observation(dict(entry)),
                name=f"replay-parity-{scan_type}-{symbol}",
            )
        except RuntimeError:
            # This helper is also used by a few synchronous tests before the
            # application event loop exists.  The bounded in-memory log still
            # remains available in that case.
            pass
    return entry

async def _fresh_public_price(symbol: str):
    """Return a fresh public price, repairing stale websocket state via REST."""
    normalized = str(symbol or "").replace("_", "").upper()
    now_ms = time.time() * 1000
    ticker = market.get_ticker(normalized) or {}
    price = float(ticker.get("last_price") or 0)
    timestamp = float(ticker.get("timestamp") or 0)
    if price > 0 and timestamp > 0 and now_ms - timestamp <= config.MAX_TICKER_AGE_SEC * 1000:
        return price, {**ticker, "source": ticker.get("source", "binance_tr_public_websocket")}
    try:
        latest = await fetch_klines(normalized, "1m", 2)
        if latest:
            price = float(latest[-1][4])
            repaired = {"symbol": normalized, "last_price": price, "timestamp": int(now_ms), "source": "binance_tr_public_rest"}
            market.tickers[normalized] = repaired
            return price, repaired
    except Exception as exc:
        print(f"[Public price fallback] {normalized}: {exc}")
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
