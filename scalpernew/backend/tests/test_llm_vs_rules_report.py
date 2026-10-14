import unittest
from unittest.mock import patch, AsyncMock
import time

from app import database
from app.routers import reports


class LlmVsRulesReportTests(unittest.IsolatedAsyncioTestCase):
    """Kural bazlı otonom işlemler ile LLM İkinci Göz karşılaştırma raporu testleri."""

    async def test_llm_vs_rules_comparison_aggregation(self):
        fake_data = {
            "stats": {
                "total_trades": 10,
                "total_closed": 8,
                "rules_pnl": 150.50,
                "rules_win_rate": 62.5,
                "llm_confirmed_count": 5,
                "llm_confirmed_pnl": 180.20,
                "llm_confirmed_win_rate": 80.0,
                "llm_traps_saved": 2,
                "llm_fake_total": 3,
                "llm_accuracy": 87.5,
                "eval_total": 8,
            },
            "trades": [
                {
                    "trade_id": 1,
                    "symbol": "BTCUSDT",
                    "status": "closed",
                    "entry_time": time.time() - 3600,
                    "exit_time": time.time() - 1800,
                    "entry_price": 60000.0,
                    "exit_price": 61200.0,
                    "quantity": 0.1,
                    "order_value_try": 6000.0,
                    "pnl": 120.0,
                    "pnl_pct": 2.0,
                    "exit_reason": "take_profit",
                    "notification_score": 85.0,
                    "notification_target_pct": 2.0,
                    "llm_verdict": "DEVAM",
                    "llm_confidence": 90.0,
                    "comparison_status": "LLM_WIN",
                    "comparison_label": "✅ Kazanç Teyitli",
                    "llm_summary": "Akış teyitli",
                }
            ],
        }

        with patch.object(database, "get_llm_vs_rules_comparison", AsyncMock(return_value=fake_data)):
            res = await reports.get_llm_vs_rules_report(day="today", limit=50)
            self.assertEqual(res["total"], 1)
            self.assertEqual(res["stats"]["llm_confirmed_win_rate"], 80.0)
            self.assertEqual(res["trades"][0]["comparison_status"], "LLM_WIN")

    async def test_llm_vs_rules_csv_export(self):
        fake_data = {
            "stats": {},
            "trades": [
                {
                    "trade_id": 42,
                    "symbol": "ETHUSDT",
                    "status": "closed",
                    "entry_time": 1700000000,
                    "exit_time": 1700001800,
                    "entry_price": 3000.0,
                    "exit_price": 2940.0,
                    "quantity": 1.0,
                    "order_value_try": 3000.0,
                    "pnl": -60.0,
                    "pnl_pct": -2.0,
                    "exit_reason": "stop_loss",
                    "notification_score": 75.0,
                    "notification_target_pct": 2.0,
                    "llm_verdict": "FAKE",
                    "llm_confidence": 85.0,
                    "comparison_status": "LLM_SAVED",
                    "comparison_label": "🛡️ Zarardan Korudu",
                    "llm_summary": "CVD zayıf fake kırılım",
                }
            ],
        }

        with patch.object(database, "get_llm_vs_rules_comparison", AsyncMock(return_value=fake_data)):
            resp = await reports.get_llm_vs_rules_csv(day="2026-09-28", limit=100)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.media_type, "text/csv; charset=utf-8")
            body_text = resp.body.decode("utf-8")
            self.assertIn("İşlem ID;Sembol", body_text)
            self.assertIn("ETHUSDT", body_text)
            self.assertIn("FAKE", body_text)
            self.assertIn("🛡️ Zarardan Korudu", body_text)


if __name__ == "__main__":
    unittest.main()
