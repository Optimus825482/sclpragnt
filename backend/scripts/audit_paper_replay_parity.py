"""Audit whether supplied paper exports can be compared to a candle replay.

This is deliberately an audit, not a backtest and it never changes runtime
configuration or opens paper positions.  It turns the decision/trade exports
into a reproducible statement of what a public-OHLCV replay can and cannot
reconstruct.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_SYMBOLS = {
    "BTCTRY", "ETHTRY", "SOLTRY", "XRPTRY", "ADATRY", "AVAXTRY", "LINKTRY",
    "NEARTRY", "APTTRY", "ARBTRY", "OPTRY", "SUITRY", "DOGETRY", "LTCTRY",
    "BNBTRY", "INJTRY", "WLDTRY", "DOTTRY",
}
REALTIME_PREFIXES = ("symbol_activity", "liquidity", "stale_", "adr_filter")
PORTFOLIO_PREFIXES = (
    "position_already_open", "remaining_cash", "insufficient_", "max_open_positions",
    "bb_mfi_pyramid", "llm_guard", "cooldown", "reentry",
)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def rows_as_dicts(rows):
    header = rows[0]
    return [dict(zip(header, row)) for row in rows[1:] if any(str(cell).strip() for cell in row)]


def count_by(rows, key):
    return dict(sorted(Counter(row.get(key, "") or "" for row in rows).items()))


def reason_class(reason):
    reason = str(reason or "")
    if reason.startswith(REALTIME_PREFIXES):
        return "requires_historical_realtime_state"
    if reason.startswith(PORTFOLIO_PREFIXES):
        return "requires_portfolio_state_and_event_order"
    if reason.startswith("bearish_reversal_mfi_unconfirmed"):
        return "replayable_if_exact_indicator_version_is_frozen"
    return "unknown_or_strategy_specific"


def parse_time(value):
    try:
        return datetime.strptime(value, "%d.%m.%Y %H:%M:%S").isoformat()
    except (TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--trades", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    decision_rows = rows_as_dicts(read_csv(args.decisions))
    trade_rows = rows_as_dicts(read_csv(args.trades))
    # Export columns are intentionally addressed by their stable positions: the
    # Turkish labels can be mojibake depending on the exporter locale.
    decisions = [
        {
            "time": row.get(list(row)[0], ""), "symbol": row.get(list(row)[1], ""),
            "strategy": row.get(list(row)[2], ""), "action": row.get(list(row)[3], ""),
            "reason": row.get(list(row)[7], ""), "trade_id": row.get(list(row)[12], ""),
            "revision": row.get(list(row)[13], ""),
        }
        for row in decision_rows
    ]
    trades = [
        {
            "symbol": row.get(list(row)[1], ""), "strategy": row.get(list(row)[2], ""),
            "trade_id": row.get(list(row)[21], ""), "revision": row.get(list(row)[22], ""),
        }
        for row in trade_rows
    ]

    decision_symbols = {item["symbol"] for item in decisions if item["symbol"]}
    bb_symbols = {item["symbol"] for item in decisions if item["strategy"] == "BB + MFI Mean Reversion"}
    blocked = [item for item in decisions if item["action"] == "BUY_BLOCKED"]
    blocked_by_class = Counter(reason_class(item["reason"]) for item in blocked)
    blocked_by_reason = Counter(item["reason"] for item in blocked)
    decision_trade_ids = {item["trade_id"] for item in decisions if item["trade_id"]}
    trade_ids = {item["trade_id"] for item in trades if item["trade_id"]}
    timestamps = sorted(value for value in (parse_time(item["time"]) for item in decisions) if value)

    output = {
        "audit_type": "paper_export_vs_public_candle_replay_contract",
        "paper_only": True,
        "inputs": {"decisions": str(Path(args.decisions)), "trades": str(Path(args.trades))},
        "decision_export": {
            "rows": len(decisions), "time_range_local_export_format": {"start": timestamps[0] if timestamps else None, "end": timestamps[-1] if timestamps else None},
            "by_strategy": count_by(decisions, "strategy"), "by_action": count_by(decisions, "action"),
            "strategy_revisions": count_by(decisions, "revision"),
            "unique_symbols": len(decision_symbols), "symbols_outside_static_18": sorted(decision_symbols - DEFAULT_SYMBOLS),
            "bb_mfi_unique_symbols": len(bb_symbols), "bb_mfi_symbols_outside_static_18": sorted(bb_symbols - DEFAULT_SYMBOLS),
            "blocked_by_contract_class": dict(sorted(blocked_by_class.items())),
            "top_blocked_reasons": [{"reason": reason, "count": count} for reason, count in blocked_by_reason.most_common(20)],
        },
        "trade_export": {
            "rows": len(trades), "by_strategy": count_by(trades, "strategy"), "strategy_revisions": count_by(trades, "revision"),
            "unique_symbols": len({item["symbol"] for item in trades if item["symbol"]}),
        },
        "join_check": {
            "decision_rows_with_trade_id": len(decision_trade_ids), "trade_rows_with_trade_id": len(trade_ids),
            "matching_trade_ids": len(decision_trade_ids & trade_ids),
            "note": "Decision export is event-level and incomplete for no-signal scans; a non-match is not a trading error.",
        },
        "verdict": {
            "status": "not_comparable_to_prior_static_18_bb_only_replay",
            "why": [
                "The export contains a dynamic universe beyond the static 18-symbol replay universe.",
                "BB-MFI and PUMP_MONITOR both produced decisions and share the paper portfolio.",
                "Most blocked decisions require historical real-time activity/liquidity state or event-ordered portfolio state, neither present in public OHLCV.",
                "The export does not include every NO_SIGNAL scan, so recall/false-positive parity cannot be measured from this file alone.",
            ],
            "prior_replay_interpretation": "Source-aligned research only; it must not be reported as the actual paper bot's PnL or decision parity.",
            "next_comparable_contract": [
                "Persist the active symbol universe and effective settings/revision at every M5 scan.",
                "Persist all evaluated decisions including NO_SIGNAL, with closed-candle timestamp and strategy identifier.",
                "Persist historical M1 activity and executable liquidity/depth snapshots, or explicitly disable these gates in both paper and replay.",
                "Replay BB-MFI and Pump Monitor in original event order against one shared cash/position ledger.",
                "Match replay decisions to exported decision IDs before interpreting aggregate PnL.",
            ],
        },
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(destination), "status": output["verdict"]["status"], "rows": len(decisions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
