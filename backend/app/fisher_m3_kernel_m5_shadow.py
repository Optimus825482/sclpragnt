"""Closed-M1, paper-only observer for Fisher M3 + Kernel M5 signals."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def _fisher(highs: list[float], lows: list[float], length: int = 11) -> list[tuple[float | None, float | None]]:
    value = f1 = 0.0
    output = []
    for index, (high, low) in enumerate(zip(highs, lows)):
        if index + 1 < length:
            output.append((None, None)); continue
        mids = [(highs[i] + lows[i]) / 2 for i in range(index - length + 1, index + 1)]
        hi, lo, mid = max(mids), min(mids), (high + low) / 2
        ratio = (mid - lo) / (hi - lo) - 0.5 if hi != lo else 0.0
        previous_f1 = f1
        value = max(-0.999, min(0.999, 0.66 * ratio + 0.67 * value))
        f1 = 0.5 * math.log((1 + value) / (1 - value)) + 0.5 * previous_f1
        output.append((f1, previous_f1))
    return output


def _kernel(closes: list[float], h: int = 8, relative_weight: float = 8.0,
            level: int = 25, lag: int = 2) -> tuple[float | None, float | None]:
    if len(closes) < level + h + 1:
        return None, None
    gaussian_h, ws_rq, wt_rq, ws_g, wt_g = max(h - lag, 1), 0.0, 0.0, 0.0, 0.0
    for offset in range(level + h + 1):
        close = float(closes[-1 - offset])
        rq_weight = math.pow(1 + offset ** 2 / (2 * relative_weight * h ** 2), -relative_weight)
        g_weight = math.exp(-(offset ** 2) / (2 * gaussian_h ** 2))
        ws_rq += close * rq_weight; wt_rq += rq_weight; ws_g += close * g_weight; wt_g += g_weight
    return ws_rq / wt_rq, ws_g / wt_g


@dataclass
class _State:
    last_m1_timestamp: int = 0
    last_m3_timestamp: int = 0


class FisherM3KernelM5Shadow:
    """Observe exact closed-candle candidates without calling the executor."""

    def __init__(self):
        self.states: dict[str, _State] = {}

    @staticmethod
    def snapshot(symbol: str, m1: dict[str, list[float]], m3: dict[str, list[float]],
                 m5: dict[str, list[float]]) -> dict[str, Any]:
        """Return the current rule state without changing signal-observer state."""
        m1_times = list(m1.get("timestamps") or [])
        m1_closes = list(m1.get("closes") or [])
        m3_times = list(m3.get("timestamps") or [])
        m3_highs = list(m3.get("highs") or [])
        m3_lows = list(m3.get("lows") or [])
        m5_closes = list(m5.get("closes") or [])
        base: dict[str, Any] = {
            "symbol": symbol.upper(), "m3_candles": min(len(m3_times), len(m3_highs), len(m3_lows)),
            "m5_candles": len(m5_closes), "m1_closed_at_ms": int(m1_times[-1]) if m1_times else None,
            "m3_closed_at_ms": int(m3_times[-1]) if m3_times else None,
            "price": float(m1_closes[-1]) if m1_closes else None,
        }
        if not m1_times or not m1_closes:
            return {**base, "ready": False, "state": "WARMING", "reason": "M1 kapanmış mum bekleniyor"}
        if min(len(m3_times), len(m3_highs), len(m3_lows)) < 12:
            return {**base, "ready": False, "state": "WARMING", "reason": "M3 Fisher için mum birikiyor"}
        if len(m5_closes) < 34:
            return {**base, "ready": False, "state": "WARMING", "reason": "M5 Kernel için mum birikiyor"}

        series = _fisher([float(value) for value in m3_highs], [float(value) for value in m3_lows])
        current, previous = series[-1], series[-2]
        rq, gaussian = _kernel([float(value) for value in m5_closes])
        if any(value is None for value in (*current, *previous, rq, gaussian)):
            return {**base, "ready": False, "state": "WARMING", "reason": "Gösterge hesaplaması hazırlanıyor"}
        fish1, fish2 = current
        prev1, prev2 = previous
        cross_up, cross_down = fish1 > fish2 and prev1 <= prev2, fish1 < fish2 and prev1 >= prev2
        green = gaussian >= rq
        entry_zone, exit_zone = fish1 < -1.0, fish1 > 2.0
        long_ready, exit_ready = cross_up and entry_zone and green, cross_down and exit_zone
        if long_ready:
            state, reason = "LONG_READY", "Fisher yukarı kesti · giriş eşiği altında · Kernel yeşil"
        elif exit_ready:
            state, reason = "EXIT_READY", "Fisher aşağı kesti · çıkış eşiği üstünde"
        elif cross_up and entry_zone:
            state, reason = "KERNEL_RED", "Fisher kesişimi var · Kernel kırmızı"
        elif cross_up:
            state, reason = "ENTRY_LEVEL", "Fisher kesişimi var · giriş eşiğinin altında değil"
        elif green:
            state, reason = "WAITING_FISHER", "Kernel yeşil · Fisher yukarı kesişimi bekleniyor"
        else:
            state, reason = "WAITING_KERNEL", "Kernel kırmızı · Fisher ve Kernel onayı bekleniyor"
        return {
            **base, "ready": True, "state": state, "reason": reason,
            "fisher": fish1, "trigger": fish2, "fisher_cross_up": cross_up,
            "fisher_cross_down": cross_down, "fisher_entry_zone": entry_zone,
            "kernel_rq": rq, "kernel_gaussian": gaussian, "kernel_green": green,
            "long_ready": long_ready, "exit_ready": exit_ready,
        }

    def process(self, symbol: str, m1: dict[str, list[float]], m3: dict[str, list[float]],
                m5: dict[str, list[float]]) -> list[dict[str, Any]]:
        m1_times = list(m1.get("timestamps") or [])
        m3_times, m3_highs, m3_lows = list(m3.get("timestamps") or []), list(m3.get("highs") or []), list(m3.get("lows") or [])
        m5_closes = list(m5.get("closes") or [])
        if not m1_times or min(len(m3_times), len(m3_highs), len(m3_lows)) < 12 or len(m5_closes) < 34:
            return []
        state = self.states.setdefault(symbol.upper(), _State())
        m1_timestamp, m3_timestamp = int(m1_times[-1]), int(m3_times[-1])
        if m1_timestamp <= state.last_m1_timestamp:
            return []
        state.last_m1_timestamp = m1_timestamp
        # request.security(..., lookahead_off) only changes when this source
        # M3 candle closes; emitting once prevents carried values becoming a
        # repeated M1 signal.
        if m3_timestamp <= state.last_m3_timestamp:
            return []
        state.last_m3_timestamp = m3_timestamp
        series = _fisher([float(value) for value in m3_highs], [float(value) for value in m3_lows])
        current, previous = series[-1], series[-2]
        rq, gaussian = _kernel([float(value) for value in m5_closes])
        if any(value is None for value in (*current, *previous, rq, gaussian)):
            return []
        fish1, fish2 = current; prev1, prev2 = previous
        cross_up, cross_down = fish1 > fish2 and prev1 <= prev2, fish1 < fish2 and prev1 >= prev2
        green = gaussian >= rq
        price = float((m1.get("closes") or [0])[-1])
        common = {"price": price, "m1_closed_at_ms": m1_timestamp, "m3_closed_at_ms": m3_timestamp,
                  "fisher": fish1, "trigger": fish2, "kernel_rq": rq, "kernel_gaussian": gaussian,
                  "kernel_green": green, "execution": "observation only; no paper order is created"}
        if cross_up and fish1 < -1.0 and green:
            return [{"type": "long_candidate", **common}]
        if cross_down and fish1 > 2.0:
            return [{"type": "exit_candidate", **common}]
        return []


class FisherM3KernelM5ExactPaper:
    """Independent per-symbol paper ledger for the supplied Pine contract.

    It deliberately has no stop, profit lock, trend filter, or shared-wallet
    constraint.  A signal is filled at the next completed M1 bar's open, the
    closest causal counterpart of ``process_orders_on_close=false``.
    """

    def __init__(self, initial_cash: float = 10_000.0, commission: float = 0.001):
        self.initial_cash = initial_cash
        self.commission = commission
        self.states: dict[str, dict[str, Any]] = {}

    def _state(self, symbol: str) -> dict[str, Any]:
        return self.states.setdefault(symbol.upper(), {"cash": self.initial_cash, "position": None, "pending": None})

    def has_open_or_pending(self, symbol: str) -> bool:
        state = self._state(symbol)
        return bool(state["position"] or state["pending"])

    def schedule(self, symbol: str, event: dict[str, Any]) -> None:
        state = self._state(symbol)
        action = "open" if event["type"] == "long_candidate" else "close"
        if action == "open" and (state["position"] or state["pending"]):
            return
        if action == "close" and (not state["position"] or state["pending"]):
            return
        state["pending"] = {"action": action, "signal_m1_closed_at_ms": event["m1_closed_at_ms"], "signal": event}

    def advance(self, symbol: str, m1: dict[str, list[float]]) -> list[dict[str, Any]]:
        times, opens = list(m1.get("timestamps") or []), list(m1.get("opens") or [])
        if not times or not opens:
            return []
        state, pending = self._state(symbol), self._state(symbol).get("pending")
        if not pending or int(times[-1]) <= int(pending["signal_m1_closed_at_ms"]):
            return []
        fill, action = float(opens[-1]), pending["action"]
        state["pending"] = None
        if action == "open":
            order_value = state["cash"] * 0.20
            entry_fee = order_value * self.commission
            if order_value + entry_fee > state["cash"]:
                order_value = state["cash"] / (1 + self.commission)
                entry_fee = order_value * self.commission
            quantity = order_value / fill
            state["cash"] -= order_value + entry_fee
            state["position"] = {"entry": fill, "quantity": quantity, "order_value": order_value, "entry_fee": entry_fee,
                                 "entry_time_ms": int(times[-1])}
            return [{"type": "paper_long_opened", "price": fill, "entry_fee": entry_fee, "order_value_try": order_value,
                     "execution": "next_completed_m1_open", "source_signal": pending["signal"]}]
        position = state["position"]
        proceeds, exit_fee = position["quantity"] * fill, position["quantity"] * fill * self.commission
        pnl = proceeds - exit_fee - position["order_value"] - position["entry_fee"]
        state["cash"] += proceeds - exit_fee
        state["position"] = None
        return [{"type": "paper_long_closed", "price": fill, "exit_fee": exit_fee, "pnl_try": pnl,
                 "cash_try": state["cash"], "execution": "next_completed_m1_open", "source_signal": pending["signal"]}]
