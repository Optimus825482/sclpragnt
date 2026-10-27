"""Defterden maksimum güvenli tutar (trade_size) testleri. DB gerektirmez."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SCALPER_ENV", "development")

from app import trade_size  # noqa: E402

ASKS = [(6.000, 342.8), (6.001, 1175.7), (6.004, 3211.5), (6.005, 4488.0)]
BIDS = [(5.992, 3696.8), (5.991, 500.0), (5.989, 2521.1)]


def test_sweep_avg_slip():
    r = trade_size.sweep(ASKS, 10_000)
    assert r["last_price"] == 6.004
    assert 0 < r["avg_slip_pct"] < 0.07


def test_volume_limit_binds():
    r = trade_size.max_safe_amount(ASKS, BIDS, quote_volume_try=500_000)
    assert r["binding"] == "volume" and r["amount_try"] == pytest.approx(10_000)


def test_exit_limit_uses_haircut():
    bids_try = sum(p * q for p, q in BIDS)
    r = trade_size.max_safe_amount(ASKS, BIDS, quote_volume_try=1e12)
    assert r["limits"]["exit"] == pytest.approx(bids_try * 0.4)
    assert r["binding"] == "exit"
    assert r["exit_slip_pct"] >= 0


def test_empty_book_is_zero():
    r = trade_size.max_safe_amount([], [], quote_volume_try=0)
    assert r["amount_try"] == 0
    assert r["entry_slip_pct"] == 0 and r["exit_slip_pct"] == 0


def test_gross_target():
    assert trade_size.gross_target_pct(3.0, 0.1, 0.2, 0.001125) == pytest.approx(3.525)


def test_parse_levels_strings():
    assert trade_size.parse_levels([["6.0", "1.5"]]) == [(6.0, 1.5)]


def test_entry_limit_partial_level_respects_threshold():
    asks = [(100.0, 10.0), (101.0, 1000.0)]
    r = trade_size.max_safe_amount(asks, [(100.0, 1e6)], 1e12, max_avg_slip_pct=0.2)
    amt = r["limits"]["entry"]
    assert 1000 < amt < 1000 + 101_000
    assert trade_size.sweep(asks, amt)["avg_slip_pct"] == pytest.approx(0.2, abs=1e-6)
