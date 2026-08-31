"""Deterministic market-intelligence helpers for Binance TR paper trading.

This adapts the useful parts of the referenced quant/regime skills without
introducing DEX, wallet, futures, or live-execution assumptions.
"""

from __future__ import annotations

from statistics import mean


def trade_economics(entry_price: float, stop_price: float | None = None,
                    take_profit: float | None = None, quantity: float = 0.0,
                    commission_pct: float = 0.0015,
                    spread_pct: float = 0.0,
                    slippage_pct: float = 0.00025,
                    min_net_pnl: float = 0.5) -> dict:
    """Calculate fee-aware LONG paper economics without authorizing a trade."""
    entry = float(entry_price or 0)
    qty = float(quantity or 0)
    notional = entry * qty
    round_trip_cost_pct = max(0.0, float(commission_pct)) * 2 + max(0.0, float(spread_pct)) + max(0.0, float(slippage_pct)) * 2
    round_trip_cost = notional * round_trip_cost_pct
    break_even_price = entry * (1 + round_trip_cost_pct) if entry > 0 else None
    target_move_pct = ((float(take_profit) / entry) - 1) if take_profit and entry > 0 else None
    stop_move_pct = (1 - (float(stop_price) / entry)) if stop_price and entry > 0 else None
    expected_net = (notional * target_move_pct - round_trip_cost) if target_move_pct is not None else None
    edge_cost_ratio = ((notional * target_move_pct) / round_trip_cost) if target_move_pct is not None and round_trip_cost > 0 else None
    return {
        "entry_price": entry, "quantity": qty, "notional": round(notional, 8),
        "round_trip_cost_pct": round(round_trip_cost_pct, 8),
        "round_trip_cost": round(round_trip_cost, 8),
        "break_even_price": round(break_even_price, 8) if break_even_price else None,
        "target_move_pct": round(target_move_pct, 8) if target_move_pct is not None else None,
        "stop_move_pct": round(stop_move_pct, 8) if stop_move_pct is not None else None,
        "expected_net_pnl": round(expected_net, 8) if expected_net is not None else None,
        "edge_cost_ratio": round(edge_cost_ratio, 4) if edge_cost_ratio is not None else None,
        "minimum_net_pnl": float(min_net_pnl),
        "economically_viable": bool(expected_net is not None and expected_net >= float(min_net_pnl)),
        "paper_only": True,
    }


def microstructure_snapshot(snapshot: dict, order_value_try: float = 500.0) -> dict:
    """Normalize realtime liquidity/order-flow fields for an LLM decision."""
    liquidity = snapshot.get("liquidity") or {}
    flow = {
        "spread_pct": liquidity.get("spread_pct"),
        "orderbook_depth_try": liquidity.get("orderbook_depth_try"),
        "depth_multiplier": liquidity.get("depth_multiplier"),
        "orderflow_imbalance": liquidity.get("orderflow_imbalance"),
        "last_trade_side": liquidity.get("last_trade_side"),
        "last_trade_qty": liquidity.get("last_trade_qty"),
        "updated_at": liquidity.get("updated_at"),
        "source": liquidity.get("source"),
    }
    imbalance = flow["orderflow_imbalance"]
    depth = flow["orderbook_depth_try"]
    flags = []
    if imbalance is None: flags.append("order-flow imbalance bilinmiyor")
    if depth in (None, 0): flags.append("order-book derinliği bilinmiyor")
    stale = False
    if flow["updated_at"]:
        import time
        stale = time.time() - float(flow["updated_at"]) > 15
        if stale: flags.append("mikro yapı verisi eski")
    return {"symbol": snapshot.get("symbol"), "order_value_try": float(order_value_try),
            "fields": flow, "flags": flags, "data_ready": not flags,
            "stale": stale, "paper_only": True}


def estimate_local_regime(rows: list[dict]) -> dict:
    """Estimate a degraded, local regime from already-fetched TR snapshots.

    This is deliberately descriptive: it is not a portfolio allocation rule.
    """
    ready = [r for r in rows if r.get("data_ready") and isinstance(r.get("snapshot"), dict)]
    if len(ready) < 3:
        return {"zone": "UNKNOWN", "score": None, "confidence": 0.0,
                "reason": "Yeterli sembol snapshot'ı yok", "data_available": False}
    scores = [float(r.get("score") or 0) for r in ready]
    bullish = [r for r in ready if str(r.get("trend_direction", "")).lower() in {"bullish", "bull", "up"}]
    participation = len(bullish) / len(ready)
    avg_score = mean(scores)
    score = max(0.0, min(100.0, 50 + participation * 35 + max(-15.0, min(15.0, avg_score * 5))))
    if score >= 70:
        zone = "RISK_ON"
        reason = "Sembollerin çoğunda pozitif teknik katılım var"
    elif score <= 35:
        zone = "RISK_OFF"
        reason = "Pozitif teknik katılım zayıf"
    else:
        zone = "NEUTRAL"
        reason = "Sembol bazlı sinyaller karışık"
    return {"zone": zone, "score": round(score, 2),
            "confidence": round(min(0.9, 0.35 + len(ready) / 40), 3),
            "reason": reason, "data_available": True,
            "sample_size": len(ready), "bullish_participation": round(participation, 4),
            "methodology": "local_binance_tr_snapshot_v1"}


def execution_quality(snapshot: dict, order_value_try: float = 500.0) -> dict:
    """Translate execution-model concepts into TR spot paper constraints."""
    liquidity = snapshot.get("liquidity") or {}
    depth = liquidity.get("orderbook_depth_try")
    volume = (snapshot.get("volume") or {}).get("volume_ratio_20")
    reasons = []
    quality = 1.0
    if depth is None or float(depth or 0) <= 0:
        quality -= 0.35; reasons.append("derinlik bilinmiyor")
    elif float(depth) < order_value_try * 5:
        quality -= 0.2; reasons.append("derinlik emir tutarına göre zayıf")
    if volume in (None, 0):
        quality -= 0.2; reasons.append("hacim oranı bilinmiyor")
    elif float(volume) < 1.0:
        quality -= 0.1; reasons.append("hacim ortalamanın altında")
    return {"score": round(max(0.0, quality), 3), "reasons": reasons,
            "order_value_try": order_value_try,
            "data_available": depth is not None and depth > 0}


def symbol_safety(snapshot: dict) -> dict:
    """Centralized-exchange safety gate; no contract/wallet claims are made."""
    liquidity = snapshot.get("liquidity") or {}
    volume = (snapshot.get("volume") or {}).get("volume_ratio_20")
    flags = []
    if not snapshot.get("data_ready"):
        flags.append("snapshot hazır değil")
    if volume in (None, 0):
        flags.append("hacim bilinmiyor")
    return {"status": "PASS" if not flags else "REVIEW", "flags": flags,
            "scope": "Binance TR listeleme/likidite; contract ve deployer analizi yok"}


def cost_aware_trade_metrics(trades: list[dict]) -> dict:
    """Summarize realized trades using net PnL, not win rate alone."""
    pnls = [float(t.get("pnl") or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {"trades": len(pnls), "net_pnl": round(sum(pnls), 6),
            "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
            "commission": round(sum(float(t.get("commission") or 0) for t in trades), 6),
            "paper_only": True}


def symbol_outcome_profile(trades: list[dict], symbol: str | None = None,
                           strategy: str | None = None, limit: int = 100) -> dict:
    rows = [t for t in (trades or [])
            if (not symbol or str(t.get("symbol", "")).upper() == str(symbol).upper())
            and (not strategy or str(t.get("strategy", "")) == str(strategy))]
    rows = rows[-max(1, min(int(limit), 500)):]
    metrics = cost_aware_trade_metrics(rows)
    pnls = [float(t.get("pnl") or 0) for t in rows]
    positive = [p for p in pnls if p > 0]
    negative = [p for p in pnls if p <= 0]
    expectancy = sum(pnls) / len(pnls) if pnls else None
    peak = 0.0; equity = 0.0; max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl; peak = max(peak, equity); max_drawdown = max(max_drawdown, peak - equity)
    streak = 0; longest = 0
    for pnl in reversed(pnls):
        if pnl <= 0: streak += 1
        else: break
    for pnl in pnls:
        longest = longest + 1 if pnl <= 0 else 0
    return {**metrics, "symbol": symbol, "strategy": strategy,
            "expectancy_net_pnl": round(expectancy, 6) if expectancy is not None else None,
            "average_win": round(sum(positive) / len(positive), 6) if positive else None,
            "average_loss": round(sum(negative) / len(negative), 6) if negative else None,
            "max_drawdown_try": round(max_drawdown, 6),
            "current_loss_streak": streak, "longest_loss_streak": longest,
            "recent_trades": rows[-10:], "sample_sufficient_for_inference": len(rows) >= 30,
            "paper_only": True}


def walk_forward_assessment(windows: list[dict]) -> dict:
    """Flag degradation across ordered historical windows without overclaiming."""
    if len(windows) < 2:
        return {"status": "INSUFFICIENT_WINDOWS", "degradation_ratio": None}
    first = float(windows[0].get("net_pnl") or 0)
    last = float(windows[-1].get("net_pnl") or 0)
    ratio = round(last / first, 4) if first > 0 else None
    status = "STABLE" if ratio is not None and ratio >= 0.5 else "DEGRADED"
    return {"status": status, "degradation_ratio": ratio,
            "note": "Pencereler farklı tarih aralıklarıdır; gerçek IS/OOS ayrımı değildir."}
