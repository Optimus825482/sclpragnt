"""Vadeli ve derinlik arşivi — Binance Data Vision + fapi (ücretsiz, anahtarsız) → yerel DB (2026-10-22, kullanıcı onayı).

Kaynaklar (hepsi doğrulandı):
  * data.binance.vision/data/futures/um/daily/metrics/<PERP>/<PERP>-metrics-<gün>.zip  — 5 dk: açık pozisyon (coin, USDT),
    top trader long/short (hesap, pozisyon), global long/short (hesap), taker alım/satım hacim oranı.
  * data.binance.vision/data/futures/um/daily/bookDepth/<PERP>/<PERP>-bookDepth-<gün>.zip — ~30 sn: orta fiyata göre
    ±1…±5 % bantlarda birikmiş derinlik (coin) ve nominal (USDT). 15 dakikaya indirgenir (her 15 dk sınırındaki ilk anlık görüntü).
  * fapi.binance.com/fapi/v1/fundingRate — 8 saatlik fonlama geçmişi (sınırsız).

Eşleme: TRY çifti → USDT perp (BASE+USDT, yoksa 1000BASE+USDT; backend/work/perp_symbols.json). Tablolar `symbol` olarak
TRY çiftini taşır (arşivle birleştirmek için), `fut_symbol` perp adı.

Tablolar (CREATE IF NOT EXISTS): futures_metrics, futures_book_depth, futures_funding, futures_fetch_progress (devam/atlama).
KULLANIM (backend/): python scripts/fetch_futures_data.py --metrics-days 90 --depth-days 30 --workers 8
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import io
import json
import os
import sys
import threading
import time
import zipfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

VISION = "https://data.binance.vision/data/futures/um/daily"
FAPI = "https://fapi.binance.com"
UTC = dt.timezone.utc
DDL = [
    """CREATE TABLE IF NOT EXISTS futures_metrics (
        symbol TEXT NOT NULL, fut_symbol TEXT NOT NULL, ts BIGINT NOT NULL,
        oi DOUBLE PRECISION, oi_value DOUBLE PRECISION, top_ls_acc DOUBLE PRECISION, top_ls_pos DOUBLE PRECISION,
        ls_acc DOUBLE PRECISION, taker_ls DOUBLE PRECISION, PRIMARY KEY (symbol, ts))""",
    """CREATE TABLE IF NOT EXISTS futures_book_depth (
        symbol TEXT NOT NULL, fut_symbol TEXT NOT NULL, ts BIGINT NOT NULL, pct SMALLINT NOT NULL,
        depth DOUBLE PRECISION, notional DOUBLE PRECISION, PRIMARY KEY (symbol, ts, pct))""",
    """CREATE TABLE IF NOT EXISTS futures_funding (
        symbol TEXT NOT NULL, fut_symbol TEXT NOT NULL, ts BIGINT NOT NULL, rate DOUBLE PRECISION, mark_price DOUBLE PRECISION,
        PRIMARY KEY (symbol, ts))""",
    """CREATE TABLE IF NOT EXISTS futures_fetch_progress (
        kind TEXT NOT NULL, symbol TEXT NOT NULL, day TEXT NOT NULL, rows INTEGER, status TEXT, PRIMARY KEY (kind, symbol, day))""",
    "CREATE INDEX IF NOT EXISTS ix_futures_metrics_ts ON futures_metrics (ts)",
    "CREATE INDEX IF NOT EXISTS ix_futures_book_depth_ts ON futures_book_depth (ts)",
]
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, file=sys.stderr, flush=True)


def connect():
    import psycopg
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL gerekli (.env)")
    return psycopg.connect(url, connect_timeout=10)


def ensure_tables() -> None:
    with connect() as conn:
        for sql in DDL:
            conn.execute(sql)
        conn.commit()


def done_set(kind: str) -> set[tuple[str, str]]:
    with connect() as conn:
        rows = conn.execute("SELECT symbol, day FROM futures_fetch_progress WHERE kind=%s AND status IN ('ok','missing')", (kind,)).fetchall()
    return {(r[0], r[1]) for r in rows}


def mark(conn, kind: str, symbol: str, day: str, rows: int, status: str) -> None:
    conn.execute("INSERT INTO futures_fetch_progress (kind, symbol, day, rows, status) VALUES (%s,%s,%s,%s,%s) "
                 "ON CONFLICT (kind, symbol, day) DO UPDATE SET rows=EXCLUDED.rows, status=EXCLUDED.status", (kind, symbol, day, rows, status))


def perp_map() -> dict[str, str]:
    p = os.path.join(ROOT, "work", "perp_symbols.json")
    m = json.load(open(p, encoding="utf-8"))
    out = {s: s[:-3] + "USDT" for s in m["direct"]}
    out.update({s: "1000" + s[:-3] + "USDT" for s in m["x1000"]})
    return out


def fetch_zip_csv(url: str, session: requests.Session) -> list[list[str]] | None:
    for attempt in range(4):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = z.namelist()[0]
                text = z.read(name).decode("utf-8", "replace")
            return list(csv.reader(io.StringIO(text)))
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                log(f"  HATA {url.rsplit('/', 1)[-1]}: {type(exc).__name__}")
                return []
            time.sleep(2 * (attempt + 1))
    return []


def parse_ts(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp() * 1000)


def do_metrics(sym: str, fut: str, day: str, session: requests.Session) -> tuple[int, str]:
    rows = fetch_zip_csv(f"{VISION}/metrics/{fut}/{fut}-metrics-{day}.zip", session)
    if rows is None:
        return 0, "missing"
    if not rows:
        return 0, "error"
    out = []
    for r in rows[1:]:
        try:
            out.append((sym, fut, parse_ts(r[0]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[6]), float(r[7])))
        except (ValueError, IndexError):
            continue
    with connect() as conn:
        conn.cursor().executemany(
            "INSERT INTO futures_metrics (symbol, fut_symbol, ts, oi, oi_value, top_ls_acc, top_ls_pos, ls_acc, taker_ls) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (symbol, ts) DO NOTHING", out)
        mark(conn, "metrics", sym, day, len(out), "ok")
        conn.commit()
    return len(out), "ok"


def do_depth(sym: str, fut: str, day: str, session: requests.Session, step_ms: int = 900_000) -> tuple[int, str]:
    rows = fetch_zip_csv(f"{VISION}/bookDepth/{fut}/{fut}-bookDepth-{day}.zip", session)
    if rows is None:
        return 0, "missing"
    if not rows:
        return 0, "error"
    # 15 dk'lık her kovanın İLK anlık görüntüsü (tüm bantlarıyla)
    out, keep_ts, cur_bucket = [], None, None
    for r in rows[1:]:
        try:
            ts = parse_ts(r[0]); pct = int(round(float(r[1]))); depth = float(r[2]); notional = float(r[3])
        except (ValueError, IndexError):
            continue
        bucket = ts // step_ms
        if bucket != cur_bucket:
            cur_bucket, keep_ts = bucket, ts
        if ts == keep_ts:
            out.append((sym, fut, ts, pct, depth, notional))
    with connect() as conn:
        conn.cursor().executemany(
            "INSERT INTO futures_book_depth (symbol, fut_symbol, ts, pct, depth, notional) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (symbol, ts, pct) DO NOTHING", out)
        mark(conn, "depth", sym, day, len(out), "ok")
        conn.commit()
    return len(out), "ok"


def do_funding(sym: str, fut: str, start_ms: int, session: requests.Session) -> tuple[int, str]:
    out, cursor = [], start_ms
    for _ in range(20):
        try:
            r = session.get(f"{FAPI}/fapi/v1/fundingRate", params={"symbol": fut, "startTime": cursor, "limit": 1000}, timeout=30)
            if r.status_code in (418, 429):
                time.sleep(float(r.headers.get("Retry-After", "10")))
                continue
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log(f"  HATA funding {fut}: {type(exc).__name__}")
            return 0, "error"
        if not data:
            break
        for d in data:
            try:
                out.append((sym, fut, int(d["fundingTime"]), float(d["fundingRate"]), float(d.get("markPrice") or 0) or None))
            except (ValueError, KeyError, TypeError):
                continue
        if len(data) < 1000:
            break
        cursor = int(data[-1]["fundingTime"]) + 1
    with connect() as conn:
        conn.cursor().executemany(
            "INSERT INTO futures_funding (symbol, fut_symbol, ts, rate, mark_price) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (symbol, ts) DO NOTHING", out)
        mark(conn, "funding", sym, "all", len(out), "ok")
        conn.commit()
    return len(out), "ok"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics-days", type=int, default=90)
    ap.add_argument("--depth-days", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip", default="", help="virgüllü: metrics,depth,funding")
    args = ap.parse_args(argv)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    ensure_tables()
    pm = perp_map()
    today = dt.datetime.now(UTC).date()
    days_m = [(today - dt.timedelta(days=i)).isoformat() for i in range(1, args.metrics_days + 1)]
    days_d = [(today - dt.timedelta(days=i)).isoformat() for i in range(1, args.depth_days + 1)]
    session_local = threading.local()

    def sess() -> requests.Session:
        s = getattr(session_local, "s", None)
        if s is None:
            s = requests.Session(); s.headers["User-Agent"] = "scalper-research/1.0"; session_local.s = s
        return s

    def run_kind(kind: str, days: list[str], fn) -> None:
        if kind in skip:
            return
        done = done_set(kind)
        jobs = [(sym, fut, day) for sym, fut in pm.items() for day in days if (sym, day) not in done]
        log(f"[{kind}] {len(jobs)} iş ({len(pm)} sembol × {len(days)} gün, {len(done)} atlandı)")
        t0, n_ok, n_rows, n_miss = time.time(), 0, 0, 0
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fn, sym, fut, day, sess()): (sym, day) for sym, fut, day in jobs}
            for i, f in enumerate(cf.as_completed(futs), 1):
                try:
                    rows, status = f.result()
                except Exception as exc:  # noqa: BLE001
                    rows, status = 0, f"error:{type(exc).__name__}"
                if status == "missing":
                    n_miss += 1
                    sym, day = futs[f]
                    with connect() as conn:
                        mark(conn, kind, sym, day, 0, "missing"); conn.commit()
                elif status == "ok":
                    n_ok += 1; n_rows += rows
                if i % 500 == 0 or i == len(jobs):
                    rate = i / max(1e-9, time.time() - t0)
                    log(f"  [{kind}] {i}/{len(jobs)} · ok {n_ok} · yok {n_miss} · satır {n_rows:,} · {rate:.1f}/sn · kalan ~{(len(jobs) - i) / max(rate, 1e-9) / 60:.0f} dk")

    run_kind("metrics", days_m, do_metrics)
    if "funding" not in skip:
        done = done_set("funding")
        start_ms = int((dt.datetime.now(UTC) - dt.timedelta(days=args.metrics_days + 2)).timestamp() * 1000)
        jobs = [(sym, fut) for sym, fut in pm.items() if (sym, "all") not in done]
        log(f"[funding] {len(jobs)} sembol")
        for i, (sym, fut) in enumerate(jobs, 1):
            do_funding(sym, fut, start_ms, sess())
            time.sleep(0.15)
            if i % 50 == 0 or i == len(jobs):
                log(f"  [funding] {i}/{len(jobs)}")
    run_kind("depth", days_d, do_depth)
    with connect() as conn:
        for t in ("futures_metrics", "futures_book_depth", "futures_funding"):
            r = conn.execute(f"SELECT COUNT(DISTINCT symbol), COUNT(*), MIN(ts), MAX(ts) FROM {t}").fetchone()
            f = lambda ms: dt.datetime.fromtimestamp(int(ms) / 1000, UTC).strftime("%d.%m.%Y %H:%M") if ms else "—"
            log(f"{t}: sembol {r[0]} satır {r[1]:,} | {f(r[2])} → {f(r[3])} UTC")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
