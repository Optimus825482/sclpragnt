"""Tek fiyat okuma servisi: taze WS ticker → REST ticker → REST 1m kline.

Paper defterleri (auto_paper, combined_paper, velocity) fiyatı buradan alır.
Servis YALNIZ OKUR: `market.tickers` içine asla yazmaz. Eski önbellek onarımı
(`api_common._fresh_public_price`) bu servisin üstüne sarmalayıcı olarak kalır
ve yan etkisini orada tutar.

Dönüş sözleşmesi: ``(price, age_sec, source)``; fiyat yoksa ``(None, None, None)``.
REST kaynaklarında yaş 0.0 kabul edilir (anlık sorgu).
"""
from __future__ import annotations

import logging
import time

from app import binance_tr_public as _btp
from app import paper_ledger
from app.state import market as _default_market

logger = logging.getLogger("scalper.price_service")

SOURCE_WS = "binance_tr_public_websocket"
SOURCE_REST_TICKER = "binance_tr_public_rest_ticker_price"
SOURCE_REST_KLINE = "binance_tr_public_rest_kline"
SOURCE_WS_MINI_ARR = "binance_tr_public_ws:miniTicker@arr"
# 2026-10-18: `market.mini_tickers` (`!miniTicker@arr`, saniyelik) satırı en
# fazla bu kadar eskiyse REST'ten ÖNCE kaynak olarak kullanılır.
MINI_TICKER_MAX_AGE_SEC = 5.0


def normalize(symbol) -> str:
    """Sembolü WS/REST anahtar biçimine getirir (``BTC_TRY`` → ``BTCTRY``)."""
    return str(symbol or "").replace("_", "").upper()


def mini_ticker_quote(symbol, *, market_obj=None, now_sec: float | None = None,
                      max_age_sec: float = MINI_TICKER_MAX_AGE_SEC):
    """`market.mini_tickers` (``!miniTicker@arr``) satırı < ``max_age_sec`` ise
    ``(price, age_sec, source)``; yoksa ``None``. Yalnız okur."""
    src = _default_market if market_obj is None else market_obj
    cache = getattr(src, "mini_tickers", None)
    if not isinstance(cache, dict):
        return None
    row = cache.get(normalize(symbol))
    if not isinstance(row, dict):
        return None
    try:
        price = float(row.get("last_price") or 0)
        ts_ms = float(row.get("timestamp") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0 or ts_ms <= 0:
        return None
    now = time.time() if now_sec is None else float(now_sec)
    age = max(0.0, now - ts_ms / 1000.0)
    if age > float(max_age_sec):
        return None
    return price, age, SOURCE_WS_MINI_ARR


def ws_quote(symbol, *, market_obj=None, now_sec: float | None = None):
    """Taze WS ticker'ı varsa ``(price, age_sec, source)``; yoksa ``None``.

    ``market_obj`` çağıranın kendi market referansıdır (testlerde ve modül
    seviyesi `market` adını yamalayan çağıranlar için); verilmezse
    `app.state.market` kullanılır.

    2026-10-18: sembolün kendi WS ticker'ı taze değilse `mini_tickers`
    (``!miniTicker@arr``, < 5 sn) denenir — REST'e gitmeden önceki son WS kaynağı.
    """
    src = _default_market if market_obj is None else market_obj
    try:
        ticker = src.get_ticker(normalize(symbol)) or {}
    except Exception:
        ticker = {}
    try:
        price = float(ticker.get("last_price") or 0)
        ts_ms = float(ticker.get("timestamp") or 0)
    except (TypeError, ValueError, AttributeError):
        price, ts_ms = 0.0, 0.0
    if price <= 0 or not paper_ledger.is_fresh(ts_ms, now_sec):
        return mini_ticker_quote(symbol, market_obj=src, now_sec=now_sec)
    now = time.time() if now_sec is None else float(now_sec)
    age = max(0.0, now - ts_ms / 1000.0)
    return price, age, (ticker.get("source") or SOURCE_WS)


async def rest_ticker_price(symbol) -> float | None:
    """REST `/ticker/price` fiyatı; yoksa veya 0 ise None. İstisna çağırana kalır."""
    normalized = normalize(symbol)
    rows = await _btp.ticker_price([normalized])
    row = next((r for r in (rows or []) if str(r.get("symbol", "")).upper() == normalized), None)
    price = float((row or {}).get("price") or 0)
    return price if price > 0 else None


async def rest_kline_price(symbol) -> float | None:
    """Son kapanmış 1m mumun kapanış fiyatı (son çare). İstisna çağırana kalır."""
    latest = await _btp.klines(normalize(symbol), "1m", 2)
    if not latest:
        return None
    price = float(latest[-1][4])
    return price if price > 0 else None


async def rest_quote(symbol):
    """REST yedeği: önce ticker, sonra kline. ``(price, 0.0, source)`` veya ``None``.

    Her adımın hatası yutulur ve loglanır; bir sonraki adıma geçilir.
    """
    try:
        price = await rest_ticker_price(symbol)
        if price:
            return price, 0.0, SOURCE_REST_TICKER
    except Exception as exc:
        logger.warning("price_service %s: REST ticker hatası: %s", normalize(symbol), exc)
    try:
        price = await rest_kline_price(symbol)
        if price:
            return price, 0.0, SOURCE_REST_KLINE
    except Exception as exc:
        logger.warning("price_service %s: REST kline hatası: %s", normalize(symbol), exc)
    return None


async def get_price(symbol, *, market_obj=None):
    """En iyi fiyat: taze WS ticker → taze miniTicker@arr (<5 sn) → REST yedeği.

    Bulunamazsa ``(None, None, None)``.
    """
    quote = ws_quote(symbol, market_obj=market_obj)
    if quote:
        return quote
    quote = await rest_quote(symbol)
    if quote:
        return quote
    return None, None, None
