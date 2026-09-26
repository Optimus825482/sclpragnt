"""History backfill eşzamanlılık sınırı (2026-09-26 deploy regresyonu).

Canlı log kanıtı: `backfill başladı` onlarca kez geçiyordu,
`backfill tamamlandı` HİÇ geçmiyordu. Yani her eksik sembol için ayrı
`_start_background` çağrısı yapılmıştı → 70 paralel görev → hepsi aynı
`max_size=8` DB havuzunda sıraya giriyor → event loop'un her isteği
geciktiriyor → `/api/*` istekleri 499 alıyor, backend `unhealthy`.

Bu test, backfill'in sınırlı eşzamanlılıkla çalıştığını ve startup'ı
beklemediğini davranışsal olarak kilitler.
"""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class BackfillConcurrencyTests(unittest.TestCase):
    """backfill_missing_active_history eşzamanlılık ve bloklama sözleşmesi."""

    def setUp(self):
        from app.routers import maintenance
        self.maintenance = maintenance
        self._orig_symbols = maintenance.config.SYMBOLS
        self._orig_get_candles = maintenance.database.get_market_candles
        self._orig_backfill = maintenance.backfill_symbol_history
        self._orig_start_bg = maintenance._start_background
        self.started: list[tuple] = []

    def tearDown(self):
        m = self.maintenance
        m.config.SYMBOLS = self._orig_symbols
        m.database.get_market_candles = self._orig_get_candles
        m.backfill_symbol_history = self._orig_backfill
        m._start_background = self._orig_start_bg

    def _patch_scan_all_stale(self, symbols):
        """Her sembolü 'backfill gerekli' işaretle."""
        async def fake_get(symbol, timeframe="5m", start_ms=None, end_ms=None):
            return []
        self.maintenance.database.get_market_candles = fake_get
        self.maintenance.config.SYMBOLS = list(symbols)

    def test_backfill_never_runs_before_startup_returns(self):
        """Startup, backfill'ler bitmeden dönmeli (healthcheck yanıt vermeli)."""
        m = self.maintenance
        symbols = [f"S{i}TRY" for i in range(30)]
        self._patch_scan_all_stale(symbols)

        ran = asyncio.Event()

        async def slow_backfill(symbol, days=7):
            ran.set()          # backfill BAŞLADI demek
            await asyncio.sleep(0.05)
        m.backfill_symbol_history = slow_backfill

        captured = {}

        def fake_start_background(coro_factory, name, single_pass=False):
            captured["name"] = name
            # Gerçek görevi başlatMA: sadece kaydet. Amaç, startup'ın
            # gerçekten backfill'i BEKLEMEDİĞini göstermek.
            return None
        m._start_background = fake_start_background

        # `inspect` her sembolü stale sayar → backfill listesi dolar.
        asyncio.run(m.backfill_missing_active_history())

        self.assertFalse(ran.is_set(), "startup backfill'i bekliyor — healthcheck kilitlenir")
        self.assertEqual(captured.get("name"), "history-backfill-drain",
                         "backfill'ler tek bir drain döngüsünde toplanmalı")

    def test_drain_limits_concurrency_to_two(self):
        """Backfill eşzamanlılığı 2 ile sınırlı olmalı (havuz koruması)."""
        m = self.maintenance
        symbols = [f"S{i}TRY" for i in range(20)]
        self._patch_scan_all_stale(symbols)

        concurrent = 0
        peak = 0

        async def tracking_backfill(symbol, days=7):
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.01)
            concurrent -= 1
        m.backfill_symbol_history = tracking_backfill

        background_coros = []

        def fake_start_background(coro_factory, name, single_pass=False):
            background_coros.append(coro_factory)
            return None
        m._start_background = fake_start_background

        async def scenario():
            await m.backfill_missing_active_history()
            for factory in background_coros:
                await factory()          # drain döngüsünü çalıştır
        asyncio.run(scenario())

        self.assertEqual(peak, 2,
                         f"backfill eşzamanlılığı {peak} çıktı; 2 sınırı aşıldı "
                         f"(DB havuzu max_size=8)")

    def test_fresh_symbols_start_no_drain(self):
        """Geçmişi taze olan sembol varsa drain döngüsü hiç başlatılmamalı."""
        m = self.maintenance
        m.config.SYMBOLS = ["FRESHTRY"]

        async def fresh_get(symbol, timeframe="5m", start_ms=None, end_ms=None):
            # 2016 satır ve taze: eşikleri geçiyor
            now = 9_000_000_000_000
            return [{"open_time": now - i * 1000} for i in range(2016)]
        m.database.get_market_candles = fresh_get

        launched = []
        m._start_background = lambda f, n, single_pass=False: launched.append(n)

        asyncio.run(m.backfill_missing_active_history())
        self.assertEqual(launched, [], "taze veri varken drain başlatılmamalı")

    def test_scan_error_does_not_abort_remaining_symbols(self):
        """Bozuk sembol tüm taramayı düşürmemeli (fail-soft)."""
        m = self.maintenance
        m.config.SYMBOLS = ["BADTRY", "GOODTRY"]

        async def selective_get(symbol, timeframe="5m", start_ms=None, end_ms=None):
            if symbol == "BADTRY":
                raise RuntimeError("simüle hata")
            return []
        m.database.get_market_candles = selective_get

        launched = []

        def fake_start_background(coro_factory, name, single_pass=False):
            launched.append(name)
            return None
        m._start_background = fake_start_background

        async def captured_backfill(symbol, days=7):
            pass
        m.backfill_symbol_history = captured_backfill

        background = []
        m._start_background = lambda f, n, single_pass=False: (background.append(f), n)

        async def scenario():
            await m.backfill_missing_active_history()
            for factory in background:
                await factory()
        asyncio.run(scenario())

        # GOODTRY backfill'e girmeli, BADTRY düşmeli.
        self.assertEqual(len(background), 1, "yalnız bir drain döngüsü bekleniyordu")


if __name__ == "__main__":
    unittest.main()
