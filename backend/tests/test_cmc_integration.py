"""CMC verisinin radar ve chat katmanına doğru biçimde aktığını doğrular.

Kural: CMC erişilemezse hiçbir tarama/araç patlamaz; alanlar None kalır ve
uydurma değer üretilmez.
"""
import asyncio
import json

import pytest
from cryptography.fernet import Fernet

from app import cmc_client
from app.ai_trading_suite import chat_tools


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setenv("LLM_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CMC_DAILY_CREDIT_BUDGET", "1000")
    data: dict[str, str] = {}

    async def fake_get(key, default=None):
        return data.get(key, default)

    async def fake_set(key, value):
        data[key] = str(value)

    monkeypatch.setattr(cmc_client.database, "get_llm_setting", fake_get)
    monkeypatch.setattr(cmc_client.database, "set_llm_setting", fake_set)
    cmc_client._QUOTES_CACHE.clear()
    cmc_client._PERF_CACHE.clear()
    cmc_client._BRIEF_CACHE = None
    cmc_client._KEY_INFO_CACHE = None
    asyncio.run(cmc_client.save_api_key("test-key-1234567890"))
    return data


def test_base_asset_strips_quote_units():
    assert cmc_client.base_asset("OPGTRY") == "OPG"
    assert cmc_client.base_asset("BTCUSDT") == "BTC"
    assert cmc_client.base_asset("PEPE_TRY") == "PEPE"
    assert cmc_client.base_asset("1000SATSUSDT") == "1000SATS"


def test_attach_market_context_fills_rows(store, monkeypatch):
    def fake_http(path, params=None, key="", timeout=6.0):
        if "quotes/latest" in path:
            return {"ok": True, "status": 200, "error": None, "data": {
                "OPG": {"id": 1, "symbol": "OPG", "slug": "opengradient", "cmc_rank": 412,
                        "quote": [{"symbol": "USD", "price": 0.167, "market_cap": 40_000_000,
                                   "volume_24h": 5_000_000, "volume_change_24h": 130.0,
                                   "percent_change_1h": 1.2, "percent_change_24h": 21.0,
                                   "percent_change_7d": 45.0, "percent_change_30d": 10.0,
                                   "market_cap_dominance": 0.01}]}}}
        if "price-performance" in path:
            return {"ok": True, "status": 200, "error": None, "data": {
                "OPG": {"symbol": "OPG", "quote": {"price": 0.167},
                        "periods": {"all_time": {"high": 0.2, "low": 0.01}}}}}
        return {"ok": False, "status": 403, "error": "plan yetmiyor", "data": None}

    monkeypatch.setattr(cmc_client, "_http_get", fake_http)

    rows = [{"symbol": "OPGTRY", "unified_score": 80}, {"symbol": "XXXXTRY", "unified_score": 10}]
    out = asyncio.run(cmc_client.attach_market_context(rows, top_n=5))

    assert out["enriched"] == 1
    profile = rows[0]["cmc"]
    assert profile["rank"] == 412
    assert profile["pct_7d"] == 45.0
    # ATH 0.2, fiyat 0.167 → -16.5%
    assert profile["ath_distance_pct"] == pytest.approx(-16.5, abs=0.01)
    assert "HACIM_PATLAMASI" in rows[0]["cmc_flags"]
    assert "7G_ASIRI_ISINMA" in rows[0]["cmc_flags"]
    # Profili olmayan satır dokunulmaz, uydurma yok
    assert "cmc" not in rows[1]


def test_attach_is_fail_open_when_http_fails(store, monkeypatch):
    monkeypatch.setattr(cmc_client, "_http_get",
                        lambda *a, **k: {"ok": False, "status": 500, "error": "boom", "data": None})
    rows = [{"symbol": "OPGTRY", "unified_score": 50}]
    out = asyncio.run(cmc_client.attach_market_context(rows))
    assert out["enriched"] == 0
    assert "cmc" not in rows[0]


def test_budget_guard_blocks_calls(store, monkeypatch):
    monkeypatch.setenv("CMC_DAILY_CREDIT_BUDGET", "1")
    asyncio.run(cmc_client._ledger_reset())
    asyncio.run(cmc_client._ledger_add(2))
    called = []
    monkeypatch.setattr(cmc_client, "_http_get", lambda *a, **k: called.append(1))
    out = asyncio.run(cmc_client.quotes_map(["BTCUSDT"]))
    assert out == {}
    assert called == [], "bütçe doluyken ağ çağrısı yapılmamalı"


def test_chat_tool_profile_fails_open(store, monkeypatch):
    monkeypatch.setattr(cmc_client, "_http_get",
                        lambda *a, **k: {"ok": False, "status": 0, "error": "ağ", "data": None})
    out = asyncio.run(chat_tools.execute_cmc_coin_profile({"symbol": "OPGTRY"}))
    assert out["ok"] is True
    assert out["available"] is False
    assert "tahmin etme" in out["note"]


def test_chat_tool_market_context_shape(store, monkeypatch):
    def fake_http(path, params=None, key="", timeout=6.0):
        if "fear-and-greed" in path:
            return {"ok": True, "status": 200, "error": None,
                    "data": [{"value": 12, "value_classification": "Extreme Fear"}]}
        if "global-metrics" in path:
            return {"ok": True, "status": 200, "error": None,
                    "data": {"btc_dominance": 57.0, "quote": {"USD": {"total_market_cap": 2.3e12,
                                                                     "total_volume_24h": 3.9e10}}}}
        return {"ok": False, "status": 403, "error": "plan yetmiyor", "data": None}

    monkeypatch.setattr(cmc_client, "_http_get", fake_http)
    out = asyncio.run(chat_tools.execute_cmc_market_context({}))
    assert out["ok"] is True
    assert out["fear_greed"]["value"] == 12
    assert out["global"]["btc_dominance"] == 57.0
    assert out["trending"] is None  # plan yetmediğinde uydurulmaz
    assert "errors" in out


def test_query_is_logged_without_secret(store, monkeypatch, capsys):
    """Her CMC isteği tek satır olarak loglanmalı; anahtar asla loglanmaz."""
    key = "test-key-1234567890"

    def fake_http(path, params=None, k="", timeout=6.0):
        return {"ok": True, "status": 200, "error": None, "data": {}}

    monkeypatch.setattr(cmc_client, "_http_get", fake_http)
    asyncio.run(cmc_client._call("/v3/fear-and-greed/latest", credits=1))

    out = capsys.readouterr().out
    assert "[CMC]" in out
    assert "/v3/fear-and-greed/latest" in out
    assert "kredi=1" in out
    assert "anahtar" in out
    assert key not in out, "API anahtarı loglanmamalı"


def test_failed_query_logs_error_line(store, monkeypatch, capsys):
    monkeypatch.setattr(cmc_client, "_http_get",
                        lambda *a, **k: {"ok": False, "status": 429, "error": "HTTP 429", "data": None})
    asyncio.run(cmc_client._call("/v3/fear-and-greed/latest", credits=1))
    out = capsys.readouterr().out
    assert "HATA" in out and "429" in out


def test_missing_key_is_logged_once(store, monkeypatch, capsys):
    async def _no_key():
        return None

    monkeypatch.setenv("LLM_ENCRYPTION_KEY", "")
    monkeypatch.delenv("CMC_API_KEY", raising=False)
    monkeypatch.setattr(cmc_client, "get_api_key", _no_key)
    cmc_client._THROTTLE.clear()

    for _ in range(3):
        asyncio.run(cmc_client._call("/v3/fear-and-greed/latest", public_ok=False))
    out = capsys.readouterr().out
    assert out.count("anahtar yok") == 1, "aynı uyarı tekrar tekrar basılmamalı"
