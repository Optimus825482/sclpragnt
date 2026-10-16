"""API anahtarı kayıt öncesi doğrulama ve alım push'unun arka plana alınması."""
import asyncio

import pytest
from fastapi import HTTPException

from app import main


def test_verify_rejects_bad_keys_without_leaking_secret(monkeypatch):
    def boom(k, s, force=False):
        raise RuntimeError("401 SUPERSECRET")
    monkeypatch.setattr(main, "get_account_balance", boom)
    with pytest.raises(HTTPException) as e:
        asyncio.run(main._verify_binance_keys("key", "SUPERSECRET"))
    assert e.value.status_code == 422 and "SUPERSECRET" not in e.value.detail


def test_verify_accepts_working_keys(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_account_balance", lambda k, s, force=False: calls.append(force) or [])
    asyncio.run(main._verify_binance_keys("key", "secret"))
    assert calls == [True]


def test_trade_push_failure_is_swallowed(monkeypatch):
    async def bad(*a, **k):
        raise RuntimeError("push down")
    monkeypatch.setattr(main.database, "get_llm_setting", bad)
    asyncio.run(main._send_admin_trade_push("ali", "ADA_TRY", {"avg_price": "1"}))


def test_spawn_background_runs_and_cleans_up():
    done = []

    async def go():
        async def work():
            done.append(1)
        main._spawn_background(work())
        await asyncio.sleep(0.05)
        return len(main._BACKGROUND_TASKS)
    assert asyncio.run(go()) == 0 and done == [1]
