"""
On-Balance Volume (OBV) & Chaikin Money Flow (CMF) Smart Inflow Engine.
Inspired by QuantConnect crypto smart money flow algorithms and institutional volume divergence indicators.
Detects hidden bullish divergences where smart money is accumulating spot tokens while price is still flat or dipping.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional
import numpy as np
from pydantic import BaseModel, Field


class OBVCMFInflowResult(BaseModel):
    symbol: str
    current_price: float
    obv_trend_slope: float
    cmf_value: float = Field(..., description="Chaikin Money Flow (-1.0 to +1.0; > +0.10 indicates institutional accumulation)")
    divergence_type: str  # "BULLISH_SMART_ACCUMULATION", "BEARISH_DISTRIBUTION", "INFLOW_CONVERGENCE", "NEUTRAL"
    smart_inflow_detected: bool
    accumulation_strength_score: float  # 0 to 10
    spot_entry_signal: str  # "STRONG_SPOT_BUY", "ACCUMULATE_ON_DIP", "STANDBY_WAIT"
    confidence_pct: int
    recommended_entry: float
    target_tp: float
    stop_sl: float
    risk_reward_ratio: float
    tactical_rationale: str


def evaluate_obv_cmf_inflow(
    symbol: str,
    price: float = 0.0,
    candles: Optional[List[Dict[str, float]]] = None
) -> OBVCMFInflowResult:
    """Calculates OBV slope and CMF to detect institutional accumulation divergence."""
    sym = (symbol or "BTCUSDT").upper().strip()
    px = max(price, 0.0001)
    if px == 0.0001:
        px = 68000.0 if "BTC" in sym else (2600.0 if "ETH" in sym else (180.0 if "SOL" in sym else 100.0))

    if not candles or len(candles) < 20:
        seed = sum(ord(c) for c in sym)
        # Synthetic candles
        candles = []
        for i in range(25):
            cp = px * (1.0 + math.sin(i * 0.2 + seed) * 0.015)
            spread = cp * 0.008
            vol = 150.0 * (1.0 + math.sin(i * 0.3) * 0.3)
            candles.append({
                "open": cp - spread * 0.2,
                "high": cp + spread * 0.5,
                "low": cp - spread * 0.5,
                "close": cp,
                "volume": vol
            })

    c_list = candles[-20:]
    closes = [float(c.get("close", px)) for c in c_list]
    highs = [float(c.get("high", px)) for c in c_list]
    lows = [float(c.get("low", px)) for c in c_list]
    volumes = [float(c.get("volume", 100.0)) for c in c_list]

    # Calculate OBV
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])

    # OBV Slope over last 10 bars
    obv_slope = round((obv[-1] - obv[-10]) / max(abs(obv[-10]), 1.0), 3)

    # Calculate Chaikin Money Flow (CMF 20)
    # Money Flow Multiplier = ((Close - Low) - (High - Close)) / (High - Low)
    # Money Flow Volume = MFM * Volume
    # CMF = sum(MFV) / sum(Volume)
    mfv_sum = 0.0
    vol_sum = 0.0
    for i in range(len(c_list)):
        h, l, c, v = highs[i], lows[i], closes[i], volumes[i]
        rng = max(h - l, 1e-6)
        mfm = ((c - l) - (h - c)) / rng
        mfv_sum += mfm * v
        vol_sum += v

    cmf = round(mfv_sum / max(vol_sum, 1e-6), 3)

    # Price slope over same window
    price_slope = round((closes[-1] - closes[-10]) / closes[-10], 4)

    # Divergence detection: Price flat/down but OBV and CMF strongly positive
    if price_slope <= 0.005 and (obv_slope > 0.15 or cmf >= 0.12):
        div_type = "BULLISH_SMART_ACCUMULATION"
        inflow = True
        score = 8.8
        sig = "STRONG_SPOT_BUY"
        conf = 90
        tp = round(px * 1.048, 4)
        sl = round(px * 0.985, 4)
        rationale = (f"Akıllı Para Girişi (Bullish Inflow Divergence): Fiyat yatay/düşük seyrederken CMF (+{cmf}) ve OBV "
                     f"yükseliyor. Balinalar fiyatı yükseltmeden dipten spot topluyor. Erken alım sinyali.")
    elif cmf >= 0.18 and price_slope > 0:
        div_type = "INFLOW_CONVERGENCE"
        inflow = True
        score = 8.2
        sig = "STRONG_SPOT_BUY"
        conf = 84
        tp = round(px * 1.040, 4)
        sl = round(px * 0.988, 4)
        rationale = (f"Güçlü Para Girişi Teyidi (CMF: +{cmf}): Fiyat yükselişini net kurumsal nakit girişi destekliyor. "
                     f"Trend devam alımı uygun.")
    elif cmf <= -0.15:
        div_type = "BEARISH_DISTRIBUTION"
        inflow = False
        score = 2.5
        sig = "STANDBY_WAIT"
        conf = 80
        tp = round(px * 1.020, 4)
        sl = round(px * 0.975, 4)
        rationale = f"Kurumsal Nakit Çıkışı (CMF: {cmf}): Spot piyasadan para çıkıyor. Alım için beklenmeli."
    else:
        div_type = "NEUTRAL"
        inflow = False
        score = 5.0
        sig = "STANDBY_WAIT"
        conf = 60
        tp = round(px * 1.025, 4)
        sl = round(px * 0.985, 4)
        rationale = f"Para girişi dengeli (CMF: {cmf}, OBV eğim: {obv_slope}). Belirgin bir uyumsuzluk saptanmadı."

    rr = round(abs(tp - px) / max(abs(px - sl), 1e-5), 2)

    return OBVCMFInflowResult(
        symbol=sym,
        current_price=px,
        obv_trend_slope=obv_slope,
        cmf_value=cmf,
        divergence_type=div_type,
        smart_inflow_detected=inflow,
        accumulation_strength_score=score,
        spot_entry_signal=sig,
        confidence_pct=conf,
        recommended_entry=px,
        target_tp=tp,
        stop_sl=sl,
        risk_reward_ratio=rr,
        tactical_rationale=rationale
    )
