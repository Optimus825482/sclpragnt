"""Risk Merkezi ayarları: doğrulama (saf) ve DB fonksiyonları (sahte bağlantı)."""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from app import database
from app.risk_settings import DEFAULTS, validate


def test_defaults():
    assert DEFAULTS == {"max_position_pct": 20.0, "default_rr": 2.0}


@pytest.mark.parametrize("payload,expected", [
    ({"max_position_pct": 35}, {"max_position_pct": 35.0}),
    ({"default_rr": 3}, {"default_rr": 3.0}),
    ({"max_position_pct": "12,5", "default_rr": "1.5"}, {"max_position_pct": 12.5, "default_rr": 1.5}),
    ({"max_position_pct": 100, "default_rr": 5}, {"max_position_pct": 100.0, "default_rr": 5.0}),
    ({}, {}),
])
def test_validate_accepts(payload, expected):
    assert validate(payload) == expected


@pytest.mark.parametrize("payload", [
    {"max_position_pct": 0}, {"max_position_pct": 101}, {"max_position_pct": -5},
    {"default_rr": 0.9}, {"default_rr": 5.1},
    {"max_position_pct": "abc"}, {"max_position_pct": None},
    {"max_position_pct": float("nan")}, {"default_rr": float("inf")},
])
def test_validate_rejects(payload):
    with pytest.raises(ValueError):
        validate(payload)


def test_validate_ignores_unknown_keys():
    assert validate({"max_position_pct": 10, "x": 1}) == {"max_position_pct": 10.0}


class _Conn:
    def __init__(self, row=None):
        self.row, self.calls = row, []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return MagicMock(fetchone=lambda: self.row)

    def commit(self):
        pass


def _run(monkeypatch, conn, coro_fn):
    async def fake(op):
        return op(conn)
    monkeypatch.setattr(database, "_run_db", fake)
    return asyncio.run(coro_fn())


def test_get_returns_defaults_when_no_row(monkeypatch):
    out = _run(monkeypatch, _Conn(None), lambda: database.get_user_risk_settings(7))
    assert out == DEFAULTS


def test_get_returns_saved_row(monkeypatch):
    out = _run(monkeypatch, _Conn((35.0, 3.0)), lambda: database.get_user_risk_settings(7))
    assert out == {"max_position_pct": 35.0, "default_rr": 3.0}


def test_set_merges_with_existing_and_upserts(monkeypatch):
    conn = _Conn((35.0, 3.0))
    out = _run(monkeypatch, conn, lambda: database.set_user_risk_settings(7, {"default_rr": 1.5}))
    assert out == {"max_position_pct": 35.0, "default_rr": 1.5}      # eksik alan mevcut değeri korur
    upsert = [c for c in conn.calls if "INSERT INTO user_risk_settings" in c[0]][0]
    assert upsert[0].count("%s") == len(upsert[1])
    assert upsert[1][0] == 7
