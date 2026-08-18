import asyncio
import json
import time
from collections import defaultdict

import numpy as np
import websockets

from app.binance_tr_public import WS_BASE, klines as fetch_klines, ticker_24h
from app.config import config


def _empty_history():
    return {
        "timestamps": [],
        "opens": [],
        "highs": [],
        "lows": [],
        "closes": [],
        "volumes": [],
        "last_closed_at_ms": 0,
        "updated_at": 0.0,
        "source": None,
    }


def _interval_ms(interval: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    try:
        return int(interval[:-1]) * units[interval[-1].lower()]
    except (KeyError, TypeError, ValueError, IndexError):
        return 60_000


class MarketData:
    """Public Binance TR market cache with source-specific health metadata."""

    WS_MAX_STREAMS_PER_CONNECTION = 180
    ORDERBOOK_MAX_AGE_SEC = 5.0
    REST_24H_MAX_AGE_SEC = 30.0
    WARMUP_BYPASS_SEC = 20.0
    MAX_HISTORY_CANDLES = 400

    def __init__(self, symbols):
        self.symbols = [s.lower() for s in symbols]
        self.timeframes = self._all_timeframes()
        self.klines = defaultdict(lambda: defaultdict(_empty_history))
        self.tickers = {}
        self.ticker_24h = {}
        self.orderflow = defaultdict(lambda: {
            "bid_price": None,
            "ask_price": None,
            "bid_qty": 0.0,
            "ask_qty": 0.0,
            "spread_pct": None,
            "last_trade_qty": 0.0,
            "last_trade_side": None,
            "updated_at": 0.0,
            "source": None,
        })
        self.running = False
        self.history_loaded = False
        self.created_at = time.time()

        # Source-specific health prevents a healthy REST refresh from hiding a
        # dead WS stream (and vice versa). The legacy aggregate fields remain
        # for existing health endpoints until their response schema is updated.
        self.rest_last_event_at = None
        self.rest_last_error = None
        self.rest_ticker_updated_at = 0.0
        self.ws_last_event_at = None
        self.ws_last_error = None
        self.last_event_at = None
        self.last_error = None

        self.reconnect_requested = False
        self.connection_generation = 0
        self._rest_refresh_task = None
        self._connect_owner_task = None
        self._ws_tasks = set()
        self.WS_URL = f"{WS_BASE}/stream?streams={{}}"

    def _all_timeframes(self):
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

    @staticmethod
    def _closed_history(rows, tf: str, now_ms: int):
        """Normalize REST rows, discard the open bar and deduplicate by open time."""
        normalized = {}
        duration_ms = _interval_ms(tf)
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                opened_at_ms = int(row[0])
                closed_at_ms = int(row[6]) if len(row) > 6 else opened_at_ms + duration_ms - 1
                values = tuple(float(row[index]) for index in range(1, 6))
            except (TypeError, ValueError, IndexError):
                continue
            if closed_at_ms > now_ms:
                continue
            normalized[opened_at_ms] = (closed_at_ms, *values)

        history = _empty_history()
        for opened_at_ms in sorted(normalized)[-MarketData.MAX_HISTORY_CANDLES:]:
            closed_at_ms, opened, high, low, close, volume = normalized[opened_at_ms]
            history["timestamps"].append(opened_at_ms)
            history["opens"].append(opened)
            history["highs"].append(high)
            history["lows"].append(low)
            history["closes"].append(close)
            history["volumes"].append(volume)
            history["last_closed_at_ms"] = closed_at_ms
        if history["timestamps"]:
            history["updated_at"] = time.time()
            history["source"] = "binance_tr_public_rest"
        return history

    async def fetch_historical_data(self, timeframes=None):
        """Warm the cache using closed REST candles only."""
        requested_timeframes = list(timeframes or self._all_timeframes())
        if not self.history_loaded:
            self.timeframes = sorted(set(requested_timeframes))
        else:
            self.timeframes = sorted(set(self.timeframes).union(requested_timeframes))
        print(f"[MarketData] Timeframes: {self.timeframes} - Geçmiş mum verileri çekiliyor...", flush=True)
        semaphore = asyncio.Semaphore(8)

        async def fetch_one(tf, raw_symbol):
            async with semaphore:
                symbol = raw_symbol.upper()
                print(f"[MarketData] geçmiş çekiliyor | symbol={symbol} timeframe={tf}", flush=True)
                try:
                    rows = await fetch_klines(raw_symbol, tf, limit=300)
                    history = self._closed_history(rows, tf, int(time.time() * 1000))
                    # A complete replacement is visible atomically to readers;
                    # they never observe half-cleared parallel arrays.
                    self.klines[tf][symbol] = history
                    if history["closes"] and symbol not in self.tickers:
                        last_price = history["closes"][-1]
                        tickers = dict(self.tickers)
                        tickers[symbol] = {
                            "symbol": symbol,
                            "last_price": last_price,
                            "timestamp": int(time.time() * 1000),
                            "source": "binance_tr_public_rest_kline",
                        }
                        self.tickers = tickers
                    print(
                        f"[MarketData] geçmiş hazır | symbol={symbol} timeframe={tf} "
                        f"closed_candles={len(history['closes'])}", flush=True,
                    )
                    return bool(history["closes"]), None
                except Exception as exc:
                    print(f"[MarketData] geçmiş veri hatası | symbol={symbol} timeframe={tf} error={exc}", flush=True)
                    return False, f"{symbol}/{tf}: {exc}"

        results = await asyncio.gather(
            *(fetch_one(tf, symbol) for tf in self.timeframes for symbol in list(self.symbols))
        )
        successes = sum(1 for ok, _ in results if ok)
        errors = [error for _, error in results if error]
        now = time.time()
        if successes:
            self.rest_last_event_at = now
            self.last_event_at = max(filter(None, [self.rest_last_event_at, self.ws_last_event_at]), default=now)
        self.rest_last_error = "; ".join(errors[:5]) if errors else None
        self.last_error = self.ws_last_error or self.rest_last_error
        self.history_loaded = self.history_loaded or successes > 0
        print(
            f"[MarketData] Geçmiş veri yüklendi | timeframes={len(self.timeframes)} "
            f"symbols={len(self.symbols)} successful_series={successes}", flush=True,
        )
        await self.refresh_24h_tickers()

    async def refresh_24h_tickers(self):
        try:
            rows = await ticker_24h([s.upper() for s in self.symbols])
            if not isinstance(rows, list):
                raise RuntimeError("24h ticker yanıtı liste değil")
            now = time.time()
            now_ms = int(now * 1000)
            quote_volumes = {}
            updates = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol", "")).upper()
                if not symbol:
                    continue
                try:
                    quote_volumes[symbol] = float(row.get("quoteVolume", 0) or 0)
                    last_price = float(row.get("lastPrice", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if last_price > 0:
                    updates[symbol] = {
                        **(self.tickers.get(symbol) or {}),
                        "symbol": symbol,
                        "last_price": last_price,
                        "timestamp": now_ms,
                        "source": "binance_tr_public_rest",
                    }
            if not quote_volumes:
                raise RuntimeError("24h ticker yanıtında geçerli sembol yok")
            self.ticker_24h = quote_volumes
            self.tickers = {**self.tickers, **updates}
            self.rest_ticker_updated_at = now
            self.rest_last_event_at = now
            self.rest_last_error = None
            self.last_event_at = max(filter(None, [self.rest_last_event_at, self.ws_last_event_at]), default=now)
            self.last_error = self.ws_last_error
        except Exception as exc:
            self.rest_last_error = str(exc)
            self.last_error = self.ws_last_error or self.rest_last_error
            print(f"[MarketData] 24h ticker yenileme hatası: {exc}", flush=True)

    async def _rest_refresh_loop(self):
        try:
            while self.running:
                await self.refresh_24h_tickers()
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise

    def _build_ws_groups(self, generation: int):
        """Create a fresh immutable connection plan for this generation."""
        symbols = list(dict.fromkeys(str(symbol).replace("_", "").lower() for symbol in self.symbols))
        timeframes = list(self.timeframes)
        streams_per_symbol = len(timeframes) + 2  # klines + depth + aggregate trades
        group_size = max(1, self.WS_MAX_STREAMS_PER_CONNECTION // streams_per_symbol)
        plans = []
        for index in range(0, len(symbols), group_size):
            group = symbols[index:index + group_size]
            streams = "/".join(
                [f"{symbol}@kline_{tf}" for tf in timeframes for symbol in group]
                + [f"{symbol}@depth5@100ms" for symbol in group]
                + [f"{symbol}@aggTrade" for symbol in group]
                + [f"{symbol}@bookTicker" for symbol in group]
            )
            plans.append({
                "group_id": index // group_size + 1,
                "generation": generation,
                "symbols": tuple(group),
                "timeframes": tuple(timeframes),
                "url": self.WS_URL.format(streams),
            })
        return plans

    async def _run_ws_group(self, plan):
        group_id = plan["group_id"]
        generation = plan["generation"]
        while self.running and generation == self.connection_generation:
            try:
                print(
                    f"[MarketData] WebSocket generation={generation} grup={group_id} "
                    f"symbols={len(plan['symbols'])} timeframes={len(plan['timeframes'])}", flush=True,
                )
                async with websockets.connect(plan["url"], ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                    async for message in ws:
                        if (not self.running or generation != self.connection_generation
                                or self.reconnect_requested):
                            break
                        self._process_ws_message(json.loads(message))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ws_last_error = str(exc)
                self.last_error = self.ws_last_error or self.rest_last_error
                print(f"[MarketData] WS Hata generation={generation} grup={group_id}: {exc}", flush=True)
                await asyncio.sleep(2)

    async def _watch_reconnect(self, generation: int):
        while self.running and generation == self.connection_generation:
            if self.reconnect_requested:
                return
            await asyncio.sleep(0.1)

    async def connect(self, skip_history: bool = False):
        if not skip_history:
            await self.fetch_historical_data()
        self.running = True
        self._connect_owner_task = asyncio.current_task()
        if self._rest_refresh_task is None or self._rest_refresh_task.done():
            self._rest_refresh_task = asyncio.create_task(self._rest_refresh_loop(), name="market-rest-refresh")
        try:
            while self.running:
                self.connection_generation += 1
                generation = self.connection_generation
                self.reconnect_requested = False
                plans = self._build_ws_groups(generation)
                print(
                    f"[MarketData] WebSocket nesli başlatılıyor | generation={generation} "
                    f"groups={len(plans)} max_streams={self.WS_MAX_STREAMS_PER_CONNECTION}", flush=True,
                )
                if not plans:
                    await asyncio.sleep(0.25)
                    continue
                group_tasks = {
                    asyncio.create_task(
                        self._run_ws_group(plan),
                        name=f"market-ws-g{generation}-{plan['group_id']}",
                    )
                    for plan in plans
                }
                watcher = asyncio.create_task(
                    self._watch_reconnect(generation), name=f"market-ws-watch-g{generation}"
                )
                generation_tasks = group_tasks | {watcher}
                self._ws_tasks.update(generation_tasks)
                await asyncio.wait(generation_tasks, return_when=asyncio.FIRST_COMPLETED)
                # All sockets from the previous immutable plan are cancelled
                # before a plan with the new symbol/timeframe set is created.
                for task in generation_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*generation_tasks, return_exceptions=True)
                self._ws_tasks.difference_update(generation_tasks)
        except asyncio.CancelledError:
            raise
        finally:
            current_tasks = list(self._ws_tasks)
            for task in current_tasks:
                task.cancel()
            if current_tasks:
                await asyncio.gather(*current_tasks, return_exceptions=True)
            self._ws_tasks.clear()
            self._connect_owner_task = None

    def _mark_ws_event(self):
        now = time.time()
        self.ws_last_event_at = now
        self.ws_last_error = None
        self.last_event_at = max(filter(None, [self.rest_last_event_at, self.ws_last_event_at]), default=now)
        self.last_error = self.rest_last_error

    def _process_ws_message(self, payload):
        """Preserve the combined-stream name needed by depth snapshots."""
        if not isinstance(payload, dict):
            return
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            return
        stream = str(payload.get("stream") or "")
        if stream and not data.get("s") and not data.get("symbol"):
            data = {**data, "_stream": stream}
        self._process_kline(data)

    def _process_kline(self, kline_data):
        event = kline_data.get("e")
        if event in {"depthUpdate", "depth"} or "bids" in kline_data or isinstance(kline_data.get("b"), list):
            self._process_orderbook(kline_data)
            self._mark_ws_event()
            return
        if event in {"aggTrade", "trade"} or ("p" in kline_data and "q" in kline_data):
            symbol = str(kline_data.get("s", "")).upper()
            if symbol:
                flow = self.orderflow[symbol]
                flow["last_trade_qty"] = float(kline_data.get("q", kline_data.get("Q", 0)) or 0)
                flow["last_trade_side"] = "sell" if kline_data.get("m", False) else "buy"
                flow["last_trade_updated_at"] = time.time()
                self._mark_ws_event()
            return
        candle = kline_data.get("k", {})
        symbol = str(candle.get("s") or "").upper()
        if not symbol:
            return
        tf = str(candle.get("i") or "")
        try:
            opened_at_ms = int(candle.get("t", 0) or 0)
            closed_at_ms = int(candle.get("T", 0) or (opened_at_ms + _interval_ms(tf) - 1))
            opened = float(candle.get("o", 0))
            high = float(candle.get("h", 0))
            low = float(candle.get("l", 0))
            close = float(candle.get("c", 0))
            volume = float(candle.get("v", 0))
        except (TypeError, ValueError):
            return

        event_ms = int(kline_data.get("E", 0) or time.time() * 1000)
        tickers = dict(self.tickers)
        tickers[symbol] = {
            "symbol": symbol,
            "last_price": close,
            "timestamp": event_ms,
            "source": "binance_tr_public_ws",
        }
        self.tickers = tickers
        self._mark_ws_event()

        if not candle.get("x", False):
            return
        history = self.klines[tf][symbol]
        timestamps = history.setdefault("timestamps", [])
        values = (opened, high, low, close, volume)
        keys = ("opens", "highs", "lows", "closes", "volumes")
        if opened_at_ms in timestamps:
            index = timestamps.index(opened_at_ms)
            for key, value in zip(keys, values):
                history[key][index] = value
        else:
            timestamps.append(opened_at_ms)
            for key, value in zip(keys, values):
                history.setdefault(key, []).append(value)
        history["last_closed_at_ms"] = max(int(history.get("last_closed_at_ms", 0) or 0), closed_at_ms)
        history["updated_at"] = time.time()
        history["source"] = "binance_tr_public_ws"
        if len(timestamps) > self.MAX_HISTORY_CANDLES:
            excess = len(timestamps) - self.MAX_HISTORY_CANDLES
            del timestamps[:excess]
            for key in keys:
                del history[key][:excess]

    def get_ticker(self, symbol):
        return self.tickers.get(symbol.upper())

    def ticker_freshness(self, symbol, max_age_sec=None):
        ticker = self.get_ticker(symbol) or {}
        timestamp_ms = float(ticker.get("timestamp", 0) or 0)
        age = time.time() - timestamp_ms / 1000 if timestamp_ms else float("inf")
        maximum = float(max_age_sec if max_age_sec is not None else config.MAX_TICKER_AGE_SEC)
        return {"fresh": age <= maximum, "age_sec": age, "max_age_sec": maximum,
                "source": ticker.get("source")}

    def kline_freshness(self, symbol, tf=None):
        tf = tf or config.UT_TIMEFRAME
        history = self.klines.get(tf, {}).get(symbol.upper(), {})
        closed_at_ms = float(history.get("last_closed_at_ms", 0) or 0)
        age = time.time() - closed_at_ms / 1000 if closed_at_ms else float("inf")
        maximum = _interval_ms(tf) / 1000 * 2 + 30
        return {"fresh": bool(history.get("closes")) and age <= maximum,
                "age_sec": age, "max_age_sec": maximum, "source": history.get("source")}

    def orderbook_freshness(self, symbol):
        flow = self.orderflow.get(symbol.upper(), {})
        updated_at = float(flow.get("updated_at", 0) or 0)
        age = time.time() - updated_at if updated_at else float("inf")
        return {"fresh": bool(flow.get("bid_qty")) and bool(flow.get("ask_qty"))
                and flow.get("spread_pct") is not None and age <= self.ORDERBOOK_MAX_AGE_SEC,
                "age_sec": age, "max_age_sec": self.ORDERBOOK_MAX_AGE_SEC,
                "source": flow.get("source")}

    def data_freshness(self, symbol, tf=None):
        return {
            "ticker": self.ticker_freshness(symbol),
            "kline": self.kline_freshness(symbol, tf),
            "orderbook": self.orderbook_freshness(symbol),
            "rest": {"last_event_at": self.rest_last_event_at, "last_error": self.rest_last_error},
            "ws": {"last_event_at": self.ws_last_event_at, "last_error": self.ws_last_error,
                   "generation": self.connection_generation},
        }

    def get_avg_volume(self, symbol, tf=None):
        tf = tf or config.UT_TIMEFRAME
        history = self.klines.get(tf, {}).get(symbol.upper(), {})
        volumes = history.get("volumes", [])
        return float(np.mean(volumes)) if volumes else 0.0

    def get_ut_kline(self, symbol, tf=None):
        tf = tf or config.UT_TIMEFRAME
        return self.klines.get(tf, {}).get(symbol.upper(), _empty_history())

    def _process_orderbook(self, data):
        stream_symbol = str(data.get("_stream") or "").split("@", 1)[0]
        symbol = str(data.get("s") or data.get("symbol") or stream_symbol or "").upper()
        bids = data.get("bids", data.get("b", []))
        asks = data.get("asks", data.get("a", []))
        if not symbol or not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
            return
        try:
            top_bids = bids[:5]
            top_asks = asks[:5]
            bid_qty = sum(float(row[1]) for row in top_bids)
            ask_qty = sum(float(row[1]) for row in top_asks)
            bid = float(top_bids[0][0])
            ask = float(top_asks[0][0])
        except (TypeError, ValueError, IndexError):
            return
        received_at = float(data.get("received_at", 0) or time.time())
        flow = self.orderflow[symbol]
        flow.update({
            "bid_price": bid,
            "ask_price": ask,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "spread_pct": ((ask - bid) / bid * 100) if bid else None,
            "updated_at": received_at,
            "source": data.get("source") or "binance_tr_public_ws",
        })

    def get_orderflow(self, symbol):
        return dict(self.orderflow.get(symbol.upper(), {}))

    def liquidity_status(self, symbol, order_value_try, allow_warmup=False):
        """Fail closed unless all price, candle, volume and depth inputs are fresh.

        A caller may explicitly opt into a startup-only observation bypass. It
        is bounded to ``WARMUP_BYPASS_SEC`` and is never used by trading callers
        by default.
        """
        symbol = symbol.upper()
        if not config.LIQUIDITY_FILTER_ENABLED:
            return True, {"disabled": True}
        ticker = self.get_ticker(symbol) or {}
        tf = config.MOMENTUM_TIMEFRAME
        history = self.klines.get(tf, {}).get(symbol, {})
        volumes = history.get("volumes", [])
        current = volumes[-1] if volumes else 0.0
        average = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else 0.0
        ratio = current / average if average > 0 else 0.0
        flow = self.get_orderflow(symbol)
        spread = flow.get("spread_pct")
        price = float(ticker.get("last_price", 0) or 0)
        depth_try = (float(flow.get("bid_qty", 0) or 0) + float(flow.get("ask_qty", 0) or 0)) * price
        quote_volume = float(self.ticker_24h.get(symbol, 0) or 0)

        freshness = self.data_freshness(symbol, tf)
        rest_24h_fresh = bool(self.rest_ticker_updated_at) and (
            time.time() - self.rest_ticker_updated_at <= self.REST_24H_MAX_AGE_SEC
        )
        missing_or_stale = []
        if not freshness["ticker"]["fresh"]:
            missing_or_stale.append("ticker")
        if not freshness["kline"]["fresh"] or len(volumes) < 21:
            missing_or_stale.append("kline")
        if not freshness["orderbook"]["fresh"]:
            missing_or_stale.append("orderbook")
        if not rest_24h_fresh or quote_volume <= 0:
            missing_or_stale.append("ticker_24h")
        warmup_bypass = bool(
            allow_warmup and missing_or_stale and time.time() - self.created_at <= self.WARMUP_BYPASS_SEC
        )

        high_liquidity = quote_volume >= config.HIGH_LIQUIDITY_BYPASS_VOLUME_TRY
        checks = {
            "fresh_inputs": not missing_or_stale or warmup_bypass,
            "quote_volume": (warmup_bypass and "ticker_24h" in missing_or_stale)
                            or quote_volume >= config.MIN_24H_QUOTE_VOLUME_TRY,
            "volume_ratio": (warmup_bypass and "kline" in missing_or_stale)
                            or high_liquidity or ratio >= config.MIN_VOLUME_RATIO,
            "spread": (warmup_bypass and "orderbook" in missing_or_stale)
                      or (spread is not None and spread <= config.MAX_SPREAD_PCT),
            "orderbook_depth": (warmup_bypass and ("ticker" in missing_or_stale
                                                     or "orderbook" in missing_or_stale))
                               or depth_try >= order_value_try * config.MIN_ORDERBOOK_DEPTH_MULTIPLIER,
        }
        return all(checks.values()), {
            "quote_volume": quote_volume,
            "high_liquidity": high_liquidity,
            "volume_ratio": ratio,
            "spread": spread,
            "depth_try": depth_try,
            "checks": checks,
            "missing_or_stale": missing_or_stale,
            "freshness": freshness,
            "warmup_bypass": warmup_bypass,
        }

    def stop(self):
        self.running = False
        self.connection_generation += 1
        self.reconnect_requested = True
        tasks = list(self._ws_tasks)
        if self._rest_refresh_task and not self._rest_refresh_task.done():
            tasks.append(self._rest_refresh_task)
        owner = self._connect_owner_task
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if owner and owner is not current and not owner.done():
            tasks.append(owner)
        for task in tasks:
            if task and not task.done():
                task.cancel()
        self._rest_refresh_task = None
