"""Resumable local cache for reproducible Binance TR public M1 research."""

import asyncio
import json
import os
from pathlib import Path

from app.binance_tr_public import klines
from scripts.research_mtf_5of5_managed_replay import normalize


PAGE_MINUTES = 1_000
PAGE_MS = PAGE_MINUTES * 60_000


def _page_path(cache_dir: Path, symbol: str, start_ms: int, end_ms: int) -> Path:
    return cache_dir / symbol.upper() / f"m1_{start_ms}_{end_ms}.json"


def _read_page(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, list) else None


def _write_page(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


async def cached_m1(symbol: str, start_ms: int, end_ms: int, cache_dir: str | Path):
    """Return normalized closed M1 rows plus cache provenance.

    Each immutable time page is atomically persisted as soon as it arrives, so
    an interrupted run resumes without refetching completed pages.
    """
    root = Path(cache_dir)
    pages, hits, misses = [], 0, 0
    for page_start in range(start_ms, end_ms, PAGE_MS):
        page_end = min(end_ms, page_start + PAGE_MS - 1)
        path = _page_path(root, symbol, page_start, page_end)
        rows = _read_page(path)
        if rows is None:
            rows = await klines(symbol, "1m", PAGE_MINUTES, page_start, page_end)
            _write_page(path, rows)
            misses += 1
            # Keep public-data requests deliberate; page persistence makes this
            # modest pause cheap and avoids a rate-limit burst on resume.
            await asyncio.sleep(0.05)
        else:
            hits += 1
        pages.extend(rows)
    return normalize(pages), {"cache_dir": str(root), "page_hits": hits, "page_misses": misses}
