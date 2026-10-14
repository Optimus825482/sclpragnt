"""Binance TR signed listen-token user-data streams.

This module owns no trading endpoints: it only creates listen tokens and
subscribes to account/order events over Binance TR's WebSocket API.
One registry entry is created per user *per application process*.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import websockets

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-api.binance.tr:443/ws-api/v3"
LISTEN_TOKEN_PATH = "/open/v1/user-listen-token"
WS_PING_INTERVAL_SEC = 20
WS_PING_TIMEOUT_SEC = 20
TOKEN_VALIDITY_MS = 24 * 60 * 60 * 1000
TOKEN_RENEW_BEFORE_SEC = 5 * 60
EVENT_QUEUE_MAXSIZE = 512
SNAPSHOT_MAX_EVENTS = 100
RECONNECT_MIN_SEC = 1.0
RECONNECT_MAX_SEC = 60.0

PublishCallback = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class BinanceTrUserStreamError(RuntimeError):
    """Listen token or WebSocket subscription failed."""


def _create_listen_token_sync(api_key: str, api_secret: str) -> tuple[str, int]:
    """Create token via shared private REST signing, clock, and limit handling."""
    # Import lazily: this module can be loaded by app startup without introducing
    # a dependency cycle if the private REST adapter later adds stream hooks.
    from app import binance_tr_private

    try:
        data = binance_tr_private._signed_request(
            "POST", LISTEN_TOKEN_PATH, {"validity": TOKEN_VALIDITY_MS},
            api_key, api_secret,
        )
    except Exception as exc:
        # Do not include exception text: it may contain request details.
        raise BinanceTrUserStreamError(
            f"Binance TR listen token isteği başarısız ({type(exc).__name__})"
        ) from None
    token = data.get("token") if isinstance(data, dict) else None
    expiration = data.get("expirationTime") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token or not expiration:
        raise BinanceTrUserStreamError("Binance TR listen token yanıtı eksik")
    return token, int(expiration)


@dataclass
class _UserStream:
    user_id: str
    api_key: str
    api_secret: str
    callback: PublishCallback | None
    queue_size: int = EVENT_QUEUE_MAXSIZE
    task: asyncio.Task | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    events: deque = field(default_factory=lambda: deque(maxlen=SNAPSHOT_MAX_EVENTS))
    latest_by_type: dict[str, dict[str, Any]] = field(default_factory=dict)
    state: str = "starting"
    last_error: str | None = None
    connected_at: float | None = None
    last_event_at: float | None = None
    reconnects: int = 0
    dropped_events: int = 0

    async def emit(self, event: dict[str, Any]) -> None:
        self.last_event_at = time.time()
        self.events.append(event)
        self.latest_by_type[event["event_type"]] = event
        for queue in tuple(self.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                    self.dropped_events += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self.dropped_events += 1
        if self.callback is not None:
            try:
                result = self.callback(event)
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Callback errors are reported without user payload/credentials.
                self.last_error = f"publish_callback:{type(exc).__name__}"
                logger.exception("Binance TR user stream publish callback failed")

    async def _rpc(self, ws, pending: dict[str, asyncio.Future],
                   method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        pending[request_id] = future
        await ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
        try:
            response = await asyncio.wait_for(future, timeout=15)
        finally:
            pending.pop(request_id, None)
        if response.get("error"):
            err = response["error"]
            raise BinanceTrUserStreamError(
                f"WebSocket {method} reddedildi (kod={err.get('code')})"
            )
        return response.get("result") or response

    async def _reader(self, ws, pending: dict[str, asyncio.Future]) -> None:
        async for frame in ws:
            try:
                message = json.loads(frame)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            if request_id is not None:
                future = pending.get(str(request_id))
                if future is None:
                    # Some servers echo the ID as a number; compare string form.
                    future = next((f for key, f in pending.items()
                                   if key == str(request_id)), None)
                if future is not None and not future.done():
                    future.set_result(message)
                continue
            event_payload = message.get("event")
            if isinstance(event_payload, dict) and event_payload.get("e") == "eventStreamTerminated":
                raise BinanceTrUserStreamError("Binance TR kullanıcı akışını sonlandırdı")
            event = _normalize_event(message)
            if event is not None:
                await self.emit(event)
        raise ConnectionError("Binance TR WebSocket bağlantısı kapandı")

    async def _connection_session(self) -> None:
        token, expiration_ms = await asyncio.to_thread(
            _create_listen_token_sync, self.api_key, self.api_secret
        )
        async with websockets.connect(
            WS_URL,
            ping_interval=WS_PING_INTERVAL_SEC,
            ping_timeout=WS_PING_TIMEOUT_SEC,
            close_timeout=5,
            max_queue=256,
            open_timeout=15,
        ) as ws:
            pending: dict[str, asyncio.Future] = {}
            subscription_id = None
            reader = asyncio.create_task(self._reader(ws, pending), name=f"binance-tr-reader-{self.user_id}")
            stop_waiter = asyncio.create_task(self.stop_event.wait())
            try:
                result = await self._rpc(
                    ws, pending, "userDataStream.subscribe.listenToken",
                    {"listenToken": token},
                )
                # Never retain the token beyond the handshake.
                token = ""
                self.state = "connected"
                self.connected_at = time.time()
                self.last_error = None
                subscription_id = result.get("subscriptionId")
                logger.info("Binance TR user stream connected user_id=%s", self.user_id)
                renew_at = max(time.time() + 1,
                               expiration_ms / 1000 - TOKEN_RENEW_BEFORE_SEC)
                while not self.stop_event.is_set():
                    delay = max(0.1, renew_at - time.time())
                    done, _ = await asyncio.wait(
                        {reader, stop_waiter},
                        timeout=delay,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    # Surface socket closure, stream termination, or reader
                    # failure immediately; do not wait until token renewal.
                    if reader in done:
                        await reader
                        raise ConnectionError("Binance TR event reader beklenmedik biçimde durdu")
                    if stop_waiter in done or self.stop_event.is_set():
                        break
                    # Timeout means token renewal is due. Reader remains active
                    # and can still resolve the subscribe RPC response.
                    new_token, new_expiration_ms = await asyncio.to_thread(
                        _create_listen_token_sync, self.api_key, self.api_secret
                    )
                    await self._rpc(
                        ws, pending, "userDataStream.subscribe.listenToken",
                        {"listenToken": new_token},
                    )
                    new_token = ""
                    expiration_ms = new_expiration_ms
                    renew_at = max(time.time() + 1,
                                   expiration_ms / 1000 - TOKEN_RENEW_BEFORE_SEC)
                    logger.info("Binance TR user stream token renewed user_id=%s", self.user_id)
            finally:
                if not stop_waiter.done():
                    stop_waiter.cancel()
                await asyncio.gather(stop_waiter, return_exceptions=True)
                if not reader.done():
                    reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
                # Best-effort unsubscribe; connection close also releases it.
                if subscription_id is not None and not self.stop_event.is_set():
                    try:
                        await asyncio.wait_for(self._rpc(
                            ws, pending, "userDataStream.unsubscribe",
                            {"subscriptionId": subscription_id},
                        ), timeout=3)
                    except Exception:
                        pass

    async def run(self) -> None:
        attempt = 0
        try:
            while not self.stop_event.is_set():
                try:
                    await self._connection_session()
                    attempt = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.state = "reconnecting"
                    self.last_error = type(exc).__name__
                    self.reconnects += 1
                    attempt += 1
                    delay = min(RECONNECT_MAX_SEC, RECONNECT_MIN_SEC * 2 ** min(attempt - 1, 6))
                    delay *= random.uniform(0.8, 1.2)
                    logger.warning(
                        "Binance TR user stream reconnect user_id=%s error=%s delay=%.1fs",
                        self.user_id, type(exc).__name__, delay,
                    )
                    try:
                        await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
        finally:
            self.state = "stopped"
            self.api_key = ""
            self.api_secret = ""
            self.callback = None


def _normalize_event(message: dict[str, Any]) -> dict[str, Any] | None:
    """Return a safe, stable envelope for documented user-data event payloads."""
    payload = message.get("event")
    if not isinstance(payload, dict):
        payload = message.get("data") if isinstance(message.get("data"), dict) else message
    kind = payload.get("e") or payload.get("eventType") or payload.get("type")
    if kind not in ("executionReport", "outboundAccountPosition"):
        return None
    if kind == "executionReport":
        fields = {
            "event_time_ms": payload.get("E"),
            "symbol": payload.get("s"),
            "client_order_id": payload.get("c"),
            "side": payload.get("S"),
            "order_type": payload.get("o"),
            "time_in_force": payload.get("f"),
            "order_quantity": payload.get("q"),
            "order_price": payload.get("p"),
            "stop_price": payload.get("P"),
            "execution_type": payload.get("x"),
            "status": payload.get("X"),
            "reject_reason": payload.get("r"),
            "order_id": payload.get("i"),
            "last_executed_quantity": payload.get("l"),
            "cumulative_filled_quantity": payload.get("z"),
            "cumulative_quote_quantity": payload.get("Z"),
            "last_executed_price": payload.get("L"),
            "commission_amount": payload.get("n"),
            "commission_asset": payload.get("N"),
            "transaction_time_ms": payload.get("T"),
            "trade_id": payload.get("t"),
            "is_maker": payload.get("m"),
        }
    else:
        fields = {
            "event_time_ms": payload.get("E"),
            "last_account_update_ms": payload.get("u"),
            "balances": [
                {"asset": item.get("a"), "free": item.get("f"), "locked": item.get("l")}
                for item in (payload.get("B") or []) if isinstance(item, dict)
            ],
        }
    return {
        "event_type": kind,
        "received_at": time.time(),
        "fields": fields,
        "raw": payload,
    }


_streams: dict[str, _UserStream] = {}
_registry_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _registry_lock
    if _registry_lock is None:
        _registry_lock = asyncio.Lock()
    return _registry_lock


async def start_user_stream(user_id: str | int, api_key: str, api_secret: str,
                            publish_callback: PublishCallback | None = None,
                            *, queue_size: int = EVENT_QUEUE_MAXSIZE) -> dict[str, Any]:
    """Start or reuse this process's stream for one user; safe to call in lifespan."""
    uid = str(user_id)
    if not uid or not api_key or not api_secret:
        raise ValueError("user_id, api_key ve api_secret boş olamaz")
    async with _lock():
        current = _streams.get(uid)
        if current and current.task and not current.task.done():
            # A same-user credential rotation must replace the connection.
            if current.api_key == api_key and current.api_secret == api_secret:
                current.callback = publish_callback or current.callback
                return stream_status(uid)
            await _stop_locked(uid, current)
        stream = _UserStream(uid, api_key, api_secret, publish_callback,
                             queue_size=max(1, int(queue_size)))
        stream.task = asyncio.create_task(stream.run(), name=f"binance-tr-user-stream-{uid}")
        _streams[uid] = stream
        return stream_status(uid)


async def _stop_locked(uid: str, stream: _UserStream) -> None:
    stream.stop_event.set()
    if stream.task and not stream.task.done():
        stream.task.cancel()
        await asyncio.gather(stream.task, return_exceptions=True)
    stream.state = "stopped"
    stream.api_key = ""
    stream.api_secret = ""
    stream.callback = None
    for queue in tuple(stream.subscribers):
        stream.subscribers.discard(queue)
    _streams.pop(uid, None)


async def stop_user_stream(user_id: str | int) -> bool:
    """Stop the stream and clear its in-memory credentials for this user."""
    uid = str(user_id)
    async with _lock():
        stream = _streams.get(uid)
        if stream is None:
            return False
        await _stop_locked(uid, stream)
        return True


def subscribe_user_stream(user_id: str | int, *, maxsize: int = EVENT_QUEUE_MAXSIZE) -> asyncio.Queue:
    """Create an async event queue; full queues drop oldest and count drops."""
    stream = _streams.get(str(user_id))
    if stream is None or stream.state == "stopped":
        raise RuntimeError("Kullanıcı stream'i başlatılmamış")
    queue: asyncio.Queue = asyncio.Queue(maxsize=max(1, int(maxsize)))
    stream.subscribers.add(queue)
    return queue


def unsubscribe_user_stream(user_id: str | int, queue: asyncio.Queue) -> None:
    stream = _streams.get(str(user_id))
    if stream:
        stream.subscribers.discard(queue)


def stream_snapshot(user_id: str | int, *, limit: int = 20) -> dict[str, Any]:
    """Return latest account/order events and lifecycle state for UI reconciliation."""
    stream = _streams.get(str(user_id))
    if stream is None:
        return {"state": "stopped", "events": [], "latest_by_type": {}}
    return {
        **stream_status(user_id),
        "events": (list(stream.events)[-min(int(limit), SNAPSHOT_MAX_EVENTS):]
                   if int(limit) > 0 else []),
        "latest_by_type": dict(stream.latest_by_type),
    }


def stream_status(user_id: str | int) -> dict[str, Any]:
    stream = _streams.get(str(user_id))
    if stream is None:
        return {"state": "stopped", "connected": False}
    return {
        "state": stream.state,
        "connected": stream.state == "connected",
        "connected_at": stream.connected_at,
        "last_event_at": stream.last_event_at,
        "reconnects": stream.reconnects,
        "dropped_events": stream.dropped_events,
        "last_error": stream.last_error,
    }
