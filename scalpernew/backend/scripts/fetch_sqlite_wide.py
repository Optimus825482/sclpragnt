"""GENİŞ-PENCERE VERİ ÇEKİCİ → SQLITE (2026-10-12).

Kullanıcı kararı: JSON cache yerine doğrudan `work/market_cache.sqlite` kullan.
Mevcut `klines` tablosu (symbol, interval, open_time, open, high, low, close,
volume, quote_volume) hem TR hem Global'i tutabilir: Global'i `XUSDT` sembolüyle
yazarız (TR `XTRY` ile çakışmaz).

Amaç: TR+Global 5m veriyi ~60 güne çıkarıp USD lead-lag'i (dar 6 günlük pencere
yerine) gerçekten test etmek.

KULLANIM:
    python backend/scripts/fetch_sqlite_wide.py --days 60 --top 60
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_TR = "https://api.binance.me"
_GL = "https://api.binance.com"
_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "..", "work", "market_cache.sqlite")


def _get(url: str, timeout: int = 30):
    import json as _j
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return _j.loads(r.read().decode())


def _fetch(base: str, symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    out, cursor = [], start_ms
    while cursor < end_ms:
        url = (f"{base}/api/v3/klines?symbol={symbol}&interval={interval}"
               f"&startTime={cursor}&endTime={end_ms}&limit=1000")
        try:
            batch = _get(url)
        except Exception:
            break
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1][0]) + 1
        time.sleep(0.04)
    return out


def _rows_to_records(sym: str, rows: list) -> list[tuple]:
    recs = []
    for r in rows:
        try:
            recs.append((sym, "5m", int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                         float(r[4]), float(r[5]), float(r[7])))
        except (IndexError, TypeError, ValueError):
            continue
    return recs


def _write(conn: sqlite3.Connection, recs: list[tuple]) -> int:
    if not recs:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO klines"
        "(symbol, interval, open_time, open, high, low, close, volume, quote_volume) "
        "VALUES(?,?,?,?,?,?,?,?,?)", recs)
    conn.commit()
    return len(recs)


def _global_map() -> dict:
    try:
        data = _get(f"{_GL}/api/v3/exchangeInfo")
    except Exception:
        return {}
    m = {}
    for s in data.get("symbols", []):
        sym = s.get("symbol", "")
        if sym.endswith("USDT") and s.get("status") == "TRADING":
            m[sym[:-4]] = sym
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--db", default=_DB)
    args = ap.parse_args()

    from app.binance_tr_public import ticker_24h, trading_symbols
    print("=== SQLITE GENİŞ-PENCERE ÇEKİCİ ===")
    conn = sqlite3.connect(args.db)
    conn.execute("CREATE TABLE IF NOT EXISTS klines("
                 "symbol TEXT, interval TEXT, open_time INTEGER, open REAL, high REAL, "
                 "low REAL, close REAL, volume REAL, quote_volume REAL)")
    syms = asyncio.run(trading_symbols("TRY"))
    tk = asyncio.run(ticker_24h(syms))
    vol = {r["symbol"]: float(r.get("quoteVolume") or 0) for r in (tk or []) if r.get("symbol")}
    top = [s for s, _ in sorted(vol.items(), key=lambda x: -x[1]) if s != "USDTTRY"][:args.top]
    print(f"  likit evren: {len(top)}")

    now = int(time.time() * 1000)
    start = now - args.days * 86400 * 1000
    gmap = _global_map()
    print(f"  global eşleşme: {len(gmap)}")
    tot_tr = tot_gl = 0
    for i, s in enumerate(top):
        try:
            tr = _fetch(_TR, s, "5m", start, now)
            tot_tr += _write(conn, _rows_to_records(s, tr))
        except Exception as exc:
            print(f"    TR {s}: {type(exc).__name__}", flush=True)
        base = s[:-3] if s.endswith("TRY") else s
        gsym = gmap.get(base)
        if gsym:
            try:
                gl = _fetch(_GL, gsym, "5m", start, now)
                tot_gl += _write(conn, _rows_to_records(gsym, gl))   # Global'i XUSDT olarak yaz
            except Exception as exc:
                print(f"    GL {gsym}: {type(exc).__name__}", flush=True)
        if (i + 1) % 10 == 0:
            print(f"    ... {i+1}/{len(top)} (TR {tot_tr} GL {tot_gl} satır)", flush=True)
    conn.close()
    print(f"  BİTTİ: TR {tot_tr} | GL {tot_gl} satır")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
