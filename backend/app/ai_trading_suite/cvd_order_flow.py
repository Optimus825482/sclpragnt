"""Cumulative Volume Delta (CVD) & Order Flow Absorption Auditor.

Features:
- Aggressor Buy Volume vs. Aggressor Sell Volume Delta
- Cumulative Volume Delta (CVD) divergence detection
- Iceberg limit order absorption identification:
  * Bull Absorption: Heavy selling absorbed by passive buy wall (Accumulation)
  * Bear Absorption: Heavy buying absorbed by passive sell wall (Distribution / Bull Trap)
- Microstructure flow confirmation for Scalper entries.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class CVDOrderFlowResult(BaseModel):
    symbol: str
    current_price: float
    volume_delta: float = Field(..., description="Net delta (Buy Volume - Sell Volume)")
    delta_ratio: float = Field(..., description="Ratio of Delta to Total Volume (-1.0 to +1.0)")
    cvd_direction: str = Field(..., description="AGGRESSIVE_BUYING, AGGRESSIVE_SELLING, or NEUTRAL")
    absorption_detected: str = Field(..., description="BULL_ABSORPTION, BEAR_ABSORPTION, or NONE")
    order_flow_confirmed: bool
    absorption_warning: Optional[str] = None
    verdict: str


def evaluate_cvd_order_flow(
    symbol: str,
    current_price: float,
    recent_price_change_pct: float,
    buy_volume: float,
    sell_volume: float
) -> CVDOrderFlowResult:
    """Audits aggressor volume delta and detects iceberg absorption traps."""
    sym = symbol.upper()
    total_vol = max(buy_volume + sell_volume, 0.0001)
    delta = buy_volume - sell_volume
    delta_ratio = max(-1.0, min(1.0, delta / total_vol))

    if delta_ratio > 0.20:
        direction = "AGGRESSIVE_BUYING"
    elif delta_ratio < -0.20:
        direction = "AGGRESSIVE_SELLING"
    else:
        direction = "NEUTRAL"

    # Iceberg Absorption Detection:
    # Bear Absorption: High positive delta (aggressive buying) BUT price failed to rise or declined
    # Bull Absorption: High negative delta (aggressive selling) BUT price held steady or rose
    absorption = "NONE"
    warning = None
    confirmed = True

    if delta_ratio > 0.35 and recent_price_change_pct <= 0.05:
        absorption = "BEAR_ABSORPTION"
        warning = "Ayı Emilimi (Bear Absorption): Yoğun piyasa alımları pasif satış duvarı (Iceberg) tarafından emiliyor! Boğa tuzağı riski."
        confirmed = False
    elif delta_ratio < -0.35 and recent_price_change_pct >= -0.05:
        absorption = "BULL_ABSORPTION"
        warning = "Boğa Emilimi (Bull Absorption): Yoğun satışlar pasif kurumsal alış duvarı tarafından toplanıyor! Taban desteği güçlü."
        confirmed = True
    else:
        confirmed = (direction == "AGGRESSIVE_BUYING" and recent_price_change_pct > 0) or (direction == "NEUTRAL")

    if absorption == "BEAR_ABSORPTION":
        verdict = f"Emir Akışı Uyarısı: {warning}"
    elif absorption == "BULL_ABSORPTION":
        verdict = f"Emir Akışı Onayı: {warning}"
    elif direction == "AGGRESSIVE_BUYING":
        verdict = f"CVD Motoru: Alıcılar agresif (%{int(delta_ratio*100)} pozitif delta), fiyat artışını destekliyor."
    elif direction == "AGGRESSIVE_SELLING":
        verdict = f"CVD Motoru: Satıcılar tahtaya baskı yapıyor (%{int(abs(delta_ratio)*100)} negatif delta)."
    else:
        verdict = "CVD Motoru: Alış ve satış deltası dengeli."

    return CVDOrderFlowResult(
        symbol=sym,
        current_price=round(current_price, 6),
        volume_delta=round(delta, 2),
        delta_ratio=round(delta_ratio, 3),
        cvd_direction=direction,
        absorption_detected=absorption,
        order_flow_confirmed=confirmed,
        absorption_warning=warning,
        verdict=verdict
    )
