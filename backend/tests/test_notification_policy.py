"""2026-10-16 (sinyal politikası): bildirim politikası kilit testleri."""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database, notification_policy as np_  # noqa: E402
from app.config import config  # noqa: E402
from tests.test_m4_database_fixes import _RoutedConn, _patched_run_db  # noqa: E402


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        np_.reset_stats()
        # 2026-10-17: bu sınıf mod/skor katmanlarını sınar; teyit kuralı ayrı sınıfta.
        _p = mock.patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", False)
        _p.start()
        self.addCleanup(_p.stop)

    def test_defaults_exist(self):
        self.assertTrue(config.RADAR_NOTIFY_POLICY_ENABLED)
        self.assertEqual(config.RADAR_NOTIFY_DISABLED_MODES, "notr,v_donusu,llm_ikinci_goz")
        self.assertEqual(config.RADAR_NOTIFY_UNIFIED_MIN_SCORE, 95.0)

    def test_disabled_modes_blocked(self):
        for mode in ("notr", "v_donusu", "llm_ikinci_goz", "NOTR"):
            self.assertIn("mod devre dışı", np_.evaluate({"mode": mode, "score": 99}))
        self.assertEqual(np_.evaluate({"mode": "notr"}), "mod devre dışı: notr")

    def test_kept_modes_pass(self):
        for mode in ("trend_devam", "global_lead_lag", "auto", "yukselis"):
            self.assertIsNone(np_.evaluate({"mode": mode, "score": 10}))

    def test_empty_mode_not_blocked(self):
        self.assertIsNone(np_.evaluate({"mode": None, "score": 1}))
        self.assertIsNone(np_.evaluate({"mode": "", "score": 1}))
        self.assertIsNone(np_.evaluate({"score": 1}))

    def test_unified_floor(self):
        self.assertEqual(np_.evaluate({"mode": "unified", "score": 88.0}),
                         "unified skor tabanı altı (88.0 < 95)")
        self.assertIsNotNone(np_.evaluate({"mode": "unified", "score": 94.9}))
        self.assertIsNone(np_.evaluate({"mode": "unified", "score": 95}))
        self.assertIsNone(np_.evaluate({"mode": "unified", "score": 100}))

    def test_unified_legacy_or_missing_score_not_blocked(self):
        self.assertIsNone(np_.evaluate({"mode": "unified", "score": 22250}))
        self.assertIsNone(np_.evaluate({"mode": "unified", "score": None}))
        self.assertIsNone(np_.evaluate({"mode": "unified", "score": "abc"}))

    def test_unified_floor_off(self):
        with mock.patch.object(config, "RADAR_NOTIFY_UNIFIED_MIN_SCORE", 0.0):
            self.assertIsNone(np_.evaluate({"mode": "unified", "score": 10}))

    def test_policy_disabled_passthrough(self):
        with mock.patch.object(config, "RADAR_NOTIFY_POLICY_ENABLED", False):
            self.assertIsNone(np_.evaluate({"mode": "notr", "score": 1}))
            self.assertIsNone(np_.evaluate({"mode": "unified", "score": 1}))

    def test_override_modes(self):
        with mock.patch.object(config, "RADAR_NOTIFY_DISABLED_MODES", "trend_devam"):
            self.assertIsNotNone(np_.evaluate({"mode": "trend_devam"}))
            self.assertIsNone(np_.evaluate({"mode": "notr"}))
        with mock.patch.object(config, "RADAR_NOTIFY_DISABLED_MODES", ""):
            self.assertIsNone(np_.evaluate({"mode": "notr"}))

    def test_env_parsed_into_config(self):
        import subprocess
        code = ("from app.config import Config as C;"
                "print(C.RADAR_NOTIFY_DISABLED_MODES, C.RADAR_NOTIFY_UNIFIED_MIN_SCORE,"
                " C.RADAR_NOTIFY_POLICY_ENABLED)")
        env = dict(os.environ, RADAR_NOTIFY_DISABLED_MODES="x,y",
                   RADAR_NOTIFY_UNIFIED_MIN_SCORE="90", RADAR_NOTIFY_POLICY_ENABLED="0")
        root = os.path.join(os.path.dirname(__file__), "..")
        out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "x,y 90.0 False", out.stderr)

    def test_apply_and_stats(self):
        entries = [{"symbol": "A", "mode": "trend_devam", "score": 70},
                   {"symbol": "B", "mode": "notr", "score": 80},
                   {"symbol": "C", "mode": "unified", "score": 90}]
        kept, blocked = np_.apply(entries)
        self.assertEqual([e["symbol"] for e in kept], ["A"])
        self.assertEqual([e["symbol"] for e, _ in blocked], ["B", "C"])
        st = np_.get_stats()
        self.assertEqual((st["kept"], st["blocked"]), (1, 2))
        self.assertEqual(st["recent"][0]["symbol"], "B")


class SinkTests(unittest.TestCase):
    def setUp(self):
        _p = mock.patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", False)
        _p.start()
        self.addCleanup(_p.stop)
        np_.reset_stats()

    @staticmethod
    def _row(symbol, mode, score):
        return {"symbol": symbol, "mode": mode, "score": score, "message": "m",
                "title": "t", "target_pct": 2.0, "price": 1.0, "expected_price": 1.02,
                "horizon_minutes": 5, "detected_at": 100.0}

    def test_only_kept_entries_persisted(self):
        conn = _RoutedConn(default=[(7,)])
        rows = [self._row("OK", "trend_devam", 70), self._row("NOTR", "notr", 80),
                self._row("UNI", "unified", 88.0), self._row("UNI95", "unified", 95.0)]
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            saved = asyncio.run(database.save_monitoring_notifications(rows))
        self.assertEqual(saved, 2)
        inserted = [p[0] for sql, p in conn.calls if "INSERT INTO monitoring_notifications" in sql]
        self.assertEqual(inserted, ["OK", "UNI95"])
        self.assertIn("mod devre dışı", rows[1]["policy_blocked"])
        self.assertIn("unified skor tabanı", rows[2]["policy_blocked"])
        self.assertNotIn("policy_blocked", rows[0])

    def test_all_blocked_returns_zero_without_db(self):
        conn = _RoutedConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            saved = asyncio.run(database.save_monitoring_notifications(
                [self._row("N", "notr", 80)]))
        self.assertEqual(saved, 0)
        self.assertEqual(conn.calls, [])

    def test_disabled_flag_persists_everything(self):
        conn = _RoutedConn(default=[(1,)])
        with mock.patch.object(config, "RADAR_NOTIFY_POLICY_ENABLED", False), \
                mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            saved = asyncio.run(database.save_monitoring_notifications(
                [self._row("N", "notr", 80), self._row("U", "unified", 10)]))
        self.assertEqual(saved, 2)

    def test_policy_error_fails_open(self):
        conn = _RoutedConn(default=[(1,)])
        with mock.patch.object(np_, "apply", side_effect=RuntimeError("x")), \
                mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            saved = asyncio.run(database.save_monitoring_notifications(
                [self._row("N", "notr", 80)]))
        self.assertEqual(saved, 1)


if __name__ == "__main__":
    unittest.main()


class ConfirmRuleTests(unittest.TestCase):
    """2026-10-17: TEYİT KURALI (≥2 kaynak ∧ velocity ∧ mod ≠ unified) ve gölge kayıt."""

    def test_defaults(self):
        self.assertTrue(config.RADAR_NOTIFY_CONFIRM_RULE_ENABLED)
        self.assertEqual(config.RADAR_NOTIFY_MIN_SOURCES, 2)
        self.assertEqual(config.RADAR_NOTIFY_REQUIRED_SOURCE, "velocity")
        self.assertEqual(config.RADAR_NOTIFY_CONFIRM_EXCLUDED_MODES, "unified")
        self.assertTrue(config.RADAR_NOTIFY_SHADOW_RULE_ENABLED)

    def test_passes_with_velocity_and_second_source(self):
        e = {"mode": "trend_devam", "score": 90, "sources": ["velocity", "jump"]}
        self.assertIsNone(np_.evaluate(e))
        self.assertIsNone(np_.evaluate({**e, "sources": '["early","jump","velocity"]'}))
        self.assertIsNone(np_.evaluate({**e, "sources": "velocity,rising"}))

    def test_single_source_blocked(self):
        self.assertEqual(np_.evaluate({"mode": "trend_devam", "sources": ["velocity"]}),
                         "teyit yetersiz (1 < 2 kaynak)")
        self.assertEqual(np_.evaluate({"mode": "yukselis", "sources": ["rising"]}),
                         "teyit yetersiz (1 < 2 kaynak)")
        self.assertEqual(np_.evaluate({"mode": "trend_devam"}), "teyit yetersiz (0 < 2 kaynak)")
        # aynı kaynağın tekrarı tek sayılır
        self.assertIn("teyit yetersiz", np_.evaluate({"mode": "trend_devam", "sources": ["velocity", "VELOCITY"]}))

    def test_without_velocity_blocked(self):
        self.assertEqual(np_.evaluate({"mode": "trend_devam", "sources": ["jump", "early", "rising"]}),
                         "teyit kuralı: velocity kaynağı yok")

    def test_unified_mode_excluded(self):
        e = {"mode": "unified", "score": 99, "sources": ["velocity", "jump", "early"]}
        self.assertEqual(np_.evaluate(e), "teyit kuralı: mod unified hariç")

    def test_rule_flags(self):
        e = {"mode": "trend_devam", "sources": ["velocity"]}
        with mock.patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", False):
            self.assertIsNone(np_.evaluate(e))
        with mock.patch.object(config, "RADAR_NOTIFY_MIN_SOURCES", 1):
            self.assertIsNone(np_.evaluate(e))
        with mock.patch.object(config, "RADAR_NOTIFY_REQUIRED_SOURCE", ""):
            self.assertIsNone(np_.evaluate({"mode": "trend_devam", "sources": ["jump", "rising"]}))
        with mock.patch.object(config, "RADAR_NOTIFY_POLICY_ENABLED", False):
            self.assertIsNone(np_.evaluate(e))

    def test_disabled_mode_reason_takes_precedence(self):
        self.assertEqual(np_.evaluate({"mode": "notr", "sources": ["velocity", "jump"]}), "mod devre dışı: notr")

    def test_shadow_rows_record_live_decision(self):
        live_ok = {"symbol": "eratry", "mode": "trend_devam", "sources": ["velocity", "jump"], "price": 3.4,
                   "target_pct": 2.5, "horizon_minutes": 15, "score": 90, "detected_at": 100.0}
        live_blocked = {"symbol": "ATRY", "mode": "trend_devam", "sources": ["jump", "early"], "detected_at": 101.0}
        not_shadow = {"symbol": "XTRY", "mode": "unified", "sources": ["velocity", "jump"], "detected_at": 102.0}
        single = {"symbol": "YTRY", "mode": "trend_devam", "sources": ["velocity"], "detected_at": 103.0}
        rows = np_.shadow_rows([live_ok, live_blocked, not_shadow, single])
        self.assertEqual([r["symbol"] for r in rows], ["ERATRY", "ATRY"])
        self.assertEqual(rows[0]["live_blocked_reason"], "")
        self.assertEqual(rows[1]["live_blocked_reason"], "teyit kuralı: velocity kaynağı yok")
        self.assertEqual(rows[0]["sources"], "jump,velocity")
        self.assertEqual({r["shadow_rule"] for r in rows}, {"ge2_trend_devam"})
        with mock.patch.object(config, "RADAR_NOTIFY_SHADOW_RULE_ENABLED", False):
            self.assertEqual(np_.shadow_rows([live_ok]), [])


class SingleSourceTierTests(unittest.TestCase):
    """2026-10-18 İKİNCİ KADEME: tek kaynaklı Hız, skor ≥ RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE → push, başlık öneki."""

    def setUp(self):
        self._p = [
            mock.patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", True),
            mock.patch.object(config, "RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE", 85.0),
        ]
        for x in self._p:
            x.start()

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def test_default_floor(self):
        self.assertEqual(config.RADAR_NOTIFY_HEARTBEAT_MINUTES, 15)   # 2026-10-18: 30 → 15 (kullanıcı)

    def test_velocity_only_high_score_passes_with_prefix(self):
        e = {"mode": "trend_devam", "score": 91.0, "sources": ["velocity"], "title": "ABCTRY +%2 potansiyel"}
        self.assertIsNone(np_.evaluate(e))
        self.assertEqual(e["notify_tier"], np_.TIER_SINGLE)
        self.assertEqual(e["title"], "TEK KAYNAK · ABCTRY +%2 potansiyel")
        np_.evaluate(e)  # tekrar değerlendirme öneki ikilemez
        self.assertEqual(e["title"], "TEK KAYNAK · ABCTRY +%2 potansiyel")

    def test_boundary_and_low_score_blocked(self):
        ok = {"mode": "trend_devam", "score": 85.0, "sources": ["velocity"], "title": "t"}
        self.assertIsNone(np_.evaluate(ok))
        low = {"mode": "trend_devam", "score": 84.9, "sources": ["velocity"], "title": "t"}
        self.assertEqual(np_.evaluate(low), "teyit yetersiz (1 < 2 kaynak)")
        self.assertNotIn("notify_tier", low)
        self.assertEqual(low["title"], "t")

    def test_other_single_sources_and_modes_still_blocked(self):
        self.assertIsNotNone(np_.evaluate({"mode": "trend_devam", "score": 95, "sources": ["rising"], "title": "t"}))
        self.assertIsNotNone(np_.evaluate({"mode": "trend_devam", "score": 95, "sources": ["jump"], "title": "t"}))
        self.assertEqual(np_.evaluate({"mode": "notr", "score": 95, "sources": ["velocity"], "title": "t"}),
                         "mod devre dışı: notr")
        self.assertIsNotNone(np_.evaluate({"mode": "unified", "score": 99, "sources": ["velocity"], "title": "t"}))
        # iki kaynak ama velocity yok → kademe aşmaz
        self.assertEqual(np_.evaluate({"mode": "trend_devam", "score": 99, "sources": ["jump", "early"], "title": "t"}),
                         "teyit kuralı: velocity kaynağı yok")

    def test_floor_zero_disables_tier(self):
        with mock.patch.object(config, "RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE", 0.0):
            self.assertEqual(np_.evaluate({"mode": "trend_devam", "score": 99, "sources": ["velocity"], "title": "t"}),
                             "teyit yetersiz (1 < 2 kaynak)")

    def test_raw_scale_score_not_tiered(self):
        # panel ölçeği üstü (ham skor) bilinmeyen ölçek → kademe uygulanmaz
        self.assertIsNotNone(np_.evaluate({"mode": "trend_devam", "score": 1500, "sources": ["velocity"], "title": "t"}))


class HeartbeatTests(unittest.TestCase):
    """2026-10-18 SESSİZLİK NABZI: süre dolduysa yalnız teyit nedeniyle takılan en yüksek skorlu aday."""

    def setUp(self):
        self._p = [
            mock.patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", True),
            mock.patch.object(config, "RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE", 0.0),
            mock.patch.object(config, "RADAR_NOTIFY_HEARTBEAT_MINUTES", 30),
        ]
        for x in self._p:
            x.start()

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def _blocked(self):
        es = [
            {"symbol": "A", "mode": "trend_devam", "score": 80, "sources": ["velocity"], "title": "a"},
            {"symbol": "B", "mode": "trend_devam", "score": 92, "sources": ["jump", "early"], "title": "b"},
            {"symbol": "C", "mode": "unified", "score": 99, "sources": ["velocity", "jump"], "title": "c"},
            {"symbol": "D", "mode": "notr", "score": 99, "sources": ["velocity"], "title": "d"},
        ]
        np_.precheck(es)
        self.assertTrue(all(e.get("policy_blocked") for e in es))
        return es

    def test_picks_highest_score_among_confirm_blocked_only(self):
        es = self._blocked()
        pick = np_.heartbeat_pick(es, now=10_000.0, last_push_ts=10_000.0 - 31 * 60)
        self.assertEqual(pick["symbol"], "B")   # C (unified hariç) ve D (kapalı mod) aday değil

    def test_not_due_or_no_counter(self):
        es = self._blocked()
        self.assertIsNone(np_.heartbeat_pick(es, now=10_000.0, last_push_ts=10_000.0 - 29 * 60))
        self.assertIsNone(np_.heartbeat_pick(es, now=10_000.0, last_push_ts=None))
        with mock.patch.object(config, "RADAR_NOTIFY_HEARTBEAT_MINUTES", 0):
            self.assertIsNone(np_.heartbeat_pick(es, now=10_000.0, last_push_ts=0.0))

    def test_marked_pick_passes_sink_with_prefix(self):
        es = self._blocked()
        pick = np_.heartbeat_pick(es, now=10_000.0, last_push_ts=0.0)
        np_.mark_tier(pick, np_.TIER_HEARTBEAT)
        self.assertEqual(pick["title"], "TEYİTSİZ · b")
        self.assertIsNone(np_.evaluate(pick))          # lavabo yeniden bloklamaz
        kept, blocked = np_.apply([pick] + [e for e in es if e is not pick])
        self.assertEqual([k["symbol"] for k in kept], ["B"])
        self.assertEqual(len(blocked), 3)


class HeartbeatCandidateTests(unittest.TestCase):
    """2026-10-18 (düzeltme): nabız adayı tarama listesinden; süre hem son push hem son denemeye bakar."""

    def setUp(self):
        self._p = [mock.patch.object(config, "RADAR_NOTIFY_HEARTBEAT_MINUTES", 15),
                   mock.patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", True)]
        for x in self._p:
            x.start()

    def tearDown(self):
        for x in reversed(self._p):
            x.stop()

    def test_due(self):
        now = 100_000.0
        self.assertTrue(np_.heartbeat_due(now, now - 16 * 60))
        self.assertFalse(np_.heartbeat_due(now, now - 14 * 60))
        self.assertFalse(np_.heartbeat_due(now, None))
        self.assertFalse(np_.heartbeat_due(now, now - 30 * 60, last_attempt_ts=now - 5 * 60))
        self.assertTrue(np_.heartbeat_due(now, now - 30 * 60, last_attempt_ts=now - 16 * 60))
        with mock.patch.object(config, "RADAR_NOTIFY_HEARTBEAT_MINUTES", 0):
            self.assertFalse(np_.heartbeat_due(now, 0.0))

    def test_candidate_pick_filters_and_takes_max(self):
        cands = [
            {"symbol": "A", "mode": "trend_devam", "price": 1.0, "s": 50},
            {"symbol": "B", "mode": "trend_devam", "price": 1.0, "s": 80},
            {"symbol": "C", "mode": "notr", "price": 1.0, "s": 99},
            {"symbol": "D", "mode": "unified", "price": 1.0, "s": 99},
            {"symbol": "E", "mode": "trend_devam", "price": 0, "s": 99},
            {"symbol": "F", "mode": "trend_devam", "price": 1.0, "s": 95},
        ]
        pick = np_.heartbeat_candidate_pick(cands, lambda c: c["s"], skip_symbols={"F"})
        self.assertEqual("B", pick["symbol"])
        self.assertIsNone(np_.heartbeat_candidate_pick([], lambda c: 1))
        self.assertIsNone(np_.heartbeat_candidate_pick([{"symbol": "X", "mode": "trend_devam", "price": 1.0}], lambda c: float("nan")))


class HeartbeatRiskBlockTests(unittest.TestCase):
    """2026-10-18: risk nedeniyle elenmiş tarama satırları nabız adayı olamaz; eşik/yapı nedenleri olabilir."""

    def setUp(self):
        self._p = mock.patch.object(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", True)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_prefix_filter(self):
        rows = [{"symbol": f"R{i}", "mode": "trend_devam", "price": 1.0, "s": 90 - i, "block_reason": r}
                for i, r in enumerate(["asiri_spread:2%", "ust_fitil_tuzagi:x", "mfi_asiri_alim:90", "rsi_asiri_satim:10",
                                       "likidite_tabani:5", "atr_yetersiz:0.1%", "yapisal_teyit_yok", "", None])]
        pick = np_.heartbeat_candidate_pick(rows, lambda c: c["s"])
        self.assertEqual("R5", pick["symbol"])          # ilk uygun: atr_yetersiz (risk önekleri atlanır)
        self.assertEqual(5, len([r for r in rows if str(r["block_reason"] or "").startswith(np_.HEARTBEAT_RISK_BLOCK_PREFIXES)]))
