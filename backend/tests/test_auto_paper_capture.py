import asyncio
from unittest.mock import AsyncMock

from app import database
from app.market_data import MarketData
from app.routers import auto_paper
from app.super_scan_notify import _envelope


def test_envelope_keeps_scan_evidence():
    candidate = {
        "symbol": "XTRY", "score": 70, "super_score": 81, "source_bonus": 6,
        "cmc_bonus": 5, "source_families": ["momentum", "macd"],
        "sources": ["velocity", "macd_mtf"], "cmc_flags": ["HACIM_PATLAMASI"],
        "price": 10, "detected_at": 1000, "atr_pct_15m": 2, "oi_change_pct": 3,
    }
    envelope = _envelope(candidate)
    assert envelope["scan_evidence"]["sources"] == ["velocity", "macd_mtf"]
    assert envelope["scan_evidence"]["source_bonus"] == 6
    assert envelope["scan_evidence"]["cmc_bonus"] == 5
    assert envelope["scan_evidence"]["detected_at"] == 1000


def test_management_records_exact_stop_inputs(monkeypatch):
    trade = {"id": 42, "symbol": "XTRY", "status": "open", "entry_price": 10.0,
             "quantity": 3, "entry_time": 995, "stop_loss": 9.7, "peak_price": 10}
    monkeypatch.setattr(auto_paper.market, "get_ticker", lambda _: {
        "last_price": 9.5, "timestamp": 999_000, "source": "test_ws",
        "exchange_event_time_ms": 998_990,
    })
    monkeypatch.setattr(database, "get_auto_paper_trade", AsyncMock(return_value=trade))
    monkeypatch.setattr(database, "update_auto_paper_excursions", AsyncMock())
    monkeypatch.setattr(database, "close_auto_paper_trade", AsyncMock(return_value=False))
    asyncio.run(auto_paper._manage_single_trade(trade, 1000, settings={}))
    call = database.close_auto_paper_trade.await_args
    evidence = call.kwargs["diagnostics"]
    assert evidence["raw_price"] == 9.5
    assert evidence["trigger_price"] == 9.7
    assert evidence["source"] == "test_ws"
    assert evidence["exchange_event_time_ms"] == 998_990
    assert auto_paper._exit_evidence.get() is None


def test_new_mini_ticker_drops_provenance_from_prior_candle():
    market = MarketData(["xtry"])
    market.tickers["XTRY"] = {
        "last_price": 2.477, "timestamp": 1000, "candle_close_time_ms": 250,
        "candle_timeframe": "30m", "candle_is_closed": True,
    }
    market._ingest_mini_ticker_arr([{"s": "XTRY", "c": "2.646", "E": 2000}])
    ticker = market.get_ticker("XTRY")
    assert ticker["last_price"] == 2.646
    assert ticker["exchange_event_time_ms"] == 2000
    assert ticker["candle_close_time_ms"] is None
    assert ticker["candle_timeframe"] is None
