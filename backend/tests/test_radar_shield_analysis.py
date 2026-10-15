"""Testler: BTC rejim kalkanı ölçümü — günlüğe `blocked_by` yazımı ve scripts/radar_shield_analysis.py.

ÖN KAYITLI KARAR KURALI (veri görülmeden sabitlendi; bkz. docs/DENEY_KAYDI.md):
  her iki grupta n >= min_n iken
    hit(kalkan) >= hit(geçen) - 5 puan   -> KALKAN_FAZLA_SIKI  (yumuşatma adayı)
    hit(kalkan) <  hit(geçen) - 10 puan  -> KALKAN_ISE_YARIYOR (olduğu gibi bırak)
    aksi                                  -> BELIRSIZ
  yetersiz n -> YETERSIZ_VERI
"""
from __future__ import annotations

import csv
import io

import pytest

from app.unified_outcomes import _candidate_row
from scripts.radar_shield_analysis import (
    classify_block,
    compute_shield_report,
    main,
    verdict,
)


# ---------------------------------------------------------------- günlüğe yazım

def _scan_row(**kw):
    base = {"symbol": "PLUMETRY", "price": 1.04, "horizon_minutes": 5,
            "unified_sources": ["velocity"], "scan_score": 85.8, "detected_at": 1_000.0}
    base.update(kw)
    return base


def test_candidate_row_keeps_block_reason():
    row = _candidate_row(_scan_row(blocked_by="BTC_BEAR_REGIME_SHIELD"))
    assert row["blocked_by"] == "BTC_BEAR_REGIME_SHIELD"


def test_candidate_row_unblocked_is_empty_string_not_null():
    # '' = "geçti" (biliniyor); NULL = eski satır (kayıt öncesi). Analiz yalnız '' ve dolu olanı kullanır.
    assert _candidate_row(_scan_row(blocked_by=None))["blocked_by"] == ""
    assert _candidate_row(_scan_row())["blocked_by"] == ""


def test_candidate_row_truncates_long_reason():
    row = _candidate_row(_scan_row(blocked_by="x" * 500))
    assert len(row["blocked_by"]) <= 80


# ---------------------------------------------------------------- sınıflandırma

@pytest.mark.parametrize("raw,expected", [
    ("BTC_BEAR_REGIME_SHIELD", "shield"),
    ("master_surge_katman1:LAYER1_LIQUIDITY", "layer1"),
    ("BTC_PANIC_DOWNTREND", "other_gate"),
    ("asiri_spread:0.60%>0.52%_siniri", "other_gate"),
    ("", "passed"),
    (None, "legacy"),
])
def test_classify_block(raw, expected):
    assert classify_block(raw) == expected


# ---------------------------------------------------------------- rapor matematiği

def _rows(n_hit: int, n_total: int, blocked: str, mfe: float = 2.0, horizon: int = 5):
    out = []
    for i in range(n_total):
        out.append({"blocked_by": blocked, "hit": i < n_hit, "mfe_pct": mfe if i < n_hit else 0.1,
                    "mae_pct": -0.5, "horizon_minutes": horizon, "detected_at": 1_000.0 + i})
    return out


def test_report_groups_and_hit_rates():
    rows = _rows(30, 100, "") + _rows(45, 100, "BTC_BEAR_REGIME_SHIELD")
    rep = compute_shield_report(rows, min_n=30)
    assert rep["passed"]["n"] == 100 and rep["passed"]["hits"] == 30
    assert rep["shield"]["n"] == 100 and rep["shield"]["hits"] == 45
    assert rep["shield"]["hit_rate"] == pytest.approx(0.45)
    lo, hi = rep["shield"]["ci"]
    assert lo < 0.45 < hi


def test_legacy_rows_are_excluded():
    rows = _rows(10, 40, None) + _rows(5, 40, "")
    rep = compute_shield_report(rows, min_n=30)
    assert rep["legacy_excluded"] == 40
    assert rep["passed"]["n"] == 40


def test_unmeasured_rows_are_skipped():
    rows = _rows(10, 40, "") + [{"blocked_by": "", "hit": None, "mfe_pct": None, "mae_pct": None,
                                 "horizon_minutes": 5, "detected_at": 9.0}]
    assert compute_shield_report(rows, min_n=30)["passed"]["n"] == 40


# ---------------------------------------------------------------- ön kayıtlı karar

def test_verdict_shield_too_tight():
    rep = compute_shield_report(_rows(30, 100, "") + _rows(28, 100, "BTC_BEAR_REGIME_SHIELD"), min_n=30)
    assert verdict(rep, min_n=30) == "KALKAN_FAZLA_SIKI"        # 28 >= 30 - 5


def test_verdict_shield_working():
    rep = compute_shield_report(_rows(40, 100, "") + _rows(10, 100, "BTC_BEAR_REGIME_SHIELD"), min_n=30)
    assert verdict(rep, min_n=30) == "KALKAN_ISE_YARIYOR"       # 10 < 40 - 10


def test_verdict_uncertain_between_thresholds():
    rep = compute_shield_report(_rows(40, 100, "") + _rows(32, 100, "BTC_BEAR_REGIME_SHIELD"), min_n=30)
    assert verdict(rep, min_n=30) == "BELIRSIZ"                 # 40-10 <= 32 < 40-5


def test_verdict_insufficient_data():
    rep = compute_shield_report(_rows(30, 100, "") + _rows(2, 5, "BTC_BEAR_REGIME_SHIELD"), min_n=30)
    assert verdict(rep, min_n=30) == "YETERSIZ_VERI"


# ---------------------------------------------------------------- CLI

def test_main_csv_prints_report(tmp_path, capsys):
    rows = _rows(30, 100, "") + _rows(45, 100, "BTC_BEAR_REGIME_SHIELD")
    path = tmp_path / "j.csv"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")
    assert main(["--csv", str(path), "--min-n", "30"]) == 0
    out = capsys.readouterr().out
    assert "KALKAN_FAZLA_SIKI" in out and "shield" in out.lower()


# ---------------------------------------------------------------- DB yazımı (sahte bağlantı)

def test_save_unified_candidates_writes_blocked_by_and_placeholders_match(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    from app import database

    captured = {}

    class _Conn:
        def execute(self, sql, params=()):
            captured["sql"], captured["params"] = sql, params
            return MagicMock(rowcount=1)

        def commit(self):
            pass

    async def _fake_run_db(op):
        return op(_Conn())

    monkeypatch.setattr(database, "_run_db", _fake_run_db)
    row = {"symbol": "PLUMETRY", "horizon_minutes": 5, "sources": '["velocity"]', "scan_score": 85.8,
           "entry_price": 1.04, "ceiling_pct": 3.8, "target_pct": 1.5, "detected_at": 1000.0,
           "blocked_by": "BTC_BEAR_REGIME_SHIELD"}
    assert asyncio.run(database.save_unified_candidates([row])) == 1
    sql, params = captured["sql"], captured["params"]
    assert "blocked_by" in sql
    assert sql.count("?") == len(params)          # kayan parametre = çalışma zamanında sessiz hata
    assert "BTC_BEAR_REGIME_SHIELD" in params
