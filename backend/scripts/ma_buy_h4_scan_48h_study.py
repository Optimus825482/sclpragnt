"""H4 MA7↗MA20 kesişimleri — son 48 saat, 5M ve 10M TL hacim tabanıyla zirve/dip/süre ölçümü (2026-10-21, kullanıcı isteği).

Radar "H4 kesişimleri" taramasının (app/ma_buy_h4_scan.py) 48 saatlik çalışma raporu: canlı kuralla (MA 7/20/99 SMA,
7↗20, MA99 şartsız) tüm işlem gören TRY çiftleri taranır; her kesişim için sinyal mumu kapanışından bu yana 5 dk
mumlarla en yüksek artış (%), zirveye süre (dk), en derin düşüş (%) ve şu anki durum ölçülür. Aynı sinyal kümesi
24 sa hacmi ≥ 5M ve ≥ 10M TL olarak iki kez özetlenir (hacim = tarama anındaki 24 sa ticker hacmi; 48 saat önceki
hacim değil — raporda belirtilir).

KULLANIM: python backend/scripts/ma_buy_h4_scan_48h_study.py [--hours 48]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import ma_buy_h4_scan as scan_mod   # noqa: E402
from app.config import config                 # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=3))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.abspath(os.path.join(ROOT, "..", "docs"))
WORK_DIR = os.path.join(ROOT, "work")
FLOORS = (5e6, 10e6)


def _fmt_dur(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    m = int(round(minutes))
    h, r = divmod(m, 60)
    return f"{h} sa {r:02d} dk" if h else f"{r} dk"


def _pct(v) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def summarize(items: list[dict]) -> dict:
    meas = [i for i in items if i.get("max_rise_pct") is not None]
    if not meas:
        return {"n": len(items), "measured": 0}
    rise = [i["max_rise_pct"] for i in meas]
    drop = [i["max_drop_pct"] for i in meas]
    tmax = [i["minutes_to_max"] for i in meas]
    now = [i["now_pct"] for i in meas if i.get("now_pct") is not None]
    return {
        "n": len(items), "measured": len(meas), "symbols": len({i["symbol"] for i in items}),
        "rise_mean": st.mean(rise), "rise_median": st.median(rise),
        "rise_ge2": sum(1 for r in rise if r >= 2) / len(rise), "rise_ge5": sum(1 for r in rise if r >= 5) / len(rise),
        "rise_ge10": sum(1 for r in rise if r >= 10) / len(rise),
        "t_mean": st.mean(tmax), "t_median": st.median(tmax),
        "drop_mean": st.mean(drop), "drop_median": st.median(drop), "drop_le8": sum(1 for d in drop if d <= -8) / len(drop),
        "now_mean": st.mean(now) if now else None, "now_pos": (sum(1 for x in now if x > 0) / len(now)) if now else None,
        "elapsed_mean_h": st.mean(i["elapsed_minutes"] for i in meas) / 60.0,
    }


def summary_rows(label: str, s: dict) -> list[str]:
    if not s.get("measured"):
        return [f"| {label} | {s.get('n', 0)} | 0 | — | — | — | — | — | — | — | — |"]
    return [f"| {label} | {s['n']} | {s['symbols']} | {s['rise_mean']:+.2f}% | {s['rise_median']:+.2f}% | "
            f"{_fmt_dur(s['t_mean'])} | {_fmt_dur(s['t_median'])} | {s['drop_mean']:+.2f}% | {s['drop_median']:+.2f}% | "
            f"{s['rise_ge2']:.0%} / {s['rise_ge5']:.0%} / {s['rise_ge10']:.0%} | {s['drop_le8']:.0%} |"]


def item_row(i: dict) -> str:
    t = dt.datetime.fromtimestamp(i["bar_close_ms"] / 1000, TZ)
    vol = (i.get("quote_volume_24h") or 0) / 1e6
    peak_at = dt.datetime.fromtimestamp(i["max_rise_at_ms"] / 1000, TZ).strftime("%d.%m %H:%M") if i.get("max_rise_at_ms") else "—"
    return (f"| {i['symbol']} | {t:%d.%m %H:%M} | {vol:.1f}M | {i['signal_price']:g} | {_pct(i.get('max_rise_pct'))} | "
            f"{i.get('max_rise_price') if i.get('max_rise_price') is not None else '—'} | {peak_at} | {_fmt_dur(i.get('minutes_to_max'))} | "
            f"{_pct(i.get('max_drop_pct'))} | {_pct(i.get('now_pct'))} | {_fmt_dur(i.get('elapsed_minutes'))} |")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=48)
    args = ap.parse_args()
    hours = int(args.hours)
    # H4 mumu: SMA99 ısınması + pencere (+ pay); 7 gün için 99 + 42 + pay.
    scan_mod.FETCH_LIMIT = min(1000, 99 + hours // 4 + 30)
    # Zirve penceresi: ≤ 80 saat 5 dk mum (en çok 1000 mum, Binance TR üst sınırı); daha uzun pencerede 15 dk mum.
    if hours * 12 + 40 <= 1000:
        peak_tf, peak_ms = "5m", 300_000
    else:
        peak_tf, peak_ms = "15m", 900_000
    scan_mod.PEAK_TF, scan_mod.PEAK_TF_MS = peak_tf, peak_ms
    scan_mod.PEAK_FETCH_LIMIT = min(1000, hours * 3_600_000 // peak_ms + 40)
    t0 = time.time()
    snap = await scan_mod.scan(hours=hours)
    elapsed = time.time() - t0
    items = snap["items"]
    floor_live = snap["min_quote_volume"]
    sets = {f: [i for i in items if (i.get("quote_volume_24h") or 0) >= f] for f in FLOORS}
    if floor_live > min(FLOORS):
        print(f"UYARI: canlı taban {floor_live:,.0f} > {min(FLOORS):,.0f}; düşük tabanlı küme eksik olabilir", file=sys.stderr)

    gen = dt.datetime.now(TZ)
    rule = snap["rule"]
    lines = [f"# H4 MA7↗MA20 kesişimleri — son {hours} saat, 5M / 10M hacim tabanı ({gen:%Y-%m-%d %H:%M})", "",
             f"Tarama: {snap['symbols_scanned']} TRY çifti (24 sa hacmi ≥ {floor_live / 1e6:g}M TL), {snap['errors']} hata, {elapsed:.0f} sn. "
             f"Kural: {rule['ma_type'].upper()} {'/'.join(map(str, rule['periods']))}, {', '.join(rule['rules'])}, "
             f"MA20 > MA99 şartı {'VAR' if rule['require_mid_above_slow'] else 'YOK'}. Pencere: son {hours} saatte KAPANAN H4 mumları "
             f"(sinyal = mum kapanışı). Ölçüm: sinyal kapanışından bu yana {peak_tf} mumlar — en yüksek artış = en yüksek high / sinyal kapanışı − 1; "
             f"en derin düşüş = en düşük low / sinyal kapanışı − 1; zirveye süre = zirve mumunun kapanışı − sinyal kapanışı; şu an = son {peak_tf} kapanışı. "
             f"Stop/hedef uygulanmadı. Hacim tabanı tarama ANINDAKİ 24 sa ticker hacmidir ({hours} saat önceki değil). "
             f"Eski sinyalin ölçüm penceresi daha uzundur (zirve için daha çok zaman); 'geçen' sütunu bunu gösterir.", "",
             "Not: yeni sinyallerin (geçen süre kısa) zirvesi henüz oluşmamış olabilir; 'geçen' sütunu bunu gösterir. "
             "Aynı sembolde birden çok kesişim ayrı satırdır; 1 gün + iz süren stop ile canlı sonuç bu ham zirveden düşüktür.", "",
             "## Özet", "",
             "| Hacim tabanı | Sinyal | Sembol | Ort. en yüksek artış | Medyan | Ort. zirveye süre | Medyan süre | Ort. en derin düşüş | Medyan düşüş | ≥%2 / ≥%5 / ≥%10 zirve payı | ≤−%8 düşüş payı |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
    summaries = {}
    for f in FLOORS:
        s = summarize(sets[f]); summaries[f] = s
        lines += summary_rows(f"≥ {f / 1e6:g}M TL", s)
    lines.append("")
    for f in FLOORS:
        s = summaries[f]
        if s.get("measured"):
            lines.append(f"- ≥ {f / 1e6:g}M: şu an ortalama {s['now_mean']:+.2f}%, sinyallerin {s['now_pos']:.0%}'i artıda; sinyalden bu yana ortalama {s['elapsed_mean_h']:.1f} sa geçti.")
    # Mum kapanışına göre kırılım (toplu piyasa hareketi görünsün)
    lines += ["", "## Mum kapanışına göre (≥ 5M)", "", "| Kapanış | Sinyal | Ort. en yüksek artış | Ort. zirveye süre | Ort. en derin düşüş |", "|---|---:|---:|---:|---:|"]
    by_close: dict = {}
    for i in sets[FLOORS[0]]:
        by_close.setdefault(i["bar_close_ms"], []).append(i)
    for cms in sorted(by_close, reverse=True):
        grp = [i for i in by_close[cms] if i.get("max_rise_pct") is not None]
        t = dt.datetime.fromtimestamp(cms / 1000, TZ)
        if grp:
            lines.append(f"| {t:%d.%m %H:%M} | {len(by_close[cms])} | {st.mean(i['max_rise_pct'] for i in grp):+.2f}% | "
                         f"{_fmt_dur(st.mean(i['minutes_to_max'] for i in grp))} | {st.mean(i['max_drop_pct'] for i in grp):+.2f}% |")
        else:
            lines.append(f"| {t:%d.%m %H:%M} | {len(by_close[cms])} | — | — | — |")
    head = ("| Sembol | Mum kapanışı | 24 sa hacim | Sinyal fiyatı | En yüksek artış | Zirve fiyatı | Zirve zamanı | Zirveye süre | En derin düşüş | Şu an | Geçen |",
            "|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|")
    for f in FLOORS:
        rows = sorted(sets[f], key=lambda i: (-(i.get("max_rise_pct") or -999), i["symbol"]))
        lines += ["", f"## Sinyaller — 24 sa hacmi ≥ {f / 1e6:g}M TL ({len(rows)} sinyal)", "", *head, *[item_row(i) for i in rows]]
    lines += ["", "## Okuma", "",
              "- Ortalamayı az sayıda büyük zirve taşır; medyan daha temsilidir. Zirveye süre, kesişim sonrası ne kadar beklemek gerektiğini gösterir.",
              "- 10M tabanı 5M kümesinin alt kümesidir; fark, 5–10M arası çiftlerin katkısıdır.",
              "- Bu iki günlük kesit tek bir piyasa rejimidir; 90 günlük replay (docs/MA_BUY_H4_REPLAY_7_20_90g_2026-10-21.md) ile birlikte okunmalı.", ""]
    md = "\n".join(lines)
    path = os.path.join(DOCS_DIR, f"MA_BUY_H4_KESISIM_{hours}sa_HACIM_5M_10M_{gen:%Y-%m-%d}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(WORK_DIR, f"ma_buy_h4_scan_{hours}h_{gen:%Y-%m-%d_%H%M}.json"), "w", encoding="utf-8") as fh:
        json.dump({"snapshot": snap, "summaries": {str(int(k / 1e6)) + "M": v for k, v in summaries.items()}}, fh, ensure_ascii=False, indent=1)
    print(md)
    print(f"\nRapor: {path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
