"""Snapback Dip Avcısı ve Makro Rejim Router'ı.

Endpoints:
- GET /api/signals/snapback: Canlı S2/S6 1H panik dip fırsatlarını tarar ve döner.
- GET /api/signals/macro-regime: BTC 1H EMA200 Makro Rejim Kalkanı durumunu döner.
"""

import time
from fastapi import APIRouter, Query
from app.config import config
from app.macro_sentiment_service import get_btc_compass, get_macro_sentiment
from app.snapback_service import scan_snapback_opportunities

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/snapback")
async def get_snapback_signals(force_refresh: bool = Query(False, description="Önbelleği baypas et")):
    """1H RSI(7) < 20 ve RSI(14) < 30 aşırı satım panik dip fırsatlarını tarar."""
    result = await scan_snapback_opportunities(force_refresh=force_refresh)
    return result


@router.get("/macro-regime")
async def get_macro_regime_status():
    """1H BTC EMA200 Makro Rejim Kalkanı ve genel piyasa stres durumunu döner."""
    compass = await get_btc_compass()
    sentiment = await get_macro_sentiment()
    shield_enabled = bool(getattr(config, "BTC_REGIME_SHIELD_ENABLED", True))

    is_above = bool(compass.get("is_btc_above_ema200", True))
    regime_shield_active = bool(shield_enabled and not is_above)

    return {
        "timestamp": time.time(),
        "btc_symbol": compass.get("btc_symbol", "BTCTRY"),
        "btc_price": compass.get("btc_price"),
        "btc_1h_ema200": compass.get("btc_1h_ema200"),
        "is_btc_above_ema200": is_above,
        "shield_enabled": shield_enabled,
        "regime_shield_active": regime_shield_active,
        "btc_trend_state": compass.get("btc_trend_state", "SIDEWAYS"),
        "btc_5m_change_pct": compass.get("btc_5m_change_pct", 0.0),
        "btc_15m_change_pct": compass.get("btc_15m_change_pct", 0.0),
        "market_stress_level": sentiment.get("market_stress_level", "HEALTHY"),
        "allow_new_longs": sentiment.get("allow_new_longs", True),
        "fear_and_greed_score": sentiment.get("fear_and_greed_score", 50),
        "fear_and_greed_class": sentiment.get("fear_and_greed_class", "Neutral"),
        "summary": sentiment.get("summary", ""),
    }
