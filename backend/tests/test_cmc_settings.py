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


def test_encryption_missing_uses_local_keyfile_not_plaintext(store, monkeypatch, tmp_path):
    """Env anahtarı yoksa yerel dosya anahtarı kullanılır; düz metin YAZILMAZ."""
    monkeypatch.delenv("LLM_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("BINANCE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("CMC_KEYFILE", str(tmp_path / ".cmc_fernet_key"))
    key = "0123456789abcdef"
    asyncio.run(cmc_client.save_api_key(key))
    assert key not in store[cmc_client.SETTINGS_KEY]
    assert asyncio.run(cmc_client.get_api_key()) == key


def test_unwritable_keyfile_refuses_plaintext(store, monkeypatch, tmp_path):
    """Anahtar dosyası yazılamıyorsa düz metne DÜŞÜLMEZ; açık hata verilir."""
    monkeypatch.delenv("LLM_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("BINANCE_ENCRYPTION_KEY", raising=False)
    blocker = tmp_path / "blocker"
    blocker.write_text("x")  # dosya → altına dizin açılamaz
    monkeypatch.setenv("CMC_KEYFILE", str(blocker / "sub" / ".cmc_fernet_key"))
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


def test_save_works_without_env_encryption_key(store, monkeypatch, tmp_path):
    """LLM_ENCRYPTION_KEY yokken de kayıt kalıcı olmalı (yerel anahtar dosyası)."""
    monkeypatch.delenv("LLM_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("BINANCE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("CMC_KEYFILE", str(tmp_path / ".cmc_fernet_key"))

    key = "0123456789abcdef0123456789abcdef"
    asyncio.run(cmc_client.save_api_key(key))

    stored = store[cmc_client.SETTINGS_KEY]
    assert key not in stored, "anahtar düz metin saklanmamalı"
    assert asyncio.run(cmc_client.get_api_key()) == key, "kayıt yeniden okunabilmeli"
    assert (tmp_path / ".cmc_fernet_key").exists()


def test_unverified_save_is_flagged(store):
    asyncio.run(cmc_client.save_api_key("abcdef1234567890", verified=False))
    status = asyncio.run(cmc_client.key_status())
    assert status["configured"] is True
    assert status["verified"] is False
    assert status["saved_at"]
