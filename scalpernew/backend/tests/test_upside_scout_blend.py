"""EN HIZLI YÜKSELİŞ ANALİZİ butonunun iki profilli (5dk-%2 / 15dk-%3) harman davranışı."""
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import llm_chat  # noqa: E402


def _cand(symbol, horizon, score, passes=True):
    return {"symbol": symbol, "horizon_minutes": horizon, "velocity_score": score,
            "passes": passes, "price": 100.0, "ret3_pct": 0.5, "atr_pct": 1.2,
            "bb_width_pct": 4.0, "rsi": 55, "mfi": 60, "linreg_slope10_pct": 0.3,
            "aroon_up": 60, "aroon_down": 20, "mode": "trend_devam",
            "m5_pattern_ok": True, "leading_ok": False}


class UpsideScoutBlendTests(unittest.IsolatedAsyncioTestCase):
    async def _run_scout(self, scan5, scan15, text):
        """_upside_scout_impl'i mock bağımlılıklarla koşar; (result, analyze_mock) döner."""
        la = MagicMock()
        la.analyze = AsyncMock(return_value={"enabled": True, "status": "ok", "text": text,
                                             "model": "test-model", "generated_at": 1.0})
        with patch.object(llm_chat, "detect_velocity_candidates",
                          side_effect=lambda args, **kw: scan5 if kw["horizon_minutes"] == 5 else scan15), \
             patch.object(llm_chat.analyzer, "positions", {}), \
             patch.object(llm_chat, "_journal_touch_rates", AsyncMock(return_value={"AAAATRY": 0.5})), \
             patch.object(llm_chat, "_velocity_journal_quality", AsyncMock(return_value={"sample": 12, "touch_rate": 0.5})), \
             patch.object(llm_chat.database, "get_llm_forecast_lessons", AsyncMock(return_value=[])), \
             patch.object(llm_chat.ml_forecast, "predict_target", lambda *a, **k: {}), \
             patch.object(llm_chat, "llm_analysis", la), \
             patch.object(llm_chat.database, "save_llm_forecasts", AsyncMock(return_value=1)), \
             patch.object(llm_chat.embedding_worker, "enqueue_persistent", AsyncMock()):
            result = await llm_chat._upside_scout_impl()
        return result, la

    async def test_two_profiles_present_and_prompt_asks_blend(self):
        scan5 = {"candidates": [_cand("AAAATRY", 5, 2.5)], "watchlist": []}
        scan15 = {"candidates": [_cand("AAAATRY", 15, 3.0)], "watchlist": []}
        text = ("Sembol: AAAATRY\nAnlık fiyat: 100 TRY\nTahmini artış: %2.5\n"
                "Tahmini süre ve hedef fiyat: 5 dk · 102.5 TRY")
        result, la = await self._run_scout(scan5, scan15, text)

        self.assertTrue(result["enabled"])
        ctx = result["candidates"][0]
        # Aynı sembol iki ufukta da yakalanmışsa her iki profil de LLM context'inde.
        self.assertIn(5, ctx["profiles"])
        self.assertIn(15, ctx["profiles"])
        self.assertIn(ctx["best_profile_minutes"], (5, 15))
        self.assertEqual(ctx["horizon_minutes"], ctx["best_profile_minutes"])
        self.assertIsNotNone(ctx["target_price"])
        scout_prompt = la.analyze.await_args.args[0]
        self.assertIn("İKİ ayrı hız avcısı profili", scout_prompt["instruction"])
        self.assertIn("profiles", scout_prompt["candidates"][0])

    async def test_single_profile_symbol_marks_missing_unavailable(self):
        scan5 = {"candidates": [_cand("BBBTRY", 5, 2.0)], "watchlist": []}
        scan15 = {"candidates": [], "watchlist": []}
        text = "Sembol: BBBTRY\nAnlık fiyat: 100 TRY\nTahmini artış: %2.0\nTahmini süre ve hedef fiyat: 5 dk · 102 TRY"
        result, _la = await self._run_scout(scan5, scan15, text)
        ctx = result["candidates"][0]
        self.assertEqual(ctx["best_profile_minutes"], 5)
        self.assertFalse(ctx["profiles"][15].get("available", True))


if __name__ == "__main__":
    unittest.main()
