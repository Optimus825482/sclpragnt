"""Güvenli VARSAYILAN kilidi — boş yönetici parolası (üretimde fail-closed).

2026-10-07 (P1-9 eş görevi): ``enforce_admin_password_policy`` üretimde BOŞ
parolada da fail-closed. Eskiden boş parola "ihlal değil" sayılıyordu → admin
kapısı hiç kurulmadan prod açılabiliyordu.

NOT (2026-10-12): Harici Global→TR lead-lag köprüsü kaldırıldığı için alıcı
varsayılan testleri (`BINANCE_TR_RECEIVER_ENABLED` / `*_AUTO_TRADE`) kaldırıldı.
"""
import unittest

from app.config import enforce_admin_password_policy


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


# NOT (2026-10-12): Harici Global→TR lead-lag köprüsü kaldırıldığı için
# `BridgeReceiverSafeDefaultsTests` (BINANCE_TR_RECEIVER_ENABLED / *_AUTO_TRADE
# varsayılanları) SİLİNDİ — bu config anahtarları artık yok. Global erken-tespit
# katmanı v4 içinde üretilir (`global_radar.py`).


if __name__ == "__main__":
    unittest.main()
