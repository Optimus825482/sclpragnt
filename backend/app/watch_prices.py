"""Kullanıcı arayüzü canlı fiyatları: tüm bağlı kullanıcılar için TEK sembol birleşimi, ~3 sn'de bir yayın."""
import asyncio
import logging
import re
import time

logger = logging.getLogger("scalper.watch_prices")

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
WATCH_CAP = 50
WATCH_INTERVAL_SEC = 3.0


def collect_watch_symbols(notif_rows: list[dict], rising_rows: list[dict], cap: int = WATCH_CAP) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in list(notif_rows) + list(rising_rows):
        sym = str((row or {}).get("symbol") or "").strip().upper()
        if not _SYMBOL_RE.match(sym) or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
        if len(out) >= cap:
            break
    return out


async def watch_prices_loop():
    """Bağlı WS istemcisi yoksa Binance'e istek ATMAZ. Hata döngüyü öldürmez."""
    from app import database
    from app.routers import monitoring
    from app.ws_runtime import ws_manager
    await asyncio.sleep(5)
    while True:
        try:
            if not getattr(ws_manager, "active_connections", None):
                await asyncio.sleep(WATCH_INTERVAL_SEC)
                continue
            notifs = await database.list_monitoring_notifications(limit=20)
            rising = await database.list_daily_rising(days=7)
            symbols = collect_watch_symbols(notifs, rising or [])
            if symbols:
                prices = await monitoring._batch_prices(symbols)
                clean = {s: float(p) for s, p in (prices or {}).items() if p}
                if clean:
                    await ws_manager.broadcast({"type": "watch_prices",
                                                "data": {"prices": clean, "time": time.time()}})
        except Exception as exc:  # noqa: BLE001 — döngü ölmemeli
            logger.debug("watch_prices atlandı: %s", type(exc).__name__)
        await asyncio.sleep(WATCH_INTERVAL_SEC)
