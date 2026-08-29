#!/usr/bin/env python3
"""
Adim 0-3: Pasifleri ele, aktif sembollerin M5/M1 verisini cek, %2+ yukselisleri tespit et.

1. ticker/24hr tek istekle tum ciftlerin 24s hacim + trade sayisini al
2. Aktiflik filtrele: dusuk quoteVolume veya 0 trade -> pasif, ele
3. Aktiflerin 6 saat M5 verisini cek -> market_candles
4. %2+ M5 yukselis tespiti (2 mum oncesi ile)
5. Yukselenlerin M1 verisini cek -> market_candles
"""

import asyncio
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.binance_tr_public import trading_symbols, ticker_24h, historical_klines

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scalper_db_v4.sqlite")

# Aktiflik esikleri (TRY spot piyasasi icin)
MIN_QUOTE_VOLUME_TRY = 250_000.0    # 24s TRY hacmi < 250K -> pasif
MIN_TRADE_COUNT = 50                # 24s trade sayisi < 50 -> pasif
RISE_PCT = 2.0
M5_HOURS = 6
M1_HOURS = 12


def get_db():
    return sqlite3.connect(DB_PATH)


def save_candles(conn, sym, tf, candles):
    cur = conn.cursor()
    ft = time.time()
    rows = 0
    for c in candles:
        try:
            ct = c[6] if len(c) > 6 else c[0] + 60000
            cur.execute("""
                INSERT OR REPLACE INTO market_candles
                (symbol, timeframe, open_time, close_time, open, high, low, close, volume, source, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (sym, tf, c[0], ct, float(c[1]), float(c[2]), float(c[3]), float(c[4]),
                  float(c[5]), "binance_tr_public", ft))
            rows += 1
        except Exception:
            pass
    conn.commit()
    return rows


async def filter_active_symbols():
    """Pasif sembolleri ele, aktif listeyi don."""
    print("\nADIM 0: Pasif/aktif filtreleme")
    print("=" * 60)
    syms = await trading_symbols("TRY")
    print(f"Toplam TRY sembol: {len(syms)}")

    # Tek istek ile tum piyasa ticker
    tickers = await ticker_24h()
    info = {}
    for t in tickers:
        s = str(t.get("symbol", "")).upper()
        if not s.endswith("TRY"):
            continue
        try:
            qv = float(t.get("quoteVolume") or 0)
            tc = int(t.get("count") or 0)
        except (TypeError, ValueError):
            qv, tc = 0.0, 0
        info[s] = {"quote_volume": qv, "trade_count": tc, "price_change_pct": float(t.get("priceChangePercent") or 0)}

    active, passive = [], []
    for s in syms:
        d = info.get(s, {"quote_volume": 0, "trade_count": 0})
        if d["quote_volume"] >= MIN_QUOTE_VOLUME_TRY and d["trade_count"] >= MIN_TRADE_COUNT:
            active.append(s)
        else:
            passive.append(s)

    print(f"Aktif: {len(active)} | Pasif/elem: {len(passive)}")
    print("Pasif ornekler (ilk 15):", passive[:15])

    with open(os.path.join(os.path.dirname(__file__), "..", "..", "active_symbols.json"), "w", encoding="utf-8") as f:
        json.dump({"active": active, "passive": passive, "filters": {
            "min_quote_volume_try": MIN_QUOTE_VOLUME_TRY, "min_trade_count": MIN_TRADE_COUNT}}, f, ensure_ascii=False, indent=1)
    return active


async def fetch_m5(conn, active_syms):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM market_candles WHERE timeframe='5m'")
    have = {r[0] for r in cur.fetchall()}
    todo = [s for s in active_syms if s not in have]
    print(f"\nM5: {len(active_syms)} aktif, {len(todo)} yeni")
    ok = 0
    for i, sym in enumerate(todo, 1):
        try:
            m5 = await historical_klines(sym, "5m", M5_HOURS)
            if m5:
                save_candles(conn, sym, "5m", m5)
                ok += 1
        except Exception:
            pass
        if i % 50 == 0 or i == len(todo):
            print(f"  M5 {i}/{len(todo)}")
            await asyncio.sleep(0.2)
    print(f"M5 tamam: {ok}")
    return ok


def detect_risers(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM market_candles WHERE timeframe='5m'")
    m5_syms = [r[0] for r in cur.fetchall()]
    risers = []
    for sym in m5_syms:
        cur.execute("""
            SELECT open_time, open, high, low, close, volume
            FROM market_candles WHERE symbol=? AND timeframe='5m'
            ORDER BY open_time ASC
        """, (sym,))
        candles = [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]
        for i in range(3, len(candles) - 1):
            prev_close = candles[i - 1]["c"]
            curr_close = candles[i]["c"]
            if not prev_close:
                continue
            rise = (curr_close - prev_close) / prev_close * 100
            if rise >= RISE_PCT:
                ctx_start = max(0, i - 2)
                ctx_end = min(len(candles), i + 3)
                risers.append({
                    "symbol": sym,
                    "rise_pct": round(rise, 2),
                    "rise_start_ms": candles[i]["ts"],
                    "rise_start_price": prev_close,
                    "peak_price": max(c["h"] for c in candles[ctx_start:ctx_end]),
                    "context": [
                        {"ts": c["ts"], "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c["v"]}
                        for c in candles[ctx_start:ctx_end]
                    ],
                })
    uniq = {r["symbol"] for r in risers}
    print(f"\n%2+ yukselis: {len(risers)} adet, {len(uniq)} benzersiz sembol")
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "m5_risers.json"), "w", encoding="utf-8") as f:
        json.dump(risers, f, ensure_ascii=False, indent=1, default=str)
    print("m5_risers.json kaydedildi")
    return risers


async def fetch_m1(conn, risers):
    syms = sorted({r["symbol"] for r in risers})
    print(f"\nM1: {len(syms)} yukselen sembol icin cekilecek")
    ok = 0
    for i, sym in enumerate(syms, 1):
        try:
            m1 = await historical_klines(sym, "1m", M1_HOURS)
            if m1:
                save_candles(conn, sym, "1m", m1)
                ok += 1
        except Exception:
            pass
        if i % 25 == 0 or i == len(syms):
            print(f"  M1 {i}/{len(syms)}")
            await asyncio.sleep(0.2)
    print(f"M1 tamam: {ok}")


async def main():
    conn = get_db()
    active = await filter_active_symbols()
    await fetch_m5(conn, active)
    risers = detect_risers(conn)
    await fetch_m1(conn, risers)
    conn.close()
    print("\nADIM 0-3 TAMAM.")


if __name__ == "__main__":
    asyncio.run(main())