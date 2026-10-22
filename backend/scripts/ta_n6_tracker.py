"""N6 kuralı — belirli bir kesitte liste üret ve canlı izleme HTML'i yaz (2026-10-22, kullanıcı isteği).

Kural (docs/SINYAL_YENIDEN_KURMA_90gun_db_2026-10-22_0254.html, N6 + genişlik kapısı):
  kapı: ADX 4h ≥ 25, +DI − −DI ≥ 10, 4h MACD histogramı artıyor · onay: hacim 12 sa / 7 gün ort ≥ 1,5, RSI 1h < 72,
  günlük RSI < 60 · eleme: 4/4 MA üstü + 4h yüksek dip · evren: 24 sa hacim ≥ 5M TL · genişlik < 0,54 ise en iyi 3 (hacim oranı).
Çıkış (sayfa uygular): iz süren +%3'ten sonra zirvenin %1,5 altı, stop −%10, en çok 24 saat; 10.000 TL, komisyon %0,1125/bacak.

Liste yerel arşivden (historical_candles) kesit anına kadar kapanmış mumlarla hesaplanır (ileriye bakma yok).
HTML kök dizine yazılır: takip_n6_<tarih>.html; sayfa açılınca kesitten bu yana 15m mumları Binance TR REST'ten çekip
yolu tamamlar (MFE/MAE/iz süren/stop), sonra miniTicker WS ile canlı sürer.

KULLANIM: python backend/scripts/ta_n6_tracker.py --cutoff 2026-10-22T00:00 [--top 3]
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ta_feature_study as FS                 # noqa: E402
import ta_symbol_report as T                  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=3))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MIN_QV = 5e6
BREADTH_FULL = 0.54


async def build_list(cutoff_ms: int, top: int) -> dict:
    from app import database
    from app.binance_tr_public import trading_symbols
    syms = sorted(await trading_symbols("TRY"))
    start_ms = cutoff_ms - 40 * 86_400_000
    feats = {}
    t0 = time.time()
    for i, sym in enumerate(syms, 1):
        if sym == "BTCTRY":
            continue
        d = await FS.load_db(sym, start_ms, cutoff_ms)
        if not d:
            continue
        pit = FS.cut(d, cutoff_ms)
        f = FS.features(sym, pit)
        if f is None or f["qv24"] < MIN_QV:
            continue
        feats[sym] = f
        if i % 60 == 0:
            print(f"  {i}/{len(syms)} ({time.time() - t0:.0f} sn)", file=sys.stderr)
    breadth = sum(1 for f in feats.values() if f["score"] >= 1) / len(feats) if feats else 0.0
    cands = [dict(sym=s, **f) for s, f in feats.items() if FS._m2(f) and FS.g(f, "d_rsi", 100) < 60]
    cands.sort(key=lambda r: -(r.get("vol_ratio") or 0))
    picked = cands if breadth >= BREADTH_FULL else cands[:top]
    return {"cutoff_ms": cutoff_ms, "breadth": breadth, "universe": len(feats), "candidates": len(cands), "picked": picked}


def html_page(res: dict, cutoff: dt.datetime) -> str:
    rows = [{"sym": r["sym"], "entry": r["px"], "adx": r.get("adx4"), "di": r.get("di_diff"), "vol": r.get("vol_ratio"), "rsi1": r.get("rsi1"),
             "drsi": r.get("d_rsi"), "above4": r.get("above4"), "chg24": r.get("chg24"), "qv": r.get("qv24"), "score": r.get("score")} for r in res["picked"]]
    data = json.dumps({"cutoff_ms": res["cutoff_ms"], "breadth": res["breadth"], "universe": res["universe"], "candidates": res["candidates"], "rows": rows}, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>N6 Takip {cutoff:%d.%m %H:%M}</title>
<meta name="description" content="N6 kuralı ile {cutoff:%d.%m.%Y %H:%M} kesitinde seçilen semboller; iz süren 3/1,5 + %10 stop + 24 saat kuralının canlı izlemesi.">
<style>
  :root {{ --bg:#0f1131; --panel:#171a3f; --line:#2a2e5c; --text:#e8eaf6; --muted:#8f95bf; --green:#22c55e; --red:#ef4444; --amber:#f59e0b; --blue:#60a5fa; }}
  @media (prefers-color-scheme: light) {{ :root:not([data-theme="dark"]) {{ --bg:#f5f6fb; --panel:#fff; --line:#d9dcec; --text:#161a3a; --muted:#5d6390; }} }}
  :root[data-theme="light"] {{ --bg:#f5f6fb; --panel:#fff; --line:#d9dcec; --text:#161a3a; --muted:#5d6390; }}
  * {{ box-sizing:border-box; }} body {{ margin:0; padding:16px; background:var(--bg); color:var(--text); font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  h1 {{ font-size:20px; margin:0 0 4px; }} .sub {{ color:var(--muted); font-size:12px; margin-bottom:10px; max-width:1100px; }}
  .bar {{ display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; font-size:12px; color:var(--muted); margin-bottom:10px; }}
  .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; background:var(--red); margin-right:6px; vertical-align:middle; }} .dot.on {{ background:var(--green); }}
  .kpi {{ display:flex; flex-wrap:wrap; gap:10px; margin:8px 0 12px; }} .kpi div {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:8px 12px; min-width:140px; }}
  .kpi b {{ display:block; font-size:17px; }} .kpi span {{ color:var(--muted); font-size:12px; }}
  .wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--panel); }}
  table {{ border-collapse:collapse; width:100%; min-width:1100px; font-variant-numeric:tabular-nums; }}
  th,td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }} th {{ color:var(--muted); font-weight:600; font-size:12px; position:sticky; top:0; background:var(--panel); }}
  td:first-child,th:first-child {{ text-align:left; }} tr:last-child td {{ border-bottom:0; }} .sym {{ font-weight:700; }}
  .pos {{ color:var(--green); }} .neg {{ color:var(--red); }} .flat {{ color:var(--muted); }}
  .badge {{ display:inline-block; padding:1px 7px; border-radius:999px; font-size:11px; font-weight:700; margin-left:6px; }}
  .b-open {{ background:rgba(96,165,250,.18); color:var(--blue); }} .b-trail {{ background:rgba(245,158,11,.18); color:var(--amber); }}
  .b-win {{ background:rgba(34,197,94,.18); color:var(--green); }} .b-loss {{ background:rgba(239,68,68,.18); color:var(--red); }} .b-time {{ background:rgba(143,149,191,.18); color:var(--muted); }}
  @keyframes blink {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.35; }} }} .blink {{ animation:blink .9s ease-in-out infinite; }}
  .note {{ color:var(--muted); font-size:12px; margin-top:12px; }} button {{ background:transparent; color:var(--muted); border:1px solid var(--line); border-radius:6px; padding:3px 9px; font-size:12px; cursor:pointer; }}
  @media (max-width:640px) {{ body {{ padding:12px 16px; }} }}
</style>
</head>
<body>
<h1>N6 takip — kesit {cutoff:%d.%m.%Y %H:%M}</h1>
<div class="sub">Kural: ADX 4h ≥ 25, +DI − −DI ≥ 10, 4h MACD histogramı artıyor, hacim ≥ 1,5×, RSI 1h < 72, günlük RSI < 60, 4/4 MA üstü + 4h yüksek dip hariç; 24 sa hacim ≥ 5M TL; piyasa genişliği {res['breadth']:.0%} ({'tam liste' if res['breadth'] >= BREADTH_FULL else 'eşik 54% altı → en iyi ' + str(len(rows))}). Evren {res['universe']} sembol, kurala uyan {res['candidates']}, seçilen {len(rows)}. Giriş: kesitten önceki son 15 dk kapanışı. Çıkış: +%3'ten sonra zirvenin %1,5 altına iz süren stop, −%10 stop, en çok 24 saat (kesit + 24 sa); aynı mumda stop ve iz süren → stop. 10.000 TL/sembol, komisyon %0,1125/bacak. Sayfa açılınca kesitten bu yana 15 dk mumlar borsadan çekilir, sonra canlı fiyatla sürer. Yatırım tavsiyesi değildir.</div>
<div class="bar">
  <span><span id="dot" class="dot"></span><span id="ws">WS bağlanıyor…</span></span>
  <span>Şu an: <b id="now">—</b></span><span>Geçen: <b id="elapsed">—</b></span><span>Süre dolumu: <b id="expiry">—</b></span>
  <span>Mum yolu: <b id="path">—</b></span>
  <button id="theme" type="button">Tema</button>
</div>
<div class="kpi">
  <div><b id="k-total">—</b><span>toplam net K/Z</span></div>
  <div><b id="k-open">—</b><span>açık pozisyon</span></div>
  <div><b id="k-closed">—</b><span>kapanan (iz süren / stop / süre)</span></div>
  <div><b id="k-mfe">—</b><span>ort. MFE</span></div>
  <div><b id="k-win">—</b><span>artıda olan</span></div>
</div>
<div class="wrap"><table id="t"><thead><tr>
  <th>Sembol</th><th>Giriş</th><th>Canlı</th><th>Değişim</th><th>Net K/Z</th><th>MFE</th><th>MFE zamanı</th><th>MAE</th><th>İz süren stop</th><th>Stop</th><th>Durum</th><th>Çıkış</th><th>ADX / DI</th><th>Hacim×</th><th>RSI 1h / gün</th><th>24 sa</th>
</tr></thead><tbody></tbody></table></div>
<p class="note">Durum: <span class="badge b-open">AÇIK</span> kural içinde · <span class="badge b-trail">İZ SÜREN AKTİF</span> +%3 görüldü, stop zirveyi takip ediyor · <span class="badge b-win">KAPANDI +</span> / <span class="badge b-loss">KAPANDI −</span> iz süren veya stop ile · <span class="badge b-time">SÜRE DOLDU</span> 24 saat sonunda kapanıştan. Kapanış fiyatı 15 dk mum içindeyse stop seviyesinden, canlı akışta ise o anki fiyattan alınır.</p>
<script>
(function () {{
  "use strict";
  var DATA = {data};
  var FEE = 0.001125, STAKE = 10000, TRIG = 3, GAP = 1.5, STOP = 10, HOLD_MS = 24 * 3600 * 1000, M15 = 900000;
  var CUT = DATA.cutoff_ms, EXP = CUT + HOLD_MS;
  var WS_BASES = ["wss://stream-cloud.binance.tr", "wss://stream.binance.me", "wss://stream.binance.com:9443"];
  var REST_BASES = ["https://api.binance.me", "https://api.binance.tr"];
  var pos = {{}};   // sym -> state
  DATA.rows.forEach(function (r) {{
    pos[r.sym] = {{ r: r, entry: r.entry, peak: r.entry, trough: r.entry, mfe_at: null, stop: r.entry * (1 - STOP / 100), trail: false, trail_stop: null,
                   live: null, live_at: 0, exit: null, exit_px: null, exit_at: null, path_bars: 0, path_ok: false }};
  }});
  function digits(x) {{ return x >= 1000 ? 1 : x >= 100 ? 2 : x >= 10 ? 3 : x >= 1 ? 4 : x >= 0.1 ? 4 : x >= 0.01 ? 5 : 7; }}
  function fp(x) {{ return x == null || !isFinite(x) ? "—" : x.toLocaleString("tr-TR", {{ minimumFractionDigits: digits(x), maximumFractionDigits: digits(x) }}); }}
  function fpct(x) {{ return x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : "") + x.toLocaleString("tr-TR", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}) + "%"; }}
  function ftl(x) {{ return x == null || !isFinite(x) ? "—" : (x > 0 ? "+" : "") + Math.round(x).toLocaleString("tr-TR") + " TL"; }}
  function cls(x) {{ return x == null ? "flat" : x > 1e-9 ? "pos" : x < -1e-9 ? "neg" : "flat"; }}
  function dur(ms) {{ if (ms < 0) ms = 0; var m = Math.floor(ms / 60000), h = Math.floor(m / 60); return h ? h + " sa " + String(m % 60).padStart(2, "0") + " dk" : m + " dk"; }}
  function tstr(ms) {{ return new Date(ms).toLocaleTimeString("tr-TR", {{ hour: "2-digit", minute: "2-digit" }}); }}
  function net(p, px) {{ return STAKE * (1 - FEE) / p.entry * px * (1 - FEE) - STAKE; }}

  // Bir fiyat adımı uygula (high/low/close + zaman). Sıra kötümser: stop → iz süren → zirve güncelle.
  function step(p, hi, lo, cl, t) {{
    if (p.exit) return;
    if (t >= EXP) {{ p.exit = "time"; p.exit_px = cl; p.exit_at = t; return; }}
    if (lo <= p.stop) {{ p.exit = "stop"; p.exit_px = p.stop; p.exit_at = t; return; }}
    if (p.trail && lo <= p.trail_stop) {{ p.exit = "trail"; p.exit_px = p.trail_stop; p.exit_at = t; return; }}
    if (hi > p.peak) {{ p.peak = hi; p.mfe_at = t; }}
    if (lo < p.trough) p.trough = lo;
    if (p.peak >= p.entry * (1 + TRIG / 100)) {{ p.trail = true; p.trail_stop = Math.max(p.trail_stop || 0, p.peak * (1 - GAP / 100)); }}
  }}
  function replay(p, bars) {{
    // baştan oynat (tazeleme için durumu sıfırla)
    p.peak = p.entry; p.trough = p.entry; p.mfe_at = null; p.stop = p.entry * (1 - STOP / 100); p.trail = false; p.trail_stop = null; p.exit = null; p.exit_px = null; p.exit_at = null;
    bars.forEach(function (b) {{ step(p, b.h, b.l, b.c, b.t + M15); }});
    p.path_bars = bars.length; p.path_ok = true;
  }}
  function fetchPath(sym, idx) {{
    idx = idx || 0; if (idx >= REST_BASES.length) return;
    var url = REST_BASES[idx] + "/api/v3/klines?symbol=" + sym + "&interval=15m&startTime=" + CUT + "&limit=120";
    fetch(url).then(function (r) {{ if (!r.ok) throw new Error(r.status); return r.json(); }}).then(function (rows) {{
      var now = Date.now();
      var bars = (rows || []).filter(function (k) {{ return k[0] + M15 <= now; }}).map(function (k) {{ return {{ t: k[0], o: +k[1], h: +k[2], l: +k[3], c: +k[4] }}; }});
      replay(pos[sym], bars); render();
    }}).catch(function () {{ fetchPath(sym, idx + 1); }});
  }}
  function fetchAllPaths() {{ Object.keys(pos).forEach(function (s) {{ fetchPath(s); }}); }}

  function render() {{
    var now = Date.now(), html = "", total = 0, open = 0, closed = {{ trail: 0, stop: 0, time: 0 }}, mfes = [], winners = 0;
    DATA.rows.forEach(function (r) {{
      var p = pos[r.sym], px = p.exit ? p.exit_px : p.live, ch = px ? (px / p.entry - 1) * 100 : null, n = px ? net(p, px) : null;
      var mfe = (p.peak / p.entry - 1) * 100, mae = (p.trough / p.entry - 1) * 100;
      if (n != null) {{ total += n; if (n > 0) winners++; }}
      mfes.push(mfe);
      var st, badge;
      if (p.exit === "stop") {{ st = '<span class="badge b-loss">KAPANDI −</span>'; closed.stop++; }}
      else if (p.exit === "trail") {{ st = '<span class="badge ' + (n > 0 ? "b-win" : "b-loss") + '">KAPANDI ' + (n > 0 ? "+" : "−") + '</span>'; closed.trail++; }}
      else if (p.exit === "time") {{ st = '<span class="badge b-time">SÜRE DOLDU</span>'; closed.time++; }}
      else {{ st = p.trail ? '<span class="badge b-trail blink">İZ SÜREN AKTİF</span>' : '<span class="badge b-open">AÇIK</span>'; open++; }}
      html += "<tr>" +
        '<td><span class="sym">' + r.sym.replace(/TRY$/, "") + '</span><span class="flat"> / TRY</span></td>' +
        "<td>" + fp(p.entry) + "</td><td>" + (p.live ? fp(p.live) : "…") + '</td><td class="' + cls(ch) + '">' + fpct(ch) + "</td>" +
        '<td class="' + cls(n) + '"><b>' + ftl(n) + "</b></td>" +
        '<td class="' + cls(mfe) + '">' + fpct(mfe) + " <span class='flat'>(" + fp(p.peak) + ")</span></td><td>" + (p.mfe_at ? tstr(p.mfe_at) + " · " + dur(p.mfe_at - CUT) : "—") + "</td>" +
        '<td class="' + cls(mae) + '">' + fpct(mae) + "</td>" +
        "<td>" + (p.trail ? fp(p.trail_stop) + " <span class='flat'>(" + fpct((p.trail_stop / p.entry - 1) * 100) + ")</span>" : "<span class='flat'>+%3'te</span>") + "</td>" +
        "<td>" + fp(p.stop) + "</td><td>" + st + "</td>" +
        "<td>" + (p.exit ? fp(p.exit_px) + " · " + tstr(p.exit_at) : "—") + "</td>" +
        "<td>" + (r.adx != null ? r.adx.toFixed(0) : "—") + " / " + (r.di != null ? r.di.toFixed(0) : "—") + "</td>" +
        "<td>" + (r.vol != null ? r.vol.toFixed(1) + "×" : "—") + "</td>" +
        "<td>" + (r.rsi1 != null ? r.rsi1.toFixed(0) : "—") + " / " + (r.drsi != null ? r.drsi.toFixed(0) : "—") + "</td>" +
        '<td class="' + cls(r.chg24) + '">' + fpct(r.chg24) + "</td></tr>";
    }});
    document.querySelector("#t tbody").innerHTML = html || '<tr><td colspan="16" class="flat">Bu kesitte kurala uyan sembol yok.</td></tr>';
    var el = document.getElementById("k-total"); el.textContent = ftl(total) + " (" + fpct(total / (STAKE * DATA.rows.length) * 100) + ")"; el.className = cls(total);
    document.getElementById("k-open").textContent = open + " / " + DATA.rows.length;
    document.getElementById("k-closed").textContent = closed.trail + " / " + closed.stop + " / " + closed.time;
    document.getElementById("k-mfe").textContent = mfes.length ? fpct(mfes.reduce(function (a, b) {{ return a + b; }}, 0) / mfes.length) : "—";
    document.getElementById("k-win").textContent = winners + " / " + DATA.rows.length;
    document.getElementById("now").textContent = tstr(now);
    document.getElementById("elapsed").textContent = dur(now - CUT);
    document.getElementById("expiry").textContent = new Date(EXP).toLocaleString("tr-TR", {{ day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }}) + (now >= EXP ? " (doldu)" : " (" + dur(EXP - now) + " kaldı)");
    var ok = Object.values(pos).filter(function (p) {{ return p.path_ok; }}).length;
    document.getElementById("path").textContent = ok + "/" + DATA.rows.length + " sembol yüklendi";
  }}

  // ---- WS
  var syms = DATA.rows.map(function (r) {{ return r.sym; }});
  var baseIdx = 0, ws = null, retryMs = 2000, lastMsg = 0;
  function setStatus(on, text) {{ document.getElementById("dot").className = "dot" + (on ? " on" : ""); document.getElementById("ws").textContent = text; }}
  function connect() {{
    if (!syms.length) {{ setStatus(false, "sembol yok"); return; }}
    var base = WS_BASES[baseIdx % WS_BASES.length];
    var url = base + "/stream?streams=" + syms.map(function (s) {{ return s.toLowerCase() + "@miniTicker"; }}).join("/");
    setStatus(false, "Bağlanıyor: " + base.replace("wss://", ""));
    try {{ ws = new WebSocket(url); }} catch (e) {{ baseIdx++; setTimeout(connect, retryMs); return; }}
    ws.onopen = function () {{ retryMs = 2000; setStatus(true, "Canlı: " + base.replace("wss://", "")); }};
    ws.onmessage = function (ev) {{
      var msg; try {{ msg = JSON.parse(ev.data); }} catch (e) {{ return; }}
      var d = msg && msg.data ? msg.data : msg; if (!d || !d.s || d.c == null) return;
      var sym = String(d.s).toUpperCase(), px = parseFloat(d.c); if (!isFinite(px) || !pos[sym]) return;
      var p = pos[sym]; p.live = px; p.live_at = Date.now(); lastMsg = p.live_at;
      if (p.path_ok && !p.exit) step(p, px, px, px, p.live_at);   // canlı: tek fiyat adımı
    }};
    ws.onclose = function () {{ setStatus(false, "Bağlantı koptu, yeniden deneniyor…"); baseIdx++; retryMs = Math.min(30000, retryMs * 1.5); setTimeout(connect, retryMs); }};
    ws.onerror = function () {{ try {{ ws.close(); }} catch (e) {{}} }};
  }}
  connect();
  // REST tohumlama: miniTicker yalnız işlem olunca gelir; açılışta ve 30 sn'de bir tüm fiyat tablosu çekilip süzülür.
  function seed(idx) {{
    idx = idx || 0; if (idx >= REST_BASES.length) return;
    fetch(REST_BASES[idx] + "/api/v3/ticker/price").then(function (r) {{ if (!r.ok) throw new Error(r.status); return r.json(); }}).then(function (rows) {{
      var t = Date.now();
      (rows || []).forEach(function (row) {{
        var sym = String(row.symbol || "").toUpperCase(), px = parseFloat(row.price), p = pos[sym];
        if (!p || !isFinite(px)) return;
        if (!p.live || p.live_at < t - 5000) {{ p.live = px; p.live_at = t; if (p.path_ok && !p.exit) step(p, px, px, px, t); }}
      }});
      render();
    }}).catch(function () {{ seed(idx + 1); }});
  }}
  seed(); setInterval(seed, 30000);
  fetchAllPaths();
  setInterval(fetchAllPaths, 5 * 60 * 1000);     // yol 5 dk'da bir mumlarla tazelenir (canlı adımlar mum yoluyla uyumlanır)
  setInterval(render, 1000);
  render();
  document.getElementById("theme").addEventListener("click", function () {{
    var cur = document.documentElement.getAttribute("data-theme"); var next = cur === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next); try {{ localStorage.setItem("takip:theme", next); }} catch (e) {{}}
  }});
  try {{ var th = localStorage.getItem("takip:theme"); if (th) document.documentElement.setAttribute("data-theme", th); }} catch (e) {{}}
}})();
</script>
</body>
</html>
"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", required=True, help="örn. 2026-10-22T00:00 (Türkiye saati)")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    cutoff = dt.datetime.fromisoformat(args.cutoff).replace(tzinfo=TZ)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    res = await build_list(cutoff_ms, args.top)
    path = args.out or os.path.join(ROOT, f"takip_n6_{cutoff:%Y-%m-%d_%H%M}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html_page(res, cutoff))
    print(f"kesit {cutoff:%d.%m.%Y %H:%M} | evren {res['universe']} | genişlik {res['breadth']:.0%} | kurala uyan {res['candidates']} | seçilen {len(res['picked'])}")
    for r in res["picked"]:
        print(f"  {r['sym']:12} giriş {r['px']:g} | ADX {r['adx4']:.0f} DI {r['di_diff']:.0f} hacim {r['vol_ratio']:.1f}× RSI1h {r['rsi1']:.0f} gRSI {r['d_rsi']:.0f} | 24sa {r['chg24']:+.1f}% | puan {r['score']:+d}")
    print(f"HTML: {path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
