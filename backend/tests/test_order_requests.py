"""Idempotent emir kaydı: client_order_id doğrulama + DB fonksiyonları (sahte bağlantı)."""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from app import database
from app.order_requests import DONE, FAILED, IN_PROGRESS, UNKNOWN, validate_client_order_id


@pytest.mark.parametrize("cid", ["abc12345", "sc-1234_ABCD", "a" * 64])
def test_valid_ids(cid):
    assert validate_client_order_id(cid) == cid


@pytest.mark.parametrize("cid", ["", None, "short", "a" * 65, "boşluk var 123", "tür§kçe123", "a;b;c;d;e;f"])
def test_invalid_ids(cid):
    with pytest.raises(ValueError):
        validate_client_order_id(cid)


def test_status_constants_are_distinct():
    assert len({IN_PROGRESS, DONE, FAILED, UNKNOWN}) == 4


class _Conn:
    def __init__(self, rowcount=1, row=None):
        self.rowcount, self.row, self.calls = rowcount, row, []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return MagicMock(rowcount=self.rowcount, fetchone=lambda: self.row)

    def commit(self):
        pass


def _run(monkeypatch, conn, fn):
    async def fake(op):
        return op(conn)
    monkeypatch.setattr(database, "_run_db", fake)
    return asyncio.run(fn())


def test_claim_true_for_first_caller(monkeypatch):
    conn = _Conn(rowcount=1)
    assert _run(monkeypatch, conn, lambda: database.claim_order_request(7, "cid-12345", "BTC_TRY", {"a": 1})) is True
    sql, params = conn.calls[0]
    assert "ON CONFLICT (user_id, client_order_id) DO NOTHING" in sql
    assert sql.count("%s") == len(params)
    assert params[0] == 7 and params[1] == "cid-12345"


def test_claim_false_when_already_exists(monkeypatch):
    assert _run(monkeypatch, _Conn(rowcount=0), lambda: database.claim_order_request(7, "cid-12345", "BTC_TRY", {})) is False


def test_finish_updates_status_and_result(monkeypatch):
    conn = _Conn()
    _run(monkeypatch, conn, lambda: database.finish_order_request(7, "cid-12345", DONE, {"order_id": "9"}))
    sql, params = conn.calls[0]
    assert "UPDATE order_requests" in sql and sql.count("%s") == len(params)
    assert DONE in params and json.loads([p for p in params if isinstance(p, str) and p.startswith("{")][0]) == {"order_id": "9"}


def test_get_returns_dict_or_none(monkeypatch):
    assert _run(monkeypatch, _Conn(row=None), lambda: database.get_order_request(7, "cid-12345")) is None
    row = (DONE, "BTC_TRY", {"order_id": "9"}, 100.0)
    out = _run(monkeypatch, _Conn(row=row), lambda: database.get_order_request(7, "cid-12345"))
    assert out == {"status": DONE, "symbol": "BTC_TRY", "result": {"order_id": "9"}, "created_at": 100.0}


def test_get_parses_json_string_result(monkeypatch):
    row = (UNKNOWN, "BTC_TRY", '{"x": 1}', 100.0)
    assert _run(monkeypatch, _Conn(row=row), lambda: database.get_order_request(7, "cid-12345"))["result"] == {"x": 1}
