"""OOS cohorts for causal 5/5 alignment freshness and 5m structure."""

import argparse
import json
from datetime import datetime

from scripts.research_5of5_flow_take_profit import summary


def median(values):
    values = sorted(values)
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", required=True)
    parser.add_argument("--output", default="research_5of5_structure_cohorts.json")
    args = parser.parse_args()

    sources = []
    for path in args.input:
        with open(path, encoding="utf-8") as handle:
            sources.append(json.load(handle))
    source = sources[0]
    if any(item["oos_start"] != source["oos_start"] for item in sources[1:]):
        raise ValueError("All replay inputs must use the same OOS cutoff")
    cutoff_ms = int(datetime.fromisoformat(source["oos_start"]).timestamp() * 1000)
    records = sorted((record for item in sources for record in item["records"]), key=lambda record: record["signal_time"])
    development = [record for record in records if record["signal_time"] < cutoff_ms]
    oos = [record for record in records if record["signal_time"] >= cutoff_ms]
    freshness_max_age = median([record["features"]["alignment_age_5m"] for record in development])

    rules = {
        "all_candidates": lambda record: True,
        "alignment_age_at_or_below_development_median": lambda record: record["features"]["alignment_age_5m"] <= freshness_max_age,
        "five_minute_breakout": lambda record: record["components"]["breakout"],
        "squeeze_expansion": lambda record: record["components"]["squeeze_expansion"],
        "fresh_alignment_and_breakout": lambda record: record["features"]["alignment_age_5m"] <= freshness_max_age and record["components"]["breakout"],
        "breakout_and_squeeze_expansion": lambda record: record["components"]["breakout"] and record["components"]["squeeze_expansion"],
    }
    cohorts = {}
    for name, rule in rules.items():
        cohorts[name] = {
            "development": summary([record for record in development if rule(record)]),
            "oos": summary([record for record in oos if rule(record)]),
        }
    payload = {
        "research_only": True,
        "source_replays": args.input,
        "candidate": source["candidate"],
        "oos_start": source["oos_start"],
        "method": "Alignment-age threshold is the development median and frozen before OOS; breakout and squeeze use completed 5m candles only.",
        "thresholds": {"alignment_age_5m_max": freshness_max_age},
        "cohorts": cohorts,
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
