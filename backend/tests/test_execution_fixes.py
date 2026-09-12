"""W2 — işlem yürütme / risk denetim düzeltmeleri (2026-09-12).

Kapsanan bulgular: D-01 (kâr kilidi round-trip maliyeti), D-02 (max-hold
planlayıcıya ulaşmıyor), D-03 (talep edilen işlem büyüklüğü yok sayılıyor),
C-06 (rejim bazlı boyutlandırma ölü), D-05 (circuit breaker penceresi +
restart amnezi), I-03 (ATR tekrarı).

Her test, denetimde ÖLÇÜLEN yanlış davranışı da bir "before" iddiasıyla
çivileyerek sabitler; yalnızca yeni davranışı doğrulamak yetmez.
"""
import asyncio
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

os.environ.setdefault("DB_BACKEND", "sqlite")


def _kline(n=60, start=100.0, step=0.1):
    """Deterministik, yeterli uzunlukta (n mum) OHLCV sözlüğü."""
    closes = [start + i * step for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return {"opens": list(closes), "highs": highs, "lows": lows,
            "closes": closes, "volumes": [10.0 + (i % 5) for i in range(n)],
            "timestamps": [i * 60_000 for i in range(n)]}


class _Market:
    """Sığ test marketi: likidite kapısı her zaman geçer."""

    def __init__(self, kline=None):
        kline = kline if kline is not None else _kline(n=2)
        self._kline = kline
        self.tickers = {"BTCTRY": {"symbol": "BTCTRY", "last_price": 100.0,
                                   "timestamp": time.time() * 1000},
                        "TESTTRY": {"symbol": "TESTTRY", "last_price": 100.0,
                                    "timestamp": time.time() * 1000}}
        self.orderflow = {}
        self.klines = {}
        self.ticker_24h = {}

    def get_ticker(self, symbol):
        return self.tickers.get(symbol)

    def get_ut_kline(self, symbol, timeframe=None):
        return self._kline

    def get_orderflow(self, symbol):
        return {"bid_qty": 10.0, "ask_qty": 9.0, "spread_pct": 0.05,
                "bid_price": 99.99, "ask_price": 100.01, "updated_at": time.time()}

    def liquidity_status(self, symbol, order_value, **_kwargs):
        return True, {"checks": {"quote_volume": True, "volume_ratio": True,
                                 "spread": True, "orderbook_depth": True}}

    def data_freshness(self, symbol, timeframe):
        return {"orderbook": {"fresh": True}}


def _new_analyzer(market=None):
    from app.analyzer import ScalpAnalyzer

    return ScalpAnalyzer(market if market is not None else _Market())


# ---------------------------------------------------------------------------
# D-01 — KRİTİK: kâr kilidi yalnızca GİRİŞ komisyonunu yüklüyordu
# ---------------------------------------------------------------------------
class ProfitLockRoundTripCostTests(unittest.IsolatedAsyncioTestCase):
    """analyzer.py kâr kilidi stop'u: gross >= round-trip maliyet olmalı."""

    def _pos(self, entry=12.0, notional=10_000.0):
        return {
            "symbol": "TESTTRY", "strategy": "CHAT_PREDICTION", "side": "LONG",
            "entry_price": entry, "quantity": notional / entry,
            "entry_time": time.time(),
            # +%0.6 görüldü → +%0.5 kilit tetiği aşıldı
            "max_price": entry * 1.006, "min_price": entry,
            "system_stop_price": None,
            "take_profit": entry * 1.02,
            "system_take_profit_price": entry * 1.02,
            "entry_context": {"signal_context": {"no_initial_stop": True,
                                                 "target_pct": 2.0,
                                                 "exit_model": "plan_tp"}},
        }

    async def _run_ladder(self, pos, price):
        """Merdiveni çalıştır; kilit zeminini (system_stop_price) üretir."""
        analyzer = _new_analyzer()
        analyzer.positions = {"TESTTRY": pos}
        analyzer.market = MagicMock()
        analyzer.market.get_ticker = MagicMock(
            return_value={"last_price": price, "timestamp": time.time() * 1000})
        analyzer.market.get_ut_kline = MagicMock(return_value=None)
        close = AsyncMock(return_value={"ok": True})
        with patch.object(analyzer, "close_position", close), \
             patch("app.analyzer.config.MAX_TICKER_AGE_SEC", 3600):
            await analyzer._manage_open_position("TESTTRY", price, "CHAT_PREDICTION")
        return analyzer, close

    async def test_old_single_leg_formula_booked_a_loss(self):
        """ÖLÇÜLEN HATA (before): eski formül 10.000 TRY'de −14.02 TRY net.

        Eski kod: entry*(1 + LOCK/100) + qty_value*COMMISSION_PCT/quantity
        İkinci terim = entry*COMMISSION_PCT → yalnızca GİRİŞ bacağı.
        """
        from app.config import config

        entry, notional = 12.0, 10_000.0
        qty = notional / entry
        old_lock_stop = entry * (1 + config.VELOCITY_PROFIT_LOCK_PCT / 100.0) + entry * config.COMMISSION_PCT
        gross_pct = (old_lock_stop - entry) / entry
        # Round-trip maliyet iki komisyon bacağıdır.
        self.assertAlmostEqual(gross_pct * 100, 0.16, places=6)   # %0.160 üretildi
        self.assertAlmostEqual(config.COMMISSION_PCT * 2 * 100, 0.30, places=6)  # %0.300 gerekiyordu
        net = (old_lock_stop - entry) * qty - (qty * entry * config.COMMISSION_PCT
                                               + qty * old_lock_stop * config.COMMISSION_PCT)
        self.assertAlmostEqual(net, -14.02, places=2)  # denetimle birebir uyumlu
        self.assertLess(net, 0.0, "eski formülün zarar yazdığı çivilenmeli")

    async def test_locked_exit_is_at_least_breakeven_net(self):
        """D-01 after: kilitli çıkış net >= 0 (10.000 TRY notional, %0.15 taker)."""
        from app.config import config

        pos = self._pos()
        entry, qty = pos["entry_price"], pos["quantity"]
        # 1) tetik turu: kilit devreye girer ve zemin yazılır (+%0.6 > +%0.5)
        await self._run_ladder(pos, entry * 1.006)
        self.assertTrue(pos.get("velocity_protection_armed"))
        lock_stop = pos["system_stop_price"]
        self.assertIsNotNone(lock_stop)

        # 2) fiyat tam zemine tick atar → system_stop_loss ile kapanır
        analyzer, close = await self._run_ladder(pos, lock_stop)
        close.assert_awaited_once()
        self.assertEqual(close.await_args.args[2], "system_stop_loss")

        # 3) üretim formülüyle net PnL (_record_trade): İKİ komisyon bacağı
        commission = qty * lock_stop * config.COMMISSION_PCT
        trade = await analyzer._record_trade("TESTTRY", pos, lock_stop,
                                             "system_stop_loss", commission)
        self.assertGreaterEqual(trade["pnl"], 0.0,
                                f"kilitli çıkış zarar yazdı: {trade['pnl']:.4f} TRY")

    async def test_armed_lock_stop_survives_the_next_tick(self):
        """D-01 yan bulgu: -inf (no_initial_stop) geçersiz kılması HER tick'te
        yeniden uygulanıyordu → kilit stop'u kurulduğu tick'ten sonra siliniyor
        ve asla tetiklenmiyordu. Kilit artık kalıcı."""
        pos = self._pos()
        entry = pos["entry_price"]
        await self._run_ladder(pos, entry * 1.006)          # 1. tick: kilit kurulur
        lock_stop = pos["system_stop_price"]
        # 2. tick: zemin üstünde → açık kalır, ama zemin KORUNUR
        _, close = await self._run_ladder(pos, lock_stop + 0.001)
        close.assert_not_awaited()
        self.assertEqual(pos["system_stop_price"], lock_stop)
        # 3. tick: zemine iner → kapanır (eski kodda burada zemin -inf'ti)
        _, close = await self._run_ladder(pos, lock_stop)
        close.assert_awaited_once()

    async def test_lock_stop_covers_both_commission_legs(self):
        """Kilit zemini round-trip maliyetten (2 × komisyon) aşağı olamaz."""
        from app.config import config

        pos = self._pos()
        entry = pos["entry_price"]
        await self._run_ladder(pos, entry * 1.006)
        gross_fraction = (pos["system_stop_price"] - entry) / entry
        round_trip = config.COMMISSION_PCT * 2
        self.assertGreaterEqual(
            gross_fraction, round_trip,
            f"kilit gross'u {gross_fraction*100:.4f}% < round-trip {round_trip*100:.4f}%")

    async def test_lock_stop_uses_canonical_helper_not_a_new_formula(self):
        """Tek doğruluk kaynağı config.min_net_exit_pct — formül uydurulmadı."""
        from app.config import config

        pos = self._pos()
        entry = pos["entry_price"]
        await self._run_ladder(pos, entry * 1.006)
        expected_fraction = max(config.VELOCITY_PROFIT_LOCK_PCT / 100.0,
                                config.min_net_exit_pct(pos["quantity"] * entry))
        self.assertAlmostEqual(pos["system_stop_price"],
                               entry * (1 + expected_fraction), places=9)


# ---------------------------------------------------------------------------
# D-02 — max_hold_sec planlayıcıya ulaşmıyordu (plan_hold = 0)
# ---------------------------------------------------------------------------
class PlannedMaxHoldTests(unittest.IsolatedAsyncioTestCase):
    def test_fallback_is_configured_velocity_max_hold_in_seconds(self):
        """Çağıran göndermezse VELOCITY_MAX_HOLD_MIN(30dk) → 1800 SANİYE."""
        from app.analyzer import ScalpAnalyzer

        with patch("app.analyzer.config.VELOCITY_MAX_HOLD_MIN", 30):
            self.assertEqual(ScalpAnalyzer._planned_max_hold_sec(None), 1800)
            self.assertEqual(ScalpAnalyzer._planned_max_hold_sec(0), 1800)
            self.assertEqual(ScalpAnalyzer._planned_max_hold_sec("boom"), 1800)

    def test_caller_supplied_value_wins(self):
        """Chat tahmin otomatının 900 sn planı olduğu gibi korunur."""
        from app.analyzer import ScalpAnalyzer

        self.assertEqual(ScalpAnalyzer._planned_max_hold_sec(900), 900)
        self.assertEqual(ScalpAnalyzer._planned_max_hold_sec(1800.0), 1800)

    async def test_chat_prediction_position_gets_a_max_hold_without_caller(self):
        """before: velocity_max_hold_sec yazılmıyordu → plan_hold 0 → ölü ayar."""
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(_Market())
        with patch("app.analyzer.database.load_positions", new=AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.database.save_signal", new=AsyncMock()), \
             patch("app.analyzer.database.commit_open_position", new=AsyncMock()), \
             patch("app.analyzer.config.CALIBRATION_SIZING_ENABLED", False), \
             patch("app.analyzer.config.REGIME_SIZING_ENABLED", False), \
             patch("app.analyzer.config.CORRELATION_CAP_ENABLED", False), \
             patch("app.analyzer.config.VELOCITY_MAX_HOLD_MIN", 30):
            await analyzer.open_position(
                "BTCTRY", 100.0, "LONG", "CHAT_PREDICTION",
                take_profit_pct=0.02,
                entry_context_extra={"no_initial_stop": True})
        pos = analyzer.positions["BTCTRY"]
        self.assertEqual(pos["velocity_max_hold_sec"], 1800)
        self.assertEqual(pos["entry_context"]["max_hold_sec"], 1800)

    async def test_ladder_closes_on_chat_plan_max_hold(self):
        """Artık planlanan süre dolunca chat_plan_max_hold ile kapanır."""
        pos = {
            "symbol": "TESTTRY", "strategy": "CHAT_PREDICTION", "side": "LONG",
            "entry_price": 100.0, "quantity": 1.0,
            "entry_time": time.time() - 1801.0,
            "max_price": 100.0, "min_price": 100.0,
            "system_stop_price": None, "velocity_max_hold_sec": 1800,
            "entry_context": {"signal_context": {"no_initial_stop": True},
                              "max_hold_sec": 1800},
        }
        analyzer = _new_analyzer()
        analyzer.positions = {"TESTTRY": pos}
        analyzer.market = MagicMock()
        analyzer.market.get_ticker = MagicMock(
            return_value={"last_price": 100.0, "timestamp": time.time() * 1000})
        analyzer.market.get_ut_kline = MagicMock(return_value=None)
        close = AsyncMock(return_value={"ok": True})
        with patch.object(analyzer, "close_position", close), \
             patch("app.analyzer.config.MAX_TICKER_AGE_SEC", 3600), \
             patch("app.analyzer.config.EARLY_FAILURE_SEC", 10 ** 9), \
             patch("app.analyzer.config.STALE_POSITION_SEC", 10 ** 9):
            await analyzer._manage_open_position("TESTTRY", 100.0, "CHAT_PREDICTION")
        close.assert_awaited_once()
        self.assertEqual(close.await_args.args[2], "chat_plan_max_hold")


# ---------------------------------------------------------------------------
# D-03 — talep edilen işlem büyüklüğü (yalnızca LLM_PAPER'da onurlandırılıyordu)
# ---------------------------------------------------------------------------
class RequestedOrderValueTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_prediction_honours_requested_value(self):
        """before: 5000 TRY isteyen velocity 998 TRY (%10) alıyordu."""
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        analyzer = ScalpAnalyzer(_Market())
        with patch("app.analyzer.database.load_positions", new=AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.database.save_signal", new=AsyncMock()), \
             patch("app.analyzer.database.commit_open_position", new=AsyncMock()), \
             patch("app.analyzer.config.CALIBRATION_SIZING_ENABLED", False), \
             patch("app.analyzer.config.REGIME_SIZING_ENABLED", False), \
             patch("app.analyzer.config.CORRELATION_CAP_ENABLED", False), \
             patch("app.analyzer.config.ORDER_PCT", 0.10), \
             patch("app.analyzer.config.VELOCITY_AUTO_BALANCE_PCT", 50.0):
            sig = await analyzer.open_position(
                "BTCTRY", 100.0, "LONG", "CHAT_PREDICTION", 5_000.0,
                take_profit_pct=0.02,
                entry_context_extra={"no_initial_stop": True})
        self.assertEqual(sig["action"], "BUY_SIGNAL")
        pos = analyzer.positions["BTCTRY"]
        used_value = pos["quantity"] * pos["entry_price"]
        # Talep edilen 5000 TRY, nakit (10000/1.0015) altında → birebir uygulanır.
        self.assertAlmostEqual(used_value, 5_000.0, places=6)
        # Raporlanan değer fiilî kullanılan değerle aynı kaynaktan gelir.
        self.assertAlmostEqual(sig["order_value_try"], used_value, places=6)
        self.assertAlmostEqual(pos["entry_context"]["order_value_try"], used_value, places=6)
        self.assertGreater(used_value, 10_000.0 / (1 + config.COMMISSION_PCT) * 0.10)

    async def test_requested_value_is_capped_by_cash_and_commission(self):
        """Talep nakitten büyükse nakit + giriş komisyonu sınırına düşer."""
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        analyzer = ScalpAnalyzer(_Market())
        with patch("app.analyzer.database.load_positions", new=AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=1_000.0)), \
             patch("app.analyzer.database.save_signal", new=AsyncMock()), \
             patch("app.analyzer.database.commit_open_position", new=AsyncMock()), \
             patch("app.analyzer.config.CALIBRATION_SIZING_ENABLED", False), \
             patch("app.analyzer.config.REGIME_SIZING_ENABLED", False), \
             patch("app.analyzer.config.CORRELATION_CAP_ENABLED", False):
            await analyzer.open_position("BTCTRY", 100.0, "LONG", "CHAT_PREDICTION",
                                         50_000.0, take_profit_pct=0.02,
                                         entry_context_extra={"no_initial_stop": True})
        pos = analyzer.positions["BTCTRY"]
        self.assertAlmostEqual(pos["quantity"] * pos["entry_price"],
                               1_000.0 / (1 + config.COMMISSION_PCT), places=6)

    async def test_preflight_mirrors_the_writer_rule(self):
        """Ön kontrol de talebi yok saymamalı (llm_chat.py:1365 bu yolu kullanır)."""
        from app.analyzer import ScalpAnalyzer

        analyzer = ScalpAnalyzer(_Market())
        with patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.config.ORDER_PCT", 0.10), \
             patch("app.analyzer.config.VOLATILITY_SIZING_ENABLED", False):
            eligible, details = await analyzer.entry_liquidity_preflight(
                "BTCTRY", "CHAT_PREDICTION", 5_000.0)
        self.assertTrue(eligible)
        self.assertAlmostEqual(details["order_value_try"], 5_000.0, places=6)

    async def test_no_request_still_uses_order_pct(self):
        """Talep yoksa eski yüzde yolu değişmeden çalışır."""
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        analyzer = ScalpAnalyzer(_Market())
        with patch("app.analyzer.database.load_positions", new=AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.database.save_signal", new=AsyncMock()), \
             patch("app.analyzer.database.commit_open_position", new=AsyncMock()), \
             patch("app.analyzer.config.CALIBRATION_SIZING_ENABLED", False), \
             patch("app.analyzer.config.REGIME_SIZING_ENABLED", False), \
             patch("app.analyzer.config.CORRELATION_CAP_ENABLED", False), \
             patch("app.analyzer.config.ORDER_PCT", 0.10):
            await analyzer.open_position("BTCTRY", 100.0, "LONG", "CHAT_PREDICTION",
                                         take_profit_pct=0.02,
                                         entry_context_extra={"no_initial_stop": True})
        pos = analyzer.positions["BTCTRY"]
        self.assertAlmostEqual(pos["quantity"] * pos["entry_price"],
                               10_000.0 / (1 + config.COMMISSION_PCT) * 0.10, places=6)


# ---------------------------------------------------------------------------
# C-06 — rejim bazlı boyutlandırma (S4) ölüydü
# ---------------------------------------------------------------------------
class RegimeSizingTests(unittest.IsolatedAsyncioTestCase):
    def test_regime_lives_under_methodologies_not_top_level(self):
        """before: `snap.get("regime")` her zaman {} dönerdi."""
        from app.technical_analysis import calculate_snapshot

        snap = calculate_snapshot("BTCTRY", 100.0, {"5m": _kline()}, None, 0, 1000, "5m")
        self.assertTrue(snap.get("data_ready"))
        self.assertIsNone(snap.get("regime"), "üst seviye 'regime' anahtarı yok")
        regime = ((snap.get("methodologies") or {}).get("regime") or {})
        self.assertTrue(regime.get("name"))
        self.assertIsNotNone(regime.get("confidence"))

    def test_calculate_snapshot_requires_three_positional_args(self):
        """before: `_cs(k)` tek argümanla çağrılıyordu → TypeError yutuluyordu."""
        import inspect

        from app.technical_analysis import calculate_snapshot

        params = list(inspect.signature(calculate_snapshot).parameters.values())
        required = [p.name for p in params
                    if p.default is inspect.Parameter.empty
                    and p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)]
        self.assertEqual(required[:3], ["symbol", "price", "klines"])

    async def test_regime_multiplier_shrinks_the_order(self):
        """S4 gerçekten çalışıyor: mean_reversion + bull_quiet → ×0.5."""
        from app.analyzer import ScalpAnalyzer
        from app.config import config

        fake_snapshot = {"data_ready": True,
                         "methodologies": {"regime": {"name": "bull_quiet",
                                                      "confidence": 0.9}}}
        analyzer = ScalpAnalyzer(_Market(_kline()))
        with patch("app.analyzer.database.load_positions", new=AsyncMock(return_value={})), \
             patch("app.analyzer.database.get_wallet_balance", new=AsyncMock(return_value=10_000.0)), \
             patch("app.analyzer.database.save_signal", new=AsyncMock()), \
             patch("app.analyzer.database.commit_open_position", new=AsyncMock()), \
             patch("app.analyzer.calculate_snapshot", return_value=fake_snapshot) as snap_mock, \
             patch("app.calibration.strategy_style_of", return_value="mean_reversion"), \
             patch("app.analyzer.config.CALIBRATION_SIZING_ENABLED", False), \
             patch("app.analyzer.config.REGIME_SIZING_ENABLED", True), \
             patch("app.analyzer.config.CORRELATION_CAP_ENABLED", False), \
             patch("app.analyzer.config.ORDER_PCT", 0.10):
            await analyzer.open_position("BTCTRY", 100.0, "LONG", "CHAT_PREDICTION",
                                         take_profit_pct=0.02,
                                         entry_context_extra={"no_initial_stop": True})
        # İmza doğru: ilk çağrı rejim sondasıdır → (symbol, price, {tf: kline}, ...)
        self.assertGreaterEqual(snap_mock.call_count, 1)
        probe = snap_mock.call_args_list[0]
        self.assertEqual(probe.args[0], "BTCTRY")
        self.assertEqual(probe.args[1], 100.0)
        self.assertEqual(list(probe.args[2]), ["1m"])  # {timeframe: kline}
        self.assertEqual(probe.args[6], "1m")          # primary_timeframe
        pos = analyzer.positions["BTCTRY"]
        base = 10_000.0 / (1 + config.COMMISSION_PCT) * 0.10
        self.assertAlmostEqual(pos["quantity"] * pos["entry_price"], base * 0.5, places=4)


# ---------------------------------------------------------------------------
# D-05 — circuit breaker penceresi + restart amnezi
# ---------------------------------------------------------------------------
class CircuitBreakerWindowTests(unittest.TestCase):
    def _breaker(self):
        from app.circuit_breaker import StrategyCircuitBreaker

        b = StrategyCircuitBreaker()
        b._loaded = True
        return b

    def test_window_larger_than_twenty_still_pauses(self):
        """before: limit sabit 20 idi → window>20 iken ASLA duraklatmazdı."""
        import app.database as database

        b = self._breaker()
        seen = {}

        async def fake_trades(limit=None, strategy=None):
            seen["limit"] = limit
            return [{"pnl": -2.0}] * 50

        with patch.object(database, "get_trades", new=fake_trades), \
             patch.object(database, "set_llm_setting", new=AsyncMock()), \
             patch.object(database, "save_signal", new=AsyncMock()), \
             patch("app.config.config.STRATEGY_BREAKER_WINDOW", 50, create=True):
            detail = asyncio.run(b.evaluate_after_close("PUMP_MONITOR"))
        self.assertIsNotNone(detail, "window=50 iken breaker çalışmalı")
        self.assertTrue(b.is_paused("PUMP_MONITOR"))
        self.assertGreaterEqual(seen["limit"], 50,
                                "get_trades limiti pencereden küçük olamaz")

    def test_window_of_one_hundred_still_pauses(self):
        import app.database as database

        b = self._breaker()
        with patch.object(database, "get_trades",
                          new=lambda limit=None, strategy=None: _coro([{"pnl": -2.0}] * 100)), \
             patch.object(database, "set_llm_setting", new=AsyncMock()), \
             patch.object(database, "save_signal", new=AsyncMock()), \
             patch("app.config.config.STRATEGY_BREAKER_WINDOW", 100, create=True):
            detail = asyncio.run(b.evaluate_after_close("PUMP_MONITOR"))
        self.assertIsNotNone(detail)
        self.assertTrue(b.is_paused("PUMP_MONITOR"))

    def test_is_paused_async_loads_db_state(self):
        """before: senkron is_paused restart sonrası False dönerdi (amnezi)."""
        import app.database as database

        from app.circuit_breaker import StrategyCircuitBreaker

        stored = {"PUMP_MONITOR": {"paused_at": time.time(),
                                   "reason": "rolling_expectancy_below_floor"}}
        b = StrategyCircuitBreaker()
        with patch.object(database, "get_llm_setting",
                          new=lambda key, default="{}": _coro(
                              __import__("json").dumps(stored))):
            self.assertFalse(b.is_paused("PUMP_MONITOR"),
                             "senkron görünüm DB'yi yüklemez (bilinçli)")
            self.assertTrue(asyncio.run(b.is_paused_async("PUMP_MONITOR")),
                            "restart sonrası pause DB'den okunmalı")


def _coro(value):
    async def _inner(*_a, **_kw):
        return value
    return _inner()


# ---------------------------------------------------------------------------
# I-03 — ATR tekrarı
# ---------------------------------------------------------------------------
class AtrSingleSourceTests(unittest.TestCase):
    def test_analyzer_atr_delegates_to_canonical_helper(self):
        from app.analyzer import ScalpAnalyzer
        import app.analyzer as analyzer_module

        kline = _kline(n=40)
        with patch.object(analyzer_module, "_atr", return_value=1.25) as atr_mock:
            got = ScalpAnalyzer.calculate_atr(None, kline, 14)
        atr_mock.assert_called_once()
        self.assertEqual(got, 1.25)

    def test_analyzer_atr_matches_canonical_helper_exactly(self):
        from app.analyzer import ScalpAnalyzer
        from app.technical_analysis import _atr

        for n in (15, 20, 60, 200):
            kline = _kline(n=n)
            for period in (2, 7, 11, 14, 21):
                self.assertEqual(
                    ScalpAnalyzer.calculate_atr(None, kline, period),
                    _atr(kline["highs"], kline["lows"], kline["closes"], period),
                    f"ATR ayrışması: n={n} period={period}")

    def test_short_series_returns_none(self):
        from app.analyzer import ScalpAnalyzer

        kline = _kline(n=10)
        self.assertIsNone(ScalpAnalyzer.calculate_atr(None, kline, 14))


if __name__ == "__main__":
    unittest.main()
