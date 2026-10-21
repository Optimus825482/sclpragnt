"""2026-10-21: H4 MA kesişimi ÖZEL PROFİLİ (app/ma_buy_profiles.py). Sinyal (kullanıcı kararı): MA 7/20/99, iki kural,
gövde/StochRSI eleği yok, MA türü grafik şeridi (MA_BUY_MA_TYPE); paper çıkışı hedef %10 / stop %8 / 3 gün / iz süren stop
yok; bildirim metni özel. Eski arama ayarı (SMA 8/34/89, orta×yavaş, gövde ≥ %1) ortam değişkeniyle geri alınabilir."""
import pytest

from app import ma_buy_notify as notify, ma_buy_profiles as profiles, ma_buy_signals, ma_buy_tracker as tracker
from app.config import config


def test_h4_profile_values_and_other_timeframes_have_none():
    p = profiles.profile("4h")
    assert p["name"] == "ma_buy_h4" and p["periods"] == (7, 20, 99) and p["rules"] == (ma_buy_signals.RULE_FAST_CROSS_MID,)
    assert p["require_mid_above_slow"] is False          # 18:30 kararı: MA99 şartı yok
    assert p["min_quote_volume"] == 5_000_000.0           # 19:15 kararı: 24 sa hacim tabanı
    assert p["min_body_pct"] == 0.0 and p["stop_loss_pct"] == 8.0 and p["max_hold_minutes"] == 4320 and p["trailing"] is False
    assert p["stoch_max"] is None and p["ma_type"] == "sma"
    for tf in ("1m", "5m", "15m", "30m", "1h"):
        assert profiles.profile(tf) is None


def test_h4_profile_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "MA_BUY_H4_PROFILE_ENABLED", False, raising=False)
    assert profiles.profile("4h") is None


def test_h4_profile_follows_chart_ma_type_and_env_overrides(monkeypatch):
    monkeypatch.setattr(config, "MA_BUY_MA_TYPE", "ema", raising=False)
    assert profiles.profile("4h")["ma_type"] == "ema"
    monkeypatch.setattr(config, "MA_BUY_MA_TYPE", "bozuk", raising=False)
    assert profiles.profile("4h")["ma_type"] == "sma"
    # Eski arama ayarı geri alınabilir
    monkeypatch.setattr(config, "MA_BUY_H4_PERIODS", "8,34,89", raising=False)
    monkeypatch.setattr(config, "MA_BUY_H4_RULES", "mid_cross_slow", raising=False)
    monkeypatch.setattr(config, "MA_BUY_H4_MIN_BODY_PCT", 1.0, raising=False)
    p = profiles.profile("4h")
    assert p["periods"] == (8, 34, 89) and p["rules"] == (ma_buy_signals.RULE_MID_CROSS_SLOW,) and p["min_body_pct"] == 1.0
    # Geçersiz kural listesi → yalnız hızlı×orta
    monkeypatch.setattr(config, "MA_BUY_H4_RULES", "yok", raising=False)
    assert profiles.profile("4h")["rules"] == (ma_buy_signals.RULE_FAST_CROSS_MID,)
    monkeypatch.setattr(config, "MA_BUY_H4_REQUIRE_MID_ABOVE_SLOW", True, raising=False)
    assert profiles.profile("4h")["require_mid_above_slow"] is True


def test_tracker_scans_4h_with_profile_periods_and_chart_ma_type(monkeypatch):
    """İzleyici H4'te profil periyotlarını (7/20/99) ve MA türünü (SMA/EMA) kullanır."""
    import asyncio
    seen = {}

    def fake_signals(symbol, tf, bars, now_ms, **kw):
        seen.update(kw)
        return []

    async def fake_klines(symbol, tf, limit):
        return [[i * 14_400_000, "1", "1", "1", "1", "0", (i + 1) * 14_400_000 - 1] for i in range(120)]

    monkeypatch.setattr(tracker, "fetch_klines", fake_klines)
    monkeypatch.setattr(tracker, "signals_from_bars", fake_signals)
    monkeypatch.setattr(config, "MA_BUY_MA_TYPE", "ema", raising=False)
    tracker._state["seen"].pop(("XTRY", "4h"), None)
    asyncio.run(tracker._scan_symbol("XTRY", "4h", 120 * 14_400_000 + 10_000, asyncio.Semaphore(1)))
    assert seen["per"] == (7, 20, 99) and seen["use_sma"] is False and seen["rules_allowed"] == (ma_buy_signals.RULE_FAST_CROSS_MID,)
    assert seen["min_body_pct"] == 0.0 and seen["stoch_max"] is None and seen["require_mid_above_slow"] is False


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
    assert "SMA20 ↗ SMA99" in n["message"] and "gövde" not in n["message"]   # gövde eleği yok → metinde de yok
    assert "Hedef: +%10" in n["message"] and "Stop: −%8" in n["message"] and "En çok 3 gün" in n["message"]
    assert n["tag"] == "ma-buy-h4-WLDTRY" and n["url"] == "/charts?symbol=WLDTRY&timeframe=4h"
    assert n["target_pct"] == 10.0 and n["expected_price"] == pytest.approx(13.75)
    assert n["exit_profile"] == {"name": "ma_buy_h4", "stop_loss_pct": 8.0, "max_hold_minutes": 4320.0, "trailing": False}
    assert n["horizon_minutes"] == 240 and n["source"] == "ma_buy" and n["notification_key"] == "ma-4h-WLDTRY-1700000000000"


def test_h4_notification_lists_both_rules_with_chart_ma_type(monkeypatch):
    monkeypatch.setattr(config, "MA_BUY_MA_TYPE", "ema", raising=False)
    row = {"symbol": "BTCTRY", "timeframe": "4h", "rules": "fast_cross_mid,mid_cross_slow", "signal_price": 100.0,
           "bar_open_ms": 0, "bar_close_ms": 14_400_000}
    n = notify.build_notification(row, (7, 20, 99), now=14_450.0)
    assert "EMA7 ↗ EMA20 + EMA20 ↗ EMA99" in n["message"] and n["exit_profile"]["name"] == "ma_buy_h4"


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


# ---------------------------------------------------------------- 18:30 kararı: MA99 şartı olmadan 7↗20 kesişimi
def _fast_mid_cross_below_slow():
    """Fiyat uzun süre düşer (MA20 < MA99 kalır), kısa bir sıçrama MA7'yi MA20'nin üstüne çıkarır: MA99 şartıyla sinyal YOK."""
    closes = [200.0 - i * 0.5 for i in range(120)] + [140.0 + i * 1.5 for i in range(8)]
    return closes


def test_fast_cross_mid_without_ma99_gate_fires_only_when_gate_is_off():
    closes = _fast_mid_cross_below_slow()
    gated = ma_buy_signals.detect_ma_buy(closes, (7, 20, 99), use_sma=True, stoch_max=None)
    free = ma_buy_signals.detect_ma_buy(closes, (7, 20, 99), use_sma=True, stoch_max=None, require_mid_above_slow=False)
    assert not any(ma_buy_signals.RULE_FAST_CROSS_MID in h["rules"] for h in gated)
    hits = [h for h in free if ma_buy_signals.RULE_FAST_CROSS_MID in h["rules"]]
    assert hits and hits[-1]["mid"] < hits[-1]["slow"]          # kesişim MA99'un ALTINDA sayıldı


def test_signals_from_bars_h4_default_profile_fires_below_ma99():
    closes = _fast_mid_cross_below_slow()
    bars = _bars(closes)
    rows = tracker.signals_from_bars("AAATRY", "4h", bars, now_ms=10 ** 13, lookback=len(bars), per=(7, 20, 99), use_sma=True,
                                     stoch_max=None, rules_allowed=(ma_buy_signals.RULE_FAST_CROSS_MID,), require_mid_above_slow=False)
    assert rows and all(r["rules"] == ma_buy_signals.RULE_FAST_CROSS_MID for r in rows)
    assert tracker.signals_from_bars("AAATRY", "4h", bars, now_ms=10 ** 13, lookback=len(bars), per=(7, 20, 99), use_sma=True,
                                     stoch_max=None, rules_allowed=(ma_buy_signals.RULE_FAST_CROSS_MID,)) == []


def test_without_gate_short_series_still_detects_before_slow_ma_exists():
    """Yavaş MA (99) henüz yokken bile 7↗20 kesişimi sayılır; slow alanı None."""
    closes = [50.0 - i * 0.2 for i in range(30)] + [44.0 + i * 1.0 for i in range(10)]
    hits = ma_buy_signals.detect_ma_buy(closes, (7, 20, 99), use_sma=True, stoch_max=None, require_mid_above_slow=False)
    assert hits and hits[0]["slow"] is None and hits[0]["rules"] == [ma_buy_signals.RULE_FAST_CROSS_MID]
    assert ma_buy_signals.detect_ma_buy(closes, (7, 20, 99), use_sma=True, stoch_max=None) == []


def test_h4_notification_text_for_fast_mid_cross():
    row = {"symbol": "BTCTRY", "timeframe": "4h", "rules": "fast_cross_mid", "signal_price": 100.0, "bar_open_ms": 0, "bar_close_ms": 14_400_000}
    n = notify.build_notification(row, (7, 20, 99), now=14_450.0)
    assert "SMA7 ↗ SMA20" in n["message"] and "Otonom paper açılır" in n["message"]


# ---------------------------------------------------------------- 19:15 kararı: H4 sembol hacim tabanı (24 sa ≥ 5M TL)
class H4VolumeFloorTests(unittest.IsolatedAsyncioTestCase):
    async def test_filter_by_quote_volume_drops_thin_symbols_and_keeps_order(self):
        rows = [{"symbol": "ATRY", "quoteVolume": "6000000"}, {"symbol": "btry", "quoteVolume": "100"}, {"symbol": "CTRY", "quoteVolume": "bozuk"}]
        with patch.object(tracker, "ticker_24h", AsyncMock(return_value=rows)) as t:
            out = await tracker.filter_by_quote_volume(["ATRY", "BTRY", "CTRY", "DTRY"], 5_000_000.0)
        self.assertEqual(out, ["ATRY"])                     # BTRY ince, CTRY bozuk, DTRY ticker'da yok
        self.assertEqual(t.await_args.args[0], ["ATRY", "BTRY", "CTRY", "DTRY"])

    async def test_filter_by_quote_volume_keeps_all_when_ticker_fails_or_floor_zero(self):
        with patch.object(tracker, "ticker_24h", AsyncMock(side_effect=RuntimeError("ağ"))):
            self.assertEqual(await tracker.filter_by_quote_volume(["ATRY", "BTRY"], 5e6), ["ATRY", "BTRY"])
        with patch.object(tracker, "ticker_24h", AsyncMock()) as t:
            self.assertEqual(await tracker.filter_by_quote_volume(["ATRY"], 0), ["ATRY"])
            t.assert_not_awaited()

    async def test_scan_once_applies_floor_only_to_h4(self):
        scanned: list = []

        async def fake_scan_symbol(symbol, tf, now_ms, sem):
            scanned.append((symbol, tf))
            return 0, []

        rows = [{"symbol": "ATRY", "quoteVolume": "9000000"}, {"symbol": "BTRY", "quoteVolume": "10"}]
        with patch.object(tracker, "active_symbols", AsyncMock(return_value=["ATRY", "BTRY"])), \
             patch.object(tracker, "timeframes", lambda: ["1h", "4h"]), \
             patch.object(tracker, "_scan_symbol", fake_scan_symbol), \
             patch.object(tracker, "ticker_24h", AsyncMock(return_value=rows)):
            await tracker.scan_once(now_ms=10 ** 13)
        self.assertEqual(sorted(scanned), [("ATRY", "1h"), ("ATRY", "4h"), ("BTRY", "1h")])
