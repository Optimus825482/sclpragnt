import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import main, ui_prefs


class NormalizeTests(unittest.TestCase):
    def test_empty_ok(self):
        self.assertEqual([], ui_prefs.normalize_hidden([]))

    def test_dedup_and_order(self):
        self.assertEqual(["charts", "reports"], ui_prefs.normalize_hidden(["reports", "charts", "charts"]))

    def test_unknown_rejected(self):
        with self.assertRaises(ValueError):
            ui_prefs.normalize_hidden(["nope"])

    def test_locked_rejected(self):
        for locked in ("home", "settings"):
            with self.assertRaises(ValueError):
                ui_prefs.normalize_hidden([locked])

    def test_removed_legacy_ids_are_silently_dropped(self):
        # 'portfolio' menüden kaldırıldı; eski kayıtlı tercihlerde kalmış olabilir → hata değil, yok sayılır.
        self.assertEqual(["charts"], ui_prefs.normalize_hidden(["portfolio", "charts"]))
        self.assertEqual([], ui_prefs.normalize_hidden(["portfolio"]))
        self.assertNotIn("portfolio", ui_prefs.MENU_IDS)

    def test_binance_and_risk_menu_items_are_hideable(self):
        self.assertEqual(["binance", "risk"], ui_prefs.normalize_hidden(["risk", "binance"]))

    def test_not_a_list_rejected(self):
        with self.assertRaises(ValueError):
            ui_prefs.normalize_hidden("charts")


class _Req:
    pass


class EndpointTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_get_returns_own_prefs_only(self):
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})), \
             patch.object(main.database, "get_user_ui_prefs", AsyncMock(return_value={"hidden_menu": ["charts"]})) as g:
            out = self._run(main.get_ui_prefs(_Req()))
        g.assert_awaited_once_with(7)
        self.assertEqual(["charts"], out["hidden_menu"])

    def test_put_invalid_is_422(self):
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})):
            with self.assertRaises(HTTPException) as cm:
                self._run(main.put_ui_prefs({"hidden_menu": ["settings"]}, _Req()))
        self.assertEqual(422, cm.exception.status_code)

    def test_put_saves_for_session_user(self):
        saved = AsyncMock(return_value={"hidden_menu": ["charts"]})
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})), \
             patch.object(main.database, "set_user_ui_prefs", saved):
            out = self._run(main.put_ui_prefs({"hidden_menu": ["charts"]}, _Req()))
        saved.assert_awaited_once_with(7, ["charts"])
        self.assertTrue(out["ok"])
