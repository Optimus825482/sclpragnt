"""Chat hattı hata düzeltmelerinin regresyon testleri (2026-11-25).

Kapsanan gerçek hatalar:
1) Araç listesinde aynı fonksiyon adının iki kez gitmesi (sağlayıcı 400'ü).
2) Bağlam kırpıldıktan sonra `tool` sonucunun `tool_calls`'sız kalması (400).
3) Sağlayıcının geçici 429/5xx yanıtının tek denemede kullanıcıya hata olarak
   dönmesi.
"""
import asyncio
import io
import json
from urllib.error import HTTPError

import numpy as np
import pytest

from app import llm_analysis
from app.routers import llm_chat


def test_dedupe_tools_keeps_first_and_order():
    tools = [
        {"function": {"name": "a"}},
        {"function": {"name": "b"}},
        {"function": {"name": "a"}},
        {"function": {"name": "c"}},
    ]
    out = llm_chat._dedupe_tools(tools)
    assert [t["function"]["name"] for t in out] == ["a", "b", "c"]


def test_dedupe_tools_keeps_malformed_entries():
    tools = [{"broken": True}, {"function": {"name": "x"}}]
    assert len(llm_chat._dedupe_tools(tools)) == 2


def test_orphan_tool_result_is_dropped():
    messages = [
        {"role": "user", "content": "eski"},
        {"role": "tool", "tool_call_id": "c1", "content": "sonuç"},
        {"role": "user", "content": "yeni"},
    ]
    out = llm_analysis._repair_tool_pairing(messages)
    assert [m["role"] for m in out] == ["user", "user"]


def test_assistant_with_unanswered_calls_is_cleaned():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "user", "content": "devam"},
    ]
    out = llm_analysis._repair_tool_pairing(messages)
    assert [m["role"] for m in out] == ["user"]


def test_matched_pair_survives():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "r"},
    ]
    out = llm_analysis._repair_tool_pairing(messages)
    assert [m["role"] for m in out] == ["assistant", "tool"]
    assert out[0]["tool_calls"][0]["id"] == "c1"


def test_context_trim_result_is_pairable():
    messages = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c9", "type": "function", "function": {"name": "y", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c9", "content": "sonuç"},
    ]
    selected, _used = llm_analysis._context_window_messages(
        messages, token_budget=40, max_messages=10)
    roles = [m["role"] for m in selected]
    if "tool" in roles:
        assert "assistant" in roles[:roles.index("tool")]
        assert selected[roles.index("tool")]["tool_call_id"] == "c9"


def test_retry_policy_codes():
    """Yalnız 429 ve 5xx yeniden denenir; plan/anahtar/şema hataları denenmez."""
    for code in (429, 500, 502, 503, 504):
        assert llm_analysis._retryable_provider_status(code) is True
    for code in (400, 401, 402, 403, 404, 422):
        assert llm_analysis._retryable_provider_status(code) is False


class _Err(Exception):
    def __init__(self, headers):
        super().__init__("err")
        self.headers = headers


def test_retry_delay_respects_retry_after_and_cap():
    assert llm_analysis._retry_delay_seconds(_Err({"Retry-After": "1"})) == 1.0
    assert llm_analysis._retry_delay_seconds(_Err({"Retry-After": "99"})) == 2.0
    assert llm_analysis._retry_delay_seconds(_Err({})) == 0.5
    assert llm_analysis._retry_delay_seconds(_Err({"Retry-After": "abc"})) == 0.5


def test_stream_chat_emits_heartbeat_while_tools_run(monkeypatch):
    """Araç döngüsü uzun sürerken SSE sessiz kalmamalı (proxy kopması)."""
    async def slow_chat(*args, **kwargs):
        await asyncio.sleep(0.12)
        return {"status": "ok", "text": "yanıt"}

    monkeypatch.setattr(llm_analysis, "chat", slow_chat)
    monkeypatch.setattr(llm_analysis, "STREAM_HEARTBEAT_SEC", 0.02)

    async def collect():
        return [event async for event in llm_analysis.stream_chat(
            {}, [], tools=[{"type": "function", "function": {"name": "x"}}],
            tool_executor=lambda *a: None)]

    events = asyncio.run(collect())
    names = [e["event"] for e in events]
    assert "heartbeat" in names
    assert names[-1] == "done"
    assert events[-1]["data"]["text"] == "yanıt"


def test_stream_chat_reports_tool_path_exception(monkeypatch):
    """Araç yolundaki beklenmedik hata SSE 'error' olayına dönüşmeli."""
    async def boom(*args, **kwargs):
        raise RuntimeError("sağlayıcı çöktü")

    monkeypatch.setattr(llm_analysis, "chat", boom)

    async def collect():
        return [event async for event in llm_analysis.stream_chat(
            {}, [], tools=[{"type": "function", "function": {"name": "x"}}],
            tool_executor=lambda *a: None)]

    events = asyncio.run(collect())
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["error_code"] == "provider_error"
    assert "sağlayıcı çöktü" in events[-1]["data"]["error"]


@pytest.mark.asyncio
async def test_chart_chat_stream_serializes_numpy_market_snapshot(monkeypatch):
    async def active_config():
        return {"model": {"name": "test-model", "temperature": 0.2}, "skills": [],
                "provider": {"base_url": "https://example.com/v1", "api_key_encrypted": "test"}}

    async def provider_url(url):
        return url

    provider_payloads = []

    async def provider_open(request, **kwargs):
        provider_payloads.append(json.loads(request.data))
        return io.BytesIO(b'{"choices":[{"message":{"role":"assistant","content":"THETRY analizi hazir"}}]}')

    monkeypatch.setattr(llm_analysis.database, "get_active_llm_config", active_config)
    monkeypatch.setattr(llm_analysis, "validate_provider_url", provider_url)
    monkeypatch.setattr(llm_analysis, "decrypt_key", lambda _: "test")
    monkeypatch.setattr(llm_analysis, "safe_provider_open", provider_open)

    snapshot = {"symbol": "THETRY", "symbol_data": {
        "empty_flow": np.array([]),
        "bids": np.array([[1.85, 250]]),
        "momentum": np.arange(20),
        "price": np.array(1.86123),
        "sample_count": np.int64(20),
        "buyer_dominant": np.bool_(False),
    }}
    events = [event async for event in llm_analysis.stream_chat(
        snapshot, [{"role": "user", "content": "Bu coinde şu an genel durum nedir?"}],
        tools=[{"type": "function", "function": {"name": "sample"}}],
        tool_executor=lambda *_: None,
    )]

    assert [event["event"] for event in events] == ["delta", "done"]
    data = json.loads(provider_payloads[0]["messages"][1]["content"].split("\n", 1)[1])
    assert data == {"symbol": "THETRY", "symbol_data": {
        "momentum": list(range(15)), "price": 1.8612, "sample_count": 20, "buyer_dominant": False,
    }}


def test_tool_timeout_constant_sane():
    assert llm_analysis.TOOL_CALL_TIMEOUT >= 5
    assert llm_analysis.STREAM_HEARTBEAT_SEC >= 3
