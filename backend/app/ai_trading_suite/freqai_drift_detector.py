"""
FreqAI inspired Dissimilarity Index (DI) & Market Concept Drift Detector.
Detects when live market conditions diverge significantly from historical model training data.
Acts as a circuit-breaker to halt or downscale trades during structural market anomalies.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
import numpy as np
from pydantic import BaseModel, Field


class DriftMetric(BaseModel):
    feature_name: str
    current_value: float
    baseline_mean: float
    z_score: float
    is_outlier: bool


class FreqAIDriftResult(BaseModel):
    symbol: str
    dissimilarity_index: float = Field(..., description="DI score; >1.0 indicates strong concept drift")
    drift_status: str  # "NORMAL_REGIME", "MILD_DRIFT", "CRITICAL_DRIFT"
    is_drift_detected: bool
    safe_to_trade: bool
    outlier_count: int
    metrics: List[DriftMetric]
    system_action: str  # "FULL_ALLOCATION", "REDUCE_SIZE_50", "HALT_NEW_ENTRIES"
    verdict: str


def evaluate_freqai_drift(
    symbol: str,
    current_features: Optional[Dict[str, float]] = None,
    baseline_stats: Optional[Dict[str, Dict[str, float]]] = None
) -> FreqAIDriftResult:
    """Computes FreqAI Dissimilarity Index (DI) against baseline statistics."""
    sym = (symbol or "BTCUSDT").upper().strip()
    feat = current_features or {}

    # Standard baselines if none provided
    defaults = {
        "volatility_atr_pct": {"mean": 1.8, "std": 0.5},
        "volume_surge_ratio": {"mean": 1.1, "std": 0.4},
        "rsi_distance_50": {"mean": 6.0, "std": 12.0},
        "spread_pct": {"mean": 0.08, "std": 0.04},
        "orderbook_imbalance": {"mean": 0.05, "std": 0.25}
    }
    stats = baseline_stats or defaults

    metrics: List[DriftMetric] = []
    sq_z_sum = 0.0
    outliers = 0

    for k, stat in stats.items():
        val = float(feat.get(k, stat["mean"]))
        m = stat["mean"]
        s = max(0.0001, stat["std"])
        z = (val - m) / s
        sq_z_sum += z ** 2
        is_out = abs(z) > 2.5
        if is_out:
            outliers += 1
        metrics.append(DriftMetric(
            feature_name=k,
            current_value=round(val, 3),
            baseline_mean=round(m, 3),
            z_score=round(z, 2),
            is_outlier=is_out
        ))

    # Normalized Mahalanobis-like Dissimilarity Index (DI)
    n_feats = max(1, len(metrics))
    di = round(math.sqrt(sq_z_sum / n_feats), 2)

    if di >= 2.0 or outliers >= 2:
        status = "CRITICAL_DRIFT"
        safe = False
        action = "HALT_NEW_ENTRIES"
        verdict = f"Piyasa yapısında kritik rejim kayması tespit edildi (DI={di:.2f}). Strateji güvenilirlik eşiği aşıldı; yeni işlem açılması durduruldu."
    elif di >= 1.25 or outliers == 1:
        status = "MILD_DRIFT"
        safe = True
        action = "REDUCE_SIZE_50"
        verdict = f"Hafif rejim anomalisi mevcut (DI={di:.2f}). İşlem tutarı %50 oranında sınırlandırılmalı."
    else:
        status = "NORMAL_REGIME"
        safe = True
        action = "FULL_ALLOCATION"
        verdict = f"Piyasa normal dağılım aralığında (DI={di:.2f}). Strateji parametreleri tam kapasite uygulanabilir."

    return FreqAIDriftResult(
        symbol=sym,
        dissimilarity_index=di,
        drift_status=status,
        is_drift_detected=(status != "NORMAL_REGIME"),
        safe_to_trade=safe,
        outlier_count=outliers,
        metrics=metrics,
        system_action=action,
        verdict=verdict
    )
