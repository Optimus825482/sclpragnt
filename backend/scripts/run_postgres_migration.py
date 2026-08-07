"""Run the ScalperAgent PostgreSQL schema during a maintenance window.

Unlike application startup, this command fails fast when another process holds a
DDL lock and never leaves a half-applied transaction behind.
"""
import asyncio
import os
from pathlib import Path

import asyncpg


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli")
    sql = (Path(__file__).resolve().parents[1] / "migrations" / "001_pgvector_schema.sql").read_text(encoding="utf-8")
    conn = await asyncpg.connect(url, server_settings={"statement_timeout": "120000", "lock_timeout": "5000"})
    try:
        async with conn.transaction():
            await conn.execute(sql)
        print("PostgreSQL migration tamamlandı.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
