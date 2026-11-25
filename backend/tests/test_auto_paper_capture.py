import asyncio
from unittest.mock import AsyncMock

from app import api_common, database, price_service
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


def test_old_candle_with_fresh_cache_time_cannot_fire_stop(monkeypatch):
    trade = {"id": 43, "symbol": "ATTRY", "entry_price": 2.63565875,
             "entry_time": 999, "stop_loss": 2.58893379168}
    monkeypatch.setattr(auto_paper.market, "get_ticker", lambda _: {
        "last_price": 2.477, "timestamp": 1_000_000, "source": "symbol_analysis_rest_kline",
        "candle_close_time_ms": 100_000, "candle_timeframe": "30m", "candle_is_closed": True,
    })
    fallback = AsyncMock(return_value=(2.646, {"source": "test_rest_ticker"}))
    monkeypatch.setattr(auto_paper, "_fresh_public_price", fallback)
    monkeypatch.setattr(database, "update_auto_paper_excursions", AsyncMock())
    monkeypatch.setattr(database, "update_auto_paper_peak", AsyncMock())
    close = AsyncMock()
    monkeypatch.setattr(auto_paper, "_close_trade", close)
    asyncio.run(auto_paper._manage_single_trade(trade, 1000, settings={}))
    close.assert_not_awaited()
    fallback.assert_awaited_once_with("ATTRY", execution_only=True)


def test_super_scan_price_is_not_used_if_execution_quote_is_unavailable(monkeypatch):
    monkeypatch.setattr(auto_paper.time, "time", lambda: 1000)
    monkeypatch.setattr(auto_paper.market, "get_ticker", lambda _: {
        "last_price": 2.477, "timestamp": 1_000_000, "source": "symbol_analysis_rest_kline",
        "candle_close_time_ms": 100_000,
    })
    monkeypatch.setattr(auto_paper, "_fresh_public_price", AsyncMock(return_value=(None, None)))
    _, block = asyncio.run(auto_paper._resolve_entry_price(
        {"source": "super_scan", "price": 2.477, "detected_at": 999},
        "ATTRY", {"block_weak_mtf": False},
    ))
    assert block["reason"] == "stale_ticker"


def test_execution_fallback_does_not_use_chart_data(monkeypatch):
    monkeypatch.setattr(price_service, "mini_ticker_quote", lambda *args, **kwargs: None)
    monkeypatch.setattr(price_service, "rest_ticker_price", AsyncMock(return_value=None))
    chart_price = AsyncMock(return_value=(2.477, 0, price_service.SOURCE_REST_KLINE))
    monkeypatch.setattr(price_service, "get_price", chart_price)
    assert asyncio.run(api_common._fresh_public_price("ATTRY", execution_only=True)) == (None, None)
    chart_price.assert_not_awaited()


def test_exchange_time_takes_priority_over_cache_time(monkeypatch):
    monkeypatch.setattr(auto_paper.market, "get_ticker", lambda _: {
        "last_price": 2.477, "timestamp": 1_000_000, "source": "test_ws",
        "exchange_event_time_ms": 100_000,
    })
    fallback = AsyncMock(return_value=(2.646, {"source": "test_rest_ticker"}))
    monkeypatch.setattr(auto_paper, "_fresh_public_price", fallback)
    price, fresh, last = asyncio.run(auto_paper._fresh_trade_price({"entry_price": 2.635}, "ATTRY", 1000))
    assert (price, fresh, last) == (2.646, True, 2.477)
    fallback.assert_awaited_once_with("ATTRY", execution_only=True)
