"""One-shot paper-only enrichment of historical trade entry contexts."""
import asyncio

from app import database
from app.main import _run_historical_mtf_backfill


async def main():
    await database.init_db()
    await _run_historical_mtf_backfill({"force": True})


if __name__ == "__main__":
    asyncio.run(main())
