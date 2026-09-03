"""Strategy-level circuit breaker: pause a strategy whose recent trades show
a negative rolling expectancy.

The 2026-08-25 PUMP Monitor history showed 292 trades at -1680 TRY with no
mechanism to stop the bleeding: per-symbol guards existed but nothing watched
the strategy as a whole. This module evaluates the last N closed trades per
strategy after each close and flips the strategy to PAUSED when the window's
expectancy drops below the floor. Pausing is paper-signal-level only (entries
blocked, open positions still managed) and requires explicit re-enable via
config or the API — never auto-resumes on its own.
"""
import json
import time

from app import database

# Rolling window and floor are read from config so they stay tunable.
WINDOW_DEFAULT = 20
FLOOR_DEFAULT = -0.5  # TRY per trade


class StrategyCircuitBreaker:
    """Tracks paused strategies in llm_settings KV; evaluates after closes."""

    def __init__(self):
        self._paused = {}          # strategy -> {"paused_at": ts, "reason": str}
        self._loaded = False
        self._last_eval = 0.0

    def _key(self):
        return "strategy_circuit_breaker_paused"

    async def _ensure_loaded(self):
        if self._loaded:
            return
        try:
            raw = await database.get_llm_setting(self._key(), "{}")
            stored = json.loads(raw or "{}")
            if isinstance(stored, dict):
                self._paused = stored
        except Exception:
            self._paused = {}
        self._loaded = True

    async def _persist(self):
        await database.set_llm_setting(self._key(), json.dumps(self._paused))

    def is_paused(self, strategy: str) -> bool:
        return strategy in self._paused

    def status(self) -> dict:
        return {name: dict(info) for name, info in self._paused.items()}

    async def resume(self, strategy: str) -> bool:
        """Human-approved resume; nothing auto-unpauses. Persists state to DB."""
        if strategy in self._paused:
            self._paused.pop(strategy, None)
            await self._persist()
            return True
        return False

    async def evaluate_after_close(self, strategy: str):
        """Recompute the rolling expectancy for one strategy; pause if breached.

        Returns a dict describing the decision (or None when healthy).
        """
        from app.config import config

        await self._ensure_loaded()
        now = time.time()
        if now - self._last_eval < 5:
            return None  # debounce rapid successive closes
        self._last_eval = now
        try:
            trades = await database.get_trades(limit=WINDOW_DEFAULT, strategy=strategy)
        except Exception:
            return None
        pnls = [float(t.get("pnl") or 0) for t in trades]
        # Only judge when the full window has data; small samples stay allowed.
        window = max(5, min(int(getattr(config, "STRATEGY_BREAKER_WINDOW", WINDOW_DEFAULT)), 100))
        floor = float(getattr(config, "STRATEGY_BREAKER_EXPECTANCY_FLOOR", FLOOR_DEFAULT))
        if len(pnls) < window:
            return None
        expectancy = sum(pnls[:window]) / window  # newest-first slice
        if expectancy >= floor:
            # Healthy: clear any stale pause record left over from an older run.
            if strategy in self._paused:
                self._paused.pop(strategy, None)
                await self._persist()
            return None
        detail = {
            "paused_at": now,
            "reason": "rolling_expectancy_below_floor",
            "window": window,
            "expectancy": round(expectancy, 4),
            "floor": floor,
            "recent_pnls": [round(p, 2) for p in pnls[:window]],
        }
        if strategy not in self._paused:
            self._paused[strategy] = detail
            await self._persist()
            try:
                await database.save_signal({
                    "symbol": "*", "action": "STRATEGY_PAUSED",
                    "reason": f"{strategy}: expectancy {expectancy:.2f} < {floor} over {window} trades",
                    "strategy": strategy, "timestamp": now})
            except Exception:
                pass
        return detail


breaker = StrategyCircuitBreaker()
