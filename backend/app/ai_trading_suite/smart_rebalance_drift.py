"""
Smart Rebalancing & Drift Threshold Engine for Spot Portfolios.
Inspired by Shrimpy-style dynamic portfolio rebalancing and institutional drift management.
Automatically locks in profits from overextended spot gainers and reallocates into cash or dip assets
without rigid calendar dates.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class AssetRebalanceAction(BaseModel):
    symbol: str
    target_weight_pct: float
    current_weight_pct: float
    drift_pct: float
    action: str  # "TRIM_PROFIT_SELL", "BUY_DEFICIT", "HOLD_IN_TOLERANCE"
    amount_try_to_trade: float
    execution_priority: int


class SmartRebalanceResult(BaseModel):
    total_portfolio_value_try: float
    cash_reserve_pct: float
    max_drift_detected_pct: float
    rebalance_triggered: bool
    actions: List[AssetRebalanceAction]
    realized_profit_lock_try: float
    tactical_rationale: str


def evaluate_smart_rebalance(
    current_holdings_map: Optional[Dict[str, float]] = None,
    prices_map: Optional[Dict[str, float]] = None,
    target_weights_map: Optional[Dict[str, float]] = None,
    drift_tolerance_pct: float = 5.0
) -> SmartRebalanceResult:
    """Evaluates spot asset weights against targets and triggers threshold-based rebalancing."""
    # Defaults if none provided
    holdings = current_holdings_map or {"BTCTRY": 0.05, "ETHTRY": 0.8, "SOLTRY": 15.0, "TRY": 5000.0}
    prices = prices_map or {"BTCTRY": 2350000.0, "ETHTRY": 95000.0, "SOLTRY": 6500.0, "TRY": 1.0}
    targets = target_weights_map or {"BTCTRY": 30.0, "ETHTRY": 25.0, "SOLTRY": 25.0, "TRY": 20.0}

    # Calculate current values
    values = {}
    for sym, qty in holdings.items():
        px = prices.get(sym, 1.0)
        values[sym] = qty * px

    total_val = max(100.0, sum(values.values()))
    current_weights = {sym: (val / total_val) * 100.0 for sym, val in values.items()}

    actions: List[AssetRebalanceAction] = []
    max_drift = 0.0
    profit_lock = 0.0
    rebal_needed = False

    for sym, target_w in targets.items():
        cur_w = current_weights.get(sym, 0.0)
        drift = round(cur_w - target_w, 2)
        abs_drift = abs(drift)
        if abs_drift > max_drift:
            max_drift = abs_drift

        val_diff = round((abs_drift / 100.0) * total_val, 2)

        if drift > drift_tolerance_pct:
            # Overextended gainer: trim and lock profit
            action = "TRIM_PROFIT_SELL"
            priority = 1
            rebal_needed = True
            profit_lock += val_diff
            rationale_action = f"{sym} hedefinin %{drift} üzerinde; kâr realize edilip nakite/dibe aktarılmalı."
        elif drift < -drift_tolerance_pct:
            # Underweight asset: accumulate dip
            action = "BUY_DEFICIT"
            priority = 2
            rebal_needed = True
            rationale_action = f"{sym} hedefinin %{abs(drift)} altında kaldı; biriken kâr ile dip alımı yapılmalı."
        else:
            action = "HOLD_IN_TOLERANCE"
            priority = 3
            val_diff = 0.0

        actions.append(AssetRebalanceAction(
            symbol=sym,
            target_weight_pct=target_w,
            current_weight_pct=round(cur_w, 2),
            drift_pct=drift,
            action=action,
            amount_try_to_trade=val_diff,
            execution_priority=priority
        ))

    actions.sort(key=lambda a: a.execution_priority)
    cash_pct = round(current_weights.get("TRY", current_weights.get("USDT", 20.0)), 1)

    if rebal_needed:
        tactical = (f"Akıllı Dengeleme Tetiklendi: Portföyde %{max_drift} sapma tespit edildi (Tolerans: %{drift_tolerance_pct}). "
                    f"Aşırı primlenen varlıklardan toplam ₺{round(profit_lock, 2)} kâr kilitlenerek dipteki varlıklara kaydırılıyor.")
    else:
        tactical = f"Portföy dengeli (Maksimum sapma: %{max_drift} <= %{drift_tolerance_pct}). Yeniden dengeleme gerekmiyor."

    return SmartRebalanceResult(
        total_portfolio_value_try=round(total_val, 2),
        cash_reserve_pct=cash_pct,
        max_drift_detected_pct=max_drift,
        rebalance_triggered=rebal_needed,
        actions=actions,
        realized_profit_lock_try=round(profit_lock, 2),
        tactical_rationale=tactical
    )
