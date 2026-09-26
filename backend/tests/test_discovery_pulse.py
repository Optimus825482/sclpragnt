"""Keşif nabzı (pulse) + olay güdümlü hızlı tarama — sözleşme testleri.

Kilitlenen davranışlar
----------------------
1. return_20s_pct (early_discovery): 0/20/40 sn örneklerle 20 sn getiri =
   (şimdi / 20-sn-önceki örnek - 1) × 100 — `RETURN_20S_WINDOW_SEC` penceresinin
   SOLUNDAKİ örnek baz. 20 sn ufku hiç örneklenmemişse (sembol pencereden genç /
   örnekleme seyrek) None. Mevcut alanlar (symbol, return_1m_pct, volume_burst,
   price, sample_age_sec) AYNEN korunur — velocity havuzu ve mevcut testler
   bunlara bağlıdır.
2. _discovery_pulse (monitoring): top_candidates çıktısı frontend sözleşmesindeki
   7 alanla BİREBİR yayınlanır (detected_at eklenir); keşif modülü yoksa/patlarsa
   boş liste döner (exception YÜKSELMEZ, logger.warning). GET /state payload'ı
   "pulse" alanını yayınlar. PULSE BİLDİRİM DEĞİLDİR — ham keşiftir.
3. Fast scan kapıları (_maybe_run_fast_scan): DISCOVERY_FAST_SCAN_ENABLED=false
   → keşif okuması DAHİL hiçbir iş yapılmaz (sıfır ek yük); return_20s eşiği
   altı / None → tetik yok; sembol cooldown'u içinde → tetik yok; global min
   gap içinde → tetik yok; koşullar sağlanırsa _run_scan koşar, running bayrağı
   temizlenir, last_started + sembol cooldown'u damgalanır.
"""
import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import early_discovery as ed            # noqa: E402


def _row(symbol, price, q, event_ms=0):
    """Binance miniTicker satırı: fiyat ve quoteVolume STRING olarak gelir."""
    return {"e": "24hrMiniTicker", "E": event_ms, "s": symbol,
            "c": str(price), "q": str(q)}


class _Clock:
    """Monotonik saat ikamesi: test zamanı tam denetler."""

    def __init__(self, start=10_000.0):
        self.value = float(start)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


class Return20sTests(unittest.TestCase):
    """return_20s_pct hesabı + mevcut alanların korunması."""

    def setUp(self):
        ed.reset()
        self.clock = _Clock()
        patcher = patch.object(ed, "_now", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(ed.reset)

    def _top(self):
        # Eşikleri aç: bu sınıf yalnız 20 sn alanının HESABINI doğrular,
        # adaylık filtresini değil.
        with patch.object(ed.config, "DISCOVERY_MIN_RETURN_1M_PCT", -1.0), \
             patch.object(ed.config, "DISCOVERY_MIN_VOLUME_BURST", -1.0):
            return ed.top_candidates()

    def test_return_20s_uses_sample_20s_ago(self):
        """0/20/40 sn örnekleri: 20 sn getiri = (şimdi/20-sn-önceki - 1) × 100."""
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 1000.0)])
        self.clock.advance(20)
        ed.ingest_mini_ticker([_row("BTCTRY", 101.0, 1500.0)])
        self.clock.advance(20)
        ed.ingest_mini_ticker([_row("BTCTRY", 103.0, 2000.0)])
        rows = self._top()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # Pencere solu (cutoff=20) tam t=20 örneği: (103/101 - 1) × 100 = %1.9802
        self.assertAlmostEqual(row["return_20s_pct"], 1.9802, places=4)
        # 1m alanı AYNEN: baz pencere solu (t=0) → (103/100 - 1) × 100 = %3.0
        self.assertAlmostEqual(row["return_1m_pct"], 3.0, places=6)
        self.assertEqual(row["price"], 103.0)
        self.assertAlmostEqual(row["sample_age_sec"], 0.0, places=6)

    def test_return_20s_none_until_window_covered(self):
        """20 sn ufku örneklenmemişse (seyrek/genç sembol) None — eski örnekten
        yapay 20 sn getirisi üretilmez; 1m alanı kısa ufku ölçmeye devam eder."""
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 10.0)])
        self.clock.advance(5)
        ed.ingest_mini_ticker([_row("BTCTRY", 101.0, 20.0)])
        row = self._top()[0]
        self.assertIsNone(row["return_20s_pct"])
        self.assertAlmostEqual(row["return_1m_pct"], 1.0, places=6)

    def test_return_20s_sparse_gap_uses_leftmost_sample(self):
        """Seyrek örneklemede pencere solunda örnek VARSA (t=0, 61 sn önce) o
        bazdır — `_reference_sample` kuralı 1m alanıyla birebir aynıdır."""
        ed.ingest_mini_ticker([_row("ETHTRY", 100.0, 10.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("ETHTRY", 110.0, 20.0)])
        row = self._top()[0]
        self.assertAlmostEqual(row["return_20s_pct"], 10.0, places=6)
        self.assertAlmostEqual(row["return_1m_pct"], 10.0, places=6)

    def test_existing_fields_and_key_set_preserved(self):
        """Mevcut alanlar AYNEN; yalnız return_20s_pct EKLENİR."""
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 1000.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("BTCTRY", 101.0, 1600.0)])
        row = self._top()[0]
        self.assertEqual(set(row), {"symbol", "return_1m_pct", "return_20s_pct",
                                    "volume_burst", "price", "sample_age_sec"})
        self.assertEqual(row["symbol"], "BTCTRY")
        self.assertAlmostEqual(row["return_1m_pct"], 1.0, places=6)
        self.assertEqual(row["price"], 101.0)


class DiscoveryPulseTests(unittest.IsolatedAsyncioTestCase):
    """_discovery_pulse: alan eşlemesi + hata dayanıklılığı + state yayını."""

    def setUp(self):
        ed.reset()
        self.addCleanup(ed.reset)

    @staticmethod
    def _discovery_row():
        return {"symbol": "BTCTRY", "return_1m_pct": 1.5, "return_20s_pct": 0.6,
                "volume_burst": 3.2, "price": 101.0, "sample_age_sec": 0.4}

    def test_pulse_maps_fields_and_detected_at(self):
        from app.routers import monitoring
        before = time.time()
        with patch("app.early_discovery.top_candidates",
                   return_value=[self._discovery_row()]) as tc:
            pulse = monitoring._discovery_pulse()
        tc.assert_called_once_with(monitoring.config.DISCOVERY_PULSE_LIMIT)
        self.assertEqual(len(pulse), 1)
        item = pulse[0]
        # Frontend sözleşmesi — alan adları BİREBİR (8 alan; macd_mtf 2026-09-26
        # MACD MTF konfluans rozeti — önbellek kaydı yoksa None):
        self.assertEqual(set(item), {"symbol", "price", "return_1m_pct",
                                     "return_20s_pct", "volume_burst",
                                     "sample_age_sec", "detected_at", "macd_mtf"})
        self.assertIsNone(item["macd_mtf"])
        self.assertEqual(item["symbol"], "BTCTRY")
        self.assertEqual(item["price"], 101.0)
        self.assertEqual(item["return_1m_pct"], 1.5)
        self.assertEqual(item["return_20s_pct"], 0.6)
        self.assertEqual(item["volume_burst"], 3.2)
        self.assertEqual(item["sample_age_sec"], 0.4)
        self.assertGreaterEqual(item["detected_at"], before)
        self.assertLessEqual(item["detected_at"], time.time())

    def test_pulse_survives_discovery_exception(self):
        """Keşif modülü patlarsa state KIRILMAZ: boş liste + logger.warning."""
        from app.routers import monitoring
        with patch("app.early_discovery.top_candidates",
                   side_effect=RuntimeError("kesif modulu yok")), \
             patch.object(monitoring.logger, "warning") as warn:
            pulse = monitoring._discovery_pulse()   # exception YÜKSELMEZ
        self.assertEqual(pulse, [])
        self.assertTrue(warn.called, "logger.warning basılmalı")

    def test_pulse_skips_non_dict_rows(self):
        from app.routers import monitoring
        rows = [None, "garbage", self._discovery_row()]
        with patch("app.early_discovery.top_candidates", return_value=rows):
            pulse = monitoring._discovery_pulse()
        self.assertEqual([item["symbol"] for item in pulse], ["BTCTRY"])

    async def test_state_payload_publishes_pulse(self):
        from app.routers import monitoring
        with patch("app.early_discovery.top_candidates",
                   return_value=[self._discovery_row()]), \
             patch.object(monitoring, "_push_health_safe",
                          new=AsyncMock(return_value={"subscribers": 0})), \
             patch.object(monitoring, "get_user_notification_settings",
                          new=AsyncMock(return_value={"enabled": False})):
            payload = await monitoring.monitoring_state()
        self.assertIn("pulse", payload)
        self.assertEqual(payload["pulse"][0]["symbol"], "BTCTRY")
        self.assertIn("return_20s_pct", payload["pulse"][0])
        # Warm şeridi yayını AYNEN sürer (pulse yanına EKLENDİ, warm etkilenmez).
        self.assertIn("warm", payload)


class FastScanGateTests(unittest.IsolatedAsyncioTestCase):
    """_maybe_run_fast_scan kapıları: ENABLED / eşik / cooldown / min gap."""

    def setUp(self):
        from app.routers import monitoring
        self.mon = monitoring
        self._reset_fast()
        self.addCleanup(self._reset_fast)
        ed.reset()
        self.addCleanup(ed.reset)

    @staticmethod
    def _reset_fast():
        from app.routers import monitoring
        monitoring._fast_scan.update(
            {"last_started": 0.0, "running": False, "symbol_last": {}})

    @staticmethod
    def _row(sym="BTCTRY", ret20=1.0, burst=5.0):
        return {"symbol": sym, "return_1m_pct": 3.0, "return_20s_pct": ret20,
                "volume_burst": burst, "price": 101.0, "sample_age_sec": 0.1}

    async def test_disabled_never_reads_discovery(self):
        """ENABLED=false → keşif okuması DAHİL hiçbir iş yapılmaz (sıfır ek yük)."""
        with patch.object(self.mon.config, "DISCOVERY_FAST_SCAN_ENABLED", False), \
             patch("app.early_discovery.top_candidates") as tc, \
             patch.object(self.mon, "_run_scan", new=AsyncMock()) as scan:
            triggered = await self.mon._maybe_run_fast_scan()
        self.assertFalse(triggered)
        tc.assert_not_called()
        scan.assert_not_awaited()

    async def test_below_threshold_and_none_return_20s_do_not_trigger(self):
        """ret20s < eşik (0.5) VEYA None → tetik yok (burst yüksek olsa bile)."""
        with patch.object(self.mon.config, "DISCOVERY_FAST_SCAN_ENABLED", True), \
             patch("app.early_discovery.top_candidates",
                   return_value=[self._row(ret20=0.4, burst=10.0),
                                 self._row(sym="ETHTRY", ret20=None, burst=10.0)]), \
             patch.object(self.mon, "_run_scan", new=AsyncMock()) as scan:
            self.assertFalse(await self.mon._maybe_run_fast_scan())
        scan.assert_not_awaited()

    async def test_below_burst_threshold_does_not_trigger(self):
        """burst < DISCOVERY_FAST_SCAN_BURST (3.0) → tetik yok."""
        with patch.object(self.mon.config, "DISCOVERY_FAST_SCAN_ENABLED", True), \
             patch("app.early_discovery.top_candidates",
                   return_value=[self._row(ret20=2.0, burst=2.9)]), \
             patch.object(self.mon, "_run_scan", new=AsyncMock()) as scan:
            self.assertFalse(await self.mon._maybe_run_fast_scan())
        scan.assert_not_awaited()

    async def test_symbol_cooldown_blocks_trigger(self):
        """Aynı sembol cooldown (90 sn) içindeyse tetiklenmez."""
        self.mon._fast_scan["symbol_last"]["BTCTRY"] = time.monotonic()
        with patch.object(self.mon.config, "DISCOVERY_FAST_SCAN_ENABLED", True), \
             patch("app.early_discovery.top_candidates",
                   return_value=[self._row()]), \
             patch.object(self.mon, "_run_scan", new=AsyncMock()) as scan:
            self.assertFalse(await self.mon._maybe_run_fast_scan())
        scan.assert_not_awaited()

    async def test_global_min_gap_blocks_trigger(self):
        """Son tarama başlangıcından beri min gap (15 sn) dolmadıysa tetiklenmez —
        sembol eşiği geçse bile."""
        self.mon._fast_scan["last_started"] = time.monotonic()
        with patch.object(self.mon.config, "DISCOVERY_FAST_SCAN_ENABLED", True), \
             patch("app.early_discovery.top_candidates",
                   return_value=[self._row()]), \
             patch.object(self.mon, "_run_scan", new=AsyncMock()) as scan:
            self.assertFalse(await self.mon._maybe_run_fast_scan())
        scan.assert_not_awaited()

    async def test_running_flag_blocks_reentry_before_discovery_read(self):
        """Çakışma kilidi: running=True iken keşif okuması bile yapılmaz."""
        self.mon._fast_scan["running"] = True
        with patch.object(self.mon.config, "DISCOVERY_FAST_SCAN_ENABLED", True), \
             patch("app.early_discovery.top_candidates") as tc, \
             patch.object(self.mon, "_run_scan", new=AsyncMock()) as scan:
            self.assertFalse(await self.mon._maybe_run_fast_scan())
        tc.assert_not_called()
        scan.assert_not_awaited()

    async def test_trigger_runs_scan_and_marks_state(self):
        """Koşullar sağlanır: _run_scan koşar, running temizlenir, damgalar düşer."""
        with patch.object(self.mon.config, "DISCOVERY_FAST_SCAN_ENABLED", True), \
             patch("app.early_discovery.top_candidates",
                   return_value=[self._row()]), \
             patch.object(self.mon, "_run_scan", new=AsyncMock()) as scan:
            self.assertTrue(await self.mon._maybe_run_fast_scan())
        scan.assert_awaited_once()
        fast = self.mon._fast_scan
        self.assertFalse(fast["running"], "finally bloğu running'i temizlemeli")
        self.assertGreater(fast["last_started"], 0.0)
        self.assertGreater(fast["symbol_last"].get("BTCTRY", 0.0), 0.0)

    async def test_trigger_ignores_symbols_below_gate_but_fires_for_qualified(self):
        """Eşiği geçmeyen satırlar atlanır; sıradaki uygun sembol tetikler."""
        rows = [self._row(ret20=0.1, burst=10.0),
                self._row(sym="SOLTRY", ret20=1.2, burst=4.0)]
        with patch.object(self.mon.config, "DISCOVERY_FAST_SCAN_ENABLED", True), \
             patch("app.early_discovery.top_candidates", return_value=rows), \
             patch.object(self.mon, "_run_scan", new=AsyncMock()) as scan:
            self.assertTrue(await self.mon._maybe_run_fast_scan())
        scan.assert_awaited_once()
        self.assertIn("SOLTRY", self.mon._fast_scan["symbol_last"])
        self.assertNotIn("BTCTRY", self.mon._fast_scan["symbol_last"])


if __name__ == "__main__":
    unittest.main()
