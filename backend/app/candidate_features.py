"""Aday ÖZELLİK anlık görüntüsü — journal'a yazılır (2026-10-17).

Neden: Mum tabanlı geriye dönük analizler (docs/CIKIS_DESEN_ANALIZI_2026-10-17.md) fiyat+hacimden
türeyen hiçbir erken-giriş kuralının Hız Avcısı'nı geçmediğini gösterdi. Sıradaki deney mumda
OLMAYAN veriler: taker alış payı, emir defteri dengesizliği, mikro yapı (balina, CVD), spread.
Canlı adaylar bunları ZATEN hesaplıyor (`radar`, `microstructure`) ama journal'a yazılmıyordu →
sonradan ölçülemiyordu. Bu modül adaydan küçük, sabit şemalı bir sözlük çıkarır.

Saf fonksiyon: ağ/DB yok; eksik alan None kalır (uydurma yok).
"""
from __future__ import annotations

from typing import Any

FEATURE_VERSION = 1

_RADAR_KEYS = ("taker_buy_ratio", "taker_confirm", "book_imbalance", "choppiness_10", "range_pos_60",
               "regime_chop", "late_phase", "exhaustion_penalty")
_MICRO_KEYS = ("whale_verdict", "whale_count", "cvd_try", "trade_rate_per_min")
_SCALAR_KEYS = ("mode", "rsi", "mfi", "exhausted", "block_reason", "volume_ratio", "bb_width_pct",
                "aroon_up", "linreg_slope10_pct", "macd_bullish", "macd_rising", "m5_macd_bullish",
                "ret_8h_pct", "adx_14", "slope_15m", "change_24h", "spread_pct", "panel_score",
                "unified_score", "velocity_score")


def _num(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    return v if isinstance(v, str) else None


def candidate_features(c: dict | None) -> dict:
    """Aday sözlüğünden journal özellikleri. Boş/None girdi → {}."""
    if not isinstance(c, dict):
        return {}
    out: dict[str, Any] = {"v": FEATURE_VERSION}
    for k in _SCALAR_KEYS:
        if c.get(k) is not None:
            out[k] = _num(c.get(k))
    radar = c.get("radar") if isinstance(c.get("radar"), dict) else {}
    for k in _RADAR_KEYS:
        if radar.get(k) is not None:
            out[k] = _num(radar.get(k))
    micro = c.get("microstructure") if isinstance(c.get("microstructure"), dict) else {}
    for k in _MICRO_KEYS:
        if micro.get(k) is not None:
            out[k] = _num(micro.get(k))
    surge = c.get("master_surge") if isinstance(c.get("master_surge"), dict) else {}
    if surge:
        if surge.get("composite_index") is not None:
            out["surge_composite"] = _num(surge.get("composite_index"))
        layers = surge.get("layers") if isinstance(surge.get("layers"), dict) else {}
        l1 = layers.get("l1_liquidity") if isinstance(layers.get("l1_liquidity"), dict) else {}
        l3 = layers.get("l3_orderflow") if isinstance(layers.get("l3_orderflow"), dict) else {}
        for src, keys in ((l1, ("spread_pct", "bid_ask_ratio", "depth_try")), (l3, ("buy_ratio", "whale_net"))):
            for k in keys:
                if src.get(k) is not None and k not in out:
                    out[k] = _num(src.get(k))
        if surge.get("regime_badge"):
            out["regime_badge"] = surge.get("regime_badge")
    return out if len(out) > 1 else {}
