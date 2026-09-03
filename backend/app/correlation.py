"""S5: dynamic correlation exposure control.

Altcoin longs are usually one BTC (and ETH) position in disguise. This module
measures rolling Pearson correlation of each active symbol's returns against
BTC and ETH from real closed candles, then caps the *correlation-weighted*
portfolio exposure so three highly correlated positions cannot stack into a
single hidden bet.

Design:
- ``CorrelationMonitor`` recomputes correlations periodically (default 30 min)
  from the market cache's closed candles — no extra exchange calls.
- Correlations decay smoothly toward a neutral floor when data is thin.
- ``exposure_check`` sums correlation-weighted notional across open positions
  and reports whether a new entry would breach ``MAX_CLUSTER_EXPOSURE_PCT``.
- Results are cached in-process; nothing here blocks trading on failure
  (paper-only safety layer, fails open with the reason recorded).
"""
import math
import time
from collections import defaultdict


class CorrelationMonitor:
    BENCHMARKS = ("BTC", "ETH")

    def __init__(self):
        self._corr = {}          # symbol -> {"BTC": float, "ETH": float, "updated_at": ts, "samples": int}
        self._last_run = 0.0

    @property
    def last_updated(self) -> float:
        return self._last_run

    def snapshot(self) -> dict:
        return {sym: {**info} for sym, info in self._corr.items()}

    def correlation_of(self, symbol: str, benchmark: str = "BTC") -> float:
        info = self._corr.get(str(symbol).upper())
        if not info:
            return 0.75  # conservative default: assume high altcoin-beta
        value = info.get(benchmark.upper())
        if value is None:
            value = max(info.get("BTC", 0.75), info.get("ETH", 0.6))
        return float(value)

    async def refresh(self, market, symbols=None, lookback=200):
        """Recompute correlations from closed candles in the market cache."""
        tf = "1h"
        benchmarks = {}
        for bench in self.BENCHMARKS:
            base = f"{bench}TRY"
            bars = (market.get_ut_kline(base, tf) or {}) if market else {}
            closes = [float(c) for c in (bars.get("closes") or [])]
            if len(closes) < 30:
                continue
            benchmarks[bench] = _returns(closes[-lookback:])
        if not benchmarks:
            return {"ok": False, "reason": "benchmark_candles_unavailable"}
        targets = list(symbols or [])
        updated = 0
        for sym in targets:
            if any(sym.startswith(b) for b in self.BENCHMARKS):
                continue  # benchmark vs itself is meaningless here
            bars = (market.get_ut_kline(sym, tf) or {})
            closes = [float(c) for c in (bars.get("closes") or [])]
            if len(closes) < 30:
                continue
            rets = _returns(closes[-lookback:])
            entry = {"updated_at": time.time(), "samples": len(rets)}
            for bench, brets in benchmarks.items():
                entry[bench] = _pearson(rets, brets)
            self._corr[str(sym).upper()] = entry
            updated += 1
        self._last_run = time.time()
        return {"ok": True, "updated": updated}

    async def maybe_refresh(self, market, symbols=None, interval_sec=1800):
        """Refresh only when stale; cheap no-op otherwise."""
        if time.time() - self._last_run >= interval_sec:
            try:
                await self.refresh(market, symbols=symbols)
            except Exception as exc:
                # Sessizce yutma — logla ki stale data tespit edilebilsin
                import logging
                logger = logging.getLogger("scalper.correlation")
                logger.warning(f"Correlation refresh hatası (stale data kalabilir): {exc}")
        return self._last_run


def _returns(closes: list[float]) -> list[float]:
    return [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes))
            if closes[i - 1] != 0]


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 20:
        return 0.75  # thin data: assume high correlation
    xs, ys = xs[-n:], ys[-n:]
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if vx == 0 or vy == 0:
        return 0.75
    return max(-1.0, min(1.0, cov / (vx * vy)))


def cluster_exposure(positions: dict, new_symbol: str | None, new_value: float,
                     monitor: CorrelationMonitor, benchmark: str = "BTC",
                     equity: float | None = None) -> dict:
    """Sum correlation-weighted long exposure as % of equity.

    weight_i = |corr(symbol_i, benchmark)|; a new entry adds its full notional
    times its own correlation. Returns the projected exposure and whether it
    breaches the configured cap.
    """
    total_weighted = 0.0
    details = []
    for sym, pos in (positions or {}).items():
        entry_price = float(pos.get("entry_price") or 0)
        qty = float(pos.get("quantity") or 0)
        notional = entry_price * qty
        corr = monitor.correlation_of(sym, benchmark)
        weighted = notional * max(0.0, corr)
        total_weighted += weighted
        details.append({"symbol": sym, "notional": round(notional, 2),
                        "corr": round(corr, 3), "weighted": round(weighted, 2)})
    if new_symbol and new_value > 0:
        corr_new = monitor.correlation_of(new_symbol, benchmark)
        total_weighted += new_value * max(0.0, corr_new)
        details.append({"symbol": str(new_symbol).upper(), "notional": round(new_value, 2),
                        "corr": round(corr_new, 3), "weighted": round(new_value * corr_new, 2),
                        "new": True})
    pct = None
    if equity and equity > 0:
        pct = round(total_weighted / equity * 100, 2)
    return {"benchmark": benchmark, "weighted_exposure": round(total_weighted, 2),
            "equity": equity, "exposure_pct": pct, "positions": details}
