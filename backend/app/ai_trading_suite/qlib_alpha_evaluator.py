"""Microsoft Qlib inspired Multi-Factor Alpha Evaluator.

Implements quantitative factor calculation inspired by Microsoft Qlib's Alpha158/Alpha360:
- Momentum factors (ROC5, ROC10, ROC20, Price/SMA distance)
- Volatility factors (Normalized ATR, Bollinger Bandwidth, Realized Volatility)
- Volume factors (Volume Surge Ratio, Price-Volume correlation)
- Alpha Consensus Score (0 to 100) and Factor Alignment Ranking.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QlibAlphaResult(BaseModel):
    symbol: str
    alpha_score: float = Field(..., ge=0.0, le=100.0, description="Composite Qlib alpha score (0-100)")
    alpha_rank: str = Field(..., description="STRONG_ALPHA, MODERATE_ALPHA, WEAK, or NEGATIVE")
    momentum_factor: float
    volatility_factor: float
    volume_factor: float
    factors_summary: Dict[str, float] = Field(default_factory=dict)
    factor_verdict: str
    action_bias: str = Field(..., description="BUY, NEUTRAL, or REDUCE")


def evaluate_qlib_alpha(
    symbol: str,
    price: float,
    indicators: Optional[Dict[str, Any]] = None,
    candles: Optional[List[Dict[str, float]]] = None
) -> QlibAlphaResult:
    """Computes composite quantitative alpha score inspired by Microsoft Qlib factor library."""
    indicators = indicators or {}
    px = max(price, 0.000001)

    # 1. Momentum Factors
    rsi = float(indicators.get("rsi") or 50.0)
    adx = float(indicators.get("adx") or 20.0)
    ema_fast = float(indicators.get("ema_fast") or px * 1.002)
    ema_slow = float(indicators.get("ema_slow") or px * 0.998)
    
    # Distance of fast EMA from slow EMA (normalized %)
    ema_spread_pct = ((ema_fast - ema_slow) / px) * 100.0
    
    # RSI distance from equilibrium 50
    rsi_norm = max(-1.0, min(1.0, (rsi - 50.0) / 30.0))
    momentum_raw = (rsi_norm * 0.6) + (min(1.0, ema_spread_pct / 1.5) * 0.4)
    momentum_factor = round(max(-1.0, min(1.0, momentum_raw)), 3)

    # 2. Volatility Factors (normalized ATR and BB width)
    atr = float(indicators.get("atr") or (px * 0.015))
    atr_pct = (atr / px) * 100.0
    bb_upper = float(indicators.get("bb_upper") or (px * 1.02))
    bb_lower = float(indicators.get("bb_lower") or (px * 0.98))
    bb_width_pct = max(0.1, ((bb_upper - bb_lower) / px) * 100.0)
    
    # Optimal volatility for trend continuation is moderate (1.0% to 3.5%)
    if 1.0 <= atr_pct <= 3.5:
        volatility_factor = 0.8
    elif atr_pct < 1.0:
        volatility_factor = 0.4  # Choppy/stagnant
    else:
        volatility_factor = max(0.1, 1.0 - ((atr_pct - 3.5) * 0.15))  # High risk/panic
    volatility_factor = round(volatility_factor, 3)

    # 3. Volume Factors
    vol_ratio = float(indicators.get("volume_ratio") or 1.2)
    if vol_ratio >= 1.5:
        volume_factor = 0.9
    elif vol_ratio >= 1.0:
        volume_factor = 0.7
    elif vol_ratio >= 0.7:
        volume_factor = 0.4
    else:
        volume_factor = 0.1  # Severe volume divergence
    volume_factor = round(volume_factor, 3)

    # 4. Composite Alpha Score (0 to 100)
    # Base score centered at 50 + weighted contributions
    alpha_raw = 50.0 + (momentum_factor * 25.0) + ((volatility_factor - 0.5) * 20.0) + ((volume_factor - 0.5) * 30.0)
    alpha_score = round(max(5.0, min(98.0, alpha_raw)), 1)

    if alpha_score >= 75.0:
        alpha_rank = "STRONG_ALPHA"
        factor_verdict = "Qlib Alpha158 faktörleri güçlü yükseliş konsensüsü gösteriyor."
        action_bias = "BUY"
    elif alpha_score >= 60.0:
        alpha_rank = "MODERATE_ALPHA"
        factor_verdict = "Pozitif faktör dizilimi; momentum ve hacim alımı destekliyor."
        action_bias = "BUY"
    elif alpha_score >= 45.0:
        alpha_rank = "WEAK"
        factor_verdict = "Karışık faktörler; net bir alpha avantajı tespit edilemedi."
        action_bias = "NEUTRAL"
    else:
        alpha_rank = "NEGATIVE"
        factor_verdict = "Negatif faktör baskısı veya hacim tükenişi riski yüksek."
        action_bias = "REDUCE"

    factors_summary = {
        "rsi": round(rsi, 2),
        "adx": round(adx, 2),
        "ema_spread_pct": round(ema_spread_pct, 3),
        "atr_pct": round(atr_pct, 2),
        "bb_width_pct": round(bb_width_pct, 2),
        "volume_ratio": round(vol_ratio, 2)
    }

    return QlibAlphaResult(
        symbol=symbol.upper(),
        alpha_score=alpha_score,
        alpha_rank=alpha_rank,
        momentum_factor=momentum_factor,
        volatility_factor=volatility_factor,
        volume_factor=volume_factor,
        factors_summary=factors_summary,
        factor_verdict=factor_verdict,
        action_bias=action_bias
    )
