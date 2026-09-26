"""W8 — piyasa verisi / WS dayanıklılığı (B-01 … B-06).

Kilitlenen bulgular
-------------------
B-01 (KRİTİK) 24s WS ömür dalı sonsuz nesil döngüsü üretiyordu (~11.900/sn, 0 bağlantı)
B-02 (KRİTİK) REST yedeği açık mumu kapalı gibi önbelleğe yazıyordu (sembol kalıcı fail-closed)
B-03 (YÜKSEK) WS yedek host'a geçiş fiilen çalışmıyordu (donmuş `plan["url"]`)
B-04 (YÜKSEK) 24h ticker evreni sessizce 50 sembolde kesiyordu (+ replace, merge değil)
B-05 (YÜKSEK) tek bozuk WS çerçevesi tüm grup soketini düşürüyordu
B-06 (YÜKSEK) `create_task(repair_history_gaps(...))` sonucu tutulmuyordu
"""
import asyncio
import inspect
import json
import unittest
from unittest.mock import patch

from app import binance_tr_public as pub
from app import market_data as md
from app.market_data import MarketData, _empty_history


class _FakeResponse:
    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return self._rows

    def raise_for_status(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class B01GenerationLoopTests(unittest.IsolatedAsyncioTestCase):
    """B-01: bayrak zaten True olsa bile watcher ANINDA dönmemeli."""

    async def test_watch_reconnect_has_a_min_dwell(self):
        m = MarketData(["BTCTRY"])
        m.running = True
        m.connection_generation = 1
        m.reconnect_requested = True  # bayrak ÖNCEDEN set (24s ömrü dalı)
        task = asyncio.create_task(m._watch_reconnect(1))
        await asyncio.sleep(0.03)
        self.assertFalse(
            task.done(),
            "bayrak zaten True iken anında dönmek sıcak nesil döngüsü üretir (B-01)",
        )
        await asyncio.wait_for(task, timeout=1.0)

    def test_lifetime_expiry_resets_ws_connected_at(self):
        src = inspect.getsource(MarketData.connect)
        # B-01: 24s ömrü dalı, bağlanma zamanlarını temizlemezse her nesil
        # aynı koşulu sağlar ve sıcak yeniden bağlanma döngüsü üretir.
        # B-07: artık tek skaler değil {group_id: ts} sözlüğü tutulduğu için
        # temizleme sözlük boşaltma şeklindedir.
        self.assertIn("self.ws_connected_at = {}", src,
                      "24s ömrü dalı bağlanma zamanlarını temizlemeli "
                      "(aksi halde her nesil yeniden tetikler)")
        self.assertIn("WS_GENERATION_MIN_INTERVAL_SEC", src,
                      "nesiller arasına asgari bekleme konmalı")

    def test_generation_interval_is_positive(self):
        self.assertGreater(MarketData.WS_GENERATION_MIN_INTERVAL_SEC, 0.0)


class B07PerGroupLifetimeTests(unittest.TestCase):
    """B-07: `ws_connected_at` TEK alandı ve tüm WS gruplarınca paylaşılıyordu.

    24 saatlik yaşam süresi kontrolü "son bağlanan grubun" zamanını
    kullandığı için diğer grupların ömrü sessizce takip edilmiyordu.
    """

    def test_connection_time_is_tracked_per_group(self):
        m = MarketData(["BTCTRY", "ETHTRY"])
        self.assertIsInstance(m.ws_connected_at, dict)
        src = inspect.getsource(MarketData._run_ws_group)
        self.assertIn("self.ws_connected_at[group_id]", src)

    def test_lifetime_check_uses_the_oldest_group(self):
        """Son bağlanan grup taze olduğu için en eski grup tetiklemelidir."""
        src = inspect.getsource(MarketData.connect)
        self.assertIn("min(self.ws_connected_at.values())", src,
                      "ömrü dolan grup 'son bağlanan' değil EN ESKİ olan olmalı")


class B03FailoverTests(unittest.IsolatedAsyncioTestCase):
    """B-03: başarısız denemede BİR SONRAKİ deneme farklı host'a gitmeli."""

    def test_url_is_rebuilt_from_base(self):
        m = MarketData(["BTCTRY", "ETHTRY"])
        url = m._ws_url_for("wss://example.invalid", ("btctry",), ("1m",))
        self.assertTrue(url.startswith("wss://example.invalid/stream?streams="))
        self.assertIn("btctry@kline_1m", url)
        self.assertIn("btctry@aggTrade", url)

    def test_plan_url_matches_the_helper(self):
        m = MarketData(["BTCTRY", "ETHTRY"])
        plans = m._build_ws_groups(1)
        self.assertTrue(plans)
        for plan in plans:
            self.assertEqual(
                m._ws_url_for(plan["base"], plan["symbols"], plan["timeframes"]),
                plan["url"],
            )

    def test_backoff_grows_and_is_capped(self):
        samples = [MarketData._ws_backoff_sec(i) for i in range(1, 9)]
        for value in samples:
            self.assertGreaterEqual(value, 0.5)
            self.assertLessEqual(value, 30.0)
        # 2. deneme 1. denemeden büyük olmalı (üstel artış; jitter'a rağmen)
        self.assertGreater(samples[4], samples[0])

    async def test_retry_rotates_the_host(self):
        m = MarketData(["BTCTRY"])
        m.running = True
        m.connection_generation = 1
        plan = m._build_ws_groups(1)[0]
        urls: list[str] = []

        def fake_connect(url, **kwargs):
            urls.append(url)
            if len(urls) >= 2:
                m.running = False  # iki denemeden sonra döngüden çık
            raise OSError("baglanti kurulamadi")

        with patch.object(md.websockets, "connect", fake_connect), \
                patch.object(MarketData, "_ws_backoff_sec", staticmethod(lambda attempt: 0.0)), \
                patch.object(m, "_schedule_repair", lambda *a, **k: None):
            await asyncio.wait_for(m._run_ws_group(plan), timeout=3.0)

        self.assertEqual(2, len(urls), "iki deneme bekleniyordu")
        self.assertNotEqual(urls[0], urls[1],
                            "başarısız denemeden sonra AYNI host'a yeniden bağlanılmamalı (B-03)")


class B05FrameResilienceTests(unittest.TestCase):
    """B-05: bozuk çerçeve akışı öldürmemeli."""

    def test_malformed_json_is_skipped_not_raised(self):
        m = MarketData(["BTCTRY"])
        self.assertEqual(0, m.ws_malformed_frames)
        m._handle_ws_frame("{bu gecerli json degil", 1, 1)  # patlamamalı
        self.assertEqual(1, m.ws_malformed_frames)

    def test_processing_error_is_contained(self):
        m = MarketData(["BTCTRY"])

        def boom(_payload):
            raise RuntimeError("islem hatasi")

        with patch.object(m, "_process_ws_message", boom):
            m._handle_ws_frame(json.dumps({"e": "kline"}), 1, 1)  # patlamamalı
        self.assertEqual(1, m.ws_malformed_frames)


class B06RepairTaskTests(unittest.IsolatedAsyncioTestCase):
    """B-06: onarım görevi güçlü referansla tutulmalı ve temizlenmeli."""

    async def test_task_is_referenced_then_discarded(self):
        m = MarketData(["BTCTRY"])
        started = asyncio.Event()

        async def fake_repair(symbols=None, timeframes=None):
            started.set()
            return {"requested": 0}

        with patch.object(m, "repair_history_gaps", fake_repair):
            task = m._schedule_repair(("btctry",), ("1m",), 1, 1)
            self.assertIn(task, m._bg_tasks, "görev güçlü referansla tutulmalı (GC riski)")
            await asyncio.wait_for(started.wait(), timeout=1.0)
            await asyncio.wait_for(task, timeout=1.0)
            await asyncio.sleep(0)  # done callback çalışsın
        self.assertNotIn(task, m._bg_tasks, "tamamlanan görev setten düşmeli")


class B04TickerChunkingTests(unittest.IsolatedAsyncioTestCase):
    """B-04: evren 50 sembolde kesilmemeli; sonuçlar birleştirilmeli."""

    def test_chunked_splits_evenly(self):
        self.assertEqual([[1, 2], [3]], list(pub._chunked([1, 2, 3], size=2)))

    def test_ticker_params_no_longer_truncates(self):
        symbols = [f"S{i}" for i in range(70)]
        params = pub._ticker_params(symbols)
        self.assertIn('"S69"', params["symbols"], "70. sembol de istekte olmalı")
        # 70 sembol → 69 virgül (her sembol çift tırnak içinde)
        self.assertEqual(69, params["symbols"].count(","))

    async def test_all_symbols_are_fetched_across_batches(self):
        symbols = [f"S{i}TR" for i in range(120)]
        seen_batches: list[list] = []

        def fake_get_json(path, params):
            listed = params.get("symbols")
            self.assertIsNotNone(listed, "dilimlerde symbols parametresi olmalı")
            batch = [s for s in symbols if f'"{s}"' in listed]
            seen_batches.append(batch)
            return [{"symbol": s, "quoteVolume": "1"} for s in batch]

        with patch.object(pub, "_get_json", fake_get_json):
            rows = await pub.ticker_24h(symbols)

        self.assertEqual(120, len(rows), "120 sembolün TAMAMI dönmeli (eskiden 50)")
        self.assertGreaterEqual(len(seen_batches), 3, "birden fazla dilim istenmeli")

    async def test_no_symbols_means_single_request(self):
        calls = []

        def fake_get_json(path, params):
            calls.append(params)
            return [{"symbol": "BTCTRY", "quoteVolume": "1"}]

        with patch.object(pub, "_get_json", fake_get_json):
            await pub.ticker_24h(None)
        self.assertEqual(1, len(calls))

    async def test_refresh_merges_instead_of_replacing(self):
        m = MarketData(["BTCTRY", "ETHTRY"])
        m.ticker_24h = {"OLDTRY": 123.0}

        async def fake_ticker_24h(_symbols):
            return [{"symbol": "BTCTRY", "quoteVolume": "500", "lastPrice": "10"}]

        async def fake_book(_symbols):
            return []

        with patch.object(md, "ticker_24h", fake_ticker_24h), \
                patch.object(md, "book_tickers", fake_book):
            await m.refresh_24h_tickers()

        self.assertEqual(500.0, m.ticker_24h["BTCTRY"])
        self.assertEqual(123.0, m.ticker_24h.get("OLDTRY"),
                         "bu turda dönmeyen sembolün değeri KORUNMALI (merge, replace değil)")


class B02RestFallbackTests(unittest.TestCase):
    """B-02: açık bar atılmalı; desenkronize seri onarılmalı."""

    def test_main_rest_fallback_uses_closed_history(self):
        from app import main
        src = inspect.getsource(main)
        self.assertIn("market._closed_history(", src,
                      "REST yedeği kanonik _closed_history kullanmalı")
        self.assertNotIn('hydrated = {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": []}',
                         src, "elle kurulmuş (timestamps'siz) sözlük kalmamalı")

    def test_closed_history_drops_the_open_bar(self):
        now_ms = 1_700_000_000_000
        duration = 5 * 60_000
        closed_open = now_ms - duration * 2
        open_open = now_ms - duration  # kapanışı gelecekte → açık bar
        rows = [
            [closed_open, "1", "2", "0.5", "1.5", "10", closed_open + duration - 1],
            [open_open, "1.5", "3", "1", "2.5", "99", open_open + duration - 1],
        ]
        history = MarketData._closed_history(rows, "5m", now_ms)
        self.assertEqual([closed_open], history["timestamps"], "açık bar atılmalı")
        self.assertEqual(1, len(history["closes"]))
        self.assertTrue(history["last_closed_at_ms"], "last_closed_at_ms yazılmalı")

    def test_process_kline_repairs_a_desynced_history(self):
        m = MarketData(["BTCTRY"])
        # `timestamps` YOK ama `closes` var → eski B-02 yazımının şekli
        m.klines["5m"]["BTCTRY"] = {"opens": [1.0], "highs": [2.0], "lows": [0.5],
                                    "closes": [1.5], "volumes": [10.0]}
        opened = 1_700_000_000_000
        payload = {
            "e": "kline", "E": opened,
            "k": {"s": "BTCTRY", "i": "5m", "t": opened, "T": opened + 299_999,
                  "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10.0, "x": True},
        }
        m._process_kline(payload)
        history = m.klines["5m"]["BTCTRY"]
        self.assertEqual(len(history["timestamps"]), len(history["closes"]),
                         "desenkronize seri onarılmalı (uzunluklar eşitlenmeli)")
        self.assertEqual([opened], history["timestamps"])


class B08TickerCopyTests(unittest.IsolatedAsyncioTestCase):
    """B-08: her kline olayında `dict(self.tickers)` tam kopya alınıyordu.

    70 elemanlı sözlüğün kopyası, saniyede ~25 olayda ve hepsi event loop'ta
    alınıyordu (≈100 KB/s saf kopyalama). Tek event loop'ta tek anahtar
    ataması atomiktir; B-04'ün toplu `{**…, **updates}` deseni ise GERÇEKTEN
    toplu güncelleme yaptığı için KORUNMALIDIR.
    """

    def test_hot_paths_no_longer_copy_the_whole_ticker_dict(self):
        # Yorum satırlarında geçen metin yanıltıcı olmasın diye gerçek
        # KOD deseni aranır: kopya alan bir atama + geri yazan satır.
        for method in (MarketData._process_kline, MarketData._handle_ws_frame):
            src = inspect.getsource(method)
            code = "\n".join(
                line for line in src.splitlines()
                if not line.lstrip().startswith("#")
            )
            self.assertNotIn("tickers = dict(", code,
                             f"{method.__name__} 70 elemanlık sözlüğü kopyalamamalı")
        self.assertIn("self.tickers[symbol] =",
                      inspect.getsource(MarketData._process_kline))

    def test_bulk_rest_refresh_keeps_the_merge_pattern(self):
        """B-04: `{**self.tickers, **updates}` toplu güncellemedir, korunmalı."""
        src = inspect.getsource(MarketData.refresh_24h_tickers)
        self.assertIn("{**self.tickers, **updates}", src)

    async def test_kline_updates_tickers_in_place(self):
        m = MarketData(["BTCTRY"])
        m.tickers["ETHTRY"] = {"symbol": "ETHTRY", "last_price": 7.0}
        identity = m.tickers
        m._process_kline({
            "e": "kline", "E": 1_700_000_000_000,
            "k": {"s": "BTCTRY", "i": "1m", "t": 1_700_000_000_000,
                  "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": False},
        })
        self.assertIs(identity, m.tickers, "sözlük nesnesi değişmemeli")
        self.assertEqual(1.5, m.tickers["BTCTRY"]["last_price"])
        # Kopyalama yapılsaydı buradaki diğer semboller kaybolmazdı ama
        # nesne kimliği değişirdi; korunması gereken sözleşme budur.
        self.assertEqual(7.0, m.tickers["ETHTRY"]["last_price"])

    async def test_ticker_stream_tolerates_a_non_numeric_close(self):
        """B-10: `data.get("c") or data.get("wrap")` kopyala-yapıştır artığıydı.

        `wrap` Binance şemasında yok; bozuk değerde `float()` tüm çerçeveyi
        düşürüyordu. Artık yerel try/except ile korunur.
        """
        m = MarketData(["BTCTRY"])
        payload = json.dumps({"e": "24hrTicker", "s": "BTCTRY", "c": "bozuk-deger",
                              "E": 1_700_000_000_000})
        m._handle_ws_frame(payload, 1, "g0")
        # Çerçeve düşmemeli, sembol de eski fiyatla kalmalı.
        self.assertNotIn("BTCTRY", m.tickers)

    async def test_ticker_stream_ignores_a_wrap_field(self):
        """B-10: `wrap` alanı olmayan bir çerçevede fiyat `wrap`'ten gelmez."""
        m = MarketData(["BTCTRY"])
        payload = json.dumps({"stream": "btctry@ticker", "data": {
            "e": "24hrTicker", "s": "BTCTRY", "c": "12.5", "E": 1_700_000_000_000}})
        m._handle_ws_frame(payload, 1, "g0")
        self.assertEqual(12.5, m.tickers["BTCTRY"]["last_price"])

    async def test_wrap_only_frame_does_not_invent_a_price(self):
        m = MarketData(["BTCTRY"])
        payload = json.dumps({"stream": "btctry@ticker", "data": {
            "e": "24hrTicker", "s": "BTCTRY", "wrap": "99.9", "E": 1_700_000_000_000}})
        m._handle_ws_frame(payload, 1, "g0")
        self.assertNotIn("BTCTRY", m.tickers)


class B10FreshnessCleanupTests(unittest.TestCase):
    """B-10: `... or missing_or_stale` geri-düşüşü temizlemeyi etkisiz bırakıyordu."""

    def test_source_has_no_or_fallback_on_the_cleanup(self):
        src = None
        for name in dir(MarketData):
            if name.startswith("__"):
                continue
            attr = getattr(MarketData, name, None)
            if not callable(attr):
                continue
            try:
                candidate = inspect.getsource(attr)
            except (TypeError, OSError):
                continue
            if "missing_or_stale" in candidate:
                src = candidate
                break
        self.assertIsNotNone(src, "missing_or_stale kullanan metot bulunamadı")
        self.assertNotIn('if item != "ticker_24h"] or missing_or_stale', src,
                         "`or` geri-düşüşü temizlemeyi tamamen etkisiz bırakıyor")


if __name__ == "__main__":
    unittest.main()
