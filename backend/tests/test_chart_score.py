import io
import json
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.ai_trading_suite_routes import router, router_alias


app = FastAPI()
app.include_router(router)
app.include_router(router_alias)
client = TestClient(app)
PATHS = ("/api/v1/ai-trading-suite/chart-score", "/api/ai-trading-suite/chart-score")
INTERVAL_MS = 15 * 60 * 1000


def recent_candles():
    now = int(time.time() * 1000)
    start = now - 25 * INTERVAL_MS
    return [
        [start + i * INTERVAL_MS, "10", str(11 + i), str(9 + i), str(10 + i), "100"]
        for i in range(25)
    ]


@pytest.mark.parametrize("path", PATHS)
def test_chart_score_uses_market_candles(path):
    with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(recent_candles()).encode())):
        response = client.get(path, params={"symbol": "BTCUSDT"})

    assert response.status_code == 200
    score = response.json()
    assert score["status"] == "ok"
    assert score["source"] == "binance_spot"
    assert score["current_price"] == 34
    assert set(score["octobot"]) >= {"score", "signal"}
    assert set(score["qlib"]) >= {"score", "rank"}


@pytest.mark.parametrize("problem", ["timeout", "insufficient", "stale", "non_finite", "bad_shape"])
def test_chart_score_reports_unavailable_without_synthetic_output(problem):
    candles = recent_candles()
    if problem == "insufficient":
        candles = candles[:3]
    elif problem == "stale":
        for candle in candles:
            candle[0] -= 3 * INTERVAL_MS
    elif problem == "non_finite":
        candles[-1][4] = "NaN"
    elif problem == "bad_shape":
        candles[-1] = {"close": 34}

    with patch(
        "urllib.request.urlopen",
        return_value=io.BytesIO(json.dumps(candles).encode()),
        side_effect=TimeoutError if problem == "timeout" else None,
    ):
        response = client.get(PATHS[0], params={"symbol": "BTCUSDT"})

    assert response.status_code == 200
    assert response.json() == {"status": "unavailable", "symbol": "BTCUSDT", "asset_type": "SPOT"}
