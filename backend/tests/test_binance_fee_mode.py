"""Binance TR komisyon modu (BNB ile komisyon) — imzalı istekler sahte; GERÇEK İSTEK YOK."""
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app import binance_tr_private as btp
from app import main

ACCOUNT = {
    "makerCommission": 10, "takerCommission": "15",
    "fiatMakerCommission": 0.001, "fiatTakerCommission": 0.0015,
    "accountAssets": [
        {"asset": "TRY", "free": "100", "locked": "0"},
        {"asset": "BNB", "free": "0.25", "locked": "0.05"},
    ],
}


class GetFeeModeTests(unittest.TestCase):
    def test_parses_commissions_and_bnb_balance(self):
        with mock.patch.object(btp, "_signed_request", return_value=ACCOUNT) as sr:
            res = btp.get_fee_mode("k", "s")
        sr.assert_called_once_with("GET", "/open/v1/account/spot", None, "k", "s")
        self.assertFalse(res["bnb_burn_supported"])
        self.assertIsNone(res["spot_bnb_burn"])
        self.assertAlmostEqual(res["maker_commission"], 0.001)   # 10 baz puan
        self.assertAlmostEqual(res["taker_commission"], 0.0015)  # "15" baz puan
        self.assertAlmostEqual(res["fiat_maker_commission"], 0.001)  # zaten oran
        self.assertAlmostEqual(res["bnb_balance"], 0.30)
        self.assertEqual(res["source"], "/open/v1/account/spot")

    def test_missing_fields_give_none_and_zero_bnb(self):
        with mock.patch.object(btp, "_signed_request",
                               return_value={"accountAssets": [{"asset": "TRY", "free": "1", "locked": "0"}]}):
            res = btp.get_fee_mode("k", "s")
        self.assertIsNone(res["maker_commission"])
        self.assertIsNone(res["taker_commission"])
        self.assertEqual(res["bnb_balance"], 0.0)

    def test_non_dict_payload_is_safe(self):
        with mock.patch.object(btp, "_signed_request", return_value=[]):
            res = btp.get_fee_mode("k", "s")
        self.assertIsNone(res["bnb_balance"])
        self.assertIsNone(res["maker_commission"])

    def test_set_fee_mode_not_supported(self):
        with mock.patch.object(btp, "_signed_request") as sr:
            with self.assertRaises(NotImplementedError) as cm:
                btp.set_fee_mode("k", "s", True)
        sr.assert_not_called()
        self.assertIn("Binance TR web ayarlarından değiştirin", str(cm.exception))


class FeeModeEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _patches(self):
        return (
            mock.patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))),
            mock.patch("app.main._require_user", return_value={"username": "u", "role": "user"}),
            mock.patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 1})),
            mock.patch("app.main._real_sell_state_for", new=AsyncMock(return_value=(True, "panel"))),
        )

    async def test_get_returns_fee_mode(self):
        with mock.patch.object(btp, "_signed_request", return_value=ACCOUNT), \
             mock.patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))):
            res = await main.binance_fee_mode_get(MagicMock())
        self.assertFalse(res["bnb_burn_supported"])
        self.assertAlmostEqual(res["bnb_balance"], 0.30)

    async def test_post_invalid_body_returns_400(self):
        for bad in ({}, {"spot_bnb_burn": "true", "confirm": True}, {"spot_bnb_burn": 1, "confirm": True}):
            with self.assertRaises(HTTPException) as cm:
                await main.binance_fee_mode_set(bad, MagicMock())
            self.assertEqual(cm.exception.status_code, 400)

    async def test_post_requires_confirm(self):
        with self.assertRaises(HTTPException) as cm:
            await main.binance_fee_mode_set({"spot_bnb_burn": True}, MagicMock())
        self.assertEqual(cm.exception.status_code, 400)

    async def test_post_unsupported_returns_501(self):
        p = self._patches()
        with p[0], p[1], p[2], p[3]:
            with self.assertRaises(HTTPException) as cm:
                await main.binance_fee_mode_set({"spot_bnb_burn": True, "confirm": True}, MagicMock())
        self.assertEqual(cm.exception.status_code, 501)
        self.assertIn("web ayarlarından", cm.exception.detail)

    async def test_post_blocked_when_real_trading_off(self):
        with mock.patch("app.main._decrypt_binance_creds", new=AsyncMock(return_value=("k", "s"))), \
             mock.patch("app.main._require_user", return_value={"username": "u"}), \
             mock.patch("app.main.database.get_user_by_username", new=AsyncMock(return_value={"id": 1})), \
             mock.patch("app.main._real_sell_state_for", new=AsyncMock(return_value=(False, "panel"))):
            with self.assertRaises(HTTPException) as cm:
                await main.binance_fee_mode_set({"spot_bnb_burn": False, "confirm": True}, MagicMock())
        self.assertEqual(cm.exception.status_code, 403)

    async def test_post_success_path_is_audited_when_supported(self):
        p = self._patches()
        with p[0], p[1], p[2], p[3], \
             mock.patch.object(btp, "set_fee_mode", return_value={"spot_bnb_burn": True}), \
             mock.patch("app.main._session_identity", return_value=("u", "user")), \
             mock.patch("app.main.log_user_action", new=AsyncMock()) as audit:
            res = await main.binance_fee_mode_set({"spot_bnb_burn": True, "confirm": True}, MagicMock())
        self.assertTrue(res["ok"])
        self.assertTrue(res["spot_bnb_burn"])
        audit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
