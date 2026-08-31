"""Data layer: Binance TR public klines -> PostgreSQL historical_candles upsert.

Binance TR klines API caps history around ~1-2 days. Older windows are
repaired from OKX public klines (USDT pairs) when needed.
"""

import asyncio
import math
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

import psycopg

from app.binance_tr_public import historical_klines

PG_DSN = os.environ["DATABASE_URL"]
SOURCE_OKX = "okx_public_repair"


def normalize_binance(rows):
    """Binance kline row: [open_time, open, high, low, close, volume, close_time, quote_volume, ...]"""
    out = []
    for row in rows or []:
        if len(row) < 7:
            continue
        try:
            open_px, high_px, low_px, close_px = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            volume = float(row[5])
            quote_volume = float(row[7]) if len(row) > 7 and row[7] is not None else None
        except (TypeError, ValueError):
            continue
        open_time, close_time = int(row[0]), int(row[6])
        if not all(math.isfinite(v) for v in (open_px, high_px, low_px, close_px, volume)):
            continue
        out.append({
            "open_time": open_time, "close_time": close_time,
            "open": open_px, "high": high_px, "low": low_px, "close": close_px,
            "volume": volume, "quote_volume": quote_volume,
        })
    return out


def okx_symbol(symbol):
    """HEMITRY -> HEMITRY-USDT (strip quote suffix)."""
    for quote in ("USDT", "TRY"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[:-len(quote)]}-USDT"
    return f"{symbol}-USDT"


M3_MS = 180_000


def build_m3_from_m1(m1_rows):
    """Aggregate 1m candles into 3m candles (3-minute buckets starting on the hour).

    Binance TR serves the ``3m`` interval directly, but M3 must stay aligned
    with the M1 series used for the pre-rise window, so we build it from the
    same M1 source. Returns chronological dicts with open/high/low/close/volume.
    """
    if not m1_rows:
        return []
    buckets = {}
    for r in m1_rows:
        t = r["open_time"]
        key = (t // M3_MS) * M3_MS
        b = buckets.get(key)
        if b is None:
            b = buckets[key] = {"open_time": key, "close_time": key + M3_MS - 1,
                                "open": r["open"], "high": r["high"], "low": r["low"],
                                "close": r["close"], "volume": 0.0}
        b["high"] = max(b["high"], r["high"])
        b["low"] = min(b["low"], r["low"])
        b["close"] = r["close"]
        b["volume"] += r["volume"]
    return [buckets[k] for k in sorted(buckets)]


def fetch_okx_klines(symbol, interval, start_ms, end_ms, bar="5m"):
    """OKX public candles; interval seconds mapping. Returns normalized rows."""
    import urllib.request
    import json as _json
    bar_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1H": "1H"}
    okx_bar = bar_map.get(bar, "5m")
    step_ms = 60_000 if okx_bar == "1m" else 300_000
    out = []
    after = end_ms  # OKX returns rows with ts < after when using "after"
    cursor = after
    while cursor > start_ms:
        params = f"?instId={okx_symbol(symbol)}&bar={okx_bar}&limit=300&after={cursor}"
        url = f"https://www.okx.com/api/v5/market/history-candles{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "scalperagent-v4"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = _json.loads(resp.read().decode())
        except Exception:
            break
        data = payload.get("data") or []
        if not data:
            break
        for item in data:
            ts = int(item[0])
            if ts < start_ms:
                continue
            try:
                o, h, l, c = (float(item[1]), float(item[2]), float(item[3]), float(item[4]))
                vol = float(item[5])
            except (TypeError, ValueError):
                continue
            out.append({"open_time": ts, "close_time": ts + step_ms - 1,
                        "open": o, "high": h, "low": l, "close": c, "volume": vol,
                        "quote_volume": None})
        cursor = int(data[-1][0])
        if len(data) < 300:
            break
        time.sleep(0.15)
    return [r for r in out if r["open_time"] < end_ms]


def pg_connect():
    return psycopg.connect(PG_DSN)


def upsert_candles(conn, symbol, timeframe, rows):
    rows = [r for r in rows if r.get("volume") is not None]
    if not rows:
        return 0
    rows = sorted({r["open_time"]: r for r in rows}.values(), key=lambda r: r["open_time"])
    now = time.time()
    params = [(symbol, timeframe, r["open_time"], r["close_time"],
               r["open"], r["high"], r["low"], r["close"],
               r["volume"], r.get("quote_volume"), now) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO historical_candles (symbol,timeframe,open_time,close_time,open,high,low,close,volume,quote_volume,fetched_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (symbol,timeframe,open_time) DO UPDATE SET high=EXCLUDED.high, low=EXCLUDED.low, "
            "close=EXCLUDED.close, volume=EXCLUDED.volume, quote_volume=EXCLUDED.quote_volume, fetched_at=EXCLUDED.fetched_at",
            params)
    conn.commit()
    return len(rows)


def load_candles(conn, symbol, timeframe, start_ms, end_ms):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT open_time, close_time, open, high, low, close, volume FROM historical_candles "
            "WHERE symbol=%s AND timeframe=%s AND open_time >= %s AND open_time <= %s ORDER BY open_time",
            (symbol, timeframe, start_ms, end_ms))
        return [{"open_time": r[0], "close_time": r[1], "open": r[2], "high": r[3],
                 "low": r[4], "close": r[5], "volume": r[6]} for r in cur.fetchall()]


def load_m3_from_m1(conn, symbol, start_ms, end_ms):
    """3m candles aggregated from stored 1m rows (keeps M3 aligned with M1)."""
    return build_m3_from_m1(load_candles(conn, symbol, "1m", start_ms, end_ms))


def upsert_candles_m3(conn, symbol, m3_rows):
    """Persist aggregated M3 rows under the explicit ``3m`` timeframe."""
    rows = [r for r in m3_rows if r.get("volume") is not None]
    if not rows:
        return 0
    rows = sorted({r["open_time"]: r for r in rows}.values(), key=lambda r: r["open_time"])
    now = time.time()
    params = [(symbol, "3m", r["open_time"], r["close_time"],
               r["open"], r["high"], r["low"], r["close"],
               r["volume"], None, now) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO historical_candles (symbol,timeframe,open_time,close_time,open,high,low,close,volume,quote_volume,fetched_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (symbol,timeframe,open_time) DO UPDATE SET high=EXCLUDED.high, low=EXCLUDED.low, "
            "close=EXCLUDED.close, volume=EXCLUDED.volume, fetched_at=EXCLUDED.fetched_at",
            params)
    conn.commit()
    return len(rows)


async def fetch_window(symbol, timeframe, start_ms, end_ms, day_backs=None):
    """Fetch from Binance TR; if history is short, extend backwards from OKX."""
    day_backs = day_backs or max(2, math.ceil((end_ms - start_ms) / 86_400_000) + 1)
    raw = await historical_klines(symbol, timeframe, day_backs, end_ms)
    rows = normalize_binance(raw)
    rows = [r for r in rows if start_ms <= r["open_time"] <= end_ms]
    if not rows:
        return []
    have_from = rows[0]["open_time"]
    if have_from - start_ms > 5 * 60_000:
        missing = fetch_okx_klines(symbol, timeframe, start_ms, have_from, bar=timeframe)
        rows = sorted(missing + rows, key=lambda r: r["open_time"])
    return rows


def sync_symbol(conn, symbol, timeframe, start_ms, end_ms):
    """Fetch + upsert; returns row count for the window."""
    raw_rows = asyncio.get_event_loop().run_until_complete(
        fetch_window(symbol, timeframe, start_ms, end_ms))
    upsert_candles(conn, symbol, timeframe, raw_rows)
    return len(raw_rows)
