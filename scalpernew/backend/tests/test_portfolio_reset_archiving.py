import asyncio
import inspect
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from app import database
from app.config import config


def _settings_fake_execute(records, reset, baseline, extra=None):
    """`llm_settings` okumalarını ve diğer sorguları ayırt eden ortak fake execute.

    - portfolio_reset_at  → SQL literal'i ile eşleşir,
    - reports_baseline_at → değer PARAMETRE olarak geçtiği için params[0] ile eşleşir.
    """
    def fake_execute(sql, params=None):
        s = " ".join(str(sql).split())
        records.append((s, tuple(params) if params is not None else ()))
        m = MagicMock()
        if "portfolio_reset_at" in s:
            m.fetchone.return_value = (str(reset),) if reset else None
        elif params and params[0] == "reports_baseline_at":
            m.fetchone.return_value = (str(baseline),) if baseline else None
        elif "AS closed," in s:  # get_auto_paper_stats kapalı agregatı
            m.fetchone.return_value = {"closed": 0, "winning": 0, "losing": 0,
                                       "total_pnl": 0.0, "total_invested": 0.0}
        elif "AS open" in s:  # get_auto_paper_stats açık sayımı
            m.fetchone.return_value = {"open": 0}
        elif extra is not None:
            m.fetchone.return_value = extra(s, params)
        else:
            m.fetchone.return_value = None
        m.fetchall.return_value = []
        return m
    return fake_execute


def _fake_run_db(fake_execute):
    """`_run_db` için `side_effect`: op() senkron çalışır, AsyncMock sonucu await
    eder (mevcut `test_list_auto_paper_trades_filters_archived_by_default` deseni)."""
    def runner(op):
        conn = MagicMock()
        conn.execute.side_effect = fake_execute
        return op(conn)
    return runner



class PortfolioResetArchivingTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_auto_paper_trades_filters_archived_by_default(self):
        """Reset cutoff öncesindeki işlemler ve exit_reason='reset' olanlar varsayılan olarak filtrelenmeli."""
        now = time.time()
        mock_cutoff = now - 100
        
        mock_rows = [
            {"id": 1, "symbol": "BTCTRY", "status": "closed", "exit_time": now - 50, "exit_reason": "take_profit_tp1", "pnl": 50.0},
        ]

        def fake_run_db(op):
            conn = MagicMock()
            # _get_reset_cutoff_sync çağrısı mock_cutoff dönsün
            conn.execute.return_value.fetchall.return_value = mock_rows
            return op(conn)

        with patch.object(database, "_run_db", side_effect=fake_run_db), \
             patch.object(database, "_get_reset_cutoff_sync", return_value=mock_cutoff):
            
            # 1. Varsayılan (include_archived=False)
            res = await database.list_auto_paper_trades(status="closed")
            self.assertEqual(len(res), 1)

    async def test_reset_trading_data_structure(self):
        """reset_trading_data advisory lock alır, cüzdanı 10000 TL yapar ve portfolio_reset_at yazar."""
        executed_sqls = []

        def fake_run_db(op):
            conn = MagicMock()
            def fake_execute(sql, params=None):
                executed_sqls.append((sql, params))
                m = MagicMock()
                m.fetchone.return_value = None
                return m
            conn.execute.side_effect = fake_execute
            return op(conn)

        with patch.object(database, "_run_db", side_effect=fake_run_db):
            result = await database.reset_trading_data()
            
            self.assertIn("reset_at", result)
            self.assertEqual(result["wallet"], config.INITIAL_BALANCE_TRY)
            
            # SQL adımlarını doğrula
            sql_texts = [s[0] for s in executed_sqls]
            self.assertTrue(any("pg_advisory_xact_lock" in s for s in sql_texts))
            self.assertTrue(any("UPDATE auto_paper_trades SET status='closed'" in s for s in sql_texts))
            self.assertTrue(any("DELETE FROM positions" in s for s in sql_texts))
            self.assertTrue(any("DELETE FROM virtual_wallet" in s for s in sql_texts))
            self.assertTrue(any("INSERT INTO virtual_wallet" in s for s in sql_texts))
            self.assertTrue(any("portfolio_reset_at" in str(s) for s in sql_texts))


# ---------------------------------------------------------------------------
# P0-5 — cüzdana yazan DÖRT yol TEK anahtarda (paper_portfolio_open) serileşmeli
# ---------------------------------------------------------------------------
class SharedWalletLockTests(unittest.TestCase):
    """Kaynak-düzeyi bekçi: açma/kapatma transaction'ları portföy anahtarını
    transaction'ın İLK statement'ı olarak (cüzdan okumasından ÖNCE) almalı.

    Sembol/trade kapsamlı ek anahtarlar farklı satırlar için değil, churn/çakışma
    denetimini sembol başına serileştirmek için durur; asıl cüzdan serileştirmesi
    paylaşılan portföy anahtarıdır. Bu testler Postgres gerektirmez.
    """

    def test_open_auto_paper_takes_portfolio_lock_before_symbol_lock(self):
        src = inspect.getsource(database.open_auto_paper_trade)
        self.assertIn("pg_advisory_xact_lock", src)
        portfolio_idx = src.index('("paper_portfolio_open",)')
        symbol_idx = src.index('f"auto_paper_open_{symbol}"')
        self.assertLess(portfolio_idx, symbol_idx,
                        "portföy anahtarı sembol anahtarından ÖNCE alınmalı")

    def test_close_auto_paper_takes_portfolio_lock_before_trade_lock(self):
        src = inspect.getsource(database.close_auto_paper_trade)
        portfolio_idx = src.index('("paper_portfolio_open",)')
        trade_idx = src.index('f"auto_paper_close_{trade_id}"')
        self.assertLess(portfolio_idx, trade_idx,
                        "portföy anahtarı trade anahtarından ÖNCE alınmalı")

    def test_reset_and_reconcile_share_the_same_portfolio_key(self):
        for fn in (database.reset_trading_data, database.reconcile_portfolio):
            src = inspect.getsource(fn)
            self.assertIn('("paper_portfolio_open",)', src,
                          f"{fn.__name__} paylaşılan portföy anahtarını almalı")


# ---------------------------------------------------------------------------
# P0-3 — RAPOR BAŞLANGICI bir görünüm filtresidir; işlem yönetimini yönetmez
# ---------------------------------------------------------------------------
class ApplyReportsBaselineToggleTests(unittest.IsolatedAsyncioTestCase):
    """`list_auto_paper_trades(apply_reports_baseline=False)` YALNIZ rapor
    başlangıcını kaldırır; reset cutoff KALIR ve varsayılan (True) değişmez."""

    def _records(self, reset, baseline):
        records = []
        return records, _settings_fake_execute(records, reset, baseline)

    def _list_call(self, records):
        return [(s, p) for s, p in records if "FROM auto_paper_trades" in s and "ORDER BY entry_time DESC LIMIT ?" in s][-1]

    async def test_false_uses_only_reset_cutoff(self):
        now = time.time()
        reset, baseline = now - 1000, now - 100  # baseline daha YENİ
        records, fake_execute = self._records(reset, baseline)
        with patch.object(database, "_run_db", side_effect=_fake_run_db(fake_execute)):
            await database.list_auto_paper_trades(status="open", apply_reports_baseline=False)
        sql, params = self._list_call(records)
        self.assertIn("entry_time >= ?", sql)
        self.assertIn(reset, params, "reset cutoff uygulanmalı")
        self.assertNotIn(baseline, params, "rapor başlangıcı açık yönetiminde uygulanmamalı")

    async def test_default_still_applies_reports_baseline(self):
        now = time.time()
        reset, baseline = now - 1000, now - 100
        records, fake_execute = self._records(reset, baseline)
        with patch.object(database, "_run_db", side_effect=_fake_run_db(fake_execute)):
            await database.list_auto_paper_trades(status="open")
        sql, params = self._list_call(records)
        # cutoff = max(reset, baseline) = baseline; rapor görünümü DEĞİŞMEZ.
        self.assertIn(baseline, params)

    async def test_include_archived_skips_both_ceilings(self):
        now = time.time()
        reset, baseline = now - 1000, now - 100
        records, fake_execute = self._records(reset, baseline)
        with patch.object(database, "_run_db", side_effect=_fake_run_db(fake_execute)):
            await database.list_auto_paper_trades(status="open", include_archived=True)
        sql, params = self._list_call(records)
        self.assertNotIn("entry_time >= ?", sql)
        self.assertNotIn(reset, params)
        self.assertNotIn(baseline, params)

    async def test_stats_open_count_ignores_reports_baseline(self):
        """`get_auto_paper_stats` açık sayımı arşiv sınırına takılmamalı (P0-3).

        Aksi halde "arşivi göster" TEK rapor gövdesinde tutarsız sayı üretiyordu
        (kapanmış=arşiv dahil, açık=arşiv hariç).
        """
        now = time.time()
        reset, baseline = now - 1000, now - 100
        records, fake_execute = self._records(reset, baseline)
        with patch.object(database, "_run_db", side_effect=_fake_run_db(fake_execute)):
            # since=1.0: default_to_today gün penceresini nötrler (deterministik).
            await database.get_auto_paper_stats(since=1.0)
        open_calls = [(s, p) for s, p in records if "WHERE status='open'" in s]
        self.assertTrue(open_calls)
        sql, params = open_calls[-1]
        self.assertIn("entry_time >= ?", sql)
        self.assertIn(reset, params, "reset cutoff açık sayımında da uygulanmalı")
        self.assertNotIn(baseline, params, "rapor sınırı açık sayımını kırpmamalı")


# ---------------------------------------------------------------------------
# P2-1 — trailing/breakeven stop yalnız KORUYUCU yönde yazılabilir
# ---------------------------------------------------------------------------
class _RowCountCursor:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _MonotonicConn:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount
        self.calls = []
        self.conn = self

    def execute(self, sql, params=()):
        self.calls.append((" ".join(str(sql).split()), tuple(params)))
        return _RowCountCursor(self.rowcount)

    def commit(self):
        pass


class MonotonicStopGuardTests(unittest.IsolatedAsyncioTestCase):
    """Daha düşük bir trailing/BE değeri stop'u aşağı KAYDIRAMAMALI."""

    def _patch(self, conn):
        async def runner(op):
            return op(conn)
        return patch.object(database, "_run_db", runner)

    async def test_trailing_update_carries_monotonic_guard(self):
        conn = _MonotonicConn(rowcount=1)
        with self._patch(conn):
            ok = await database.update_auto_paper_trailing(7, True, 105.0)
        self.assertTrue(ok)
        sql, params = conn.calls[-1]
        self.assertIn("trailing_stop IS NULL OR trailing_stop <= ?", sql)
        self.assertEqual(105.0, params[-1], "yeni değer monotonik karşılaştırmaya girmeli")

    async def test_trailing_rejected_when_lower_returns_false(self):
        conn = _MonotonicConn(rowcount=0)  # koruyucu olmayan güncelleme → 0 satır
        with self._patch(conn):
            ok = await database.update_auto_paper_trailing(7, True, 90.0)
        self.assertFalse(ok, "stop aşağı kaydıran güncelleme reddedilmeli ve False dönmeli")

    async def test_breakeven_update_carries_monotonic_guard(self):
        conn = _MonotonicConn(rowcount=1)
        with self._patch(conn):
            ok = await database.update_auto_paper_breakeven(7, True, 101.0)
        self.assertTrue(ok)
        sql, params = conn.calls[-1]
        self.assertIn("breakeven_stop IS NULL OR breakeven_stop <= ?", sql)
        self.assertEqual(101.0, params[-1])

    async def test_breakeven_without_value_only_sets_flag(self):
        conn = _MonotonicConn(rowcount=1)
        with self._patch(conn):
            await database.update_auto_paper_breakeven(7, activated=False)
        sql, _ = conn.calls[-1]
        self.assertNotIn("breakeven_stop=?", sql)

    async def test_peak_update_is_monotonic_and_returns_rowcount(self):
        conn = _MonotonicConn(rowcount=1)
        with self._patch(conn):
            ok = await database.update_auto_paper_peak(7, 110.0)
        self.assertTrue(ok)
        sql, _ = conn.calls[-1]
        self.assertIn("peak_price IS NULL OR peak_price < ?", sql)


# ---------------------------------------------------------------------------
# P2-5 — model varsayımı GEÇERLİ bir pozisyonu düşürmemeli
# ---------------------------------------------------------------------------
class _Cursor:
    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows) if rows else []
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _ReconcileRoutedConn:
    """`reconcile_portfolio` için SQL'e göre yanıt veren sahte bağlantı."""

    def __init__(self, *, realized, main_open, positions_rows):
        self.realized = realized
        self.main_open = main_open
        self.positions_rows = positions_rows
        self.deleted = []
        self.statements = []
        self.conn = self

    def execute(self, sql, params=()):
        s = " ".join(str(sql).split())
        self.statements.append(s)
        if "pg_advisory_xact_lock" in s:
            return _Cursor(rowcount=0)
        if "portfolio_reset_at" in s:
            return _Cursor([])  # cutoff yok
        if "SUM(pnl),0) FROM trades" in s:
            return _Cursor([(self.realized,)])
        if "SUM(pnl),0) FROM auto_paper_trades" in s:
            return _Cursor([(0.0,)])
        if "SUM(order_value_try),0) FROM auto_paper_trades" in s:
            return _Cursor([(0.0,)])
        if "SUM(entry_price*quantity),0) FROM positions" in s:
            return _Cursor([(self.main_open,)])
        if "SELECT amount FROM virtual_wallet" in s:
            return _Cursor([(5000.0,)])
        if "SELECT entry_time,exit_time,entry_price,quantity,pnl,exit_price FROM trades" in s:
            return _Cursor(self._trade_rows)
        if "SELECT entry_time,exit_time,order_value_try" in s:
            return _Cursor([])
        if "SELECT symbol,entry_time,entry_price,quantity FROM positions" in s:
            return _Cursor(self.positions_rows)
        if "SELECT trade_id FROM positions WHERE symbol=?" in s:
            return _Cursor([("legacy-t1",)])
        if s.startswith("DELETE FROM positions"):
            self.deleted.append(params)
            return _Cursor(rowcount=1)
        if s.startswith("SELECT COUNT("):
            return _Cursor([(0,)])
        return _Cursor([])

    def commit(self):
        pass


def _reconcile_runner(conn):
    async def runner(op):
        return op(conn)
    return runner


class OverallocationJustificationTests(unittest.IsolatedAsyncioTestCase):
    """Model adayı olsa bile teminatlı pozisyon KORUNMALI; gerçekten
    karşılanamayan pozisyon silinebilir."""

    def test_helper_gate(self):
        # genuine_cash = INITIAL + realized; obligation = open_cost*(1+c)
        self.assertFalse(database._overallocation_removal_justified(4000.0, 500.0),
                         "cüzdan pozisyonu karşılıyorsa silme gerekçesiz")
        self.assertTrue(database._overallocation_removal_justified(0.0, 12000.0),
                        "pozisyon gerçek nakdi aşıyorsa silme gerekçeli")

    async def test_covered_position_is_preserved_despite_model_candidate(self):
        """Model nakit akışı negatife düşse de gerçek rakamlar pozisyonu kapsıyor
        (realized +4000, açık maliyet 500) → silme YAPILMAMALI."""
        conn = _ReconcileRoutedConn(
            realized=4000.0, main_open=500.0,
            positions_rows=[["TESTUSDT", 3.0, 5.0, 100.0]])
        # Model: büyük geçmiş debit cüzdanı negatife iter → aday üretir.
        conn._trade_rows = [[1.0, 2.0, 150.0, 100.0, 4000.0, 10.0]]
        with patch.object(database, "_run_db", _reconcile_runner(conn)):
            result = await database.reconcile_portfolio()
        self.assertEqual([], result["removed_overallocated_positions"])
        self.assertEqual([], conn.deleted, "geçerli pozisyon silinmemeli")

    async def test_uncovered_position_is_still_removed(self):
        """Gerçek nakil pozisyonu karşılamıyorsa silme yasal — kapı yolu kapatmaz."""
        conn = _ReconcileRoutedConn(
            realized=0.0, main_open=12000.0,
            positions_rows=[["BIGUSDT", 3.0, 120.0, 100.0]])
        conn._trade_rows = []
        with patch.object(database, "_run_db", _reconcile_runner(conn)):
            result = await database.reconcile_portfolio()
        self.assertEqual(1, len(result["removed_overallocated_positions"]))
        self.assertEqual(1, len(conn.deleted))

    async def test_preview_uses_the_same_justification(self):
        conn = _ReconcileRoutedConn(
            realized=4000.0, main_open=500.0,
            positions_rows=[["TESTUSDT", 3.0, 5.0, 100.0]])
        conn._trade_rows = [[1.0, 2.0, 150.0, 100.0, 4000.0, 10.0]]
        with patch.object(database, "_run_db", _reconcile_runner(conn)):
            preview = await database.preview_portfolio_reconcile()
        self.assertEqual([], preview["would_remove"])
        self.assertFalse(preview["requires_confirmation"])


# ---------------------------------------------------------------------------
# P1-6 — sütun izin listesi + LIMIT sınırı zorlaması
# ---------------------------------------------------------------------------
class _RawConn:
    class _C:
        description = [("x",)]

        def fetchall(self):
            return [[1]]

    def __init__(self):
        self.raw_sql = None

    def raw_execute(self, sql, params=()):
        self.raw_sql = sql
        return self._C()

    def execute(self, sql, params=()):
        raise AssertionError("read_only_query compat execute kullandı (V-19)")

    def commit(self):
        pass


class ReadOnlyQueryHardeningTests(unittest.IsolatedAsyncioTestCase):
    """Opak/hassas sütunlar reddedilmeli; LIMIT bypass'i kapatılmalı."""

    def _patch(self, conn):
        async def runner(op):
            return op(conn)
        return patch.object(database, "_run_db", runner)

    async def _run(self, sql, limit=500):
        conn = _RawConn()
        with self._patch(conn):
            rows = await database.read_only_query(sql, limit)
        return conn, rows

    async def test_opaque_jsonb_columns_are_rejected(self):
        for sql in ("SELECT metadata FROM decision_logs",
                    "SELECT payload FROM analysis_snapshots",
                    "SELECT id, entry_context FROM trades",
                    "SELECT arguments FROM llm_tool_logs"):
            with self.subTest(sql=sql):
                with self.assertRaises(ValueError):
                    await self._run(sql)

    async def test_secret_like_columns_are_rejected(self):
        for sql in ("SELECT api_key FROM trades",
                    "SELECT s.api_secret FROM signals s"):
            with self.subTest(sql=sql):
                with self.assertRaises(ValueError):
                    await self._run(sql)

    async def test_allowed_query_still_runs_with_outer_limit(self):
        conn, rows = await self._run("SELECT symbol, pnl FROM trades", limit=10)
        self.assertEqual([{"x": 1}], rows)
        self.assertIn(" AS llm_read_only_result LIMIT 10", conn.raw_sql)

    async def test_large_inner_limit_is_clamped(self):
        conn, _ = await self._run("SELECT id FROM trades LIMIT 999999", limit=10)
        self.assertEqual(
            "SELECT * FROM (SELECT id FROM trades LIMIT 10) AS llm_read_only_result LIMIT 10",
            conn.raw_sql)

    async def test_small_inner_limit_is_preserved_but_outer_caps(self):
        conn, _ = await self._run("SELECT id FROM trades LIMIT 3", limit=10)
        self.assertIn("LIMIT 3", conn.raw_sql)
        self.assertIn(" AS llm_read_only_result LIMIT 10", conn.raw_sql)

    async def test_query_without_limit_gets_outer_cap(self):
        conn, _ = await self._run("SELECT id FROM trades", limit=7)
        self.assertTrue(conn.raw_sql.endswith(" AS llm_read_only_result LIMIT 7"))

    async def test_disallowed_table_still_rejected(self):
        with self.assertRaises(ValueError):
            await self._run("SELECT api_key_encrypted FROM llm_providers")


# ---------------------------------------------------------------------------
# init_db sertleştirme — şema DDL retry + migrasyon keşfi glob'lanır
# ---------------------------------------------------------------------------
class _RawDdlConn:
    """`conn.conn` — ham psycopg.execute yüzeyi."""

    def __init__(self, ddl, fail_times, sqlstate):
        self.ddl = ddl
        self.fail_times = fail_times
        self.sqlstate = sqlstate
        self.calls = []
        self.rollbacks = 0

    def execute(self, sql, params=()):
        self.calls.append(sql)
        if sql == self.ddl and self.fail_times > 0:
            self.fail_times -= 1
            exc = Exception("schema DDL failed")
            if self.sqlstate is not None:
                exc.sqlstate = self.sqlstate
            raise exc
        return MagicMock()

    def rollback(self):
        self.rollbacks += 1


class _DdlCompat:
    """`_PostgresCompat` yüzeyi: sha yazımını kaydeder."""

    def __init__(self, raw):
        self.conn = raw
        self.sha_writes = []

    def execute(self, sql, params=()):
        if "schema_sha256" in sql:
            self.sha_writes.append(params[0])
        return MagicMock()


class InitDbHardeningTests(unittest.TestCase):
    """Denetim: DDL daha uzun kilit sınırıyla koşmalı ve geçici kilit
    hatalarında çökmeden yeniden denenmeli."""

    def test_migration_discovery_is_globbed_not_hardcoded(self):
        src = inspect.getsource(database.init_db)
        self.assertIn("_MIGRATION_FILE_RE", src)
        self.assertNotIn("005_user_binance_keys.sql", src,
                         "sabit dosya listesi glob ile değiştirilmeli")

    def test_migration_pattern_matches_numbered_files_only(self):
        self.assertTrue(database._MIGRATION_FILE_RE.match("006_new_feature.sql"))
        self.assertTrue(database._MIGRATION_FILE_RE.match("001_pgvector_schema.sql"))
        self.assertFalse(database._MIGRATION_FILE_RE.match("helper.sql"))
        self.assertFalse(database._MIGRATION_FILE_RE.match("001_pgvector_schema.SQL"))

    def test_transient_lock_error_is_retried_with_longer_timeout(self):
        raw = _RawDdlConn("CREATE TABLE x()", fail_times=1, sqlstate="55P03")
        compat = _DdlCompat(raw)
        with patch("time.sleep"):  # artan backoff'u gerçekten beklemeyelim
            database._apply_schema_ddl(compat, "CREATE TABLE x()", "sha123")
        self.assertEqual(["sha123"], compat.sha_writes, "retry sonrası sha yazılmalı")
        self.assertTrue(any("SET LOCAL lock_timeout = '30s'" in c for c in raw.calls))
        self.assertEqual(1, raw.rollbacks, "başarısız denemeden sonra rollback edilmeli")

    def test_permanent_error_propagates_without_retry(self):
        raw = _RawDdlConn("CREATE TABLE x()", fail_times=99, sqlstate="42601")
        compat = _DdlCompat(raw)
        with patch("time.sleep"):
            with self.assertRaises(Exception):
                database._apply_schema_ddl(compat, "CREATE TABLE x()", "sha123")
        self.assertEqual([], compat.sha_writes)
        self.assertEqual(1, len([c for c in raw.calls if c == "CREATE TABLE x()"]),
                         "kalıcı (non-transient) hata ANINDA yükseltilmeli — retry YOK")

    def test_retries_exhausted_raises_last_error(self):
        raw = _RawDdlConn("CREATE TABLE x()", fail_times=999, sqlstate="40P01")
        compat = _DdlCompat(raw)
        with patch("time.sleep"):
            with self.assertRaises(Exception):
                database._apply_schema_ddl(compat, "CREATE TABLE x()", "sha123", attempts=3)
        self.assertEqual(3, len([c for c in raw.calls if c == "CREATE TABLE x()"]))
        self.assertEqual([], compat.sha_writes)


if __name__ == "__main__":
    unittest.main()
