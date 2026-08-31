import pathlib
import sys
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _trade(ts_ms, price, qty, buyer_maker=False):
    return {"t": ts_ms, "p": price, "q": qty, "m": buyer_maker}


class WhaleActivityClassifierTests(unittest.TestCase):
    def test_whale_buy_holding_price_classified_as_accumulation(self):
        from app.market_intelligence import classify_whale_trade

        base = 100_000_000  # arbitrary ms base
        tape = [
            _trade(base - 10_000, 100.0, 1.0),
            _trade(base - 5_000, 100.0, 0.5),
            # Whale buy 100.0 * 300 = 30k TRY (>= 25k threshold)
            _trade(base, 100.0, 300.0, buyer_maker=False),
            _trade(base + 1_000, 100.12, 2.0),
            _trade(base + 2_000, 100.15, 1.5),
            _trade(base + 4_000, 100.10, 1.0),
        ]
        result = classify_whale_trade(_trade(base, 100.0, 300.0, buyer_maker=False), tape)
        self.assertEqual(result["verdict"], "accumulation")
        self.assertGreaterEqual(result["impact_pct"], 0.10)
        self.assertEqual(result["side"], "buy")
        self.assertEqual(result["notional_try"], 30_000.0)

    def test_whale_buy_giving_back_price_classified_as_distribution(self):
        from app.market_intelligence import classify_whale_trade

        base = 200_000_000
        tape = [
            _trade(base - 10_000, 100.0, 1.0),
            _trade(base - 5_000, 100.0, 0.5),
            _trade(base, 100.0, 300.0, buyer_maker=False),  # whale buy
            _trade(base + 1_000, 99.88, 2.0),
            _trade(base + 2_000, 99.85, 1.5),
            _trade(base + 4_000, 99.82, 1.0),
        ]
        result = classify_whale_trade(_trade(base, 100.0, 300.0, buyer_maker=False), tape)
        self.assertEqual(result["verdict"], "distribution")
        self.assertLessEqual(result["impact_pct"], -0.10)

    def test_whale_sell_driving_price_down_classified_as_distribution(self):
        from app.market_intelligence import classify_whale_trade

        base = 300_000_000
        tape = [
            _trade(base - 10_000, 100.0, 1.0),
            _trade(base - 5_000, 100.0, 0.5),
            _trade(base, 100.0, 300.0, buyer_maker=True),  # whale sell
            _trade(base + 1_000, 99.88, 2.0),
            _trade(base + 2_000, 99.85, 1.5),
            _trade(base + 4_000, 99.82, 1.0),
        ]
        result = classify_whale_trade(_trade(base, 100.0, 300.0, buyer_maker=True), tape)
        self.assertEqual(result["verdict"], "distribution")
        self.assertEqual(result["side"], "sell")

    def test_no_impact_window_returns_unknown(self):
        from app.market_intelligence import classify_whale_trade

        base = 400_000_000
        tape = [_trade(base - 10_000, 100.0, 1.0), _trade(base, 100.0, 300.0, buyer_maker=False)]
        result = classify_whale_trade(_trade(base, 100.0, 300.0, buyer_maker=False), tape)
        self.assertEqual(result["verdict"], "unknown")

    def test_whale_activity_summary_filters_by_threshold(self):
        from app.market_intelligence import whale_activity_from_tape

        base = 500_000_000
        tape = [
            _trade(base - 20_000, 100.0, 1.0),
            _trade(base - 10_000, 100.0, 0.5),
            # whale buy 30k, price holds up
            _trade(base, 100.0, 300.0, buyer_maker=False),
            _trade(base + 1_000, 100.12, 2.0),
            _trade(base + 2_000, 100.15, 1.5),
            # small trade 10k (below 25k) must NOT be counted as whale
            _trade(base + 3_000, 100.15, 100.0, buyer_maker=True),
            # whale sell 30k, price drops
            _trade(base + 4_000, 100.15, 300.0, buyer_maker=True),
            _trade(base + 5_000, 99.88, 2.0),
            _trade(base + 6_000, 99.85, 1.5),
        ]
        result = whale_activity_from_tape(tape, whale_threshold_try=25_000.0, limit=8)
        self.assertEqual(result["whale_count"], 2)
        self.assertEqual(result["accumulation"], 1)
        self.assertEqual(result["distribution"], 1)
        self.assertEqual(result["verdict"], "mixed")
        self.assertEqual(result["net_direction"], "neutral")

    def test_empty_tape_returns_no_whale(self):
        from app.market_intelligence import whale_activity_from_tape

        result = whale_activity_from_tape([], whale_threshold_try=25_000.0)
        self.assertEqual(result["verdict"], "no_whale")
        self.assertEqual(result["whale_count"], 0)


class MarketDataWhaleTests(unittest.IsolatedAsyncioTestCase):
    def test_get_microstructure_includes_whale_activity(self):
        from app.market_data import MarketData

        market = MarketData(["BTCTRY"])
        now_ms = int(time.time() * 1000)
        # Warm the orderbook so microstructure has a spread.
        market.orderflow["BTCTRY"].update({
            "bid_price": 99.5, "ask_price": 100.5, "bid_qty": 20.0, "ask_qty": 20.0,
            "spread_pct": 1.0, "updated_at": time.time(),
        })
        # A whale-sized buy (30k TRY) followed by higher prices → accumulation.
        # Referans fiyat için whale'den önce bir trade olmalı (tape akış başı).
        market._process_ws_message({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100", "q": "1",
            "m": False, "T": now_ms - 20_000, "E": now_ms - 20_000}})
        market._process_ws_message({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100", "q": "300",
            "m": False, "T": now_ms - 10_000, "E": now_ms - 10_000}})
        market._process_ws_message({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100.12", "q": "2",
            "m": False, "T": now_ms - 8_000, "E": now_ms - 8_000}})
        market._process_ws_message({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100.15", "q": "1.5",
            "m": False, "T": now_ms - 6_000, "E": now_ms - 6_000}})
        ms = market.get_microstructure("BTCTRY", 100.0)
        activity = ms["trade_flow"]["whale_activity"]
        self.assertEqual(activity["verdict"], "accumulation")
        self.assertEqual(activity["whale_count"], 1)
        self.assertEqual(ms["trade_flow"]["whale_buys"], 1)


class MicroFlowWhaleTests(unittest.TestCase):
    def test_get_snapshot_includes_whale_activity(self):
        from app.microflow import MicroFlow

        mf = MicroFlow()
        mf.symbol = "BTCTRY"
        now_ms = int(time.time() * 1000)
        mf._handle({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100", "q": "1",
            "m": False, "T": now_ms - 20_000, "E": now_ms - 20_000}})
        mf._handle({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100", "q": "300",
            "m": False, "T": now_ms - 10_000, "E": now_ms - 10_000}})
        mf._handle({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100.12", "q": "2",
            "m": False, "T": now_ms - 8_000, "E": now_ms - 8_000}})
        snap = mf.get_snapshot(price=100.0)
        activity = snap["trade_flow"]["whale_activity"]
        self.assertEqual(activity["verdict"], "accumulation")
        self.assertEqual(activity["whale_count"], 1)

    def test_roll_reset_keeps_tape(self):
        from app.microflow import MicroFlow

        mf = MicroFlow()
        mf.symbol = "BTCTRY"
        now_ms = int(time.time() * 1000)
        mf._handle({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100", "q": "300",
            "m": False, "T": now_ms - 70_000, "E": now_ms - 70_000}})
        bucket = mf.trade_flow["BTCTRY"]
        # Force window rollover by aging window_start.
        bucket["window_start"] = time.time() - 61
        mf._handle({"stream": "btctry@aggTrade", "data": {
            "e": "aggTrade", "s": "BTCTRY", "p": "100.05", "q": "1",
            "m": False, "T": now_ms, "E": now_ms}})
        self.assertTrue(bucket.get("_tape"))
        self.assertEqual(bucket["buy_count"], 1)  # counters reset, tape kept


if __name__ == "__main__":
    unittest.main()
