#!/usr/bin/env python3
"""
SQLite market_candles -> PostgreSQL historical_candles aktarimi.

Neden: Bazi gelistirme scriptleri gecici olarak SQLite'a yazdi. Uygulama
PostgreSQL (historical_candles) kullaniyor. Analiz oncesi bu verileri
PG'ye tasiyip tek kaynak haline getiriyoruz. Idempotent (ON CONFLICT).
"""

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# .env yukle
_env = os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", ".env")
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

import psycopg

SQLITE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", "scalper_db_v4.sqlite")
BATCH = 5000


def copy_timeframe(tf):
    src = sqlite3.connect(SQLITE)
    src.row_factory = sqlite3.Row
    pg = psycopg.connect(os.environ["DATABASE_URL"])
    cur_src = src.cursor()

    # mevcut PG durumu
    cur_pg = pg.cursor()
    cur_pg.execute("SELECT COUNT(*) FROM historical_candles WHERE timeframe=%s", (tf,))
    before = cur_pg.fetchone()[0]
    print(f"[{tf}] PG oncesi: {before} satir")

    cur_src.execute(
        "SELECT symbol, timeframe, open_time, close_time, open, high, low, close, volume, "
        "quote_volume, trade_count, source, fetched_at FROM market_candles WHERE timeframe=? ORDER BY open_time",
        (tf,),
    )
    rows = cur_src.fetchall()
    print(f"[{tf}] SQLite: {len(rows)} satir cekildi")

    sql = """INSERT INTO historical_candles
        (symbol,timeframe,open_time,close_time,open,high,low,close,volume,quote_volume,trade_count,source,fetched_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(symbol,timeframe,open_time) DO UPDATE SET
        close_time=EXCLUDED.close_time,open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,
        close=EXCLUDED.close,volume=EXCLUDED.volume,quote_volume=EXCLUDED.quote_volume,
        trade_count=EXCLUDED.trade_count,source=EXCLUDED.source,fetched_at=EXCLUDED.fetched_at"""

    batch = []
    total = 0
    t0 = time.time()
    for r in rows:
        batch.append((
            r["symbol"], r["timeframe"], int(r["open_time"]), int(r["close_time"]),
            float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
            float(r["volume"]),
            float(r["quote_volume"]) if r["quote_volume"] is not None else None,
            int(r["trade_count"]) if r["trade_count"] is not None else None,
            r["source"], float(r["fetched_at"]),
        ))
        if len(batch) >= BATCH:
            with pg.cursor() as c:
                c.executemany(sql, batch)
            pg.commit()
            total += len(batch)
            batch = []
    if batch:
        with pg.cursor() as c:
            c.executemany(sql, batch)
        pg.commit()
        total += len(batch)

    cur_pg.execute("SELECT COUNT(*) FROM historical_candles WHERE timeframe=%s", (tf,))
    after = cur_pg.fetchone()[0]
    print(f"[{tf}] Aktarildi: {total} | PG sonrasi: {after} | sure: {time.time()-t0:.1f}s")
    src.close()
    pg.close()


if __name__ == "__main__":
    for tf in ("5m", "1m"):
        copy_timeframe(tf)
    print("AKTARIM TAMAM.")