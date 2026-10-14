"""Unit tests for Binance TR position cost basis and fallback calculations."""
from unittest import mock
import pytest
from app.main import _avg_buy_cost, _binance_cost_cache


@pytest.fixture(autouse=True)
def _clear_cost_cache():
    _binance_cost_cache.clear()
    yield
    _binance_cost_cache.clear()


def test_avg_buy_cost_fifo_normal():
    # User bought 10 SOL at 100 TRY, then sold 4 SOL at 110 TRY
    # Remaining 6 SOL should have cost basis 100 TRY
    trades = [
        {"id": 1, "time": 1000, "isBuyer": True, "qty": "10.0", "price": "100.0", "symbol": "SOLTRY"},
        {"id": 2, "time": 2000, "isBuyer": False, "qty": "4.0", "price": "110.0", "symbol": "SOLTRY"},
    ]
    with mock.patch("app.main.get_trade_history", return_value=trades):
        info = _avg_buy_cost(
            user_id=1,
            api_key="k",
            api_secret="s",
            asset="SOL",
            symbol_concat="SOLTRY",
            now=100.0,
            total_qty=6.0,
            usdt_try=38.0,
        )
    assert info is not None
    assert info["avg_price"] == pytest.approx(100.0)
    assert info["quote"] == "TRY"


def test_avg_buy_cost_fifo_exhausted_fallback():
    # User sold 10 SOL, FIFO queue is empty (0 remaining in queue)
    # but user currently holds 5 SOL (from earlier deposits or outside history).
    # Fallback to recent buy should calculate VWAP of the recent purchase!
    trades = [
        {"id": 1, "time": 1000, "isBuyer": True, "qty": "10.0", "price": "2500.0", "symbol": "SOLTRY"},
        {"id": 2, "time": 2000, "isBuyer": False, "qty": "10.0", "price": "2600.0", "symbol": "SOLTRY"},
    ]
    with mock.patch("app.main.get_trade_history", return_value=trades):
        info = _avg_buy_cost(
            user_id=1,
            api_key="k",
            api_secret="s",
            asset="SOL",
            symbol_concat="SOLTRY",
            now=100.0,
            total_qty=5.0,
            usdt_try=38.0,
        )
    assert info is not None
    # Because FIFO was empty, fallback uses the most recent buy price
    assert info["avg_price"] == pytest.approx(2500.0)
    assert info["quote"] == "TRY"


def test_avg_buy_cost_usdt_pair_converted_to_try():
    # User bought BTC using USDT: price 60,000 USDT, usdt_try = 38.0
    # Expected cost basis in TRY: 60,000 * 38 = 2,280,000 TRY
    def mock_trades(key, secret, symbol, start, end, limit, offset):
        if "USDT" in symbol:
            return [{"id": 10, "time": 1000, "isBuyer": 1, "qty": "0.5", "price": "60000.0", "symbol": "BTCUSDT"}]
        return []

    with mock.patch("app.main.get_trade_history", side_effect=mock_trades):
        info = _avg_buy_cost(
            user_id=1,
            api_key="k",
            api_secret="s",
            asset="BTC",
            symbol_concat="BTCTRY",
            now=100.0,
            total_qty=0.5,
            usdt_try=38.0,
        )
    assert info is not None
    assert info["avg_price"] == pytest.approx(2_280_000.0)
    assert info["quote"] == "TRY"


def test_avg_buy_cost_string_is_buyer_parsing():
    # Binance TR API sometimes returns string "1" or "0"
    trades = [
        {"id": 1, "time": 1000, "isBuyer": "1", "qty": "100.0", "price": "5.0", "symbol": "DOGETRY"},
        {"id": 2, "time": 2000, "isBuyer": "0", "qty": "50.0", "price": "6.0", "symbol": "DOGETRY"},
    ]
    with mock.patch("app.main.get_trade_history", return_value=trades):
        info = _avg_buy_cost(
            user_id=1,
            api_key="k",
            api_secret="s",
            asset="DOGE",
            symbol_concat="DOGETRY",
            now=100.0,
            total_qty=50.0,
            usdt_try=38.0,
        )
    assert info is not None
    assert info["avg_price"] == pytest.approx(5.0)
