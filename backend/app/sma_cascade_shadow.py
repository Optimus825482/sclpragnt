"""Paper-only observation of the 1m SMA 7/25/99 cascade.

This module deliberately has no dependency on the trade executor.  It detects
the user-defined ordering (7 crosses 25, then 99, then 25 crosses 99) using
closed one-minute candles and emits research events for a caller to persist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(float(value) for value in values[-period:]) / period


def crossed_up(previous_left: float | None, previous_right: float | None,
               current_left: float | None, current_right: float | None) -> bool:
    return all(value is not None for value in (previous_left, previous_right, current_left, current_right)) and (
        float(previous_left) <= float(previous_right) and float(current_left) > float(current_right)
    )


@dataclass
class CascadeState:
    last_timestamp_ms: int = 0
    first_cross_at_ms: int | None = None
    second_cross_at_ms: int | None = None
    first_cross_price: float | None = None
    sequence_high: float | None = None
    sequence_low: float | None = None
    pending_cascade: dict[str, Any] | None = None
    pending_outcomes: list[dict[str, Any]] = field(default_factory=list)


class SmaCascadeShadow:
    """Stateful closed-candle detector; it never opens or modifies positions."""

    def __init__(self, max_sequence_minutes: int = 10, breakout_window_minutes: int = 30,
                 outcome_window_minutes: int = 30):
        self.max_sequence_ms = max(1, int(max_sequence_minutes)) * 60_000
        self.breakout_window_ms = max(1, int(breakout_window_minutes)) * 60_000
        self.outcome_window_ms = max(1, int(outcome_window_minutes)) * 60_000
        self.states: dict[str, CascadeState] = {}

    @staticmethod
    def _ma_values(closes: list[float]) -> tuple[float | None, float | None, float | None]:
        return sma(closes, 7), sma(closes, 25), sma(closes, 99)

    def process(self, symbol: str, bars: dict[str, list[float]]) -> list[dict[str, Any]]:
        """Consume the latest *closed* 1m bar and return zero or more events."""
        timestamps = list(bars.get("timestamps") or [])
        closes = list(bars.get("closes") or [])
        highs = list(bars.get("highs") or [])
        lows = list(bars.get("lows") or [])
        if min(len(timestamps), len(closes), len(highs), len(lows)) < 100:
            return []
        timestamp_ms = int(timestamps[-1])
        state = self.states.setdefault(symbol.upper(), CascadeState())
        if timestamp_ms <= state.last_timestamp_ms:
            return []
        state.last_timestamp_ms = timestamp_ms

        previous = self._ma_values(closes[:-1])
        current = self._ma_values(closes)
        ma7, ma25, ma99 = current
        if any(value is None for value in current):
            return []

        price = float(closes[-1])
        high = float(highs[-1])
        low = float(lows[-1])
        events: list[dict[str, Any]] = []

        # Keep the observed MFE/MAE for any earlier breakout alive on every
        # closed bar before deciding whether its 30-minute window has ended.
        retained_outcomes = []
        for outcome in state.pending_outcomes:
            outcome["max_high"] = max(float(outcome["max_high"]), high)
            outcome["min_low"] = min(float(outcome["min_low"]), low)
            if timestamp_ms - int(outcome["breakout_at_ms"]) >= self.outcome_window_ms:
                entry = float(outcome["entry_price"])
                events.append({
                    "type": "outcome_30m",
                    "event_id": outcome["event_id"],
                    "cascade_at_ms": outcome["cascade_at_ms"],
                    "breakout_at_ms": outcome["breakout_at_ms"],
                    "entry_price": entry,
                    "price": price,
                    "return_pct": (price / entry - 1) * 100 if entry else None,
                    "max_favorable_pct": (float(outcome["max_high"]) / entry - 1) * 100 if entry else None,
                    "max_adverse_pct": (float(outcome["min_low"]) / entry - 1) * 100 if entry else None,
                    "ma7": ma7, "ma25": ma25, "ma99": ma99,
                })
            else:
                retained_outcomes.append(outcome)
        state.pending_outcomes = retained_outcomes

        if state.pending_cascade:
            pending = state.pending_cascade
            elapsed = timestamp_ms - int(pending["cascade_at_ms"])
            if elapsed > self.breakout_window_ms:
                state.pending_cascade = None
            elif timestamp_ms > int(pending["cascade_at_ms"]) and price > float(pending["cascade_high"]):
                event_id = f"{symbol.upper()}-{int(pending['cascade_at_ms'])}"
                breakout = {
                    "type": "breakout_observed", "event_id": event_id,
                    "cascade_at_ms": pending["cascade_at_ms"], "breakout_at_ms": timestamp_ms,
                    "price": price, "cascade_high": pending["cascade_high"], "cascade_low": pending["cascade_low"],
                    "ma7": ma7, "ma25": ma25, "ma99": ma99,
                }
                events.append(breakout)
                state.pending_outcomes.append({
                    "event_id": event_id, "cascade_at_ms": pending["cascade_at_ms"],
                    "breakout_at_ms": timestamp_ms, "entry_price": price, "max_high": high, "min_low": low,
                })
                state.pending_cascade = None

        # A stage expires rather than being allowed to combine unrelated
        # crossovers hours apart.
        if state.first_cross_at_ms and timestamp_ms - state.first_cross_at_ms > self.max_sequence_ms:
            state.first_cross_at_ms = state.second_cross_at_ms = None
            state.first_cross_price = state.sequence_high = state.sequence_low = None

        if state.first_cross_at_ms:
            state.sequence_high = max(float(state.sequence_high or high), high)
            state.sequence_low = min(float(state.sequence_low or low), low)

        if crossed_up(previous[0], previous[1], ma7, ma25):
            state.first_cross_at_ms = timestamp_ms
            state.second_cross_at_ms = None
            state.first_cross_price = price
            state.sequence_high, state.sequence_low = high, low

        elif state.first_cross_at_ms and crossed_up(previous[0], previous[2], ma7, ma99):
            state.second_cross_at_ms = timestamp_ms

        elif state.first_cross_at_ms and state.second_cross_at_ms and crossed_up(previous[1], previous[2], ma25, ma99):
            cascade_at_ms = timestamp_ms
            event_id = f"{symbol.upper()}-{cascade_at_ms}"
            cascade = {
                "type": "cascade_detected", "event_id": event_id, "cascade_at_ms": cascade_at_ms,
                "first_cross_at_ms": state.first_cross_at_ms, "second_cross_at_ms": state.second_cross_at_ms,
                "price": price, "cascade_high": max(float(state.sequence_high or high), high),
                "cascade_low": min(float(state.sequence_low or low), low),
                "ma7": ma7, "ma25": ma25, "ma99": ma99,
            }
            events.append(cascade)
            state.pending_cascade = dict(cascade)
            state.first_cross_at_ms = state.second_cross_at_ms = None
            state.first_cross_price = state.sequence_high = state.sequence_low = None

        return events
