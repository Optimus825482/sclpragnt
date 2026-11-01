"""
Freqtrade-inspired Protections, Circuit Breakers & Dynamic ROI Engine.
Enforces StoplossGuard, CooldownPeriods, MaxDrawdownProtection and dynamic ROI tables.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time


@dataclass
class TradeRecord:
    symbol: str
    pnl_pct: float
    timestamp: float
    exit_type: str  # "STOP_LOSS", "TAKE_PROFIT", "TIMEOUT", "MANUAL"


@dataclass
class ProtectionStatus:
    is_trading_allowed: bool
    active_circuit_breaker: Optional[str]
    cooldown_symbols: Dict[str, float]  # symbol -> remaining cooldown seconds
    consecutive_losses: int
    current_drawdown_pct: float
    reason: str


class FreqtradeProtectionsEngine:
    """
    Freqtrade-style capital protection system.
    Safeguards against revenge trading, volatility cascading, and consecutive stopout spirals.
    """

    def __init__(
        self,
        max_consecutive_stops: int = 3,
        stoploss_guard_cooldown_sec: float = 3600.0,  # 1 hour pause
        symbol_cooldown_sec: float = 900.0,            # 15 minutes rest per symbol
        max_drawdown_limit_pct: float = 5.0            # 5% max daily drawdown limit
    ):
        self.max_consecutive_stops = max_consecutive_stops
        self.stoploss_guard_cooldown_sec = stoploss_guard_cooldown_sec
        self.symbol_cooldown_sec = symbol_cooldown_sec
        self.max_drawdown_limit_pct = max_drawdown_limit_pct

        self._trade_history: List[TradeRecord] = []
        self._symbol_cooldowns: Dict[str, float] = {}  # symbol -> expiry timestamp
        self._global_guard_expiry: float = 0.0

        # Dynamic ROI Table (minutes -> target profit pct)
        # e.g., 0 min: 2.5%, 15 min: 1.5%, 45 min: 0.8%, 90 min: 0.4%
        self.roi_table = [
            (90, 0.004),
            (45, 0.008),
            (15, 0.015),
            (0, 0.025),
        ]

    def register_trade_exit(self, symbol: str, pnl_pct: float, exit_type: str):
        now = time.time()
        record = TradeRecord(symbol=symbol, pnl_pct=pnl_pct, timestamp=now, exit_type=exit_type)
        self._trade_history.append(record)

        # Enforce symbol cooldown
        self._symbol_cooldowns[symbol] = now + self.symbol_cooldown_sec

        # Check consecutive stoploss guard
        recent_exits = [t for t in self._trade_history[-self.max_consecutive_stops:]]
        if len(recent_exits) >= self.max_consecutive_stops:
            all_stops = all(t.exit_type == "STOP_LOSS" or t.pnl_pct < 0 for t in recent_exits)
            if all_stops:
                self._global_guard_expiry = now + self.stoploss_guard_cooldown_sec

    def evaluate_protection(self, symbol: Optional[str] = None, current_drawdown_pct: float = 0.0) -> ProtectionStatus:
        now = time.time()

        # 1. Global Drawdown Breach
        if current_drawdown_pct >= self.max_drawdown_limit_pct:
            return ProtectionStatus(
                is_trading_allowed=False,
                active_circuit_breaker="MAX_DRAWDOWN_LIMIT",
                cooldown_symbols={},
                consecutive_losses=self._count_consecutive_losses(),
                current_drawdown_pct=current_drawdown_pct,
                reason=f"Daily drawdown limit of {self.max_drawdown_limit_pct}% breached (Current: {current_drawdown_pct}%)."
            )

        # 2. Stoploss Guard (Global freeze)
        if now < self._global_guard_expiry:
            remaining = int(self._global_guard_expiry - now)
            return ProtectionStatus(
                is_trading_allowed=False,
                active_circuit_breaker="STOPLOSS_GUARD",
                cooldown_symbols={},
                consecutive_losses=self._count_consecutive_losses(),
                current_drawdown_pct=current_drawdown_pct,
                reason=f"StoplossGuard triggered after {self.max_consecutive_stops} consecutive stopouts. Cooling down for {remaining}s."
            )

        # 3. Symbol specific cooldown
        active_cooldowns: Dict[str, float] = {}
        for sym, exp in list(self._symbol_cooldowns.items()):
            if now < exp:
                active_cooldowns[sym] = round(exp - now, 1)
            else:
                self._symbol_cooldowns.pop(sym, None)

        if symbol and symbol in active_cooldowns:
            return ProtectionStatus(
                is_trading_allowed=False,
                active_circuit_breaker="SYMBOL_COOLDOWN",
                cooldown_symbols=active_cooldowns,
                consecutive_losses=self._count_consecutive_losses(),
                current_drawdown_pct=current_drawdown_pct,
                reason=f"Symbol {symbol} in cooldown for another {active_cooldowns[symbol]}s."
            )

        return ProtectionStatus(
            is_trading_allowed=True,
            active_circuit_breaker=None,
            cooldown_symbols=active_cooldowns,
            consecutive_losses=self._count_consecutive_losses(),
            current_drawdown_pct=current_drawdown_pct,
            reason="All protection parameters normal. Trading allowed."
        )

    def check_dynamic_roi(self, trade_duration_minutes: float, current_profit_pct: float) -> bool:
        """
        Evaluates whether dynamic ROI exit criteria is fulfilled based on holding duration.
        """
        for min_duration, required_profit in self.roi_table:
            if trade_duration_minutes >= min_duration:
                if current_profit_pct >= required_profit:
                    return True
        return False

    def _count_consecutive_losses(self) -> int:
        count = 0
        for t in reversed(self._trade_history):
            if t.pnl_pct < 0 or t.exit_type == "STOP_LOSS":
                count += 1
            else:
                break
        return count
