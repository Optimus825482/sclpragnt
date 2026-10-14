"""Erken keşif (early_discovery) — `!miniTicker@arr` sözleşme testleri.

Kilitlenen davranışlar
----------------------
1. ingest: (ts, price, q) örnekleri tutulur; q KÜMÜLATİF 24h quoteVolume
   olduğu için periyot hacmi = q FARKI.
2. return_1m_pct = son fiyat / ~60 sn önceki fiyat - 1 (yüzde). Seyrek
   örneklemede (0 sn ve 61 sn) baz pencere sınırının solundaki örnek olur.
3. volume_burst = volume_1m / max(medyan dakika hacmi, VOLUME_MEDIAN_FLOOR);
   DISCOVERY_MIN_VOLUME_BURST (2.0) eşikini geçmeyen sessiz sembol elenir.
4. Sıralama |return_1m_pct| büyükten küçüğe + limit; sample_age > 15 sn eleme;
   2 dk'dır örnek gelmeyen sembolün durumu tamamen budanır (sızıntı yok).
5. Bozuk satır (None, eksik alan, sayıya çevrilemeyen fiyat) exception
   üretmez, yalnız o satır atlanır; sağlam satırlar işlenmeye devam eder.
6. reset() → durum ve aday listesi boşalır.
7. market_data entegrasyonu: `!miniTicker@arr` çerçevesinin `data` alanı DİZİ
   olduğu için `_process_ws_message` içindeki dict guard'ından ÖNCE list dalı
   early_discovery'yi beslemeli; dict çerçeveler (kline/ticker) aynen işlenir.
"""
import inspect
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import early_discovery as ed            # noqa: E402
from app import market_data as md                # noqa: E402
from app.market_data import MarketData           # noqa: E402


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


class EarlyDiscoveryBase(unittest.TestCase):
    def setUp(self):
        ed.reset()
        self.clock = _Clock()
        patcher = patch.object(ed, "_now", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(ed.reset)


class IngestAndReturnTests(EarlyDiscoveryBase):
    def test_return_1m_uses_price_60s_ago(self):
        """0 sn ve 61 sn sonra iki örnek → getiri 61 sn önceki fiyata göre."""
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 1000.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("BTCTRY", 101.0, 1600.0)])
        candidates = ed.top_candidates()
        row = next(item for item in candidates if item["symbol"] == "BTCTRY")
        # (101 / 100 - 1) * 100 = %1.0
        self.assertAlmostEqual(row["return_1m_pct"], 1.0, places=6)
        self.assertEqual(row["price"], 101.0)
        self.assertAlmostEqual(row["sample_age_sec"], 0.0, places=6)

    def test_cumulative_q_yields_minute_volume_and_burst(self):
        """q kümülatif → dakika hacmi = q farkı; sessiz sembol burst eşiğinde kalır."""
        pump_q = [0, 100, 200, 300, 400, 900]      # son dakikada +500 (taban 100/dk)
        steady_q = [0, 100, 200, 300, 400, 500]    # her dakika +100 → burst 1.0
        for minute in range(6):
            rows = [_row("PUMPTRY", 100.0 if minute < 5 else 105.0, pump_q[minute]),
                    _row("STEADYTRY", 100.0 if minute < 5 else 100.5, steady_q[minute])]
            ed.ingest_mini_ticker(rows)
            if minute < 5:
                self.clock.advance(60)
        candidates = ed.top_candidates()
        pump = next(item for item in candidates if item["symbol"] == "PUMPTRY")
        # getiri: (105/100-1)*100 = %5.0; hacim: (900-400)/medyan(0,100,100,100,100)=5.0
        self.assertAlmostEqual(pump["return_1m_pct"], 5.0, places=6)
        self.assertAlmostEqual(pump["volume_burst"], 5.0, places=6)
        # STEADYTRY getiri eşiğini geçer (%0.5 >= %0.4) ama burst 1.0 < 2.0 → elenir.
        self.assertFalse(any(item["symbol"] == "STEADYTRY" for item in candidates),
                         "sessiz sembol hacim patlaması olmadan aday olmamalı")

    def test_negative_q_delta_counts_as_zero(self):
        """UTC gün başında q sıfırlanınca negatif fark hayali hacim üretmemeli."""
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 1000.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 900.0)])   # q DÜŞTÜ (pencere sıfırlandı)
        # Hacim 0 → burst 0 → aday çıkmamalı; en azından istisna/hayali değer yok.
        self.assertEqual(ed.top_candidates(), [])
        state = ed._state["BTCTRY"]
        self.assertEqual(state["minutes"][-1][1], 0.0)

    def test_candidates_sorted_by_abs_return_desc_and_limited(self):
        ed.ingest_mini_ticker([_row("ETHTRY", 100.0, 10.0),      # +%1
                               _row("BTCTRY", 100.0, 10.0),      # +%3
                               _row("SOLTRY", 100.0, 10.0)])     # +%2
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("ETHTRY", 101.0, 9000.0),
                               _row("BTCTRY", 103.0, 9000.0),
                               _row("SOLTRY", 102.0, 9000.0)])
        ranked = [item["symbol"] for item in ed.top_candidates()]
        self.assertEqual(ranked, ["BTCTRY", "SOLTRY", "ETHTRY"])
        self.assertEqual([item["symbol"] for item in ed.top_candidates(limit=1)], ["BTCTRY"])
        self.assertEqual([item["symbol"] for item in ed.top_candidates(limit=2)],
                         ["BTCTRY", "SOLTRY"])

    def test_return_threshold_filters_falling_symbols(self):
        """DÜŞEN sembol (negatif getiri) |getiri| büyük olsa bile aday değildir."""
        ed.ingest_mini_ticker([_row("DUMPTRY", 100.0, 10.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("DUMPTRY", 95.0, 9000.0)])   # -%5
        self.assertEqual(ed.top_candidates(), [])


class FilterAndLifecycleTests(EarlyDiscoveryBase):
    def test_stale_sample_excluded_then_window_pruned(self):
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 10.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("BTCTRY", 110.0, 9000.0)])   # aday olur
        self.assertTrue(any(item["symbol"] == "BTCTRY" for item in ed.top_candidates()))
        # 16 sn örnek gelmedi → sample_age 16 > 15 → adaylık düşer ama durum kalır.
        self.clock.advance(16)
        self.assertEqual(ed.top_candidates(), [])
        self.assertIn("BTCTRY", ed._state)
        # 2 dk'dır örnek yok → pencere tamamen budanır ve durum düşer (sızıntı yok).
        self.clock.advance(200)
        self.assertEqual(ed.top_candidates(), [])
        self.assertEqual(ed._state, {})

    def test_broken_rows_are_skipped_without_raising(self):
        ed.ingest_mini_ticker([
            _row("BTCTRY", 100.0, 1000.0),               # sağlam
            {"s": "ETHTRY"},                             # eksik c/q → fiyat 0 → atlanır
            {"s": "XRPTRY", "c": "abc", "q": "5"},       # sayıya çevrilemeyen fiyat
            None,                                        # dict değil
            "garbage",                                   # dict değil
            {"s": "BTCUSDT", "c": "1", "q": "10"},       # TRY eki yok → saklanmaz
            {"s": "ADATRY", "c": "2.5", "q": "50"},      # sağlam
        ])
        self.assertIn("BTCTRY", ed._state)
        self.assertIn("ADATRY", ed._state)
        self.assertNotIn("BTCUSDT", ed._state)
        self.assertNotIn("XRPTRY", ed._state)
        self.assertNotIn("ETHTRY", ed._state)
        self.assertEqual(ed.top_candidates(), [])        # eşiği geçen yok, hata da yok

    def test_ingest_never_raises_on_non_list_input(self):
        ed.ingest_mini_ticker(None)
        ed.ingest_mini_ticker(12345)   # TypeError yutulur
        ed.ingest_mini_ticker([])
        self.assertEqual(ed._state, {})

    def test_reset_clears_state_and_candidates(self):
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 10.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("BTCTRY", 110.0, 9000.0)])
        self.assertTrue(ed.top_candidates())
        ed.reset()
        self.assertEqual(ed._state, {})
        self.assertEqual(ed.top_candidates(), [])


class ThresholdSourceTests(EarlyDiscoveryBase):
    def test_return_threshold_read_from_config(self):
        """Eşik config'ten okunur: DISCOVERY_MIN_RETURN_1M_PCT (varsayılan 0.4)."""
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 10.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("BTCTRY", 100.2, 5000.0)])   # getiri %0.2, burst çok yüksek
        self.assertEqual(ed.top_candidates(), [])                # %0.2 < varsayılan %0.4
        with patch.object(ed.config, "DISCOVERY_MIN_RETURN_1M_PCT", 0.1, create=True):
            self.assertEqual([item["symbol"] for item in ed.top_candidates()], ["BTCTRY"])
        self.assertEqual(ed.top_candidates(), [])                # patch kapanınca varsayılana döner

    def test_burst_threshold_read_from_config(self):
        ed.ingest_mini_ticker([_row("BTCTRY", 100.0, 10.0)])
        self.clock.advance(61)
        ed.ingest_mini_ticker([_row("BTCTRY", 103.0, 25.0)])     # getiri %3, hacim farkı 15 → burst 15
        self.assertTrue(ed.top_candidates())
        with patch.object(ed.config, "DISCOVERY_MIN_VOLUME_BURST", 20.0, create=True):
            self.assertEqual(ed.top_candidates(), [])

    def test_quote_suffix_env_override(self):
        with patch.dict(os.environ, {"DISCOVERY_QUOTE_SUFFIX": "USDT"}):
            ed.ingest_mini_ticker([_row("BTCUSDT", 100.0, 10.0), _row("BTCTRY", 100.0, 10.0)])
        self.assertIn("BTCUSDT", ed._state)
        self.assertNotIn("BTCTRY", ed._state)

    def test_quote_suffix_falls_back_to_config_attr(self):
        saved = os.environ.pop("DISCOVERY_QUOTE_SUFFIX", None)
        try:
            with patch.object(ed.config, "DISCOVERY_QUOTE_SUFFIX", "EUR", create=True):
                ed.ingest_mini_ticker([_row("BTCEUR", 100.0, 10.0), _row("BTCTRY", 100.0, 10.0)])
            self.assertIn("BTCEUR", ed._state)
            self.assertNotIn("BTCTRY", ed._state)
        finally:
            if saved is not None:
                os.environ["DISCOVERY_QUOTE_SUFFIX"] = saved


class MarketDataArrRoutingTests(unittest.TestCase):
    def setUp(self):
        ed.reset()
        self.addCleanup(ed.reset)

    def test_process_ws_message_routes_arr_list_into_early_discovery(self):
        market = MarketData(["BTCTRY"])
        market._process_ws_message({
            "stream": "!miniTicker@arr",
            "data": [_row("BTCTRY", 100.0, 1000.0),
                     _row("ETHTRY", 50.0, 20.0),
                     _row("BTCUSDT", 1.0, 1.0)],   # modülde filtrelenir
        })
        self.assertIn("BTCTRY", ed._state)
        self.assertIn("ETHTRY", ed._state)
        self.assertNotIn("BTCUSDT", ed._state)
        samples = ed._state["BTCTRY"]["samples"]
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0][1], 100.0)
        self.assertIsNotNone(market.ws_last_event_at, "arr çerçevesi WS canlılık damgası vurmalı")

    def test_arr_list_frame_does_not_break_dict_frames(self):
        """Liste dalı dict guard'ından ÖNCE gelir; kline/ticker dict akışı etkilenmez."""
        market = MarketData(["BTCTRY"])
        market._process_ws_message({
            "stream": "!miniTicker@arr",
            "data": [_row("BTCTRY", 100.0, 1000.0)],
        })
        market._process_ws_message({
            "stream": "btctry@ticker",
            "data": {"e": "24hrTicker", "E": 1000, "s": "BTCTRY", "c": "102.5"},
        })
        self.assertEqual(market.get_ticker("BTCTRY")["last_price"], 102.5)
        self.assertEqual(market.get_ticker("BTCTRY")["source"], "binance_tr_public_ws:ticker")


class WsArrSubscriptionTests(unittest.TestCase):
    def test_stream_list_appends_arr_at_the_end(self):
        streams = MarketData._ws_stream_list(("btctry",), ("1m",), include_arr=True)
        self.assertTrue(streams.endswith("!miniTicker@arr"), "arr stream listenin SONUNA eklenmeli")
        self.assertIn("btctry@kline_1m", streams)
        self.assertNotIn("!miniTicker@arr",
                         MarketData._ws_stream_list(("btctry",), ("1m",)),
                         "varsayılan (include_arr=False) abonelik arr içermemeli")

    def test_url_for_passes_include_arr(self):
        market = MarketData(["BTCTRY"])
        with_arr = market._ws_url_for("wss://example.invalid", ("btctry",), ("1m",), True)
        without_arr = market._ws_url_for("wss://example.invalid", ("btctry",), ("1m",))
        self.assertTrue(with_arr.endswith("!miniTicker@arr"))
        self.assertNotIn("!miniTicker@arr", without_arr)

    def test_only_first_group_subscribes_to_arr(self):
        market = MarketData([f"S{index}TRY" for index in range(40)])
        plans = market._build_ws_groups(1)
        self.assertGreater(len(plans), 1, "40 sembol tek gruba sığmamalı (çokyollu doğrulama)")
        self.assertTrue(plans[0]["include_arr"], "yalnız ilk grup arr abonesi olmalı")
        for plan in plans[1:]:
            self.assertFalse(plan["include_arr"])
        # test_w8 sözleşmesi: plan["url"] helper'ın 3-argümanlı çağrısıyla birebir
        # eşleşir; arr yalnız _run_ws_group'un yeniden kurduğu gerçek URL'de olur.
        self.assertNotIn("!miniTicker@arr", plans[0]["url"])

    def test_run_ws_group_rebuild_preserves_arr_flag(self):
        """Yeniden bağlanmada include_arr korunmalı (kaynak sözleşmesi)."""
        source = inspect.getsource(MarketData._run_ws_group)
        self.assertIn('plan.get("include_arr")', source)


if __name__ == "__main__":
    unittest.main()
