import asyncio
import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import derivatives_service
from app.config import config


@pytest.mark.asyncio
async def test_chart_open_interest_uses_fresh_exact_window_and_its_own_cache(monkeypatch):
    now = 1_801
    monkeypatch.setattr(derivatives_service.time, "time", lambda: now)
    monkeypatch.setattr(derivatives_service, "_CHART_OI_CACHE", {})
    monkeypatch.setattr(derivatives_service, "_OI_HIST_CACHE", {})
    rows = [{"timestamp": 1_800_000, "sumOpenInterest": "102"},
            {"timestamp": 900_000, "sumOpenInterest": "100"}]
    fetch = MagicMock(side_effect=[rows, rows, None])
    monkeypatch.setattr(derivatives_service, "_fetch_fapi_json", fetch)

    result = await derivatives_service.chart_open_interest("PORTALTRY")
    assert result == {
        "futures_symbol": "PORTALUSDT", "source": "binance_usdm_futures", "window_minutes": 15,
        "status": "fresh", "change_pct": 2, "start_timestamp_ms": 900_000, "end_timestamp_ms": 1_800_000,
    }
    assert await derivatives_service.chart_open_interest("PORTALTRY") == result
    assert fetch.call_count == 1
    assert "symbol=PORTALUSDT&period=5m" in fetch.call_args.args[0]
    assert not derivatives_service._OI_HIST_CACHE

    now = 2_401
    assert (await derivatives_service.chart_open_interest("PORTALTRY"))["status"] == "stale"
    missing = await derivatives_service.chart_open_interest("NOSYMBOLTRY")
    assert missing["status"] == "unavailable"
    assert "change_pct" not in missing


@pytest.mark.asyncio
async def test_chart_open_interest_refresh_retries_a_cached_miss(monkeypatch):
    monkeypatch.setattr(derivatives_service.time, "time", lambda: 1_801)
    monkeypatch.setattr(derivatives_service, "_CHART_OI_CACHE", {})
    rows = [{"timestamp": 1_800_000, "sumOpenInterest": "102"},
            {"timestamp": 900_000, "sumOpenInterest": "100"}]
    fetch = MagicMock(side_effect=[None, rows])
    monkeypatch.setattr(derivatives_service, "_fetch_fapi_json", fetch)

    assert (await derivatives_service.chart_open_interest("ROBOTRY"))["status"] == "unavailable"
    assert (await derivatives_service.chart_open_interest("ROBOTRY"))["status"] == "unavailable"
    result = await derivatives_service.chart_open_interest("ROBOTRY", refresh=True)
    assert result["status"] == "fresh"
    assert result["change_pct"] == 2
    assert fetch.call_count == 2


def test_squeeze_confirmation_keeps_exact_15m_metadata(monkeypatch):
    monkeypatch.setattr(derivatives_service, "_OI_HIST_CACHE", {})
    monkeypatch.setattr(derivatives_service.time, "time", lambda: 1_801)
    monkeypatch.setattr(config, "AUTO_PAPER_OI_WINDOW_MIN", 30)
    rows = [{"timestamp": 300_000 * i, "sumOpenInterest": str(value)}
            for i, value in enumerate([100, 105, 110, 120, 121, 122, 123])]
    mock_fapi = MagicMock(side_effect=[rows, []])
    monkeypatch.setattr(derivatives_service, "_fetch_fapi_json", mock_fapi)

    captured = asyncio.run(derivatives_service.squeeze_confirmation("BABYTRY"))

    assert captured["oi_change_1h_pct"] == 23
    expected = {
        "change_pct": pytest.approx(2.5),
        "start_timestamp_ms": 900_000,
        "end_timestamp_ms": 1_800_000,
    }
    assert captured["oi_15m"] == expected
    assert derivatives_service.get_cached_squeeze_confirmation("BABYTRY")["oi_15m"] == expected
    assert mock_fapi.call_count == 2


@pytest.mark.parametrize("first_timestamp,oi", [(899_999, "100"), (900_000, "NaN"), (900_000, "0")])
def test_squeeze_confirmation_rejects_invalid_15m_sample(monkeypatch, first_timestamp, oi):
    monkeypatch.setattr(derivatives_service, "_OI_HIST_CACHE", {})
    monkeypatch.setattr(derivatives_service.time, "time", lambda: 1_801)
    rows = [{"timestamp": first_timestamp, "sumOpenInterest": oi},
            {"timestamp": 1_800_000, "sumOpenInterest": "102"}]
    monkeypatch.setattr(derivatives_service, "_fetch_fapi_json", MagicMock(side_effect=[rows, []]))

    captured = asyncio.run(derivatives_service.squeeze_confirmation("BABYTRY"))

    assert captured["oi_15m"] is None


class DerivativesServiceTests(unittest.TestCase):
    def setUp(self):
        derivatives_service._DERIVATIVES_CACHE.clear()

    def test_symbol_to_futures(self):
        self.assertEqual(derivatives_service.symbol_to_futures("BTCTRY"), "BTCUSDT")
        self.assertEqual(derivatives_service.symbol_to_futures("SOLTRY"), "SOLUSDT")
        self.assertEqual(derivatives_service.symbol_to_futures("ETHUSDT"), "ETHUSDT")
        self.assertEqual(derivatives_service.symbol_to_futures("RENDERTRY"), "RENDERUSDT")

    @patch("app.derivatives_service._fetch_fapi_json")
    def test_get_derivatives_intel_healthy(self, mock_fapi):
        # mock premiumIndex and openInterest responses
        mock_fapi.side_effect = [
            {"lastFundingRate": "0.00010000", "markPrice": "65000.0"},
            {"openInterest": "15000.0"},
        ]

        res = asyncio.run(derivatives_service.get_derivatives_intel("BTCTRY"))
        self.assertTrue(res["futures_available"])
        self.assertEqual(res["futures_symbol"], "BTCUSDT")
        self.assertEqual(res["funding_rate"], 0.0001)
        self.assertEqual(res["funding_state"], "HEALTHY")
        self.assertEqual(res["surge_score_bonus"], 5)
        self.assertFalse(res["crowded_long_danger"])

    @patch("app.derivatives_service._fetch_fapi_json")
    def test_get_derivatives_intel_extreme_long(self, mock_fapi):
        mock_fapi.side_effect = [
            {"lastFundingRate": "0.00095000", "markPrice": "65000.0"},
            {"openInterest": "20000.0"},
        ]

        res = asyncio.run(derivatives_service.get_derivatives_intel("BTCTRY"))
        self.assertTrue(res["futures_available"])
        self.assertEqual(res["funding_state"], "EXTREME_LONG")
        self.assertTrue(res["crowded_long_danger"])
        self.assertEqual(res["surge_score_bonus"], -15)

    @patch("app.derivatives_service._fetch_fapi_json")
    def test_get_derivatives_intel_short_squeeze(self, mock_fapi):
        mock_fapi.side_effect = [
            {"lastFundingRate": "-0.00045000", "markPrice": "65000.0"},
            {"openInterest": "12000.0"},
        ]

        res = asyncio.run(derivatives_service.get_derivatives_intel("BTCTRY"))
        self.assertTrue(res["futures_available"])
        self.assertEqual(res["funding_state"], "CROWDED_SHORT")
        self.assertTrue(res["short_squeeze_potential"])
        self.assertEqual(res["surge_score_bonus"], 10)

    @patch("app.derivatives_service._fetch_fapi_json")
    def test_get_derivatives_intel_unavailable(self, mock_fapi):
        mock_fapi.side_effect = [None, None]

        res = asyncio.run(derivatives_service.get_derivatives_intel("UNKNOWNTRY"))
        self.assertFalse(res["futures_available"])
        self.assertEqual(res["funding_state"], "UNKNOWN")
        self.assertEqual(res["surge_score_bonus"], 0)

    def test_cached_derivatives_intel(self):
        derivatives_service._DERIVATIVES_CACHE["BTCUSDT"] = (
            derivatives_service.time.time(),
            {"futures_available": True, "funding_state": "HEALTHY", "surge_score_bonus": 5},
        )
        cached = derivatives_service.get_cached_derivatives_intel("BTCTRY")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["funding_state"], "HEALTHY")


if __name__ == "__main__":
    unittest.main()
