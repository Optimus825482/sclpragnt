"""Mum önbelleği (2026-10-17, çevrimdışı araştırma): `historical_candles` 21 günlük retention ile budanıyor
(`app/main.py::retention_loop`, 6 saatte bir) — 09-26'dan eski mumlar yok. Bu betik bildirim araştırması için gereken mumları
DB'den (var olan kısım) + Binance genel kline API'sinden (eksik kısım) `work/confirm_elems/cache/` altına .npy olarak yazar.
DB'ye YAZMAZ (budama zaten silerdi); canlı koda bağlanmaz.

Kolonlar: 0 open_time(ms) 1 open 2 high 3 low 4 close 5 volume(base) 6 quote_volume 7 taker_buy_quote_volume.

Kullanım (backend/): DATABASE_URL=... python scripts/confirm_elems_cache.py --from 2026-09-14 [--symbols A,B]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.fast_backfill_klines import WeightGate, fetch_page, pages  # noqa: E402

TF_MS = {"1m": 60_000, "5m": 300_000}
CACHE = ROOT / "work" / "confirm_elems" / "cache"


def merge_rows(*arrs: np.ndarray) -> np.ndarray:
    """open_time'a göre tekilleştirir (sonraki dizi kazanır) ve sıralar."""
    parts = [a for a in arrs if a is not None and len(a)]
    if not parts:
        return np.zeros((0, 8))
    cat = np.concatenate(parts, axis=0)
    # sonraki kazanır: ters çevir, ilk görüleni al
    cat = cat[::-1]
    _, idx = np.unique(cat[:, 0], return_index=True)
    out = cat[idx]
    return out[np.argsort(out[:, 0], kind="stable")]


def klines_to_rows(kl: list) -> np.ndarray:
    return np.array([[float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[7]), float(k[10])]
                     for k in kl], dtype=float).reshape(-1, 8)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="date_from", default="2026-09-14")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--max-weight", type=int, default=4000)
    args = ap.parse_args(argv)
    import psycopg
    import requests
    url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(url, connect_timeout=10)
    CACHE.mkdir(parents=True, exist_ok=True)
    start_ms = int(datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    if args.symbols:
        universe = sorted({s.strip().upper() for s in args.symbols.split(",") if s.strip()})
    else:
        universe = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='5m' ORDER BY 1").fetchall()]
    print("sembol:", len(universe), flush=True)
    # 1) DB'den var olanı al
    db_rows: dict[tuple[str, str], np.ndarray] = {}
    t0 = time.time()
    for j, sym in enumerate(universe):
        for tf in TF_MS:
            rows = conn.execute(
                "SELECT open_time, open, high, low, close, volume, quote_volume, COALESCE(taker_buy_quote_volume, 'NaN'::float8) "
                "FROM historical_candles WHERE symbol=%s AND timeframe=%s AND open_time >= %s ORDER BY open_time",
                (sym, tf, start_ms)).fetchall()
            db_rows[(sym, tf)] = np.array(rows, dtype=float).reshape(-1, 8)
        if (j + 1) % 50 == 0:
            print("[db] %d/%d, %.0f sn" % (j + 1, len(universe), time.time() - t0), flush=True)
    # 2) eksik baş kısmı Binance'ten çek
    now_ms = int(time.time() * 1000)
    jobs = []
    for sym in universe:
        for tf, bar in TF_MS.items():
            a = db_rows[(sym, tf)]
            first = int(a[0, 0]) if len(a) else (now_ms // bar) * bar
            if first - bar >= start_ms:
                for pa, pb in pages(start_ms, first - bar, bar):
                    jobs.append((sym, tf, pa, pb))
    print("[fetch] sayfa:", len(jobs), flush=True)
    gate = WeightGate(args.max_weight)
    local = threading.local()
    got: dict[tuple[str, str], list] = {}
    invalid = set()
    failed = [0]
    lock = threading.Lock()
    done = [0]

    def work(job):
        sym, tf, a, b = job
        if sym in invalid:
            return
        if not hasattr(local, "s"):
            local.s = requests.Session()
        try:
            kl = fetch_page(local.s, gate, sym, tf, a, b)
        except Exception:
            with lock:
                failed[0] += 1
            return
        with lock:
            if kl is None:
                invalid.add(sym)
            else:
                kl = [k for k in kl if a <= int(k[0]) <= b]
                got.setdefault((sym, tf), []).append(klines_to_rows(kl))
            done[0] += 1
            if done[0] % 500 == 0:
                print("[fetch] %d/%d, %.0f sn" % (done[0], len(jobs), time.time() - t0), flush=True)

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, jobs))
    print("[fetch] bitti, hatalı sayfa %d, geçersiz %s" % (failed[0], sorted(invalid)), flush=True)
    # 3) birleştir + yaz
    for (sym, tf), a in db_rows.items():
        m = merge_rows(a, *got.get((sym, tf), []))
        if tf == "1m":
            m = m[:, :6]                      # 1m'de quote/taker kolonları gerekmiyor
        np.save(CACHE / ("%s_%s.npy" % (sym, tf)), m)
    print("önbellek yazıldı:", CACHE, "süre %.1f dk" % ((time.time() - t0) / 60), flush=True)
    return 0 if failed[0] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
