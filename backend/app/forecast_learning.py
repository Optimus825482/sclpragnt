"""Deterministic evaluation and bounded lessons for journaled LLM forecasts.

Forecast outcomes are measured from subsequent closed candles.  Lessons are
derived from evaluated rows only; an LLM response can never promote itself.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


VALID_DIRECTIONS = {"up", "down", "range"}


def normalize_direction(value: object) -> str | None:
    mapping = {
        "up": "up", "yukarı": "up", "yukari": "up", "bullish": "up",
        "down": "down", "aşağı": "down", "asagi": "down", "bearish": "down",
        "range": "range", "yatay": "range", "flat": "range", "neutral": "range",
    }
    return mapping.get(str(value or "").strip().lower())


def evaluate_forecast(forecast: dict[str, Any], *, outcome_price: float, max_high: float,
                      min_low: float, evaluated_at: float,
                      first_hit_minutes: float | None = None) -> dict[str, Any]:
    entry = float(forecast["entry_price"])
    threshold = max(0.0001, float(forecast.get("min_move_pct") or 0.0015))
    return_pct = outcome_price / entry - 1 if entry else 0.0
    actual = "up" if return_pct >= threshold else "down" if return_pct <= -threshold else "range"
    direction = normalize_direction(forecast.get("direction")) or "range"
    return {
        "evaluated_at": evaluated_at,
        "outcome_price": outcome_price,
        "outcome_return_pct": return_pct,
        "outcome_direction": actual,
        "direction_correct": actual == direction,
        "max_favorable_pct": max_high / entry - 1 if entry else None,
        "max_adverse_pct": min_low / entry - 1 if entry else None,
        "details": {"threshold_pct": threshold, "predicted_direction": direction,
                    "invalidation_hit": _invalidation_hit(forecast, min_low, max_high),
                    # Hedefe ilk dokunuş dakikası (ufuk + grace penceresi).
                    "first_hit_minutes": first_hit_minutes,
                    "eventual_hit": first_hit_minutes is not None},
    }


def _invalidation_hit(forecast: dict[str, Any], low: float, high: float) -> bool | None:
    invalidation = forecast.get("invalidation_price")
    direction = normalize_direction(forecast.get("direction"))
    if invalidation in (None, "") or direction not in {"up", "down"}:
        return None
    return low <= float(invalidation) if direction == "up" else high >= float(invalidation)


def derive_lessons(rows: list[dict[str, Any]], *, min_samples: int = 12) -> list[dict[str, Any]]:
    """Require chronological holdout evidence before a lesson becomes active."""
    grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("status") != "evaluated" or row.get("direction_correct") is None:
            continue
        direction = normalize_direction(row.get("direction"))
        if direction is None:
            continue
        regime = row.get("regime") or "unknown"
        symbol = str(row.get("symbol") or "").upper() or None
        horizon = int(row.get("horizon_minutes") or 0)
        grouped[(symbol, horizon, regime, direction)].append(row)
        grouped[(None, horizon, regime, direction)].append(row)

    lessons = []
    for (symbol, horizon, regime, direction), samples in grouped.items():
        samples.sort(key=lambda item: float(item.get("created_at") or 0))
        if len(samples) < min_samples:
            continue
        split = max(1, int(len(samples) * 0.70))
        train, holdout = samples[:split], samples[split:]
        if len(holdout) < max(3, min_samples // 3):
            continue
        train_accuracy = _accuracy(train)
        holdout_accuracy = _accuracy(holdout)
        calibration = _calibration_error(samples)
        # A lesson can guide wording only after holdout consistency.  It never
        # changes an entry gate or makes a forecast a trade instruction.
        active = holdout_accuracy >= 0.55 and abs(holdout_accuracy - train_accuracy) <= 0.20
        label = "destekleyici" if active else "temkinli"
        subject = symbol or "genel evren"
        lesson = (f"{subject} · {regime} rejiminde {horizon}dk {direction} tahminleri "
                  f"{len(samples)} örnekte holdout %{holdout_accuracy * 100:.0f} doğruluk verdi; {label} bağlamdır.")
        key = f"forecast:{symbol or 'global'}:{horizon}:{regime}:{direction}"
        lessons.append({
            "lesson_key": key, "symbol": symbol, "horizon_minutes": horizon, "regime": regime,
            "direction": direction, "sample_size": len(samples), "in_sample_accuracy": train_accuracy,
            "holdout_accuracy": holdout_accuracy, "confidence_calibration_error": calibration,
            "lesson": lesson, "status": "active" if active else "candidate",
            "evidence": {"train_size": len(train), "holdout_size": len(holdout),
                         "train_accuracy": train_accuracy, "holdout_accuracy": holdout_accuracy,
                         "calibration_error": calibration, "policy": "forecast_journal_holdout_only"},
        })
    return lessons


def _accuracy(rows: list[dict[str, Any]]) -> float:
    return sum(bool(item.get("direction_correct")) for item in rows) / len(rows) if rows else 0.0


# ---------------------------------------------------------------------------
# Hedef desen madenciliği: ölçülen upside-scout satırlarından okunabilir
# kurallar türetir (snapshot koşulu -> hedefe ulaşma oranı). ML modelinin
# gölge tahminini okunabilir derslerle tamamlar; kurallar yalnızca bağlam
# olarak scout'a akar, giriş kapısı veya emir kararı değildir.
# ---------------------------------------------------------------------------

_PATTERN_CONDITIONS = {
    "m5_desen_uyumlu": lambda s: s.get("m5_pattern_ok") is True,
    "m5_desen_uyumsuz": lambda s: s.get("m5_pattern_ok") is False,
    "oncu_atr_uyumlu": lambda s: s.get("leading_ok") is True,
    "oncu_atr_uyumsuz": lambda s: s.get("leading_ok") is False,
    "rsi_40_alti": lambda s: s.get("rsi") is not None and float(s["rsi"]) < 40,
    "rsi_40_55": lambda s: s.get("rsi") is not None and 40 <= float(s["rsi"]) < 55,
    "rsi_55_70": lambda s: s.get("rsi") is not None and 55 <= float(s["rsi"]) < 70,
    "rsi_70_uzeri": lambda s: s.get("rsi") is not None and float(s["rsi"]) >= 70,
    "atr_08_alti": lambda s: s.get("atr_pct") is not None and float(s["atr_pct"]) < 0.8,
    "atr_08_15": lambda s: s.get("atr_pct") is not None and 0.8 <= float(s["atr_pct"]) < 1.5,
    "atr_15_uzeri": lambda s: s.get("atr_pct") is not None and float(s["atr_pct"]) >= 1.5,
    "bb_dar_3_alti": lambda s: s.get("bb_width_pct") is not None and float(s["bb_width_pct"]) < 3,
    "bb_genis_6_uzeri": lambda s: s.get("bb_width_pct") is not None and float(s["bb_width_pct"]) >= 6,
    "aroon_up_60_uzeri": lambda s: s.get("aroon_up") is not None and float(s["aroon_up"]) >= 60,
    "aroon_up_40_alti": lambda s: s.get("aroon_up") is not None and float(s["aroon_up"]) < 40,
    "ret3_pozitif": lambda s: s.get("ret3_pct") is not None and float(s["ret3_pct"]) > 0,
    "ret3_negatif": lambda s: s.get("ret3_pct") is not None and float(s["ret3_pct"]) <= 0,
    "hiz_puani_10_uzeri": lambda s: s.get("velocity_score") is not None and float(s["velocity_score"]) >= 10,
    "hiz_puani_3_alti": lambda s: s.get("velocity_score") is not None and float(s["velocity_score"]) < 3,
}


def _target_hit(row: dict[str, Any]) -> bool | None:
    mfe, threshold = row.get("max_favorable_pct"), row.get("min_move_pct")
    if row.get("status") != "evaluated" or mfe is None or threshold in (None, 0):
        return None
    return float(mfe) >= float(threshold)


def mine_target_patterns(rows: list[dict[str, Any]], *, min_support: int = 8,
                         min_lift: float = 1.25) -> list[dict[str, Any]]:
    """Koşul -> isabet oranını tarar; anlamlı sapmaları ders üretir.

    Bir ders ancak (1) destek >= min_support, (2) lift >= min_lift (veya
    olumsuz yönde <= 1/min_lift) ve (3) kronolojik son %30'da etki aynı
    yönde sürüyorsa 'active' olur; aksi halde 'candidate' olarak kaydedilir.
    """
    samples = []
    for row in rows or []:
        hit = _target_hit(row)
        if hit is None:
            continue
        snap = row.get("snapshot") or {}
        samples.append({"hit": hit, "snap": snap,
                        "created_at": float(row.get("created_at") or 0),
                        "horizon": int(row.get("horizon_minutes") or 0),
                        "symbol": str(row.get("symbol") or "").upper() or None})
    if not samples:
        return []
    baseline = sum(1 for s in samples if s["hit"]) / len(samples)
    if baseline in (0.0, 1.0):
        return []
    lessons = []
    for name, condition in _PATTERN_CONDITIONS.items():
        matched = [s for s in samples if condition(s["snap"])]
        if len(matched) < min_support:
            continue
        hit_rate = sum(1 for s in matched if s["hit"]) / len(matched)
        lift = hit_rate / baseline
        favorable = lift >= min_lift
        unfavorable = lift <= 1 / min_lift
        if not (favorable or unfavorable):
            continue
        matched.sort(key=lambda item: item["created_at"])
        tail = matched[int(len(matched) * 0.70):]
        tail_rate = (sum(1 for s in tail if s["hit"]) / len(tail)) if tail else hit_rate
        tail_lift = tail_rate / baseline
        consistent = (tail_lift >= min_lift) if favorable else (tail_lift <= 1 / min_lift)
        active = len(matched) >= min_support * 2 and consistent
        label = "destekleyici" if favorable else "uyarı"
        subject = f"{matched[0]['symbol']} odaklı" if len({s['symbol'] for s in matched}) == 1 else "genel"
        lesson = (f"DESEN · {subject} '{name}' koşulu {len(matched)} örnekte %{hit_rate * 100:.0f} "
                  f"hedefe ulaşma oranı gösterdi (genel %{baseline * 100:.0f}, lift {lift:.2f}); "
                  f"son dönem lift {tail_lift:.2f} → {label} bağlam.")
        lessons.append({
            "lesson_key": f"pattern:{name}", "symbol": None, "horizon_minutes": 0,
            "regime": "pattern", "direction": "up" if favorable else "down",
            "sample_size": len(matched), "in_sample_accuracy": hit_rate,
            "holdout_accuracy": tail_rate, "confidence_calibration_error": abs(lift - 1),
            "lesson": lesson, "status": "active" if active else "candidate",
            "evidence": {"pattern": name, "baseline": round(baseline, 4),
                         "hit_rate": round(hit_rate, 4), "lift": round(lift, 3),
                         "tail_lift": round(tail_lift, 3), "min_support": min_support,
                         "policy": "context_only_never_entry_gate"},
        })
    return lessons


def _calibration_error(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 1.0
    return sum(abs(float(item.get("confidence") or 0) / 100 - float(bool(item.get("direction_correct")))) for item in rows) / len(rows)
