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
