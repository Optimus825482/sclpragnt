"""Teknik tarama listesinin geriye dönük sınaması — her gün 09:00'da liste, sonraki 09:00'a kadar sonuç (2026-10-22).

Soru (kullanıcı): "3 gün üst üste sabah 09:00'da bu listeyi isteseydim, o andaki veriye göre komisyon hariç en az %2
artacakları nasıl verirdin; bir sonraki listeye kadar MFE ve MFE süreleri ne olurdu; her birinden 10.000 TL alsaydım
T2'ye varanı sat, %5 stop ile günlük K/Z ne olurdu?"

Yöntem (ileriye bakma yok, yalnız 09:00'dan önce KAPANMIŞ mumlar):
  * Evren: bugünkü 24 sa hacmi ≥ 5M TL olan TRY çiftleri (o günkü hacim değil — küçük bir seçim yanlılığı, raporda yazılır).
  * Tarama: `ta_symbol_report.analyze` (aynı göstergeler) 09:00 kesitiyle; aday = yön puanı ≥ +3 (YÜKSELİŞ) ve T2'de iki
    bacak komisyon (%0,1125 × 2) sonrası net ≥ %2. Giriş = 09:00'dan önceki son 15m kapanışı (= analizin "şu an"ı).
  * Sonuç penceresi: 09:00 → ertesi 09:00, 15m mumlarla. Çıkış sırası kötümser: aynı mumda stop ve hedef → stop.
    Stop %5 (giriş altı), hedef T2'de satış, ikisi de olmazsa penceredeki son kapanışta çıkış. MFE = pencere boyunca en
    yüksek high / giriş − 1 (çıkıştan bağımsız), MFE süresi = o mumun kapanışına kadar geçen süre; MAE = en düşük low.
  * K/Z: 10.000 TL, alım ve satış komisyonu düşülmüş net TL.

Çıktı: docs/TARAMA_GERIYE_DONUK_<tarih>.html (+ .json). Bir yatırım tavsiyesi değildir.

KULLANIM: python backend/scripts/ta_screen_backtest.py --days 2026-10-18 2026-10-19 2026-10-20 2026-10-21
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

import ta_symbol_report as T                  # noqa: E402
from app import ma_buy_h4_scan as scan_mod    # noqa: E402
from app.binance_tr_public import klines      # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=3))
FEE = 0.001125
STAKE = 10000.0
MIN_NET_PCT = 2.0
STOP_PCT = 5.0
M15 = 900_000
DOCS_DIR = T.DOCS_DIR
WORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")


def net_pct(ref: float, target: float) -> float:
    return ((target / ref) * (1 - FEE) ** 2 - 1) * 100


def cut(data: dict, cutoff_ms: int) -> dict:
    return {tf: [b for b in bars if b["t"] + T.TF_MS[tf] <= cutoff_ms] for tf, bars in data.items()}


def simulate(entry: float, t2: float, b15: list[dict], start_ms: int, end_ms: int) -> dict:
    """15m mumlarla ileri simülasyon [start, end)."""
    win = [b for b in b15 if start_ms <= b["t"] < end_ms]
    stop = entry * (1 - STOP_PCT / 100)
    out = {"bars": len(win), "mfe_pct": None, "mfe_min": None, "mae_pct": None, "exit": None, "exit_price": None, "exit_min": None}
    if not win:
        return out
    hi_i = max(range(len(win)), key=lambda k: (win[k]["h"], -k))
    out["mfe_pct"] = (win[hi_i]["h"] / entry - 1) * 100
    out["mfe_min"] = (win[hi_i]["t"] + M15 - start_ms) / 60000
    out["mae_pct"] = (min(b["l"] for b in win) / entry - 1) * 100
    for b in win:
        if b["l"] <= stop:
            out.update({"exit": "stop", "exit_price": stop, "exit_min": (b["t"] + M15 - start_ms) / 60000}); break
        if b["h"] >= t2:
            out.update({"exit": "t2", "exit_price": t2, "exit_min": (b["t"] + M15 - start_ms) / 60000}); break
    if out["exit"] is None:
        out.update({"exit": "zaman", "exit_price": win[-1]["c"], "exit_min": (win[-1]["t"] + M15 - start_ms) / 60000})
    out["net_tl"] = STAKE * (1 - FEE) / entry * out["exit_price"] * (1 - FEE) - STAKE
    return out


def simulate_exit(entry: float, b15: list[dict], start_ms: int, end_ms: int, target: float | None,
                  stop_pct: float, trail: tuple | None = None) -> dict:
    """Genel çıkış: sabit stop + isteğe bağlı hedef + isteğe bağlı iz süren (tetik%, mesafe%). Kötümser sıra: stop → hedef."""
    win = [b for b in b15 if start_ms <= b["t"] < end_ms]
    if not win:
        return {"exit": None, "net_tl": 0.0}
    stop = entry * (1 - stop_pct / 100)
    peak = entry
    for b in win:
        if b["l"] <= stop:
            px = stop
            return {"exit": "stop", "exit_price": px, "net_tl": STAKE * (1 - FEE) / entry * px * (1 - FEE) - STAKE}
        if target is not None and b["h"] >= target:
            return {"exit": "t2", "exit_price": target, "net_tl": STAKE * (1 - FEE) / entry * target * (1 - FEE) - STAKE}
        if trail is not None:
            peak = max(peak, b["h"])
            if peak >= entry * (1 + trail[0] / 100):
                stop = max(stop, peak * (1 - trail[1] / 100))
    px = win[-1]["c"]
    return {"exit": "zaman", "exit_price": px, "net_tl": STAKE * (1 - FEE) / entry * px * (1 - FEE) - STAKE}


def fwd_max_pct(b15: list[dict], horizon_bars: int = 96, days: int = 7) -> list[float]:
    """Son `days` günde her 15m mumdan sonraki `horizon_bars` mumun en yüksek high'ı / kapanış − 1 (%)."""
    n = len(b15)
    lo = max(0, n - days * 96 - horizon_bars)
    out = []
    for i in range(lo, n - horizon_bars):
        c = b15[i]["c"]
        if c <= 0:
            continue
        out.append((max(b["h"] for b in b15[i + 1:i + 1 + horizon_bars]) / c - 1) * 100)
    return out


def pctl(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * (len(v) - 1)))]


VARIANTS = ["T2 (mevcut)", "sabit +3%", "sabit +4%", "sabit +5%", "sabit +6%", "sabit +8%",
            "ATR4h ×1", "ATR4h ×1,5", "ATR4h ×2", "24sa zirve p50", "24sa zirve p60", "24sa zirve p70",
            "7g tepe", "iz süren 3/1,5", "iz süren 4/2", "iz süren 5/2,5", "hedef yok (zaman)"]


def variant_target(name: str, x: dict) -> tuple:
    """(hedef fiyat | None, iz süren | None)"""
    e = x["entry"]
    if name == "T2 (mevcut)":
        return x["t2"], None
    if name.startswith("sabit"):
        return e * (1 + float(name.split("+")[1].rstrip("%")) / 100), None
    if name.startswith("ATR4h"):
        k = float(name.split("×")[1].replace(",", "."))
        return (e * (1 + k * x["atr4_pct"] / 100)) if x.get("atr4_pct") else None, None
    if name.startswith("24sa zirve"):
        q = int(name[-2:]) / 100
        v = x.get("fwd_p", {}).get(q)
        return (e * (1 + v / 100)) if v is not None and v > 0 else None, None
    if name == "7g tepe":
        return x["hi7d"] if x.get("hi7d") and x["hi7d"] > e * 1.005 else None, None
    if name.startswith("iz süren"):
        a, b = name.split(" ")[2].split("/")
        return None, (float(a.replace(",", ".")), float(b.replace(",", ".")))
    return None, None


def btc_regime(d: dict | None, cutoff_ms: int) -> dict:
    """09:00 kesitinde BTC rejim bayrakları (True = liste verilebilir)."""
    out = {"BTC 4h kapanış > SMA20": False, "BTC 4h SMA7 > SMA20": False, "BTC 1h EMA20 > EMA50": False,
           "BTC 24 sa değişim ≥ 0": False, "BTC 4h RSI > 50": False, "_btc_chg24": None}
    if not d:
        return out
    pit = cut(d, cutoff_ms)
    c4 = [b["c"] for b in pit["4h"]]
    c1 = [b["c"] for b in pit["1h"]]
    if len(c4) >= 25 and len(c1) >= 60:
        s7, s20 = T.last(T.sma(c4, 7)), T.last(T.sma(c4, 20))
        e20, e50 = T.last(T.ema(c1, 20)), T.last(T.ema(c1, 50))
        rsi4 = T.last(__import__("app.ma_buy_signals", fromlist=["x"]).rsi_series(c4, 14))
        chg = (c1[-1] / c1[-25] - 1) * 100 if len(c1) >= 25 else None
        out.update({"BTC 4h kapanış > SMA20": bool(s20 and c4[-1] > s20), "BTC 4h SMA7 > SMA20": bool(s7 and s20 and s7 > s20),
                    "BTC 1h EMA20 > EMA50": bool(e20 and e50 and e20 > e50), "BTC 24 sa değişim ≥ 0": bool(chg is not None and chg >= 0),
                    "BTC 4h RSI > 50": bool(rsi4 and rsi4 > 50), "_btc_chg24": chg})
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


async def main() -> int:
    global STOP_PCT
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", nargs="+", default=["2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"])
    ap.add_argument("--hour", type=int, default=9)
    ap.add_argument("--stop", type=float, default=STOP_PCT, help="stop yüzdesi (varsayılan 5)")
    args = ap.parse_args()
    STOP_PCT = float(args.stop)
    now_ms = int(time.time() * 1000)
    days = [dt.datetime.fromisoformat(d).replace(hour=args.hour, minute=0, second=0, microsecond=0, tzinfo=TZ) for d in args.days]
    uni = await scan_mod.universe()
    syms = [u["symbol"] for u in uni]
    print(f"evren {len(syms)} sembol; günler {', '.join(d.strftime('%d.%m %H:%M') for d in days)}", file=sys.stderr)
    sem = asyncio.Semaphore(4)
    data: dict = {}
    t0 = time.time()

    async def fetch(sym):
        try:
            async with sem:
                d = await T.fetch_all(sym, now_ms)
                # 15m geçmişini uzat: ilk mumdan önceki 1000 mum daha (7 günlük tarihsel "görme oranı" her kesitte dolu olsun).
                if d["15m"]:
                    older = T.bars(await klines(sym, "15m", limit=1000, end_time_ms=d["15m"][0]["t"] - 1), T.TF_MS["15m"], now_ms)
                    seen = {b["t"] for b in d["15m"]}
                    d["15m"] = [b for b in older if b["t"] not in seen] + d["15m"]
                data[sym] = d
        except Exception as exc:  # noqa: BLE001
            print(f"  {sym}: veri yok ({type(exc).__name__})", file=sys.stderr)
    await asyncio.gather(*(fetch(s) for s in syms))
    print(f"veri {len(data)} sembol, {time.time() - t0:.0f} sn", file=sys.stderr)

    report = []
    for i, day in enumerate(days):
        start_ms = int(day.timestamp() * 1000)
        end_ms = int((day + dt.timedelta(days=1)).timestamp() * 1000)
        partial = end_ms > now_ms
        end_eff = min(end_ms, now_ms)
        rows = []
        breadth_n = breadth_up = 0
        for sym, d in data.items():
            pit = cut(d, start_ms)
            if len(pit["15m"]) < 300 or len(pit["1h"]) < 60 or len(pit["4h"]) < 40 or not pit["1d"]:
                continue
            try:
                _, s = T.analyze(sym, None, pit, start_ms)
            except Exception:  # noqa: BLE001
                continue
            breadth_n += 1
            breadth_up += s["score"] >= 1
            if s["score"] < 3:
                continue
            n2 = net_pct(s["px"], s["t2"])
            if n2 < MIN_NET_PCT:
                continue
            sim = simulate(s["px"], s["t2"], d["15m"], start_ms, end_eff)
            atr4 = T.atr(pit["4h"])
            fm = fwd_max_pct(pit["15m"])
            x = {"sym": sym, "entry": s["px"], "score": s["score"], "t1": s["t1"], "t2": s["t2"], "d2": s["d2"], "net2": n2,
                 "r2": s["r2"], "m2": s["m2"], "inval": s["inval"], "atr4_pct": (atr4 / s["px"] * 100) if atr4 else None,
                 "fwd_p": {0.5: pctl(fm, 0.5), 0.6: pctl(fm, 0.6), 0.7: pctl(fm, 0.7)},
                 "hi7d": max(b["h"] for b in pit["15m"][-672:]) if pit["15m"] else None, **sim}
            x["variants"] = {}
            for vname in VARIANTS:
                tgt, trail = variant_target(vname, x)
                if vname != "hedef yok (zaman)" and tgt is None and trail is None:
                    x["variants"][vname] = None
                    continue
                x["variants"][vname] = simulate_exit(s["px"], d["15m"], start_ms, end_eff, tgt, STOP_PCT, trail)
            rows.append(x)
        rows.sort(key=lambda r: -(r["net2"] * (r["r2"] or 0)))
        done = [r for r in rows if r["exit"] is not None]
        summ = {"n": len(rows), "t2": sum(1 for r in done if r["exit"] == "t2"), "stop": sum(1 for r in done if r["exit"] == "stop"),
                "zaman": sum(1 for r in done if r["exit"] == "zaman"), "net": sum(r["net_tl"] for r in done),
                "mfe_mean": st.mean(r["mfe_pct"] for r in done) if done else None,
                "mfe_median": st.median(r["mfe_pct"] for r in done) if done else None,
                "mfe_min_mean": st.mean(r["mfe_min"] for r in done) if done else None,
                "mfe_min_median": st.median(r["mfe_min"] for r in done) if done else None,
                "mae_mean": st.mean(r["mae_pct"] for r in done) if done else None,
                "mfe_ge2": (sum(1 for r in done if r["mfe_pct"] >= 2) / len(done)) if done else None}
        btc = btc_regime(data.get("BTCTRY") or data.get("BTCUSDT"), start_ms)
        btc["genişlik ≥ %40"] = (breadth_up / breadth_n) >= 0.40 if breadth_n else False
        btc["genişlik ≥ %50"] = (breadth_up / breadth_n) >= 0.50 if breadth_n else False
        btc["_breadth"] = (breadth_up / breadth_n) if breadth_n else None
        report.append({"day": day, "partial": partial, "end": end_eff, "rows": rows, "summary": summ, "btc": btc})
        print(f"  {day:%d.%m} liste {len(rows)} | T2 {summ['t2']} stop {summ['stop']} zaman {summ['zaman']} | net {summ['net']:+.0f} TL", file=sys.stderr)

    gen = dt.datetime.now(TZ)
    # ------------------------------------------------------------------------------------------------- HTML
    css = """
    body{margin:0;padding:18px;background:#0f1131;color:#e8eaf6;font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
    h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:26px 0 8px;color:#c7cbea}
    p.sub{color:#8f95bf;font-size:12px;max-width:1100px}
    .wrap{overflow-x:auto;border:1px solid #2a2e5c;border-radius:10px;background:#171a3f;margin-bottom:10px}
    table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
    th,td{padding:6px 9px;border-bottom:1px solid #2a2e5c;text-align:right;white-space:nowrap}
    th{color:#8f95bf;font-size:12px;position:sticky;top:0;background:#171a3f}td:first-child,th:first-child{text-align:left}
    .pos{color:#22c55e}.neg{color:#ef4444}.flat{color:#8f95bf}.b{font-weight:700}
    .tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:700}
    .t2{background:rgba(34,197,94,.18);color:#22c55e}.st{background:rgba(239,68,68,.18);color:#ef4444}.zm{background:rgba(96,165,250,.18);color:#60a5fa}
    .kpi{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 12px}.kpi div{background:#171a3f;border:1px solid #2a2e5c;border-radius:8px;padding:8px 12px;min-width:150px}
    .kpi b{display:block;font-size:17px}.kpi span{color:#8f95bf;font-size:12px}
    """
    def c(x):
        return "pos" if x is not None and x > 0 else "neg" if x is not None and x < 0 else "flat"
    H = [f"<!doctype html><html lang='tr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Tarama Geriye Dönük (stop %{STOP_PCT:g})</title><style>{css}</style></head><body>",
         f"<h1>Sabah 09:00 tarama listesi — geriye dönük sınama ({gen:%d.%m.%Y %H:%M})</h1>",
         "<p class='sub'>Her gün 09:00'da yalnız o ana kadar kapanmış mumlarla aynı teknik tarama (yön puanı ≥ +3 ve T2'de iki bacak komisyon sonrası net ≥ %2). "
         f"Giriş: 09:00'dan önceki son 15 dk kapanışı. Pencere: ertesi 09:00'a kadar, 15 dk mumlarla. Çıkış: %{STOP_PCT:g} stop (aynı mumda stop ve hedef → stop), T2'de satış, "
         "yoksa penceredeki son kapanış. MFE = pencere boyunca en yüksek high'a göre artış (çıkıştan bağımsız), MFE süresi o muma kadar geçen süre; MAE = en düşük low. "
         f"10.000 TL/sembol, komisyon %0,1125/bacak. Evren: bugün 24 sa hacmi ≥ 5M TL olan {len(syms)} çift (o günkü değil; küçük seçim yanlılığı). Yatırım tavsiyesi değildir.</p>"]
    tot_net = sum(r["summary"]["net"] for r in report)
    tot_n = sum(r["summary"]["n"] for r in report)
    tot_t2 = sum(r["summary"]["t2"] for r in report)
    tot_stop = sum(r["summary"]["stop"] for r in report)
    all_done = [row for r in report for row in r["rows"] if row["exit"] is not None]
    H.append("<div class='kpi'>"
             f"<div><b class='{c(tot_net)}'>{ftl(tot_net)}</b><span>toplam net ({len(report)} gün)</span></div>"
             f"<div><b>{tot_n}</b><span>toplam sinyal</span></div>"
             f"<div><b class='pos'>{tot_t2}</b><span>T2'de satış</span></div>"
             f"<div><b class='neg'>{tot_stop}</b><span>%{STOP_PCT:g} stop</span></div>"
             f"<div><b>{fpct(st.mean(r['mfe_pct'] for r in all_done)) if all_done else '—'}</b><span>ort. MFE</span></div>"
             f"<div><b>{fdur(st.median(r['mfe_min'] for r in all_done)) if all_done else '—'}</b><span>medyan MFE süresi</span></div>"
             "</div>")
    H += ["<h2>Gün özeti</h2><div class='wrap'><table><tr><th>Liste</th><th>Pencere</th><th>Sinyal</th><th>T2</th><th>Stop</th><th>Zaman</th>"
          "<th>Net K/Z</th><th>Sermaye</th><th>Getiri</th><th>Ort. MFE</th><th>Medyan MFE</th><th>MFE ≥ %2</th><th>Ort. MFE süresi</th><th>Medyan MFE süresi</th><th>Ort. MAE</th></tr>"]
    for r in report:
        s = r["summary"]; cap = s["n"] * STAKE
        H.append(f"<tr><td class='b'>{r['day']:%d.%m %H:%M}</td><td>{'→ ' + dt.datetime.fromtimestamp(r['end'] / 1000, TZ).strftime('%d.%m %H:%M') + (' (kısmi)' if r['partial'] else '')}</td>"
                 f"<td>{s['n']}</td><td class='pos'>{s['t2']}</td><td class='neg'>{s['stop']}</td><td>{s['zaman']}</td><td class='{c(s['net'])} b'>{ftl(s['net'])}</td>"
                 f"<td>{cap:,.0f} TL</td><td class='{c(s['net'])}'>{fpct(s['net'] / cap * 100 if cap else None)}</td>"
                 f"<td>{fpct(s['mfe_mean'])}</td><td>{fpct(s['mfe_median'])}</td><td>{'—' if s['mfe_ge2'] is None else f'{s['mfe_ge2']:.0%}'}</td>"
                 f"<td>{fdur(s['mfe_min_mean'])}</td><td>{fdur(s['mfe_min_median'])}</td><td>{fpct(s['mae_mean'])}</td></tr>".replace(",", "."))
    H.append("</table></div>")
    # ---- hedef varyantları
    H += ["<h2>Hedef varyantları — aynı listeler, aynı stop, farklı çıkış</h2>",
          "<p class='sub'>Seçim (liste) değişmedi; yalnız satış hedefi değişti. 'ATR4h ×k' = giriş × (1 + k × 4 saatlik ATR%); "
          "'24sa zirve pXX' = sembolün son 7 gündeki 24 saatlik ileri zirve dağılımının XX. yüzdeliği; 'iz süren a/b' = +%a'dan sonra zirvenin %b altından takip, hedef yok; "
          "'hedef yok' = yalnız stop + süre dolumu. Hedef hesaplanamayan sinyal o varyantta atlanır (n sütunu).</p>",
          "<div class='wrap'><table><tr><th>Varyant</th><th>n</th><th>Hedef isabeti</th><th>Stop</th><th>Zaman</th><th>Toplam net</th><th>Sinyal başı</th><th>Ort. hedef mesafesi</th>"
          + "".join(f"<th>{r['day']:%d.%m}</th>" for r in report) + "</tr>"]
    vsum = []
    for vname in VARIANTS:
        n = hit = stp = zm = 0; net = 0.0; dist = []; per_day = []
        for r in report:
            dn = 0.0
            for x in r["rows"]:
                v = x["variants"].get(vname)
                if not v or v.get("exit") is None:
                    continue
                n += 1; net += v["net_tl"]; dn += v["net_tl"]
                hit += v["exit"] == "t2"; stp += v["exit"] == "stop"; zm += v["exit"] == "zaman"
                tgt, _ = variant_target(vname, x)
                if tgt:
                    dist.append((tgt / x["entry"] - 1) * 100)
            per_day.append(dn)
        vsum.append((vname, n, hit, stp, zm, net, per_day, st.mean(dist) if dist else None))
    for vname, n, hit, stp, zm, net, per_day, md in sorted(vsum, key=lambda v: -v[5]):
        H.append(f"<tr><td class='b'>{vname}</td><td>{n}</td><td class='pos'>{hit}</td><td class='neg'>{stp}</td><td>{zm}</td><td class='{c(net)} b'>{ftl(net)}</td>"
                 f"<td class='{c(net)}'>{ftl(net / n) if n else '—'}</td><td>{fpct(md, 1)}</td>" + "".join(f"<td class='{c(v)}'>{ftl(v)}</td>" for v in per_day) + "</tr>")
    H.append("</table></div>")
    for vname, n, hit, stp, zm, net, per_day, md in sorted(vsum, key=lambda v: -v[5]):
        print(f"  {vname:20} n={n:3} hedef={hit:3} stop={stp:2} zaman={zm:3} net={net:+8.0f} TL  sinyal başı {net / n if n else 0:+6.0f}  ort.mesafe {md if md is not None else float('nan'):+.1f}%", file=sys.stderr)
    # ---- piyasa filtreleri
    FILTERS = [k for k in report[0]["btc"] if not k.startswith("_")] if report else []
    EXITS = ["T2 (mevcut)", "sabit +3%", "iz süren 3/1,5"]
    H += ["<h2>Piyasa filtresi — filtre kapalıysa o gün liste verilmez</h2>",
          "<p class='sub'>Her sabah 09:00'da BTCTRY'nin durumu (ya da taranan sembollerin kaçının yükseliş puanlı olduğu = genişlik). Filtre o gün 'kapalı' diyorsa listedeki hiçbir sinyal alınmaz. "
          "Üç satış kuralıyla toplam net; 'gün' sütunlarında ✓ = o gün liste verildi.</p>",
          "<div class='wrap'><table><tr><th>Filtre</th><th>Açık gün</th><th>Sinyal</th>" + "".join(f"<th>{e}</th>" for e in EXITS)
          + "".join(f"<th>{r['day']:%d.%m}</th>" for r in report) + "</tr>"]

    def day_net(r, exit_name):
        if exit_name == "T2 (mevcut)":
            return sum(x["net_tl"] for x in r["rows"] if x.get("exit")), len([x for x in r["rows"] if x.get("exit")])
        tot = n = 0
        for x in r["rows"]:
            v = x["variants"].get(exit_name)
            if v and v.get("exit"):
                tot += v["net_tl"]; n += 1
        return tot, n
    lines_f = [("filtre yok", [True] * len(report))] + [(f, [bool(r["btc"].get(f)) for r in report]) for f in FILTERS]
    for fname, flags in lines_f:
        nets = []
        nsig = 0
        for e in EXITS:
            tot = 0.0
            for r, ok in zip(report, flags):
                if ok:
                    t, n = day_net(r, e); tot += t
                    if e == EXITS[0]:
                        nsig += n
            nets.append(tot)
        H.append(f"<tr><td class='b'>{fname}</td><td>{sum(flags)}/{len(flags)}</td><td>{nsig}</td>" + "".join(f"<td class='{c(v)} b'>{ftl(v)}</td>" for v in nets)
                 + "".join("<td class='pos'>✓</td>" if ok else "<td class='neg'>✗</td>" for ok in flags) + "</tr>")
        print(f"  filtre {fname:26} açık {sum(flags)}/{len(flags)} sinyal {nsig:3} | " + " | ".join(f"{e}: {v:+7.0f}" for e, v in zip(EXITS, nets)), file=sys.stderr)
    H.append("</table></div>")
    H.append("<p class='sub'>BTC 24 sa değişimi (09:00): " + ", ".join(f"{r['day']:%d.%m} {fpct(r['btc'].get('_btc_chg24'), 1)}" for r in report)
             + " · Genişlik (puan ≥ +1 payı): " + ", ".join(f"{r['day']:%d.%m} {('—' if r['btc'].get('_breadth') is None else f'{r['btc']['_breadth']:.0%}')}" for r in report) + "</p>")
    for r in report:
        H += [f"<h2>{r['day']:%d.%m.%Y} 09:00 listesi — {len(r['rows'])} sinyal{' (pencere kısmi, ' + dt.datetime.fromtimestamp(r['end'] / 1000, TZ).strftime('%d.%m %H:%M') + ' itibarıyla)' if r['partial'] else ''}</h2>",
              f"<div class='wrap'><table><tr><th>Sembol</th><th>Giriş</th><th>Puan</th><th>T1</th><th>T2</th><th>T2 net</th><th>Görme / medyan</th><th>Stop (%{STOP_PCT:g})</th>"
              "<th>MFE</th><th>MFE süresi</th><th>MAE</th><th>Çıkış</th><th>Çıkış fiyatı</th><th>Çıkış süresi</th><th>Net K/Z</th></tr>"]
        for x in r["rows"]:
            tag = {"t2": "<span class='tag t2'>T2</span>", "stop": "<span class='tag st'>STOP</span>", "zaman": "<span class='tag zm'>ZAMAN</span>", None: "—"}[x["exit"]]
            H.append(f"<tr><td class='b'>{html.escape(x['sym'].replace('TRY', ''))}</td><td>{fp(x['entry'])}</td><td>{x['score']:+d}</td><td>{fp(x['t1'])}</td>"
                     f"<td>{fp(x['t2'])} <span class='flat'>({fpct(x['d2'], 1)})</span></td><td class='pos'>{fpct(x['net2'])}</td>"
                     f"<td>{'—' if x['r2'] is None else f'{x['r2']:.0%}'} / {('—' if x['m2'] is None else f'{x['m2']:.1f} sa')}</td><td>{fp(x['entry'] * (1 - STOP_PCT / 100))}</td>"
                     f"<td class='{c(x['mfe_pct'])}'>{fpct(x['mfe_pct'])}</td><td>{fdur(x['mfe_min'])}</td><td class='neg'>{fpct(x['mae_pct'])}</td>"
                     f"<td>{tag}</td><td>{fp(x['exit_price'])}</td><td>{fdur(x['exit_min'])}</td><td class='{c(x.get('net_tl'))} b'>{ftl(x.get('net_tl'))}</td></tr>")
        H.append("</table></div>")
    H += ["<h2>Okuma</h2><ul>",
          "<li>Gün özeti satırı o günün listesine 10.000 TL/sembol koyup kuralı uygulamanın net sonucudur; 'Sermaye' o gün bağlanan toplam para.</li>",
          "<li>MFE çıkıştan bağımsız ham zirvedir; T2'de satış kuralı zirvenin yalnız T2'ye kadar olan kısmını alır, stop ise MFE'den önce gelebilir.</li>",
          "<li>Tek günlük listeler piyasa yönüne bağlıdır; dört günün işareti aynıysa kural, farklıysa gün anlamlıdır.</li>",
          "<li>Evren bugünkü likit çiftlerdir; o gün hacimsiz olup bugün likit olan bir çift listeye girmiş olabilir (küçük yanlılık).</li></ul></body></html>"]
    path = os.path.join(DOCS_DIR, f"TARAMA_GERIYE_DONUK_{len(report)}gun_stop{STOP_PCT:g}_{gen:%Y-%m-%d_%H%M}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(H))
    with open(os.path.join(WORK_DIR, f"ta_screen_backtest_{gen:%Y-%m-%d_%H%M}.json"), "w", encoding="utf-8") as fh:
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
