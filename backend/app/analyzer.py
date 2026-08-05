import time
import asyncio
import numpy as np
from app.config import config
from app.technical_analysis import calculate_snapshot
from app import database

class ScalpAnalyzer:
    def __init__(self, market):
        self.market = market
        self.positions = {}
        self._last_signal_lengths = {}
        self._cooldown_until = {}
        self._timeout_block_until = {}
        self._hard_stop_block_until = {}
        self._open_position_lock = asyncio.Lock()

    def max_open_positions(self):
        """Use the configured global paper-trading position limit."""
        return max(1, int(config.MAX_OPEN_POSITIONS))

    async def load_state(self):
        self.positions = await database.load_positions()

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
        if pos and config.HARD_STOP_LOSS_PCT > 0 and price <= pos["entry_price"] * (1 - config.HARD_STOP_LOSS_PCT):
            return await self.close_position(symbol, price, "hard_stop_loss")
        if pos:
            elapsed = max(0.0, time.time() - pos.get("entry_time", time.time()))
            if elapsed < config.TIME_DECAY_TP_STAGE_2_SEC:
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
            if price >= pos["entry_price"] * (1 + target_pct):
                return await self.close_position(symbol, price, target_reason)
        if pos and time.time() - pos.get("entry_time", time.time()) >= config.MAX_POSITION_HOLD_SEC:
            return await self.close_position(symbol, price, "max_hold_2h")
        return None

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

    def strategy_ema_vwap(self, kline, symbol=None):
        closes, highs, lows, volumes = kline.get("closes", []), kline.get("highs", []), kline.get("lows", []), kline.get("volumes", [])
        if len(closes) < 55: return None
        e9, e21, e50 = self.calculate_ema(closes, config.EMA_SHORT), self.calculate_ema(closes, config.EMA_MID), self.calculate_ema(closes, config.EMA_TREND)
        typical = (np.array(highs[-20:]) + np.array(lows[-20:]) + np.array(closes[-20:])) / 3
        vol = np.array(volumes[-20:]); vwap = float(np.sum(typical * vol) / np.sum(vol)) if np.sum(vol) else None
        if None in (e9, e21, e50, vwap): return None
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else (True, 0)
        # Tek mumluk crossover yerine son 3 mum içinde EMA21'e gerçek pullback
        # arıyoruz; böylece strateji yalnızca 1 kez değil, yeni kurulumlarda tekrar
        # sinyal üretebilir. Kapanış EMA21 üzerine dönerken trend ve VWAP korunmalı.
        recent_lows = lows[-4:-1]
        touched_ema = any(low <= e21 * 1.002 for low in recent_lows)
        bullish_reclaim = closes[-1] > closes[-2] and closes[-1] > e21
        if e9 > e21 > e50 and closes[-1] > vwap and touched_ema and bullish_reclaim and flow_ok: return "buy"
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
        closes = kline.get("closes", [])
        if len(closes) < 30: return None
        short = config.MOMENTUM_SHORT_LOOKBACK; long = config.MOMENTUM_LONG_LOOKBACK
        if len(closes) <= long: return None
        r1 = closes[-1] / closes[-short - 1] - 1; r2 = closes[-1] / closes[-long] - 1
        flow_ok, _ = self._optional_flow_filter(symbol) if symbol else (True, 0)
        if r1 > config.MOMENTUM_MIN_RETURN_PCT and r2 > 0 and flow_ok: return "buy"
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
        if ema is not None and atr and closes[-1] > ema + config.KELTNER_ATR_MULTIPLIER * atr and volumes[-1] >= avg_vol * config.KELTNER_VOLUME_MULTIPLIER and flow_ok: return "buy"
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

        # Açık pozisyonu spot kurallarıyla yönet (yalnızca sabit %2 kâr hedefi)
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
                if result == "sell":
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
        pos = self.positions.get(symbol)
        if not pos: return None
        sell_value = pos["quantity"] * price
        commission = sell_value * config.COMMISSION_PCT
        try_balance = await database.get_wallet_balance("TRY")
        await database.update_wallet_balance("TRY", try_balance + sell_value - commission)
        await database.update_wallet_balance(symbol.replace("TRY", ""), 0.0)
        await self._record_trade(symbol, pos, price, reason, commission)
        del self.positions[symbol]
        await database.delete_position(symbol)
        tf = self._strategy_tf(pos.get("strategy", "UT"))
        current_bar = self._current_bar(symbol, tf)
        if current_bar is not None:
            self._cooldown_until[symbol] = current_bar + config.COOLDOWN_BARS
        if reason == "max_hold_2h":
            self._timeout_block_until[symbol] = time.time() + config.TIMEOUT_REENTRY_BLOCK_SEC
        elif reason == "hard_stop_loss":
            self._hard_stop_block_until[symbol] = time.time() + config.HARD_STOP_REENTRY_BLOCK_SEC
        sig = {"symbol": symbol, "action": "CLOSE_LONG", "reason": reason, "price": price, "timestamp": time.time()}
        await database.save_signal(sig)
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
        await database.save_trade({
            "symbol": symbol, "strategy": pos.get("strategy", "UT"),
            "side": pos.get("side", "LONG"), "entry_price": entry, "exit_price": exit_price,
            "quantity": pos.get("quantity", 0.0), "pnl": pnl, "pnl_pct": pnl_pct,
            "entry_time": pos.get("entry_time"), "exit_time": time.time(),
            "commission": total_commission, "reason": reason,
            "entry_context": pos.get("entry_context", {}),
            "max_favorable_pct": max_favorable_pct,
            "max_adverse_pct": max_adverse_pct,
            "hold_seconds": hold_seconds,
        })

    async def open_position(self, symbol, entry_price, side="LONG", strat_name="UT"):
        # Strategy loop ve Gainer Radar aynı anda aynı sembolü tetikleyebilir.
        # Cüzdan düşümü ile pozisyon kaydı tek atomik akışta yapılmalı.
        async with self._open_position_lock:
            return await self._open_position_unlocked(symbol, entry_price, side, strat_name)

    async def _open_position_unlocked(self, symbol, entry_price, side="LONG", strat_name="UT"):
        if symbol not in self.positions and len(self.positions) >= self.max_open_positions():
            return None
        details = {}
        expected_gross = None
        expected_net = None
        if self.market:
            liquid, details = self.market.liquidity_status(symbol, config.DEFAULT_ORDER_USDT)
            if not liquid:
                failed = [key for key, ok in details.get("checks", {}).items() if not ok]
                reason = "liquidity_filter:" + ",".join(failed or ["unknown"])
                blocked = {"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                           "reason": reason, "strategy": strat_name, "timestamp": time.time()}
                print(f"[Likidite] {symbol} işlem engellendi: {reason}")
                await database.save_signal(blocked)
                return blocked
            target_value = config.DEFAULT_ORDER_USDT * (1 + config.SPOT_PROFIT_TARGET_PCT)
            expected_gross = config.DEFAULT_ORDER_USDT * config.SPOT_PROFIT_TARGET_PCT
            expected_fees = (config.DEFAULT_ORDER_USDT + target_value) * config.COMMISSION_PCT
            expected_slippage = config.DEFAULT_ORDER_USDT * config.ESTIMATED_SLIPPAGE_PCT * 2
            expected_net = expected_gross - expected_fees - expected_slippage
            if expected_net < config.MIN_EXPECTED_NET_PNL_TRY:
                blocked = {"symbol": symbol, "action": "BUY_BLOCKED", "price": entry_price,
                           "reason": "net_profit_filter:expected_net_below_minimum", "strategy": strat_name, "timestamp": time.time()}
                await database.save_signal(blocked)
                return blocked
        entry_context = {"liquidity": details if self.market else {},
                         "expected_gross_pnl_try": expected_gross if self.market else None,
                         "expected_net_pnl_try": expected_net if self.market else None,
                         "commission_pct": config.COMMISSION_PCT,
                         "estimated_slippage_pct": config.ESTIMATED_SLIPPAGE_PCT,
                         "profit_target_pct": config.SPOT_PROFIT_TARGET_PCT}
        if self.market:
            entry_context["technical"] = calculate_snapshot(symbol, entry_price, self.market.klines, self.market.get_orderflow(symbol), self.market.ticker_24h.get(symbol, 0), config.DEFAULT_ORDER_USDT, self._strategy_tf(strat_name))
        try_balance = await database.get_wallet_balance("TRY")
        required_cash = config.DEFAULT_ORDER_USDT * (1 + config.COMMISSION_PCT)
        if try_balance < required_cash:
            return None

        quantity = config.DEFAULT_ORDER_USDT / entry_price
        commission = config.DEFAULT_ORDER_USDT * config.COMMISSION_PCT
        
        await database.update_wallet_balance("TRY", try_balance - config.DEFAULT_ORDER_USDT - commission)
        await database.update_wallet_balance(symbol.replace("TRY", ""), quantity)

        existing = self.positions.get(symbol)
        if existing:
            total_qty = existing["quantity"] + quantity
            entry_price = ((existing["entry_price"] * existing["quantity"]) + (entry_price * quantity)) / total_qty
            pos = {**existing, "entry_price": entry_price, "spot_profit_target": entry_price * (1 + config.SPOT_PROFIT_TARGET_PCT), "quantity": total_qty, "layers": existing.get("layers", 1) + 1}
        else:
            pos = {
            "side": "LONG",  # Binance TR Spot olduğu için her zaman LONG
            "entry_price": entry_price,
            "spot_profit_target": entry_price * (1 + config.SPOT_PROFIT_TARGET_PCT),
                "quantity": quantity, "entry_time": time.time(), "strategy": strat_name, "layers": 1,
                "max_price": entry_price, "min_price": entry_price, "entry_context": entry_context
            }
        self.positions[symbol] = pos
        await database.save_position(symbol, pos)
        
        sig = {"symbol": symbol, "action": "BUY_SIGNAL", "price": entry_price, "reason": strat_name, "timestamp": time.time()}
        await database.save_signal(sig)
        return sig

