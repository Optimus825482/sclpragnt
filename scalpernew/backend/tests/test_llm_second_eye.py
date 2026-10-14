"""LLM İKİNCİ GÖZ: şemalı karar ayrıştırma, kanıt paketi, kapılar ve bildirim zarfı."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from app import llm_second_eye


def _notif(**over):
    base = {
        "symbol": "HEMITRY", "score": 72.0, "target_pct": 2.0, "price": 1.23,
        "horizon_minutes": 5, "sources": ["velocity"], "mode": "test",
    }
    base.update(over)
    return base


class ParseVerdictTests(unittest.TestCase):
    def test_plain_and_fenced_json(self):
        raw = json.dumps({"verdict": "DEVAM", "confidence": 83, "reasons": ["cvd_pozitif", "derinlik_güçlü"],
                          "trap_evidence": [], "summary": "akış teyitli"})
        parsed = llm_second_eye.parse_verdict(raw)
        self.assertEqual(parsed["verdict"], "DEVAM")
        self.assertEqual(parsed["confidence"], 83)
        self.assertEqual(parsed["reasons"], ["cvd_pozitif", "derinlik_güçlü"])
        fenced = llm_second_eye.parse_verdict("```json\n" + raw + "\n```")
        self.assertEqual(fenced["verdict"], "DEVAM")

    def test_alias_and_clamping(self):
        parsed = llm_second_eye.parse_verdict('{"verdict":"TRAP","confidence":250,"reasons":["x"]}')
        self.assertEqual(parsed["verdict"], "FAKE")
        self.assertEqual(parsed["confidence"], 100)
        tuzak = llm_second_eye.parse_verdict('{"verdict":"TUZAK","confidence":60}')
        self.assertEqual(tuzak["verdict"], "FAKE")
        fake = llm_second_eye.parse_verdict('{"verdict":"FAKE","confidence":70}')
        self.assertEqual(fake["verdict"], "FAKE")
        low = llm_second_eye.parse_verdict('{"verdict":"belirsiz","confidence":-5}')
        self.assertEqual(low["verdict"], "BELIRSIZ")
        self.assertEqual(low["confidence"], 0)

    def test_invalid_payloads_rejected(self):
        self.assertIsNone(llm_second_eye.parse_verdict("JSON değil"))
        self.assertIsNone(llm_second_eye.parse_verdict('{"verdict":"BILINMEYEN","confidence":50}'))
        self.assertIsNone(llm_second_eye.parse_verdict(None))
        self.assertIsNone(llm_second_eye.parse_verdict('{"confidence":50}'))

    def test_non_string_reasons_dropped(self):
        parsed = llm_second_eye.parse_verdict(
            '{"verdict":"DEVAM","confidence":60,"reasons":["iyi", 5, "", null, "cvd"], "trap_evidence":"değil liste"}')
        self.assertEqual(parsed["reasons"], ["iyi", "5", "cvd"])
        self.assertEqual(parsed["trap_evidence"], [])

    def test_synonym_verdicts_mapped(self):
        # Canlıda rozet SCHEMA gösteriyordu: model eş anlamlı kelime yazıyordu.
        self.assertEqual(llm_second_eye.parse_verdict('{"verdict":"GERÇEK","confidence":70}')["verdict"], "DEVAM")
        self.assertEqual(llm_second_eye.parse_verdict('{"verdict":"REAL","confidence":70}')["verdict"], "DEVAM")
        self.assertEqual(llm_second_eye.parse_verdict('{"verdict":"SAHTE","confidence":70}')["verdict"], "FAKE")
        self.assertEqual(llm_second_eye.parse_verdict('{"verdict":"BİLİNMİYOR","confidence":50}')["verdict"], "BELIRSIZ")

    def test_wrapped_json_unwrapped(self):
        parsed = llm_second_eye.parse_verdict(
            '{"result": {"verdict": "FAKE", "confidence": 66, "reasons": ["whale_satis"]}}')
        self.assertEqual(parsed["verdict"], "FAKE")
        self.assertEqual(parsed["reasons"], ["whale_satis"])

    def test_prose_embedded_json_salvaged_by_regex(self):
        # JSON cümle içine gömülmüş: lenient parser başarısızsa regex kurtarır.
        text = 'Piyasa karışık görünüyor. Sonuç: {"verdict": "DEVAM", "confidence": 72} — kanıtlar hemfikir.'
        parsed = llm_second_eye.parse_verdict(text)
        self.assertEqual(parsed["verdict"], "DEVAM")
        self.assertEqual(parsed["confidence"], 72)

    def test_free_prose_without_verdict_pattern_rejected(self):
        # Serbest metin taraması YOK: küçük harf "gerçek değil / fake" tuzağına düşülmez.
        self.assertIsNone(llm_second_eye.parse_verdict("Bu kırılım gerçek değil, fake olabilir gibi."))

    def test_leaked_reasoning_with_uppercase_token_salvaged(self):
        # CANLI VAKA (rozet SCHEMA): model düşünme sürecini İngilizce sızdırdı,
        # JSON hiç yazmadı ama kararını BÜYÜK HARF şema tokeniyle verdi.
        live_sample = (
            "We need answer only JSON exact schema. Need evaluate solely evidence. "
            "Package bullish technical but no CVD/trade imbalance, whales, ladder, "
            "funding, BTC. We should perhaps DEVAM due strong confluence?"
        )
        parsed = llm_second_eye.parse_verdict(live_sample)
        self.assertEqual(parsed["verdict"], "DEVAM")
        self.assertEqual(parsed["confidence"], 50)   # güven alanı yok → nötr

    def test_salvage_respects_percent_and_negation(self):
        parsed = llm_second_eye.parse_verdict("Kanıtlar çelişiyor, FAKE olasılığı yüksek. %65")
        self.assertEqual(parsed["verdict"], "FAKE")
        self.assertEqual(parsed["confidence"], 65)
        # küçük harf "devam etmez" — token taramasına takılmaz
        self.assertIsNone(llm_second_eye.parse_verdict("Momentum bitmiş, devam etmez."))

    def test_extract_content_list_and_reasoning_fallback(self):
        # content parça listesi biçimi
        body_list = {"choices": [{"message": {"content": [{"type": "text", "text": '{"verdict":'},
                                                          {"type": "text", "text": '"FAKE"}'}]}}]}
        # _extract _fast_llm_call içinde tanımlı; aynı mantığı taşan fonksiyondan test edilemez
        # → davranışı _fast_llm_call üzerinden doğrula:
        cfg = {"model": {"name": "m", "temperature": 0.3},
               "provider": {"base_url": "https://gw.example/v1", "api_key_encrypted": "e"}}

        async def _fake_open(req, timeout=None):
            class _Resp:
                def read(self):
                    return json.dumps(body_list).encode()
            return _Resp()

        with patch("app.database.get_active_llm_config", AsyncMock(return_value=cfg)), \
             patch("app.security.validate_provider_url", AsyncMock(return_value="https://gw.example/v1")), \
             patch("app.llm_analysis.decrypt_key", lambda *_a, **_k: "k"), \
             patch("app.security.safe_provider_open", _fake_open):
            result = asyncio.run(llm_second_eye._fast_llm_call({}))
        self.assertIn("FAKE", result["text"])

    def test_extract_empty_content_falls_back_to_reasoning(self):
        cfg = {"model": {"name": "m", "temperature": 0.3},
               "provider": {"base_url": "https://gw.example/v1", "api_key_encrypted": "e"}}
        body_reasoning = {"choices": [{"message": {
            "content": "", "reasoning_content": 'Kanıtlar hemfikir. {"verdict": "DEVAM", "confidence": 80}'}}]}

        async def _fake_open(req, timeout=None):
            class _Resp:
                def read(self):
                    return json.dumps(body_reasoning).encode()
            return _Resp()

        with patch("app.database.get_active_llm_config", AsyncMock(return_value=cfg)), \
             patch("app.security.validate_provider_url", AsyncMock(return_value="https://gw.example/v1")), \
             patch("app.llm_analysis.decrypt_key", lambda *_a, **_k: "k"), \
             patch("app.security.safe_provider_open", _fake_open):
            result = asyncio.run(llm_second_eye._fast_llm_call({}))
        parsed = llm_second_eye.parse_verdict(result["text"])
        self.assertEqual(parsed["verdict"], "DEVAM")


class EligibleTests(unittest.TestCase):
    def setUp(self):
        llm_second_eye.reset_state_for_tests()

    def test_valid_notification_eligible(self):
        self.assertTrue(llm_second_eye.eligible(_notif()))

    def test_updates_and_suppressed_skipped(self):
        self.assertFalse(llm_second_eye.eligible(_notif(updated=True)))
        self.assertFalse(llm_second_eye.eligible(_notif(suppressed_by_unified=True)))
        self.assertFalse(llm_second_eye.eligible(_notif(source="llm_second_eye")))

    def test_low_score_and_bad_shape_skipped(self):
        # MIN_SCORE varsayılan 0 (her push değerlendirilir); skor'suz/basit
        # zarflar da uygundur. Kapı yükseltildiğinde düşük skor elenir.
        with patch.object(llm_second_eye, "MIN_SCORE", 50.0):
            self.assertFalse(llm_second_eye.eligible(_notif(score=30.0)))
            self.assertFalse(llm_second_eye.eligible(_notif(score=None)))
        self.assertFalse(llm_second_eye.eligible(_notif(symbol="")))
        self.assertFalse(llm_second_eye.eligible(None))

    def test_env_kill_switch(self):
        with patch.dict(os.environ, {"LLM_SECOND_EYE_ENABLED": "0"}):
            self.assertFalse(llm_second_eye.eligible(_notif()))


class EvidenceTests(unittest.TestCase):
    def test_master_surge_compacted(self):
        surge = {
            "passed": True, "composite_index": 81.0, "confluence_4way": True, "confluence_count": 4,
            "layers": {"l1_liquidity": {"passed": True, "score": 20.0, "reason": "ok", "spread_pct": 0.1},
                       "l2_volatility": {"passed": True, "score": 20.0}},
            "derivatives": {"funding_rate_pct": 0.01, "funding_state": "NEUTRAL", "open_interest_usd": 1.0,
                            "extra_field": "kesilir"},
            "macro_sentiment": {"btc_trend_state": "UP"},
        }
        compact = llm_second_eye.compact_master_surge(surge)
        self.assertEqual(compact["composite_index"], 81.0)
        self.assertIn("l1_liquidity", compact["layers"])
        self.assertNotIn("spread_pct", compact["layers"]["l1_liquidity"])
        self.assertNotIn("extra_field", compact["derivatives"])
        self.assertEqual(compact["macro_sentiment"]["btc_trend_state"], "UP")
        self.assertIsNone(llm_second_eye.compact_master_surge(None))

    def test_build_evidence_includes_surge_and_signals(self):
        notif = _notif(master_surge={"passed": True, "composite_index": 80.0},
                       signals={"proximity": 0.9, "green": 4})
        evidence = asyncio.run(llm_second_eye.build_evidence(notif))
        self.assertEqual(evidence["master_surge"]["composite_index"], 80.0)
        self.assertEqual(evidence["rising_signals"]["proximity"], 0.9)
        self.assertIn("signal", evidence)

    def test_microstructure_only_for_active_symbol(self):
        notif = _notif(symbol="HEMITRY")

        class _StubFlow:
            def get_snapshot(self):
                return {"symbol": "HEMITRY", "data_ready": True, "bars": {"1s": {"count": 10}},
                        "trade_flow": {"cvd_try": 100.0}, "depth": {"ladder_asymmetry": 0.2}}

        with patch("app.microflow.microflow", _StubFlow()):
            evidence = asyncio.run(llm_second_eye.build_evidence(notif))
            self.assertIn("microstructure", evidence)
            other = asyncio.run(llm_second_eye.build_evidence(_notif(symbol="BTCTRY")))
            self.assertNotIn("microstructure", other)


class EvaluateGuardTests(unittest.TestCase):
    def setUp(self):
        llm_second_eye.reset_state_for_tests()

    def _patch_db(self, setting="1"):
        return patch("app.database.get_llm_setting", AsyncMock(return_value=setting))

    def _patch_fast(self, result):
        # DİKKAT: mock'u testin gördüğü referansla AYNI nesne yapmalı; yoksa
        # await_count/claim'ler gerçek patch'e değil ölü kopyaya bakar.
        self._fast_mock = AsyncMock(return_value=result)
        return patch.object(llm_second_eye, "_fast_llm_call", self._fast_mock)

    def test_db_setting_off_skips_llm(self):
        with self._patch_db("0"), self._patch_fast({}):
            result = asyncio.run(llm_second_eye.evaluate(_notif()))
        self.assertIsNone(result)
        self._fast_mock.assert_not_awaited()

    def test_provider_missing_sets_backoff(self):
        with self._patch_db("1"), self._patch_fast({"enabled": False, "status": "disabled", "text": None}):
            first = asyncio.run(llm_second_eye.evaluate(_notif()))
            self.assertIsNone(first)
            # backoff penceresi içinde ikinci çağrı LLM'e HİÇ gitmez
            second = asyncio.run(llm_second_eye.evaluate(_notif(score=95.0)))
        self.assertIsNone(second)
        self.assertEqual(self._fast_mock.await_count, 1)
        self.assertGreater(llm_second_eye._state["provider_missing_until"], 0)

    def test_successful_verdict_then_cooldown(self):
        good = {"enabled": True, "text": json.dumps(
            {"verdict": "DEVAM", "confidence": 77, "reasons": ["cvd_pozitif"], "trap_evidence": [],
             "summary": "akış destekliyor"})}
        with self._patch_db("1"), self._patch_fast(good):
            envelope = asyncio.run(llm_second_eye.evaluate(_notif()))
            self.assertIsNotNone(envelope)
            self.assertEqual(envelope["llm_verdict"], "DEVAM")
            again = asyncio.run(llm_second_eye.evaluate(_notif(score=95.0)))
        self.assertIsNone(again)  # sembol cooldown'u
        self.assertEqual(self._fast_mock.await_count, 1)
        self.assertEqual(llm_second_eye._state["evaluated"], 1)

    def test_schema_violation_returns_none(self):
        bad = {"enabled": True, "text": "karar veremedim ama JSON da yazmadım"}
        with self._patch_db("1"), self._patch_fast(bad):
            result = asyncio.run(llm_second_eye.evaluate(_notif()))
        self.assertIsNone(result)
        self.assertIn("şemasına uymadı", str(llm_second_eye._state["last_error"]))
        self.assertEqual(llm_second_eye._state["last_error_kind"], "schema")

    def test_slow_provider_marks_timeout_kind(self):
        async def _slow(evidence):
            await asyncio.sleep(0.05)
            return {"enabled": True, "text": "{}"}

        with self._patch_db("1"), patch.object(llm_second_eye, "_fast_llm_call", _slow), \
             patch.object(llm_second_eye, "TIMEOUT_SEC", 0.01):
            result = asyncio.run(llm_second_eye.evaluate(_notif()))
        self.assertIsNone(result)
        self.assertEqual(llm_second_eye._state["last_error_kind"], "timeout")
        self.assertEqual(llm_second_eye._state["error_counts"].get("timeout"), 1)

    def test_stats_exposes_diagnostics(self):
        stats = llm_second_eye.stats()
        for key in ("evaluated", "delivered", "skipped", "last_error_kind",
                    "error_counts", "provider_missing_active", "timeout_sec"):
            self.assertIn(key, stats)


class FastLlmCallTests(unittest.TestCase):
    """Hızlı kanal sözleşmesi: 2 mesaj, ≤250 token, json_object, text çıkarımı."""

    def _patch_provider(self, body: bytes):
        cfg = {"model": {"name": "test-model", "temperature": 0.3},
               "provider": {"base_url": "https://gw.example/v1", "api_key_encrypted": "enc"}}

        captured = {}

        async def _fake_open(req, timeout=15):
            captured["payload"] = json.loads(req.data.decode())
            captured["timeout"] = timeout

            class _Resp:
                def read(self):
                    return body

            return _Resp()

        return (patch("app.database.get_active_llm_config", AsyncMock(return_value=cfg)),
                patch("app.security.validate_provider_url", AsyncMock(return_value="https://gw.example/v1")),
                patch("app.llm_analysis.decrypt_key", lambda *_a, **_k: "test-key"),
                patch("app.security.safe_provider_open", _fake_open),
                captured)

    def test_lean_payload_and_text_extraction(self):
        body = json.dumps({"choices": [{"message": {"content": '{"verdict":"DEVAM"}'}}]}).encode()
        patches = self._patch_provider(body)
        with patches[0], patches[1], patches[2], patches[3]:
            result = asyncio.run(llm_second_eye._fast_llm_call({"symbol": "HEMITRY"}))
        self.assertTrue(result["enabled"])
        self.assertIn("DEVAM", result["text"])
        payload = patches[4]["payload"]
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["max_tokens"], llm_second_eye.FAST_MAX_TOKENS)
        self.assertLessEqual(payload["max_tokens"], 250)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertIn("HEMITRY", payload["messages"][1]["content"])
        self.assertEqual(patches[4]["timeout"], llm_second_eye.HTTP_TIMEOUT_SEC)

    def test_gateway_refusing_json_mode_retries_without_response_format(self):
        from urllib.error import HTTPError
        cfg = {"model": {"name": "test-model", "temperature": 0.3},
               "provider": {"base_url": "https://gw.example/v1/chat/completions", "api_key_encrypted": "enc"}}
        calls = {"n": 0}

        async def _fake_open(req, timeout=15):
            calls["n"] += 1
            if calls["n"] == 1:
                raise HTTPError(req.full_url, 400, "no json mode", None, None)

            class _Resp:
                def read(self):
                    return json.dumps({"choices": [{"message": {"content": '{"verdict":"FAKE"}'}}]}).encode()

            return _Resp()

        with (patch("app.database.get_active_llm_config", AsyncMock(return_value=cfg)),
              patch("app.security.validate_provider_url", AsyncMock(return_value="https://gw.example/v1/chat/completions")),
              patch("app.llm_analysis.decrypt_key", lambda *_a, **_k: "test-key"),
              patch("app.security.safe_provider_open", _fake_open)):
            result = asyncio.run(llm_second_eye._fast_llm_call({"symbol": "X"}))
        self.assertIn("FAKE", result["text"])
        self.assertEqual(calls["n"], 2)


class VerdictNotificationTests(unittest.TestCase):
    def test_devam_title_short_and_clear(self):
        devam = llm_second_eye.build_verdict_notification(
            _notif(), {"verdict": "DEVAM", "confidence": 80, "reasons": ["cvd_pozitif"],
                       "trap_evidence": [], "summary": None})
        self.assertIn("DEVAM ✓ %80", devam["title"])
        self.assertIn("HEMITRY", devam["title"])
        self.assertIn("Kırılım gerçek görünüyor", devam["message"])
        self.assertIn("cvd_pozitif", devam["message"])
        self.assertEqual(devam["mode"], "llm_ikinci_goz")
        self.assertEqual(devam["source"], "llm_second_eye")
        reasons = json.loads(devam["llm_reasons"])
        self.assertEqual(reasons["reasons"], ["cvd_pozitif"])

    def test_fake_title_and_trap_reason(self):
        fake = llm_second_eye.build_verdict_notification(
            _notif(), {"verdict": "FAKE", "confidence": 65, "reasons": [],
                       "trap_evidence": ["whale_satis"], "summary": "dağıtım var"})
        self.assertIn("FAKE ⚠ %65", fake["title"])
        self.assertIn("Fake kırılım riski", fake["message"])
        self.assertIn("whale_satis", fake["message"])
        self.assertIn("Güven %65", fake["message"])
        self.assertEqual(fake["url"], "/charts?symbol=HEMITRY")

    def test_belirsiz_falls_back_to_summary(self):
        unclear = llm_second_eye.build_verdict_notification(
            _notif(), {"verdict": "BELIRSIZ", "confidence": 40, "reasons": [],
                       "trap_evidence": [], "summary": "kanıt yetersiz"})
        self.assertIn("BELİRSİZ %40", unclear["title"])
        self.assertIn("Yeterli kanıt yok", unclear["message"])
        self.assertIn("kanıt yetersiz", unclear["message"])


if __name__ == "__main__":
    unittest.main()
