from dataclasses import dataclass
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class JesseRiskResult(BaseModel):
    symbol: str
    entry_price: float
    optimized_sl: float
    optimized_tp1: float
    optimized_tp2: float
    risk_reward_ratio: float
    trailing_stop_offset: float
    volatility_mode: str
    execution_efficiency_score: float = Field(..., ge=0.0, le=100.0)
    passes_jesse_standard: bool
    verdict: str


def evaluate_jesse_risk(
    symbol: str,
    entry_price: float,
    atr: float,
    win_rate_estimate: float = 0.55,
    volatility_mode: str = "NORMAL"
) -> JesseRiskResult:
    """Calculates Jesse-inspired dynamic SL, TP and trailing parameters."""
    if isinstance(win_rate_estimate, str):
        volatility_mode = win_rate_estimate
        win_rate_estimate = 0.55
    else:
        try:
            win_rate_estimate = float(win_rate_estimate)
        except Exception:
            win_rate_estimate = 0.55

    px = max(float(entry_price), 0.000001)
    effective_atr = max(float(atr), px * 0.005)

    mode = str(volatility_mode).upper()
    if mode == "HIGH":
        sl_mult = 1.6
        tp1_mult = 2.5
        tp2_mult = 4.0
        trailing_mult = 1.3
    elif mode == "LOW":
        sl_mult = 1.2
        tp1_mult = 1.9
        tp2_mult = 3.0
        trailing_mult = 0.9
    else:  # NORMAL
        sl_mult = 1.4
        tp1_mult = 2.2
        tp2_mult = 3.5
        trailing_mult = 1.1

    sl_dist = effective_atr * sl_mult
    tp1_dist = effective_atr * tp1_mult
    tp2_dist = effective_atr * tp2_mult

    optimized_sl = max(px * 0.01, px - sl_dist)
    optimized_tp1 = px + tp1_dist
    optimized_tp2 = px + tp2_dist

    rr = round(tp1_dist / max(sl_dist, 0.000001), 2)
    trailing_offset = round(effective_atr * trailing_mult, 6)

    # Jesse efficiency score: Reward:Risk combined with win rate
    expected_value = (win_rate_estimate * rr) - ((1.0 - win_rate_estimate) * 1.0)
    score_raw = 50.0 + (expected_value * 35.0)
    execution_efficiency_score = round(max(10.0, min(99.0, score_raw)), 1)

    passes = rr >= 1.40 and execution_efficiency_score >= 55.0

    if passes:
        verdict = f"Jesse Algoritmik Risk Onaylandı: R:R = {rr:.2f} (Hedef 1: {optimized_tp1:.4f}, Stop: {optimized_sl:.4f})"
    else:
        verdict = f"Jesse Risk Reddi: R:R oranı ({rr:.2f}) veya verimlilik skoru yetersiz."

    return JesseRiskResult(
        symbol=symbol.upper(),
        entry_price=round(px, 6),
        optimized_sl=round(optimized_sl, 6),
        optimized_tp1=round(optimized_tp1, 6),
        optimized_tp2=round(optimized_tp2, 6),
        risk_reward_ratio=rr,
        trailing_stop_offset=trailing_offset,
        volatility_mode=mode,
        execution_efficiency_score=execution_efficiency_score,
        passes_jesse_standard=passes,
        verdict=verdict
    )
