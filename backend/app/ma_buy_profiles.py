"""MA BUY — zaman dilimine özel sinyal/çıkış profilleri (2026-10-21: H4).

90 günlük arama (docs/MA_KESISIM_H4_ARAMA_90g_2026-10-21.md): H4'te SMA 8/34/89, ORTA×YAVAŞ yukarı kesişim, sinyal mumu
gövdesi ≥ %1; hedef %10, stop %8, en çok 3 gün, iz süren / başabaş stop YOK → eğitim +%3,1 (n 41), test +%3,0 (n 14).
Diğer dilimler genel ayarlarla (MA_BUY_PERIODS, iki kural, StochRSI ≤ 80, otonom paper çıkış profili) çalışmaya devam eder.

Saf modül: config okur, DB/ağ yok. `profile(tf)` None dönerse o dilimde özel profil yoktur.
"""
from __future__ import annotations

from app import ma_buy_signals
from app.config import config

H4 = "4h"
H4_PROFILE_NAME = "ma_buy_h4"


def _periods(raw: str, default: tuple) -> tuple:
    try:
        vals = tuple(int(float(x)) for x in str(raw or "").split(",") if x.strip())
    except ValueError:
        return default
    return vals if len(vals) == 3 and vals[0] < vals[1] < vals[2] and vals[0] >= 1 else default


def profile(tf: str) -> dict | None:
    """H4 için özel profil; kapalıysa (`MA_BUY_H4_PROFILE_ENABLED=0`) veya başka dilimse None."""
    if str(tf or "") != H4 or not bool(getattr(config, "MA_BUY_H4_PROFILE_ENABLED", True)):
        return None
    rules_raw = str(getattr(config, "MA_BUY_H4_RULES", ma_buy_signals.RULE_MID_CROSS_SLOW) or "")
    rules = tuple(r.strip() for r in rules_raw.split(",") if r.strip() in (ma_buy_signals.RULE_FAST_CROSS_MID,
                                                                             ma_buy_signals.RULE_MID_CROSS_SLOW))
    return {
        "name": H4_PROFILE_NAME,
        "label": "H4 uzun vade",
        "periods": _periods(getattr(config, "MA_BUY_H4_PERIODS", "8,34,89"), (8, 34, 89)),
        "rules": rules or (ma_buy_signals.RULE_MID_CROSS_SLOW,),
        "min_body_pct": max(0.0, float(getattr(config, "MA_BUY_H4_MIN_BODY_PCT", 1.0) or 0.0)),
        "stoch_max": None,                                   # aramada StochRSI eleği kullanılmadı
        "stop_loss_pct": float(getattr(config, "MA_BUY_H4_STOP_PCT", 8.0) or 8.0),
        "max_hold_minutes": float(getattr(config, "MA_BUY_H4_MAX_HOLD_MIN", 4320) or 4320),
        "trailing": False,                                   # iz süren / başabaş stop yok (arama sonucu)
        "horizon_minutes": 240,                              # bir H4 mumu: yeniden açma ufku
    }


def exit_overrides(notification: dict) -> dict | None:
    """Zarftaki `exit_profile` (notify yazar) → auto_paper'ın uyguladığı sözlük; yoksa None."""
    ep = notification.get("exit_profile") if isinstance(notification, dict) else None
    if not isinstance(ep, dict) or not ep.get("name"):
        return None
    out = {"name": str(ep["name"]), "trailing": bool(ep.get("trailing", True))}
    for key in ("stop_loss_pct", "max_hold_minutes"):
        try:
            v = float(ep.get(key))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[key] = v
    return out


def rules_text(rules: str, periods: tuple, ma_type: str = "SMA") -> str:
    fast, mid, slow = periods
    names = {ma_buy_signals.RULE_FAST_CROSS_MID: f"{ma_type}{fast} ↗ {ma_type}{mid}",
             ma_buy_signals.RULE_MID_CROSS_SLOW: f"{ma_type}{mid} ↗ {ma_type}{slow}"}
    parts = [names.get(r.strip(), r.strip()) for r in str(rules or "").split(",") if r.strip()]
    return " + ".join(parts) or "MA kesişimi"
