"""Audit only the historical M5 movement gate; it never opens paper trades.

Example:
python -m scripts.audit_activity_filter --start-date 2026-08-12T04:10:00 --end-date 2026-08-13T04:10:00
"""
import argparse
import asyncio
import bisect
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from app.analyzer import ScalpAnalyzer
from app.config import config


def series(rows):
    data = {key: [] for key in ("closes", "highs", "lows", "volumes", "times")}
    for row in rows:
        for key in ("closes", "highs", "lows", "volumes"):
            source = {"closes": "close", "highs": "high", "lows": "low", "volumes": "volume"}[key]
            data[key].append(float(row[source]))
        data["times"].append(int(row["close_time"]) // 1000)
    return data


def movement_check(analyzer, data, index, min_range, min_atr):
    start = max(0, index - 249)
    window = {key: values[start:index + 1] for key, values in data.items()}
    if len(window["closes"]) < 21:
        return None
    low, high = min(window["lows"][-3:]), max(window["highs"][-3:])
    range_pct = (high - low) / low * 100 if low else 0.0
    atr = analyzer.calculate_atr(window, 14) or 0.0
    atr_pct = atr / window["closes"][-1] * 100 if window["closes"][-1] else 0.0
    return {
        "range_15m_pct": round(range_pct, 4), "atr_pct": round(atr_pct, 4),
        "range_ok": range_pct >= min_range, "atr_ok": atr_pct >= min_atr,
    }


def future_move_pct(data, index, horizon_bars):
    """Realised future excursion used only to audit the filter, never as a signal."""
    end = min(len(data["closes"]), index + 1 + horizon_bars)
    if end <= index + 1 or not data["closes"][index]:
        return None
    base = data["closes"][index]
    highest = max(data["highs"][index + 1:end])
    lowest = min(data["lows"][index + 1:end])
    return max((highest / base - 1) * 100, (1 - lowest / base) * 100)


async def main(args):
    tz = ZoneInfo(args.timezone)
    start_ts = int(datetime.fromisoformat(args.start_date).replace(tzinfo=tz).timestamp())
    end_ts = int(datetime.fromisoformat(args.end_date).replace(tzinfo=tz).timestamp())
    if start_ts >= end_ts:
        raise SystemExit("Başlangıç bitişten önce olmalıdır")
    await database.init_db()
    symbols = args.symbols or await database.get_market_symbols("5m")
    analyzer = ScalpAnalyzer(None)
    sample_times = list(range(start_ts, end_ts + 1, args.refresh_minutes * 60))
    start_ms = (start_ts - 250 * 300) * 1000
    end_ms = end_ts * 1000
    semaphore = asyncio.Semaphore(args.workers)

    async def audit(symbol):
        async with semaphore:
            data = series(await database.get_market_candles(symbol, "5m", start_ms, end_ms))
        counts = {"samples": 0, "active": 0, "warming": 0, "range_reject": 0, "atr_reject": 0, "both_reject": 0,
                  "validated": 0, "active_future_moved": 0, "active_future_quiet": 0,
                  "passive_future_moved": 0, "passive_future_quiet": 0,
                  "range_only_future_moved": 0, "range_only_future_quiet": 0,
                  "atr_only_future_moved": 0, "atr_only_future_quiet": 0,
                  "both_future_moved": 0, "both_future_quiet": 0}
        details = []
        for ts in sample_times:
            index = bisect.bisect_right(data["times"], ts) - 1
            if index < 0:
                counts["warming"] += 1
                continue
            result = movement_check(analyzer, data, index, args.min_range_pct, args.min_atr_pct)
            if result is None:
                counts["warming"] += 1
                continue
            counts["samples"] += 1
            is_active = result["range_ok"] and result["atr_ok"]
            if is_active:
                counts["active"] += 1
                reject_kind = None
            elif not result["range_ok"] and not result["atr_ok"]:
                counts["both_reject"] += 1
                reject_kind = "both"
            elif not result["range_ok"]:
                counts["range_reject"] += 1
                reject_kind = "range_only"
            else:
                counts["atr_reject"] += 1
                reject_kind = "atr_only"
            future_move = future_move_pct(data, index, args.validation_horizon_minutes // 5)
            if future_move is not None:
                counts["validated"] += 1
                key = ("active" if is_active else "passive") + ("_future_moved" if future_move >= args.realized_min_move_pct else "_future_quiet")
                counts[key] += 1
                if reject_kind:
                    counts[reject_kind + ("_future_moved" if future_move >= args.realized_min_move_pct else "_future_quiet")] += 1
            if args.include_samples:
                details.append({"timestamp": ts, **result, "future_move_pct": round(future_move, 4) if future_move is not None else None})
        return symbol, {**counts, "active_pct": round(counts["active"] / counts["samples"] * 100, 2) if counts["samples"] else 0.0,
                        "active_future_move_pct": round(counts["active_future_moved"] / max(1, counts["active_future_moved"] + counts["active_future_quiet"]) * 100, 2),
                        "passive_future_move_pct": round(counts["passive_future_moved"] / max(1, counts["passive_future_moved"] + counts["passive_future_quiet"]) * 100, 2),
                        "samples_detail": details}

    result = dict(await asyncio.gather(*(audit(symbol) for symbol in symbols)))
    summary = {key: sum(value[key] for value in result.values()) for key in ("samples", "active", "warming", "range_reject", "atr_reject", "both_reject", "validated", "active_future_moved", "active_future_quiet", "passive_future_moved", "passive_future_quiet", "range_only_future_moved", "range_only_future_quiet", "atr_only_future_moved", "atr_only_future_quiet", "both_future_moved", "both_future_quiet")}
    summary["active_pct"] = round(summary["active"] / summary["samples"] * 100, 2) if summary["samples"] else 0.0
    summary["active_future_move_pct"] = round(summary["active_future_moved"] / max(1, summary["active_future_moved"] + summary["active_future_quiet"]) * 100, 2)
    summary["passive_future_move_pct"] = round(summary["passive_future_moved"] / max(1, summary["passive_future_moved"] + summary["passive_future_quiet"]) * 100, 2)
    for prefix in ("range_only", "atr_only", "both"):
        summary[prefix + "_future_move_pct"] = round(summary[prefix + "_future_moved"] / max(1, summary[prefix + "_future_moved"] + summary[prefix + "_future_quiet"]) * 100, 2)
    payload = {"window": {"start": args.start_date, "end": args.end_date, "timezone": args.timezone},
               "movement_thresholds": {"min_range_15m_pct": args.min_range_pct, "min_atr_pct": args.min_atr_pct},
               "validation": {"horizon_minutes": args.validation_horizon_minutes, "realized_min_move_pct": args.realized_min_move_pct,
                              "warning": "Future movement is audit-only and is never used by the live activity filter."},
               "refresh_minutes": args.refresh_minutes, "summary": summary, "symbols": result}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[COMPLETE] result=" + str(Path(args.output).resolve()))
    print("RESULT_JSON=" + json.dumps({"symbols": len(symbols), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--refresh-minutes", type=int, default=60)
    parser.add_argument("--min-range-pct", type=float, default=config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT)
    parser.add_argument("--min-atr-pct", type=float, default=config.SYMBOL_ACTIVITY_MIN_ATR_PCT * 100)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--validation-horizon-minutes", type=int, choices=(15, 30, 60), default=30)
    parser.add_argument("--realized-min-move-pct", type=float, default=0.30,
                        help="Audit için sonraki ufuktaki gerçekleşen minimum tek-yön fiyat hareketi (yüzde)")
    parser.add_argument("--include-samples", action="store_true")
    parser.add_argument("--output", default="activity-movement-audit.json")
    args = parser.parse_args()
    if args.refresh_minutes <= 0 or args.workers < 1 or args.min_range_pct < 0 or args.min_atr_pct < 0 or args.realized_min_move_pct < 0:
        parser.error("eşikler ve worker/yenileme değerleri negatif veya sıfır olamaz")
    asyncio.run(main(args))
