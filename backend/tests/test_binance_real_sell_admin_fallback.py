"""Gerçek emir anahtarı: anahtarları eski genel ayarda duran yönetici için (user_binance_keys satırı yok)
'Canlı işlemi aç' kalıcı olmalı ve kapı açılmalı. Sahte DB; GERÇEK EMİR YOK."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import main


@pytest.fixture
def no_env(monkeypatch):
    monkeypatch.delenv("ENABLE_REAL_BINANCE_SELL", raising=False)


def test_admin_without_key_row_falls_back_to_legacy_panel_setting(no_env):
    with patch("app.main.database.get_user_binance_keys", new=AsyncMock(return_value=None)), \
            patch("app.main.database.get_llm_setting", new=AsyncMock(return_value="1")):
        assert asyncio.run(main._real_sell_state_for(1, role="admin")) == (True, "panel")


def test_user_without_key_row_stays_closed(no_env):
    with patch("app.main.database.get_user_binance_keys", new=AsyncMock(return_value=None)), \
            patch("app.main.database.get_llm_setting", new=AsyncMock(return_value="1")):
        assert asyncio.run(main._real_sell_state_for(1, role="user")) == (False, "panel")


def test_user_row_wins_over_legacy_setting(no_env):
    row = {"user_id": 1, "api_key_encrypted": "x", "api_secret_encrypted": "y", "real_sell_enabled": False}
    with patch("app.main.database.get_user_binance_keys", new=AsyncMock(return_value=row)), \
            patch("app.main.database.get_llm_setting", new=AsyncMock(return_value="1")):
        assert asyncio.run(main._real_sell_state_for(1, role="admin")) == (False, "panel")


def _settings_patches(role, update_rows):
    # Yöneticinin anahtarları eski genel ayarda (user_binance_keys satırı yok).
    legacy = {"binance_real_sell_enabled": "0", main.BINANCE_API_KEY_SETTING: "enc-key"}

    async def get_setting(key, default=""):
        return legacy.get(key, default)

    async def set_setting(key, value):
        legacy[key] = value

    patches = [
        patch("app.main._require_user", MagicMock(return_value={"username": "erkan", "role": role})),
        patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 1, "role": role})),
        patch("app.main.database.get_user_binance_keys", new=AsyncMock(return_value=None)),
        patch("app.main.database.set_user_binance_real_sell", new=AsyncMock(return_value=update_rows)),
        patch("app.main.database.get_llm_setting", new=get_setting),
        patch("app.main.database.set_llm_setting", new=set_setting),
        patch("app.main.log_user_action", new=AsyncMock()),
    ]
    return patches, legacy


def test_admin_toggle_persists_in_legacy_setting_when_no_key_row(no_env):
    patches, legacy = _settings_patches("admin", update_rows=False)
    for p in patches:
        p.start()
    try:
        out = asyncio.run(main.save_binance_settings({"real_sell_enabled": True}, MagicMock()))
    finally:
        for p in patches:
            p.stop()
    assert legacy["binance_real_sell_enabled"] == "1"
    assert out["sell_enabled"] is True


def test_user_toggle_without_key_row_is_rejected(no_env):
    patches, _ = _settings_patches("user", update_rows=False)
    for p in patches:
        p.start()
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main.save_binance_settings({"real_sell_enabled": True}, MagicMock()))
    finally:
        for p in patches:
            p.stop()
    assert exc.value.status_code == 404
