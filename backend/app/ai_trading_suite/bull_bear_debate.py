"""
Bull vs. Bear Debate Protocol (inspired by virattt/ai-hedge-fund and TauricResearch/TradingAgents).
Deploys specialized Bull Researcher and Bear Inquisitor agents that cross-examine a trading setup.
Produces a synthesized arbitration verdict, risk discount, and actionable consensus.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ArgumentPoint(BaseModel):
    category: str  # "TECHNICAL", "MOMENTUM", "ORDERFLOW", "RISK"
    claim: str
    weight: float  # 0.0 to 1.0


class BullThesis(BaseModel):
    stance: str = "BULLISH"
    conviction_pct: int
    arguments: List[ArgumentPoint]
    target_price: float
    catalyst_summary: str


class BearThesis(BaseModel):
    stance: str = "BEARISH"
    conviction_pct: int
    arguments: List[ArgumentPoint]
    risk_price: float
    trap_warning: str


class DebateExchange(BaseModel):
    bull_rebuttal: str
    bear_rebuttal: str
    cross_examination_score: float  # -1.0 (Bear dominant) to +1.0 (Bull dominant)


class DebateVerdict(BaseModel):
    symbol: str
    winner: str  # "BULL", "BEAR", or "DEADLOCK"
    net_confidence_pct: int
    bull_thesis: BullThesis
    bear_thesis: BearThesis
    debate: DebateExchange
    arbitrator_verdict: str
    action_bias: str  # "AGGRESSIVE_BUY", "CAUTIOUS_BUY", "HOLD_STANDBY", "AVOID_TRAP"
    recommended_position_discount: float  # 0.0 to 1.0 (multiplier for sizing)


def evaluate_bull_bear_debate(
    symbol: str,
    price: float,
    indicators: Optional[Dict[str, Any]] = None,
    klines: Optional[List[Dict[str, Any]]] = None
) -> DebateVerdict:
    """Runs a multi-agent debate between a Bull Researcher and Bear Inquisitor."""
    sym = (symbol or "BTCUSDT").upper().strip()
    px = max(price, 0.00001)
    ind = indicators or {}

    rsi = float(ind.get("rsi") or 52.0)
    adx = float(ind.get("adx") or 22.0)
    vol_ratio = float(ind.get("volume_ratio") or 1.1)
    ema_fast = float(ind.get("ema_fast") or (px * 1.005))
    ema_slow = float(ind.get("ema_slow") or (px * 0.995))
    atr = float(ind.get("atr") or (px * 0.015))

    trend_up = ema_fast > ema_slow
    trend_dist_pct = ((ema_fast - ema_slow) / px) * 100.0

    # 1. Bullish Arguments
    bull_args: List[ArgumentPoint] = []
    bull_score = 0.0

    if trend_up:
        weight = min(0.35, 0.2 + (abs(trend_dist_pct) * 0.1))
        bull_args.append(ArgumentPoint(
            category="TECHNICAL",
            claim=f"Hızlı EMA ({ema_fast:.2f}) yavaş EMA'nın üzerinde; trend pozitif ({trend_dist_pct:+.2f}% spread).",
            weight=round(weight, 2)
        ))
        bull_score += weight

    if rsi < 38:
        bull_args.append(ArgumentPoint(
            category="MOMENTUM",
            claim=f"RSI {rsi:.1f} ile aşırı satım bölgesinde; ortalamaya dönüş alımı için elverişli.",
            weight=0.30
        ))
        bull_score += 0.30
    elif 48 <= rsi <= 65 and trend_up:
        bull_args.append(ArgumentPoint(
            category="MOMENTUM",
            claim=f"RSI {rsi:.1f} sağlıklı boğa genişleme aralığında, henüz aşırı alım şişkinliği yok.",
            weight=0.25
        ))
        bull_score += 0.25

    if vol_ratio >= 1.25:
        bull_args.append(ArgumentPoint(
            category="ORDERFLOW",
            claim=f"Hacim patlaması {vol_ratio:.2f}x ile alıcı talebini teyit ediyor.",
            weight=0.30
        ))
        bull_score += 0.30

    if adx >= 25:
        bull_args.append(ArgumentPoint(
            category="MOMENTUM",
            claim=f"ADX {adx:.1f} güçlü trend gücüne işaret ediyor.",
            weight=0.20
        ))
        bull_score += 0.20

    bull_conviction = int(min(98, max(15, bull_score * 100)))

    # 2. Bearish Arguments
    bear_args: List[ArgumentPoint] = []
    bear_score = 0.0

    if rsi > 70:
        bear_args.append(ArgumentPoint(
            category="MOMENTUM",
            claim=f"RSI {rsi:.1f} ile aşırı alım bölgesinde; tepe tükenişi ve kâr satışı riski çok yüksek.",
            weight=0.35
        ))
        bear_score += 0.35

    if not trend_up:
        bear_args.append(ArgumentPoint(
            category="TECHNICAL",
            claim=f"Kısa vadeli EMA yapısı ayı eğilimli; ana trend aşağı basıyor.",
            weight=0.35
        ))
        bear_score += 0.35

    if vol_ratio < 0.85:
        bear_args.append(ArgumentPoint(
            category="ORDERFLOW",
            claim=f"Hacim ortalamanın altında ({vol_ratio:.2f}x); likidite yetersizliği ve sahte yükseliş (boğa tuzağı) riski var.",
            weight=0.30
        ))
        bear_score += 0.30

    if adx < 18:
        bear_args.append(ArgumentPoint(
            category="RISK",
            claim=f"ADX {adx:.1f} zayıf; piyasa testere/range modunda, erken stop olasılığı yüksek.",
            weight=0.25
        ))
        bear_score += 0.25

    bear_conviction = int(min(98, max(15, bear_score * 100)))

    # Cross-examination exchange
    diff = bull_conviction - bear_conviction
    cross_score = round(diff / 100.0, 2)

    if diff >= 25:
        winner = "BULL"
        action = "AGGRESSIVE_BUY" if diff >= 45 else "CAUTIOUS_BUY"
        discount = 1.0 if diff >= 45 else 0.75
        verdict = f"Boğa Analisti ({bull_conviction}%) Ayı Müfettişini ({bear_conviction}%) açık farkla eledi. Trend ve hacim desteği güçlü."
        bull_rebuttal = "Ayı itirazları zayıf; hacimli kırılım seviyesi tüm dirençleri egale etti."
        bear_rebuttal = "Satış baskısı şimdilik zayıf görünüyor fakat direnç testinde kâr realizasyonuna dikkat edilmeli."
    elif diff <= -25:
        winner = "BEAR"
        action = "AVOID_TRAP"
        discount = 0.0
        verdict = f"Ayı Müfettişi ({bear_conviction}%) Boğa tezini çürüttü. Boğa tuzağı veya hacim yetersizliği riski baskın."
        bull_rebuttal = "Kısa vadeli toparlanma çabası mevcut fakat satış hacmini karşılamakta zorlanıyoruz."
        bear_rebuttal = "Yukarı yönlü iğneler sahte likidite avından ibaret, alım güvenli değil."
    else:
        winner = "DEADLOCK"
        action = "HOLD_STANDBY"
        discount = 0.50
        verdict = f"Boğa (%{bull_conviction}) ve Ayı (%{bear_conviction}) kilitlendi. Piyasa kararsız; teyit mumu beklenmeli."
        bull_rebuttal = "Alıcılar taban oluşturmaya çalışıyor."
        bear_rebuttal = "Tepedeki direnç henüz kırılabilmiş değil."

    return DebateVerdict(
        symbol=sym,
        winner=winner,
        net_confidence_pct=abs(diff),
        bull_thesis=BullThesis(
            conviction_pct=bull_conviction,
            arguments=bull_args or [ArgumentPoint(category="TECHNICAL", claim="Temel teknik göstergeler dengeli.", weight=0.2)],
            target_price=round(px * (1.0 + (atr / px) * 1.5), 4),
            catalyst_summary="Momentum ve trend akışı yukarı yönlü genişlemeyi destekliyor."
        ),
        bear_thesis=BearThesis(
            conviction_pct=bear_conviction,
            arguments=bear_args or [ArgumentPoint(category="RISK", claim="Olağandışı bir risk anomalisi tespit edilmedi.", weight=0.2)],
            risk_price=round(px * (1.0 - (atr / px) * 1.0), 4),
            trap_warning="Volatilite sıkışması veya sahte kırılım ihtimali göz ardı edilmemeli."
        ),
        debate=DebateExchange(
            bull_rebuttal=bull_rebuttal,
            bear_rebuttal=bear_rebuttal,
            cross_examination_score=cross_score
        ),
        arbitrator_verdict=verdict,
        action_bias=action,
        recommended_position_discount=discount
    )
