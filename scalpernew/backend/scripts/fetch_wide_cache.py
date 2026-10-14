"""GENİŞ-PENCERE VERİ ÇEKİCİ (2026-10-12) — USD lead-lag yeniden testi için.

AMAÇ: Mevcut `channel_cache.json` yalnız ~6 günlük. Yedi turun "gerçek sinyal /
kararsız" yargıları bu dar pencereye dayanıyor. Bu araç TR+Global 5m veriyi
60+ güne çıkarır ki USD lead-lag gerçekten test edilsin.

KAYNAKLAR:
  * TR (`api.binance.me`) 5m — REST, ~90 gün geriye (doğrulandı)
  * Global (`api.binance.com`) 5m — REST, çok uzun geçmiş
    (Not: aylık arşiv de var ama REST sayfalaması daha basit ve yeterli.)

ÇIKTI: `work/wide_cache.json` — {tr:{sym:{...}}, gl:{sym:{...}}, meta:{...}}
  (channel_cache ile AYNI şema → research_usd_leadlag doğrudan okur.)

LİKİDİTE: Yalnız likit semboller çekilir (24h hacme göre top-N) — illikit
semboller hem maliyet hem gürültü getirir; zaten karar likiditeye bağlı.

KULLANIM:
    python backend/scripts/fetch_wide_cache.py --days 60 --top 60
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_TR = "https://api.binance.me"
_GL = "https://api.binance.com"
_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "..", "work", "wide_cache.json")


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
        time.sleep(0.05)
    return out


def _bars(rows: list) -> dict:
    b = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [], "tb": []}
    for r in rows:
        try:
            b["t"].append(float(r[0]) / 1000.0); b["o"].append(float(r[1]))
            b["h"].append(float(r[2])); b["l"].append(float(r[3]))
            b["c"].append(float(r[4])); b["v"].append(float(r[5]))
            b["tb"].append(float(r[9]))
        except (IndexError, TypeError, ValueError):
            continue
    return b


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
    ap.add_argument("--out", default=_OUT)
    args = ap.parse_args()

    from app.binance_tr_public import ticker_24h, trading_symbols
    print("=== GENİŞ-PENCERE VERİ ÇEKİCİ ===")
    syms = asyncio.run(trading_symbols("TRY"))
    tk = asyncio.run(ticker_24h(syms))
    vol = {r["symbol"]: float(r.get("quoteVolume") or 0) for r in (tk or []) if r.get("symbol")}
    top = [s for s, _ in sorted(vol.items(), key=lambda x: -x[1]) if s != "USDTTRY"][:args.top]
    print(f"  likit evren: {len(top)} sembol (top-{args.top})")

    now = int(time.time() * 1000)
    start = now - args.days * 86400 * 1000
    gmap = _global_map()
    print(f"  global eşleşme: {len(gmap)} sembol")

    cache = {"tr": {}, "gl": {}, "global_map": gmap,
             "meta": {"days": args.days, "top": args.top, "built_at": time.time()}}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    for i, s in enumerate(top):
        try:
            tr = _fetch(_TR, s, "5m", start, now)
            cache["tr"][s] = _bars(tr)
        except Exception as exc:
            print(f"    TR {s}: {type(exc).__name__}", flush=True)
        base = s[:-3] if s.endswith("TRY") else s
        gsym = gmap.get(base)
        if gsym:
            try:
                gl = _fetch(_GL, gsym, "5m", start, now)
                cache["gl"][s] = _bars(gl)
            except Exception as exc:
                print(f"    GL {s}: {type(exc).__name__}", flush=True)
        if (i + 1) % 10 == 0:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            ntr = len(cache["tr"].get(s, {}).get("t", []))
            print(f"    ... {i+1}/{len(top)} (örnek bar {s}={ntr}, kaydedildi)", flush=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    print(f"  önbellek: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
