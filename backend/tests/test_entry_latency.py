"""Giriş gecikmesi ölçümü (2026-10-16): saf yardımcılar, uyarı, stats alanı, rapor script'i.

KİLİT: bildirim `detected_at` -> paper dolum (`entry_time`) gecikmesi ve giriş kayması
ölçülür; yüksek gecikmede WARNING; `/api/auto-paper/stats` `entry_latency` bloğu döner.
"""
import importlib.util
import logging
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers import auto_paper  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "entry_latency_report", ROOT / "scripts" / "entry_latency_report.py")
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


class PureHelperTests(unittest.TestCase):
    def test_latency_basic_and_ms_epoch(self):
        self.assertAlmostEqual(auto_paper.compute_entry_latency_sec(1000.0 + 7.5, 1000.0), 7.5)
        # ms epoch saniyeye çevrilir
        self.assertAlmostEqual(
            auto_paper.compute_entry_latency_sec(1_700_000_012_000, 1_700_000_000_000), 12.0)

    def test_latency_invalid_inputs_return_none(self):
        self.assertIsNone(auto_paper.compute_entry_latency_sec(100.0, None))
        self.assertIsNone(auto_paper.compute_entry_latency_sec(100.0, 0))
        self.assertIsNone(auto_paper.compute_entry_latency_sec(None, 100.0))
        self.assertIsNone(auto_paper.compute_entry_latency_sec("x", 100.0))
        # saat kayması (negatif) ölçüm dışı
        self.assertIsNone(auto_paper.compute_entry_latency_sec(100.0, 105.0))

    def test_slippage_pct(self):
        self.assertAlmostEqual(auto_paper.compute_entry_slippage_pct(101.0, 100.0), 1.0)
        self.assertAlmostEqual(auto_paper.compute_entry_slippage_pct(99.0, 100.0), -1.0)
        self.assertIsNone(auto_paper.compute_entry_slippage_pct(0, 100.0))
        self.assertIsNone(auto_paper.compute_entry_slippage_pct(100.0, None))

    def test_summarize_entry_latency(self):
        rows = [{"latency_sec": v, "slippage_pct": s} for v, s in
                [(1.0, 0.1), (2.0, 0.2), (3.0, 0.3), (20.0, 0.4), (100.0, None)]]
        rows.append({"latency_sec": None, "slippage_pct": 0.5})
        out = auto_paper.summarize_entry_latency(rows)
        self.assertEqual(out["n"], 5)
        self.assertEqual(out["median_latency_sec"], 3.0)
        self.assertEqual(out["max_latency_sec"], 100.0)
        self.assertAlmostEqual(out["share_over_15s"], 2 / 5)
        self.assertEqual(out["slippage_n"], 5)
        self.assertAlmostEqual(out["median_slippage_pct"], 0.3)

    def test_summarize_empty(self):
        out = auto_paper.summarize_entry_latency([])
        self.assertEqual(out["n"], 0)
        self.assertIsNone(out["median_latency_sec"])
        self.assertIsNone(out["share_over_15s"])


class RecordAndWarnTests(unittest.TestCase):
    def setUp(self):
        auto_paper._ENTRY_LATENCY_LOG.clear()

    def test_warns_when_latency_exceeds_threshold(self):
        notif = {"id": 5, "detected_at": 1000.0, "price": 100.0, "mode": "trend_devam"}
        with patch.object(auto_paper.config, "AUTO_PAPER_ENTRY_LATENCY_WARN_SEC", 15.0, create=True):
            with self.assertLogs("scalper.auto_paper", level=logging.WARNING) as cm:
                rec = auto_paper.record_entry_latency("AAATRY", 1, 1040.0, 100.5, notif, market_price=100.2)
        self.assertTrue(any("GİRİŞ GECİKMESİ" in m for m in cm.output))
        self.assertEqual(rec["entry_latency_sec"], 40.0)
        self.assertAlmostEqual(rec["entry_slippage_pct"], 0.5, places=3)
        self.assertAlmostEqual(rec["market_drift_pct"], 0.2, places=3)
        self.assertEqual(len(auto_paper._ENTRY_LATENCY_LOG), 1)

    def test_no_warning_when_fast(self):
        notif = {"id": 5, "detected_at": 1000.0, "price": 100.0}
        with patch.object(auto_paper.config, "AUTO_PAPER_ENTRY_LATENCY_WARN_SEC", 15.0, create=True):
            with self.assertLogs("scalper.auto_paper", level=logging.INFO) as cm:
                auto_paper.record_entry_latency("AAATRY", 1, 1002.0, 100.0, notif)
        self.assertFalse(any(r.levelno >= logging.WARNING for r in cm.records))

    def test_never_raises_on_garbage(self):
        # bildirim None bile olsa istisna fırlatmaz
        self.assertEqual(auto_paper.record_entry_latency("X", 1, "bad", "bad", {"detected_at": "q"}).get(
            "entry_latency_sec"), None)


class StatsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_has_entry_latency_block_from_mocked_rows(self):
        rows = [{"trade_id": i, "symbol": "AAATRY", "latency_sec": v, "slippage_pct": 0.1 * i}
                for i, v in enumerate([1.0, 2.0, 30.0, 4.0], start=1)]
        with patch.object(auto_paper.database, "get_auto_paper_stats", AsyncMock(return_value={"n": 0})), \
             patch.object(auto_paper.database, "get_reset_cutoff", AsyncMock(return_value=0)), \
             patch.object(auto_paper, "_fetch_recent_entry_latency_rows", AsyncMock(return_value=rows)):
            res = await auto_paper.get_stats_endpoint()
        el = res["entry_latency"]
        self.assertEqual(el["n"], 4)
        self.assertEqual(el["source"], "db_join")
        self.assertAlmostEqual(el["median_latency_sec"], 3.0)
        self.assertAlmostEqual(el["share_over_15s"], 0.25)
        self.assertAlmostEqual(el["median_slippage_pct"], 0.25)
        self.assertIn("p90_latency_sec", el)

    async def test_stats_falls_back_to_ring_when_db_fails(self):
        auto_paper._ENTRY_LATENCY_LOG.clear()
        auto_paper._ENTRY_LATENCY_LOG.append({"latency_sec": 8.0, "slippage_pct": 0.2})
        with patch.object(auto_paper.database, "get_auto_paper_stats", AsyncMock(return_value={})), \
             patch.object(auto_paper.database, "get_reset_cutoff", AsyncMock(return_value=0)), \
             patch.object(auto_paper, "_fetch_recent_entry_latency_rows",
                          AsyncMock(side_effect=RuntimeError("db down"))):
            res = await auto_paper.get_stats_endpoint()
        self.assertEqual(res["entry_latency"]["source"], "memory_ring")
        self.assertEqual(res["entry_latency"]["n"], 1)
        auto_paper._ENTRY_LATENCY_LOG.clear()


class ReportScriptTests(unittest.TestCase):
    def test_bucket_pnl_boundaries(self):
        rows = [{"latency_sec": v, "pnl_pct": p} for v, p in
                [(5.0, 1.0), (5.1, -1.0), (15.0, -2.0), (60.0, 3.0), (61.0, 5.0), (2.0, None)]]
        b = {x["bucket"]: x for x in report.bucket_pnl(rows)}
        self.assertEqual(b["<=5s"]["n"], 1)               # 5.0 dahil, pnl=None hariç
        self.assertEqual(b["5-15s"]["n"], 2)              # 5.1 ve 15.0
        self.assertAlmostEqual(b["5-15s"]["mean_pnl_pct"], -1.5)
        self.assertEqual(b["15-60s"]["n"], 1)             # 60.0
        self.assertEqual(b[">60s"]["n"], 1)

    def test_match_by_id_then_fallback_then_none(self):
        notifs = [{"id": 1, "symbol": "AAATRY", "detected_at": 1000.0, "price": 10.0, "mode": "trend_devam"},
                  {"id": 2, "symbol": "BBBTRY", "detected_at": 2000.0, "price": 5.0, "mode": "unified"}]
        idx = report.build_notif_index(notifs)
        n, how = report.match_notification({"notification_id": 1, "symbol": "AAATRY", "entry_time": 1003.0}, idx)
        self.assertEqual((n["id"], how), (1, "id"))
        # id yok -> aynı sembolde en yakın önceki bildirim, 10 dk içinde
        n, how = report.match_notification({"notification_id": None, "symbol": "BBBTRY", "entry_time": 2100.0}, idx)
        self.assertEqual((n["id"], how), (2, "fallback"))
        # 10 dk'dan uzak -> eşleşmez
        n, how = report.match_notification({"notification_id": None, "symbol": "BBBTRY", "entry_time": 2700.1}, idx)
        self.assertEqual((n, how), (None, "none"))
        # bildirimden ÖNCE dolum -> eşleşmez
        n, how = report.match_notification({"notification_id": None, "symbol": "BBBTRY", "entry_time": 1900.0}, idx)
        self.assertEqual(how, "none")

    def test_make_rows_and_group_stats(self):
        notifs = [{"id": 1, "symbol": "AAATRY", "detected_at": 1_000_000_000.0, "price": 100.0, "mode": "trend_devam"}]
        trades = [{"id": 9, "symbol": "AAATRY", "notification_id": 1, "entry_time": 1_000_000_020.0,
                   "entry_price": 100.5, "pnl_pct": -0.4, "status": "closed"}]
        rows = report.make_rows(trades, notifs)
        self.assertEqual(rows[0]["mode"], "trend_devam")
        self.assertAlmostEqual(rows[0]["latency_sec"], 20.0)
        self.assertAlmostEqual(rows[0]["slippage_pct"], 0.5)
        self.assertAlmostEqual(rows[0]["pnl_pct"], -0.4)
        g = report.group_stats(rows, "mode")
        self.assertEqual(g["trend_devam"]["latency"]["n"], 1)

    def test_db_url_read_lazily(self):
        # import anında DATABASE_URL gerekmez; yokken _db_url() çıkar
        with patch.dict("os.environ", {"DATABASE_URL": ""}):
            with self.assertRaises(SystemExit):
                report._db_url()


if __name__ == "__main__":
    unittest.main()
