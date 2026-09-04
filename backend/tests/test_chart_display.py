import unittest
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException


class ChartDisplayPatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_display_patch_merges_without_clobber(self):
        """Görünüm tercihi PATCH'i mevcut ayarları ezmeden merge eder.

        localStorage kaldırıldığından toggle'lar anlık bu endpoint'e yazılır;
        indikatör/interval/paneHeights ve diğer display alanları korunmalı
        (2026-09-04).
        """
        from app.main import patch_chart_display
        from app import database

        calls = []

        async def fake_get(sym):
            return {"interval": "5m", "display": {"showPositions": True, "showPressure": False}}

        async def fake_save(sym, data):
            calls.append((sym, data))

        with patch.object(database, "get_chart_settings", side_effect=fake_get), \
             patch.object(database, "save_chart_settings", side_effect=fake_save):
            result = await patch_chart_display("BTCTRY", {"display": {"showMonitoringLines": False}})
        self.assertTrue(result["saved"])
        __, data = calls[0]
        self.assertEqual(data["interval"], "5m")                        # dokunulmadi
        self.assertEqual(data["display"]["showPositions"], True)        # eski korundu
        self.assertEqual(data["display"]["showPressure"], False)        # eski korundu
        self.assertEqual(data["display"]["showMonitoringLines"], False)  # yeni eklendi

    async def test_display_patch_creates_when_missing(self):
        """Kayıt hiç yoksa display'den geçerli bir kayıt oluşturur."""
        from app.main import patch_chart_display
        from app import database

        calls = []

        async def fake_get(sym):
            return None

        async def fake_save(sym, data):
            calls.append((sym, data))

        with patch.object(database, "get_chart_settings", side_effect=fake_get), \
             patch.object(database, "save_chart_settings", side_effect=fake_save):
            result = await patch_chart_display("XYZTRY", {"display": {"showMonitoringLines": True}})
        self.assertTrue(result["saved"])
        __, data = calls[0]
        self.assertEqual(data.get("display", {}).get("showMonitoringLines"), True)

    async def test_display_patch_rejects_empty_payload(self):
        """display alanı boşsa 400 — indikatör kaydına dokunmaz."""
        from app.main import patch_chart_display

        with self.assertRaises(HTTPException) as ctx:
            await patch_chart_display("BTCTRY", {})
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()