"""Kalman Filter Zero-Lag Trend & Noise Reduction Engine.

Implements a 1-dimensional dynamic State-Space Kalman Filter:
- State estimation: True unobserved price and velocity
- Dynamic observation variance update based on high-frequency candle noise
- Zero-lag crossover detection against raw market prices
- Filters out deceptive wick fluctuations without traditional moving average lag.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class KalmanTrendResult(BaseModel):
    symbol: str
    current_price: float
    kalman_price: float
    kalman_velocity: float
    noise_variance: float
    trend_state: str = Field(..., description="BULLISH_TREND, BEARISH_TREND, or CHOPPY_NOISE")
    zero_lag_signal: str = Field(..., description="BULLISH_CROSS, BEARISH_CROSS, or IN_TREND")
    confidence_pct: float = Field(..., ge=0.0, le=100.0)
    verdict: str


class Kalman1DFilter:
    """Adaptive 1D Kalman Filter for financial price smoothing and velocity tracking."""

    def __init__(self, process_variance: float = 1e-4, measurement_variance: float = 1e-2):
        self.q = process_variance  # Process noise (speed of underlying trend changes)
        self.r = measurement_variance  # Measurement noise (tick/wick noise)
        self.x = 0.0  # Estimated true price
        self.v = 0.0  # Estimated velocity (drift)
        self.p = 1.0  # Error covariance
        self.initialized = False

    def update(self, measurement: float) -> tuple[float, float]:
        if not self.initialized:
            self.x = measurement
            self.v = 0.0
            self.p = 1.0
            self.initialized = True
            return self.x, self.v

        # 1. Prediction step
        x_pred = self.x + self.v
        p_pred = self.p + self.q

        # 2. Measurement update step
        kalman_gain = p_pred / (p_pred + self.r)
        self.x = x_pred + kalman_gain * (measurement - x_pred)
        self.v = self.x - x_pred  # Instantaneous velocity update
        self.p = (1.0 - kalman_gain) * p_pred

        return self.x, self.v


def evaluate_kalman_trend(
    symbol: str,
    prices: List[float],
    current_atr: float = 1.0,
    process_variance: float = 1e-4
) -> KalmanTrendResult:
    """Computes zero-lag Kalman smoothed price, velocity, and crossover signals."""
    sym = symbol.upper()
    if not prices:
        return KalmanTrendResult(
            symbol=sym,
            current_price=1.0,
            kalman_price=1.0,
            kalman_velocity=0.0,
            noise_variance=0.01,
            trend_state="CHOPPY_NOISE",
            zero_lag_signal="IN_TREND",
            confidence_pct=50.0,
            verdict="Fiyat serisi yetersiz, nötr rejim."
        )

    # Estimate noise variance from ATR relative to current price
    px = max(prices[-1], 0.000001)
    noise_var = max(1e-5, min(0.1, (current_atr / px) ** 2))

    kf = Kalman1DFilter(process_variance=process_variance, measurement_variance=noise_var)
    kalman_series = []
    velocities = []

    for p in prices:
        k_val, vel = kf.update(p)
        kalman_series.append(k_val)
        velocities.append(vel)

    final_k = kalman_series[-1]
    final_v = velocities[-1]

    # Zero-lag crossover detection
    prev_px = prices[-2] if len(prices) >= 2 else prices[-1]
    prev_k = kalman_series[-2] if len(kalman_series) >= 2 else kalman_series[-1]

    is_bullish_cross = (prev_px <= prev_k) and (px > final_k)
    is_bearish_cross = (prev_px >= prev_k) and (px < final_k)

    if is_bullish_cross:
        signal = "BULLISH_CROSS"
    elif is_bearish_cross:
        signal = "BEARISH_CROSS"
    else:
        signal = "IN_TREND"

    # Trend state
    vel_threshold = px * 0.0002
    if final_v > vel_threshold and px >= final_k:
        state = "BULLISH_TREND"
        conf = min(95.0, 65.0 + (final_v / max(vel_threshold, 1e-6)) * 10.0)
        verdict = f"Kalman Filtresi: Sıfır gecikmeli yukarı yönlü ivme (Hız: +{final_v:.4f}). Fiyat filtrelenmiş ortalamanın üzerinde."
    elif final_v < -vel_threshold and px <= final_k:
        state = "BEARISH_TREND"
        conf = min(95.0, 65.0 + (abs(final_v) / max(vel_threshold, 1e-6)) * 10.0)
        verdict = f"Kalman Filtresi: Sıfır gecikmeli aşağı yönlü ivme (Hız: {final_v:.4f}). Satış baskısı aktif."
    else:
        state = "CHOPPY_NOISE"
        conf = 55.0
        verdict = "Kalman Filtresi: Düşük ivme ve piyasa gürültüsü; net bir yönlü akış yok."

    return KalmanTrendResult(
        symbol=sym,
        current_price=round(px, 6),
        kalman_price=round(final_k, 6),
        kalman_velocity=round(final_v, 6),
        noise_variance=round(noise_var, 6),
        trend_state=state,
        zero_lag_signal=signal,
        confidence_pct=round(conf, 1),
        verdict=verdict
    )
