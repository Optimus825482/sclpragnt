"""Tarihsel işlem akışı (aggTrades) geri doldurma — dakikalık mikro-yapı (2026-10-17).

Binance TR'nin TRY marketleri Binance global TRY marketleriyle aynıdır (aynı aggTrade id/fiyat/zaman);
`data.binance.vision` aggTrades arşivi bu yüzden Binance TR'nin kendi işlem geçmişidir. Betik her
(sembol, gün) için günlük zip'i indirir, `.CHECKSUM` (sha256) ile doğrular, CSV'yi numpy ile ayrıştırıp
1 dakikalık satırlara toplar ve `historical_trade_flow` tablosuna (migration 023) upsert eder.

  - Evren: Binance TR exchangeInfo'daki TRY semboller (status TRADING).
  - Pencere: son `--days` gün (UTC günleri) → dünün sonuna kadar arşivden. Bugünün (ve arşive henüz
    düşmemiş son günlerin) kuyruğu Binance TR REST aggTrades'ten (fromId sayfalama) tamamlanır;
    bugünkü kısmi dakika yazılmaz (kapanmış dakikalar), sonraki koşuda arşivden üstüne yazılır.
  - 404 = o gün o sembolde işlem yok (eski günlerde); loglanır, checkpoint'e `404` olarak işlenir.
  - Devam edilebilir: `work/tradeflow/checkpoint.tsv` (sembol, gün, durum) — biten çiftler atlanır.
  - Bellek: her dosya akış hâlinde işlenir (indir → ayrıştır → topla → yaz → at); tepe RAM ~ işçi sayısı
    × en büyük dosya (onlarca MB).

Birim: buy = agresif alıcı (is_buyer_maker = False), sell = agresif satıcı (True). big ≥ 10.000 TRY ve
whale ≥ 50.000 TRY işlem başına quote tutarıdır; kademeler iç içedir (whale işlemi big'e de dahildir).
Zaman damgası 2026 dosyalarında µs (16 hane); büyüklüğe göre ms/µs ayrılır.

Kullanım (backend/):
  DATABASE_URL=... python scripts/backfill_trade_flow.py --days 90 --workers 16
  # günlük cron (dün arşivden + bugünün kuyruğu REST'ten; biten günler checkpoint'le atlanır):
  DATABASE_URL=... python scripts/backfill_trade_flow.py --days 3
  # yalnız rapor:
  DATABASE_URL=... python scripts/backfill_trade_flow.py --report-only
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import io
import json
import os
import queue
import sys
import threading
import time
import zipfile
from collections.abc import Iterable

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.fast_backfill_klines import WeightGate  # noqa: E402

ARCHIVE = "https://data.binance.vision/data/spot/daily/aggTrades"
REST_AGG = "https://api.binance.me/api/v3/aggTrades"
REST_INFO = "https://api.binance.me/api/v3/exchangeInfo"
BIG_QUOTE = 10_000.0
WHALE_QUOTE = 50_000.0
MINUTE_MS = 60_000
WORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "tradeflow")
CKPT_PATH = os.path.join(WORK_DIR, "checkpoint.tsv")
STATS_PATH = os.path.join(WORK_DIR, "run_stats.json")
REPORT_PATH = os.path.join(WORK_DIR, "report.md")
VALIDATION_PATH = os.path.join(WORK_DIR, "validation.md")

COLUMNS = (
    "symbol", "minute_open_ms", "n_trades", "buy_base", "sell_base", "buy_quote", "sell_quote", "vwap",
    "max_trade_quote", "big_buy_quote", "big_sell_quote", "big_buy_n", "big_sell_n",
    "whale_buy_quote", "whale_sell_quote", "first_agg_id", "last_agg_id",
)
_CSV_DTYPE = np.dtype([("id", "i8"), ("p", "f8"), ("q", "f8"), ("t", "i8"), ("m", "S5")])


# ───────────────────────── saf yardımcılar (test edilir) ─────────────────────────

def to_ms(t: np.ndarray) -> np.ndarray:
    """Zaman damgasını ms'ye çevir: ≥ 1e14 ise µs (16 hane), değilse ms (13 hane). Dizi bazında karar."""
    t = np.asarray(t, dtype=np.int64)
    return np.where(t >= 10 ** 14, t // 1000, t)


def parse_agg_csv(data: bytes) -> dict[str, np.ndarray]:
    """aggTrades CSV baytlarını ayrıştır → id, price, qty, t_ms, is_sell dizileri.

    Kolonlar: aggTradeId, price, quantity, firstTradeId, lastTradeId, transact_time, is_buyer_maker,
    is_best_match. Başlık satırı (eski dosyalar) varsa atlanır. is_buyer_maker=True → SATIŞ agresörü.
    """
    empty = {"id": np.zeros(0, "i8"), "price": np.zeros(0), "qty": np.zeros(0),
             "t_ms": np.zeros(0, "i8"), "is_sell": np.zeros(0, bool)}
    if not data or not data.strip():
        return empty
    skip = 0
    first = data[:64].lstrip()[:1]
    if first and not first.isdigit():
        skip = 1
    arr = np.loadtxt(io.BytesIO(data), delimiter=",", usecols=(0, 1, 2, 5, 6), dtype=_CSV_DTYPE, skiprows=skip, ndmin=1)
    if arr.size == 0:
        return empty
    return {
        "id": arr["id"], "price": arr["p"], "qty": arr["q"], "t_ms": to_ms(arr["t"]),
        "is_sell": (arr["m"] == b"True") | (arr["m"] == b"true"),
    }


def aggregate_minutes(ids, price, qty, t_ms, is_sell, big: float = BIG_QUOTE, whale: float = WHALE_QUOTE) -> dict[str, np.ndarray]:
    """İşlemleri 1 dakikalık gruplara topla (yalnız işlem olan dakikalar). Girdi sırası önemsiz."""
    ids = np.asarray(ids, dtype=np.int64)
    price = np.asarray(price, dtype=np.float64)
    qty = np.asarray(qty, dtype=np.float64)
    t_ms = np.asarray(t_ms, dtype=np.int64)
    is_sell = np.asarray(is_sell, dtype=bool)
    if ids.size == 0:
        return {c: np.zeros(0) for c in COLUMNS if c != "symbol"}
    minute = (t_ms // MINUTE_MS) * MINUTE_MS
    order = np.argsort(minute, kind="stable")
    minute, ids, price, qty, is_sell = minute[order], ids[order], price[order], qty[order], is_sell[order]
    quote = price * qty
    starts = np.flatnonzero(np.concatenate(([True], minute[1:] != minute[:-1])))
    buy = ~is_sell
    is_big = quote >= big
    is_whale = quote >= whale

    def rsum(x):
        return np.add.reduceat(x, starts)

    n = np.diff(np.append(starts, minute.size))
    base_tot = rsum(qty)
    quote_tot = rsum(quote)
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = np.where(base_tot > 0, quote_tot / base_tot, np.nan)
    return {
        "minute_open_ms": minute[starts],
        "n_trades": n.astype(np.int64),
        "buy_base": rsum(qty * buy),
        "sell_base": rsum(qty * is_sell),
        "buy_quote": rsum(quote * buy),
        "sell_quote": rsum(quote * is_sell),
        "vwap": vwap,
        "max_trade_quote": np.maximum.reduceat(quote, starts),
        "big_buy_quote": rsum(quote * (is_big & buy)),
        "big_sell_quote": rsum(quote * (is_big & is_sell)),
        "big_buy_n": rsum((is_big & buy).astype(np.int64)),
        "big_sell_n": rsum((is_big & is_sell).astype(np.int64)),
        "whale_buy_quote": rsum(quote * (is_whale & buy)),
        "whale_sell_quote": rsum(quote * (is_whale & is_sell)),
        "first_agg_id": np.minimum.reduceat(ids, starts),
        "last_agg_id": np.maximum.reduceat(ids, starts),
    }


def rows_from_agg(symbol: str, agg: dict[str, np.ndarray]) -> list[tuple]:
    """Toplanmış dizileri DB satır demetlerine çevir (COLUMNS sırası; NaN vwap → None)."""
    n = len(agg["minute_open_ms"])
    cols = [agg[c].tolist() for c in COLUMNS if c != "symbol"]
    out = []
    for i in range(n):
        row = [symbol] + [c[i] for c in cols]
        v = row[COLUMNS.index("vwap")]
        if v != v:
            row[COLUMNS.index("vwap")] = None
        out.append(tuple(row))
    return out


def parse_checksum(text: str) -> str | None:
    """`.CHECKSUM` içeriğinden sha256 (ilk sözcük, 64 hex) al."""
    parts = (text or "").strip().split()
    if parts and len(parts[0]) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in parts[0]):
        return parts[0].lower()
    return None


def date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    """[start, end] kapalı gün listesi."""
    n = (end - start).days
    return [start + dt.timedelta(days=i) for i in range(n + 1)] if n >= 0 else []


def day_bounds_ms(day: dt.date) -> tuple[int, int]:
    """UTC günü [başlangıç, bitiş) ms."""
    a = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    return a, a + 86_400_000


def rest_trades_to_arrays(trades: list[dict]) -> dict[str, np.ndarray]:
    """REST aggTrades yanıtını (a,p,q,T,m) ayrıştırılmış dizilere çevir (aynı sözleşme: m=True → satış)."""
    if not trades:
        return parse_agg_csv(b"")
    return {
        "id": np.array([int(x["a"]) for x in trades], dtype=np.int64),
        "price": np.array([float(x["p"]) for x in trades]),
        "qty": np.array([float(x["q"]) for x in trades]),
        "t_ms": to_ms(np.array([int(x["T"]) for x in trades], dtype=np.int64)),
        "is_sell": np.array([bool(x["m"]) for x in trades], dtype=bool),
    }


# ───────────────────────── ağ ─────────────────────────

class Fetcher:
    """İş parçacığı başına bir requests.Session; arşiv indirme + sha256 doğrulama + REST sayfalama."""

    def __init__(self, gate: WeightGate):
        self.gate = gate
        self.local = threading.local()
        self.bytes_down = 0
        self.lock = threading.Lock()

    @property
    def sess(self) -> requests.Session:
        if not hasattr(self.local, "s"):
            self.local.s = requests.Session()
        return self.local.s

    def _add_bytes(self, n: int) -> None:
        with self.lock:
            self.bytes_down += n

    def archive_day(self, symbol: str, day: dt.date) -> bytes | None:
        """Günlük CSV baytları; None = arşivde yok (404). sha256 uyuşmazlığında yeniden dener."""
        name = f"{symbol}-aggTrades-{day.isoformat()}.zip"
        url = f"{ARCHIVE}/{symbol}/{name}"
        last_err = "bilinmeyen"
        for attempt in range(6):
            try:
                r = self.sess.get(url, timeout=60)
                if r.status_code == 404:
                    return None
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(1.5 * (attempt + 1))
                    continue
                body = r.content
                self._add_bytes(len(body))
                rc = self.sess.get(url + ".CHECKSUM", timeout=30)
                if rc.status_code == 200:
                    want = parse_checksum(rc.text)
                    got = hashlib.sha256(body).hexdigest()
                    if want and want != got:
                        last_err = "sha256 uyuşmazlığı"
                        time.sleep(1.0 * (attempt + 1))
                        continue
                elif rc.status_code != 404:
                    last_err = f"CHECKSUM HTTP {rc.status_code}"
                    time.sleep(1.0 * (attempt + 1))
                    continue
                with zipfile.ZipFile(io.BytesIO(body)) as zf:
                    return zf.read(zf.namelist()[0])
            except (requests.RequestException, zipfile.BadZipFile) as exc:
                last_err = type(exc).__name__
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"{url}: {last_err}")

    def rest_range(self, symbol: str, start_ms: int, end_ms: int) -> list[dict]:
        """[start_ms, end_ms) aralığındaki tüm aggTrade'ler: startTime ile ilk sayfa, sonra fromId (1000/sayfa)."""
        out: list[dict] = []
        from_id: int | None = None
        while True:
            if from_id is None:
                q = {"symbol": symbol, "limit": 1000, "startTime": start_ms}
            else:
                q = {"symbol": symbol, "limit": 1000, "fromId": from_id}
            data = None
            for attempt in range(8):
                self.gate.wait()
                try:
                    r = self.sess.get(REST_AGG, params=q, timeout=20)
                except requests.RequestException:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                used = r.headers.get("x-mbx-used-weight-1m")
                if r.status_code in (418, 429):
                    self.gate.observe(None, float(r.headers.get("Retry-After") or 30))
                    continue
                self.gate.observe(int(used) if used and used.isdigit() else None)
                if r.status_code == 400:
                    return out
                if r.status_code != 200:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                data = r.json()
                self._add_bytes(len(r.content))
                break
            if data is None:
                raise RuntimeError(f"{symbol} REST aggTrades çekilemedi (from_id={from_id})")
            done = False
            for x in data:
                if x["T"] >= end_ms:
                    done = True
                    break
                out.append(x)
            if done or len(data) < 1000:
                return out
            from_id = int(data[-1]["a"]) + 1


def fetch_universe(sess: requests.Session) -> list[str]:
    r = sess.get(REST_INFO, timeout=30)
    r.raise_for_status()
    return sorted(s["symbol"] for s in r.json()["symbols"] if s.get("quoteAsset") == "TRY" and s.get("status") == "TRADING")


# ───────────────────────── DB ─────────────────────────

_UPSERT_SQL = (
    "INSERT INTO historical_trade_flow (" + ", ".join(COLUMNS) + ") SELECT " + ", ".join(COLUMNS) + " FROM _tf_stage "
    "ON CONFLICT (symbol, minute_open_ms) DO UPDATE SET " +
    ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in ("symbol", "minute_open_ms"))
)


def upsert_rows(conn, rows: list[tuple]) -> int:
    """COPY → geçici tablo → ON CONFLICT DO UPDATE; tek transaction."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS _tf_stage (LIKE historical_trade_flow) ON COMMIT DELETE ROWS")
        with cur.copy("COPY _tf_stage (" + ", ".join(COLUMNS) + ") FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
        cur.execute(_UPSERT_SQL)
    conn.commit()
    return len(rows)


def load_checkpoint() -> dict[tuple[str, str], str]:
    done: dict[tuple[str, str], str] = {}
    if os.path.exists(CKPT_PATH):
        with open(CKPT_PATH, encoding="utf-8") as fh:
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3:
                    done[(p[0], p[1])] = p[2]
    return done


# ───────────────────────── ana akış ─────────────────────────

class Progress:
    def __init__(self, total: int):
        self.total = total
        self.t0 = time.time()
        self.done = 0
        self.rows = 0
        self.n404 = 0
        self.failed = 0
        self.lock = threading.Lock()
        self.last_print = 0.0

    def tick(self, rows: int, is404: bool, fetcher: Fetcher, force: bool = False) -> None:
        with self.lock:
            self.done += 1
            self.rows += rows
            self.n404 += 1 if is404 else 0
            now = time.time()
            if force or now - self.last_print >= 20 or self.done == self.total:
                self.last_print = now
                el = now - self.t0
                rate = self.done / el if el else 0
                eta = (self.total - self.done) / rate / 60 if rate else 0
                print(f"[tf] {self.done:,}/{self.total:,} çift ({100 * self.done / self.total:.1f}%) · satır {self.rows:,} · "
                      f"404 {self.n404:,} · hata {self.failed} · {rate:.1f} çift/sn · {fetcher.bytes_down / 1e6:.0f} MB indi · "
                      f"geçen {el / 60:.1f} dk · kalan ~{eta:.0f} dk", flush=True)


def process_pair(fetcher: Fetcher, symbol: str, day: dt.date, recent_cutoff: dt.date, now_ms: int) -> tuple[list[tuple], str]:
    """Bir (sembol, gün) çifti → (satırlar, durum). Durum: ok | 404 | rest."""
    data = fetcher.archive_day(symbol, day)
    if data is None:
        if day >= recent_cutoff:
            # arşiv ~1 gün geride: REST ile tamamla (yalnız kapanmış dakikalar)
            a, b = day_bounds_ms(day)
            b = min(b, (now_ms // MINUTE_MS) * MINUTE_MS)
            trades = fetcher.rest_range(symbol, a, b) if b > a else []
            arr = rest_trades_to_arrays(trades)
            agg = aggregate_minutes(arr["id"], arr["price"], arr["qty"], arr["t_ms"], arr["is_sell"])
            return rows_from_agg(symbol, agg), "rest"
        return [], "404"
    arr = parse_agg_csv(data)
    agg = aggregate_minutes(arr["id"], arr["price"], arr["qty"], arr["t_ms"], arr["is_sell"])
    return rows_from_agg(symbol, agg), "ok"


def run(args: argparse.Namespace) -> int:
    import psycopg

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL gerekli", file=sys.stderr)
        return 2
    os.makedirs(WORK_DIR, exist_ok=True)
    gate = WeightGate(args.max_weight)
    fetcher = Fetcher(gate)
    now = time.time()
    now_ms = int(now * 1000)
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    start_day = today - dt.timedelta(days=args.days)
    yesterday = today - dt.timedelta(days=1)
    days = date_range(start_day, yesterday)
    universe = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else fetch_universe(fetcher.sess)
    ckpt = load_checkpoint()
    recent_cutoff = today - dt.timedelta(days=2)  # arşiv gecikmesi: son 2 günde 404 → REST
    # Bugünün kuyruğu her koşuda yeniden REST'ten alınır (kısmi gün; checkpoint'lenmez).
    pairs = [(s, d) for d in days for s in universe if ckpt.get((s, d.isoformat())) not in ("ok", "404")]
    tail_syms = universe if not args.no_tail else []
    print(f"[tf] evren {len(universe)} sembol · gün {days[0]} → {days[-1]} ({len(days)}) · kalan çift {len(pairs):,} "
          f"(checkpoint {len(ckpt):,}) · bugün kuyruğu {len(tail_syms)} sembol · {args.workers} işçi", flush=True)

    q: queue.Queue = queue.Queue(maxsize=args.workers * 4)
    prog = Progress(len(pairs) + len(tail_syms))
    ckpt_lock = threading.Lock()
    SENTINEL = object()

    writer_err: list[str] = []

    def writer() -> None:
        conn = psycopg.connect(db_url, connect_timeout=10)
        buf: list[tuple] = []
        pend: list[tuple[str, str, str, int]] = []

        def flush() -> None:
            nonlocal buf, pend
            if buf:
                upsert_rows(conn, buf)
            if pend:
                with ckpt_lock, open(CKPT_PATH, "a", encoding="utf-8") as fh:
                    for sym, d, st, n in pend:
                        fh.write(f"{sym}\t{d}\t{st}\t{n}\n")
            buf, pend = [], []

        while True:
            item = q.get()
            if item is SENTINEL:
                break
            if writer_err:
                continue  # yazıcı bozuldu: kuyruğu boşalt (checkpoint'lenmez → sonraki koşu tekrar dener)
            sym, dstr, status, rows, persist = item
            buf.extend(rows)
            if persist:
                pend.append((sym, dstr, status, len(rows)))
            if len(buf) >= 20_000 or len(pend) >= 200:
                try:
                    flush()
                except Exception as exc:  # noqa: BLE001
                    writer_err.append(str(exc))
                    print(f"[tf] YAZICI HATASI: {exc}", flush=True)
        if not writer_err:
            try:
                flush()
            except Exception as exc:  # noqa: BLE001
                writer_err.append(str(exc))
                print(f"[tf] YAZICI HATASI: {exc}", flush=True)
        conn.close()

    wt = threading.Thread(target=writer, name="tf-writer", daemon=True)
    wt.start()

    def work(job) -> None:
        sym, day = job
        try:
            rows, status = process_pair(fetcher, sym, day, recent_cutoff, now_ms)
        except Exception as exc:  # noqa: BLE001
            with prog.lock:
                prog.failed += 1
            print(f"[tf] HATA {sym} {day}: {exc}", flush=True)
            prog.tick(0, False, fetcher)
            return
        # REST ile tamamlanan (arşivde olmayan) günler checkpoint'lenmez: arşiv gelince üstüne yazılır
        q.put((sym, day.isoformat(), status, rows, status in ("ok", "404")))
        prog.tick(len(rows), status == "404", fetcher)

    def tail(sym: str) -> None:
        a, _ = day_bounds_ms(today)
        b = (now_ms // MINUTE_MS) * MINUTE_MS
        try:
            trades = fetcher.rest_range(sym, a, b) if b > a else []
            arr = rest_trades_to_arrays(trades)
            agg = aggregate_minutes(arr["id"], arr["price"], arr["qty"], arr["t_ms"], arr["is_sell"])
            rows = rows_from_agg(sym, agg)
        except Exception as exc:  # noqa: BLE001
            with prog.lock:
                prog.failed += 1
            print(f"[tf] HATA kuyruk {sym}: {exc}", flush=True)
            prog.tick(0, False, fetcher)
            return
        q.put((sym, today.isoformat(), "tail", rows, False))
        prog.tick(len(rows), False, fetcher)

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(work, p) for p in pairs] + [ex.submit(tail, s) for s in tail_syms]
        for f in futs:
            f.result()
    q.put(SENTINEL)
    wt.join()
    elapsed = time.time() - t0
    print(f"[tf] BİTTİ · çift {prog.done:,} · satır {prog.rows:,} · 404 {prog.n404:,} · hata {prog.failed} · "
          f"{fetcher.bytes_down / 1e6:.0f} MB · süre {elapsed / 60:.1f} dk", flush=True)
    stats = {}
    if os.path.exists(STATS_PATH):
        try:
            with open(STATS_PATH, encoding="utf-8") as fh:
                stats = json.load(fh)
        except ValueError:
            stats = {}
    stats.setdefault("runs", []).append({
        "started": dt.datetime.fromtimestamp(t0, dt.timezone.utc).isoformat(), "elapsed_s": round(elapsed, 1),
        "pairs": prog.done, "rows": prog.rows, "n404": prog.n404, "failed": prog.failed,
        "mb_downloaded": round(fetcher.bytes_down / 1e6, 1), "workers": args.workers, "days": args.days,
    })
    with open(STATS_PATH, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1)
    write_report(db_url)
    return 0 if prog.failed == 0 and not writer_err else 1


# ───────────────────────── rapor ─────────────────────────

def _fmt_pct(vals: Iterable[float]) -> str:
    a = np.array(list(vals), dtype=float)
    if a.size == 0:
        return "-"
    q = np.percentile(a, [0, 10, 25, 50, 75, 90, 100])
    return " / ".join(f"{x:.0f}" for x in q)


def write_report(db_url: str) -> str:
    import psycopg

    lines: list[str] = ["# historical_trade_flow kapsam raporu", "", f"Üretim: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}", ""]
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        tot = conn.execute("SELECT count(*), count(DISTINCT symbol), min(minute_open_ms), max(minute_open_ms), "
                           "sum(n_trades) FROM historical_trade_flow").fetchone()
        size = conn.execute("SELECT pg_size_pretty(pg_total_relation_size('historical_trade_flow')), "
                            "pg_size_pretty(pg_database_size(current_database()))").fetchone()
        per_day = conn.execute(
            "SELECT to_char(to_timestamp(minute_open_ms/1000.0) AT TIME ZONE 'UTC', 'YYYY-MM-DD') d, "
            "count(DISTINCT symbol), count(*), sum(n_trades) FROM historical_trade_flow GROUP BY 1 ORDER BY 1").fetchall()
        sd = conn.execute(
            "SELECT symbol, to_char(to_timestamp(minute_open_ms/1000.0) AT TIME ZONE 'UTC', 'YYYY-MM-DD') d, count(*) "
            "FROM historical_trade_flow GROUP BY 1, 2").fetchall()
    lines += [f"- Satır: {tot[0]:,} · sembol: {tot[1]} · toplam işlem (aggTrade): {int(tot[4] or 0):,}",
              f"- Aralık (UTC): {dt.datetime.fromtimestamp((tot[2] or 0) / 1000, dt.timezone.utc):%Y-%m-%d %H:%M} → "
              f"{dt.datetime.fromtimestamp((tot[3] or 0) / 1000, dt.timezone.utc):%Y-%m-%d %H:%M}",
              f"- Tablo boyutu (indeksli): {size[0]} · veritabanı: {size[1]}", ""]
    mins = [r[2] for r in sd]
    lines += ["## Sembol-gün başına işlem olan dakika sayısı (min / p10 / p25 / medyan / p75 / p90 / maks)", "",
              f"{_fmt_pct(mins)}  (sembol-gün çifti: {len(mins):,}; 1 gün = 1440 dakika)", ""]
    lines += ["## Gün bazında kapsam", "", "| Gün (UTC) | Sembol | Satır | aggTrade |", "|---|---|---|---|"]
    for d, ns, nr, nt in per_day:
        lines.append(f"| {d} | {ns} | {nr:,} | {int(nt):,} |")
    lines.append("")
    if os.path.exists(STATS_PATH):
        with open(STATS_PATH, encoding="utf-8") as fh:
            st = json.load(fh)
        lines += ["## Koşular", "", "| Başlangıç (UTC) | Süre (dk) | Çift | Satır | 404 | Hata | İndirilen MB | İşçi |", "|---|---|---|---|---|---|---|---|"]
        for r in st.get("runs", []):
            lines.append(f"| {r['started'][:19]} | {r['elapsed_s'] / 60:.1f} | {r['pairs']:,} | {r['rows']:,} | {r['n404']:,} | "
                         f"{r['failed']} | {r['mb_downloaded']} | {r['workers']} |")
        lines.append("")
    if os.path.exists(VALIDATION_PATH):
        with open(VALIDATION_PATH, encoding="utf-8") as fh:
            lines += ["", fh.read()]
    lines += ["", "## Notlar", "",
              "- Tablo yalnız araştırma amaçlıdır (canlı yazıcı yok); retention döngüsü bu tabloyu BUDAMAZ.",
              "- Yeniden çalıştırma / uzatma: `python scripts/backfill_trade_flow.py --days N` (biten çiftler checkpoint ile atlanır).", ""]
    text = "\n".join(lines)
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"[tf] rapor yazıldı: {REPORT_PATH}", flush=True)
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90, help="bugünden geriye kaç UTC günü (dün dahil)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--symbols", default="", help="virgüllü sembol listesi (varsayılan: TRY TRADING evreni)")
    ap.add_argument("--max-weight", type=int, default=4000, help="REST ağırlık eşiği (dakikada; limit 6000)")
    ap.add_argument("--no-tail", action="store_true", help="bugünün REST kuyruğunu atla")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)
    if args.report_only:
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            print("DATABASE_URL gerekli", file=sys.stderr)
            return 2
        write_report(db_url)
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
