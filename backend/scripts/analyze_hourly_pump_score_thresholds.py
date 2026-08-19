"""Audit score-3 versus score-4 selection using an existing exit replay."""
import argparse
import json
from pathlib import Path


def summary(rows):
    values = [row["result"]["net_return_pct"] for row in rows]
    pnl = [row["result"]["net_pnl_try"] for row in rows]
    return {"n": len(rows), "net_pnl_try": round(sum(pnl), 2),
            "expectancy_pct_per_trade": round(sum(values) / len(values), 4) if values else 0,
            "positive_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else 0}


def main(args):
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    cutoff = int(data["sample"]["chronological_cutoff_ms"])
    records = data["records"][args.model]
    result = {"research_only": True, "input": args.input, "model": args.model,
              "rule": "Count true conditions in the frozen four-condition alarm; no threshold is changed.", "partitions": {}}
    for name, final in (("development", False), ("final_chronological", True)):
        result["partitions"][name] = {}
        for minimum in args.minimum_scores:
            selected = [row for row in records if sum(bool(value) for value in row["conditions"].values()) >= minimum and ((int(row["reference_event_time"]) >= cutoff) == final)]
            result["partitions"][name][str(minimum)] = {"all": summary(selected),
                "pump_events": summary([row for row in selected if row["label"] == "pump_event"]),
                "quiet_controls": summary([row for row in selected if row["label"] == "quiet_control"])}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["partitions"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="hourly-pump-exit-replay-60d-controls12.json")
    parser.add_argument("--output", default="hourly-pump-score-thresholds-60d-controls12.json")
    parser.add_argument("--model", default="atr_trailing_runner")
    parser.add_argument("--minimum-scores", type=int, nargs="+", default=[3, 4])
    main(parser.parse_args())
