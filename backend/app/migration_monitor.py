import asyncio, hashlib, json, os, sqlite3, time, subprocess, sys
from pathlib import Path
from . import database

TABLES = ("positions", "trades", "signals", "decision_logs", "llm_tool_logs", "virtual_wallet", "chart_settings", "llm_providers", "llm_models", "llm_skills", "llm_settings", "backtests")
state = {"status":"idle", "phase":"idle", "progress":0, "message":"Migration hazır", "source":None, "counts":{}, "error":None, "started_at":None, "finished_at":None}
lock = asyncio.Lock()

def inspect_source(path):
    p = Path(path)
    if not p.is_file(): raise FileNotFoundError(path)
    conn = sqlite3.connect(path); counts = {}
    for table in TABLES:
        try: counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error: counts[table] = 0
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    conn.close(); return {"path":str(p.resolve()), "sha256":digest, "counts":counts, "size_bytes":p.stat().st_size}

async def _set(**kwargs):
    state.update(kwargs)

async def run(source, database_url, publish=None):
    async with lock:
        if state["status"] == "running": return
        await _set(status="running", phase="inspect", progress=5, message="SQLite kaynak doğrulanıyor", source=source, error=None, started_at=time.time(), finished_at=None)
        try:
            info = inspect_source(source); state["source"] = info
            await _set(phase="schema", progress=15, message="PostgreSQL şeması kuruluyor")
            import asyncpg
            pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
            try:
                schema = Path(__file__).resolve().parent.parent / "migrations" / "001_pgvector_schema.sql"
                async with pool.acquire() as pg:
                    await pg.execute(schema.read_text(encoding="utf-8"))
                await _set(phase="transfer", progress=25, message="SQLite kayıtları aktarılıyor")
                await asyncio.to_thread(_copy_rows, source, database_url)
                await _set(phase="verify", progress=90, message="Kayıt sayıları doğrulanıyor")
                await _set(phase="complete", progress=100, status="completed", message="Migration başarıyla tamamlandı", finished_at=time.time())
            finally: await pool.close()
        except Exception as exc:
            await _set(status="failed", phase="error", message="Migration başarısız", error=str(exc), finished_at=time.time())

def _copy_rows(source, database_url):
    script = Path(__file__).resolve().parent.parent / "scripts" / "migrate_sqlite_to_postgres.py"
    result = subprocess.run([sys.executable, str(script), "--source", source, "--database-url", database_url, "--apply"], capture_output=True, text=True, timeout=1800)
    if result.returncode != 0: raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:] or "Migration script failed")
