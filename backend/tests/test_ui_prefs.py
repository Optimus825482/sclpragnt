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


class WatchListTests(unittest.TestCase):
    def test_normalizes_symbol_price_at(self):
        out = ui_prefs.normalize_watch_list([{"symbol": " btctry ", "price": "100.5", "at": 1760000000}])
        self.assertEqual([{"symbol": "BTCTRY", "price": 100.5, "at": 1760000000.0}], out)

    def test_at_defaults_to_now(self):
        out = ui_prefs.normalize_watch_list([{"symbol": "ETHTRY", "price": 2}], now=123.0)
        self.assertEqual(123.0, out[0]["at"])

    def test_dedupe_keeps_first(self):
        out = ui_prefs.normalize_watch_list([
            {"symbol": "BTCTRY", "price": 1, "at": 5}, {"symbol": "btctry", "price": 9, "at": 6}])
        self.assertEqual([{"symbol": "BTCTRY", "price": 1.0, "at": 5.0}], out)

    def test_empty_ok(self):
        self.assertEqual([], ui_prefs.normalize_watch_list([]))

    def test_max_items(self):
        ok = [{"symbol": f"A{i:02d}TRY", "price": 1, "at": 1} for i in range(30)]
        self.assertEqual(30, len(ui_prefs.normalize_watch_list(ok)))
        with self.assertRaises(ValueError):
            ui_prefs.normalize_watch_list(ok + [{"symbol": "ZZZTRY", "price": 1, "at": 1}])

    def test_invalid_rejected(self):
        bad = [
            "BTCTRY", None, {"symbol": "BTCUSDT", "price": 1}, {"symbol": "TRY", "price": 1},
            {"symbol": "A" * 16 + "TRY", "price": 1}, {"symbol": "BTC-TRY", "price": 1},
            {"symbol": "BTCTRY"}, {"symbol": "BTCTRY", "price": 0}, {"symbol": "BTCTRY", "price": -1},
            {"symbol": "BTCTRY", "price": "x"}, {"symbol": "BTCTRY", "price": True},
            {"symbol": "BTCTRY", "price": float("nan")}, {"symbol": "BTCTRY", "price": float("inf")},
            {"symbol": "BTCTRY", "price": 1, "at": 0}, {"symbol": "BTCTRY", "price": 1, "at": "abc"},
        ]
        for item in bad:
            with self.assertRaises(ValueError, msg=repr(item)):
                ui_prefs.normalize_watch_list([item])

    def test_not_a_list_rejected(self):
        for raw in (None, "BTCTRY", {"symbol": "BTCTRY"}):
            with self.assertRaises(ValueError):
                ui_prefs.normalize_watch_list(raw)


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
        saved.assert_awaited_once_with(7, ["charts"], None, None)
        self.assertTrue(out["ok"])

    def test_put_partial_keeps_other_keys_unchanged(self):
        # Yalnız favorites gönderilirse hidden_menu / pinned None (= DB'de korunur) geçmeli.
        merged = {"hidden_menu": ["charts"], "favorites": [{"symbol": "BTCTRY", "price": 1.5, "at": 10.0}],
                  "pinned": [{"symbol": "ETHTRY", "price": 2.0, "at": 11.0}]}
        saved = AsyncMock(return_value=merged)
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})), \
             patch.object(main.database, "set_user_ui_prefs", saved):
            out = self._run(main.put_ui_prefs(
                {"favorites": [{"symbol": "btctry", "price": "1.5", "at": 10}]}, _Req()))
        saved.assert_awaited_once_with(7, None, [{"symbol": "BTCTRY", "price": 1.5, "at": 10.0}], None)
        self.assertEqual(merged["hidden_menu"], out["hidden_menu"])
        self.assertEqual(merged["pinned"], out["pinned"])

    def test_put_pinned_only_and_empty_clears(self):
        saved = AsyncMock(return_value={"hidden_menu": [], "favorites": [], "pinned": []})
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})), \
             patch.object(main.database, "set_user_ui_prefs", saved):
            self._run(main.put_ui_prefs({"pinned": []}, _Req()))
        saved.assert_awaited_once_with(7, None, None, [])

    def test_put_invalid_watch_list_is_422(self):
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})):
            for key in ("favorites", "pinned"):
                with self.assertRaises(HTTPException) as cm:
                    self._run(main.put_ui_prefs({key: [{"symbol": "BTCUSDT", "price": 1}]}, _Req()))
                self.assertEqual(422, cm.exception.status_code)


class RowParsingTests(unittest.TestCase):
    def test_row_to_prefs_and_defaults(self):
        from app import database
        self.assertEqual({"hidden_menu": [], "favorites": [], "pinned": []}, database._ui_prefs_from_row(None))
        row = ('["charts"]', '[{"symbol":"BTCTRY","price":1,"at":2}, 5]', "not json")
        self.assertEqual(
            {"hidden_menu": ["charts"], "favorites": [{"symbol": "BTCTRY", "price": 1, "at": 2}], "pinned": []},
            database._ui_prefs_from_row(row))
