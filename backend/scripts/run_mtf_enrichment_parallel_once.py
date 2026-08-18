"""Parallel, paper-only refresh of enriched historical trade snapshots."""
import asyncio
import time

from app import database
from app.main import _historical_entry_mtf


async def main():
    await database.init_db()
    rows = await database.get_trades(None)
    semaphore = asyncio.Semaphore(6)

    async def enrich(row):
        async with semaphore:
            symbol = str(row.get("symbol") or "").replace("_", "").upper()
            entry_time = row.get("entry_time")
            if not symbol or entry_time is None:
                return False
            entry_price = float(row.get("entry_price") or 500)
            order_value = entry_price * float(row.get("quantity") or 1)
            snapshots = await _historical_entry_mtf(symbol, entry_time, entry_price, order_value)
            context = database._json_value(row.get("entry_context"), {}) if isinstance(row.get("entry_context"), str) else dict(row.get("entry_context") or {})
            technical = dict(context.get("technical") or {})
            technical["mtf_snapshots"] = snapshots
            technical["mtf_timeframes"] = list(snapshots)
            alignments = [(item.get("trend") or {}).get("alignment") for item in snapshots.values()]
            bullish = sum(value == "bullish" for value in alignments)
            bearish = sum(value == "bearish" for value in alignments)
            technical["derived_entry_features"] = {"mtf_bullish_count": bullish, "mtf_bearish_count": bearish,
                "mtf_mixed_count": len(alignments) - bullish - bearish, "mtf_alignment_score": bullish - bearish,
                "mtf_all_ready": len(snapshots) == 5 and all(item.get("data_ready") for item in snapshots.values())}
            context["technical"] = technical
            context["mtf_backfill"] = {"version": "public-entry-mtf-v2-enriched", "source": "binance_tr_public",
                "completed_at": time.time(), "entry_time": float(entry_time), "liquidity_fields": "unknown"}
            await database.apply_historical_mtf_backfill("trade", row.get("id"), symbol, row.get("trade_id"), context, snapshots)
            return True

    results = await asyncio.gather(*(enrich(row) for row in rows), return_exceptions=True)
    success = sum(result is True for result in results)
    failed = len(results) - success
    print(f"[COMPLETE] enriched={success} failed={failed} total={len(results)} paper_only=True", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
