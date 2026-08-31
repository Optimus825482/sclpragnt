"""ML fiyat-tahmin modeli: özellik üretimi, eğitim ve artifact yönetimi.

Tasarım (kullanıcı vizyonu): sembol bazlı, taze veriyle eğitilen, journal'daki
ölçülmüş tahmin sonuçlarıyla sürekli pekişen bir yükseliş hedefi modeli.
- Tek taban model; sembol/gün-çeyreği/saat özellik olarak girer (veri açlığı
  yerine genelleme), HistGradientBoosting NaN özellikleri doğal kabul eder.
- Etiket: sonraki H dakikadaki gerçek maksimum yükseliş (MFE) / düşüş (MAE).
- Journal (llm_forecasts, evaluated) satırları doğrulanmış canlı örnek olarak
  ML_JOURNAL_SAMPLE_WEIGHT ağırlığıyla eğitime girer -> model kendi
  hatalarından/başarılarından öğrenir.
- Regressor %ML_TARGET_QUANTILE çeyreğini tahmin eder (dürüst scalper hedefi);
  classifier "hedefe dokunma olasılığı" verir.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import numpy as np

from .config import config

logger = logging.getLogger("scalper.ml")

FEATURE_VERSION = "v1"
HORIZONS = (5, 15)
FEATURE_NAMES = [
    "ret1_pct", "ret3_pct", "ret5_pct", "atr_pct", "bb_width_pct", "rsi14",
    "mfi14", "vol_z", "linreg_slope10_pct", "aroon_up14", "aroon_down14",
    "hour", "day_quarter", "velocity_proxy", "symbol_code",
]


def _rolling(a: np.ndarray, window: int) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view
    if len(a) < window:
        return np.full(len(a), np.nan, dtype=np.float64)
    windows = sliding_window_view(a, window)
    out = np.full(len(a), np.nan, dtype=np.float64)
    out[window - 1:] = windows.mean(axis=1)
    return out


def _rolling_std(a: np.ndarray, window: int) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view
    if len(a) < window:
        return np.full(len(a), np.nan, dtype=np.float64)
    windows = sliding_window_view(a, window)
    out = np.full(len(a), np.nan, dtype=np.float64)
    out[window - 1:] = windows.std(axis=1)
    return out


def _rolling_argmax_dist(a: np.ndarray, window: int, highest: bool) -> np.ndarray:
    """Aroon bileşeni: pencere içindeki en uç değerin kaç bar önce olduğuna daken mesafe."""
    from numpy.lib.stride_tricks import sliding_window_view
    if len(a) < window:
        return np.full(len(a), np.nan, dtype=np.float64)
    windows = sliding_window_view(a, window)
    hit = windows.argmax(axis=1) if highest else windows.argmin(axis=1)
    out = np.full(len(a), np.nan, dtype=np.float64)
    out[window - 1:] = (window - 1) - hit
    return out


def _future_extreme(a: np.ndarray, horizon: int, highest: bool) -> np.ndarray:
    """Her bar i için a[i+1 .. i+horizon] aralığının en uç değeri (mum i hariç)."""
    from numpy.lib.stride_tricks import sliding_window_view
    n = len(a)
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= horizon:
        return out
    windows = sliding_window_view(a, horizon)  # window j = a[j .. j+horizon-1]
    extremes = windows.max(axis=1) if highest else windows.min(axis=1)
    # i için gelecek penceresi a[i+1..i+horizon] = extremes[i+1]
    out[:n - horizon] = extremes[1:]
    return out


def build_symbol_dataset(open_time: np.ndarray, high: np.ndarray, low: np.ndarray,
                         close: np.ndarray, volume: np.ndarray, symbol_code: int) -> dict[str, np.ndarray]:
    """Tek sembolün M1 dizilerinden özellik matrisi + etiketler üretir.

    Tüm hesaplar vektörel; özellik yalnızca bar t kapanışına kadar bilgi
    kullanır, etiketler t+1..t+H geleceğinden gelir (sızıntı yok).
    """
    c = close.astype(np.float64)
    h = high.astype(np.float64)
    low_ = low.astype(np.float64)
    v = volume.astype(np.float64)
    n = len(c)
    prev_c = np.concatenate(([np.nan], c[:-1]))

    ret1 = c / prev_c - 1
    ret3 = c / np.concatenate(([np.nan] * 3, c[:-3])) - 1 if n > 3 else np.full(n, np.nan)
    ret5 = c / np.concatenate(([np.nan] * 5, c[:-5])) - 1 if n > 5 else np.full(n, np.nan)

    tr = np.maximum(h - low_, np.maximum(np.abs(h - prev_c), np.abs(low_ - prev_c)))
    atr_pct = _rolling(tr, 14) / c
    std20 = _rolling_std(c, 20)
    bb_width = (4 * std20) / c

    gain = np.clip(np.diff(c, prepend=c[0]), 0, None)
    loss = np.clip(np.diff(c, prepend=c[0]), None, 0) * -1
    avg_gain = _rolling(gain, 14)
    avg_loss = _rolling(loss, 14)
    rsi = 100 - 100 / (1 + avg_gain / np.where(avg_loss == 0, np.nan, avg_loss))

    tp = (h + low_ + c) / 3
    flow = tp * v
    tp_up = np.diff(tp, prepend=tp[0]) > 0
    pos_flow = np.where(tp_up, flow, 0.0)
    neg_flow = np.where(tp_up, 0.0, flow)
    pos_sum = _rolling(pos_flow, 14)
    neg_sum = _rolling(neg_flow, 14)
    mfi = 100 - 100 / (1 + pos_sum / np.where(neg_sum == 0, np.nan, neg_sum))

    vol_z = (v - _rolling(v, 20)) / np.where(_rolling_std(v, 20) == 0, np.nan, _rolling_std(v, 20))

    # 10-bar LinReg eğimi: slope = cov(x, y)/var(x), x = 0..9
    from numpy.lib.stride_tricks import sliding_window_view
    x = np.arange(10, dtype=np.float64)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    out = np.full(n, np.nan, dtype=np.float64)
    if n >= 10:
        windows = sliding_window_view(c, 10)
        y_mean = windows.mean(axis=1, keepdims=True)
        slope = ((windows - y_mean) * (x - x_mean)).sum(axis=1) / x_var
        out[9:] = slope / windows.mean(axis=1)

    aroon_up = 100 - 100 * _rolling_argmax_dist(c, 14, highest=True) / 14
    aroon_down = 100 - 100 * _rolling_argmax_dist(c, 14, highest=False) / 14

    hours = ((open_time.astype(np.int64) // 1000 + 3 * 3600) % 86400) // 3600
    day_quarter = hours // 6
    velocity_proxy = atr_pct * 100 * (1 + np.nan_to_num(ret3, nan=0.0))

    features = np.column_stack([
        ret1, ret3, ret5, atr_pct, bb_width, rsi, mfi, vol_z, out,
        aroon_up, aroon_down, hours.astype(np.float64), day_quarter.astype(np.float64),
        velocity_proxy, np.full(n, float(symbol_code)),
    ]).astype(np.float32)

    labels = {}
    for horizon in HORIZONS:
        fut_high = _future_extreme(h, horizon, highest=True)
        fut_low = _future_extreme(low_, horizon, highest=False)
        labels[f"mfe_{horizon}"] = (fut_high / c - 1).astype(np.float32)
        labels[f"mae_{horizon}"] = (fut_low / c - 1).astype(np.float32)
    labels["open_time"] = open_time.astype(np.int64)
    return {"features": features, **labels}


def prepare_journal_samples(rows: list[dict], symbol_codes: dict[str, int]):
    """Ölçülmüş canlı tahminler: özellikler snapshot'tan, etiket gerçek sonuçtan.

    Yalnızca direction='up' satırlar; etiket MFE, ikinci etiket min_move_pct'e
    dokunma (classifier). Ağırlık ML_JOURNAL_SAMPLE_WEIGHT (pekiştirme).
    """
    X, y_mfe, y_hit, horizon_ids, weights = [], [], [], [], []
    for row in rows or []:
        if row.get("direction") != "up" or row.get("max_favorable_pct") is None:
            continue
        snap = row.get("snapshot") or {}
        sym = str(row.get("symbol") or "").upper()
        if sym not in symbol_codes:
            continue
        horizon = int(row.get("horizon_minutes") or 5)
        if horizon not in HORIZONS:
            continue
        mfe = float(row["max_favorable_pct"])
        X.append([snap.get("ret3_pct"), snap.get("ret3_pct"), snap.get("ret3_pct"),
                  (snap.get("atr_pct") or 0) / 100 if snap.get("atr_pct") is not None else None,
                  (snap.get("bb_width_pct") or 0) / 100 if snap.get("bb_width_pct") is not None else None,
                  snap.get("rsi"), snap.get("mfi"), None,
                  (snap.get("linreg_slope10_pct") or 0) / 100 if snap.get("linreg_slope10_pct") is not None else None,
                  snap.get("aroon_up"), snap.get("aroon_down"),
                  None, None, None, float(symbol_codes[sym])])
        y_mfe.append(mfe)
        y_hit.append(1.0 if mfe >= config.ML_HIT_TARGET_PCT.get(horizon, 0.02) else 0.0)
        horizon_ids.append(HORIZONS.index(horizon))
        weights.append(config.ML_JOURNAL_SAMPLE_WEIGHT)
    if not X:
        empty = np.empty((0, len(FEATURE_NAMES)), dtype=np.float32)
        return empty, np.empty(0, dtype=np.float32), np.empty(0), np.empty(0), np.empty(0, dtype=np.float32)
    return (np.asarray(X, dtype=np.float32), np.asarray(y_mfe, dtype=np.float32),
            np.asarray(y_hit), np.asarray(horizon_ids), np.asarray(weights, dtype=np.float32))


def train(candles: dict[str, dict[str, np.ndarray]], journal_rows: list[dict]) -> dict[str, Any]:
    """Eğitim: candle verisi + journal örnekleri -> artifact + metrics sözlüğü.

    Saf/senkron fonksiyon; DB okuma ve artifact kaydı çağıran tarafta async
    yapılır. Holdout: candle örneklerinin zaman sırasıyla son %15'i.
    Journal örnekleri (doğrulanmış canlı tahminler) tamamen eğitime girer.
    """
    try:
        from sklearn.ensemble import (HistGradientBoostingClassifier,
                                      HistGradientBoostingRegressor)
    except ImportError as exc:
        raise RuntimeError("scikit-learn kurulu değil; requirements güncel mi?") from exc

    import joblib

    if not candles:
        raise RuntimeError("Eğitim verisi yok: historical_candles boş")
    symbols = sorted(candles)
    symbol_codes = {sym: idx for idx, sym in enumerate(symbols)}
    journal_X, journal_mfe, journal_hit, journal_h, journal_w = prepare_journal_samples(journal_rows, symbol_codes)

    xs, mfe_by_h, times_by_h = {h: [] for h in HORIZONS}, {h: [] for h in HORIZONS}, {h: [] for h in HORIZONS}
    for sym, arrays in candles.items():
        if len(arrays["close"]) < 120:
            continue
        ds = build_symbol_dataset(arrays["open_time"], arrays["high"], arrays["low"],
                                  arrays["close"], arrays["volume"], symbol_codes[sym])
        for horizon in HORIZONS:
            mfe = ds[f"mfe_{horizon}"]
            valid = np.isfinite(mfe) & np.isfinite(ds["features"][:, 3])
            xs[horizon].append(ds["features"][valid])
            mfe_by_h[horizon].append(mfe[valid])
            times_by_h[horizon].append(ds["open_time"][valid])

    artifact = {"feature_version": FEATURE_VERSION, "feature_names": FEATURE_NAMES,
                "symbol_codes": symbol_codes, "horizons": {}, "trained_at": time.time(),
                "journal_sample_count": int(len(journal_X))}
    metrics: dict[str, Any] = {"per_horizon": {}}

    for horizon in HORIZONS:
        X = np.vstack(xs[horizon]) if xs[horizon] else np.empty((0, len(FEATURE_NAMES)), dtype=np.float32)
        y = np.concatenate(mfe_by_h[horizon]) if mfe_by_h[horizon] else np.empty(0, dtype=np.float32)
        times = np.concatenate(times_by_h[horizon]) if times_by_h[horizon] else np.empty(0, dtype=np.int64)
        if len(X) < 500:
            metrics["per_horizon"][str(horizon)] = {"status": "insufficient_data", "samples": int(len(X))}
            continue
        order = np.argsort(times, kind="stable")
        X, y, times = X[order], y[order], times[order]
        split = int(len(X) * 0.85)
        h_mask = journal_h == HORIZONS.index(horizon)
        X_train = np.vstack([X[:split], journal_X[h_mask]])
        y_train = np.concatenate([y[:split], journal_mfe[h_mask]])
        weights = np.concatenate([np.ones(split, dtype=np.float32), journal_w[h_mask]])
        hit_train = np.concatenate([
            (y[:split] >= config.ML_HIT_TARGET_PCT.get(horizon, 0.02)).astype(np.float64),
            journal_hit[h_mask]])

        reg = HistGradientBoostingRegressor(loss="quantile", quantile=config.ML_TARGET_QUANTILE,
                                            max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                            early_stopping=True, random_state=7)
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                             early_stopping=True, random_state=7)
        reg.fit(X_train, y_train, sample_weight=weights)
        clf.fit(X_train, hit_train, sample_weight=weights)

        X_hold, y_hold = X[split:], y[split:]
        pred = reg.predict(X_hold)
        hit_rate = float(np.mean(y_hold >= config.ML_HIT_TARGET_PCT.get(horizon, 0.02)))
        metrics["per_horizon"][str(horizon)] = {
            "samples": int(len(X)), "holdout": int(len(X_hold)),
            "mae_mfe_pct": round(float(np.mean(np.abs(pred - y_hold))) * 100, 4),
            "pred_p65_pct_mean": round(float((pred * 100).mean()), 3),
            "actual_mfe_pct_mean": round(float((y_hold * 100).mean()), 3),
            "actual_hit_rate": round(hit_rate, 4),
            "journal_samples": int(h_mask.sum()),
        }
        artifact["horizons"][str(horizon)] = {"reg": reg, "clf": clf}

    if not artifact["horizons"]:
        raise RuntimeError(f"Eğitim için yeterli örnek yok: {metrics}")

    os.makedirs(config.ML_MODELS_DIR, exist_ok=True)
    path = os.path.join(config.ML_MODELS_DIR, f"upside_{FEATURE_VERSION}.joblib")
    joblib.dump(artifact, path, compress=3)
    total = sum(int(m.get("samples") or 0) for m in metrics["per_horizon"].values())
    logger.info("[ML] eğitim tamam: %s örnek, %s sembol -> %s", total, len(symbol_codes), path)
    return {"created_at": time.time(), "horizons": list(HORIZONS), "sample_count": int(total),
            "journal_sample_count": artifact["journal_sample_count"], "symbol_count": len(symbol_codes),
            "metrics": metrics, "artifact_path": path, "feature_version": FEATURE_VERSION, "status": "ready"}


_MODEL_CACHE: dict[str, Any] = {"artifact": None, "loaded_at": 0.0}


def load_model(max_age_seconds: int = 86400) -> dict[str, Any] | None:
    """Scout/gölge mod için artifact yükler; 24 saatten eskiyse yeniden okur."""
    import joblib
    now = time.time()
    if _MODEL_CACHE["artifact"] is not None and now - _MODEL_CACHE["loaded_at"] < max_age_seconds:
        return _MODEL_CACHE["artifact"]
    path = os.path.join(config.ML_MODELS_DIR, f"upside_{FEATURE_VERSION}.joblib")
    if not os.path.exists(path):
        return None
    _MODEL_CACHE["artifact"] = joblib.load(path)
    _MODEL_CACHE["loaded_at"] = now
    return _MODEL_CACHE["artifact"]


def predict_target(symbol: str, features: dict[str, Any], horizon: int = 5) -> dict[str, Any] | None:
    """Tek nokta tahmin (Faz 2 gölge modda kullanılacak)."""
    artifact = load_model()
    if not artifact or str(horizon) not in artifact["horizons"]:
        return None
    sym = str(symbol).upper()
    if sym not in artifact["symbol_codes"]:
        return None
    row = [
        features.get("ret3_pct"), features.get("ret3_pct"), features.get("ret3_pct"),
        (features.get("atr_pct") or 0) / 100 if features.get("atr_pct") is not None else None,
        (features.get("bb_width_pct") or 0) / 100 if features.get("bb_width_pct") is not None else None,
        features.get("rsi"), features.get("mfi"), None,
        (features.get("linreg_slope10_pct") or 0) / 100 if features.get("linreg_slope10_pct") is not None else None,
        features.get("aroon_up"), features.get("aroon_down"), None, None, None,
        float(artifact["symbol_codes"][sym]),
    ]
    X = np.asarray([row], dtype=np.float32)
    bundle = artifact["horizons"][str(horizon)]
    return {"target_pct": round(float(bundle["reg"].predict(X)[0]) * 100, 3),
            "hit_probability": round(float(bundle["clf"].predict_proba(X)[0][1]), 4),
            "quantile": config.ML_TARGET_QUANTILE, "trained_at": artifact["trained_at"]}
