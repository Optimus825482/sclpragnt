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
