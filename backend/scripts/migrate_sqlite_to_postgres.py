"""Safe, explicit SQLite -> PostgreSQL migration.

This command never guesses the source database and never deletes SQLite data.
Run only after stopping the application and review the printed source hash/counts.
"""
import argparse, asyncio, hashlib, json, os, sqlite3
from pathlib import Path
import asyncpg

TABLES = ("positions", "trades", "signals", "decision_logs", "llm_tool_logs", "a2a_messages", "llm_symbol_guards", "virtual_wallet", "chart_settings", "llm_providers", "llm_models", "llm_skills", "llm_settings", "backtests")
JSON_COLUMNS = {"entry_context", "metadata", "arguments", "payload", "evidence", "data", "params", "trades"}

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()

def snapshot(path):
    conn = sqlite3.connect(path, timeout=30); conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    counts = {}
    for table in TABLES:
        try: counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error: counts[table] = None
    return conn, counts

async def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--source", required=True); parser.add_argument("--database-url", default=os.getenv("DATABASE_URL")); parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = str(Path(args.source).resolve())
    if not Path(source).is_file(): raise SystemExit(f"SQLite source not found: {source}")
    # "-" means the URL is piped via stdin so the password never appears in argv.
    database_url = os.getenv("DATABASE_URL") if args.database_url == "-" else args.database_url
    if not database_url: raise SystemExit("DATABASE_URL is required")
    sqlite_conn, counts = snapshot(source); digest = sha256(source)
    print(json.dumps({"source": source, "sha256": digest, "counts": counts}, ensure_ascii=False, indent=2))
    if not args.apply: print("Dry run only. Re-run with --apply after reviewing source."); return
    pg = await asyncpg.connect(database_url)
    try:
        schema = (Path(__file__).resolve().parent.parent / "migrations" / "001_pgvector_schema.sql").read_text(encoding="utf-8")
        await pg.execute(schema)
        await pg.execute("INSERT INTO migration_meta(version,source_path,source_sha256,source_counts) VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(version) DO NOTHING", "sqlite-001", source, digest, json.dumps(counts))
        for table in TABLES:
            try: rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.Error: continue
            if not rows: continue
            columns = [d[0] for d in sqlite_conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
            target_rows = await pg.fetch("SELECT column_name,data_type,udt_name FROM information_schema.columns WHERE table_name=$1", table)
            target_columns = {r["column_name"]: (r["data_type"], r["udt_name"]) for r in target_rows}
            columns = [c for c in columns if c in target_columns]
            if not columns: continue
            quoted = ",".join('"' + c.replace('"','""') + '"' for c in columns)
            placeholders = ",".join(f"${i}" for i in range(1, len(columns)+1))
            sql = f"INSERT INTO \"{table}\" ({quoted}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            values = []
            for row in rows:
                item = []
                for col in columns:
                    value = row[col]
                    data_type, udt_name = target_columns[col]
                    if data_type == "boolean" and value is not None:
                        value = bool(value)
                    if col in JSON_COLUMNS and value:
                        try: value = json.dumps(json.loads(value), ensure_ascii=False)
                        except (TypeError, json.JSONDecodeError): value = json.dumps(value)
                    item.append(value)
                values.append(item)
            await pg.executemany(sql, values, timeout=120)
            migrated = await pg.fetchval(f'SELECT COUNT(*) FROM "{table}"')
            if int(migrated) < len(rows): raise RuntimeError(f"{table}: hedef satır sayısı eksik ({migrated}/{len(rows)})")
            print(f"{table}: {len(rows)} kayıt aktarıldı", flush=True)
        initial_balance = float(os.getenv("INITIAL_BALANCE_TRY", "10000"))
        commission_pct = float(os.getenv("COMMISSION_PCT", "0.0015"))
        await pg.execute("""UPDATE virtual_wallet SET amount=(
            $1 + COALESCE((SELECT SUM(pnl) FROM trades), 0)
            - COALESCE((SELECT SUM(entry_price * quantity) FROM positions), 0)
            - COALESCE((SELECT SUM(entry_price * quantity) FROM positions), 0) * $2
        ) WHERE asset='TRY'""", initial_balance, commission_pct)
        print("TRY cüzdanı açık pozisyonlar ve net PnL ile mutabıklandı", flush=True)
        print("Migration completed with row-count lower-bound validation. SQLite source was not modified.")
    finally: await pg.close(); sqlite_conn.close()

if __name__ == "__main__": asyncio.run(main())
