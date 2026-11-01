"""
TradingAgents-inspired Institutional Trading Desk & Risk Chief Veto Engine.
Uses strict Pydantic JSON contracts and an unappealable Risk Chief Veto layer.
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


class AssetClass(str, Enum):
    SPOT = "SPOT"
    FOREX = "FOREX"


class TradeContractProposal(BaseModel):
    """
    Rigorous institutional proposal contract.
    Must contain explicit entry, stops, targets, and rationale.
    """
    symbol: str
    asset_class: AssetClass
    action: TradeAction
    confidence: float = Field(ge=0.0, le=1.0)
    current_price: float
    entry_target: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward_ratio: float
    proposed_lot_or_qty: float
    account_margin_used_pct: float
    spread_pips_or_pct: float
    macro_event_within_minutes: Optional[int] = None
    daily_drawdown_so_far_pct: float = 0.0
    thesis_summary: str


class VetoVerdict(BaseModel):
    approved: bool
    final_action: TradeAction
    veto_reasons: List[str]
    risk_score: float = Field(ge=0.0, le=1.0)
    adjusted_lot_or_qty: float
    audit_notes: str


class RiskChiefVetoEngine:
    """
    Independent compliance and risk management officer.
    Has absolute authority to block or downsize any trade proposal,
    protecting capital against high spread, news slippage, and excessive margin.
    """

    MAX_ACCOUNT_MARGIN_PCT = 15.0     # Max 15% total margin on active trades
    MAX_DAILY_DRAWDOWN_PCT = 4.0      # Block new trades if daily loss > 4%
    MAX_SPREAD_FOREX_PIPS = 2.5       # Max 2.5 pips spread on MT5
    MAX_SPREAD_SPOT_PCT = 0.0012      # Max 0.12% spread on Binance spot
    NEWS_BLACKOUT_WINDOW_MINUTES = 20 # Block within 20 mins of high-impact event

    def review_contract(self, proposal: TradeContractProposal) -> VetoVerdict:
        veto_reasons: List[str] = []
        risk_score = 0.20
        approved = True
        adjusted_qty = proposal.proposed_lot_or_qty

        # 1. Action Check
        if proposal.action == TradeAction.WAIT:
            return VetoVerdict(
                approved=True,
                final_action=TradeAction.WAIT,
                veto_reasons=[],
                risk_score=0.0,
                adjusted_lot_or_qty=0.0,
                audit_notes="Desk is in WAIT stance; no order will be routed."
            )

        # 2. Risk/Reward Ratio Check
        if proposal.risk_reward_ratio < 1.4:
            approved = False
            veto_reasons.append(f"Substandard R:R ratio ({proposal.risk_reward_ratio:.2f} < 1.40). Expectancy negative.")
            risk_score += 0.35

        # 3. Daily Drawdown Ceiling Veto
        if proposal.daily_drawdown_so_far_pct >= self.MAX_DAILY_DRAWDOWN_PCT:
            approved = False
            veto_reasons.append(f"Daily drawdown threshold reached ({proposal.daily_drawdown_so_far_pct:.2f}% >= {self.MAX_DAILY_DRAWDOWN_PCT}%). Lockout active.")
            risk_score = 1.0

        # 4. Account Margin Limit Veto
        if proposal.account_margin_used_pct >= self.MAX_ACCOUNT_MARGIN_PCT:
            approved = False
            veto_reasons.append(f"Portfolio margin limit exceeded ({proposal.account_margin_used_pct:.1f}% >= {self.MAX_ACCOUNT_MARGIN_PCT}%).")
            risk_score += 0.40

        # 5. Economic Calendar Blackout Veto
        if proposal.macro_event_within_minutes is not None:
            if 0 <= proposal.macro_event_within_minutes <= self.NEWS_BLACKOUT_WINDOW_MINUTES:
                approved = False
                veto_reasons.append(f"High-impact macroeconomic event in {proposal.macro_event_within_minutes}m. High slippage/spread widening danger.")
                risk_score += 0.50

        # 6. Spread Check
        if proposal.asset_class == AssetClass.FOREX:
            if proposal.spread_pips_or_pct > self.MAX_SPREAD_FOREX_PIPS:
                approved = False
                veto_reasons.append(f"Forex spread too wide ({proposal.spread_pips_or_pct:.1f} pips > {self.MAX_SPREAD_FOREX_PIPS} pips).")
                risk_score += 0.30
        else:
            if proposal.spread_pips_or_pct > self.MAX_SPREAD_SPOT_PCT:
                approved = False
                veto_reasons.append(f"Spot spread too wide ({proposal.spread_pips_or_pct*100:.3f}% > {self.MAX_SPREAD_SPOT_PCT*100:.3f}%).")
                risk_score += 0.30

        # 7. Confidence Sizing Adjustment
        if approved:
            if proposal.confidence < 0.70:
                adjusted_qty = proposal.proposed_lot_or_qty * 0.50
                audit_notes = f"Approved with cautionary 50% downsizing (Confidence: {proposal.confidence*100:.1f}%)."
            else:
                audit_notes = f"Fully approved by Risk Chief (Confidence: {proposal.confidence*100:.1f}%, R:R: {proposal.risk_reward_ratio:.2f})."
            final_action = proposal.action
        else:
            adjusted_qty = 0.0
            final_action = TradeAction.WAIT
            audit_notes = f"VETOED by Risk Chief. {len(veto_reasons)} violation(s) identified."

        return VetoVerdict(
            approved=approved,
            final_action=final_action,
            veto_reasons=veto_reasons,
            risk_score=min(1.0, risk_score),
            adjusted_lot_or_qty=round(adjusted_qty, 4),
            audit_notes=audit_notes
        )
