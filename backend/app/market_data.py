import asyncio
import json
import time
import numpy as np
import websockets
from collections import defaultdict
from app.config import config
from app.binance_tr_public import WS_BASE, klines as fetch_klines, ticker_24h

class MarketData:
    def __init__(self, symbols):
        self.symbols = [s.lower() for s in symbols]
        # Tüm strateji timeframe'lerini topla (aktif olmasa da veri hazır olsun)
        self.timeframes = sorted(set([
            "1m", "3m", "5m", "15m", "30m", "1h", "4h",
            config.UT_TIMEFRAME,
            config.BB_SQUEEZE_TIMEFRAME,
            config.EMA_PULLBACK_TIMEFRAME,
            config.VWAP_MACD_TIMEFRAME,
            config.CMO_CRSI_TIMEFRAME,
            config.EMA_VWAP_TIMEFRAME,
            config.BREAKOUT_TIMEFRAME,
            config.ORDERFLOW_TIMEFRAME,
            config.MOMENTUM_TIMEFRAME,
            config.ADR_TIMEFRAME,
            config.KELTNER_TIMEFRAME, config.CHOP_TIMEFRAME, config.DONCHIAN_TIMEFRAME,
        ]))
        # klines[tf][symbol] = {opens, highs, lows, closes, volumes}
        self.klines = defaultdict(lambda: defaultdict(lambda: {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": []}))
        self.tickers = {}
        self.ticker_24h = {}
        self.orderflow = defaultdict(lambda: {"bid_qty": 0.0, "ask_qty": 0.0, "spread_pct": None, "last_trade_qty": 0.0, "last_trade_side": None, "updated_at": 0.0})
        self.running = False
        self.history_loaded = False
        self.last_event_at = None
        self.last_error = None
        self.reconnect_requested = False
        self._rest_refresh_task = None
        # Kimlik doğrulama gerektirmeyen public market API.
        self.WS_URL = f"{WS_BASE}/stream?streams={{}}"

    def _all_timeframes(self):
        """Config'deki tüm strateji timeframe'lerini topla (dinamik)."""
        return sorted(set([
            "1m", "3m", "5m", "15m", "30m", "1h", "4h",
            config.UT_TIMEFRAME,
            config.BB_SQUEEZE_TIMEFRAME,
            config.EMA_PULLBACK_TIMEFRAME,
            config.VWAP_MACD_TIMEFRAME,
            config.CMO_CRSI_TIMEFRAME,
            config.EMA_VWAP_TIMEFRAME,
            config.BREAKOUT_TIMEFRAME,
            config.ORDERFLOW_TIMEFRAME,
            config.MOMENTUM_TIMEFRAME,
            config.ADR_TIMEFRAME,
            config.MEAN_REVERSION_TIMEFRAME,
            config.KELTNER_TIMEFRAME,
            config.CHOP_TIMEFRAME,
            config.DONCHIAN_TIMEFRAME,
        ]))

    async def fetch_historical_data(self):
        """Bot başlarken her timeframe için son 60 mumu REST API'den çeker (Warm-Up bypass)"""
        self.timeframes = self._all_timeframes()
        print(f"[MarketData] Timeframes: {self.timeframes} - Geçmiş mum verileri çekiliyor...")
        for tf in self.timeframes:
            for s in self.symbols:
                try:
                    klines = await fetch_klines(s, tf, limit=300)
                    hist = self.klines[tf][s.upper()]
                    for key in ("opens", "highs", "lows", "closes", "volumes"):
                        hist[key] = []
                    for k in klines:
                        # Binance kline formatı: [OpenTime, Open, High, Low, Close, Volume...]
                        hist["opens"].append(float(k[1]))
                        hist["highs"].append(float(k[2]))
                        hist["lows"].append(float(k[3]))
                        hist["closes"].append(float(k[4]))
                        hist["volumes"].append(float(k[5]))

                    # İlk canlı fiyatı set et (en küçük timeframe'den)
                    last_close = float(klines[-1][4])
                    if s.upper() not in self.tickers:
                        self.tickers[s.upper()] = {"symbol": s.upper(), "last_price": last_close, "timestamp": int(time.time() * 1000)}
                except Exception as e:
                    print(f"[MarketData] {s.upper()} {tf} geçmiş veri hatası: {e}")
        print(f"[MarketData] Geçmiş veri yüklendi ({len(self.timeframes)} timeframe).")
        self.history_loaded = bool(self.tickers)
        await self.refresh_24h_tickers()

    async def refresh_24h_tickers(self):
        try:
            rows = await ticker_24h()
            self.ticker_24h = {str(r.get("symbol", "")).upper(): float(r.get("quoteVolume", 0) or 0) for r in rows if r.get("symbol")}
            now_ms = int(time.time() * 1000)
            for row in rows:
                symbol = str(row.get("symbol", "")).upper()
                last_price = float(row.get("lastPrice", 0) or 0)
                if symbol and last_price > 0:
                    previous = self.tickers.get(symbol) or {}
                    self.tickers[symbol] = {**previous, "symbol": symbol, "last_price": last_price,
                                            "timestamp": now_ms, "source": "binance_tr_public_rest"}
            self.last_event_at = time.time()
            self.last_error = None
        except Exception as exc:
            print(f"[MarketData] 24h ticker yenileme hatası: {exc}")

    async def _rest_refresh_loop(self):
        while self.running:
            try:
                await self.refresh_24h_tickers()
            except Exception as exc:
                print(f"[MarketData] REST ticker yenileme döngüsü hatası: {exc}")
            await asyncio.sleep(10)

    async def connect(self, skip_history: bool = False):
        # 1) Önce geçmiş veriyi yükle
        if not skip_history:
            await self.fetch_historical_data()

        # 2) Canlı WebSocket ile tüm timeframe'leri dinle
        self.running = True
        if self._rest_refresh_task is None or self._rest_refresh_task.done():
            self._rest_refresh_task = asyncio.create_task(self._rest_refresh_loop())
        last_rest_refresh = 0.0
        while self.running:
            try:
                if time.time() - last_rest_refresh >= 10:
                    await self.refresh_24h_tickers()
                    last_rest_refresh = time.time()
                streams = "/".join([f"{s}@kline_{tf}" for tf in self.timeframes for s in self.symbols] + [f"{s}@depth5@100ms" for s in self.symbols] + [f"{s}@aggTrade" for s in self.symbols])
                url = self.WS_URL.format(streams)
                self.reconnect_requested = False
                print(f"[MarketData] Canlı WebSocket ({len(self.symbols)} sembol, {self.timeframes}) bağlantısı kuruldu.")
                async with websockets.connect(url, ping_interval=20) as ws:
                    async for msg in ws:
                        if not self.running: break
                        if self.reconnect_requested: break
                        data = json.loads(msg)
                        self._process_kline(data.get("data", data))
            except Exception as e:
                self.last_error = str(e)
                print(f"[MarketData] WS Hata: {e}")
                # Keep positions and manual/LLM closes supplied with a fresh
                # public price while the websocket reconnects.
                try:
                    await self.refresh_24h_tickers()
                    last_rest_refresh = time.time()
                except Exception as refresh_error:
                    print(f"[MarketData] REST ticker fallback hatası: {refresh_error}")
                await asyncio.sleep(2)

    def _process_kline(self, kline_data):
        event = kline_data.get("e")
        if event in {"depthUpdate", "depth"} or "bids" in kline_data or "b" in kline_data:
            self._process_orderbook(kline_data)
            return
        if event in {"aggTrade", "trade"} or "p" in kline_data:
            symbol = kline_data.get("s", "").upper()
            if symbol:
                flow = self.orderflow[symbol]
                flow["last_trade_qty"] = float(kline_data.get("q", kline_data.get("Q", 0)) or 0)
                flow["last_trade_side"] = "sell" if kline_data.get("m", False) else "buy"
                flow["updated_at"] = time.time()
            return
        k = kline_data.get("k", {})
        symbol = k.get("s")
        if not symbol: return

        tf = k.get("i", "")
        o = float(k.get("o", 0))
        h = float(k.get("h", 0))
        l = float(k.get("l", 0))
        c = float(k.get("c", 0))
        v = float(k.get("v", 0))
        is_closed = k.get("x", False)

        # Canlı fiyatı her veri akışında günceller (Frontend anlık görsün diye)
        self.tickers[symbol] = {"symbol": symbol, "last_price": c, "timestamp": kline_data.get("E")}
        self.last_event_at = time.time()
        self.last_error = None

        # Sadece mum KAPANDIĞINDA geçmiş veriye ekleme yapar
        if is_closed:
            hist = self.klines[tf][symbol]
            hist["opens"].append(o)
            hist["highs"].append(h)
            hist["lows"].append(l)
            hist["closes"].append(c)
            hist["volumes"].append(v)

            # CRSI rank=100 dahil tüm strateji warm-up geçmişini tut
            if len(hist["closes"]) > 400:
                hist["opens"].pop(0)
                hist["highs"].pop(0)
                hist["lows"].pop(0)
                hist["closes"].pop(0)
                hist["volumes"].pop(0)

    def get_ticker(self, symbol):
        return self.tickers.get(symbol.upper())

    def get_avg_volume(self, symbol, tf=None):
        """Son kapanan mumların ortalama hacmi."""
        tf = tf or config.UT_TIMEFRAME
        hist = self.klines.get(tf, {}).get(symbol.upper(), {})
        vols = hist.get("volumes", [])
        return float(np.mean(vols)) if vols else 0.0

    def get_ut_kline(self, symbol, tf=None):
        """Belirtilen timeframe'in kline verisi (varsayılan UT_TIMEFRAME)."""
        tf = tf or config.UT_TIMEFRAME
        return self.klines.get(tf, {}).get(symbol.upper(), {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": []})

    def _process_orderbook(self, data):
        symbol = (data.get("s") or data.get("symbol") or "").upper()
        bids = data.get("bids", data.get("b", []))
        asks = data.get("asks", data.get("a", []))
        if not symbol or not bids or not asks:
            return
        bid_qty = sum(float(row[1]) for row in bids[:5])
        ask_qty = sum(float(row[1]) for row in asks[:5])
        bid = float(bids[0][0]); ask = float(asks[0][0])
        flow = self.orderflow[symbol]
        flow.update({"bid_qty": bid_qty, "ask_qty": ask_qty,
                     "spread_pct": ((ask - bid) / bid * 100) if bid else None,
                     "updated_at": time.time()})

    def get_orderflow(self, symbol):
        return dict(self.orderflow.get(symbol.upper(), {}))

    def liquidity_status(self, symbol, order_value_try):
        sym = symbol.upper()
        if not config.LIQUIDITY_FILTER_ENABLED:
            return True, {"disabled": True}
        ticker = self.get_ticker(sym) or {}
        hist = self.klines.get(config.MOMENTUM_TIMEFRAME, {}).get(sym, {})
        volumes = hist.get("volumes", [])
        current = volumes[-1] if volumes else 0.0
        average = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else 0.0
        ratio = current / average if average > 0 else 0.0
        flow = self.get_orderflow(sym)
        spread = flow.get("spread_pct")
        price = float(ticker.get("last_price", 0) or 0)
        depth_try = (float(flow.get("bid_qty", 0) or 0) + float(flow.get("ask_qty", 0) or 0)) * price
        quote_volume = float(self.ticker_24h.get(sym, 0) or 0)
        # Veri henüz ısınmadıysa false-negative üretme; geldiğinde filtre uygula.
        high_liquidity = quote_volume >= config.HIGH_LIQUIDITY_BYPASS_VOLUME_TRY
        checks = {
            "quote_volume": quote_volume <= 0 or quote_volume >= config.MIN_24H_QUOTE_VOLUME_TRY,
            # Büyük hacimli BTC/ETH gibi piyasalarda tek düşük mum işlem kalitesini
            # temsil etmez; hacim oranı filtresi yalnızca düşük/orta likiditede serttir.
            "volume_ratio": high_liquidity or average <= 0 or ratio >= config.MIN_VOLUME_RATIO,
            "spread": spread is None or spread <= config.MAX_SPREAD_PCT,
            "orderbook_depth": depth_try <= 0 or depth_try >= order_value_try * config.MIN_ORDERBOOK_DEPTH_MULTIPLIER,
        }
        return all(checks.values()), {"quote_volume": quote_volume, "high_liquidity": high_liquidity, "volume_ratio": ratio, "spread": spread, "depth_try": depth_try, "checks": checks}

    def stop(self):
        self.running = False
        if self._rest_refresh_task and not self._rest_refresh_task.done():
            self._rest_refresh_task.cancel()
        self._rest_refresh_task = None
