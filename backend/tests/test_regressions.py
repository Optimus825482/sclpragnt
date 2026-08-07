import ast
import asyncio
import os
import sqlite3
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RegressionContracts(unittest.TestCase):
    def test_backtest_fill_model_charges_round_trip_costs(self):
        from app.backtest import _close_trade

        _, pnl, fees, trade = _close_trade(
            9000.0, 100.0, 101.0, 10.0, 1000.0, "test",
            spread_pct=0.002, slippage_pct=0.001,
        )
        self.assertGreater(fees, 0)
        self.assertLess(pnl, 10.0)
        self.assertEqual(trade["spread_pct"], 0.002)
        self.assertEqual(trade["slippage_pct"], 0.001)

    def test_backtest_has_explicit_microstructure_and_spread_contract(self):
        from app.config import config

        self.assertGreater(config.BACKTEST_ASSUMED_SPREAD_PCT, 0)
        source = (ROOT / "app" / "backtest.py").read_text()
        self.assertIn('"microstructure_model"', source)
        self.assertIn('"cost_model"', source)

    def test_custom_exit_policy_is_not_forced_to_use_tp_sl(self):
        source = (ROOT / "app" / "backtest.py").read_text()
        self.assertIn('"conditions_only"', source)
        self.assertIn('"custom_exit_condition"', source)
        self.assertIn('"custom_trailing_stop"', source)
        self.assertIn('"custom_max_hold"', source)

    def test_main_has_one_reconcile_function(self):
        tree = ast.parse((ROOT / "app" / "main.py").read_text())
        names = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.assertEqual(names.count("reconcile_portfolio"), 1)
        self.assertEqual(names.count("reconcile_portfolio_state"), 1)

    def test_radar_has_interval_and_lock(self):
        source = (ROOT / "app" / "main.py").read_text()
        self.assertIn("async with _radar_lock", source)
        self.assertIn("await asyncio.sleep(config.GAINER_RADAR_INTERVAL_SEC)", source)

    def test_concurrent_position_open_is_serialized(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(None)
        self.assertIsInstance(analyzer._open_position_lock, asyncio.Lock)

    def test_websocket_runtime_isolated_module(self):
        from app.ws_runtime import ConnectionManager

        manager = ConnectionManager()
        self.assertEqual(manager.active_connections, [])

    def test_sqlite_list_contract_supports_filter_and_offset(self):
        from app import database

        previous_backend = os.environ.get("DB_BACKEND")
        previous_conn = database._DB_CONN
        try:
            os.environ["DB_BACKEND"] = "sqlite"
            database._DB_CONN = sqlite3.connect(":memory:", check_same_thread=False)
            database._DB_CONN.row_factory = sqlite3.Row
            asyncio.run(database.init_db())
            database._DB_CONN.execute(
                "INSERT INTO trades(symbol,strategy,exit_time,pnl) VALUES (?,?,?,?)",
                ("BTCTRY", "MOMENTUM", 3, 1.0),
            )
            database._DB_CONN.execute(
                "INSERT INTO trades(symbol,strategy,exit_time,pnl) VALUES (?,?,?,?)",
                ("ETHTRY", "MOMENTUM", 2, 2.0),
            )
            database._DB_CONN.commit()
            rows = asyncio.run(database.get_trades(limit=1, offset=1, strategy="MOMENTUM"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "ETHTRY")
        finally:
            if database._DB_CONN:
                database._DB_CONN.close()
            database._DB_CONN = previous_conn
            if previous_backend is None:
                os.environ.pop("DB_BACKEND", None)
            else:
                os.environ["DB_BACKEND"] = previous_backend


if __name__ == "__main__":
    unittest.main()
