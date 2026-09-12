"""W9 kilit testleri — piyasa verisi & mikro akış bulguları (B-07…B-19).

Her test, bulgunun ESKİ hâline döndürülmesi durumunda KIRILACAK şekilde
yazılmıştır; amaç "yeşil ama boş" bir koruma üretmemektir.
"""
import asyncio
import pathlib
import sys
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _empty_hist():
    return {"timestamps": [], "opens": [], "highs": [], "lows": [], "closes": [],
            "volumes": [], "last_closed_at_ms": 0, "updated_at": 0.0, "source": None}


# ---------------------------------------------------------------- B-15
class IntervalParsingTests(unittest.TestCase):
    def test_known_units_parse_exactly(self):
        from app.market_data import _interval_ms
        for tf, expected in (("1s", 1_000), ("5s", 5_000), ("1m", 60_000),
                             ("5m", 300_000), ("15m", 900_000), ("1h", 3_600_000),
                             ("4h", 14_400_000), ("1d", 86_400_000),
                             ("1w", 604_800_000), ("1M", 2_592_000_000)):
            self.assertEqual(expected, _interval_ms(tf), tf)

    def test_unknown_interval_raises_instead_of_defaulting_to_60s(self):
        from app.market_data import _interval_ms
        # Eski hâl: hepsi sessizce 60_000 dönüyordu.
        for bad in ("", "1x", "abc", None, "m", "5", "1mm"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                _interval_ms(bad)

    def test_month_is_not_silently_a_minute(self):
        from app.market_data import _interval_ms
        # Eski hâl `.lower()` yaptığı için "1M" = 60_000 (1 dakika) dönüyordu.
        self.assertNotEqual(_interval_ms("1m"), _interval_ms("1M"))


# ---------------------------------------------------------------- B-07
class KlineFreshnessTests(unittest.TestCase):
    def _market(self):
        from app.market_data import MarketData
        return MarketData(["BTCTRY"])

    def _seed(self, market, tf, source, age_sec):
        closed_ms = int((time.time() - age_sec) * 1000)
        market.klines[tf]["BTCTRY"].update({
            "timestamps": list(range(30)), "opens": [1.0] * 30, "highs": [1.0] * 30,
            "lows": [1.0] * 30, "closes": [1.0] * 30, "volumes": [1.0] * 30,
            "last_closed_at_ms": closed_ms, "updated_at": time.time(), "source": source,
        })

    def test_ws_fed_tolerance_is_interval_plus_small_lag(self):
        market = self._market()
        self._seed(market, "5m", "binance_tr_public_ws", age_sec=400)
        status = market.kline_freshness("BTCTRY", "5m")
        # Eski hâl: 5m toleransı 630 sn idi → 400 sn "fresh" sayılırdı.
        self.assertFalse(status["fresh"], status)
        self.assertEqual(315.0, status["max_age_sec"])

    def test_ws_fed_series_within_one_bar_period_is_fresh(self):
        market = self._market()
        self._seed(market, "5m", "binance_tr_public_ws", age_sec=290)
        self.assertTrue(market.kline_freshness("BTCTRY", "5m")["fresh"])

    def test_rest_fed_tolerance_still_covers_the_refresh_cadence(self):
        # 30m serisi WS aboneliğinde değildir; MACD monitörü onu 31 dakikada
        # bir REST ile tazeler. Tolerans bu kadansı kapsamalıdır.
        market = self._market()
        self._seed(market, "30m", "binance_tr_public_rest_refresh", age_sec=1860)
        status = market.kline_freshness("BTCTRY", "30m")
        self.assertTrue(status["fresh"], status)
        self.assertGreater(status["max_age_sec"], 1860)

    def test_unknown_timeframe_is_not_reported_fresh(self):
        market = self._market()
        status = market.kline_freshness("BTCTRY", "7x")
        self.assertFalse(status["fresh"])
        self.assertIsNone(status["max_age_sec"])


# ---------------------------------------------------------------- B-12
class RepairGapFreshClockTests(unittest.IsolatedAsyncioTestCase):
    async def test_now_ms_is_captured_after_the_fetch_await(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        stale_closed = int(time.time() * 1000) - 10 * 300_000
        market.klines["5m"]["BTCTRY"].update({
            "timestamps": [stale_closed - 300_000], "opens": [1.0], "highs": [1.0],
            "lows": [1.0], "closes": [1.0], "volumes": [1.0],
            "last_closed_at_ms": stale_closed, "updated_at": time.time(),
            "source": "binance_tr_public_ws",
        })

        returned_at = {}
        recorded = {}

        async def fake_fetch(symbol, tf, limit=400, start_time_ms=None):
            await asyncio.sleep(0.08)          # yavaş fetch
            returned_at["t"] = time.time()
            return [[stale_closed, "1", "1", "1", "1", "1", stale_closed + 300_000 - 1]]

        def recording_closed_history(rows, tf, now_ms):
            recorded["now_ms"] = now_ms
            hist = _empty_hist()
            hist["timestamps"] = [stale_closed]
            hist["last_closed_at_ms"] = stale_closed + 300_000 - 1
            hist["closes"] = [1.0]
            return hist

        with mock.patch("app.market_data.fetch_klines", side_effect=fake_fetch), \
             mock.patch.object(market, "_closed_history", side_effect=recording_closed_history):
            await market.repair_history_gaps(symbols=["BTCTRY"], timeframes=["5m"])

        self.assertIn("now_ms", recorded)
        # Eski hâl: now_ms döngü başında (fetch'ten ~80 ms ÖNCE) yakalanıyordu.
        self.assertGreaterEqual(recorded["now_ms"], int(returned_at["t"] * 1000) - 2)


# ---------------------------------------------------------------- B-10
class TradeFlowSlidingWindowTests(unittest.TestCase):
    def _trade(self, price, qty, buyer_maker=False):
        return {"p": str(price), "q": str(qty), "m": buyer_maker}

    def test_window_does_not_discard_valid_data_at_the_rollover(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        clock = {"t": 1_000_000.0}
        with mock.patch("app.market_data.time.time", side_effect=lambda: clock["t"]):
            market._accumulate_trade("BTCTRY", self._trade(100, 1))     # t=0
            clock["t"] += 59.0
            market._accumulate_trade("BTCTRY", self._trade(100, 2))     # t=59
            clock["t"] += 2.0
            market._accumulate_trade("BTCTRY", self._trade(100, 3))     # t=61
            trades = market.trade_flow["BTCTRY"]

        # t=0 kovası 61 sn yaşında → düşer. t=59 (2 sn yaşında) KALMALIDIR.
        # Eski "tumbling" hâlde 61. saniyedeki işlem sayaçları sıfırlar ve
        # hâlâ geçerli olan t=59 verisi tek tick'te silinirdi.
        self.assertEqual(2, trades["buy_count"])
        self.assertEqual(500.0, trades["buy_notional"])

    def test_window_age_is_reported_so_a_fresh_window_is_visible(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        clock = {"t": 2_000_000.0}
        with mock.patch("app.market_data.time.time", side_effect=lambda: clock["t"]):
            market._accumulate_trade("BTCTRY", self._trade(100, 1))
            clock["t"] += 7.0
            micro = market.get_microstructure("BTCTRY", 100.0)

        flow = micro["trade_flow"]
        self.assertIn("window_elapsed_sec", flow)
        self.assertAlmostEqual(7.0, flow["window_elapsed_sec"], places=3)
        self.assertEqual("2000_agg_trades", flow["tape_horizon"])
        self.assertEqual(1, flow["tape_trades"])

    def test_flat_counters_stay_accurate_for_external_readers(self):
        # macd_monitor `_symbol_cvd` `market.trade_flow`'u DOĞRUDAN okur.
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        clock = {"t": 3_000_000.0}
        with mock.patch("app.market_data.time.time", side_effect=lambda: clock["t"]):
            market._accumulate_trade("BTCTRY", self._trade(100, 5))
            clock["t"] += 120.0
            market._accumulate_trade("BTCTRY", self._trade(100, 1))
            trades = market.trade_flow["BTCTRY"]

        self.assertEqual(1, int(trades["buy_count"]))
        self.assertEqual(100.0, float(trades["buy_notional"]))


# ---------------------------------------------------------------- B-18
class LiquidityAverageVolumeTests(unittest.TestCase):
    def test_liquidity_status_reuses_the_cached_average(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        now = time.time()
        market.tickers["BTCTRY"] = {"symbol": "BTCTRY", "last_price": 100.0,
                                    "timestamp": int(now * 1000)}
        market.ticker_24h["BTCTRY"] = 10_000_000.0
        market.rest_ticker_updated_at = now
        market.orderflow["BTCTRY"].update({
            "bid_qty": 100.0, "ask_qty": 100.0, "spread_pct": 0.1, "updated_at": now,
        })
        # 21'den kısa seri: eski kopya kod ortalama 0.0 → oran 0.0 veriyordu.
        market.klines["5m"]["BTCTRY"].update({
            "timestamps": list(range(10)), "opens": [100.0] * 10, "highs": [100.0] * 10,
            "lows": [100.0] * 10, "closes": [100.0] * 10, "volumes": [10.0] * 10,
            "last_closed_at_ms": int(now * 1000), "updated_at": now,
        })
        with mock.patch.object(market, "get_avg_volume", return_value=10.0) as gav:
            _ok, details = market.liquidity_status("BTCTRY", 1000)
        self.assertTrue(gav.called, "liquidity_status önbellekli ortalamayı kullanmalı")
        self.assertEqual(1.0, details["volume_ratio"])


# ---------------------------------------------------------------- B-08
class Aggregate5sTests(unittest.TestCase):
    def _bars(self, timestamps, closes=None):
        closes = closes or [float(i) for i in range(len(timestamps))]
        return {"timestamps": list(timestamps), "opens": [1.0] * len(timestamps),
                "highs": [2.0] * len(timestamps), "lows": [0.5] * len(timestamps),
                "closes": list(closes), "volumes": [1.0] * len(timestamps)}

    def test_bucket_is_aligned_to_the_timestamp_not_the_array_index(self):
        from app.microflow import _aggregate_5s

        # Akış 5 sn kovasının ORTASINDA başlıyor (faz 3000 ms).
        bars = self._bars([3000, 4000, 5000, 6000, 7000, 8000, 9000])
        out = _aggregate_5s(bars)
        # Eski hâl: dizinin 0. elemanından 5'er → etiket 3000 (kaymış faz).
        self.assertEqual([5000], out["timestamps"])

    def test_bucket_with_a_missing_1s_bar_is_dropped_not_faked(self):
        from app.microflow import _aggregate_5s

        # 4000 ms eksik (WS yeniden bağlanma) → 0..4000 kovası tamamlanmaz.
        bars = self._bars([0, 1000, 2000, 3000, 5000, 6000, 7000, 8000, 9000])
        out = _aggregate_5s(bars)
        self.assertEqual([5000], out["timestamps"])
        self.assertEqual(5.0, out["volumes"][0])

    def test_complete_aligned_stream_is_unchanged(self):
        from app.microflow import _aggregate_5s

        bars = self._bars([0, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000],
                          closes=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        bars["opens"] = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        out = _aggregate_5s(bars)
        self.assertEqual([0, 5000], out["timestamps"])
        self.assertEqual([1.0, 6.0], out["opens"])
        self.assertEqual([5.0, 10.0], out["closes"])
        self.assertEqual([2.0, 2.0], out["highs"])
        self.assertEqual([0.5, 0.5], out["lows"])


# ---------------------------------------------------------------- B-09
class MicroFlowEvictionTests(unittest.IsolatedAsyncioTestCase):
    async def test_symbol_change_evicts_the_previous_symbol_state(self):
        from app.microflow import MicroFlow

        mf = MicroFlow()
        mf.symbol = "AAATRY"
        mf.bars["1s"]["AAATRY"]["timestamps"] = [1, 2, 3]
        mf.bars["1s"]["AAATRY"]["closes"] = [1.0, 2.0, 3.0]
        mf.trade_flow["AAATRY"]["buy_count"] = 7
        mf.depth = {"symbol": "AAATRY", "bids": [[1.0, 1.0]], "asks": [[2.0, 1.0]]}
        mf.depth_updated_at = time.time()

        async def _noop():
            return None

        with mock.patch.object(mf, "_run", new=_noop):
            await mf.start("BBBTry")
        try:
            self.assertNotIn("AAATRY", mf.bars["1s"])
            self.assertNotIn("AAATRY", mf.trade_flow)
            self.assertEqual({}, mf.depth, "sembole göre anahtarlı olmayan depth temizlenmeli")
        finally:
            await mf.stop()

    async def test_same_symbol_restart_keeps_the_warm_state(self):
        from app.microflow import MicroFlow

        mf = MicroFlow()
        mf.symbol = "AAATRY"
        mf.running = True
        mf._ws_task = mock.Mock()
        mf._ws_task.done.return_value = False
        mf.bars["1s"]["AAATRY"]["timestamps"] = [1]
        await mf.start("AAATRY")
        self.assertIn("AAATRY", mf.bars["1s"])


# ---------------------------------------------------------------- B-16
class MicroFlowBackoffTests(unittest.TestCase):
    def test_backoff_grows_and_is_capped(self):
        from app.microflow import _microflow_backoff_sec
        first = _microflow_backoff_sec(1)
        self.assertGreater(first, 0.0)
        self.assertLessEqual(first, 1.0)          # eski hâl sabit 2.0 sn idi
        self.assertLessEqual(_microflow_backoff_sec(3), 4.0)
        self.assertLessEqual(_microflow_backoff_sec(50), 30.0)
        self.assertGreater(_microflow_backoff_sec(50), 15.0)

    def test_stream_list_is_a_single_source(self):
        from app.microflow import MicroFlow
        self.assertEqual(["btctry@kline_1s", "btctry@aggTrade"], MicroFlow()._streams("BTCTRY"))

    def test_snapshot_exposes_feed_health(self):
        from app.microflow import MicroFlow
        mf = MicroFlow()
        mf.symbol = "BTCTRY"
        mf.ws_updated_at = time.time()
        snap = mf.get_snapshot(price=100.0)
        self.assertEqual("microflow_own_ws", snap["agg_feed"])
        for key in ("ws_messages", "ws_reconnects", "ws_queue_max"):
            self.assertIn(key, snap["freshness"])


# ---------------------------------------------------------------- B-19
class MicroFlowSnapshotMetricTests(unittest.TestCase):
    def _mf_with_1s_bars(self, closes):
        from app.microflow import MicroFlow
        mf = MicroFlow()
        mf.symbol = "BTCTRY"
        mf.ws_updated_at = time.time()
        mf.bars["1s"]["BTCTRY"].update({
            "timestamps": [i * 1000 for i in range(len(closes))],
            "opens": list(closes), "highs": list(closes), "lows": list(closes),
            "closes": list(closes), "volumes": [1.0] * len(closes),
        })
        return mf

    def test_ret_1s_is_actually_a_one_second_return(self):
        mf = self._mf_with_1s_bars([100.0, 105.0, 110.0])
        snap = mf.get_snapshot(price=110.0)
        # Eski hâl closes[-3]=100 → %10 (2 saniyelik getiri) raporlanıyordu.
        self.assertAlmostEqual(4.7619, snap["bars"]["1s"]["ret_1s_pct"], places=3)

    def test_ret_1s_available_with_only_two_bars(self):
        mf = self._mf_with_1s_bars([100.0, 110.0])
        snap = mf.get_snapshot(price=110.0)
        self.assertAlmostEqual(10.0, snap["bars"]["1s"]["ret_1s_pct"], places=3)

    def test_sample_span_is_the_trade_span_not_the_window_age(self):
        from collections import deque
        from app.microflow import MicroFlow

        mf = MicroFlow()
        mf.symbol = "BTCTRY"
        mf.ws_updated_at = time.time()
        mf.bars["1s"]["BTCTRY"].update({
            "timestamps": [0, 1000, 2000], "opens": [100.0] * 3, "highs": [100.0] * 3,
            "lows": [100.0] * 3, "closes": [100.0] * 3, "volumes": [1.0] * 3,
        })
        now_ms = int(time.time() * 1000)
        bucket = mf.trade_flow["BTCTRY"]
        bucket["window_start"] = time.time() - 600.0     # pencere 10 dakikalık
        bucket["_tape"] = deque(
            ({"t": now_ms - 29_000 + i * 1_000, "p": 100.0, "q": 1.0, "m": False}
             for i in range(30)), maxlen=2000)
        snap = mf.get_snapshot(price=100.0)
        # Eski hâl: pencere YAŞI (≈600 sn) raporlanıyordu.
        self.assertAlmostEqual(29.0, snap["slippage"]["sample_span_sec"], places=1)


if __name__ == "__main__":
    unittest.main()
