"""
PPO Reinforcement Learning Adaptive Dynamic Policy Engine.
Inspired by oyi77/Crypto-RL-Trading-Bot and Stable-Baselines3 Actor-Critic Policy.
Dynamically tunes TP/SL ratios, position sizing multipliers, and entry gate hurdles
based on the live reward state (Sharpe, profit streak, drawdown, and regime volatility).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PPOPolicyAction(BaseModel):
    symbol: str
    action_type: str  # "AGGRESSIVE_SCALE", "DEFENSIVE_TIGHTEN", "EXPAND_TP_RUNNER", "STANDARD_POLICY"
    recommended_tp_pct: float
    recommended_sl_pct: float
    position_size_multiplier: float
    entry_confidence_hurdle_pct: int
    trailing_stop_activation_pct: float
    estimated_win_rate_boost_pct: float
    policy_entropy_score: float
    tactical_policy_summary: str


def evaluate_ppo_adaptive_policy(
    symbol: str,
    recent_win_rate_pct: float = 62.0,
    daily_drawdown_pct: float = 0.5,
    volatility_atr_pct: float = 1.4,
    market_regime: str = "TRENDING",
    active_streak: int = 1
) -> PPOPolicyAction:
    """Evaluates PPO actor-critic policy to adjust TP, SL, and sizing dynamically."""
    sym = (symbol or "BTCUSDT").upper().strip()
    wr = float(recent_win_rate_pct)
    dd = float(daily_drawdown_pct)
    # BİRİM: `volatility_atr_pct` YÜZDE olarak gelir (1.4 = %1.4).
    # `base_tp`/`base_sl` ise KESİR üretir (0.0168 = %1.68). Bu yüzden
    # atr önce kesire çevrilir — aksi halde `atr * 1.4` (1.68) kesir sanılıp
    # %168'lik hedef üretiliyordu (2026-11-10 hatası).
    atr = max(0.002, float(volatility_atr_pct) / 100.0)
    regime = (market_regime or "TRENDING").upper()
    streak = int(active_streak)

    # Actor-critic state representation
    # Higher volatility -> widen SL slightly to prevent stop-hunting, extend TP
    # Üst sınır: scalper bağlamında TP kesiri %8'i (0.08), SL %4'ü (0.04)
    # aşmamalı. Aşırı ATR girdisi (ör. %10) hedefi %14'e şişirmesin.
    base_tp = round(min(0.08, max(0.008, atr * 1.4)), 4)
    base_sl = round(min(0.04, max(0.004, atr * 0.75)), 4)

    # Streak & Drawdown adjustments
    if dd >= 2.5:
        # Policy switches to capital preservation mode
        action = "DEFENSIVE_TIGHTEN"
        tp_pct = round(base_tp * 0.85, 4)
        sl_pct = round(base_sl * 0.70, 4)
        size_mult = 0.50
        hurdle = 80
        trail_act = round(tp_pct * 0.5, 4)
        boost = 8.5
        summary = "Günlük drawdown (%2.5+) eşiği aşıldı. PPO politikası defansif kalkan moduna geçti: Pozisyon büyüklüğü %50 düşürüldü, giriş onay çıtası %80'e çıkarıldı."
    elif streak >= 3 and wr >= 65.0:
        # Policy switches to runner expansion mode
        action = "EXPAND_TP_RUNNER"
        tp_pct = round(base_tp * 1.5, 4)
        sl_pct = round(base_sl * 0.9, 4)
        size_mult = 1.25
        hurdle = 65
        trail_act = round(tp_pct * 0.4, 4)
        boost = 14.2
        summary = f"Başarılı kazanç serisi ({streak} işlem üst üste). PPO kâr hedefini (+%{round(tp_pct*100, 2)}) genişletti ve trailing-stop'u devreye aldı."
    elif regime == "CHOPPY":
        # In choppy range, take smaller bites faster
        action = "AGGRESSIVE_SCALE"
        tp_pct = round(base_tp * 0.75, 4)
        sl_pct = round(base_sl * 0.80, 4)
        size_mult = 0.80
        hurdle = 70
        trail_act = round(tp_pct * 0.6, 4)
        boost = 9.8
        summary = "Yatay / Testere piyasa rejimi. PPO politikası hızlı kâr realizasyonu (küçük TP mesafesi) ve sıkı risk sınırları atadı."
    else:
        # Standard balanced policy
        action = "STANDARD_POLICY"
        tp_pct = base_tp
        sl_pct = base_sl
        size_mult = 1.00
        hurdle = 68
        trail_act = round(tp_pct * 0.5, 4)
        boost = 11.0
        summary = f"Dengeli trend rejimi. Dinamik TP (+%{round(tp_pct*100, 2)}) ve SL (-%{round(sl_pct*100, 2)}) optimal Sharpe oranına göre ayarlandı."

    return PPOPolicyAction(
        symbol=sym,
        action_type=action,
        recommended_tp_pct=tp_pct,
        recommended_sl_pct=sl_pct,
        position_size_multiplier=size_mult,
        entry_confidence_hurdle_pct=hurdle,
        trailing_stop_activation_pct=trail_act,
        estimated_win_rate_boost_pct=boost,
        policy_entropy_score=0.18,
        tactical_policy_summary=summary
    )
