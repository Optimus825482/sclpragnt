"""scalpernew MA KURDELE kuralının 90 günlük gerçekleşebilir net ölçümü (canlı evren + canlı çıkış kuralı).

AMAÇ (2026-10-21): D:/PROJELLER/scalpernew deposundaki otonom paper'ın fiilen açık tek girişi SMA 7/20/99 kurdelesi
(backend/app/ema_ribbon.py): kesişim + dilime göre RSI/ADX/MACD/aralık şartları + sıkışıklık / durağan tahta / ölü
çubuk elekleri + StochRSI ≤ 80 (M15 hariç). Oradaki backtest betiği sabit "bugünkü ilk 40" listesiyle ve hedef/stop
ızgarasında örneklem içi aramayla çalışıyor. Bu betik aynı kural fonksiyonlarını DOSYADAN yükler (iki depo da `app`
paketi kullandığı için modül farklı adla içe alınır) ve bizim araçlarla ölçer:
  * evren: scalpernew ayarı — her 10 dk 24 sa yükselenler ilk 40, saatlik aktivite filtresi, endeksli çiftler hariç
  * sinyal: mum kapandığı anda sembol taranan kümedeyse sayılır (sclpragnt canlı-evren replay zinciri)
  * çıkış: scalpernew canlı varsayılanı — hedefte satış KAPALI (tp_primary_exit_enabled=false), iz süren stop
    tetik %2 / aralık %1, stop ve tutma dilime göre (RIBBON_STOP_PCT / _RIBBON_HOLD_MINUTES), komisyon %0,1125/bacak + kayma;
    karşılaştırma için hedefte satış AÇIK varyantı da koşulur (RIBBON_TARGET_PCT).
Veri: historical_candles arşivi (1m/5m/15m; 30m/1h 15m'den).

KULLANIM:
    python backend/scripts/scalpernew_ribbon_study.py --days 90
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import importlib.util
import json
import os
import statistics
import sys
import time
from bisect import bisect_left
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import database, ma_buy_tracker, ma_buy_replay_universe as uni   # noqa: E402
from app.binance_tr_public import trading_symbols                          # noqa: E402
from app.config import config                                              # noqa: E402
from app.ma_buy_notify import tf_label                                     # noqa: E402
from app.paper_sim import simulate_exit                                    # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.abspath(os.path.join(ROOT, "..", "docs"))
TZ = dt.timezone(dt.timedelta(hours=3))
DAY_MS = 86_400_000
M15_MS = 900_000
SCALPERNEW_RIBBON = os.environ.get("SCALPERNEW_RIBBON", "D:/PROJELLER/scalpernew/backend/app/ema_ribbon.py")
RIBBON_HOLD_MINUTES = {"5m": 150.0, "15m": 150.0, "30m": 270.0, "1h": 480.0}   # auto_paper._RIBBON_HOLD_MINUTES
TOP_LIMIT = 40                                                                   # scalpernew TOP_GAINERS_LIMIT
TRAIL = dict(trail_trigger_pct=2.0, trail_gap_pct=1.0)


def load_ribbon():
    spec = importlib.util.spec_from_file_location("scalpernew_ema_ribbon", SCALPERNEW_RIBBON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # `from app.config import config` → sclpragnt config (kullanılan fonksiyonlar config'e bakmaz)
    return mod


def detect_ribbon(rb, bars: list[dict], tf: str) -> list[dict]:
    """scalpernew.select_recent_cross ile aynı eleme, pencere/tazelik kısıtı olmadan HER mum için (replay)."""
    closes = [b["close"] for b in bars]
    opens = [b["open"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    fast, mid, slow = rb.sma_series(closes, rb.RIBBON_FAST), rb.sma_series(closes, rb.RIBBON_MID), rb.sma_series(closes, rb.RIBBON_SLOW)
    k_line = rb.stoch_rsi_k(closes)
    rsi = rb._rsi_series(closes) if tf in {"5m", "15m", "1h"} else None
    hist = rb._macd_hist(closes) if tf == "30m" else None
    adx = rb._adx_series(highs, lows, closes) if tf in {"5m", "30m", "1h"} else None
    apply_stoch = tf not in {"1m", "15m"}
    out = []
    for i in range(1, len(closes)):
        if not rb.ribbon_buy_at(fast, mid, slow, i):
            continue
        if apply_stoch and rb.stoch_rsi_too_high(k_line[i] if i < len(k_line) else None):
            continue
        if not rb.timeframe_combo_ok(tf, closes, highs, lows, i, rsi, hist, adx):
            continue
        if rb.ribbon_is_compressed(fast[i], mid[i], slow[i], closes[i]):
            continue
        if rb.tape_is_flat(highs, lows, i):
            continue
        if rb.bodies_are_flat(opens, closes, i, highs, lows):
            continue
        out.append({"index": i})
    return out


async def rows_for(symbol: str, tf: str, start_ms: int, end_ms: int) -> list:
    base = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "15m", "1h": "15m"}[tf]
    rows = uni.db_rows_to_klines(await database.get_market_candles(symbol, base, start_ms=start_ms, end_ms=end_ms))
    return rows if base == tf else uni.aggregate_klines(rows, M15_MS, ma_buy_tracker.SUPPORTED_TF_MS[tf])


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    rb = load_ribbon()
    tfs = list(rb.RIBBON_TIMEFRAMES)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - args.days * DAY_MS
    t0 = start_ms - 6 * DAY_MS
    uni.apply_runtime_overrides(json.loads(await database.get_llm_setting("runtime_config", "{}") or "{}"))
    config.TOP_GAINERS_LIMIT = TOP_LIMIT
    settings = uni.selection_settings()
    universe = sorted(s for s in await trading_symbols("TRY") if not rb.is_pegged_symbol(s))
    commission = float(config.effective_commission_pct())
    slippage = float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.00025))
    print(f"scalpernew kurdele: {len(universe)} çift (endeksli hariç), {args.days} gün, TF {tfs}, ilk {TOP_LIMIT} yükselen | "
          f"hedef {rb.RIBBON_TARGET_PCT} stop {rb.RIBBON_STOP_PCT} tutma {RIBBON_HOLD_MINUTES} | komisyon {commission*100:.4f}%")

    gainer_period = int(settings["TOP_GAINERS_REFRESH_SEC"]) * 1000
    activity_period = int(settings["SYMBOL_ACTIVITY_REFRESH_SEC"]) * 1000
    gainer_marks = uni.refresh_marks(start_ms - activity_period, now_ms, gainer_period)
    activity_marks = uni.refresh_marks(start_ms, now_ms, activity_period, offset_ms=20_000)
    stats_by_mark: list[dict] = [dict() for _ in gainer_marks]
    for n, symbol in enumerate(universe, 1):
        p5 = uni.parse_rows(await rows_for(symbol, "5m", t0, now_ms))
        for i, st in enumerate(uni.ticker_stats_series(p5, gainer_marks)):
            if st is not None:
                stats_by_mark[i][symbol] = st
        if n % 50 == 0:
            print(f"  5m ticker: {n}/{len(universe)}", file=sys.stderr)
    tracked_by_amark = []
    for t in activity_marks:
        gi = bisect_left(gainer_marks, t + 1) - 1
        tracked_by_amark.append(uni.rank_top_gainers(stats_by_mark[gi], TOP_LIMIT) if gi >= 0 else [])
    need: dict[str, set] = defaultdict(set)
    for i, syms in enumerate(tracked_by_amark):
        for s in syms:
            need[s].add(i)
    active: dict[str, set] = defaultdict(set)
    for n, symbol in enumerate(sorted(need), 1):
        p5 = uni.parse_rows(await rows_for(symbol, "5m", t0, now_ms))
        p1 = uni.parse_rows(await rows_for(symbol, "1m", start_ms - DAY_MS, now_ms))
        marks = sorted(need[symbol])
        for i, st in zip(marks, uni.ticker_stats_series(p5, [activity_marks[i] for i in marks])):
            t = activity_marks[i]
            res = uni.activity_status(uni.history_upto(p5, t, uni.M5_HISTORY_BARS), uni.history_upto(p1, t, uni.M1_HISTORY_BARS),
                                      quote_volume=(st or {}).get("quote_volume", 0.0), now_ms=t)
            if res["status"] == "ACTIVE":
                active[symbol].add(i)
        if n % 50 == 0 or n == len(need):
            print(f"  aktivite: {n}/{len(need)}", file=sys.stderr)
    timeline = [{"at_ms": t, "active": {s for s in tracked_by_amark[i] if i in active[s]}, "tracked": set(tracked_by_amark[i])}
                for i, t in enumerate(activity_marks)]
    scan_symbols = sorted(uni.symbols_ever(uni.membership_at(timeline, t) for t in activity_marks))
    print(f"  taranan sembol: {len(scan_symbols)}; saatlik ort. AKTİF {statistics.fmean(len(s['active']) for s in timeline):.1f}", file=sys.stderr)

    results: dict = defaultdict(list)      # (variant, tf) -> [net]
    reasons: dict = defaultdict(Counter)
    raw_count: Counter = Counter()
    for n, symbol in enumerate(scan_symbols, 1):
        m1 = await database.get_market_candles(symbol, "1m", start_ms=start_ms - DAY_MS, end_ms=now_ms)
        bars1 = [{"open_time": int(b["open_time"]) / 1000.0, "high": float(b["high"]), "low": float(b["low"]), "close": float(b["close"])} for b in m1]
        o1 = [b["open_time"] for b in bars1]
        for tf in tfs:
            tf_ms = ma_buy_tracker.SUPPORTED_TF_MS[tf]
            bars = ma_buy_tracker.closed_bars(await rows_for(symbol, tf, t0, now_ms), tf_ms, now_ms)
            if len(bars) < rb.RIBBON_SLOW + 2:
                continue
            for sig in detect_ribbon(rb, bars, tf):
                close_ms = bars[sig["index"]]["open_ms"] + tf_ms
                if close_ms < start_ms:
                    continue
                raw_count[tf] += 1
                if symbol not in uni.membership_at(timeline, close_ms):
                    continue
                i0 = bisect_left(o1, close_ms / 1000.0)
                hold = RIBBON_HOLD_MINUTES[tf]
                window = bars1[i0:i0 + int(hold) + 5]
                if len(window) < 30:
                    continue
                entry = float(bars[sig["index"]]["close"])
                common = dict(sl_pct=float(rb.RIBBON_STOP_PCT[tf]), cancel_tp_on_trail=False, no_profit_min=0.0,
                              commission_pct=commission, slippage_pct=slippage, bar_seconds=60.0, max_hold_min=hold, **TRAIL)
                live = simulate_exit(window, entry, entry_time=close_ms / 1000.0, tp_pct=0.0, **common)             # hedefte satış kapalı
                tpon = simulate_exit(window, entry, entry_time=close_ms / 1000.0, tp_pct=float(rb.RIBBON_TARGET_PCT[tf]), **common)
                for name, sim in (("canlı (hedefte satış kapalı)", live), ("hedefte satış açık", tpon)):
                    if sim.get("sim_pct") is not None:
                        results[(name, tf)].append(float(sim["sim_pct"]))
                        reasons[(name, tf)][sim["reason"]] += 1
        if n % 25 == 0 or n == len(scan_symbols):
            print(f"  sinyaller: {n}/{len(scan_symbols)}", file=sys.stderr)

    generated = dt.datetime.now(TZ)
    tag = args.tag or f"{args.days}g_{generated:%Y-%m-%d}"
    lines = [f"# scalpernew MA kurdele kuralı — {args.days} günlük gerçekleşebilir net ({generated:%Y-%m-%d %H:%M})", "",
             f"Kural: `scalpernew/backend/app/ema_ribbon.py` (SMA 7/20/99 kesişimi, dilim şartları, sıkışıklık/durağan/ölü çubuk elekleri, "
             f"StochRSI ≤ 80 M15 hariç). Evren: her 10 dk 24 sa yükselenler ilk {TOP_LIMIT} + saatlik aktivite filtresi, endeksli çiftler hariç "
             f"({len(universe)} çift; saatlik ortalama aktif {statistics.fmean(len(s['active']) for s in timeline):.1f}). "
             f"Çıkış: iz süren stop tetik %2 / aralık %1, stop {rb.RIBBON_STOP_PCT}, tutma {RIBBON_HOLD_MINUTES} dk, komisyon "
             f"{commission*100:.4f}%/bacak + kayma {slippage*100:.3f}%. Aynı mumda stop ve hedef görülürse stop (kötümser).", "",
             "| Varyant | TF | Ham sinyal | Taranan anda | Kazanan | Ort. net | Medyan net | Toplam net | Çıkış nedenleri |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for name in ("canlı (hedefte satış kapalı)", "hedefte satış açık"):
        for tf in tfs:
            vals = results.get((name, tf), [])
            if not vals:
                lines.append(f"| {name} | {tf_label(tf)} | {raw_count[tf]} | 0 | — | — | — | — | — |")
                continue
            rs = ", ".join(f"{k} {v}" for k, v in reasons[(name, tf)].most_common())
            lines.append(f"| {name} | {tf_label(tf)} | {raw_count[tf]} | {len(vals)} | {100*sum(1 for v in vals if v > 0)/len(vals):.0f}% | "
                         f"{statistics.fmean(vals):+.2f}% | {statistics.median(vals):+.2f}% | {sum(vals):+.0f}% | {rs} |")
    lines += ["", "## Dürüst sınırlar", "",
              "- Giriş sinyal mumunun kapanışı; canlıda 180 sn tazelik penceresi ve 90 sn tarama kadansı var, burada her uygun mum sayılır.",
              "- Paper'ın diğer giriş kapıları (LLM hakemi, MTF uyumu, sessiz saat, tekilleştirme, maks 8 pozisyon, likidite) uygulanmadı; "
              "canlıda açılan işlem daha az olur. Kâr hedefin %90'ında iz süren aralığın yarıya inmesi simüle edilmedi.",
              "- scalpernew'in kendi backtest betiği sabit 'bugünkü ilk 40' listesi ve hedef/stop ızgarasında örneklem içi arama kullanır; "
              "oradaki artı sonuçlar bu ölçümle karşılaştırılamaz.", ""]
    md = "\n".join(lines)
    os.makedirs(DOCS_DIR, exist_ok=True)
    md_path = os.path.join(DOCS_DIR, f"SCALPERNEW_KURDELE_CIKIS_SIM_{tag}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(ROOT, "work", f"scalpernew_ribbon_{tag}.json"), "w", encoding="utf-8") as fh:
        json.dump({str(k): v for k, v in results.items()}, fh)
    print(md)
    print(f"\nRapor: {md_path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
