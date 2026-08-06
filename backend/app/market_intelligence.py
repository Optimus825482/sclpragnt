"""Deterministic market-intelligence helpers for Binance TR paper trading.

This adapts the useful parts of the referenced quant/regime skills without
introducing DEX, wallet, futures, or live-execution assumptions.
"""

from __future__ import annotations

from statistics import mean


def estimate_local_regime(rows: list[dict]) -> dict:
    """Estimate a degraded, local regime from already-fetched TR snapshots.

    This is deliberately descriptive: it is not a portfolio allocation rule.
    """
    ready = [r for r in rows if r.get("data_ready") and isinstance(r.get("snapshot"), dict)]
    if len(ready) < 3:
        return {"zone": "UNKNOWN", "score": None, "confidence": 0.0,
                "reason": "Yeterli sembol snapshot'ı yok", "data_available": False}
    scores = [float(r.get("score", 0)) for r in ready]
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
    spread = liquidity.get("spread_pct")
    depth = liquidity.get("orderbook_depth_try")
    volume = (snapshot.get("volume") or {}).get("volume_ratio_20")
    reasons = []
    quality = 1.0
    if spread is None:
        quality -= 0.35; reasons.append("spread bilinmiyor")
    elif float(spread) > 0.20:
        quality -= 0.35; reasons.append("spread yüksek")
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
            "data_available": not (spread is None and depth in (None, 0))}


def symbol_safety(snapshot: dict) -> dict:
    """Centralized-exchange safety gate; no contract/wallet claims are made."""
    liquidity = snapshot.get("liquidity") or {}
    volume = (snapshot.get("volume") or {}).get("volume_ratio_20")
    flags = []
    if not snapshot.get("data_ready"):
        flags.append("snapshot hazır değil")
    if liquidity.get("spread_pct") is None:
        flags.append("spread bilinmiyor")
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
