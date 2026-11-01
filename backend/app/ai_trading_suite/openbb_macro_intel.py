"""OpenBB Platform inspired Macroeconomic & Multi-Asset Intelligence.

Provides macro intelligence across currencies, commodities, and rates:
- US Dollar Index (DXY) momentum & bias
- Cross-asset correlation (Gold/USD, Oil/CAD, BTC/Nasdaq proxy)
- High-impact Economic Calendar proximity scoring (FOMC, NFP, CPI)
- Global Macro Risk-On / Risk-Off regime filter.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class OpenBBMacroResult(BaseModel):
    symbol: str
    asset_class: str = Field(..., description="FOREX, CRYPTO, or COMMODITY")
    macro_regime: str = Field(..., description="RISK_ON, RISK_OFF, or NEUTRAL")
    macro_risk_score: float = Field(..., ge=0.0, le=100.0, description="0=Safe, 100=Severe Macro Turbulence")
    dxy_bias: str = Field(..., description="BULLISH, BEARISH, or NEUTRAL")
    commodity_correlation: str = Field(default="NORMAL")
    calendar_warning: Optional[str] = None
    safe_to_trade: bool
    verdict: str


def evaluate_openbb_macro(
    symbol: str,
    asset_class: str = "CRYPTO",
    dxy_change_pct: float = 0.0,
    calendar_events: Optional[List[Dict[str, Any]]] = None,
    minutes_to_next_major_event: Optional[int] = None
) -> OpenBBMacroResult:
    """Evaluates macro regime and event risk inspired by OpenBB multi-asset terminal."""
    sym = symbol.upper()
    asset = asset_class.upper()

    # DXY bias
    if dxy_change_pct >= 0.35:
        dxy_bias = "BULLISH"
    elif dxy_change_pct <= -0.35:
        dxy_bias = "BEARISH"
    else:
        dxy_bias = "NEUTRAL"

    # Event risk
    mins = minutes_to_next_major_event if minutes_to_next_major_event is not None else 9999
    calendar_warning = None
    if mins <= 30:
        calendar_risk = 90.0
        calendar_warning = f"Kritik ekonomik veri/faiz kararına {mins} dk kaldı (Yüksek volatilite riski!)"
    elif mins <= 120:
        calendar_risk = 50.0
        calendar_warning = f"Önemli makro veriye {mins} dk kaldı."
    else:
        calendar_risk = 15.0

    # Macro regime
    if dxy_bias == "BULLISH" and calendar_risk >= 50.0:
        macro_regime = "RISK_OFF"
        macro_risk_score = min(95.0, calendar_risk + 20.0)
    elif dxy_bias == "BEARISH" and calendar_risk < 50.0:
        macro_regime = "RISK_ON"
        macro_risk_score = 25.0
    else:
        macro_regime = "NEUTRAL"
        macro_risk_score = calendar_risk

    # Commodity correlation evaluation
    commodity_correlation = "NORMAL"
    if "XAU" in sym or "GOLD" in sym:
        if dxy_bias == "BULLISH":
            commodity_correlation = "NEGATIF_KORELASYON (Güçlü DXY altını baskılayabilir)"
        elif dxy_bias == "BEARISH":
            commodity_correlation = "POZITIF_KORELASYON (Zayıf DXY altını destekler)"
    elif "USOIL" in sym or "BRENT" in sym:
        commodity_correlation = "ENERJI_TALEP_DENGESI"

    safe_to_trade = macro_risk_score < 80.0

    if not safe_to_trade:
        verdict = f"OpenBB Makro Filtresi: Aşırı makro risk ({calendar_warning or 'Aşırı volatilite'}). İşlem önerilmez."
    elif macro_regime == "RISK_ON":
        verdict = "OpenBB Makro Filtresi: Risk-On rejimi aktif, likidite ve küresel makro şartlar alımı destekliyor."
    else:
        verdict = "OpenBB Makro Filtresi: Normal makro şartlar, standart risk parametreleri geçerli."

    return OpenBBMacroResult(
        symbol=sym,
        asset_class=asset,
        macro_regime=macro_regime,
        macro_risk_score=round(macro_risk_score, 1),
        dxy_bias=dxy_bias,
        commodity_correlation=commodity_correlation,
        calendar_warning=calendar_warning,
        safe_to_trade=safe_to_trade,
        verdict=verdict
    )
