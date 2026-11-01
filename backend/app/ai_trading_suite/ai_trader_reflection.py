"""
AI-Trader inspired Self-Reflection, Devil's Advocate & Trap Detection Engine.
Subjects every trade thesis to rigorous counter-examination before approval.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TradeThesis:
    symbol: str
    asset_type: str
    proposed_action: str  # "BUY" or "SELL"
    timeframe: str
    primary_reason: str
    indicators_supporting: List[str]
    volume_trend: str     # "EXPANDING", "FLAT", "DECLINING"
    cvd_alignment: bool   # Cumulative Volume Delta agrees with price
    near_key_resistance: bool
    near_key_support: bool


@dataclass
class ReflectionAuditReport:
    symbol: str
    initial_verdict: str
    final_verdict: str  # "APPROVED", "REJECTED_TRAP", "REDUCED_SIZE_CAUTION"
    trap_detected: str  # "NONE", "BULL_TRAP", "BEAR_TRAP", "LIQUIDITY_SWEEP"
    devils_advocate_critique: str
    confidence_penalty: float
    final_confidence: float
    reflection_notes: List[str]


class AITraderSelfReflectionAuditor:
    """
    Acts as the second eye / devil's advocate that attempts to disprove any proposed setup.
    Prevents buying the top of fakeouts or shorting into liquidity absorption zones.
    """

    def audit_trade_proposal(self, thesis: TradeThesis, raw_confidence: float = 0.85) -> ReflectionAuditReport:
        reflection_notes = []
        trap_detected = "NONE"
        confidence_penalty = 0.0

        # Check Bull Trap
        if thesis.proposed_action.upper() == "BUY":
            if thesis.near_key_resistance and not thesis.cvd_alignment:
                trap_detected = "BULL_TRAP"
                confidence_penalty += 0.45
                reflection_notes.append("Price pushing resistance with declining CVD and buying exhaustion.")

            if thesis.volume_trend == "DECLINING":
                confidence_penalty += 0.20
                reflection_notes.append("Volume is declining into the upward move; lack of institutional participation.")

        # Check Bear Trap
        elif thesis.proposed_action.upper() == "SELL":
            if thesis.near_key_support and not thesis.cvd_alignment:
                trap_detected = "BEAR_TRAP"
                confidence_penalty += 0.45
                reflection_notes.append("Price breaking support but selling absorption detected without follow-through.")

            if thesis.volume_trend == "DECLINING":
                confidence_penalty += 0.20
                reflection_notes.append("Declining selling volume near multi-session low; risk of snapback bounce.")

        final_conf = max(0.0, raw_confidence - confidence_penalty)

        if trap_detected in ("BULL_TRAP", "BEAR_TRAP"):
            final_verdict = "REJECTED_TRAP"
            critique = f"Self-Reflection Veto: Setup rejected due to high probability {trap_detected} characteristics."
        elif confidence_penalty >= 0.30:
            final_verdict = "REDUCED_SIZE_CAUTION"
            critique = "Self-Reflection Warning: Setup viable but exhibits divergence; scale down exposure by 50%."
        else:
            final_verdict = "APPROVED"
            critique = "Self-Reflection Approved: No severe trap or divergence detected across volume/orderflow metrics."

        return ReflectionAuditReport(
            symbol=thesis.symbol,
            initial_verdict=thesis.proposed_action,
            final_verdict=final_verdict,
            trap_detected=trap_detected,
            devils_advocate_critique=critique,
            confidence_penalty=round(confidence_penalty, 3),
            final_confidence=round(final_conf, 3),
            reflection_notes=reflection_notes
        )
