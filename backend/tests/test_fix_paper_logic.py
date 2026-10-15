"""2026-10-15 denetim düzeltmeleri — paper mantığı testleri.

Kapsam (DENETIM_RAPORU_2026-10-15.md §2 numaralandırması):
  1. auto_paper: bayat/eksik ticker → REST yedeği ile yönetim sürer; REST de
     başarısızsa max_hold×1.5 sonrası `stale_force_close`.
  2. Stop/breakeven/trailing dolumu iki fiyatın KÖTÜSÜ (min); TP değişmedi.
  6. combined_paper: giriş TAZE fiyatla + giriş kayması; taze fiyat yoksa açılmaz.
  7. ATR stop: max(sl, min(TAVAN, 1.2×ATR)) — artık ölü kod değil.
 14. Gömülü sabitler config'e taşındı (varsayılanlar eski değerlerle aynı).

Mock desenleri test_auto_paper.py / test_combined_paper.py ile aynıdır.
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

from app.config import config  # noqa: E402
from app.routers import auto_paper  # noqa: E402
from app import combined_paper as cp  # noqa: E402


# ---------------------------------------------------------------------------
# Ortak fixture'lar (auto_paper)
# ---------------------------------------------------------------------------
def _trade(entry_time_ago_min: float = 10.0, **over) -> dict:
    now = time.time()
    t = {
        "id": 7,
        "symbol": "APTEST",
        "status": "open",
        "entry_price": 100.0,
        "quantity": 10.0,
        "take_profit": 110.0,
        "stop_loss": 97.0,
        "peak_price": 102.0,
        "entry_time": now - entry_time_ago_min * 60.0,
        "breakeven_activated": False,
        "breakeven_stop": None,
        "trailing_activated": False,
        "trailing_stop": None,
    }
    t.update(over)
    return t


def _market(price: float | None, age_sec: float = 0.0) -> MagicMock:
    """price=None → ticker yok; age_sec büyükse bayat ticker."""
    m = MagicMock()
    m.symbols = ["aptest"]
    if price is None:
        m.get_ticker = MagicMock(return_value=None)
    else:
        m.get_ticker = MagicMock(return_value={
            "last_price": price,
            "timestamp": (time.time() - age_sec) * 1000,
        })
    return m


_BASE_SETTINGS = {
    "max_hold_minutes": 60.0,
    "breakeven_enabled": False,
    "trailing_enabled": False,
    "tp_primary_exit_enabled": False,
    "tp_cancel_on_trail": False,
}

_STALE_AGE = config.MAX_TICKER_AGE_SEC + 120


def _db_patches():
    return [
        patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock()),
        patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock()),
        patch.object(auto_paper.database, "update_auto_paper_trailing", AsyncMock()),
        patch.object(auto_paper.database, "update_auto_paper_trade_tp", AsyncMock()),
        patch.object(auto_paper.database, "cancel_auto_paper_trade_tp", AsyncMock()),
    ]


async def _run(trade, market, rest, settings=None, close_mock=None):
    close_mock = close_mock or AsyncMock(return_value=None)
    patches = [
        patch("app.routers.auto_paper.market", market),
        patch.object(auto_paper, "_fresh_public_price", rest),
        patch.object(auto_paper, "_close_trade", close_mock),
        *_db_patches(),
    ]
    for p in patches:
        p.start()
    try:
        await auto_paper._manage_single_trade(trade, time.time(), 1.5, settings or dict(_BASE_SETTINGS))
    finally:
        for p in reversed(patches):
            p.stop()
    return close_mock


# ---------------------------------------------------------------------------
# Madde 1: bayat/eksik ticker → REST yedeği, zorla kapanış
# ---------------------------------------------------------------------------
class StaleTickerRestFallbackTests(unittest.IsolatedAsyncioTestCase):

    async def test_stale_ticker_uses_rest_price_and_stop_loss_fires(self):
        """Ticker bayat; REST 96 döner (stop 97'nin altında) → SL ÇALIŞIR (eskiden erken return)."""
        rest = AsyncMock(return_value=(96.0, {"source": "rest"}))
        close = await _run(_trade(), _market(50.0, age_sec=_STALE_AGE), rest)
        rest.assert_awaited_once_with("APTEST")
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "stop_loss")
        self.assertAlmostEqual(args[2], 96.0, places=9)   # min(96, 97)

    async def test_stale_ticker_rest_price_allows_max_hold_close(self):
        """Ticker bayat ama REST taze fiyat verdi → max_hold dolmuşsa REST fiyatıyla kapanır."""
        rest = AsyncMock(return_value=(100.0, {}))
        close = await _run(_trade(entry_time_ago_min=65), _market(50.0, age_sec=_STALE_AGE), rest)
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "max_duration")
        self.assertAlmostEqual(args[2], 100.0, places=9)

    async def test_rest_fails_before_force_window_defers(self):
        """REST de başarısız, süre 65 dk < 60×1.5=90 → kapanış ertelenir (bayat fiyatla kapanma yok)."""
        rest = AsyncMock(return_value=(None, None))
        close = await _run(_trade(entry_time_ago_min=65), _market(50.0, age_sec=_STALE_AGE), rest)
        close.assert_not_awaited()

    async def test_rest_fails_after_force_window_force_closes_at_last_known(self):
        """REST başarısız, süre 100 dk >= 90 → son bilinen (bayat ticker) fiyatla stale_force_close."""
        rest = AsyncMock(return_value=(None, None))
        close = await _run(_trade(entry_time_ago_min=100), _market(50.0, age_sec=_STALE_AGE), rest)
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "stale_force_close")
        self.assertAlmostEqual(args[2], 50.0, places=9)

    async def test_missing_ticker_and_rest_exception_force_closes_at_peak(self):
        """Ticker hiç yok, REST istisna atıyor, süre 100 dk → peak_price ile stale_force_close."""
        rest = AsyncMock(side_effect=RuntimeError("rest down"))
        close = await _run(_trade(entry_time_ago_min=100, peak_price=102.0), _market(None), rest)
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "stale_force_close")
        self.assertAlmostEqual(args[2], 102.0, places=9)

    async def test_fresh_ticker_does_not_call_rest(self):
        """Ticker tazeyse REST yedeğine hiç gidilmez (ekstra REST yükü yok)."""
        rest = AsyncMock(return_value=(1.0, {}))
        close = await _run(_trade(), _market(100.0), rest)
        rest.assert_not_awaited()
        close.assert_not_awaited()


# ---------------------------------------------------------------------------
# Madde 2: stop dolumu min(price, stop); TP değişmedi
# ---------------------------------------------------------------------------
class StopFillPessimisticTests(unittest.IsolatedAsyncioTestCase):

    async def test_stop_loss_fills_at_worse_price_in_gap(self):
        """Fiyat 95, stop 97 → dolum 95 (eski kod 97 yazıyordu)."""
        close = await _run(_trade(), _market(95.0), AsyncMock(return_value=(None, None)))
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "stop_loss")
        self.assertAlmostEqual(args[2], 95.0, places=9)

    async def test_trailing_stop_fills_at_worse_price(self):
        """Trailing aktif, stop 101.97 (peak 103 × 0.99), fiyat 100.9 → dolum 100.9."""
        trade = _trade(peak_price=103.0, trailing_activated=True, trailing_stop=101.5)
        settings = dict(_BASE_SETTINGS, trailing_enabled=True, trailing_gap_pct=1.0,
                        trailing_trigger_pct=2.0)
        close = await _run(trade, _market(100.9), AsyncMock(return_value=(None, None)), settings)
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "trailing_stop")
        self.assertAlmostEqual(args[2], 100.9, places=9)

    async def test_breakeven_stop_fills_at_worse_price(self):
        """Breakeven kilidi 101.5, fiyat 100.2 → dolum 100.2 (min)."""
        trade = _trade(breakeven_activated=True, breakeven_stop=101.5)
        settings = dict(_BASE_SETTINGS, breakeven_enabled=True)
        close = await _run(trade, _market(100.2), AsyncMock(return_value=(None, None)), settings)
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "breakeven_stop")
        self.assertAlmostEqual(args[2], 100.2, places=9)

    async def test_take_profit_fill_unchanged(self):
        """TP dolumu olduğu gibi: min(price, tp) → fiyat 112, TP 110 → 110."""
        settings = dict(_BASE_SETTINGS, tp_primary_exit_enabled=True)
        close = await _run(_trade(), _market(112.0), AsyncMock(return_value=(None, None)), settings)
        close.assert_awaited_once()
        args = close.await_args.args
        self.assertEqual(args[4], "take_profit")
        self.assertAlmostEqual(args[2], 110.0, places=9)


# ---------------------------------------------------------------------------
# Madde 7: ATR stop artık ölü kod değil
# ---------------------------------------------------------------------------
class AtrStopCapTests(unittest.TestCase):

    def test_atr_widens_stop_within_cap(self):
        # sl %1, ATR %1.5 → 1.2×1.5 = %1.8 < tavan %2.8 → %1.8
        self.assertAlmostEqual(auto_paper._effective_sl_pct(0.01, 0.015, cap_pct=0.028), 0.018, places=12)

    def test_atr_widening_is_capped(self):
        # sl %1, ATR %5 → 1.2×5 = %6 → tavan %2.8
        self.assertAlmostEqual(auto_paper._effective_sl_pct(0.01, 0.05, cap_pct=0.028), 0.028, places=12)

    def test_atr_never_narrows_stop(self):
        # sl %1, ATR %0.5 → 1.2×0.5 = %0.6 < sl → sl kalır
        self.assertAlmostEqual(auto_paper._effective_sl_pct(0.01, 0.005, cap_pct=0.028), 0.01, places=12)
        # sl %5 (tavandan geniş) → her zaman sl
        self.assertAlmostEqual(auto_paper._effective_sl_pct(0.05, 0.05, cap_pct=0.028), 0.05, places=12)

    def test_cap_default_comes_from_config(self):
        self.assertGreater(config.AUTO_PAPER_ATR_SL_CAP_PCT, 0)
        self.assertAlmostEqual(auto_paper._effective_sl_pct(0.001, 1.0),
                               config.AUTO_PAPER_ATR_SL_CAP_PCT / 100.0, places=12)

    def test_old_dead_formula_is_gone(self):
        import inspect
        src = inspect.getsource(auto_paper._open_new_trade)
        self.assertNotIn("min(sl_pct, 1.2 * atr_pct)", src)
        self.assertIn("_effective_sl_pct(sl_pct, atr_pct)", src)


# ---------------------------------------------------------------------------
# Madde 14: gömülü sabitler config'de, varsayılanlar eski değerler
# ---------------------------------------------------------------------------
class EmbeddedConstantsTests(unittest.TestCase):

    def test_config_defaults_match_old_embedded_values(self):
        self.assertEqual(config.AUTO_PAPER_SL_COOLDOWN_MINUTES, 5.0)
        self.assertEqual(config.AUTO_PAPER_LOOP_STARTUP_DELAY_SEC, 30.0)
        self.assertEqual(config.AUTO_PAPER_REOPEN_HOUR_BUCKET_SEC, 3600)
        self.assertEqual(config.AUTO_PAPER_STALE_FORCE_CLOSE_FACTOR, 1.5)
        self.assertEqual(auto_paper._REOPEN_HOUR_BUCKET_SEC, 3600)
        self.assertEqual(auto_paper._SL_COOLDOWN_MINUTES_DEFAULT, 5.0)

    def test_no_market_tickers_write_in_open_path(self):
        """Madde 3: açılış yolunda paylaşımlı market.tickers'a yazılmaz."""
        import inspect
        src = inspect.getsource(auto_paper.try_open_from_notification)
        self.assertNotIn("market.tickers[symbol] =", src)


# ---------------------------------------------------------------------------
# Madde 2/5/6: combined_paper (pytest + monkeypatch, test_combined_paper.py deseni)
# ---------------------------------------------------------------------------
def _cp_trade(**over):
    t = {"id": 1, "symbol": "T", "entry_price": 100.0, "quantity": 1.0,
         "take_profit": 110.0, "stop_loss": 97.0, "peak_price": 100.0,
         "trailing_activated": False, "entry_time": time.time()}
    t.update(over)
    return t


def test_combined_stop_fills_at_worse_price(monkeypatch):
    """Madde 2: fiyat 95 < stop 97 → kapanış fiyatı 95 (eski max → 97)."""
    closed = []

    async def _close(tid, price, now, reason):
        closed.append((price, reason)); return {"pnl": -1.0}
    monkeypatch.setattr(cp.database, "close_combined_paper_trade", _close)

    async def _price(_s):
        return 95.0
    monkeypatch.setattr(cp, "_price", _price)
    asyncio.run(cp._manage_single(_cp_trade(), time.time()))
    assert closed == [(95.0, "stop_loss")]


def test_combined_close_retries_once_when_db_returns_none(monkeypatch):
    """Madde 5: kapanış None dönerse uyarı + BİR tekrar; ikincisi başarılıysa biter."""
    calls = []
    results = [None, {"pnl": -1.0}]

    async def _close(tid, price, now, reason):
        calls.append(reason); return results.pop(0)
    monkeypatch.setattr(cp.database, "close_combined_paper_trade", _close)

    async def _price(_s):
        return 95.0
    monkeypatch.setattr(cp, "_price", _price)
    asyncio.run(cp._manage_single(_cp_trade(), time.time()))
    assert calls == ["stop_loss", "stop_loss"]


def test_combined_close_gives_up_after_two_failures(monkeypatch):
    calls = []

    async def _close(tid, price, now, reason):
        calls.append(reason); return None
    monkeypatch.setattr(cp.database, "close_combined_paper_trade", _close)

    async def _price(_s):
        return 95.0
    monkeypatch.setattr(cp, "_price", _price)
    asyncio.run(cp._manage_single(_cp_trade(), time.time()))
    assert len(calls) == 2


def test_combined_entry_uses_fresh_price_with_entry_slippage(monkeypatch):
    """Madde 6: liste fiyatı 100 (bayat), taze fiyat 110 → giriş 110×(1+slip); TP/SL bu çapadan."""
    opened_plans = []

    async def _price(_s):
        return 110.0
    monkeypatch.setattr(cp, "_price", _price)

    async def _wallet():
        return 5000.0
    monkeypatch.setattr(cp.database, "get_combined_paper_wallet", _wallet)

    async def _open(plan):
        opened_plans.append(plan); return ({"id": 1, **plan}, "opened")
    monkeypatch.setattr(cp.database, "open_combined_paper_trade", _open)
    monkeypatch.setattr(config, "COMBINED_PAPER_ENABLED", True)

    n = asyncio.run(cp.on_combined_list_sent(
        [{"symbol": "wtest", "price": 100.0, "potential_pct": 20.0}], report_id=5))
    assert n == 1 and len(opened_plans) == 1
    plan = opened_plans[0]
    fill = 110.0 * (1 + config.ESTIMATED_SLIPPAGE_PCT)
    assert abs(plan["entry_price"] - fill) < 1e-9
    assert abs(plan["quantity"] - 500.0 / fill) < 1e-9
    assert plan["take_profit"] > fill and plan["stop_loss"] < fill
    assert abs(plan["stop_loss"] - round(fill * (1 - config.COMBINED_PAPER_SL_PCT / 100.0), 8)) < 1e-9


def test_combined_entry_skipped_without_fresh_price(monkeypatch):
    """Madde 6: taze fiyat yoksa (WS+REST None) bayat liste fiyatıyla AÇILMAZ."""
    opened = []

    async def _price(_s):
        return None
    monkeypatch.setattr(cp, "_price", _price)

    async def _wallet():
        return 5000.0
    monkeypatch.setattr(cp.database, "get_combined_paper_wallet", _wallet)

    async def _open(plan):
        opened.append(plan); return ({"id": 1}, "opened")
    monkeypatch.setattr(cp.database, "open_combined_paper_trade", _open)
    monkeypatch.setattr(config, "COMBINED_PAPER_ENABLED", True)

    n = asyncio.run(cp.on_combined_list_sent([{"symbol": "WTEST", "price": 100.0}], report_id=5))
    assert n == 0 and opened == []


def test_plan_entry_without_price_keeps_candidate_price_plus_slippage():
    """Geriye uyum: `price` verilmezse aday fiyatı (+giriş kayması) kullanılır."""
    plan = cp._plan_entry({"symbol": "X", "price": 10.0, "potential_pct": 8.0}, 5000.0)
    assert plan is not None
    assert abs(plan["entry_price"] - 10.0 * (1 + config.ESTIMATED_SLIPPAGE_PCT)) < 1e-12
