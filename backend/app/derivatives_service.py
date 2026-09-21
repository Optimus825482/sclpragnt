"""Binance Futures public market-data adapter for derivatives intelligence.

Retrieves Open Interest and Funding Rate metrics via Binance Futures public REST API
(fapi.binance.com - keyless/free) to provide derivatives sentiment and leverage risk
analysis for both LLM Chat/Assistant and the Master Surge Engine.
"""

import asyncio
import json
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

FAPI_BASE = "https://fapi.binance.com"
CACHE_TTL_SEC = 90.0  # 90 saniye TTL - IP rate limit koruması

# In-memory TTL cache: { futures_symbol: (timestamp, data_dict) }
_DERIVATIVES_CACHE: dict[str, tuple[float, dict]] = {}


def symbol_to_futures(symbol: str) -> str:
    """Binance TR sembolünü (örn. BTCTRY) vadeli USDT sembolüne (BTCUSDT) çevirir."""
    s = str(symbol or "").strip().upper()
    if s.endswith("TRY"):
        return s[:-3] + "USDT"
    if not s.endswith("USDT"):
        return s + "USDT"
    return s


def _fetch_fapi_json(url: str, timeout: float = 4.0) -> dict | list | None:
    """Senkron URL okuma yardımcısı (asyncio.to_thread ile koşturulur)."""
    try:
        req = Request(url, headers={"User-Agent": "ScalperAgent/4.0"})
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.debug("Binance FAPI isteği başarısız: %s (%s)", url, exc)
        return None
    except Exception as exc:
        logger.debug("Binance FAPI parse hatası: %s", exc)
        return None


async def get_derivatives_intel(symbol: str) -> dict:
    """Bir sembolün vadeli Açık Pozisyon (OI) ve Fonlama Oranı (Funding Rate) verilerini getirir."""
    futures_sym = symbol_to_futures(symbol)
    now = time.time()

    # Önbellek kontrolü
    cached = _DERIVATIVES_CACHE.get(futures_sym)
    if cached and (now - cached[0]) < CACHE_TTL_SEC:
        return cached[1]

    # Paralel çekim: premiumIndex (anlık fonlama ve mark price) ve openInterest
    def _fetch_sync():
        prem_url = f"{FAPI_BASE}/fapi/v1/premiumIndex?symbol={futures_sym}"
        oi_url = f"{FAPI_BASE}/fapi/v1/openInterest?symbol={futures_sym}"
        prem = _fetch_fapi_json(prem_url)
        oi = _fetch_fapi_json(oi_url)
        return prem, oi

    prem_data, oi_data = await asyncio.to_thread(_fetch_sync)

    if not isinstance(prem_data, dict) or "lastFundingRate" not in prem_data:
        # Bu coin vadeli piyasada listeli değil veya Binance vadeli kapalı
        result = {
            "symbol": symbol.upper(),
            "futures_symbol": futures_sym,
            "futures_available": False,
            "funding_rate": None,
            "funding_rate_pct": None,
            "funding_state": "UNKNOWN",
            "open_interest": None,
            "open_interest_usd": None,
            "mark_price": None,
            "crowded_long_danger": False,
            "short_squeeze_potential": False,
            "derivatives_bias": "NEUTRAL",
            "surge_score_bonus": 0,
            "description": f"{futures_sym} vadeli piyasada listeli değil veya veriye ulaşılamadı.",
            "updated_at": now,
        }
        _DERIVATIVES_CACHE[futures_sym] = (now, result)
        return result

    try:
        funding_rate = float(prem_data.get("lastFundingRate") or 0.0)
        mark_price = float(prem_data.get("markPrice") or 0.0)
        funding_pct = round(funding_rate * 100.0, 4)
    except (ValueError, TypeError):
        funding_rate = 0.0
        mark_price = 0.0
        funding_pct = 0.0

    oi_val = 0.0
    if isinstance(oi_data, dict):
        try:
            oi_val = float(oi_data.get("openInterest") or 0.0)
        except (ValueError, TypeError):
            oi_val = 0.0

    oi_usd = round(oi_val * mark_price, 2)

    # Fonlama Durumu ve Tuzak Risk Sınıflandırması:
    # 0.00010 = %0.01 (Standart 8 saatlik oran)
    # >= 0.0005 (+%0.05) -> Piyasa aşırı longa boğuldu, long tasfiyesi riski
    # >= 0.0010 (+%0.10) -> Tehlikeli derecede aşırı long
    # <= -0.0003 (-%0.03) -> Shortlar sıkışıyor, yukarı patlama potansiyeli
    crowded_long = False
    short_squeeze = False
    surge_bonus = 0

    if funding_rate >= 0.0008:
        funding_state = "EXTREME_LONG"
        crowded_long = True
        derivatives_bias = "LONG_SQUEEZE_RISK"
        surge_bonus = -15  # Şişkin longlarda Master Surge skorunu ciddi kır
        desc = f"Vadeli piyasada aşırı long birikimi var (%{funding_pct:.3f} fonlama). Long tasfiyesi (dump) riski yüksek!"
    elif funding_rate >= 0.0004:
        funding_state = "CROWDED_LONG"
        crowded_long = True
        derivatives_bias = "CAUTION_HEAVY_LONG"
        surge_bonus = -5
        desc = f"Vadeli fonlama pozitif ve yüksek (%{funding_pct:.3f}). Alıcılar ağırlıkta ancak direnç kırılmazsa kar satışı gelebilir."
    elif funding_rate <= -0.0003:
        funding_state = "CROWDED_SHORT"
        short_squeeze = True
        derivatives_bias = "SHORT_SQUEEZE_POTENTIAL"
        surge_bonus = +10  # Negatif fonlamada short sıkışması yukarı patlatır
        desc = f"Vadeli piyasada shortlar sıkışmış durumda (%{funding_pct:.3f} negatif fonlama). Yukarı yönlü short squeeze potansiyeli yüksek!"
    else:
        funding_state = "HEALTHY"
        derivatives_bias = "HEALTHY_MOMENTUM"
        surge_bonus = +5  # Sağlıklı fonlama + likit vadeli desteği
        desc = f"Vadeli piyasa dengeli (%{funding_pct:.3f} fonlama). Açık pozisyon: ₺{oi_usd:,.0f} USD."

    result = {
        "symbol": symbol.upper(),
        "futures_symbol": futures_sym,
        "futures_available": True,
        "funding_rate": funding_rate,
        "funding_rate_pct": funding_pct,
        "funding_state": funding_state,
        "open_interest": oi_val,
        "open_interest_usd": oi_usd,
        "mark_price": mark_price,
        "crowded_long_danger": crowded_long,
        "short_squeeze_potential": short_squeeze,
        "derivatives_bias": derivatives_bias,
        "surge_score_bonus": surge_bonus,
        "description": desc,
        "updated_at": now,
    }

    _DERIVATIVES_CACHE[futures_sym] = (now, result)
    return result


def get_cached_derivatives_intel(symbol: str) -> dict | None:
    """Bellekteki son vadeli piyasa istihbaratını senkron olarak döner (varsa ve bayat değilse)."""
    futures_sym = symbol_to_futures(symbol)
    cached = _DERIVATIVES_CACHE.get(futures_sym)
    if cached and (time.time() - cached[0]) < CACHE_TTL_SEC:
        return cached[1]
    return None
