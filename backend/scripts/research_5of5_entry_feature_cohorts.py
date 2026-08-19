"""Development-threshold OOS cohorts for measurable entry conditions."""

import argparse
import json
from datetime import datetime

from scripts.research_5of5_flow_take_profit import summary


FEATURES = ("flow_min", "m5_atr_pct", "vwap_extension_atr", "m5_bb_width_pct")


def median(values):
    values = sorted(values); middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True); parser.add_argument("--output", default="research_5of5_entry_feature_cohorts.json")
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as handle: source = json.load(handle)
    cutoff_ms = int(datetime.fromisoformat(source["oos_start"]).timestamp() * 1000)
    development = [record for record in source["records"] if record["signal_time"] < cutoff_ms]
    oos = [record for record in source["records"] if record["signal_time"] >= cutoff_ms]
    thresholds = {name: median([record["features"][name] for record in development if record.get("features", {}).get(name) is not None]) for name in FEATURES}
    rules = {
        "all_candidates": lambda record: True,
        "flow_at_or_above_development_median": lambda record: record["features"]["flow_min"] >= thresholds["flow_min"],
        "atr_at_or_below_development_median": lambda record: record["features"]["m5_atr_pct"] <= thresholds["m5_atr_pct"],
        "vwap_extension_at_or_below_development_median": lambda record: record["features"]["vwap_extension_atr"] <= thresholds["vwap_extension_atr"],
        "bb_width_at_or_below_development_median": lambda record: record["features"]["m5_bb_width_pct"] <= thresholds["m5_bb_width_pct"],
        "flow_high_and_atr_moderate": lambda record: record["features"]["flow_min"] >= thresholds["flow_min"] and record["features"]["m5_atr_pct"] <= thresholds["m5_atr_pct"],
    }
    cohorts = {}
    for name, rule in rules.items():
        selected_development = [record for record in development if rule(record)]
        selected_oos = [record for record in oos if rule(record)]
        cohorts[name] = {"development": summary(selected_development), "oos": summary(selected_oos)}
    payload = {"research_only": True, "source_replay": args.input, "candidate": source["candidate"], "oos_start": source["oos_start"],
               "method": "thresholds are medians calculated only from development candidates and frozen for OOS", "thresholds": thresholds, "cohorts": cohorts}
    with open(args.output, "w", encoding="utf-8") as handle: json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
