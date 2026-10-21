"""TETİKLEYİCİ × EVREN ÇALIŞMASI — hangi giriş, hangi sembol kümesinde gerçekleşebilir net kazandırıyor?

AMAÇ (2026-10-20): MA kesişimi canlı evrende (24 sa yükselenler ilk 50) net ≈ −maliyet çıktı; basit filtreler değiştirmedi.
Bu betik iki ekseni birlikte tarar:
  Tetikleyiciler (app/entry_triggers.py): ma_cross (taban), stoch_turn, breakout_vol, pullback_sma20, rsi_cross30, bb_reentry
  Evrenler (saatlik; hepsi canlı aktivite filtresinden geçer — app/ma_buy_replay_universe.activity_status):
    U1 canlı        : 24 sa değişime göre ilk 50 (sistem bugün böyle)
    U2 az uzamış    : |24 sa değişim| ≤ 5% ve 24 sa hacim ≥ 1 M TL, hacme göre ilk 50
    U3 düşenler     : 24 sa değişim < 0 ve hacim ≥ 1 M TL, hacme göre ilk 50
    U4 tüm likit    : 24 sa hacim ≥ 1 M TL olan herkes (sıralama yok)
Sinyal, mumu kapandığı anda sembol evrendeyse sayılır. Sonuç: app/paper_sim.simulate_exit, senaryo D (TF'ye göre tutma
M5/M15 4 sa, M30 8 sa; hedef %1,5 / %1,5 / %2; canlı stop ve iz süren stop; komisyon + kayma). Veri: historical_candles.

KULLANIM:
    python backend/scripts/ma_buy_trigger_universe_study.py --days 30 --tfs 5m,15m,30m
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
from bisect import bisect_left
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import database, entry_triggers, ma_buy_tracker, ma_buy_replay_universe as uni   # noqa: E402
from app.binance_tr_public import trading_symbols                                          # noqa: E402
from app.config import config                                                              # noqa: E402
from app.ma_buy_notify import tf_label                                                     # noqa: E402
from app.paper_sim import simulate_exit                                                    # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.abspath(os.path.join(ROOT, "..", "docs"))
TZ = dt.timezone(dt.timedelta(hours=3))
DAY_MS = 86_400_000
M15_MS = 900_000
HOLD = {"5m": 240, "15m": 240, "30m": 480, "1h": 1440}
TARGET = {"5m": 1.5, "15m": 1.5, "30m": 2.0, "1h": 3.0}
MIN_VOL = 1_000_000.0
UNIVERSES = ["U1 canlı", "U2 az uzamış", "U3 düşenler", "U4 tüm likit"]


def pick_universe(name: str, stats: dict, limit: int) -> list[str]:
    liquid = {s: v for s, v in stats.items() if v and float(v["quote_volume"]) >= MIN_VOL}
    if name.startswith("U1"):
        return uni.rank_top_gainers(stats, limit)
    if name.startswith("U2"):
        pool = {s: v for s, v in liquid.items() if abs(float(v["change_pct"])) <= 5.0}
    elif name.startswith("U3"):
        pool = {s: v for s, v in liquid.items() if float(v["change_pct"]) < 0}
    else:
        return sorted(liquid)
    return [s for s, _ in sorted(pool.items(), key=lambda kv: float(kv[1]["quote_volume"]), reverse=True)[:limit]]


async def live_exit() -> dict:
    try:
        saved = json.loads(await asyncio.wait_for(database.get_llm_setting("auto_paper_settings", "{}"), 15) or "{}")
    except Exception:  # noqa: BLE001
        saved = {}
    ex = config.auto_paper_exit_defaults()
    return dict(sl_pct=float(saved.get("stop_loss_pct", ex["stop_loss_pct"])),
                trail_trigger_pct=float(saved.get("trailing_trigger_pct", ex["trailing_trigger_pct"])),
                trail_gap_pct=float(saved.get("trailing_gap_pct", ex["trailing_gap_pct"])),
                cancel_tp_on_trail=bool(saved.get("tp_cancel_on_trail", getattr(config, "AUTO_PAPER_TP_CANCEL_ON_TRAIL", False))),
                no_profit_min=0.0, commission_pct=config.effective_commission_pct(),
                slippage_pct=float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.00025)), bar_seconds=60.0)


async def rows_for(symbol: str, tf: str, start_ms: int, end_ms: int) -> list:
    base = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "15m", "1h": "15m"}[tf]
    rows = uni.db_rows_to_klines(await database.get_market_candles(symbol, base, start_ms=start_ms, end_ms=end_ms))
    return rows if base == tf else uni.aggregate_klines(rows, M15_MS, ma_buy_tracker.SUPPORTED_TF_MS[tf])


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--tfs", default="5m,15m,30m")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    tfs = [t for t in args.tfs.split(",") if t in HOLD]
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - args.days * DAY_MS
    t0 = start_ms - 6 * DAY_MS                         # ısınma: 24 sa ticker + SMA99 (30m: 50 sa) + aktivite
    overrides = uni.apply_runtime_overrides(json.loads(await database.get_llm_setting("runtime_config", "{}") or "{}"))
    settings = uni.selection_settings()
    exit_params = await live_exit()
    universe = sorted(await trading_symbols("TRY"))
    print(f"Tetikleyici × evren: {len(universe)} çift, {args.days} gün, TF {tfs} | seçim {settings['TOP_GAINERS_LIMIT']}/"
          f"{settings['TOP_GAINERS_REFRESH_SEC']} sn, aktivite / {settings['SYMBOL_ACTIVITY_REFRESH_SEC']} sn | çıkış {exit_params}")

    gainer_period = int(settings["TOP_GAINERS_REFRESH_SEC"]) * 1000
    activity_period = int(settings["SYMBOL_ACTIVITY_REFRESH_SEC"]) * 1000
    gainer_marks = uni.refresh_marks(start_ms - activity_period, now_ms, gainer_period)
    activity_marks = uni.refresh_marks(start_ms, now_ms, activity_period, offset_ms=20_000)
    limit = int(settings["TOP_GAINERS_LIMIT"])

    # 1) 5m → her 10 dk ticker karşılığı (tüm evren)
    stats_by_mark: list[dict] = [dict() for _ in gainer_marks]
    for n, symbol in enumerate(universe, 1):
        rows5 = await rows_for(symbol, "5m", t0, now_ms)
        for i, st in enumerate(uni.ticker_stats_series(uni.parse_rows(rows5), gainer_marks)):
            if st is not None:
                stats_by_mark[i][symbol] = st
        if n % 50 == 0:
            print(f"  5m ticker: {n}/{len(universe)}", file=sys.stderr)

    def gmark_index(t_ms: int) -> int | None:
        idx = bisect_left(gainer_marks, t_ms + 1) - 1
        return idx if idx >= 0 else None

    tracked: dict[str, list[list[str]]] = {u: [] for u in UNIVERSES}
    for t in activity_marks:
        gi = gmark_index(t)
        stats = stats_by_mark[gi] if gi is not None else {}
        for u in UNIVERSES:
            tracked[u].append(pick_universe(u, stats, limit))
    need_activity: dict[str, set] = defaultdict(set)          # symbol -> {mark index}
    for u in UNIVERSES:
        for i, syms in enumerate(tracked[u]):
            for s in syms:
                need_activity[s].add(i)
    print(f"  aktivite değerlendirilecek sembol: {len(need_activity)}; evren büyüklükleri (saatlik ort.): " +
          ", ".join(f"{u}={statistics.fmean(len(x) for x in tracked[u]):.0f}" for u in UNIVERSES), file=sys.stderr)

    # 2) aktivite (sembol başına bir kez; 1m + 5m)
    active: dict[str, set] = defaultdict(set)                  # symbol -> {mark index ACTIVE}
    for n, symbol in enumerate(sorted(need_activity), 1):
        p5 = uni.parse_rows(await rows_for(symbol, "5m", t0, now_ms))
        p1 = uni.parse_rows(await rows_for(symbol, "1m", start_ms - DAY_MS, now_ms))
        marks = sorted(need_activity[symbol])
        qv = uni.ticker_stats_series(p5, [activity_marks[i] for i in marks])
        for i, st in zip(marks, qv):
            t = activity_marks[i]
            res = uni.activity_status(uni.history_upto(p5, t, uni.M5_HISTORY_BARS), uni.history_upto(p1, t, uni.M1_HISTORY_BARS),
                                      quote_volume=(st or {}).get("quote_volume", 0.0), now_ms=t)
            if res["status"] == "ACTIVE":
                active[symbol].add(i)
        if n % 50 == 0 or n == len(need_activity):
            print(f"  aktivite: {n}/{len(need_activity)}", file=sys.stderr)
    timelines: dict[str, list[dict]] = {}
    for u in UNIVERSES:
        tl = []
        for i, t in enumerate(activity_marks):
            tr = set(tracked[u][i])
            tl.append({"at_ms": t, "active": {s for s in tr if i in active[s]}, "tracked": tr})
        timelines[u] = tl
    scan_symbols = sorted(uni.symbols_ever(uni.membership_at(timelines[u], t) for u in UNIVERSES for t in activity_marks))
    print(f"  taranacak sembol: {len(scan_symbols)}; saatlik ort. AKTİF: " +
          ", ".join(f"{u}={statistics.fmean(len(s['active']) for s in timelines[u]):.1f}" for u in UNIVERSES), file=sys.stderr)

    # 3) tetikleyici × TF × evren → çıkış simülasyonu (sinyal başına bir kez)
    results: dict = defaultdict(list)                         # (universe, trigger, tf) -> [net]
    for n, symbol in enumerate(scan_symbols, 1):
        m1 = await database.get_market_candles(symbol, "1m", start_ms=start_ms - DAY_MS, end_ms=now_ms)
        bars1 = [{"open_time": int(b["open_time"]) / 1000.0, "high": float(b["high"]), "low": float(b["low"]), "close": float(b["close"])} for b in m1]
        o1 = [b["open_time"] for b in bars1]
        for tf in tfs:
            tf_ms = ma_buy_tracker.SUPPORTED_TF_MS[tf]
            rows = await rows_for(symbol, tf, t0, now_ms)
            raw = {int(r[0]): float(r[5]) for r in rows}
            bars = ma_buy_tracker.closed_bars(rows, tf_ms, now_ms)
            for b in bars:
                b["volume"] = raw.get(b["open_ms"], 0.0)
            if len(bars) < 110:
                continue
            for trig in entry_triggers.TRIGGERS:
                kwargs = {"use_sma": True, "stoch_max": ma_buy_tracker.stoch_max(tf)} if trig["id"] == "ma_cross" else {}
                for sig in trig["fn"](bars, **kwargs):
                    close_ms = bars[sig["index"]]["open_ms"] + tf_ms
                    if close_ms < start_ms:
                        continue
                    members = [u for u in UNIVERSES if symbol in uni.membership_at(timelines[u], close_ms)]
                    if not members:
                        continue
                    i0 = bisect_left(o1, close_ms / 1000.0)
                    window = bars1[i0:i0 + HOLD[tf] + 5]
                    if len(window) < 30:
                        continue
                    sim = simulate_exit(window, float(bars[sig["index"]]["close"]), entry_time=close_ms / 1000.0,
                                        tp_pct=TARGET[tf], max_hold_min=float(HOLD[tf]), **exit_params)
                    if sim.get("sim_pct") is None:
                        continue
                    for u in members:
                        results[(u, trig["id"], tf)].append(float(sim["sim_pct"]))
        if n % 25 == 0 or n == len(scan_symbols):
            print(f"  sinyaller: {n}/{len(scan_symbols)}", file=sys.stderr)

    def cell(vals):
        return (f"{len(vals)} / {statistics.fmean(vals):+.2f}% / {100*sum(1 for v in vals if v > 0)/len(vals):.0f}%" if vals else "—")

    generated = dt.datetime.now(TZ)
    tag = args.tag or f"{args.days}g_{generated:%Y-%m-%d}"
    lines = [f"# Tetikleyici × evren çalışması — gerçekleşebilir net % ({generated:%Y-%m-%d %H:%M})", "",
             f"{args.days} gün, {len(universe)} TRY çifti, TF {', '.join(tf_label(t) for t in tfs)}. Hücre: işlem sayısı / işlem başına ortalama net / "
             f"kazanan oranı. Çıkış: TF'ye göre tutma (M5/M15 4 sa, M30 8 sa), hedef %1,5 / %1,5 / %2, stop %{exit_params['sl_pct']:g}, "
             f"iz süren %{exit_params['trail_trigger_pct']:g}/%{exit_params['trail_gap_pct']:g}, komisyon %{exit_params['commission_pct']*100:.4f}/bacak + kayma. "
             "Aynı mumda stop ve hedef görülürse stop (kötümser). Evrenlerin hepsi canlı aktivite filtresinden geçer; saatlik ortalama AKTİF: " +
             ", ".join(f"{u} {statistics.fmean(len(s['active']) for s in timelines[u]):.1f}" for u in UNIVERSES) + ".", ""]
    for tf in tfs:
        lines += [f"## {tf_label(tf)}", "", "| Tetikleyici | " + " | ".join(UNIVERSES) + " |", "|---|" + "---:|" * len(UNIVERSES)]
        for trig in entry_triggers.TRIGGERS:
            lines.append(f"| {trig['title']} | " + " | ".join(cell(results.get((u, trig['id'], tf), [])) for u in UNIVERSES) + " |")
        lines.append("")
    lines += ["## Tüm TF'ler birlikte", "", "| Tetikleyici | " + " | ".join(UNIVERSES) + " |", "|---|" + "---:|" * len(UNIVERSES)]
    for trig in entry_triggers.TRIGGERS:
        lines.append(f"| {trig['title']} | " + " | ".join(cell([v for tf in tfs for v in results.get((u, trig['id'], tf), [])]) for u in UNIVERSES) + " |")
    best = sorted(((statistics.fmean(v), k, len(v)) for k, v in results.items() if len(v) >= 100), reverse=True)[:10]
    lines += ["", "## En iyi 10 hücre (n ≥ 100)", "", "| Evren | Tetikleyici | TF | n | Ort. net |", "|---|---|---|---:|---:|"]
    for m, (u, tid, tf), n in best:
        lines.append(f"| {u} | {tid} | {tf_label(tf)} | {n} | {m:+.2f}% |")
    lines += ["", "## Dürüst sınırlar", "",
              "- Örneklem içi karşılaştırma; en iyi hücrenin bir kısmı şans. Pozitif çıkan bir hücre ayrı dönemde doğrulanmalı.",
              "- Evren tanımları U2–U4 bu çalışma için kuruldu; canlıda yok. Aktivite filtresi ve 1 saatlik yenileme aynen uygulandı.",
              "- Giriş fiyatı sinyal mumunun kapanışı; giriş engelleri (MTF, LLM kapısı, tekilleştirme) simüle edilmedi.", ""]
    md = "\n".join(lines)
    os.makedirs(DOCS_DIR, exist_ok=True)
    md_path = os.path.join(DOCS_DIR, f"MA_BUY_TETIKLEYICI_EVREN_{tag}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(ROOT, "work", f"trigger_universe_{tag}.json"), "w", encoding="utf-8") as fh:
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
