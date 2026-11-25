"""Kesilme koruması (2026-11-25): token sınırı yüzünden yanıt YARIM kalmamalı.

Senaryo: sağlayıcı `finish_reason="length"` döndürür → devam turu(ları) yapılır,
metin birleştirilir. Tüm turlar da kesilirse metin korunur ve `truncated=True`
işaretlenir (sessiz yarım cümle yok).
"""
import asyncio
import json

from app import llm_analysis


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload


def _cfg():
    return {
        "provider": {"base_url": "https://provider.test/v1", "api_key_encrypted": "enc"},
        "model": {"name": "test-model", "temperature": 0.2},
        "skills": [],
    }


def _answer(text, finish):
    return json.dumps({"choices": [{"message": {"content": text}, "finish_reason": finish}]}).encode()


def _run(monkeypatch, responses):
    calls = {"n": 0}

    async def fake_open(req, timeout=45):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return _Resp(responses[idx])

    async def fake_cfg():
        return _cfg()

    async def fake_url(url):
        return "https://provider.test/v1"

    monkeypatch.setattr(llm_analysis, "safe_provider_open", fake_open)
    monkeypatch.setattr(llm_analysis.database, "get_active_llm_config", fake_cfg)
    monkeypatch.setattr(llm_analysis, "validate_provider_url", fake_url)
    monkeypatch.setattr(llm_analysis, "decrypt_key", lambda *a, **k: "k")
    monkeypatch.setenv("LLM_CONTINUE_MAX_ROUNDS", "2")

    result = asyncio.run(llm_analysis.chat({}, [{"role": "user", "content": "sor"}], None, None, max_tokens=1200))
    return result, calls["n"]


def test_length_finish_triggers_continuation_and_merges(monkeypatch):
    result, calls = _run(monkeypatch, [
        _answer("İlk yarım cümle", "length"),
        _answer(" ve devamı tamamlandı.", "stop"),
    ])
    assert result["status"] == "ok"
    assert result["text"].startswith("İlk yarım cümle")
    assert result["text"].endswith("tamamlandı.")
    assert result["truncated"] is False
    assert result["continue_rounds"] == 1
    assert calls == 2, "bir devam turu yapılmalı"


def test_still_too_long_is_flagged_not_silently_cut(monkeypatch):
    result, calls = _run(monkeypatch, [
        _answer("Uzun metin", "length"),
        _answer(" yine uzun", "length"),
        _answer(" yine uzun", "length"),
    ])
    assert result["truncated"] is True
    assert result["text"].rstrip().endswith("…")
    assert calls == 3, "en fazla LLM_CONTINUE_MAX_ROUNDS=2 devam turu"


def test_normal_answer_has_no_extra_calls(monkeypatch):
    result, calls = _run(monkeypatch, [_answer("Kısa yanıt.", "stop")])
    assert result["text"] == "Kısa yanıt."
    assert result["truncated"] is False
    assert calls == 1
