"""Spot SATIŞ koruma emirleri (SL/TP/OCO) için fiyat ilişkisi kuralları (saf, testli).

Binance TR dokümanı (OCO, SELL): Limit (TP) fiyatı > Son fiyat > Stop (SL) fiyatı; `stopLimitPrice` zorunlu.
Tekil emirlerde de aynı mantık geçerlidir: TP son fiyatın ÜSTÜNDE olmalı (altındaki limit satış hemen dolar),
SL son fiyatın ALTINDA olmalı (üstündeki stop anında tetiklenir). Doğrulama emirler İPTAL EDİLMEDEN önce yapılır:
aksi halde reddedilen istek mevcut korumayı silip pozisyonu korumasız bırakabilirdi.
"""
from __future__ import annotations

MODES = ("OCO", "SL_ONLY", "TP_ONLY")


def validate_sl_tp(mode: str, last_price: float | None, tp_price: float | None, sl_price: float | None) -> str | None:
    """Hata mesajı (Türkçe) ya da None. `last_price` bilinmiyorsa yalnız fiyatların kendi aralarındaki ilişki denetlenir."""
    tp = float(tp_price or 0)
    sl = float(sl_price or 0)
    last = float(last_price) if last_price else None
    if mode not in MODES:
        return "Geçersiz mod (OCO, SL_ONLY veya TP_ONLY olmalı)"
    if mode == "OCO":
        if tp <= 0 or sl <= 0:
            return "OCO için hem Kâr Al (TP) hem Zarar Kes (SL) fiyatı girilmelidir"
        if tp <= sl:
            return "Kâr Al (TP) fiyatı Zarar Kes (SL) fiyatından büyük olmalıdır"
    elif mode == "SL_ONLY" and sl <= 0:
        return "Zarar Kes (SL) fiyatı girilmelidir"
    elif mode == "TP_ONLY" and tp <= 0:
        return "Kâr Al (TP) fiyatı girilmelidir"
    if last:
        if mode in ("OCO", "SL_ONLY") and sl >= last:
            return f"Zarar Kes (SL) fiyatı güncel fiyatın ({last:g}) altında olmalıdır; aksi halde emir hemen tetiklenir"
        if mode in ("OCO", "TP_ONLY") and tp <= last:
            return f"Kâr Al (TP) fiyatı güncel fiyatın ({last:g}) üstünde olmalıdır; aksi halde pozisyon hemen satılır"
    return None
