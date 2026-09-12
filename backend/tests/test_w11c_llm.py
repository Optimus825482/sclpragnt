"""W11c-LLM kilit testleri — LLM-01, LLM-02, LLM-03, EMB-01.

Mutasyon kanıtı: `outputs/denetim_2026-09-12/scratch/verify_w11c_llm_mutations.py`.
"""
import asyncio
import contextlib
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database, llm_analysis, security  # noqa: E402


def _cfg():
    return {
        "model": {"name": "test-model", "temperature": 0.3},
        "skills": [],
        "provider": {"base_url": "https://api.example.com/v1",
                     "api_key_encrypted": "enc"},
    }


def _async_value(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


class _FakeHttpResponse:
    """`safe_provider_open` dönüşü — yalnız `status` ve `read()` gerekir."""

    def __init__(self, body):
        self.status = 200
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

    def read(self, size=None):
        return self._body


def _chat_context(stack, handler, extra=None):
    """chat/stream_chat için ortak yamalar."""
    stack.enter_context(mock.patch.object(
        database, "get_active_llm_config", _async_value(_cfg())))
    stack.enter_context(mock.patch.object(
        llm_analysis, "validate_provider_url", _async_value("https://api.example.com/v1")))
    stack.enter_context(mock.patch.object(llm_analysis, "safe_provider_open", handler))
    stack.enter_context(mock.patch.object(llm_analysis, "decrypt_key", lambda *a, **k: "key"))
    for name, value in (extra or {}).items():
        stack.enter_context(mock.patch.object(llm_analysis, name, value))


class StreamOffloadTests(unittest.TestCase):
    """LLM-01 — SSE gövdesi event-loop'u bloke etmemeli ve akış sınırlı olmalı."""

    def test_body_is_read_off_the_event_loop_thread(self):
        threads = []

        class _RecordingResponse:
            status = 200

            def __iter__(self):
                threads.append(threading.current_thread().name)
                yield b'data: {"choices":[{"delta":{"content":"merhaba"}}]}\n'
                yield b"data: [DONE]\n"

        async def handler(request, timeout=None):
            return _RecordingResponse()

        loop_thread = []

        async def scenario():
            loop_thread.append(threading.current_thread().name)
            with contextlib.ExitStack() as stack:
                _chat_context(stack, handler)
                return [event async for event in llm_analysis.stream_chat({}, [])]

        events = asyncio.run(scenario())
        assert threads, "gövde hiç okunmadı"
        assert loop_thread, "senaryo çalışmadı"
        # `for raw_line in response:` senkron soket okumasıdır; event-loop
        # thread'inde çalışırsa tüm uygulama durur.
        assert threads[0] != loop_thread[0], (
            "SSE gövdesi event-loop thread'inde okunuyor (LLM-01 geri geldi)")
        assert any(e["event"] == "delta" and e["data"]["text"] == "merhaba" for e in events)
        assert events[-1]["event"] == "done"

    def test_stream_aborts_at_the_total_deadline(self):
        release = threading.Event()

        class _EndlessResponse:
            status = 200

            def __iter__(self):
                # Sınırlı iterasyon: mutasyon (event-loop'u bloke eden doğrudan
                # çağrı) durumunda test sonsuza kadar asılmaz; en fazla ~12 sn
                # sonra sona erer ve `done` ile çıkar.
                for _ in range(240):
                    if release.is_set():
                        return
                    time.sleep(0.05)
                    yield b": keep-alive\n"

        async def handler(request, timeout=None):
            return _EndlessResponse()

        async def scenario():
            with contextlib.ExitStack() as stack:
                _chat_context(stack, handler, {"STREAM_TOTAL_TIMEOUT": 1})
                events = []
                try:
                    async for event in llm_analysis.stream_chat({}, []):
                        events.append(event)
                finally:
                    release.set()
                return events

        events = asyncio.run(asyncio.wait_for(scenario(), timeout=10))
        assert events[-1]["event"] == "error", events
        assert "toplam süre" in events[-1]["data"]["error"]

    def test_stream_open_uses_the_bounded_constant(self):
        captured = {}

        async def handler(request, timeout=None):
            captured["timeout"] = timeout
            return _FakeHttpResponse(b"data: [DONE]\n")

        async def scenario():
            with contextlib.ExitStack() as stack:
                _chat_context(stack, handler, {"STREAM_OPEN_TIMEOUT": 7})
                return [event async for event in llm_analysis.stream_chat({}, [])]

        asyncio.run(scenario())
        assert captured.get("timeout") == 7, captured


class ChatLimitTests(unittest.TestCase):
    """LLM-02 — `max_tokens`, mutlak süre sınırı ve birikimli token muhasebesi."""

    def _run(self, handler, extra=None, **chat_kwargs):
        async def scenario():
            with contextlib.ExitStack() as stack:
                _chat_context(stack, handler, extra)
                return await llm_analysis.chat({}, [], **chat_kwargs)
        return asyncio.run(scenario())

    def test_payload_carries_max_tokens(self):
        payloads = []

        async def handler(request, timeout=None):
            payloads.append(json.loads(request.data.decode("utf-8")))
            return _FakeHttpResponse({"choices": [{"message": {"content": "ok"}}]})

        result = self._run(handler)
        assert result["status"] == "ok", result
        assert payloads[0]["max_tokens"] == llm_analysis.CHAT_MAX_TOKENS

    def test_max_tokens_can_be_disabled(self):
        payloads = []

        async def handler(request, timeout=None):
            payloads.append(json.loads(request.data.decode("utf-8")))
            return _FakeHttpResponse({"choices": [{"message": {"content": "ok"}}]})

        self._run(handler, {"CHAT_MAX_TOKENS": 0})
        assert "max_tokens" not in payloads[0]

    def test_tool_loop_aborts_on_the_total_deadline(self):
        async def handler(request, timeout=None):
            return _FakeHttpResponse({"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "ping", "arguments": "{}"}}]}}]})

        async def executor(name, arguments):
            return {"ok": True}

        result = self._run(handler, {"TOOL_LOOP_TOTAL_TIMEOUT": 0},
                           tools=[{"type": "function"}], tool_executor=executor)
        assert result["status"] == "error", result
        assert "toplam süre" in result["error"], result

    def test_provider_usage_accumulates_across_rounds(self):
        calls = {"n": 0}
        usage = {"total_tokens": 100, "prompt_tokens": 60, "completion_tokens": 40}

        async def handler(request, timeout=None):
            calls["n"] += 1
            if calls["n"] >= 2:
                return _FakeHttpResponse({"choices": [{"message": {"content": "bitti"}}],
                                          "usage": dict(usage)})
            return _FakeHttpResponse({"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "ping", "arguments": "{}"}}]}}],
                "usage": dict(usage)})

        async def executor(name, arguments):
            return {"ok": True}

        result = self._run(handler, None, tools=[{"type": "function"}], tool_executor=executor)
        assert result["status"] == "ok", result
        # Her round TÜM konuşmayı yeniden gönderir → gerçek maliyet toplamdır.
        assert result["tool_loop"]["provider_total_tokens"] == 200, result["tool_loop"]
        assert result["tool_loop"]["provider_completion_tokens"] == 80, result["tool_loop"]


class LlmExecutorTests(unittest.TestCase):
    """LLM-03 — provider çağrıları ayrı, sınırlı bir havuzda çalışmalı."""

    def test_executor_is_dedicated_and_bounded(self):
        executor = security._LLM_EXECUTOR
        assert executor._max_workers == security.LLM_EXECUTOR_MAX_WORKERS
        assert executor._thread_name_prefix == "llm-provider"

    def test_provider_validation_runs_on_the_llm_executor(self):
        names = []

        def fake_sync(base_url):
            names.append(threading.current_thread().name)
            return base_url

        with mock.patch.object(security, "_validate_provider_url_sync", fake_sync):
            asyncio.run(security.validate_provider_url("https://api.example.com"))
        assert names, "senkron doğrulama çalışmadı"
        assert names[0].startswith("llm-provider"), names


class EmbeddingDimensionTests(unittest.TestCase):
    """EMB-01 — `dimensions` zorunlu; uyuşmazlık erken yakalanmalı."""

    def _run(self, model, vector):
        async def handler(request, timeout=None):
            return _FakeHttpResponse({"data": [{"embedding": vector}]})

        async def scenario():
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    database, "get_embedding_llm_config",
                    _async_value({"model": model, "provider": _cfg()["provider"]})))
                stack.enter_context(mock.patch.object(
                    llm_analysis, "_validate_provider_url_sync", lambda url: url))
                stack.enter_context(mock.patch.object(llm_analysis, "safe_provider_open", handler))
                stack.enter_context(mock.patch.object(
                    llm_analysis, "decrypt_key", lambda *a, **k: "key"))
                return await llm_analysis.embedding("metin")

        return asyncio.run(scenario())

    def test_missing_dimensions_is_rejected(self):
        model = {"name": "emb", "model_type": "embedding", "dimensions": None}
        result = self._run(model, [0.1] * 3)
        assert result["status"] == "error", result
        assert "tanımlı değil" in result["error"], result

    def test_mismatched_dimensions_is_rejected(self):
        model = {"name": "emb", "model_type": "embedding", "dimensions": 4}
        result = self._run(model, [0.1] * 3)
        assert result["status"] == "error", result
        assert "Dimension uyumsuzluğu" in result["error"], result

    def test_matching_dimensions_is_accepted(self):
        model = {"name": "emb", "model_type": "embedding", "dimensions": 3}
        result = self._run(model, [0.1] * 3)
        assert result["status"] == "ok", result
        assert result["dimensions"] == 3


class EmbeddingWorkerStartTests(unittest.TestCase):
    """EMB-01 — eşzamanlı `start()` tek bir worker üretmeli."""

    def test_concurrent_start_creates_a_single_worker(self):
        from app import embedding_worker as ew

        async def scenario():
            worker = ew.EmbeddingWorker()
            started = []
            release = asyncio.Event()

            async def fake_run():
                started.append(1)
                await release.wait()

            async def noop(*args, **kwargs):
                # GERÇEK bir askıya alma noktası: kilit olmadan iki `start()`
                # bu noktada iç içe girer ve iki `_run` görevi üretir. Yalnız
                # `return None` yeterli değildi — await hiç yield etmediği için
                # kilit kaldırılsa bile test geçiyordu (G-02 dersi).
                await asyncio.sleep(0)

            worker._run = fake_run
            worker._recover_interrupted_jobs = noop
            worker._fill_from_persistence = noop
            await asyncio.gather(worker.start(None, None), worker.start(None, None))
            # Zamanlanan worker görevlerinin ilk `await`ine kadar koşmasına izin
            # ver; aksi halde `started` sayımı yarışa duyarsız kalır.
            for _ in range(3):
                await asyncio.sleep(0)
            count = len(started)
            release.set()
            await worker.stop()
            return count

        assert asyncio.run(scenario()) == 1


if __name__ == "__main__":
    unittest.main()
