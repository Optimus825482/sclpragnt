"""MA BUY — GİRİŞ FİLTRESİ ÇALIŞMASI (hangi koşulda kesişim para kazandırıyor?).

AMAÇ (2026-10-20): çıkış simülasyonu, MA 7/20/99 kesişiminin TEK BAŞINA beklentisinin sıfıra yakın (net = −maliyet)
olduğunu gösterdi. Bu betik canlı-evren replay sinyallerinin her biri için sinyal anında bilinen (ileri bakışsız)
özellikleri hesaplar ve her özellik kovasında GERÇEKLEŞEBİLİR net sonucu (app/paper_sim.simulate_exit, senaryo D:
TF'ye göre tutma + hedef, stop %4; ve A: canlı 60 dk) ölçer. Böylece "hacim patlamasıyla gelen kesişim", "1 saatlik
trend yukarıyken", "StochRSI düşükken", "gece saatlerinde" gibi filtre adayları aynı veriyle karşılaştırılır.

ÖZELLİKLER (sinyal mumunun kapanışında):
    vol_ratio   : sinyal mumu hacmi / önceki 20 mumun ortalaması (aynı TF)
    stoch_k     : StochRSI K (14,14,3), aynı TF
    ext_pct     : kapanış / SMA99 − 1 (%), aynı TF (ne kadar "uzamış")
    trend_1h    : 1 saatlik dilimde kapanış > SMA99 ve SMA20 > SMA99 (yukarı) / değil
    hour        : İstanbul saati (0-6, 6-12, 12-18, 18-24)
    chg_24h     : 24 sa değişim (%) — sembolün "yükselenler" sırasındaki konumu
    rule        : fast_cross_mid / mid_cross_slow / ikisi
    weekday     : hafta içi / hafta sonu

KULLANIM:
    python backend/scripts/ma_buy_filter_study.py --rows work/ma_buy_replay_canli_evren_90g_2026-10-20.json --tag 90g
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import statistics
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import database, ma_buy_signals, ma_buy_tracker, ma_buy_replay_universe as uni   # noqa: E402
from app.config import config                                                                # noqa: E402
from app.ma_buy_notify import target_pct, tf_label                                           # noqa: E402
from app.paper_sim import simulate_exit                                                      # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.abspath(os.path.join(ROOT, "..", "docs"))
TZ = dt.timezone(dt.timedelta(hours=3))
HOLD_C = {"1m": 60, "5m": 240, "15m": 240, "30m": 480, "1h": 1440}
TARGET_D = {"1m": 1.0, "5m": 1.5, "15m": 1.5, "30m": 2.0, "1h": 3.0}
H1_MS = 3_600_000
M15_MS = 900_000

BUCKETS = {
    "vol_ratio": [("<1", lambda v: v < 1), ("1-1.5", lambda v: 1 <= v < 1.5), ("1.5-2.5", lambda v: 1.5 <= v < 2.5), (">=2.5", lambda v: v >= 2.5)],
    "stoch_k": [("<20", lambda v: v < 20), ("20-50", lambda v: 20 <= v < 50), ("50-80", lambda v: 50 <= v < 80), (">=80", lambda v: v >= 80)],
    "ext_pct": [("<0", lambda v: v < 0), ("0-2", lambda v: 0 <= v < 2), ("2-5", lambda v: 2 <= v < 5), (">=5", lambda v: v >= 5)],
    "trend_1h": [("yukarı", lambda v: v is True), ("değil", lambda v: v is False)],
    "hour": [("00-06", lambda v: v < 6), ("06-12", lambda v: 6 <= v < 12), ("12-18", lambda v: 12 <= v < 18), ("18-24", lambda v: v >= 18)],
    "chg_24h": [("<0", lambda v: v < 0), ("0-5", lambda v: 0 <= v < 5), ("5-15", lambda v: 5 <= v < 15), (">=15", lambda v: v >= 15)],
    "rule": [("fast_cross_mid", lambda v: v == "fast_cross_mid"), ("mid_cross_slow", lambda v: v == "mid_cross_slow"), ("ikisi", lambda v: v == "ikisi")],
    "weekday": [("hafta içi", lambda v: v < 5), ("hafta sonu", lambda v: v >= 5)],
}


async def live_settings() -> dict:
    try:
        saved = json.loads(await asyncio.wait_for(database.get_llm_setting("auto_paper_settings", "{}"), 15) or "{}")
    except Exception:  # noqa: BLE001
        saved = {}
    ex = config.auto_paper_exit_defaults()
    return {"sl_pct": float(saved.get("stop_loss_pct", ex["stop_loss_pct"])),
            "trail_trigger_pct": float(saved.get("trailing_trigger_pct", ex["trailing_trigger_pct"])),
            "trail_gap_pct": float(saved.get("trailing_gap_pct", ex["trailing_gap_pct"])),
            "cancel_tp_on_trail": bool(saved.get("tp_cancel_on_trail", getattr(config, "AUTO_PAPER_TP_CANCEL_ON_TRAIL", False))),
            "max_hold_live": float(saved.get("max_hold_minutes", getattr(config, "AUTO_PAPER_MAX_HOLD_MINUTES", 120.0))),
            "commission_pct": config.effective_commission_pct(),
            "slippage_pct": float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.00025))}


def sma_last(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


async def tf_rows(symbol: str, tf: str, start_ms: int, end_ms: int) -> list:
    base = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "15m", "1h": "15m"}[tf]
    rows = uni.db_rows_to_klines(await database.get_market_candles(symbol, base, start_ms=start_ms, end_ms=end_ms))
    if base != tf:
        rows = uni.aggregate_klines(rows, M15_MS, ma_buy_tracker.SUPPORTED_TF_MS[tf])
    return rows


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    rows = json.load(open(args.rows, encoding="utf-8"))["rows"]
    live = await live_settings()
    per = ma_buy_tracker.periods()
    use_sma = str(getattr(config, "MA_BUY_MA_TYPE", "sma")).strip().lower() == "sma"
    fn = ma_buy_signals.sma_series if use_sma else ma_buy_signals.ema_series
    now_ms = int(dt.datetime.now(TZ).timestamp() * 1000)
    print(f"Filtre çalışması: {len(rows)} sinyal | {live}")

    by_symbol: dict = defaultdict(list)
    for r in rows:
        by_symbol[r["symbol"]].append(r)
    feats: list[dict] = []
    done = 0
    for symbol, items in sorted(by_symbol.items()):
        t0 = min(int(r["signal_time_ms"]) for r in items) - 120 * H1_MS      # SMA99 1h ısınması
        t1 = max(int(r["signal_time_ms"]) for r in items) + 2 * 86_400_000
        rows5 = await tf_rows(symbol, "5m", t0, t1)
        p5 = uni.parse_rows(rows5)
        rows1h_k = await tf_rows(symbol, "1h", t0, t1)
        bars1h = ma_buy_tracker.closed_bars(rows1h_k, H1_MS, now_ms)
        h1_open = [b["open_ms"] for b in bars1h]
        h1_close = [b["close"] for b in bars1h]
        m1 = await database.get_market_candles(symbol, "1m", start_ms=min(int(r["signal_time_ms"]) for r in items), end_ms=t1)
        bars1 = [{"open_time": int(b["open_time"]) / 1000.0, "high": float(b["high"]), "low": float(b["low"]), "close": float(b["close"])} for b in m1]
        o1 = [b["open_time"] for b in bars1]
        tf_cache: dict = {}
        for r in items:
            tf = r["timeframe"]
            tf_ms = ma_buy_tracker.SUPPORTED_TF_MS[tf]
            if tf not in tf_cache:
                bars = ma_buy_tracker.closed_bars(await tf_rows(symbol, tf, t0, t1), tf_ms, now_ms)
                tf_cache[tf] = (bars, [b["open_ms"] for b in bars])
            bars, opens = tf_cache[tf]
            i = bisect_left(opens, int(r["signal_time_ms"]))
            if i >= len(bars) or opens[i] != int(r["signal_time_ms"]) or i < max(per) + 1:
                continue
            closes = [b["close"] for b in bars[:i + 1]]
            vols = [b["volume"] if "volume" in b else 0.0 for b in bars[:i + 1]]
            # closed_bars hacim taşımıyor → ham satırdan al
            f: dict = {"symbol": symbol, "tf": tf, "rules": r.get("rules") or []}
            # closed_bars hacim tasimaz -> ham satirdan, TF basina bir kez
            if ("raw", tf) not in tf_cache:
                tf_cache[("raw", tf)] = {int(x[0]): float(x[5]) for x in (await tf_rows(symbol, tf, t0, t1))}
            raw_vols = tf_cache[("raw", tf)]
            vol_now = raw_vols.get(opens[i], 0.0) if raw_vols else vols[-1]
            prev = [raw_vols.get(opens[j], 0.0) for j in range(max(0, i - 20), i)] if raw_vols else vols[-21:-1]
            avg_prev = sum(prev) / len(prev) if prev else 0.0
            f["vol_ratio"] = (vol_now / avg_prev) if avg_prev > 0 else None
            k = ma_buy_signals.stoch_rsi_k(closes, 14, 14, 3)
            f["stoch_k"] = k[-1] if k and k[-1] is not None else None
            s99 = sma_last(closes, per[2])
            f["ext_pct"] = (closes[-1] / s99 - 1) * 100 if s99 else None
            close_ms = int(r["signal_time_ms"]) + tf_ms
            j = bisect_right(h1_open, close_ms - H1_MS)     # kapanışı sinyalden önce olan son 1h mumu
            if j >= per[2]:
                c1 = h1_close[:j]
                s20, s99h = sma_last(c1, per[1]), sma_last(c1, per[2])
                f["trend_1h"] = bool(c1[-1] > s99h and s20 > s99h) if s20 and s99h else None
            else:
                f["trend_1h"] = None
            local = dt.datetime.fromtimestamp(close_ms / 1000, TZ)
            f["hour"], f["weekday"] = local.hour, local.weekday()
            st = uni.ticker_stats_series(p5, [close_ms])[0]
            f["chg_24h"] = st["change_pct"] if st else None
            rules = f["rules"]
            f["rule"] = "ikisi" if len(rules) > 1 else (rules[0] if rules else "?")
            # gerçekleşebilir net: D ve A
            i0 = bisect_left(o1, close_ms / 1000.0)
            window = bars1[i0:i0 + 1445]
            if len(window) < 30:
                continue
            common = dict(sl_pct=live["sl_pct"], trail_trigger_pct=live["trail_trigger_pct"], trail_gap_pct=live["trail_gap_pct"],
                          cancel_tp_on_trail=live["cancel_tp_on_trail"], no_profit_min=0.0, commission_pct=live["commission_pct"],
                          slippage_pct=live["slippage_pct"], bar_seconds=60.0)
            d = simulate_exit(window, float(r["signal_price"]), entry_time=close_ms / 1000.0, tp_pct=TARGET_D[tf], max_hold_min=float(HOLD_C[tf]), **common)
            a = simulate_exit(window, float(r["signal_price"]), entry_time=close_ms / 1000.0, tp_pct=target_pct(tf), max_hold_min=live["max_hold_live"], **common)
            if d.get("sim_pct") is None or a.get("sim_pct") is None:
                continue
            f["net_d"], f["net_a"] = float(d["sim_pct"]), float(a["sim_pct"])
            f["h4"] = (r.get("horizons") or {}).get("4h")
            feats.append(f)
        done += 1
        if done % 25 == 0 or done == len(by_symbol):
            print(f"  {done}/{len(by_symbol)} sembol, {len(feats)} sinyal", file=sys.stderr)

    def cell(items):
        if not items:
            return None
        d = [x["net_d"] for x in items]; a = [x["net_a"] for x in items]
        return {"n": len(items), "mean_d": statistics.fmean(d), "win_d": sum(1 for v in d if v > 0) / len(d),
                "mean_a": statistics.fmean(a), "sum_d": sum(d)}

    tfs = ["5m", "15m", "30m", "1h"]
    generated = dt.datetime.now(TZ)
    tag = args.tag or generated.strftime("%Y-%m-%d")
    lines = [f"# MA BUY giriş filtresi çalışması ({generated:%Y-%m-%d %H:%M})", "",
             f"Kaynak: `{os.path.basename(args.rows)}`, {len(feats)} sinyal (özellikleri hesaplanabilen). Sonuç ölçütü: gerçekleşebilir net % "
             "(`paper_sim.simulate_exit`, komisyon + kayma düşülmüş). **D** = TF'ye göre tutma (M5/M15 4 sa, M30 8 sa, H1 24 sa) + hedef "
             f"(%1,5 / %1,5 / %2 / %3), stop %{live['sl_pct']:g}, iz süren %{live['trail_trigger_pct']:g}/%{live['trail_gap_pct']:g}. "
             f"**A** = canlı ayar (hedef TF'ye göre, tutma {live['max_hold_live']:g} dk). Taban (filtresiz) satırı karşılaştırma için.", ""]
    base_all = cell(feats)
    lines += ["## Taban (filtresiz)", "", "| TF | n | D ort. net | D kazanan | A ort. net |", "|---|---:|---:|---:|---:|"]
    for tf in tfs:
        c = cell([f for f in feats if f["tf"] == tf])
        if c:
            lines.append(f"| {tf_label(tf)} | {c['n']} | {c['mean_d']:+.2f}% | {c['win_d']*100:.0f}% | {c['mean_a']:+.2f}% |")
    lines.append(f"| Tümü | {base_all['n']} | {base_all['mean_d']:+.2f}% | {base_all['win_d']*100:.0f}% | {base_all['mean_a']:+.2f}% |")
    for feat, buckets in BUCKETS.items():
        lines += ["", f"## {feat}", "", "| Kova | " + " | ".join(f"{tf_label(t)} n / D ort." for t in tfs) + " | Tümü n / D ort. / kazanan / A ort. |",
                  "|---|" + "---:|" * (len(tfs) + 1)]
        for name, pred in buckets:
            sel = [f for f in feats if f.get(feat) is not None and pred(f[feat])]
            cells = []
            for tf in tfs:
                c = cell([f for f in sel if f["tf"] == tf])
                cells.append(f"{c['n']} / {c['mean_d']:+.2f}%" if c else "—")
            c = cell(sel)
            tot = f"{c['n']} / {c['mean_d']:+.2f}% / {c['win_d']*100:.0f}% / {c['mean_a']:+.2f}%" if c else "—"
            lines.append(f"| {name} | " + " | ".join(cells) + f" | {tot} |")
    # en iyi tek kovalar (n >= 150) ve birleşimler
    singles = []
    for feat, buckets in BUCKETS.items():
        for name, pred in buckets:
            sel = [f for f in feats if f.get(feat) is not None and pred(f[feat])]
            c = cell(sel)
            if c and c["n"] >= 150:
                singles.append((c["mean_d"], feat, name, c))
    singles.sort(reverse=True)
    lines += ["", "## En iyi tek filtreler (n ≥ 150, D ortalama nete göre)", "", "| Filtre | n | D ort. net | D kazanan | A ort. net |", "|---|---:|---:|---:|---:|"]
    for m, feat, name, c in singles[:10]:
        lines.append(f"| {feat} = {name} | {c['n']} | {c['mean_d']:+.2f}% | {c['win_d']*100:.0f}% | {c['mean_a']:+.2f}% |")
    lines += ["", "## İkili birleşimler (en iyi 5 tek filtrenin çiftleri, n ≥ 80)", "", "| Birleşim | n | D ort. net | D kazanan |", "|---|---:|---:|---:|"]
    top = singles[:5]
    combos = []
    for x in range(len(top)):
        for y in range(x + 1, len(top)):
            _, f1, n1, _ = top[x]; _, f2, n2, _ = top[y]
            if f1 == f2:
                continue
            p1 = dict(BUCKETS[f1])[n1]; p2 = dict(BUCKETS[f2])[n2]
            sel = [f for f in feats if f.get(f1) is not None and f.get(f2) is not None and p1(f[f1]) and p2(f[f2])]
            c = cell(sel)
            if c and c["n"] >= 80:
                combos.append((c["mean_d"], f"{f1}={n1} ∧ {f2}={n2}", c))
    combos.sort(reverse=True)
    for m, name, c in combos[:10]:
        lines.append(f"| {name} | {c['n']} | {c['mean_d']:+.2f}% | {c['win_d']*100:.0f}% |")
    lines += ["", "## Dürüst sınırlar", "",
              "- Kovalar aynı veri üzerinde seçildi (örneklem içi); en iyi görünen filtrenin bir kısmı şans. Karar vermeden önce "
              "bulunan filtre ayrı bir dönemde (ör. 7 günlük canlı kayıt) doğrulanmalı.",
              "- Çıkış kuralı sabit (D / A); filtre ile çıkış birlikte optimize edilmedi.",
              "- Özellikler sinyal mumunun kapanışında bilinenlerdir; ileri bakış yoktur.", ""]
    md = "\n".join(lines)
    os.makedirs(DOCS_DIR, exist_ok=True)
    md_path = os.path.join(DOCS_DIR, f"MA_BUY_FILTRE_CALISMASI_{tag}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(ROOT, "work", f"ma_buy_filter_feats_{tag}.json"), "w", encoding="utf-8") as fh:
        json.dump(feats, fh, ensure_ascii=False)
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
