"""Chronological, research-only evaluation of the hourly-pump feature dataset.

This script never generates orders.  It chooses a compact score on the earliest
70% of H1 +20% events and evaluates that frozen score on the final 30%.
"""
import argparse
import glob
import json
from pathlib import Path


FAMILIES = {
    "ema9": [("m5_price_above_ema9", lambda r: metric(r, "5m", "price_vs_ema9_pct") > 0)],
    "vwap": [("m5_price_above_vwap", lambda r: metric(r, "5m", "price_vs_vwap_pct") > 0)],
    "rsi": [(f"m5_rsi_ge_{x}", lambda r, x=x: metric(r, "5m", "rsi_14") >= x) for x in (55, 60, 65)],
    "mfi": [(f"m5_mfi_ge_{x}", lambda r, x=x: metric(r, "5m", "mfi_14") >= x) for x in (45, 50, 55)],
    "di": [("m5_plus_di_above_minus_di", lambda r: metric(r, "5m", "plus_di") > metric(r, "5m", "minus_di"))],
    "bb": [(f"m5_bb_position_ge_{x:.2f}", lambda r, x=x: metric(r, "5m", "bb_position") >= x) for x in (.50, .65, .80)],
    "context": [("m15_or_m30_continuation", lambda r: bool(r["flags"].get("continuation_context"))),
                ("m30_reversal", lambda r: bool(r["flags"].get("reversal_context")))],
}


def metric(row, timeframe, key):
    value = row["snapshots"].get(timeframe, {}).get("key_metrics", {}).get(key)
    return float(value) if value is not None else float("-inf")


def score_condition(condition, positives, negatives):
    _, predicate = condition
    tp = sum(predicate(row) for row in positives)
    fp = sum(predicate(row) for row in negatives)
    tpr = tp / len(positives) if positives else 0
    fpr = fp / len(negatives) if negatives else 0
    return {"name": condition[0], "tp": tp, "fp": fp, "tpr": tpr, "fpr": fpr, "j": tpr - fpr, "predicate": predicate}


def evaluate_rule(conditions, minimum_score, positives, negatives):
    def hit(row):
        return sum(item["predicate"](row) for item in conditions) >= minimum_score
    tp, fp = sum(hit(row) for row in positives), sum(hit(row) for row in negatives)
    fn, tn = len(positives) - tp, len(negatives) - fp
    tpr = tp / len(positives) if positives else 0
    fpr = fp / len(negatives) if negatives else 0
    precision = tp / (tp + fp) if tp + fp else 0
    return {"conditions": [item["name"] for item in conditions], "minimum_score": minimum_score,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn, "recall": tpr, "false_positive_rate": fpr,
            "precision": precision, "youden_j": tpr - fpr}


def point_rows(events, point_name):
    return [item[point_name] for item in events if item.get(point_name)]


def main(args):
    files = sorted(glob.glob(args.inputs))
    if not files:
        raise SystemExit(f"No input matches: {args.inputs}")
    events = []
    for filename in files:
        events.extend(json.loads(Path(filename).read_text(encoding="utf-8"))["events"])
    events.sort(key=lambda row: row["event"]["hour_start_ms"])
    split = int(len(events) * args.train_fraction)
    train, final = events[:split], events[split:]
    train_events, train_controls = point_rows(train, "event_point"), point_rows(train, "control_point")
    final_events, final_controls = point_rows(final, "event_point"), point_rows(final, "control_point")

    # Select at most one condition per family using development data only.
    selected = []
    family_scores = {}
    for family, candidates in FAMILIES.items():
        best = max((score_condition(c, train_events, train_controls) for c in candidates), key=lambda item: (item["j"], item["tpr"], -item["fpr"]))
        family_scores[family] = {key: value for key, value in best.items() if key != "predicate"}
        if best["j"] > 0:
            selected.append(best)
    selected.sort(key=lambda item: item["j"], reverse=True)
    selected = selected[:args.max_conditions]

    candidates = [evaluate_rule(selected, k, train_events, train_controls) for k in range(1, len(selected) + 1)]
    eligible = [item for item in candidates if item["false_positive_rate"] <= args.max_fpr]
    # When the caller supplies a noise ceiling, prefer the most discriminative
    # score under that ceiling.  This is selected on development data only.
    chosen = max(eligible or candidates, key=lambda item: (item["youden_j"], item["precision"], item["recall"]))
    frozen = [item for item in selected if item["name"] in chosen["conditions"]]
    final_result = evaluate_rule(frozen, chosen["minimum_score"], final_events, final_controls)

    payload = {
        "research_only": True,
        "purpose": "Retrospective chronological walk-forward screen; not a trading backtest and not eligible for live activation.",
        "data": {"files": files, "events": len(events), "train_events": len(train_events), "train_controls": len(train_controls),
                 "final_events": len(final_events), "final_controls": len(final_controls), "train_fraction": args.train_fraction},
        "method": "Each threshold is selected on the chronological development slice only. One condition per feature family, maximum N conditions, a development false-positive ceiling, and the score cutoff are then frozen before evaluating the final slice.",
        "development_max_false_positive_rate": args.max_fpr,
        "development_family_selection": family_scores,
        "development_rule_grid": candidates,
        "frozen_rule": {key: value for key, value in chosen.items() if key not in {"tp", "fp", "fn", "tn", "recall", "false_positive_rate", "precision", "youden_j"}},
        "development_result": chosen,
        "final_chronological_result": final_result,
        "limitations": [
            "The original feature ideas came from an earlier short exploratory sample, so the final slice is chronological but not fully blind.",
            "Controls are quiet same-symbol H1 candles, not all possible market states.",
            "This detects H1 +20% events; it does not model execution, spreads, slippage, fees, stops, take-profit, or PnL.",
        ],
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"frozen_rule": payload["frozen_rule"], "development": chosen, "final": final_result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", default="hourly-pump-context-60d-batch-*.json")
    parser.add_argument("--output", default="hourly-pump-walk-forward-60d.json")
    parser.add_argument("--train-fraction", type=float, default=.70)
    parser.add_argument("--max-conditions", type=int, default=4)
    parser.add_argument("--max-fpr", type=float, default=.20)
    main(parser.parse_args())
