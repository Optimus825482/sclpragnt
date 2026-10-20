"""MA BUY 7 GÜNLÜK REPLAY — sinyal sonrası EN YÜKSEK yükseliş (bir sonraki sinyale kadar).

AMAÇ (2026-10-20, kullanıcı isteği): M1/M5/M15/M30/H1 MA kesişim BUY sinyallerini son 7 günün mumlarıyla,
canlı motorla (app/ma_buy_tracker + app/ma_buy_signals) BİREBİR aynı kural ve parametrelerle yeniden üretip her
sinyalden sonra fiyatın en fazla ne kadar yükseldiğini ölçmek. Ölçüm matematiği app/ma_buy_replay.py (saf, testli).

NASIL ÇALIŞIR:
    1. Sembol evreni: varsayılan `aktif ∪ izlenen` (symbol_activity_status = ACTIVE + config.SYMBOLS; canlı motor
       aktif listeyi, boşsa izleneni tarar). `--scope all` tüm TRY çiftleri, `--symbols A,B` elle liste.
    2. Her sembol × TF için Binance TR herkese açık klines ucundan 7 gün (+ MA(99) ısınması için 99 mum) çekilir,
       `work/ma_buy_replay_cache/` altına gün damgalı JSON olarak önbelleklenir (tekrar çalıştırmak ağa gitmez).
    3. Sinyaller detect_ma_buy ile üretilir; her sinyal için bir sonraki sinyale kadar MFE, zirveye süre,
       sabit ufuklar ve TF hedefine dokunma hesaplanır.
    4. Çıktı: docs/MA_BUY_REPLAY_7G_<tarih>.md (rapor) + work/ma_buy_replay_<tarih>.json (ham satırlar).

KULLANIM:
    python backend/scripts/ma_buy_replay_7d.py
    python backend/scripts/ma_buy_replay_7d.py --days 7 --tfs 1m,5m,15m,30m,1h --scope active_tracked
    python backend/scripts/ma_buy_replay_7d.py --symbols BTCTRY,ETHTRY --no-cache
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import ma_buy_replay, ma_buy_signals, ma_buy_tracker          # noqa: E402
from app.binance_tr_public import historical_klines, trading_symbols   # noqa: E402
from app.config import config                                           # noqa: E402
from app.ma_buy_notify import target_pct                               # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_DIR = os.path.join(ROOT, "work", "ma_buy_replay_cache")
DOCS_DIR = os.path.abspath(os.path.join(ROOT, "..", "docs"))
TZ = dt.timezone(dt.timedelta(hours=3))


async def resolve_symbols(scope: str, explicit: str | None) -> list[str]:
    if explicit:
        return sorted({s.strip().upper() for s in explicit.split(",") if s.strip()})
    if scope == "all":
        return sorted(await trading_symbols("TRY"))
    tracked = sorted({str(s).upper() for s in (config.SYMBOLS or []) if s})
    active: list[str] = []
    try:
        from app import database
        raw = await asyncio.wait_for(database.get_llm_setting("symbol_activity_status", "{}"), 15)
        statuses = json.loads(raw or "{}")
        active = sorted(str(sym).upper() for sym, item in (statuses or {}).items()
                        if isinstance(item, dict) and str(item.get("status")).upper() == "ACTIVE")
    except Exception as exc:  # noqa: BLE001 — DB yoksa izlenen liste yeter
        print(f"[uyarı] aktif sembol listesi okunamadı ({exc}); yalnız izlenen liste kullanılacak", file=sys.stderr)
    if scope == "active":
        return active or tracked
    return sorted(set(active) | set(tracked))


async def load_bars(symbol: str, tf: str, days: int, now_ms: int, use_cache: bool, sem: asyncio.Semaphore) -> list[dict]:
    tf_ms = ma_buy_tracker.SUPPORTED_TF_MS[tf]
    warmup_days = (max(ma_buy_tracker.periods()) + 5) * tf_ms / 86_400_000
    fetch_days = days + max(1, int(warmup_days) + 1)
    stamp = dt.datetime.fromtimestamp(now_ms / 1000, TZ).strftime("%Y%m%d")
    path = os.path.join(CACHE_DIR, f"{symbol}_{tf}_{days}d_{stamp}.json")
    rows = None
    if use_cache and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
    if rows is None:
        async with sem:
            rows = await historical_klines(symbol, tf, fetch_days, end_time_ms=now_ms)
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
    return ma_buy_tracker.closed_bars(rows, tf_ms, now_ms)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--tfs", default="1m,5m,15m,30m,1h")
    ap.add_argument("--scope", choices=("active", "active_tracked", "all"), default="active_tracked")
    ap.add_argument("--symbols", default=None, help="virgüllü sembol listesi (scope'u geçersiz kılar)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out-tag", default=None, help="dosya adı eki (varsayılan tarih)")
    args = ap.parse_args()

    tfs = [t.strip() for t in args.tfs.split(",") if t.strip() in ma_buy_tracker.SUPPORTED_TF_MS]
    now_ms = int(time.time() * 1000)
    symbols = await resolve_symbols(args.scope, args.symbols)
    per = ma_buy_tracker.periods()
    use_sma = str(getattr(config, "MA_BUY_MA_TYPE", "sma")).strip().lower() == "sma"
    print(f"Replay: {len(symbols)} sembol × {tfs} × {args.days} gün | MA {per} {'SMA' if use_sma else 'EMA'} | "
          f"StochRSI sınırı: {', '.join(f'{t}:{ma_buy_tracker.stoch_max(t)}' for t in tfs)}")

    sem = asyncio.Semaphore(max(1, args.concurrency))
    window_start_ms = now_ms - args.days * 86_400_000
    rows_out: list[dict] = []
    fetch_errors: list[str] = []

    async def one(symbol: str, tf: str) -> None:
        try:
            bars = await load_bars(symbol, tf, args.days, now_ms, not args.no_cache, sem)
        except Exception as exc:  # noqa: BLE001
            fetch_errors.append(f"{symbol} {tf}: {exc}")
            return
        if len(bars) < max(per) + 2:
            return
        closes = [b["close"] for b in bars]
        signals = ma_buy_signals.detect_ma_buy(closes, per, use_sma=use_sma, slow_cross=True,
                                               stoch_max=ma_buy_tracker.stoch_max(tf))
        # Isınma dilimindeki (7 gün öncesi) sinyaller rapora girmez; ama "sonraki sinyal" zinciri için hepsi kullanılır.
        outcomes = ma_buy_replay.outcomes_for_signals(bars, signals, tf=tf, target_pct=target_pct(tf), symbol=symbol)
        rows_out.extend(o for o in outcomes if o["signal_time_ms"] >= window_start_ms)

    tasks = [one(sym, tf) for sym in symbols for tf in tfs]
    done = 0
    for coro in asyncio.as_completed(tasks):
        await coro
        done += 1
        if done % 25 == 0 or done == len(tasks):
            print(f"  {done}/{len(tasks)} sembol×TF işlendi, {len(rows_out)} sinyal", file=sys.stderr)

    rows_out.sort(key=lambda r: (r["timeframe"], r["symbol"], r["signal_time_ms"]))
    agg = ma_buy_replay.aggregate(rows_out)
    generated = dt.datetime.fromtimestamp(now_ms / 1000, TZ)
    meta = {"days": args.days, "symbols": len(symbols), "generated_at": generated.strftime("%Y-%m-%d %H:%M"),
            "rules_text": f"{'SMA' if use_sma else 'EMA'} {'/'.join(str(p) for p in per)}, "
                          f"StochRSI K ≤ {getattr(config, 'MA_BUY_STOCH_MAX', 80):g} "
                          f"({getattr(config, 'MA_BUY_STOCH_OFF_TIMEFRAMES', '1m')} hariç)",
            "scope": args.scope, "symbol_list": symbols, "fetch_errors": fetch_errors}
    tag = args.out_tag or generated.strftime("%Y-%m-%d")
    os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)
    json_path = os.path.join(ROOT, "work", f"ma_buy_replay_{tag}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "aggregate": agg, "rows": rows_out}, fh, ensure_ascii=False, indent=1)
    md = ma_buy_replay.render_markdown(rows_out, agg, meta)
    if fetch_errors:
        md += "\n## Veri hataları\n\n" + "\n".join(f"- {e}" for e in fetch_errors) + "\n"
    os.makedirs(DOCS_DIR, exist_ok=True)
    md_path = os.path.join(DOCS_DIR, f"MA_BUY_REPLAY_7G_{tag}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    print(f"\nRapor: {md_path}\nHam veri: {json_path}")
    return 0


if __name__ == "__main__":
    # Windows konsolu cp1254: rapor UTF-8 karakter (≤, —) içerir; dosyalar zaten UTF-8 yazılır.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
