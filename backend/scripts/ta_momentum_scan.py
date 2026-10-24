"""M1H kuralı — betik tarafı sarmalayıcı (2026-10-24). Mantık app/momentum_scan.py'de; burada yalnız yerel arşiv (historical_candles)
yükleyicisi ve kesit şimdiye yakınsa canlı REST'e geçiş vardır. ta_n6_tracker.py `MS.scan(cutoff_ms, top)` ile çağırır.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.momentum_scan import (  # noqa: E402,F401  (geriye dönük: tracker ve testler bu adları buradan okur)
    BASE_TARGET_PCT, M15, MIN_BARS, MIN_QV, STABLE, WEIGHTS, bars_live, is_stable, momentum_features, momentum_score, rank, rows_to_bars,
)
from app import momentum_scan as _core  # noqa: E402

LIVE_WINDOW_MS = 90 * 60_000      # kesit şimdiye bu kadar yakınsa REST, değilse arşiv


async def _bars_archive(sym: str, cutoff_ms: int) -> list[dict]:
    import ta_feature_study as FS
    d = await FS.load_db(sym, cutoff_ms - 8 * 86_400_000, cutoff_ms)
    if not d:
        return []
    return [{"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "q": b["q"]} for b in d["15m"]]


async def scan(cutoff_ms: int, top: int = 3, live: bool | None = None, concurrency: int = 6) -> dict:
    """Tüm TRY paritelerini tarar; ta_n6_tracker.build_list ile aynı şekilde sonuç sözlüğü döner."""
    if live is None:
        live = (time.time() * 1000 - cutoff_ms) <= LIVE_WINDOW_MS

    def progress(done: int, total: int) -> None:
        if done % 50 == 0:
            print(f"  {done}/{total}", file=sys.stderr)

    loader = None if live else (lambda sym: _bars_archive(sym, cutoff_ms))
    res = await _core.scan(cutoff_ms, top, bars_loader=loader, concurrency=concurrency, progress=progress)
    res["depth_src"] = "canlı defter" if live else "arşiv"
    return res
