"""MA BUY — ÇIKIŞ KURALI SİMÜLASYONU (gerçekleşebilir net %), canlı-evren replay sinyalleri üzerinde.

AMAÇ (2026-10-20): MFE "görülen en yüksek fiyat"tır; otonom paper ise stop / iz süren stop / hedef / maks tutma ile
çıkar ve komisyon + kayma öder. Bu betik canlı-evren replay'in saydığı sinyalleri (work/ma_buy_replay_canli_evren_*.json)
arşivdeki 1 dakikalık mumlarla `app.paper_sim.simulate_exit` (canlı motorla aynı kurallar; bar içi belirsizlikte stop
önce → KÖTÜMSER taban) üzerinden oynatır ve senaryo × zaman dilimi bazında net sonuç verir.

SENARYOLAR (hepsi: stop %4, iz süren stop tetik %2 / aralık %1, sabit TP iz sürende iptal edilmez, komisyon %0,1125/bacak
+ kayma %0,025, kârsız-süre kuralı yok — canlı ayarlarla aynı):
    A canlı        : hedef TF'ye göre (1m:1 5m:1.5 15m:2 30m:2.5 1h:3), maks tutma 60 dk (kayıtlı ayar)
    B 2 saat       : A + maks tutma 120 dk (kod varsayılanı)
    C TF'ye göre   : A + maks tutma M5/M15 4 sa, M30 8 sa, H1 24 sa
    D C + hedef    : C + hedef M5/M15 %1.5, M30 %2, H1 %3
    E iz sürme yok : D + iz süren stop kapalı (yalnız sabit TP / SL / süre)

KULLANIM:
    python backend/scripts/ma_buy_exit_sim.py --rows work/ma_buy_replay_canli_evren_90g_2026-10-20.json --tag 90g
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import database, ma_buy_tracker                                   # noqa: E402
from app.config import config                                              # noqa: E402
from app.ma_buy_notify import target_pct, tf_label                         # noqa: E402
from app.paper_sim import simulate_exit                                    # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.abspath(os.path.join(ROOT, "..", "docs"))
TZ = dt.timezone(dt.timedelta(hours=3))
HOLD_C = {"1m": 60, "5m": 240, "15m": 240, "30m": 480, "1h": 1440}
TARGET_D = {"1m": 1.0, "5m": 1.5, "15m": 1.5, "30m": 2.0, "1h": 3.0}
MAX_BARS = 1440 + 5


def scenarios(tf: str, live: dict) -> dict:
    base = dict(sl_pct=float(live["stop_loss_pct"]), trail_trigger_pct=float(live["trailing_trigger_pct"]),
                trail_gap_pct=float(live["trailing_gap_pct"]), cancel_tp_on_trail=bool(live["tp_cancel_on_trail"]),
                no_profit_min=0.0, commission_pct=float(live["commission_pct"]), slippage_pct=float(live["slippage_pct"]),
                bar_seconds=60.0)
    tp_live = target_pct(tf)
    return {
        "A canlı (60 dk)": {**base, "tp_pct": tp_live, "max_hold_min": float(live["max_hold_minutes"])},
        "B 2 saat": {**base, "tp_pct": tp_live, "max_hold_min": 120.0},
        "C TF'ye göre tutma": {**base, "tp_pct": tp_live, "max_hold_min": float(HOLD_C[tf])},
        "D C + hedef": {**base, "tp_pct": TARGET_D[tf], "max_hold_min": float(HOLD_C[tf])},
        "E iz sürme yok": {**base, "tp_pct": TARGET_D[tf], "max_hold_min": float(HOLD_C[tf]), "trail_trigger_pct": 0.0},
        # 2026-10-20 ikinci tur: A-E'nin hepsinde ortalama net eksi cikti (stop %4 > hedef) -> stop genisligi denemeleri.
        "F D + stop %2": {**base, "tp_pct": TARGET_D[tf], "max_hold_min": float(HOLD_C[tf]), "sl_pct": 2.0},
        "G D + stop %1,5": {**base, "tp_pct": TARGET_D[tf], "max_hold_min": float(HOLD_C[tf]), "sl_pct": 1.5},
        "H kalibre profili": {**base, "tp_pct": TARGET_D[tf], "max_hold_min": float(HOLD_C[tf]), "sl_pct": 0.8,
                              "trail_trigger_pct": 1.0, "trail_gap_pct": 0.8},
        "I D + stop %1": {**base, "tp_pct": TARGET_D[tf], "max_hold_min": float(HOLD_C[tf]), "sl_pct": 1.0},
    }


async def live_settings() -> dict:
    try:
        saved = json.loads(await asyncio.wait_for(database.get_llm_setting("auto_paper_settings", "{}"), 15) or "{}")
    except Exception as exc:  # noqa: BLE001
        print(f"[uyarı] auto_paper_settings okunamadı ({exc}); kod varsayılanları", file=sys.stderr)
        saved = {}
    ex = config.auto_paper_exit_defaults()
    return {
        "stop_loss_pct": saved.get("stop_loss_pct", ex["stop_loss_pct"]),
        "trailing_trigger_pct": saved.get("trailing_trigger_pct", ex["trailing_trigger_pct"]),
        "trailing_gap_pct": saved.get("trailing_gap_pct", ex["trailing_gap_pct"]),
        "tp_cancel_on_trail": saved.get("tp_cancel_on_trail", getattr(config, "AUTO_PAPER_TP_CANCEL_ON_TRAIL", False)),
        "max_hold_minutes": saved.get("max_hold_minutes", getattr(config, "AUTO_PAPER_MAX_HOLD_MINUTES", 120.0)),
        "commission_pct": config.effective_commission_pct(),
        "slippage_pct": float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.00025)),
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True, help="canlı-evren replay JSON'u")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    data = json.load(open(args.rows, encoding="utf-8"))
    rows = data["rows"]
    live = await live_settings()
    print(f"Çıkış simülasyonu: {len(rows)} sinyal | canlı ayar: {live}")

    by_symbol: dict = defaultdict(list)
    for r in rows:
        by_symbol[r["symbol"]].append(r)
    results: dict = defaultdict(lambda: defaultdict(list))   # scenario -> tf -> [sim]
    done = 0
    for symbol, items in sorted(by_symbol.items()):
        start = min(int(r["signal_time_ms"]) for r in items)
        end = max(int(r["signal_time_ms"]) for r in items) + 2 * 86_400_000
        db = await database.get_market_candles(symbol, "1m", start_ms=start, end_ms=end)
        bars = [{"open_time": int(b["open_time"]) / 1000.0, "high": float(b["high"]), "low": float(b["low"]),
                 "close": float(b["close"])} for b in db]
        opens = [b["open_time"] for b in bars]
        from bisect import bisect_left
        for r in items:
            tf = r["timeframe"]
            tf_ms = ma_buy_tracker.SUPPORTED_TF_MS[tf]
            entry_ms = int(r["signal_time_ms"]) + tf_ms          # sinyal mumunun kapanışı
            i0 = bisect_left(opens, entry_ms / 1000.0)
            window = bars[i0:i0 + MAX_BARS]
            if len(window) < 30:
                continue
            for name, params in scenarios(tf, live).items():
                sim = simulate_exit(window, float(r["signal_price"]), entry_time=entry_ms / 1000.0, **params)
                if sim.get("sim_pct") is None:
                    continue
                results[name][tf].append({"pct": float(sim["sim_pct"]), "reason": sim["reason"], "symbol": symbol,
                                          "time_ms": entry_ms, "rules": r.get("rules")})
        done += 1
        if done % 25 == 0 or done == len(by_symbol):
            print(f"  {done}/{len(by_symbol)} sembol", file=sys.stderr)

    def stats(items: list) -> dict:
        p = [x["pct"] for x in items]
        return {"n": len(p), "win_rate": round(sum(1 for v in p if v > 0) / len(p), 4) if p else None,
                "mean_pct": round(statistics.fmean(p), 4) if p else None,
                "median_pct": round(statistics.median(p), 4) if p else None,
                "sum_pct": round(sum(p), 2), "p25": round(statistics.quantiles(p, n=4)[0], 3) if len(p) > 1 else None,
                "p75": round(statistics.quantiles(p, n=4)[2], 3) if len(p) > 1 else None,
                "reasons": dict(Counter(x["reason"] for x in items).most_common())}

    summary = {name: {tf: stats(items) for tf, items in tfs.items()} for name, tfs in results.items()}
    generated = dt.datetime.now(TZ)
    tag = args.tag or generated.strftime("%Y-%m-%d")
    tfs_order = [t for t in ("1m", "5m", "15m", "30m", "1h") if any(t in s for s in summary.values())]
    lines = [f"# MA BUY çıkış kuralı simülasyonu — gerçekleşebilir net % ({generated:%Y-%m-%d %H:%M})", "",
             f"Kaynak: `{os.path.basename(args.rows)}` ({len(rows)} sinyal, canlı sembol seçimi). Simülatör: `app/paper_sim.simulate_exit` "
             "(otonom paper kurallarının kopyası; aynı mumda stop ve hedef görülürse STOP önce → sonuçlar taban, tavan değil). "
             f"Mum: arşivdeki 1 dakikalık. Giriş: sinyal mumunun kapanış fiyatı. Komisyon {live['commission_pct']*100:.4f}%/bacak, kayma "
             f"{live['slippage_pct']*100:.3f}%. Ortak: stop %{live['stop_loss_pct']:g}, iz süren stop tetik %{live['trailing_trigger_pct']:g} / "
             f"aralık %{live['trailing_gap_pct']:g}, hedef iz sürende {'iptal' if live['tp_cancel_on_trail'] else 'korunur'}.",
             "", "Senaryolar: A canlı (hedef TF'ye göre, tutma 60 dk) · B 2 saat · C TF'ye göre tutma (M5/M15 4 sa, M30 8 sa, H1 24 sa) · "
             "D C + hedef (M5/M15 %1,5, M30 %2, H1 %3) · E D + iz süren stop kapalı · F/G/I D ile stop %2 / %1,5 / %1 · H kalibre profili (stop %0,8, iz süren %1/%0,8).", ""]
    for name in summary:
        lines += [f"## {name}", "", "| TF | İşlem | Kazanan | Ortalama net | Medyan net | P25 | P75 | Toplam net | Çıkış nedenleri |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for tf in tfs_order:
            s = summary[name].get(tf)
            if not s:
                continue
            reasons = ", ".join(f"{k} {v}" for k, v in s["reasons"].items())
            q = lambda v: "—" if v is None else f"{v:+.2f}%"
            lines.append(f"| {tf_label(tf)} | {s['n']} | {s['win_rate']*100:.0f}% | {s['mean_pct']:+.2f}% | {s['median_pct']:+.2f}% | "
                         f"{q(s['p25'])} | {q(s['p75'])} | {s['sum_pct']:+.0f}% | {reasons} |")
        lines.append("")
    lines += ["## Dürüst sınırlar", "",
              "- Giriş fiyatı sinyal mumunun kapanışı; canlıda tarayıcı mumu kapanıştan 30 sn sonra görür ve piyasa emri verir (küçük kayma).",
              "- Paper motorunun dinamik breakeven / dinamik trailing ve LLM kapısı, MTF kapısı, sembol tekilleştirme gibi GİRİŞ engelleri simüle edilmedi; "
              "burada her sinyal işleme döner. Canlıda açılan işlem sayısı daha azdır.",
              "- Aynı sembolde üst üste sinyaller ayrı işlem sayıldı (canlıda tekilleştirme bazılarını eler).",
              "- Mum içi sıra bilinmediği için stop önce kabul edilir; gerçek sonuç biraz daha iyi olabilir.", ""]
    md = "\n".join(lines)
    os.makedirs(DOCS_DIR, exist_ok=True)
    md_path = os.path.join(DOCS_DIR, f"MA_BUY_CIKIS_SIMULASYONU_{tag}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    json_path = os.path.join(ROOT, "work", f"ma_buy_exit_sim_{tag}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"live": live, "summary": summary}, fh, ensure_ascii=False, indent=1)
    print(md)
    print(f"\nRapor: {md_path}\nHam: {json_path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
