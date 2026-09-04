import asyncio
import json
import time
from collections import defaultdict, deque

import numpy as np
import websockets

from app.binance_tr_public import WS_BASE, WS_BASES, klines as fetch_klines, ticker_24h, book_tickers
from app.config import config
from app.market_intelligence import whale_activity_from_tape


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
        # Aggressive-flow accumulation from the existing aggTrade stream. The
        # Binance TR WS already delivers per-symbol aggTrade events; previously
        # only the latest trade was kept. These rolling 60s counters turn the
        # same stream into a realtime CVD proxy (maker/taker side known from
        # the m flag), a trade-frequency gauge and a whale detector. All values
        # are observable market data, not position/orderbook truths.
        self.trade_flow = defaultdict(lambda: {
            "buy_qty": 0.0,
            "sell_qty": 0.0,
            "buy_count": 0,
            "sell_count": 0,
            "buy_notional": 0.0,
            "sell_notional": 0.0,
            "whale_buys": 0,
            "whale_sells": 0,
            "window_start": 0.0,
            "updated_at": 0.0,
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
        # Dokümantasyona göre sunucu bağlantıyı 24 saatte bir kapatır ve
        # serverShutdown olayı gönderir. Kod bunu fark edip bilinçli şekilde
        # yeni nesil başlatır; böylece saatlerce sessiz kalan tek soket kalmaz.
        self.ws_connected_at = 0.0
        self.ws_max_lifetime_sec = 24 * 3600
        self.ws_host_index = 0
        self._rest_refresh_task = None
        self._connect_owner_task = None
        self._ws_tasks = set()
        self.WS_URL = f"{WS_BASE}/stream?streams={{}}"

    def _all_timeframes(self):
        return sorted(set(["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]))

    @staticmethod
    def _closed_history(rows, tf: str, now_ms: int):
        """Normalize REST rows, discard the open bar and deduplicate by open time.

        ``now_ms`` is shifted back by a small margin so a host clock that
        runs ahead of exchange time cannot admit a candle whose close is
        still in the future (look-ahead window proportional to the skew).
        """
        now_ms = int(now_ms) - 1500
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

    async def repair_history_gaps(self, symbols=None, timeframes=None):
        """REST-backfill cache series whose tail predates the last expected close.

        After a WebSocket outage across one or more candle closes the stream
        resumes appending new bars onto a gapped series; freshness checks only
        see the tail timestamp. This splices the missing closed candles in so
        indicators never run across discontinuous bars.
        """
        requested_symbols = [str(symbol).upper() for symbol in (symbols or self.symbols)]
        requested_timeframes = list(dict.fromkeys(str(tf) for tf in (timeframes or self.timeframes)))
        now_ms = int(time.time() * 1000)
        stale = []
        for timeframe in requested_timeframes:
            duration_ms = _interval_ms(timeframe)
            for symbol in requested_symbols:
                history = (self.klines.get(timeframe, {}).get(symbol, {}) or {})
                timestamps = history.get("timestamps") or []
                if not timestamps:
                    continue
                last_closed = int(history.get("last_closed_at_ms") or 0)
                if last_closed < now_ms - 2 * duration_ms:
                    stale.append((timeframe, symbol))
        if not stale:
            return {"checked": len(requested_timeframes) * len(requested_symbols), "repaired": 0, "errors": []}

        semaphore = asyncio.Semaphore(8)
        repaired = 0
        errors = []

        async def backfill(timeframe: str, symbol: str):
            nonlocal repaired
            async with semaphore:
                try:
                    history = (self.klines.get(timeframe, {}).get(symbol, {}) or {})
                    timestamps = history.get("timestamps") or []
                    if not timestamps:
                        return
                    gap_start_ms = int(timestamps[-1]) + 1
                    rows = await fetch_klines(symbol.lower(), timeframe, limit=400, start_time_ms=gap_start_ms)
                    fresh_rows = self._closed_history(rows, timeframe, now_ms)
                    if not fresh_rows["timestamps"]:
                        return
                    merged = {ts: (
                        history["opens"][index], history["highs"][index], history["lows"][index],
                        history["closes"][index], history["volumes"][index])
                        for index, ts in enumerate(timestamps)}
                    for index, ts in enumerate(fresh_rows["timestamps"]):
                        merged[ts] = (
                            fresh_rows["opens"][index], fresh_rows["highs"][index],
                            fresh_rows["lows"][index], fresh_rows["closes"][index],
                            fresh_rows["volumes"][index])
                    ordered = sorted(merged)[-self.MAX_HISTORY_CANDLES:]
                    result = _empty_history()
                    for ts in ordered:
                        opened, high, low, close, volume = merged[ts]
                        result["timestamps"].append(ts)
                        result["opens"].append(opened)
                        result["highs"].append(high)
                        result["lows"].append(low)
                        result["closes"].append(close)
                        result["volumes"].append(volume)
                    result["last_closed_at_ms"] = max(
                        int(history.get("last_closed_at_ms") or 0), fresh_rows["last_closed_at_ms"])
                    result["updated_at"] = time.time()
                    result["source"] = "binance_tr_public_rest_gap_fill"
                    self.klines[timeframe][symbol] = result
                    repaired += 1
                except Exception as exc:
                    errors.append(f"{symbol}/{timeframe}: {type(exc).__name__}: {exc}")

        await asyncio.gather(*(backfill(timeframe, symbol) for timeframe, symbol in stale))
        if repaired or errors:
            print(f"[MarketData] Gap repair: {repaired} seri onarıldı, {len(errors)} hata", flush=True)
        return {"checked": len(requested_timeframes) * len(requested_symbols),
                "repaired": repaired, "errors": errors[:20]}

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

    async def ensure_history(self, timeframes, *, min_candles=55, candle_limit=120):
        """Hydrate only cache series that cannot yet support a strategy decision.

        This is intentionally narrower than ``fetch_historical_data``: it
        avoids re-fetching already warm series and keeps full-universe feature
        monitors bounded to their required timeframes and history depth.
        """
        requested = list(dict.fromkeys(str(tf) for tf in (timeframes or []) if str(tf)))
        if not requested:
            return {"requested": 0, "hydrated": 0, "already_ready": 0, "errors": []}
        required = max(1, int(min_candles))
        limit = max(required + 1, min(self.MAX_HISTORY_CANDLES, int(candle_limit)))
        symbols = list(dict.fromkeys(str(symbol).upper() for symbol in self.symbols))
        missing = [
            (timeframe, symbol)
            for timeframe in requested
            for symbol in symbols
            if len((self.klines.get(timeframe, {}).get(symbol, {}) or {}).get("closes", [])) < required
        ]
        self.timeframes = sorted(set(self.timeframes).union(requested))
        if not missing:
            return {"requested": len(requested) * len(symbols), "hydrated": 0,
                    "already_ready": len(requested) * len(symbols), "errors": []}

        semaphore = asyncio.Semaphore(8)

        async def hydrate(timeframe, symbol):
            async with semaphore:
                try:
                    rows = await fetch_klines(symbol.lower(), timeframe, limit=limit)
                    history = self._closed_history(rows, timeframe, int(time.time() * 1000))
                    if len(history["closes"]) < required:
                        return False, f"{symbol}/{timeframe}: insufficient_closed_candles={len(history['closes'])}"
                    self.klines[timeframe][symbol] = history
                    if symbol not in self.tickers:
                        tickers = dict(self.tickers)
                        tickers[symbol] = {
                            "symbol": symbol,
                            "last_price": history["closes"][-1],
                            "timestamp": int(time.time() * 1000),
                            "source": "binance_tr_public_rest_kline",
                        }
                        self.tickers = tickers
                    return True, None
                except Exception as exc:
                    return False, f"{symbol}/{timeframe}: {exc}"

        results = await asyncio.gather(*(hydrate(timeframe, symbol) for timeframe, symbol in missing))
        hydrated = sum(1 for ok, _ in results if ok)
        errors = [error for _, error in results if error]
        if hydrated:
            self.rest_last_event_at = time.time()
            self.last_event_at = max(filter(None, [self.rest_last_event_at, self.ws_last_event_at]), default=self.rest_last_event_at)
        if errors:
            self.rest_last_error = "; ".join(errors[:5])
            self.last_error = self.ws_last_error or self.rest_last_error
        return {"requested": len(requested) * len(symbols), "hydrated": hydrated,
                "already_ready": len(requested) * len(symbols) - len(missing), "errors": errors[:20]}

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
        # WS top-of-book taze değilse (sessiz/ölü soket) REST bookTicker tek
        # istekle best-bid/ask yedeği sağlar; böylece likidite kapısı WS
        # kesintisinde bile güncel spread/derinlik görebilir.
        try:
            rows_book = await book_tickers([str(symbol).upper() for symbol in self.symbols])
            book_now = time.time()
            for row in rows_book or []:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol", "")).upper()
                try:
                    bid = float(row.get("b") or 0)
                    ask = float(row.get("a") or 0)
                    bid_qty = float(row.get("B") or 0)
                    ask_qty = float(row.get("A") or 0)
                except (TypeError, ValueError):
                    continue
                if bid <= 0 or ask <= 0:
                    continue
                flow = self.orderflow.get(symbol)
                flow_age = float((flow or {}).get("updated_at") or 0)
                if flow_age and (book_now - flow_age) <= self.ORDERBOOK_MAX_AGE_SEC:
                    continue  # WS hâlâ taze; üzerine yazma.
                self.orderflow[symbol].update({
                    "bid_price": bid, "ask_price": ask,
                    "bid_qty": bid_qty, "ask_qty": ask_qty,
                    "spread_pct": ((ask - bid) / bid * 100) if bid else None,
                    "updated_at": book_now,
                    "source": "binance_tr_public_rest_bookTicker",
                })
        except Exception as exc:
            print(f"[MarketData] bookTicker yenileme hatası: {exc}", flush=True)

    async def _rest_refresh_loop(self):
        try:
            while self.running:
                await self.refresh_24h_tickers()
                # Safety net: repair any series the WS left gapped (silent
                # per-stream stalls never raise in _run_ws_group).
                try:
                    await self.repair_history_gaps()
                except Exception as exc:
                    # Hata durumunda döngüyü sonlandırma — logla ve devam et.
                    # Geçici bir hata (ağ kopması, timeout) tüm izlemeyi durdurmasın.
                    print(f"[MarketData] Gap repair hatası (denenecek): {exc}", flush=True)
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise

    def _build_ws_groups(self, generation: int):
        """Create a fresh immutable connection plan for this generation."""
        symbols = list(dict.fromkeys(str(symbol).replace("_", "").lower() for symbol in self.symbols))
        timeframes = list(self.timeframes)
        # kline + depth5 + aggTrade + bookTicker + ticker
        streams_per_symbol = len(timeframes) + 4
        # Stream sayısı dokümantasyondaki 1024 bağlantı limitinin çok altında
        # tutulur; host rotasyonu generation bazında yapılır.
        group_size = max(1, self.WS_MAX_STREAMS_PER_CONNECTION // streams_per_symbol)
        bases = list(WS_BASES or (WS_BASE,))
        base = bases[self.ws_host_index % len(bases)]
        plans = []
        for index in range(0, len(symbols), group_size):
            group = symbols[index:index + group_size]
            streams = "/".join(
                [f"{symbol}@kline_{tf}" for tf in timeframes for symbol in group]
                + [f"{symbol}@depth5@100ms" for symbol in group]
                + [f"{symbol}@aggTrade" for symbol in group]
                + [f"{symbol}@bookTicker" for symbol in group]
                + [f"{symbol}@ticker" for symbol in group]
            )
            plans.append({
                "group_id": index // group_size + 1,
                "generation": generation,
                "symbols": tuple(group),
                "timeframes": tuple(timeframes),
                "base": base,
                "url": f"{base}/stream?streams={streams}",
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
                    self.ws_connected_at = time.time()
                    print(f"[MarketData] WS bağlandı generation={generation} grup={group_id} base={plan.get('base')}", flush=True)
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
                # Bağlantı hatasında bir sonraki nesil diğer hostu denesin.
                bases = list(WS_BASES or (WS_BASE,))
                self.ws_host_index = (self.ws_host_index + 1) % len(bases)
                # Candles may have closed while the socket was down; splice
                # the missing range back in before fresh bars resume.
                asyncio.create_task(self.repair_history_gaps(symbols=plan["symbols"], timeframes=plan["timeframes"]),
                                    name=f"market-gap-repair-g{generation}-{group_id}")
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
                # 24 saatlik sunucu bağlantı ömrü dolduysa yeni nesil başlat.
                if self.ws_connected_at and (time.time() - self.ws_connected_at) >= self.ws_max_lifetime_sec:
                    print("[MarketData] WS 24s ömrü doldu; yeni nesil başlatılıyor", flush=True)
                    self.reconnect_requested = True
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
        # bookTicker stream'i (b/B/a/A skaler) orderbook olarak işlenir.
        if stream.endswith("@bookTicker") or str(data.get("e") or "") == "bookTicker":
            self._process_orderbook(data)
            self._mark_ws_event()
            return
        # Sunucu kapanışı: Binance dokümantasyonuna göre sunucu 24 saatte bir
        # serverShutdown olayı gönderip bağlantıyı kapatır; yeni nesil hemen
        # açılmalı.
        if str(data.get("e") or "").lower() == "servershutdown":
            print("[MarketData] serverShutdown alındı; yeni nesil başlatılıyor", flush=True)
            self.reconnect_requested = True
            return
        # Bireysel bookTicker event'i (b/B/a/A skaler): depth yoksa dahi
        # orderbook olarak işlenir.
        if str(data.get("e") or "") == "bookTicker":
            self._process_orderbook(data)
            self._mark_ws_event()
            return
        # Event adına göre de ticker/miniTicker işle (raw stream veya stream
        # alanı olmayan mesajlar için).
        if str(data.get("e") or "") in {"24hrTicker", "24hrMiniTicker"}:
            symbol = str(data.get("s") or "").upper()
            price = float(data.get("c") or 0)
            if symbol and price and price > 0:
                tickers = dict(self.tickers)
                tickers[symbol] = {
                    "symbol": symbol,
                    "last_price": price,
                    "timestamp": int(data.get("E", time.time() * 1000) or time.time() * 1000),
                    "source": "binance_tr_public_ws:ticker",
                }
                self.tickers = tickers
                self._mark_ws_event()
            return
        if not stream:
            self._process_kline(data)
            return
        # Bireysel ticker/miniTicker stream'leri kline şemasına uymaz; bunlar
        # doğrudan canlı fiyat önbelleğine işlenir.
        sig = stream.split("@")
        if len(sig) == 2 and sig[1] in {"ticker", "miniTicker"} and isinstance(data, dict):
            symbol = str(data.get("s") or sig[0] or "").upper()
            price = float(data.get("c") or data.get("wrap") or 0)
            if symbol and price and price > 0:
                tickers = dict(self.tickers)
                tickers[symbol] = {
                    "symbol": symbol,
                    "last_price": price,
                    "timestamp": int(data.get("E", time.time() * 1000) or time.time() * 1000),
                    "source": f"binance_tr_public_ws:{sig[1]}",
                }
                self.tickers = tickers
                self._mark_ws_event()
            return
        self._process_kline(data)

    def _process_kline(self, kline_data):
        event = kline_data.get("e")
        if event in {"depthUpdate", "depth", "bookTicker"} or "bids" in kline_data \
                or (isinstance(kline_data.get("b"), list) and isinstance(kline_data.get("a"), list)):
            self._process_orderbook(kline_data)
            self._mark_ws_event()
            return
        if event in {"aggTrade", "trade"} or ("p" in kline_data and "q" in kline_data):
            symbol = str(kline_data.get("s", "")).upper()
            if symbol:
                self._accumulate_trade(symbol, kline_data)
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
        # O(n) linear scan yerine dict mapping kullan — O(1) lookup
        ts_index_map = history.get("_ts_index_map")
        if ts_index_map is None:
            # İlk sefer: mapping oluştur (lazy initialization)
            ts_index_map = {ts: idx for idx, ts in enumerate(timestamps)}
            history["_ts_index_map"] = ts_index_map
        index = ts_index_map.get(opened_at_ms)
        if index is not None:
            for key, value in zip(keys, values):
                history[key][index] = value
            # Mapping'i güncelle (değişiklik yok ama tutarlılık için)
        else:
            index = len(timestamps)
            timestamps.append(opened_at_ms)
            ts_index_map[opened_at_ms] = index
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
            # Mapping'i yeniden indeksle — eski offset'i düzelt
            ts_index_map = history.get("_ts_index_map")
            if ts_index_map is not None:
                history["_ts_index_map"] = {ts: idx for idx, ts in enumerate(timestamps)}

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
        tf = tf or "5m"
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
        tf = tf or "5m"
        history = self.klines.get(tf, {}).get(symbol.upper(), {})
        volumes = history.get("volumes", [])
        return float(np.mean(volumes)) if volumes else 0.0

    def get_ut_kline(self, symbol, tf=None):
        tf = tf or "5m"
        return self.klines.get(tf, {}).get(symbol.upper(), _empty_history())

    def _process_orderbook(self, data):
        stream_symbol = str(data.get("_stream") or "").split("@", 1)[0]
        symbol = str(data.get("s") or data.get("symbol") or stream_symbol or "").upper()
        bids = data.get("bids", data.get("b", []))
        asks = data.get("asks", data.get("a", []))
        # Bireysel bookTicker (b/B/a/A alanları skaler) burada işlenir.
        if isinstance(bids, list) and not bids and isinstance(asks, list) and not asks:
            return
        if not symbol:
            return
        if isinstance(bids, list) and isinstance(asks, list) and bids and asks:
            try:
                top_bids = bids[:5]
                top_asks = asks[:5]
                bid_qty = sum(float(row[1]) for row in top_bids)
                ask_qty = sum(float(row[1]) for row in top_asks)
                bid = float(top_bids[0][0])
                ask = float(top_asks[0][0])
            except (TypeError, ValueError, IndexError):
                return
        else:
            try:
                bid = float(data.get("b", 0) or 0)
                ask = float(data.get("a", 0) or 0)
                bid_qty = float(data.get("B", 0) or 0)
                ask_qty = float(data.get("A", 0) or 0)
            except (TypeError, ValueError):
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

    # Aggressive-flow accumulation window in seconds; the rolling counters are
    # reset when the window rolls over, never mid-window.
    TRADE_FLOW_WINDOW_SEC = 60.0

    @staticmethod
    def _trade_side(is_buyer_maker: bool) -> str:
        """Binance `m` flag: true → buyer was maker → aggressive SELL."""
        return "sell" if is_buyer_maker else "buy"

    def _accumulate_trade(self, symbol: str, trade: dict):
        """Fold one aggTrade event into the symbol's rolling 60s trade flow.

        Uses the same WS stream that was already subscribed; this is a pure
        addition of counters, not a new connection or API dependency. Whale
        thresholds are in TRY notional so a low-priced AXLTRY fill needs far
        more units to count as a whale than a BTCTRY fill.
        """
        try:
            qty = float(trade.get("q", trade.get("Q", 0)) or 0)
            price = float(trade.get("p", trade.get("P", 0)) or 0)
        except (TypeError, ValueError):
            return
        if qty <= 0 or price <= 0:
            return
        notional = qty * price
        side = self._trade_side(bool(trade.get("m", False)))
        bucket = self.trade_flow[symbol]
        now = time.time()
        if now - float(bucket.get("window_start") or 0) >= self.TRADE_FLOW_WINDOW_SEC:
            bucket.update({
                "buy_qty": 0.0, "sell_qty": 0.0, "buy_count": 0, "sell_count": 0,
                "buy_notional": 0.0, "sell_notional": 0.0,
                "whale_buys": 0, "whale_sells": 0, "window_start": now,
            })
        if side == "buy":
            bucket["buy_qty"] += qty
            bucket["buy_count"] += 1
            bucket["buy_notional"] += notional
            if notional >= self.WHALE_NOTIONAL_TRY:
                bucket["whale_buys"] += 1
        else:
            bucket["sell_qty"] += qty
            bucket["sell_count"] += 1
            bucket["sell_notional"] += notional
            if notional >= self.WHALE_NOTIONAL_TRY:
                bucket["whale_sells"] += 1
        bucket["updated_at"] = now
        # Bounded FIFO trade tape: whale activity classification needs the
        # surrounding trades to measure the post-fill price impact. 2000
        # aggTrade events is enough for a multi-minute context on active pairs.
        tape = bucket.setdefault("_tape", deque(maxlen=2000))
        tape.append({"t": int(trade.get("T", trade.get("E", 0)) or 0),
                     "p": price, "q": qty, "m": bool(trade.get("m", False))})

    # A single trade is "whale-sized" when its TRY notional reaches this.
    # Binance TR spot notional for BTCTRY ~ 25k+ TRY; for low-price pairs the
    # same threshold still catches genuinely large market orders.
    WHALE_NOTIONAL_TRY = 25_000.0

    def _roll_trade_window(self, symbol: str):
        bucket = self.trade_flow[symbol]
        now = time.time()
        if now - float(bucket.get("window_start") or 0) >= self.TRADE_FLOW_WINDOW_SEC:
            tape = bucket.get("_tape")
            bucket.update({
                "buy_qty": 0.0, "sell_qty": 0.0, "buy_count": 0, "sell_count": 0,
                "buy_notional": 0.0, "sell_notional": 0.0,
                "whale_buys": 0, "whale_sells": 0, "window_start": now,
            })
            if tape:
                bucket["_tape"] = tape

    def get_microstructure(self, symbol: str, price: float | None = None,
                           window_sec: float = 60.0) -> dict:
        """Realtime microstructure: depth imbalance + rolling aggressive flow.

        ``price`` lets callers compute a spread_pct snapshot and TRY depth when
        the ticker and the orderbook have slightly different freshness; the
        returned flags never claim data that the WS has not delivered.
        """
        symbol = symbol.upper()
        flow = self.orderflow[symbol]
        trades = self.trade_flow[symbol]
        self._roll_trade_window(symbol)
        now = time.time()
        bid, ask = flow.get("bid_price"), flow.get("ask_price")
        bid_qty = float(flow.get("bid_qty") or 0)
        ask_qty = float(flow.get("ask_qty") or 0)
        book_total = bid_qty + ask_qty
        spread_pct = flow.get("spread_pct")
        if spread_pct is None and bid and ask and bid > 0:
            spread_pct = (ask - bid) / bid * 100
        mid = (bid + ask) / 2 if bid and ask else (price or 0)
        depth_try = book_total * mid if (book_total > 0 and mid > 0) else None
        imbalance = (bid_qty - ask_qty) / book_total if book_total > 0 else None
        buy_notional = float(trades.get("buy_notional") or 0)
        sell_notional = float(trades.get("sell_notional") or 0)
        trade_total = buy_notional + sell_notional
        trade_imbalance = (buy_notional - sell_notional) / trade_total if trade_total > 0 else None
        buy_count = int(trades.get("buy_count") or 0)
        sell_count = int(trades.get("sell_count") or 0)
        buy_qty = float(trades.get("buy_qty") or 0)
        sell_qty = float(trades.get("sell_qty") or 0)
        whale_buys = int(trades.get("whale_buys") or 0)
        whale_sells = int(trades.get("whale_sells") or 0)
        age_sec = (now - float(flow.get("updated_at") or 0)) if flow.get("updated_at") else None
        trade_age_sec = (now - float(trades.get("updated_at") or 0)) if trades.get("updated_at") else None
        flags = []
        if age_sec is None or age_sec > self.ORDERBOOK_MAX_AGE_SEC:
            flags.append("orderbook_stale")
        if not buy_count and not sell_count:
            flags.append("no_agg_trades_60s")
        elif trade_age_sec is not None and trade_age_sec > self.TRADE_FLOW_WINDOW_SEC:
            flags.append("trade_flow_stale")
        # Whale giriş/çıkış sınıflandırması: tape'teki whale işlemlerinin
        # işlem-sonrası fiyat etkisiyle birikim/dağıtım ayrımı. Pahalı değildir
        # ve veri yoksa no_whale döner.
        try:
            whale_activity = whale_activity_from_tape(list(trades.get("_tape") or []),
                                                      self.WHALE_NOTIONAL_TRY, 8)
        except Exception:
            whale_activity = {"verdict": "error", "data_ready": False}
        return {
            "symbol": symbol,
            "spread_pct": round(spread_pct, 6) if spread_pct is not None else None,
            "best_bid": bid, "best_ask": ask,
            "bid_qty": round(bid_qty, 8), "ask_qty": round(ask_qty, 8),
            "depth_imbalance": round(imbalance, 4) if imbalance is not None else None,
            "orderbook_depth_try": round(depth_try, 2) if depth_try is not None else None,
            "trade_flow": {
                "window_sec": self.TRADE_FLOW_WINDOW_SEC,
                "buy_qty": round(buy_qty, 8), "sell_qty": round(sell_qty, 8),
                "buy_count": buy_count, "sell_count": sell_count,
                "buy_notional_try": round(buy_notional, 2),
                "sell_notional_try": round(sell_notional, 2),
                "cvd_try": round(buy_notional - sell_notional, 2),
                "trade_imbalance": round(trade_imbalance, 4) if trade_imbalance is not None else None,
                "trade_rate_per_min": buy_count + sell_count,
                "whale_buys": whale_buys, "whale_sells": whale_sells,
                "whale_notional_threshold_try": self.WHALE_NOTIONAL_TRY,
                "whale_activity": whale_activity,
            },
            "freshness": {
                "orderbook_age_sec": round(age_sec, 3) if age_sec is not None else None,
                "trade_flow_age_sec": round(trade_age_sec, 3) if trade_age_sec is not None else None,
            },
            "flags": flags,
            "data_ready": not flags,
            "source": flow.get("source") or "binance_tr_public_ws",
            "updated_at": now,
        }

    def liquidity_status(self, symbol, order_value_try, allow_warmup=False, ignore_ws_freshness=False):
        """Fail closed unless all price, candle, volume and depth inputs are fresh.

        A caller may explicitly opt into a startup-only observation bypass. It
        is bounded to ``WARMUP_BYPASS_SEC`` and is never used by trading callers
        by default.  ``ignore_ws_freshness`` keeps every liquidity threshold
        (depth, volume ratio, 24h quote volume) but skips the WebSocket
        freshness stamps — for auto-traders whose candidates come from
        Top-Gainer REST scans with no WS subscription history yet; their
        orderbook snapshot is refreshed via REST right before the call.
        Spread hiçbir likidite kapısında koşul değildir: spread koruması
        otonom ve manuel taramadan tamamen kaldırıldı.
        """
        symbol = symbol.upper()
        if not config.LIQUIDITY_FILTER_ENABLED:
            return True, {"disabled": True}
        ticker = self.get_ticker(symbol) or {}
        tf = "5m"
        history = self.klines.get(tf, {}).get(symbol, {})
        volumes = history.get("volumes", [])
        current = volumes[-1] if volumes else 0.0
        average = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else 0.0
        ratio = current / average if average > 0 else 0.0
        flow = self.get_orderflow(symbol)
        price = float(ticker.get("last_price", 0) or 0)
        depth_try = (float(flow.get("bid_qty", 0) or 0) + float(flow.get("ask_qty", 0) or 0)) * price
        quote_volume = float(self.ticker_24h.get(symbol, 0) or 0)

        freshness = self.data_freshness(symbol, tf)
        rest_24h_fresh = bool(self.rest_ticker_updated_at) and (
            time.time() - self.rest_ticker_updated_at <= self.REST_24H_MAX_AGE_SEC
        )
        missing_or_stale = []
        if not ignore_ws_freshness and not freshness["ticker"]["fresh"]:
            missing_or_stale.append("ticker")
        if (not ignore_ws_freshness and not freshness["kline"]["fresh"]) or len(volumes) < 21:
            missing_or_stale.append("kline")
        if not ignore_ws_freshness and not freshness["orderbook"]["fresh"]:
            missing_or_stale.append("orderbook")
        if not rest_24h_fresh or quote_volume <= 0:
            missing_or_stale.append("ticker_24h")
        if ignore_ws_freshness:
            # WS damgası atlanan bileşenler gerçek veriyle dolu olmayabilir;
            # bunları missing_or_stale'den çıkarıp yalnız gerçek eşiklere bak.
            missing_or_stale = [item for item in missing_or_stale if item != "ticker_24h"] or missing_or_stale
        warmup_bypass = bool(
            allow_warmup and missing_or_stale and time.time() - self.created_at <= self.WARMUP_BYPASS_SEC
        )

        high_liquidity = quote_volume >= config.HIGH_LIQUIDITY_BYPASS_VOLUME_TRY
        if ignore_ws_freshness:
            checks = {
                "fresh_inputs": True,  # REST ile taze aday; WS damgası beklenmiyor
                "quote_volume": quote_volume >= config.MIN_24H_QUOTE_VOLUME_TRY,
                "volume_ratio": high_liquidity or ratio >= config.MIN_VOLUME_RATIO,
                "orderbook_depth": depth_try >= order_value_try * config.MIN_ORDERBOOK_DEPTH_MULTIPLIER,
            }
        else:
            checks = {
                "fresh_inputs": not missing_or_stale or warmup_bypass,
                "quote_volume": (warmup_bypass and "ticker_24h" in missing_or_stale)
                                or quote_volume >= config.MIN_24H_QUOTE_VOLUME_TRY,
                "volume_ratio": (warmup_bypass and "kline" in missing_or_stale)
                                or high_liquidity or ratio >= config.MIN_VOLUME_RATIO,
                "orderbook_depth": (warmup_bypass and ("ticker" in missing_or_stale
                                                         or "orderbook" in missing_or_stale))
                                   or depth_try >= order_value_try * config.MIN_ORDERBOOK_DEPTH_MULTIPLIER,
            }
        if ignore_ws_freshness:
            high_liquidity = quote_volume >= config.HIGH_LIQUIDITY_BYPASS_VOLUME_TRY
        return all(checks.values()), {
            "quote_volume": quote_volume,
            "high_liquidity": high_liquidity,
            "volume_ratio": ratio,
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
