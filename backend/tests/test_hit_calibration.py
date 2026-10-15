"""Testler: app/hit_calibration.py (izotonik p_hit kalibrasyonu)."""
from __future__ import annotations

import json

import numpy as np
from sklearn.isotonic import IsotonicRegression

from app.hit_calibration import (
    MIN_FIT_ROWS,
    HitCalibrator,
    fit_from_rows,
    reliability_table,
)


def _synthetic(n: int = 400, seed: int = 0):
    """Skor 0..100 arası; isabet olasılığı skorla birlikte artar (p = skor/100)."""
    rng = np.random.default_rng(seed)
    scores = rng.uniform(0.0, 100.0, size=n)
    hits = rng.uniform(0.0, 1.0, size=n) < (scores / 100.0)
    return [float(s) for s in scores], [bool(h) for h in hits]


def test_predictions_are_monotonic_and_follow_score():
    scores, hits = _synthetic()
    cal = HitCalibrator().fit(scores, hits)

    assert cal.ready is True
    assert cal.n == len(scores)

    grid = np.linspace(0.0, 100.0, 201)
    preds = np.asarray([cal.predict(float(g)) for g in grid])
    assert np.all(np.diff(preds) >= -1e-12), "p_hit skorla birlikte azalmamalı"
    assert np.all((preds >= 0.0) & (preds <= 1.0))
    assert cal.predict(90.0) > cal.predict(10.0)


def test_matches_sklearn_isotonic_predictions():
    scores, hits = _synthetic(n=300, seed=3)
    cal = HitCalibrator().fit(scores, hits)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(
        np.asarray(scores), np.asarray(hits, dtype=float))

    probe = np.linspace(-5.0, 105.0, 37)
    ours = np.asarray([cal.predict(float(p)) for p in probe])
    theirs = iso.predict(probe)
    assert np.allclose(ours, theirs, atol=1e-9)


def test_not_ready_below_min_fit_rows():
    assert MIN_FIT_ROWS == 50
    scores, hits = _synthetic(n=MIN_FIT_ROWS - 1, seed=1)
    cal = HitCalibrator().fit(scores, hits)
    assert cal.ready is False
    assert cal.predict(80.0) is None

    scores, hits = _synthetic(n=MIN_FIT_ROWS, seed=1)
    assert HitCalibrator().fit(scores, hits).ready is True


def test_none_and_nonfinite_inputs_are_dropped():
    scores, hits = _synthetic(n=60, seed=2)
    scores = scores + [None, float("nan")]
    hits = hits + [True, False]
    cal = HitCalibrator().fit(scores, hits)
    assert cal.n == 60
    assert cal.predict(None) is None
    assert cal.predict(float("nan")) is None


def test_to_dict_from_dict_round_trip_same_predictions():
    scores, hits = _synthetic(seed=4)
    cal = HitCalibrator().fit(scores, hits)

    restored = HitCalibrator.from_dict(json.loads(json.dumps(cal.to_dict())))
    assert restored.ready is True
    assert restored.n == cal.n

    for probe in np.linspace(-10.0, 110.0, 121):
        a = cal.predict(float(probe))
        b = restored.predict(float(probe))
        assert abs(a - b) <= 1e-6


def test_round_trip_not_ready_stays_none():
    cal = HitCalibrator().fit([1.0, 2.0], [True, False])
    restored = HitCalibrator.from_dict(json.loads(json.dumps(cal.to_dict())))
    assert restored.ready is False
    assert restored.predict(1.5) is None


def test_reliability_table_bins_sum_to_n():
    scores, hits = _synthetic(n=250, seed=5)
    table = reliability_table(scores, hits, bins=10)

    assert len(table) == 10
    assert sum(row["n"] for row in table) == len(scores)
    for row in table:
        assert set(row) >= {"bin", "n", "mean_score", "observed_rate", "predicted_rate"}
        assert 0.0 <= row["observed_rate"] <= 1.0
        assert 0.0 <= row["predicted_rate"] <= 1.0


def test_reliability_table_predicted_none_when_not_ready():
    table = reliability_table([10.0, 20.0, 30.0], [True, False, True], bins=2)
    assert sum(row["n"] for row in table) == 3
    assert all(row["predicted_rate"] is None for row in table)


def test_fit_from_rows_uses_db_style_rows():
    scores, hits = _synthetic(n=80, seed=6)
    rows = [{"scan_score": s, "hit": h} for s, h in zip(scores, hits)]
    rows += [{"scan_score": None, "hit": True}, {"scan_score": 50.0, "hit": None}]

    cal = fit_from_rows(rows)
    assert cal.n == 80
    assert cal.ready is True
    assert cal.predict(90.0) > cal.predict(10.0)
