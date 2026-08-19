"""Leakage-free symbol cohort evaluation from a completed causal active-exit replay."""

import argparse
import json
from collections import Counter


def median(values):
    values = sorted(values); middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def stats(records):
    if not records:
        return {"n": 0}
    net = [record["result"]["net_pct"] for record in records]
    return {"n": len(records), "mean_net_pct": round(sum(net) / len(net), 4), "median_net_pct": round(median(net), 4),
            "net_positive_rate": round(sum(value > 0 for value in net) / len(net), 4),
            "exit_reasons": dict(sorted(Counter(record["result"]["exit_reason"] for record in records).items()))}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True); parser.add_argument("--output", default="research_5of5_symbol_cohorts.json")
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as handle: source = json.load(handle)
    cutoff = source["oos_start"]
    # ISO strings are chronological when they share the same UTC offset.
    records = source["records"]
    # Use the supplied partition membership by reconstructing the epoch cutoff.
    from datetime import datetime
    cutoff_ms = int(datetime.fromisoformat(cutoff).timestamp() * 1000)
    development = [record for record in records if record["signal_time"] < cutoff_ms]
    oos = [record for record in records if record["signal_time"] >= cutoff_ms]
    symbols = sorted({record["symbol"] for record in records})
    development_by_symbol = {symbol: stats([record for record in development if record["symbol"] == symbol]) for symbol in symbols}
    rules = {
        "all_symbols": lambda value: value["n"] > 0,
        "minimum_sample_5": lambda value: value["n"] >= 5,
        "development_mean_positive_min5": lambda value: value["n"] >= 5 and value["mean_net_pct"] > 0,
        "development_positive_rate_60_min5": lambda value: value["n"] >= 5 and value["net_positive_rate"] >= .60,
        "provisional_mean_positive_min3": lambda value: value["n"] >= 3 and value["mean_net_pct"] > 0,
    }
    cohorts = {}
    for name, rule in rules.items():
        selected = [symbol for symbol, value in development_by_symbol.items() if rule(value)]
        cohorts[name] = {"selection_rule": name, "selected_from_development_only": selected,
                         "development": stats([record for record in development if record["symbol"] in selected]),
                         "oos": stats([record for record in oos if record["symbol"] in selected])}
    payload = {"research_only": True, "source_replay": args.input, "candidate": source["candidate"], "oos_start": cutoff,
               "method": "symbols are selected only from development performance, then frozen for OOS evaluation", "development_by_symbol": development_by_symbol,
               "cohorts": cohorts}
    with open(args.output, "w", encoding="utf-8") as handle: json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload["cohorts"], ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
