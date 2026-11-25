"""CMC anahtar saklama, maskeleme ve kota sayacı testleri.

Kural: anahtar hiçbir yanıtta/hatada tam görünmez, düz metin saklanmaz.
"""
import asyncio
import json

import pytest
from cryptography.fernet import Fernet

from app import cmc_client


@pytest.fixture()
def store(monkeypatch):
    """llm_settings'i bellek içi sözlüğe çevirir + şifreleme anahtarı verir."""
    monkeypatch.setenv("LLM_ENCRYPTION_KEY", Fernet.generate_key().decode())
    data: dict[str, str] = {}

    async def fake_get(key, default=None):
        return data.get(key, default)

    async def fake_set(key, value):
        data[key] = str(value)

    monkeypatch.setattr(cmc_client.database, "get_llm_setting", fake_get)
    monkeypatch.setattr(cmc_client.database, "set_llm_setting", fake_set)
    cmc_client._KEY_INFO_CACHE = None
    cmc_client._BRIEF_CACHE = None
    return data


def test_mask_keeps_only_edges():
    assert cmc_client.mask_key("abcdef1234567890xyz") == "abcd…0xyz"
    assert cmc_client.mask_key("short") == "*****"
    assert cmc_client.mask_key("") == ""


def test_save_encrypts_and_returns_masked(store):
    key = "0123456789abcdef0123456789abcdef"
    asyncio.run(cmc_client.save_api_key(key))

    stored = store[cmc_client.SETTINGS_KEY]
    assert key not in stored, "anahtar düz metin saklanmamalı"
    assert asyncio.run(cmc_client.get_api_key()) == key

    status = asyncio.run(cmc_client.key_status())
    assert status["configured"] is True
    assert status["masked"].endswith(key[-4:])
    assert key not in json.dumps(status)


def test_delete_clears_key(store):
    asyncio.run(cmc_client.save_api_key("0123456789abcdef"))
    asyncio.run(cmc_client.delete_api_key())
    assert asyncio.run(cmc_client.get_api_key()) is None
    assert asyncio.run(cmc_client.key_status())["configured"] is False


def test_encryption_missing_refuses_plaintext(store, monkeypatch):
    monkeypatch.delenv("LLM_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("BINANCE_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        asyncio.run(cmc_client.save_api_key("0123456789abcdef"))
    assert cmc_client.SETTINGS_KEY not in store


def test_validate_key_does_not_leak_candidate(monkeypatch):
    secret = "SECRETKEY-DO-NOT-LEAK"

    def boom(path, params, key, timeout=6.0):
        return {"ok": False, "data": None, "status": 401,
                "error": f"HTTP 401: {key} geçersiz"}

    monkeypatch.setattr(cmc_client, "_http_get", boom)
    out = asyncio.run(cmc_client.validate_key(secret))
    assert out["ok"] is False
    assert secret not in json.dumps(out)


def test_ledger_counts_requests(store):
    asyncio.run(cmc_client._ledger_reset())
    asyncio.run(cmc_client._ledger_add(2))
    asyncio.run(cmc_client._ledger_add(1))
    ledger = json.loads(store[cmc_client.LEDGER_KEY])
    assert ledger["requests"] == 2
    assert ledger["credits"] == 3
