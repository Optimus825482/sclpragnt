"""Portfolio-capacity replay over already fee-aware hourly-pump exit records.

The input is produced by replay_hourly_pump_exit_models.py.  It applies a
fixed TRY order size, cash accounting, and a maximum-open-position limit
without creating paper or real orders.
"""
import argparse
import json
from pathlib import Path

from app.config import config


def simulate(records, max_positions, initial_cash, order_value):
    cash = initial_cash
    open_positions, closed, blocked = [], [], []
    peak_cash, max_liquidity_drawdown = cash, 0.0
    for record in sorted(records, key=lambda row: (row["result"]["entry_time"], row["symbol"])):
        entry_time = record["result"]["entry_time"]
        # Capital becomes available only after the M1 bar containing the exit.
        due = [position for position in open_positions if position["exit_time"] <= entry_time]
        for position in due:
            cash += position["return_cash"]
            closed.append(position)
            open_positions.remove(position)
        peak_cash = max(peak_cash, cash)
        required = order_value * (1 + config.COMMISSION_PCT)
        if max_positions and len(open_positions) >= max_positions:
            blocked.append({"signal_time": entry_time, "symbol": record["symbol"], "reason": "max_open_positions"})
            continue
        if cash < required:
            blocked.append({"signal_time": entry_time, "symbol": record["symbol"], "reason": "insufficient_cash"})
            continue
        cash -= required
        result = record["result"]
        open_positions.append({"symbol": record["symbol"], "label": record["label"], "entry_time": entry_time,
                               "exit_time": result["exit_time"], "return_cash": required + result["net_pnl_try"],
                               "net_pnl_try": result["net_pnl_try"], "exit_reason": result["exit_reason"]})
        # This is cash availability, not an equity drawdown: the compact input
        # has each trade's extrema but not a synchronized M1 portfolio curve.
        max_liquidity_drawdown = min(max_liquidity_drawdown, (cash / peak_cash - 1) * 100 if peak_cash else 0)
    for position in sorted(open_positions, key=lambda row: row["exit_time"]):
        cash += position["return_cash"]
        closed.append(position)
    wins = [position for position in closed if position["net_pnl_try"] > 0]
    losses = [position for position in closed if position["net_pnl_try"] <= 0]
    return {"initial_cash_try": initial_cash, "final_cash_try": round(cash, 2), "net_pnl_try": round(cash - initial_cash, 2),
            "net_pnl_pct": round((cash / initial_cash - 1) * 100, 4), "closed_trades": len(closed),
            "wins": len(wins), "losses": len(losses), "win_rate_pct": round(len(wins) / len(closed) * 100, 2) if closed else 0,
            "profit_factor": round(sum(p["net_pnl_try"] for p in wins) / abs(sum(p["net_pnl_try"] for p in losses)), 4) if losses else None,
            "max_liquidity_drawdown_pct": round(max_liquidity_drawdown, 4), "blocked": len(blocked),
            "blocked_reasons": {reason: sum(item["reason"] == reason for item in blocked) for reason in sorted({item["reason"] for item in blocked})},
            "executed_by_label": {label: sum(item["label"] == label for item in closed) for label in ("pump_event", "quiet_control")},
            "trades": closed, "blocked_signals": blocked}


def main(args):
    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records = source["records"][args.model]
    cutoff = int(source["sample"]["chronological_cutoff_ms"])
    payload = {"research_only": True, "source_replay": args.input, "model": args.model,
               "assumptions": {"initial_cash_try": args.initial_cash, "order_value_try": args.order_value,
                               "commission_pct_each_side": config.COMMISSION_PCT,
                               "capacity": "0 means unlimited, matching the configured MAX_OPEN_POSITIONS default"},
               "partitions": {}}
    for name, rows in {"development": [r for r in records if r["reference_event_time"] < cutoff],
                       "final_chronological": [r for r in records if r["reference_event_time"] >= cutoff]}.items():
        payload["partitions"][name] = {str(limit): simulate(rows, limit, args.initial_cash, args.order_value) for limit in args.max_positions}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({part: {limit: {key: value[key] for key in ("net_pnl_try", "net_pnl_pct", "closed_trades", "blocked", "max_liquidity_drawdown_pct")} for limit, value in values.items()} for part, values in payload["partitions"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="hourly-pump-exit-replay-60d-controls4.json")
    parser.add_argument("--output", default="hourly-pump-portfolio-replay-60d-controls4.json")
    parser.add_argument("--model", default="atr_trailing_runner")
    parser.add_argument("--initial-cash", type=float, default=config.INITIAL_BALANCE_TRY)
    parser.add_argument("--order-value", type=float, default=1_000.0)
    parser.add_argument("--max-positions", type=int, nargs="+", default=[0, 1, 3])
    main(parser.parse_args())
