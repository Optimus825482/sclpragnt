import time
import asyncio
import numpy as np
import uuid
from app.config import config
from app.technical_analysis import calculate_snapshot, _adx, _stochastic, _macd, _mfi
from app.binance_tr_public import orderbook
from app import database
from app import agent_learning

class ScalpAnalyzer:
    def __init__(self, market):
        self.market = market
        self.positions = {}
        self._last_signal_lengths = {}
        self._cooldown_until = {}
        self._timeout_block_until = {}
        self._hard_stop_block_until = {}
        self._open_position_lock = asyncio.Lock()
        self.pending_orders = []

    def max_open_positions(self):
        """0 removes the global cap; financial/liquidity guards remain active."""
        configured = int(config.MAX_OPEN_POSITIONS)
        return float("inf") if configured <= 0 else configured

    @staticmethod
    def _bb_mfi_layers_net_profitable(position, price):
        """Every stored pyramid layer must clear round-trip fees at this price."""
        layers = position.get("entry_layers") or []
        if not layers:
            return False
        for layer in layers:
            quantity = float(layer.get("quantity") or 0)
            entry = float(layer.get("entry_price") or 0)
            if quantity <= 0 or entry <= 0:
                return False
            proceeds = quantity * float(price) * (1 - config.COMMISSION_PCT)
            cost = quantity * entry * (1 + config.COMMISSION_PCT)
            if proceeds <= cost:
                return False
        return True

    async def load_state(self):
        self.positions = await database.load_positions()
        self.pending_orders = await database.load_paper_orders()

    async def _idempotent_order_replay(self, duplicate):
        status = str(duplicate.get("status") or "UNKNOWN").upper()
        if status == "PROCESSING":
            symbol = str(duplicate.get("symbol") or "").upper()
            position = self.positions.get(symbol)
            created_at = float(duplicate.get("created_at") or 0)
            if position and float(position.get("entry_time") or 0) >= created_at - 1:
                duplicate.update(status="FILLED", filled_at=position.get("entry_time") or time.time(),
                                 updated_at=time.time(), recovered=True,
                                 result={"action": "BUY_SIGNAL", "trade_id": position.get("trade_id")})
                await database.save_paper_order(duplicate)
                status = "FILLED"
            elif created_at and time.time() - created_at > 30:
                duplicate.update(status="FAILED", updated_at=time.time(),
                                 error="interrupted_before_terminal_persist")
                await database.save_paper_order(duplicate)
                status = "FAILED"
        return {"ok": status in {"OPEN", "PENDING", "FILLED"}, "paper_only": True,
                "idempotent_replay": True, "status": status, "order": duplicate}

    async def place_paper_order(self, order):
        """Execute or queue an exchange-like order entirely in paper trading."""
        client_request_id = str(order.get("client_request_id") or "").strip() or None
        if client_request_id:
            duplicate = next((item for item in self.pending_orders if item.get("client_request_id") == client_request_id), None)
            if not duplicate:
                duplicate = await database.get_paper_order_by_client_request_id(client_request_id)
            if duplicate:
                return await self._idempotent_order_replay(duplicate)
        order_type = str(order.get("order_type", "MARKET")).upper()
        if order_type not in {"MARKET", "LIMIT", "STOP_LIMIT", "STOP_MARKET", "OCO"}:
            return {"ok": False, "error": "Desteklenmeyen paper emir türü"}
        symbol = str(order.get("symbol") or "").replace("_", "").upper()
        ticker = self.market.get_ticker(symbol) if self.market else None
        price = float(order.get("price") or (ticker or {}).get("last_price") or 0)
        if not symbol or price <= 0: return {"ok": False, "error": "Geçerli sembol ve fiyat gerekli"}
        if order_type == "MARKET":
            async with self._open_position_lock:
                if client_request_id:
                    duplicate = await database.get_paper_order_by_client_request_id(client_request_id)
                    if duplicate:
                        return await self._idempotent_order_replay(duplicate)
                reservation = {**order, "symbol": symbol, "order_type": order_type, "status": "PROCESSING",
                               "created_at": time.time(), "updated_at": time.time(), "reference_price": price,
                               "order_id": uuid.uuid4().hex, "client_request_id": client_request_id}
                await database.save_paper_order(reservation)
            try:
                result = await self.open_position(symbol, price, str(order.get("side", "LONG")).upper(), "LLM_PAPER", order.get("order_value_try"), order.get("stop_loss_pct"), order.get("take_profit_pct"), order.get("max_hold_seconds"))
            except asyncio.CancelledError:
                reservation.update(status="FAILED", updated_at=time.time(), error="execution_cancelled")
                await asyncio.shield(database.save_paper_order(reservation))
                raise
            except Exception as exc:
                reservation.update(status="FAILED", updated_at=time.time(), error=f"{type(exc).__name__}: {exc}")
                await database.save_paper_order(reservation)
                return {"ok": False, "paper_only": True, "status": "FAILED", "order": reservation,
                        "error": reservation["error"]}
            succeeded = self._paper_order_succeeded(result, order.get("side", "BUY"))
            reservation.update({"status": "FILLED" if succeeded else "REJECTED", "updated_at": time.time(), "result": result})
            if succeeded: reservation["filled_at"] = time.time()
            await database.save_paper_order(reservation)
            return {"ok": succeeded, "paper_only": True, "status": reservation["status"], "order": reservation, "result": result}
        async with self._open_position_lock:
            if client_request_id:
                duplicate = next((item for item in self.pending_orders if item.get("client_request_id") == client_request_id), None)
                if duplicate:
                    return {"ok": True, "paper_only": True, "idempotent_replay": True, "status": duplicate.get("status"), "order": duplicate}
            pending = {**order, "symbol": symbol, "status": "OPEN", "created_at": time.time(), "reference_price": price, "order_id": uuid.uuid4().hex, "client_request_id": client_request_id}
            self.pending_orders.append(pending)
            await database.save_paper_order(pending)
        return {"ok": True, "paper_only": True, "status": "PENDING", "order": pending}

    def get_paper_order(self, order_id):
        return next((order for order in self.pending_orders if order.get("order_id") == str(order_id)), None)

    def list_paper_orders(self, symbol=None, status=None):
        rows = self.pending_orders
        if symbol: rows = [row for row in rows if row.get("symbol") == str(symbol).replace("_", "").upper()]
        if status: rows = [row for row in rows if row.get("status") == str(status).upper()]
        return rows

    async def cancel_paper_order(self, order_id):
        order = self.get_paper_order(order_id)
        if not order: return {"ok": False, "error": "Paper emir bulunamadı"}
        if order.get("status") != "OPEN": return {"ok": False, "error": "Sadece açık emir iptal edilebilir", "order": order}
        order["status"] = "CANCELLED"; order["cancelled_at"] = time.time()
        await database.save_paper_order(order)
        return {"ok": True, "paper_only": True, "order": order}

    async def modify_paper_order(self, order_id, changes):
        order = self.get_paper_order(order_id)
        if not order: return {"ok": False, "error": "Paper emir bulunamadı"}
        if order.get("status") != "OPEN": return {"ok": False, "error": "Sadece açık emir güncellenebilir", "order": order}
        allowed = {"price", "limit_price", "stop_price", "take_profit_price", "order_value_try", "stop_loss_pct", "take_profit_pct", "max_hold_seconds"}
        for key, value in (changes or {}).items():
            if key in allowed: order[key] = value
        order["updated_at"] = time.time()
        await database.save_paper_order(order)
        return {"ok": True, "paper_only": True, "order": order}

    async def _evaluate_pending_orders(self, symbol, price):
        for order in list(self.pending_orders):
            if order.get("symbol") != symbol or order.get("status") != "OPEN": continue
            side = str(order.get("side", "BUY")).upper(); order_type = str(order.get("order_type", "LIMIT")).upper()
            stop = float(order.get("stop_price") or 0); limit = float(order.get("limit_price") or order.get("price") or 0)
            if order_type == "OCO":
                take_profit_price = float(order.get("take_profit_price") or order.get("limit_price") or 0)
                take_profit_hit = price >= take_profit_price if side in {"SELL", "SHORT"} else price <= take_profit_price
                stop_hit = price <= stop if side in {"SELL", "SHORT"} else price >= stop
                triggered = take_profit_hit or stop_hit
                if not triggered: continue
                execution_price = price
                reason = "paper_oco_stop" if stop_hit else "paper_oco_take_profit"
                result = await self.close_position(symbol, execution_price, reason) if side in {"SELL", "SHORT"} and symbol in self.positions else await self.open_position(symbol, execution_price, "LONG", "LLM_PAPER", order.get("order_value_try"), order.get("stop_loss_pct"), order.get("take_profit_pct"), order.get("max_hold_seconds"))
                succeeded = self._paper_order_succeeded(result, side)
                order["status"] = "FILLED" if succeeded else "REJECTED"
                if succeeded: order["filled_at"] = time.time()
                await database.save_paper_order(order)
                if succeeded:
                    for other in self.pending_orders:
                        if other.get("oco_group") == order.get("oco_group") and other is not order:
                            other["status"] = "CANCELLED"; other["cancelled_at"] = time.time(); await database.save_paper_order(other)
                continue
            triggered = (price <= limit if side in {"BUY", "LONG"} else price >= limit) if order_type == "LIMIT" else (price <= stop if side in {"SELL", "SHORT"} else price >= stop)
            if order_type == "STOP_LIMIT" and triggered: triggered = price <= limit if side in {"SELL", "SHORT"} else price >= limit
            if not triggered: continue
            if order_type == "STOP_LIMIT" and limit <= 0: continue
            execution_price = price if order_type in {"STOP_MARKET", "OCO"} else limit
            if side in {"BUY", "LONG"}:
                result = await self.open_position(symbol, execution_price, "LONG", "LLM_PAPER", order.get("order_value_try"), order.get("stop_loss_pct"), order.get("take_profit_pct"), order.get("max_hold_seconds"))
            else:
                result = await self.close_position(symbol, execution_price, f"paper_{order_type.lower()}") if symbol in self.positions else None
            succeeded = self._paper_order_succeeded(result, side)
            order["status"] = "FILLED" if succeeded else "REJECTED"
            if succeeded: order["filled_at"] = time.time()
            await database.save_paper_order(order)
            if order_type == "OCO":
                for other in self.pending_orders:
                    if other.get("oco_group") == order.get("oco_group") and other is not order: other["status"] = "CANCELLED"

    @staticmethod
    def _paper_order_succeeded(result, side):
        action = str((result or {}).get("action", "")).upper()
        return action.startswith("CLOSE") if str(side).upper() in {"SELL", "SHORT"} else action == "BUY_SIGNAL"

    def _current_bar(self, symbol, timeframe):
        if not self.market:
            return None
        kline = self.market.get_ut_kline(symbol, timeframe)
        times = kline.get("times", [])
        return len(times) - 1 if times else len(kline.get("closes", [])) - 1

    def _reentry_block_reason(self, symbol, timeframe):
        now = time.time()
        for store, reason in (
            (self._timeout_block_until, "timeout_reentry_block"),
            (self._hard_stop_block_until, "hard_stop_reentry_block"),
        ):
            blocked_until = float(store.get(symbol, 0) or 0)
            if blocked_until > now:
                return reason
            store.pop(symbol, None)
        current_bar = self._current_bar(symbol, timeframe)
        cooldown_bar = self._cooldown_until.get(symbol)
        if cooldown_bar is not None and current_bar is not None:
            if current_bar < cooldown_bar:
                return "bar_cooldown"
            self._cooldown_until.pop(symbol, None)
        return None

    def calculate_atr(self, kline, period=11):
        highs = kline.get("highs", [])
        lows = kline.get("lows", [])
        closes = kline.get("closes", [])
        if len(closes) < period + 1: return None
        trs = []
        for i in range(len(closes) - period, len(closes)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        return float(np.mean(trs))

    def heikin_ashi(self, kline):
        # HA mumlarını döndür: (open, high, low, close) listeleri — uzunluk azalır
        opens = kline.get("opens", [])
        highs = kline.get("highs", [])
        lows = kline.get("lows", [])
        closes = kline.get("closes", [])
        n = len(closes)
        if n == 0: return [], [], [], []
        ha_open = [(opens[0] + closes[0]) / 2]  # İlk HA open doğru hesaplanmalı
        ha_close = []
        ha_high = []
        ha_low = []
        for i in range(n):
            c = (opens[i] + highs[i] + lows[i] + closes[i]) / 4
            ha_close.append(c)
            o = ha_open[i]
            ha_high.append(max(highs[i], o, c))
            ha_low.append(min(lows[i], o, c))
            if i < n - 1:
                ha_open.append((o + c) / 2)
        return ha_open, ha_high, ha_low, ha_close

    def ut_bot_signal(self, kline):
        """UT Bot trailing stop sinyali. Döner: "buy"/"sell"/None"""
        closes = kline.get("closes", [])
        if len(closes) < config.UT_ATR_PERIOD + 5:
            return None

        if config.UT_HEIKIN_ASHI:
            _, _, _, src = self.heikin_ashi(kline)
        else:
            src = closes

        atr = self.calculate_atr(kline, config.UT_ATR_PERIOD)
        if not atr: return None
        n_loss = config.UT_KEY_VALUE * atr

        # xATRTrailingStop serisi
        stop = [0.0] * len(src)
        for i in range(len(src)):
            s = src[i]
            prev_prev = stop[i-1] if i > 0 else 0.0
            if i == 0:
                stop[i] = s - n_loss
                continue
            prev_src = src[i-1]
            if s > prev_prev and prev_src > prev_prev:
                stop[i] = max(prev_prev, s - n_loss)
            elif s < prev_prev and prev_src < prev_prev:
                stop[i] = min(prev_prev, s + n_loss)
            elif s > prev_prev:
                stop[i] = s - n_loss
            else:
                stop[i] = s + n_loss

        # pos serisi
        pos = [0] * len(src)
        for i in range(1, len(src)):
            prev_src = src[i-1]
            prev_stop = stop[i-1]
            s = src[i]
            if prev_src < prev_stop and s > prev_stop:
                pos[i] = 1
            elif prev_src > prev_stop and s < prev_stop:
                pos[i] = -1
            else:
                pos[i] = pos[i-1]

        # ema(src,1) = src — crossover mantığı: önceki bar stop'un altında, şimdi üstünde
        above = src[-1] > stop[-1] and src[-2] <= stop[-2] if len(src) > 1 else False
        below = src[-1] < stop[-1] and src[-2] >= stop[-2] if len(src) > 1 else False
        buy = src[-1] > stop[-1] and above
        sell = src[-1] < stop[-1] and below

        if buy: return "buy"
        if sell: return "sell"
        return None

    def calculate_ema(self, prices, period):
        if len(prices) < period: return None
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        return float(np.convolve(prices, weights, mode='valid')[-1])

    def calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1: return None
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calculate_crsi(self, prices, rsi_period=3, streak_period=2, rank_period=100):
        """Connors RSI: kısa RSI + streak RSI + ROC percentile rank (0-100)."""
        if len(prices) < rank_period + rsi_period + streak_period + 2:
            return None
        price_rsi = self.calculate_rsi(prices, rsi_period)
        streaks = []
        streak = 0
        for i in range(1, len(prices)):
            if prices[i] > prices[i - 1]: streak = max(streak, 0) + 1
            elif prices[i] < prices[i - 1]: streak = min(streak, 0) - 1
            else: streak = 0
            streaks.append(streak)
        streak_rsi = self.calculate_rsi(streaks, streak_period)
        roc = np.diff(prices) / np.array(prices[:-1]) * 100
        current = roc[-1]
        sample = roc[-rank_period:]
        percentile = float(np.sum(sample < current) / len(sample) * 100)
        if price_rsi is None or streak_rsi is None: return None
        return float((price_rsi + streak_rsi + percentile) / 3)

    def calculate_bollinger_bands(self, prices, period=20, std_dev: float = 2.0):
        if len(prices) < period: return None
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        bandwidth = (upper - lower) / sma if sma != 0 else 0
        return {"upper": upper, "middle": sma, "lower": lower, "bandwidth": bandwidth}

    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        if len(prices) < slow + signal: return None, None, None
        ema_fast = np.convolve(prices, np.exp(np.linspace(-1., 0., fast)) / np.sum(np.exp(np.linspace(-1., 0., fast))), mode='valid')
        ema_slow = np.convolve(prices, np.exp(np.linspace(-1., 0., slow)) / np.sum(np.exp(np.linspace(-1., 0., slow))), mode='valid')
        ema_fast = ema_fast[-len(ema_slow):]
        macd_line = ema_fast - ema_slow
        if len(macd_line) < signal: return None, None, None
        sig_weights = np.exp(np.linspace(-1., 0., signal))
        sig_weights /= sig_weights.sum()
        signal_line = np.convolve(macd_line, sig_weights, mode='valid')
        macd_line = macd_line[-len(signal_line):]
        hist = macd_line - signal_line
        return macd_line[-1], signal_line[-1], hist[-1]

    # --- YARDIMCI: Chande Momentum (CMO) Hesaplama ---
    def calculate_cmo(self, prices, period=9):
        if len(prices) < period + 1: return None
        deltas = np.diff(prices[-period-1:])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        sum_gains = np.sum(gains)
        sum_losses = np.sum(losses)

        if (sum_gains + sum_losses) == 0: return 0.0
        return 100 * (sum_gains - sum_losses) / (sum_gains + sum_losses)

    # --- EK STRATEJİLER ---
    def strategy_bollinger_squeeze(self, kline):
        closes = kline.get("closes", [])
        volumes = kline.get("volumes", [])
        if len(closes) < config.SQUEEZE_LOOKBACK: return None
        price = closes[-1]
        current_vol = volumes[-1]
        avg_vol = np.mean(volumes[-10:])
        bb = self.calculate_bollinger_bands(closes, config.BB_PERIOD, config.BB_STD_DEV)
        if not bb: return None
        historical_bws = []
        for i in range(2, config.SQUEEZE_LOOKBACK + 1):
            if len(closes) >= config.BB_PERIOD + i:
                hist_bb = self.calculate_bollinger_bands(closes[-i:-i+config.BB_PERIOD], config.BB_PERIOD, config.BB_STD_DEV)
                if hist_bb: historical_bws.append(hist_bb["bandwidth"])
        if not historical_bws: return None
        min_bw = min(historical_bws)
        is_squeeze = bb["bandwidth"] <= min_bw * 1.1
        is_volume_spike = current_vol > avg_vol * 1.5

        if is_squeeze and is_volume_spike and price > bb["upper"]: return "buy"
        if is_squeeze and is_volume_spike and price < bb["lower"]: return "sell"
        return None

    def strategy_ema_pullback(self, kline):
        closes = kline.get("closes", [])
        if len(closes) < config.EMA_TREND + 5: return None
        price = closes[-1]
        ema9 = self.calculate_ema(closes, config.EMA_SHORT)
        ema21 = self.calculate_ema(closes, config.EMA_MID)
        ema50 = self.calculate_ema(closes, config.EMA_TREND)
        rsi = self.calculate_rsi(closes, config.RSI_PERIOD)
        if ema9 is None or ema21 is None or ema50 is None or rsi is None: return None

        is_uptrend = ema9 > ema21 > ema50
        pulled_back = closes[-2] <= ema21 and price > ema21
        rsi_cooled = 40 <= rsi <= 55
        if is_uptrend and pulled_back and rsi_cooled: return "buy"

        if ema9 < ema21: return "sell"
        return None

    def strategy_vwap_macd(self, kline):
        closes = kline.get("closes", [])
        highs = kline.get("highs", [])
        lows = kline.get("lows", [])
        volumes = kline.get("volumes", [])
        if len(closes) < config.VWAP_PERIOD + config.MACD_SLOW: return None
        price = closes[-1]
        typical_prices = (np.array(highs[-config.VWAP_PERIOD:]) + np.array(lows[-config.VWAP_PERIOD:]) + np.array(closes[-config.VWAP_PERIOD:])) / 3
        vols = np.array(volumes[-config.VWAP_PERIOD:])
        vwap = float(np.sum(typical_prices * vols) / np.sum(vols))
        macd, signal, hist = self.calculate_macd(closes, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL)
        if macd is None or signal is None or hist is None: return None

        if price > vwap and hist > 0 and macd > signal: return "buy"
        if hist < 0 and macd < signal: return "sell"
        return None

    # --- STRATEJİ 4: CMO + CRSI DERİN DİP TOPLAMA ---
    def strategy_cmo_crsi(self, kline):
        closes = kline.get("closes", [])
        if len(closes) < 70: return None

        cmo = self.calculate_cmo(closes, period=9)
        crsi = self.calculate_crsi(closes, rsi_period=3, streak_period=2, rank_period=100)

        if cmo is None or crsi is None: return None

        # CMO -63 ve CRSI 30 ise = LONG (AL)
        if cmo <= -63 and crsi <= 30:
            return "buy"

        # Çıkış Sinyali: CMO +63 üstü (aşırı alım)
        if cmo >= 63:
            return "sell"

        return None

    # --- POZİSYON TAKİBİ (açık pozisyon varsa stratejiye göre) ---
    def _strategy_tf(self, strat_name):
        """Stratejinin takip ettiği timeframe."""
        return {
            "UT": config.UT_TIMEFRAME,
            "BB_Squeeze": config.BB_SQUEEZE_TIMEFRAME,
            "EMA_Pullback": config.EMA_PULLBACK_TIMEFRAME,
            "VWAP_MACD": config.VWAP_MACD_TIMEFRAME,
            "CMO_CRSI_Dip": config.CMO_CRSI_TIMEFRAME,
            "EMA_VWAP_PULLBACK": config.EMA_VWAP_TIMEFRAME,
            "BB_SQUEEZE_ORDERFLOW": config.BB_SQUEEZE_TIMEFRAME,
            "ORDERFLOW": config.ORDERFLOW_TIMEFRAME,
            "MOMENTUM": config.MOMENTUM_TIMEFRAME,
            "KELTNER_BREAKOUT": config.KELTNER_TIMEFRAME,
            "CHOP_TREND_FILTER": config.CHOP_TIMEFRAME,
            "DONCHIAN_BREAKOUT": config.DONCHIAN_TIMEFRAME,
            "BB_MFI_MEAN_REVERSION": config.ACTIVE_STRATEGY_TIMEFRAME,
        }.get(strat_name, config.UT_TIMEFRAME)

    async def _manage_open_position(self, symbol, price, strat_name):
        tf = self._strategy_tf(strat_name)
        kline = self.market.get_ut_kline(symbol, tf)
        ticker = self.market.get_ticker(symbol) if self.market else None
        ticker_age = time.time() - float((ticker or {}).get("timestamp", 0) or 0) / 1000 if ticker else float("inf")
        if ticker_age > config.MAX_TICKER_AGE_SEC:
            # Never turn a missing/stale public price into a fake flat move or
            # a stale-position loss. The strategy loop will retry after the
            # market adapter repairs the ticker through REST/WebSocket.
            return {"action": "POSITION_DATA_UNAVAILABLE", "symbol": symbol,
                    "price": price, "reason": "public_price_stale", "age_seconds": round(ticker_age, 2),
                    "strategy": strat_name, "paper_only": True}
        # Önce hedef/stop kontrolü; aynı anda süre dolduysa gerçek kapanış nedeni korunur.
        pos = self.positions.get(symbol)
        if pos:
            pos["max_price"] = max(pos.get("max_price", pos["entry_price"]), price)
            pos["min_price"] = min(pos.get("min_price", pos["entry_price"]), price)
        if pos and pos.get("strategy") == "LLM_PAPER" and pos.get("llm_stop_price") and price <= pos["llm_stop_price"]:
            return await self.close_position(symbol, price, "llm_stop_loss")
        if pos and pos.get("strategy") == "LLM_PAPER" and pos.get("llm_take_profit_price") and price >= pos["llm_take_profit_price"]:
            return await self.close_position(symbol, price, "llm_take_profit")
        if pos and pos.get("strategy") == "LLM_PAPER" and pos.get("llm_max_hold_sec"):
            entry_time = float(pos.get("entry_time") or 0)
            if entry_time and time.time() - entry_time >= float(pos["llm_max_hold_sec"]):
                return await self.close_position(symbol, price, "llm_max_hold")
        # LLM_PAPER exits are owned by the LLM plan and position manager. Do
        # not apply legacy fixed early-failure, stale, trailing, time-decay,
        # or legacy max-hold policies to these positions.
        if pos and pos.get("strategy") == "LLM_PAPER":
            return None
        if pos and pos.get("strategy") != "LLM_PAPER":
            entry = float(pos.get("entry_price") or price)
            fallback_stop_pct = config.BB_MFI_STOP_LOSS_PCT if pos.get("strategy") == "BB_MFI_MEAN_REVERSION" else config.HARD_STOP_LOSS_PCT
            system_stop = float(pos.get("system_stop_price") or pos.get("stop_price") or entry * (1 - fallback_stop_pct))
            if pos.get("strategy") != "BB_MFI_MEAN_REVERSION" and price <= system_stop:
                return await self.close_position(symbol, price, "system_stop_loss")
            # BB-MFI canlıda backtest ile aynı karar kurallarını kullanır;
            # gerçekleşen fill, teyit sonrası mevcut canlı ticker fiyatıdır.
            if pos.get("strategy") == "BB_MFI_MEAN_REVERSION":
                if price <= system_stop:
                    return await self.close_position(symbol, price, "bb_mfi_stop_loss")
                # Existing paper positions opened before the v3 repair may
                # not have persisted target fields; apply the selected v3
                # target immediately instead of leaving them unmanaged.
                target = float(pos.get("system_take_profit_price") or pos.get("take_profit") or
                               entry * (1 + config.BB_MFI_TAKE_PROFIT_PCT))
                if target and price >= target:
                    return await self.close_position(symbol, price, "bb_mfi_take_profit")
                # MarketData retains closed candles only.  Evaluate the Pine
                # close signal once for each newly-confirmed strategy candle;
                # live paper closes at the next available ticker price.
                closed_at = int(kline.get("last_closed_at_ms") or 0)
                if (closed_at and pos.get("bb_mfi_exit_evaluated_at") != closed_at and
                        self.strategy_bb_mfi_mean_reversion(kline, symbol) == "sell"):
                    pos["bb_mfi_exit_evaluated_at"] = closed_at
                    return await self.close_position(symbol, price, f"bb_mfi_{config.BB_MFI_PINE_VERSION}_signal_exit")
                if closed_at:
                    pos["bb_mfi_exit_evaluated_at"] = closed_at
                return None
        if pos:
            elapsed = max(0.0, time.time() - pos.get("entry_time", time.time()))
            entry = pos.get("entry_price", price)
            max_progress = max(0.0, (pos.get("max_price", entry) - entry) / entry) if entry else 0.0
            if elapsed >= config.EARLY_FAILURE_SEC and max_progress < config.EARLY_FAILURE_MIN_PROGRESS_PCT:
                return await self.close_position(symbol, price, "early_failure_no_progress")
            if elapsed >= config.STALE_POSITION_SEC and max_progress < config.STALE_POSITION_MIN_PROGRESS_PCT:
                return await self.close_position(symbol, price, "stale_position_no_progress")
            # Klasik stratejilerde sabit yüzdeli trailing yerine ATR trailing kullanılır.
            # Stop yalnızca yukarı taşınır; trend devam ettiği sürece pozisyon süreyle kesilmez.
            atr = self.calculate_atr(kline, config.SYSTEM_ATR_PERIOD) if kline else None
            if atr and max_progress >= (atr * config.SYSTEM_ATR_TRAILING_ACTIVATION_ATR / entry):
                candidate = pos.get("max_price", entry) - atr * config.SYSTEM_ATR_TRAILING_MULTIPLIER
                previous = float(pos.get("system_trailing_stop_price") or 0)
                pos["system_trailing_stop_price"] = max(previous, candidate)
                net_floor = entry * (1 + config.min_net_exit_pct(pos.get("quantity", 0) * entry))
                if price <= pos["system_trailing_stop_price"] and price >= net_floor:
                    return await self.close_position(symbol, price, "atr_trailing_stop")
            if (config.STALE_POSITION_EXIT_BELOW_COST and elapsed >= config.STALE_POSITION_SEC and
                    price < entry * (1 + config.min_net_exit_pct(pos.get("quantity", 0) * entry))):
                return await self.close_position(symbol, price, "stale_position_below_cost")
            # Sistem TP'si sabit erken kapanış değildir: RR hedefi görüldüğünde
            # işaretlenir, pozisyon ATR trailing stop ile trendi takip etmeye devam eder.
            system_target = pos.get("system_take_profit_price") or pos.get("take_profit")
            if system_target and price >= float(system_target):
                pos["system_target_reached"] = True
                if pos.get("strategy") == "BB_MFI_MEAN_REVERSION":
                    return await self.close_position(symbol, price, "bb_mfi_take_profit")
        return None

    def llm_position_context(self, symbol, price=None):
        symbol = str(symbol).replace("_", "").upper()
        pos = self.positions.get(symbol)
        if not pos or pos.get("strategy") != "LLM_PAPER":
            return None
        ticker = self.market.get_ticker(symbol) if self.market else None
        current = float(price or (ticker or {}).get("last_price") or pos.get("entry_price") or 0)
        entry = float(pos.get("entry_price") or 0)
        return {
            "symbol": symbol,
            "strategy": "LLM_PAPER",
            "side": pos.get("side", "LONG"),
            "entry_price": entry,
            "current_price": current,
            "unrealized_gross_pct": ((current - entry) / entry) if entry else None,
            "quantity": pos.get("quantity"),
            "entry_time": pos.get("entry_time"),
            "plan_revision": (pos.get("entry_context") or {}).get("plan_revision", 0),
            "stop_loss_pct": (pos.get("entry_context") or {}).get("stop_loss_pct"),
            "take_profit_pct": (pos.get("entry_context") or {}).get("profit_target_pct"),
            "max_hold_seconds": pos.get("llm_max_hold_sec"),
            "llm_stop_price": pos.get("llm_stop_price"),
            "llm_take_profit_price": pos.get("llm_take_profit_price"),
            "max_price": pos.get("max_price", entry),
            "min_price": pos.get("min_price", entry),
            "entry_context": pos.get("entry_context", {}),
            "paper_only": True,
        }

    async def update_llm_position_plan(self, symbol, changes, reason="llm_plan_update", evidence=None):
        symbol = str(symbol).replace("_", "").upper()
        async with self._open_position_lock:
            pos = self.positions.get(symbol)
            if not pos or pos.get("strategy") != "LLM_PAPER":
                return {"ok": False, "error": "LLM paper pozisyonu bulunamadı", "paper_only": True}
            changes = changes or {}
            context = dict(pos.get("entry_context") or {})
            revision = int(context.get("plan_revision") or 0) + 1
            try:
                if "stop_loss_pct" in changes:
                    stop = float(changes["stop_loss_pct"])
                    if not 0.0001 <= stop <= 0.25: raise ValueError("stop_loss_pct 0.0001-0.25 arasında olmalı")
                    context["stop_loss_pct"] = stop
                    pos["llm_stop_price"] = float(pos["entry_price"]) * (1 - stop)
                if "take_profit_pct" in changes:
                    target = float(changes["take_profit_pct"])
                    if not 0.0001 <= target <= 0.25: raise ValueError("take_profit_pct 0.0001-0.25 arasında olmalı")
                    context["profit_target_pct"] = target
                    pos["llm_take_profit_price"] = float(pos["entry_price"]) * (1 + target)
                if "max_hold_seconds" in changes:
                    hold = int(changes["max_hold_seconds"])
                    if hold < 60 or hold > 7 * 24 * 3600: raise ValueError("max_hold_seconds 60-604800 arasında olmalı")
                    context["max_hold_sec"] = hold
                    pos["llm_max_hold_sec"] = hold
                context["plan_revision"] = revision
                context["last_plan_reason"] = str(reason)
                context["last_plan_evidence"] = evidence or {}
                context["plan_updated_at"] = time.time()
                pos["entry_context"] = context
                await database.save_position(symbol, pos)
                await database.save_signal({"symbol": symbol, "action": "LLM_PLAN_UPDATED", "price": pos.get("entry_price"), "reason": reason, "strategy": "LLM_PAPER", "timestamp": time.time()})
                return {"ok": True, "paper_only": True, "symbol": symbol, "plan_revision": revision, "position": self.llm_position_context(symbol)}
            except (TypeError, ValueError) as exc:
                return {"ok": False, "paper_only": True, "symbol": symbol, "error": str(exc)}

    def _flow_filter(self, symbol):
        if not self.market:
            return True, 0.0
        flow = self.market.get_orderflow(symbol)
        bid, ask = flow.get("bid_qty", 0), flow.get("ask_qty", 0)
        spread = flow.get("spread_pct")
        if not bid or not ask or spread is None:
            return False, 0.0
        imbalance = (bid - ask) / (bid + ask)
        return imbalance >= config.ORDERFLOW_MIN_IMBALANCE and spread <= 0.25, imbalance

    def _optional_flow_filter(self, symbol):
        """Akış verisi yoksa trend stratejisini kilitleme; varsa kalite filtresi uygula."""
        if not self.market: return True, 0.0
        flow = self.market.get_orderflow(symbol)
        if not flow.get("bid_qty") or not flow.get("ask_qty") or flow.get("spread_pct") is None:
            return True, 0.0
        return self._flow_filter(symbol)

    def calculate_orderflow_proxy(self, kline, lookback=20):
        """Backtest proxy: mum kapanış konumu + gövde yönü + hacim ile baskı tahmini."""
        opens, highs, lows = kline.get("opens", []), kline.get("highs", []), kline.get("lows", [])
        closes, volumes = kline.get("closes", []), kline.get("volumes", [])
        if len(closes) < lookback or len(volumes) < lookback: return None
        pressure = []
        for o, h, l, c, v in zip(opens[-lookback:], highs[-lookback:], lows[-lookback:], closes[-lookback:], volumes[-lookback:]):
            span = max(h - l, 1e-12)
            close_location = (2 * c - h - l) / span
            body_direction = 1 if c > o else -1 if c < o else 0
            pressure.append(v * (0.7 * close_location + 0.3 * body_direction))
        total_volume = sum(volumes[-lookback:])
        return max(-1.0, min(1.0, sum(pressure) / total_volume)) if total_volume else None

    @staticmethod
    def _volume_ratio(kline, lookback=20):
        volumes = kline.get("volumes", [])
        if len(volumes) < lookback + 1:
            return None
        baseline = float(np.mean(volumes[-lookback - 1:-1]))
        return float(volumes[-1] / baseline) if baseline > 0 else None

    def _mtf_bullish(self, symbol, timeframe):
        """Require a bullish EMA structure on the next higher loaded timeframe."""
        if not symbol or not self.market:
            return True
        higher = {"1m": "5m", "5m": "15m", "15m": "1h", "1h": "4h", "4h": "1d"}.get(timeframe)
        if not higher:
            return True
        kline = self.market.get_ut_kline(symbol, higher)
        closes = kline.get("closes", [])
        if len(closes) < 55:
            return False
        e9 = self.calculate_ema(closes, config.EMA_SHORT)
        e21 = self.calculate_ema(closes, config.EMA_MID)
        e50 = self.calculate_ema(closes, config.EMA_TREND)
        return all(value is not None for value in (e9, e21, e50)) and e9 > e21 > e50 and closes[-1] > e21

    def strategy_ema_vwap(self, kline, symbol=None):
        closes, highs, lows, volumes = kline.get("closes", []), kline.get("highs", []), kline.get("lows", []), kline.get("volumes", [])
        if len(closes) < 55: return None
        e9, e21, e50 = self.calculate_ema(closes, config.EMA_SHORT), self.calculate_ema(closes, config.EMA_MID), self.calculate_ema(closes, config.EMA_TREND)
        typical = (np.array(highs[-20:]) + np.array(lows[-20:]) + np.array(closes[-20:])) / 3
        vol = np.array(volumes[-20:]); vwap = float(np.sum(typical * vol) / np.sum(vol)) if np.sum(vol) else None
        if None in (e9, e21, e50, vwap): return None
        adx_result = _adx(highs, lows, closes)
        adx_value = adx_result.get("adx") if adx_result else None
        adx_ok = adx_value is not None and adx_value >= config.EMA_VWAP_MIN_ADX
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else (True, 0)
        volume_ratio = self._volume_ratio(kline)
        volume_ok = volume_ratio is not None and volume_ratio >= config.EMA_VWAP_MIN_VOLUME_RATIO
        mtf_ok = self._mtf_bullish(symbol, config.EMA_VWAP_TIMEFRAME) if config.EMA_VWAP_REQUIRE_MTF_ALIGNMENT else True
        # Tek mumluk crossover yerine son 3 mum içinde EMA21'e gerçek pullback
        # arıyoruz; böylece strateji yalnızca 1 kez değil, yeni kurulumlarda tekrar
        # sinyal üretebilir. Kapanış EMA21 üzerine dönerken trend ve VWAP korunmalı.
        recent_lows = lows[-4:-1]
        touched_ema = any(low <= e21 * 1.002 for low in recent_lows)
        bullish_reclaim = closes[-1] > closes[-2] and closes[-1] > e21
        if e9 > e21 > e50 and adx_ok and closes[-1] > vwap and touched_ema and bullish_reclaim and flow_ok and volume_ok and mtf_ok: return "buy"
        return None

    def strategy_breakout(self, kline, symbol=None):
        closes, volumes = kline.get("closes", []), kline.get("volumes", [])
        if len(closes) < 25: return None
        high = max(closes[-21:-1]); avg_vol = float(np.mean(volumes[-21:-1]))
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else (True, 0)
        if closes[-1] > high and volumes[-1] > avg_vol * 1.5 and flow_ok: return "buy"
        return None

    def strategy_orderflow(self, kline, symbol=None):
        closes = kline.get("closes", [])
        if len(closes) < 5: return None
        if symbol:
            flow_ok, imbalance = self._flow_filter(symbol)
        else:
            imbalance = self.calculate_orderflow_proxy(kline) or 0
            flow_ok = imbalance >= config.ORDERFLOW_MIN_IMBALANCE
        if flow_ok and closes[-1] > closes[-2] > closes[-3]: return "buy"
        return None

    def strategy_momentum(self, kline, symbol=None):
        closes = kline.get("closes", []); highs = kline.get("highs", []); lows = kline.get("lows", [])
        if len(closes) < 30: return None
        short = config.MOMENTUM_SHORT_LOOKBACK; long = config.MOMENTUM_LONG_LOOKBACK
        if len(closes) <= long: return None
        r1 = closes[-1] / closes[-short - 1] - 1; r2 = closes[-1] / closes[-long] - 1
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else (True, 0)
        volume_ratio = self._volume_ratio(kline)
        volume_ok = volume_ratio is not None and volume_ratio >= config.MOMENTUM_MIN_VOLUME_RATIO
        mtf_ok = self._mtf_bullish(symbol, config.MOMENTUM_TIMEFRAME) if config.MOMENTUM_REQUIRE_MTF_ALIGNMENT else True
        adx = _adx(highs, lows, closes).get("adx") if len(closes) >= 30 else None
        adx_ok = adx is not None and adx >= config.MOMENTUM_MIN_ADX
        if r1 > config.MOMENTUM_MIN_RETURN_PCT and r2 > 0 and flow_ok and volume_ok and mtf_ok and adx_ok: return "buy"
        return None

    def strategy_momentum_cost_aware(self, kline, symbol=None):
        """Lower-turnover momentum variant with stricter cost-aware confirmation."""
        closes = kline.get("closes", []); highs = kline.get("highs", []); lows = kline.get("lows", [])
        if len(closes) < 55: return None
        short, long = config.MOMENTUM_SHORT_LOOKBACK, config.MOMENTUM_LONG_LOOKBACK
        r1 = closes[-1] / closes[-short - 1] - 1; r2 = closes[-1] / closes[-long] - 1
        volume_ratio = self._volume_ratio(kline)
        adx = _adx(highs, lows, closes).get("adx")
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else (True, 0)
        mtf_ok = self._mtf_bullish(symbol, config.MOMENTUM_TIMEFRAME)
        if (r1 >= config.MOMENTUM_COST_AWARE_MIN_RETURN_PCT and r2 > 0 and
                volume_ratio is not None and volume_ratio >= config.MOMENTUM_COST_AWARE_MIN_VOLUME_RATIO and
                adx is not None and adx >= config.MOMENTUM_COST_AWARE_MIN_ADX and flow_ok and mtf_ok):
            return "buy"
        return None

    def strategy_momentum_scored(self, kline, symbol=None):
        """Quality-gated momentum entry; score is explainable and no-lookahead."""
        closes = kline.get("closes", []); highs = kline.get("highs", []); lows = kline.get("lows", []); volumes = kline.get("volumes", [])
        if len(closes) < 55: return None
        short, long = config.MOMENTUM_SHORT_LOOKBACK, config.MOMENTUM_LONG_LOOKBACK
        r1 = closes[-1] / closes[-short - 1] - 1; r2 = closes[-1] / closes[-long] - 1
        volume_ratio = self._volume_ratio(kline) or 0
        adx = (_adx(highs, lows, closes) or {}).get("adx") or 0
        ema9 = self.calculate_ema(closes, 9); ema21 = self.calculate_ema(closes, 21); ema50 = self.calculate_ema(closes, 50)
        rsi = self.calculate_rsi(closes, 14) or 0; cmo = self.calculate_cmo(closes, 9) or 0
        macd = _macd(closes) or {}; hist = macd.get("histogram") or 0
        typical = [(h + l + c) / 3 for h, l, c in zip(highs[-20:], lows[-20:], closes[-20:])]
        vv = sum(volumes[-20:]); vwap = sum(p * v for p, v in zip(typical, volumes[-20:])) / vv if vv else closes[-1]
        score = 0
        score += 2 if ema9 and ema21 and ema50 and ema9 > ema21 > ema50 else 0
        score += 1 if r1 >= config.MOMENTUM_MIN_RETURN_PCT and r2 > 0 else 0
        score += 2 if volume_ratio >= 1.2 else 1 if volume_ratio >= 1.0 else 0
        score += 1 if adx >= max(20, config.MOMENTUM_MIN_ADX) else 0
        score += 1 if hist > 0 else 0
        score += 1 if 48 <= rsi <= 72 else 0
        score += 1 if cmo > 0 else 0
        score += 1 if closes[-1] > vwap else 0
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else (True, 0)
        return "buy" if score >= 7 and flow_ok else None

    def strategy_momentum_scored_v2(self, kline, symbol=None):
        """Experimental scored entry with candle-quality and extension gates."""
        if self.strategy_momentum_scored(kline, symbol) != "buy":
            return None
        opens = kline.get("opens", []); highs = kline.get("highs", []); lows = kline.get("lows", []); closes = kline.get("closes", [])
        if len(closes) < 55:
            return None
        candle_range = max(highs[-1] - lows[-1], 1e-12)
        close_location = (closes[-1] - lows[-1]) / candle_range
        ema21 = self.calculate_ema(closes, 21)
        atr = self.calculate_atr(kline, 14) or closes[-1] * 0.01
        extension = (closes[-1] - ema21) / closes[-1] if ema21 else 1
        # Experimental extra component: strong close, but avoid a late chase.
        return "buy" if closes[-1] > opens[-1] and close_location >= 0.65 and extension <= 2 * atr / closes[-1] else None

    def strategy_oversold_trend_reentry(self, kline, symbol=None):
        """Long re-entry candidate: oversold oscillators with bullish EMA structure."""
        closes = kline.get("closes", []); highs = kline.get("highs", []); lows = kline.get("lows", [])
        if len(closes) < 55: return None
        rsi = self.calculate_rsi(closes, config.RSI_PERIOD)
        cmo = self.calculate_cmo(closes, 9)
        stoch = _stochastic(highs, lows, closes)
        ema9 = self.calculate_ema(closes, 9); ema21 = self.calculate_ema(closes, 21)
        if (rsi is not None and cmo is not None and stoch and ema9 is not None and ema21 is not None and
                cmo < 0 and stoch.get("k") is not None and stoch["k"] < 40 and rsi < config.OVERSOLD_TREND_REENTRY_RSI_MAX and ema9 > ema21):
            return "buy"
        return None

    def strategy_adaptive_volatility_trend(self, kline, symbol=None):
        """15m trend entry gated by a usable ATR regime and 4h EMA alignment."""
        closes = kline.get("closes", []); highs = kline.get("highs", []); lows = kline.get("lows", [])
        if len(closes) < 55 or not closes[-1]: return None
        ema9 = self.calculate_ema(closes, 9); ema21 = self.calculate_ema(closes, 21); ema50 = self.calculate_ema(closes, 50)
        adx_value = _adx(highs, lows, closes).get("adx")
        atr = self.calculate_atr(kline, 14); atr_pct = atr / closes[-1] if atr else None
        higher_ok = True
        if symbol and self.market:
            higher = self.market.get_ut_kline(symbol, "4h")
            hc = higher.get("closes", [])
            if len(hc) < 55: higher_ok = False
            else:
                he9 = self.calculate_ema(hc, 9); he21 = self.calculate_ema(hc, 21); he50 = self.calculate_ema(hc, 50)
                higher_ok = all(v is not None for v in (he9, he21, he50)) and he9 > he21 > he50 and hc[-1] > he21
        if (all(v is not None for v in (ema9, ema21, ema50, adx_value, atr_pct)) and
                ema9 > ema21 > ema50 and adx_value >= config.ADAPTIVE_VOLATILITY_MIN_ADX and
                config.ADAPTIVE_VOLATILITY_MIN_ATR_PCT <= atr_pct <= config.ADAPTIVE_VOLATILITY_MAX_ATR_PCT and higher_ok):
            return "buy"
        return None

    def strategy_regime_gate_low_turnover(self, kline, symbol=None):
        """Low-turnover 1h trend entry; trades only a confirmed trend regime."""
        closes = kline.get("closes", []); highs = kline.get("highs", []); lows = kline.get("lows", []); volumes = kline.get("volumes", [])
        if len(closes) < 55 or len(volumes) < 21: return None
        ema9 = self.calculate_ema(closes, 9); ema21 = self.calculate_ema(closes, 21); ema50 = self.calculate_ema(closes, 50)
        adx_value = _adx(highs, lows, closes).get("adx"); return_21 = closes[-1] / closes[-22] - 1 if closes[-22] else 0
        volume_ratio = self._volume_ratio(kline); higher_ok = True
        if symbol and self.market:
            higher = self.market.get_ut_kline(symbol, "4h"); hc = higher.get("closes", [])
            if len(hc) < 55: higher_ok = False
            else:
                he9 = self.calculate_ema(hc, 9); he21 = self.calculate_ema(hc, 21); he50 = self.calculate_ema(hc, 50)
                higher_ok = all(v is not None for v in (he9, he21, he50)) and he9 > he21 > he50 and hc[-1] > he21
        if (all(v is not None for v in (ema9, ema21, ema50, adx_value, volume_ratio)) and ema9 > ema21 > ema50 and
                adx_value >= config.REGIME_GATE_MIN_ADX and return_21 >= config.REGIME_GATE_MIN_RETURN_PCT and
                volume_ratio >= config.REGIME_GATE_MIN_VOLUME_RATIO and higher_ok): return "buy"
        return None

    def adr_status(self, symbol, price):
        """Return ADR capacity for a momentum entry without using future data."""
        if not config.ADR_FILTER_ENABLED:
            return True, {"enabled": False}
        daily = self.market.klines.get(config.ADR_TIMEFRAME, {}).get(symbol.upper(), {})
        highs, lows, closes, opens = (daily.get(k, []) for k in ("highs", "lows", "closes", "opens"))
        period = config.ADR_PERIOD
        if len(closes) < period + 1 or len(opens) < 1:
            return True, {"enabled": True, "ready": False, "reason": "warming_up"}
        # Exclude the current incomplete daily candle from ADR history.
        hist_highs, hist_lows, hist_closes = highs[-period-1:-1], lows[-period-1:-1], closes[-period-1:-1]
        ranges = [(h - l) / c for h, l, c in zip(hist_highs, hist_lows, hist_closes) if c > 0]
        if len(ranges) < period:
            return True, {"enabled": True, "ready": False, "reason": "warming_up"}
        adr_pct = float(np.mean(ranges))
        today_open = float(opens[-1])
        if today_open <= 0:
            return True, {"enabled": True, "ready": False, "reason": "invalid_open"}
        current_range_pct = max(price, today_open) / min(price, today_open) - 1 if price > 0 else 0.0
        remaining_pct = adr_pct - current_range_pct
        utilization = current_range_pct / adr_pct if adr_pct > 0 else 1.0
        checks = {
            "minimum_adr": adr_pct >= config.ADR_MIN_PCT,
            "remaining_capacity": remaining_pct >= config.ADR_MIN_REMAINING_PCT,
            "not_overextended": utilization <= config.ADR_MAX_UTILIZATION_PCT,
        }
        return all(checks.values()), {
            "enabled": True, "ready": True, "adr_pct": adr_pct,
            "current_range_pct": current_range_pct, "remaining_pct": remaining_pct,
            "utilization": utilization, "checks": checks,
        }

    def strategy_mean_reversion(self, kline, symbol=None):
        closes = kline.get("closes", [])
        if len(closes) < 110: return None
        bb = self.calculate_bollinger_bands(closes, config.BB_PERIOD, config.BB_STD_DEV); crsi = self.calculate_crsi(closes)
        flow_ok, imbalance = self._optional_flow_filter(symbol) if symbol else (True, 0)
        if bb and crsi is not None and closes[-1] < bb["lower"] and crsi < 30 and imbalance >= 0 and flow_ok: return "buy"
        return None

    def strategy_bb_mfi_mean_reversion(self, kline, symbol=None):
        """Deterministic Flawless Victory profile selected for live paper flow."""
        closes = kline.get("closes", []); highs = kline.get("highs", []); lows = kline.get("lows", [])
        volumes = kline.get("volumes", [])
        version = config.BB_MFI_PINE_VERSION
        if version not in {"v1", "v2", "v3"}:
            raise ValueError("BB_MFI_PINE_VERSION v1, v2 veya v3 olmalıdır")
        min_history = max(config.BB_MFI_BB_PERIOD, config.BB_MFI_RSI_PERIOD + 1,
                          config.BB_MFI_MFI_PERIOD + 1 if version == "v3" else 0)
        if len(closes) < min_history or len(highs) < min_history or len(lows) < min_history or len(volumes) < min_history:
            return None
        bb = self.calculate_bollinger_bands(closes, period=config.BB_MFI_BB_PERIOD, std_dev=config.BB_MFI_BB_STD_DEV)
        rsi = self.calculate_rsi(closes, period=config.BB_MFI_RSI_PERIOD)
        if not bb or rsi is None:
            return None
        average_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0.0
        volume_ratio = volumes[-1] / average_volume if average_volume else 0.0
        dip_range = highs[-1] - lows[-1]
        close_position = (closes[-1] - lows[-1]) / dip_range if dip_range > 0 else 0.0
        entry_volume_ok = volume_ratio >= config.BB_MFI_ENTRY_VOLUME_RATIO_MIN
        dip_confirmed = (not config.BB_MFI_DIP_CONFIRMATION_ENABLED or
                         close_position >= config.BB_MFI_DIP_MIN_CLOSE_POSITION)
        if version == "v3":
            mfi = _mfi(highs, lows, closes, volumes, config.BB_MFI_MFI_PERIOD)
            if mfi is None:
                return None
            previous_mfi = _mfi(highs[:-1], lows[:-1], closes[:-1], volumes[:-1], config.BB_MFI_MFI_PERIOD)
            mfi_reversal_ok = (not config.BB_MFI_ENTRY_MFI_REVERSAL_ENABLED or
                               (previous_mfi is not None and mfi >= previous_mfi + config.BB_MFI_ENTRY_MFI_REVERSAL_MIN_DELTA))
            mfi_slowdown_ok = (config.BB_MFI_ENTRY_MFI_SLOWDOWN_MAX_DROP < 0 or
                               (previous_mfi is not None and mfi >= previous_mfi - config.BB_MFI_ENTRY_MFI_SLOWDOWN_MAX_DROP))
            bear_pressure = self._bb_mfi_bear_pressure(kline)
            if closes[-1] < bb["lower"] and mfi < config.BB_MFI_ENTRY_MFI_MAX and entry_volume_ok and dip_confirmed and mfi_reversal_ok and mfi_slowdown_ok and not bear_pressure:
                return "buy"
            if (closes[-1] > bb["upper"] and rsi > config.BB_MFI_EXIT_RSI_MIN and
                    mfi > config.BB_MFI_EXIT_MFI_MIN):
                return "sell"
            return None
        lower = config.BB_MFI_V1_RSI_LOWER_LEVEL if version == "v1" else config.BB_MFI_V2_RSI_LOWER_LEVEL
        upper = config.BB_MFI_V1_RSI_UPPER_LEVEL if version == "v1" else config.BB_MFI_V2_RSI_UPPER_LEVEL
        if closes[-1] < bb["lower"] and rsi > lower and entry_volume_ok and dip_confirmed:
            return "buy"
        if closes[-1] > bb["upper"] and rsi > upper:
            return "sell"
        return None

    @staticmethod
    def _bb_mfi_entry_context_block_reason(technical, kline):
        """Return a deterministic BB/MFI entry block reason, if any.

        Bearish EMA alignment is not an absolute ban for a mean-reversion
        strategy. It must, however, show both a candle recovery and an MFI
        reversal. Every input uses the current or an already-closed prior bar.
        """
        if not isinstance(technical, dict) or not technical.get("data_ready"):
            return "technical_data_not_ready" if config.BB_MFI_REQUIRE_DATA_READY else None

        alignment = str((technical.get("trend") or {}).get("alignment") or "").lower()
        if alignment != "bearish" or not config.BB_MFI_BEARISH_REQUIRE_REVERSAL_CONFIRMATION:
            return None

        closes = kline.get("closes", []) if isinstance(kline, dict) else []
        highs = kline.get("highs", []) if isinstance(kline, dict) else []
        lows = kline.get("lows", []) if isinstance(kline, dict) else []
        volumes = kline.get("volumes", []) if isinstance(kline, dict) else []
        if min(len(closes), len(highs), len(lows), len(volumes)) < config.BB_MFI_MFI_PERIOD + 2:
            return "bearish_reversal_data_insufficient"

        candle_range = highs[-1] - lows[-1]
        close_position = (closes[-1] - lows[-1]) / candle_range if candle_range > 0 else 0.0
        current_mfi = _mfi(highs, lows, closes, volumes, config.BB_MFI_MFI_PERIOD)
        previous_mfi = _mfi(highs[:-1], lows[:-1], closes[:-1], volumes[:-1], config.BB_MFI_MFI_PERIOD)
        mfi_reversal = (
            current_mfi is not None and previous_mfi is not None and
            current_mfi >= previous_mfi + config.BB_MFI_BEARISH_MIN_MFI_REVERSAL_DELTA
        )
        if close_position < config.BB_MFI_BEARISH_MIN_CLOSE_POSITION:
            return "bearish_reversal_candle_unconfirmed"
        if not mfi_reversal:
            return "bearish_reversal_mfi_unconfirmed"
        return None

    @staticmethod
    def _bb_mfi_bear_pressure(kline):
        """Causal M5 selloff gate for V3 long entries; disabled only by config."""
        if not config.BB_MFI_BEAR_PRESSURE_FILTER_ENABLED:
            return False
        closes = kline.get("closes", []); highs = kline.get("highs", []); lows = kline.get("lows", [])
        if len(closes) < 13:
            return False
        directional = _adx(highs, lows, closes) or {}
        adx, plus_di, minus_di = directional.get("adx"), directional.get("plus_di"), directional.get("minus_di")
        if not all(isinstance(value, (int, float)) for value in (adx, plus_di, minus_di)):
            return False
        return_1h = closes[-1] / closes[-13] - 1 if closes[-13] else 0.0
        return_15m = closes[-1] / closes[-4] - 1 if closes[-4] else 0.0
        return (adx >= config.BB_MFI_BEAR_PRESSURE_MIN_ADX and
                minus_di - plus_di >= config.BB_MFI_BEAR_PRESSURE_MIN_DI_GAP and
                return_1h <= -config.BB_MFI_BEAR_PRESSURE_MIN_RETURN_1H_PCT / 100 and
                return_15m <= -config.BB_MFI_BEAR_PRESSURE_MIN_RETURN_15M_PCT / 100)

    def strategy_bb_squeeze_orderflow(self, kline, symbol=None):
        if symbol:
            flow_ok, _ = self._flow_filter(symbol)
        else:
            flow_ok = (self.calculate_orderflow_proxy(kline) or 0) >= 0.10
        return "buy" if flow_ok and self.strategy_bollinger_squeeze(kline) == "buy" else None

    def strategy_keltner_breakout(self, kline, symbol=None):
        closes, highs, lows, volumes = [kline.get(k, []) for k in ("closes", "highs", "lows", "volumes")]
        if len(closes) < 30: return None
        ema = self.calculate_ema(closes, config.KELTNER_EMA_PERIOD); atr = self.calculate_atr(kline, config.KELTNER_ATR_PERIOD)
        avg_vol = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else 0
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else ((self.calculate_orderflow_proxy(kline) or 0) >= 0.05, 0)
        mtf_ok = self._mtf_bullish(symbol, config.KELTNER_TIMEFRAME) if config.KELTNER_REQUIRE_MTF_ALIGNMENT else True
        previous = {key: values[:-1] for key, values in kline.items() if isinstance(values, list)}
        prev_ema = self.calculate_ema(previous.get("closes", []), config.KELTNER_EMA_PERIOD)
        prev_atr = self.calculate_atr(previous, config.KELTNER_ATR_PERIOD)
        upper = ema + config.KELTNER_ATR_MULTIPLIER * atr if ema is not None and atr else None
        was_below_band = prev_ema is not None and prev_atr is not None and closes[-2] <= prev_ema + config.KELTNER_ATR_MULTIPLIER * prev_atr
        retest_ok = not config.KELTNER_REQUIRE_RETEST or (upper is not None and lows[-1] <= upper * 1.001 and closes[-1] > upper)
        if ema is not None and atr and was_below_band and retest_ok and volumes[-1] >= avg_vol * config.KELTNER_VOLUME_MULTIPLIER and flow_ok and mtf_ok: return "buy"
        return None

    def calculate_chop(self, kline, period=14):
        highs, lows, closes = kline.get("highs", []), kline.get("lows", []), kline.get("closes", [])
        if len(closes) < period + 1: return None
        tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) for i in range(len(closes)-period, len(closes))]
        hi, lo = max(highs[-period:]), min(lows[-period:]); span = hi - lo
        return 100 * np.log10(sum(tr) / span) / np.log10(period) if span > 0 else 100.0

    def strategy_chop_trend(self, kline, symbol=None):
        closes = kline.get("closes", [])
        if len(closes) < 30: return None
        chop = self.calculate_chop(kline, config.CHOP_PERIOD); rsi = self.calculate_rsi(closes, config.RSI_PERIOD)
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else ((self.calculate_orderflow_proxy(kline) or 0) >= 0, 0)
        if chop is not None and chop < config.CHOP_MAX_VALUE and rsi is not None and rsi > config.CHOP_MIN_RSI and closes[-1] > closes[-2] and flow_ok: return "buy"
        return None

    def strategy_donchian_breakout(self, kline, symbol=None):
        closes, volumes = kline.get("closes", []), kline.get("volumes", [])
        lookback = config.DONCHIAN_LOOKBACK
        if len(closes) < lookback + 2: return None
        upper = max(closes[-lookback-1:-1]); avg_vol = float(np.mean(volumes[-lookback-1:-1]))
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else ((self.calculate_orderflow_proxy(kline) or 0) >= 0, 0)
        if closes[-1] > upper and volumes[-1] >= avg_vol * config.DONCHIAN_VOLUME_MULTIPLIER and flow_ok: return "buy"
        return None

    async def evaluate(self, symbol, ticker, allow_entry=True):
        signals = []
        price = ticker["last_price"]
        await self._evaluate_pending_orders(symbol, price)

        # Açık spot pozisyonu time-decay hedef, hard stop ve timeout ile yönet.
        if symbol in self.positions:
            strat = self.positions[symbol].get("strategy")
            # UT stratejisi de artık _manage_open_position'a girer
            sig = await self._manage_open_position(symbol, price, strat or "EMA_VWAP_PULLBACK")
            if sig: signals.append(sig)
            if sig: return signals
            # Pozisyon yönetimi her çağrıda devam eder; yeni katman yalnızca
            # periyodik giriş taraması sırasında değerlendirilebilir.
            if not allow_entry:
                return signals
            # Pozisyon yalnızca kendisini açan stratejinin sinyaliyle yönetilir.
            strategy_specs = [
                (config.EMA_VWAP_ENABLED, "EMA_VWAP_PULLBACK", self.strategy_ema_vwap, config.EMA_VWAP_TIMEFRAME),
                (config.BB_SQUEEZE_ENABLED, "BB_SQUEEZE_ORDERFLOW", self.strategy_bb_squeeze_orderflow, config.BB_SQUEEZE_TIMEFRAME),
                (config.ORDERFLOW_ENABLED, "ORDERFLOW", self.strategy_orderflow, config.ORDERFLOW_TIMEFRAME),
                (config.MOMENTUM_ENABLED, "MOMENTUM", self.strategy_momentum, config.MOMENTUM_TIMEFRAME),
                (config.MOMENTUM_COST_AWARE_ENABLED, "MOMENTUM_COST_AWARE", self.strategy_momentum_cost_aware, config.MOMENTUM_TIMEFRAME),
                (config.OVERSOLD_TREND_REENTRY_ENABLED, "OVERSOLD_TREND_REENTRY", self.strategy_oversold_trend_reentry, config.OVERSOLD_TREND_REENTRY_TIMEFRAME),
                (config.ADAPTIVE_VOLATILITY_TREND_ENABLED, "ADAPTIVE_VOLATILITY_TREND", self.strategy_adaptive_volatility_trend, config.ADAPTIVE_VOLATILITY_TREND_TIMEFRAME),
                (config.REGIME_GATE_LOW_TURNOVER_ENABLED, "REGIME_GATE_LOW_TURNOVER", self.strategy_regime_gate_low_turnover, config.REGIME_GATE_LOW_TURNOVER_TIMEFRAME),
                (config.KELTNER_ENABLED, "KELTNER_BREAKOUT", self.strategy_keltner_breakout, config.KELTNER_TIMEFRAME),
                (config.CHOP_ENABLED, "CHOP_TREND_FILTER", self.strategy_chop_trend, config.CHOP_TIMEFRAME),
                (config.DONCHIAN_ENABLED, "DONCHIAN_BREAKOUT", self.strategy_donchian_breakout, config.DONCHIAN_TIMEFRAME),
                (config.MEAN_REVERSION_ENABLED, "BB_MFI_MEAN_REVERSION", self.strategy_bb_mfi_mean_reversion, config.ACTIVE_STRATEGY_TIMEFRAME),
            ]
            selected = next((item for item in strategy_specs if item[1] == strat and item[0]), None)
            if selected:
                _, name, fn, tf = selected
                strategy_kline = self.market.get_ut_kline(symbol, tf)
                result = fn(strategy_kline, symbol)
                if result == "sell" and config.EXIT_ON_OPPOSITE_SIGNAL:
                    return [await self.close_position(symbol, price, "opposite_signal")]
                if result == "buy" and strat == "BB_MFI_MEAN_REVERSION":
                    max_layers = int(config.SYMBOL_PYRAMIDING_LAYERS.get(symbol, config.PYRAMIDING_LAYERS))
                    if self.positions[symbol].get("layers", 1) < max_layers:
                        added = await self.open_position(symbol, price, "LONG", strat)
                        if added: signals.append(added)
                # Spotta aynı sembole tekrar katman ekleme yok: tek sembol = tek pozisyon.
                # Yalnızca seçili BB-MFI stratejisinde ayarlanmış katman sınırına kadar ekleme yapılır.
            return signals

        if not allow_entry:
            return signals

        # Açık pozisyon yok: aktif stratejileri sırayla değerlendir
        eval_order = [
            (config.EMA_VWAP_ENABLED, "EMA_VWAP_PULLBACK", self.strategy_ema_vwap, config.EMA_VWAP_TIMEFRAME),
            (config.BB_SQUEEZE_ENABLED, "BB_SQUEEZE_ORDERFLOW", self.strategy_bb_squeeze_orderflow, config.BB_SQUEEZE_TIMEFRAME),
            (config.ORDERFLOW_ENABLED, "ORDERFLOW", self.strategy_orderflow, config.ORDERFLOW_TIMEFRAME),
            (config.MOMENTUM_ENABLED, "MOMENTUM", self.strategy_momentum, config.MOMENTUM_TIMEFRAME),
            (config.MOMENTUM_COST_AWARE_ENABLED, "MOMENTUM_COST_AWARE", self.strategy_momentum_cost_aware, config.MOMENTUM_TIMEFRAME),
            (config.OVERSOLD_TREND_REENTRY_ENABLED, "OVERSOLD_TREND_REENTRY", self.strategy_oversold_trend_reentry, config.OVERSOLD_TREND_REENTRY_TIMEFRAME),
            (config.ADAPTIVE_VOLATILITY_TREND_ENABLED, "ADAPTIVE_VOLATILITY_TREND", self.strategy_adaptive_volatility_trend, config.ADAPTIVE_VOLATILITY_TREND_TIMEFRAME),
            (config.REGIME_GATE_LOW_TURNOVER_ENABLED, "REGIME_GATE_LOW_TURNOVER", self.strategy_regime_gate_low_turnover, config.REGIME_GATE_LOW_TURNOVER_TIMEFRAME),
            (config.KELTNER_ENABLED, "KELTNER_BREAKOUT", self.strategy_keltner_breakout, config.KELTNER_TIMEFRAME),
            (config.CHOP_ENABLED, "CHOP_TREND_FILTER", self.strategy_chop_trend, config.CHOP_TIMEFRAME),
                (config.DONCHIAN_ENABLED, "DONCHIAN_BREAKOUT", self.strategy_donchian_breakout, config.DONCHIAN_TIMEFRAME),
                (config.MEAN_REVERSION_ENABLED, "BB_MFI_MEAN_REVERSION", self.strategy_bb_mfi_mean_reversion, config.ACTIVE_STRATEGY_TIMEFRAME),
        ]
        for enabled, name, fn, tf in eval_order:
            if not enabled: continue
            kline = self.market.get_ut_kline(symbol, tf)
            length_key = (symbol, name)
            current_length = len(kline.get("closes", []))
            if current_length == self._last_signal_lengths.get(length_key):
                continue
            self._last_signal_lengths[length_key] = current_length
            result = fn(kline, symbol)
            if result == "buy":
                if name == "MOMENTUM":
                    adr_ok, adr = self.adr_status(symbol, price)
                    if not adr_ok:
                        failed = [key for key, ok in adr.get("checks", {}).items() if not ok]
                        reason = "adr_filter:" + ",".join(failed or [adr.get("reason", "unknown")])
                        blocked = {"symbol": symbol, "action": "BUY_BLOCKED", "price": price,
                                   "reason": reason, "strategy": name, "timestamp": time.time()}
                        await database.save_signal(blocked)
                        return signals + [blocked]
                sig = await self.open_position(symbol, price, "LONG", name)
                if sig: signals.append(sig)
                break
        return signals

    async def close_position(self, symbol, price, reason):
        # Strategy loop and manual close can arrive concurrently. Keep the
        # wallet/trade/position transition under the same lock used by opens
        # so one position can produce at most one close transaction.
        async with self._open_position_lock:
            return await self._close_position_unlocked(symbol, price, reason)

    async def _close_position_unlocked(self, symbol, price, reason):
        pos = self.positions.get(symbol)
        if not pos: return None
        if pos.get("strategy") == "LLM_PAPER" and (
            str(reason).startswith("time_decay_")
            or str(reason).startswith("early_failure")
            or str(reason).startswith("stale_position")
            or str(reason).startswith("max_hold_")
        ):
            await database.save_signal({"symbol": symbol, "action": "CLOSE_BLOCKED", "price": price, "reason": f"llm_legacy_exit_blocked:{reason}", "strategy": "LLM_PAPER", "timestamp": time.time()})
            return None
        sell_value = pos["quantity"] * price
        commission = sell_value * config.COMMISSION_PCT
        try_balance = await database.get_wallet_balance("TRY")
        trade = await self._record_trade(symbol, pos, price, reason, commission)
        sig = {"symbol": symbol, "action": "CLOSE_LONG", "reason": reason, "price": price,
               "strategy": pos.get("strategy", "UT"), "trade_id": pos.get("trade_id"), "timestamp": time.time()}
        await database.commit_close_position(symbol, symbol.replace("TRY", ""), try_balance + sell_value - commission, trade, sig)
        try:
            await agent_learning.record_paper_trade_outcome(trade)
        except Exception as learning_error:
            print(f"[Learning] paper outcome kaydedilemedi: {learning_error}")
        closed_strategy = pos.get("strategy")
        del self.positions[symbol]
        if closed_strategy == "LLM_PAPER":
            # Closing is not an implicit permission to re-enter the same setup.
            # Require a fresh post-exit setup before the LLM can buy this symbol.
            technical = (pos.get("entry_context") or {}).get("technical") or {}
            volatility = technical.get("volatility") or {}
            try:
                atr_pct = max(0.0, float(volatility.get("atr_pct") or 0))
            except (TypeError, ValueError):
                atr_pct = 0.0
            rearm_pct = max(config.LLM_REENTRY_MIN_MOVE_PCT, min(0.02, atr_pct * 0.75 or 0))
            guard_reason = "llm_exit_reentry_lock:" + str(reason)
            cooldown_seconds = (config.LLM_PROFIT_REENTRY_COOLDOWN_SEC
                                if float(trade.get("pnl") or 0.0) > 0
                                else config.LLM_REENTRY_COOLDOWN_SEC)
            await database.upsert_llm_symbol_guard(
                symbol, "cooldown", "active",
                time.time() + cooldown_seconds,
                guard_reason,
                {"exit_reason": reason, "exit_price": price, "requires_fresh_setup": True,
                 "atr_pct_at_exit": atr_pct, "rearm_required_pct": rearm_pct,
                 "realized_pnl": float(trade.get("pnl") or 0.0),
                 "cooldown_seconds": cooldown_seconds,
                 "cooldown_kind": "profit" if float(trade.get("pnl") or 0.0) > 0 else "loss"},
            )
            await database.save_signal({
                "symbol": symbol, "action": "LLM_REENTRY_BLOCKED", "price": price,
                "reason": guard_reason, "strategy": "LLM_PAPER", "timestamp": time.time(),
            })
        tf = self._strategy_tf(pos.get("strategy", "UT"))
        current_bar = self._current_bar(symbol, tf)
        if current_bar is not None:
            self._cooldown_until[symbol] = current_bar + config.COOLDOWN_BARS
        if reason.startswith("max_hold_") or reason in {"early_failure_no_progress", "stale_position_no_progress"}:
            self._timeout_block_until[symbol] = time.time() + config.TIMEOUT_REENTRY_BLOCK_SEC
        elif reason in {"hard_stop_loss", "system_stop_loss", "llm_stop_loss"}:
            self._hard_stop_block_until[symbol] = time.time() + config.HARD_STOP_REENTRY_BLOCK_SEC
        return sig

    async def _record_trade(self, symbol, pos, exit_price, reason, commission=0.0):
        """Kapanan pozisyonu işlem geçmişine kaydet (komisyon dahil)."""
        entry = pos["entry_price"]
        entry_context = dict(pos.get("entry_context") or {})
        # Positions opened before the context correction may still carry the
        # generic spot plan.  Normalize their closed-trade audit record to the
        # BB-MFI plan that the position manager actually enforced.
        if pos.get("strategy") == "BB_MFI_MEAN_REVERSION":
            entry_context.update({
                "profit_target_pct": config.BB_MFI_TAKE_PROFIT_PCT,
                "stop_loss_pct": config.BB_MFI_STOP_LOSS_PCT,
                "max_hold_sec": None,
            })
        buy_commission = (pos["quantity"] * entry) * config.COMMISSION_PCT
        total_commission = buy_commission + commission
        pnl = (exit_price - entry) * pos["quantity"] - total_commission
        pnl_pct = (pnl / (entry * pos["quantity"])) * 100 if entry else 0.0
        hold_seconds = max(0.0, time.time() - pos.get("entry_time", time.time()))
        max_favorable_pct = ((pos.get("max_price", entry) - entry) / entry) if entry else 0.0
        max_adverse_pct = ((pos.get("min_price", entry) - entry) / entry) if entry else 0.0
        return {
            "symbol": symbol, "strategy": pos.get("strategy", "UT"),
            "trade_id": pos.get("trade_id"),
            "side": pos.get("side", "LONG"), "entry_price": entry, "exit_price": exit_price,
            "quantity": pos.get("quantity", 0.0), "pnl": pnl, "pnl_pct": pnl_pct,
            "entry_time": pos.get("entry_time"), "exit_time": time.time(),
            "commission": total_commission, "reason": reason,
            "entry_context": entry_context,
            "strategy_revision": entry_context.get("strategy_revision", config.STRATEGY_REVISION),
            "max_favorable_pct": max_favorable_pct,
            "max_adverse_pct": max_adverse_pct,
            "hold_seconds": hold_seconds,
        }

    async def open_position(self, symbol, entry_price, side="LONG", strat_name="UT", order_value=None, stop_loss_pct=None, take_profit_pct=None, max_hold_sec=None):
        # Strategy loop ve Gainer Radar aynı anda aynı sembolü tetikleyebilir.
        # Cüzdan düşümü ile pozisyon kaydı tek atomik akışta yapılmalı.
        async with self._open_position_lock:
            return await self._open_position_unlocked(symbol, entry_price, side, strat_name, order_value, stop_loss_pct, take_profit_pct, max_hold_sec)

    @staticmethod
    def _liquidity_reason(details, prefix="entry_ineligible"):
        failed = [key for key, ok in (details or {}).get("checks", {}).items() if not ok]
        return prefix + ":" + ",".join(failed or ["unknown"])

    async def _refresh_liquidity_snapshot(self, symbol):
        """Refresh the top-of-book only when the local snapshot cannot gate an entry."""
        if not self.market:
            return {}
        flow = self.market.get_orderflow(symbol)
        try:
            freshness = self.market.data_freshness(symbol, config.MOMENTUM_TIMEFRAME)
            orderbook_stale = not freshness.get("orderbook", {}).get("fresh", False)
        except Exception:
            orderbook_stale = False
        needs_snapshot = (
            not flow.get("bid_qty")
            or not flow.get("ask_qty")
            or flow.get("spread_pct") is None
            or orderbook_stale
        )
        if not needs_snapshot:
            return flow
        try:
            book = await orderbook(symbol, 5)
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            if bids and asks:
                bid_price, bid_qty = float(bids[0][0]), float(bids[0][1])
                ask_price, ask_qty = float(asks[0][0]), float(asks[0][1])
                mid = (bid_price + ask_price) / 2
                flow.update({"bid_qty": bid_qty, "ask_qty": ask_qty,
                             "spread_pct": ((ask_price - bid_price) / mid * 100) if mid else None,
                             "source": "binance_tr_public_rest",
                             "updated_at": time.time()})
                self.market.orderflow[symbol.upper()] = flow
        except Exception as exc:
            print(f"[Likidite] {symbol} REST order-book snapshot alınamadı: {exc}")
        return flow

    async def _entry_order_value(self, symbol, strat_name, requested_order_value=None):
        """Mirror the paper order-size calculation without opening or recording a signal."""
        try_balance = await database.get_wallet_balance("TRY")
        requested = float(requested_order_value or 0)
        if strat_name == "LLM_PAPER" and requested > 0:
            return min(requested, try_balance / (1 + config.COMMISSION_PCT))
        available_value = try_balance / (1 + config.COMMISSION_PCT)
        if strat_name == "BB_MFI_MEAN_REVERSION":
            # User-selected cash budgeting: each new BB-MFI layer consumes a
            # percentage of currently available TRY, never total equity.
            order_pct = float(config.SYMBOL_ORDER_PCT.get(symbol, config.ORDER_PCT))
            order_value = available_value * max(0.001, min(order_pct, 1.0))
        else:
            order_pct = float(config.SYMBOL_ORDER_PCT.get(symbol, config.ORDER_PCT))
            order_value = available_value * max(0.001, min(order_pct, 1.0))
        if order_value < config.MIN_PARTIAL_ORDER_TRY and strat_name != "BB_MFI_MEAN_REVERSION":
            if available_value >= config.FALLBACK_ORDER_TRY:
                order_value = config.FALLBACK_ORDER_TRY
            elif available_value >= config.MIN_PARTIAL_ORDER_TRY:
                order_value = available_value
        return order_value

    async def entry_liquidity_preflight(self, symbol, strat_name="UT", requested_order_value=None):
        """Gate a *new* entry before strategy/LLM signal production.

        This creates no signal, order, or position.  A false result is an
        eligibility observation for the caller's scan log, not BUY_BLOCKED.
        """
        symbol = str(symbol).replace("_", "").upper()
        if not self.market or not config.LIQUIDITY_FILTER_ENABLED:
            return True, {"disabled": not config.LIQUIDITY_FILTER_ENABLED}
        order_value = await self._entry_order_value(symbol, strat_name, requested_order_value)
        # Balance/position policy is deliberately left to open_position; this
        # gate owns only current market liquidity eligibility.
        if order_value < config.MIN_PARTIAL_ORDER_TRY:
            return True, {"skipped": "order_value_below_minimum", "order_value_try": order_value}
        await self._refresh_liquidity_snapshot(symbol)
        liquid, details = self.market.liquidity_status(symbol, order_value)
        details = {**details, "order_value_try": order_value}
        if not liquid:
            details["reason"] = self._liquidity_reason(details)
        return liquid, details

    async def _open_position_unlocked(self, symbol, entry_price, side="LONG", strat_name="UT", requested_order_value=None, requested_stop_pct=None, requested_tp_pct=None, requested_hold_sec=None):
        symbol = str(symbol).replace("_", "").upper()
        # Every entry path (strategy, LLM, alert, radar and pending orders)
        # converges here. A passive symbol must therefore be rejected at this
        # final writer boundary, not only skipped by the strategy scan loop.
        if config.SYMBOL_ACTIVITY_FILTER_ENABLED and symbol in config.PASSIVE_SYMBOLS:
            activity = dict(config.SYMBOL_ACTIVITY_STATUS.get(symbol) or {})
            failed = [key for key, ok in activity.get("checks", {}).items() if not ok]
            reason = "symbol_activity:passive"
            if failed:
                reason += ":" + ",".join(failed)
            blocked = {
                "symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                "reason": reason, "strategy": strat_name, "timestamp": time.time(),
                "activity": activity,
            }
            await database.save_signal(blocked)
            print(f"[Aktivite] {symbol} yeni giriş engellendi: {reason}", flush=True)
            return blocked
        llm_guard = await database.get_llm_symbol_guard(symbol) if strat_name == "LLM_PAPER" else None
        if llm_guard and llm_guard.get("status") == "active":
            blocked_until = llm_guard.get("blocked_until")
            if blocked_until is None or float(blocked_until) > time.time():
                reason = f"llm_guard:{llm_guard.get('guard_type', 'symbol_block')}"
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price, "reason": reason, "strategy": strat_name, "timestamp": time.time(), "guard_revision": llm_guard.get("revision")})
                return None
            llm_guard = await database.upsert_llm_symbol_guard(symbol, llm_guard.get("guard_type", "cooldown"), "expired", blocked_until, "cooldown_expired", llm_guard.get("evidence"))
        if llm_guard and llm_guard.get("status") == "expired":
            evidence = llm_guard.get("evidence") or {}
            exit_price = evidence.get("exit_price")
            try:
                moved = abs(float(entry_price) - float(exit_price)) / float(exit_price) if exit_price else 1.0
            except (TypeError, ValueError, ZeroDivisionError):
                moved = 1.0
            required_move = max(config.LLM_REENTRY_MIN_MOVE_PCT, float(evidence.get("rearm_required_pct") or 0))
            if moved < required_move:
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                            "reason": "llm_guard_rearm_not_reached", "strategy": strat_name,
                                            "timestamp": time.time(), "rearm_required_pct": required_move,
                                            "last_exit_price": exit_price})
                return None
        # The in-memory portfolio can lag after a restart or another worker's
        # write. Reconcile this symbol before attempting the unique DB insert.
        db_positions = await database.load_positions()
        if symbol not in self.positions and symbol in db_positions:
            self.positions[symbol] = db_positions[symbol]
        if symbol in self.positions:
            await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                        "reason": "position_already_open", "strategy": strat_name, "timestamp": time.time()})
            existing = self.positions[symbol]
            max_layers = int(config.SYMBOL_PYRAMIDING_LAYERS.get(symbol, config.PYRAMIDING_LAYERS))
            layers = int(existing.get("layers", 1))
            if strat_name != existing.get("strategy"):
                return None
            if strat_name == "BB_MFI_MEAN_REVERSION":
                quantity = float(existing.get("quantity") or 0)
                average_entry = float(existing.get("entry_price") or 0)
                net_exit_value = quantity * float(entry_price) * (1 - config.COMMISSION_PCT)
                cost_basis = quantity * average_entry * (1 + config.COMMISSION_PCT)
                if config.BB_MFI_PYRAMID_REQUIRE_NET_PROFIT and (quantity <= 0 or net_exit_value <= cost_basis):
                    await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                                "reason": "bb_mfi_pyramid_underwater", "strategy": strat_name,
                                                "timestamp": time.time(), "layers": layers,
                                                "net_unrealized_pnl_try": net_exit_value - cost_basis})
                    return None
                extension_allowed = (layers < max_layers + config.BB_MFI_PYRAMID_PROFIT_EXTENSION_LAYERS and
                                     self._bb_mfi_layers_net_profitable(existing, entry_price))
                if layers >= max_layers and not extension_allowed:
                    await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                                "reason": "bb_mfi_pyramid_profit_extension_not_eligible", "strategy": strat_name,
                                                "timestamp": time.time(), "layers": layers})
                    return None
            elif layers >= max_layers:
                return None
        else:
            if len(self.positions) >= self.max_open_positions():
                blocked = {"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                           "reason": "max_open_positions_reached", "strategy": strat_name, "timestamp": time.time()}
                await database.save_signal(blocked)
                return blocked
            if strat_name != "LLM_PAPER":
                block_reason = self._reentry_block_reason(symbol, self._strategy_tf(strat_name))
                if block_reason:
                    blocked = {"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                               "reason": block_reason, "strategy": strat_name, "timestamp": time.time()}
                    await database.save_signal(blocked)
                    return blocked
        try_balance = await database.get_wallet_balance("TRY")
        requested_order_value = float(requested_order_value or 0)
        if strat_name == "LLM_PAPER" and requested_order_value > 0:
            order_value = min(requested_order_value, try_balance / (1 + config.COMMISSION_PCT))
            if order_value < config.MIN_PARTIAL_ORDER_TRY:
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price, "reason": "llm_order_below_minimum_or_balance", "strategy": strat_name, "timestamp": time.time()})
                return None
        else:
            order_pct = float(config.SYMBOL_ORDER_PCT.get(symbol, config.ORDER_PCT))
            available_value = try_balance / (1 + config.COMMISSION_PCT)
            if strat_name == "BB_MFI_MEAN_REVERSION":
                order_value = available_value * max(0.001, min(order_pct, 1.0))
            else:
                order_value = available_value * max(0.001, min(order_pct, 1.0))
            if order_value < config.MIN_PARTIAL_ORDER_TRY and strat_name != "BB_MFI_MEAN_REVERSION":
                # Küçük yüzde tutarı yüzünden kullanılabilir bakiye boşta
                # kalmasın: önce 250 TL kademeli tutarı, son aşamada ise
                # minimumun üzerindeki tüm kalan bakiyeyi kullan.
                if available_value >= config.FALLBACK_ORDER_TRY:
                    order_value = config.FALLBACK_ORDER_TRY
                elif available_value >= config.MIN_PARTIAL_ORDER_TRY:
                    order_value = available_value
                elif strat_name != "BB_MFI_MEAN_REVERSION":
                    await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                                "reason": "insufficient_balance_for_minimum_order", "strategy": strat_name, "timestamp": time.time()})
                    return None
            if order_value < config.MIN_PARTIAL_ORDER_TRY:
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                            "reason": "remaining_cash_pct_below_minimum_order", "strategy": strat_name, "timestamp": time.time()})
                return None
        details = {}
        expected_gross = None
        expected_net = None
        if self.market:
            # The final recheck covers the small race between a preflight and
            # the atomic portfolio write.  It is an eligibility outcome, never
            # a BUY_BLOCKED signal or notification.
            flow = await self._refresh_liquidity_snapshot(symbol)
            liquid, details = self.market.liquidity_status(symbol, order_value)
            if not liquid:
                reason = self._liquidity_reason(details, "entry_recheck_failed")
                ineligible = {"symbol": symbol, "action": "ENTRY_INELIGIBLE", "price": entry_price,
                              "reason": reason, "strategy": strat_name, "timestamp": time.time(),
                              "liquidity": details}
                print(f"[Likidite] {symbol} giriş ön-koşulu sağlanmadı: {reason}")
                return ineligible
            target_pct = config.BB_MFI_TAKE_PROFIT_PCT if strat_name == "BB_MFI_MEAN_REVERSION" else config.SPOT_PROFIT_TARGET_PCT
            target_value = order_value * (1 + target_pct)
            expected_gross = order_value * target_pct
            expected_fees = (order_value + target_value) * config.COMMISSION_PCT
            expected_slippage = order_value * config.ESTIMATED_SLIPPAGE_PCT * 2
            expected_net = expected_gross - expected_fees - expected_slippage
        is_bb_mfi = strat_name == "BB_MFI_MEAN_REVERSION"
        planned_take_profit_pct = (
            float(requested_tp_pct) if strat_name == "LLM_PAPER" and requested_tp_pct is not None
            else (None if strat_name == "LLM_PAPER" else
                  (config.BB_MFI_TAKE_PROFIT_PCT if is_bb_mfi else config.SPOT_PROFIT_TARGET_PCT))
        )
        planned_stop_loss_pct = (
            float(requested_stop_pct) if strat_name == "LLM_PAPER" and requested_stop_pct is not None
            else (None if strat_name == "LLM_PAPER" else
                  (config.BB_MFI_STOP_LOSS_PCT if is_bb_mfi else config.HARD_STOP_LOSS_PCT))
        )
        # BB-MFI exits through its fixed stop/target or a confirmed sell signal;
        # the generic max-hold setting is not an active exit for this strategy.
        planned_max_hold_sec = (
            int(requested_hold_sec) if strat_name == "LLM_PAPER" and requested_hold_sec is not None
            else (None if strat_name in {"LLM_PAPER", "BB_MFI_MEAN_REVERSION"}
                  else config.MAX_POSITION_HOLD_SEC)
        )
        entry_context = {"strategy_revision": config.STRATEGY_REVISION,
                         "liquidity": details if self.market else {},
                         "expected_gross_pnl_try": expected_gross if self.market else None,
                         "expected_net_pnl_try": expected_net if self.market else None,
                         "commission_pct": config.COMMISSION_PCT,
                         "estimated_slippage_pct": config.ESTIMATED_SLIPPAGE_PCT,
                         "profit_target_pct": planned_take_profit_pct,
                         "stop_loss_pct": planned_stop_loss_pct,
                         "max_hold_sec": planned_max_hold_sec,
                         "bear_pressure_filter_enabled": config.BB_MFI_BEAR_PRESSURE_FILTER_ENABLED,
                         "pyramid_require_net_profit": config.BB_MFI_PYRAMID_REQUIRE_NET_PROFIT,
                         "pyramid_profit_extension_layers": config.BB_MFI_PYRAMID_PROFIT_EXTENSION_LAYERS,
                         "order_value_try": order_value,
                         "partial_order": order_value < config.DEFAULT_ORDER_USDT}
        if self.market:
            technical_tf = self._strategy_tf(strat_name)
            symbol_klines = {
                technical_tf: self.market.klines.get(technical_tf, {}).get(symbol.upper(), {}),
                "1d": self.market.klines.get("1d", {}).get(symbol.upper(), {}),
            }
            entry_context["technical"] = calculate_snapshot(
                symbol, entry_price, symbol_klines,
                flow,
                self.market.ticker_24h.get(symbol, 0),
                order_value, technical_tf
            )
            if strat_name == "BB_MFI_MEAN_REVERSION":
                block_reason = self._bb_mfi_entry_context_block_reason(
                    entry_context["technical"], symbol_klines[technical_tf]
                )
                if block_reason:
                    blocked = {
                        "symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                        "reason": block_reason, "strategy": strat_name, "timestamp": time.time(),
                        "technical": entry_context["technical"],
                    }
                    await database.save_signal(blocked)
                    return blocked
        quantity = order_value / entry_price
        commission = order_value * config.COMMISSION_PCT

        next_cash = try_balance - order_value - commission

        existing = self.positions.get(symbol)
        if existing:
            layer_entry_price = float(entry_price)
            total_qty = existing["quantity"] + quantity
            entry_price = ((existing["entry_price"] * existing["quantity"]) + (entry_price * quantity)) / total_qty
            pos = {**existing, "entry_price": entry_price, "spot_profit_target": entry_price * (1 + (float(requested_tp_pct) if requested_tp_pct is not None else config.SPOT_PROFIT_TARGET_PCT)), "quantity": total_qty, "layers": existing.get("layers", 1) + 1}
            pos.setdefault("entry_layers", []).append({"entry_price": layer_entry_price, "quantity": quantity})
            if strat_name == "BB_MFI_MEAN_REVERSION":
                pos["system_stop_price"] = entry_price * (1 - config.BB_MFI_STOP_LOSS_PCT)
                pos["system_take_profit_price"] = entry_price * (1 + config.BB_MFI_TAKE_PROFIT_PCT)
                pos["stop_price"] = pos["system_stop_price"]
                pos["take_profit"] = pos["system_take_profit_price"]
        else:
            pos = {
            "side": "LONG",  # Binance TR Spot olduğu için her zaman LONG
            "entry_price": entry_price,
                "spot_profit_target": entry_price * (1 + (float(requested_tp_pct) if strat_name == "LLM_PAPER" and requested_tp_pct is not None else config.SPOT_PROFIT_TARGET_PCT)),
                "quantity": quantity, "entry_time": time.time(), "strategy": strat_name, "layers": 1,
                "trade_id": uuid.uuid4().hex,
                "max_price": entry_price, "min_price": entry_price, "entry_context": entry_context,
                "entry_layers": [{"entry_price": float(entry_price), "quantity": quantity}]
            }
            if strat_name != "LLM_PAPER":
                technical_tf = self._strategy_tf(strat_name)
                system_kline = self.market.get_ut_kline(symbol, technical_tf) if self.market else None
                atr = self.calculate_atr(system_kline, config.SYSTEM_ATR_PERIOD) if system_kline else None
                strategy_stop_pct = config.BB_MFI_STOP_LOSS_PCT if strat_name == "BB_MFI_MEAN_REVERSION" else config.HARD_STOP_LOSS_PCT
                stop_distance = entry_price * strategy_stop_pct if strat_name == "BB_MFI_MEAN_REVERSION" else max(
                    entry_price * strategy_stop_pct,
                    float(atr or 0) * config.SYSTEM_INITIAL_STOP_ATR_MULTIPLIER,
                )
                if stop_distance <= 0:
                    stop_distance = entry_price * strategy_stop_pct
                pos["system_stop_price"] = entry_price - stop_distance
                pos["system_take_profit_price"] = entry_price * (1 + config.BB_MFI_TAKE_PROFIT_PCT) if strat_name == "BB_MFI_MEAN_REVERSION" else entry_price + stop_distance * config.SYSTEM_RISK_REWARD
                pos["stop_price"] = pos["system_stop_price"]
                pos["take_profit"] = pos["system_take_profit_price"]
                pos["system_atr"] = float(atr or 0)
                pos["system_risk_reward"] = config.SYSTEM_RISK_REWARD
                pos["system_exit_model"] = "atr_trailing_after_rr_target"
            if strat_name == "LLM_PAPER":
                if requested_stop_pct is not None:
                    pos["llm_stop_price"] = entry_price * (1 - max(0.0001, float(requested_stop_pct)))
                if requested_tp_pct is not None:
                    pos["llm_take_profit_price"] = entry_price * (1 + max(0.0001, float(requested_tp_pct)))
                if requested_hold_sec is not None:
                    pos["llm_max_hold_sec"] = max(60, int(requested_hold_sec))
        self.positions[symbol] = pos
        sig = {"symbol": symbol, "action": "BUY_SIGNAL", "price": entry_price, "reason": "position_opened", "strategy": strat_name, "trade_id": pos.get("trade_id"), "strategy_revision": config.STRATEGY_REVISION, "timestamp": time.time()}
        try:
            await database.commit_open_position(symbol, symbol.replace("TRY", ""), next_cash, quantity, pos, sig)
        except Exception as exc:
            error_text = str(exc).lower()
            if any(token in error_text for token in ("duplicate key", "unique constraint", "max_open_positions_reached", "insufficient_paper_balance")):
                self.positions = await database.load_positions()
                reason = "max_open_positions_reached" if "max_open_positions" in error_text else "insufficient_paper_balance" if "insufficient" in error_text else "position_already_open"
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                            "reason": reason, "strategy": strat_name, "timestamp": time.time()})
                return {"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                        "reason": reason, "strategy": strat_name, "timestamp": time.time()}
            raise
        return sig

