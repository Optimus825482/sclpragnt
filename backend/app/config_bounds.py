"""Tamsayı ayar alanlarının sınırları — TEK doğruluk kaynağı.

`main._apply_config_update` bu sınırların dışını REDDEDER. Kalıcı ayarlar (`llm_settings.runtime_config`)
açılışta doğrulanmadan geri yükleniyordu; sınırlar daralmışsa (ör. top_gainers_limit eskiden >50 olabilirdi)
sayfa sınır dışı değeri gösterip tüm taslağı geri gönderiyor, güncelleme ucu reddediyor ve HİÇBİR ayar
kaydedilemiyordu. Geri yükleme artık aynı sınırlara kenetler.
"""
from __future__ import annotations

from typing import Any

INT_FIELD_BOUNDS: dict[str, tuple[int, int]] = {
    "top_gainers_limit": (1, 50),
    "top_gainers_refresh_sec": (60, 3600),
    "max_open_positions": (0, 500),
    "gainer_radar_min_score": (0, 100),
    "symbol_activity_m1_flat_5m_max_count": (1, 5),
    "symbol_activity_m1_flat_30m_max_count": (1, 30),
}


def clamp_int_field(key: str, value: Any) -> Any:
    """Bilinen alanı sınırlar içine kenetler; bilinmeyen alan / sayı olmayan değer AYNEN döner."""
    bounds = INT_FIELD_BOUNDS.get(key)
    if bounds is None:
        return value
    try:
        number = int(value)
    except (TypeError, ValueError):
        return value
    lo, hi = bounds
    return max(lo, min(hi, number))


def sanitize_persisted(persisted: dict) -> tuple[dict, list[tuple[str, Any, Any]]]:
    """Kalıcı ayar sözlüğünü temizler. Döner: (temiz kopya, [(alan, eski, yeni), ...])."""
    cleaned = dict(persisted)
    changes: list[tuple[str, Any, Any]] = []
    for key in INT_FIELD_BOUNDS:
        if key in cleaned:
            new = clamp_int_field(key, cleaned[key])
            if new != cleaned[key]:
                changes.append((key, cleaned[key], new))
                cleaned[key] = new
    return cleaned, changes
