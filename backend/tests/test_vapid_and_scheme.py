"""VAPID anahtar teşhisi + ters proxy şema tespiti (2026-09-16).

Kapsanan hatalar (backend log'undan):
  1. "VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY yapılandırılmamış" uyarısı, frontend'de
     public key varken ve abonelikler kayıtlıyken yanıltıcıydı: backend için
     zorunlu olan TEK anahtar private'tır. Dahası private↔public uyuşmazlığı
     (sessiz 401) hiç kontrol edilmiyordu.
  2. "SCALPER_COOKIE_SECURE=1 ama scheme=http" uyarısı ters proxy arkasında
     YANLIŞ ALARM'dı (TLS proxy'de sonlanır; gerçek şema X-Forwarded-Proto'da).
"""
import base64
import os
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import vapid as vapid_mod       # noqa: E402


def _make_keypair():
    """Gerçek P-256 VAPID çift üret (base64url private + public)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    priv = ec.generate_private_key(ec.SECP256R1())
    raw_priv = priv.private_numbers().private_value.to_bytes(32, "big")
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint)
    enc = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
    return enc(raw_priv), enc(pub)


class VapidDiagnosisTests(unittest.TestCase):
    def test_missing_private_key_reports_problem(self):
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": ""}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertFalse(diag["configured"])
        self.assertFalse(diag["private_set"])
        self.assertTrue(any("VAPID_PRIVATE_KEY" in p for p in diag["problems"]))

    def test_valid_private_derives_public(self):
        priv, pub = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv, "VAPID_PUBLIC_KEY": ""}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertTrue(diag["configured"])
        self.assertTrue(diag["private_valid"])
        self.assertEqual(pub, diag["derived_public_key"], "türetilen public anahtar yanlış")

    def test_matching_public_key_is_accepted(self):
        priv, pub = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv, "VAPID_PUBLIC_KEY": pub}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertTrue(diag["configured"])
        self.assertIs(True, diag["public_key_matches"])
        self.assertEqual([], [p for p in diag["problems"] if "401" in p])

    def test_mismatched_public_key_is_flagged(self):
        """En sinsi hata: private ile frontend public'i farklı → push sessizce 401."""
        priv_a, _ = _make_keypair()
        _, pub_b = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv_a, "VAPID_PUBLIC_KEY": pub_b}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertIs(False, diag["public_key_matches"])
        self.assertTrue(any("401" in p for p in diag["problems"]),
                        "private↔public uyuşmazlığı uyarılmadı")

    def test_invalid_private_key_is_rejected(self):
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "not-a-real-key"}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertFalse(diag["configured"])
        self.assertFalse(diag["private_valid"])
        self.assertTrue(any("geçersiz" in p for p in diag["problems"]))

    def test_unset_public_key_does_not_block_sending(self):
        """public ayarlı olmasa bile push gönderilebilir (yalnızca bilgi notu)."""
        priv, _ = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv, "VAPID_PUBLIC_KEY": ""}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertTrue(diag["configured"], "public yok diye push engellenmemeli")
        self.assertIsNone(diag["public_key_matches"])


class ForwardedSchemeTests(unittest.TestCase):
    """Login uyarısının ters proxy şemasını doğru okuduğunu kilitler."""

    def _scheme(self, headers, raw_scheme):
        forwarded = (headers.get("x-forwarded-proto", "") or "").split(",")[0].strip().lower()
        return forwarded or raw_scheme

    def test_forwarded_https_suppresses_false_alarm(self):
        scheme = self._scheme({"x-forwarded-proto": "https"}, "http")
        self.assertEqual("https", scheme, "proxy arkasında https yanlış okundu")

    def test_raw_http_without_forward_header_still_warns(self):
        scheme = self._scheme({}, "http")
        self.assertEqual("http", scheme)

    def test_multi_value_forwarded_header_uses_first(self):
        scheme = self._scheme({"x-forwarded-proto": "https, http"}, "http")
        self.assertEqual("https", scheme)


class VapidInfoVsProblemTests(unittest.TestCase):
    """DÜZELTME KİLİDİ: "public key ayarlı değil" bir ARIZA DEĞİLDİR.

    Gerçek olay (backend log'u): sistem TAMAMEN sağlıklıyken (private anahtar
    geçerli, 4 abonelik kayıtlı, frontend'de public anahtar var) log'a şu
    WARNING düşüyordu:

        "Monitoring push: VAPID_PUBLIC_KEY ayarlı değil (backend için zorunlu
         değil). Frontend'in NEXT_PUBLIC_VAPID_PUBLIC_KEY değerinin şu olması
         gerekir: BKfhbaii..."

    Bu bir bilgi notuydu ama `problems` listesinde durduğu için
    `monitoring_background_loop` onu `logger.warning` ile basıyordu — yani
    çalışan bir sistemde korkutucu bir uyarı. Ayrım artık yapısal:
        problems = aksiyon gerektiren gerçek arızalar
        info     = durum notları (INFO seviyesinde loglanır)
    """

    def test_unset_public_key_is_info_not_problem(self):
        priv, pub = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv, "VAPID_PUBLIC_KEY": ""}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertTrue(diag["configured"], "public yok diye push engellenmemeli")
        self.assertEqual([], diag["problems"],
                         "sağlıklı sistem 'problem' üretmemeli (yanlış alarm)")
        self.assertTrue(diag["info"], "bilgi notu kaybolmamalı")
        self.assertTrue(any(pub in note for note in diag["info"]),
                        "doğru public anahtar bilgi notunda verilmeli")

    def test_effective_public_key_is_the_derived_one(self):
        """Tarayıcının abone olması gereken anahtar HER ZAMAN private'dan türetilendir.

        `alerting._send_push` pywebpush'a yalnızca `vapid_private_key` verir →
        kütüphane public'i kendi türetir. Bu yüzden `VAPID_PUBLIC_KEY` env
        değişkeni bu karşılaştırmada rol oynamaz.
        """
        priv, pub = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv, "VAPID_PUBLIC_KEY": ""}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertEqual(pub, diag["effective_public_key"])

    def test_effective_key_stays_derived_when_configured_public_mismatches(self):
        """Uyuşmayan env değeri 'efektif' anahtar SAYILMAMALI (yoksa panel yanlış karşılaştırır)."""
        priv_a, _ = _make_keypair()
        _, pub_b = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv_a, "VAPID_PUBLIC_KEY": pub_b}, clear=False):
            diag = vapid_mod.diagnose_vapid()
        self.assertIs(False, diag["public_key_matches"])
        self.assertNotEqual(pub_b, diag["effective_public_key"])
        self.assertEqual(diag["derived_public_key"], diag["effective_public_key"])

    def test_no_warning_logged_for_info_only_config(self):
        """Sağlıklı yapılandırmada log'a WARNING düşmemeli — yanlış alarmın asıl kilidi."""
        priv, _ = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv, "VAPID_PUBLIC_KEY": ""}, clear=False):
            with patch.object(vapid_mod.logger, "info"):
                with patch.object(vapid_mod.logger, "warning") as warn:
                    vapid_mod.log_vapid_diagnosis()
        self.assertFalse(warn.called, f"sağlıklı sistemde beklenmeyen uyarı: {warn.call_args_list}")

    def test_missing_private_key_still_warns(self):
        """Gerçek arıza (push gönderilemez) uyarı üretmeye DEVAM etmeli."""
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "", "VAPID_PUBLIC_KEY": ""}, clear=False):
            with patch.object(vapid_mod.logger, "info"):
                with patch.object(vapid_mod.logger, "warning") as warn:
                    vapid_mod.log_vapid_diagnosis()
        self.assertTrue(warn.called, "gerçek arıza artık uyarı üretmiyor")


class PushHealthPayloadTests(unittest.TestCase):
    """Panel sözleşmesi: `/state.push.vapid_public_key` frontend'e ULAŞMALI.

    Uyuşma tespiti yalnızca iki değeri birden görebilen tarafta (frontend) yapılır;
    backend kendi env'ini frontend'in BUILD argümanıyla karşılaştıramaz. Bu yüzden
    backend'in türettiği anahtarı yayınlaması ŞARTTIR — bu test o sözleşmeyi kilitler.
    """

    def test_push_health_exposes_effective_key(self):
        import asyncio
        from app.routers import monitoring as mon

        priv, pub = _make_keypair()
        with patch.dict(os.environ, {"VAPID_PRIVATE_KEY": priv, "VAPID_PUBLIC_KEY": ""}, clear=False):
            with patch.object(mon.database, "count_push_subscriptions",
                              new=AsyncMock(return_value=3)):
                payload = asyncio.run(mon._push_health_safe())
        self.assertEqual(3, payload["subscribers"])
        self.assertTrue(payload["backend_vapid_configured"])
        self.assertEqual(pub, payload["vapid_public_key"],
                         "türetilen public anahtar panele ulaşmıyor")

    def test_push_health_survives_vapid_failure(self):
        """Teşhis patlarsa state yanıtı BOZULMAMALI (panel sağlığı düşmesin)."""
        import asyncio
        from app.routers import monitoring as mon

        with patch.object(mon.database, "count_push_subscriptions",
                          new=AsyncMock(side_effect=RuntimeError("db down"))):
            payload = asyncio.run(mon._push_health_safe())
        self.assertEqual(0, payload["subscribers"])
        self.assertIsNone(payload["vapid_public_key"])


if __name__ == "__main__":
    unittest.main()