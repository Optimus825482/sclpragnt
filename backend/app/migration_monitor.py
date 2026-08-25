import asyncio, hashlib, json, os, sqlite3, time, subprocess, sys
from pathlib import Path
from . import database

TABLES = ("positions", "trades", "signals", "decision_logs", "llm_tool_logs", "a2a_messages", "llm_symbol_guards", "virtual_wallet", "chart_settings", "llm_providers", "llm_models", "llm_skills", "llm_settings", "backtests")
state = {"status":"idle", "phase":"idle", "progress":0, "message":"Migration hazır", "source":None, "counts":{}, "error":None, "started_at":None, "finished_at":None, "logs":[]}
lock = asyncio.Lock()

def _log(message, level="info"):
    state.setdefault("logs", []).append({"time": time.time(), "level": level, "message": message})
    state["logs"] = state["logs"][-200:]

def inspect_source(path):
    p = Path(path)
    if not p.is_file(): raise FileNotFoundError(path)
    conn = sqlite3.connect(path, timeout=30); conn.execute("PRAGMA busy_timeout=30000"); counts = {}
    for table in TABLES:
        try: counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error: counts[table] = 0
    # Hash in chunks: reading the whole database into RAM scales with file size.
    digest = hashlib.sha256()
    with open(p, "rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    conn.close(); return {"path":str(p.resolve()), "sha256":digest.hexdigest(), "counts":counts, "size_bytes":p.stat().st_size}


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
    counts = {}
    async with pool.acquire() as pg:
        for table in TABLES:
            counts[table] = int(await pg.fetchval(f'SELECT COUNT(*) FROM "{table}"') or 0)
    return counts

async def _set(**kwargs):
    state.update(kwargs)

async def run(source, database_url, publish=None):
    async with lock:
        if state["status"] == "running": return
        state["logs"] = []
        _log("Migration başlatıldı")
        await _set(status="running", phase="inspect", progress=5, message="SQLite kaynak doğrulanıyor", source=source, error=None, started_at=time.time(), finished_at=None)
        try:
            info = inspect_source(source); state["source"] = info
            _log(f"SQLite doğrulandı: {info['size_bytes']} byte")
            await _set(phase="schema", progress=15, message="PostgreSQL şeması kuruluyor")
            import asyncpg
            pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
            try:
                schema = Path(__file__).resolve().parent.parent / "migrations" / "001_pgvector_schema.sql"
                async with pool.acquire() as pg:
                    _log("PostgreSQL şema SQL'i çalıştırılıyor")
                    await asyncio.wait_for(pg.execute(schema.read_text(encoding="utf-8")), timeout=120)
                _log("PostgreSQL şeması hazır")
                await _set(phase="transfer", progress=25, message="SQLite kayıtları aktarılıyor")
                await asyncio.to_thread(_copy_rows, source, database_url)
                _log("Tüm SQLite kayıtları PostgreSQL'e aktarıldı")
                await _set(phase="verify", progress=90, message="Kayıt sayıları doğrulanıyor")
                target_counts = await fetch_target_counts(pool)
                count_errors = compare_counts(info["counts"], target_counts)
                if count_errors:
                    raise RuntimeError("Migration kayıt doğrulaması başarısız: " + "; ".join(count_errors))
                state["counts"] = {"source": info["counts"], "target": target_counts}
                _log("Kayıt sayıları doğrulandı", "success")
                await _set(phase="complete", progress=100, status="completed", message="Migration başarıyla tamamlandı", finished_at=time.time())
            finally: await pool.close()
        except Exception as exc:
            _log(f"Hata: {exc}", "error")
            await _set(status="failed", phase="error", message="Migration başarısız", error=str(exc), finished_at=time.time())

def _copy_rows(source, database_url):
    script = Path(__file__).resolve().parent.parent / "scripts" / "migrate_sqlite_to_postgres.py"
    # The URL carries the DB password: pass it via stdin, never argv, so it
    # is not readable from `ps` inside the container.
    process = subprocess.Popen([sys.executable, "-u", str(script), "--source", source, "--database-url", "-", "--apply"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        stdout, stderr = process.communicate(input=database_url, timeout=600)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise RuntimeError("Migration script 600 saniyede tamamlanmadı")
    for line in stdout.splitlines():
        if line.strip(): _log(line.strip())
    if process.returncode != 0: raise RuntimeError(stderr[-4000:] or stdout[-4000:] or "Migration script failed")
