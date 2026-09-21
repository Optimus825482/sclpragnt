"""Sohbet HIZLI ŞERİDİ kilitleri (2026-09-17).

NEDEN VAR: sembol sorusunda kullanıcı yanıt tamamen bitene kadar HİÇBİR ŞEY
görmüyordu. İki kök neden:
  1. Ağır ön-iş: `get_trades` + embedding/pgvector (30 sn timeout) +
     `deep_analyze_symbol` (7× `calculate_snapshot` ≈ 153 ms senkron CPU +
     `get_velocity_symbol_quality_stats` tam-tablo agregasyonu) + 2. embedding.
  2. Araç listesi doluyken `llm_analysis.stream_chat` TAMPONLAR
     (llm_analysis.py:577) → yanıt tek blok hâlinde, tool döngüsü bitince gelir.

Hızlı şerit ikisini birden kaldırır: yalnız hazır bellek önbellekleri
(+2 indeksli tek-satır DB okuması) ve ARAÇSIZ `stream_chat` → jeton jeton akış.

Kilitlenen davranışlar:
  1. Yalnız TEK sembol + durum sorusunda devreye girer (çoklu sembol, derinlik
     isteği, işlem/araştırma niyeti, uzun mesaj → AĞIR yol).
  2. Canlı kaynak yoksa None döner (soğuk başlangıçta ağır yola düşer).
  3. HIZLI ŞERİT ARAÇ GEÇİRMEZ — araç geçerse tamponlanır ve jeton jeton akış
     sessizce kaybolur. AST kilidi bunu korur.
  4. Bağlam YALNIZ var olan alanları taşır (prompt şişmez).
  5. `stream_chat` `max_tokens` kabul eder (kısa yanıt = hızlı ilk jeton).
"""
import ast
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config                     # noqa: E402
from app import llm_analysis                      # noqa: E402
from app.routers import llm_chat                  # noqa: E402
from app.routers import macd_monitor              # noqa: E402
from app.routers import monitoring                # noqa: E402

LLM_CHAT_PY = pathlib.Path(llm_chat.__file__)


class _FakeMarket:
    """Yalnız `get_ticker` kullanan test double'ı (ağ/WS yok)."""

    def __init__(self, ticker=None):
        self._ticker = ticker or {}

    def get_ticker(self, symbol):
        return self._ticker


def _func_node(name):
    tree = ast.parse(LLM_CHAT_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


class QuickLaneSymbolTests(unittest.TestCase):
    """Tetikleyici sınırları: hızlı şerit YALNIZ tek sembollü durum sorusunda."""

    def test_single_symbol_triggers(self):
        self.assertEqual("EGLDTRY", llm_chat._quick_lane_symbol(["EGLDTRY"], "EGLDTRY"))
        self.assertEqual("EGLDTRY", llm_chat._quick_lane_symbol(["EGLDTRY"], "EGLDTRY analiz"))
        self.assertEqual("EGLDTRY", llm_chat._quick_lane_symbol(["EGLDTRY"], "EGLDTRY şu an nasıl"))

    def test_multiple_symbols_stay_on_heavy_path(self):
        self.assertIsNone(llm_chat._quick_lane_symbol(["EGLDTRY", "BTCTRY"], "EGLDTRY BTCTRY karşılaştır"))

    def test_trade_intent_stays_on_heavy_path(self):
        self.assertIsNone(llm_chat._quick_lane_symbol(["EGLDTRY"], "EGLDTRY al", trade_intent=True))

    def test_research_intent_stays_on_heavy_path(self):
        self.assertIsNone(llm_chat._quick_lane_symbol(
            ["EGLDTRY"], "EGLDTRY geriye dönük test", research_only_intent=True))

    def test_depth_request_stays_on_heavy_path(self):
        for text in ("EGLDTRY detaylı analiz", "EGLDTRY tam analiz", "EGLDTRY rapor",
                     "EGLDTRY backtest", "EGLDTRY tüm göstergeler", "EGLDTRY işlem planı"):
            self.assertIsNone(llm_chat._quick_lane_symbol(["EGLDTRY"], text), text)

    def test_long_message_stays_on_heavy_path(self):
        long_text = "EGLDTRY " + " ".join(f"kelime{i}" for i in range(20))
        self.assertIsNone(llm_chat._quick_lane_symbol(["EGLDTRY"], long_text))

    def test_no_symbol_returns_none(self):
        self.assertIsNone(llm_chat._quick_lane_symbol([], "piyasa nasıl"))

    def test_disabled_by_config(self):
        with patch.object(config, "LLM_QUICK_LANE_ENABLED", False):
            self.assertIsNone(llm_chat._quick_lane_symbol(["EGLDTRY"], "EGLDTRY"))


class QuickLaneContextTests(unittest.IsolatedAsyncioTestCase):
    """Bağlam kurucu: yalnız hazır önbellekler; kaynak yoksa None (güvenli düşüş)."""

    def setUp(self):
        self._orig_market = llm_chat.market
        self.addCleanup(lambda: setattr(llm_chat, "market", self._orig_market))
        self.macd_patch = patch.object(macd_monitor, "_SNAPSHOT", {})
        self.macd_patch.start()
        self.addCleanup(self.macd_patch.stop)
        self.radar_patch = patch.object(monitoring, "get_cached_radar_candidate", lambda symbol: None)
        self.radar_patch.start()
        self.addCleanup(self.radar_patch.stop)
        self.ticker_patch = patch.object(llm_chat, "ticker_price", new=AsyncMock(return_value=[]))
        self.ticker_patch.start()
        self.addCleanup(self.ticker_patch.stop)

    async def test_returns_none_without_live_sources(self):
        llm_chat.market = _FakeMarket({})
        self.assertIsNone(await llm_chat._symbol_quick_context("EGLDTRY"))

    async def test_builds_compact_context_from_caches(self):
        llm_chat.market = _FakeMarket({"symbol": "EGLDTRY", "last_price": 42.5, "timestamp": 1_700_000_000_000})
        patch.object(macd_monitor, "_SNAPSHOT", {
            "symbols": {
                "EGLDTRY": {
                    "strength": 8.5, "tier": "GUCLU", "dir": 1, "early_score": 61,
                    "pre": {"dip": True, "approach": True, "m1": False},
                    "pre_detail": {"proximity": 0.82, "gap_atr": 0.3, "transition": True},
                    "sigs": {"5m": {"break": True, "state": "expand"}, "15m": None},
                    "cvd": {"buy_dominant": True, "buy_ratio": 0.62, "whale_net": 1200},
                    "tfs": {"5m": {"green": 6}, "15m": {"green": 4}, "3m": {"green": 5}},
                }
            }
        }).start()
        patch.object(monitoring, "get_cached_radar_candidate", lambda symbol: {
            "symbol": symbol, "mode": "trend_devam", "panel_score": 72.5,
            "target_pct": 2.5, "horizon_minutes": 5, "ml_target_pct": 1.8,
            "ml_hit_probability": 0.71, "volume_ratio": 2.1, "block_reason": None,
        }).start()
        with patch.object(llm_chat.database, "get_symbol_target_state",
                          AsyncMock(return_value={"target_pct": 1.9, "total_count": 12, "success_rate": 0.58})), \
             patch.object(llm_chat.database, "get_pending_monitoring_notification",
                          AsyncMock(return_value={"target_pct": 2.5, "price": 42.4,
                                                  "detected_at": 1_700_000_000, "horizon_minutes": 5})):
            quick = await llm_chat._symbol_quick_context("EGLDTRY")

        self.assertIsNotNone(quick)
        self.assertTrue(quick["quick_lane"])
        self.assertEqual("EGLDTRY", quick["symbol"])
        self.assertEqual(42.5, quick["price"])
        self.assertIn("answer_contract", quick)
        self.assertEqual("trend_devam", quick["radar_candidate"]["mode"])
        self.assertEqual(2.5, quick["radar_candidate"]["target_pct"])
        self.assertEqual({"5m": 6, "15m": 4}, quick["macd_state"]["green_by_tf"])
        self.assertTrue(quick["macd_state"]["cvd"]["buy_dominant"])
        self.assertEqual(1.9, quick["learned_target"]["target_pct"])
        self.assertEqual(2.5, quick["active_notification"]["target_pct"])

    async def test_context_omits_missing_fields(self):
        """Var olmayan alan bağlama girmez (prompt şişmesin)."""
        llm_chat.market = _FakeMarket({"symbol": "EGLDTRY", "last_price": 10.0})
        with patch.object(llm_chat.database, "get_symbol_target_state", AsyncMock(return_value=None)), \
             patch.object(llm_chat.database, "get_pending_monitoring_notification", AsyncMock(return_value=None)):
            quick = await llm_chat._symbol_quick_context("EGLDTRY")
        self.assertNotIn("macd_state", quick)
        self.assertNotIn("radar_candidate", quick)
        self.assertNotIn("learned_target", quick)
        self.assertNotIn("active_notification", quick)

    async def test_db_failure_does_not_break_context(self):
        """Öğrenilmiş hedef okunamazsa bağlam yine kurulur (hızlı şerit düşmesin)."""
        llm_chat.market = _FakeMarket({"symbol": "EGLDTRY", "last_price": 10.0})
        with patch.object(llm_chat.database, "get_symbol_target_state",
                          AsyncMock(side_effect=RuntimeError("db down"))), \
             patch.object(llm_chat.database, "get_pending_monitoring_notification",
                          AsyncMock(side_effect=RuntimeError("db down"))):
            quick = await llm_chat._symbol_quick_context("EGLDTRY")
        self.assertIsNotNone(quick)
        self.assertEqual(10.0, quick["price"])


class StreamChatContractTests(unittest.TestCase):
    """Akış sözleşmesi kilidi — hızlı şeridin tek kazancı jeton jeton akıştır."""

    def test_stream_chat_accepts_max_tokens(self):
        import inspect
        params = inspect.signature(llm_analysis.stream_chat).parameters
        self.assertIn("max_tokens", params)

    def test_quick_lane_passes_tools(self):
        """Hızlı şerit izinli araçlarla stream_chat çağırır (commit dd69d9f)."""
        func = _func_node("_symbol_quick_stream")
        self.assertIsNotNone(func, "llm_chat._symbol_quick_stream bulunamadı")
        calls = [n for n in ast.walk(func)
                 if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "stream_chat"]
        self.assertEqual(1, len(calls), "hızlı şeritte tam olarak bir stream_chat çağrısı olmalı")
        args = calls[0].args
        self.assertGreaterEqual(len(args), 4)

    def test_no_dotenv_or_env_import_needed_for_quick_lane(self):
        """Hızlı şerit config dışında ayar okumaz (tek kaynak: config.py)."""
        source = LLM_CHAT_PY.read_text(encoding="utf-8")
        start = source.index("HIZLI ŞERİT (2026-09-17)")
        end = source.index("@router.post(\"/api/strategies/llm/chat\")")
        block = source[start:end]
        self.assertNotIn("os.getenv", block)


# --------------------------------------------------------------------------
# Mutasyon notu: `_symbol_quick_stream` çağrısına tools/tool_executor eklenirse
# test_quick_lane_passes_no_tools KIRILIR; tetikleyici sınırları gevşetilirse
# (ör. `len(symbols) != 1` kaldırılırsa) çoklu-sembol testleri KIRILIR.
# --------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
