import asyncio
import json
import logging
from unittest.mock import AsyncMock
import pytest

from app import api_common, database, derivatives_service, price_service
from app.market_data import MarketData
from app.routers import auto_paper
from app.super_scan_notify import _envelope


@pytest.mark.parametrize(
    "families,change,end_ms,window,threshold,expected",
    [
        (["short_squeeze"], 0.7983, 1_800_000, 15, 1.2, "would_block"),
        (["short_squeeze", "macd"], 1.0354, 1_800_000, 15, 1.2, "would_block"),
        (["short_squeeze"], 1.2, 1_800_000, 15, 1.2, "would_pass"),
        (["short_squeeze"], 2.1, 1_200_000, 15, 1.2, "stale"),
        (["short_squeeze"], 2.1, 2_100_000, 15, 1.2, "unavailable"),
        (["short_squeeze"], None, None, 15, 1.2, "unavailable"),
        (["short_squeeze"], 2.1, 1_800_000, 30, 1.2, "unsupported_window"),
        (["short_squeeze"], 2.1, 1_800_000, 15, 0, "disabled"),
        (["momentum"], 2.1, 1_800_000, 15, 1.2, None),
    ],
)
def test_oi_shadow_is_persisted_without_blocking_paper_open(
    monkeypatch, caplog, families, change, end_ms, window, threshold, expected,
):
    occurrence = None if change is None else {
        "change_pct": change, "start_timestamp_ms": end_ms - 900_000, "end_timestamp_ms": end_ms,
    }
    monkeypatch.setattr(derivatives_service, "get_cached_squeeze_confirmation", lambda _: {
        "oi_15m": occurrence, "oi_change_1h_pct": 0.31,
    })
    monkeypatch.setattr(auto_paper, "_resolve_order_size", AsyncMock(return_value=(10_000, 500, 50, None)))
    plan = {
        "now": 1_801.0, "fill_entry": 1.0, "quantity": 500, "net_order_value": 500,
        "stop_loss_price": 0.96, "take_profit_price": 1.1, "target_pct": 10,
        "tp1_scalp_val": None, "tp2_runner_val": None, "trade_exit_profile": None,
        "trade_max_hold": None, "plan_context": None,
    }
    monkeypatch.setattr(auto_paper, "_calc_exit_plan", AsyncMock(return_value=(plan, None)))
    insert = AsyncMock(return_value=({"id": 3099}, "opened"))
    monkeypatch.setattr(database, "open_auto_paper_trade", insert)
    monkeypatch.setattr(auto_paper, "_apply_post_open_effects", AsyncMock())
    notif = {"source": "super_scan", "notification_key": "super:BABYTRY:6",
             "scan_evidence": {"source_families": families},
             "_paper_diagnostics": {"thresholds": {"oi_change_pct": {"evaluated": False}}}}

    with caplog.at_level(logging.INFO, logger=auto_paper.logger.name):
        result = asyncio.run(auto_paper._open_new_trade(
            "BABYTRY", notif, 1.0, {"oi_window_min": window, "min_oi_change_pct": threshold},
        ))

    assert result["status"] == "opened"
    insert.assert_awaited_once()
    record, _ = insert.await_args.args
    assert record["oi_change_pct"] == 0.31
    assert record["diagnostics"]["thresholds"]["oi_change_pct"] == {"evaluated": False}
    decision = record["diagnostics"].get("oi_shadow")
    events = [json.loads(r.message) for r in caplog.records if '"event": "auto_paper_oi_shadow"' in r.message]
    if expected is None:
        assert decision is None
        assert events == []
    else:
        assert decision["status"] == expected
        assert decision["minimum_pct"] == threshold
        assert decision["configured_window_minutes"] == window
        assert events == [{"event": "auto_paper_oi_shadow", "entry_point": "super_scan",
                           "trade_id": 3099, "symbol": "BABYTRY", **decision}]
        if expected.startswith("would_"):
            assert decision["change_pct"] == change
            assert decision["end_timestamp_ms"] == end_ms


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
