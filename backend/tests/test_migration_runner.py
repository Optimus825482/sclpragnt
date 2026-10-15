"""Dosya başına migration takibi — sıralama, idempotens, sha uyuşmazlığı, eski-marker geçişi.

İki yol test edilir ve ikisi de AYNI kararları vermelidir:
* ``scripts/run_postgres_migration.py`` (asyncpg, sahte bağlantı),
* ``app/database.py`` ``_apply_pending_migrations`` (psycopg, sahte bağlantı).

Gerçek bir Postgres gerekmez; "transaction" davranışı her sahtede anlık görüntü
(snapshot) ile modellenir: bir dosya hata verirse o dosyanın yazdıkları geri alınır.
"""
import asyncio
import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import database
from app.migration_plan import (
    MIGRATIONS_DIR_DEFAULT,
    LegacyMarkerError,
    MigrationDriftError,
    SCHEMA_MIGRATIONS_DDL,
    aggregate_sha256,
    discover_migrations,
    legacy_bootstrap_rows,
    plan_pending,
)

ROOT = Path(__file__).resolve().parents[1]
_RUNNER_PATH = ROOT / "scripts" / "run_postgres_migration.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_postgres_migration", _RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()

# Üç dosya: ikincisi ayrıca "kalıcı hata" / "geçici hata" senaryolarında kullanılır.
FILE_1 = "CREATE TABLE llm_settings (key TEXT PRIMARY KEY, value TEXT);\n"
FILE_2 = "CREATE TABLE t2 (id INT);\n"
FILE_3 = "CREATE TABLE t3 (id INT);\n"


class _PgError(Exception):
    def __init__(self, sqlstate):
        super().__init__(f"sahte hata {sqlstate}")
        self.sqlstate = sqlstate


# ---------------------------------------------------------------------------
# Ortak karar mantığı (app/migration_plan.py)
# ---------------------------------------------------------------------------
class MigrationPlanTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _put(self, name, text="SELECT 1;\n"):
        (self.dir / name).write_text(text, encoding="utf-8")

    def test_discovery_orders_by_number_not_lexically(self):
        for name in ("002_b.sql", "010_c.sql", "001_a.sql"):
            self._put(name)
        self.assertEqual(["001_a.sql", "002_b.sql", "010_c.sql"],
                         [m.version for m in discover_migrations(self.dir)])

    def test_discovery_ignores_files_without_number_prefix(self):
        for name in ("001_a.sql", "helper.sql", "001_x.SQL", "notes.txt"):
            self._put(name)
        self.assertEqual(["001_a.sql"], [m.version for m in discover_migrations(self.dir)])

    def test_duplicate_number_is_rejected(self):
        # İki dal aynı numarayı alırsa (ör. iki 014) sıra belirsizleşir: açık hata.
        self._put("014_first.sql")
        self._put("014_second.sql")
        with self.assertRaises(ValueError):
            discover_migrations(self.dir)

    def test_plan_skips_applied_and_keeps_numeric_order(self):
        for name in ("001_a.sql", "002_b.sql", "010_c.sql"):
            self._put(name)
        migrations = discover_migrations(self.dir)
        applied = {"001_a.sql": migrations[0].sha256}
        self.assertEqual(["002_b.sql", "010_c.sql"],
                         [m.version for m in plan_pending(migrations, applied)])

    def test_applied_file_with_changed_content_raises_drift(self):
        self._put("001_a.sql", "CREATE TABLE a();\n")
        migrations = discover_migrations(self.dir)
        with self.assertRaises(MigrationDriftError):
            plan_pending(migrations, {"001_a.sql": "0" * 64})

    def test_legacy_marker_marks_matching_prefix_and_leaves_newer_file_pending(self):
        # Eski marker 001+002'nin birleşik sha'sı; 003 sonradan eklenmiş → yalnız 003 bekler.
        for name, text in (("001_a.sql", FILE_1), ("002_b.sql", FILE_2), ("003_c.sql", FILE_3)):
            self._put(name, text)
        migrations = discover_migrations(self.dir)
        marker = aggregate_sha256(migrations[:2])
        rows = legacy_bootstrap_rows(migrations, marker)
        self.assertEqual({"001_a.sql", "002_b.sql"}, set(rows))
        self.assertEqual(["003_c.sql"], [m.version for m in plan_pending(migrations, rows)])

    def test_legacy_marker_covering_all_files_marks_all_applied(self):
        for name, text in (("001_a.sql", FILE_1), ("002_b.sql", FILE_2)):
            self._put(name, text)
        migrations = discover_migrations(self.dir)
        rows = legacy_bootstrap_rows(migrations, aggregate_sha256(migrations))
        self.assertEqual([], plan_pending(migrations, rows))

    def test_legacy_marker_matching_no_prefix_fails_loudly(self):
        # Uygulandıktan sonra bir dosya düzenlenmiş olabilir: tahmin yürütülmez.
        self._put("001_a.sql", FILE_1)
        migrations = discover_migrations(self.dir)
        with self.assertRaises(LegacyMarkerError):
            legacy_bootstrap_rows(migrations, "deadbeef" * 8)

    def test_real_migrations_directory_has_unique_numbers(self):
        # Numara çakışması (ör. iki dalın ikisi de 015 eklemesi) burada yakalanır.
        migrations = discover_migrations(MIGRATIONS_DIR_DEFAULT)
        self.assertGreater(len(migrations), 0)
        self.assertEqual(len({m.number for m in migrations}), len(migrations))


# ---------------------------------------------------------------------------
# Runner (scripts/run_postgres_migration.py) — sahte asyncpg bağlantısı
# ---------------------------------------------------------------------------
class _FakePg:
    """asyncpg yüzeyinin bellek içi karşılığı; transaction'ları anlık görüntüyle modeller."""

    def __init__(self, failures=None):
        self.schema_rows = {}          # version -> sha256
        self.settings = {}             # llm_settings
        self.has_llm_settings = False  # 001 bu tabloyu yaratır
        self.ran = []                  # başarıyla koşan ham migration SQL'leri
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.connects = 0
        self.committed = 0
        self.rolled_back = 0
        self.locks = []

    async def execute(self, sql, *args):
        if sql == SCHEMA_MIGRATIONS_DDL:
            return "CREATE TABLE"
        if sql.startswith("SELECT pg_advisory"):
            self.locks.append(sql)
            return "SELECT 1"
        if sql.startswith("INSERT INTO schema_migrations"):
            self.schema_rows[args[0]] = args[1]
            return "INSERT 0 1"
        if sql.startswith("INSERT INTO llm_settings"):
            self.settings[args[0]] = args[1]
            return "INSERT 0 1"
        codes = self.failures.get(sql)
        if codes:
            raise _PgError(codes.pop(0))
        self.ran.append(sql)
        self.has_llm_settings = True
        return "OK"

    async def fetch(self, sql, *args):
        return [{"version": v, "sha256": s} for v, s in self.schema_rows.items()]

    async def fetchval(self, sql, *args):
        if "to_regclass" in sql:
            return "llm_settings" if self.has_llm_settings else None
        if "FROM llm_settings" in sql:
            return self.settings.get(args[0])
        raise AssertionError(f"beklenmeyen fetchval: {sql}")

    def transaction(self):
        return _FakeTx(self)

    async def close(self):
        pass


class _FakeTx:
    def __init__(self, pg):
        self.pg = pg

    async def __aenter__(self):
        self.snapshot = (dict(self.pg.schema_rows), dict(self.pg.settings),
                         self.pg.has_llm_settings, len(self.pg.ran))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.pg.committed += 1
            return False
        rows, settings, has_llm, ran_len = self.snapshot
        self.pg.schema_rows, self.pg.settings = rows, settings
        self.pg.has_llm_settings = has_llm
        del self.pg.ran[ran_len:]
        self.pg.rolled_back += 1
        return False


class RunnerTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.files = {"001_a.sql": FILE_1, "002_b.sql": FILE_2, "003_c.sql": FILE_3}
        for name, text in self.files.items():
            (self.dir / name).write_text(text, encoding="utf-8")
        self.sql = {"001_a.sql": FILE_1, "002_b.sql": FILE_2, "003_c.sql": FILE_3}

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, pg):
        async def fake_connect(*args, **kwargs):
            pg.connects += 1
            return pg

        env = {"DATABASE_URL": "postgresql://fake/fake"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(runner.asyncpg, "connect", new=fake_connect), \
                mock.patch.object(runner, "_RETRY_SLEEP_SEC", 0):
            return asyncio.run(runner.main(self.dir))

    def test_fresh_database_applies_all_files_in_order_each_in_own_transaction(self):
        pg = _FakePg()
        self._run(pg)
        self.assertEqual([FILE_1, FILE_2, FILE_3], pg.ran)
        self.assertEqual(["001_a.sql", "002_b.sql", "003_c.sql"], list(pg.schema_rows))
        # 3 dosya + 1 birleşik marker yazımı = her biri ayrı transaction.
        self.assertEqual(4, pg.committed)
        self.assertEqual(
            aggregate_sha256(discover_migrations(self.dir)), pg.settings["schema_sha256"])

    def test_second_run_is_a_noop(self):
        pg = _FakePg()
        self._run(pg)
        ran_after_first = list(pg.ran)
        self._run(pg)
        self.assertEqual(ran_after_first, pg.ran, "uygulanmış dosya tekrar koşmamalı")

    def test_failing_file_rolls_back_and_run_resumes_from_it(self):
        pg = _FakePg(failures={FILE_2: ["42601"] * 25})  # kalıcı SQL hatası
        with self.assertRaises(SystemExit):
            self._run(pg)
        self.assertEqual(["001_a.sql"], list(pg.schema_rows),
                         "hatalı dosyanın kaydı yazılmamalı; 003 hiç koşmamalı")
        self.assertEqual([FILE_1], pg.ran)
        self.assertEqual(1, pg.connects, "kalıcı hata yeniden denenmemeli")

        pg.failures = {}  # hata giderildi
        self._run(pg)
        self.assertEqual([FILE_1, FILE_2, FILE_3], pg.ran,
                         "001 ikinci kez koşmamalı; kalan dosyalar sırayla koşmalı")

    def test_transient_lock_error_is_retried_and_completes(self):
        pg = _FakePg(failures={FILE_2: ["55P03"]})  # ilk denemede kilit beklemesi
        self._run(pg)
        self.assertEqual(2, pg.connects)
        self.assertEqual([FILE_1, FILE_2, FILE_3], pg.ran)

    def test_sha_drift_stops_before_running_anything(self):
        pg = _FakePg()
        pg.schema_rows = {"001_a.sql": "0" * 64}
        pg.has_llm_settings = True
        with self.assertRaises(SystemExit) as ctx:
            self._run(pg)
        self.assertIn("içeriği değişmiş", str(ctx.exception))
        self.assertEqual([], pg.ran)

    def test_legacy_marker_marks_prefix_applied_and_runs_only_newer_files(self):
        pg = _FakePg()
        pg.has_llm_settings = True
        pg.settings["schema_sha256"] = aggregate_sha256(discover_migrations(self.dir)[:2])
        self._run(pg)
        self.assertEqual([FILE_3], pg.ran, "001-002 eski marker ile uygulanmış sayılmalı")
        self.assertEqual(["001_a.sql", "002_b.sql", "003_c.sql"], list(pg.schema_rows))

    def test_legacy_marker_matching_nothing_fails_without_running(self):
        pg = _FakePg()
        pg.has_llm_settings = True
        pg.settings["schema_sha256"] = "deadbeef" * 8
        with self.assertRaises(SystemExit) as ctx:
            self._run(pg)
        self.assertIn("eşleşmiyor", str(ctx.exception))
        self.assertEqual([], pg.ran)
        self.assertEqual({}, pg.schema_rows)


# ---------------------------------------------------------------------------
# init_db yolu (app/database.py) — sahte psycopg bağlantısı
# ---------------------------------------------------------------------------
class _Cursor:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakePsycopg:
    """psycopg yüzeyi: `conn.execute`, `conn.conn` (ham), commit/rollback.

    Yazımlar tamponda tutulur; commit uygular, rollback atar — gerçek transaction gibi.
    """

    def __init__(self, failures=None):
        self.conn = self
        self.schema_rows = {}
        self.settings = {}
        self.has_llm_settings = False
        self.ran = []
        self.set_local = []
        self.buffer = []
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        if text.startswith("SET LOCAL"):
            self.set_local.append(text)
            return _Cursor()
        if text.startswith("SELECT pg_advisory") or text.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
            return _Cursor()
        if text.startswith("SELECT version, sha256 FROM schema_migrations"):
            return _Cursor(list(self.schema_rows.items()))
        if "to_regclass" in text:
            return _Cursor([("llm_settings" if self.has_llm_settings else None,)])
        if text.startswith("SELECT value FROM llm_settings"):
            value = self.settings.get("schema_sha256")
            return _Cursor([(value,)] if value is not None else [])
        if text.startswith("INSERT INTO schema_migrations"):
            self.buffer.append(lambda v=params[0], s=params[1]: self.schema_rows.__setitem__(v, s))
            return _Cursor()
        if text.startswith("INSERT INTO llm_settings"):
            self.buffer.append(lambda s=params[0]: self.settings.__setitem__("schema_sha256", s))
            return _Cursor()
        codes = self.failures.get(sql)
        if codes:
            exc = _PgError(codes.pop(0))
            raise exc
        self.buffer.append(lambda: self.ran.append(sql) or setattr(self, "has_llm_settings", True))
        return _Cursor()

    def commit(self):
        for write in self.buffer:
            write()
        self.buffer = []
        self.commits += 1

    def rollback(self):
        self.buffer = []
        self.rollbacks += 1


class InitDbPathTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for name, text in (("001_a.sql", FILE_1), ("002_b.sql", FILE_2), ("003_c.sql", FILE_3)):
            (self.dir / name).write_text(text, encoding="utf-8")
        self.migrations = discover_migrations(self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_database_runs_each_file_once_and_records_it(self):
        conn = _FakePsycopg()
        with mock.patch("time.sleep"):
            applied = database._apply_pending_migrations(conn, self.migrations)
        self.assertEqual(3, applied)
        self.assertEqual([FILE_1, FILE_2, FILE_3], conn.ran)
        self.assertEqual(["001_a.sql", "002_b.sql", "003_c.sql"], list(conn.schema_rows))
        self.assertEqual(aggregate_sha256(self.migrations), conn.settings["schema_sha256"],
                         "geriye dönük uyum için birleşik marker yazılmalı")
        self.assertEqual(3, sum(1 for s in conn.set_local if "lock_timeout = '30s'" in s),
                         "her dosya kendi SET LOCAL'ını alır")

    def test_already_applied_files_are_skipped(self):
        conn = _FakePsycopg()
        conn.schema_rows = {"001_a.sql": self.migrations[0].sha256,
                            "002_b.sql": self.migrations[1].sha256}
        conn.has_llm_settings = True
        with mock.patch("time.sleep"):
            applied = database._apply_pending_migrations(conn, self.migrations)
        self.assertEqual(1, applied)
        self.assertEqual([FILE_3], conn.ran)

    def test_transient_error_retries_only_the_failing_file(self):
        conn = _FakePsycopg(failures={FILE_2: ["55P03"]})
        with mock.patch("time.sleep"):
            database._apply_pending_migrations(conn, self.migrations)
        self.assertEqual([FILE_1, FILE_2, FILE_3], conn.ran,
                         "001 yeniden koşmamalı; yalnız takılan 002 tekrar denenmeli")
        self.assertEqual(1, conn.rollbacks, "başarısız deneme geri alınmalı")

    def test_drift_raises_and_runs_nothing(self):
        conn = _FakePsycopg()
        conn.schema_rows = {"001_a.sql": "0" * 64}
        conn.has_llm_settings = True
        with self.assertRaises(MigrationDriftError):
            database._apply_pending_migrations(conn, self.migrations)
        self.assertEqual([], conn.ran)

    def test_legacy_marker_bootstrap_on_init_path(self):
        conn = _FakePsycopg()
        conn.has_llm_settings = True
        conn.settings["schema_sha256"] = aggregate_sha256(self.migrations[:2])
        with mock.patch("time.sleep"):
            applied = database._apply_pending_migrations(conn, self.migrations)
        self.assertEqual(1, applied)
        self.assertEqual([FILE_3], conn.ran)
        self.assertEqual(["001_a.sql", "002_b.sql", "003_c.sql"], list(conn.schema_rows))

    def test_bootstrap_rows_match_aggregate_formula(self):
        marker = aggregate_sha256(self.migrations[:2])
        self.assertEqual(legacy_bootstrap_rows(self.migrations, marker),
                         {m.version: m.sha256 for m in self.migrations[:2]})
        self.assertEqual(
            hashlib.sha256(("".join(m.sql + "\n" for m in self.migrations[:2])).encode("utf-8")).hexdigest(),
            marker)


if __name__ == "__main__":
    unittest.main()
