"""
Liquidation Heatmap & Stop-Hunt Radar (inspired by Open-Perp-Tracker & Coinglass algorithms).
Estimates concentrated liquidation leverage bands (25x, 50x, 100x) and institutional stop hunt magnetic zones.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class LiquidationBand(BaseModel):
    tier: str  # "100x_LEVERAGE", "50x_LEVERAGE", "25x_LEVERAGE"
    side: str  # "LONG_LIQUIDATION_BELOW", "SHORT_LIQUIDATION_ABOVE"
    price_level: float
    distance_pct: float
    estimated_intensity: str  # "HIGH", "EXTREME", "MODERATE"


class LiquidationRadarResult(BaseModel):
    symbol: str
    current_price: float
    magnetic_target_zone: float
    magnetic_target_side: str  # "HUNT_LONGS_DOWN", "HUNT_SHORTS_UP", "NEUTRAL"
    nearest_stop_cluster_distance_pct: float
    liquidation_bands: List[LiquidationBand]
    stop_hunt_risk_level: str  # "EXTREME_HUNT_IMMINENT", "ELEVATED", "LOW"
    tactical_advice: str


def evaluate_liquidation_radar(
    symbol: str,
    price: float,
    high_24h: Optional[float] = None,
    low_24h: Optional[float] = None,
    atr: Optional[float] = None
) -> LiquidationRadarResult:
    """Estimates leveraged liquidation clusters and institutional stop-hunt levels."""
    sym = (symbol or "BTCUSDT").upper().strip()
    px = max(price, 0.00001)

    h24 = high_24h or (px * 1.03)
    l24 = low_24h or (px * 0.97)
    a = atr or (px * 0.015)

    bands: List[LiquidationBand] = []

    # 1. Long Liquidations (below current price)
    # 100x long liquidations cluster ~0.8% below entry
    p_100x_long = round(px * 0.992, 4)
    # 50x long liquidations cluster ~1.8% below
    p_50x_long = round(px * 0.982, 4)
    # 25x long liquidations cluster ~3.8% below (often near 24h low)
    p_25x_long = round(min(l24, px * 0.962), 4)

    bands.append(LiquidationBand(tier="100x_LEVERAGE", side="LONG_LIQUIDATION_BELOW", price_level=p_100x_long, distance_pct=round(((p_100x_long - px) / px) * 100, 2), estimated_intensity="HIGH"))
    bands.append(LiquidationBand(tier="50x_LEVERAGE", side="LONG_LIQUIDATION_BELOW", price_level=p_50x_long, distance_pct=round(((p_50x_long - px) / px) * 100, 2), estimated_intensity="EXTREME"))
    bands.append(LiquidationBand(tier="25x_LEVERAGE", side="LONG_LIQUIDATION_BELOW", price_level=p_25x_long, distance_pct=round(((p_25x_long - px) / px) * 100, 2), estimated_intensity="HIGH"))

    # 2. Short Liquidations (above current price)
    # 100x short liquidations cluster ~0.8% above entry
    p_100x_short = round(px * 1.008, 4)
    # 50x short liquidations cluster ~1.8% above
    p_50x_short = round(px * 1.018, 4)
    # 25x short liquidations cluster ~3.8% above (often near 24h high)
    p_25x_short = round(max(h24, px * 1.038), 4)

    bands.append(LiquidationBand(tier="100x_LEVERAGE", side="SHORT_LIQUIDATION_ABOVE", price_level=p_100x_short, distance_pct=round(((p_100x_short - px) / px) * 100, 2), estimated_intensity="HIGH"))
    bands.append(LiquidationBand(tier="50x_LEVERAGE", side="SHORT_LIQUIDATION_ABOVE", price_level=p_50x_short, distance_pct=round(((p_50x_short - px) / px) * 100, 2), estimated_intensity="EXTREME"))
    bands.append(LiquidationBand(tier="25x_LEVERAGE", side="SHORT_LIQUIDATION_ABOVE", price_level=p_25x_short, distance_pct=round(((p_25x_short - px) / px) * 100, 2), estimated_intensity="HIGH"))

    # Determine dominant magnetic direction based on distance to 24h extremes
    dist_to_low = abs(px - l24)
    dist_to_high = abs(h24 - px)

    if dist_to_high < dist_to_low:
        magnetic_target = p_50x_short
        magnetic_side = "HUNT_SHORTS_UP"
        risk_level = "ELEVATED" if abs(px - p_50x_short) / px < 0.02 else "LOW"
        advice = f"Fiyat {p_50x_short:.4f} bölgesindeki 50x short likidasyonlarını süpürmeye istekli; yukarı fitil avı beklenebilir."
    else:
        magnetic_target = p_50x_long
        magnetic_side = "HUNT_LONGS_DOWN"
        risk_level = "EXTREME_HUNT_IMMINENT" if abs(px - p_50x_long) / px < 0.015 else "ELEVATED"
        advice = f"Fiyat {p_50x_long:.4f} bölgesindeki long stoplarını patlatmaya yakın; dip süpürme (sweep) bitmeden acele alım yapılmamalı."

    nearest_dist = min(abs(b.distance_pct) for b in bands)

    return LiquidationRadarResult(
        symbol=sym,
        current_price=round(px, 4),
        magnetic_target_zone=round(magnetic_target, 4),
        magnetic_target_side=magnetic_side,
        nearest_stop_cluster_distance_pct=nearest_dist,
        liquidation_bands=bands,
        stop_hunt_risk_level=risk_level,
        tactical_advice=advice
    )
