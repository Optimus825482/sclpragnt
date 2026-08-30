"""Bucketed win-rate calibration: turn closed-trade history into entry
confidence multipliers.

The 2026-08-25 audit found the expected-net model predicted +10.34 TRY per
trade while reality averaged -5.75 TRY — the model had no feedback loop. This
module closes that loop deterministically:

1. ``build_buckets`` groups closed trades by coarse, robust context buckets
   (strategy × hour-band × volume-ratio band) and computes win rate / sample
   count per bucket.
2. ``confidence_multiplier`` maps a new entry's context to [0.5 .. 1.0]:
   buckets with proven bad expectancy scale size down; unknown contexts stay
   neutral at 1.0 (no fabricated statistics).
3. A weekly refresh job re-reads trades from the database. Buckets need
   >= min samples before they are allowed to influence sizing.

No machine learning, no parameter fitting — plain counting with
walk-forward-safe semantics (only *past* trades feed today's multiplier).
"""
import time
from collections import defaultdict

MIN_BUCKET_SAMPLES = 8
GOOD_WIN_RATE = 0.55     # >= this wins -> full size (multiplier 1.0)
BAD_WIN_RATE = 0.35      # <= this wins -> minimum multiplier
MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 1.0

# Shared bucket state. Refreshed weekly by the main.py calibration loop and
# read by the analyzer at entry time; kept here so both sides share one
# source of truth without a circular import.
_bucket_state = {"buckets": {}, "updated_at": 0.0}


def store_buckets(buckets: dict) -> None:
    """Publish a freshly built bucket table (weekly refresh path)."""
    _bucket_state["buckets"] = buckets or {}
    _bucket_state["updated_at"] = time.time()


def bucket_state() -> dict:
    """Read-only view for UI/report surfaces."""
    return dict(_bucket_state)


def multiplier_for(strategy: str, *, volume_ratio: float | None = None) -> float:
    """Current confidence multiplier for one entry; neutral before first build."""
    from datetime import datetime, timezone
    hour = datetime.now(timezone.utc).hour
    return confidence_multiplier(
        _bucket_state.get("buckets") or {},
        strategy=strategy, hour=hour, volume_ratio=volume_ratio)


def hour_band(hour: int | None) -> str:
    if hour is None:
        return "unknown"
    if 5 <= hour < 9:
        return "early_eu"
    if 9 <= hour < 14:
        return "eu_day"
    if 14 <= hour < 18:
        return "us_overlap"
    if 18 <= hour < 23:
        return "evening"
    return "late_night"


def volume_band(volume_ratio: float | None) -> str:
    if volume_ratio is None:
        return "unknown"
    if volume_ratio < 0.5:
        return "very_low"
    if volume_ratio < 1.0:
        return "low"
    if volume_ratio <= 2.0:
        return "normal"      # healthy pump band per the trade audit
    return "chasing"         # VR > 2.0: the worst historical cluster


def bucket_key(*, strategy: str | None, hour: int | None,
               volume_ratio: float | None) -> tuple:
    return (str(strategy or "unknown"), hour_band(hour), volume_band(volume_ratio))


def build_buckets(trades: list[dict]) -> dict[tuple, dict]:
    """Group closed trades into buckets with win-rate statistics."""
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for trade in trades or []:
        pnl = float(trade.get("pnl") or 0)
        try:
            hour = None
            ts = float(trade.get("entry_time") or 0)
            if ts > 0:
                from datetime import datetime, timezone
                hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        except (TypeError, ValueError):
            hour = None
        ctx = trade.get("entry_context") or {}
        vr = ((ctx.get("liquidity") or {}).get("volume_ratio")
              if isinstance(ctx, dict) else None)
        key = bucket_key(strategy=trade.get("strategy"), hour=hour, volume_ratio=vr)
        grouped[key].append(pnl)
    buckets = {}
    for key, pnls in grouped.items():
        wins = sum(1 for p in pnls if p > 0)
        buckets[key] = {
            "samples": len(pnls),
            "win_rate": wins / len(pnls),
            "net_pnl": round(sum(pnls), 2),
            "expectancy": round(sum(pnls) / len(pnls), 4),
        }
    return buckets


def confidence_multiplier(buckets: dict[tuple, dict], *, strategy: str | None,
                          hour: int | None, volume_ratio: float | None) -> float:
    """Map a new entry's bucket to a size multiplier in [0.5 .. 1.0].

    Unknown or thin-sample buckets are neutral (1.0): absence of evidence is
    not evidence of quality, but it must not block trading either.
    """
    key = bucket_key(strategy=strategy, hour=hour, volume_ratio=volume_ratio)
    stats = buckets.get(key)
    if not stats or stats["samples"] < MIN_BUCKET_SAMPLES:
        return MAX_MULTIPLIER
    wr = stats["win_rate"]
    if wr >= GOOD_WIN_RATE:
        return MAX_MULTIPLIER
    if wr <= BAD_WIN_RATE:
        return MIN_MULTIPLIER
    # Linear between the two anchors.
    span = GOOD_WIN_RATE - BAD_WIN_RATE
    ratio = (wr - BAD_WIN_RATE) / span
    return round(MIN_MULTIPLIER + ratio * (MAX_MULTIPLIER - MIN_MULTIPLIER), 3)


def summarize_for_ui(buckets: dict[tuple, dict], limit: int = 12) -> list[dict]:
    """Most decision-relevant buckets for the reports page."""
    rows = []
    for key, stats in buckets.items():
        if stats["samples"] < MIN_BUCKET_SAMPLES:
            continue
        rows.append({
            "strategy": key[0], "hour_band": key[1], "volume_band": key[2],
            **stats,
        })
    rows.sort(key=lambda r: r["expectancy"])
    return rows[:limit]


# ---------------------------------------------------------------------------
# S4: regime-gated sizing.
# Deterministic regimes already exist in technical_analysis; this maps them to
# size multipliers per strategy *style*. Mean-reversion entries fight the move
# in trending regimes, so they shrink there; continuation strategies (PUMP)
# are the opposite and shrink in dead ranges.

TRENDING_REGIMES = {"bull_quiet", "bull_volatile", "bear_quiet", "bear_volatile"}
RANGE_REGIMES = {"range_transition", "accumulation", "distribution"}


def regime_size_multiplier(strategy_style: str, regime: str | None,
                           regime_confidence: float | None = None) -> float:
    """Size multiplier from market regime vs strategy style.

    mean_reversion: full size in range regimes, half size in strong trends
      (the entry fights an ADX-confirmed directional move).
    trend_following / continuation: full size in trends or unknown; shrinks
      only inside a confirmed dead range when confidence is meaningful.
    Unknown regime or low confidence stays neutral at 1.0.
    """
    if not regime:
        return 1.0
    confidence_ok = (regime_confidence is None) or (regime_confidence >= 0.55)
    if strategy_style == "mean_reversion":
        if regime in TRENDING_REGIMES and confidence_ok:
            return 0.5
        return 1.0
    if strategy_style in {"trend_following", "continuation"}:
        if regime in RANGE_REGIMES and confidence_ok:
            return 0.7
        return 1.0
    return 1.0


def strategy_style_of(strategy_name: str | None) -> str:
    name = str(strategy_name or "").upper()
    if "MEAN_REVERSION" in name:
        return "mean_reversion"
    if "PUMP" in name or "BREAKOUT" in name or "MOMENTUM" in name:
        return "continuation"
    return "unknown"
