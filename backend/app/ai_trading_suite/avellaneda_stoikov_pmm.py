"""
Avellaneda-Stoikov Pure Market Making (PMM) Engine.
Inspired by hummingbot/hummingbot PMM strategy and high-frequency quantitative market making.
Calculates reservation price, inventory risk discount, and optimal two-sided bid/ask spreads.
Generates continuous passive spread-capture paper orders without directional bias.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PMMQuoteResult(BaseModel):
    symbol: str
    mid_price: float
    reservation_price: float = Field(..., description="Inventory-adjusted reservation price r(s, q)")
    inventory_position_q: float
    risk_aversion_gamma: float
    volatility_sigma: float
    optimal_bid_quote: float
    optimal_ask_quote: float
    optimal_half_spread_pct: float
    expected_spread_capture_try: float
    market_making_state: str  # "ACTIVE_DUAL_QUOTING", "SKEWED_REDUCE_LONG", "SKEWED_REDUCE_SHORT", "WIDE_VOLATILITY_DEFENSE"
    daily_turnover_multiplier: float
    tactical_rationale: str


def evaluate_avellaneda_stoikov(
    symbol: str,
    mid_price: float = 0.0,
    current_inventory_qty: float = 0.0,
    volatility_annual: float = 0.45,
    gamma: float = 0.1,
    kappa: float = 1.5,
    order_size_try: float = 1000.0
) -> PMMQuoteResult:
    """Calculates Avellaneda-Stoikov reservation price and optimal two-sided quotes."""
    sym = (symbol or "BTCUSDT").upper().strip()
    s = max(mid_price, 0.0001)
    if s == 0.0001:
        s = 68000.0 if "BTC" in sym else (2750.0 if "XAU" in sym else (1.0850 if "EUR" in sym else 100.0))

    q = float(current_inventory_qty)
    g = max(0.01, float(gamma))
    sigma = max(0.05, float(volatility_annual))
    k = max(0.1, float(kappa))

    # Time horizon normalized to intraday slice (T - t = 0.05)
    tau = 0.05

    # 1. Reservation Price: r(s, q) = s - q * gamma * sigma^2 * tau
    inventory_penalty = q * g * (sigma ** 2) * tau * s
    r = round(s - inventory_penalty, 4)

    # 2. Optimal half spread: s_spread = (gamma * sigma^2 * tau) + (2 / gamma) * ln(1 + gamma / kappa)
    spread_component = (g * (sigma ** 2) * tau) + ((2.0 / g) * math.log(1.0 + (g / k)))
    # Scale to reasonable percentage between 0.12% and 1.5%
    half_spread_pct = max(0.0012, min(0.015, spread_component * 0.005))

    delta = s * half_spread_pct
    bid_quote = round(r - delta, 4)
    ask_quote = round(r + delta, 4)

    # Spread capture expected per completed round-turn
    expected_capture = round(order_size_try * (half_spread_pct * 2.0), 2)

    # State determination based on inventory skew q
    if q > 2.0:
        state = "SKEWED_REDUCE_LONG"
        rationale = f"Envanter uzun yönlü birikti (q={q}). Rezervasyon fiyatı ({r}) aşağı çekildi; satış emri daha agresif kademeye konuluyor."
    elif q < -2.0:
        state = "SKEWED_REDUCE_SHORT"
        rationale = f"Envanter kısa yönlü birikti (q={q}). Rezervasyon fiyatı ({r}) yukarı çekildi; alış emri daha agresif kademeye konuluyor."
    elif sigma > 0.8:
        state = "WIDE_VOLATILITY_DEFENSE"
        rationale = "Yüksek volatilite rejimi; kâr marjını korumak için spreadler otomatik genişletildi."
    else:
        state = "ACTIVE_DUAL_QUOTING"
        rationale = f"Mükemmel envanter dengesi. Bid ({bid_quote}) ve Ask ({ask_quote}) üzerinden iki yönlü spread biçme (market making) devrede."

    turnover_mult = round(2.5 + (1.0 / max(half_spread_pct, 0.001)), 1)

    return PMMQuoteResult(
        symbol=sym,
        mid_price=s,
        reservation_price=r,
        inventory_position_q=q,
        risk_aversion_gamma=g,
        volatility_sigma=sigma,
        optimal_bid_quote=bid_quote,
        optimal_ask_quote=ask_quote,
        optimal_half_spread_pct=round(half_spread_pct * 100, 3),
        expected_spread_capture_try=expected_capture,
        market_making_state=state,
        daily_turnover_multiplier=turnover_mult,
        tactical_rationale=rationale
    )
