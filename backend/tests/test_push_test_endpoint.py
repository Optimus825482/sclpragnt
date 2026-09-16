"""`POST /api/alerts/push-test` — Ayarlar > Uygulama Ayarları test bildirimi.

NEDEN TEST EDİLİR:
    Push zinciri dört katmandan oluşur (backend VAPID anahtarı → kayıtlı abonelik
    → tarayıcı izni → service worker). Herhangi biri bozuksa HİÇBİR bildirim
    gelmez ve hiçbir yerde hata görünmez. Bu uç nokta, kullanıcının tek tuşla
    zinciri sınamasını sağlar; bu yüzden KOPAN KATMANI ADIYLA söylemek ZORUNDADIR
    (HTTP durum kodu + Türkçe `detail`). Sessiz başarı/başarısızlık asıl hataydı.

KİLİTLENEN DAVRANIŞLAR:
    • Yetki: yönetici olmayan istek 401/403 alır — çağrı TÜM aboneliklere
      bildirim gönderir, korumasız olamaz.
    • VAPID_PRIVATE_KEY yok       → 409 + "VAPID_PRIVATE_KEY"
    • Kayıtlı abonelik yok        → 409 + "abonelik"
    • Abonelik var ama teslim yok → 502
    • Gönderim istisnası          → 502
    • Başarı                      → ok=True, sent/total/dead alanları
"""
import asyncio
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _AnonymousRequest:
    """Kimliksiz istek: gerçek `security.require_admin` kapısından geçmeli (401)."""

    headers: dict = {}
    cookies: dict = {}


class PushTestEndpointTests(unittest.TestCase):
    def _invoke(self, push_result):
        """Gerçek fonksiyonu, yalnız yetki/denetim/push sınırında mock'layarak çağır."""
        from app import main as app_main
        from app import alerting as alerting_mod

        with patch.object(app_main, "_require_admin",
                          return_value={"username": "admin", "role": "admin"}), \
             patch.object(app_main, "_session_identity", return_value=("admin", "admin")), \
             patch.object(app_main, "log_user_action", new=AsyncMock()), \
             patch.object(alerting_mod, "deliver_web_push",
                          new=AsyncMock(return_value=push_result)):
            return asyncio.run(app_main.send_test_push_notification(object()))

    def _invoke_expecting_error(self, push_result):
        with self.assertRaises(HTTPException) as ctx:
            self._invoke(push_result)
        return ctx.exception

    # ---- Yetki -----------------------------------------------------------
    def test_anonymous_request_is_rejected(self):
        """Kimliksiz çağrı 401 almalı: bu uç nokta HERKESE bildirim gönderir."""
        from app import main as app_main

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(app_main.send_test_push_notification(_AnonymousRequest()))
        self.assertEqual(401, ctx.exception.status_code)

    # ---- Kopan katmanı adıyla söyleme -----------------------------------
    def test_missing_vapid_key_says_vapid(self):
        exc = self._invoke_expecting_error(
            {"ok": False, "skipped": True, "reason": "vapid_not_configured"})
        self.assertEqual(409, exc.status_code)
        self.assertIn("VAPID_PRIVATE_KEY", exc.detail)

    def test_no_subscribers_says_subscription_missing(self):
        """Abone yokken 'gönderildi' DEMEMELİ — kullanıcı nereye bakacağını bilmeli."""
        exc = self._invoke_expecting_error({"ok": False, "count": 0, "total": 0, "dead_count": 0})
        self.assertEqual(409, exc.status_code)
        self.assertIn("aboneli", exc.detail.lower())

    def test_all_deliveries_failed_is_502(self):
        exc = self._invoke_expecting_error({"ok": False, "count": 0, "total": 2, "dead_count": 0})
        self.assertEqual(502, exc.status_code)

    def test_push_exception_is_502(self):
        exc = self._invoke_expecting_error({"ok": False, "error": "boom"})
        self.assertEqual(502, exc.status_code)
        self.assertIn("boom", exc.detail)

    # ---- Başarı ----------------------------------------------------------
    def test_success_reports_counts(self):
        payload = self._invoke({"ok": True, "count": 3, "total": 4, "dead_count": 1})
        self.assertTrue(payload["ok"])
        self.assertEqual(3, payload["sent"])
        self.assertEqual(4, payload["total"])
        self.assertEqual(1, payload["dead"])
        self.assertTrue(payload["paper_only"])

    # ---- Kapsam ----------------------------------------------------------
    def test_endpoint_is_registered_on_the_app(self):
        """Rota gerçekten kayıtlı olmalı (yol yazım hatası sessiz 404 olurdu)."""
        from app import main as app_main

        paths = {getattr(route, "path", "") for route in app_main.app.routes}
        self.assertIn("/api/alerts/push-test", paths)

    def test_delivers_through_the_shared_push_helper(self):
        """SW'nin okuduğu zarf `deliver_web_push` ile üretilmeli (tek yol)."""
        from app import main as app_main
        from app import alerting as alerting_mod

        captured = {}

        async def _fake(message, **kwargs):
            captured["message"] = message
            captured.update(kwargs)
            return {"ok": True, "count": 1, "total": 1, "dead_count": 0}

        with patch.object(app_main, "_require_admin",
                          return_value={"username": "admin", "role": "admin"}), \
             patch.object(app_main, "_session_identity", return_value=("admin", "admin")), \
             patch.object(app_main, "log_user_action", new=AsyncMock()), \
             patch.object(alerting_mod, "deliver_web_push", new=_fake):
            asyncio.run(app_main.send_test_push_notification(object()))

        # sw.js: `data.title`, `data.body`, `data.url`, `data.tag` okur.
        self.assertIn("title", captured)
        self.assertIn("url", captured)
        self.assertIn("tag", captured)
        self.assertTrue(captured.get("message"), "bildirim gövdesi boş olmamalı")


if __name__ == "__main__":
    unittest.main()
