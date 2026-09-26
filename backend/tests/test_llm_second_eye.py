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

    def test_db_setting_off_skips_llm(self):
        chat = AsyncMock(return_value={})
        with self._patch_db("0"), patch("app.llm_analysis.chat", chat):
            result = asyncio.run(llm_second_eye.evaluate(_notif()))
        self.assertIsNone(result)
        chat.assert_not_awaited()

    def test_provider_missing_sets_backoff(self):
        chat = AsyncMock(return_value={"enabled": False, "status": "disabled", "text": None})
        with self._patch_db("1"), patch("app.llm_analysis.chat", chat):
            first = asyncio.run(llm_second_eye.evaluate(_notif()))
            self.assertIsNone(first)
            # backoff penceresi içinde ikinci çağrı LLM'e HİÇ gitmez
            second = asyncio.run(llm_second_eye.evaluate(_notif(score=95.0)))
        self.assertIsNone(second)
        self.assertEqual(chat.await_count, 1)
        self.assertGreater(llm_second_eye._state["provider_missing_until"], 0)

    def test_successful_verdict_then_cooldown(self):
        good = {"enabled": True, "text": json.dumps(
            {"verdict": "DEVAM", "confidence": 77, "reasons": ["cvd_pozitif"], "trap_evidence": [],
             "summary": "akış destekliyor"})}
        chat = AsyncMock(return_value=good)
        with self._patch_db("1"), patch("app.llm_analysis.chat", chat):
            envelope = asyncio.run(llm_second_eye.evaluate(_notif()))
            self.assertIsNotNone(envelope)
            self.assertEqual(envelope["llm_verdict"], "DEVAM")
            again = asyncio.run(llm_second_eye.evaluate(_notif(score=95.0)))
        self.assertIsNone(again)  # sembol cooldown'u
        self.assertEqual(chat.await_count, 1)
        self.assertEqual(llm_second_eye._state["evaluated"], 1)

    def test_schema_violation_returns_none(self):
        bad = {"enabled": True, "text": "karar veremedim ama JSON da yazmadım"}
        chat = AsyncMock(return_value=bad)
        with self._patch_db("1"), patch("app.llm_analysis.chat", chat):
            result = asyncio.run(llm_second_eye.evaluate(_notif()))
        self.assertIsNone(result)
        self.assertIn("şemasına uymadı", str(llm_second_eye._state["last_error"]))


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
