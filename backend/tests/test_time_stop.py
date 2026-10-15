"""2026-10-15 (radar iyileştirme): ZAMAN-DURDURMA (time-stop) testleri.

Kural: süre T dk'ya ulaştığında kâr eşiğin altındaysa pozisyonu kapat.

Kapsam:
  * `app/paper_sim.simulate_exit` — time_stop_min / time_stop_min_profit_pct:
    (a) düz fiyat → T'den sonraki ilk mumda time_stop;
    (b) T'de kâr eşiğin üstündeyse time_stop YOK;
    (c) T'den önce TP → reason değişmez (take_profit);
    (d) time_stop_min=None → yeni argümanlar olmadan AYNI sonuç.
  * `app/routers/auto_paper._manage_single_trade` — flag 0 iken kapatma yok;
    flag 15 ve bayat-düz pozisyonda `_close_trade(..., "time_stop")` çağrılır.

Mock deseni test_fix_paper_logic.py ile aynıdır.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SCALPER_ENV", "development")

from app import paper_sim  # noqa: E402
from app.routers import auto_paper  # noqa: E402

T0 = 1_000_000.0  # giriş epoch (sn); ilk mum T0'da açılır


def _bar(k: int, h: float, l: float, c: float) -> dict:
    """k. 5m mum: açılış T0 + k*300 sn, kapanış T0 + (k+1)*300 sn."""
    return {"open_time": T0 + k * 300.0, "high": float(h), "low": float(l), "close": float(c)}


def _flat(n: int, close: float = 100.0) -> list[dict]:
    return [_bar(k, close + 0.1, close - 0.1, close) for k in range(n)]


# ---------------------------------------------------------------------------
# paper_sim.simulate_exit
# ---------------------------------------------------------------------------
class TimeStopSimTests(unittest.TestCase):

    def test_flat_price_fires_at_first_bar_after_T(self):
        """T=15 dk: hold 5/10/15 dk'lık mumlar; 15. dakikadaki (k=2) kapanışta çık.

        k=1 kapanışı 99.9 (hold 10 < 15 → tetiklenmez), k=2 kapanışı 99.8 → çıkış 99.8.
        """
        bars = [_bar(0, 100.1, 99.9, 100.0), _bar(1, 100.1, 99.8, 99.9),
                _bar(2, 100.0, 99.7, 99.8), _bar(3, 99.9, 99.6, 99.7)]
        r = paper_sim.simulate_exit(bars, 100.0, entry_time=T0, tp_pct=3.0, sl_pct=3.0,
                                    trail_trigger_pct=50.0, no_profit_min=0.0, max_hold_min=0.0,
                                    commission_pct=0.0, slippage_pct=0.0,
                                    time_stop_min=15.0, time_stop_min_profit_pct=0.3)
        self.assertEqual(r["reason"], "time_stop")
        self.assertAlmostEqual(r["exit_price"], 99.8, places=9)
        self.assertAlmostEqual(r["sim_pct"], -0.2, places=2)

    def test_profit_above_threshold_at_T_no_time_stop(self):
        """T'de kâr +%0.5 ≥ eşik %0.3 → time_stop yok; pozisyon açık kalır."""
        bars = [_bar(k, 100.6, 100.4, 100.5) for k in range(6)]  # 30 dk, hepsi +%0.5
        r = paper_sim.simulate_exit(bars, 100.0, entry_time=T0, tp_pct=3.0, sl_pct=3.0,
                                    trail_trigger_pct=50.0, no_profit_min=0.0, max_hold_min=0.0,
                                    commission_pct=0.0, slippage_pct=0.0,
                                    time_stop_min=15.0, time_stop_min_profit_pct=0.3)
        self.assertNotEqual(r["reason"], "time_stop")
        self.assertEqual(r["reason"], "open")

    def test_take_profit_before_T_keeps_reason(self):
        """İlk mumda TP (%3) vurulur; T=15 dk'dan önce → reason 'take_profit' kalır."""
        bars = [_bar(0, 103.5, 99.9, 103.2)] + [_bar(k, 100.0, 99.9, 100.0) for k in range(1, 6)]
        r = paper_sim.simulate_exit(bars, 100.0, entry_time=T0, tp_pct=3.0, sl_pct=3.0,
                                    trail_trigger_pct=50.0, no_profit_min=0.0, max_hold_min=0.0,
                                    commission_pct=0.0, slippage_pct=0.0,
                                    time_stop_min=15.0, time_stop_min_profit_pct=0.3)
        self.assertEqual(r["reason"], "take_profit")
        self.assertAlmostEqual(r["exit_price"], 103.0, places=9)

    def test_take_profit_on_time_stop_bar_wins(self):
        """T'deki mumda hem TP hem düz kapanış: TP önceliklidir (time_stop sonra değerlendirilir)."""
        bars = [_bar(k, 100.0, 99.9, 100.0) for k in range(2)] + [_bar(2, 103.5, 99.9, 100.0)]
        r = paper_sim.simulate_exit(bars, 100.0, entry_time=T0, tp_pct=3.0, sl_pct=3.0,
                                    trail_trigger_pct=50.0, no_profit_min=0.0, max_hold_min=0.0,
                                    commission_pct=0.0, slippage_pct=0.0,
                                    time_stop_min=15.0, time_stop_min_profit_pct=0.3)
        self.assertEqual(r["reason"], "take_profit")

    def test_none_is_identical_to_call_without_new_args(self):
        """time_stop_min=None → yeni argümanlar yokmuş gibi birebir aynı dict."""
        bars = [_bar(0, 100.5, 99.5, 100.2), _bar(1, 101.0, 99.0, 99.4),
                _bar(2, 100.2, 98.9, 99.1), _bar(3, 99.8, 98.0, 98.2),
                _bar(4, 98.5, 97.0, 97.1), _bar(5, 97.5, 96.0, 96.5),
                _bar(6, 96.8, 95.0, 95.5), _bar(7, 95.8, 94.0, 94.2)]
        kw = dict(entry_time=T0, tp_pct=3.0, sl_pct=3.0, trail_trigger_pct=2.0,
                  trail_gap_pct=1.0, no_profit_min=30.0, max_hold_min=120.0,
                  commission_pct=0.0015, slippage_pct=0.00025)
        without = paper_sim.simulate_exit(bars, 100.0, **kw)
        with_none = paper_sim.simulate_exit(bars, 100.0, time_stop_min=None, **kw)
        self.assertEqual(without, with_none)
        self.assertNotEqual(without["reason"], "time_stop")

    def test_reason_strings_unchanged_for_existing_paths(self):
        """Mevcut çıkış nedenleri (stop_loss) time-stop açıkken de aynı kalır."""
        bars = [_bar(0, 100.0, 96.0, 96.5)]
        r = paper_sim.simulate_exit(bars, 100.0, entry_time=T0, sl_pct=3.0,
                                    commission_pct=0.0, slippage_pct=0.0,
                                    time_stop_min=15.0, time_stop_min_profit_pct=0.3)
        self.assertEqual(r["reason"], "stop_loss")


# ---------------------------------------------------------------------------
# auto_paper._manage_single_trade (canlı yönetici)
# ---------------------------------------------------------------------------
_SETTINGS = {
    "max_hold_minutes": 120.0,
    "breakeven_enabled": False,
    "trailing_enabled": False,
    "tp_primary_exit_enabled": False,
    "tp_cancel_on_trail": False,
}


def _live_trade(hold_min: float) -> dict:
    now = time.time()
    return {
        "id": 9, "symbol": "APTEST", "status": "open",
        "entry_price": 100.0, "quantity": 10.0,
        "take_profit": 110.0, "stop_loss": 97.0, "peak_price": 100.0,
        "entry_time": now - hold_min * 60.0,
        "breakeven_activated": False, "breakeven_stop": None,
        "trailing_activated": False, "trailing_stop": None,
    }


def _live_market(price: float) -> MagicMock:
    m = MagicMock()
    m.symbols = ["aptest"]
    m.get_ticker = MagicMock(return_value={"last_price": price,
                                           "timestamp": time.time() * 1000})
    return m


async def _run_live(trade: dict, price: float, flag_min: float) -> AsyncMock:
    close_mock = AsyncMock(return_value=None)
    patches = [
        patch("app.routers.auto_paper.market", _live_market(price)),
        patch.object(auto_paper, "_fresh_public_price", AsyncMock(return_value=(None, None))),
        patch.object(auto_paper, "_close_trade", close_mock),
        patch.object(auto_paper, "AUTO_PAPER_TIME_STOP_MIN", flag_min),
        patch.object(auto_paper, "AUTO_PAPER_TIME_STOP_MIN_PROFIT_PCT", 0.3),
        patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock()),
        patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock()),
        patch.object(auto_paper.database, "update_auto_paper_trailing", AsyncMock()),
        patch.object(auto_paper.database, "update_auto_paper_trade_tp", AsyncMock()),
        patch.object(auto_paper.database, "cancel_auto_paper_trade_tp", AsyncMock()),
    ]
    for p in patches:
        p.start()
    try:
        await auto_paper._manage_single_trade(trade, time.time(), 1.5, dict(_SETTINGS))
    finally:
        for p in reversed(patches):
            p.stop()
    return close_mock


class TimeStopLiveTests(unittest.TestCase):

    def test_flag_zero_never_calls_close_helper(self):
        """Flag 0 (varsayılan): 60 dk'lık düz pozisyon bile time_stop ile kapanmaz."""
        close = asyncio.run(_run_live(_live_trade(60.0), 100.0, flag_min=0.0))
        close.assert_not_awaited()

    def test_flag_15_closes_stale_flat_trade_with_time_stop(self):
        """Flag 15: 20 dk önce açılmış, fiyat düz (kâr 0 < 0.3) → time_stop ile kapat."""
        close = asyncio.run(_run_live(_live_trade(20.0), 100.0, flag_min=15.0))
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "time_stop")
        self.assertAlmostEqual(args[2], 100.0, places=9)

    def test_flag_15_keeps_trade_that_is_up_enough(self):
        """Flag 15 ama kâr %1 ≥ eşik %0.3 → kapatılmaz."""
        close = asyncio.run(_run_live(_live_trade(20.0), 101.0, flag_min=15.0))
        close.assert_not_awaited()

    def test_flag_15_young_trade_not_closed(self):
        """Flag 15 ama süre 10 dk < 15 dk → kapatılmaz."""
        close = asyncio.run(_run_live(_live_trade(10.0), 100.0, flag_min=15.0))
        close.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
