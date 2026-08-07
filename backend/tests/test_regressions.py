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

    def test_llm_exit_creates_symbol_reentry_lock(self):
        source = (ROOT / "app" / "analyzer.py").read_text()
        self.assertIn("LLM_REENTRY_COOLDOWN_SEC", source)
        self.assertIn("LLM_REENTRY_MIN_MOVE_PCT", source)
        self.assertIn("rearm_required_pct", source)
        self.assertIn("atr_pct_at_exit", source)
        self.assertIn("except (TypeError, ValueError)", source)
        self.assertIn("LLM_REENTRY_BLOCKED", source)
        self.assertIn("requires_fresh_setup", source)

    def test_llm_entry_has_overextension_and_microstructure_gate(self):
        source = (ROOT / "app" / "main.py").read_text()
        self.assertIn("_llm_entry_quality_gate", source)
        self.assertIn("overbought_rsi", source)
        self.assertIn("negative_orderflow", source)
        self.assertIn("spread_above_entry_limit", source)
        self.assertIn("symbol_loss_streak", source)
        self.assertIn("symbol_negative_net_expectancy", source)
        self.assertIn('f"{higher_tf}_bearish_trend"', source)
        self.assertIn('for higher_tf in ("15m", "1h")', source)

    def test_llm_entry_gate_rejects_biotry_like_overbought_setup(self):
        from app.main import _llm_entry_quality_gate

        snapshot = {
            "data_ready": True,
            "price": 1.203,
            "trend": {"alignment": "bullish"},
            "momentum": {"rsi_14": 75, "stochastic": {"k": 96}, "mfi_14": 83},
            "oscillators": {"values": {"cci_20": 253}},
            "liquidity": {"spread_pct": 0.166, "orderflow_imbalance": -0.399},
            "channels": {"bollinger": {"upper": 1.202}},
        }
        ok, reasons = _llm_entry_quality_gate(snapshot, {
            "trades": 4, "current_loss_streak": 3, "expectancy_net_pnl": -0.5,
        })
        self.assertFalse(ok)
        self.assertIn("overbought_rsi", reasons)
        self.assertIn("negative_orderflow", reasons)
        self.assertIn("symbol_loss_streak", reasons)

    def test_llm_system_prompt_has_trade_manager_rules(self):
        source = (ROOT / "app" / "llm_analysis.py").read_text()
        self.assertIn("TRADE_MANAGER_RULES", source)
        self.assertIn("cooldown ve sembolün dinamik re-arm", source)

    def test_entry_policy_endpoint_exposes_auditable_contract(self):
        source = (ROOT / "app" / "main.py").read_text()
        self.assertIn('@app.get("/api/llm/entry-policy")', source)
        self.assertIn('"policy_version": "scalper-trade-manager-v2"', source)

    def test_llm_close_does_not_schedule_immediate_replenishment(self):
        source = (ROOT / "app" / "main.py").read_text()
        self.assertGreaterEqual(source.count('if str(sig.get("strategy", "")).upper() != "LLM_PAPER":'), 2)
        self.assertIn('llm_guard = await database.get_llm_symbol_guard(symbol)', source)
        self.assertIn('"reason": "llm_guard:cooldown"', source)

    def test_health_defaults_to_postgres(self):
        source = (ROOT / "app" / "main.py").read_text()
        self.assertIn('os.getenv("DB_BACKEND", "postgres")', source)

    def test_production_entrypoint_is_postgres_only(self):
        source = (ROOT / "entrypoint.sh").read_text()
        self.assertIn('${DB_BACKEND:-postgres}', source)
        self.assertIn('DATABASE_URL', source)
        self.assertIn('exit 1', source)

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
            asyncio.run(database.ensure_default_scalper_skill())
            skills = database._DB_CONN.execute(
                "SELECT name,enabled FROM llm_skills WHERE name=?",
                ("Scalper Trade Manager",),
            ).fetchall()
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0]["enabled"], 1)
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
