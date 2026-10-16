"""Risk Merkezi ayarlarının doğrulaması (saf).

`max_position_pct`: tek bir pozisyonda serbest TRY bakiyesinin en fazla yüzde kaçı kullanılabilir.
`default_rr`: standart risk/ödül oranı (kâr al mesafesi / zarar durdur mesafesi).
"""
from __future__ import annotations

import math
from typing import Any

DEFAULTS: dict[str, float] = {"max_position_pct": 20.0, "default_rr": 2.0}
_BOUNDS: dict[str, tuple[float, float]] = {"max_position_pct": (1.0, 100.0), "default_rr": (1.0, 5.0)}
_LABELS = {"max_position_pct": "Pozisyon yüzdesi", "default_rr": "Standart RR"}


def _to_float(name: str, raw: Any) -> float:
    if isinstance(raw, str):
        raw = raw.strip().replace(",", ".")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{_LABELS[name]} sayı olmalı") from None
    if not math.isfinite(value):
        raise ValueError(f"{_LABELS[name]} geçerli bir sayı olmalı")
    return value


def validate(payload: dict) -> dict[str, float]:
    """Yalnız gelen bilinen alanları doğrular; sınır dışı/sayı olmayan değerde ValueError."""
    out: dict[str, float] = {}
    for name, (lo, hi) in _BOUNDS.items():
        if name not in payload:
            continue
        value = _to_float(name, payload[name])
        if not lo <= value <= hi:
            raise ValueError(f"{_LABELS[name]} {lo:g} ile {hi:g} arasında olmalı")
        out[name] = value
    return out
