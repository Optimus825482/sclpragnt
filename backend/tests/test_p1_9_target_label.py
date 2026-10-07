"""P1-9 KİLİT testleri — iyimser MFE etiketi ve ölü classifier.

BULGU (P1-9): regressor ``labels[f"mfe_{h}"] = fut_high / c - 1`` (gelecek
MAKSİMUM high, yani ulaşılamaz tepe) ile eğitiliyordu; bu değer canlıda
``predict_target`` üzerinden TP hedefine giriyordu → hedef sistematik olarak
fazla yüksekti ve kâr alma nadiren tetikleniyordu. Ayrıca classifier
``class_weight`` OLMADAN eğitiliyordu; nadir pozitif sınıf yüzünden olasılık
``ML_TARGET_MIN_PROB`` eşiğini geçemiyor, ``ml_prob`` özelliği fiilen ölüyordu
(velocity.py:2312 kapısı).

Bu dosya iki düzeltmeyi deterministik sentetik veriyle kilitler:
  1. Etiket: ``realized_{h}`` = ufuk sonu KAPANIŞ getirisi (gerçekleştirilebilir
     çıkış); regressor bununla eğitilir. MFE yalnız analiz + classifier kalır.
  2. classifier ``class_weight="balanced"`` ile kurulur.
"""
import tempfile
import unittest
from unittest import mock

import numpy as np

from app import ml_forecast
from app.ml_forecast import (FEATURE_NAMES, build_symbol_dataset,
                             prepare_journal_samples)


def _handcrafted():
    """Eldeki küçük seri: MFE ile gerçekleşen çıkışın AYRIŞTIĞI bilinen dizi."""
    open_time = np.arange(6, dtype=np.int64) * 300_000
    closes = np.array([100.0, 101.0, 102.0, 101.0, 100.0, 99.0])
    highs = closes + 0.5
    lows = closes - 0.5
    vols = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    return open_time, highs, lows, closes, vols


class CorrectedTargetLabelTests(unittest.TestCase):
    """Etiket sözleşmesi: realized = ufuk sonu kapanış getirisi (MFE değil)."""

    def test_realized_5m_is_the_close_to_close_return(self):
        ot, h, l, c, v = _handcrafted()
        ds = build_symbol_dataset(ot, h, l, c, v, 0, bar_minutes=5)
        realized = ds["realized_5"]
        # horizon 5 dk / 5m bar = 1 bar ileri: close[t+1]/close[t]-1
        self.assertAlmostEqual(float(realized[0]), 101.0 / 100.0 - 1, places=6)
        self.assertAlmostEqual(float(realized[1]), 102.0 / 101.0 - 1, places=6)
        self.assertAlmostEqual(float(realized[3]), 100.0 / 101.0 - 1, places=6)
        # Ufuk kapanmayan son bar: etiket UYDURULMAZ (NaN, ileriye dönük bilgi yok).
        self.assertTrue(np.isnan(realized[-1]))

    def test_realized_uses_close_not_the_future_high(self):
        """P1-9: regressor etiketi ulaşılamaz tepeyi DEĞİL, gerçek çıkışı tutmalı."""
        ot, h, l, c, v = _handcrafted()
        ds = build_symbol_dataset(ot, h, l, c, v, 0, bar_minutes=5)
        realized, mfe = ds["realized_5"], ds["mfe_5"]
        # high > close olduğu için gelecek tepe, gerçekleşen çıkıştan DAİMA yüksek.
        self.assertGreater(float(mfe[0]), float(realized[0]))
        self.assertAlmostEqual(float(mfe[0]), 101.5 / 100.0 - 1, places=6)
        self.assertAlmostEqual(float(realized[0]), 101.0 / 100.0 - 1, places=6)

    def test_realized_15m_spans_three_bars(self):
        ot, h, l, c, v = _handcrafted()
        ds = build_symbol_dataset(ot, h, l, c, v, 0, bar_minutes=5)
        realized = ds["realized_15"]
        # horizon 15 dk / 5m bar = 3 bar ileri.
        self.assertAlmostEqual(float(realized[0]), 101.0 / 100.0 - 1, places=6)
        self.assertAlmostEqual(float(realized[2]), 99.0 / 102.0 - 1, places=6)
        self.assertTrue(np.isnan(realized[3]), "t+3 dizinin dışına taşınca NaN olmalı")

    def test_mfe_and_mae_labels_are_preserved_for_analysis(self):
        """MFE/MAE analiz + classifier için KORUNUR (silinmedi)."""
        ot, h, l, c, v = _handcrafted()
        ds = build_symbol_dataset(ot, h, l, c, v, 0, bar_minutes=5)
        for key in ("mfe_5", "mae_5", "mfe_15", "mae_15"):
            self.assertIn(key, ds)


class JournalTargetTests(unittest.TestCase):
    """Journal satırı regressor hedefi DÜZELTİLMİŞ sonuçtur (MFE değil)."""

    def _row(self, **extra):
        row = {
            "direction": "up", "symbol": "BTC", "horizon_minutes": 5,
            "max_favorable_pct": 3.0, "timestamp": 1.75e12,
            "snapshot": {"atr_pct": 1.0, "ret3_pct": 0.5, "rsi": 57},
        }
        row.update(extra)
        return row

    def test_target_prefers_realized_outcome_over_mfe(self):
        rows = [self._row(outcome_return_pct=0.01)]
        X, y_target, y_hit, *_ = prepare_journal_samples(rows, {"BTC": 0})
        self.assertEqual(X.shape[0], 1)
        # Hedef = gerçekleşen çıkış (0.01), MFE (3.0) DEĞİL.
        self.assertAlmostEqual(float(y_target[0]), 0.01, places=6)
        # classifier hedefi MFE'ye dayanır: 3.0 >= %2 eşiği -> 1.0.
        self.assertAlmostEqual(float(y_hit[0]), 1.0, places=6)

    def test_target_falls_back_to_mfe_for_legacy_rows(self):
        """outcome_return_pct kolonu öncesi satırlar: güvenli geri-uyumluluk."""
        rows = [self._row()]
        _, y_target, *_ = prepare_journal_samples(rows, {"BTC": 0})
        self.assertAlmostEqual(float(y_target[0]), 3.0, places=6)

    def test_negative_realized_is_used_as_is(self):
        """Gerçekleşen kayıp da hedeftir — iyimserliğe geri dönülmemeli."""
        rows = [self._row(outcome_return_pct=-0.02)]
        _, y_target, *_ = prepare_journal_samples(rows, {"BTC": 0})
        self.assertAlmostEqual(float(y_target[0]), -0.02, places=6)


class _RecordingRegressor:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fit_y = None
        self.fit_w = None
        _RecordingRegressor.instances.append(self)

    def fit(self, X, y, sample_weight=None):
        self.fit_y = np.asarray(y)
        self.fit_w = None if sample_weight is None else np.asarray(sample_weight)
        return self

    def predict(self, X):
        return np.zeros(len(np.asarray(X)), dtype=np.float64)


class _RecordingClassifier:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fit_y = None
        _RecordingClassifier.instances.append(self)

    def fit(self, X, y, sample_weight=None):
        self.fit_y = np.asarray(y)
        return self

    def predict(self, X):
        return np.zeros(len(np.asarray(X)), dtype=np.int64)

    def predict_proba(self, X):
        count = len(np.asarray(X))
        return np.column_stack([np.full(count, 0.4), np.full(count, 0.6)])


def _volatile_candles(bars=700, seed=5):
    """MFE ile gerçekleşen çıkışın AYRIŞTIĞI, eğitime yeterli (>500) sentetik set."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.3, bars))
    high = close + np.abs(rng.normal(0.0, 0.8, bars))   # tepe sıçramaları
    low = close - np.abs(rng.normal(0.0, 0.3, bars))
    volume = 12.0 + np.array([(index * 7) % 11 for index in range(bars)], dtype=np.float64)
    return {
        "BTCUSDT": {
            "open_time": np.arange(bars, dtype=np.int64) * 300_000,
            "high": high, "low": low, "close": close, "volume": volume,
        }
    }


def _expected_train_target(candles, symbol, horizon):
    """train()'in regressor'a vermesi GEREKEN hedefi bağımsız olarak yeniden üretir."""
    arrays = candles[symbol]
    ds = build_symbol_dataset(arrays["open_time"], arrays["high"], arrays["low"],
                              arrays["close"], arrays["volume"], 0, bar_minutes=5)
    feats = ds["features"]
    target = ds[f"realized_{horizon}"]
    finite_cols = [i for i in range(feats.shape[1]) if FEATURE_NAMES[i] != "symbol_code"]
    valid = np.isfinite(target) & np.isfinite(feats[:, 3])
    valid &= np.isfinite(feats[:, finite_cols]).all(axis=1)
    X = feats[valid]
    y = target[valid]
    times = ds["open_time"][valid]
    order = np.argsort(times, kind="stable")
    X, y = X[order], y[order]
    split = int(len(X) * 0.85)
    return y[:split]


class TrainWiringTests(unittest.TestCase):
    """train(): regressor DÜZELTİLMİŞ hedefle ve classifier dengeli ağırlıkla."""

    def _run_train(self, candles, rows=None):
        _RecordingRegressor.instances = []
        _RecordingClassifier.instances = []
        captured = {}
        import joblib
        import sklearn.ensemble as sk_ensemble
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(ml_forecast.config, "ML_MODELS_DIR", tmp), \
                mock.patch.object(sk_ensemble, "HistGradientBoostingRegressor",
                                  _RecordingRegressor), \
                mock.patch.object(sk_ensemble, "HistGradientBoostingClassifier",
                                  _RecordingClassifier), \
                mock.patch.object(joblib, "dump",
                                  lambda obj, path, **kw: captured.update(obj)):
            meta = ml_forecast.train(candles, rows or [])
        return meta, captured

    def test_regressor_is_fed_the_realized_label_not_mfe(self):
        candles = _volatile_candles()
        meta, _ = self._run_train(candles)
        self.assertTrue(_RecordingRegressor.instances, "regressor kurulmadı")
        # İlk ufuk (HORIZONS[0] == 5) için regressor fit(target) doğrulanır.
        reg = _RecordingRegressor.instances[0]
        self.assertIsNotNone(reg.fit_y)
        expected = _expected_train_target(candles, "BTCUSDT", 5)
        np.testing.assert_allclose(reg.fit_y, expected, rtol=1e-5, atol=1e-6)
        # Ve hedef, geleceğin tepesi (MFE) DEĞİL: MFE'ye eşit çıkamaz.
        arrays = candles["BTCUSDT"]
        ds = build_symbol_dataset(arrays["open_time"], arrays["high"], arrays["low"],
                                  arrays["close"], arrays["volume"], 0, bar_minutes=5)
        self.assertFalse(np.allclose(reg.fit_y, np.nan_to_num(ds["mfe_5"][:len(reg.fit_y)])),
                         "regressor hedefi hâlâ MFE gibi görünüyor")

    def test_classifier_uses_balanced_class_weight(self):
        candles = _volatile_candles()
        self._run_train(candles)
        self.assertTrue(_RecordingClassifier.instances, "classifier kurulmadı")
        for clf in _RecordingClassifier.instances:
            self.assertEqual(clf.kwargs.get("class_weight"), "balanced",
                             "classifier class_weight='balanced' olmalı (P1-9)")

    def test_metrics_report_the_optimism_gap(self):
        candles = _volatile_candles()
        meta, _ = self._run_train(candles)
        metrics = meta["metrics"]["per_horizon"]["5"]
        self.assertIn("mfe_optimism_gap_pct", metrics)
        self.assertIn("mae_pct", metrics)
        # MFE ortalaması gerçekleşen çıkıştan yüksek olmalı (etki ölçülür).
        self.assertGreater(metrics["actual_mfe_pct_mean"], metrics["actual_realized_pct_mean"])

    def test_journal_weight_applies_to_corrected_target(self):
        """3× pekiştirme ağırlığı regressor'a geçer ve hedef GERÇEKLEŞEN'dir."""
        candles = _volatile_candles()
        rows = [{
            "direction": "up", "symbol": "BTCUSDT", "horizon_minutes": 5,
            "max_favorable_pct": 2.5, "outcome_return_pct": 0.004,
            # Holdout kesiminden ÖNCE sayılacak çok eski karar zamanı.
            "timestamp": 1.0, "snapshot": {"atr_pct": 1.0, "ret3_pct": 0.5, "rsi": 55},
        }]
        self._run_train(candles, rows)
        reg = _RecordingRegressor.instances[0]
        # Journal katkısı hedefin SON elemanıdır ve DÜZELTİLMİŞ değeri taşır.
        self.assertAlmostEqual(float(reg.fit_y[-1]), 0.004, places=6)


if __name__ == "__main__":
    unittest.main()
