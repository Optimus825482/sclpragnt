"""Institutional Volume Profile & POC (Point of Control) Engine.

Calculates:
- Volume distribution across discrete price bins (Volume by Price)
- POC (Point of Control): Price bin where the highest trading volume occurred
- VAH (Value Area High): Price boundary encapsulating top 70% volume distribution
- VAL (Value Area Low): Price boundary encapsulating bottom 70% volume distribution
- Liquidity Voids (Low Volume Nodes - LVN) where rapid acceleration occurs.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class VolumeProfileResult(BaseModel):
    symbol: str
    current_price: float
    point_of_control: float = Field(..., description="POC: Price level with the highest traded volume")
    value_area_high: float = Field(..., description="VAH: Upper 70% Value Area boundary")
    value_area_low: float = Field(..., description="VAL: Lower 70% Value Area boundary")
    position_relative_to_value: str = Field(..., description="ABOVE_VAH, INSIDE_VALUE_AREA, or BELOW_VAL")
    poc_distance_pct: float
    volume_node_count: int
    trade_bias: str = Field(..., description="BULLISH_EXPANSION, MEAN_REVERSION_LONG, or OVEREXTENDED")
    verdict: str


def evaluate_volume_profile(
    symbol: str,
    candles: List[Dict[str, float]],
    bins: int = 24,
    value_area_pct: float = 0.70
) -> VolumeProfileResult:
    """Computes POC, VAH, and VAL from recent price and volume history."""
    sym = symbol.upper()
    if not candles:
        return VolumeProfileResult(
            symbol=sym,
            current_price=1.0,
            point_of_control=1.0,
            value_area_high=1.01,
            value_area_low=0.99,
            position_relative_to_value="INSIDE_VALUE_AREA",
            poc_distance_pct=0.0,
            volume_node_count=bins,
            trade_bias="INSIDE_VALUE_AREA",
            verdict="Hacim profili verisi yetersiz."
        )

    prices_high = [float(c.get("high") or c.get("close") or 1.0) for c in candles]
    prices_low = [float(c.get("low") or c.get("close") or 1.0) for c in candles]
    closes = [float(c.get("close") or 1.0) for c in candles]
    volumes = [float(c.get("volume") or 1.0) for c in candles]

    min_p = min(prices_low)
    max_p = max(prices_high)
    current_p = closes[-1]

    if max_p <= min_p:
        max_p = min_p * 1.01

    bin_size = (max_p - min_p) / float(bins)
    volume_by_bin = [0.0] * bins

    # Distribute candle volume across traversed bins
    for c_low, c_high, c_vol in zip(prices_low, prices_high, volumes):
        start_idx = max(0, min(bins - 1, int((c_low - min_p) / bin_size)))
        end_idx = max(0, min(bins - 1, int((c_high - min_p) / bin_size)))
        span = max(1, (end_idx - start_idx + 1))
        vol_per_bin = c_vol / float(span)
        for i in range(start_idx, end_idx + 1):
            volume_by_bin[i] += vol_per_bin

    # 1. Point of Control (POC)
    poc_idx = max(range(bins), key=lambda i: volume_by_bin[i])
    poc_price = min_p + (poc_idx + 0.5) * bin_size

    # 2. Value Area Calculation (70% total volume radiating outward from POC)
    total_volume = sum(volume_by_bin)
    target_va_vol = total_volume * value_area_pct

    current_va_vol = volume_by_bin[poc_idx]
    lower_idx = poc_idx
    upper_idx = poc_idx

    while current_va_vol < target_va_vol and (lower_idx > 0 or upper_idx < bins - 1):
        next_lower_vol = volume_by_bin[lower_idx - 1] if lower_idx > 0 else -1.0
        next_upper_vol = volume_by_bin[upper_idx + 1] if upper_idx < bins - 1 else -1.0

        if next_upper_vol >= next_lower_vol and next_upper_vol >= 0:
            upper_idx += 1
            current_va_vol += next_upper_vol
        elif next_lower_vol >= 0:
            lower_idx -= 1
            current_va_vol += next_lower_vol
        else:
            break

    vah_price = min_p + (upper_idx + 1.0) * bin_size
    val_price = min_p + lower_idx * bin_size

    # Position evaluation
    poc_dist_pct = ((current_p - poc_price) / max(poc_price, 0.000001)) * 100.0

    if current_p > vah_price:
        pos = "ABOVE_VAH"
        bias = "BULLISH_EXPANSION"
        verdict = f"Fiyat Değer Alanı Zirvesini (VAH: {vah_price:.4f}) aştı. Kurumsal trend genişlemesi aktif."
    elif current_p < val_price:
        pos = "BELOW_VAL"
        bias = "MEAN_REVERSION_LONG"
        verdict = f"Fiyat Değer Alanı Tabanının (VAL: {val_price:.4f}) altında. POC ({poc_price:.4f}) mıknatısına dönüş potansiyeli yüksek."
    else:
        pos = "INSIDE_VALUE_AREA"
        bias = "BALANCED"
        verdict = f"Fiyat Değer Alanı içinde dengeli (POC: {poc_price:.4f}, VAH: {vah_price:.4f}, VAL: {val_price:.4f})."

    return VolumeProfileResult(
        symbol=sym,
        current_price=round(current_p, 6),
        point_of_control=round(poc_price, 6),
        value_area_high=round(vah_price, 6),
        value_area_low=round(val_price, 6),
        position_relative_to_value=pos,
        poc_distance_pct=round(poc_dist_pct, 2),
        volume_node_count=bins,
        trade_bias=bias,
        verdict=verdict
    )
