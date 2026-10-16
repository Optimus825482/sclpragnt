"""RR öneri hizmeti: LLM (doğrulanmış) → kural yedeği; zaman aşımı/hata/devre dışı; önbellek."""
import asyncio

import pytest

from app import rr_service
from app.rr_service import extract_features, suggest_rr

SNAP = {
    "symbol": "INITTRY", "price": 6.934, "data_ready": True,
    "trend": {"alignment": "mixed", "adx": {"adx": 27.2}},
    "momentum": {"return_1h": -0.003, "rsi_14": 47.5},
    "volatility": {"atr_pct": 0.0074, "adr_14_pct": 0.093, "day_range_used_pct": 0.107},
    "volume": {"volume_quality": "low_volume", "volume_ratio_20": 0.13},
    "symbol_behavior": {"volatility_regime": "expanding"},
}


@pytest.fixture(autouse=True)
def _clean():
    rr_service._CACHE.clear()
    yield
    rr_service._CACHE.clear()


def _run(coro):
    return asyncio.run(coro)


def test_extract_features_converts_fractions_to_percent():
    f = extract_features(SNAP)
    assert f["atr_pct"] == pytest.approx(0.74, abs=0.01)
    assert f["adr_14_pct"] == pytest.approx(9.3, abs=0.01)
    assert f["rsi_14"] == 47.5 and f["trend_alignment"] == "mixed" and f["adx"] == pytest.approx(27.2)
    assert f["return_1h_pct"] == pytest.approx(-0.3, abs=0.01)


def test_extract_features_tolerates_missing_parts():
    f = extract_features({"price": 1.0})
    assert f["atr_pct"] is None and f["price"] == 1.0


def _chat_returning(text):
    calls = {"n": 0}

    async def chat(snapshot, messages, **kw):
        calls["n"] += 1
        return {"enabled": True, "status": "ok", "text": text}
    return chat, calls


def test_llm_suggestion_used_when_valid():
    chat, _ = _chat_returning('{"sl_pct": 2.5, "rr": 2.4, "kisa_gerekce": "Trend karışık, volatilite genişliyor."}')
    out = _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat))
    assert out["source"] == "llm" and out["sl_pct"] == 2.5 and out["rr"] == 2.4
    assert "volatilite" in out["rationale"]


@pytest.mark.parametrize("text", ["saçma yanıt", "", None, '{"sl_pct": "x"}'])
def test_invalid_llm_output_falls_back_to_rule(text):
    chat, _ = _chat_returning(text)
    out = _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat))
    assert out["source"] == "kural" and out["rr"] == 2.0
    assert out["sl_pct"] == pytest.approx(1.5 * 0.74, abs=0.05) or out["sl_pct"] == 0.8   # kenetli


def test_llm_disabled_falls_back():
    async def chat(snapshot, messages, **kw):
        return {"enabled": False, "status": "disabled", "text": None}
    assert _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat))["source"] == "kural"


def test_llm_exception_falls_back():
    async def chat(snapshot, messages, **kw):
        raise RuntimeError("sağlayıcı hatası")
    assert _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat))["source"] == "kural"


def test_llm_timeout_falls_back_quickly():
    async def chat(snapshot, messages, **kw):
        await asyncio.sleep(5)
        return {"text": '{"sl_pct": 2, "rr": 2}'}
    out = _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat, timeout=0.05))
    assert out["source"] == "kural"


def test_cache_avoids_second_llm_call_within_ttl():
    chat, calls = _chat_returning('{"sl_pct": 2, "rr": 2, "kisa_gerekce": "ok"}')
    _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat, now=1000.0))
    _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat, now=1030.0))
    assert calls["n"] == 1
    _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat, now=1100.0))     # 60 sn sonra yeniden
    assert calls["n"] == 2


def test_cache_is_per_symbol_and_does_not_mix_user_rr():
    chat, calls = _chat_returning('{"sl_pct": 2, "rr": 2, "kisa_gerekce": "ok"}')
    _run(suggest_rr("INITTRY", SNAP, 2.0, chat=chat, now=1000.0))
    _run(suggest_rr("BTCTRY", {**SNAP, "symbol": "BTCTRY"}, 2.0, chat=chat, now=1001.0))
    assert calls["n"] == 2
