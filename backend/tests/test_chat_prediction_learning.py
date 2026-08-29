"""Chat M5/M15 prediction learning: postmortem parsing and insight derivation."""
import unittest

from app.chat_prediction_learning import parse_analysis_response, derive_insights, build_analysis_snapshot


def _prediction(symbol, *, correct, horizon=5, factors=None, analyzed=True, seq=0):
    return {
        "prediction_id": f"p-{symbol}-{horizon}-{seq}", "symbol": symbol, "horizon_minutes": horizon,
        "direction": "up", "confidence": 62.0, "entry_price": 100.0, "min_move_pct": 0.5,
        "regime": "trend_up", "score": 3.2, "status": "evaluated", "analysis_status": "done" if analyzed else "pending",
        "direction_correct": correct, "outcome_return_pct": 0.8 if correct else -0.4,
        "analysis": "hacim teyidi belirleyiciydi" if factors else None,
        "analysis_factors": factors or {},
    }


class ParseAnalysisTests(unittest.TestCase):
    def test_plain_json_parses_tags(self):
        parsed = parse_analysis_response('{"summary":"yukarı tahmini doğru","misleading_factors":[],'
                                         '"success_factors":["Hacim Oranı Yüksek","adx güçlü","hacim oranı yüksek"],'
                                         '"lesson":"hacim teyidi öncelikli","confidence_note":"kalibre"}')
        self.assertEqual(parsed["summary"], "yukarı tahmini doğru")
        self.assertEqual(parsed["factors"]["success_factors"], ["hacim_oranı_yüksek", "adx_güçlü"])
        self.assertEqual(parsed["lesson"], "hacim teyidi öncelikli")

    def test_fenced_and_prose_wrapped_json(self):
        parsed = parse_analysis_response('Önce cümle. ```json\n{"summary":"s","misleading_factors":["spread"],'
                                         '"success_factors":[],"lesson":"l","confidence_note":"c"}\n```')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["factors"]["misleading_factors"], ["spread"])

    def test_invalid_payload_rejected(self):
        self.assertIsNone(parse_analysis_response("JSON değil"))
        self.assertIsNone(parse_analysis_response('{"no_summary":true}'))


class DeriveInsightsTests(unittest.TestCase):
    def test_insights_grouped_by_symbol_and_global(self):
        rows = []
        for index in range(5):
            rows.append(_prediction("BTCTRY", correct=index % 2 == 0, factors={
                "misleading_factors": ["adx_yetersiz"], "success_factors": ["hacim_orani_yuksek"]}, seq=index))
            rows.append(_prediction("ETHTRY", correct=True, factors={"success_factors": ["trend_uyumu"]}, seq=index))
        insights = derive_insights(rows, min_samples=5)
        btc = next(row for row in insights if row["symbol"] == "BTCTRY")
        self.assertEqual(btc["sample_size"], 5)
        self.assertEqual(btc["success_count"], 3)
        self.assertEqual(btc["failure_count"], 2)
        self.assertIn("adx_yetersiz", btc["factors"]["misleading_factors"])
        self.assertIn("hacim_orani_yuksek", btc["factors"]["success_factors"])
        general = [row for row in insights if row["symbol"] is None and row["horizon_minutes"] == 5]
        self.assertEqual(len(general), 1)
        self.assertGreaterEqual(general[0]["sample_size"], 10)

    def test_pending_and_below_min_samples_are_excluded(self):
        rows = [_prediction("BTCTRY", correct=True, analyzed=False) for _ in range(6)]
        self.assertEqual(derive_insights(rows, min_samples=5), [])
        rows = [_prediction("BTCTRY", correct=True) for _ in range(3)]
        self.assertEqual(derive_insights(rows, min_samples=5), [])


class SnapshotTests(unittest.TestCase):
    def test_snapshot_contains_prediction_and_outcome_only(self):
        prediction = _prediction("BTCTRY", correct=True)
        prediction["snapshot"] = {"candidate": {"returns_pct": {"return_5m": 1.2}, "evidence": ["e1"]}}
        snapshot = build_analysis_snapshot(prediction)
        self.assertEqual(snapshot["type"], "chat_prediction_postmortem")
        self.assertEqual(snapshot["prediction"]["symbol"], "BTCTRY")
        self.assertEqual(snapshot["measured_outcome"]["direction_correct"], True)
        self.assertEqual(snapshot["prediction_inputs"]["indicator_context"]["returns_pct"], {"return_5m": 1.2})
        self.assertNotIn("snapshot", snapshot)


if __name__ == "__main__":
    unittest.main()
