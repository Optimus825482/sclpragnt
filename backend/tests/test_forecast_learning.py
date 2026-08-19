import sqlite3
import unittest
from unittest.mock import patch

from app.forecast_learning import derive_lessons, evaluate_forecast, normalize_direction


class ForecastLearningTests(unittest.TestCase):
    def test_evaluator_uses_threshold_and_direction(self):
        forecast = {"entry_price": 100.0, "direction": "up", "min_move_pct": 0.01}
        outcome = evaluate_forecast(forecast, outcome_price=102.0, max_high=103.0, min_low=99.0, evaluated_at=1.0)
        self.assertEqual(outcome["outcome_direction"], "up")
        self.assertTrue(outcome["direction_correct"])
        self.assertAlmostEqual(outcome["outcome_return_pct"], 0.02)

    def test_direction_normalization_accepts_turkish_labels(self):
        self.assertEqual(normalize_direction("YUKARI"), "up")
        self.assertEqual(normalize_direction("aşağı"), "down")
        self.assertEqual(normalize_direction("yatay"), "range")

    def test_lessons_require_holdout_and_activate_only_when_consistent(self):
        rows = []
        for index in range(15):
            rows.append({"status": "evaluated", "created_at": index, "symbol": "TESTTRY", "horizon_minutes": 60,
                         "regime": "bull_quiet", "direction": "up", "confidence": 60,
                         "direction_correct": index not in {4, 9, 14}})
        lessons = derive_lessons(rows, min_samples=12)
        symbol_lesson = next(item for item in lessons if item["symbol"] == "TESTTRY")
        self.assertEqual(symbol_lesson["status"], "active")
        self.assertEqual(symbol_lesson["sample_size"], 15)

    def test_llm_forecast_parser_requires_every_horizon(self):
        from app.main import _parse_forecast_response

        payload = '{"summary":"Kısa senaryo", "forecasts": [' + \
            '{"horizon_minutes":5,"direction":"yatay","confidence":54,"invalidation_price":null,"scenario":"test"},' + \
            '{"horizon_minutes":15,"direction":"yukarı","confidence":61,"invalidation_price":99,"scenario":"test"},' + \
            '{"horizon_minutes":60,"direction":"range","confidence":52,"invalidation_price":null,"scenario":"test"},' + \
            '{"horizon_minutes":240,"direction":"aşağı","confidence":55,"invalidation_price":101,"scenario":"test"}]}'
        parsed = _parse_forecast_response(payload, 100.0)
        self.assertEqual([item["direction"] for item in parsed["forecasts"]], ["range", "up", "range", "down"])
        self.assertIsNone(_parse_forecast_response('{"summary":"x","forecasts":[]}', 100.0))

    def test_forecast_text_never_exposes_a_partial_word(self):
        from app.main import _complete_forecast_text

        self.assertEqual(_complete_forecast_text("Birinci cümle tamam. İkinci cümle çok uzun sürer", 24), "Birinci cümle tamam.")
        self.assertEqual(_complete_forecast_text("Kelime kelime kelime kelime", 16), "Kelime kelime…")


class ForecastReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_aggregates_evaluated_and_pending_by_horizon(self):
        from app import database

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute("""CREATE TABLE llm_forecasts (
            forecast_id TEXT PRIMARY KEY, horizon_minutes INTEGER, status TEXT,
            direction_correct INTEGER, confidence REAL, outcome_return_pct REAL)""")
        conn.executemany("INSERT INTO llm_forecasts VALUES (?,?,?,?,?,?)", [
            ("a", 5, "evaluated", 1, 70, 0.01), ("b", 5, "evaluated", 0, 60, -0.01),
            ("c", 5, "pending", None, 55, None), ("d", 60, "evaluated", 1, 65, 0.02),
        ])
        async def run(operation): return operation(conn)
        with patch("app.database._run_db", new=run):
            rows = await database.get_llm_forecast_report()
        five = next(row for row in rows if row["horizon_minutes"] == 5)
        self.assertEqual(five["evaluated_count"], 2)
        self.assertEqual(five["correct_count"], 1)
        self.assertEqual(five["pending_count"], 1)
