"""Chronological train/validation/test check for enriched entry patterns."""
import argparse
import json
import math
from pathlib import Path


def stats(rows, name="all"):
    pnl = sum(float(row.get("pnl") or 0) for row in rows)
    wins = sum(float(row.get("pnl") or 0) > 0 for row in rows)
    gains = sum(float(row.get("pnl") or 0) for row in rows if float(row.get("pnl") or 0) > 0)
    losses = abs(sum(float(row.get("pnl") or 0) for row in rows if float(row.get("pnl") or 0) <= 0))
    return {"rule": name, "n": len(rows), "wins": wins, "losses": len(rows) - wins,
            "win_rate_pct": round(wins / len(rows) * 100, 4) if rows else None,
            "net_pnl_try": round(pnl, 6), "mean_pnl_try": round(pnl / len(rows), 6) if rows else None,
            "profit_factor": round(gains / losses, 6) if losses else None}


def predicates():
    return {
        "mtf_alignment_score_ge_1": lambda r: (r.get("mtf_alignment_score") or 0) >= 1,
        "mtf_bullish_count_ge_3": lambda r: (r.get("mtf_bullish_count") or 0) >= 3,
        "h1_h4_bullish": lambda r: r.get("1h_alignment") == "bullish" and r.get("4h_alignment") == "bullish",
        "m5_atr_expansion_ge_1": lambda r: (r.get("5m_atr_expansion_ratio_5") or 0) >= 1,
        "m5_rejection_candle": lambda r: (r.get("5m_lower_wick_ratio") or 0) >= 0.30 and (r.get("5m_close_position") or 0) >= 0.55,
        "m5_adx_ge_35_and_di_positive": lambda r: (r.get("5m_adx") or 0) >= 35 and (r.get("5m_di_gap") or 0) > 0,
    }


def main(args):
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    rows = sorted(payload.get("trade_rows") or [], key=lambda row: float(row.get("entry_time") or 0))
    if len(rows) < 30:
        raise SystemExit("En az 30 enriched işlem gerekiyor")
    n = len(rows); train_end = int(n * 0.60); validation_end = int(n * 0.80)
    splits = {"train": rows[:train_end], "validation": rows[train_end:validation_end], "test": rows[validation_end:]}
    rules = predicates()
    all_results = {}
    for name, predicate in rules.items():
        all_results[name] = {split: stats([row for row in part if predicate(row)], name) for split, part in splits.items()}
    baseline = {split: stats(part, "baseline_all_trades") for split, part in splits.items()}
    eligible = [(name, result["train"]) for name, result in all_results.items() if result["train"]["n"] >= args.min_train_trades and result["train"]["profit_factor"] is not None]
    selected = sorted(eligible, key=lambda item: (item[1]["profit_factor"], item[1]["mean_pnl_try"]), reverse=True)[:args.select_top]
    selected_names = [name for name, _ in selected]
    result = {"paper_only": True, "input": str(Path(args.input).resolve()), "total_trades": n,
              "split_sizes": {name: len(part) for name, part in splits.items()}, "split_policy": "chronological 60/20/20",
              "baseline": baseline, "rules": all_results, "selected_on_train": selected_names,
              "selected_rule_results": {name: all_results[name] for name in selected_names},
              "selection_policy": f"top {args.select_top} train profit factor with minimum {args.min_train_trades} trades",
              "limitations": ["Only 206 historical trades; validation/test intervals are small.", "Rules are trade-level filters, not standalone wallet replay results.", "No historical spread/depth/orderflow fields in the backfill snapshots."]}
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {"split_sizes": result["split_sizes"], "baseline": baseline, "selected_on_train": selected_names,
               "selected_rule_results": result["selected_rule_results"]}
    print(json.dumps({"output": str(output.resolve()), **compact}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="trade-entry-pattern-analysis-enriched.json")
    parser.add_argument("--output", default="trade-entry-pattern-validation.json")
    parser.add_argument("--min-train-trades", type=int, default=10)
    parser.add_argument("--select-top", type=int, default=2)
    args = parser.parse_args()
    if args.min_train_trades < 5 or args.select_top < 1:
        parser.error("minimums invalid")
    main(args)
