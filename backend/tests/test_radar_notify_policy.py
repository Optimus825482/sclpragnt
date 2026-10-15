"""RADAR bildirim politikası kilitleri (2026-10-15 radar iyileştirme).

Kapsam:
  1. Sembol soğuma: aynı sembol pencere içinde ikinci kez bildirilmez, pencere dolunca serbest.
  2. Günlük tavan: sembol başına gün içinde en fazla N bildirim; gün (Europe/Istanbul) değişince sıfırlanır.
  3. Lead-lag (`global`) teyidi ve yalnız-velocity sınıflandırması (saf fonksiyonlar).
  4. Politika kapalıyken (değerler 0) hiçbir bildirim engellenmez.
"""
import datetime as _dt
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import monitoring as mo  # noqa: E402

# 2026-10-15 12:00 Europe/Istanbul (UTC+3) == 09:00 UTC
T0 = _dt.datetime(2026, 10, 15, 9, 0, tzinfo=_dt.timezone.utc).timestamp()


class _PolicyState(unittest.TestCase):
    """Her test temiz durumla çalışır: sözlükler ve sabitler izole edilir."""

    def setUp(self):
        self._patches = [
            patch.object(mo, "_notify_last_sent_at", {}),
            patch.object(mo, "_notify_daily_count", {}),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _set_policy(self, cooldown_min, cap):
        patcher_c = patch.object(mo, "_NOTIFY_SYMBOL_COOLDOWN_MIN", float(cooldown_min))
        patcher_k = patch.object(mo, "_NOTIFY_DAILY_CAP_PER_SYMBOL", int(cap))
        patcher_c.start()
        patcher_k.start()
        self.addCleanup(patcher_c.stop)
        self.addCleanup(patcher_k.stop)


class SymbolCooldownTests(_PolicyState):
    def test_cooldown_blocks_within_window_and_allows_after(self):
        self._set_policy(cooldown_min=120, cap=100)
        self.assertIsNone(mo._notify_policy_allows("BTCTRY", T0))
        mo._notify_policy_record("BTCTRY", T0)
        # 60 dk sonra: pencere içinde → engel, neden Türkçe soğuma metni
        reason = mo._notify_policy_allows("BTCTRY", T0 + 60 * 60)
        self.assertEqual(reason, "sembol soğuma (120 dk)")
        # 121 dk sonra: pencere doldu → serbest
        self.assertIsNone(mo._notify_policy_allows("BTCTRY", T0 + 121 * 60))

    def test_cooldown_is_per_symbol(self):
        self._set_policy(cooldown_min=120, cap=100)
        mo._notify_policy_record("BTCTRY", T0)
        self.assertIsNone(mo._notify_policy_allows("ETHTRY", T0 + 60))

    def test_allows_is_pure_and_does_not_mutate_state(self):
        self._set_policy(cooldown_min=120, cap=2)
        mo._notify_policy_allows("BTCTRY", T0)
        self.assertEqual(mo._notify_last_sent_at, {})
        self.assertEqual(mo._notify_daily_count, {})


class DailyCapTests(_PolicyState):
    def test_daily_cap_blocks_next_send_same_day(self):
        self._set_policy(cooldown_min=0, cap=2)
        mo._notify_policy_record("BTCTRY", T0)
        mo._notify_policy_record("BTCTRY", T0 + 1)
        self.assertEqual(mo._notify_policy_allows("BTCTRY", T0 + 2), "günlük tavan (2)")

    def test_daily_cap_resets_on_istanbul_day_change(self):
        self._set_policy(cooldown_min=0, cap=2)
        mo._notify_policy_record("BTCTRY", T0)
        mo._notify_policy_record("BTCTRY", T0 + 1)
        # 2026-10-16 12:00 İstanbul → yeni gün, sayaç sıfır
        next_day = T0 + 24 * 3600
        self.assertIsNone(mo._notify_policy_allows("BTCTRY", next_day))
        mo._notify_policy_record("BTCTRY", next_day)
        self.assertEqual(mo._notify_daily_count["BTCTRY"], ("2026-10-16", 1))

    def test_day_key_uses_istanbul_midnight(self):
        # 2026-10-14 23:30 İstanbul = 20:30 UTC → 14 Ekim
        before = _dt.datetime(2026, 10, 14, 20, 30, tzinfo=_dt.timezone.utc).timestamp()
        # 2026-10-14 21:30 UTC = 2026-10-15 00:30 İstanbul → 15 Ekim
        after = _dt.datetime(2026, 10, 14, 21, 30, tzinfo=_dt.timezone.utc).timestamp()
        self.assertEqual(mo._notify_day_key(before), "2026-10-14")
        self.assertEqual(mo._notify_day_key(after), "2026-10-15")


class PolicyDisabledTests(_PolicyState):
    def test_zero_values_disable_policy(self):
        self._set_policy(cooldown_min=0, cap=0)
        for i in range(10):
            self.assertIsNone(mo._notify_policy_allows("BTCTRY", T0 + i))
            mo._notify_policy_record("BTCTRY", T0 + i)
        self.assertIsNone(mo._notify_policy_allows("BTCTRY", T0 + 11))

    def test_cooldown_zero_keeps_cap_active(self):
        self._set_policy(cooldown_min=0, cap=1)
        mo._notify_policy_record("BTCTRY", T0)
        self.assertEqual(mo._notify_policy_allows("BTCTRY", T0 + 1), "günlük tavan (1)")

    def test_cap_zero_keeps_cooldown_active(self):
        self._set_policy(cooldown_min=120, cap=0)
        mo._notify_policy_record("BTCTRY", T0)
        self.assertEqual(mo._notify_policy_allows("BTCTRY", T0 + 60), "sembol soğuma (120 dk)")
        self.assertIsNone(mo._notify_policy_allows("BTCTRY", T0 + 60 * 121))


class CandidateClassificationTests(unittest.TestCase):
    def test_leadlag_confirmed_from_unified_sources(self):
        self.assertTrue(mo._is_leadlag_confirmed({"unified_sources": ["velocity", "global"]}))

    def test_leadlag_confirmed_from_sources_list(self):
        self.assertTrue(mo._is_leadlag_confirmed({"sources": ["global"]}))

    def test_leadlag_confirmed_from_kind(self):
        self.assertTrue(mo._is_leadlag_confirmed({"kind": "global"}))

    def test_leadlag_not_confirmed_without_global(self):
        self.assertFalse(mo._is_leadlag_confirmed({"sources": ["velocity"]}))
        self.assertFalse(mo._is_leadlag_confirmed({}))

    def test_velocity_only_true_for_single_velocity_source(self):
        self.assertTrue(mo._is_velocity_only({"sources": ["velocity"]}))
        self.assertTrue(mo._is_velocity_only({"unified_sources": ["velocity"], "kind": "erken"}))

    def test_velocity_only_true_when_no_labels(self):
        # Etiketsiz radar adayı, _build_notification'daki ["velocity"] varsayılanıyla aynıdır.
        self.assertTrue(mo._is_velocity_only({}))

    def test_velocity_only_false_with_confirmation(self):
        self.assertFalse(mo._is_velocity_only({"unified_sources": ["velocity", "jump"]}))
        self.assertFalse(mo._is_velocity_only({"sources": ["global"]}))


if __name__ == "__main__":
    unittest.main()
