"""
Vibe-Trading inspired Sentiment, Social Momentum & Breakout Tracker.
Combines price-volume velocity with sentiment buzz to qualify momentum breakouts.
"""
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class VibeMetric:
    symbol: str
    asset_type: str  # "SPOT" or "FOREX"
    price_change_pct: float
    volume_ratio: float  # Current volume / 20-period avg volume (RVOL)
    social_buzz_score: float  # -1.0 to +1.0
    sentiment_velocity: float  # Rate of sentiment change
    orderbook_depth_ratio: float  # Bid depth / Ask depth


@dataclass
class VibeAnalysisResult:
    symbol: str
    vibe_score: float  # -1.0 to +1.0
    vibe_category: str  # "HYPER_BULLISH", "BULLISH_VIBE", "NEUTRAL_CHOP", "BEARISH_VIBE", "PANIC_SELL"
    breakout_confirmed: bool
    is_fomo_trap: bool
    momentum_thrust: float
    confidence: float
    commentary: str


class VibeBreakoutTracker:
    """
    Measures the energetic 'vibe' of price action and volume divergence.
    Distinguishes genuine institutional breakouts from retail FOMO traps.
    """

    def analyze_vibe(self, metric: VibeMetric) -> VibeAnalysisResult:
        # 1. Price-Volume alignment (Institutional thrust)
        # Genuine breakout requires high RVOL (> 1.8x) and positive orderbook support
        vol_boost = float(np.clip((metric.volume_ratio - 1.0) * 0.4, -0.5, 0.8))
        book_boost = float(np.clip((metric.orderbook_depth_ratio - 1.0) * 0.3, -0.4, 0.4))
        
        # 2. Vibe composite score
        price_norm = float(np.clip(metric.price_change_pct / 3.0, -1.0, 1.0))
        raw_vibe = (price_norm * 0.40) + (metric.social_buzz_score * 0.25) + vol_boost + book_boost
        vibe_score = float(np.clip(raw_vibe, -1.0, 1.0))

        # 3. Detect FOMO traps: high social buzz and price surge, but RVOL or orderbook depth is weak
        is_fomo_trap = False
        if metric.price_change_pct > 2.0 and metric.social_buzz_score > 0.6:
            if metric.volume_ratio < 1.1 or metric.orderbook_depth_ratio < 0.85:
                is_fomo_trap = True

        # 4. Breakout confirmation
        breakout_confirmed = (
            metric.volume_ratio >= 1.6 and
            metric.price_change_pct > 0.8 and
            metric.orderbook_depth_ratio >= 1.2 and
            not is_fomo_trap
        )

        # Categorize
        if vibe_score >= 0.65:
            cat = "HYPER_BULLISH"
        elif vibe_score >= 0.20:
            cat = "BULLISH_VIBE"
        elif vibe_score <= -0.65:
            cat = "PANIC_SELL"
        elif vibe_score <= -0.20:
            cat = "BEARISH_VIBE"
        else:
            cat = "NEUTRAL_CHOP"

        commentary = (
            f"Vibe Score: {vibe_score:.2f} ({cat}). "
            f"RVOL: {metric.volume_ratio:.2f}x. "
            f"{'FOMO trap risk detected!' if is_fomo_trap else 'Momentum supported by liquidity.'}"
        )

        return VibeAnalysisResult(
            symbol=metric.symbol,
            vibe_score=round(vibe_score, 4),
            vibe_category=cat,
            breakout_confirmed=breakout_confirmed,
            is_fomo_trap=is_fomo_trap,
            momentum_thrust=round(metric.volume_ratio * max(0.1, metric.price_change_pct), 3),
            confidence=round(min(1.0, abs(vibe_score) * 1.2), 3),
            commentary=commentary
        )
