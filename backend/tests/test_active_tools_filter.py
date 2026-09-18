"""Sohbet "Aktif Araçlar" tercihinin genel sohbete uygulanması (2026-09-18).

Kullanıcı ayarları panelinde seçilen araçlar `active_tools` olarak gelir.
Beklenen davranış:
  - İstemci hiç tercih göndermezse tam araç listesi korunur (eski davranış).
  - Tercih gönderirse liste YALNIZ bu yüzeyin zaten sahip olduğu araçlarla
    kesişir; kullanıcı kendine yeni/yetkili bir araç enjekte edemez.
  - Emir araçları (open_llm_paper_trade / place_paper_order) kullanıcı
    seçse bile yalnız niyet bayrağıyla (trade_intent) değerlendirilir;
    `_resolve_active_tools` tek başına güvenlik kapısı değildir.
"""
import unittest

from app.routers import llm_chat


def _tool(name):
    return {"type": "function", "function": {"name": name}}


class ActiveToolsResolveTests(unittest.TestCase):
    def test_missing_preference_returns_full_list(self):
        tools = [_tool("a"), _tool("b")]
        self.assertEqual(tools, llm_chat._resolve_active_tools({}, tools))
        self.assertEqual(tools, llm_chat._resolve_active_tools({"active_tools": []}, tools))

    def test_preference_narrows_to_intersection(self):
        tools = [_tool("get_trades"), _tool("scan_market_snapshots"), _tool("open_llm_paper_trade")]
        result = llm_chat._resolve_active_tools(
            {"active_tools": ["get_trades", "get_real_account"]}, tools)
        self.assertEqual(["get_trades"], [t["function"]["name"] for t in result])

    def test_unknown_tools_cannot_be_injected(self):
        tools = [_tool("get_trades")]
        result = llm_chat._resolve_active_tools(
            {"active_tools": ["get_trades", "place_market_sell"]}, tools)
        self.assertEqual(["get_trades"], [t["function"]["name"] for t in result])

    def test_empty_intersection_leaves_no_tools(self):
        tools = [_tool("get_trades")]
        result = llm_chat._resolve_active_tools({"active_tools": ["bogus"]}, tools)
        self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
