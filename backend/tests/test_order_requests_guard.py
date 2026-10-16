"""Basit al/sat uçları için idempotent koruma (begin/complete/fail). Sahte DB."""
import asyncio

import pytest

from app import database, order_requests as orq


class FakeDB:
    def __init__(self):
        self.rows = {}

    async def claim(self, uid, cid, symbol, request):
        if (uid, cid) in self.rows:
            return False
        self.rows[(uid, cid)] = {"status": "in_progress", "result": {}}
        return True

    async def finish(self, uid, cid, status, result):
        self.rows[(uid, cid)].update(status=status, result=result)

    async def get(self, uid, cid):
        return self.rows.get((uid, cid))


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setattr(database, "claim_order_request", d.claim)
    monkeypatch.setattr(database, "finish_order_request", d.finish)
    monkeypatch.setattr(database, "get_order_request", d.get)
    return d


def run(c):
    return asyncio.run(c)


def test_no_id_means_no_guard(db):
    assert run(orq.begin(1, None, "ADA_TRY", {})) is None
    assert run(orq.begin(1, "", "ADA_TRY", {})) is None
    assert db.rows == {}


def test_first_call_owns_second_replays(db):
    assert run(orq.begin(1, "web-12345678", "ADA_TRY", {})) == "web-12345678"
    with pytest.raises(orq.Replay) as e:
        run(orq.begin(1, "web-12345678", "ADA_TRY", {}))
    assert e.value.status == orq.IN_PROGRESS and e.value.stored is None


def test_replay_after_done_returns_stored_result(db):
    cid = run(orq.begin(1, "web-12345678", "ADA_TRY", {}))
    run(orq.complete(1, cid, {"order_id": "5"}))
    with pytest.raises(orq.Replay) as e:
        run(orq.begin(1, "web-12345678", "ADA_TRY", {}))
    assert e.value.status == orq.DONE and e.value.stored == {"order_id": "5"}


def test_failed_and_unknown_are_recorded_and_block_reuse(db):
    cid = run(orq.begin(1, "web-aaaaaaaa", "X", {}))
    run(orq.fail(1, cid, "boom", ambiguous=False))
    assert db.rows[(1, cid)]["status"] == orq.FAILED
    cid2 = run(orq.begin(1, "web-bbbbbbbb", "X", {}))
    run(orq.fail(1, cid2, "timeout", ambiguous=True))
    assert db.rows[(1, cid2)]["status"] == orq.UNKNOWN
    with pytest.raises(orq.Replay) as e:
        run(orq.begin(1, "web-bbbbbbbb", "X", {}))
    assert e.value.status == orq.UNKNOWN


def test_users_are_isolated(db):
    run(orq.begin(1, "web-12345678", "X", {}))
    assert run(orq.begin(2, "web-12345678", "X", {})) == "web-12345678"


def test_invalid_id_rejected(db):
    with pytest.raises(ValueError):
        run(orq.begin(1, "kisa", "X", {}))


def test_complete_and_fail_without_id_are_noops(db):
    run(orq.complete(1, None, {}))
    run(orq.fail(1, None, "x", False))
    assert db.rows == {}
