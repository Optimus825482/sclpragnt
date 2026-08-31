import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _trade(ts_ms, price, qty, buyer_maker=False):
    return {"t": ts_ms, "p": price, "q": qty, "m": buyer_maker}


class VelocityMicrostructureFilterTests(unittest.IsolatedAsyncioTestCase):
    async def test_whale_distribution_filter_blocks_entry_when_enabled(self):
        from app.microflow import microflow
        from app.routers.velocity import _open_velocity_position
        from app.config import config

        symbol = "BTCTRY"
        # Microflow tape'ini whale dağıtım sinyali üretecek şekilde doldur:
        # whale buy sonrası fiyat geri veriliyor → distribution.
        now_ms = int(time.time() * 1000)
        microflow.symbol = symbol
        microflow.trade_flow[symbol] = microflow.trade_flow[symbol]  # touch
        bucket = microflow.trade_flow[symbol]
        bucket.update({"buy_qty": 0.0, "sell_qty": 0.0, "buy_count": 0, "sell_count": 0,
                       "buy_notional": 0.0, "sell_notional": 0.0,
                       "whale_buys": 0, "whale_sells": 0, "window_start": time.time(),
                       "updated_at": time.time()})
        tape = [
            _trade(now_ms - 20_000, 100.0, 1.0),
            _trade(now_ms - 10_000, 100.0, 300.0, buyer_maker=False),  # whale buy
            _trade(now_ms - 8_000, 99.88, 2.0),
            _trade(now_ms - 6_000, 99.85, 1.5),
        ]
        bucket["_tape"] = tape
        bucket["whale_buys"] = 1
        bucket["buy_notional"] = 30_000.0

        old_flag = config.VELOCITY_WHALE_DISTRIBUTION_FILTER
        config.VELOCITY_WHALE_DISTRIBUTION_FILTER = True
        try:
            # _open_velocity_position ilk kapılardan geçebilmesi için aday sahte;
            # whale filtresi likidite kapısından ÖNCE çalışır, bu yüzden erken
            # SKIPPED döner.
            result = await _open_velocity_position({
                "symbol": symbol, "price": 100.0, "velocity_score": 5.0,
                "mode": "trend_devam", "m5_pattern_ok": True,
                "atr_pct": 0.5, "m5_pattern": None,
            })
            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("whale_dagilim", result["reason"])
            self.assertEqual(result["whale_activity"]["verdict"], "distribution")
        finally:
            config.VELOCITY_WHALE_DISTRIBUTION_FILTER = old_flag

    async def test_flow_confirmation_filter_blocks_negative_cvd_when_enabled(self):
        from app.microflow import microflow
        from app.routers.velocity import _open_velocity_position
        from app.config import config

        symbol = "BTCTRY"
        microflow.symbol = symbol
        bucket = microflow.trade_flow[symbol]
        bucket.update({"buy_count": 0, "sell_count": 2, "buy_notional": 0.0,
                       "sell_notional": 50_000.0, "whale_buys": 0, "whale_sells": 0,
                       "window_start": time.time(), "updated_at": time.time()})
        bucket["_tape"] = [_trade(int(time.time() * 1000) - 5_000, 100.0, 500.0, buyer_maker=True)]

        old_flag = config.VELOCITY_FLOW_CONFIRMATION_FILTER
        config.VELOCITY_FLOW_CONFIRMATION_FILTER = True
        try:
            result = await _open_velocity_position({
                "symbol": symbol, "price": 100.0, "velocity_score": 5.0,
                "mode": "trend_devam", "m5_pattern_ok": True,
                "atr_pct": 0.5, "m5_pattern": None,
            })
            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("akis_aykiri", result["reason"])
            self.assertLess(result["cvd_try"], 0)
        finally:
            config.VELOCITY_FLOW_CONFIRMATION_FILTER = old_flag

    async def test_get_snapshot_handles_deque_tape(self):
        # Canlıda _tape bir deque'tir (maxlen sınırlı FIFO); get_snapshot'ın
        # slippage hesabı tape'i dilimlerken deque'ye izin verilmeyen bir slice
        # uygulamamalıdır. Regresyon: "sequence index must be integer, not 'slice'".
        from collections import deque
        from app.microflow import microflow

        symbol = "BTCTRY"
        microflow.symbol = symbol
        bucket = microflow.trade_flow[symbol]
        bucket.update({"buy_count": 10, "sell_count": 5, "buy_notional": 30_000.0,
                       "sell_notional": 20_000.0, "whale_buys": 1, "whale_sells": 0,
                       "window_start": time.time() - 30, "updated_at": time.time()})
        now_ms = int(time.time() * 1000)
        bucket["_tape"] = deque((_trade(now_ms - 40_000 + i * 1_000, 100.0, 1.0) for i in range(40)),
                                maxlen=2000)
        snapshot = microflow.get_snapshot(price=100.0)
        self.assertTrue(snapshot.get("data_ready") or snapshot.get("price"))
        self.assertIn("slippage", snapshot)
        self.assertGreaterEqual(snapshot["slippage"]["sample_trades"], 10)

    async def test_filters_are_fail_open_when_microflow_has_no_data(self):
        from app.microflow import microflow
        from app.routers.velocity import _open_velocity_position
        from app.config import config

        # Filtreler açık ama microflow verisi yok → fail-open (filtre engellemez).
        symbol = "ASDFTRY"
        microflow.symbol = symbol
        microflow.trade_flow.pop(symbol, None)
        old_w = config.VELOCITY_WHALE_DISTRIBUTION_FILTER
        old_f = config.VELOCITY_FLOW_CONFIRMATION_FILTER
        config.VELOCITY_WHALE_DISTRIBUTION_FILTER = True
        config.VELOCITY_FLOW_CONFIRMATION_FILTER = True
        try:
            result = await _open_velocity_position({
                "symbol": symbol, "price": 1.0, "velocity_score": 1.0,
                "mode": "trend_devam", "m5_pattern_ok": True,
                "atr_pct": 0.5, "m5_pattern": None,
            })
            # Sembol aktif listede değil → daha erken kapılardan reddedilir; önemli
            # olan whale/akis filtrelerinin "veri yok" yüzünden engellememesidir.
            self.assertNotIn("whale_dagilim", str(result.get("reason") or ""))
            self.assertNotIn("akis_aykiri", str(result.get("reason") or ""))
        finally:
            config.VELOCITY_WHALE_DISTRIBUTION_FILTER = old_w
            config.VELOCITY_FLOW_CONFIRMATION_FILTER = old_f


if __name__ == "__main__":
    unittest.main()
