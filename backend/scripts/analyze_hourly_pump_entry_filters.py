"""Development-only ablation of one extra gate on the score>=3 pump alarm."""
import argparse
import json
from pathlib import Path


def metric(point, timeframe, name, fallback=None):
    value = point.get("snapshots", {}).get(timeframe, {}).get("key_metrics", {}).get(name, fallback)
    return fallback if value is None else value


def positive(value):
    return isinstance(value, (int, float)) and value > 0


FILTERS = {
    "m5_price_above_ema9": lambda p: positive(metric(p, "5m", "price_vs_ema9_pct")),
    "m5_price_above_vwap": lambda p: positive(metric(p, "5m", "price_vs_vwap_pct")),
    "m5_plus_di_above_minus_di": lambda p: (metric(p, "5m", "plus_di", -1) > metric(p, "5m", "minus_di", 0)),
    "m5_macd_histogram_positive": lambda p: positive(metric(p, "5m", "macd_histogram")),
    "m5_volume_ratio_ge_1": lambda p: metric(p, "5m", "volume_ratio_20", -1) >= 1,
    "m5_volume_ratio_ge_1_5": lambda p: metric(p, "5m", "volume_ratio_20", -1) >= 1.5,
    "m5_adx_ge_25": lambda p: metric(p, "5m", "adx_14", -1) >= 25,
    "m15_bullish_alignment": lambda p: metric(p, "15m", "trend_alignment") == "bullish",
    "m30_bullish_alignment": lambda p: metric(p, "30m", "trend_alignment") == "bullish",
    "m15_bullish_and_m5_volume_ge_1": lambda p: metric(p, "15m", "trend_alignment") == "bullish" and metric(p, "5m", "volume_ratio_20", -1) >= 1,
    "m30_bullish_and_m5_volume_ge_1": lambda p: metric(p, "30m", "trend_alignment") == "bullish" and metric(p, "5m", "volume_ratio_20", -1) >= 1,
    "m15_and_m30_bullish": lambda p: metric(p, "15m", "trend_alignment") == "bullish" and metric(p, "30m", "trend_alignment") == "bullish",
}


def summary(rows):
    pnl = [row["result"]["net_pnl_try"] for row in rows]
    returns = [row["result"]["net_return_pct"] for row in rows]
    return {"n": len(rows), "net_pnl_try": round(sum(pnl), 2),
            "expectancy_pct_per_trade": round(sum(returns) / len(returns), 4) if returns else 0,
            "positive_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else 0}


def main(args):
    context = json.loads(Path(args.context).read_text(encoding="utf-8"))
    replay = json.loads(Path(args.replay).read_text(encoding="utf-8"))
    cutoff = int(replay["sample"]["chronological_cutoff_ms"])
    points = {}
    for item in context["events"]:
        event = item["event"]
        for label, values in (("pump_event", [item.get("event_point")]), ("quiet_control", item.get("control_points") or [item.get("control_point")])):
            for point in values:
                if point:
                    points[(event["symbol"], int(point["time_ms"]), int(event["hour_start_ms"]), label)] = point
    rows = []
    for row in replay["records"][args.model]:
        if sum(bool(value) for value in row["conditions"].values()) < 3:
            continue
        point = points.get((row["symbol"], int(row["signal_time"]), int(row["reference_event_time"]), row["label"]))
        if point:
            rows.append({**row, "point": point})
    result = {"research_only": True, "base_rule": "frozen score >=3 plus one independently tested extra gate",
              "selection": "Choose only among filters that retain >=70% of development pump rows and remove >=20% of development quiet controls; rank by development net PnL, then control removal.",
              "inputs": {"context": args.context, "replay": args.replay, "model": args.model, "base_rows": len(rows)}, "filters": {}}
    development_rank = []
    for name, predicate in FILTERS.items():
        record = {}
        for partition, final in (("development", False), ("final_chronological", True)):
            selected = [row for row in rows if (int(row["reference_event_time"]) >= cutoff) == final and predicate(row["point"])]
            record[partition] = {"all": summary(selected), "pump_events": summary([row for row in selected if row["label"] == "pump_event"]),
                                 "quiet_controls": summary([row for row in selected if row["label"] == "quiet_control"])}
        base_dev = [row for row in rows if int(row["reference_event_time"]) < cutoff]
        base_pump = sum(row["label"] == "pump_event" for row in base_dev)
        base_control = sum(row["label"] == "quiet_control" for row in base_dev)
        pump_recall = record["development"]["pump_events"]["n"] / base_pump if base_pump else 0
        control_removed = 1 - record["development"]["quiet_controls"]["n"] / base_control if base_control else 0
        record["development_gate_metrics"] = {"pump_recall": round(pump_recall, 4), "control_removed": round(control_removed, 4),
                                                "eligible": pump_recall >= .70 and control_removed >= .20}
        result["filters"][name] = record
        if record["development_gate_metrics"]["eligible"]:
            development_rank.append((record["development"]["all"]["net_pnl_try"], control_removed, name))
    result["development_selected_filter"] = max(development_rank)[2] if development_rank else None
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": result["development_selected_filter"], "filters": {name: data["development_gate_metrics"] for name, data in result["filters"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default="hourly-pump-context-60d-controls12.json")
    parser.add_argument("--replay", default="hourly-pump-exit-replay-60d-controls12.json")
    parser.add_argument("--output", default="hourly-pump-entry-filter-ablation-60d.json")
    parser.add_argument("--model", default="atr_trailing_runner")
    main(parser.parse_args())
