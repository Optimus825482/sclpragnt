"""SQLite → PostgreSQL migration monitor (pasif).

SQLite desteği uygulamadan tamamen kaldırılmıştır; uygulama yalnızca
PostgreSQL kullanır. Migration aracı artık gereksizdir. `/api/migration/*`
uçları çağrılmaya devam ederse "SQLite migration gerekmiyor" durumu döner
ve hiçbir SQLite dosyasına dokunulmaz.
"""

import time

# Durable tables that any historical SQLite → PostgreSQL migration had to
# cover. Kept as the canonical list so migration/verification contracts stay
# testable even though the live app is PostgreSQL-only.
TABLES = ("positions", "trades", "signals", "decision_logs", "llm_tool_logs",
          "llm_symbol_guards", "virtual_wallet", "chart_settings",
          "llm_providers", "llm_models", "llm_skills", "llm_settings", "backtests")

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
def _log(message, level="info"):
    state.setdefault("logs", []).append({"time": time.time(), "level": level, "message": message})
    state["logs"] = state["logs"][-200:]


def inspect_source(path):
    raise RuntimeError("SQLite migration kaldırıldı; uygulama yalnızca PostgreSQL kullanır")


def compare_counts(source_counts, target_counts):
    """Return deterministic lower-bound violations for migrated tables."""
    errors = []
    for table in TABLES:
        source_count = source_counts.get(table)
        if source_count is None:
            continue
        target_count = int(target_counts.get(table) or 0)
        if target_count != int(source_count):
            errors.append(f"{table}: hedef satır sayısı uyuşmuyor ({target_count}/{source_count})")
    return errors


async def fetch_target_counts(pool):
    return {}


async def run(source, database_url, publish=None):
    await _set(status="completed", phase="complete", progress=100,
               message="SQLite migration gerekmiyor (PostgreSQL tek backend)",
               finished_at=time.time())


async def _set(**kwargs):
    state.update(kwargs)