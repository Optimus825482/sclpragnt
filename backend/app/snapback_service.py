"""S2/S6 Snapback Dip Avcısı (Mean Reversion Dip Hunter).

Scalper Global kuant replay testlerinde (10 coin x 9000 saat IS/OOS) kanıtlanmış strateji:
- 1H zaman diliminde RSI(7) < 20 ve RSI(14) < 30 olan aşırı satım panik diplerini tespit eder.
- BTC 1H EMA200 üzerindeyse "A+" (Boğa destekli güvenli dip), altındaysa "B" (Ayı içi tepki) derecelendirir.
- Çıkış Kuralı: RSI(7) > 50 Dinamik Çıkış
- Stop-Loss: 1.5 x ATR(14)
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.config import config
from app.binance_tr_public import klines as fetch_klines
from app.technical_analysis import _atr, _rsi
from app.macro_sentiment_service import get_btc_compass

logger = logging.getLogger(__name__)

SNAPBACK_CACHE_TTL = 30.0  # 30 saniye önbellek
_SNAPBACK_CACHE: Optional[tuple[float, Dict[str, Any]]] = None


async def scan_single_symbol(symbol: str, btc_is_above_ema: bool) -> Optional[Dict[str, Any]]:
    """Tek bir sembol için 1H RSI7, RSI14 ve ATR14 hesaplayarak Snapback dip koşulunu denetler."""
    try:
        k1h = await fetch_klines(symbol, "1h", limit=50)
        if not k1h or len(k1h) < 20:
            return None

        closes = [float(k[4]) for k in k1h]
        highs = [float(k[2]) for k in k1h]
        lows = [float(k[3]) for k in k1h]
        current_price = closes[-1]

        rsi7 = _rsi(closes, 7)
        rsi14 = _rsi(closes, 14)
        atr14 = _atr(highs, lows, closes, 14)

        if rsi7 is None or rsi14 is None:
            return None

        # S2/S6 Snapback Dip Koşulu: RSI(7) < 20 VE RSI(14) < 30
        if rsi7 < 20.0 and rsi14 < 30.0:
            # BTC 1H EMA200 üzerindeyse A+, altındaysa B
            grade = "A+" if btc_is_above_ema else "B"

            if atr14 and atr14 > 0:
                sl_dist = 1.5 * atr14
                stop_loss = max(0.0, current_price - sl_dist)
                stop_loss_pct = round((sl_dist / current_price) * 100.0, 2)
            else:
                sl_dist = current_price * 0.03
                stop_loss = current_price * 0.97
                stop_loss_pct = 3.0

            # Dinamik kalite skoru (Aşırı satım derinleştikçe skor yükselir)
            oversold_bonus = (20.0 - rsi7) + (30.0 - rsi14)
            base_score = 80.0 if grade == "A+" else 70.0
            quality_score = round(min(99.0, base_score + oversold_bonus * 0.7), 1)

            return {
                "symbol": symbol,
                "current_price": current_price,
                "rsi7": round(float(rsi7), 2),
                "rsi14": round(float(rsi14), 2),
                "atr14": round(float(atr14), 4) if atr14 else None,
                "stop_loss": round(float(stop_loss), 4),
                "stop_loss_pct": stop_loss_pct,
                "exit_condition": "RSI(7) > 50",
                "grade": grade,
                "quality_score": quality_score,
                "macro_regime": "BULL_REGIME" if btc_is_above_ema else "BEAR_REGIME",
                "detected_at": time.time(),
            }
    except Exception as exc:
        logger.debug("Snapback dip tarama hatası (%s): %s", symbol, exc)
    return None


async def scan_snapback_opportunities(force_refresh: bool = False) -> Dict[str, Any]:
    """Tüm yapılandırılmış sembolleri tarayarak canlı S2/S6 dip fırsatlarını döndürür."""
    global _SNAPBACK_CACHE
    now = time.time()

    if not force_refresh and _SNAPBACK_CACHE and (now - _SNAPBACK_CACHE[0]) < SNAPBACK_CACHE_TTL:
        return _SNAPBACK_CACHE[1]

    # BTC Pusula ve 1H EMA200 durumunu al
    btc_compass = await get_btc_compass()
    btc_is_above = bool(btc_compass.get("is_btc_above_ema200", True))
    btc_ema200 = btc_compass.get("btc_1h_ema200")
    regime_shield_active = bool(btc_compass.get("regime_shield_active", not btc_is_above))

    # Taranacak semboller (varsayılan: config.SYMBOLS)
    symbols = list(getattr(config, "SYMBOLS", []))
    if not symbols:
        symbols = [
            "BTCTRY", "ETHTRY", "SOLTRY", "XRPTRY", "ADATRY", "AVAXTRY",
            "LINKTRY", "NEARTRY", "APTTRY", "ARBTRY", "OPTRY", "SUITRY",
            "DOGETRY", "LTCTRY", "BNBTRY", "INJTRY", "WLDTRY", "DOTTRY"
        ]

    tasks = [scan_single_symbol(sym, btc_is_above) for sym in symbols]
    scan_results = await asyncio.gather(*tasks, return_exceptions=True)

    opportunities: List[Dict[str, Any]] = []
    for item in scan_results:
        if isinstance(item, dict) and item:
            opportunities.append(item)

    # En kaliteli/en derin aşırı satımdan en aza doğru sırala
    opportunities.sort(key=lambda x: (x.get("grade") == "A+", x.get("quality_score", 0)), reverse=True)

    result = {
        "timestamp": now,
        "macro_regime": {
            "btc_symbol": btc_compass.get("btc_symbol", "BTCTRY"),
            "btc_price": btc_compass.get("btc_price"),
            "btc_1h_ema200": btc_ema200,
            "is_btc_above_ema200": btc_is_above,
            "regime_shield_active": regime_shield_active,
            "market_grade": "A+" if btc_is_above else "B",
        },
        "opportunities": opportunities,
        "total_scanned": len(symbols),
        "matches_found": len(opportunities),
    }

    _SNAPBACK_CACHE = (now, result)
    return result
