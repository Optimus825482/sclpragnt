"""Canlı mum akışı (2026-09-16).

BİRİNCİ SORUN: Grafik sayfası mum verisini YALNIZCA doğrudan tarayıcı→Binance
WS'ine bağlıyordu. Bu adres browser'dan ERİŞİLEMEZ (backend sunucudan
bağlanabiliyor ama browser'dan TCP/TLS kurulamıyor → "WebSocket connection
failed") → grafik hiç canlı güncellenmiyordu.

İKİNCİ SORUN (bu dosyanın asıl kilitlediği): ilk çözüm YALNIZCA KAPANMIŞ mumları
yayınlıyordu. Ama HTTP `/api/market-klines` son eleman olarak **oluşan** mumu
verir ve kapanmış bir mumun açılış zamanı ondan her zaman KÜÇÜKTÜR. İstemcinin
`setBars` kapısı yalnızca `bar.time === last.time` (güncelle) veya
`bar.time > last.time` (ekle) durumunda resmi işler; küçük olanı DÜŞÜRÜR. Yani
canlı kanaldan gelen HER mum atılıyordu → grafik 10 sn'lik HTTP yoklamasına
mahkûmdu ve "canlı" rozeti yanıltıcı biçimde yeşil yanıyordu.

Bu dosya üç sözleşmeyi kilitler:
  1. MarketData dinleyiciyi HEM oluşan HEM kapanmış mumda çağırır (`closed` ile ayırt).
  2. Yayın zarfı istemcinin `===`/`>` kapısıyla kullanılabilir zaman dizisi üretir.
  3. Oluşan mum YALNIZCA bakılan (sembol, ufuk) çifti için yayınlanır (~420
     stream'in tamamı için yayın yapmak gereksiz yüktü) + burst koruması.
"""
import asyncio
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ws_live_candles as candles       # noqa: E402

BAR_MS = 1_700_000_000_000          # 5 dk'lık bir mumun açılış zamanı
NEXT_BAR_MS = BAR_MS + 300_000


def _bar(time_ms=BAR_MS, close=12.5, closed=False):
    return {"symbol": "BTCTRY", "timeframe": "5m", "time": time_ms, "open": 12.0,
            "high": 13.0, "low": 11.5, "close": close, "volume": 42.0,
            "closed": closed}


def _reset_module_state():
    candles._last_closed_ms.clear()
    candles._last_open_ms.clear()
    candles._last_open_publish_at.clear()
    candles._viewed_pairs.clear()


class BarListenerRegistrationTests(unittest.TestCase):
    def test_listener_registered_once(self):
        from app.state import market
        before = list(market._bar_listeners)
        try:
            market.add_bar_listener(candles._on_bar)
            market.add_bar_listener(candles._on_bar)
            self.assertEqual(1, market._bar_listeners.count(candles._on_bar),
                             "aynı dinleyici iki kez kaydedilmemeli")
        finally:
            market._bar_listeners[:] = before

    def test_remove_is_idempotent(self):
        from app.state import market
        before = list(market._bar_listeners)
        try:
            market.add_bar_listener(candles._on_bar)
            market.remove_bar_listener(candles._on_bar)
            market.remove_bar_listener(candles._on_bar)  # ikinci kez patlamamalı
            self.assertNotIn(candles._on_bar, market._bar_listeners)
        finally:
            market._bar_listeners[:] = before


class MarketDataDispatchesBothBarStatesTests(unittest.TestCase):
    """KÖK NEDEN KİLİDİ: MarketData oluşan mumu da iletmeli.

    Eskiden `_process_kline` içinde dinleyici çağrısı `if not candle["x"]: return`
    satırından SONRAydı → oluşan mumda dinleyici hiç çağrılmıyordu. Bu yüzden
    istemci, son (oluşan) mumuyla eşleşen bir canlı güncelleme ASLA alamıyordu.
    """

    def _market(self):
        from app.market_data import MarketData
        return MarketData(["BTCTRY"])

    @staticmethod
    def _kline(closed: bool, opened_ms: int = BAR_MS):
        return {"e": "kline", "k": {
            "s": "BTCTRY", "i": "5m", "t": opened_ms, "T": opened_ms + 299_999,
            "o": 12.0, "h": 13.0, "l": 11.5, "c": 12.5, "v": 42.0, "x": closed,
        }}

    def _dispatch(self, closed: bool):
        market = self._market()
        seen: list[dict] = []
        market.add_bar_listener(lambda symbol, tf, bar: seen.append(dict(bar)))
        market._process_kline(self._kline(closed))
        return seen

    def test_open_bar_reaches_listener(self):
        seen = self._dispatch(closed=False)
        self.assertEqual(1, len(seen), "OLUŞAN mum dinleyiciye ulaşmadı (canlı güncelleme ölür)")
        self.assertIs(False, seen[0]["closed"])

    def test_closed_bar_reaches_listener(self):
        seen = self._dispatch(closed=True)
        self.assertEqual(1, len(seen))
        self.assertIs(True, seen[0]["closed"])

    def test_bar_time_is_the_open_time_the_client_already_has(self):
        """İstemcinin son mumu ile AYNI açılış zamanı → `===` kapısı eşleşir."""
        seen = self._dispatch(closed=False)
        self.assertEqual(BAR_MS, seen[0]["time"])


class PublishContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_module_state()

    async def _publish(self, bar, *, viewed=True, symbol="BTCTRY", timeframe="5m"):
        if viewed:
            candles.note_viewed(symbol, timeframe)
        broadcast = AsyncMock(return_value=None)
        with patch("app.ws_runtime.ws_manager", MagicMock(broadcast=broadcast)):
            candles._on_bar(symbol, timeframe, bar)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        return broadcast

    async def test_closed_bar_payload_shape(self):
        broadcast = await self._publish(_bar(closed=True), viewed=False)
        broadcast.assert_awaited()
        payload = broadcast.await_args.args[0]
        self.assertEqual("kline", payload["type"])
        data = payload["data"]
        for field in ("symbol", "timeframe", "time", "open", "high", "low",
                      "close", "volume", "closed"):
            self.assertIn(field, data, f"yayın zarfında eksik alan: {field}")
        self.assertEqual("BTCTRY", data["symbol"])
        self.assertEqual("5m", data["timeframe"])
        self.assertEqual(12.5, data["close"])
        self.assertIs(True, data["closed"])

    # ---- Bakılan çift kapısı (gereksiz yayın yok) ------------------------
    async def test_open_bar_not_published_when_nobody_is_watching(self):
        """Kimse bu çifti görüntülemiyorsa oluşan mum için TEK mesaj üretilmemeli."""
        broadcast = await self._publish(_bar(closed=False), viewed=False)
        self.assertEqual(0, broadcast.await_count,
                         "bakılmayan sembol için oluşan mum yayınlandı (boşa yük)")

    async def test_open_bar_published_for_viewed_pair(self):
        broadcast = await self._publish(_bar(closed=False))
        self.assertEqual(1, broadcast.await_count)
        self.assertIs(False, broadcast.await_args.args[0]["data"]["closed"])

    async def test_closed_bar_published_even_if_not_viewed(self):
        """Bar geçişini panel hemen görsün: kapanmış mum bakılmadan da gider."""
        broadcast = await self._publish(_bar(closed=True), viewed=False)
        self.assertEqual(1, broadcast.await_count)

    async def test_viewed_pair_expires_after_ttl(self):
        """TTL dolunca çift düşer → oluşan mum yayını kendiliğinden durur."""
        candles.note_viewed("BTCTRY", "5m")
        candles._viewed_pairs[("BTCTRY", "5m")] = 0.0        # çok eski
        broadcast = await self._publish(_bar(closed=False), viewed=False)
        self.assertEqual(0, broadcast.await_count)
        self.assertNotIn(("BTCTRY", "5m"), candles._viewed_pairs,
                         "süresi dolan çift temizlenmedi")

    async def test_symbol_normalisation_matches_underscored_input(self):
        """`BTC_TRY` ile kaydedilen çift, `BTCTRY` yayınıyla eşleşmeli."""
        candles.note_viewed("BTC_TRY", "5m")
        broadcast = await self._publish(_bar(closed=False), viewed=False)
        self.assertEqual(1, broadcast.await_count)

    # ---- Mükerrer/eski mum bastırma -------------------------------------
    async def test_duplicate_closed_bar_is_not_republished(self):
        first = await self._publish(_bar(closed=True), viewed=False)
        self.assertEqual(1, first.await_count)
        second = await self._publish(_bar(closed=True), viewed=False)   # aynı zaman
        self.assertEqual(0, second.await_count, "aynı kapanmış mum iki kez yayınlandı")

    async def test_older_closed_bar_is_ignored(self):
        await self._publish(_bar(NEXT_BAR_MS, closed=True), viewed=False)
        older = await self._publish(_bar(BAR_MS, closed=True), viewed=False)
        self.assertEqual(0, older.await_count, "eski kapanmış mum yayınlanmamalı")

    async def test_older_open_bar_is_ignored(self):
        """Oluşan mum geriye gitmemeli (eski seriden gelen tick yayınlanmasın)."""
        await self._publish(_bar(NEXT_BAR_MS, closed=False))
        candles._last_open_publish_at.clear()               # throttle'ı devre dışı bırak
        older = await self._publish(_bar(BAR_MS, closed=False))
        self.assertEqual(0, older.await_count)

    async def test_open_bar_burst_is_throttled(self):
        """Ard arda gelen tick'ler sınırlanmalı (burst koruması)."""
        first = await self._publish(_bar(BAR_MS, closed=False))
        self.assertEqual(1, first.await_count)
        second = await self._publish(_bar(BAR_MS + 1000, closed=False))
        self.assertEqual(0, second.await_count, "burst koruması çalışmadı")

    # ---- ASIL REGRESYON: istemci kapısı bu diziyi İŞLEYEBİLMELİ ----------
    async def test_published_sequence_is_usable_by_the_client_gate(self):
        """İstemci kapısı (`===` güncelle / `>` ekle / `<` düşür) simülasyonu.

        Gerçek akış: mum açılır → tick'ler → kapanır → yenisi açılır.
        İstemcinin elinde HTTP'den gelen son mum (açılış zamanı BAR_MS, OLUŞAN)
        vardır. Yayınlanan dizinin bu kapıdan GEÇMESİ ve seriyi ilerletmesi şart.
        """
        import copy
        with patch.object(candles, "MIN_OPEN_PUBLISH_GAP_SEC", 0.0):
            open_first = await self._publish(_bar(BAR_MS, close=12.4, closed=False))
            on_close = await self._publish(_bar(BAR_MS, close=12.9, closed=True))
            next_open = await self._publish(_bar(NEXT_BAR_MS, close=13.1, closed=False))

        emitted = []
        for call in (open_first, on_close, next_open):
            self.assertGreaterEqual(call.await_count, 1, "beklenen mum yayınlanmadı")
            emitted.append(call.await_args.args[0]["data"])

        # İstemcinin setBars kapısı (charts/page.tsx) — birebir kopyası.
        last_time = BAR_MS                     # HTTP'den gelen son (oluşan) mum
        updates, appends = 0, 0
        for data in emitted:
            if data["time"] == last_time:
                updates += 1                    # series.update() → mum canlı tazelenir
            elif data["time"] > last_time:
                appends += 1                    # yeni bar eklenir
                last_time = data["time"]
            else:
                self.fail(f"mum istemci kapısında DÜŞÜRÜLÜRDÜ: {data['time']} < {last_time}")

        self.assertEqual(2, updates, "oluşan mum/kapanış canlı güncelleme üretmedi")
        self.assertEqual(1, appends, "yeni bar istemciye eklenmedi")

    async def test_broadcast_failure_does_not_raise(self):
        """Yayın hatası MarketData'nın WS döngüsünü bozmamalı."""
        candles.note_viewed("BTCTRY", "5m")
        fake_ws = MagicMock(broadcast=AsyncMock(side_effect=RuntimeError("boom")))
        with patch("app.ws_runtime.ws_manager", fake_ws):
            candles._on_bar("BTCTRY", "5m", _bar(closed=False))   # istisna sızdırmamalı
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    async def test_malformed_bar_is_ignored(self):
        for bad in (None, {}, {"time": 0}, {"time": None}, "not-a-dict"):
            candles._on_bar("BTCTRY", "5m", bad)      # patlamamalı
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
