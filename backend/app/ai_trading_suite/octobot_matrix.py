"""
OctoBot-inspired Matrix Evaluator for Scalper Global Agent.
Provides multi-indicator weighted scoring and consensus aggregation for Spot & Forex.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np


@dataclass
class IndicatorEvaluation:
    indicator_name: str
    signal: float  # Range: -1.0 (Strong Sell) to +1.0 (Strong Buy)
    weight: float   # Relative importance in consensus
    timeframe: str = "5m"
    details: Dict[str, float] = field(default_factory=dict)


@dataclass
class MatrixConsensusResult:
    symbol: str
    asset_type: str  # "SPOT" or "FOREX"
    composite_score: float  # -1.0 to +1.0
    consensus_signal: str   # "STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"
    consensus_confidence: float  # 0.0 to 1.0 (Agreement ratio)
    bullish_weight_sum: float
    bearish_weight_sum: float
    total_weight: float
    evaluations: List[IndicatorEvaluation]
    is_actionable: bool
    threshold: float


class OctoBotMatrixEvaluator:
    """
    Evaluates trading signals using weighted matrix voting.
    Suitable for both Spot (crypto) and Forex (MT5) indicators.
    """

    def __init__(self, consensus_threshold: float = 0.60):
        self.consensus_threshold = consensus_threshold

    def evaluate(
        self,
        symbol: str,
        asset_type: str,
        evaluations: List[IndicatorEvaluation],
        custom_threshold: Optional[float] = None
    ) -> MatrixConsensusResult:
        threshold = custom_threshold if custom_threshold is not None else self.consensus_threshold

        if not evaluations:
            return MatrixConsensusResult(
                symbol=symbol,
                asset_type=asset_type,
                composite_score=0.0,
                consensus_signal="NEUTRAL",
                consensus_confidence=0.0,
                bullish_weight_sum=0.0,
                bearish_weight_sum=0.0,
                total_weight=0.0,
                evaluations=[],
                is_actionable=False,
                threshold=threshold
            )

        total_weight = sum(e.weight for e in evaluations if e.weight > 0)
        if total_weight <= 0:
            total_weight = 1.0

        weighted_sum = sum(e.signal * e.weight for e in evaluations)
        composite_score = float(np.clip(weighted_sum / total_weight, -1.0, 1.0))

        bullish_weights = sum(e.weight for e in evaluations if e.signal > 0.15)
        bearish_weights = sum(e.weight for e in evaluations if e.signal < -0.15)
        neutral_weights = sum(e.weight for e in evaluations if -0.15 <= e.signal <= 0.15)

        # Confidence is ratio of the dominant directional weight to total weight
        dominant_weight = max(bullish_weights, bearish_weights)
        confidence = dominant_weight / total_weight if total_weight > 0 else 0.0

        if composite_score >= 0.70 and confidence >= threshold:
            signal = "STRONG_BUY"
            actionable = True
        elif composite_score >= 0.35 and confidence >= threshold:
            signal = "BUY"
            actionable = True
        elif composite_score <= -0.70 and confidence >= threshold:
            signal = "STRONG_SELL"
            actionable = True
        elif composite_score <= -0.35 and confidence >= threshold:
            signal = "SELL"
            actionable = True
        else:
            signal = "NEUTRAL"
            actionable = False

        return MatrixConsensusResult(
            symbol=symbol,
            asset_type=asset_type.upper(),
            composite_score=round(composite_score, 4),
            consensus_signal=signal,
            consensus_confidence=round(confidence, 4),
            bullish_weight_sum=round(bullish_weights, 3),
            bearish_weight_sum=round(bearish_weights, 3),
            total_weight=round(total_weight, 3),
            evaluations=evaluations,
            is_actionable=actionable,
            threshold=threshold
        )
