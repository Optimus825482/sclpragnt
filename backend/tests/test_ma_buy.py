"""MA şerit BUY sinyal kaydı testleri — DB'siz, ağsız (2026-10-18)."""
import json
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ma_buy_signals, ma_buy_tracker  # noqa: E402

TF = 300_000
BASE = 1_700_000_100_000   # 5 dk sınırına hizalı


def _kline(i, close, high=None, low=None, base=BASE):
    open_ms = base + i * TF
    return [open_ms, str(close), str(high if high is not None else close), str(low if low is not None else close),
            str(close), "1", open_ms + TF - 1]


def _fixture():
    return json.loads((ROOT / "tests" / "fixtures" / "ma_buy_parity.json").read_text(encoding="utf-8"))


class PureSignalTests(unittest.TestCase):
    def test_ema_seed_and_sma(self):
        self.assertEqual(ma_buy_signals.ema_series([1, 2, 3, 4], 3)[:2], [None, None])
        self.assertAlmostEqual(ma_buy_signals.ema_series([1, 2, 3, 4], 3)[2], 2.0)
        self.assertEqual(ma_buy_signals.sma_series([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_float_noise_is_not_a_cross(self):
        # 2.950000000000003 ile 2.9499999999999984 aynı değerdir; kesişim sayılmaz, sonraki gerçek yükseliş sayılır.
        self.assertFalse(ma_buy_signals._cross_up(2.9442857142857, 2.9495, 2.950000000000003, 2.9499999999999984))
        self.assertTrue(ma_buy_signals._cross_up(2.95, 2.95, 2.9557, 2.951))

    def test_parity_fixture_matches_detector(self):
        fx = _fixture()
        for case in fx["cases"]:
            got = ma_buy_signals.detect_ma_buy(fx["closes"], tuple(case["periods"]), case["use_sma"], case["slow_cross"], case["stoch_max"])
            self.assertEqual([{"index": g["index"], "rules": g["rules"]} for g in got], case["signals"])
        rules = {r for c in fx["cases"] for s in c["signals"] for r in s["rules"]}
        self.assertEqual(rules, set(ma_buy_signals.ALL_RULES))

    def test_slow_cross_off_leaves_only_fast_cross_mid(self):
        got = ma_buy_signals.detect_ma_buy(_fixture()["closes"], (7, 20, 99), False, False, None)
        self.assertTrue(got)
        self.assertTrue(all(g["rules"] == [ma_buy_signals.RULE_FAST_CROSS_MID] for g in got))

    def test_outcome_metrics(self):
        bars = [{"high": 101.0, "low": 99.5, "close": 100.5}, {"high": 103.0, "low": 100.0, "close": 102.0},
                {"high": 102.0, "low": 98.0, "close": 99.0}]
        m = ma_buy_signals.outcome_metrics(100.0, bars, 5)
        self.assertEqual(m["max_rise_5m_pct"], 1.0)
        self.assertEqual(m["max_rise_10m_pct"], 3.0)
        self.assertEqual(m["max_rise_15m_pct"], 3.0)
        self.assertEqual(m["max_drop_15m_pct"], -2.0)
        self.assertEqual(m["close_15m_pct"], -1.0)
        self.assertEqual(m["peak_bar_minutes"], 10)
        self.assertIsNone(ma_buy_signals.outcome_metrics(100.0, bars[:2], 5))


class StochCapTests(unittest.TestCase):
    def test_second_rule_blocked_when_stoch_k_above_cap(self):
        closes = _fixture()["closes"]
        free = ma_buy_signals.detect_ma_buy(closes, (7, 20, 99), False, True, None)
        capped = ma_buy_signals.detect_ma_buy(closes, (7, 20, 99), False, True, 80.0)
        k = ma_buy_signals.stoch_rsi_k(closes)
        dropped = [h for h in free if ma_buy_signals.RULE_MID_CROSS_SLOW in h["rules"]
                   and h["index"] not in {c["index"] for c in capped if ma_buy_signals.RULE_MID_CROSS_SLOW in c["rules"]}]
        for h in dropped:
            self.assertGreater(k[h["index"]], 80.0)
        # 1. kural stoch'tan etkilenmez
        fast_free = [h["index"] for h in free if ma_buy_signals.RULE_FAST_CROSS_MID in h["rules"]]
        fast_cap = [h["index"] for h in capped if ma_buy_signals.RULE_FAST_CROSS_MID in h["rules"]]
        self.assertEqual(fast_free, fast_cap)

    def test_stoch_rsi_k_range_and_warmup(self):
        closes = _fixture()["closes"]
        k = ma_buy_signals.stoch_rsi_k(closes)
        self.assertTrue(all(v is None for v in k[:16]))
        vals = [v for v in k if v is not None]
        self.assertTrue(vals and all(-1e-9 <= v <= 100 + 1e-9 for v in vals))


class TrackerPureTests(unittest.TestCase):
    def test_closed_bars_drops_open_bar_and_dupes(self):
        now = BASE + 3 * TF + 10_000
        rows = [_kline(0, 1), _kline(1, 2), _kline(1, 2), _kline(2, 3), _kline(3, 4), ["bad"]]
        bars = ma_buy_tracker.closed_bars(rows, TF, now)
        self.assertEqual([b["close"] for b in bars], [1.0, 2.0, 3.0])

    def test_due_bar_open_is_last_closed(self):
        self.assertEqual(ma_buy_tracker.due_bar_open(BASE + 10 * TF + 5_000, TF), BASE + 9 * TF)

    def test_summarize_and_public_item(self):
        items = [
            {"status": "done", "rules": "fast_cross_mid", "max_rise_15m_pct": 2.0, "max_drop_15m_pct": -0.5, "close_15m_pct": 1.0},
            {"status": "done", "rules": "mid_cross_slow", "max_rise_15m_pct": 0.5, "max_drop_15m_pct": -1.5, "close_15m_pct": -0.2},
            {"status": "open", "rules": "fast_cross_mid,mid_cross_slow"},
        ]
        s = ma_buy_tracker.summarize(items)
        self.assertEqual((s["count"], s["evaluated"], s["pending"]), (3, 2, 1))
        self.assertAlmostEqual(s["avg_max_rise_15m_pct"], 1.25)
        self.assertEqual(s["by_rule"]["fast_cross_mid"]["count"], 2)
        self.assertEqual(s["by_rule"]["mid_cross_slow"]["evaluated"], 1)
        hit = {t["min_pct"]: t["n"] for t in s["thresholds"]}
        self.assertEqual(hit[1.0], 1)
        self.assertEqual(ma_buy_tracker.public_item(items[2])["rules"], ["fast_cross_mid", "mid_cross_slow"])
        self.assertIsNone(ma_buy_tracker.summarize([])["avg_max_rise_15m_pct"])


class TrackerFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ma_buy_tracker._state.update({"seen": {}, "last_error": None})

    async def test_scan_inserts_recent_signal_once(self):
        fx = _fixture()
        closes = fx["closes"]
        last = 565            # EMA 7/20/99 fast_cross_mid (fixture ile doğrulanır)
        self.assertIn(last, [s["index"] for s in fx["cases"][0]["signals"]])
        now = BASE + (last + 2) * TF + 5_000
        rows = [_kline(i, c) for i, c in enumerate(closes[: last + 2])]
        inserted_rows = []

        async def fake_insert(rs):
            inserted_rows.extend(rs)
            return len(rs)

        with patch.object(ma_buy_tracker, "fetch_klines", AsyncMock(return_value=rows)), \
             patch.object(ma_buy_tracker.database, "insert_ma_buy_signals", side_effect=fake_insert), \
             patch.object(ma_buy_tracker, "active_symbols", AsyncMock(return_value=["ABCTRY"])):
            out = await ma_buy_tracker.scan_once(now)
            self.assertEqual((out["symbols"], out["errors"]), (1, 0))
            self.assertIn(BASE + last * TF, [r["bar_open_ms"] for r in inserted_rows])
            self.assertTrue(all(r["symbol"] == "ABCTRY" and r["timeframe"] == "5m" for r in inserted_rows))
            n = len(inserted_rows)
            await ma_buy_tracker.scan_once(now + 1_000)
            self.assertEqual(len(inserted_rows), n)

    async def test_scan_isolates_symbol_errors(self):
        async def boom(symbol, tf, limit=0, **kw):
            if symbol == "BADTRY":
                raise RuntimeError("ağ")
            return []

        with patch.object(ma_buy_tracker, "fetch_klines", side_effect=boom), \
             patch.object(ma_buy_tracker, "active_symbols", AsyncMock(return_value=["BADTRY", "OKTRY"])):
            out = await ma_buy_tracker.scan_once(BASE + 100 * TF)
        self.assertEqual(out["errors"], 1)
        self.assertIn("BADTRY", ma_buy_tracker.status_snapshot()["last_error"])

    async def test_evaluate_writes_done_and_waits_when_not_due(self):
        due_row = {"id": 1, "symbol": "ABCTRY", "timeframe": "5m", "bar_open_ms": BASE, "bar_close_ms": BASE + TF,
                   "signal_price": 100.0}
        young_row = {"id": 2, "symbol": "ABCTRY", "timeframe": "5m", "bar_open_ms": BASE + 10 * TF,
                     "bar_close_ms": BASE + 11 * TF, "signal_price": 100.0}
        after = [_kline(1, 100.5, 101.0, 99.5), _kline(2, 102.0, 103.0, 100.0), _kline(3, 99.0, 102.0, 98.0)]
        now = BASE + 4 * TF + 15 * 60_000 + 10_000
        upd = AsyncMock(return_value=True)
        with patch.object(ma_buy_tracker.database, "list_ma_buy_open", AsyncMock(return_value=[due_row, young_row])), \
             patch.object(ma_buy_tracker.database, "update_ma_buy_outcome", upd), \
             patch.object(ma_buy_tracker, "fetch_klines", AsyncMock(return_value=after)):
            done = await ma_buy_tracker.evaluate_once(now)
        self.assertEqual(done, 1)
        upd.assert_awaited_once()
        args, kwargs = upd.await_args
        self.assertEqual(args[0], 1)
        self.assertEqual(kwargs["status"], "done")
        self.assertEqual(args[1]["max_rise_15m_pct"], 3.0)

    async def test_evaluate_marks_no_data_after_six_hours(self):
        row = {"id": 9, "symbol": "ABCTRY", "timeframe": "5m", "bar_open_ms": BASE, "bar_close_ms": BASE + TF,
               "signal_price": 100.0}
        upd = AsyncMock(return_value=True)
        now = BASE + TF + 15 * 60_000 + ma_buy_tracker.NO_DATA_AFTER_MS + 60_000
        with patch.object(ma_buy_tracker.database, "list_ma_buy_open", AsyncMock(return_value=[row])), \
             patch.object(ma_buy_tracker.database, "update_ma_buy_outcome", upd), \
             patch.object(ma_buy_tracker, "fetch_klines", AsyncMock(return_value=[])):
            await ma_buy_tracker.evaluate_once(now)
        self.assertEqual(upd.await_args.kwargs["status"], "no_data")

    async def test_active_symbols_prefers_active_status(self):
        raw = json.dumps({"AAATRY": {"status": "ACTIVE"}, "BBBTRY": {"status": "PASSIVE"}})
        with patch.object(ma_buy_tracker.database, "get_llm_setting", AsyncMock(return_value=raw)), \
             patch.object(ma_buy_tracker.config, "MA_BUY_SYMBOL_SCOPE", "active", create=True):
            self.assertEqual(await ma_buy_tracker.active_symbols(), ["AAATRY"])


class RouterAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_admin(self):
        from fastapi import HTTPException
        from app.routers import ma_buy
        with patch("app.main._require_admin", side_effect=HTTPException(status_code=403, detail="admin")):
            with self.assertRaises(HTTPException) as cm:
                await ma_buy.list_ma_buy_signals(MagicMock(), days=7, symbol="", rule="", status="", limit=10)
        self.assertEqual(cm.exception.status_code, 403)

    async def test_lists_items_and_summary(self):
        from app.routers import ma_buy
        rows = [{"id": 1, "symbol": "AAATRY", "timeframe": "5m", "bar_open_ms": 1, "bar_close_ms": 2, "detected_at": 1.0,
                 "rules": "fast_cross_mid", "signal_price": 1.0, "status": "done", "max_rise_15m_pct": 2.0,
                 "max_drop_15m_pct": -1.0, "close_15m_pct": 0.5, "eval_attempts": 1},
                {"id": 2, "symbol": "BBBTRY", "timeframe": "5m", "bar_open_ms": 3, "bar_close_ms": 4, "detected_at": 1.0,
                 "rules": "mid_cross_slow", "signal_price": 1.0, "status": "open", "eval_attempts": 0}]
        with patch("app.main._require_admin", return_value={"role": "admin"}), \
             patch.object(ma_buy.database, "list_ma_buy_signals", AsyncMock(return_value=rows)):
            out = await ma_buy.list_ma_buy_signals(MagicMock(), days=7, symbol="", rule="mid_cross_slow", status="", limit=10)
        self.assertTrue(out["ok"])
        self.assertEqual([i["symbol"] for i in out["items"]], ["BBBTRY"])
        self.assertEqual(out["items"][0]["rules"], ["mid_cross_slow"])
        self.assertEqual(out["summary"]["count"], 1)
        self.assertIn("tracker", out)

    def test_route_registered(self):
        from app.main import app
        # include_router ile eklenen yollar `app.routes` içinde düz görünmez; OpenAPI şeması kesin kaynak.
        self.assertIn("/api/admin/ma-buy-signals", app.openapi()["paths"])


if __name__ == "__main__":
    unittest.main()
