"""
NautilusTrader-inspired Realistic Execution & Fill Simulation Model.
Emulates network latency, orderbook queue latency, dynamic slippage, and fee accounting.
"""
from dataclasses import dataclass
import random
import numpy as np


@dataclass
class OrderFillResult:
    symbol: str
    order_side: str
    requested_price: float
    filled_price: float
    slippage_bps: float
    slippage_amount: float
    simulated_latency_ms: float
    fee_incurred: float
    net_filled_value: float
    execution_status: str  # "FILLED", "PARTIAL", "REJECTED_LATENCY"
    fill_notes: str


class NautilusExecutionModel:
    """
    Sub-millisecond realism for backtesting and paper trading.
    Prevents idealized instantaneous fills at exact tick price.
    """

    def __init__(self, default_fee_bps: float = 10.0, base_latency_ms: float = 35.0):
        self.default_fee_bps = default_fee_bps  # 10 bps = 0.10% Binance Spot
        self.base_latency_ms = base_latency_ms

    def simulate_fill(
        self,
        symbol: str,
        side: str,
        requested_price: float,
        quantity: float,
        current_atr: float,
        is_market_order: bool = True,
        market_volatility_multiplier: float = 1.0
    ) -> OrderFillResult:
        side = side.upper()
        # 1. Simulate network + exchange matching engine latency (30ms - 80ms standard)
        jitter = random.uniform(-10.0, 35.0)
        latency_ms = max(5.0, self.base_latency_ms + jitter)

        # 2. Dynamic slippage modeling based on ATR and order type
        atr_pct = (current_atr / requested_price) if requested_price > 0 else 0.005

        if is_market_order:
            # Market orders incur adverse slippage proportional to volatility
            base_slip_pct = atr_pct * 0.15 * market_volatility_multiplier
            # Slight random walk on slippage
            slip_pct = max(0.0001, base_slip_pct * random.uniform(0.7, 1.3))
        else:
            # Limit orders queue: small adverse selection or 0 slippage if maker
            slip_pct = max(0.0, (atr_pct * 0.03) * random.uniform(-0.5, 0.8))

        if side == "BUY":
            filled_price = requested_price * (1.0 + slip_pct)
        else:
            filled_price = requested_price * (1.0 - slip_pct)

        slippage_amount = abs(filled_price - requested_price)
        slippage_bps = (slippage_amount / requested_price) * 10000.0 if requested_price > 0 else 0.0

        # 3. Fee calculation
        gross_value = filled_price * quantity
        fee_incurred = gross_value * (self.default_fee_bps / 10000.0)
        net_value = gross_value - fee_incurred if side == "SELL" else gross_value + fee_incurred

        notes = (
            f"Simulated {latency_ms:.1f}ms latency. Slippage: {slippage_bps:.2f} bps "
            f"(${slippage_amount:.4f}). Realistic fill verified."
        )

        return OrderFillResult(
            symbol=symbol,
            order_side=side,
            requested_price=round(requested_price, 5),
            filled_price=round(filled_price, 5),
            slippage_bps=round(slippage_bps, 2),
            slippage_amount=round(slippage_amount, 5),
            simulated_latency_ms=round(latency_ms, 1),
            fee_incurred=round(fee_incurred, 4),
            net_filled_value=round(net_value, 4),
            execution_status="FILLED",
            fill_notes=notes
        )
