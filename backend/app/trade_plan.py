"""Sembole özel işlem planı: SL/TP/RR hesabı, yedek kural ve LLM önerisinin doğrulanması (saf).

LLM yalnız ÖNERİ üretir (SL %, RR, kısa gerekçe). Çıktısı burada doğrulanır ve kenetlenir; emir vermez.
Geçersiz/eksik çıktı → None (çağıran kural tabanlı yedeğe düşer).
"""
from __future__ import annotations

import json
import math
import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

SL_PCT_MIN, SL_PCT_MAX = 0.5, 10.0
RR_MIN, RR_MAX = 1.0, 5.0
RATIONALE_MAX = 240
_FALLBACK_SL_PCT = 2.0


def floor_to_step(value: float, step: float | None) -> float:
    """Değeri adıma AŞAĞI yuvarlar, Decimal ile (float kayması yok: 1.15/0.01 → 1.15, 0.3/0.1 → 0.3).

    Lot/miktar yuvarlamasının TEK kaynağı; `math.floor(q / step) * step` yerine bunu çağırın.
    """
    if not step or float(step) <= 0:
        return float(value)
    s = Decimal(str(step))
    return float((Decimal(str(value)) / s).to_integral_value(ROUND_DOWN) * s)


round_down = floor_to_step  # eski ad; çağıranlar için


def round_to_tick(value: float, tick: float | None) -> float:
    """Fiyatı en yakın tick'e yuvarlar (tick yoksa dokunmaz), Decimal ile."""
    if not tick or float(tick) <= 0:
        return float(value)
    t = Decimal(str(tick))
    return float((Decimal(str(value)) / t).to_integral_value(ROUND_HALF_UP) * t)


def compute_plan(price: float, amount_try: float, sl_pct: float, rr: float, filters: dict, fee_rate: float) -> dict:
    """Piyasa alımı + OCO (SL/TP) planı. Emir GÖNDERMEZ.

    SL = fiyat × (1 − sl_pct/100); TP = fiyat × (1 + sl_pct × rr/100). Miktar komisyon düşülüp LOT adımına aşağı yuvarlanır;
    fiyatlar tick'e yuvarlanır. Senaryolar alım + satım komisyonu dahil NET TL sonucudur.
    """
    for name, val in (("fiyat", price), ("tutar", amount_try), ("sl_pct", sl_pct), ("rr", rr)):
        if not (isinstance(val, (int, float)) and math.isfinite(val) and val > 0):
            raise ValueError(f"Geçersiz {name}")
    fee = max(0.0, min(float(fee_rate or 0), 0.05))
    step = float(filters.get("step_size") or 0)
    tick = float(filters.get("tick_size") or 0)
    min_notional = float(filters.get("min_notional") or 0)
    min_qty = float(filters.get("min_qty") or 0)

    qty = round_down(amount_try / price * (1.0 - fee), step)
    sl_price = round_to_tick(price * (1.0 - sl_pct / 100.0), tick)
    tp_price = round_to_tick(price * (1.0 + sl_pct * rr / 100.0), tick)
    proceeds = lambda px: qty * px * (1.0 - fee)  # noqa: E731
    loss = proceeds(sl_price) - amount_try
    gain = proceeds(tp_price) - amount_try
    break_even = amount_try / (qty * (1.0 - fee)) if qty > 0 else None

    warnings: list[str] = []
    if min_notional and amount_try < min_notional:
        warnings.append("min_tutar_alti")
    if min_qty and qty < min_qty:
        warnings.append("min_miktar_alti")
    if filters.get("oco_enable") is False:
        warnings.append("oco_desteklenmiyor")
    if sl_price >= price or (price - sl_price) / price < 0.002:
        warnings.append("sl_fiyata_cok_yakin")
    if tp_price <= price:
        warnings.append("tp_fiyata_cok_yakin")

    return {
        "qty": qty, "cost_try": float(amount_try), "fee_buy_try": float(amount_try) * fee,
        "sl_price": sl_price, "tp_price": tp_price, "sl_pct": float(sl_pct), "rr": float(rr),
        "loss_try": loss, "gain_try": gain, "break_even_price": break_even, "warnings": warnings,
    }


def rule_suggestion(atr_pct: float | None, default_rr: float) -> dict:
    """Yedek kural: SL = 1,5 × ATR% (0,8–6 arası), RR = kullanıcının standart RR'si."""
    try:
        atr = float(atr_pct)
        sl = max(0.8, min(6.0, 1.5 * atr)) if math.isfinite(atr) and atr > 0 else _FALLBACK_SL_PCT
    except (TypeError, ValueError):
        sl = _FALLBACK_SL_PCT
    return {"sl_pct": sl, "rr": float(default_rr), "source": "kural"}


def _reject_constant(name: str):
    raise ValueError(f"geçersiz sabit: {name}")


def _extract_json(text: str) -> Any:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    return json.loads(text[start:end + 1], parse_constant=_reject_constant)


def validate_llm_suggestion(raw: Any) -> dict | None:
    """LLM metnini doğrular: {sl_pct, rr, kisa_gerekce} → {sl_pct, rr, rationale}; geçersizse None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = _extract_json(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        sl = float(data["sl_pct"])
        rr = float(data["rr"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(sl) and math.isfinite(rr)):
        return None
    rationale = re.sub(r"\s+", " ", str(data.get("kisa_gerekce") or data.get("rationale") or "")).strip()
    return {
        "sl_pct": max(SL_PCT_MIN, min(SL_PCT_MAX, sl)),
        "rr": max(RR_MIN, min(RR_MAX, rr)),
        "rationale": rationale[:RATIONALE_MAX],
    }
