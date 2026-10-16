"""Sembole özel RR önerisi: LLM (doğrulanmış) → kural tabanlı yedek.

LLM yalnız ÖNERİ üretir; emir vermez. Çıktısı `trade_plan.validate_llm_suggestion` ile doğrulanıp kenetlenir.
LLM yok / zaman aşımı / hata / geçersiz çıktı → `rule_suggestion` (asla istisna). Yalnız LLM sonuçları 60 sn önbelleğe alınır.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

from app.trade_plan import rule_suggestion, validate_llm_suggestion

logger = logging.getLogger("scalper.rr_service")

CACHE_TTL_SEC = 60.0
LLM_TIMEOUT_SEC = 6.0
_CACHE: dict[str, tuple[float, dict]] = {}


def _num(value: Any, scale: float = 1.0) -> float | None:
    try:
        number = float(value) * scale
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def extract_features(snapshot: dict) -> dict:
    """Snapshot'tan LLM için kısa, YÜZDE cinsinden öznitelikler (eksik alan None)."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    vol = snap.get("volatility") or {}
    trend = snap.get("trend") or {}
    mom = snap.get("momentum") or {}
    volume = snap.get("volume") or {}
    behavior = snap.get("symbol_behavior") or {}
    adx = trend.get("adx")
    if isinstance(adx, dict):
        adx = adx.get("adx")
    return {
        "price": _num(snap.get("price")),
        "atr_pct": _num(vol.get("atr_pct"), 100),
        "adr_14_pct": _num(vol.get("adr_14_pct"), 100),
        "day_range_used_pct": _num(vol.get("day_range_used_pct"), 100),
        "return_5m_pct": _num(mom.get("return_5m"), 100),
        "return_15m_pct": _num(mom.get("return_15m"), 100),
        "return_1h_pct": _num(mom.get("return_1h"), 100),
        "rsi_14": _num(mom.get("rsi_14")),
        "adx": _num(adx),
        "trend_alignment": trend.get("alignment"),
        "volume_quality": volume.get("volume_quality"),
        "volume_ratio_20": _num(volume.get("volume_ratio_20")),
        "volatility_regime": behavior.get("volatility_regime"),
    }


_PROMPT = (
    "Aşağıdaki sembol özniteliklerine göre SPOT ALIM için sembole özel bir zarar durdur (SL) mesafesi ve risk/ödül oranı (RR) öner. "
    "SL mesafesi giriş fiyatından yüzde olarak aşağıdadır (0,5–10). RR = kâr al mesafesi / SL mesafesi (1–5). "
    "Günlük yükseliş (adr_14_pct, day_range_used_pct), trend uyumu, volatilite (atr_pct) ve hacim kalitesini dikkate al: "
    "volatilite yüksekse SL'yi genişlet, trend zayıf/karışıksa RR'yi düşük tut. "
    "Yalnızca şu biçimde TEK bir JSON döndür: "
    '{"sl_pct": sayı, "rr": sayı, "kisa_gerekce": "en fazla iki Türkçe cümle"}. Emir verme, başka metin yazma.'
)


async def suggest_rr(symbol: str, snapshot: dict, default_rr: float, *, now: float | None = None,
                     timeout: float = LLM_TIMEOUT_SEC,
                     chat: Callable[..., Awaitable[dict]] | None = None) -> dict:
    """{sl_pct, rr, rationale?, source: 'llm'|'kural'}. Asla istisna fırlatmaz."""
    features = extract_features(snapshot)
    fallback = rule_suggestion(features.get("atr_pct"), default_rr)
    fallback["rationale"] = "Otomatik hesap: zarar durdur, son dönem oynaklığın (ATR) 1,5 katı; RR standart ayarınızdır."
    clock = now if now is not None else time.time()
    key = str(symbol).upper()
    cached = _CACHE.get(key)
    if cached and clock - cached[0] < CACHE_TTL_SEC:
        return dict(cached[1])
    if chat is None:
        from app import llm_analysis
        chat = llm_analysis.chat
    try:
        result = await asyncio.wait_for(
            chat({"symbol": key, "ozellikler": features},
                 [{"role": "user", "content": _PROMPT + "\n" + json.dumps({"symbol": key, **features}, ensure_ascii=False)}],
                 json_mode=True, max_tokens=300),
            timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — zaman aşımı dahil her hata yedeğe düşer
        logger.debug("RR LLM önerisi alınamadı (%s): %s", key, type(exc).__name__)
        return fallback
    suggestion = validate_llm_suggestion((result or {}).get("text") if isinstance(result, dict) else None)
    if suggestion is None:
        return fallback
    out = {**suggestion, "source": "llm"}
    _CACHE[key] = (clock, out)
    if len(_CACHE) > 200:                       # sınırsız büyümeyi önle
        for old in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:100]:
            _CACHE.pop(old, None)
    return dict(out)
