"""MA BUY REPLAY — CANLI SEMBOL SEÇİMİYLE (sabit liste değil; sistem nasıl seçiyorsa öyle).

AMAÇ (2026-10-20, kullanıcı isteği): "Replay, sistem nasıl çalışıyorsa aynı mantıkla olmalı." Canlı zincir:
    her 10 dk  → tüm TRY çiftleri 24 sa değişime göre sıralanır, ilk 50 izlenen evren olur (refresh_top_gainer_symbols)
    her saat   → izlenen semboller aktivite filtresinden geçer, AKTİF olanlar kalır (refresh_symbol_activity)
    her 30 sn  → MA izleyici yalnız AKTİF sembolleri tarar (ma_buy_tracker.active_symbols)
Bu betik aynı zinciri geçmiş mumlardan yeniden üretir (app/ma_buy_replay_universe.py, saf + testli) ve MA BUY sinyalini
yalnız mumu kapandığı anda sembol taranan kümedeyse sayar. Ölçüm (bir sonraki sinyale kadar MFE) app/ma_buy_replay.py.

VERİ: Binance TR herkese açık klines. 5m: TÜM TRY çiftleri (24 sa değişim/hacim + aktivite). 1m: yalnız en az bir kez
izlenen evrene giren semboller (M1 düz mum / pasiflik analizi). Diğer TF'ler: yalnız taranan semboller. Disk önbelleği:
work/ma_buy_replay_cache/live_*.json (gün damgalı; tekrar koşu ağa gitmez).

KULLANIM:
    python backend/scripts/ma_buy_replay_live_universe.py --days 7
    python backend/scripts/ma_buy_replay_live_universe.py --days 30 --tfs 5m,15m,30m,1h
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import ma_buy_replay, ma_buy_replay_universe as uni, ma_buy_rules, ma_buy_signals, ma_buy_tracker   # noqa: E402
from app.binance_tr_public import historical_klines, trading_symbols                              # noqa: E402
from app.config import config                                                                      # noqa: E402
from app.ma_buy_notify import target_pct, tf_label                                                 # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_DIR = os.path.join(ROOT, "work", "ma_buy_replay_cache")
DOCS_DIR = os.path.abspath(os.path.join(ROOT, "..", "docs"))
TZ = dt.timezone(dt.timedelta(hours=3))
DAY_MS = 86_400_000
WARMUP_DAYS = {"1m": 1, "5m": 2, "15m": 2, "30m": 3, "1h": 5}


async def fetch_rows_api(symbol: str, tf: str, fetch_days: int, now_ms: int, use_cache: bool, sem: asyncio.Semaphore) -> list:
    """Borsadan (önbellekli) tam aralık."""
    stamp = dt.datetime.fromtimestamp(now_ms / 1000, TZ).strftime("%Y%m%d")
    path = os.path.join(CACHE_DIR, f"live_{symbol}_{tf}_{fetch_days}d_{stamp}.json")
    if use_cache and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    async with sem:
        rows = await historical_klines(symbol, tf, fetch_days, end_time_ms=now_ms)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    return rows


async def fetch_tail_api(symbol: str, tf: str, after_open_ms: int, now_ms: int, sem: asyncio.Semaphore) -> list:
    """Arşivin kuyruğu eskiyse yalnız eksik kısım (after_open_ms sonrası) borsadan."""
    from app.binance_tr_public import klines
    out, cursor = [], int(after_open_ms) + 1
    while cursor < now_ms:
        async with sem:
            batch = await klines(symbol, tf, 1000, cursor, now_ms)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1][0]) + 1
    return out


DB_BASE_TF = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "15m", "1h": "15m"}   # 30m/1h → 15m'den türetilir
STALE_TAIL_MS = 6 * 3_600_000


async def fetch_rows(symbol: str, tf: str, fetch_days: int, now_ms: int, use_cache: bool, sem: asyncio.Semaphore,
                     source: str = "db") -> list:
    """Mum satırları: varsayılan kaynak veritabanı arşivi (historical_candles); 30m/1h 15m'den kurulur; arşivde yoksa
    borsadan tam aralık, kuyruğu 6 saatten eskiyse yalnız kuyruk borsadan tamamlanır."""
    tf_ms = ma_buy_tracker.SUPPORTED_TF_MS[tf]
    if source != "db":
        return await fetch_rows_api(symbol, tf, fetch_days, now_ms, use_cache, sem)
    from app import database
    base = DB_BASE_TF[tf]
    base_ms = ma_buy_tracker.SUPPORTED_TF_MS[base]
    start_ms = now_ms - int(fetch_days) * DAY_MS
    rows = uni.db_rows_to_klines(await database.get_market_candles(symbol, base, start_ms=start_ms, end_ms=now_ms))
    if not rows:
        rows = await fetch_rows_api(symbol, base, fetch_days, now_ms, use_cache, sem)
    elif rows[-1][0] < now_ms - base_ms - STALE_TAIL_MS:
        rows = rows + await fetch_tail_api(symbol, base, rows[-1][0], now_ms, sem)
    if base != tf:
        rows = uni.aggregate_klines(rows, base_ms, tf_ms)
    return rows


async def load_runtime_overrides() -> dict:
    try:
        from app import database
        raw = await asyncio.wait_for(database.get_llm_setting("runtime_config", "{}"), 15)
        return json.loads(raw or "{}")
    except Exception as exc:  # noqa: BLE001
        print(f"[uyarı] runtime_config okunamadı ({exc}); kod varsayılanları kullanılacak", file=sys.stderr)
        return {}


async def gather_with_progress(coros, label: str):
    done, out = 0, []
    for coro in asyncio.as_completed(coros):
        out.append(await coro)
        done += 1
        if done % 50 == 0 or done == len(coros):
            print(f"  {label}: {done}/{len(coros)}", file=sys.stderr)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--tfs", default="5m,15m,30m,1h")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out-tag", default=None)
    ap.add_argument("--extra-rules", action="store_true",
                    help="2026-10-21 kullanıcı tablosu: M15 gövde ≥ %%1 + RSI 45-65; M30 MACD hist artıyor + ADX > 20; "
                         "H1 son 3 mum yükseliş + dalga ≥ %%2 + RSI 45-65 + ADX > 20 (app/ma_buy_rules.py)")
    ap.add_argument("--source", choices=("db", "api"), default="db",
                    help="mum kaynagi: db = historical_candles arsivi (30m/1h 15m'den), api = borsadan (onbellekli)")
    args = ap.parse_args()

    tfs = [t.strip() for t in args.tfs.split(",") if t.strip() in ma_buy_tracker.SUPPORTED_TF_MS]
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - args.days * DAY_MS
    use_cache = not args.no_cache
    sem = asyncio.Semaphore(max(1, args.concurrency))

    overrides = uni.apply_runtime_overrides(await load_runtime_overrides())
    settings = uni.selection_settings()
    per = ma_buy_tracker.periods()
    use_sma = str(getattr(config, "MA_BUY_MA_TYPE", "sma")).strip().lower() == "sma"
    universe = sorted(await trading_symbols("TRY"))
    print(f"Canlı evren replay: {len(universe)} TRY çifti, {args.days} gün, TF {tfs} | ilk {settings['TOP_GAINERS_LIMIT']} "
          f"yükselen / {settings['TOP_GAINERS_REFRESH_SEC']} sn, aktivite / {settings['SYMBOL_ACTIVITY_REFRESH_SEC']} sn | "
          f"MA {per} {'SMA' if use_sma else 'EMA'} | runtime override: {overrides}")

    # 1) 5m: tüm evren → 24 sa ticker karşılığı (her 10 dk)
    gainer_period = int(settings["TOP_GAINERS_REFRESH_SEC"]) * 1000
    activity_period = int(settings["SYMBOL_ACTIVITY_REFRESH_SEC"]) * 1000
    gainer_marks = uni.refresh_marks(start_ms - activity_period, now_ms, gainer_period)
    activity_marks = uni.refresh_marks(start_ms, now_ms, activity_period, offset_ms=20_000)
    stats_by_mark: list[dict] = [dict() for _ in gainer_marks]
    fetch_errors: list[str] = []

    async def pass1(symbol: str):
        try:
            rows = await fetch_rows(symbol, "5m", args.days + WARMUP_DAYS["5m"], now_ms, use_cache, sem, args.source)
        except Exception as exc:  # noqa: BLE001
            fetch_errors.append(f"{symbol} 5m: {exc}")
            return
        series = uni.ticker_stats_series(uni.parse_rows(rows), gainer_marks)
        for i, st in enumerate(series):
            if st is not None:
                stats_by_mark[i][symbol] = st

    await gather_with_progress([pass1(s) for s in universe], "5m evren")
    limit = int(settings["TOP_GAINERS_LIMIT"])
    tracked_by_gmark = [uni.rank_top_gainers(stats, limit) for stats in stats_by_mark]

    def tracked_at(t_ms: int) -> list[str]:
        idx = None
        for i, g in enumerate(gainer_marks):
            if g <= t_ms:
                idx = i
        return tracked_by_gmark[idx] if idx is not None else []

    tracked_by_amark = [tracked_at(t) for t in activity_marks]
    ever_tracked = sorted(uni.symbols_ever(tracked_by_amark))
    print(f"  izlenen evrene en az bir kez giren sembol: {len(ever_tracked)} ({len(activity_marks)} saatlik anlık görüntü)",
          file=sys.stderr)

    # 2) 1m (yalnız izlenenler) + aktivite kararı
    active_by_amark: list[set] = [set() for _ in activity_marks]
    status_counter: Counter = Counter()

    async def pass2(symbol: str):
        try:
            rows5 = await fetch_rows(symbol, "5m", args.days + WARMUP_DAYS["5m"], now_ms, use_cache, sem, args.source)
            rows1 = await fetch_rows(symbol, "1m", args.days + WARMUP_DAYS["1m"], now_ms, use_cache, sem, args.source)
        except Exception as exc:  # noqa: BLE001
            fetch_errors.append(f"{symbol} 1m: {exc}")
            return
        p5, p1 = uni.parse_rows(rows5), uni.parse_rows(rows1)
        marks = [t for i, t in enumerate(activity_marks) if symbol in tracked_by_amark[i]]
        qv = uni.ticker_stats_series(p5, marks)
        for (i, t), st in zip([(i, t) for i, t in enumerate(activity_marks) if symbol in tracked_by_amark[i]], qv):
            m5 = uni.history_upto(p5, t, uni.M5_HISTORY_BARS)
            m1 = uni.history_upto(p1, t, uni.M1_HISTORY_BARS)
            res = uni.activity_status(m5, m1, quote_volume=(st or {}).get("quote_volume", 0.0), now_ms=t)
            status_counter[res["status"]] += 1
            if res["status"] == "ACTIVE":
                active_by_amark[i].add(symbol)

    await gather_with_progress([pass2(s) for s in ever_tracked], "aktivite")
    timeline = [{"at_ms": t, "active": active_by_amark[i], "tracked": set(tracked_by_amark[i])}
                for i, t in enumerate(activity_marks)]
    scanned_sets = [uni.membership_at(timeline, t) for t in activity_marks]
    scan_symbols = sorted(uni.symbols_ever(scanned_sets))
    fallback_hours = sum(1 for i, s in enumerate(scanned_sets) if not active_by_amark[i] and s)
    print(f"  taranan küme: {len(scan_symbols)} sembol; saat başına ortalama aktif {statistics.fmean(len(a) for a in active_by_amark):.1f}"
          f" (izlenene düşen saat: {fallback_hours})", file=sys.stderr)

    # 3) MA BUY sinyalleri — mum kapanışında sembol taranan kümedeyse
    rows_out: list[dict] = []
    raw_signal_count = 0
    rule_drops: Counter = Counter()

    async def pass3(symbol: str, tf: str):
        nonlocal raw_signal_count
        tf_ms = ma_buy_tracker.SUPPORTED_TF_MS[tf]
        try:
            rows = await fetch_rows(symbol, tf, args.days + WARMUP_DAYS.get(tf, 2), now_ms, use_cache, sem, args.source)
        except Exception as exc:  # noqa: BLE001
            fetch_errors.append(f"{symbol} {tf}: {exc}")
            return
        bars = ma_buy_tracker.closed_bars(rows, tf_ms, now_ms)
        if len(bars) < max(per) + 2:
            return
        signals = ma_buy_signals.detect_ma_buy([b["close"] for b in bars], per, use_sma=use_sma, slow_cross=True,
                                               stoch_max=ma_buy_tracker.stoch_max(tf))
        if args.extra_rules:
            signals, dropped = ma_buy_rules.apply_rules(tf, bars, signals, ma_buy_rules.feature_series(bars))
            for d in dropped:
                if bars[d["index"]]["open_ms"] + tf_ms >= start_ms:
                    rule_drops[f"{tf}: {d['reason'].split(' (')[0]}"] += 1
        kept = []
        for sig in signals:
            close_ms = bars[sig["index"]]["open_ms"] + tf_ms
            if close_ms < start_ms:
                continue
            raw_signal_count += 1
            if symbol in uni.membership_at(timeline, close_ms):
                kept.append(sig)
        rows_out.extend(ma_buy_replay.outcomes_for_signals(bars, kept, tf=tf, target_pct=target_pct(tf), symbol=symbol))

    await gather_with_progress([pass3(s, tf) for s in scan_symbols for tf in tfs], "MA sinyalleri")

    rows_out.sort(key=lambda r: (r["timeframe"], r["symbol"], r["signal_time_ms"]))
    agg = ma_buy_replay.aggregate(rows_out)
    generated = dt.datetime.fromtimestamp(now_ms / 1000, TZ)
    tag = args.out_tag or f"{args.days}g_{generated.strftime('%Y-%m-%d')}"
    meta = {"days": args.days, "symbols": f"{len(scan_symbols)} (canlı seçim; evren {len(universe)})",
            "generated_at": generated.strftime("%Y-%m-%d %H:%M"),
            "rules_text": f"{'SMA' if use_sma else 'EMA'} {'/'.join(str(p) for p in per)}, "
                          f"StochRSI K ≤ {getattr(config, 'MA_BUY_STOCH_MAX', 80):g} ({getattr(config, 'MA_BUY_STOCH_OFF_TIMEFRAMES', '1m')} hariç)",
            "selection": settings, "overrides": overrides, "fetch_errors": fetch_errors,
            "extra_rules": bool(args.extra_rules), "rule_drops": dict(rule_drops)}

    # Evren bölümü
    active_counts = [len(a) for a in active_by_amark]
    hours_active: Counter = Counter()
    for a in active_by_amark:
        hours_active.update(a)
    uni_lines = ["", "## Canlı sembol seçimi (yeniden üretim)", "",
                 f"- Her {settings['TOP_GAINERS_REFRESH_SEC']} sn: 24 sa yükselenler ilk {settings['TOP_GAINERS_LIMIT']} "
                 f"(5m mumlardan: son kapanış / 24 sa önceki kapanış; 24 sa quote hacim). Her {settings['SYMBOL_ACTIVITY_REFRESH_SEC']} sn: "
                 f"aktivite filtresi (hacim ≥ {settings['SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY']:,.0f} TL, 15 dk aralık ≥ "
                 f"%{settings['SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT']}, ATR ≥ {settings['SYMBOL_ACTIVITY_MIN_ATR_PCT']}, hacim oranı ≥ "
                 f"{settings['SYMBOL_ACTIVITY_MIN_VOLUME_RATIO']}, M1 düz mum filtresi "
                 f"{'açık' if settings['SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED'] else 'kapalı'} "
                 f"[5/{settings['SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT']}, 30/{settings['SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT']}], kapsamlı pasiflik analizi).",
                 f"- Saatlik anlık görüntü: {len(activity_marks)}; izlenen evrene giren sembol: {len(ever_tracked)}; "
                 f"saat başına AKTİF: ortalama {statistics.fmean(active_counts):.1f}, en az {min(active_counts) if active_counts else 0}, "
                 f"en çok {max(active_counts) if active_counts else 0}; aktif küme boş olup izlenen listeye düşülen saat: {fallback_hours}.",
                 f"- Aktivite kararları: {dict(status_counter)}. Sinyal elemesi: {raw_signal_count} ham sinyalden "
                 f"{len(rows_out)} tanesi o anda taranan sembolde (kalanı sistem görmezdi).",
                 "", "| Sembol | Aktif saat | Sinyal |", "|---|---:|---:|"]
    sig_count = Counter(r["symbol"] for r in rows_out)
    for sym, h in hours_active.most_common(20):
        uni_lines.append(f"| {sym} | {h} | {sig_count.get(sym, 0)} |")
    uni_lines += ["", "Sadeleştirmeler: açık paper pozisyonlarının evrene eklenmesi yok; ticker `priceChangePercent` yerine 5m "
                  "kapanış oranı; `_m1_activity_features` karara girmediği için hesaplanmadı; aktivite kararı yalnız izlenen "
                  "sembollerde (canlıda izlenmeyen sembolün 5m serisi olmadığından WARMING kalır)."]

    os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)
    json_path = os.path.join(ROOT, "work", f"ma_buy_replay_canli_evren_{tag}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "aggregate": agg, "rows": rows_out,
                   "timeline": [{"at_ms": s["at_ms"], "active": sorted(s["active"]), "tracked": sorted(s["tracked"])} for s in timeline]},
                  fh, ensure_ascii=False, indent=1)
    md = ma_buy_replay.render_markdown(rows_out, agg, meta).replace(
        "# MA BUY 7 günlük replay", f"# MA BUY {args.days} günlük replay (CANLI sembol seçimiyle)")
    if args.extra_rules:
        uni_lines += ["", "## Ek kurallar (2026-10-21 tablosu)", "",
                      "M15: mum gövdesi ≥ %1 (yükseliş) ve RSI14 45–65 · M30: MACD(12,26,9) histogramı artıyor ve ADX14 > 20 · "
                      "H1: son 3 mum yükseliş, 3 mumluk aralık ≥ %2, RSI14 45–65, ADX14 > 20 · M5: ek kural yok (karşılaştırma).",
                      "", "| Elenme nedeni | Sinyal |", "|---|---:|"]
        uni_lines += [f"| {k} | {v} |" for k, v in sorted(rule_drops.items(), key=lambda kv: -kv[1])]
    md += "\n".join(uni_lines) + "\n"
    if fetch_errors:
        md += "\n## Veri hataları\n\n" + "\n".join(f"- {e}" for e in fetch_errors[:50]) + "\n"
    os.makedirs(DOCS_DIR, exist_ok=True)
    md_path = os.path.join(DOCS_DIR, f"MA_BUY_REPLAY_CANLI_EVREN_{tag}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    print(f"\nRapor: {md_path}\nHam veri: {json_path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
