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

    # AĞ HATASI AYRIMI (2026-09-26 denetimi, bulgu #66): `_fetch_fapi_json`
    # ağ hatasında `None` döndürür. Eskiden bu, "vadeli piyasada listeli değil"
    # cevabıyla AYNI 90 sn cache'leniyordu → `master_surge` risk kapısı
    # fail-OPEN kalıyordu (EXTREME_LONG cezası uygulanmıyordu). Artık
    # `fetch_error=True` ile ayrılır ve Master Surge bu durumda nötr/kapalı
    # davranır. Not: `_fetch_fapi_json` sözlük/liste yerine `None` döndüğünde
    # "listed değil" ile "ağ hatası" AYIRT EDİLEMEZ; bu yüzden liste kontrolü
    # ikisini de kapsar ve bilinmeyen durumda hata kabul edilir (fail-closed).
    _transport_failed = prem_data is None or oi_data is None
    if not isinstance(prem_data, dict) or "lastFundingRate" not in prem_data:
        # Bu coin vadeli piyasada listeli değil ya da Binance vadeli kapalı/
        # erişilemez. İkisi de "veri yok" → fail-closed.
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
            # True → ağ/erişim hatası; False → gerçekten listeli değil.
            "fetch_error": bool(_transport_failed),
            "description": (
                f"{futures_sym} vadeli istihbaratına ulaşılamadı (ağ/erişim hatası); "
                "risk kapısı fail-closed olarak nötr kabul edildi."
                if _transport_failed else
                f"{futures_sym} vadeli piyasada listeli değil."
            ),
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
        "fetch_error": False,
        "description": desc,
        "updated_at": now,
    }

    _DERIVATIVES_CACHE[futures_sym] = (now, result)
    return result


# ----------------------------------------------------------------------
# TOPLU SHORT-SQUEEZE TARAMASI (2026-10-10)
# Tek çağrıda TÜM vadeli sembollerin funding'ini çeker (premiumIndex, sembolsüz)
# ve TR sembol evreniyle eşleştirir. Funding + long/short dengesizliği ile
# short-squeeze adaylarını bulur. Sıfırdan veri kaynağı değil — mevcut
# `get_derivatives_intel` sınıflandırma eşikleriyle AYNI mantık.
# ----------------------------------------------------------------------
_SQUEEZE_SCAN_CACHE: dict = {"rows": None, "expires": 0.0}
SQUEEZE_SCAN_TTL_SEC = 120.0


async def scan_short_squeeze(tr_symbols: list[str], *,
                             min_funding_neg_pct: float = -0.03,
                             top_n: int = 25) -> list[dict]:
    """TR sembol evreninde short-squeeze adaylarını bul (toplu funding).

    DÖNÜŞ: [{"symbol": "MINATRY", "funding_rate_pct": -0.17, "funding_state": ...,
             "short_squeeze_potential": True, "derivatives_bias": ..., "score": ...}]

    `min_funding_neg_pct`: squeeze için funding üst sınırı (yüzde). Varsayılan
    -0.03 (= config eşiği). Daha negatif = daha kalabalık short = daha güçlü squeeze.
    """
    now = time.time()
    if _SQUEEZE_SCAN_CACHE["rows"] is not None and now < _SQUEEZE_SCAN_CACHE["expires"]:
        data = _SQUEEZE_SCAN_CACHE["rows"]
    else:
        data = await asyncio.to_thread(
            _fetch_fapi_json, f"{FAPI_BASE}/fapi/v1/premiumIndex")
        _SQUEEZE_SCAN_CACHE["rows"] = data if isinstance(data, list) else []
        _SQUEEZE_SCAN_CACHE["expires"] = now + SQUEEZE_SCAN_TTL_SEC
    if not isinstance(data, list):
        return []

    # futures sembol → funding
    by_fut = {}
    for row in data:
        try:
            fs = str(row.get("symbol") or "").upper()
            if not fs.endswith("USDT"):
                continue
            by_fut[fs[:-4]] = {
                "funding_rate": float(row.get("lastFundingRate") or 0.0),
                "mark_price": float(row.get("markPrice") or 0.0),
            }
        except (TypeError, ValueError):
            continue

    out = []
    for sym in tr_symbols:
        base = str(sym or "").upper()
        if base.endswith("TRY"):
            base = base[:-3]
        fut = by_fut.get(base)
        if not fut:
            continue
        fr = fut["funding_rate"]
        fr_pct = fr * 100.0
        if fr_pct <= -0.10:
            state, bias, score = "EXTREME_SHORT", "SHORT_SQUEEZE_POTENTIAL", 100.0
        elif fr_pct <= min_funding_neg_pct:
            state, bias, score = "CROWDED_SHORT", "SHORT_SQUEEZE_POTENTIAL", 70.0
        elif fr_pct <= -0.01:
            state, bias = "MILD_SHORT", "NEUTRAL"
            score = 40.0
        else:
            continue
        # daha negatif funding -> daha güçlü squeeze (skor ölçeği)
        score += min(50.0, abs(fr_pct) * 200.0)
        out.append({
            "symbol": str(sym).upper(),
            "futures_symbol": base + "USDT",
            "funding_rate": fr,
            "funding_rate_pct": round(fr_pct, 4),
            "funding_state": state,
            "short_squeeze_potential": state in ("CROWDED_SHORT", "EXTREME_SHORT"),
            "derivatives_bias": bias,
            "mark_price": fut["mark_price"],
            "score": round(score, 1),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:max(1, int(top_n))]


def get_cached_derivatives_intel(symbol: str, max_age_sec: float | None = None) -> dict | None:
    """Bellekteki son vadeli piyasa istihbaratını senkron olarak döner.

    `unified_signals.enrich_candidates` ve `master_surge` BU FONKSİYONU
    kullanır (eskiden `_DERIVATIVES_CACHE` sözlüğüne doğrudan, TTL kontrolü
    OLMADAN bakıyordu — bulgu #67: 90 sn bayat kontrolü atlanıyordu).

    `max_age_sec` verilirse daha yaşlı (ama daha taze olmayan) kayıt da
    döndürülebilir; Master Surge risk kapısı fail-closed olduğu için
    "taze veri yok ama az önce ölçülmüştür" ayrımı faydalıdır.
    """
    futures_sym = symbol_to_futures(symbol)
    cached = _DERIVATIVES_CACHE.get(futures_sym)
    if not cached:
        return None
    age = time.time() - cached[0]
    ttl = float(max_age_sec if max_age_sec is not None else CACHE_TTL_SEC)
    if ttl > 0 and age >= ttl:
        return None
    return cached[1]


# ----------------------------------------------------------------------
# SQUEEZE TEYİDİ (Faz 3.3, 2026-10-14; docs/radar-improvement-analysis.md)
# OI delta (1 saat, 5m barlar) + funding trendi. Kısa squeeze adayının
# gerçekten "kalabalık short KAPANIYOR" mu yoksa sönmüş mü olduğunu ayırt
# eder: OI hızla artıyorsa short pozisyonları hâlâ açılıyor/likidite
# birikiyor (teyit); OI eriyorsa kısa sıkışma çoktan oynanmış (fade).
# ----------------------------------------------------------------------
_OI_HIST_CACHE: dict[str, tuple[float, dict]] = {}
OI_HIST_TTL_SEC = 300.0  # 5 dk TTL — openInterestHist çağrısını kısıtlar


async def squeeze_confirmation(symbol: str) -> dict:
    """Short-squeeze teyit verisi: OI 1s değişimi + funding trendi.

    DÖNÜŞ: {"oi_change_1h_pct": float|None, "funding_trend": "strengthening"|
    "easing"|"flat"|None, "confirm_score_mult": float, "squeeze_confirmed": bool}
    Ağ/listeli olmama durumunda çarpan 1.0 (nötr) döner — tarama asla düşmez.
    """
    fut = symbol_to_futures(symbol)
    now = time.time()
    cached = _OI_HIST_CACHE.get(fut)
    if cached and (now - cached[0]) < OI_HIST_TTL_SEC:
        return cached[1]

    def _fetch_sync():
        oi_url = f"{FAPI_BASE}/futures/data/openInterestHist?symbol={fut}&period=5m&limit=13"
        fr_url = f"{FAPI_BASE}/fapi/v1/fundingRate?symbol={fut}&limit=3"
        return _fetch_fapi_json(oi_url), _fetch_fapi_json(fr_url)

    oi_hist, fr_hist = await asyncio.to_thread(_fetch_sync)
    result: dict = {"oi_change_1h_pct": None, "funding_trend": None,
                    "confirm_score_mult": 1.0, "squeeze_confirmed": False}
    try:
        if isinstance(oi_hist, list) and len(oi_hist) >= 2:
            first = float(oi_hist[0].get("sumOpenInterest") or 0)
            last = float(oi_hist[-1].get("sumOpenInterest") or 0)
            if first > 0:
                result["oi_change_1h_pct"] = round((last / first - 1) * 100.0, 2)
    except (TypeError, ValueError, AttributeError, IndexError):
        pass
    try:
        if isinstance(fr_hist, list) and len(fr_hist) >= 2:
            rates = [float(r.get("fundingRate") or 0) for r in fr_hist]
            # Kayıt sırası eskiden yeniye; fonlama daha negatife gidiyorsa
            # short baskısı güçleniyor (squeeze dinamiği sürüyor).
            if rates[-1] < rates[-2]:
                result["funding_trend"] = "strengthening"
            elif rates[-1] > rates[-2]:
                result["funding_trend"] = "easing"
            else:
                result["funding_trend"] = "flat"
    except (TypeError, ValueError, AttributeError, IndexError):
        pass

    oi_chg = result.get("oi_change_1h_pct")
    if oi_chg is not None:
        # Eşikler config'ten (SQUEEZE_OI_*): +%10+ → teyit, ≤−%8 → fade.
        try:
            from app.config import config as _cfg
            strong = float(getattr(_cfg, "SQUEEZE_OI_STRONG_PCT", 10.0))
            fade = float(getattr(_cfg, "SQUEEZE_OI_FADE_PCT", -8.0))
            confirm_mult = float(getattr(_cfg, "SQUEEZE_OI_CONFIRM_MULT", 1.25))
            fade_mult = float(getattr(_cfg, "SQUEEZE_OI_FADE_MULT", 0.7))
        except Exception:
            strong, fade, confirm_mult, fade_mult = 10.0, -8.0, 1.25, 0.7
        if oi_chg >= strong:
            result["confirm_score_mult"] = confirm_mult
            result["squeeze_confirmed"] = True
        elif oi_chg <= fade:
            result["confirm_score_mult"] = fade_mult

    _OI_HIST_CACHE[fut] = (now, result)
    return result
