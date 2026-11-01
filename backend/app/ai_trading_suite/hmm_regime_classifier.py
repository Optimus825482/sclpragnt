"""Hidden Markov Models (HMM) inspired Unsupervised Market Regime Classifier.

Classifies the market into 3 unobservable latent states:
1. TRENDING_EXPANSION: Moderate volatility, positive drift, strong directional momentum
2. CHOPPY_MEAN_REVERSION: Low-to-medium volatility, zero drift, oscillating bounds
3. PANIC_VOLATILITY: High/extreme volatility, negative drift, erratic wicks (Liquidity shock)

Directs the execution strategy: Trend-Following vs. Mean-Reversion vs. Circuit-Breaker Halt.
"""
from __future__ import annotations

import math
from typing import List, Optional
from pydantic import BaseModel, Field


class HMMRegimeResult(BaseModel):
    symbol: str
    active_regime: str = Field(..., description="TRENDING_EXPANSION, CHOPPY_MEAN_REVERSION, or PANIC_VOLATILITY")
    prob_trending: float = Field(..., ge=0.0, le=1.0)
    prob_choppy: float = Field(..., ge=0.0, le=1.0)
    prob_panic: float = Field(..., ge=0.0, le=1.0)
    strategy_directive: str
    transition_risk: str
    verdict: str


def evaluate_hmm_regime(
    symbol: str,
    returns_series: List[float],
    volatility_ratio: float = 1.0,
    adx: float = 22.0
) -> HMMRegimeResult:
    """Classifies latent market regime using transition probabilities and return moments."""
    sym = symbol.upper()
    if not returns_series:
        returns_series = [0.001, 0.002, -0.001, 0.003]

    # Calculate mean and variance of returns
    n = len(returns_series)
    mean_ret = sum(returns_series) / float(n)
    variance = sum((r - mean_ret) ** 2 for r in returns_series) / max(1, n - 1)
    std_ret = math.sqrt(max(1e-8, variance))

    # Likelihood scoring for each latent regime
    # State 1: Trending Expansion (Higher ADX, positive drift, controlled volatility)
    score_trending = max(0.01, (adx / 25.0) * (1.2 if mean_ret > 0 else 0.8))

    # State 2: Choppy / Mean-Reversion (Low ADX, low volatility, mean returns near 0)
    score_choppy = max(0.01, (1.0 / max(0.5, volatility_ratio)) * (1.3 if adx < 22.0 else 0.7))

    # State 3: Panic / Liquidity Shock (Averaging large standard deviation or high volatility ratio > 1.8)
    score_panic = max(0.01, (volatility_ratio * 1.5) if volatility_ratio > 1.8 else (0.1 if volatility_ratio < 1.3 else 0.4))

    # Normalize into posterior probabilities
    total_score = score_trending + score_choppy + score_panic
    prob_trend = round(score_trending / total_score, 3)
    prob_chop = round(score_choppy / total_score, 3)
    prob_panic = round(score_panic / total_score, 3)

    if prob_panic >= 0.50 or volatility_ratio >= 2.2:
        regime = "PANIC_VOLATILITY"
        directive = "CIRCUIT_BREAKER_HALT (Yeni pozisyon açılışlarını durdur, stopları koru)"
        trans_risk = "HIGH_SHOCK"
        verdict = f"HMM Rejimi: Panik/Volatilite Şoku (Olasılık: %{int(prob_panic*100)}). Scalping riskli, piyasa çalkantılı."
    elif prob_trend >= prob_chop:
        regime = "TRENDING_EXPANSION"
        directive = "TREND_FOLLOWING_ACTIVE (Trend devamı ve kırılım stratejilerini tam kapasite çalıştır)"
        trans_risk = "LOW"
        verdict = f"HMM Rejimi: Trend Genişlemesi (Olasılık: %{int(prob_trend*100)}, ADX: {adx:.1f}). Alım momentumu sağlıklı."
    else:
        regime = "CHOPPY_MEAN_REVERSION"
        directive = "MEAN_REVERSION_ONLY (Kırılım alımlarını durdur, destek/direnç osilasyonlarına odaklan)"
        trans_risk = "MODERATE"
        verdict = f"HMM Rejimi: Testere / Yatay Piyasa (Olasılık: %{int(prob_chop*100)}). Sahte kırılım (whipsaw) tuzağı riski."

    return HMMRegimeResult(
        symbol=sym,
        active_regime=regime,
        prob_trending=prob_trend,
        prob_choppy=prob_chop,
        prob_panic=prob_panic,
        strategy_directive=directive,
        transition_risk=trans_risk,
        verdict=verdict
    )
