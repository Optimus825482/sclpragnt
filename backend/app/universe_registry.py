"""S7a: point-in-time symbol universe registry.

Top-gainer rotation replaces the tradable list hourly; backtests that iterate
"current symbols" therefore carry survivorship bias (delisted/dropped symbols
vanish from research). This module records, on every universe change, which
symbols were active and when — giving research tools a way to reconstruct the
universe *as it existed at any past moment*.

Storage reuses llm_settings KV as JSON (small, low-churn document).
"""
import json
import time

from app import database

_KEY = "symbol_universe_history"
_MAX_ENTRIES = 2000  # ~ years of hourly snapshots; KV stays bounded


async def record_universe(active_symbols: list[str], source: str = "top_gainers"):
    """Append one snapshot {ts, source, symbols} and prune old entries."""
    try:
        raw = await database.get_llm_setting(_KEY, "[]")
        history = json.loads(raw or "[]")
    except (ValueError, TypeError):
        history = []
    now = time.time()
    # Skip duplicate consecutive snapshots (same set within 10 min).
    if history:
        last = history[-1]
        if now - float(last.get("ts") or 0) < 600 and \
                sorted(last.get("symbols") or []) == sorted(active_symbols):
            return {"recorded": False, "reason": "duplicate_recent"}
    history.append({"ts": now, "source": source,
                    "symbols": sorted(str(s).upper() for s in active_symbols)})
    history = history[-_MAX_ENTRIES:]
    await database.set_llm_setting(_KEY, json.dumps(history))
    return {"recorded": True, "entries": len(history)}


async def universe_at(ts: float) -> dict:
    """Reconstruct the active universe as it was at ``ts``."""
    try:
        raw = await database.get_llm_setting(_KEY, "[]")
        history = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return {"symbols": [], "as_of": None}
    best = None
    for entry in history:
        if float(entry.get("ts") or 0) <= ts:
            best = entry
        else:
            break
    if not best:
        return {"symbols": [], "as_of": None}
    return {"symbols": best.get("symbols") or [], "as_of": best.get("ts"),
            "source": best.get("source")}
