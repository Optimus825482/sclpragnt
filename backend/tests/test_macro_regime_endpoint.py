"""`/api/signals/macro-regime` sözleşmesi — kullanıcı arayüzündeki 'düşüş rejimi' bandı buna dayanır.

Bant yalnız şu alanlara bakar: shield_enabled, regime_shield_active, btc_price, btc_1h_ema200.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.config import config
from app.routers import snapback


def _call(compass: dict, enabled: bool = True) -> dict:
    with patch.object(snapback, "get_btc_compass", AsyncMock(return_value=compass)), \
         patch.object(snapback, "get_macro_sentiment", AsyncMock(return_value={})), \
         patch.object(config, "BTC_REGIME_SHIELD_ENABLED", enabled, create=True):
        return asyncio.run(snapback.get_macro_regime_status())


class MacroRegimeContractTests(unittest.TestCase):
    def test_shield_active_when_btc_below_ema200(self):
        out = _call({"is_btc_above_ema200": False, "btc_price": 4072000.0, "btc_1h_ema200": 4076155.36})
        self.assertTrue(out["shield_enabled"])
        self.assertTrue(out["regime_shield_active"])
        self.assertEqual(4072000.0, out["btc_price"])
        self.assertEqual(4076155.36, out["btc_1h_ema200"])

    def test_not_active_when_btc_above_ema200(self):
        out = _call({"is_btc_above_ema200": True, "btc_price": 4100000.0, "btc_1h_ema200": 4076155.36})
        self.assertFalse(out["regime_shield_active"])

    def test_disabled_flag_overrides_even_when_below(self):
        out = _call({"is_btc_above_ema200": False, "btc_price": 1.0, "btc_1h_ema200": 2.0}, enabled=False)
        self.assertFalse(out["shield_enabled"])
        self.assertFalse(out["regime_shield_active"])

    def test_missing_data_defaults_to_not_active(self):
        out = _call({})
        self.assertFalse(out["regime_shield_active"])


if __name__ == "__main__":
    unittest.main()
