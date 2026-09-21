"""Macro market sentiment and BTC compass service.

Combines Alternative.me Crypto Fear and Greed Index with real-time BTC 5m/15m
directional momentum to calculate the global market regime and provide a systemic
safety gate (BTC Compass Gate) for Master Surge and LLM chat/assistant.
"""

import asyncio
import json
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"
FNG_CACHE_TTL = 900.0  # 15 dakika (Günde 1 kez güncellenir)
BTC_CACHE_TTL = 30.0   # 30 saniye BTC pusulası tazeleme

_FNG_CACHE: tuple[float, dict] | None = None
_BTC_COMPASS_CACHE: tuple[float, dict] | None = None


def _fetch_fng_sync(timeout: float = 3.5) -> dict | None:
    try:
        req = Request(FNG_URL, headers={"User-Agent": "ScalperAgent/4.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("data") or []
            if items and isinstance(items[0], dict):
                return {
                    "score": int(items[0].get("value") or 50),
                    "classification": str(items[0].get("value_classification") or "Neutral"),
                    "updated_at": time.time(),
                }
    except Exception as exc:
        logger.debug("Fear & Greed çekimi başarısız: %s", exc)
    return None


async def get_fear_and_greed() -> dict:
    """Korku ve Açgözlülük İndeksini döner (15 dk TTL önbellekli)."""
    global _FNG_CACHE
    now = time.time()
    if _FNG_CACHE and (now - _FNG_CACHE[0]) < FNG_CACHE_TTL:
        return _FNG_CACHE[1]

    data = await asyncio.to_thread(_fetch_fng_sync)
    if not data:
        data = {"score": 50, "classification": "Neutral", "updated_at": now}

    _FNG_CACHE = (now, data)
    return data


async def get_btc_compass() -> dict:
    """Bitcoin'in anlık kısa vadeli yönünü ve piyasa stres seviyesini ölçer."""
    global _BTC_COMPASS_CACHE
    now = time.time()
    if _BTC_COMPASS_CACHE and (now - _BTC_COMPASS_CACHE[0]) < BTC_CACHE_TTL:
        return _BTC_COMPASS_CACHE[1]

    from app.binance_tr_public import klines as fetch_klines
    btc_5m_ret = 0.0
    btc_15m_ret = 0.0
    btc_trend_state = "SIDEWAYS"
    is_panic = False

    try:
        # BTCTRY 5m klines
        k5 = await fetch_klines("BTCTRY", "5m", 6)
        if k5 and len(k5) >= 4:
            c_now = float(k5[-1][4])
            c_prev1 = float(k5[-2][4])
            c_prev3 = float(k5[-4][4])
            btc_5m_ret = round(((c_now - c_prev1) / c_prev1) * 100.0, 2)
            btc_15m_ret = round(((c_now - c_prev3) / c_prev3) * 100.0, 2)

            if btc_15m_ret <= -1.0 or (btc_5m_ret <= -0.7 and btc_15m_ret <= -0.8):
                btc_trend_state = "PANIC_DUMP"
                is_panic = True
            elif btc_15m_ret < -0.4:
                btc_trend_state = "BEARISH_PRESSURE"
            elif btc_15m_ret > 0.6:
                btc_trend_state = "STRONG_BULLISH"
            elif btc_15m_ret > 0.2:
                btc_trend_state = "MILD_BULLISH"
            else:
                btc_trend_state = "SIDEWAYS"
    except Exception as exc:
        logger.debug("BTC pusula hesabı hatası: %s", exc)

    result = {
        "btc_symbol": "BTCTRY",
        "btc_5m_change_pct": btc_5m_ret,
        "btc_15m_change_pct": btc_15m_ret,
        "btc_trend_state": btc_trend_state,
        "is_panic_dump": is_panic,
        "updated_at": now,
    }
    _BTC_COMPASS_CACHE = (now, result)
    return result


async def get_macro_sentiment() -> dict:
    """Tüm makro duygu ve BTC koruma durumunu tek özet nesnede birleştirir."""
    fng = await get_fear_and_greed()
    btc = await get_btc_compass()

    score = fng.get("score", 50)
    classification = fng.get("classification", "Neutral")
    is_panic = btc.get("is_panic_dump", False)

    # Piyasa Stres Seviyesi
    if is_panic or score <= 20:
        stress_level = "HIGH_RISK"
        allow_new_longs = not is_panic  # BTC şelale düşüşündeyse yeni alım kapatılır
        desc = "Piyasa yüksek stres veya panik satış altında. Bitcoin ani düşüşte; yeni altcoin alımları yüksek risk taşır."
    elif score >= 75:
        stress_level = "OVERHEATED"
        allow_new_longs = True
        desc = "Piyasa aşırı açgözlülük bölgesinde. Coşku yüksek ancak direnç seviyelerinde kâr realizasyonu olasılığı var."
    else:
        stress_level = "HEALTHY"
        allow_new_longs = True
        desc = f"Genel piyasa dengeli ({classification} - Skor {score}). Bitcoin yatay/destekleyici."

    return {
        "fear_and_greed_score": score,
        "fear_and_greed_class": classification,
        "btc_trend_state": btc.get("btc_trend_state", "SIDEWAYS"),
        "btc_15m_change_pct": btc.get("btc_15m_change_pct", 0.0),
        "is_btc_panic": is_panic,
        "market_stress_level": stress_level,
        "allow_new_longs": allow_new_longs,
        "summary": desc,
        "updated_at": time.time(),
    }


def get_cached_macro_sentiment() -> dict | None:
    """Bellekteki son makro duygu ve BTC durumunu senkron döner (varsa)."""
    now = time.time()
    if not _FNG_CACHE and not _BTC_COMPASS_CACHE:
        return None

    fng_val = _FNG_CACHE[1] if (_FNG_CACHE and (now - _FNG_CACHE[0]) < FNG_CACHE_TTL) else {"score": 50, "classification": "Neutral"}
    btc_val = _BTC_COMPASS_CACHE[1] if (_BTC_COMPASS_CACHE and (now - _BTC_COMPASS_CACHE[0]) < BTC_CACHE_TTL) else {"btc_trend_state": "SIDEWAYS", "btc_15m_change_pct": 0.0, "is_panic_dump": False}

    score = fng_val.get("score", 50)
    classification = fng_val.get("classification", "Neutral")
    is_panic = btc_val.get("is_panic_dump", False)

    return {
        "fear_and_greed_score": score,
        "fear_and_greed_class": classification,
        "btc_trend_state": btc_val.get("btc_trend_state", "SIDEWAYS"),
        "btc_15m_change_pct": btc_val.get("btc_15m_change_pct", 0.0),
        "is_btc_panic": is_panic,
        "market_stress_level": "HIGH_RISK" if (is_panic or score <= 20) else ("OVERHEATED" if score >= 75 else "HEALTHY"),
        "allow_new_longs": not is_panic,
        "summary": "Makro önbellek özeti",
        "updated_at": now,
    }
