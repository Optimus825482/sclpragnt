"""Testler: scripts/radar_lift_analysis.py (sinyal ailesi kaldıraç analizi)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.radar_lift_analysis import (
    compute_family_lift,
    main,
    precision_at_k,
    spearman_score_mfe,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")


def _synthetic_rows() -> list[dict]:
    """200 satır, 4 hücre (velocity x pulse), her biri 50 satır.

    hit oranları:  (v=1,p=1) 0.6   (v=1,p=0) 0.6   (v=0,p=1) 0.2   (v=0,p=0) 0.2
    -> velocity: VAR 0.6, YOK 0.2  => lift 3.0 (gerçek kaldıraç)
    -> pulse:    VAR 0.4, YOK 0.4  => lift 1.0 (ayırt edici değil)
    """
    cells = [
        (True, True, 30, '["velocity","pulse"]'),
        (True, False, 30, '["velocity"]'),
        (False, True, 10, '["pulse"]'),
        (False, False, 10, "[]"),
    ]
    rows: list[dict] = []
    base = datetime(2026, 10, 10, 12, 0, tzinfo=ISTANBUL).timestamp()
    idx = 0
    for _v, _p, hit_count, sources in cells:
        for j in range(50):
            score = 60.0 + (idx % 40)  # 60..99 arası, bantlara dağılır
            rows.append({
                "symbol": f"SYM{idx}",
                "sources": sources,
                "scan_score": score,
                "mfe_pct": score / 10.0,
                "hit": j < hit_count,
                "detected_at": base + (idx % 4) * 86400.0,
            })
            idx += 1
    return rows


def test_compute_family_lift_finds_real_lift_and_neutral_family():
    rows = _synthetic_rows()
    fams = {f["family"]: f for f in compute_family_lift(rows, min_n=30)}

    velocity = fams["velocity"]
    assert velocity["kind"] == "source"
    assert velocity["n_with"] == 100 and velocity["n_without"] == 100
    assert velocity["lift"] is not None and velocity["lift"] > 1.0
    assert abs(velocity["lift"] - 3.0) < 1e-9
    assert velocity["ci_low"] <= velocity["hit_rate_with"] <= velocity["ci_high"]

    pulse = fams["pulse"]
    assert pulse["lift"] is not None
    assert abs(pulse["lift"] - 1.0) < 0.05


def test_compute_family_lift_includes_score_buckets_and_sorts():
    rows = _synthetic_rows()
    results = compute_family_lift(rows, min_n=30)
    names = [r["family"] for r in results]
    for bucket in ("score<70", "70-85", "85-95", "95-100"):
        assert bucket in names
    lifts = [r["lift"] for r in results if r["lift"] is not None]
    assert lifts == sorted(lifts, reverse=True)


def test_min_n_and_zero_without_give_none_lift():
    rows = _synthetic_rows()
    fams = {f["family"]: f for f in compute_family_lift(rows, min_n=500)}
    assert fams["velocity"]["lift"] is None

    # YOK grubunda hiç hit yok (hit oranı 0) -> payda 0, lift None olmalı.
    zero_without = [{"sources": '["x"]', "scan_score": 80.0, "hit": True}] * 40
    zero_without += [{"sources": "[]", "scan_score": 80.0, "hit": False}] * 40
    fams = {f["family"]: f for f in compute_family_lift(zero_without, min_n=30)}
    assert fams["x"]["hit_rate_without"] == 0.0
    assert fams["x"]["lift"] is None

    # YOK grubu pozitif hit oranına sahipse lift sayısal olmalı.
    positive = [{"sources": '["x"]', "scan_score": 80.0, "hit": True}] * 40
    positive += [{"sources": "[]", "scan_score": 80.0, "hit": i < 10} for i in range(40)]
    fams = {f["family"]: f for f in compute_family_lift(positive, min_n=30)}
    assert fams["x"]["lift"] == pytest.approx(1.0 / 0.25)


def test_bad_json_and_null_hit_rows_are_skipped():
    rows = _synthetic_rows()
    rows.append({"sources": "{bad json", "scan_score": 90.0, "hit": True})
    rows.append({"sources": '["velocity"]', "scan_score": 90.0, "hit": None})
    fams = {f["family"]: f for f in compute_family_lift(rows, min_n=30)}
    assert fams["velocity"]["n_with"] == 100
    assert fams["velocity"]["n_without"] == 100


def test_precision_at_k_values_in_unit_interval():
    rows = _synthetic_rows()
    values = precision_at_k(rows, k_values=(5, 10, 20))
    assert set(values) == {5, 10, 20}
    for v in values.values():
        assert v is not None
        assert 0.0 <= v <= 1.0


def test_precision_at_k_top_selection_by_day():
    base = datetime(2026, 10, 10, 12, 0, tzinfo=ISTANBUL).timestamp()
    rows = [{"scan_score": float(s), "hit": s >= 5, "detected_at": base}
            for s in range(10)]
    values = precision_at_k(rows, k_values=(5, 10))
    assert values[5] == pytest.approx(1.0)   # en yüksek 5 skorun hepsi hit
    assert values[10] == pytest.approx(0.5)  # 10 adayda hit oranı 5/10


def test_spearman_perfect_order_and_reverse():
    rows = [{"scan_score": float(s), "mfe_pct": float(2 * s), "hit": True}
            for s in range(1, 51)]
    assert spearman_score_mfe(rows) == pytest.approx(1.0, abs=1e-9)

    reversed_rows = [{"scan_score": float(s), "mfe_pct": float(-s), "hit": False}
                     for s in range(1, 51)]
    assert spearman_score_mfe(reversed_rows) == pytest.approx(-1.0, abs=1e-9)


def test_spearman_none_for_too_few_or_constant():
    assert spearman_score_mfe([{"scan_score": 1.0, "mfe_pct": 1.0, "hit": True}]) is None
    constant = [{"scan_score": 5.0, "mfe_pct": float(i), "hit": True} for i in range(10)]
    assert spearman_score_mfe(constant) is None


def test_module_imports_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import importlib

    module = importlib.import_module("scripts.radar_lift_analysis")
    assert callable(module.main)


def test_csv_input_path_produces_report(tmp_path, capsys):
    rows = _synthetic_rows()
    csv_path = tmp_path / "outcomes.csv"
    import csv as _csv

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "hit": "True" if row["hit"] else "False"})

    code = main(["--csv", str(csv_path), "--min-n", "30"])
    out = capsys.readouterr().out
    assert code == 0
    assert "KARAR: lift<1.0 olan aileler:" in out
    assert "| velocity |" in out


def test_missing_csv_gives_turkish_error_not_traceback(tmp_path, capsys):
    code = main(["--csv", str(tmp_path / "yok.csv")])
    captured = capsys.readouterr()
    assert code == 1
    assert "bulunamadı" in captured.err
    assert "Traceback" not in captured.err


def test_cli_missing_csv_subprocess_exits_cleanly(tmp_path):
    import os

    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.radar_lift_analysis",
         "--csv", str(tmp_path / "yok.csv")],
        capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=str(_backend_dir()), timeout=60,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "bulunamadı" in proc.stderr


def _backend_dir():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent
