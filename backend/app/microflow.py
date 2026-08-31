"""Sub-minute market microstructure layer for the velocity fast-riser system.

The main MarketData feed subscribes the whole active universe on kline_*/depth5/
aggTrade streams — it cannot carry 1s/5s bars for every symbol. This module
opens a *single-symbol* WS stream only for the handful of active velocity
candidates so that:

- 1s and 5s candles give the LLM a sub-minute picture the 1m feed cannot;
- the same stream folds aggTrade events into a rolling CVD proxy + whale count;
- a REST depth snapshot (default 20 levels) feeds wall/ladder asymmetry.

Everything here is public market data and paper-trading safe; nothing opens,
closes or sizes an order.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque

import websockets

from app.binance_tr_public import WS_BASE, depth as rest_depth
from app.market_intelligence import whale_activity_from_tape

logger = logging.getLogger("scalper.microflow")

_SECONDS_PER_S = 1_000
_SECONDS_PER_5S = 5_000
_1M_MS = 60_000
_MAX_AGG_TRADES = 2000


def _empty_bars():
    return {"timestamps": [], "opens": [], "highs": [], "lows": [], "closes": [], "volumes": []}


def _aggregate_5s(bars_1s: dict) -> dict:
    """5s bar'ı 1s barlardan türetir (her 5 tam bar bir 5s bar olur)."""
    timestamps = bars_1s.get("timestamps") or []
    closes = bars_1s.get("closes") or []
    opens = bars_1s.get("opens") or []
    highs = bars_1s.get("highs") or []
    lows = bars_1s.get("lows") or []
    volumes = bars_1s.get("volumes") or []
    out = _empty_bars()
    for start in range(0, len(timestamps) - len(timestamps) % 5, 5):
        chunk = list(range(start, start + 5))
        out["timestamps"].append(timestamps[chunk[0]])
        out["opens"].append(opens[chunk[0]])
        out["highs"].append(max(highs[i] for i in chunk))
        out["lows"].append(min(lows[i] for i in chunk))
        out["closes"].append(closes[chunk[-1]])
        out["volumes"].append(sum(volumes[i] for i in chunk))
    return out


def _reset_flow():
    return {"buy_qty": 0.0, "sell_qty": 0.0, "buy_count": 0, "sell_count": 0,
            "buy_notional": 0.0, "sell_notional": 0.0,
            "whale_buys": 0, "whale_sells": 0, "window_start": time.time(),
            "updated_at": 0.0}


class MicroFlow:
    """Per-symbol live sub-minute microstructure cache with bounded memory."""

    MAX_BARS = 240           # ~4 min of 1s bars, ~20 min of 5s bars
    TRADE_WINDOW_SEC = 60.0
    WHALE_NOTIONAL_TRY = 25_000.0

    def __init__(self):
        self._lock = asyncio.Lock()
        self._ws_task = None
        self._connect_owner = None
        self._reconnect_requested = False
        self._generation = 0
        self.symbol: str | None = None
        self.bars = {"1s": defaultdict(_empty_bars), "5s": defaultdict(_empty_bars)}
        self.trade_flow = defaultdict(_reset_flow)
        self.depth = {}
        self.depth_updated_at = 0.0
        self.ws_updated_at = 0.0
        self.ws_error = None
        self.running = False

    # ---------------------------------------------------------------- control
    async def start(self, symbol: str):
        symbol = str(symbol).replace("_", "").upper()
        if not symbol:
            return
        if self.symbol == symbol and self.running and self._ws_task and not self._ws_task.done():
            return
        self.symbol = symbol
        self.running = True
        self._reconnect_requested = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except (asyncio.CancelledError, Exception):
                pass
        self._ws_task = asyncio.create_task(self._run(), name=f"microflow-ws-{symbol.lower()}")
        logger.info("microflow: %s için tekil WS akışı başlatıldı", symbol)

    async def stop(self):
        self.running = False
        self._reconnect_requested = True
        self._generation += 1
        task = self._ws_task
        self._ws_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("microflow: akış durduruldu")

    # ---------------------------------------------------------------- ws loop
    async def _run(self):
        generation = self._generation
        while self.running and generation == self._generation:
            symbol = self.symbol
            if not symbol:
                await asyncio.sleep(0.5)
                continue
            streams = "/".join([
                f"{symbol.lower()}@kline_1s",
                f"{symbol.lower()}@aggTrade",
            ])
            url = f"{WS_BASE}/stream?streams={streams}"
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20,
                                              close_timeout=5, max_queue=5000) as ws:
                    logger.info("microflow: WS bağlandı | symbol=%s generation=%d", symbol, generation)
                    async for raw in ws:
                        if (not self.running or generation != self._generation
                                or self._reconnect_requested):
                            break
                        try:
                            self._handle(json.loads(raw))
                        except (json.JSONDecodeError, ValueError):
                            continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ws_error = f"{type(exc).__name__}: {exc}"
                logger.warning("microflow: WS hata | symbol=%s: %s", symbol, exc)
                if self.running and generation == self._generation:
                    await asyncio.sleep(2)

    def _handle(self, message: dict):
        data = message.get("data", message)
        if not isinstance(data, dict):
            return
        event = data.get("e")
        if event == "kline":
            candle = data.get("k") or {}
            interval = str(candle.get("i") or "")
            symbol = str(candle.get("s") or self.symbol or "").upper()
            if interval in self.bars and candle.get("x", False) and symbol:
                self._fold_candle(interval, symbol, candle)
        elif event in {"aggTrade", "trade"} or ("p" in data and "q" in data):
            symbol = str(data.get("s", "")).upper()
            if symbol:
                self._accumulate_trade(symbol, data)
        self.ws_updated_at = time.time()

    def _fold_candle(self, interval: str, symbol: str, candle: dict):
        try:
            opened_at_ms = int(candle.get("t", 0) or 0)
            opened = float(candle.get("o", 0))
            high = float(candle.get("h", 0))
            low = float(candle.get("l", 0))
            close = float(candle.get("c", 0))
            volume = float(candle.get("v", 0))
        except (TypeError, ValueError):
            return
        bucket = self.bars[interval][symbol]
        timestamps = bucket["timestamps"]
        if timestamps and timestamps[-1] == opened_at_ms:
            bucket["closes"][-1] = close
            bucket["highs"][-1] = max(bucket["highs"][-1], high)
            bucket["lows"][-1] = min(bucket["lows"][-1], low)
            bucket["volumes"][-1] = volume
        else:
            timestamps.append(opened_at_ms)
            bucket["opens"].append(opened)
            bucket["highs"].append(high)
            bucket["lows"].append(low)
            bucket["closes"].append(close)
            bucket["volumes"].append(volume)
        if len(timestamps) > self.MAX_BARS:
            excess = len(timestamps) - self.MAX_BARS
            del timestamps[:excess]
            for key in ("opens", "highs", "lows", "closes", "volumes"):
                del bucket[key][:excess]

    def _accumulate_trade(self, symbol: str, trade: dict):
        try:
            qty = float(trade.get("q", trade.get("Q", 0)) or 0)
            price = float(trade.get("p", trade.get("P", 0)) or 0)
        except (TypeError, ValueError):
            return
        if qty <= 0 or price <= 0:
            return
        notional = qty * price
        side = "sell" if bool(trade.get("m", False)) else "buy"
        bucket = self.trade_flow[symbol]
        now = time.time()
        if now - float(bucket.get("window_start") or 0) >= self.TRADE_WINDOW_SEC:
            tape = bucket.get("_tape")
            bucket.update(_reset_flow())
            if tape:
                bucket["_tape"] = tape
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
        # Bounded FIFO for the trade tape (slippage histogram input).
        tape = self.trade_flow[symbol].setdefault("_tape", deque(maxlen=_MAX_AGG_TRADES))
        tape.append({"t": int(trade.get("T", trade.get("E", 0)) or 0),
                     "p": price, "q": qty, "m": bool(trade.get("m", False))})

    # ---------------------------------------------------------------- snapshot
    async def refresh_depth(self, limit: int = 20):
        if not self.symbol:
            return None
        try:
            book = await rest_depth(self.symbol, limit)
            bids = book.get("bids") or []
            asks = book.get("asks") or []
            if not bids or not asks:
                return None
            self.depth = {
                "symbol": self.symbol,
                "bids": [[float(row[0]), float(row[1])] for row in bids],
                "asks": [[float(row[0]), float(row[1])] for row in asks],
                "source": "binance_tr_public_rest",
                "received_at": book.get("received_at"),
            }
            self.depth_updated_at = time.time()
            return self.depth
        except Exception as exc:
            logger.warning("microflow: depth %s: %s", self.symbol, exc)
            return None

    def get_snapshot(self, price: float | None = None) -> dict:
        """Microstructure snapshot for the active symbol (pure, non-blocking)."""
        symbol = self.symbol
        if not symbol:
            return {"symbol": None, "data_ready": False, "error": "aktif sembol yok"}
        bars = self.bars
        flow = self.trade_flow.get(symbol) or {}
        now = time.time()
        buy_notional = float(flow.get("buy_notional") or 0)
        sell_notional = float(flow.get("sell_notional") or 0)
        trade_total = buy_notional + sell_notional
        bars_1s = bars["1s"].get(symbol, {})
        closes_1s = bars_1s.get("closes", [])
        last_price = closes_1s[-1] if closes_1s else price
        ret_1s = (last_price / closes_1s[-3] - 1) * 100 if last_price and len(closes_1s) >= 3 else None
        # 5s bar, 1s barlardan 5'er birleştirilerek türetilir (Binance TR'de
        # kline_5s stream'i yoktur); son eksik grup dahil edilmez.
        bars_5s = _aggregate_5s(bars_1s)
        closes_5s = bars_5s.get("closes", [])
        ret_5s = (last_price / closes_5s[-1] - 1) * 100 if last_price and closes_5s else None
        depth = self.depth or {}
        bids = depth.get("bids") or []
        asks = depth.get("asks") or []
        bid_total = sum(qty for _, qty in bids[:5])
        ask_total = sum(qty for _, qty in asks[:5])
        wall_bid = max((qty for _, qty in bids), default=0.0)
        wall_ask = max((qty for _, qty in asks), default=0.0)
        mid = None
        if bids and asks:
            mid = (bids[0][0] + asks[0][0]) / 2
        depth_try = (bid_total + ask_total) * mid if mid else None
        ladder_asymmetry = (bid_total - ask_total) / (bid_total + ask_total) if (bid_total + ask_total) > 0 else None
        tape = flow.get("_tape") or []
        try:
            whale_activity = whale_activity_from_tape(list(tape), self.WHALE_NOTIONAL_TRY, 8)
        except Exception:
            whale_activity = {"verdict": "error", "data_ready": False}
        slippage = None
        if len(tape) >= 10 and last_price:
            prices = [item["p"] for item in tape[-30:]]
            realized = (max(prices) - min(prices)) / min(prices) * 100 if min(prices) > 0 else None
            if realized is not None:
                slippage = {
                    "sample_trades": len(prices),
                    "sample_span_sec": round((now - flow.get("window_start", now)), 3),
                    "realized_range_pct": round(realized, 4),
                    "estimated_slippage_pct": round(realized * 0.5, 4),
                }
        return {
            "symbol": symbol,
            "price": last_price,
            "bars": {
                "1s": {"count": len(closes_1s), "last_close": closes_1s[-1] if closes_1s else None,
                       "ret_1s_pct": round(ret_1s, 4) if ret_1s is not None else None},
                "5s": {"count": len(closes_5s), "last_close": closes_5s[-1] if closes_5s else None,
                       "ret_5s_pct": round(ret_5s, 4) if ret_5s is not None else None},
            },
            "trade_flow": {
                "window_sec": self.TRADE_WINDOW_SEC,
                "buy_count": int(flow.get("buy_count") or 0),
                "sell_count": int(flow.get("sell_count") or 0),
                "buy_notional_try": round(buy_notional, 2),
                "sell_notional_try": round(sell_notional, 2),
                "cvd_try": round(buy_notional - sell_notional, 2),
                "trade_imbalance": round((buy_notional - sell_notional) / trade_total, 4) if trade_total > 0 else None,
                "trade_rate_per_min": int(flow.get("buy_count") or 0) + int(flow.get("sell_count") or 0),
                "whale_buys": int(flow.get("whale_buys") or 0),
                "whale_sells": int(flow.get("whale_sells") or 0),
                "whale_notional_threshold_try": self.WHALE_NOTIONAL_TRY,
                "whale_activity": whale_activity,
            },
            "depth": {
                "levels": len(bids),
                "depth_try": round(depth_try, 2) if depth_try is not None else None,
                "wall_bid_try": round(wall_bid * mid, 2) if wall_bid and mid else None,
                "wall_ask_try": round(wall_ask * mid, 2) if wall_ask and mid else None,
                "ladder_asymmetry": round(ladder_asymmetry, 4) if ladder_asymmetry is not None else None,
                "updated_age_sec": round(now - self.depth_updated_at, 2) if self.depth_updated_at else None,
            },
            "slippage": slippage,
            "freshness": {
                "ws_age_sec": round(now - self.ws_updated_at, 2) if self.ws_updated_at else None,
                "ws_error": self.ws_error,
            },
            "data_ready": bool(self.ws_updated_at),
            "paper_only": True,
            "generated_at": now,
        }


microflow = MicroFlow()


async def start_microflow_for(symbol: str):
    """Start (or hot-swap) the single-symbol sub-minute feed."""
    await microflow.start(symbol)


async def stop_microflow():
    await microflow.stop()
