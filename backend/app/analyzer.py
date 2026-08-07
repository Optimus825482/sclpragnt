import time
import asyncio
import numpy as np
import uuid
from app.config import config
from app.technical_analysis import calculate_snapshot, _adx, _stochastic
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
        """Use the configured global paper-trading position limit."""
        return max(1, int(config.MAX_OPEN_POSITIONS))

    async def load_state(self):
        self.positions = await database.load_positions()
        self.pending_orders = await database.load_paper_orders()

    async def place_paper_order(self, order):
        """Execute or queue an exchange-like order entirely in paper trading."""
        client_request_id = str(order.get("client_request_id") or "").strip() or None
        if client_request_id:
            duplicate = next((item for item in self.pending_orders if item.get("client_request_id") == client_request_id), None)
            if duplicate:
                return {"ok": True, "paper_only": True, "idempotent_replay": True, "status": duplicate.get("status"), "order": duplicate}
        order_type = str(order.get("order_type", "MARKET")).upper()
        if order_type not in {"MARKET", "LIMIT", "STOP_LIMIT", "STOP_MARKET", "OCO"}:
            return {"ok": False, "error": "Desteklenmeyen paper emir türü"}
        symbol = str(order.get("symbol") or "").replace("_", "").upper()
        ticker = self.market.get_ticker(symbol) if self.market else None
        price = float(order.get("price") or (ticker or {}).get("last_price") or 0)
        if not symbol or price <= 0: return {"ok": False, "error": "Geçerli sembol ve fiyat gerekli"}
        if order_type == "MARKET":
            return await self.open_position(symbol, price, str(order.get("side", "LONG")).upper(), "LLM_PAPER", order.get("order_value_try"), order.get("stop_loss_pct"), order.get("take_profit_pct"), order.get("max_hold_seconds"))
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
                triggered = (price >= take_profit_price if side in {"SELL", "SHORT"} else price <= take_profit_price) or (price <= stop if side in {"SELL", "SHORT"} else price >= stop)
                if not triggered: continue
                execution_price = price
                result = await self.close_position(symbol, execution_price, "paper_oco_take_profit" if price == take_profit_price else "paper_oco_stop") if side in {"SELL", "SHORT"} and symbol in self.positions else await self.open_position(symbol, execution_price, "LONG", "LLM_PAPER", order.get("order_value_try"), order.get("stop_loss_pct"), order.get("take_profit_pct"), order.get("max_hold_seconds"))
                order["status"] = "FILLED" if result else "REJECTED"
                await database.save_paper_order(order)
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
            order["status"] = "FILLED" if result else "REJECTED"
            await database.save_paper_order(order)
            if order_type == "OCO":
                for other in self.pending_orders:
                    if other.get("oco_group") == order.get("oco_group") and other is not order: other["status"] = "CANCELLED"

    def _current_bar(self, symbol, timeframe):
        if not self.market:
            return None
        kline = self.market.get_ut_kline(symbol, timeframe)
        times = kline.get("times", [])
        return len(times) - 1 if times else len(kline.get("closes", [])) - 1

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

    def calculate_crsi(self, prices, rsi_period=3, streak_rsi_period=2, rank_period=100):
        """Connors RSI: kısa RSI + streak RSI + ROC percentile rank (0-100)."""
        if len(prices) < rank_period + rsi_period + streak_rsi_period + 2:
            return None
        price_rsi = self.calculate_rsi(prices, rsi_period)
        streaks = []
        streak = 0
        for i in range(1, len(prices)):
            if prices[i] > prices[i - 1]: streak = max(streak, 0) + 1
            elif prices[i] < prices[i - 1]: streak = min(streak, 0) - 1
            else: streak = 0
            streaks.append(streak)
        streak_rsi = self.calculate_rsi(streaks, streak_rsi_period)
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

    # --- YARDIMCI: Connors RSI (CRSI) Hesaplama ---
    def calculate_crsi(self, prices, rsi_period=3, streak_period=2, rank_period=100):
        if len(prices) < rank_period + 2: return None

        # 1. Standart RSI (Kısa periyotlu, genelde 3)
        rsi = self.calculate_rsi(prices, rsi_period)
        if rsi is None: return None

        # 2. Streak RSI (Üst üste düşüş/yükseliş serisi)
        streaks = [0]
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                streaks.append(max(1, streaks[-1] + 1) if streaks[-1] > 0 else 1)
            elif prices[i] < prices[i-1]:
                streaks.append(min(-1, streaks[-1] - 1) if streaks[-1] < 0 else -1)
            else:
                streaks.append(0)

        up_streaks = np.where(np.array(streaks) > 0, np.array(streaks), 0)
        down_streaks = np.where(np.array(streaks) < 0, abs(np.array(streaks)), 0)
        avg_up = np.mean(up_streaks[-streak_period:])
        avg_down = np.mean(down_streaks[-streak_period:])
        if avg_down == 0: streak_rsi = 100
        else: streak_rsi = 100 - (100 / (1 + (avg_up / avg_down)))

        # 3. Percent Rank (Yüzdelik Sıralama - Genelde 50 periyot)
        current_change = prices[-1] - prices[-2]
        rank_lookback = prices[-rank_period-1:-1]
        changes = np.diff(rank_lookback)
        if len(changes) == 0: return None
        percent_rank = (np.sum(changes < current_change) / len(changes)) * 100

        # CRSI = Üçünün ortalaması
        return (rsi + streak_rsi + percent_rank) / 3

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
            "VWAP_MEAN_REVERSION": config.MEAN_REVERSION_TIMEFRAME,
            "KELTNER_BREAKOUT": config.KELTNER_TIMEFRAME,
            "CHOP_TREND_FILTER": config.CHOP_TIMEFRAME,
            "DONCHIAN_BREAKOUT": config.DONCHIAN_TIMEFRAME,
        }.get(strat_name, config.UT_TIMEFRAME)

    async def _manage_open_position(self, symbol, price, strat_name):
        tf = self._strategy_tf(strat_name)
        kline = self.market.get_ut_kline(symbol, tf)
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
        if pos and pos.get("strategy") != "LLM_PAPER" and config.HARD_STOP_LOSS_PCT > 0 and price <= pos["entry_price"] * (1 - config.HARD_STOP_LOSS_PCT):
            return await self.close_position(symbol, price, "hard_stop_loss")
        if pos:
            elapsed = max(0.0, time.time() - pos.get("entry_time", time.time()))
            entry = pos.get("entry_price", price)
            max_progress = max(0.0, (pos.get("max_price", entry) - entry) / entry) if entry else 0.0
            if elapsed >= config.EARLY_FAILURE_SEC and max_progress < config.EARLY_FAILURE_MIN_PROGRESS_PCT:
                return await self.close_position(symbol, price, "early_failure_no_progress")
            if elapsed >= config.STALE_POSITION_SEC and max_progress < config.STALE_POSITION_MIN_PROGRESS_PCT:
                return await self.close_position(symbol, price, "stale_position_no_progress")
            # Kârı koru: hedefe ulaşmadan önce pozisyon yeterince ilerlediyse
            # tepe fiyatın gerisinden takip eden stop ile geri dönüşte çık.
            # Stop hiçbir zaman komisyon/slippage sonrası başa-baş seviyesinin
            # altında çalıştırılmaz.
            if (config.TRAILING_STOP_ENABLED
                    and max_progress >= config.TRAILING_ACTIVATION_PCT
                    and config.TRAILING_STOP_PCT > 0):
                trail_price = pos.get("max_price", entry) * (1 - config.TRAILING_STOP_PCT)
                net_floor = entry * (1 + config.min_net_exit_pct(pos.get("quantity", 0) * entry))
                if price <= trail_price and price >= net_floor:
                    return await self.close_position(symbol, price, "trailing_profit_protection")
            if (config.STALE_POSITION_EXIT_BELOW_COST and elapsed >= config.STALE_POSITION_SEC and
                    price < entry * (1 + config.min_net_exit_pct(pos.get("quantity", 0) * entry))):
                return await self.close_position(symbol, price, "stale_position_below_cost")
            if pos.get("strategy") == "LLM_PAPER" and pos.get("llm_take_profit_price") and price >= pos["llm_take_profit_price"]:
                return await self.close_position(symbol, price, "llm_take_profit")
            if pos.get("strategy") == "LLM_PAPER":
                target_pct = None
            elif elapsed < config.TIME_DECAY_TP_STAGE_2_SEC:
                target_pct = config.TIME_DECAY_TP_1_PCT
                target_reason = "time_decay_target_1_0pct"
            elif elapsed < config.TIME_DECAY_TP_STAGE_3_SEC:
                target_pct = config.TIME_DECAY_TP_2_PCT
                target_reason = "time_decay_target_0_75pct"
            elif elapsed < config.TIME_DECAY_BREAKEVEN_SEC:
                target_pct = config.TIME_DECAY_TP_3_PCT
                target_reason = "time_decay_target_0_5pct"
            else:
                # Never exit below the amount required to cover both sides'
                # costs, slippage and the configured minimum net PnL.
                target_pct = config.min_net_exit_pct(pos.get("quantity", 0) * pos["entry_price"])
                target_reason = "breakeven_exit"
            if target_pct is not None and price >= pos["entry_price"] * (1 + target_pct):
                return await self.close_position(symbol, price, target_reason)
        if pos:
            max_hold = pos.get("llm_max_hold_sec") if pos.get("strategy") == "LLM_PAPER" else config.STRATEGY_MAX_HOLD_SEC.get(strat_name, config.MAX_POSITION_HOLD_SEC)
            if time.time() - pos.get("entry_time", time.time()) >= max_hold:
                reason = f"max_hold_{max_hold // 3600}h" if max_hold % 3600 == 0 else f"max_hold_{max_hold // 60}m"
                return await self.close_position(symbol, price, reason)
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

    async def evaluate(self, symbol, ticker):
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
                (config.MEAN_REVERSION_ENABLED, "VWAP_MEAN_REVERSION", self.strategy_mean_reversion, config.MEAN_REVERSION_TIMEFRAME),
                (config.KELTNER_ENABLED, "KELTNER_BREAKOUT", self.strategy_keltner_breakout, config.KELTNER_TIMEFRAME),
                (config.CHOP_ENABLED, "CHOP_TREND_FILTER", self.strategy_chop_trend, config.CHOP_TIMEFRAME),
                (config.DONCHIAN_ENABLED, "DONCHIAN_BREAKOUT", self.strategy_donchian_breakout, config.DONCHIAN_TIMEFRAME),
            ]
            selected = next((item for item in strategy_specs if item[1] == strat and item[0]), None)
            if selected:
                _, name, fn, tf = selected
                strategy_kline = self.market.get_ut_kline(symbol, tf)
                result = fn(strategy_kline, symbol)
                if result == "sell" and config.EXIT_ON_OPPOSITE_SIGNAL:
                    return [await self.close_position(symbol, price, "opposite_signal")]
                # Spotta aynı sembole tekrar katman ekleme yok: tek sembol = tek pozisyon.
                # Pozisyon açıkken yeni BUY sinyali işlem sinyaline dönüştürülmez.
            return signals

        # Açık pozisyon yok: kapanış sonrası sembol cooldown'ını uygula.
        blocked_until = self._timeout_block_until.get(symbol)
        if blocked_until and time.time() < blocked_until:
            return signals
        if blocked_until:
            self._timeout_block_until.pop(symbol, None)
        hard_stop_block_until = self._hard_stop_block_until.get(symbol)
        if hard_stop_block_until and time.time() < hard_stop_block_until:
            return signals
        if hard_stop_block_until:
            self._hard_stop_block_until.pop(symbol, None)
        if symbol in self._cooldown_until:
            bar = self._current_bar(symbol, config.MOMENTUM_TIMEFRAME)
            if bar is not None and bar < self._cooldown_until[symbol]:
                return signals
            self._cooldown_until.pop(symbol, None)

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
            (config.MEAN_REVERSION_ENABLED, "VWAP_MEAN_REVERSION", self.strategy_mean_reversion, config.MEAN_REVERSION_TIMEFRAME),
            (config.KELTNER_ENABLED, "KELTNER_BREAKOUT", self.strategy_keltner_breakout, config.KELTNER_TIMEFRAME),
            (config.CHOP_ENABLED, "CHOP_TREND_FILTER", self.strategy_chop_trend, config.CHOP_TIMEFRAME),
            (config.DONCHIAN_ENABLED, "DONCHIAN_BREAKOUT", self.strategy_donchian_breakout, config.DONCHIAN_TIMEFRAME),
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
        sig = {"symbol": symbol, "action": "CLOSE_LONG", "reason": reason, "price": price, "timestamp": time.time()}
        await database.commit_close_position(symbol, symbol.replace("TRY", ""), try_balance + sell_value - commission, trade, sig)
        try:
            await agent_learning.record_paper_trade_outcome(trade)
        except Exception as learning_error:
            print(f"[Learning] paper outcome kaydedilemedi: {learning_error}")
        del self.positions[symbol]
        tf = self._strategy_tf(pos.get("strategy", "UT"))
        current_bar = self._current_bar(symbol, tf)
        if current_bar is not None:
            self._cooldown_until[symbol] = current_bar + config.COOLDOWN_BARS
        if reason.startswith("max_hold_") or reason in {"early_failure_no_progress", "stale_position_no_progress"}:
            self._timeout_block_until[symbol] = time.time() + config.TIMEOUT_REENTRY_BLOCK_SEC
        elif reason == "hard_stop_loss":
            self._hard_stop_block_until[symbol] = time.time() + config.HARD_STOP_REENTRY_BLOCK_SEC
        return sig

    async def _record_trade(self, symbol, pos, exit_price, reason, commission=0.0):
        """Kapanan pozisyonu işlem geçmişine kaydet (komisyon dahil)."""
        entry = pos["entry_price"]
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
            "entry_context": pos.get("entry_context", {}),
            "strategy_revision": pos.get("entry_context", {}).get("strategy_revision", config.STRATEGY_REVISION),
            "max_favorable_pct": max_favorable_pct,
            "max_adverse_pct": max_adverse_pct,
            "hold_seconds": hold_seconds,
        }

    async def open_position(self, symbol, entry_price, side="LONG", strat_name="UT", order_value=None, stop_loss_pct=None, take_profit_pct=None, max_hold_sec=None):
        # Strategy loop ve Gainer Radar aynı anda aynı sembolü tetikleyebilir.
        # Cüzdan düşümü ile pozisyon kaydı tek atomik akışta yapılmalı.
        async with self._open_position_lock:
            return await self._open_position_unlocked(symbol, entry_price, side, strat_name, order_value, stop_loss_pct, take_profit_pct, max_hold_sec)

    async def _open_position_unlocked(self, symbol, entry_price, side="LONG", strat_name="UT", requested_order_value=None, requested_stop_pct=None, requested_tp_pct=None, requested_hold_sec=None):
        llm_guard = await database.get_llm_symbol_guard(symbol) if strat_name == "LLM_PAPER" else None
        if llm_guard and llm_guard.get("status") == "active":
            blocked_until = llm_guard.get("blocked_until")
            if blocked_until is None or float(blocked_until) > time.time():
                reason = f"llm_guard:{llm_guard.get('guard_type', 'symbol_block')}"
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price, "reason": reason, "strategy": strat_name, "timestamp": time.time(), "guard_revision": llm_guard.get("revision")})
                return None
            await database.upsert_llm_symbol_guard(symbol, llm_guard.get("guard_type", "cooldown"), "expired", blocked_until, "cooldown_expired", llm_guard.get("evidence"))
        # The in-memory portfolio can lag after a restart or another worker's
        # write. Reconcile this symbol before attempting the unique DB insert.
        db_positions = await database.load_positions()
        if symbol not in self.positions and symbol in db_positions:
            self.positions[symbol] = db_positions[symbol]
        if symbol in self.positions:
            await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                        "reason": "position_already_open", "strategy": strat_name, "timestamp": time.time()})
            return None
        if symbol not in self.positions and len(self.positions) >= self.max_open_positions():
            await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                        "reason": "position_limit_reached", "strategy": strat_name, "timestamp": time.time()})
            return None
        try_balance = await database.get_wallet_balance("TRY")
        requested_order_value = float(requested_order_value or 0)
        if strat_name == "LLM_PAPER" and requested_order_value > 0:
            order_value = min(requested_order_value, try_balance / (1 + config.COMMISSION_PCT))
            if order_value < config.MIN_PARTIAL_ORDER_TRY:
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price, "reason": "llm_order_below_minimum_or_balance", "strategy": strat_name, "timestamp": time.time()})
                return None
        elif try_balance >= config.DEFAULT_ORDER_USDT * (1 + config.COMMISSION_PCT):
            order_value = config.DEFAULT_ORDER_USDT
        else:
            # Use the remaining cash when it is still economically meaningful;
            # reserve the entry commission before sizing the paper order.
            order_value = try_balance / (1 + config.COMMISSION_PCT)
            if order_value <= config.MIN_PARTIAL_ORDER_TRY:
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                            "reason": "insufficient_balance_for_minimum_order", "strategy": strat_name, "timestamp": time.time()})
                return None
        details = {}
        expected_gross = None
        expected_net = None
        if self.market:
            # WebSocket depth can still be warming up when a signal arrives.
            # Capture a read-only REST snapshot so the opening context does
            # not silently persist null spread/depth/order-flow values.
            flow = self.market.get_orderflow(symbol)
            if not flow.get("bid_qty") or not flow.get("ask_qty") or flow.get("spread_pct") is None:
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
            liquid, details = self.market.liquidity_status(symbol, order_value)
            if not liquid:
                failed = [key for key, ok in details.get("checks", {}).items() if not ok]
                reason = "liquidity_filter:" + ",".join(failed or ["unknown"])
                blocked = {"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                           "reason": reason, "strategy": strat_name, "timestamp": time.time()}
                print(f"[Likidite] {symbol} işlem engellendi: {reason}")
                await database.save_signal(blocked)
                return blocked
            target_value = order_value * (1 + config.SPOT_PROFIT_TARGET_PCT)
            expected_gross = order_value * config.SPOT_PROFIT_TARGET_PCT
            expected_fees = (order_value + target_value) * config.COMMISSION_PCT
            expected_slippage = order_value * config.ESTIMATED_SLIPPAGE_PCT * 2
            expected_net = expected_gross - expected_fees - expected_slippage
            minimum_net = min(config.MIN_EXPECTED_NET_PNL_TRY, order_value * config.MIN_EXPECTED_NET_PNL_TRY / config.DEFAULT_ORDER_USDT)
            if expected_net < minimum_net:
                blocked = {"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                           "reason": "net_profit_filter:expected_net_below_minimum", "strategy": strat_name, "timestamp": time.time()}
                await database.save_signal(blocked)
                return blocked
        entry_context = {"strategy_revision": config.STRATEGY_REVISION,
                         "liquidity": details if self.market else {},
                         "expected_gross_pnl_try": expected_gross if self.market else None,
                         "expected_net_pnl_try": expected_net if self.market else None,
                         "commission_pct": config.COMMISSION_PCT,
                         "estimated_slippage_pct": config.ESTIMATED_SLIPPAGE_PCT,
                         "profit_target_pct": float(requested_tp_pct) if strat_name == "LLM_PAPER" and requested_tp_pct is not None else (None if strat_name == "LLM_PAPER" else config.SPOT_PROFIT_TARGET_PCT),
                         "stop_loss_pct": float(requested_stop_pct) if strat_name == "LLM_PAPER" and requested_stop_pct is not None else (None if strat_name == "LLM_PAPER" else config.HARD_STOP_LOSS_PCT),
                         "max_hold_sec": int(requested_hold_sec) if strat_name == "LLM_PAPER" and requested_hold_sec is not None else (None if strat_name == "LLM_PAPER" else config.MAX_POSITION_HOLD_SEC),
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
        quantity = order_value / entry_price
        commission = order_value * config.COMMISSION_PCT

        next_cash = try_balance - order_value - commission

        existing = self.positions.get(symbol)
        if existing:
            total_qty = existing["quantity"] + quantity
            entry_price = ((existing["entry_price"] * existing["quantity"]) + (entry_price * quantity)) / total_qty
            pos = {**existing, "entry_price": entry_price, "spot_profit_target": entry_price * (1 + (float(requested_tp_pct) if requested_tp_pct is not None else config.SPOT_PROFIT_TARGET_PCT)), "quantity": total_qty, "layers": existing.get("layers", 1) + 1}
        else:
            pos = {
            "side": "LONG",  # Binance TR Spot olduğu için her zaman LONG
            "entry_price": entry_price,
                "spot_profit_target": entry_price * (1 + (float(requested_tp_pct) if strat_name == "LLM_PAPER" and requested_tp_pct is not None else config.SPOT_PROFIT_TARGET_PCT)),
                "quantity": quantity, "entry_time": time.time(), "strategy": strat_name, "layers": 1,
                "trade_id": uuid.uuid4().hex,
                "max_price": entry_price, "min_price": entry_price, "entry_context": entry_context
            }
            if strat_name == "LLM_PAPER":
                if requested_stop_pct is not None:
                    pos["llm_stop_price"] = entry_price * (1 - max(0.0001, float(requested_stop_pct)))
                if requested_tp_pct is not None:
                    pos["llm_take_profit_price"] = entry_price * (1 + max(0.0001, float(requested_tp_pct)))
                if requested_hold_sec is not None:
                    pos["llm_max_hold_sec"] = max(60, int(requested_hold_sec))
        self.positions[symbol] = pos
        sig = {"symbol": symbol, "action": "BUY_SIGNAL", "price": entry_price, "reason": "position_opened", "strategy": strat_name, "strategy_revision": config.STRATEGY_REVISION, "timestamp": time.time()}
        try:
            await database.commit_open_position(symbol, symbol.replace("TRY", ""), next_cash, quantity, pos, sig)
        except Exception as exc:
            if "duplicate key" in str(exc).lower() or "unique constraint" in str(exc).lower():
                self.positions = await database.load_positions()
                await database.save_signal({"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                                            "reason": "position_already_open", "strategy": strat_name, "timestamp": time.time()})
                return None
            raise
        return sig

