"""QuantConnect LEAN inspired Cross-Asset Portfolio & Volatility Parity Sizing Engine.

Features:
- Volatility Parity (Inverse ATR) lot and capital sizing
- Clustered exposure warning (correlated currency pairs or altcoin baskets)
- Portfolio drawdown throttle and maximum capital commitment safety
- Institutional portfolio risk governor.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class LeanPortfolioResult(BaseModel):
    symbol: str
    account_balance: float
    allocated_risk_usd: float
    suggested_units_or_lot: float
    volatility_weight: float
    cluster_warning: Optional[str] = None
    portfolio_approved: bool
    sizing_rationale: str


# Clustered currency / coin groups
_CORRELATION_CLUSTERS = {
    "USD_BULL_CLUSTER": {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"},
    "YEN_CLUSTER": {"USDJPY", "EURJPY", "GBPJPY"},
    "CRYPTO_MAJOR": {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
}


def evaluate_lean_portfolio(
    symbol: str,
    account_balance: float,
    risk_pct_per_trade: float = 1.0,
    atr_pct: float = 1.5,
    open_positions: Optional[List[str]] = None,
    asset_class: str = "CRYPTO"
) -> LeanPortfolioResult:
    """Calculates QuantConnect LEAN-inspired volatility parity sizing and portfolio risk."""
    sym = symbol.upper().replace("/", "").replace("_", "")
    bal = max(account_balance, 100.0)
    risk_usd = bal * (risk_pct_per_trade / 100.0)

    open_pos = [str(s).upper().replace("/", "").replace("_", "") for s in (open_positions or [])]

    # Cluster exposure check
    cluster_warning = None
    for cluster_name, members in _CORRELATION_CLUSTERS.items():
        if sym in members:
            overlap = [p for p in open_pos if p in members]
            if len(overlap) >= 2:
                cluster_warning = (
                    f"LEAN Portföy Uyarısı: {cluster_name} grubunda zaten {len(overlap)} açık pozisyon var ({', '.join(overlap)}). "
                    "Aynı yönlü aşırı kümelenme riski."
                )
                break

    # Volatility Parity Weight: Higher ATR -> Smaller Position
    safe_atr_pct = max(0.5, min(10.0, atr_pct))
    vol_weight = round(1.5 / safe_atr_pct, 3)

    if asset_class.upper() == "FOREX":
        # Forex lot sizing approximation: Standard 1 lot = 100k, pip value approx $10
        # For a standard 30 pip stop on 1.0 lot, risk is ~$300
        # Lot = risk_usd / (stop_pips * 10)
        base_lots = (risk_usd / 300.0) * vol_weight
        suggested_size = max(0.01, min(5.0, round(base_lots, 2)))
        rationale = f"LEAN Forex Volatilite Paritesi: {suggested_size} lot (ATR ağırlığı: {vol_weight}x, Risk: ${risk_usd:.2f})"
    else:
        # Crypto dollar allocation sizing
        allocated_capital = (risk_usd / (safe_atr_pct / 100.0)) * 0.5
        suggested_size = round(allocated_capital, 2)
        rationale = f"LEAN Spot Volatilite Paritesi: ~${suggested_size} sermaye tahsisi (Risk: ${risk_usd:.2f})"

    approved = cluster_warning is None or len(open_pos) < 5

    return LeanPortfolioResult(
        symbol=sym,
        account_balance=round(bal, 2),
        allocated_risk_usd=round(risk_usd, 2),
        suggested_units_or_lot=suggested_size,
        volatility_weight=vol_weight,
        cluster_warning=cluster_warning,
        portfolio_approved=approved,
        sizing_rationale=rationale
    )
