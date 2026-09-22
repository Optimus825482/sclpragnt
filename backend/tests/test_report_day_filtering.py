import pathlib
import sys
import unittest
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import database
from app.routers import reports, monitoring, auto_paper


class TestReportDayFiltering(unittest.IsolatedAsyncioTestCase):
    """Raporlama Merkezi gün bazlı izolasyon testi (2026-09-22 güncellemesi)."""

    async def test_report_day_filtering_isolated(self):
        await database.init_db()

        today_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d")
        today_start = datetime.strptime(today_str, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=3))).timestamp()
        yesterday_ts = today_start - 3600 * 24

        def op(conn):
            conn.execute(
                """INSERT INTO auto_paper_trades
                   (symbol, entry_price, quantity, order_value_try, status, pnl, pnl_pct, entry_time, exit_time, exit_reason, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("TESTOLDTRY", 10.0, 10, 100.0, "closed", 10.0, 10.0, yesterday_ts, yesterday_ts + 600, "tp",
                 float(yesterday_ts), float(yesterday_ts + 600))
            )
            conn.execute(
                """INSERT INTO auto_paper_trades
                   (symbol, entry_price, quantity, order_value_try, status, pnl, pnl_pct, entry_time, exit_time, exit_reason, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("TESTTODAYTRY", 20.0, 5, 100.0, "closed", 10.0, 10.0, today_start + 100, today_start + 700, "tp",
                 float(today_start + 100), float(today_start + 700))
            )
            conn.commit()
        await database._run_db(op)

        try:
            # 1. Bugünün istatistikleri (varsayılan)
            today_stats = await database.get_auto_paper_stats()
            self.assertGreaterEqual(today_stats["closed"], 1)

            # 2. Bugünün sembol kırılımı
            today_symbols = await database.get_auto_paper_symbol_breakdown()
            today_sym_names = [s["symbol"] for s in today_symbols]
            self.assertIn("TESTTODAYTRY", today_sym_names)
            self.assertNotIn("TESTOLDTRY", today_sym_names)

            # 3. Tüm zamanlar (day='all')
            all_stats = await database.get_auto_paper_stats(day="all")
            self.assertGreater(all_stats["closed"], today_stats["closed"])

            all_symbols = await database.get_auto_paper_symbol_breakdown(day="all")
            all_sym_names = [s["symbol"] for s in all_symbols]
            self.assertIn("TESTOLDTRY", all_sym_names)
            self.assertIn("TESTTODAYTRY", all_sym_names)

            # 4. /api/reports/overview endpoint testi
            ov_today = await reports.get_report_overview()
            self.assertEqual(ov_today["day"], "today")
            self.assertTrue(any(s["symbol"] == "TESTTODAYTRY" for s in ov_today["symbols"]))
            self.assertFalse(any(s["symbol"] == "TESTOLDTRY" for s in ov_today["symbols"]))

            ov_all = await reports.get_report_overview(day="all")
            self.assertEqual(ov_all["day"], "all")
            self.assertTrue(any(s["symbol"] == "TESTOLDTRY" for s in ov_all["symbols"]))

        finally:
            def cleanup(conn):
                conn.execute("DELETE FROM auto_paper_trades WHERE symbol IN ('TESTOLDTRY', 'TESTTODAYTRY')")
                conn.commit()
            await database._run_db(cleanup)
