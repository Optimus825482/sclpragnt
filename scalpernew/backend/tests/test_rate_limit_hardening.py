"""Binance public rate-limit sağlamlaştırma (2026-09-28 denetim).

Üç kilitlenen davranış:

1. `_get_json` uzun beklemelerini (Retry-After / ban backoff) semaphore
   DIŞINDA yapar — eski kodda `with _REQUEST_SEMAPHORE` içindeydi ve tek bir
   429/418 isteği 16 yuvayı saatlerce bloke edebiliyordu. Test, her uyku
   anında semaforun tam kapasitede olduğunu doğrular; eski kodda bu assert
   DÜŞER (mutasyon doğrulaması).

2. 429/418 sonrası paylaşılan soğuma penceresi `GLOBAL_COOLDOWN_MAX_SEC`
   ile kırpılır (thread havuzu korunur) ve pencere bitince bekleyenler
   ilerler.

3. Canlı tick evreni (`_order_tick_assets`) ve canlı 5m kalıcılık evreni
   (`_rotate_universe_window`) tavanlarla sınırlıdır.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import binance_tr_public  # noqa: E402


class _FakeClock:
    """time.time/time.sleep ikamesi; her uykuda semaforun boş olduğunu doğrular."""

    def __init__(self, module, start=10_000.0, assert_slot_free=True):
        self._module = module
        self.now = start
        self.sleeps: list[float] = []
        self._assert_slot_free = assert_slot_free

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        if self._assert_slot_free and seconds > 0:
            free = self._module._REQUEST_SEMAPHORE._value
            assert free == self._module.REST_MAX_CONCURRENCY, (
                f"bekleme semaphore YENİDEN KAZANILMADAN yapıldı — boş yuva {free}/"
                f"{self._module.REST_MAX_CONCURRENCY} (yuva bloke!)")
        self.sleeps.append(seconds)
        self.now += max(0.0, seconds)


class _Resp:
    def __init__(self, status, headers, data=b"{}"):
        self.status = status
        self.headers = headers
        self.data = data


class SemaphoreReleaseTests(unittest.TestCase):
    """429 sonrası Retry-After beklemesi yuvayı BLOKE ETMEMELİ."""

    def setUp(self):
        self.mod = binance_tr_public
        self._orig_pool = self.mod._HTTP_POOL
        self._orig_cooldown = self.mod._cooldown_until
        self._orig_used = dict(self.mod._rate_limit_used)

    def tearDown(self):
        self.mod._HTTP_POOL = self._orig_pool
        self.mod._cooldown_until = self._orig_cooldown
        self.mod._rate_limit_used.clear()
        self.mod._rate_limit_used.update(self._orig_used)

    def test_429_sleep_releases_semaphore_slot(self):
        clock = _FakeClock(self.mod)
        self.mod.time = clock  # test süresince sahte saat; tearDown cooldown'u geri alır
        calls = {"n": 0}

        class _Pool:
            def request(self, method, url, retries=False):
                calls["n"] += 1
                if calls["n"] == 1:
                    return _Resp(429, {"Retry-After": "5"})
                return _Resp(200, {"X-MBX-USED-WEIGHT-1M": "10"},
                             json.dumps({"ok": 1}).encode())

        self.mod._HTTP_POOL = _Pool()
        try:
            result = self.mod._get_json("/api/v3/ticker/price", {"symbol": "BTCUSDT"})
        finally:
            self.mod.time = __import__("time")
        self.assertEqual(result, {"ok": 1})
        self.assertGreaterEqual(len(clock.sleeps), 1, "429 sonrası hiç bekleme yapılmadı")
        self.assertAlmostEqual(clock.sleeps[0], 5.0, places=6,
                               msg="Retry-After değeri saygı görmedi")

    def test_418_notes_global_cooldown_and_recovers(self):
        clock = _FakeClock(self.mod)
        self.mod.time = clock
        calls = {"n": 0}

        class _Pool:
            def request(self, method, url, retries=False):
                calls["n"] += 1
                if calls["n"] == 1:
                    return _Resp(418, {"Retry-After": "600"})
                return _Resp(200, {}, json.dumps({"ok": 2}).encode())

        self.mod._HTTP_POOL = _Pool()
        try:
            result = self.mod._get_json("/api/v3/ticker/price", {})
        finally:
            self.mod.time = __import__("time")
        self.assertEqual(result, {"ok": 2})
        # 418 penceresi tavana kırpıldı (600 sn değil) ve saat ilerledikçe
        # bekleyenler ilerledi.
        self.assertLessEqual(self.mod._cooldown_remaining(), 0.0001)


class GlobalCooldownTests(unittest.TestCase):
    """Paylaşılan soğuma penceresi tavanı ve tükenmesi."""

    def setUp(self):
        self.mod = binance_tr_public
        self._orig_cooldown = self.mod._cooldown_until
        self._orig_time = self.mod.time
        self.mod.time = _FakeClock(self.mod, assert_slot_free=False)
        self.mod._cooldown_until = 0.0

    def tearDown(self):
        self.mod.time = self._orig_time
        self.mod._cooldown_until = self._orig_cooldown

    def test_ban_scale_delay_is_capped(self):
        self.mod._note_global_cooldown(3600.0)
        self.assertGreater(self.mod._cooldown_remaining(), 0.0)
        self.assertLessEqual(self.mod._cooldown_remaining(),
                             self.mod.GLOBAL_COOLDOWN_MAX_SEC + 0.001)

    def test_zero_delay_opens_no_window(self):
        self.mod._note_global_cooldown(0.0)
        self.mod._note_global_cooldown(-5.0)
        self.assertEqual(self.mod._cooldown_remaining(), 0.0)

    def test_wait_returns_after_window_expires(self):
        self.mod._note_global_cooldown(12.0)
        self.mod._wait_global_cooldown()
        self.assertEqual(self.mod._cooldown_remaining(), 0.0)

    def test_snapshot_reports_cooldown(self):
        self.mod._note_global_cooldown(10.0)
        snap = self.mod.rate_limit_snapshot()
        self.assertIn("global_cooldown_remaining_sec", snap)
        self.assertIn("global_cooldown_max_sec", snap)


class PriceTickUniverseTests(unittest.TestCase):
    """`_order_tick_assets`: extra önceliği, TRY dışlaması, deterministik tavan."""

    def test_extra_first_then_sorted_seen(self):
        from app.main import _order_tick_assets
        ordered = _order_tick_assets({"SOL", "BTC"}, ["ZRX", "ADA"], cap=10)
        self.assertEqual(ordered, ["ZRX", "ADA", "BTC", "SOL"])

    def test_try_excluded_and_dedup(self):
        from app.main import _order_tick_assets
        ordered = _order_tick_assets({"TRY", "BTC", "ETH"}, ["BTC", "TRY"], cap=10)
        self.assertEqual(ordered, ["BTC", "ETH"])

    def test_cap_truncates_deterministically(self):
        from app.main import _order_tick_assets, PRICE_TICK_MAX_ASSETS
        seen = {f"A{i:03d}" for i in range(50)}
        ordered = _order_tick_assets(seen, [], cap=PRICE_TICK_MAX_ASSETS)
        self.assertEqual(ordered, sorted(seen)[:PRICE_TICK_MAX_ASSETS])
        # 24 varlık × 2 çift + USDTTRY = 49 aday ≤ TICKER_SYMBOL_BATCH → tek istek
        self.assertLessEqual(len(ordered) * 2 + 1, binance_tr_public.TICKER_SYMBOL_BATCH)

    def test_empty_inputs(self):
        from app.main import _order_tick_assets
        self.assertEqual(_order_tick_assets(set(), [], cap=5), [])
        self.assertEqual(_order_tick_assets({"TRY"}, ["TRY"], cap=5), [])


class HistoryUniverseRotationTests(unittest.TestCase):
    """`_rotate_universe_window`: tavan + tam kapsama dönüşü."""

    def test_short_universe_untouched(self):
        from app.routers.maintenance import _rotate_universe_window
        window, cursor = _rotate_universe_window(["A", "B"], 5, 7)
        self.assertEqual((window, cursor), (["A", "B"], 0))

    def test_rotation_covers_every_symbol_within_three_rounds(self):
        from app.routers.maintenance import _rotate_universe_window
        full = [f"S{i:03d}" for i in range(250)]
        cap = 100
        seen: set[str] = set()
        cursor = 0
        for _ in range(3):
            window, cursor = _rotate_universe_window(full, cap, cursor)
            self.assertLessEqual(len(window), cap)
            seen |= set(window)
        self.assertEqual(seen, set(full))


if __name__ == "__main__":
    unittest.main()
