"""Bounded, auditable learning summaries from closed paper trades.

This module never mutates strategy parameters or authorizes a trade. It only
turns historical outcomes into context that the LLM can inspect.
"""

from __future__ import annotations

from collections import defaultdict


def build_learning_context(trades: list[dict], limit: int = 200) -> dict:
    recent = list(trades or [])[:max(1, min(int(limit), 500))]
    groups: dict[str, list[dict]] = defaultdict(list)
    for trade in recent:
        groups[str(trade.get("strategy") or "UNKNOWN")].append(trade)

    by_strategy = []
    for strategy, rows in groups.items():
        pnls = [float(row.get("pnl") or 0) for row in rows]
        wins = sum(1 for pnl in pnls if pnl > 0)
        by_strategy.append({
            "strategy": strategy,
            "trades": len(rows),
            "net_pnl": round(sum(pnls), 4),
            "win_rate_pct": round(wins / len(rows) * 100, 2) if rows else 0,
            "profit_factor": round(sum(p for p in pnls if p > 0) / abs(sum(p for p in pnls if p < 0)), 3) if any(p < 0 for p in pnls) else None,
            "common_exit_reasons": _top_values(rows, "reason"),
        })
    by_strategy.sort(key=lambda item: item["net_pnl"], reverse=True)
    losing_reasons = _top_values([row for row in recent if float(row.get("pnl") or 0) < 0], "reason")
    lessons = []
    if losing_reasons:
        lessons.append("Son kayıplarda tekrar eden çıkış nedenlerini yeni adaylarda özellikle kontrol et.")
    if by_strategy and by_strategy[0]["net_pnl"] > 0:
        lessons.append(f"Geçmişte en iyi net sonuç: {by_strategy[0]['strategy']}; bu geçmiş başarı geleceği garanti etmez.")
    return {"enabled": bool(recent), "sample_size": len(recent), "by_strategy": by_strategy[:12],
            "repeated_loss_reasons": losing_reasons, "lessons": lessons,
            "policy": "descriptive_only_no_parameter_mutation_no_trade_authorization",
            "source": "closed_paper_trades_net_pnl"}


def _top_values(rows: list[dict], key: str, limit: int = 5) -> list[dict]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        value = str(row.get(key) or "unknown")
        counts[value] += 1
    return [{"value": value, "count": count} for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]
