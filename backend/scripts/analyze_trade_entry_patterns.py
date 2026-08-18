"""Exploratory, fee-aware comparison of enriched entry snapshots.

Paper-only: reads closed trades and their causal entry_context snapshots;
does not change balances or place orders. Thresholds are descriptive, not
production strategy rules.
"""
import argparse
import asyncio
import json
import math
import statistics
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database


TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")


def numeric(values):
    return [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]


def summary(rows, field):
    wins = numeric([row[field] for row in rows if row["win"]])
    losses = numeric([row[field] for row in rows if not row["win"]])
    result = {}
    for label, values in (("wins", wins), ("losses", losses)):
        result[label] = {"n": len(values), "mean": round(statistics.mean(values), 6) if values else None,
                         "median": round(statistics.median(values), 6) if values else None}
    result["median_delta_wins_minus_losses"] = round(result["wins"]["median"] - result["losses"]["median"], 6) if wins and losses else None
    return result


def rule_stats(trades, name, predicate):
    selected = [row for row in trades if predicate(row)]
    pnl = sum(row["pnl"] for row in selected)
    wins = sum(row["win"] for row in selected)
    return {"rule": name, "n": len(selected), "wins": wins, "win_rate_pct": round(wins / len(selected) * 100, 4) if selected else None,
            "net_pnl_try": round(pnl, 6), "mean_pnl_try": round(pnl / len(selected), 6) if selected else None}


async def main(args):
    await database.init_db()
    raw = await database.get_trades(None)
    trades = []
    for trade in raw:
        pnl = float(trade.get("pnl") or 0)
        context = database._json_value(trade.get("entry_context"), {}) if isinstance(trade.get("entry_context"), str) else (trade.get("entry_context") or {})
        technical = context.get("technical") or {}
        snapshots = technical.get("mtf_snapshots") or {}
        derived = technical.get("derived_entry_features") or {}
        if not all(tf in snapshots for tf in TIMEFRAMES):
            continue
        row = {"trade_id": trade.get("trade_id"), "symbol": trade.get("symbol"), "entry_time": trade.get("entry_time"), "pnl": pnl, "win": pnl > 0,
               "mtf_alignment_score": derived.get("mtf_alignment_score"), "mtf_bullish_count": derived.get("mtf_bullish_count"),
               "mtf_bearish_count": derived.get("mtf_bearish_count"), "mtf_mixed_count": derived.get("mtf_mixed_count")}
        for tf in TIMEFRAMES:
            snap = snapshots[tf] or {}
            feat = snap.get("derived_entry_features") or {}
            trend = snap.get("trend") or {}
            adx = trend.get("adx") or {}
            bb = (snap.get("channels") or {}).get("bollinger") or {}
            vol = snap.get("volatility") or {}
            row[f"{tf}_alignment"] = trend.get("alignment")
            row[f"{tf}_adx"] = feat.get("adx", adx.get("adx"))
            row[f"{tf}_di_gap"] = feat.get("adx_di_gap")
            row[f"{tf}_ema20_slope_3_pct"] = feat.get("ema20_slope_3_pct")
            row[f"{tf}_atr_expansion_ratio_5"] = feat.get("atr_expansion_ratio_5")
            row[f"{tf}_bb_width_pct"] = feat.get("bb_width_pct", bb.get("width_pct"))
            row[f"{tf}_bb_position"] = bb.get("position")
            row[f"{tf}_lower_wick_ratio"] = feat.get("lower_wick_ratio")
            row[f"{tf}_close_position"] = feat.get("close_position")
            row[f"{tf}_volume_ratio_20"] = (snap.get("volume") or {}).get("volume_ratio_20")
            row[f"{tf}_atr_pct"] = vol.get("atr_pct")
        trades.append(row)

    numeric_fields = [key for key in trades[0] if key not in {"trade_id", "symbol", "entry_time", "pnl", "win"} and not key.endswith("_alignment")] if trades else []
    comparisons = {field: summary(trades, field) for field in numeric_fields}
    patterns = [
        rule_stats(trades, "MTF alignment score >= 1", lambda r: (r["mtf_alignment_score"] or 0) >= 1),
        rule_stats(trades, "MTF bullish count >= 3", lambda r: (r["mtf_bullish_count"] or 0) >= 3),
        rule_stats(trades, "H1/H4 bullish", lambda r: r["1h_alignment"] == "bullish" and r["4h_alignment"] == "bullish"),
        rule_stats(trades, "M5 positive DI gap and EMA slope", lambda r: (r["5m_di_gap"] or 0) > 0 and (r["5m_ema20_slope_3_pct"] or 0) > 0),
        rule_stats(trades, "M5 ATR expansion >= 1.0", lambda r: (r["5m_atr_expansion_ratio_5"] or 0) >= 1.0),
        rule_stats(trades, "M5 rejection candle", lambda r: (r["5m_lower_wick_ratio"] or 0) >= 0.30 and (r["5m_close_position"] or 0) >= 0.55),
        rule_stats(trades, "Combined quality candidate", lambda r: (r["mtf_alignment_score"] or 0) >= 1 and (r["5m_di_gap"] or 0) > 0 and (r["5m_lower_wick_ratio"] or 0) >= 0.30),
    ]
    result = {"paper_only": True, "source": "local PostgreSQL trades.entry_context", "trade_count_total": len(raw),
              "trade_count_with_all_mtf": len(trades), "wins": sum(row["win"] for row in trades),
              "losses": sum(not row["win"] for row in trades), "comparisons": comparisons, "patterns": patterns,
              "limitations": ["Exploratory thresholds use the same 206 trades and require out-of-sample confirmation.", "Historical spread/depth/orderflow are unavailable in backfill snapshots."],
              "features": numeric_fields, "trade_rows": trades}
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output.resolve()), "trade_count_total": len(raw), "trade_count_with_all_mtf": len(trades), "patterns": patterns}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="trade-entry-pattern-analysis.json")
    asyncio.run(main(parser.parse_args()))
