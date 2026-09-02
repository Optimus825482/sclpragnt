"""Forecast yanıt ayrıştırıcısı tolerans ve hata raporlama testleri."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers.llm_chat import _forecast_parse_defects, _parse_forecast_response

ALLOWED = {5, 15, 60}


class ParseTests(unittest.TestCase):
    def test_full_set_parses(self):
        text = ('{"summary":"En olası: up.","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"a"},'
                '{"horizon_minutes":15,"direction":"range","confidence":50,"scenario":"b"},'
                '{"horizon_minutes":60,"direction":"down","confidence":55,"scenario":"c"}]}')
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["forecasts"]), 3)

    def test_partial_set_now_accepted(self):
        """Tek ufuk eksikse kayıt çöpe gitmemeli; mevcutlar journal'a yazılmalı."""
        text = ('{"summary":"En olası: up.","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"a"},'
                '{"horizon_minutes":60,"direction":"down","confidence":55,"scenario":"c"}]}')
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual([f["horizon_minutes"] for f in parsed["forecasts"]], [5, 60])

    def test_fenced_json_and_prose(self):
        text = 'İşte analiz:\n```json\n{"summary":"x","forecasts":[{"horizon_minutes":5,"direction":"yukarı","confidence":70,"scenario":"ok"}]}\n```'
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["forecasts"][0]["direction"], "up")

    def test_invalid_rejects(self):
        self.assertIsNone(_parse_forecast_response("selam", 10.0, ALLOWED))
        self.assertIsNone(_parse_forecast_response(
            '{"forecasts":[{"horizon_minutes":5,"direction":"up","confidence":60}]}',
            10.0, ALLOWED))  # scenario yok
        self.assertIsNone(_parse_forecast_response(
            '{"summary":"x","forecasts":[]}', 10.0, ALLOWED))

    def test_defects_report(self):
        text = ('{"summary":"x","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"a"}]}')
        report = _forecast_parse_defects(text, ALLOWED)
        self.assertIn("ufuk(lar) eksik", report)
        self.assertIn("[15, 60]", report)
        report2 = _forecast_parse_defects("completely not json", ALLOWED)
        self.assertIn("JSON", report2)

    def test_turkish_direction_normalized(self):
        text = ('{"summary":"x","forecasts":['
                '{"horizon_minutes":15,"direction":"aşağı","confidence":40,"scenario":"s"}]}')
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertEqual(parsed["forecasts"][0]["direction"], "down")

    # --- toleranslı JSON kurtarma: modelin şemadan sapmaları artık veri
    # kaybettirmiyor (kayıt oluşturulmadan retry/retry sonrası çözüm döner).

    def test_single_quote_json_recovers(self):
        text = "{'summary': 'En olası: up.', 'forecasts': [{'horizon_minutes': 5, 'direction': 'up', 'confidence': 60, 'scenario': 'a'}]}"
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["forecasts"][0]["direction"], "up")

    def test_trailing_comma_recovers(self):
        text = ('{"summary":"En olası: up.","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"a",},'
                '{"horizon_minutes":15,"direction":"range","confidence":50,"scenario":"b"},'
                '{"horizon_minutes":60,"direction":"down","confidence":55,"scenario":"c"},]}')
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["forecasts"]), 3)

    def test_python_barewords_recovers(self):
        text = ('{"summary":"En olası: up.","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"a","invalidation_price":None},'
                '{"horizon_minutes":15,"direction":"range","confidence":50,"scenario":"b"},'
                '{"horizon_minutes":60,"direction":"down","confidence":55,"scenario":"c"}]}')
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed["forecasts"][0]["invalidation_price"])

    def test_scenario_with_brace_recovers(self):
        # Senaryo metni içinde '}' varsa eski find/rfind kırılırdı; denge
        # tarayıcı yalnızca gerçek kapanış süslüsünü almalı.
        text = ('{"summary":"En olası: up.","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"Seviye {x} kırılırsa devam eder."},'
                '{"horizon_minutes":60,"direction":"down","confidence":55,"scenario":"c"}]}')
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["forecasts"]), 2)

    def test_unterminated_object_recovers(self):
        # Model JSON'un kapanış süslüsünü kesmiş: `...}}` yerine `...}}`.
        text = ('{"summary":"En olası: up.","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"a"},'
                '{"horizon_minutes":15,"direction":"range","confidence":50,"scenario":"b"},'
                '{"horizon_minutes":60,"direction":"down","confidence":55,"scenario":"c"}],')
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["forecasts"]), 3)

    def test_double_encoded_json_recovers(self):
        import json as _json
        inner = {"summary": "En olası: up.", "forecasts": [
            {"horizon_minutes": 5, "direction": "up", "confidence": 60, "scenario": "a"}]}
        # Provider JSON-string content field'in içine kaçmış JSON.
        text = _json.dumps(_json.dumps(inner, ensure_ascii=False))
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["forecasts"][0]["horizon_minutes"], 5)

    def test_prose_wrapped_recovers(self):
        text = ('İşte analiz: {"summary":"En olası: up.","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"a"}]} '
                'Umarım yardımcı olmuştur.')
        parsed = _parse_forecast_response(text, entry_price=10.0, allowed_horizons=ALLOWED)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["forecasts"][0]["direction"], "up")

    def test_parse_defects_empty_when_valid(self):
        text = ('{"summary":"En olası: up.","forecasts":['
                '{"horizon_minutes":5,"direction":"up","confidence":60,"scenario":"a"},'
                '{"horizon_minutes":15,"direction":"range","confidence":50,"scenario":"b"},'
                '{"horizon_minutes":60,"direction":"down","confidence":55,"scenario":"c"}]}')
        self.assertEqual(_forecast_parse_defects(text, ALLOWED), "")

    def test_single_quote_defects_report(self):
        # Kurtarılamazsa bile defects insan-okur kalmalı; JSON değil diye
        # düşüp "JSON dışına metin yazılmış" dememeli (tek tırnak JSON'dur).
        text = ("{'summary': 'x', 'forecasts': [{'horizon_minutes': 5, 'direction': 'up', 'confidence': 60, 'scenario': 'a'}]}")
        report = _forecast_parse_defects(text, ALLOWED)
        self.assertIn("ufuk(lar) eksik", report)


if __name__ == "__main__":
    unittest.main()
