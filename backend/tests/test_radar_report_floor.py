"""RADAR RAPOR KESİMİ (2026-10-15 22:30) — yalnız radar bildirimi raporları.

Sözleşme: etkin alt sınır = max(rapor başlangıcı, radar kesimi); yalnız
`apply_radar_floor=True` geçen rapor uçları uygular; "arşivi göster"
(`ignore_reports_baseline=True`) ikisini de kaldırır.
"""
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app import database
from app.config import config

UTC3 = timezone(timedelta(hours=3))
CUT = datetime(2026, 10, 15, 22, 30, tzinfo=UTC3).timestamp()


def _settings_conn(rows=()):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE llm_settings (key TEXT PRIMARY KEY, value TEXT)")
    for k, v in rows:
        conn.execute("INSERT INTO llm_settings VALUES (?, ?)", (k, v))
    return conn


class RadarFloorTests(unittest.TestCase):
    def test_default_is_documented_cut(self):
        self.assertEqual(CUT, database._parse_reports_baseline(config.RADAR_REPORTS_BASELINE_DEFAULT))
        self.assertEqual(CUT, database._get_radar_floor_sync(_settings_conn()))

    def test_db_value_overrides_default_and_zero_disables(self):
        c = _settings_conn([("radar_reports_baseline_at", "2026-11-01 00:00")])
        self.assertEqual(datetime(2026, 11, 1, tzinfo=UTC3).timestamp(), database._get_radar_floor_sync(c))
        c = _settings_conn([("radar_reports_baseline_at", "0")])
        self.assertEqual(0.0, database._get_radar_floor_sync(c))

    def test_radar_cut_is_later_than_global_baseline(self):
        glob = database._get_reports_baseline_sync(_settings_conn())
        self.assertGreater(database._get_radar_floor_sync(_settings_conn()), glob)


class MacdMtfFloorTests(unittest.IsolatedAsyncioTestCase):
    async def _lower(self, **kw):
        seen = {}
        base = _settings_conn()
        fake = MagicMock()
        fake.execute.side_effect = lambda sql, params=(): (
            base.execute(sql, params) if "llm_settings" in sql
            else (seen.update(params=params) or MagicMock(fetchall=lambda: []))
        )
        orig = database._run_db

        async def runner(op):
            return op(fake)
        database._run_db = runner
        try:
            await database.list_macd_mtf_report(days=60, **kw)
        finally:
            database._run_db = orig
        return seen["params"][0]

    async def test_floor_applied_only_when_requested(self):
        self.assertEqual(CUT, await self._lower(apply_radar_floor=True))
        self.assertLess(await self._lower(), CUT)

    async def test_archive_view_removes_both(self):
        lower = await self._lower(ignore_reports_baseline=True, apply_radar_floor=True)
        self.assertLess(lower, CUT)


class DailyRisingFloorTests(unittest.IsolatedAsyncioTestCase):
    async def _since(self, **kw):
        import time
        seen = {}
        base = _settings_conn()
        fake = MagicMock()

        def execute(sql, params=()):
            if "llm_settings" in sql:
                return base.execute(sql, params)
            if "daily_rising_reports" in sql and "SELECT" in sql:
                seen["params"] = params
            return MagicMock(fetchall=lambda: [])
        fake.execute.side_effect = execute
        orig, orig_schema = database._run_db, database._ensure_daily_rising_reports_schema

        async def runner(op):
            return op(fake)
        database._run_db = runner
        database._ensure_daily_rising_reports_schema = lambda c: None
        try:
            await database.list_daily_rising_reports(days=30, **kw)
        finally:
            database._run_db, database._ensure_daily_rising_reports_schema = orig, orig_schema
        return seen["params"][0], time.time()

    async def test_floor_clamps_window_only_when_requested(self):
        # 2026-11-15 DUZELTME: bu test duvar saatine bagliydi ve CUT (2026-10-15)
        # ile now-30g cakisti -> bugun patladi. Sorun testin kendi kurgusundaydi:
        # "now-30g < CUT" varsayimi yalniz 2026-11-14'e kadar dogruydu.
        # Cozum: now'u CUT'a yakin SABIT bir ana dondur (deterministik).
        import time as _time
        frozen = CUT + 1.0            # CUT'un 1 sn sonrasi
        real_time = _time.time
        try:
            _time.time = lambda: frozen
            since_floor, _ = await self._since(apply_radar_floor=True)
            since_plain, _ = await self._since()
        finally:
            _time.time = real_time

        # (a) floor istendiginde alt sinir CUT'tan asagi inemez
        self.assertGreaterEqual(since_floor, CUT)
        # (b) floor istenmediginde pencere kirpilmaz -> CUT'un ALTINDA kalabilir
        self.assertLess(since_plain, CUT)
        # (c) floor istendiginde 30 gunluk pencerenin basi ile CUT'un BUYUGU
        self.assertEqual(max(CUT, frozen - 30 * 86400.0) // 1000,
                         since_floor // 1000)
