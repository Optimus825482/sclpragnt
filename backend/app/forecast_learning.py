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
                      min_low: float, evaluated_at: float) -> dict[str, Any]:
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
                    "invalidation_hit": _invalidation_hit(forecast, min_low, max_high)},
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


def _calibration_error(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 1.0
    return sum(abs(float(item.get("confidence") or 0) / 100 - float(bool(item.get("direction_correct")))) for item in rows) / len(rows)
