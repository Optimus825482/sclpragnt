"""Ayarlar > MA BUY: /api/config alanları, doğrulama ve kalıcılık (2026-10-18)."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import ma_buy_notify, main
from app.config import config


class NormalizeTests(unittest.TestCase):
    def test_timeframes_are_validated_and_ordered(self):
        self.assertEqual(ma_buy_notify.normalize_setting("ma_buy_notify_timeframes", "5m, 1m"), "1m,5m")
        self.assertEqual(ma_buy_notify.normalize_setting("ma_buy_notify_timeframes", ""), "")
        with self.assertRaises(ValueError):
            ma_buy_notify.normalize_setting("ma_buy_notify_timeframes", "1m,4h")

    def test_target_pct_format(self):
        self.assertEqual(ma_buy_notify.normalize_setting("ma_buy_target_pct", "1m:1.0, 5m:1.50"), "1m:1,5m:1.5")
        for bad in ("1m:0", "1m:x", "4h:1", "1m:25"):
            with self.assertRaises(ValueError):
                ma_buy_notify.normalize_setting("ma_buy_target_pct", bad)

    def test_float_bounds(self):
        self.assertEqual(ma_buy_notify.normalize_setting("ma_buy_notify_cooldown_min", "30"), 30.0)
        with self.assertRaises(ValueError):
            ma_buy_notify.normalize_setting("ma_buy_notify_max_age_sec", 5)


class ConfigApiTests(unittest.TestCase):
    def setUp(self):
        self._saved = {a: getattr(config, a) for a in ma_buy_notify.SETTINGS_FIELDS.values()}

    def tearDown(self):
        for attr, val in self._saved.items():
            setattr(config, attr, val)

    def test_get_config_exposes_ma_buy_fields(self):
        data = asyncio.run(main.get_config())
        for key in ma_buy_notify.SETTINGS_FIELDS:
            self.assertIn(key, data)

    def test_update_applies_and_persists(self):
        stored = {}

        async def set_setting(key, value):
            stored[key] = value

        payload = {"ma_buy_notify_enabled": False, "ma_buy_auto_paper_enabled": "false",
                   "ma_buy_notify_timeframes": "5m", "ma_buy_notify_cooldown_min": 30,
                   "ma_buy_target_pct": "1m:0.8,5m:2"}
        with patch.object(main.database, "get_llm_setting", AsyncMock(return_value="{}")), \
                patch.object(main.database, "set_llm_setting", side_effect=set_setting), \
                patch.object(main, "log_user_action", AsyncMock(), create=True):
            try:
                asyncio.run(main._apply_config_update(payload))
            except Exception:  # noqa: BLE001 — ayar uygulandıktan sonraki yan işler (piyasa onarımı vb.) test dışı
                pass
        self.assertFalse(config.MA_BUY_NOTIFY_ENABLED)
        self.assertFalse(config.MA_BUY_AUTO_PAPER_ENABLED)
        self.assertEqual(config.MA_BUY_NOTIFY_TIMEFRAMES, "5m")
        self.assertEqual(config.MA_BUY_NOTIFY_COOLDOWN_MIN, 30.0)
        self.assertEqual(config.MA_BUY_TARGET_PCT, "1m:0.8,5m:2")
        persisted = __import__("json").loads(stored["runtime_config"])
        self.assertEqual(persisted["ma_buy_notify_timeframes"], "5m")
        self.assertIs(persisted["ma_buy_notify_enabled"], False)

    def test_invalid_value_is_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(main._apply_config_update({"ma_buy_notify_timeframes": "2h"}))


if __name__ == "__main__":
    unittest.main()
