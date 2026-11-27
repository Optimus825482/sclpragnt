import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

from pytest import approx, mark

from app import large_move_paper
from app.large_move_paper import (
    MINUTE,
    RADAR_SIGNAL_AGE,
    Tracker,
    database,
    followup_path,
    mark_exit,
    read_book,
    recent_signal_notifications,
    scan_missing_bars,
    signal_notification,
    trailing_level,
)


@mark.asyncio
async def test_notification_history_matches_live_payload_for_confirmed_signals(monkeypatch):
    migration = Path(__file__).resolve().parents[1] / "migrations/034_large_move_paper.sql"
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.executemany(
            """INSERT INTO large_move_paper
               (symbol, seed_ms, base_price, watch_ms, signal_ms, signal_price, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                ("WATCHTRY", 0, 100, 60000, None, None, "watch"),
                ("OPENTRY", 0, 100, 60000, 120000, 115, "open"),
                ("PORTALTRY", 60000, 100, 120000, 180000, 118.5, "blocked"),
            ],
        )

        async def run_db(operation):
            return operation(conn)

        monkeypatch.setattr(database, "_run_db", run_db)
        events = await recent_signal_notifications()
        assert [event["symbol"] for event in events] == ["PORTALTRY", "OPENTRY"]
        assert events[0] == signal_notification("PORTALTRY", 60000, 180000, 118.5, 100)
        assert events[0] == {
            "id": "large-move-PORTALTRY-60000",
            "kind": "large_move",
            "symbol": "PORTALTRY",
            "message": "Bir dakikalık mum baz fiyatın +%18,5 üzerinde kapandı.",
            "price": 118.5,
            "triggered_at": 180.0,
        }


@mark.asyncio
async def test_periodic_radar_fills_missing_close_once_and_keeps_live_episode(monkeypatch):
    def candle(minute, close):
        stamp = minute * MINUTE
        return [stamp, close, close, close, close, 10, stamp + MINUTE - 1]

    port = warmed_tracker()
    assert port.observe(31 * MINUTE, 103, True) is None
    watch = port.observe(32 * MINUTE, 110, True)
    healthy = warmed_tracker()
    for minute in range(31, 35):
        healthy.observe(minute * MINUTE, 100, True)
    trackers = {"PORTALTRY": port, "HEITRY": healthy}
    candles = [candle(35, 145), candle(34, 116), candle(33, 112), candle(32, 110)]
    fetch = AsyncMock(return_value=candles)
    monkeypatch.setattr(large_move_paper, "klines", fetch)
    alerts = []

    def accept(symbol, stamp, price, traded, *, max_age):
        alert = trackers[symbol].observe(stamp, price, traded)
        if alert:
            alerts.append((alert, max_age))

    symbols = ["USDTTRY", "HEITRY", "PORTALTRY", "PORTALUSDT"]
    close_ms = 35 * MINUTE
    await scan_missing_bars(symbols, trackers, accept, close_ms)
    await scan_missing_bars(symbols, trackers, accept, close_ms)

    fetch.assert_awaited_once_with("PORTALTRY", "1m", 2, end_time_ms=close_ms - 1)
    assert trackers["PORTALTRY"] is port
    assert port.last == 34 * MINUTE
    [(alert, max_age)] = alerts
    assert (alert.seed, alert.base, alert.level, alert.stamp) == (watch.seed, 100, 15, close_ms)
    assert max_age == RADAR_SIGNAL_AGE
    assert port.observe(34 * MINUTE, 116, True) is None


def warmed_tracker():
    tracker = Tracker()
    for i in range(1, 31):
        assert tracker.observe(i * MINUTE, 100, True) is None
    return tracker


def test_watch_and_entry_share_a_prior_only_seed_and_do_not_repeat():
    tracker = warmed_tracker()
    assert tracker.observe(31 * MINUTE, 103, True) is None
    watch = tracker.observe(32 * MINUTE, 110, True)
    assert (watch.level, watch.base, watch.seed, watch.stamp) == (10, 100, 31 * MINUTE, 33 * MINUTE)
    assert tracker.observe(33 * MINUTE, 115, False) is None
    entry = tracker.observe(34 * MINUTE, 115, True)
    assert (entry.level, entry.seed, entry.stamp) == (15, watch.seed, 35 * MINUTE)
    assert tracker.observe(34 * MINUTE, 130, True) is None
    assert tracker.observe(35 * MINUTE, 130, True) is None


def test_gap_rewarm_and_direct_jump():
    tracker = warmed_tracker()
    assert tracker.observe(32 * MINUTE, 140, True) is None
    for i in range(33, 62):
        assert tracker.observe(i * MINUTE, 100, True) is None
    assert tracker.observe(62 * MINUTE, 117, True).level == 15


def test_exit_walk_uses_bids_and_round_trip_cost():
    book = read_book({"bids": [["102", "5"], ["100", "6"]], "asks": [["103", "10"]]})
    price, net, pct = mark_exit(book[0], 10, 1002, .002)
    assert price == 101
    assert net == approx(5.98)
    assert pct == approx(100 * net / 1002)
    assert mark_exit(book[0], 12, 1002, .002) is None
    assert read_book({"bids": [[110, 100]], "asks": [[109, 100]]}) is None


def test_trailing_activates_at_net_profit_and_never_backs_off():
    assert trailing_level(1.99, None, None) == (1.99, None)
    assert trailing_level(2, 1.99, None) == (2, .75)
    assert trailing_level(5, 2, .75) == approx((5, 4.2))
    assert trailing_level(4.3, 5, 4.2) == approx((5, 4.2))
    assert trailing_level(7, 5, 4.2) == approx((7, 6.5))
    assert trailing_level(12, 7, 6.5) == approx((12, 11.5))


def test_post_stop_path_measures_rebound_without_exit_candle_or_open_bar():
    rows = [
        [0, 4.8, 5, 4.2, 4.66],
        [MINUTE, 4.6, 4.7, 4.16, 4.19],
        [2 * MINUTE, 4.2, 4.53, 4.2, 4.49],
        [3 * MINUTE, 4.49, 5, 4.48, 5],
    ]
    assert followup_path(rows, MINUTE, 3 * MINUTE) == (2, 4.16, 4.7, 4.49, None)
    assert followup_path(rows[::2], MINUTE, 3 * MINUTE) is None
    assert followup_path([rows[1], rows[3]], MINUTE, 4 * MINUTE) == (1, 4.16, 4.7, 4.19, None)


def test_late_signal_uses_close_and_reports_the_time_the_candle_closes():
    rows = [
        [0, 1.32, 1.413, 1.32, 1.3746],
        [MINUTE, 1.373, 1.44, 1.34, 1.3812],
        [2 * MINUTE, 1.385, 1.438, 1.385, 1.4073],
    ]
    assert followup_path(rows, MINUTE, 3 * MINUTE, 1.2171)[-1] == 3 * MINUTE
    assert followup_path(rows, MINUTE, 2 * MINUTE, 1.2171)[-1] is None
