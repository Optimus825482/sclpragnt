"""Append an explicitly partial replay-parity audit for legacy decisions.

It never changes positions, trades, balances, signals or strategy settings.
Use --apply only after reviewing the dry-run summary.
"""
import argparse
import asyncio
import json

from app import database


async def run(args):
    result = await database.backfill_replay_parity_observations(args.limit, args.apply)
    result["mode"] = "apply" if args.apply else "dry_run"
    result["paper_only"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20_000)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))
