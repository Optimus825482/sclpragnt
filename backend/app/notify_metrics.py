"""Bildirimde gösterilen sayıların DÜRÜST karşılıkları (2026-10-18; canlı yol).

Kaynak: docs/HEDEF_SKOR_OLASILIK_OZET_2026-10-18.md ve üç denetim raporu.
  * `measured_target_pct`  — hedef = ölçülmüş ulaşılabilirlik (nominal %30 isabet; HEDEF_DENETIMI §6).
  * `calibrated_hit_prob`  — kalibre "tahmini isabet %" (SKOR_DENETIMI §6.1, SL %5 rejimi, haftalık yeniden uydurulur).
  * `breakeven_hit_prob`   — başabaş isabet = kayıp / (kazanç + kayıp) (SKOR_DENETIMI §6.2).
  * `target_net_pct`       — net hedef = brüt hedef − kâr-al gidiş-dönüş maliyeti.

Hepsi SAF fonksiyondur (ağ/DB yok); bozuk/NaN girdide istisna FIRLATMAZ (None ya da güvenli varsayılan döner).
`config` yalnız bayrak/maliyet varsayılanları için ÇAĞRI ANINDA okunur. (`app/hit_calibration.py` kullanılmayan
eski bir taslaktır; canlı yol BU modüldür.)
"""
from __future__ import annotations

import math
from typing import Sequence

SCORE_LABEL = "hareket_siddeti"   # panel skoru kalite değil, oynaklık/hareket şiddetidir (AUC≈0,5, ATR kontrollü)

DEFAULT_MEASURED_COEFS = (0.27, 0.71, 0.06, 0.51)       # a, b, c, d (nominal %30 isabet)
DEFAULT_HIT_PROB_COEFS = (1.106, -0.675, -1.402, 0.059)  # b0, b1 (ln ATR), b2 (ln hedef/ATR), b3 (ufuk>=15)

TARGET_MIN_PCT = 0.5
TARGET_MAX_PCT = 6.0
_ATR_MIN, _ATR_MAX = 0.05, 5.0       # modelin kurulduğu ATR% aralığı
_SCORE_MIN, _SCORE_MAX = 30.0, 100.0  # panel skoru kelepçesi
_FALLBACK_ATR_PCT = 0.8              # ATR bilinmiyorsa (None/NaN/<=0) tipik 5 dk ATR%; ölçülmüş hedef orta değer verir
_P_MIN, _P_MAX = 0.01, 0.99


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_coefs(raw, default: Sequence[float]) -> tuple[float, ...]:
    """'a,b,c,d' metni (ya da dizi) → float demeti; bozuksa/uzunluk uyuşmuyorsa `default`."""
    want = len(default)
    if raw is None:
        return tuple(default)
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        parts = [p for p in str(raw).replace(";", ",").split(",") if p.strip()]
    values = [_finite(p) for p in parts]
    if len(values) != want or any(v is None for v in values):
        return tuple(default)
    return tuple(float(v) for v in values)


def measured_target_pct(atr_pct, horizon_minutes, score_panel, coefs=None) -> float:
    """T = clamp(exp(a)·atr_pct^b·(ufuk/5)^d·exp(c·(skor−70)/10), 0,5, 6,0) — YÜZDE.

    atr_pct: sinyal anındaki ATR14 % (dedektörün kullandığı); [0,05; 5] aralığına kısılır; bilinmiyorsa
    sabit tipik değer (0,8) kullanılır. horizon_minutes: bilinmiyor/≤0 → 5; [1, 60] kısılır.
    score_panel: 0–100 panel skoru; [30, 100] kısılır; bilinmiyorsa 70 (skor terimi 0).
    ATR ve ufukta MONOTON artan (b, d > 0), skorda c > 0 ile artan. NaN/bozuk girdi güvenli varsayılana düşer.
    """
    a, b, c, d = parse_coefs(coefs, DEFAULT_MEASURED_COEFS)
    atr = _finite(atr_pct)
    atr = _FALLBACK_ATR_PCT if (atr is None or atr <= 0) else min(_ATR_MAX, max(_ATR_MIN, atr))
    horizon = _finite(horizon_minutes)
    horizon = 5.0 if (horizon is None or horizon <= 0) else min(60.0, max(1.0, horizon))
    score = _finite(score_panel)
    score = 70.0 if score is None else min(_SCORE_MAX, max(_SCORE_MIN, score))
    exponent = a + b * math.log(atr) + d * math.log(horizon / 5.0) + c * (score - 70.0) / 10.0
    target = math.exp(exponent)
    if not math.isfinite(target):
        target = TARGET_MAX_PCT
    return round(min(TARGET_MAX_PCT, max(TARGET_MIN_PCT, target)), 3)


def calibrated_hit_prob(atr_pct, target_pct, horizon_minutes, coefs=None, model: str | None = None) -> float | None:
    """σ(b0 + b1·ln ATR% + b2·ln(hedef%/ATR%) + b3·[ufuk ≥ 15]) → 0–1; model 'off' ya da girdi geçersizse None.

    Katsayılar çıkış rejimine (SL %5) bağlıdır; HAFTALIK yeniden uydurulmalıdır. Sonuç [0,01; 0,99] kısılır
    (kullanıcıya %0/%100 gösterilmez).
    """
    if str(model if model is not None else _cfg("RADAR_HIT_PROB_MODEL", "logistic")).strip().lower() in {"off", "none", "0", "false", ""}:
        return None
    atr = _finite(atr_pct)
    target = _finite(target_pct)
    if atr is None or target is None or atr <= 0 or target <= 0:
        return None
    if coefs is None:
        coefs = _cfg("RADAR_HIT_PROB_COEFS", None)
    b0, b1, b2, b3 = parse_coefs(coefs, DEFAULT_HIT_PROB_COEFS)
    atr = min(_ATR_MAX, max(_ATR_MIN, atr))
    horizon = _finite(horizon_minutes) or 0.0
    z = b0 + b1 * math.log(atr) + b2 * math.log(target / atr) + b3 * (1.0 if horizon >= 15 else 0.0)
    prob = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
    return round(min(_P_MAX, max(_P_MIN, prob)), 4)


def breakeven_hit_prob(target_pct, sl_pct=None, cost_tp_pct=None, cost_stop_pct=None) -> float | None:
    """Başabaş isabet = kayıp / (kazanç + kayıp); kazanç = hedef − cost_tp, kayıp = SL + cost_stop (YÜZDE).

    Varsayılanlar: sl = AUTO_PAPER_SL_PCT_DEFAULT, cost_tp = round_trip_cost_tp()·100 (kâr-al maker),
    cost_stop = round_trip_cost()·100. Kazanç ≤ 0 ise (hedef maliyeti karşılamıyor) 1,0 döner. Geçersiz girdi → None.
    """
    target = _finite(target_pct)
    if target is None or target <= 0:
        return None
    sl = _finite(sl_pct)
    if sl is None:
        sl = _finite(_cfg("AUTO_PAPER_SL_PCT_DEFAULT", 5.0))
    cost_tp = _finite(cost_tp_pct)
    if cost_tp is None:
        cost_tp = default_cost_tp_pct()
    cost_stop = _finite(cost_stop_pct)
    if cost_stop is None:
        cost_stop = default_cost_stop_pct()
    if sl is None or sl <= 0 or cost_tp is None or cost_stop is None:
        return None
    gain = target - cost_tp
    loss = sl + cost_stop
    if gain <= 0:
        return 1.0
    return round(loss / (gain + loss), 4)


def target_net_pct(target_pct, cost_tp_pct=None) -> float | None:
    """Net hedef = brüt hedef − kâr-al gidiş-dönüş maliyeti (YÜZDE; maliyetin altındaysa negatif olabilir)."""
    target = _finite(target_pct)
    if target is None:
        return None
    cost_tp = _finite(cost_tp_pct)
    if cost_tp is None:
        cost_tp = default_cost_tp_pct()
    if cost_tp is None:
        return None
    return round(target - cost_tp, 3)


def default_cost_tp_pct() -> float | None:
    """config.round_trip_cost_tp()·100 (kâr-al çıkışı); okunamazsa None."""
    return _cost_pct("round_trip_cost_tp")


def default_cost_stop_pct() -> float | None:
    """config.round_trip_cost()·100 (stop / zaman çıkışı); okunamazsa None."""
    return _cost_pct("round_trip_cost")


def notification_metrics(target_pct, atr_pct, horizon_minutes) -> dict:
    """Bildirim sözlüğüne eklenecek dört alan (contract: frontend bu adlara bağlı).

    {'hit_prob_calibrated': 0–1|None, 'breakeven_hit_prob': 0–1|None,
     'target_net_pct': float|None, 'score_label': 'hareket_siddeti'}
    """
    return {
        "hit_prob_calibrated": calibrated_hit_prob(atr_pct, target_pct, horizon_minutes),
        "breakeven_hit_prob": breakeven_hit_prob(target_pct),
        "target_net_pct": target_net_pct(target_pct),
        "score_label": SCORE_LABEL,
    }


def _cfg(name: str, default):
    try:
        from app.config import config
        return getattr(config, name, default)
    except Exception:  # pragma: no cover - config yüklenemezse saf varsayılan
        return default


def _cost_pct(method: str) -> float | None:
    try:
        from app.config import config
        return _finite(float(getattr(config, method)()) * 100.0)
    except Exception:
        return None
