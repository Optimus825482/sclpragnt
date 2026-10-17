"""Hızlı kline geri doldurma — sayfa düzeyinde paralel (2026-10-17).

`backfill_historical_candles.py` her sembolün sayfalarını SIRAYLA çeker (`historical_klines` sayfalama
döngüsü); 1m × 90 gün × ~300 sembol için bu ~3+ saat sürüyordu (istek başı ~0,4 sn, ağırlık kullanımı
limitin %2'si). Bu betik pencereyi 1000 barlık sayfalara böler ve tüm sembollerin sayfalarını ortak
bir iş parçacığı havuzunda çeker; yazım aynı tabloya, aynı satır şemasıyla (`kline_to_row`, taker
kolonları dahil) ve aynı çakışma kuralıyla (`_INSERT_SQL`: yalnız boş taker alanları doldurulur).

Hız sınırı: Binance `x-mbx-used-weight-1m` başlığı izlenir; `--max-weight` (varsayılan 4000/dk, limit
6000) üstünde tüm işçiler dakika sonuna kadar bekler. 429/418'de `Retry-After` kadar beklenir.

Kullanım (backend/):
  DATABASE_URL=... python scripts/fast_backfill_klines.py --days 90 --timeframe 1m --workers 12
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys
import threading
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.backfill_historical_candles import TF_MS, insert_rows, kline_to_row, window_start_ms  # noqa: E402

URL = "https://api.binance.me/api/v3/klines"


class WeightGate:
    """Paylaşılan ağırlık kapısı: son görülen dakika ağırlığı eşiği aşınca herkes bekler."""

    def __init__(self, max_weight: int):
        self.max_weight = max_weight
        self.lock = threading.Lock()
        self.pause_until = 0.0

    def wait(self) -> None:
        while True:
            with self.lock:
                delay = self.pause_until - time.time()
            if delay <= 0:
                return
            time.sleep(min(delay, 5.0))

    def observe(self, used: int | None, retry_after: float | None = None) -> None:
        with self.lock:
            if retry_after:
                self.pause_until = max(self.pause_until, time.time() + retry_after)
            elif used is not None and used >= self.max_weight:
                # dakika sınırına kadar bekle (+1 sn pay)
                self.pause_until = max(self.pause_until, (time.time() // 60 + 1) * 60 + 1)


def pages(start_ms: int, last_bar_ms: int, bar_ms: int) -> list[tuple[int, int]]:
    """[start, last] aralığını en çok 1000 barlık (başlangıç, bitiş) sayfalarına böler."""
    out = []
    a = start_ms
    while a <= last_bar_ms:
        b = min(last_bar_ms, a + 999 * bar_ms)
        out.append((a, b))
        a = b + bar_ms
    return out


def fetch_page(session: requests.Session, gate: WeightGate, symbol: str, tf: str, a: int, b: int) -> list | None:
    for attempt in range(8):
        gate.wait()
        try:
            r = session.get(URL, params={"symbol": symbol, "interval": tf, "limit": 1000,
                                          "startTime": a, "endTime": b + TF_MS[tf] - 1}, timeout=20)
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
            continue
        used = r.headers.get("x-mbx-used-weight-1m")
        if r.status_code in (418, 429):
            gate.observe(None, float(r.headers.get("Retry-After") or 30))
            continue
        gate.observe(int(used) if used and used.isdigit() else None)
        if r.status_code == 400:
            return None  # geçersiz/delist sembol
        if r.status_code != 200:
            time.sleep(1.5 * (attempt + 1))
            continue
        try:
            return r.json()
        except ValueError:
            time.sleep(1.0)
    raise RuntimeError(f"{symbol} {tf} sayfa {a} çekilemedi")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--timeframe", default="1m", choices=sorted(TF_MS))
    ap.add_argument("--symbols", default="")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--max-weight", type=int, default=4000)
    ap.add_argument("--source", default="backfill")
    args = ap.parse_args(argv)
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL gerekli", file=sys.stderr)
        return 2
    import psycopg
    tf = args.timeframe
    bar_ms = TF_MS[tf]
    now_ms = int(time.time() * 1000)
    start_ms = window_start_ms(args.days)
    last_bar_ms = (now_ms // bar_ms) * bar_ms - bar_ms
    if args.symbols:
        universe = sorted({s.strip().upper() for s in args.symbols.split(",") if s.strip()})
    else:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            universe = [r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='5m' ORDER BY 1").fetchall()]
    jobs = [(s, a, b) for s in universe for a, b in pages(start_ms, last_bar_ms, bar_ms)]
    print(f"[fast] {tf} {args.days} gün, {len(universe)} sembol, {len(jobs):,} sayfa, {args.workers} işçi", flush=True)
    gate = WeightGate(args.max_weight)
    local = threading.local()
    stats = {"pages": 0, "rows": 0, "written": 0, "invalid": set(), "failed": 0}
    lock = threading.Lock()
    t0 = time.time()

    def work(job):
        sym, a, b = job
        if sym in stats["invalid"]:
            return
        if not hasattr(local, "s"):
            local.s = requests.Session()
        try:
            kl = fetch_page(local.s, gate, sym, tf, a, b)
        except Exception:
            with lock:
                stats["failed"] += 1
            return
        if kl is None:
            with lock:
                stats["invalid"].add(sym)
            return
        fetched_at = time.time()
        now2 = int(fetched_at * 1000)
        rows = [r for r in (kline_to_row(sym, tf, k, args.source, fetched_at, now2) for k in kl)
                if r is not None and a <= r[2] <= b]
        written = insert_rows(db_url, rows)
        with lock:
            stats["pages"] += 1
            stats["rows"] += len(rows)
            stats["written"] += written
            if stats["pages"] % 500 == 0:
                el = time.time() - t0
                rate = stats["pages"] / el if el else 0
                eta = (len(jobs) - stats["pages"]) / rate / 60 if rate else 0
                print(f"[fast] {stats['pages']:,}/{len(jobs):,} sayfa · satır {stats['rows']:,} · yazılan {stats['written']:,} "
                      f"· {rate:.1f} sayfa/sn · kalan ~{eta:.0f} dk", flush=True)

    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        list(ex.map(work, jobs))
    print(f"[fast] BİTTİ {tf}: sayfa {stats['pages']:,}, satır {stats['rows']:,}, yazılan/doldurulan {stats['written']:,}, "
          f"hatalı sayfa {stats['failed']}, geçersiz {sorted(stats['invalid'])}, süre {(time.time() - t0) / 60:.1f} dk", flush=True)
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
