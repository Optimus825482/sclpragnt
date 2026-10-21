"""2026-10-21: Radar > "H4 kesişimleri" — son 24 saatte H4 MA 7/20/99 kesişimi olan likit çiftlerin taraması (app/ma_buy_h4_scan.py)."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import ma_buy_h4_scan as scan_mod, ma_buy_signals
from app.config import config

H4 = 14_400_000


def _bars(closes, start_ms=0):
    return [{"open_ms": start_ms + i * H4, "close_ms": start_ms + (i + 1) * H4 - 1, "open": c, "high": c, "low": c, "close": c}
            for i, c in enumerate(closes)]


def _cross_series():
    """Uzun düşüş + sert dönüş: SMA 7/20/99 ile tek kesişim, 120. mumda (orta×yavaş)."""
    return [100.0 - i * 0.05 for i in range(110)] + [94.5 + i * 0.9 for i in range(30)]


CROSS_INDEX = 120
CROSS_CLOSE_MS = (CROSS_INDEX + 1) * H4     # sinyal mumunun kapanışı (satırdaki bar_close_ms)


def _settings(**over):
    base = {"periods": (7, 20, 99), "rules": tuple(ma_buy_signals.ALL_RULES), "ma_type": "sma", "min_body_pct": 0.0,
            "stoch_max": None, "profile": "ma_buy_h4", "stop_loss_pct": 8.0, "max_hold_minutes": 4320.0,
            "require_mid_above_slow": True}
    base.update(over)
    return base


class CrossesFromBarsTests(unittest.TestCase):
    def test_only_bars_closed_within_window_are_returned(self):
        bars = _bars(_cross_series())
        all_hits = scan_mod.crosses_from_bars("ATRY", bars, now_ms=bars[-1]["close_ms"] + 1, hours=24 * 365, settings=_settings())
        self.assertEqual([h["bar_close_ms"] for h in all_hits], [CROSS_CLOSE_MS])
        # Kesişim mumu kapanalı 24 saatten az → listede
        recent = scan_mod.crosses_from_bars("ATRY", bars, now_ms=CROSS_CLOSE_MS + 23 * 3_600_000, hours=24, settings=_settings())
        self.assertEqual([h["bar_close_ms"] for h in recent], [CROSS_CLOSE_MS])
        self.assertEqual(recent[0]["rules"], "mid_cross_slow")
        # 24 saatten eski → düşer (pencere kapanış zamanına göre)
        self.assertEqual(scan_mod.crosses_from_bars("ATRY", bars, now_ms=CROSS_CLOSE_MS + 24 * 3_600_000 + 2, hours=24,
                                                    settings=_settings()), [])
        # Daha geniş pencere yine bulur
        self.assertEqual(len(scan_mod.crosses_from_bars("ATRY", bars, now_ms=CROSS_CLOSE_MS + 30 * 3_600_000, hours=48,
                                                        settings=_settings())), 1)

    def test_default_settings_follow_h4_profile(self):
        st = scan_mod.signal_settings()
        self.assertEqual(st["periods"], (7, 20, 99))
        self.assertEqual(st["rules"], (ma_buy_signals.RULE_FAST_CROSS_MID,))
        self.assertFalse(st["require_mid_above_slow"])
        self.assertEqual(st["profile"], "ma_buy_h4")

    def test_merge_tracker_rows_marks_notified_and_paper(self):
        items = [{"symbol": "ATRY", "bar_open_ms": 100}, {"symbol": "BTRY", "bar_open_ms": 100}]
        tracked = [{"symbol": "atry", "timeframe": "4h", "bar_open_ms": 100, "push_ok": True, "notified_at": 5.0,
                    "paper_status": "acildi", "paper_trade_id": 9},
                   {"symbol": "BTRY", "timeframe": "1h", "bar_open_ms": 100, "push_ok": True}]   # başka TF → sayılmaz
        out = scan_mod.merge_tracker_rows(items, tracked)
        self.assertTrue(out[0]["tracked"] and out[0]["notified"] and out[0]["paper_status"] == "acildi" and out[0]["paper_trade_id"] == 9)
        self.assertFalse(out[1]["tracked"] or out[1]["notified"])
        self.assertIsNone(out[1]["paper_status"])


class ScanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        scan_mod.reset_cache()

    async def test_scan_joins_ticker_and_tracker_rows_and_sorts_newest_first(self):
        closes = _cross_series()
        last_close = CROSS_CLOSE_MS + 10 * 300_000 + 5_000   # "şimdi" = kesişimden 50 dk sonra (10 adet 5 dk mum kapandı)
        raw = [[i * H4, c, c, c, c, "1", (i + 1) * H4 - 1] for i, c in enumerate(closes)]
        flat = [[i * H4, 1, 1, 1, 1, "1", (i + 1) * H4 - 1] for i in range(len(closes))]

        m5 = [[CROSS_CLOSE_MS + i * 300_000, 100, 100 + (12 if i == 7 else 2), 99, 100 + (6 if i == 7 else 1), "1",
               CROSS_CLOSE_MS + (i + 1) * 300_000 - 1] for i in range(10)]   # zirve 8. mumda (high 112), son kapanış 101

        async def fake_klines(symbol, tf, limit, start_time_ms=None):
            if tf == "5m":
                self.assertEqual(start_time_ms, CROSS_CLOSE_MS)
                return m5
            self.assertEqual((tf, limit), ("4h", scan_mod.FETCH_LIMIT))
            if symbol == "ERRTRY":
                raise RuntimeError("ağ")
            return raw if symbol == "ATRY" else flat

        uni = [{"symbol": "ATRY", "quoteVolume": 5e6, "priceChangePercent": 3.5, "lastPrice": 121.0},
               {"symbol": "FLATTRY", "quoteVolume": 2e6, "priceChangePercent": 0.0, "lastPrice": 1.0},
               {"symbol": "ERRTRY", "quoteVolume": 1e6, "priceChangePercent": 0.0, "lastPrice": 1.0}]
        tracked = [{"symbol": "ATRY", "timeframe": "4h", "bar_open_ms": CROSS_INDEX * H4, "push_ok": True, "paper_status": "acildi"}]
        with patch.object(scan_mod, "universe", AsyncMock(return_value=uni)), \
             patch.object(scan_mod, "fetch_klines", fake_klines), \
             patch.object(scan_mod, "signal_settings", lambda: _settings(require_mid_above_slow=False)), \
             patch.object(scan_mod.database, "list_ma_buy_signals", AsyncMock(return_value=tracked)) as q:
            snap = await scan_mod.scan(now_ms=last_close + 1, hours=24)
        self.assertEqual(snap["symbols_scanned"], 3)
        self.assertEqual(snap["errors"], 1)
        self.assertEqual(snap["rule"]["periods"], [7, 20, 99])
        self.assertEqual([(it["symbol"], it["bar_close_ms"]) for it in snap["items"]], [("ATRY", CROSS_CLOSE_MS)])
        it = snap["items"][0]
        self.assertEqual(it["rules"], ["mid_cross_slow"])
        self.assertEqual(it["change_24h_pct"], 3.5)
        self.assertEqual(it["quote_volume_24h"], 5e6)
        self.assertEqual(it["target_pct"], 10.0)
        self.assertEqual(it["stop_loss_pct"], 8.0)
        self.assertEqual(it["ma_label"], "SMA 7/20/99")
        self.assertTrue(it["tracked"] and it["notified"] and it["paper_status"] == "acildi")
        # Zirve ölçümü (5 dk mumlar): sinyal fiyatına göre
        sp = it["signal_price"]
        self.assertAlmostEqual(it["max_rise_pct"], (112 / sp - 1) * 100, places=3)
        self.assertEqual(it["max_rise_price"], 112)
        self.assertEqual(it["minutes_to_max"], 40.0)                         # 8. mumun kapanışı = 40 dk
        self.assertEqual(it["max_rise_at_ms"], CROSS_CLOSE_MS + 8 * 300_000)
        self.assertAlmostEqual(it["max_drop_pct"], (99 / sp - 1) * 100, places=3)
        self.assertAlmostEqual(it["now_pct"], (101 / sp - 1) * 100, places=3)
        self.assertEqual(it["bars_after"], 10)
        self.assertFalse(snap["rule"]["require_mid_above_slow"])
        # İzleyici kaydı 24 sa + bir H4 mumu geriden okunur
        self.assertLessEqual(q.await_args.args[0], last_close + 1 - 24 * 3_600_000 - H4)

    async def test_snapshot_returns_cache_and_refreshes_in_background_once(self):
        calls = []

        async def fake_scan(hours=24, now_ms=None):
            calls.append(hours)
            await asyncio.sleep(0)
            return {"scanned_at": 1e9, "hours": hours, "symbols_scanned": 1, "errors": 0, "min_quote_volume": 1e6,
                    "rule": {}, "items": [{"symbol": "ATRY"}]}

        with patch.object(scan_mod, "scan", fake_scan), patch.object(scan_mod.time, "time", lambda: 1e9 + 5):
            first = await scan_mod.snapshot(hours=24)
            self.assertEqual(first["items"], [])
            self.assertTrue(first["refreshing"])
            second = await scan_mod.snapshot(hours=24)        # tazeleme sürerken ikinci görev başlamaz
            self.assertTrue(second["refreshing"])
            await scan_mod._cache["task"]
            third = await scan_mod.snapshot(hours=24)
            self.assertEqual(third["items"], [{"symbol": "ATRY"}])
            self.assertFalse(third["refreshing"])
        self.assertEqual(calls, [24])

    async def test_snapshot_force_and_stale_trigger_refresh(self):
        async def fake_scan(hours=24, now_ms=None):
            return {"scanned_at": scan_mod.time.time(), "hours": hours, "symbols_scanned": 0, "errors": 0,
                    "min_quote_volume": 0, "rule": {}, "items": []}

        with patch.object(scan_mod, "scan", fake_scan):
            await scan_mod.snapshot()
            await scan_mod._cache["task"]
            fresh = await scan_mod.snapshot()
            self.assertFalse(fresh["refreshing"])
            forced = await scan_mod.snapshot(force=True)
            self.assertTrue(forced["refreshing"])
            await scan_mod._cache["task"]
            scan_mod._cache["snapshot"]["scanned_at"] -= scan_mod.ttl_sec() + 1
            stale = await scan_mod.snapshot()
            self.assertTrue(stale["refreshing"])
            await scan_mod._cache["task"]

    async def test_refresh_failure_is_recorded_not_raised(self):
        async def boom(hours=24, now_ms=None):
            raise RuntimeError("borsa")

        with patch.object(scan_mod, "scan", boom):
            await scan_mod.snapshot()
            await scan_mod._cache["task"]
            out = await scan_mod.snapshot()
        self.assertIn("borsa", out["last_error"])

    async def test_universe_filters_by_volume_and_trading_status(self):
        rows = [{"symbol": "ATRY", "quoteVolume": "2000000", "priceChangePercent": "1", "lastPrice": "2"},
                {"symbol": "LOWTRY", "quoteVolume": "10", "priceChangePercent": "1", "lastPrice": "2"},
                {"symbol": "DEADTRY", "quoteVolume": "9000000", "priceChangePercent": "1", "lastPrice": "2"},
                {"symbol": "BTCUSDT", "quoteVolume": "9000000", "priceChangePercent": "1", "lastPrice": "2"}]
        with patch.object(scan_mod, "ticker_24h", AsyncMock(return_value=rows)), \
             patch.object(scan_mod, "trading_symbols", AsyncMock(return_value=["ATRY", "LOWTRY"])), \
             patch.object(config, "MA_BUY_H4_MIN_QUOTE_VOLUME", 1_000_000.0, create=True):
            uni = await scan_mod.universe()
        self.assertEqual([u["symbol"] for u in uni], ["ATRY"])

    async def test_universe_default_floor_is_5m_and_matches_profile(self):
        self.assertEqual(scan_mod.min_quote_volume(), 5_000_000.0)
        rows = [{"symbol": "ATRY", "quoteVolume": "4999999", "priceChangePercent": "1", "lastPrice": "2"},
                {"symbol": "BTRY", "quoteVolume": "5000000", "priceChangePercent": "1", "lastPrice": "2"}]
        with patch.object(scan_mod, "ticker_24h", AsyncMock(return_value=rows)), \
             patch.object(scan_mod, "trading_symbols", AsyncMock(return_value=["ATRY", "BTRY"])):
            uni = await scan_mod.universe()
        self.assertEqual([u["symbol"] for u in uni], ["BTRY"])

    def test_route_registered(self):
        from app.main import app
        self.assertIn("/api/ma-buy/h4-crosses", app.openapi()["paths"])


if __name__ == "__main__":
    unittest.main()


class WarmupTests(unittest.TestCase):
    def test_seconds_until_next_bar_close_targets_next_h4_boundary_plus_grace(self):
        # 10:00 UTC → sonraki kapanış 12:00; 7200 sn + 90 pay
        self.assertEqual(scan_mod.seconds_until_next_bar_close(10 * 3_600_000, grace_sec=90), 7200 + 90)
        self.assertEqual(scan_mod.seconds_until_next_bar_close(12 * 3_600_000 - 1_000, grace_sec=0), 1.0)

    def test_warmup_loop_registered_in_main(self):
        import inspect
        from app import main
        src = inspect.getsource(main)
        self.assertIn("_start_background(h4_scan_warmup_loop", src)


class PeakMetricsTests(unittest.TestCase):
    def test_peak_metrics_empty_and_basic(self):
        empty = scan_mod.peak_metrics(10.0, 1_000_000, [], now_ms=1_000_000 + 120_000)
        self.assertIsNone(empty["max_rise_pct"]) and self.assertEqual(empty["bars_after"], 0)
        self.assertEqual(empty["elapsed_minutes"], 2.0)
        bars = [{"open_ms": 1_000_000 + i * 300_000, "high": h, "low": l, "close": c}
                for i, (h, l, c) in enumerate([(10.5, 9.9, 10.2), (11.0, 10.0, 10.8), (11.0, 10.5, 10.6), (10.7, 9.5, 9.6)])]
        m = scan_mod.peak_metrics(10.0, 1_000_000, bars, now_ms=1_000_000 + 4 * 300_000)
        self.assertEqual(m["max_rise_pct"], 10.0)
        self.assertEqual(m["max_rise_at_ms"], 1_000_000 + 2 * 300_000)       # eşit zirvede İLK mum (2.)
        self.assertEqual(m["minutes_to_max"], 10.0)
        self.assertEqual(m["max_drop_pct"], -5.0)
        self.assertEqual(m["now_pct"], -4.0)
        self.assertEqual(m["bars_after"], 4)

    def test_peak_metrics_ignores_bars_before_signal_close(self):
        bars = [{"open_ms": 500_000, "high": 99.0, "low": 1.0, "close": 50.0}, {"open_ms": 1_000_000, "high": 11.0, "low": 10.0, "close": 10.5}]
        m = scan_mod.peak_metrics(10.0, 1_000_000, bars, now_ms=2_000_000)
        self.assertEqual(m["max_rise_pct"], 10.0) and self.assertEqual(m["bars_after"], 1)

    def test_attach_peaks_survives_fetch_error(self):
        async def run():
            async def boom(*a, **k):
                raise RuntimeError("ağ")
            items = [{"symbol": "ATRY", "signal_price": 10.0, "bar_close_ms": 1_000_000}]
            with patch.object(scan_mod, "fetch_klines", boom):
                errors = await scan_mod.attach_peaks(items, now_ms=2_000_000)
            return errors, items[0]
        errors, it = asyncio.run(run())
        self.assertEqual(errors, 1)
        self.assertTrue(it["peak_error"]) and self.assertIsNone(it["max_rise_pct"])
