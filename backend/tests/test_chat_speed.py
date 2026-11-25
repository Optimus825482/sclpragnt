"""Sohbet hızlandırma: paralel araç yürütme + sembol bağlamı önbelleği.

Kanıt: sıralı araçlarda 3 araç = 3 × süre; her mesajda 7 zaman dilimi snapshot
yeniden hesaplanıyordu.
"""
import asyncio
import time

from app import llm_analysis
from app.routers import llm_chat


def test_tool_calls_run_in_parallel():
    """Üç yavaş araç sırayla DEĞİL, aynı anda çalışmalı."""
    active = {"now": 0, "max": 0}

    async def executor(name, args):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.05)
        active["now"] -= 1
        return {"ok": True, "tool": name}

    calls = [{"id": f"c{i}", "function": {"name": f"tool{i}", "arguments": "{}"}} for i in range(3)]

    started = time.perf_counter()
    results = asyncio.run(llm_analysis.execute_tool_calls(calls, executor))
    elapsed = time.perf_counter() - started

    assert active["max"] == 3, "araçlar paralel çalışmalı"
    assert elapsed < 0.14, f"paralel olmalı, geçen süre {elapsed:.2f}s"
    assert [name for name, _ in results] == ["tool0", "tool1", "tool2"], "sıra korunmalı"


def test_tool_timeout_returns_error_without_killing_round():
    async def slow_executor(name, args):
        await asyncio.sleep(0.2)
        return {"ok": True}

    calls = [{"id": "c1", "function": {"name": "slow", "arguments": "{}"}}]
    results = asyncio.run(llm_analysis.execute_tool_calls(calls, slow_executor, timeout=0.02))
    name, result = results[0]
    assert result.get("tool") == "slow"
    assert "zaman aşımı" in result.get("error", "")


def test_symbol_context_is_cached(monkeypatch):
    """Aynı sembol/td için ikinci çağrı snapshot'ı YENİDEN hesaplamamalı."""
    calls = {"n": 0}

    async def fake_analysis(symbol, tf):
        calls["n"] += 1
        return {"data_ready": True, "items": [], "tf": tf}

    monkeypatch.setattr(llm_chat, "symbol_analysis", fake_analysis)
    monkeypatch.setenv("LLM_CONTEXT_TTL_SEC", "60")
    # CMC çağrılarını nötrle
    monkeypatch.setattr(llm_chat, "cmc_client", None, raising=False)
    llm_chat._CTX_CACHE.clear()

    first = asyncio.run(llm_chat.symbol_llm_context("ABCTRY", "5m"))
    after_first = calls["n"]
    second = asyncio.run(llm_chat.symbol_llm_context("ABCTRY", "5m"))

    assert first == second
    assert calls["n"] == after_first, "önbellek isabet etmeli, yeni snapshot yok"
    assert after_first == 7
