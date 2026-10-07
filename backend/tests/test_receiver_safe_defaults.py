"""Güvenli VARSAYILAN kilitleri — TR köprü alıcısı + boş yönetici parolası.

2026-10-07 (P1-9 eş görevi): İki canlı-para ayak ayarı düzeltildi:
  1. ``BINANCE_TR_RECEIVER_ENABLED`` / ``BINANCE_TR_BRIDGE_AUTO_TRADE`` artık
     VARSAYILAN KAPALI. Alıcı, harici bir sinyal kaynağının otomatik işlem
     tetiklemesine izin verir; yalnızca placeholder secret varken açık gelmek
     footgun'dur. Bu testler varsayılanın "false" olduğunu kilitler.
  2. ``enforce_admin_password_policy`` üretimde BOŞ parolada da fail-closed.
     Eskiden boş parola "ihlal değil" sayılıyordu → admin kapısı hiç
     kurulmadan prod açılabiliyordu.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from app.config import enforce_admin_password_policy

BACKEND_ROOT = Path(__file__).resolve().parents[1]

_BRIDGE_ENV_KEYS = (
    "BINANCE_TR_RECEIVER_ENABLED",
    "BINANCE_TR_BRIDGE_AUTO_TRADE",
    "BINANCE_TR_BRIDGE_SECRET",
)


class AdminPasswordFailClosedTests(unittest.TestCase):
    """Üretimde boş yönetici parolası başlatmayı ENGELLEMELİ."""

    def test_empty_password_raises_in_production(self):
        with self.assertRaises(RuntimeError):
            enforce_admin_password_policy("", production=True)

    def test_whitespace_only_password_raises_in_production(self):
        with self.assertRaises(RuntimeError):
            enforce_admin_password_policy("   ", production=True)

    def test_empty_password_only_warns_in_development(self):
        # Geliştirmede davranış korunur (yerel kurulumlar kırılmasın).
        self.assertIsNone(enforce_admin_password_policy("", production=False))

    def test_strong_password_passes_in_production(self):
        self.assertIsNone(
            enforce_admin_password_policy("Str0ng-Pass-Word!", production=True))


class BridgeReceiverSafeDefaultsTests(unittest.TestCase):
    """Alıcı ve otomatik-işlem VARSAYILAN KAPALI olmalı (ortam değişkeni yokken)."""

    def _defaults_without_env(self):
        env = {k: v for k, v in os.environ.items() if k not in _BRIDGE_ENV_KEYS}
        code = ("from app.config import config; "
                "print(config.BINANCE_TR_RECEIVER_ENABLED, "
                "config.BINANCE_TR_BRIDGE_AUTO_TRADE)")
        out = subprocess.check_output(
            [sys.executable, "-c", code], env=env, cwd=str(BACKEND_ROOT),
            text=True)
        return out.split()

    def test_receiver_and_auto_trade_default_to_false(self):
        enabled, auto_trade = self._defaults_without_env()
        self.assertEqual(enabled, "False",
                         "BINANCE_TR_RECEIVER_ENABLED varsayılanı KAPALI olmalı")
        self.assertEqual(auto_trade, "False",
                         "BINANCE_TR_BRIDGE_AUTO_TRADE varsayılanı KAPALI olmalı")

    def test_explicit_env_still_enables_the_receiver(self):
        """Açıkça verilirse açılabilmeli (varsayılan değişikliği işlevi kırmaz)."""
        env = {k: v for k, v in os.environ.items() if k not in _BRIDGE_ENV_KEYS}
        env["BINANCE_TR_RECEIVER_ENABLED"] = "true"
        env["BINANCE_TR_BRIDGE_AUTO_TRADE"] = "true"
        code = ("from app.config import config; "
                "print(config.BINANCE_TR_RECEIVER_ENABLED, "
                "config.BINANCE_TR_BRIDGE_AUTO_TRADE)")
        out = subprocess.check_output(
            [sys.executable, "-c", code], env=env, cwd=str(BACKEND_ROOT),
            text=True)
        self.assertEqual(out.split(), ["True", "True"])


if __name__ == "__main__":
    unittest.main()
