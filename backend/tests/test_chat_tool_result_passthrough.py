"""Genel sohbet aracının SONUCU modele geri dönmeli (2026-11-01).

NEDEN VAR: `/api/strategies/llm/chat` yolundaki `execute_tool` sarmalayıcısı
`_dispatch_tool`'u çağırıp sonucu `result` değişkenine alıyor, telemetriyi
yazıyor... ama HİÇBİR ŞEY DÖNDÜRMÜYOR. Python'da gövdesiz düşen bir coroutine
`None` üretir.

`llm_analysis.chat` her araç turunda dönen değeri
`json.dumps(_trim_tool_result(tool_result))` ile `role: "tool"` mesajına yazıp
modele geri gönderir → model beklediği veriyi bulamaz ve kullanıcıya
"tüm canlı araçlar boş (null) döndü" der. Model doğru söylüyor: gerçekten
`"content": "null"` alıyor.

Bu kilit iki şeyi korur:
  1. `execute_tool` `_dispatch_tool`'un sonucunu AYNEN döndürür.
  2. Gerçek araçlar (get_signals, scan_market_snapshots, ...) bu yoldan
     çağrıldığında `None` değil, araç sözlüğü döner.

Sembol sohbeti yolu (`/api/symbol-analysis/{symbol}/llm/chat`) bu hatadan
etkilenmez: onun `execute_tool`'u `return await ...` kalıbını korumuştur.
"""
import contextlib
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import llm_chat  # noqa: E402


@contextlib.contextmanager
def _no_rate_limit():
    """Sohbet hız sınırı SÜREÇ GENELİ durum tutar; test sırasına bağlı kalmamak
    için bu testlerde daima izin ver (sınanan davranış araç sonucunun
    aktarımıdır, hız sınırı değil)."""
    with patch.object(llm_chat, "rate_limit", lambda *a, **k: True):
        yield


async def _capture_tool_executor(text="SOLVTRY ve TRUMPTRY analiz"):
    """`strategies_llm_chat`'i çalıştırıp yakaladığı `execute_tool`'u döndürür."""
    captured: dict = {}

    async def fake_chat(context, messages, tools, tool_executor, active_skills=None,
                        *, max_tokens=None, json_mode=False):
        captured["tool_executor"] = tool_executor
        captured["tools"] = tools
        return {"enabled": True, "status": "ok", "text": "ok", "model": "test"}

    with patch.object(llm_chat.llm_analysis, "chat", fake_chat), \
         patch.object(llm_chat, "_persist_chat_memory", new=AsyncMock()), \
         patch.object(llm_chat, "_chat_memory_context", new=AsyncMock(return_value={})), \
         patch.object(llm_chat, "start_trace", new=AsyncMock()), \
         patch.object(llm_chat, "finish_trace", new=AsyncMock()), \
         patch.object(llm_chat, "save_evaluation", new=AsyncMock()), \
         patch.object(llm_chat, "_main_pg_pool", lambda: None), \
         patch.object(llm_chat.database, "get_trades", new=AsyncMock(return_value=[])), \
         patch.object(llm_chat.database, "get_chat_prediction_insights",
                      new=AsyncMock(return_value=[])), \
         _no_rate_limit():
        await llm_chat.strategies_llm_chat({"messages": [{"role": "user", "content": text}]})
    return captured


class ExecuteToolReturnsResultTests(unittest.IsolatedAsyncioTestCase):
    """Sarmalayıcı, `_dispatch_tool` sonucunu modele taşımalı."""

    async def test_executor_returns_dispatched_result_not_none(self):
        captured = await _capture_tool_executor()
        executor = captured.get("tool_executor")
        self.assertIsNotNone(executor, "execute_tool yakalanamadı — test kurulumu bozuk")

        sentinel = {"ok": True, "sinyaller": [{"symbol": "SOLVTRY"}], "count": 1}
        with patch.object(llm_chat, "get_monitoring_status_tool",
                          new=AsyncMock(return_value=sentinel)):
            result = await executor("get_monitoring_status", {})

        self.assertIsNotNone(
            result,
            "execute_tool None döndü: araç sonucu modele 'null' olarak gidiyor")
        self.assertEqual(sentinel, result)

    async def test_real_read_only_tool_is_not_none(self):
        """Gerçek araç yolu: sentetik değil, gerçek dispatch üzerinden."""
        captured = await _capture_tool_executor("sinyalleri göster")
        executor = captured["tool_executor"]

        with patch.object(llm_chat.database, "get_signals",
                          new=AsyncMock(return_value=[{"symbol": "SOLVTRY", "action": "BUY_SIGNAL"}])):
            result = await executor("get_signals", {"limit": 10})

        self.assertIsNotNone(result, "get_signals sonucu yolda kayboldu")
        self.assertEqual(1, result.get("count"))
        self.assertEqual("SOLVTRY", result["signals"][0]["symbol"])

    async def test_error_result_still_reaches_model(self):
        """Hata sözlüğü de dönmeli — model hatayı görüp strateji değiştirebilsin."""
        captured = await _capture_tool_executor()
        executor = captured["tool_executor"]

        result = await executor("bilinmeyen_arac_xyz", {})
        self.assertIsNotNone(result, "hata sözlüğü de yolda kayboldu")
        self.assertIn("error", result)


class SymbolRouteUnaffectedTests(unittest.IsolatedAsyncioTestCase):
    """Sembol sohbeti yolu bu hatadan muaf kalmalı (regresyon kilidi)."""

    async def test_symbol_route_executor_returns_result(self):
        captured: dict = {}

        async def fake_chat(context, messages, tools, tool_executor, active_skills=None,
                            *, max_tokens=None, json_mode=False):
            captured["tool_executor"] = tool_executor
            return {"enabled": True, "status": "ok", "text": "ok"}

        snapshot = {"type": "symbol", "symbol": "SOLVTRY", "data_ready": True}
        with patch.object(llm_chat.llm_analysis, "chat", fake_chat), \
             patch.object(llm_chat, "symbol_llm_context", new=AsyncMock(return_value=snapshot)), \
             patch.object(llm_chat, "_symbol_quick_context", new=AsyncMock(return_value=None)), \
             patch.object(llm_chat, "_persist_chat_memory", new=AsyncMock()), \
             patch.object(llm_chat, "_chat_memory_context", new=AsyncMock(return_value={})), \
             patch.object(llm_chat, "start_trace", new=AsyncMock()), \
             patch.object(llm_chat, "finish_trace", new=AsyncMock()), \
             patch.object(llm_chat, "_main_pg_pool", lambda: None), \
             _no_rate_limit():
            await llm_chat.symbol_analysis_llm_chat(
                "SOLVTRY", {"messages": [{"role": "user", "content": "SOLVTRY analiz"}]})

        executor = captured.get("tool_executor")
        self.assertIsNotNone(executor)
        sentinel = {"ok": True, "karar": "uygun", "edge_cost_ratio": 1.8}
        with patch.object(llm_chat, "validate_trade_plan",
                          new=AsyncMock(return_value=sentinel)):
            result = await executor("validate_trade_plan", {"symbol": "SOLVTRY"})
        self.assertIsNotNone(result, "sembol yolu da sonucu kaybediyor")
        self.assertEqual(sentinel, result)


if __name__ == "__main__":
    unittest.main()
