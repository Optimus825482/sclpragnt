"""Audit exported paper trades and decision records without changing live policy.

Candidate filters are selected only on the chronological development portion of
the supplied trade history and then checked on the later holdout.  A retained
trade screen is not a portfolio replay: it cannot model cash freed by skipped
trades or overlapping positions, so it is only used to prioritize candidates
for a subsequent causal, fee-aware replay.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd


MIN_DEV, MIN_OOS = 20, 15


def value_at(payload, path):
    current = payload
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def metrics(frame):
    if frame.empty:
        return {"trades": 0}
    pnl = frame["pnl"].astype(float)
    gains, losses = pnl[pnl > 0].sum(), pnl[pnl <= 0].sum()
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for value in pnl:
        equity += value; peak = max(peak, equity); drawdown = max(drawdown, peak - equity)
    return {
        "trades": int(len(frame)), "wins": int((pnl > 0).sum()), "losses": int((pnl <= 0).sum()),
        "net_pnl_try": round(float(pnl.sum()), 2), "fees_try": round(float(frame["fee"].sum()), 2),
        "expectancy_try": round(float(pnl.mean()), 3),
        "profit_factor": round(float(gains / abs(losses)), 3) if losses < 0 else None,
        "max_sequential_drawdown_try": round(float(drawdown), 2),
    }


def improved(candidate, baseline, minimum):
    if candidate["trades"] < minimum or candidate["trades"] >= baseline["trades"]:
        return False
    # A filter that merely loses less than an already losing baseline is not
    # a viable causal-replay candidate.  Require an absolute positive OOS
    # result in addition to relative improvement.
    if (candidate["net_pnl_try"] <= 0 or candidate["expectancy_try"] <= 0 or
            candidate["net_pnl_try"] <= baseline["net_pnl_try"] or candidate["expectancy_try"] <= baseline["expectancy_try"]):
        return False
    baseline_pf, candidate_pf = baseline.get("profit_factor"), candidate.get("profit_factor")
    return baseline_pf is not None and candidate_pf is not None and candidate_pf > 1.0 and candidate_pf > baseline_pf


def make_condition(feature, operator, threshold, label):
    if operator == "ge":
        return label, lambda frame: frame[feature].notna() & (frame[feature] >= threshold)
    if operator == "le":
        return label, lambda frame: frame[feature].notna() & (frame[feature] <= threshold)
    return label, lambda frame: frame[feature].eq(threshold)


def candidate_conditions(development, features):
    """Quantiles are derived only from development data, then frozen for OOS."""
    conditions = []
    for feature in features:
        series = development[feature].dropna()
        if series.empty:
            continue
        # Bool values are eligibility states, not an ordinal measurement for
        # a percentile threshold.  NumPy also disallows quantile interpolation
        # on bool arrays in recent versions.
        if pd.api.types.is_bool_dtype(series):
            for value, count in series.value_counts().items():
                if count >= MIN_DEV:
                    conditions.append(make_condition(feature, "eq", value, f"{feature} == {value}"))
        elif pd.api.types.is_numeric_dtype(series):
            for quantile in (.25, .50, .75):
                threshold = float(series.quantile(quantile))
                for operator in ("ge", "le"):
                    conditions.append(make_condition(feature, operator, threshold, f"{feature} {operator} {threshold:.6g}"))
        else:
            for value, count in series.value_counts().items():
                if count >= MIN_DEV:
                    conditions.append(make_condition(feature, "eq", value, f"{feature} == {value}"))
    return conditions


def analyze_strategy(frame, feature_names):
    frame = frame.sort_values("entry_time").reset_index(drop=True)
    split = int(len(frame) * .70)
    development, oos = frame.iloc[:split].copy(), frame.iloc[split:].copy()
    dev_base, oos_base = metrics(development), metrics(oos)
    records = []
    for label, predicate in candidate_conditions(development, feature_names):
        dev_filtered, oos_filtered = development[predicate(development)], oos[predicate(oos)]
        dev_stats, oos_stats = metrics(dev_filtered), metrics(oos_filtered)
        record = {"rule": label, "development": dev_stats, "oos": oos_stats,
                  "development_improves": improved(dev_stats, dev_base, MIN_DEV),
                  "oos_improves": improved(oos_stats, oos_base, MIN_OOS)}
        records.append(record)
    accepted = [record for record in records if record["development_improves"] and record["oos_improves"]]
    accepted.sort(key=lambda record: (record["oos"]["expectancy_try"], record["oos"]["net_pnl_try"]), reverse=True)
    records.sort(key=lambda record: (record["oos_improves"], record["development_improves"], record["oos"].get("expectancy_try", -10_000)), reverse=True)
    return {"all": metrics(frame), "development_baseline": dev_base, "oos_baseline": oos_base,
            "accepted_for_causal_replay": accepted, "top_screening_results": records[:20],
            "development_window": {"start": development["entry_time"].iloc[0].isoformat() if len(development) else None, "end": development["entry_time"].iloc[-1].isoformat() if len(development) else None},
            "oos_window": {"start": oos["entry_time"].iloc[0].isoformat() if len(oos) else None, "end": oos["entry_time"].iloc[-1].isoformat() if len(oos) else None}}


def load_trades(path):
    raw = pd.read_csv(path)
    # Positional references tolerate Turkish terminal mojibake while preserving
    # the fixed export schema documented in the header.
    result = pd.DataFrame({
        "symbol": raw.iloc[:, 1].astype(str), "strategy": raw.iloc[:, 2].astype(str),
        "pnl": pd.to_numeric(raw.iloc[:, 12], errors="coerce"), "fee": pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0),
        "reason": raw.iloc[:, 17].fillna("unknown").astype(str), "entry_time": pd.to_datetime(raw.iloc[:, 18], dayfirst=True, errors="coerce"),
        "trade_id": raw.iloc[:, 21].astype(str), "context_raw": raw.iloc[:, 27],
    }).dropna(subset=["pnl", "entry_time"]).copy()
    contexts = []
    for value in result.pop("context_raw"):
        try:
            contexts.append(json.loads(value) if isinstance(value, str) else {})
        except json.JSONDecodeError:
            contexts.append({})
    paths = {
        "data_ready": "technical.data_ready", "trend_alignment": "technical.trend.alignment", "trend_adx": "technical.trend.adx.adx",
        "mfi_14": "technical.momentum.mfi_14", "rsi_14": "technical.momentum.rsi_14", "return_1h": "technical.momentum.return_1h",
        "volume_ratio_20": "technical.volume.volume_ratio_20", "bb_position": "technical.channels.bollinger.position", "bb_width_pct": "technical.channels.bollinger.width_pct",
        "atr_pct": "technical.volatility.atr_pct", "liquidity_spread_pct": "liquidity.spread", "liquidity_depth_try": "liquidity.depth_try",
        "orderflow_imbalance_proxy": "technical.liquidity.orderflow_imbalance", "signal_score": "signal_context.score",
        "signal_high_confidence": "signal_context.high_confidence", "m15_alignment": "signal_context.m15_alignment", "m30_alignment": "signal_context.m30_alignment",
        "activity_status": "symbol_activity.status", "price_action_direction": "technical.price_action.direction",
        "regime_name": "technical.methodologies.regime.name",
    }
    for name, path_name in paths.items():
        result[name] = [value_at(context, path_name) for context in contexts]
        numeric = pd.to_numeric(result[name], errors="coerce")
        if numeric.notna().sum() >= max(10, len(result) * .25):
            result[name] = numeric
    return result, raw


def signal_export_summary(path, known_trade_ids):
    signals = pd.read_csv(path)
    status, reason, trade_id = signals.iloc[:, 4], signals.iloc[:, 7], signals.iloc[:, 12]
    closed = signals[status.astype(str).eq("closed")]
    matched = closed[closed.iloc[:, 12].astype(str).isin(known_trade_ids)]
    return {"rows": int(len(signals)), "status_counts": dict(Counter(status.fillna("unknown").astype(str))),
            "strategy_counts": dict(Counter(signals.iloc[:, 2].fillna("unknown").astype(str))),
            "blocked_reason_counts": dict(Counter(reason[status.astype(str).eq("blocked")].fillna("unknown").astype(str))),
            "closed_rows": int(len(closed)), "closed_rows_matched_to_trade_export": int(len(matched)),
            "window": {"first": str(signals.iloc[:, 0].min()), "last": str(signals.iloc[:, 0].max())}}


def main(args):
    trades, raw = load_trades(args.trades)
    feature_names = [column for column in trades.columns if column not in {"symbol", "strategy", "pnl", "fee", "reason", "entry_time", "trade_id"}]
    strategies = {}
    for strategy, frame in trades.groupby("strategy"):
        if len(frame) >= MIN_DEV + MIN_OOS:
            strategies[strategy] = analyze_strategy(frame, feature_names)
    result = {"paper_only": True, "purpose": "Exported-trade loss analysis and candidate screening; no live configuration is changed.",
              "trade_export": {"path": str(args.trades), "rows_raw": int(len(raw)), "rows_analyzed": int(len(trades)),
                               "window": {"first_entry": trades["entry_time"].min().isoformat(), "last_entry": trades["entry_time"].max().isoformat()},
                               "overall": metrics(trades), "by_exit_reason": {reason: metrics(frame) for reason, frame in trades.groupby("reason")},
                               "by_strategy": {strategy: metrics(frame) for strategy, frame in trades.groupby("strategy")}},
              "signal_export": signal_export_summary(args.signals, set(trades["trade_id"])), "candidate_screening": strategies,
              "method": {"split": "first 70% of each strategy by entry timestamp is development; final 30% is chronological OOS", "selection": "one-feature quantile/category screen; must improve net PnL, expectancy and PF with >=20 development and >=15 OOS retained trades", "important_limit": "Static retained-trade screen is not a causal portfolio replay and does not account for skipped-trade capital reuse or position overlap."},
              "limitations": ["The decision export covers a much shorter window than the trade export and can corroborate matching decisions but cannot independently validate filters.", "Historical snapshot fields may be unavailable for older trades; missing fields are never treated as a pass.", "No candidate is activated by this analysis."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {strategy: {"accepted": values["accepted_for_causal_replay"], "oos_baseline": values["oos_baseline"]} for strategy, values in strategies.items()}
    print("RESULT_JSON=" + json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals", required=True)
    parser.add_argument("--trades", required=True)
    parser.add_argument("--output", required=True)
    main(parser.parse_args())
