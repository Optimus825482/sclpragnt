"""ticker_24h yükleme kilidi — event loop kilitlenmesi regresyonu (py-spy kanıtlı).

2026-09-26 deploy kilitlenmesinin py-spy yığını:

    Thread 1 (active): "MainThread"
        ticker_24h (app/binance_tr_public.py:402)      ← `with _ticker_24h_load_lock:`
        detect_velocity_candidates (app/routers/velocity.py:316)

`_ticker_24h_load_lock` threading.Lock idi ve `await _ticker_paged(...)` kilidin
altında tutuluyordu. İlk çağıran (radar) yüklerken Binance 429/418 döndü ve
_get_json worker thread'de time.sleep(30-90 sn) ile retry etti — kilidi elde.
İkinci çağıran (velocity scan) MainThread üzerinde SENKRON beklemeye girdi,
event loop dondu ve ilk yükleyicinin tamamlanması bir daha işlenemedi →
kalıcı deadlock → /health hiç yanıt vermedi → docker compose up -d exit 255.

Bu test aynı senaryoyu davranışsal olarak kilitler: yavaş bir yükleyici
sürerken ikinci çağıran beklemeye girer ve O SIRADA event loop
duyarlı kalmalıdır (healthcheck benzeri bir görev zamanında tamamlanmalı).
"""
import asyncio
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import binance_tr_public as btp


class Ticker24hLoadLockTests(unittest.TestCase):
    def setUp(self):
        btp._ticker_24h_cache.update({"key": None, "rows": None, "expires": 0.0})
        self._orig_paged = btp._ticker_paged
        self._orig_ttl = btp.TICKER_24H_CACHE_TTL_SEC
        btp.TICKER_24H_CACHE_TTL_SEC = 0.0  # her test taze yükleme görür

    def tearDown(self):
        btp._ticker_paged = self._orig_paged
        btp.TICKER_24H_CACHE_TTL_SEC = self._orig_ttl
        btp._ticker_24h_cache.update({"key": None, "rows": None, "expires": 0.0})

    def test_slow_load_does_not_block_event_loop(self):
        """Yükleme sürerken event loop duyarlı kalmalı (py-spy senaryosu)."""
        load_calls = 0

        async def slow_paged(path, symbols):
            nonlocal load_calls
            load_calls += 1
            await asyncio.sleep(0.4)  # "429 retry" benzeri yavaş yükleme
            return [{"symbol": "BTCTRY", "lastPrice": "1"}]

        btp._ticker_paged = slow_paged

        async def scenario():
            loader = asyncio.create_task(btp.ticker_24h())
            await asyncio.sleep(0.05)  # yükleyicinin kilidi almasını bekle

            # İkinci çağıran: eski kodda MainThread'i KİLİTLER.
            waiter = asyncio.create_task(btp.ticker_24h())

            # healthcheck benzeri görev: yükleme SÜRERKEN loop duyarlı olmalı.
            t0 = time.monotonic()
            probe = await asyncio.wait_for(_noop(), timeout=0.2)
            elapsed = time.monotonic() - t0

            rows = await asyncio.wait_for(waiter, timeout=2.0)
            await loader
            return probe, elapsed, rows

        probe, elapsed, rows = asyncio.run(scenario())
        self.assertLess(elapsed, 0.2,
                        f"loop {elapsed:.2f} sn bloklandı — threading.Lock "
                        f"regresyonu geri geldi (healthcheck timeout)")
        self.assertEqual(rows, [{"symbol": "BTCTRY", "lastPrice": "1"}])

    def test_concurrent_loads_single_network_call(self):
        """Eşzamanlı çağrılar tek ağ yüklemesi yapmalı (önbellek amacı korunur)."""
        load_calls = 0
        btp.TICKER_24H_CACHE_TTL_SEC = 1.0  # tek-yükleme için taze TTL şart

        async def counting_paged(path, symbols):
            nonlocal load_calls
            load_calls += 1
            await asyncio.sleep(0.05)
            return [{"symbol": "BTCTRY"}]

        btp._ticker_paged = counting_paged

        async def scenario():
            return await asyncio.gather(*(btp.ticker_24h() for _ in range(5)))

        results = asyncio.run(scenario())
        self.assertEqual(len(results), 5)
        self.assertEqual(load_calls, 1,
                         f"{load_calls} ağ yüklemesi yapıldı; tek yüklenme beklenirdi")

    def test_loader_failure_does_not_poison_cache(self):
        """Başarısız yükleme önbelleği zehirlememeli; sonraki çağrı tekrar denemeli."""
        attempts = 0

        async def flaky_paged(path, symbols):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("429 simülasyonu")
            return [{"symbol": "BTCTRY"}]

        btp._ticker_paged = flaky_paged

        async def scenario():
            with self.assertRaises(RuntimeError):
                await btp.ticker_24h()
            return await btp.ticker_24h()

        rows = asyncio.run(scenario())
        self.assertEqual(rows, [{"symbol": "BTCTRY"}])
        self.assertEqual(attempts, 2)


async def _noop():
    """Healthcheck benzeri hafif görev — loop duyarlılığının ölçütü."""
    await asyncio.sleep(0.01)
    return True


if __name__ == "__main__":
    unittest.main()
