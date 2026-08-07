"""Run the ScalperAgent PostgreSQL schema during a maintenance window.

Unlike application startup, this command fails fast when another process holds a
DDL lock and never leaves a half-applied transaction behind.
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli")
    sql = (Path(__file__).resolve().parents[1] / "migrations" / "001_pgvector_schema.sql").read_text(encoding="utf-8")
    conn = None
    last_error = None
    for attempt in range(1, 13):
        try:
            conn = await asyncpg.connect(
                url,
                timeout=10,
                server_settings={"statement_timeout": "120000", "lock_timeout": "5000"},
            )
            break
        except Exception as exc:
            last_error = exc
            print(f"PostgreSQL bağlantısı bekleniyor ({attempt}/12): {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            if attempt < 12:
                await asyncio.sleep(5)
    if conn is None:
        raise SystemExit(f"PostgreSQL migration bağlantısı kurulamadı: {last_error}")
    try:
        async with conn.transaction():
            await conn.execute(sql)
        print("PostgreSQL migration tamamlandı.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
