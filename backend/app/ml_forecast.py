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

from datetime import datetime, timezone
import json
import logging
import os
import time
from typing import Any

import numpy as np

from .config import config

logger = logging.getLogger("scalper.ml")

FEATURE_VERSION = "v3"  # v3: göstergeler kanonik kaynakla birleştirildi
                        #     (Wilder RSI, Aroon-25, kanonik linreg_slope10_pct).
                        #     v2 artefaktları artık yüklenmez; yeniden eğitim gerekir.
HORIZONS = (5, 15)
# ML-01 (2026-09-12): eğitim ve çıkarım AYNI bar dayanağını kullanmalıdır.
# Model 5m kapanış barlarıyla eğitilir; çıkarım da 5m kapanış barlardan
# özellik üretmelidir. Aksi halde aynı isimli özellik (ret3_pct, atr_pct,
# rsi14, aroon25) farklı anlama gelir ve model eğitim dağılımının dışında
# bir noktada çalışır.
TRAINING_BAR_MINUTES = 5


def inference_bar_minutes() -> int:
    """Çıkarımın kullanması gereken bar dakikası — eğitimle birebir.

    Çağıranlar (velocity, chart_forecast, llm_chat) eğitimle uyumlu kalmak
    için 5m kapanış barlarından özellik üretirken bu fonksiyonu kullanmalıdır.
    """
    return TRAINING_BAR_MINUTES
FEATURE_NAMES = [
    "ret1_pct", "ret3_pct", "ret5_pct", "atr_pct", "bb_width_pct", "rsi14",
    "mfi14", "vol_z", "linreg_slope10_pct", "aroon_up25", "aroon_down25",
    "hour", "day_quarter", "velocity_proxy", "symbol_code",
]

# ---------------------------------------------------------------------------
# Feature-unit contract (tek kaynak — eğitim ve çıkarım AYNI birimi görmeli):
#   TÜM ``*_pct`` girdi alanları YÜZDE'dir (2.0 = %2). predict_target ve
#   prepare_journal_samples bunları içeride KESİRE çevirir (2.0 -> 0.02) ve
#   satıra kesir olarak yazar; build_symbol_dataset ise aynı sonucu doğrudan
#   ham fiyat dizilerinden üretir. Ayrıca rsi/mfi/aroon 0..100 ölçeğindedir.
#
# Gösterge tanım sözleşmesi (2026-09-10): eğitimdeki vektörel hesaplar ile
# çıkarımdaki skaler hesaplar AYNI tanımı kullanmalıdır. Kanonik skaler
# kaynak ``technical_analysis`` (``_rsi`` Wilder, ``_aroon`` periyot 25,
# ``_linreg_slope_pct`` periyot 10). Buradaki vektörel eşlenikler
# ``tests/test_ml_feature_parity.py`` ile birebir eşleşmeye zorlanır.
# ---------------------------------------------------------------------------
def _ratio_from_pct(value) -> float | None:
    """None/NaN güvenli yüzde→kesir dönüşümü (sözleşme: girdi YÜZDE)."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric / 100.0


def velocity_proxy_value(atr_ratio: float | None, ret3_ratio: float | None) -> float:
    """Paylaşılan hız vekili: ATR oranı × 100 × (1 + 3-bar getiri oranı).

    build_symbol_dataset'teki ``atr_pct * 100 * (1 + ret3)`` ile birebir aynı
    tanım; eğitim/çıkarım arasında özellik kaymasını önler.
    """
    try:
        atr = float(atr_ratio) if atr_ratio is not None and np.isfinite(float(atr_ratio)) else 0.0
        ret3 = float(ret3_ratio) if ret3_ratio is not None and np.isfinite(float(ret3_ratio)) else 0.0
    except (TypeError, ValueError):
        return 0.0
    return atr * 100.0 * (1.0 + ret3)


def _wilder_rsi_series(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Vektörel Wilder RSI — ``technical_analysis._rsi`` ile birebir aynı sonuç.

    Wilder yumuşatması özyinelemeli olduğundan (``avg = (avg*(p-1)+x)/p``)
    dizinin tamamı için tek geçiş gerekir; başlangıç değeri ilk ``period``
    farkın basit ortalamasıdır (kanonik tanım). NaN'lar yalnızca ısınma
    bölgesinde (``period`` bar) kalır.
    """
    n = len(closes)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # t barındaki RSI, deltas[0..t-1] işlendikten sonraki durumdur; ilk geçerli
    # bar t=period olup başlangıç ilk `period` farkın basit ortalamasıdır.
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    out[period] = _rsi_from_averages(avg_gain, avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi_from_averages(avg_gain, avg_loss)
    return out


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    """Wilder ortalamalarından RSI — kanonik ``technical_analysis._rsi`` ile aynı."""
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


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
    """Aroon bileşeni: pencere içindeki en uç değere kaç bar önce ulaşıldığı.

    Eşit değerlerde **son** oluşum esas alınır (kanonik ``technical_analysis._aroon``
    ile aynı): ters pencerede argmax/argmin almak doğrudan "kaç bar önce"yi verir.
    """
    from numpy.lib.stride_tricks import sliding_window_view
    if len(a) < window:
        return np.full(len(a), np.nan, dtype=np.float64)
    windows = sliding_window_view(a, window)
    reversed_windows = windows[:, ::-1]
    hit = reversed_windows.argmax(axis=1) if highest else reversed_windows.argmin(axis=1)
    out = np.full(len(a), np.nan, dtype=np.float64)
    out[window - 1:] = hit
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
                         close: np.ndarray, volume: np.ndarray, symbol_code: int,
                         bar_minutes: int = 1) -> dict[str, np.ndarray]:
    """Tek sembolün bar dizilerinden özellik matrisi + etiketler üretir.

    bar_minutes: bar başına dakika (1m veri = 1, 5m veri = 5). HORIZONS dakika
    cinsindendir; bar horizonu = horizon / bar_minutes (5m veride 5dk=1, 15dk=3).
    Tüm hesaplar vektörel; özellik yalnızca bar t kapanışına kadar bilgi
    kullanır, etiketler t+1..t+H geleceğinden gelir (sızıntı yok).
    """
    c = np.asarray(close, dtype=np.float64)
    h = np.asarray(high, dtype=np.float64)
    low_ = np.asarray(low, dtype=np.float64)
    v = np.asarray(volume, dtype=np.float64)
    open_time = np.asarray(open_time, dtype=np.int64)
    n = len(c)
    prev_c = np.concatenate(([np.nan], c[:-1]))

    ret1 = c / prev_c - 1
    ret3 = c / np.concatenate(([np.nan] * 3, c[:-3])) - 1 if n > 3 else np.full(n, np.nan)
    ret5 = c / np.concatenate(([np.nan] * 5, c[:-5])) - 1 if n > 5 else np.full(n, np.nan)

    tr = np.maximum(h - low_, np.maximum(np.abs(h - prev_c), np.abs(low_ - prev_c)))
    atr_pct = _rolling(tr, 14) / c
    std20 = _rolling_std(c, 20)
    bb_width = (4 * std20) / c

    # RSI: kanonik Wilder yumuşatması (technical_analysis._rsi ile birebir).
    # Önceden basit hareketli ortalama kullanılıyordu; çıkarım tarafı Wilder
    # olduğu için aynı isimli özellik iki farklı dağılım gösteriyordu (E6).
    rsi = _wilder_rsi_series(c, 14)

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

    # Aroon: kanonik periyot 25 (technical_analysis._aroon, sistem genelinde
    # ``aroon_25`` olarak kullanılır ve velocity eşikleri bu periyoda kalibre).
    # Standart tanım gereği pencere period+1 = 26 bardır (değer aralığı 0..100).
    # Kanonik tanım Aroon Up'ı HIGH, Aroon Down'ı LOW üzerinden hesaplar;
    # önceden eğitimde her ikisi de KAPANIŞ fiyatından ve periyot 14 ile
    # hesaplanıyordu → çıkarımla aynı isimli özellik farklı tanımdı (E6).
    aroon_up = 100 - 100 * _rolling_argmax_dist(h, 26, highest=True) / 25
    aroon_down = 100 - 100 * _rolling_argmax_dist(low_, 26, highest=False) / 25

    hours = ((open_time.astype(np.int64) // 1000 + 3 * 3600) % 86400) // 3600
    day_quarter = hours // 6
    # velocity_proxy: eğitim tarafı (vektörel). Skaler eşleniği olan
    # ``velocity_proxy(atr_ratio, ret3_ratio)`` ile aynı tanımı korumalıdır.
    velocity_proxy = atr_pct * 100 * (1 + np.nan_to_num(ret3, nan=0.0))

    features = np.column_stack([
        ret1, ret3, ret5, atr_pct, bb_width, rsi, mfi, vol_z, out,
        aroon_up, aroon_down, hours.astype(np.float64), day_quarter.astype(np.float64),
        velocity_proxy, np.full(n, float(symbol_code)),
    ]).astype(np.float32)

    labels = {}
    for horizon in HORIZONS:
        bars = max(1, round(horizon / bar_minutes))
        fut_high = _future_extreme(h, bars, highest=True)
        fut_low = _future_extreme(low_, bars, highest=False)
        labels[f"mfe_{horizon}"] = (fut_high / c - 1).astype(np.float32)
        labels[f"mae_{horizon}"] = (fut_low / c - 1).astype(np.float32)
    labels["open_time"] = open_time.astype(np.int64)
    return {"features": features, **labels}


def prepare_journal_samples(rows: list[dict], symbol_codes: dict[str, int]):
    """Ölçülmüş canlı tahminler: özellikler snapshot'tan, etiket gerçek sonuçtan.

    Yalnızca direction='up' satırlar; baz etiket MFE, ikinci etiket min_move_pct'e
    dokunma (classifier). Ağırlık ML_JOURNAL_SAMPLE_WEIGHT (pekiştirme).

    Dönüş: (X, y_mfe, y_hit, horizon_ids, weights, timestamps_ms). Son öğe,
    her journal satırının karar zamanını (ms, epoch) taşır; ML-02 kronolojik
    holdout ayrımı bu zaman damgalarına dayanır. Eşleşme sağlama garantisi için
    `ts_list` asymptotic işaretçidir; boş dönüşte de aynı uzunlukta olur.

    ML-09 (2026-09-12): alan kapsamı filtresi. Chat-candidate satırlarının
    snapshot'ı özellik alanları içermeyebilir (yalnız trend/hacim/likidite) →
    özelliklerin neredeyse tamamı NaN olur ve "uydurulmuş" değerler eğitime
    gürültü enjekte eder. Çekirdek özelliklerden en az biri dolu değilse satır
    atılır ve `atr_pct=None` → 0.0 yerine NaN yazılır.
    """
    X, meta, y_min, y_hit, hid, weights, ts_list = [], [], [], [], [], [], []
    for row in rows or []:
        if row.get("direction") != "up" or row.get("max_favorable_pct") is None:
            continue
        snap = row.get("snapshot") or {}
        if isinstance(snap, dict) and not any(
                key in snap for key in ("ret3_pct", "atr_pct", "rsi")) \
                and isinstance(snap.get("candidate"), dict):
            snap = snap["candidate"]
        sym = str(row.get("symbol") or "").upper()
        if sym not in symbol_codes:
            continue
        horizon = int(row.get("horizon_minutes") or 5)
        if horizon not in HORIZONS:
            continue
        mfe = float(row["max_favorable_pct"])
        ts = row.get("timestamp") or row.get("created_at") or row.get("decision_at")
        if isinstance(ts, (int, float)):
            if ts < 1e11:
                ts = ts * 1000
        elif hasattr(ts, "timestamp"):
            ts = ts.timestamp() * 1000
        else:
            ts = time.time() * 1000
        # ML-09 (2026-09-12): alan kapsamı — çekirdek özelliklerden EN AZ biri
        # dolu olmalı. Chat-candidate satırlarında snapshot, özellik alanlarını
        # taşımadığı için bu satırlar hep NaN üretirdi; artık atlanır.
        core_present = any(k in snap and snap.get(k) is not None
                           for k in ("atr_pct", "ret3_pct", "rsi", "aroon_up"))
        if not core_present:
            continue
        hour = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).hour
        hour = (hour + 3) % 24
        day_quarter = hour // 6
        # velocity_proxy: sözleşme gereği TÜM *_pct alanları YÜZDE; kesire çevir
        # ve paykınlanan tanımdan geç (evaluate-allı ham dizi tanımıyla aynı).
        snap_atr_ratio = _ratio_from_pct(snap.get("atr_pct"))
        snap_ret3_ratio = _ratio_from_pct(snap.get("ret3_pct"))
        vp = velocity_proxy_value(snap_atr_ratio, snap_ret3_ratio)
        # ML-09: `atr_pct=None` → 0.0 UYDURMA; model NaN'ı doğal işler.
        X.append([_ratio_from_pct(snap.get("ret1_pct")),
                  snap_ret3_ratio,
                  _ratio_from_pct(snap.get("ret5_pct")),
                  snap_atr_ratio,  # None kalabilir (NaN), 0.0 değil
                  (_ratio_from_pct(snap.get("bb_width_pct")) if snap.get("bb_width_pct") is not None else None),
                  snap.get("rsi"), snap.get("mfi"), None,
                  (_ratio_from_pct(snap.get("linreg_slope10_pct")) if snap.get("linreg_slope10_pct") is not None else None),
                  snap.get("aroon_up"), snap.get("aroon_down"),
                  float(hour), float(day_quarter), float(vp), float(symbol_codes[sym])])
        y_min.append(mfe)
        y_hit.append(1.0 if mfe >= config.ML_HIT_TARGET_PCT.get(horizon, 0.02) else 0.0)
        hid.append(HORIZONS.index(horizon))
        weights.append(config.ML_JOURNAL_SAMPLE_WEIGHT)
        ts_list.append(float(ts))
    if not X:
        empty = np.empty((0, len(FEATURE_NAMES)), dtype=np.float32)
        return (empty, np.empty(0, dtype=np.float32), np.empty(0), np.empty(0),
                np.empty(0, dtype=np.float32), np.empty(0, dtype=np.float64))
    return (np.asarray(X, dtype=np.float32), np.asarray(y_min, dtype=np.float32),
            np.asarray(y_hit), np.asarray(hid), np.asarray(weights, dtype=np.float32),
            np.asarray(ts_list, dtype=np.float64))


def train(candles: dict[str, dict[str, np.ndarray]], journal_rows: list[dict]) -> dict[str, Any]:
    """Eğitim: 5m candle verisi + journal örnekleri -> artifact + metrics sözlüğü.

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
        raise RuntimeError("Eğitim verisi yok: historical_candles (5m) boş")
    symbols = sorted(candles)
    symbol_codes = {sym: idx for idx, sym in enumerate(symbols)}
    (journal_X, journal_mfe, journal_hit, journal_h, journal_w,
     journal_ts) = prepare_journal_samples(journal_rows, symbol_codes)

    xs, mfe_by_h, times_by_h = {h: [] for h in HORIZONS}, {h: [] for h in HORIZONS}, {h: [] for h in HORIZONS}
    for sym, arrays in candles.items():
        if len(arrays["close"]) < 120:
            continue
        ds = build_symbol_dataset(arrays["open_time"], arrays["high"], arrays["low"],
                                  arrays["close"], arrays["volume"], symbol_codes[sym],
                                  bar_minutes=5)
        for horizon in HORIZONS:
            mfe = ds[f"mfe_{horizon}"]
            valid = np.isfinite(mfe) & np.isfinite(ds["features"][:, 3])
            xs[horizon].append(ds["features"][valid])
            mfe_by_h[horizon].append(mfe[valid])
            times_by_h[horizon].append(ds["open_time"][valid])

    artifact = {"feature_version": FEATURE_VERSION, "feature_names": FEATURE_NAMES,
                "symbol_codes": symbol_codes, "horizons": {}, "trained_at": time.time(),
                "journal_sample_count": int(len(journal_X)),
                "training_bar_minutes": TRAINING_BAR_MINUTES}
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
        # ML-02 (2026-09-12): kronolojik holdout bütünlüğü. Journal satırları
        # artık karar zaman damgası (journal_ts, ms) taşır; split noktasına
        # (times[split-1]) KADAR olanlar eğitime, sonrakiler holdout'a girer.
        # Eskiden hepsi eğitime giriyordu → holdout metriği iyimserdi.
        train_cutoff_ms = float(times[split - 1]) if split > 0 else float("-inf")
        in_split_ts = h_mask & (journal_ts <= train_cutoff_ms) if split > 0 else h_mask
        X_train = np.vstack([X[:split], journal_X[in_split_ts]])
        y_train = np.concatenate([y[:split], journal_mfe[in_split_ts]])
        weights = np.concatenate([np.ones(split, dtype=np.float32), journal_w[in_split_ts]])
        hit_train = np.concatenate([
            (y[:split] >= config.ML_HIT_TARGET_PCT.get(horizon, 0.02)).astype(np.float64),
            journal_hit[in_split_ts]])

        reg = HistGradientBoostingRegressor(loss="quantile", quantile=config.ML_TARGET_QUANTILE,
                                            max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                            early_stopping=True, random_state=7)
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                             early_stopping=True, random_state=7)
        reg.fit(X_train, y_train, sample_weight=weights)
        clf.fit(X_train, hit_train, sample_weight=weights)

        X_hold, y_hold = X[split:], y[split:]
        pred = reg.predict(X_hold)
        actual_hit = (y_hold >= config.ML_HIT_TARGET_PCT.get(horizon, 0.02)).astype(np.int64)
        hit_rate = float(np.mean(actual_hit))
        # Model-level holdout metrics (the classifier's own accuracy), so the
        # readout reflects model quality rather than just the dataset hit-rate.
        try:
            clf_pred = clf.predict(X_hold).astype(np.int64)
            model_hit_accuracy = float(np.mean(clf_pred == actual_hit))
        except Exception:
            model_hit_accuracy = None
        metrics["per_horizon"][str(horizon)] = {
            "samples": int(len(X)), "holdout": int(len(X_hold)),
            "mae_mfe_pct": round(float(np.mean(np.abs(pred - y_hold))) * 100, 4),
            "pred_p65_pct_mean": round(float((pred * 100).mean()), 3),
            "actual_mfe_pct_mean": round(float((y_hold * 100).mean()), 3),
            "dataset_hit_rate": round(hit_rate, 4),
            "model_hit_accuracy": (round(model_hit_accuracy, 4) if model_hit_accuracy is not None else None),
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
    """Scout/gölge mod için artifact yükler; 24 saatten geçse de yeniden okur.

    I-05 (2026-09-12): artifact'ın `feature_version` ve `feature_names`i
    FEATURE_VERSION / FEATURE_NAMES ile birebir eşleşmeyen yükleme reddedilir;
    ayrıca (I-04 follow-up) `training_bar_minutes` = TRAINING_BAR_MINUTES
    doğrulanır. Aksi halde predict_target kolonları anlamsız sırada kurar ve
    model "sayı üretmeye devam eder". Uyuşmazlıkta `None` döner + hata loglar.

    Geriye uyumluluk (2026-09-12 üretim regresyonu): W3 öncesi üretilmiş
    artifact'larda `training_bar_minutes` alanı YOKTUR. Bu alan yoksa (None)
    eski artifact'lar da zaten 5m kapanmış barlarla eğitildiği için kabul
    edilir; yalnızca alan MEVCUT ve farklıysa reddedilir. Böylece mevcut
    üretim artifact'ı (upside_v3.joblib) silinip yeniden eğitilmeden çalışır.
    """
    import joblib
    now = time.time()
    if _MODEL_CACHE["artifact"] is not None and now - _MODEL_CACHE["loaded_at"] < max_age_seconds:
        return _MODEL_CACHE["artifact"]
    path = os.path.join(config.ML_MODELS_DIR, f"upside_{FEATURE_VERSION}.joblib")
    if not os.path.exists(path):
        return None
    artifact = joblib.load(path)
    training_bars = artifact.get("training_bar_minutes")
    training_ok = training_bars is None or int(training_bars) == TRAINING_BAR_MINUTES
    if artifact.get("feature_version") != FEATURE_VERSION \
            or artifact.get("feature_names") != FEATURE_NAMES \
            or not training_ok:
        logger.error("[ML] artifact uyumsuz (I-05): %s; feature_version=%r feature_names=%r training=%r",
                     path, artifact.get("feature_version"), artifact.get("feature_names"),
                     artifact.get("training_bar_minutes"))
        _MODEL_CACHE["artifact"] = None
        return None
    _MODEL_CACHE["artifact"] = artifact
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
    ts = features.get("timestamp") or features.get("ts") or features.get("last_closed_at_ms")
    if isinstance(ts, (int, float)):
        if ts < 1e11:
            ts = ts * 1000
    elif hasattr(ts, "timestamp"):
        ts = ts.timestamp() * 1000
    else:
        ts = time.time() * 1000
    hour = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).hour
    hour = (hour + 3) % 24
    day_quarter = hour // 6
    # Sözleşme: girdideki TÜM *_pct alanları YÜZDE; satıra kesir olarak yazılır.
    # velocity_proxy paylaşılan tanımdan geçer (eğitimdeki ölçekle aynı).
    atr_ratio = _ratio_from_pct(features.get("atr_pct"))
    ret3_ratio = _ratio_from_pct(features.get("ret3_pct"))
    vp = velocity_proxy_value(atr_ratio, ret3_ratio)
    row = [
        _ratio_from_pct(features.get("ret1_pct")),
        ret3_ratio,
        _ratio_from_pct(features.get("ret5_pct")),
        atr_ratio if atr_ratio is not None else 0.0,
        _ratio_from_pct(features.get("bb_width_pct")),
        features.get("rsi"), features.get("mfi"), None,
        _ratio_from_pct(features.get("linreg_slope10_pct")),
        features.get("aroon_up"), features.get("aroon_down"),
        float(hour), float(day_quarter), float(vp),
        float(artifact["symbol_codes"][sym]),
    ]
    X = np.asarray([row], dtype=np.float32)
    bundle = artifact["horizons"][str(horizon)]
    return {"target_pct": round(float(bundle["reg"].predict(X)[0]) * 100, 3),
            "hit_probability": round(float(bundle["clf"].predict_proba(X)[0][1]), 4),
            "quantile": config.ML_TARGET_QUANTILE, "trained_at": artifact["trained_at"]}
