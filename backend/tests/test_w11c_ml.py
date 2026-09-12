"""W11c (ML kümesi) kilit testleri — ML-03, ML-04, ML-05, ML-06, ML-07, ML-08.

Mutasyon kanıtı: `outputs/denetim_2026-09-12/scratch/verify_w11c_mutations.py`.
"""
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

import joblib
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import ml_forecast  # noqa: E402
from app.routers import velocity  # noqa: E402
from app.technical_analysis import _atr, _bollinger  # noqa: E402


def _series(count=60, start=100.0, step=0.4):
    closes = [start + index * step for index in range(count)]
    highs = [value + 0.6 for value in closes]
    lows = [value - 0.5 for value in closes]
    vols = [10.0 + (index % 5) for index in range(count)]
    return closes, highs, lows, vols


def _step_series():
    """Volatilite sicramali 60 barlik seri.

    Sicrama 15'lik pencerenin EN ESKI barinda (j=45) durur; 14'luk pencere
    onu disarida birakir. Duz seride iki pencere ayni sonucu verirdi, bu
    yuzden pencere kaymasi ancak boyle bir seride gorunur olur.
    """
    closes = [100.0] * 45 + [130.0] * 15
    highs = [value + 0.5 for value in closes]
    lows = [value - 0.5 for value in closes]
    vols = [10.0 + (index % 5) for index in range(len(closes))]
    return closes, highs, lows, vols


class _StubEstimator:
    """Gerçek model kurmadan egitim akisini yürütmek icin sahte estimator.

    `train()` estimator'lari fonksiyon icinde import eder; testte
    `sklearn.ensemble` uzerindeki isimler bunlarla degistirilir.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fit_rows = None

    def fit(self, X, y, sample_weight=None):
        self.fit_rows = len(np.asarray(X))
        return self

    def predict(self, X):
        return np.zeros(len(np.asarray(X)), dtype=np.float64)

    def predict_proba(self, X):
        count = len(np.asarray(X))
        return np.column_stack([np.full(count, 0.4), np.full(count, 0.6)])


def _training_candles(symbols, bars=620):
    """`train()` icin yeterli (>=500 gecerli ornek) sentetik 5m mumlar."""
    out = {}
    for offset, symbol in enumerate(symbols):
        base = 100.0 + 10.0 * offset
        close = np.array([base + index * 0.3 for index in range(bars)],
                         dtype=np.float64)
        out[symbol] = {
            "open_time": np.arange(bars, dtype=np.int64) * 300_000,
            "high": close + 0.4,
            "low": close - 0.3,
            "close": close,
            "volume": np.full(bars, 12.0, dtype=np.float64),
        }
    return out


class _StubModel:
    def __init__(self, value=0.02, proba=0.7):
        self.value = value
        self.proba = proba
        self.last = None

    def predict(self, X):
        self.last = np.asarray(X)
        return np.asarray([self.value])

    def predict_proba(self, X):
        self.last = np.asarray(X)
        return np.asarray([[1.0 - self.proba, self.proba]])


def _fake_artifact(symbol="TESTUSDT"):
    return {
        "feature_version": ml_forecast.FEATURE_VERSION,
        "feature_names": ml_forecast.FEATURE_NAMES,
        "symbol_codes": {symbol: 0},
        "horizons": {"5": {"reg": _StubModel(0.02), "clf": _StubModel(0.02, 0.7)}},
        "trained_at": 1.0,
        "training_bar_minutes": ml_forecast.TRAINING_BAR_MINUTES,
    }


class AtrWindowParityTests(unittest.TestCase):
    """ML-04 — çıkarım ATR'si eğitimle aynı pencereyi (14 TR) kullanmalı."""

    def test_helper_matches_the_canonical_atr(self):
        closes, highs, lows, _ = _series()
        expected = _atr(highs, lows, closes, 14) / closes[-1]
        assert abs(ml_forecast.atr_ratio_from_bars(highs, lows, closes) - expected) < 1e-12

    def test_helper_uses_fourteen_ranges_not_fifteen(self):
        # Volatilite sıçraması 15'lik pencerenin EN ESKİ barında; 14'lük pencere
        # onu dışarıda bırakır. Düz seride ikisi aynı sonucu verirdi.
        closes = [100.0] * 45 + [130.0] * 15
        highs = [value + 0.5 for value in closes]
        lows = [value - 0.5 for value in closes]
        price = closes[-1]
        fifteen = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
                   for j in range(len(closes) - 15, len(closes))]
        old_value = (sum(fifteen) / len(fifteen)) / price
        new_value = ml_forecast.atr_ratio_from_bars(highs, lows, closes)
        assert abs(new_value - old_value) > 1e-6, "14'lük pencere 15'likten farklı olmalı"
        assert abs(new_value - (1.0 / price)) < 1e-12

    def test_velocity_ml_feature_uses_the_canonical_atr(self):
        # ML-04: duz seride 14'luk ve 15'lik pencere ayni sonucu verir, bu
        # yuzden pencere kaymasi gorunmez olurdu. Sicramali seride ayrim
        # acikca olculur.
        closes, highs, lows, vols = _step_series()
        feats = velocity._velocity_ml_feature_dict(closes, highs, lows, vols)
        expected = ml_forecast.atr_ratio_from_bars(highs, lows, closes) * 100
        assert abs(feats["atr_pct"] - expected) < 1e-9
        fifteen = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]),
                       abs(lows[j] - closes[j - 1]))
                   for j in range(len(closes) - 15, len(closes))]
        stale = (sum(fifteen) / len(fifteen)) / closes[-1] * 100
        assert abs(feats["atr_pct"] - stale) > 1e-6, (
            "velocity ML ATR'si 15'lik pencereye kaymamali")

    def test_insufficient_history_returns_none(self):
        closes, highs, lows, _ = _series(count=10)
        assert ml_forecast.atr_ratio_from_bars(highs, lows, closes) is None


class BollingerWidthParityTests(unittest.TestCase):
    """ML-03 — Bollinger genişliği eğitimdeki ``4·std(ddof=0)/close`` olmalı."""

    def test_helper_matches_the_training_definition(self):
        closes, _, _, _ = _series()
        values = np.asarray(closes, dtype=np.float64)
        training = float(ml_forecast._rolling_std(values, 20)[-1]) * 4.0 / float(values[-1])
        assert abs(ml_forecast.bb_width_ratio_from_bars(closes) - training) < 1e-12

    def test_helper_uses_close_not_mean_as_denominator(self):
        closes = [100.0 + index * 1.5 for index in range(40)]
        values = np.asarray(closes, dtype=np.float64)
        window = values[-20:]
        mean_based = (4.0 * float(window.std())) / float(window.mean())
        close_based = ml_forecast.bb_width_ratio_from_bars(closes)
        assert abs(close_based - mean_based) > 1e-6

    def test_helper_uses_ddof_zero(self):
        closes, _, _, _ = _series()
        values = np.asarray(closes, dtype=np.float64)
        window = values[-20:]
        assert abs(ml_forecast.bb_width_ratio_from_bars(closes)
                   - (4.0 * float(window.std(ddof=0)) / float(values[-1]))) < 1e-12

    def test_velocity_ml_feature_uses_the_canonical_width(self):
        closes, highs, lows, vols = _series()
        feats = velocity._velocity_ml_feature_dict(closes, highs, lows, vols)
        expected = ml_forecast.bb_width_ratio_from_bars(closes) * 100
        assert abs(feats["bb_width_pct"] - expected) < 1e-9

    def test_screening_indicator_is_left_alone(self):
        # `_velocity_bollinger_width` KALİBRE tarama göstergesidir; ML özelliği
        # değildir. Dokunulmadığını kilitle.
        closes, _, _, _ = _series()
        expected = _bollinger(closes, 20, 2.0)["width_pct"] * 100
        assert abs(velocity._velocity_bollinger_width(closes) - expected) < 1e-9


class PredictTargetGuardTests(unittest.TestCase):
    """ML-05 — zorunlu özellikler eksikse tahmin ÜRETİLMEMELİ."""

    def _predict(self, features, symbol="TESTUSDT"):
        artifact = _fake_artifact(symbol)
        with mock.patch.object(ml_forecast, "load_model", lambda *a, **k: artifact):
            return ml_forecast.predict_target(symbol, features, 5), artifact

    def test_empty_features_are_rejected(self):
        result, _ = self._predict({})
        assert result is None

    def test_partial_features_are_rejected(self):
        result, _ = self._predict({"atr_pct": 1.0, "ret3_pct": 0.5})
        assert result is None

    def test_all_none_values_are_rejected(self):
        result, _ = self._predict({"atr_pct": None, "ret3_pct": None, "rsi": None})
        assert result is None

    def test_complete_features_still_produce_a_prediction(self):
        result, _ = self._predict({"atr_pct": 1.0, "ret3_pct": 0.5, "rsi": 55.0})
        assert result is not None
        assert result["hit_probability"] == 0.7

    def test_unknown_symbol_is_still_rejected(self):
        # Artifact YALNIZ "TESTUSDT" biliyor.
        artifact = _fake_artifact("TESTUSDT")
        with mock.patch.object(ml_forecast, "load_model", lambda *a, **k: artifact):
            result = ml_forecast.predict_target(
                "OTHERUSDT", {"atr_pct": 1.0, "ret3_pct": 0.5, "rsi": 55.0}, 5)
        assert result is None


class ModelCacheStampTests(unittest.TestCase):
    """ML-06 — diskte yenilenen artifact cache'i geçersiz kılmalı."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cache_backup = dict(ml_forecast._MODEL_CACHE)
        ml_forecast._MODEL_CACHE.update({"artifact": None, "loaded_at": 0.0, "stamp": None})
        self._patch = mock.patch.object(ml_forecast.config, "ML_MODELS_DIR", self._tmp.name)
        self._patch.start()
        self.path = os.path.join(self._tmp.name, f"upside_{ml_forecast.FEATURE_VERSION}.joblib")

    def tearDown(self):
        self._patch.stop()
        ml_forecast._MODEL_CACHE.update(self._cache_backup)
        self._tmp.cleanup()

    def _write(self, marker):
        import joblib
        artifact = _fake_artifact()
        artifact["marker"] = marker
        joblib.dump(artifact, self.path)
        # mtime'ı kesin olarak ilerlet (aynı saniyede yazım testi bozmasın).
        current = os.path.getmtime(self.path)
        os.utime(self.path, (current + 5.0, current + 5.0))

    def test_missing_file_returns_none(self):
        assert ml_forecast.load_model() is None

    def test_cache_is_reused_while_the_file_is_unchanged(self):
        self._write("first")
        first = ml_forecast.load_model()
        second = ml_forecast.load_model()
        assert first is second

    def test_rewritten_artifact_invalidates_the_cache(self):
        self._write("first")
        first = ml_forecast.load_model()
        self._write("second")
        second = ml_forecast.load_model()
        assert second is not None
        assert second is not first
        assert second["marker"] == "second"

    def test_mismatched_artifact_is_rejected_and_not_cached(self):
        import joblib
        artifact = _fake_artifact()
        artifact["feature_version"] = "v0"
        joblib.dump(artifact, self.path)
        assert ml_forecast.load_model() is None
        assert ml_forecast._MODEL_CACHE["artifact"] is None


class SymbolCodeStabilityTests(unittest.TestCase):
    """ML-07 — sembol kodları ardışık eğitimler arasında kararlı kalmalı."""

    def test_codes_are_inherited_for_known_symbols(self):
        merged = ml_forecast._merge_symbol_codes(["AAA", "BBB", "CCC"], {"AAA": 7, "CCC": 2})
        assert merged["AAA"] == 7
        assert merged["CCC"] == 2

    def test_new_symbols_are_appended_above_the_max(self):
        merged = ml_forecast._merge_symbol_codes(["AAA", "BBB", "ZZZ"], {"AAA": 7, "BBB": 9})
        assert merged["ZZZ"] == 10

    def test_no_previous_mapping_falls_back_to_input_order(self):
        # `train()` girdiyi `sorted(candles)` ile verir; yardımcı sırayı korur.
        merged = ml_forecast._merge_symbol_codes(["AAA", "BBB"], None)
        assert merged == {"AAA": 0, "BBB": 1}

    def test_train_inherits_previous_codes(self):
        """ML-07 — `train()` ÇAĞRI YERİ de devralmayi kullanmali.

        `_merge_symbol_codes`'u izole test etmek yetmiyordu: cagri yeri
        `{sym: idx for idx, sym in enumerate(symbols)}` ile degistirilse
        bile hicbir test kirilmiyordu. Bu test hem cagri yerini hem
        artifact'a yazilan eslemeyi dogrular.
        """
        previous = {"AAAUSDT": 41, "BBBUSDT": 7}
        candles = _training_candles(["AAAUSDT", "BBBUSDT"])
        calls = []
        real = ml_forecast._merge_symbol_codes

        def spy(symbols, prev):
            calls.append((list(symbols), prev))
            return real(symbols, prev)

        captured = {}
        with tempfile.TemporaryDirectory() as tmp:
            import sklearn.ensemble as sk_ensemble
            with mock.patch.object(ml_forecast, "_merge_symbol_codes",
                                   side_effect=spy), \
                 mock.patch.object(ml_forecast.config, "ML_MODELS_DIR", tmp), \
                 mock.patch.object(sk_ensemble, "HistGradientBoostingRegressor",
                                   _StubEstimator), \
                 mock.patch.object(sk_ensemble, "HistGradientBoostingClassifier",
                                   _StubEstimator), \
                 mock.patch.object(joblib, "dump",
                                   lambda obj, path, **kw: captured.update(obj)):
                ml_forecast.train(candles, [], previous)

        assert calls, "train() _merge_symbol_codes'u cagirmali"
        assert calls[0][0] == ["AAAUSDT", "BBBUSDT"]
        assert calls[0][1] is previous
        assert captured["symbol_codes"] == {"AAAUSDT": 41, "BBBUSDT": 7}, (
            "sembol kodlari onceki artifact'tan devralinmali")

    def test_codes_are_unique(self):
        merged = ml_forecast._merge_symbol_codes(["A", "B", "C", "D"], {"A": 3})
        assert len(set(merged.values())) == len(merged)

    def test_dropped_symbols_do_not_shift_the_rest(self):
        first = ml_forecast._merge_symbol_codes(["AAA", "BBB", "CCC"], None)
        second = ml_forecast._merge_symbol_codes(["AAA", "CCC"], first)
        assert second["AAA"] == first["AAA"]
        assert second["CCC"] == first["CCC"]


class DeadFeatureFillTests(unittest.TestCase):
    """ML-08 — `ret1_pct` / `ret5_pct` / `vol_z` artık gerçekten doldurulmalı."""

    def test_velocity_features_fill_the_three_dead_columns(self):
        closes, highs, lows, vols = _series()
        feats = velocity._velocity_ml_feature_dict(closes, highs, lows, vols)
        assert feats["ret1_pct"] is not None
        assert feats["ret5_pct"] is not None
        assert feats["vol_z"] is not None

    def test_ret1_and_ret5_use_the_right_offsets(self):
        closes, highs, lows, vols = _series()
        feats = velocity._velocity_ml_feature_dict(closes, highs, lows, vols)
        assert abs(feats["ret1_pct"] - (closes[-1] / closes[-2] - 1) * 100) < 1e-9
        assert abs(feats["ret5_pct"] - (closes[-1] / closes[-6] - 1) * 100) < 1e-9

    def test_volume_z_matches_the_training_definition(self):
        closes, highs, lows, vols = _series()
        window = [float(value) for value in vols[-20:]]
        mean = sum(window) / 20
        std = math.sqrt(sum((value - mean) ** 2 for value in window) / 20)
        expected = (float(vols[-1]) - mean) / std
        assert abs(velocity._velocity_volume_z(vols) - expected) < 1e-12

    def test_volume_z_is_none_for_flat_volume(self):
        assert velocity._velocity_volume_z([5.0] * 25) is None

    def test_volume_z_is_none_for_short_history(self):
        assert velocity._velocity_volume_z([1.0, 2.0]) is None

    def test_predict_target_forwards_vol_z(self):
        artifact = _fake_artifact()
        stub = artifact["horizons"]["5"]["reg"]
        features = {"atr_pct": 1.0, "ret3_pct": 0.5, "rsi": 55.0, "vol_z": 2.5}
        with mock.patch.object(ml_forecast, "load_model", lambda *a, **k: artifact):
            ml_forecast.predict_target("TESTUSDT", features, 5)
        assert stub.last is not None
        assert abs(float(stub.last[0][7]) - 2.5) < 1e-5

    def test_predict_target_does_not_invent_zero_atr(self):
        artifact = _fake_artifact()
        stub = artifact["horizons"]["5"]["reg"]
        # atr_pct var ama 0 -> kapı geçer; değer 0.0 olarak yazılır (uydurma yok).
        features = {"atr_pct": 0.0, "ret3_pct": 0.5, "rsi": 55.0}
        with mock.patch.object(ml_forecast, "load_model", lambda *a, **k: artifact):
            ml_forecast.predict_target("TESTUSDT", features, 5)
        assert abs(float(stub.last[0][3]) - 0.0) < 1e-9

    def test_journal_samples_carry_vol_z(self):
        rows = [{
            "direction": "up", "symbol": "TESTUSDT", "horizon_minutes": 5,
            "max_favorable_pct": 2.5, "timestamp": 1_700_000_000.0,
            "snapshot": {"atr_pct": 1.0, "ret3_pct": 0.5, "rsi": 55.0, "vol_z": 1.75},
        }]
        X, _, _, _, _, _ = ml_forecast.prepare_journal_samples(rows, {"TESTUSDT": 0})
        assert X.shape[0] == 1
        assert abs(float(X[0][7]) - 1.75) < 1e-5

    def test_chart_forecast_forwards_every_feature(self):
        from app.routers import chart_forecast

        artifact = _fake_artifact()
        stub = artifact["horizons"]["5"]["reg"]
        features = {"atr_pct": 1.0, "ret3_pct": 0.5, "rsi": 55.0, "vol_z": 3.25,
                    "ret1_pct": 0.1, "ret5_pct": 0.9}
        with mock.patch.object(ml_forecast, "load_model", lambda *a, **k: artifact):
            chart_forecast._run_predict("TESTUSDT", features, 5)
        assert stub.last is not None
        assert abs(float(stub.last[0][7]) - 3.25) < 1e-5
        assert abs(float(stub.last[0][0]) - 0.001) < 1e-6


class FeatureNameLayoutTests(unittest.TestCase):
    """Özellik sırası sözleşmesi — indeks tabanlı testlerin temeli."""

    def test_vol_z_is_at_index_seven(self):
        assert ml_forecast.FEATURE_NAMES[7] == "vol_z"

    def test_ret_columns_are_at_the_expected_offsets(self):
        assert ml_forecast.FEATURE_NAMES[0] == "ret1_pct"
        assert ml_forecast.FEATURE_NAMES[1] == "ret3_pct"
        assert ml_forecast.FEATURE_NAMES[2] == "ret5_pct"
