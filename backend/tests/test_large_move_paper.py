import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pytest import approx, mark, raises

from app import large_move_paper
from app.large_move_paper import (
    MINUTE,
    Alert,
    Tracker,
    database,
    followup_path,
    mark_exit,
    read_book,
    recent_notifications,
    scan_missing_bars,
    save_entry,
    save_watch,
    signal_notification,
    trailing_level,
)


@mark.asyncio
async def test_notification_history_keeps_watch_and_signal_as_separate_events(monkeypatch):
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
        events = await recent_notifications()
        assert [(event["symbol"], event["kind"]) for event in events] == [
            ("PORTALTRY", "large_move"), ("OPENTRY", "large_move"),
            ("PORTALTRY", "large_move_watch"), ("OPENTRY", "large_move_watch"),
            ("WATCHTRY", "large_move_watch"),
        ]
        assert events[0] == signal_notification("PORTALTRY", 60000, 180000, 118.5, 100)
        assert events[0] == {
            "id": "large-move-PORTALTRY-60000",
            "kind": "large_move",
            "symbol": "PORTALTRY",
            "message": "Bir dakikalık mum baz fiyatın +%18,5 üzerinde kapandı.",
            "price": 118.5,
            "triggered_at": 180.0,
        }
        assert events[-1] == {
            "id": "large-move-watch-WATCHTRY-0",
            "kind": "large_move_watch",
            "symbol": "WATCHTRY",
            "message": "Baz fiyata göre +%10 eşiği geçildi. Parite izlemeye alındı.",
            "triggered_at": 60.0,
        }
        assert await recent_notifications(2) == events[:2]


@mark.asyncio
async def test_watch_returns_true_once_and_preserves_an_earlier_candle(monkeypatch):
    migration = Path(__file__).resolve().parents[1] / "migrations/034_large_move_paper.sql"
    with sqlite3.connect(":memory:") as conn:
        conn.executescript(migration.read_text(encoding="utf-8"))

        async def run_db(operation):
            return operation(conn)

        monkeypatch.setattr(database, "_run_db", run_db)
        alert = Alert(60_000, 100, 240_000, 115, 15)
        assert await save_watch("CFGTRY", alert) is True
        assert await save_watch("CFGTRY", alert) is False
        assert await save_watch("CFGTRY", Alert(60_000, 100, 180_000, 110, 10)) is False
        assert conn.execute("SELECT watch_ms FROM large_move_paper").fetchone()[0] == 180_000


@mark.asyncio
@mark.parametrize("direct_jump", [False, True])
async def test_worker_records_early_watch_silently_then_broadcasts_watch_and_signal(monkeypatch, direct_jump):
    notices = asyncio.Queue()
    push = asyncio.Queue()
    listener_ready = asyncio.Event()
    market = SimpleNamespace(klines={}, get_depth_snapshot=lambda *a, **kw: {
        "bids": [[114.9, 20]], "asks": [[115, 20]],
    })

    def add_listener(listener):
        market.listener = listener
        listener_ready.set()

    market.add_bar_listener = add_listener
    market.remove_bar_listener = lambda listener: None
    clock = [31 * 60]
    monkeypatch.setattr(large_move_paper, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(large_move_paper, "open_trades", AsyncMock(return_value=[]))
    monkeypatch.setattr(large_move_paper, "refresh_followup_paths", AsyncMock())
    monkeypatch.setattr(large_move_paper.ws_manager, "broadcast", notices.put)
    send_push = AsyncMock(side_effect=lambda *a, **kw: push.put_nowait(kw))
    monkeypatch.setattr(large_move_paper.alerting, "deliver_alert_push", send_push)
    save_entry_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(large_move_paper, "save_entry", save_entry_mock)

    migrations = Path(__file__).resolve().parents[1] / "migrations"
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        for name in ("034_large_move_paper.sql", "037_large_move_early_watch.sql"):
            conn.executescript((migrations / name).read_text(encoding="utf-8"))

        early_recorded = asyncio.Event()
        save_early = large_move_paper.save_early_watch

        async def save_early_then_signal(symbol, alert):
            await save_early(symbol, alert)
            early_recorded.set()

        monkeypatch.setattr(large_move_paper, "save_early_watch", save_early_then_signal)

        async def run_db(operation):
            return operation(conn)

        monkeypatch.setattr(database, "_run_db", run_db)
        worker = asyncio.create_task(large_move_paper.run(market))
        try:
            await asyncio.wait_for(listener_ready.wait(), 2)

            def candle(minute, price):
                market.listener("CFGTRY", "1m", {
                    "closed": True, "time": minute * MINUTE, "close": price, "volume": 10,
                })

            for minute in range(1, 31):
                candle(minute, 100)
            clock[0] = 32 * 60
            if direct_jump:
                candle(31, 115)
            else:
                candle(31, 105)
                await asyncio.wait_for(early_recorded.wait(), 2)
                assert conn.execute("SELECT watch_price FROM large_move_early_watch").fetchone()[0] == 105
                assert conn.execute("SELECT COUNT(*) FROM large_move_paper").fetchone()[0] == 0
                assert notices.empty()
                send_push.assert_not_awaited()
                save_entry_mock.assert_not_awaited()

                clock[0] = 33 * 60
                candle(32, 110)
            watch = await asyncio.wait_for(notices.get(), 2)
            pushed = await asyncio.wait_for(push.get(), 2)
            assert watch["type"] == "large_move_alert"
            assert watch["data"]["kind"] == "large_move_watch"
            assert pushed["title"] == "CFGTRY izlemeye alındı"
            assert pushed["tag"] == watch["data"]["id"]
            assert pushed["extra"]["symbol"] == "CFGTRY"
            if not direct_jump:
                save_entry_mock.assert_not_awaited()
                clock[0] = 34 * 60
                candle(33, 115)
            signal = await asyncio.wait_for(notices.get(), 2)
            assert signal["data"]["kind"] == "large_move"
            assert signal["data"]["id"] != watch["data"]["id"]
            save_entry_mock.assert_awaited_once()
            send_push.assert_awaited_once()
            await asyncio.wait_for(early_recorded.wait(), 2)
            expected = 115 if direct_jump else 105
            assert conn.execute("SELECT watch_price FROM large_move_early_watch").fetchone()[0] == expected
        finally:
            worker.cancel()
            with raises(asyncio.CancelledError):
                await worker


@mark.asyncio
async def test_monitor_joins_watch_stages_and_distinguishes_expired_rows(monkeypatch):
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    now = 100_000
    now_ms = now * 1000
    monkeypatch.setattr(large_move_paper, "time", SimpleNamespace(time=lambda: now))
    market = SimpleNamespace(
        get_ticker=lambda symbol: {"last_price": 109},
        ticker_freshness=lambda symbol, **kwargs: {"fresh": symbol == "CFGTRY"},
    )

    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        for name in ("034_large_move_paper.sql", "037_large_move_early_watch.sql"):
            conn.executescript((migrations / name).read_text(encoding="utf-8"))

        async def run_db(operation):
            return operation(conn)

        monkeypatch.setattr(database, "_run_db", run_db)
        seed = now_ms - 5 * MINUTE
        await large_move_paper.save_early_watch("CFGTRY", Alert(seed, 100, seed + 2 * MINUTE, 106, 5))
        await large_move_paper.save_early_watch("CFGTRY", Alert(seed, 100, seed + MINUTE, 105, 5))
        await save_watch("CFGTRY", Alert(seed, 100, seed + 3 * MINUTE, 110, 10))
        await large_move_paper.save_early_watch("ROBOTRY", Alert(seed, 100, seed + MINUTE, 105, 5))
        expired = now_ms - 40 * MINUTE
        await large_move_paper.save_early_watch("THETRY", Alert(expired, 100, expired + MINUTE, 105, 5))

        payload = await large_move_paper.monitor_rows(market)
        cfg, robo, the = payload["rows"]
        assert (cfg["symbol"], cfg["display_status"], cfg["early_watch_price"], cfg["current_price"]) == ("CFGTRY", "watch", 105, 109)
        assert cfg["early_watch_ms"] == seed + MINUTE
        assert cfg["watch_ms"] == seed + 3 * MINUTE
        assert (robo["symbol"], robo["display_status"], robo["watch_ms"], robo["current_price"]) == ("ROBOTRY", "early", None, None)
        assert (the["symbol"], the["display_status"]) == ("THETRY", "expired")


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

    def accept(symbol, stamp, price, traded, *, from_radar):
        alert = trackers[symbol].observe(stamp, price, traded)
        if alert:
            alerts.append((alert, from_radar))

    symbols = ["USDTTRY", "HEITRY", "PORTALTRY", "PORTALUSDT"]
    close_ms = 35 * MINUTE
    await scan_missing_bars(symbols, trackers, accept, close_ms)
    await scan_missing_bars(symbols, trackers, accept, close_ms)

    fetch.assert_awaited_once_with("PORTALTRY", "1m", 2, end_time_ms=close_ms - 1)
    assert trackers["PORTALTRY"] is port
    assert port.last == 34 * MINUTE
    [(alert, from_radar)] = alerts
    assert (alert.seed, alert.base, alert.level, alert.stamp) == (watch.seed, 100, 15, close_ms)
    assert from_radar
    assert port.observe(34 * MINUTE, 116, True) is None


@mark.asyncio
@mark.parametrize(("from_radar", "lag", "ask", "expected"), [
    (True, 30, 1.598, None),
    (True, 30, 1.63, "radar_price_moved"),
    (True, 30, 1.55, "radar_price_moved"),
    (True, 91, 1.598, "stale_signal"),
    (False, 30, 1.598, "stale_signal"),
])
async def test_late_radar_entry_requires_current_price_near_confirmed_signal(
    monkeypatch, from_radar, lag, ask, expected,
):
    migration = Path(__file__).resolve().parents[1] / "migrations/034_large_move_paper.sql"
    alert = Alert(MINUTE, 1.37, 10 * MINUTE, 1.597, 15)
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute("CREATE TABLE llm_settings (key TEXT, value TEXT)")
        conn.create_function("pg_advisory_xact_lock", 1, lambda _: None)
        conn.execute(
            "INSERT INTO large_move_paper (symbol, seed_ms, base_price, watch_ms, status) VALUES (?, ?, ?, ?, 'watch')",
            ("THETRY", alert.seed, alert.base, alert.stamp),
        )

        async def run_db(operation):
            return operation(conn)

        monkeypatch.setattr(database, "_run_db", run_db)
        book = [(ask - 0.001, 1000)], [(ask, 1000)]
        assert await save_entry("THETRY", alert, book, alert.stamp / 1000 + lag, from_radar=from_radar)
        row = conn.execute("SELECT status, reason, entry_price FROM large_move_paper").fetchone()
        assert row["reason"] == expected
        assert row["status"] == ("blocked" if expected else "open")
        assert row["entry_price"] == (None if expected else approx(ask))


def warmed_tracker():
    tracker = Tracker()
    for i in range(1, 31):
        assert tracker.observe(i * MINUTE, 100, True) is None
    return tracker


def test_watch_and_entry_share_a_prior_only_seed_and_do_not_repeat():
    tracker = warmed_tracker()
    assert tracker.observe(31 * MINUTE, 103, True) is None
    early = tracker.observe(32 * MINUTE, 105, True)
    assert (early.level, early.base, early.seed, early.stamp) == (5, 100, 31 * MINUTE, 33 * MINUTE)
    watch = tracker.observe(33 * MINUTE, 110, True)
    assert (watch.level, watch.seed, watch.stamp) == (10, early.seed, 34 * MINUTE)
    assert tracker.observe(34 * MINUTE, 115, False) is None
    entry = tracker.observe(35 * MINUTE, 115, True)
    assert (entry.level, entry.seed, entry.stamp) == (15, watch.seed, 36 * MINUTE)
    assert tracker.observe(35 * MINUTE, 130, True) is None
    assert tracker.observe(36 * MINUTE, 130, True) is None


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
