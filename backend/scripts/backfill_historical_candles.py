"""historical_candles GERİ DOLDURMA (2026-10-16) — son N gün, 5m, radar evreni.

AMAÇ: Backtest/replay harness'ı `historical_candles` tablosunu okur; tablo yalnız
~98 sembol × 7 günü kapsıyordu. Bu betik, pencere içinde `monitoring_notifications`
veya `velocity_candidates` (passes=true) tablosunda görünen HER sembol için Binance
TR public REST'ten 5m mumları çeker ve tabloya `ON CONFLICT DO NOTHING` ile yazar
(canlı toplayıcının yazdığı satırlar asla ezilmez).

YÖNTEM:
  * Evren: pencere başlangıcından (Europe/Istanbul gece yarısı, `--days` gün önce)
    bugüne kadar iki tabloda geçen farklı semboller (veya `--symbols`).
  * Eksik aralık: sembolün mevcut satırlarından baş (pencere başı → ilk satır), kuyruk
    (son satır → şimdi) ve ≥ `--min-gap-bars` bar'lık iç boşluklar hesaplanır; yalnız
    bunlar çekilir (kapsanan günler için istek harcanmaz).
  * İstek: `app.binance_tr_public.historical_klines` (1000'lik sayfalama, ağırlık/
    rate-limit/soğuma mantığı modülün kendisinde — burada sıkı döngü YOK). En çok
    `--concurrency` (≤3) sembol eşzamanlı. `BinanceCooldownError` olursa soğuma
    süresi kadar beklenip aynı aralık yeniden denenir (limitler düşürülmez).
  * Kline satırı: [open_ms, open, high, low, close, volume, close_ms, quote_volume,
    trade_count, ...]. Yalnız KAPANMIŞ barlar (close_ms < şimdi) yazılır.
  * Checkpoint: biten semboller JSON dosyasına yazılır; yeniden çalıştırma kaldığı
    yerden sürer (`--fresh` ile sıfırlanır). Geçersiz/delist sembol (HTTP 400)
    loglanır ve atlanır.

KULLANIM (backend/ içinden):
    .venv/Scripts/python.exe scripts/backfill_historical_candles.py --days 30 --timeframe 5m
    ... --symbols AAVETRY,ADATRY --dry-run
Ortam: DATABASE_URL (Postgres) gerekir.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000}
DAY_MS = 86_400_000
_TZ_FALLBACK = dt.timezone(dt.timedelta(hours=3))  # Europe/Istanbul (DST yok)

_DEFAULT_CKPT = os.path.join(tempfile.gettempdir(), "backfill_historical_candles.checkpoint.json")


def _istanbul_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Istanbul")
    except Exception:
        return _TZ_FALLBACK


def window_start_ms(days: int, now_s: float | None = None) -> int:
    """Pencere başı: Istanbul'da `days` gün önceki gece yarısı (ms, UTC epoch)."""
    tz = _istanbul_tz()
    now = dt.datetime.fromtimestamp(now_s if now_s is not None else time.time(), tz)
    start = (now - dt.timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def load_universe(conn, start_s: float) -> list[str]:
    rows = conn.execute(
        "SELECT symbol FROM monitoring_notifications WHERE detected_at >= %s "
        "UNION SELECT symbol FROM velocity_candidates WHERE passes AND created_at >= %s",
        (start_s, start_s)).fetchall()
    return sorted({str(r[0]).upper() for r in rows if r[0]})


def existing_open_times(conn, symbol: str, tf: str, start_ms: int) -> list[int]:
    rows = conn.execute(
        "SELECT open_time FROM historical_candles WHERE symbol=%s AND timeframe=%s "
        "AND open_time >= %s ORDER BY open_time", (symbol, tf, start_ms)).fetchall()
    return [int(r[0]) for r in rows]


def missing_ranges(times: list[int], start_ms: int, last_bar_ms: int, bar_ms: int,
                   min_gap_bars: int) -> list[tuple[int, int]]:
    """Eksik [from_ms, to_ms] open_time aralıkları (uçlar dahil). Boş = tam kapsam.

    Baş ve kuyruk boşlukları eşik: ≥ 1 bar; iç boşluklar: ≥ `min_gap_bars` bar
    (az işlem gören sembollerde boş 5m aralıkları normaldir, bunlar için istek harcanmaz).
    """
    first_grid = ((start_ms + bar_ms - 1) // bar_ms) * bar_ms
    if not times:
        return [(first_grid, last_bar_ms)] if last_bar_ms >= first_grid else []
    out: list[tuple[int, int]] = []
    # Baş: ilk satır pencere başından ≥ min_gap_bars sonra ise geçmişi çek.
    if times[0] - first_grid >= bar_ms * max(1, min_gap_bars):
        out.append((first_grid, times[0] - bar_ms))
    for a, b in zip(times, times[1:]):
        if (b - a) // bar_ms - 1 >= min_gap_bars:
            out.append((a + bar_ms, b - bar_ms))
    if last_bar_ms - times[-1] >= bar_ms * max(1, min_gap_bars):
        out.append((times[-1] + bar_ms, last_bar_ms))
    return out


def kline_to_row(symbol: str, tf: str, k, source: str, fetched_at: float, now_ms: int):
    """Binance kline → tablo satırı; kapanmamış / bozuk satır için None."""
    try:
        open_ms = int(k[0])
        close_ms = int(k[6])
        if close_ms >= now_ms:
            return None
        # 2026-10-17: [9]/[10] taker alış hacmi (baz / TL); 9 kolonlu eski yanıtta None.
        tb_base = float(k[9]) if len(k) > 10 else None
        tb_quote = float(k[10]) if len(k) > 10 else None
        return (symbol, tf, open_ms, close_ms, float(k[1]), float(k[2]), float(k[3]),
                float(k[4]), float(k[5]), float(k[7]), int(k[8]), source, fetched_at, tb_base, tb_quote)
    except (TypeError, ValueError, IndexError):
        return None


# 2026-10-17: çakışmada YALNIZ eksik taker alanları doldurulur (canlı toplayıcının OHLCV'si ezilmez).
_INSERT_SQL = (
    "INSERT INTO historical_candles (symbol,timeframe,open_time,close_time,open,high,low,"
    "close,volume,quote_volume,trade_count,source,fetched_at,taker_buy_base_volume,taker_buy_quote_volume) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
    "ON CONFLICT (symbol,timeframe,open_time) DO UPDATE SET "
    "taker_buy_base_volume=EXCLUDED.taker_buy_base_volume, taker_buy_quote_volume=EXCLUDED.taker_buy_quote_volume "
    "WHERE historical_candles.taker_buy_quote_volume IS NULL AND EXCLUDED.taker_buy_quote_volume IS NOT NULL")


def insert_rows(db_url: str, rows: list[tuple]) -> int:
    """Eklenen + taker'ı doldurulan satır sayısı (zaten dolu çakışmalar sayılmaz)."""
    if not rows:
        return 0
    import psycopg
    inserted = 0
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            for i in range(0, len(rows), 2000):
                chunk = rows[i:i + 2000]
                cur.executemany(_INSERT_SQL, chunk)
                inserted += max(0, int(cur.rowcount or 0))
        conn.commit()
    return inserted


def _load_ckpt(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_ckpt(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=0)
    os.replace(tmp, path)


async def _fetch_range(historical_klines, cooldown_cls, symbol: str, tf: str,
                       from_ms: int, to_ms: int, bar_ms: int):
    """[from_ms, to_ms] aralığı için kline'lar; soğuma hatasında bekleyip yeniden dener."""
    # historical_klines başlangıcı `end - days_back*86400s` olarak hesaplar; tam gün
    # sayısına yukarı yuvarlanır (fazlalık ON CONFLICT DO NOTHING ile zararsız).
    end_ms = to_ms + bar_ms
    days_back = max(1, int(math.ceil((end_ms - from_ms) / DAY_MS)))
    for attempt in range(1, 9):
        try:
            return await historical_klines(symbol, tf, days_back, end_time_ms=end_ms)
        except cooldown_cls as exc:
            wait = min(max(float(exc.remaining), 5.0), 120.0) + 2.0
            print(f"  [{symbol}] soğuma ({exc.reason}) — {wait:.0f} sn bekleniyor "
                  f"(deneme {attempt})", flush=True)
            await asyncio.sleep(wait)
    raise RuntimeError("soğuma penceresi tekrarlı açıldı; sembol sonraya bırakıldı")


async def run(args) -> int:
    import psycopg
    from app import binance_tr_public as btp

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("DATABASE_URL gerekli", file=sys.stderr)
        return 2
    tf = args.timeframe
    bar_ms = TF_MS[tf]
    now_ms = int(time.time() * 1000)
    start_ms = window_start_ms(args.days)
    last_bar_ms = (now_ms // bar_ms) * bar_ms - bar_ms  # son kapanmış barın open_time'ı
    print(f"Pencere: {dt.datetime.fromtimestamp(start_ms/1000, _istanbul_tz()):%Y-%m-%d %H:%M} .. "
          f"{dt.datetime.fromtimestamp(now_ms/1000, _istanbul_tz()):%Y-%m-%d %H:%M} (Istanbul), tf={tf}",
          flush=True)

    with psycopg.connect(db_url, connect_timeout=10) as conn:
        if args.symbols:
            universe = sorted({s.strip().upper() for s in args.symbols.split(",") if s.strip()})
        elif args.universe_from_candles:
            universe = [r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='5m' ORDER BY 1").fetchall()]
        else:
            universe = load_universe(conn, start_ms / 1000.0)
        print(f"Evren: {len(universe)} sembol", flush=True)
        plans: dict[str, list[tuple[int, int]]] = {}
        for sym in universe:
            if args.refill_taker:
                # 2026-10-17: taker kolonlarını mevcut satırlar için de doldurmak üzere TÜM pencere çekilir.
                plans[sym] = [(start_ms, last_bar_ms)]
                continue
            times = existing_open_times(conn, sym, tf, start_ms)
            plans[sym] = missing_ranges(times, start_ms, last_bar_ms, bar_ms, args.min_gap_bars)

    ckpt_path = args.checkpoint
    ckpt = {} if args.fresh else _load_ckpt(ckpt_path)
    key = f"{tf}:{start_ms}" + (":taker" if args.refill_taker else "")
    done = set(ckpt.get(key, {}).get("done", []))
    failed: dict[str, str] = dict(ckpt.get(key, {}).get("failed", {}))
    invalid: dict[str, str] = dict(ckpt.get(key, {}).get("invalid", {}))

    todo = [s for s in universe if plans[s] and s not in done and s not in invalid]
    full = [s for s in universe if not plans[s]]
    print(f"Tam kapsanan: {len(full)}, çekilecek: {len(todo)}, checkpoint'te biten: "
          f"{len([s for s in universe if s in done])}", flush=True)
    est_bars = sum(((b - a) // bar_ms + 1) for s in todo for a, b in plans[s])
    est_req = sum(max(1, math.ceil((((b - a) // bar_ms + 1)) / 1000)) for s in todo for a, b in plans[s])
    print(f"Tahmini eksik bar: {est_bars:,}; tahmini istek: >= {est_req:,}", flush=True)
    if args.dry_run:
        for s in todo[:400]:
            rng = ", ".join(f"{dt.datetime.fromtimestamp(a/1000, _istanbul_tz()):%m-%d %H:%M}"
                            f"..{dt.datetime.fromtimestamp(b/1000, _istanbul_tz()):%m-%d %H:%M}"
                            for a, b in plans[s])
            print(f"  {s}: {rng}")
        print("DRY-RUN: veritabanına yazılmadı, REST çağrısı yapılmadı.")
        return 0

    sem = asyncio.Semaphore(max(1, min(8, args.concurrency)))
    stats = {"inserted": 0, "fetched": 0, "n": 0}
    t0 = time.time()
    lock = asyncio.Lock()

    async def one(sym: str):
        async with sem:
            sym_inserted = sym_fetched = 0
            try:
                for a, b in plans[sym]:
                    kl = await _fetch_range(btp.historical_klines, btp.BinanceCooldownError,
                                            sym, tf, a, b, bar_ms)
                    fetched_at = time.time()
                    now_ms2 = int(time.time() * 1000)
                    rows = []
                    for k in kl or []:
                        r = kline_to_row(sym, tf, k, args.source, fetched_at, now_ms2)
                        if r is not None and a <= r[2] <= b:
                            rows.append(r)
                    sym_fetched += len(rows)
                    sym_inserted += await asyncio.to_thread(insert_rows, db_url, rows)
                outcome = "ok"
            except Exception as exc:  # noqa: BLE001 — sembol bazlı izolasyon
                msg = str(exc)
                if "HTTP 400" in msg or "Invalid symbol" in msg:
                    invalid[sym] = msg[:160]
                    outcome = f"GEÇERSİZ/delist ({msg[:100]})"
                else:
                    failed[sym] = msg[:160]
                    outcome = f"HATA ({msg[:100]})"
            async with lock:
                stats["inserted"] += sym_inserted
                stats["fetched"] += sym_fetched
                stats["n"] += 1
                if outcome == "ok":
                    done.add(sym)
                    failed.pop(sym, None)
                ckpt[key] = {"done": sorted(done), "failed": failed, "invalid": invalid}
                _save_ckpt(ckpt_path, ckpt)
                print(f"[{stats['n']}/{len(todo)}] {sym}: çekilen={sym_fetched} eklenen={sym_inserted} "
                      f"{outcome} (toplam eklenen={stats['inserted']:,}, {time.time()-t0:.0f} sn)",
                      flush=True)

    await asyncio.gather(*[one(s) for s in todo])
    print(f"BİTTİ: eklenen={stats['inserted']:,} çekilen={stats['fetched']:,} "
          f"geçersiz={len(invalid)} hatalı={len(failed)} süre={time.time()-t0:.0f} sn", flush=True)
    if failed:
        print("Hatalı semboller (yeniden çalıştırınca denenir):", ", ".join(sorted(failed)))
    if invalid:
        print("Geçersiz semboller:", ", ".join(f"{k}" for k in sorted(invalid)))
    coverage_report(db_url, universe, tf, start_ms, last_bar_ms, bar_ms, args.coverage_out)
    return 0


def coverage_report(db_url: str, universe: list[str], tf: str, start_ms: int,
                    last_bar_ms: int, bar_ms: int, out_path: str | None) -> None:
    """Sembol başına kapsama tablosu (pencere beklenen bar sayısına göre)."""
    import psycopg
    first_grid = ((start_ms + bar_ms - 1) // bar_ms) * bar_ms
    expected = (last_bar_ms - first_grid) // bar_ms + 1
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        rows = conn.execute(
            "SELECT symbol, count(*), min(open_time), max(open_time) FROM historical_candles "
            "WHERE timeframe=%s AND open_time >= %s AND symbol = ANY(%s) GROUP BY symbol",
            (tf, start_ms, universe)).fetchall()
    by = {r[0]: r for r in rows}
    tz = _istanbul_tz()
    f = lambda ms: dt.datetime.fromtimestamp(ms / 1000, tz).strftime("%m-%d %H:%M")
    lines = [f"Beklenen bar/sembol (pencere): {expected}  tf={tf}",
             f"{'sembol':<14}{'bar':>7}{'kapsama%':>10}{'vs_ilk_bar%':>13}  ilk .. son"]
    n90 = npart = nnone = 0
    for s in universe:
        r = by.get(s)
        if not r:
            nnone += 1
            lines.append(f"{s:<14}{0:>7}{0.0:>10.1f}{'-':>13}  (veri yok)")
            continue
        cnt, mn, mx = int(r[1]), int(r[2]), int(r[3])
        pct = 100.0 * cnt / expected
        exp_after_first = (last_bar_ms - mn) // bar_ms + 1
        pct2 = 100.0 * cnt / max(1, exp_after_first)
        if pct >= 90:
            n90 += 1
        else:
            npart += 1
        lines.append(f"{s:<14}{cnt:>7}{pct:>10.1f}{pct2:>13.1f}  {f(mn)} .. {f(mx)}")
    lines.append(f"ÖZET: >=90%: {n90}, kısmi: {npart}, hiç: {nnone}, toplam: {len(universe)}")
    text = "\n".join(lines)
    print(text)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="historical_candles geri doldurma (Binance TR public REST)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--timeframe", default="5m", choices=sorted(TF_MS))
    ap.add_argument("--symbols", default="", help="virgülle ayrık; boşsa evren DB'den")
    ap.add_argument("--universe-from-candles", action="store_true",
                    help="evren: historical_candles 5m'de bulunan tüm semboller (90+ günlük çekim için)")
    ap.add_argument("--source", default="backfill")
    ap.add_argument("--concurrency", type=int, default=2, help="eşzamanlı sembol (<=8; ağırlık/soğuma modülde)")
    ap.add_argument("--refill-taker", action="store_true",
                    help="tüm pencereyi yeniden çek; mevcut satırların boş taker kolonlarını doldur (migration 020)")
    ap.add_argument("--min-gap-bars", type=int, default=24,
                    help="bu kadar ardışık eksik barlık iç boşluk yeniden çekilir (varsayılan 24 = 2 saat)")
    ap.add_argument("--checkpoint", default=_DEFAULT_CKPT)
    ap.add_argument("--fresh", action="store_true", help="checkpoint'i yok say")
    ap.add_argument("--coverage-out", default="", help="kapsama tablosunun yazılacağı dosya")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
