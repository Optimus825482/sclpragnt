"""Paper-only outcome labels for BB-MFI positions that lock capital without progress."""

import argparse
import asyncio
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database


def finite(values):
    return [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]


def group_summary(rows, field):
    result = {}
    for name, subset in (("capital_lock", [row for row in rows if row["capital_lock"]]),
                         ("other", [row for row in rows if not row["capital_lock"]])):
        values = finite([row.get(field) for row in subset])
        result[name] = {
            "n": len(values),
            "mean": round(statistics.mean(values), 6) if values else None,
            "median": round(statistics.median(values), 6) if values else None,
        }
    return result


async def run(args):
    await database.init_db()
    raw = await database.get_trades(limit=None, strategy="BB_MFI_MEAN_REVERSION")
    rows = []
    for trade in raw:
        context = database._json_value(trade.get("entry_context"), {}) if isinstance(trade.get("entry_context"), str) else (trade.get("entry_context") or {})
        activity = context.get("symbol_activity") or {}
        features = activity.get("m1_features") or {}
        hold_seconds = float(trade.get("hold_seconds") or 0)
        max_favorable = float(trade.get("max_favorable_pct") or 0)
        if hold_seconds <= 0:
            continue
        rows.append({
            "trade_id": trade.get("trade_id"), "symbol": trade.get("symbol"),
            "pnl_try": float(trade.get("pnl") or 0), "hold_hours": hold_seconds / 3600,
            "max_favorable_pct": max_favorable * 100,
            "capital_lock": hold_seconds >= args.min_hold_hours * 3600 and max_favorable < args.max_favorable_pct / 100,
            "m1_flat_5m_count": activity.get("m1_flat_5m_count"),
            "m1_flat_30m_count": activity.get("m1_flat_30m_count"),
            **{f"m1_{key}": value for key, value in features.items() if isinstance(value, (int, float))},
        })
    fields = sorted({key for row in rows for key in row if key.startswith("m1_")})
    locked = [row for row in rows if row["capital_lock"]]
    result = {
        "paper_only": True,
        "source": "local PostgreSQL trades.entry_context",
        "label": {"min_hold_hours": args.min_hold_hours, "max_favorable_pct": args.max_favorable_pct},
        "trade_count": len(rows),
        "capital_lock_count": len(locked),
        "capital_lock_net_pnl_try": round(sum(row["pnl_try"] for row in locked), 6),
        "fields_with_snapshot_data": fields,
        "comparisons": {field: group_summary(rows, field) for field in fields},
        "limitations": [
            "Only positions opened after symbol_activity snapshot persistence have M1 activity fields.",
            "This labels observed outcomes; it does not change entry, exit, or position sizing.",
            "Any future filter requires separate chronological replay and OOS confirmation.",
        ],
    }
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("trade_count", "capital_lock_count", "capital_lock_net_pnl_try", "fields_with_snapshot_data")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-hold-hours", type=float, default=4.0)
    parser.add_argument("--max-favorable-pct", type=float, default=0.75)
    parser.add_argument("--output", default="capital-lock-outcome-analysis.json")
    args = parser.parse_args()
    if args.min_hold_hours <= 0 or args.max_favorable_pct < 0:
        parser.error("Etiket eşikleri pozitif/negatif olmayan değerler olmalıdır")
    asyncio.run(run(args))
