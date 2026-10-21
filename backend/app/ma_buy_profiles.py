"""MA BUY — zaman dilimine özel sinyal/çıkış profilleri (2026-10-21: H4).

H4 sinyali (kullanıcı kararı, 2026-10-21 akşam, 18:30 güncellemesi): MA7 MA20'yi YUKARI keser → sinyal. MA99 şartı
(orta > yavaş) ARANMAZ; orta×yavaş kuralı varsayılan listede yok (`MA_BUY_H4_RULES` ile eklenebilir); gövde ve StochRSI
eleği yok; MA türü grafik şeridiyle aynı (`MA_BUY_MA_TYPE`, varsayılan SMA). Grafikteki BUY rozeti MA99 şartını
koruduğu için H4'te rozetten DAHA ÇOK sinyal üretir — bilinçli. 19:15: sembolün 24 sa TL hacmi `MA_BUY_H4_MIN_QUOTE_VOLUME`
(5M) altındaysa H4 sinyali yok (izleyici ve radar sekmesi aynı eşiği kullanır). Paper çıkışı (19:46, replay B tablosu): hedef %10, stop %8,
en çok 1 gün, iz süren stop %3 tetik / %1,5 mesafe, başabaş stop YOK, dinamik tetik/mesafe YOK (replay simülasyonuyla birebir). Aramanın bulduğu SMA 8/34/89 orta×yavaş + gövde ≥ %1 ayarı
(docs/MA_KESISIM_H4_ARAMA_90g_2026-10-21.md) `MA_BUY_H4_PERIODS/RULES/MIN_BODY_PCT` ile geri alınabilir.
Diğer dilimler genel ayarlarla (MA_BUY_PERIODS, iki kural, StochRSI ≤ 80, otonom paper çıkış profili) çalışmaya devam eder.

Saf modül: config okur, DB/ağ yok. `profile(tf)` None dönerse o dilimde özel profil yoktur.
"""
from __future__ import annotations

from app import ma_buy_signals
from app.config import config

H4 = "4h"
H4_PROFILE_NAME = "ma_buy_h4"
DEFAULT_H4_PERIODS = (7, 20, 99)
DEFAULT_H4_RULES = ma_buy_signals.RULE_FAST_CROSS_MID


def _periods(raw: str, default: tuple) -> tuple:
    try:
        vals = tuple(int(float(x)) for x in str(raw or "").split(",") if x.strip())
    except ValueError:
        return default
    return vals if len(vals) == 3 and vals[0] < vals[1] < vals[2] and vals[0] >= 1 else default


def ma_type() -> str:
    """Grafikteki MA şeridiyle aynı tür: "sma" | "ema" (`MA_BUY_MA_TYPE`)."""
    kind = str(getattr(config, "MA_BUY_MA_TYPE", "sma") or "sma").strip().lower()
    return kind if kind in ("sma", "ema") else "sma"


def profile(tf: str) -> dict | None:
    """H4 için özel profil; kapalıysa (`MA_BUY_H4_PROFILE_ENABLED=0`) veya başka dilimse None."""
    if str(tf or "") != H4 or not bool(getattr(config, "MA_BUY_H4_PROFILE_ENABLED", True)):
        return None
    rules_raw = str(getattr(config, "MA_BUY_H4_RULES", DEFAULT_H4_RULES) or "")
    rules = tuple(r.strip() for r in rules_raw.split(",") if r.strip() in ma_buy_signals.ALL_RULES)
    return {
        "name": H4_PROFILE_NAME,
        "label": "H4 uzun vade",
        "periods": _periods(getattr(config, "MA_BUY_H4_PERIODS", "7,20,99"), DEFAULT_H4_PERIODS),
        "rules": rules or (ma_buy_signals.RULE_FAST_CROSS_MID,),
        "require_mid_above_slow": bool(getattr(config, "MA_BUY_H4_REQUIRE_MID_ABOVE_SLOW", False)),
        "min_quote_volume": max(0.0, float(getattr(config, "MA_BUY_H4_MIN_QUOTE_VOLUME", 5_000_000) or 0.0)),  # 24 sa TL hacim tabanı
        "ma_type": ma_type(),
        "min_body_pct": max(0.0, float(getattr(config, "MA_BUY_H4_MIN_BODY_PCT", 0.0) or 0.0)),
        "stoch_max": None,                                   # H4'te StochRSI eleği yok (kullanıcı: saf kesişim)
        "stop_loss_pct": float(getattr(config, "MA_BUY_H4_STOP_PCT", 8.0) or 8.0),
        "max_hold_minutes": float(getattr(config, "MA_BUY_H4_MAX_HOLD_MIN", 1440) or 1440),
        **trailing_params(),
        "horizon_minutes": 240,                              # bir H4 mumu: yeniden açma ufku
    }


def trailing_params() -> dict:
    """H4 iz süren stop ayarı (config): {trailing, trailing_trigger_pct, trailing_gap_pct}."""
    return {"trailing": bool(getattr(config, "MA_BUY_H4_TRAILING", True)),
            "trailing_trigger_pct": max(0.1, float(getattr(config, "MA_BUY_H4_TRAIL_TRIGGER_PCT", 3.0) or 3.0)),
            "trailing_gap_pct": max(0.1, float(getattr(config, "MA_BUY_H4_TRAIL_GAP_PCT", 1.5) or 1.5))}


def manage_params(exit_profile_name) -> dict | None:
    """auto_paper pozisyon yönetimi: işlemin `exit_profile` adına göre iz süren stop kuralı; profil dışı işlemde None.
    Profil kapatılmış olsa da eski açık işlemler aynı kuralla yönetilir (config'ten okunur). Başabaş stop ve dinamik
    tetik/mesafe profilli işlemde uygulanmaz."""
    if str(exit_profile_name or "") != H4_PROFILE_NAME:
        return None
    return {**trailing_params(), "breakeven": False, "dynamic": False}


def exit_overrides(notification: dict) -> dict | None:
    """Zarftaki `exit_profile` (notify yazar) → auto_paper'ın uyguladığı sözlük; yoksa None."""
    ep = notification.get("exit_profile") if isinstance(notification, dict) else None
    if not isinstance(ep, dict) or not ep.get("name"):
        return None
    out = {"name": str(ep["name"]), "trailing": bool(ep.get("trailing", True))}
    for key in ("stop_loss_pct", "max_hold_minutes", "trailing_trigger_pct", "trailing_gap_pct"):
        try:
            v = float(ep.get(key))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[key] = v
    return out


def rules_text(rules: str, periods: tuple, ma_type: str = "SMA") -> str:
    fast, mid, slow = periods
    kind = str(ma_type or "SMA").upper()
    names = {ma_buy_signals.RULE_FAST_CROSS_MID: f"{kind}{fast} ↗ {kind}{mid}",
             ma_buy_signals.RULE_MID_CROSS_SLOW: f"{kind}{mid} ↗ {kind}{slow}"}
    parts = [names.get(r.strip(), r.strip()) for r in str(rules or "").split(",") if r.strip()]
    return " + ".join(parts) or "MA kesişimi"
