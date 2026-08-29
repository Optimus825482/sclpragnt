"""SQLite → PostgreSQL migration monitor (pasif).

SQLite desteği uygulamadan tamamen kaldırılmıştır; uygulama yalnızca
PostgreSQL kullanır. Migration aracı artık gereksizdir. `/api/migration/*`
uçları çağrılmaya devam ederse "SQLite migration gerekmiyor" durumu döner
ve hiçbir SQLite dosyasına dokunulmaz.
"""

import time

state = {
    "status": "idle",
    "phase": "idle",
    "progress": 0,
    "message": "Uygulama yalnızca PostgreSQL kullanıyor; SQLite migration gerekmiyor",
    "source": None,
    "counts": {},
    "error": None,
    "started_at": None,
    "finished_at": None,
    "logs": [{"time": time.time(), "level": "info",
               "message": "SQLite desteği kaldırıldı; PostgreSQL tek veritabanıdır."}],
}
lock = None


def _log(message, level="info"):
    state.setdefault("logs", []).append({"time": time.time(), "level": level, "message": message})
    state["logs"] = state["logs"][-200:]


def inspect_source(path):
    raise RuntimeError("SQLite migration kaldırıldı; uygulama yalnızca PostgreSQL kullanır")


def compare_counts(source_counts, target_counts):
    return []


async def fetch_target_counts(pool):
    return {}


async def run(source, database_url, publish=None):
    await _set(status="completed", phase="complete", progress=100,
               message="SQLite migration gerekmiyor (PostgreSQL tek backend)",
               finished_at=time.time())


async def _set(**kwargs):
    state.update(kwargs)