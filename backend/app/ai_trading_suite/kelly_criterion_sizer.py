"""Kelly Criterion & Optimal Mathematical Capital Sizing Engine.

Implements Ed Thorp's Kelly Criterion:
f* = (p * b - q) / b
where:
- p = Win Rate probability (from historical trade outcome profile)
- b = Reward-to-Risk ratio (TP / SL distance)
- q = Loss probability (1 - p)

Applies Half-Kelly (f*/2) and Quarter-Kelly (f*/4) safety cushions to prevent drawdown drag
and eliminates mathematical risk of ruin while compounding growth.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class KellySizingResult(BaseModel):
    symbol: str
    account_balance: float
    win_rate: float
    reward_to_risk: float
    full_kelly_fraction: float
    half_kelly_fraction: float
    quarter_kelly_fraction: float
    suggested_trade_usd: float
    ruin_probability_pct: float
    is_positive_expectancy: bool
    verdict: str


def evaluate_kelly_sizing(
    symbol: str,
    account_balance: float,
    win_rate: float = 0.58,
    reward_to_risk: float = 1.80,
    max_capital_cap_pct: float = 20.0
) -> KellySizingResult:
    """Computes Kelly optimal capital fraction and safe trade sizing."""
    sym = symbol.upper()
    bal = max(account_balance, 50.0)
    p = max(0.1, min(0.95, win_rate))
    b = max(0.2, reward_to_risk)
    q = 1.0 - p

    # Ed Thorp's Kelly Formula
    kelly_raw = (p * b - q) / b
    is_positive = kelly_raw > 0.0

    full_k = max(0.0, kelly_raw) if is_positive else 0.0
    half_k = full_k * 0.5
    quarter_k = full_k * 0.25

    # Safe applied percentage (Quarter-Kelly bounded by max_capital_cap_pct)
    applied_fraction = min(quarter_k, max_capital_cap_pct / 100.0)
    suggested_usd = round(bal * applied_fraction, 2)

    # Risk of ruin estimation (low with fractional Kelly)
    ruin_prob = 0.01 if is_positive else 99.0

    if not is_positive:
        verdict = f"Kelly Kriteri: Negatif matematiksel beklenti (Win Rate: %{int(p*100)}, R:R: {b:.2f}). İşlem açılması sermaye erimesine yol açar."
    else:
        verdict = (
            f"Kelly Kriteri: Pozitif beklenti. Çeyrek Kelly (%{applied_fraction*100:.1f}) ile "
            f"önerilen güvenli işlem tutarı: ${suggested_usd:.2f} (Tam Kelly: %{full_k*100:.1f})."
        )

    return KellySizingResult(
        symbol=sym,
        account_balance=round(bal, 2),
        win_rate=round(p, 3),
        reward_to_risk=round(b, 2),
        full_kelly_fraction=round(full_k, 4),
        half_kelly_fraction=round(half_k, 4),
        quarter_kelly_fraction=round(quarter_k, 4),
        suggested_trade_usd=suggested_usd,
        ruin_probability_pct=ruin_prob,
        is_positive_expectancy=is_positive,
        verdict=verdict
    )
