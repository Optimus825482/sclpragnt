import ast
import asyncio
import os
import sqlite3
import pathlib
import unittest
from unittest.mock import AsyncMock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RegressionContracts(unittest.TestCase):
    def test_bb_mfi_v3_signal_contract(self):
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(None)
        rising = [float(100 + index) for index in range(30)]
        up_kline = {"closes": rising, "highs": [value + 1 for value in rising],
                    "lows": [value - 1 for value in rising], "volumes": [100.0] * len(rising)}
        self.assertEqual(analyzer.strategy_bb_mfi_mean_reversion(up_kline), "sell")

        falling = [float(130 - index) for index in range(30)]
        down_kline = {"closes": falling, "highs": [value + 1 for value in falling],
                      "lows": [value - 1 for value in falling], "volumes": [100.0] * len(falling)}
        self.assertEqual(analyzer.strategy_bb_mfi_mean_reversion(down_kline), "buy")

    def test_bb_mfi_v3_backtest_has_signal_exit_and_pine_sizing(self):
        source = (ROOT / "app" / "backtest.py").read_text()
        self.assertIn('"bb_mfi_v3_signal_exit"', source)
        self.assertIn('config.MAX_POSITION_LAYERS = max(1, int(pyramiding_layers))', source)
        self.assertIn('order_pct if order_pct is not None else config.ORDER_PCT', source)

    def test_bb_mfi_metric_overrides_are_isolated_backtest_params(self):
        from app.backtest import PARAM_FIELDS
        self.assertEqual(PARAM_FIELDS["bb_mfi_bb_period"], "BB_MFI_BB_PERIOD")
        self.assertEqual(PARAM_FIELDS["bb_mfi_exit_mfi_min"], "BB_MFI_EXIT_MFI_MIN")

    def test_bb_mfi_v3_signal_exit_fills_at_next_bar_open(self):
        from app import backtest

        data = {key: [100.0] * 24 for key in ("opens", "highs", "lows", "closes", "volumes")}
        data["opens"][22] = 101.0
        data["times"] = list(range(24))

        def signal(_self, kline, _symbol=None):
            return "buy" if len(kline["closes"]) == 21 else "sell" if len(kline["closes"]) == 22 else None

        with patch.object(backtest, "_fetch_klines", return_value=data), \
             patch.object(backtest.ScalpAnalyzer, "strategy_bb_mfi_mean_reversion", signal):
            result = backtest._run_single("BTCTRY", "5m", 1, "BB_MFI_MEAN_REVERSION", {}, 500.0, 0.01, 0.01, 0.0)
        self.assertEqual(result["trades"][0]["reason"], "bb_mfi_v3_signal_exit")
        self.assertEqual(result["trades"][0]["exit_time"], 22)
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
        self.assertIn('"spread_above_entry_limit"', source)
        self.assertIn('"negative_orderflow"', source)

    def test_llm_entry_gate_rejects_biotry_like_overbought_setup(self):
        from app.main import _llm_entry_quality_gate

        snapshot = {
            "data_ready": True,
            "price": 1.203,
            "trend": {"alignment": "bullish"},
            "momentum": {"rsi_14": 95, "stochastic": {"k": 96}, "mfi_14": 83},
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
        self.assertIn('guard_reason = _llm_guard_block_reason(llm_guard)', source)

    def test_llm_reentry_cooldown_is_shorter_after_profit(self):
        source = (ROOT / "app" / "analyzer.py").read_text()
        config_source = (ROOT / "app" / "config.py").read_text()
        self.assertIn('LLM_PROFIT_REENTRY_COOLDOWN_SEC', source)
        self.assertIn('float(trade.get("pnl") or 0.0) > 0', source)
        self.assertIn('str(5 * 60)', config_source)
        self.assertIn('str(30 * 60)', config_source)

    def test_alert_can_trigger_gated_paper_entry(self):
        source = (ROOT / "app" / "alerting.py").read_text()
        main_source = (ROOT / "app" / "main.py").read_text()
        self.assertIn('on_paper_trigger=None', source)
        self.assertIn('"auto_paper_trade" in channels', source)
        self.assertIn('on_paper_trigger=auto_open_from_alert', main_source)
        self.assertIn('"source": "market_alert"', main_source)
        self.assertIn('"auto_paper_trade"', main_source)

    def test_health_defaults_to_postgres(self):
        source = (ROOT / "app" / "main.py").read_text()
        self.assertIn('os.getenv("DB_BACKEND", "postgres")', source)

    def test_production_entrypoint_is_postgres_only(self):
        source = (ROOT / "entrypoint.sh").read_text()
        self.assertIn('${DB_BACKEND:-postgres}', source)
        self.assertIn('DATABASE_URL', source)
        self.assertIn('exit 1', source)

    def test_default_skill_uses_postgres_boolean_literal(self):
        source = (ROOT / "app" / "database.py").read_text()
        self.assertIn('enabled_literal = "TRUE"', source)
        self.assertIn('enabled_literal = "1"', source)
        self.assertIn('VALUES(?,?,{enabled_literal},?)', source)

    def test_postgres_migration_retries_transient_connection_failures(self):
        source = (ROOT / "scripts" / "run_postgres_migration.py").read_text()
        self.assertIn('for attempt in range(1, 13)', source)
        self.assertIn('await asyncio.sleep(5)', source)
        self.assertIn('PostgreSQL migration bağlantısı kurulamadı', source)

    def test_compose_forces_postgres_backend(self):
        source = (ROOT.parent / "docker-compose.yaml").read_text()
        self.assertIn("DB_BACKEND: postgres", source)

    def test_compose_passes_runtime_strategy_and_llm_configuration(self):
        source = (ROOT.parent / "docker-compose.yaml").read_text(encoding="utf-8")
        self.assertIn("LLM_ENCRYPTION_KEY: ${LLM_ENCRYPTION_KEY:?", source)
        self.assertIn("TOP_GAINERS_AUTO_ACTIVATE: ${TOP_GAINERS_AUTO_ACTIVATE:-true}", source)
        self.assertIn("TOP_GAINERS_LIMIT: ${TOP_GAINERS_LIMIT:-70}", source)
        self.assertIn("TOP_GAINERS_REFRESH_SEC: ${TOP_GAINERS_REFRESH_SEC:-21600}", source)
        self.assertIn("NEXT_PUBLIC_VAPID_PUBLIC_KEY: ${NEXT_PUBLIC_VAPID_PUBLIC_KEY:-}", source)

        dockerfile = (ROOT.parent / "frontend" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG NEXT_PUBLIC_VAPID_PUBLIC_KEY", dockerfile)
        self.assertIn("ENV NEXT_PUBLIC_VAPID_PUBLIC_KEY=${NEXT_PUBLIC_VAPID_PUBLIC_KEY}", dockerfile)
        self.assertNotIn("DB_BACKEND: ${DB_BACKEND:-postgres}", source)
        self.assertIn("@postgres:5432/${POSTGRES_DB:-scalper}", source)
        self.assertNotIn("DATABASE_URL:-postgresql://", source)

    def test_symbol_activity_replaces_scheduled_top_gainer_universe(self):
        source = (ROOT / "app" / "main.py").read_text()
        config_source = (ROOT / "app" / "config.py").read_text()
        self.assertIn('async def refresh_top_gainer_symbols()', source)
        self.assertIn('async def refresh_symbol_activity()', source)
        self.assertIn('_start_background(symbol_activity_loop(), "symbol-activity")', source)
        self.assertNotIn('asyncio.create_task(top_gainers_refresh_loop()', source)
        self.assertIn('@app.get("/api/market/top-gainers")', source)
        self.assertIn('SYMBOL_ACTIVITY_REFRESH_SEC', config_source)
        self.assertIn('TOP_GAINERS_LIMIT = max(1, min(70', config_source)
        self.assertIn('source": "binance_tr_public_24h_ticker"', source)
        self.assertIn('known_try = set(await trading_symbols("TRY"))', source)

    def test_symbol_activity_does_not_overwrite_configured_scan_symbols(self):
        tree = ast.parse((ROOT / "app" / "main.py").read_text())
        refresh = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "refresh_symbol_activity")
        refresh_source = ast.get_source_segment((ROOT / "app" / "main.py").read_text(), refresh)
        self.assertIsNotNone(refresh_source)
        self.assertNotIn("config.SYMBOLS = universe", refresh_source)
        self.assertIn("configured paper-trading scan universe", refresh_source)

    def test_scan_logs_have_one_auditable_scan_id_path_for_each_symbol(self):
        source = (ROOT / "app" / "main.py").read_text()
        self.assertIn('scan_id = f"automatic-{int(time.time() * 1000)}"', source)
        self.assertIn('scan_id = f"manual-{uuid.uuid4().hex[:12]}"', source)
        self.assertIn('"MIGRATION_BLOCKED"', source)
        self.assertIn('item.get("scan_id") == scan_id', source)

    def test_manual_scan_evaluates_passive_configured_symbols(self):
        source = (ROOT / "app" / "main.py").read_text()
        start = source.index('async def manual_strategy_scan():')
        end = source.index('\n@app.get("/api/strategy/scan-logs")', start)
        manual_source = source[start:end]
        self.assertIn('passive_overridden += 1', manual_source)
        self.assertNotIn('_record_strategy_scan_log("manual", symbol, "PASSIVE"', manual_source)
        self.assertIn('ticker.get("last_price")', manual_source)
        self.assertIn('activity_status=activity_status', manual_source)

    def test_strategy_replay_uses_configured_symbols_and_public_history_fallback(self):
        source = (ROOT / "app" / "main.py").read_text()
        start = source.index('async def _run_strategy_replay(')
        end = source.index('\n@app.post("/api/strategy/manual-scan")', start)
        replay_source = source[start:end]
        self.assertIn('symbols = [s.upper() for s in config.SYMBOLS]', replay_source)
        self.assertNotIn('config.SYMBOLS if s not in config.PASSIVE_SYMBOLS', replay_source)
        self.assertIn('fetch_klines(symbol, "5m", limit=400)', replay_source)
        self.assertIn('int(row.get("close_time") or 0) <= now_ms', replay_source)
        self.assertNotIn('await database.upsert_market_candles', replay_source)
        self.assertIn('"BUY_SIGNAL" if strategy_fn(kline, symbol) == "buy" else "NO_SIGNAL"', replay_source)
        self.assertIn('Aktif tarama sembol listesi boş', replay_source)


class StrategyReplayBehavior(unittest.IsolatedAsyncioTestCase):
    async def test_replay_checks_only_latest_closed_candles_without_mutating_state(self):
        from app import main

        now_ms = int(__import__("time").time() * 1000)
        closed_rows = [{
            "symbol": "BTC_TRY", "timeframe": "5m", "open_time": now_ms - (23 - index) * 300_000,
            "close_time": now_ms - (22 - index) * 300_000, "open": 100 + index,
            "high": 101 + index, "low": 99 + index, "close": 100 + index,
            "volume": 10 + index,
        } for index in range(22)]
        incomplete_row = {**closed_rows[-1], "open_time": now_ms - 60_000, "close_time": now_ms + 240_000, "close": 999999}
        strategy_lengths = []

        def fake_strategy(kline, _symbol):
            strategy_lengths.append(len(kline["closes"]))
            return "buy" if len(kline["closes"]) == 22 else None

        async def no_mutation(*_args, **_kwargs):
            self.fail("Signal replay must not persist candles or mutate strategy state")

        previous_symbols = main.config.SYMBOLS
        previous_strategy = main.config.ACTIVE_STRATEGY
        previous_positions = dict(main.analyzer.positions)
        main.config.SYMBOLS = ["BTC_TRY"]
        main.config.ACTIVE_STRATEGY = "BB_MFI_MEAN_REVERSION"
        main._strategy_replay_jobs["closed-candle-test"] = {
            "job_id": "closed-candle-test", "status": "queued", "strategy": main.config.ACTIVE_STRATEGY,
            "timeframe": "5m", "candle_count": 2, "completed": 0, "total": 0, "results": [], "logs": [],
        }
        try:
            with patch.object(main.database, "get_market_candles", AsyncMock(return_value=closed_rows + [incomplete_row])), \
                 patch.object(main.database, "upsert_market_candles", no_mutation), \
                 patch.object(main, "fetch_klines", AsyncMock()) , \
                 patch.object(main.analyzer, "strategy_bb_mfi_mean_reversion", fake_strategy):
                await main._run_strategy_replay("closed-candle-test", 2)
        finally:
            main.config.SYMBOLS = previous_symbols
            main.config.ACTIVE_STRATEGY = previous_strategy

        job = main._strategy_replay_jobs.pop("closed-candle-test")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["completed"], 2)
        self.assertEqual(job["total"], 2)
        self.assertEqual(strategy_lengths, [21, 22])
        self.assertEqual([result["close"] for result in job["results"]], [120.0, 121.0])
        self.assertEqual([result["action"] for result in job["results"]], ["NO_SIGNAL", "BUY_SIGNAL"])
        self.assertEqual(main.analyzer.positions, previous_positions)

    async def test_replay_endpoint_rejects_candle_counts_outside_one_to_twenty(self):
        from app.main import start_strategy_replay
        from fastapi import HTTPException

        for candle_count in (0, 21, "not-a-number"):
            with self.assertRaises(HTTPException) as raised:
                await start_strategy_replay({"candle_count": candle_count})
            self.assertEqual(raised.exception.status_code, 422)

    def test_llm_market_scan_uses_fast_hot_cache_defaults(self):
        source = (ROOT / "app" / "main.py").read_text()
        config_source = (ROOT / "app" / "config.py").read_text()
        self.assertIn('["5m", "15m", "1h"]', source)
        self.assertIn('LLM_MARKET_SCAN_CACHE_SEC', config_source)
        self.assertIn('"scan_mode": "fast_hot_cache"', source)
        self.assertIn('"fresh"', source)

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

    def test_live_strategy_reads_ram_market_klines_not_historical_database(self):
        source = (ROOT / "app" / "analyzer.py").read_text()
        main_source = (ROOT / "app" / "main.py").read_text()
        # Live evaluation receives the in-memory MarketData cache. Historical
        # PostgreSQL reads belong to replay/backtest paths only.
        self.assertGreaterEqual(source.count("self.market.get_ut_kline(symbol, tf)"), 1)
        self.assertIn("trigger=5m_candle_close", main_source)
        self.assertIn("await database.get_market_candles(symbol, \"5m\")", main_source)

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
