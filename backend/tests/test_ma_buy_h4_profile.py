"""2026-10-21: H4 MA kesişimi ÖZEL PROFİLİ (app/ma_buy_profiles.py): SMA 8/34/89, yalnız orta×yavaş kesişim, gövde ≥ %1;
paper çıkışı hedef %10 / stop %8 / 3 gün / iz süren stop yok; bildirim metni özel. Kaynak: docs/MA_KESISIM_H4_ARAMA_90g_2026-10-21.md"""
import pytest

from app import ma_buy_notify as notify, ma_buy_profiles as profiles, ma_buy_signals, ma_buy_tracker as tracker
from app.config import config


def test_h4_profile_values_and_other_timeframes_have_none():
    p = profiles.profile("4h")
    assert p["name"] == "ma_buy_h4" and p["periods"] == (8, 34, 89) and p["rules"] == (ma_buy_signals.RULE_MID_CROSS_SLOW,)
    assert p["min_body_pct"] == 1.0 and p["stop_loss_pct"] == 8.0 and p["max_hold_minutes"] == 4320 and p["trailing"] is False
    assert p["stoch_max"] is None
    for tf in ("1m", "5m", "15m", "30m", "1h"):
        assert profiles.profile(tf) is None


def test_h4_profile_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "MA_BUY_H4_PROFILE_ENABLED", False, raising=False)
    assert profiles.profile("4h") is None


def test_h4_target_default_is_10_pct():
    assert notify.target_pct("4h") == 10.0


def _bars(closes, opens=None, tf_ms=14_400_000):
    opens = opens or closes
    return [{"open_ms": i * tf_ms, "close_ms": (i + 1) * tf_ms - 1, "open": o, "high": max(o, c), "low": min(o, c), "close": c}
            for i, (o, c) in enumerate(zip(opens, closes))]


def _mid_slow_cross_series():
    """Uzun düşüş + sert dönüş: SMA34 SMA89'u yukarı keser (orta×yavaş); hızlı×orta kesişimi daha önce olur."""
    closes = [100.0 - i * 0.05 for i in range(120)] + [94.0 + i * 0.6 for i in range(60)]
    return closes


def test_signals_from_bars_rules_allowed_keeps_only_mid_cross_slow():
    closes = _mid_slow_cross_series()
    bars = _bars(closes)
    all_rows = tracker.signals_from_bars("AAATRY", "4h", bars, now_ms=10 ** 13, lookback=len(bars), per=(8, 34, 89),
                                         use_sma=True, stoch_max=None)
    only = tracker.signals_from_bars("AAATRY", "4h", bars, now_ms=10 ** 13, lookback=len(bars), per=(8, 34, 89),
                                     use_sma=True, stoch_max=None, rules_allowed=(ma_buy_signals.RULE_MID_CROSS_SLOW,))
    assert all_rows
    assert only and all(r["rules"] == ma_buy_signals.RULE_MID_CROSS_SLOW for r in only)
    assert all("body_pct" in r for r in only)


def test_signals_from_bars_min_body_filters_small_candles():
    closes = _mid_slow_cross_series()
    opens = [c * 0.9995 for c in closes]            # her mum +%0,05 gövde → %1 eşiğinde elenir
    bars = _bars(closes, opens)
    rows_no_filter = tracker.signals_from_bars("AAATRY", "4h", bars, now_ms=10 ** 13, lookback=len(bars), per=(8, 34, 89),
                                               use_sma=True, stoch_max=None, rules_allowed=(ma_buy_signals.RULE_MID_CROSS_SLOW,))
    rows_filtered = tracker.signals_from_bars("AAATRY", "4h", bars, now_ms=10 ** 13, lookback=len(bars), per=(8, 34, 89),
                                              use_sma=True, stoch_max=None, rules_allowed=(ma_buy_signals.RULE_MID_CROSS_SLOW,),
                                              min_body_pct=1.0)
    assert rows_no_filter and not rows_filtered
    big = _bars(closes, [c * 0.98 for c in closes])  # +%2 gövde → geçer
    assert tracker.signals_from_bars("AAATRY", "4h", big, now_ms=10 ** 13, lookback=len(big), per=(8, 34, 89), use_sma=True,
                                     stoch_max=None, rules_allowed=(ma_buy_signals.RULE_MID_CROSS_SLOW,), min_body_pct=1.0)


def test_h4_notification_is_special_and_carries_exit_profile():
    row = {"symbol": "wldtry", "timeframe": "4h", "rules": ma_buy_signals.RULE_MID_CROSS_SLOW, "signal_price": 12.5,
           "bar_open_ms": 1_700_000_000_000, "bar_close_ms": 1_700_014_400_000, "body_pct": 1.8}
    n = notify.build_notification(row, (7, 20, 99), now=1_700_014_450.0)
    assert n["title"] == "🕓 WLDTRY · H4 MA KESİŞİMİ · uzun vade"
    assert "SMA34 ↗ SMA89" in n["message"] and "gövde +%1.8" in n["message"]
    assert "Hedef: +%10" in n["message"] and "Stop: −%8" in n["message"] and "En çok 3 gün" in n["message"]
    assert n["tag"] == "ma-buy-h4-WLDTRY" and n["url"] == "/charts?symbol=WLDTRY&timeframe=4h"
    assert n["target_pct"] == 10.0 and n["expected_price"] == pytest.approx(13.75)
    assert n["exit_profile"] == {"name": "ma_buy_h4", "stop_loss_pct": 8.0, "max_hold_minutes": 4320.0, "trailing": False}
    assert n["horizon_minutes"] == 240 and n["source"] == "ma_buy" and n["notification_key"] == "ma-4h-WLDTRY-1700000000000"


def test_other_timeframes_keep_generic_notification():
    row = {"symbol": "BTCTRY", "timeframe": "1h", "rules": ma_buy_signals.RULE_FAST_CROSS_MID, "signal_price": 100.0,
           "bar_open_ms": 0, "bar_close_ms": 3_600_000}
    n = notify.build_notification(row, (7, 20, 99), now=3_650.0)
    assert n["title"] == "📈 BTCTRY · MA BUY (H1)" and "exit_profile" not in n


def test_exit_overrides_reads_envelope_and_ignores_garbage():
    assert profiles.exit_overrides({"exit_profile": {"name": "ma_buy_h4", "stop_loss_pct": 8, "max_hold_minutes": 4320, "trailing": False}}) == \
        {"name": "ma_buy_h4", "trailing": False, "stop_loss_pct": 8.0, "max_hold_minutes": 4320.0}
    assert profiles.exit_overrides({"exit_profile": {"name": "x", "stop_loss_pct": "yok"}}) == {"name": "x", "trailing": True}
    assert profiles.exit_overrides({}) is None and profiles.exit_overrides({"exit_profile": "ma_buy_h4"}) is None


def test_enable_timeframe_once_uses_10_pct_target_for_h4():
    persisted = {"ma_buy_notify_timeframes": "5m,1h", "ma_buy_target_pct": "1h:3"}
    notify.enable_timeframe_once(persisted)
    assert persisted["ma_buy_target_pct"] == "1h:3,4h:10"


# ---------------------------------------------------------------- auto_paper: zarftaki cikis profili uygulanir
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.routers import auto_paper


class AutoPaperH4ExitProfileTests(unittest.IsolatedAsyncioTestCase):
    async def _open(self, notification, settings):
        captured = {}

        async def fake_open(trade_data, signal):
            captured["trade_data"] = trade_data
            return ({"id": 1}, "opened")

        with patch.object(auto_paper.database, "get_wallet_balance", AsyncMock(return_value=10_000.0)), \
             patch.object(auto_paper.database, "open_auto_paper_trade", AsyncMock(side_effect=fake_open)), \
             patch.object(auto_paper, "_broadcast_trade", AsyncMock()):
            await auto_paper._open_new_trade("WLDTRY", notification, 100.0, settings)
        return captured["trade_data"]

    async def test_h4_envelope_sets_stop_8pct_hold_3_days_and_profile_name(self):
        settings = {"balance_pct": 10.0, "min_order_try": 10.0, "stop_loss_pct": 3.0, "default_target_pct": 2.0}
        notif = {"symbol": "WLDTRY", "source": "ma_buy", "target_pct": 10.0, "price": 100.0,
                 "exit_profile": {"name": "ma_buy_h4", "stop_loss_pct": 8.0, "max_hold_minutes": 4320.0, "trailing": False}}
        td = await self._open(notif, settings)
        entry = td["entry_price"]
        self.assertAlmostEqual(td["stop_loss"], entry * (1 - 0.08), places=6)         # ayarlardaki %3 degil, profil %8
        self.assertEqual(td["exit_profile"], "ma_buy_h4")
        self.assertEqual(td["max_hold_minutes"], 4320.0)
        self.assertGreater(td["take_profit"], entry * 1.10)                            # hedef %10 (+maliyet payi)

    async def test_envelope_profile_ignored_for_non_rule_signals(self):
        settings = {"balance_pct": 10.0, "min_order_try": 10.0, "stop_loss_pct": 3.0, "default_target_pct": 2.0,
                    "volatility_sl_enabled": False}
        notif = {"symbol": "WLDTRY", "score": 80.0, "target_pct": 2.0, "price": 100.0,
                 "exit_profile": {"name": "ma_buy_h4", "stop_loss_pct": 8.0, "max_hold_minutes": 4320.0}}
        td = await self._open(notif, settings)
        self.assertAlmostEqual(td["stop_loss"], td["entry_price"] * (1 - 0.03), places=6)
        self.assertIsNone(td["exit_profile"]) and self.assertIsNone(td["max_hold_minutes"])

    async def test_manage_skips_trailing_and_uses_trade_hold_for_profile_trade(self):
        """Profilli islem: +%3 karda bile trailing/breakeven yazilmaz; tutma 3 gun dolmadan time_stop olmaz."""
        now = time.time()
        trade = {"id": 7, "symbol": "WLDTRY", "status": "open", "entry_price": 100.0, "quantity": 1.0,
                 "stop_loss": 92.0, "take_profit": 110.5, "peak_price": 103.0, "entry_time": now - 10 * 3600,
                 "exit_profile": "ma_buy_h4", "max_hold_minutes": 4320.0}
        settings = {"trailing_enabled": True, "trailing_trigger_pct": 2.0, "trailing_gap_pct": 1.0,
                    "breakeven_enabled": True, "max_hold_minutes": 120.0, "tp_primary_exit_enabled": False}
        closed, trailing_updates, breakeven_updates = [], [], []

        async def fake_close(trade_id, symbol, price, when, reason):
            closed.append(reason)

        with patch.object(auto_paper, "_close_trade", AsyncMock(side_effect=fake_close)), \
             patch.object(auto_paper.database, "update_auto_paper_trailing", AsyncMock(side_effect=lambda *a: trailing_updates.append(a))), \
             patch.object(auto_paper.database, "update_auto_paper_breakeven", AsyncMock(side_effect=lambda *a: breakeven_updates.append(a))), \
             patch.object(auto_paper.database, "update_auto_paper_peak", AsyncMock(), create=True), \
             patch.object(auto_paper.market, "get_ticker", lambda s: {"last_price": 103.0, "timestamp": now * 1000}):
            await auto_paper._manage_single_trade(trade, now, 1.5, settings)
        self.assertEqual(closed, [], "10 saatlik profilli islem 120 dk ayariyla kapatilmamali")
        self.assertEqual(trailing_updates, [])
        self.assertEqual(breakeven_updates, [])
