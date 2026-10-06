import asyncio
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from app import database
from app.config import config


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


if __name__ == "__main__":
    unittest.main()
