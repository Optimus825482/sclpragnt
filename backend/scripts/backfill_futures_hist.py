"""Tarihsel Binance USDⓈ-M futures bağlamı GERİ DOLDURMA (2026-10-17).

AMAÇ: Binance TR TRY spot emir defteri için ücretsiz GEÇMİŞ yok. Aynı BASE varlığın USDⓈ-M perpetual'ının
public arşivleri (data.binance.vision) küresel likidite / türev bağlamı vekili olarak backtest'lerde kullanılır:
  * metrics     (günlük, ~5 dk)  -> hist_futures_metrics   (açık pozisyon + long/short oranları)
  * bookDepth   (günlük, ~25 sn) -> hist_futures_bookdepth (±1..5 % derinlik; 5 dk dilimin SON görüntüsü, GENİŞ biçim)
  * fundingRate (aylık)          -> hist_funding_rate      (güncel ay + eksik/404 aylar REST'ten)
Tablolar: migrations/024_historical_futures.sql. Eşleme tablosu: futures_symbol_map.

YÖNTEM
  * Eşleme: Binance TR exchangeInfo (quote=TRY, TRADING) tabanları -> USDⓈ-M PERPETUAL (quote=USDT). Aday sırası
    BASE, 1000BASE, 1000000BASE, 1MBASE; takma ad LUNA -> LUNA2. Perp'i olmayan taban (ör. RAD, stable) atlanır.
  * İndirme: ~16 iş parçacığı, her zip için .CHECKSUM sha256 doğrulaması, 404/403 loglanır (kalıcı atlanır;
    son 2 günün 404'ü kalıcı SAYILMAZ -> yayın gecikmesi olabilir), ağ/5xx hatasında üstel geri çekilmeyle yeniden dener.
  * Akış ayrıştırma (bellekte yalnız tek zip), ON CONFLICT DO NOTHING ile toplu yazım (idempotent).
  * Checkpoint JSON (work/futures_hist/checkpoint.json): yalnız DB'ye COMMIT edildikten sonra işaretlenir -> güvenle
    kesilip yeniden başlatılır. İlerleme + ETA stdout'a.

KULLANIM (backend/ içinden; ortam: DATABASE_URL):
    .venv/Scripts/python.exe scripts/backfill_futures_hist.py                 # tam 90 gün
    ... --symbols BTCUSDT,ETHUSDT --days 3 --fresh                           # küçük deneme
    ... --validate                                                           # yalnız doğrulama raporu (report.md)
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import functools
import hashlib
import io
import json
import os
import statistics
import sys
import threading
import time
import zipfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TR_EXCHANGE_INFO = "https://api.binance.me/api/v3/exchangeInfo"
FAPI_EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
FAPI_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"
VISION = "https://data.binance.vision/data/futures/um"

HERE = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(os.path.dirname(HERE), "work", "futures_hist")
DEFAULT_CKPT = os.path.join(WORK_DIR, "checkpoint.json")

DAY_MS = 86_400_000
BUCKET_MIN_DEFAULT = 5
LEVELS = (1, 2, 3, 4, 5)
# Perp sözleşmesi çarpanlı adlandırma önekleri (aday sırası önemli: önce birebir eşleşme).
PREFIXES = (("", 1.0), ("1000", 1000.0), ("1000000", 1_000_000.0), ("1M", 1_000_000.0))
BASE_ALIASES = {"LUNA": "LUNA2"}
STABLE_BASES = frozenset({"USDT", "USDC", "FDUSD", "USD1", "TUSD", "BUSD", "DAI", "USDP", "EUR", "TRY", "U"})
OK_PERP_STATUS = ("TRADING", "SETTLING")


# --------------------------------------------------------------------------------------------------
# Sembol eşleme (saf)
# --------------------------------------------------------------------------------------------------
def build_symbol_map(tr_info: dict, fut_info: dict) -> list[dict]:
    """TRY (TRADING) sembolleri -> USDⓈ-M perpetual. Çıktı: try_symbol sıralı sözlük listesi.

    Dönen her satır: try_symbol, base, perp_symbol, multiplier, perp_status. Perp'i olmayan taban listede YOKTUR.
    """
    perps: dict[str, dict] = {}
    for s in fut_info.get("symbols", []):
        if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT":
            perps[str(s.get("baseAsset"))] = s
    out: list[dict] = []
    for s in tr_info.get("symbols", []):
        if s.get("quoteAsset") != "TRY" or s.get("status") != "TRADING":
            continue
        base = str(s.get("baseAsset"))
        if base in STABLE_BASES:
            continue
        target = BASE_ALIASES.get(base, base)
        hit = None
        for prefix, mult in PREFIXES:
            cand = perps.get(prefix + target)
            if cand is not None and cand.get("status") in OK_PERP_STATUS:
                hit = (cand, mult if prefix else 1.0)
                break
        if hit is None:
            continue
        cand, mult = hit
        out.append({"try_symbol": str(s.get("symbol")), "base": base, "perp_symbol": str(cand["symbol"]),
                    "multiplier": float(mult), "perp_status": str(cand.get("status"))})
    out.sort(key=lambda r: r["try_symbol"])
    return out


# --------------------------------------------------------------------------------------------------
# CSV ayrıştırma (saf)
# --------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=512)
def _day_ms(date_s: str) -> int:
    y, m, d = int(date_s[0:4]), int(date_s[5:7]), int(date_s[8:10])
    return int(dt.datetime(y, m, d, tzinfo=dt.timezone.utc).timestamp()) * 1000


def parse_ts_ms(s: str) -> int:
    """'YYYY-MM-DD HH:MM:SS' (UTC) -> epoch ms. Epoch ms (saf rakam) da kabul edilir."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    return (_day_ms(s[:10]) + int(s[11:13]) * 3_600_000 + int(s[14:16]) * 60_000 + int(s[17:19]) * 1000)


def _f(x):
    x = x.strip() if x is not None else x
    if x is None or x == "":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def parse_metrics_csv(text: str, perp_symbol: str) -> list[tuple]:
    """metrics CSV -> (perp_symbol, ts_ms, sum_oi, sum_oi_value, top_count_ls, top_sum_ls, count_ls, taker_ls)."""
    rows: list[tuple] = []
    rd = csv.reader(io.StringIO(text))
    header = next(rd, None)
    if not header or header[0].strip().lower() != "create_time":
        return rows
    for r in rd:
        if len(r) < 8 or not r[0].strip():
            continue
        try:
            ts = parse_ts_ms(r[0])
        except (ValueError, IndexError):
            continue
        rows.append((perp_symbol, ts, _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5]), _f(r[6]), _f(r[7])))
    return rows


def parse_bookdepth_csv(text: str, perp_symbol: str, bucket_min: int = BUCKET_MIN_DEFAULT) -> list[tuple]:
    """bookDepth CSV -> geniş satırlar; her `bucket_min` dk diliminin SON anlık görüntüsü.

    CSV: timestamp,percentage,depth,notional (anlık görüntü başına yüzde -5..-1,1..5 = 10 satır).
    Satır: (perp_symbol, ts_ms, bid_n1..5, ask_n1..5, bid_d1..5, ask_d1..5) — sütun sırası migration 024 ile aynı.
    Hızlı yol: yalnız anlık görüntü sınırları taranır, seçilen görüntüler tam ayrıştırılır.
    """
    lines = text.splitlines()
    if not lines or not lines[0].lower().startswith("timestamp"):
        return []
    starts: list[tuple[str, int]] = []  # (ts_str, ilk satır indeksi)
    cur = None
    for i in range(1, len(lines)):
        ln = lines[i]
        if len(ln) < 20:
            continue
        t = ln[:19]
        if t != cur:
            cur = t
            starts.append((t, i))
    if not starts:
        return []
    step = bucket_min * 60
    last_by_bucket: dict[int, tuple[str, int, int]] = {}
    n = len(starts)
    for k, (t, i) in enumerate(starts):
        sec = int(t[11:13]) * 3600 + int(t[14:16]) * 60 + int(t[17:19])
        end = starts[k + 1][1] if k + 1 < n else len(lines)
        last_by_bucket[(_day_ms(t[:10]) // 1000 + sec) // step] = (t, i, end)
    rows: list[tuple] = []
    for b in sorted(last_by_bucket):
        t, i, end = last_by_bucket[b]
        bn = [None] * 5
        an = [None] * 5
        bd = [None] * 5
        ad = [None] * 5
        for ln in lines[i:end]:
            p = ln.split(",")
            if len(p) < 4:
                continue
            try:
                pct = int(round(float(p[1])))
            except ValueError:
                continue
            if pct == 0 or abs(pct) > 5:
                continue
            depth, notional = _f(p[2]), _f(p[3])
            if pct < 0:
                bn[-pct - 1], bd[-pct - 1] = notional, depth
            else:
                an[pct - 1], ad[pct - 1] = notional, depth
        rows.append((perp_symbol, parse_ts_ms(t), *bn, *an, *bd, *ad))
    return rows


def parse_funding_csv(text: str, perp_symbol: str, min_ms: int = 0) -> list[tuple]:
    """Aylık fundingRate CSV (calc_time,funding_interval_hours,last_funding_rate) -> (sym, ms, rate, None, hours)."""
    rows: list[tuple] = []
    rd = csv.reader(io.StringIO(text))
    header = next(rd, None)
    if not header or header[0].strip().lower() != "calc_time":
        return rows
    for r in rd:
        if len(r) < 3 or not r[0].strip():
            continue
        try:
            ts = int(r[0])
        except ValueError:
            continue
        if ts < min_ms:
            continue
        hours = None
        try:
            hours = int(float(r[1]))
        except ValueError:
            pass
        rows.append((perp_symbol, ts, _f(r[2]), None, hours))
    return rows


def depth_imbalance(row: dict, level: int) -> float | None:
    """(bid − ask) / (bid + ask) notional, ±level %. Eksik/0 toplam için None."""
    b, a = row.get("bid_n%d" % level), row.get("ask_n%d" % level)
    if b is None or a is None or (b + a) <= 0:
        return None
    return (b - a) / (b + a)


# --------------------------------------------------------------------------------------------------
# İndirme
# --------------------------------------------------------------------------------------------------
class Missing(Exception):
    """Arşivde dosya yok (404/403)."""


class ChecksumError(Exception):
    pass


def parse_checksum(text: str) -> str | None:
    tok = text.strip().split()
    return tok[0].lower() if tok and len(tok[0]) == 64 else None


def _get(client, url: str, attempts: int = 6) -> bytes:
    last = None
    for k in range(attempts):
        try:
            r = client.get(url)
            if r.status_code in (403, 404):
                raise Missing(url)
            if r.status_code == 200:
                return r.content
            last = RuntimeError("HTTP %d" % r.status_code)
        except Missing:
            raise
        except Exception as exc:  # ağ hatası / zaman aşımı
            last = exc
        time.sleep(min(2.0 ** k, 30.0))
    raise RuntimeError("indirilemedi: %s (%s)" % (url, last))


def fetch_zip_text(client, url: str, verify: bool = True) -> str:
    """zip + .CHECKSUM indir, sha256 doğrula, tek CSV üyenin metnini döndür."""
    blob = _get(client, url)
    if verify:
        want = parse_checksum(_get(client, url + ".CHECKSUM").decode("utf-8", "replace"))
        got = hashlib.sha256(blob).hexdigest()
        if want is not None and want != got:
            raise ChecksumError("%s sha256 uyuşmuyor" % url)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        return zf.read(name).decode("utf-8", "replace")


def daily_url(kind: str, sym: str, day: str) -> str:
    return "%s/daily/%s/%s/%s-%s-%s.zip" % (VISION, kind, sym, sym, kind, day)


def monthly_funding_url(sym: str, month: str) -> str:
    return "%s/monthly/fundingRate/%s/%s-fundingRate-%s.zip" % (VISION, sym, sym, month)


def fetch_funding_rest(client, sym: str, start_ms: int, end_ms: int) -> list[tuple]:
    """REST fundingRate (mark_price dahil), 1000'lik sayfalama."""
    rows: list[tuple] = []
    cur = start_ms
    while cur <= end_ms:
        r = client.get(FAPI_FUNDING, params={"symbol": sym, "startTime": cur, "endTime": end_ms, "limit": 1000})
        if r.status_code == 429 or r.status_code == 418:
            time.sleep(int(r.headers.get("Retry-After", "10")))
            continue
        if r.status_code != 200:
            raise RuntimeError("fundingRate %s HTTP %d" % (sym, r.status_code))
        data = r.json()
        if not data:
            break
        for d in data:
            rows.append((sym, int(d["fundingTime"]), _f(str(d.get("fundingRate", ""))),
                         _f(str(d.get("markPrice", ""))), None))
        nxt = int(data[-1]["fundingTime"]) + 1
        if nxt <= cur or len(data) < 1000:
            break
        cur = nxt
    return rows


# --------------------------------------------------------------------------------------------------
# DB yazımı
# --------------------------------------------------------------------------------------------------
_BD_COLS = ("perp_symbol, ts_ms, bid_n1, bid_n2, bid_n3, bid_n4, bid_n5, ask_n1, ask_n2, ask_n3, ask_n4, ask_n5, "
            "bid_d1, bid_d2, bid_d3, bid_d4, bid_d5, ask_d1, ask_d2, ask_d3, ask_d4, ask_d5")
SQL_METRICS = ("INSERT INTO hist_futures_metrics (perp_symbol, ts_ms, sum_open_interest, sum_open_interest_value, "
               "count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, "
               "sum_taker_long_short_vol_ratio) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING")
SQL_BOOKDEPTH = "INSERT INTO hist_futures_bookdepth (" + _BD_COLS + ") VALUES (" + ",".join(["%s"] * 22) + ") ON CONFLICT DO NOTHING"
SQL_FUNDING = ("INSERT INTO hist_funding_rate (perp_symbol, funding_time_ms, funding_rate, mark_price, "
               "funding_interval_hours) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (perp_symbol, funding_time_ms) DO UPDATE SET "
               "mark_price = COALESCE(EXCLUDED.mark_price, hist_funding_rate.mark_price)")
SQL_MAP = ("INSERT INTO futures_symbol_map (try_symbol, base, perp_symbol, multiplier, perp_status, updated_at) "
           "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (try_symbol) DO UPDATE SET base=EXCLUDED.base, "
           "perp_symbol=EXCLUDED.perp_symbol, multiplier=EXCLUDED.multiplier, perp_status=EXCLUDED.perp_status, "
           "updated_at=EXCLUDED.updated_at")
SQL_BY_KIND = {"metrics": SQL_METRICS, "bookDepth": SQL_BOOKDEPTH, "funding": SQL_FUNDING}


def write_rows(conn, kind: str, rows: list[tuple]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        for i in range(0, len(rows), 5000):
            cur.executemany(SQL_BY_KIND[kind], rows[i:i + 5000])


# --------------------------------------------------------------------------------------------------
# Checkpoint
# --------------------------------------------------------------------------------------------------
class Checkpoint:
    def __init__(self, path: str, fresh: bool = False):
        self.path = path
        self.done: dict[str, str] = {}
        if not fresh:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self.done = dict(json.load(fh).get("done", {}))
            except Exception:
                self.done = {}
        self._last_save = 0.0

    def save(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_save < 20:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"saved_at": now, "done": self.done}, fh)
        os.replace(tmp, self.path)
        self._last_save = now


def date_range(start: dt.date, end: dt.date) -> list[str]:
    out = []
    d = start
    while d <= end:
        out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def month_list(start: dt.date, end: dt.date) -> list[str]:
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# --------------------------------------------------------------------------------------------------
# Ana akış
# --------------------------------------------------------------------------------------------------
def _task(client, kind: str, sym: str, day: str, bucket_min: int, verify: bool):
    """Bir (tür, sembol, gün) işi -> (anahtar, durum, satırlar). Durum: ok | 404 | err:<msg>."""
    key = "%s|%s|%s" % (kind, sym, day)
    try:
        text = fetch_zip_text(client, daily_url(kind, sym, day), verify)
    except Missing:
        return key, "404", []
    except Exception as exc:
        return key, "err:" + str(exc)[:200], []
    if kind == "metrics":
        return key, "ok", parse_metrics_csv(text, sym)
    return key, "ok", parse_bookdepth_csv(text, sym, bucket_min)


def _funding_task(client, sym: str, month: str, start_ms: int, end_ms: int, use_rest: bool):
    key = "funding|%s|%s" % (sym, month)
    try:
        if not use_rest:
            text = fetch_zip_text(client, monthly_funding_url(sym, month), True)
            return key, "ok", parse_funding_csv(text, sym, start_ms)
    except Missing:
        pass  # REST'e düş
    except Exception as exc:
        return key, "err:" + str(exc)[:200], []
    try:
        y, m = int(month[:4]), int(month[5:7])
        m0 = int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        m1 = int(dt.datetime(ny, nm, 1, tzinfo=dt.timezone.utc).timestamp() * 1000) - 1
        rows = fetch_funding_rest(client, sym, max(m0, start_ms), min(m1, end_ms))
        return key, "ok", rows
    except Exception as exc:
        return key, "err:" + str(exc)[:200], []


def _make_client(threads: int):
    import httpx
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True,
                        limits=httpx.Limits(max_connections=threads + 4, max_keepalive_connections=threads + 4),
                        headers={"User-Agent": "scalper-futures-hist/1.0"})


def load_symbol_map(client) -> list[dict]:
    tr = client.get(TR_EXCHANGE_INFO, timeout=120).json()
    tr = {"symbols": [s for s in tr.get("symbols", []) if s.get("quoteAsset") == "TRY"]}
    bases = sorted({s["baseAsset"] for s in tr["symbols"] if s.get("status") == "TRADING"})
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(os.path.join(WORK_DIR, "try_bases.json"), "w", encoding="utf-8") as fh:
        json.dump(bases, fh)
    fut = client.get(FAPI_EXCHANGE_INFO, timeout=120).json()
    return build_symbol_map(tr, fut)


def run(args) -> int:
    import psycopg
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL gerekli", file=sys.stderr)
        return 2
    today = dt.datetime.now(dt.timezone.utc).date()
    end = dt.date.fromisoformat(args.end) if args.end else today - dt.timedelta(days=1)
    start = dt.date.fromisoformat(args.start) if args.start else end - dt.timedelta(days=args.days - 1)
    days = date_range(start, end)
    start_ms = _day_ms(start.isoformat())
    end_ms = _day_ms(end.isoformat()) + DAY_MS - 1
    print("Pencere (UTC): %s .. %s (%d gün)" % (start, end, len(days)), flush=True)

    client = _make_client(args.threads)
    smap = load_symbol_map(client)
    perps = sorted({r["perp_symbol"] for r in smap})
    print("TRY sembol eşleme: %d TRY sembolü -> %d perp" % (len(smap), len(perps)), flush=True)
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(os.path.join(WORK_DIR, "symbol_map.json"), "w", encoding="utf-8") as fh:
        json.dump(smap, fh, ensure_ascii=False, indent=1)
    conn = psycopg.connect(db_url, connect_timeout=10)
    now_s = time.time()
    with conn.cursor() as cur:
        cur.executemany(SQL_MAP, [(r["try_symbol"], r["base"], r["perp_symbol"], r["multiplier"],
                                   r["perp_status"], now_s) for r in smap])
    conn.commit()

    if args.symbols:
        want = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        perps = [p for p in perps if p in want]
        print("Sembol filtresi: %d perp" % len(perps), flush=True)
    if args.map_only:
        return 0

    ck = Checkpoint(args.checkpoint, args.fresh)
    recent_cut = (today - dt.timedelta(days=2)).isoformat()
    tasks: list[tuple] = []
    kinds = [k for k in ("metrics", "bookDepth") if (args.only in (None, k))]
    for sym in perps:
        for day in days:
            for kind in kinds:
                key = "%s|%s|%s" % (kind, sym, day)
                if ck.done.get(key) in ("ok", "404") and not (ck.done.get(key) == "404" and day >= recent_cut):
                    continue
                tasks.append(("d", kind, sym, day))
    if args.only in (None, "funding"):
        cur_month = today.strftime("%Y-%m")
        for sym in perps:
            for month in month_list(start, end):
                key = "funding|%s|%s" % (sym, month)
                if ck.done.get(key) == "ok" and month != cur_month:
                    continue
                tasks.append(("f", "funding", sym, month))
    total = len(tasks)
    print("Yapılacak iş: %d (checkpoint'te biten atlandı)" % total, flush=True)
    if total == 0:
        return 0

    stats = collections.Counter()
    pending: list[tuple[str, str]] = []  # (key, status) commit sonrası işaretlenecek
    rows_buf: dict[str, list[tuple]] = {"metrics": [], "bookDepth": [], "funding": []}
    t0 = time.time()
    last_print = 0.0
    cur_month = today.strftime("%Y-%m")

    def flush(force: bool = False) -> None:
        n = sum(len(v) for v in rows_buf.values())
        if not force and n < 30_000:
            return
        for kind, rows in rows_buf.items():
            write_rows(conn, kind, rows)
            stats["rows_" + kind] += len(rows)
            rows.clear()
        conn.commit()
        for key, status in pending:
            ck.done[key] = status
        pending.clear()
        ck.save(force=force)

    def submit(ex, t):
        if t[0] == "d":
            return ex.submit(_task, client, t[1], t[2], t[3], args.bucket_min, not args.no_verify)
        month = t[3]
        use_rest = month == cur_month or args.funding_rest_all
        return ex.submit(_funding_task, client, t[2], month, start_ms, end_ms, use_rest)

    it = iter(tasks)
    inflight: set = set()
    done_n = 0
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        for _ in range(args.threads * 3):
            t = next(it, None)
            if t is None:
                break
            inflight.add(submit(ex, t))
        while inflight:
            fin, inflight = wait(inflight, return_when=FIRST_COMPLETED)
            for fut in fin:
                key, status, rows = fut.result()
                done_n += 1
                kind = key.split("|", 1)[0]
                if status == "ok":
                    rows_buf[kind].extend(rows)
                    pending.append((key, "ok"))
                    stats["ok"] += 1
                elif status == "404":
                    pending.append((key, "404"))
                    stats["404"] += 1
                else:
                    stats["err"] += 1
                    print("  HATA %s -> %s" % (key, status), flush=True)
                t = next(it, None)
                if t is not None:
                    inflight.add(submit(ex, t))
            flush()
            now = time.time()
            if now - last_print >= 15 or not inflight:
                el = now - t0
                rate = done_n / el if el > 0 else 0.0
                eta = (total - done_n) / rate if rate > 0 else 0.0
                print("[%5.1f%%] %d/%d  ok=%d 404=%d err=%d  satır: met=%d bd=%d fr=%d  %.1f iş/sn  geçen %dm  ETA %dm"
                      % (100.0 * done_n / total, done_n, total, stats["ok"], stats["404"], stats["err"],
                         stats["rows_metrics"], stats["rows_bookDepth"], stats["rows_funding"], rate,
                         el // 60, eta // 60), flush=True)
                last_print = now
    flush(force=True)
    conn.close()
    print("BİTTİ: %s  süre %.1f dk" % (dict(stats), (time.time() - t0) / 60), flush=True)
    return 0 if stats["err"] == 0 else 1


# --------------------------------------------------------------------------------------------------
# Doğrulama + rapor
# --------------------------------------------------------------------------------------------------
def _q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def validate(args) -> int:
    import psycopg
    db_url = os.environ.get("DATABASE_URL", "")
    conn = psycopg.connect(db_url, connect_timeout=10)
    L: list[str] = []
    P = L.append
    n_map = _q(conn, "SELECT count(*), count(DISTINCT perp_symbol) FROM futures_symbol_map")[0]
    try:
        n_try_bases = len(json.load(open(os.path.join(WORK_DIR, "try_bases.json"), encoding="utf-8")))
    except Exception:
        n_try_bases = None
    P("# Tarihsel futures bağlamı — doğrulama (%s)" % dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    P("")
    P("## Sembol eşleme")
    P("- TRY sembolü eşlenen: **%d**, farklı perp: **%d**%s" % (
        n_map[0], n_map[1], "" if n_try_bases is None else " (TRY TRADING taban sayısı %d)" % n_try_bases))
    ren = _q(conn, "SELECT try_symbol, perp_symbol, multiplier FROM futures_symbol_map "
                   "WHERE multiplier<>1 OR perp_symbol<>base||'USDT' ORDER BY 1")
    P("- Yeniden adlandırılan/çarpanlı: " + ", ".join("%s→%s(x%g)" % (a, b, c) for a, b, c in ren))
    P("")
    P("## Kapsam (tablo bazında)")
    P("| tablo | satır | perp | gün (farklı) | min..max (UTC) | boyut |")
    P("|---|---|---|---|---|---|")
    for tab, tcol, div in (("hist_futures_metrics", "ts_ms", DAY_MS), ("hist_futures_bookdepth", "ts_ms", DAY_MS),
                           ("hist_funding_rate", "funding_time_ms", DAY_MS)):
        r = _q(conn, "SELECT count(*), count(DISTINCT perp_symbol), count(DISTINCT %s/%d), min(%s), max(%s), "
                     "pg_size_pretty(pg_total_relation_size('%s')) FROM %s" % (tcol, div, tcol, tcol, tab, tab))[0]
        f = lambda ms: "-" if ms is None else dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M")
        P("| %s | %s | %s | %s | %s..%s | %s |" % (tab, format(r[0], ","), r[1], r[2], f(r[3]), f(r[4]), r[5]))
    P("")
    P("- Veritabanı toplam boyutu: **%s**" % _q(conn, "SELECT pg_size_pretty(pg_database_size(current_database()))")[0][0])
    cov = _q(conn, "SELECT n, count(*) FROM (SELECT perp_symbol, count(DISTINCT ts_ms/%d) n FROM hist_futures_metrics "
                   "GROUP BY 1) t GROUP BY n ORDER BY n DESC" % DAY_MS)
    P("- Perp başına metrics gün sayısı dağılımı (gün: perp sayısı): " + ", ".join("%d: %d" % (a, b) for a, b in cov[:12]))
    covb = _q(conn, "SELECT n, count(*) FROM (SELECT perp_symbol, count(DISTINCT ts_ms/%d) n FROM hist_futures_bookdepth "
                    "GROUP BY 1) t GROUP BY n ORDER BY n DESC" % DAY_MS)
    P("- Perp başına bookDepth gün sayısı dağılımı: " + ", ".join("%d: %d" % (a, b) for a, b in covb[:12]))
    P("")
    P("## Büyük 5 sembol sağlık kontrolü ve defter dengesizliği (quick look)")
    P("Dengesizlik = (alış notional − satış notional) / toplam; +1 = tüm derinlik alış tarafında.")
    P("")
    P("| perp | OI>0 | derinlik monoton | funding ±0,5 % içinde | bd satır | imb ±1% ort / std / p5 / p95 | imb ±2% ort / std / p5 / p95 |")
    P("|---|---|---|---|---|---|---|")
    top = [r[0] for r in _q(conn, "SELECT perp_symbol FROM hist_futures_metrics GROUP BY 1 "
                                  "ORDER BY avg(sum_open_interest_value) DESC NULLS LAST LIMIT 5")]
    for sym in top:
        oi_bad = _q(conn, "SELECT count(*) FROM hist_futures_metrics WHERE perp_symbol=%s AND "
                          "(sum_open_interest IS NULL OR sum_open_interest<=0 OR sum_open_interest_value<=0)", (sym,))[0][0]
        mono_bad = _q(conn, "SELECT count(*) FROM hist_futures_bookdepth WHERE perp_symbol=%s AND ("
                            "bid_n1>bid_n2 OR bid_n2>bid_n3 OR bid_n3>bid_n4 OR bid_n4>bid_n5 OR "
                            "ask_n1>ask_n2 OR ask_n2>ask_n3 OR ask_n3>ask_n4 OR ask_n4>ask_n5 OR "
                            "bid_d1>bid_d2 OR bid_d2>bid_d3 OR bid_d3>bid_d4 OR bid_d4>bid_d5 OR "
                            "ask_d1>ask_d2 OR ask_d2>ask_d3 OR ask_d3>ask_d4 OR ask_d4>ask_d5)", (sym,))[0][0]
        fr_bad, fr_n = _q(conn, "SELECT count(*) FILTER (WHERE abs(funding_rate)>0.005 OR funding_rate IS NULL), count(*) "
                                "FROM hist_funding_rate WHERE perp_symbol=%s", (sym,))[0]
        bd = _q(conn, "SELECT bid_n1, ask_n1, bid_n2, ask_n2 FROM hist_futures_bookdepth WHERE perp_symbol=%s", (sym,))
        cells = []
        for (bi, ai) in ((0, 1), (2, 3)):
            v = [(r[bi] - r[ai]) / (r[bi] + r[ai]) for r in bd if r[bi] is not None and r[ai] is not None and (r[bi] + r[ai]) > 0]
            if len(v) > 20:
                q = statistics.quantiles(v, n=20)
                cells.append("%+.3f / %.3f / %+.3f / %+.3f" % (statistics.fmean(v), statistics.pstdev(v), q[0], q[-1]))
            else:
                cells.append("-")
        P("| %s | %s | %s | %s | %d | %s | %s |" % (
            sym, "evet" if oi_bad == 0 else "HAYIR (%d)" % oi_bad,
            "evet" if mono_bad == 0 else "HAYIR (%d anlık görüntü)" % mono_bad,
            "evet (%d)" % fr_n if fr_bad == 0 else "HAYIR (%d/%d)" % (fr_bad, fr_n), len(bd), cells[0], cells[1]))
    P("")
    P("## Genel tutarlılık (tüm perp'ler)")
    P("- OI <= 0 veya NULL metrics satırı: %s" % _q(conn, "SELECT count(*) FROM hist_futures_metrics WHERE "
                                                   "sum_open_interest IS NULL OR sum_open_interest<=0")[0][0])
    P("- |funding| > 0,5 %% satır: %s" % _q(conn, "SELECT count(*) FROM hist_funding_rate WHERE abs(funding_rate)>0.005")[0][0])
    P("- bookDepth derinlik-monoton ihlali (satır): %s" % _q(conn, "SELECT count(*) FROM hist_futures_bookdepth WHERE "
                                                          "bid_n1>bid_n2 OR bid_n2>bid_n3 OR bid_n3>bid_n4 OR bid_n4>bid_n5 OR "
                                                          "ask_n1>ask_n2 OR ask_n2>ask_n3 OR ask_n3>ask_n4 OR ask_n4>ask_n5")[0][0])
    conn.close()
    path = os.path.join(WORK_DIR, "validation.md")
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))
    print("\n->", path)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--start", help="YYYY-MM-DD (varsayılan: end - days + 1)")
    ap.add_argument("--end", help="YYYY-MM-DD (varsayılan: dün UTC)")
    ap.add_argument("--symbols", help="virgüllü PERP sembolleri (ör. BTCUSDT,ETHUSDT)")
    ap.add_argument("--only", choices=("metrics", "bookDepth", "funding"))
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--bucket-min", type=int, default=BUCKET_MIN_DEFAULT, help="bookDepth dilim dakikası")
    ap.add_argument("--checkpoint", default=DEFAULT_CKPT)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--no-verify", action="store_true", help="sha256 doğrulamasını atla")
    ap.add_argument("--funding-rest-all", action="store_true", help="tüm aylar REST'ten (mark_price doldurur)")
    ap.add_argument("--map-only", action="store_true")
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args(argv)
    return validate(args) if args.validate else run(args)


if __name__ == "__main__":
    sys.exit(main())
