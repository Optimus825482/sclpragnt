"""N6 kuralı — günlük 00:00 kesitlerinde geriye dönük replay, HTML rapor (2026-10-22, kullanıcı isteği).

Her gün 00:00'da (Türkiye saati) yalnız o ana kadar kapanmış mumlarla N6 listesi (ta_n6_tracker.build_list ile aynı:
kapı + onay + günlük RSI < 60 + olgun eleme, genişlik < 0,54 ise en iyi 3) üretilir; ertesi 00:00'a kadar 15 dk mumlarla
simülasyon: iz süren +%3'ten sonra zirvenin %1,5 altı, stop −%10, süre dolumu kapanıştan; aynı mumda stop ve iz süren →
stop. 10.000 TL/sembol, komisyon %0,1125/bacak. Veri: yerel arşiv (historical_candles 15m/1h/4h/1d).

Çıktı: docs/N6_REPLAY_<gün>gun_0000_<tarih>.html (+ work/...json).
KULLANIM: python backend/scripts/ta_n6_replay.py --days 2026-10-15 ... 2026-10-21 [--hour 0] [--top 3]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import html
import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ta_feature_study as FS                 # noqa: E402
import ta_symbol_report as T                  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=3))
FEE = 0.001125
STAKE = 10000.0
TRIG, GAP, STOP = 3.0, 1.5, 10.0
M15 = 900_000
MIN_QV = 5e6
BREADTH_FULL = 0.54
DOCS_DIR = T.DOCS_DIR
WORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")


def simulate(entry: float, b15: list[dict], start_ms: int, end_ms: int, partial: bool = False) -> dict:
    win = [b for b in b15 if start_ms <= b["t"] < end_ms]
    out = {"bars": len(win), "mfe": None, "mfe_min": None, "mae": None, "exit": None, "exit_px": None, "exit_min": None, "net": None, "trail": False}
    if not win:
        return out
    stop = entry * (1 - STOP / 100)
    peak, trough, trail_stop, mfe_at = entry, entry, None, None
    for b in win:
        t_close = b["t"] + M15
        if b["l"] <= stop:
            out.update({"exit": "stop", "exit_px": stop, "exit_min": (t_close - start_ms) / 60000}); break
        if trail_stop is not None and b["l"] <= trail_stop:
            out.update({"exit": "trail", "exit_px": trail_stop, "exit_min": (t_close - start_ms) / 60000}); break
        if b["h"] > peak:
            peak, mfe_at = b["h"], t_close
        trough = min(trough, b["l"])
        if peak >= entry * (1 + TRIG / 100):
            trail_stop = max(trail_stop or 0.0, peak * (1 - GAP / 100))
    if out["exit"] is None:   # pencere kısmiyse (arşiv sonu) pozisyon hâlâ AÇIK: son kapanıştan gerçekleşmemiş K/Z
        out.update({"exit": "open" if partial else "time", "exit_px": win[-1]["c"], "exit_min": (win[-1]["t"] + M15 - start_ms) / 60000})
    # MFE/MAE: pencerenin tamamı (çıkıştan bağımsız)
    hi_i = max(range(len(win)), key=lambda k: (win[k]["h"], -k))
    out.update({"mfe": (win[hi_i]["h"] / entry - 1) * 100, "mfe_min": (win[hi_i]["t"] + M15 - start_ms) / 60000,
                "mae": (min(b["l"] for b in win) / entry - 1) * 100, "trail": trail_stop is not None,
                "net": STAKE * (1 - FEE) / entry * out["exit_px"] * (1 - FEE) - STAKE})
    return out


def fdur(m):
    if m is None:
        return "—"
    h, r = divmod(int(round(m)), 60)
    return f"{h} sa {r:02d} dk" if h else f"{r} dk"


def fpct(x, d=2):
    return "—" if x is None else f"{x:+.{d}f}%".replace(".", ",")


def ftl(x):
    return "—" if x is None else (f"{x:+,.0f} TL").replace(",", ".")


def fp(x):
    return T.fmt(x)


def c(x):
    return "pos" if x is not None and x > 0 else "neg" if x is not None and x < 0 else "flat"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", nargs="+", default=["2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"])
    ap.add_argument("--hour", type=int, default=0)
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args()
    from app import database
    from app.binance_tr_public import trading_symbols
    days = [dt.datetime.fromisoformat(d).replace(hour=args.hour, minute=0, second=0, microsecond=0, tzinfo=TZ) for d in args.days]
    last = await database._run_db(lambda conn: conn.execute("SELECT MAX(open_time) AS mx FROM historical_candles WHERE timeframe='15m'").fetchone()["mx"])
    arch_end = int(last) + M15
    syms = sorted(await trading_symbols("TRY"))
    t0 = time.time()
    data = {}
    start_ms = int(days[0].timestamp() * 1000) - 40 * 86_400_000
    for i, sym in enumerate(syms, 1):
        if sym == "BTCTRY":
            continue
        d = await FS.load_db(sym, start_ms, arch_end)
        if d:
            data[sym] = d
        if i % 60 == 0 or i == len(syms):
            print(f"  DB: {i}/{len(syms)} ({time.time() - t0:.0f} sn)", file=sys.stderr)
    report = []
    for day in days:
        cms = int(day.timestamp() * 1000)
        end_ms = min(cms + 86_400_000, arch_end)
        partial = cms + 86_400_000 > arch_end
        feats = {}
        for sym, d in data.items():
            pit = FS.cut(d, cms)
            f = FS.features(sym, pit)
            if f is None or f["qv24"] < MIN_QV:
                continue
            feats[sym] = f
        breadth = sum(1 for f in feats.values() if f["score"] >= 1) / len(feats) if feats else 0.0
        cands = [dict(sym=s, **f) for s, f in feats.items() if FS._m2(f) and FS.g(f, "d_rsi", 100) < 60]
        cands.sort(key=lambda r: -(r.get("vol_ratio") or 0))
        picked = cands if breadth >= BREADTH_FULL else cands[:args.top]
        rows = []
        for r in picked:
            sim = simulate(r["px"], data[r["sym"]]["15m"], cms, end_ms, partial)
            rows.append({"sym": r["sym"], "entry": r["px"], "adx": r.get("adx4"), "di": r.get("di_diff"), "vol": r.get("vol_ratio"), "rsi1": r.get("rsi1"),
                         "drsi": r.get("d_rsi"), "chg24": r.get("chg24"), "score": r.get("score"), **sim})
        done = [x for x in rows if x["exit"]]
        summ = {"n": len(rows), "universe": len(feats), "breadth": breadth, "candidates": len(cands),
                "trail": sum(1 for x in done if x["exit"] == "trail"), "stop": sum(1 for x in done if x["exit"] == "stop"),
                "time": sum(1 for x in done if x["exit"] == "time"), "open": sum(1 for x in done if x["exit"] == "open"),
                "net": sum(x["net"] for x in done), "win": (sum(1 for x in done if x["net"] > 0) / len(done)) if done else None,
                "mfe_mean": st.mean(x["mfe"] for x in done) if done else None, "mfe_median": st.median(x["mfe"] for x in done) if done else None,
                "mfe_min_median": st.median(x["mfe_min"] for x in done) if done else None, "mae_mean": st.mean(x["mae"] for x in done) if done else None,
                "mfe_ge3": (sum(1 for x in done if x["mfe"] >= 3) / len(done)) if done else None}
        report.append({"day": day, "partial": partial, "end": end_ms, "rows": rows, "summary": summ})
        print(f"  {day:%d.%m %H:%M} evren {len(feats)} genişlik {breadth:.0%} aday {len(cands)} seçilen {len(rows)} | iz süren {summ['trail']} stop {summ['stop']} zaman {summ['time']} | net {summ['net']:+.0f} TL", file=sys.stderr)

    gen = dt.datetime.now(TZ)
    all_done = [x for r in report for x in r["rows"] if x["exit"]]
    tot_net = sum(x["net"] for x in all_done)
    css = """body{margin:0;padding:18px;background:#0f1131;color:#e8eaf6;font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
    h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:26px 0 8px;color:#c7cbea}p.sub{color:#8f95bf;font-size:12px;max-width:1100px}
    .wrap{overflow-x:auto;border:1px solid #2a2e5c;border-radius:10px;background:#171a3f;margin-bottom:10px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
    th,td{padding:6px 9px;border-bottom:1px solid #2a2e5c;text-align:right;white-space:nowrap}th{color:#8f95bf;font-size:12px;position:sticky;top:0;background:#171a3f}
    td:first-child,th:first-child{text-align:left}.pos{color:#22c55e}.neg{color:#ef4444}.flat{color:#8f95bf}.b{font-weight:700}
    .tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:700}.tr{background:rgba(245,158,11,.18);color:#f59e0b}.st{background:rgba(239,68,68,.18);color:#ef4444}.zm{background:rgba(96,165,250,.18);color:#60a5fa}
    .kpi{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 12px}.kpi div{background:#171a3f;border:1px solid #2a2e5c;border-radius:8px;padding:8px 12px;min-width:150px}.kpi b{display:block;font-size:17px}.kpi span{color:#8f95bf;font-size:12px}"""
    H = [f"<!doctype html><html lang='tr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>N6 Replay {len(report)} gün</title><style>{css}</style></head><body>",
         f"<h1>N6 kuralı — her gün {args.hour:02d}:00 listesi, geriye dönük replay ({gen:%d.%m.%Y %H:%M})</h1>",
         f"<p class='sub'>Kural: ADX 4h ≥ 25, +DI − −DI ≥ 10, 4h MACD histogramı artıyor, hacim 12 sa / 7 gün ≥ 1,5×, RSI 1h < 72, günlük RSI < 60, 4/4 MA üstü + 4h yüksek dip hariç; "
         f"evren 24 sa hacim ≥ 5M TL; genişlik < %54 ise en iyi {args.top} (hacim oranı). Her kesit yalnız o ana kadar kapanmış mumlarla (yerel arşiv, ileriye bakma yok). "
         f"Giriş: kesitten önceki son 15 dk kapanışı; pencere ertesi {args.hour:02d}:00'a kadar, 15 dk mumlarla. Çıkış: +%3 sonrası zirvenin %1,5 altı iz süren stop, −%10 stop, "
         f"süre dolumunda son kapanış; aynı mumda stop ve iz süren → stop. 10.000 TL/sembol, komisyon %0,1125/bacak. MFE/MAE pencerenin tamamı (çıkıştan bağımsız). Yatırım tavsiyesi değildir.</p>"]
    H.append("<div class='kpi'>"
             f"<div><b class='{c(tot_net)}'>{ftl(tot_net)}</b><span>toplam net ({len(report)} gün)</span></div>"
             f"<div><b>{len(all_done)}</b><span>toplam sinyal</span></div>"
             f"<div><b class='pos'>{sum(1 for x in all_done if x['exit'] == 'trail')}</b><span>iz süren çıkış</span></div>"
             f"<div><b class='neg'>{sum(1 for x in all_done if x['exit'] == 'stop')}</b><span>%10 stop</span></div>"
             f"<div><b>{(sum(1 for x in all_done if x['net'] > 0) / len(all_done) * 100):.0f}%</b><span>kazanma</span></div>" if all_done else ""
             f"<div><b>{fpct(st.mean(x['mfe'] for x in all_done)) if all_done else '—'}</b><span>ort. MFE</span></div>"
             f"<div><b>{fdur(st.median(x['mfe_min'] for x in all_done)) if all_done else '—'}</b><span>medyan MFE süresi</span></div>"
             "</div>")
    H += ["<h2>Gün özeti</h2><div class='wrap'><table><tr><th>Liste</th><th>Pencere</th><th>Evren</th><th>Genişlik</th><th>Aday</th><th>Seçilen</th><th>İz süren</th><th>Stop</th><th>Zaman</th>"
          "<th>Kazanma</th><th>Net K/Z</th><th>Sermaye</th><th>Getiri</th><th>Ort. MFE</th><th>Medyan MFE</th><th>MFE ≥ %3</th><th>Medyan MFE süresi</th><th>Ort. MAE</th></tr>"]
    for r in report:
        s = r["summary"]; cap = s["n"] * STAKE
        H.append(f"<tr><td class='b'>{r['day']:%d.%m %H:%M}</td><td>→ {dt.datetime.fromtimestamp(r['end'] / 1000, TZ):%d.%m %H:%M}{' (kısmi)' if r['partial'] else ''}</td>"
                 f"<td>{s['universe']}</td><td>{s['breadth']:.0%}</td><td>{s['candidates']}</td><td>{s['n']}</td><td class='pos'>{s['trail']}</td><td class='neg'>{s['stop']}</td><td>{s['time']}{(' + ' + str(s['open']) + ' açık') if s.get('open') else ''}</td>"
                 f"<td>{'—' if s['win'] is None else f'{s['win']:.0%}'}</td><td class='{c(s['net'])} b'>{ftl(s['net'])}</td><td>{cap:,.0f} TL</td><td class='{c(s['net'])}'>{fpct(s['net'] / cap * 100 if cap else None)}</td>"
                 f"<td>{fpct(s['mfe_mean'])}</td><td>{fpct(s['mfe_median'])}</td><td>{'—' if s['mfe_ge3'] is None else f'{s['mfe_ge3']:.0%}'}</td><td>{fdur(s['mfe_min_median'])}</td><td>{fpct(s['mae_mean'])}</td></tr>".replace(",", "."))
    H.append("</table></div>")
    for r in report:
        H += [f"<h2>{r['day']:%d.%m.%Y %H:%M} listesi — {len(r['rows'])} sinyal{' (pencere kısmi)' if r['partial'] else ''}</h2>",
              "<div class='wrap'><table><tr><th>Sembol</th><th>Giriş</th><th>ADX / DI</th><th>Hacim×</th><th>RSI 1h / gün</th><th>24 sa</th><th>Puan</th><th>MFE</th><th>MFE süresi</th><th>MAE</th>"
              "<th>İz süren tetiklendi</th><th>Çıkış</th><th>Çıkış fiyatı</th><th>Çıkış süresi</th><th>Net K/Z</th></tr>"]
        for x in sorted(r["rows"], key=lambda z: -(z["net"] or -1e9)):
            tag = {"trail": "<span class='tag tr'>İZ SÜREN</span>", "stop": "<span class='tag st'>STOP</span>", "time": "<span class='tag zm'>ZAMAN</span>",
                   "open": "<span class='tag zm'>AÇIK (arşiv sonu)</span>", None: "—"}[x["exit"]]
            H.append(f"<tr><td class='b'>{html.escape(x['sym'].replace('TRY', ''))}</td><td>{fp(x['entry'])}</td><td>{x['adx']:.0f} / {x['di']:.0f}</td><td>{x['vol']:.1f}×</td>"
                     f"<td>{x['rsi1']:.0f} / {x['drsi']:.0f}</td><td class='{c(x['chg24'])}'>{fpct(x['chg24'], 1)}</td><td>{x['score']:+d}</td>"
                     f"<td class='{c(x['mfe'])}'>{fpct(x['mfe'])}</td><td>{fdur(x['mfe_min'])}</td><td class='neg'>{fpct(x['mae'])}</td><td>{'evet' if x['trail'] else 'hayır'}</td>"
                     f"<td>{tag}</td><td>{fp(x['exit_px'])}</td><td>{fdur(x['exit_min'])}</td><td class='{c(x['net'])} b'>{ftl(x['net'])}</td></tr>")
        if not r["rows"]:
            H.append("<tr><td colspan='15' class='flat'>Bu kesitte kurala uyan sembol yok.</td></tr>")
        H.append("</table></div>")
    H += ["<h2>Okuma</h2><ul>",
          "<li>Gün satırı o günün listesine 10.000 TL/sembol koyup kuralı 24 saat uygulamanın net sonucudur; 'Sermaye' o gün bağlanan toplam.</li>",
          "<li>İZ SÜREN çıkışı kârda da zararda da olabilir (zirve +%3 görülüp geri çekilince); STOP −%10'dur.</li>",
          "<li>Bu kural 90 günlük çalışmada seçildi (örneklem içi); son 7 gün o çalışmanın parçası, yani bağımsız doğrulama değildir. İleriye dönük takip (takip_n6_*.html) gerçek sınavdır.</li></ul></body></html>"]
    path = os.path.join(DOCS_DIR, f"N6_REPLAY_{len(report)}gun_{args.hour:02d}00_{gen:%Y-%m-%d_%H%M}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(H))
    with open(os.path.join(WORK_DIR, f"n6_replay_{gen:%Y-%m-%d_%H%M}.json"), "w", encoding="utf-8") as fh:
        json.dump([{"day": r["day"].isoformat(), "partial": r["partial"], "summary": r["summary"], "rows": r["rows"]} for r in report], fh, ensure_ascii=False, indent=1, default=str)
    print(f"Rapor: {path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
