import asyncio
import os
import sqlite3
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


os.environ.setdefault("DB_BACKEND", "sqlite")


class _Market:
    def __init__(self):
        self.tickers = {"BTCTRY": {"symbol": "BTCTRY", "last_price": 100.0, "timestamp": time.time() * 1000}}
        self.orderflow = {}

    def get_ticker(self, symbol):
        return self.tickers.get(symbol)

    def get_ut_kline(self, symbol, timeframe=None):
        return {
            "opens": [90.0, 95.0],
            "highs": [101.0, 102.0],
            "lows": [89.0, 94.0],
            "closes": [100.0, 101.0],
            "volumes": [10.0, 12.0],
            "times": [1, 2],
        }

    def get_orderflow(self, symbol):
        return {"bid_qty": 10.0, "ask_qty": 9.0, "spread_pct": 0.05, "updated_at": time.time()}

    def liquidity_status(self, symbol, order_value):
        return True, {"checks": {"quote_volume": True, "volume_ratio": True, "spread": True, "orderbook_depth": True}}


class LifecycleBehavior(unittest.IsolatedAsyncioTestCase):
    async def test_passive_symbol_is_blocked_at_central_opening_boundary(self):
        """Direct/LLM/radar entry paths cannot bypass symbol activity."""
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        analyzer = ScalpAnalyzer(_Market())
        save_signal = AsyncMock()
        activity = {
            "status": "PASSIVE",
            "checks": {"range_15m": False, "atr": False, "volume_ratio": True},
            "range_15m_pct": 0.08,
            "atr_pct": 0.07,
        }
        with patch.object(config, "SYMBOL_ACTIVITY_FILTER_ENABLED", True), \
             patch.object(config, "PASSIVE_SYMBOLS", {"BTCTRY"}), \
             patch.object(config, "SYMBOL_ACTIVITY_STATUS", {"BTCTRY": activity}), \
             patch("app.analyzer.database.save_signal", new=save_signal), \
             patch("app.analyzer.database.commit_open_position", new=AsyncMock()) as commit:
            result = await analyzer.open_position("btc_try", 100.0, "LONG", "LLM_PAPER", 1000.0)

        self.assertEqual(result["action"], "BUY_BLOCKED")
        self.assertEqual(result["reason"], "symbol_activity:passive:range_15m,atr")
        self.assertEqual(result["activity"]["range_15m_pct"], 0.08)
        save_signal.assert_awaited_once()
        commit.assert_not_awaited()

    async def test_automatic_scan_records_entry_ineligible_before_strategy_evaluation(self):
        """A failed liquidity preflight is an audit result, never a signal."""
        from app import main

        class _Clock:
            def __init__(self):
                self.calls = 0

            def time(self):
                self.calls += 1
                # The first value initializes the loop; the second starts an
                # entry scan.  Keep every later read on that same scan tick.
                return 0.0 if self.calls == 1 else 61.0

        ticker = {"symbol": "BTCTRY", "last_price": 100.0, "timestamp": 61_000}
        market = SimpleNamespace(
            get_ticker=Mock(return_value=ticker),
            kline_freshness=Mock(return_value={"fresh": True, "age_sec": 0.0}),
        )
        analyzer = SimpleNamespace(
            positions={},
            entry_liquidity_preflight=AsyncMock(
                return_value=(False, {"reason": "entry_ineligible:spread", "checks": {"spread": False}})
            ),
            evaluate=AsyncMock(return_value=[]),
        )
        scan_log = Mock()
        ws_manager = SimpleNamespace(broadcast=AsyncMock())

        sleep_calls = 0

        async def stop_after_first_cycle(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls > 1:
                raise asyncio.CancelledError()

        with patch.object(main, "time", _Clock()), \
             patch.object(main, "market", market), \
             patch.object(main, "analyzer", analyzer), \
             patch.object(main, "ws_manager", ws_manager), \
             patch.object(main, "_record_strategy_scan_log", scan_log), \
             patch.object(main, "migration_monitor", SimpleNamespace(state={"status": "idle"})), \
             patch.object(main.asyncio, "sleep", new=stop_after_first_cycle), \
             patch.object(main.config, "SYMBOLS", ["BTCTRY"]), \
             patch.object(main.config, "PASSIVE_SYMBOLS", set()), \
             patch.object(main.config, "STRATEGY_ENTRY_SCAN_INTERVAL_SEC", 60):
            with self.assertRaises(asyncio.CancelledError):
                await main.strategy_loop()

        analyzer.entry_liquidity_preflight.assert_awaited_once_with("BTCTRY", main.config.ACTIVE_STRATEGY)
        analyzer.evaluate.assert_awaited_once_with("BTCTRY", ticker, allow_entry=False)
        ws_manager.broadcast.assert_not_awaited()
        statuses = [call.args[2] for call in scan_log.call_args_list]
        self.assertIn("ENTRY_INELIGIBLE", statuses)
        self.assertNotIn("BUY_BLOCKED", statuses)

    async def test_opening_liquidity_race_is_entry_ineligible_not_buy_blocked(self):
        """The final writer-side liquidity recheck remains a non-signal guard."""
        from app.analyzer import ScalpAnalyzer

        market = _Market()
        market.liquidity_status = Mock(return_value=(False, {"checks": {"spread": False}}))
        analyzer = ScalpAnalyzer(market)
        saved = AsyncMock()
        commit = AsyncMock()

        with patch("app.analyzer.database.load_positions", new=AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.database.save_signal", new=saved), \
             patch("app.analyzer.database.commit_open_position", new=commit):
            result = await analyzer.open_position("BTCTRY", 100.0, "LONG", "EMA_VWAP_PULLBACK")

        self.assertEqual(result["action"], "ENTRY_INELIGIBLE")
        self.assertTrue(str(result["reason"]).startswith("entry_recheck_failed:"))
        commit.assert_not_awaited()
        saved.assert_not_awaited()

    async def test_bb_mfi_trade_context_uses_its_actual_exit_plan(self):
        """CSV/exported context must not report generic spot TP/SL for BB-MFI."""
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        analyzer = ScalpAnalyzer(None)
        commit = AsyncMock()
        with patch("app.analyzer.database.load_positions", new=AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.database.commit_open_position", new=commit):
            result = await analyzer.open_position("BTCTRY", 100.0, "LONG", "BB_MFI_MEAN_REVERSION")

        self.assertEqual(result["action"], "BUY_SIGNAL")
        persisted_position = commit.await_args.args[4]
        context = persisted_position["entry_context"]
        self.assertEqual(context["profit_target_pct"], config.BB_MFI_TAKE_PROFIT_PCT)
        self.assertEqual(context["stop_loss_pct"], config.BB_MFI_STOP_LOSS_PCT)
        self.assertIsNone(context["max_hold_sec"])

    async def test_bb_mfi_close_normalizes_a_legacy_context_plan(self):
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        trade = await ScalpAnalyzer(None)._record_trade(
            "BTCTRY",
            {
                "entry_price": 100.0,
                "quantity": 1.0,
                "entry_time": time.time(),
                "strategy": "BB_MFI_MEAN_REVERSION",
                "entry_context": {"profit_target_pct": 0.01, "stop_loss_pct": 0.012, "max_hold_sec": 14_400},
            },
            101.0,
            "bb_mfi_v3_signal_exit",
            0.3,
        )

        self.assertEqual(trade["entry_context"]["profit_target_pct"], config.BB_MFI_TAKE_PROFIT_PCT)
        self.assertEqual(trade["entry_context"]["stop_loss_pct"], config.BB_MFI_STOP_LOSS_PCT)
        self.assertIsNone(trade["entry_context"]["max_hold_sec"])

    async def test_bb_mfi_preflight_uses_the_same_equity_sizing_as_opening(self):
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        market = _Market()
        market.tickers["ETHTRY"] = {"symbol": "ETHTRY", "last_price": 100.0, "timestamp": time.time() * 1000}
        market.liquidity_status = Mock(return_value=(True, {"checks": {"spread": True}}))
        analyzer = ScalpAnalyzer(market)
        analyzer.positions = {"ETHTRY": {"entry_price": 50.0, "quantity": 1.0}}
        with patch.object(config, "ORDER_PCT", 0.90), \
             patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=1_000.0)):
            eligible, details = await analyzer.entry_liquidity_preflight("BTCTRY", "BB_MFI_MEAN_REVERSION")

        self.assertTrue(eligible)
        self.assertAlmostEqual(details["order_value_try"], 110.0, places=6)
        market.liquidity_status.assert_called_once_with("BTCTRY", 110.0)

    async def test_bb_mfi_preflight_applies_the_minimum_order_fallback(self):
        from app.analyzer import ScalpAnalyzer

        market = _Market()
        market.liquidity_status = Mock(return_value=(True, {"checks": {"spread": True}}))
        analyzer = ScalpAnalyzer(market)
        with patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=500.0)):
            eligible, details = await analyzer.entry_liquidity_preflight("BTCTRY", "BB_MFI_MEAN_REVERSION")

        self.assertTrue(eligible)
        self.assertEqual(details["order_value_try"], 250.0)
        market.liquidity_status.assert_called_once_with("BTCTRY", 250.0)

    async def test_market_order_client_request_id_is_durable(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(_Market())
        order = {"symbol": "BTCTRY", "side": "BUY", "order_type": "MARKET", "client_request_id": "req-1"}
        persisted = {}

        async def lookup(request_id):
            return persisted.get(request_id)

        async def save(row):
            persisted[row["client_request_id"]] = dict(row)

        analyzer.open_position = AsyncMock(return_value={"action": "BUY_SIGNAL", "symbol": "BTCTRY"})
        with patch("app.analyzer.database.get_paper_order_by_client_request_id", new=lookup), \
             patch("app.analyzer.database.save_paper_order", new=save):
            first = await analyzer.place_paper_order(order)
            second = await analyzer.place_paper_order(order)
        self.assertEqual(first["status"], "FILLED")
        self.assertTrue(second["idempotent_replay"])
        analyzer.open_position.assert_awaited_once()

    async def test_failed_market_order_reservation_becomes_terminal(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(_Market())
        persisted = {}
        async def lookup(request_id): return persisted.get(request_id)
        async def save(row): persisted[row["client_request_id"]] = dict(row)
        analyzer.open_position = AsyncMock(side_effect=RuntimeError("writer failed"))
        with patch("app.analyzer.database.get_paper_order_by_client_request_id", new=lookup), \
             patch("app.analyzer.database.save_paper_order", new=save):
            result = await analyzer.place_paper_order({"symbol": "BTCTRY", "side": "BUY", "order_type": "MARKET", "client_request_id": "req-fail"})
        self.assertFalse(result["ok"])
        self.assertEqual(persisted["req-fail"]["status"], "FAILED")

    async def test_stale_processing_order_is_recovered_as_failed(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(_Market())
        row = {"order_id": "stale", "client_request_id": "req-stale", "symbol": "BTCTRY",
               "status": "PROCESSING", "created_at": time.time() - 60}
        save = AsyncMock()
        with patch("app.analyzer.database.get_paper_order_by_client_request_id", new=AsyncMock(return_value=row)), \
             patch("app.analyzer.database.save_paper_order", new=save):
            result = await analyzer.place_paper_order({"symbol": "BTCTRY", "side": "BUY", "order_type": "MARKET", "client_request_id": "req-stale"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "FAILED")
        save.assert_awaited_once()

    async def test_pending_order_rejects_buy_blocked_result(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(_Market())
        order = {
            "order_id": "limit-blocked",
            "symbol": "BTCTRY",
            "side": "BUY",
            "order_type": "LIMIT",
            "status": "OPEN",
            "price": 101.0,
        }
        analyzer.pending_orders = [order]
        analyzer.open_position = AsyncMock(return_value={"action": "BUY_BLOCKED", "reason": "liquidity_filter:spread"})
        with patch("app.analyzer.database.save_paper_order", new=AsyncMock()):
            await analyzer._evaluate_pending_orders("BTCTRY", 100.0)
        self.assertEqual(order["status"], "REJECTED")

    async def test_global_position_limit_is_enforced_at_writer(self):
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        analyzer = ScalpAnalyzer(_Market())
        analyzer.positions = {"ETHTRY": {"strategy": "LLM_PAPER"}}
        with patch.object(config, "MAX_OPEN_POSITIONS", 1), \
             patch("app.analyzer.database.load_positions", new=AsyncMock(return_value={})), \
             patch("app.analyzer.database.save_signal", new=AsyncMock()) as save_signal:
            result = await analyzer.open_position("BTCTRY", 100.0, "LONG", "LLM_PAPER", 1000.0, 0.01, 0.02, 3600)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "BUY_BLOCKED")
        self.assertEqual(result["reason"], "max_open_positions_reached")
        save_signal.assert_awaited()

    def test_classic_reentry_guards_are_read(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(_Market())
        analyzer._timeout_block_until["BTCTRY"] = time.time() + 60
        self.assertEqual(analyzer._reentry_block_reason("BTCTRY", "5m"), "timeout_reentry_block")
        analyzer._timeout_block_until.clear()
        analyzer._hard_stop_block_until["BTCTRY"] = time.time() + 60
        self.assertEqual(analyzer._reentry_block_reason("BTCTRY", "5m"), "hard_stop_reentry_block")

    def test_expired_llm_guard_is_not_active(self):
        from app.main import _llm_guard_block_reason

        self.assertIsNone(_llm_guard_block_reason({"status": "active", "blocked_until": time.time() - 1}))
        self.assertEqual(
            _llm_guard_block_reason({"status": "active", "blocked_until": time.time() + 60}),
            "llm_guard:cooldown",
        )

    async def test_percent_alert_uses_selected_timeframe_return(self):
        from app.alerting import _rule_value

        market = _Market()
        value = _rule_value({"symbol": "BTCTRY", "rule_type": "percent", "timeframe": "5m"}, market, market.get_ticker("BTCTRY"))
        self.assertAlmostEqual(value, 0.0, places=6)

    async def test_alert_rearm_requires_a_separate_rearm_transition(self):
        from app.alerting import evaluate_rules

        market = _Market()
        market.tickers["BTCTRY"]["last_price"] = 106.0
        rule = {
            "id": 7,
            "symbol": "BTCTRY",
            "timeframe": "5m",
            "rule_type": "price",
            "operator": "lte",
            "threshold": 95.0,
            "rearm_threshold": 105.0,
            "armed": False,
            "cooldown_seconds": 0,
            "notify_channels": ["websocket"],
        }
        update = AsyncMock(return_value=rule)
        with patch("app.alerting.database.list_alert_rules", new=AsyncMock(return_value=[rule])), \
             patch("app.alerting.database.update_alert_rule", new=update), \
             patch("app.alerting.database.record_alert_trigger", new=AsyncMock()):
            events = await evaluate_rules(market)
        self.assertEqual(events, [])
        update.assert_awaited_once_with(7, {"armed": True, "last_value": 106.0})


class RestartPersistenceBehavior(unittest.IsolatedAsyncioTestCase):
    async def test_database_writer_enforces_limit_and_debits_current_cash(self):
        from app import database
        from app.config import config

        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript("""
            CREATE TABLE virtual_wallet(asset TEXT PRIMARY KEY, amount REAL);
            INSERT INTO virtual_wallet VALUES ('TRY', 10000);
            CREATE TABLE positions(symbol TEXT PRIMARY KEY, side TEXT, entry_price REAL, stop_price REAL,
              take_profit REAL, peak_price REAL, breakeven_hit INTEGER, quantity REAL, entry_time REAL,
              strategy TEXT, entry_context TEXT, trade_id TEXT);
            CREATE TABLE signals(id INTEGER PRIMARY KEY, timestamp REAL, symbol TEXT, action TEXT, price REAL,
              reason TEXT, strategy TEXT, trade_id TEXT);
            CREATE TABLE decision_logs(id INTEGER PRIMARY KEY, timestamp REAL, symbol TEXT, strategy TEXT,
              decision TEXT, reason TEXT, price REAL, metadata TEXT);
            CREATE TABLE analysis_snapshots(id INTEGER PRIMARY KEY, symbol TEXT, timeframe TEXT, captured_at REAL,
              source TEXT, methodology_version TEXT, regime TEXT, regime_confidence REAL, confluence_score REAL,
              payload TEXT, trade_id TEXT);
        """)

        async def run(operation):
            return operation(conn)

        pos = {"side": "LONG", "entry_price": 100.0, "quantity": 1.0, "entry_time": 1.0,
               "strategy": "LLM_PAPER", "entry_context": {}, "trade_id": "t1"}
        sig = {"timestamp": 1.0, "symbol": "BTCTRY", "action": "BUY_SIGNAL", "price": 100.0,
               "reason": "position_opened", "strategy": "LLM_PAPER", "trade_id": "t1"}
        with patch.object(config, "MAX_OPEN_POSITIONS", 1), patch("app.database._run_db", new=run):
            await database.commit_open_position("BTCTRY", "BTC", 0.0, 1.0, pos, sig)
            cash = conn.execute("SELECT amount FROM virtual_wallet WHERE asset='TRY'").fetchone()[0]
            self.assertLess(cash, 9900.0)
            with self.assertRaisesRegex(RuntimeError, "max_open_positions_reached"):
                await database.commit_open_position("ETHTRY", "ETH", 0.0, 1.0,
                    {**pos, "trade_id": "t2"}, {**sig, "symbol": "ETHTRY", "trade_id": "t2"})

    async def test_load_positions_does_not_invent_llm_exit_plan(self):
        from app import database

        row = {
            "symbol": "BTCTRY",
            "side": "LONG",
            "entry_price": 100.0,
            "stop_price": None,
            "take_profit": None,
            "peak_price": 110.0,
            "breakeven_hit": False,
            "quantity": 1.0,
            "entry_time": 1.0,
            "strategy": "LLM_PAPER",
            "entry_context": "{}",
            "trade_id": "t1",
        }

        class Result:
            def fetchall(self):
                return [row]

        class Connection:
            def execute(self, *_args, **_kwargs):
                return Result()

        async def run(operation):
            return operation(Connection())

        with patch("app.database._run_db", new=run):
            positions = await database.load_positions()
        position = positions["BTCTRY"]
        self.assertNotIn("llm_stop_price", position)
        self.assertNotIn("llm_take_profit_price", position)
        self.assertNotIn("llm_max_hold_sec", position)
        self.assertEqual(position["max_price"], 110.0)
        self.assertEqual(position["layers"], 1)


if __name__ == "__main__":
    unittest.main()
