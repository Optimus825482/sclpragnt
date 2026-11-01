"""
ai-hedge-fund inspired Multi-Persona Investment Committee.
Simulates trading decisions of George Soros (Macro), Jim Simons (Quant), and Ray Dalio (Risk Parity).
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class CouncilVote:
    persona_name: str
    vote: str           # "BULLISH", "BEARISH", "NEUTRAL"
    confidence: float   # 0.0 to 1.0
    thesis: str
    key_factors: List[str]


@dataclass
class CouncilConsensus:
    symbol: str
    asset_type: str
    consensus_decision: str  # "LONG", "SHORT", "STAND_ASIDE"
    aggregate_score: float   # -1.0 to +1.0
    consensus_agreement: float  # 0.0 to 1.0
    soros_vote: CouncilVote
    simons_vote: CouncilVote
    dalio_vote: CouncilVote
    committee_statement: str


class HedgeFundCouncil:
    """
    Synthesizes views from Macro (Soros), Quantitative (Simons), and Risk Parity (Dalio).
    Balances aggressive macro inflection bets with strict statistical edge and capital protection.
    """

    def deliberate(
        self,
        symbol: str,
        asset_type: str,
        macro_score: float,        # -1.0 to +1.0 (from Macro analyzer)
        quant_z_score: float,      # Statistical z-score of current price deviation
        volatility_regime: str,    # "LOW", "NORMAL", "EXTREME"
        rsi_value: float,
        trend_slope: float
    ) -> CouncilConsensus:
        asset_type = asset_type.upper()

        # 1. George Soros: Reflexivity & Macro Imbalance
        if macro_score >= 0.35 and trend_slope > 0:
            soros_vote = CouncilVote(
                persona_name="George Soros",
                vote="BULLISH",
                confidence=min(1.0, 0.6 + abs(macro_score) * 0.4),
                thesis="Macro fundamentals and market reflexivity align positively for sustained upward momentum.",
                key_factors=["Macro Score Positive", "Trend Following", "Reflexive Feedback Loop"]
            )
        elif macro_score <= -0.35 and trend_slope < 0:
            soros_vote = CouncilVote(
                persona_name="George Soros",
                vote="BEARISH",
                confidence=min(1.0, 0.6 + abs(macro_score) * 0.4),
                thesis="Fundamental divergence and monetary headwinds indicate severe downside vulnerability.",
                key_factors=["Macro Disbalance", "Tightening Pressure", "Downside Momentum"]
            )
        else:
            soros_vote = CouncilVote(
                persona_name="George Soros",
                vote="NEUTRAL",
                confidence=0.5,
                thesis="Macro conditions are mixed without clear catalyst.",
                key_factors=["Indecisive Macro Outlook"]
            )

        # 2. Jim Simons: Mathematical Edge & Mean-Reversion / Trend Signals
        if quant_z_score > 1.8 and rsi_value > 72.0:
            simons_vote = CouncilVote(
                persona_name="Jim Simons",
                vote="BEARISH",
                confidence=0.82,
                thesis="Extreme statistical extension (Z > 1.8). High probability mean reversion anticipated.",
                key_factors=[f"Z-Score {quant_z_score:.2f}", f"RSI {rsi_value:.1f}", "Mean Reversion Probability 78%"]
            )
        elif quant_z_score < -1.8 and rsi_value < 28.0:
            simons_vote = CouncilVote(
                persona_name="Jim Simons",
                vote="BULLISH",
                confidence=0.82,
                thesis="Oversold statistical dislocation (Z < -1.8). Expect positive reversion to volume mean.",
                key_factors=[f"Z-Score {quant_z_score:.2f}", f"RSI {rsi_value:.1f}", "Mean Reversion Probability 81%"]
            )
        elif trend_slope > 0.005 and 45.0 <= rsi_value <= 65.0:
            simons_vote = CouncilVote(
                persona_name="Jim Simons",
                vote="BULLISH",
                confidence=0.74,
                thesis="Positive drift factor with healthy momentum bounds.",
                key_factors=["Positive Drift Factor", "Sustainable Momentum"]
            )
        elif trend_slope < -0.005 and 35.0 <= rsi_value <= 55.0:
            simons_vote = CouncilVote(
                persona_name="Jim Simons",
                vote="BEARISH",
                confidence=0.74,
                thesis="Negative drift factor with unyielding selling persistence.",
                key_factors=["Negative Drift Factor", "Selling Continuation"]
            )
        else:
            simons_vote = CouncilVote(
                persona_name="Jim Simons",
                vote="NEUTRAL",
                confidence=0.45,
                thesis="No statistically significant edge detected in current distribution.",
                key_factors=["Stochastic Noise", "Low Signal-to-Noise Ratio"]
            )

        # 3. Ray Dalio: Volatility & Capital Preservation
        if volatility_regime.upper() == "EXTREME":
            dalio_vote = CouncilVote(
                persona_name="Ray Dalio",
                vote="NEUTRAL",
                confidence=0.90,
                thesis="Extreme volatility regime. Capital preservation dictates standing aside or drastically cutting risk.",
                key_factors=["Extreme Volatility", "All-Weather Risk Budget Preserved"]
            )
        else:
            # Dalio checks if Soros and Simons are in rough harmony
            if soros_vote.vote == simons_vote.vote and soros_vote.vote != "NEUTRAL":
                dalio_vote = CouncilVote(
                    persona_name="Ray Dalio",
                    vote=soros_vote.vote,
                    confidence=0.78,
                    thesis=f"Risk parity conditions satisfied. Quant signals and macro backdrop corroborate a {soros_vote.vote} stance.",
                    key_factors=["Balanced Risk Profile", "Regime Stability"]
                )
            else:
                dalio_vote = CouncilVote(
                    persona_name="Ray Dalio",
                    vote="NEUTRAL",
                    confidence=0.60,
                    thesis="Divergence between Macro and Quant models. Risk budget prudently recommends neutral exposure.",
                    key_factors=["Model Divergence", "Capital Protection"]
                )

        # Aggregate deliberation
        vote_map = {"BULLISH": 1.0, "NEUTRAL": 0.0, "BEARISH": -1.0}
        weights = {"Soros": 0.35, "Simons": 0.40, "Dalio": 0.25}

        agg_score = (
            vote_map[soros_vote.vote] * weights["Soros"] +
            vote_map[simons_vote.vote] * weights["Simons"] +
            vote_map[dalio_vote.vote] * weights["Dalio"]
        )

        all_votes = [soros_vote.vote, simons_vote.vote, dalio_vote.vote]
        directional_count = max(all_votes.count("BULLISH"), all_votes.count("BEARISH"))
        agreement = directional_count / 3.0

        if agg_score >= 0.45 and agreement >= 0.66:
            decision = "LONG"
        elif agg_score <= -0.45 and agreement >= 0.66:
            decision = "SHORT"
        else:
            decision = "STAND_ASIDE"

        statement = (
            f"Council Deliberation for {symbol}: Result is {decision} (Score: {agg_score:.2f}). "
            f"Agreement: {int(agreement*100)}%. "
            f"Soros={soros_vote.vote}, Simons={simons_vote.vote}, Dalio={dalio_vote.vote}."
        )

        return CouncilConsensus(
            symbol=symbol,
            asset_type=asset_type,
            consensus_decision=decision,
            aggregate_score=round(agg_score, 4),
            consensus_agreement=round(agreement, 2),
            soros_vote=soros_vote,
            simons_vote=simons_vote,
            dalio_vote=dalio_vote,
            committee_statement=statement
        )
