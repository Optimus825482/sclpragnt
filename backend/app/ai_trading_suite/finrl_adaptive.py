"""
FinRL-inspired Deep Reinforcement Learning Adaptive Exit & Position Sizing Engine.
Implements fee-aware reward calibration, ATR-adaptive trailing stops, and multi-tier exits.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class AdaptiveExitPlan:
    symbol: str
    entry_price: float
    atr: float
    current_profit_pct: float
    holding_bars: int
    base_stop_loss: float
    recommended_stop_loss: float
    take_profit_target_1: float
    take_profit_target_2: float
    trailing_activated: bool
    exit_urgency: str  # "HOLD", "TIGHTEN_STOP", "PARTIAL_CLOSE", "IMMEDIATE_EXIT"
    reward_score: float
    action_reason: str


class FinRLAdaptiveEngine:
    """
    Simulates dynamic policy exits learned from DRL continuous action models.
    Takes into account transaction fees (maker/taker in Spot, spread/commissions in Forex).
    """

    def __init__(self, spot_fee_pct: float = 0.001, forex_pip_cost_pct: float = 0.00015):
        self.spot_fee_pct = spot_fee_pct  # 0.1% Binance spot fee
        self.forex_pip_cost_pct = forex_pip_cost_pct

    def compute_exit_policy(
        self,
        symbol: str,
        asset_type: str,
        entry_price: float,
        current_price: float,
        atr: float,
        holding_bars: int,
        highest_price_since_entry: float,
        side: str = "BUY"
    ) -> AdaptiveExitPlan:
        asset_type = asset_type.upper()
        fee_pct = self.spot_fee_pct * 2.0 if asset_type == "SPOT" else self.forex_pip_cost_pct * 2.0

        if side.upper() == "BUY":
            profit_pct = (current_price - entry_price) / entry_price
            peak_profit_pct = (highest_price_since_entry - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price
            peak_profit_pct = (entry_price - highest_price_since_entry) / entry_price

        # Net profit after round-trip transaction costs
        net_profit_pct = profit_pct - fee_pct

        # ATR multiplier dynamically contracts as profit or holding duration expands
        atr_pct = (atr / current_price) if current_price > 0 else 0.01

        # Base stops (Targeting >= 1.5 R:R baseline)
        if side.upper() == "BUY":
            base_stop = entry_price - (atr * 1.4)
            tp1 = entry_price + (atr * 2.1)
            tp2 = entry_price + (atr * 3.8)
        else:
            base_stop = entry_price + (atr * 1.4)
            tp1 = entry_price - (atr * 2.1)
            tp2 = entry_price - (atr * 3.8)

        # Trailing activation check (e.g. once 1.2x ATR profit or > 1.2% is locked)
        trailing_activated = net_profit_pct >= (atr_pct * 1.2)

        recommended_stop = base_stop
        exit_urgency = "HOLD"
        reason = "Trade running within standard ATR breathing room."

        if trailing_activated:
            # DRL Trailing Policy: Lock in 50% to 75% of peak gains
            if side.upper() == "BUY":
                locked_profit_price = entry_price + (highest_price_since_entry - entry_price) * 0.65
                breakeven_plus_fees = entry_price * (1.0 + fee_pct * 1.2)
                recommended_stop = max(base_stop, locked_profit_price, breakeven_plus_fees)
                
                # Check if current price is falling below tightened trail
                if current_price <= recommended_stop:
                    exit_urgency = "IMMEDIATE_EXIT"
                    reason = "Trailing stop hit; locking in verified profit."
                elif net_profit_pct >= (atr_pct * 3.0):
                    exit_urgency = "PARTIAL_CLOSE"
                    reason = "Tier 2 target reached; take 50% off table and trail remainder."
                else:
                    exit_urgency = "TIGHTEN_STOP"
                    reason = "Trailing active; stop raised to lock profit above breakeven."
            else:
                locked_profit_price = entry_price - (entry_price - highest_price_since_entry) * 0.65
                breakeven_plus_fees = entry_price * (1.0 - fee_pct * 1.2)
                recommended_stop = min(base_stop, locked_profit_price, breakeven_plus_fees)
                if current_price >= recommended_stop:
                    exit_urgency = "IMMEDIATE_EXIT"
                    reason = "Short trailing stop hit; locking in verified profit."
                else:
                    exit_urgency = "TIGHTEN_STOP"
                    reason = "Short trailing active; stop lowered below breakeven."
        else:
            # Time decay protection: if holding bars > 25 and net profit is stalled around 0, tighten
            if holding_bars >= 25 and abs(net_profit_pct) < fee_pct:
                exit_urgency = "TIGHTEN_STOP"
                recommended_stop = entry_price * (0.998 if side.upper() == "BUY" else 1.002)
                reason = "Stagnation timeout: Position flat after 25 bars. Tightening stop to mitigate capital lockup."

        # Sharpe/Sortino reward metric
        downside_penalty = max(0.0, -net_profit_pct) * 2.5
        reward_score = float(np.tanh((net_profit_pct * 10.0) - downside_penalty))

        return AdaptiveExitPlan(
            symbol=symbol,
            entry_price=round(entry_price, 5),
            atr=round(atr, 5),
            current_profit_pct=round(profit_pct * 100.0, 3),
            holding_bars=holding_bars,
            base_stop_loss=round(base_stop, 5),
            recommended_stop_loss=round(recommended_stop, 5),
            take_profit_target_1=round(tp1, 5),
            take_profit_target_2=round(tp2, 5),
            trailing_activated=trailing_activated,
            exit_urgency=exit_urgency,
            reward_score=round(reward_score, 4),
            action_reason=reason
        )
