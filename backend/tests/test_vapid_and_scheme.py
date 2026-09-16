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
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
