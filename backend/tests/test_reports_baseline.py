"""RAPOR BAŞLANGICI ("bu deploy") sınırı — 2026-10-07.

Raporlar (sinyal + otonom işlem) ve KPI'lar yalnız bu andan SONRAKİ veriyle
hesaplanır; öncesi arşivdir ve varsayılan olarak gizlenir.

Sınanan yüzey dört parçalı:
  1. `_parse_reports_baseline` — kabul edilen biçimler ve UTC+3 yorumu,
  2. `set/get_reports_baseline` — DB satırı ile config varsayılanı geçişi,
  3. `/api/reports/baseline` GET/PUT — admin kapısı ve geçersiz girişte 400,
  4. DB fonksiyonlarının `ignore_reports_baseline` davranışı.
"""
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

from app import database
from app.config import config
from app.routers import reports

UTC3 = timezone(timedelta(hours=3))


def _local_epoch(text: str) -> float:
    """'YYYY-MM-DD HH:MM' → UTC+3 duvarsaati epoch'u (test bağımsız)."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC3).timestamp()


class ReportsBaselineParserTests(unittest.TestCase):
    """`_parse_reports_baseline` biçim sözleşmesi."""

    def test_empty_and_zero_disable_the_filter(self):
        for raw in (None, "", "   ", "0", 0, 0.0):
            with self.subTest(raw=raw):
                self.assertEqual(0.0, database._parse_reports_baseline(raw))

    def test_unparsable_text_disables_rather_than_crashes(self):
        # Sessizce 0 dönmek "filtre kapalı"dır; `set_reports_baseline` bunu
        # PUT ucunda 400'e çevirir (aşağıdaki endpoint testine bkz).
        self.assertEqual(0.0, database._parse_reports_baseline("salakca metin"))

    def test_epoch_seconds_pass_through(self):
        self.assertEqual(1791388800.0, database._parse_reports_baseline("1791388800"))
        self.assertEqual(1791388800.0, database._parse_reports_baseline(1791388800))

    def test_date_only_means_midnight_utc3(self):
        self.assertEqual(_local_epoch("2026-10-07 00:00"),
                         database._parse_reports_baseline("2026-10-07"))

    def test_datetime_is_interpreted_as_utc3_wall_clock(self):
        expected = _local_epoch("2026-10-07 11:30")
        for raw in ("2026-10-07 11:30", "2026-10-07T11:30", "  2026-10-07 11:30  "):
            with self.subTest(raw=raw):
                self.assertEqual(expected, database._parse_reports_baseline(raw))
        # UTC+3 yorumu kanıtı: aynı duvarsaatini UTC sanmak 3 saat kaydırırdı.
        self.assertNotEqual(expected, _local_epoch("2026-10-07 08:30"))

    def test_code_default_is_the_documented_deploy_moment(self):
        # Kullanıcı sözleşmesi: değer girilmezse varsayılan 2026-10-07 11:30.
        self.assertEqual(_local_epoch("2026-10-07 11:30"),
                         database._parse_reports_baseline(config.REPORTS_BASELINE_DEFAULT))


class _FakeSettingsConn:
    """Tek `llm_settings` tablosu taşıyan sahte bağlantı."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE llm_settings (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.commit()


class _AdminRequest:
    """PUT ucunun denetim kaydı için dokunduğu minimum istek yüzeyi.

    Yetki kapısı burada TAKLİT EDİLMEZ; repodaki yerleşik desen uyarınca
    `app.api_common.require_admin` yamalanır (bkz. `_as_admin`).
    """

    def __init__(self):
        self.client = type("C", (), {"host": "127.0.0.1"})()
        self.headers = {}
        self.cookies = {}


class ReportsBaselineStoreTests(unittest.IsolatedAsyncioTestCase):
    """`reports_baseline_at` yaz/oku döngüsü ve config varsayılanına düşüş."""

    def setUp(self):
        self.fake = _FakeSettingsConn()
        self._orig_run_db = database._run_db

        async def runner(operation):
            return operation(self.fake.conn)

        database._run_db = runner

    def tearDown(self):
        database._run_db = self._orig_run_db
        self.fake.conn.close()

    async def test_missing_row_falls_back_to_config_default(self):
        self.assertEqual(database._parse_reports_baseline(config.REPORTS_BASELINE_DEFAULT),
                         await database.get_reports_baseline())

    async def test_round_trip_overrides_default(self):
        await database.set_reports_baseline("2027-01-02 03:04")
        self.assertEqual(_local_epoch("2027-01-02 03:04"), await database.get_reports_baseline())
        # DB satırı varsayılanı gerçekten EZMİŞ olmalı.
        self.assertNotEqual(database._parse_reports_baseline(config.REPORTS_BASELINE_DEFAULT),
                            await database.get_reports_baseline())

    async def test_blank_write_returns_to_config_default(self):
        await database.set_reports_baseline("2027-01-02 03:04")
        await database.set_reports_baseline("")
        self.assertEqual(database._parse_reports_baseline(config.REPORTS_BASELINE_DEFAULT),
                         await database.get_reports_baseline())

    async def test_zero_write_means_filter_off_not_default(self):
        # "0" ile "" AYRI anlam taşır: 0 = filtre kapalı, "" = varsayılana dön.
        await database.set_reports_baseline("0")
        self.assertEqual(0.0, await database.get_reports_baseline())


class ReportsBaselineEndpointTests(ReportsBaselineStoreTests):
    """/api/reports/baseline GET + PUT (admin kapısı ve 400 doğrulaması).

    Admin kapısı repodaki yerleşik desenle yamalanır: router `require_admin`'i
    çağrı anında `app.api_common`'dan import eder, dolayısıyla modül özniteliği
    yamamak yeterlidir. Kapının kapalı olduğu ayrı sınıfta sınanır.
    """

    def setUp(self):
        super().setUp()
        self._admin = patch("app.api_common.require_admin",
                            return_value={"role": "admin", "sub": "admin"})
        self._admin.start()

    def tearDown(self):
        self._admin.stop()
        super().tearDown()

    async def test_get_reports_effective_and_default(self):
        body = await reports.get_reports_baseline_endpoint()
        self.assertTrue(body["paper_only"])
        self.assertEqual(config.REPORTS_BASELINE_DEFAULT, body["default_value"])
        self.assertTrue(body["enabled"])
        self.assertEqual(_local_epoch("2026-10-07 11:30"), body["effective_ts"])
        self.assertEqual("2026-10-07 11:30", body["effective_local"])

    async def test_put_rejects_unparsable_value_with_400(self):
        payload = reports.ReportsBaselinePayload(value="salakca metin")
        with self.assertRaises(HTTPException) as ctx:
            await reports.set_reports_baseline_endpoint(payload, _AdminRequest())
        self.assertEqual(400, ctx.exception.status_code)

    async def test_put_persists_and_reports_effective_value(self):
        payload = reports.ReportsBaselinePayload(value="2027-01-02 03:04")
        body = await reports.set_reports_baseline_endpoint(payload, _AdminRequest())
        self.assertTrue(body["ok"])
        self.assertEqual("2027-01-02 03:04", body["effective_local"])
        self.assertEqual(_local_epoch("2027-01-02 03:04"), body["effective_ts"])
        # Kalıcı olmalı: yeni bir GET aynı sınırı okur.
        self.assertEqual(_local_epoch("2027-01-02 03:04"),
                         (await reports.get_reports_baseline_endpoint())["effective_ts"])

    async def test_put_zero_disables_filter_and_still_valid(self):
        payload = reports.ReportsBaselinePayload(value="0")
        body = await reports.set_reports_baseline_endpoint(payload, _AdminRequest())
        self.assertFalse(body["enabled"])
        self.assertIsNone(body["effective_local"])


class ReportsBaselineAdminGateTests(unittest.IsolatedAsyncioTestCase):
    """Admin OLMAYAN principal PUT edemez — kapı gerçekten kapalı mı?"""

    async def test_put_requires_admin(self):
        payload = reports.ReportsBaselinePayload(value="2027-01-02 03:04")
        with patch("app.api_common.require_admin",
                   side_effect=HTTPException(status_code=403, detail="Yönetici gerekli")):
            with self.assertRaises(HTTPException) as ctx:
                await reports.set_reports_baseline_endpoint(payload, _AdminRequest())
        self.assertEqual(403, ctx.exception.status_code)


class ReportsBaselineFloorTests(unittest.IsolatedAsyncioTestCase):
    """Sınırın GERÇEKTEN veri kestiğini kanıtlayan uçtan uca test.

    Sınır GÜN ORTASINA demirlenir, "şimdi"ye değil: aksi halde gece yarısına
    yakın koşularda `before_ts` önceki güne taşar ve test saate göre değişirdi.
    Tüm satırlar böylece her zaman tek bir UTC+3 günü içinde kalır.
    """

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE auto_paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, entry_price REAL, quantity REAL, order_value_try REAL,
                status TEXT, pnl REAL, pnl_pct REAL, entry_time REAL, exit_time REAL,
                exit_reason TEXT, created_at REAL, updated_at REAL, confluence_4way INTEGER,
                commission REAL
            )
        """)
        today_start = datetime.now(UTC3).replace(hour=0, minute=0, second=0,
                                                 microsecond=0).timestamp()
        self.baseline = today_start + 12 * 3600     # bugün 12:00 (UTC+3)
        self.day = datetime.fromtimestamp(self.baseline, UTC3).strftime("%Y-%m-%d")
        self.before_ts = self.baseline - 600        # 11:50 — sınırdan ÖNCE
        self.after_ts = self.baseline + 600         # 12:10 — sınırdan SONRA
        for symbol, exit_ts in (("ARCHIVE", self.before_ts), ("FRESH", self.after_ts)):
            self.conn.execute(
                "INSERT INTO auto_paper_trades(symbol, entry_price, quantity, order_value_try,"
                " status, pnl, pnl_pct, entry_time, exit_time, exit_reason, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (symbol, 10.0, 1.0, 100.0, "closed", 5.0, 5.0, exit_ts, exit_ts, "tp",
                 exit_ts, exit_ts))
        self.conn.commit()

        self._orig_run_db = database._run_db
        self._orig_baseline = database._get_reports_baseline_sync
        self._orig_reset = database._get_reset_cutoff_sync

        async def runner(operation):
            return operation(self.conn)

        database._run_db = runner
        database._get_reports_baseline_sync = lambda conn: self.baseline
        database._get_reset_cutoff_sync = lambda conn: 0.0

    def tearDown(self):
        database._run_db = self._orig_run_db
        database._get_reports_baseline_sync = self._orig_baseline
        database._get_reset_cutoff_sync = self._orig_reset
        self.conn.close()

    async def _symbols(self, **kwargs):
        rows = await database.get_auto_paper_symbol_breakdown(**kwargs)
        return {str(r.get("symbol") or "").upper() for r in rows}

    async def test_default_hides_archive(self):
        names = await self._symbols()
        self.assertIn("FRESH", names)
        self.assertNotIn("ARCHIVE", names)

    async def test_ignore_reports_baseline_shows_archive(self):
        names = await self._symbols(ignore_reports_baseline=True)
        self.assertIn("FRESH", names)
        self.assertIn("ARCHIVE", names)

    async def test_stats_count_only_post_baseline_rows(self):
        stats = await database.get_auto_paper_stats()
        self.assertEqual(1, stats["closed"])
        self.assertEqual(5.0, stats["total_pnl_try"])

        all_stats = await database.get_auto_paper_stats(ignore_reports_baseline=True)
        self.assertEqual(2, all_stats["closed"])
        self.assertEqual(10.0, all_stats["total_pnl_try"])

    async def test_explicit_day_window_is_a_floor_above_baseline_not_a_replacement(self):
        """Gün penceresi sınırı EZMEZ; en büyüğü kazanır.

        İki satır da AYNI güne düşer. Gün penceresi tek başına ikisini de
        geçirirdi; sınır devrede olduğu için yalnız `FRESH` kalır. Bu, gece
        yarısı kırpılması (midnight truncation) regresyonunun testidir:
        sınır gün penceresinin YERİNE geçseydi `FRESH` de düşerdi.
        """
        names = await self._symbols(day=self.day)
        self.assertEqual({"FRESH"}, names)
        # Arşivi göster denince aynı gün penceresi ikisini de getirir.
        self.assertEqual({"FRESH", "ARCHIVE"},
                         await self._symbols(day=self.day, ignore_reports_baseline=True))


if __name__ == "__main__":
    unittest.main()
