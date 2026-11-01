"""
FinCon inspired Episodic Negative Memory & Trap Shield (Memory-Augmented Financial Agent).
Stores failed trading episodes (stop-outs, false breakouts, bull traps) as normalized feature vectors.
When a new trade setup is evaluated, it computes similarity to known trap patterns and vetoes entries
that replicate past loss conditions.
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class NegativeEpisode(BaseModel):
    episode_id: str
    symbol: str
    failure_type: str  # "BULL_TRAP", "FALSE_BREAKOUT", "VOLATILITY_WHIPSAW", "VOLUME_EXHAUSTION"
    loss_pct: float
    rsi: float
    adx: float
    volume_ratio: float
    trend_spread_pct: float
    market_regime: str
    timestamp: float
    lesson: str


class TrapShieldVerdict(BaseModel):
    symbol: str
    is_trap_detected: bool
    highest_similarity_pct: float
    matching_episode_id: Optional[str] = None
    matching_failure_type: Optional[str] = None
    historical_loss_pct: Optional[float] = None
    protective_veto: bool
    verdict: str


# In-memory episodic store initialized with canonical market trap patterns
_EPISODIC_MEMORY: List[NegativeEpisode] = [
    NegativeEpisode(
        episode_id="trap_001_bull_exhaustion",
        symbol="ALL",
        failure_type="BULL_TRAP",
        loss_pct=-1.85,
        rsi=74.5,
        adx=15.2,
        volume_ratio=0.75,
        trend_spread_pct=0.45,
        market_regime="CHOPPY",
        timestamp=time.time() - 86400 * 3,
        lesson="Düşük hacimde aşırı alım RSI ile tepe kırılımı denemesi sert boğa tuzağıyla sonuçlandı."
    ),
    NegativeEpisode(
        episode_id="trap_002_whipsaw_choppy",
        symbol="ALL",
        failure_type="VOLATILITY_WHIPSAW",
        loss_pct=-1.40,
        rsi=52.0,
        adx=12.0,
        volume_ratio=0.60,
        trend_spread_pct=-0.10,
        market_regime="CHOPPY",
        timestamp=time.time() - 86400 * 5,
        lesson="ADX < 15 iken testere piyasasında EMA kesişimi erken stop ettirdi."
    ),
    NegativeEpisode(
        episode_id="trap_003_volume_divergence",
        symbol="ALL",
        failure_type="VOLUME_EXHAUSTION",
        loss_pct=-2.10,
        rsi=68.0,
        adx=28.0,
        volume_ratio=0.55,
        trend_spread_pct=1.20,
        market_regime="EXHAUSTION",
        timestamp=time.time() - 86400 * 7,
        lesson="Fiyat yükselirken hacim dramatik düştü (%45 eksik); hacim uyumsuzluğu sert çöktü."
    )
]


def _feature_vector(rsi: float, adx: float, vol_ratio: float, spread: float) -> List[float]:
    """Normalizes features into standard scale [-1.0, 1.0]."""
    return [
        (rsi - 50.0) / 50.0,
        (adx - 20.0) / 30.0,
        (vol_ratio - 1.0) / 2.0,
        spread / 2.0
    ]


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 <= 0 or norm2 <= 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm1 * norm2)))


def record_negative_episode(
    symbol: str,
    failure_type: str,
    loss_pct: float,
    indicators: Dict[str, Any],
    market_regime: str = "CHOPPY",
    lesson: str = "Stop loss seviyesine ulaşıldı."
) -> NegativeEpisode:
    """Stores a new negative episode when a trade is stopped out."""
    sym = (symbol or "UNKNOWN").upper().strip()
    ep = NegativeEpisode(
        episode_id=f"trap_{int(time.time())}_{sym}",
        symbol=sym,
        failure_type=failure_type,
        loss_pct=float(loss_pct),
        rsi=float(indicators.get("rsi") or 50.0),
        adx=float(indicators.get("adx") or 20.0),
        volume_ratio=float(indicators.get("volume_ratio") or 1.0),
        trend_spread_pct=float(indicators.get("trend_spread_pct") or 0.0),
        market_regime=market_regime,
        timestamp=time.time(),
        lesson=lesson
    )
    _EPISODIC_MEMORY.append(ep)
    return ep


def evaluate_trap_shield(
    symbol: str,
    indicators: Dict[str, Any],
    similarity_threshold: float = 0.85
) -> TrapShieldVerdict:
    """Cross-examines proposed setup against FinCon episodic negative trap memory."""
    sym = (symbol or "BTCUSDT").upper().strip()
    rsi = float(indicators.get("rsi") or 50.0)
    adx = float(indicators.get("adx") or 20.0)
    vol_ratio = float(indicators.get("volume_ratio") or 1.0)
    spread = float(indicators.get("trend_spread_pct") or 0.0)

    cand_vec = _feature_vector(rsi, adx, vol_ratio, spread)

    max_sim = 0.0
    best_ep: Optional[NegativeEpisode] = None

    for ep in _EPISODIC_MEMORY:
        if ep.symbol != "ALL" and ep.symbol != sym:
            continue
        ep_vec = _feature_vector(ep.rsi, ep.adx, ep.volume_ratio, ep.trend_spread_pct)
        sim = _cosine_similarity(cand_vec, ep_vec)
        if sim > max_sim:
            max_sim = sim
            best_ep = ep

    sim_pct = round(max_sim * 100.0, 1)
    is_trap = sim_pct >= (similarity_threshold * 100.0)

    if is_trap and best_ep:
        verdict = (
            f"🛡️ FİNCON TUZAK KALKANI DEVREDE: Bu indikatör ve hacim yapısı, "
            f"geçmişteki {best_ep.failure_type} ({best_ep.loss_pct:.2f}% zarar) senaryosuyla "
            f"%{sim_pct} oranında benzerlik gösteriyor! Ders: {best_ep.lesson}. İşlem engellendi."
        )
        veto = True
    elif sim_pct >= 70.0 and best_ep:
        verdict = (
            f"⚠️ DİKKAT: Kurulum geçmiş bir {best_ep.failure_type} senaryosuna %{sim_pct} benzerlik taşıyor. "
            f"İşlem açılacaksa dar stop ve düşük bakiye kullanılmalı."
        )
        veto = False
    else:
        verdict = f"Temiz kurulum; geçmiş tuzak epizotlarıyla benzerlik güvenli seviyede (%{sim_pct})."
        veto = False

    return TrapShieldVerdict(
        symbol=sym,
        is_trap_detected=is_trap,
        highest_similarity_pct=sim_pct,
        matching_episode_id=best_ep.episode_id if best_ep else None,
        matching_failure_type=best_ep.failure_type if best_ep else None,
        historical_loss_pct=best_ep.loss_pct if best_ep else None,
        protective_veto=veto,
        verdict=verdict
    )
