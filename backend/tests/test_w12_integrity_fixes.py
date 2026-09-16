"""W12 — düzeltme planına hiç atanmamış bulgular için kilit testleri.

Kapsam: V-02 (açılış döngüsü), V-03 (002 migration), V-04 (okuma yolu saflığı),
V-05 (`get_*` yazmaz), V-06 (NULL trade_id kapanışı), V-16 (LIMIT clamp),
V-19 (LLM SQL `?` dönüşümü).

Testler Postgres gerektirmez: `_run_db` yamalanır ve op() sahte bağlantıyla
çalıştırılır; hem üretilen SQL hem dönen sonuç doğrulanır.
Mutasyon kanıtı: `outputs/denetim_2026-09-12/scratch/verify_w12_mutations.py`.
"""
import asyncio
import hashlib
import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database  # noqa: E402
from app.config import config as app_config  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class _FakeCursor:
    def __init__(self, rows=None, rowcount=0, description=None):
        self._rows = list(rows) if rows else []
        self.rowcount = rowcount
        self.description = description

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _RoutedConn:
    """SQL metnine göre satır döndüren sahte bağlantı; ifadeleri kaydeder."""

    def __init__(self, routes=(), default=(), fail_on=None):
        self.routes = list(routes)
        self.default = list(default)
        self.fail_on = fail_on
        self.statements = []
        self.calls = []
        self.commits = 0
        self.conn = self

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        self.statements.append(text)
        self.calls.append((text, params))
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("kısıt kurulamadı (mevcut veride ihlal)")
        for needle, rows in self.routes:
            if needle in text:
                return _FakeCursor(rows)
        return _FakeCursor(self.default)

    def executemany(self, sql, values):
        self.statements.append(" ".join(str(sql).split()))
        self.values = list(values)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _patched_run_db(conn):
    async def runner(operation):
        return operation(conn)
    return runner


async def _noop_backfill():
    return 0


class ReadPathPurityTests(unittest.TestCase):
    """V-04 — istatistik uçları DDL/INSERT/COMMIT yapmamalı."""

    def _run(self, fn):
        conn = _RoutedConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            result = asyncio.run(fn())
        return result, conn

    def _assert_read_only(self, conn):
        ddl = [s for s in conn.statements
               if s.upper().startswith(("ALTER", "CREATE", "INSERT", "UPDATE", "DELETE"))]
        assert ddl == [], ddl
        assert conn.commits == 0, "okuma yolu COMMIT etti"

    def test_stats_is_read_only(self):
        _result, conn = self._run(lambda: database.macd_monitor_alert_stats(days=1))
        self._assert_read_only(conn)

    def test_conditional_stats_is_read_only(self):
        _result, conn = self._run(
            lambda: database.macd_monitor_alert_conditional_stats(days=1))
        self._assert_read_only(conn)

    def test_event_paths_is_read_only(self):
        _result, conn = self._run(
            lambda: database.macd_monitor_alert_event_paths(days=1, kind="early"))
        self._assert_read_only(conn)

    def test_baseline_map_never_computes(self):
        conn = _RoutedConn()
        with mock.patch.object(database, "_baseline_rows_for_bucket",
                               side_effect=AssertionError("okuma yolu taban ÜRETTİ")):
            result = database._baseline_map(conn, {123, 456})
        assert result == {}


class InitDbResilienceTests(unittest.TestCase):
    """V-02/V-04/V-06 — açılış: toleranslı kısıtlar, şema hazırlığı, tek sha."""

    def setUp(self):
        # `_ensure_macd_evidence_schema` modül-global bayrağı süreç boyunca
        # bir kez çalışır; başka bir test dosyası onu True bırakmış olabilir.
        self._flag = database._MACD_EVIDENCE_SCHEMA_READY
        database._MACD_EVIDENCE_SCHEMA_READY = False

    def tearDown(self):
        database._MACD_EVIDENCE_SCHEMA_READY = self._flag

    def _run_init_db(self, conn):
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)), \
                mock.patch.object(database, "backfill_position_trade_ids", _noop_backfill):
            asyncio.run(database.init_db())
        return conn

    def test_unique_constraints_are_created(self):
        conn = self._run_init_db(_RoutedConn(routes=[("to_regclass", [[None]])]))
        for name in ("uq_trades_trade_id", "uq_positions_trade_id",
                     "auto_paper_trades_one_open_per_symbol"):
            assert any(name in s for s in conn.statements), name

    def test_failing_constraint_does_not_abort_boot(self):
        # V-02: tekil transaction abort olursa kalıcı açılış döngüsü oluşurdu.
        conn = _RoutedConn(routes=[("to_regclass", [[None]])],
                           fail_on="auto_paper_trades_one_open_per_symbol")
        self._run_init_db(conn)
        assert any("idx_signals_trade_id" in s for s in conn.statements)

    def test_evidence_schema_is_prepared_at_boot(self):
        conn = self._run_init_db(_RoutedConn(routes=[("to_regclass", [[None]])]))
        assert any("macd_market_baseline" in s for s in conn.statements)

    def test_schema_sha_covers_all_migrations(self):
        # V-03: her migration dosyası uygulanır; sha TÜM dosyaların birleşimidir.
        # R2 (2026-09-14): liste artık SABİT DEĞİL, glob'lanır — yeni bir migration
        # eklenip `init_db`'nin tuple'ına yazılmazsa test KIRILIR (002'nin bir zamanlar
        # "ölü dosya" olması gibi sessiz bir boşluk oluşmasın).
        conn = self._run_init_db(_RoutedConn(routes=[("to_regclass", [[None]])]))
        # init_db ile AYNI okuma yolu (metin + evrensel satır sonu + utf-8).
        names = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
        assert names, "migration dosyası bulunamadı"
        schema_text = "".join(
            (MIGRATIONS / name).read_text(encoding="utf-8") + "\n" for name in names)
        expected = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
        recorded = [params[0] for sql, params in conn.calls
                    if "schema_sha256" in sql and params]
        assert recorded and recorded[0] == expected, recorded


class SymbolTargetStatePurityTests(unittest.TestCase):
    """V-05 — `get_*` yazmaz; kayıt tek transaction'da günceller."""

    def test_get_missing_row_does_not_insert(self):
        conn = _RoutedConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            state = asyncio.run(database.get_symbol_target_state("btcusdt"))
        assert state["symbol"] == "BTCUSDT"
        assert state["target_pct"] == 2.0
        assert not any(s.upper().startswith(("INSERT", "UPDATE")) for s in conn.statements)
        assert conn.commits == 0

    def test_record_upserts_and_updates_in_one_transaction(self):
        row = {"target_pct": 2.0, "horizon_minutes": 5, "success_count": 0,
               "fail_count": 0, "total_count": 0, "last_adjusted_at": 0.0, "created_at": 0.0}
        conn = _RoutedConn(routes=[("FROM symbol_target_state", [row])])
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            state = asyncio.run(database.record_symbol_target_outcome("BTCUSDT", True))
        assert state["success_count"] == 1
        inserts = [s for s in conn.statements if s.upper().startswith("INSERT")]
        updates = [s for s in conn.statements if s.upper().startswith("UPDATE")]
        assert len(inserts) == 1 and "ON CONFLICT(symbol) DO NOTHING" in inserts[0]
        assert len(updates) == 1
        assert conn.commits == 1


class ClosePositionNullTradeIdTests(unittest.TestCase):
    """V-06 — `trade_id` NULL iken pozisyon kapatılabilmeli."""

    def test_null_trade_id_uses_symbol_identity(self):
        conn = _RoutedConn(routes=[
            ("SELECT quantity FROM positions", [[1.0]]),
            ("SELECT amount FROM virtual_wallet", [[1000.0]]),
            ("SELECT COUNT(*) FROM trades WHERE trade_id=?", [[0]]),
            ("SELECT COUNT(*) FROM trades WHERE symbol=", [[1]]),
            ("SELECT COUNT(*) FROM positions WHERE symbol=?", [[0]]),
        ])
        trade = {"symbol": "BTCUSDT", "strategy": "LLM_PAPER", "side": "LONG",
                 "entry_price": 100.0, "exit_price": 101.0, "quantity": 1.0,
                 "pnl": 1.0, "pnl_pct": 1.0, "entry_time": 1.0, "exit_time": 2.0,
                 "commission": 0.0, "reason": "tp", "entry_context": {},
                 "max_favorable_pct": 0.01, "max_adverse_pct": -0.01, "hold_seconds": 1.0,
                 "trade_id": None}
        sig = {"timestamp": 2.0, "symbol": "BTCUSDT", "action": "CLOSE_LONG",
               "price": 101.0, "reason": "tp"}
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            asyncio.run(database.commit_close_position("BTCUSDT", "USDT", 0.0, trade, sig))
        assert any("entry_time=? AND exit_time=?" in s for s in conn.statements), conn.statements


class LimitClampTests(unittest.TestCase):
    """V-16 — kullanıcı girdisi LIMIT'i sınırsız büyütememeli."""

    def _params(self, fn):
        conn = _RoutedConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            asyncio.run(fn())
        return conn.calls

    def test_chart_forecast_history_is_clamped(self):
        calls = self._params(lambda: database.list_chart_forecasts("BTCUSDT", limit=10 ** 9))
        _sql, params = calls[0]
        assert params[-1] == 500

    def test_pending_chart_forecasts_is_clamped(self):
        calls = self._params(lambda: database.get_pending_chart_forecasts(limit=10 ** 9))
        _sql, params = calls[0]
        assert params[-1] == 500

    def test_monitoring_notifications_is_clamped(self):
        calls = self._params(lambda: database.list_monitoring_notifications(limit=10 ** 9))
        _sql, params = calls[0]
        assert params[-1] == 500


class ReadOnlyQueryRawExecuteTests(unittest.TestCase):
    """V-19 — LLM SQL'i `?` → `%s` dönüşümüne uğramamalı."""

    class _RawCursor:
        description = [("x",)]

        def fetchall(self):
            return [[1]]

    class _RawConn:
        def __init__(self):
            self.raw_sql = None
            self.compat_used = False

        def raw_execute(self, sql, params=()):
            self.raw_sql = sql
            return ReadOnlyQueryRawExecuteTests._RawCursor()

        def execute(self, sql, params=()):
            self.compat_used = True
            raise AssertionError("read_only_query compat execute kullandı (V-19)")

        def commit(self):
            pass

    def test_question_mark_literal_survives(self):
        conn = self._RawConn()
        with mock.patch.object(database, "_run_db", _patched_run_db(conn)):
            result = asyncio.run(database.read_only_query("SELECT '?' AS x FROM trades"))
        assert result == [{"x": 1}]
        assert "'?'" in conn.raw_sql
        assert conn.compat_used is False


class PostgresCompatRawExecuteTests(unittest.TestCase):
    """V-19 — compat `raw_execute` gerçekten dönüşüm yapmaz."""

    def test_raw_execute_preserves_question_marks(self):
        captured = {}

        class _Cursor:
            def execute(self, sql, params=()):
                captured["sql"] = sql

        class _Raw:
            def cursor(self):
                return _Cursor()

        compat = database._PostgresCompat(_Raw())
        compat.raw_execute("SELECT '?' AS x FROM trades")
        assert captured["sql"] == "SELECT '?' AS x FROM trades"

    def test_execute_still_translates(self):
        captured = {}

        class _Cursor:
            def execute(self, sql, params=()):
                captured["sql"] = sql

        class _Raw:
            def cursor(self):
                return _Cursor()

        compat = database._PostgresCompat(_Raw())
        compat.execute("SELECT * FROM trades WHERE symbol=?", ("BTCUSDT",))
        assert captured["sql"] == "SELECT * FROM trades WHERE symbol=%s"


class RadarUniverseMutationTests(unittest.TestCase):
    """G-09 — radar taraması kullanıcının evrenini mutasyona uğratmamalı."""

    def test_scan_reports_candidates_without_mutating_universe(self):
        import app.main as main

        volume = str(app_config.MIN_24H_QUOTE_VOLUME_TRY * 10)
        tickers = [
            {"symbol": "BTCUSDT", "priceChangePercent": "5", "quoteVolume": volume},
            {"symbol": "NEWUSDT", "priceChangePercent": "6", "quoteVolume": volume},
        ]

        async def fake_tickers():
            return tickers

        async def fake_symbols(_quote):
            return {"BTCUSDT", "NEWUSDT"}

        with mock.patch.object(main, "ticker_24h", fake_tickers), \
                mock.patch.object(main, "trading_symbols", fake_symbols), \
                mock.patch.object(main.config, "SYMBOLS", ["BTCUSDT"]), \
                mock.patch.object(main.market, "get_ut_kline", lambda *a, **k: {}):
            result = asyncio.run(main._gainers_radar_uncached(execute=False))
            # Patch bloğu İÇİNDE doğrula: yama kalkınca `config.SYMBOLS` gerçek
            # listeye döner ve mutasyonu maskeler.
            assert main.config.SYMBOLS == ["BTCUSDT"], "radar GET evreni mutasyona uğrattı"
            assert result["symbols"] == ["BTCUSDT"]
            assert result["auto_added"] == ["NEWUSDT"]


class SupervisedLoopTests(unittest.TestCase):
    """G-10 — bu döngüler süpervizörlü başlatılmalı, ham create_task değil."""

    def test_loop_starters_use_the_supervisor(self):
        from app.routers import auto_paper, macd_monitor, monitoring

        for starter in (monitoring.start_monitoring_loop,
                        auto_paper.start_auto_paper_loop,
                        macd_monitor.start_macd_monitor_loop):
            source = inspect.getsource(starter)
            assert "_start_background(" in source, starter.__qualname__
            assert "asyncio.create_task(" not in source, starter.__qualname__


class ExportAdminGateTests(unittest.TestCase):
    """G-05 — tüm işlem geçmişini döken CSV ucu admin kapısına sahip olmalı."""

    def test_export_endpoint_requires_admin(self):
        from app.routers import maintenance

        endpoint = maintenance.download_replay_parity_trade_csv
        assert "request" in inspect.signature(endpoint).parameters
        assert "_require_admin(" in inspect.getsource(endpoint)


if __name__ == "__main__":
    unittest.main()
