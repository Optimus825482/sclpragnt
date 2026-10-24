"""N6 / N7 kuralı — belirli bir kesitte liste üret ve canlı izleme HTML'i yaz (2026-10-22, kullanıcı isteği).

Kural (docs/SINYAL_YENIDEN_KURMA_90gun_db_2026-10-22_0254.html, N6 + genişlik kapısı):
  kapı: ADX 4h ≥ 25, +DI − −DI ≥ 10, 4h MACD histogramı artıyor · onay: hacim 12 sa / 7 gün ort ≥ 1,5, RSI 1h < 72,
  günlük RSI < 60 · eleme: 4/4 MA üstü + 4h yüksek dip · evren: 24 sa hacim ≥ 5M TL · genişlik < 0,54 ise en iyi 3 (hacim oranı).
Çıkış (sayfa uygular): iz süren +%3'ten sonra zirvenin %1,5 altı, stop −%10, en çok 24 saat; 10.000 TL, komisyon %0,1125/bacak.

Liste yerel arşivden (historical_candles) kesit anına kadar kapanmış mumlarla hesaplanır (ileriye bakma yok).
HTML kök dizine yazılır: takip_n6_<tarih>.html; sayfa açılınca kesitten bu yana 15m mumları Binance TR REST'ten çekip
yolu tamamlar (MFE/MAE/iz süren/stop), sonra miniTicker WS ile canlı sürer.

N7 (varsayılan): N6 + vadeli fonlaması negatif olan sembol elenir (vadelisi olmayan kalır); --rule n6 ile eski kural.
M1H (2026-10-24): 1 saatlik yükseliş potansiyeli taraması (scripts/ta_momentum_scan.py) — momentum + hacim + VWAP + kendi
oynaklık tabanı puanıyla en iyi --top sembol; çıkış varsayılanı kısa: iz süren +%2 sonra zirvenin %1 altı, stop −%4, en çok 4 sa
(RULE_EXIT; --hold-hours/--stop-pct/--trail-trig/--trail-gap ile değişir). Kesit şimdiye 90 dk'dan yakınsa veri canlı REST'ten.
KULLANIM: python backend/scripts/ta_n6_tracker.py --cutoff 2026-10-22T00:00 [--top 3] [--rule n7|n6|m1h]
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
import fetch_futures_data as FD               # noqa: E402  (perp eşlemesi)
import ta_momentum_scan as MS                 # noqa: E402  (M1H kuralı)
import ta_symbol_report as T                  # noqa: E402
from app import momentum_scan as MC           # noqa: E402  (M1H sabitleri sayfaya gömülür; tarayıcı içi tarama)

TZ = dt.timezone(dt.timedelta(hours=3))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MIN_QV = 5e6
BREADTH_FULL = 0.54
# Kurala göre çıkış parametreleri (sayfa uygular): iz süren tetiği/aralığı %, stop %, en çok tutma saati.
RULE_EXIT = {
    "n6": {"trig": 3.0, "gap": 1.5, "stop": 10.0, "hold_h": 24},
    "n7": {"trig": 3.0, "gap": 1.5, "stop": 10.0, "hold_h": 24},
    "m1h": {"trig": 2.0, "gap": 1.0, "stop": 4.0, "hold_h": 4},
}
FAPI_DEPTH = "https://fapi.binance.com/fapi/v1/depth"
LIVE_WINDOW_MS = 90 * 60_000     # kesit şimdiye bu kadar yakınsa derinlik canlı defterden, değilse arşivden
# Tablo başlıkları (2026-10-24): ilk başlık Python'da, "Tara" sonrası kural değişirse JS aynı listelerden yeniden kurar.
TH_BASE = ["Sembol", "Giriş", "Canlı", "Değişim", "Net K/Z", "MFE", "MFE zamanı", "MAE", "İz süren stop", "Stop", "Durum", "Çıkış"]
TH_EXTRA = {
    "m1h": ["1 sa / 4 sa", "Hacim×", "Puan / taban", "24 sa", "Tepeye yol", "VWAP", "ATR 15m", "Derinlik ±1%"],
    "n6": ["ADX / DI", "Hacim×", "RSI 1h / gün", "24 sa", "Fonlama", "OI 24 sa", "Taker", "Derinlik ±1%"],
}

# M1H saf hesaplarının JS kopyası (2026-10-24): app/momentum_scan.py ile aynı matematik; sabitler sayfadaki `M1H` nesnesinden
# okunur (Python json.dumps ile gömer, JS'te sayı yazılmaz). tests/test_ta_n6_tracker_m1h.py node ile Python'a eşitliğini sınar.
M1H_JS = r"""
  // ---- M1H saf hesaplar (app/momentum_scan.py eşleniği; sabitler M1H'den)
  function rowsToBars(raw) {
    var out = [];
    (raw || []).forEach(function (k) {
      var b = { t: +k[0], o: +k[1], h: +k[2], l: +k[3], c: +k[4], q: +k[7] };
      if ([b.t, b.o, b.h, b.l, b.c, b.q].every(isFinite)) out.push(b);
    });
    return out;
  }
  function momentumFeatures(bars, cutoffMs) {
    if (cutoffMs != null) bars = bars.filter(function (b) { return b.t + M1H.M15 <= cutoffMs; });
    var n = bars.length;
    if (n < M1H.MIN_BARS) return null;
    var c = bars.map(function (b) { return b.c; }), h = bars.map(function (b) { return b.h; }), l = bars.map(function (b) { return b.l; }), q = bars.map(function (b) { return b.q; });
    var p = c[n - 1];
    if (p <= 0) return null;
    function sum(a) { return a.reduce(function (s, x) { return s + x; }, 0); }
    function ret(k) { return n > k && c[n - 1 - k] > 0 ? (p / c[n - 1 - k] - 1) * 100 : 0; }
    var vol1 = sum(q.slice(n - 4)), prev = q.slice(Math.max(0, n - 100), n - 4);
    var volavg = prev.length ? sum(prev) / (prev.length / 4) : 0, vr = volavg > 0 ? vol1 / volavg : 0;
    var w = bars.slice(n - 96), qsum = sum(w.map(function (b) { return b.q; }));
    var vwap = qsum > 0 ? sum(w.map(function (b) { return b.c * b.q; })) / qsum : p;
    var hi24 = Math.max.apply(null, w.map(function (b) { return b.h; })), lo24 = Math.min.apply(null, w.map(function (b) { return b.l; }));
    var hits = 0, tot = 0, tgt = 1 + M1H.BASE_TARGET_PCT / 100;
    for (var i = 0; i < n - 5; i++) { tot++; if (Math.max.apply(null, h.slice(i + 1, i + 5)) >= c[i] * tgt) hits++; }
    var base = tot ? hits / tot * 100 : 0, hl = 0;
    for (var j = n - 3; j < n; j++) if (l[j] > l[j - 1]) hl++;
    var atr = 0, cnt = 0;
    for (var k = n - 16; k < n; k++) if (c[k] > 0) { atr += (h[k] - l[k]) / c[k] * 100; cnt++; }
    return { px: p, t: bars[n - 1].t, r1: ret(4), r2: ret(8), r4: ret(16), r24: ret(96), vr: vr, vwap: vwap, vwap_rel: vwap > 0 ? (p / vwap - 1) * 100 : 0,
             hi24: hi24, lo24: lo24, room: (hi24 / p - 1) * 100, base: base, hl: hl, atr15: cnt ? atr / cnt : 0, qv24: sum(q.slice(n - 96)) };
  }
  function momentumScore(f, W) {
    W = W || M1H.WEIGHTS;
    function clamp(x, cap) { return Math.max(Math.min(x, cap), -cap); }
    var sc = clamp(f.r1, W.r1_cap) * W.r1 + clamp(f.r2, W.r2_cap) * W.r2 + clamp(f.r4, W.r4_cap) * W.r4;
    sc += Math.min(f.vr, W.vr_cap) * W.vr;
    sc += f.px > f.vwap ? W.vwap : -W.vwap;
    sc += f.hl * W.hl;
    sc += Math.min(f.base, W.base_cap) * W.base;
    sc += f.room >= 1.5 && f.room <= 8 ? W.room_ok : (f.room > 8 ? W.room_far : W.room_tight);
    if (f.r1 > W.spike_pct) sc -= W.spike_pen;
    return sc;
  }
  function isStable(sym) { var b = /TRY$/.test(sym) ? sym.slice(0, -3) : sym; return M1H.STABLE.indexOf(b) >= 0; }
  function rankRows(feats, top) {   // {sym: özellikler} -> {rows: puana göre ilk `top`, candidates: filtreyi geçen sayı}
    var rows = [];
    Object.keys(feats).forEach(function (sym) {
      var f = feats[sym];
      if (!f || isStable(sym) || f.qv24 < M1H.MIN_QV) return;
      var r = Object.assign({ sym: sym }, f); r.score = momentumScore(f); rows.push(r);
    });
    rows.sort(function (a, b) { return b.score - a.score; });
    return { rows: rows.slice(0, top), candidates: rows.length };
  }
"""


def live_depth(fut: str, band: float = 0.01) -> dict | None:
    """USDT perp defterinden ±band içindeki alış/satış nominalini (USDT) ve dengeyi hesaplar (anahtarsız REST)."""
    import urllib.parse
    import urllib.request
    url = FAPI_DEPTH + "?" + urllib.parse.urlencode({"symbol": fut, "limit": 1000})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "scalper-research/1.0"}), timeout=15) as r:
            d = json.load(r)
    except Exception as exc:  # noqa: BLE001 — sembol yoksa/ağ hatası: derinlik yok
        print(f"  derinlik alınamadı {fut}: {exc}", file=sys.stderr)
        return None
    bids, asks = d.get("bids") or [], d.get("asks") or []
    if not bids or not asks:
        return None
    mid = (float(bids[0][0]) + float(asks[0][0])) / 2
    b = sum(float(px) * float(q) for px, q in bids if float(px) >= mid * (1 - band))
    a = sum(float(px) * float(q) for px, q in asks if float(px) <= mid * (1 + band))
    return {"bid1": b, "ask1": a, "imb1": (b - a) / (b + a) if (b + a) else None, "at_ms": int(d.get("E") or time.time() * 1000)}


def attach_depth(cands: list[dict], cutoff_ms: int) -> str:
    """Adaylara derinlik dengesi ekler: kesit yeni ise canlı defter, değilse arşiv (fut_features f_imb1). Kaynak etiketi döner."""
    pm = FD.perp_map()
    live = (time.time() * 1000 - cutoff_ms) <= LIVE_WINDOW_MS
    for r in cands:
        r["fut"] = pm.get(r["sym"])
        if live and r["fut"]:
            dd = live_depth(r["fut"])
            if dd:
                r["imb1"], r["bid1_usdt"], r["ask1_usdt"], r["depth_at"] = dd["imb1"], dd["bid1"], dd["ask1"], dd["at_ms"]
                continue
        r["imb1"], r["bid1_usdt"], r["depth_at"] = r.get("f_imb1"), r.get("f_bid1_usdt"), None
    return "canlı defter" if live else "arşiv (Data Vision, 15 dk)"


async def build_list(cutoff_ms: int, top: int, rule: str = "n7", force_top: bool = False, manual: list[str] | None = None,
                     depth_filter: bool = False) -> dict:
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
        f.update(FS.fut_features(d.get("_fut"), cutoff_ms))
        feats[sym] = f
        if i % 60 == 0:
            print(f"  {i}/{len(syms)} ({time.time() - t0:.0f} sn)", file=sys.stderr)
    breadth = sum(1 for f in feats.values() if f["score"] >= 1) / len(feats) if feats else 0.0
    n6 = [dict(sym=s, **f) for s, f in feats.items() if FS._m2(f) and FS.g(f, "d_rsi", 100) < 60]
    dropped = [r for r in n6 if rule == "n7" and FS.g(r, "f_funding", 0) < 0]
    for r in dropped:
        r["why"] = "fonlama < 0"
    cands = [r for r in n6 if r not in dropped]
    depth_src = attach_depth(cands, cutoff_ms)
    if depth_filter:
        dd = [r for r in cands if r.get("imb1") is not None and r["imb1"] <= 0]
        for r in dd:
            r["why"] = "derinlik satış ağır"
        dropped += dd
        cands = [r for r in cands if r not in dd]
    cands.sort(key=lambda r: -(r.get("vol_ratio") or 0))
    picked = cands if breadth >= BREADTH_FULL and not force_top else cands[:top]
    if manual:
        picked = [dict(sym=s, **feats[s]) for s in manual if s in feats]
        attach_depth(picked, cutoff_ms)
    return {"cutoff_ms": cutoff_ms, "breadth": breadth, "universe": len(feats), "candidates": len(cands), "picked": picked,
            "rule": rule, "n6_count": len(n6), "dropped": dropped, "force_top": force_top, "top": top, "manual": bool(manual), "depth_src": depth_src, "depth_filter": depth_filter}


def _fmt_pct_tr(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def rule_text(res: dict, rows: list[dict], ex: dict) -> str:
    """Sayfanın üstündeki kural açıklaması (kurala göre)."""
    exit_txt = (f"Giriş: kesitten önceki son 15 dk kapanışı. Çıkış: +%{_fmt_pct_tr(ex['trig'])}'ten sonra zirvenin %{_fmt_pct_tr(ex['gap'])} altına iz süren stop, "
                f"−%{_fmt_pct_tr(ex['stop'])} stop, en çok {ex['hold_h']} saat (kesit + {ex['hold_h']} sa); aynı mumda stop ve iz süren → stop. 10.000 TL/sembol, komisyon %0,1125/bacak. "
                "Sayfa açılınca kesitten bu yana 15 dk mumlar borsadan çekilir, sonra canlı fiyatla sürer. Yatırım tavsiyesi değildir.")
    if res.get("rule") == "m1h":
        return (f"Kural M1H (1 saatlik potansiyel): yalnız kesitten önce kapanmış 15 dk mumlar; puan = son 1/2/4 sa getirisi (tavanlı) + son 1 sa hacmi / 24 sa saatlik ortalaması "
                f"(en çok 4×) + VWAP üstü (+1 / −1) + yükselen dip (son 3 mum) + sembolün kendi 7 günlük \"1 saatte +%2 görme\" oranı / 10 + tepeye mesafe (%1,5–8 arası +1); "
                f"son 1 saatte +%{_fmt_pct_tr(MS.WEIGHTS['spike_pct'])} üstü sıçrayan −{_fmt_pct_tr(MS.WEIGHTS['spike_pen'])} (fitile alım yapmamak için). "
                f"Evren: 24 sa hacim ≥ 5M TL, stabil/altın pariteleri hariç; veri {res.get('source', '')}. Evren {res['universe']} sembol, aday {res['candidates']}, "
                f"puana göre en iyi {len(rows)}. Derinlik ±1% USDT perp defterinden ({res.get('depth_src', '')}; bilgi amaçlı). {exit_txt}")
    dropped_txt = ", ".join(f"{r['sym'].replace('TRY', '')} ({r.get('why', '')}: {('%+.3f%%' % r['f_funding']) if r.get('why') == 'fonlama < 0' else ('%+.2f' % r['imb1'])})" for r in res.get("dropped", [])) or "yok"
    pick_txt = ('manuel seçim: kurala tam uymayan en yakın ' + str(len(rows)) + ' sembol' if res.get('manual') else 'hacim oranına göre en iyi ' + str(res['top']) + ' (istek)' if res.get('force_top')
                else 'tam liste' if res['breadth'] >= BREADTH_FULL else 'eşik 54% altı → en iyi ' + str(len(rows)))
    n7_txt = ("vadeli fonlaması negatif olan elenir (N6 uyan " + str(res.get("n6_count", 0)) + ", elenen: " + dropped_txt + "); ") if res.get("rule") == "n7" else ""
    return (f"Kural: ADX 4h ≥ 25, +DI − −DI ≥ 10, 4h MACD histogramı artıyor, hacim ≥ 1,5×, RSI 1h < 72, günlük RSI < 60, 4/4 MA üstü + 4h yüksek dip hariç; {n7_txt}"
            f"24 sa hacim ≥ 5M TL; derinlik dengesi ±1% = (alış − satış) / (alış + satış) nominal, USDT perp defterinden ({res.get('depth_src', '')}; "
            f"{'satış ağır olanlar elendi' if res.get('depth_filter') else 'bilgi amaçlı, elemiyor'}; 90 günlük çalışmada yalnız 30 gün veri: alış ağır +88, satış ağır −20 TL/sinyal, kanıtlanmamış); "
            f"piyasa genişliği {res['breadth']:.0%} ({pick_txt}). Evren {res['universe']} sembol, kurala uyan {res['candidates']}, seçilen {len(rows)}. {exit_txt}")


def html_page(res: dict, cutoff: dt.datetime, exit_params: dict | None = None) -> str:
    rows = [{"sym": r["sym"], "entry": r["px"], "adx": r.get("adx4"), "di": r.get("di_diff"), "vol": r.get("vol_ratio"), "rsi1": r.get("rsi1"),
             "drsi": r.get("d_rsi"), "above4": r.get("above4"), "chg24": r.get("chg24"), "qv": r.get("qv24"), "score": r.get("score"),
             "funding": r.get("f_funding"), "oi24": r.get("f_oi_chg24"), "taker": r.get("f_taker"),
             "r1": r.get("r1"), "r4": r.get("r4"), "base": r.get("base"), "room": r.get("room"), "vwap_rel": r.get("vwap_rel"), "atr15": r.get("atr15"),
             "fut": r.get("fut"), "imb1": r.get("imb1"), "bid1": r.get("bid1_usdt"), "ask1": r.get("ask1_usdt"), "depth_at": r.get("depth_at")} for r in res["picked"]]
    rule = res.get("rule", "n6")
    rule_name = rule.upper()
    ex = dict(RULE_EXIT.get(rule, RULE_EXIT["n6"]), **(exit_params or {}))
    sub_txt = rule_text(res, rows, ex)
    data = json.dumps({"cutoff_ms": res["cutoff_ms"], "breadth": res["breadth"], "universe": res["universe"], "candidates": res["candidates"], "rows": rows,
                       "depth_src": res.get("depth_src", ""), "rule": rule, "exit": ex, "top": res.get("top", 3)}, ensure_ascii=False)
    th_html = "".join(f"<th>{x}</th>" for x in TH_BASE + TH_EXTRA["m1h" if rule == "m1h" else "n6"])
    th_js = json.dumps({"base": TH_BASE, "extra": TH_EXTRA}, ensure_ascii=False)
    # Tarayıcı içi "Tara" için M1H sabitleri (2026-10-24): Python ile aynı sayılar, JS'te elle yazılmaz.
    m1h_js = json.dumps({"M15": MC.M15, "MIN_QV": MC.MIN_QV, "MIN_BARS": MC.MIN_BARS, "KLINES_LIMIT": MC.KLINES_LIMIT, "BASE_TARGET_PCT": MC.BASE_TARGET_PCT,
                         "STABLE": sorted(MC.STABLE), "WEIGHTS": MC.WEIGHTS, "EXIT": RULE_EXIT["m1h"]}, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{rule_name} Takip {cutoff:%d.%m %H:%M}</title>
<meta name="description" content="{rule_name} kuralı ile {cutoff:%d.%m.%Y %H:%M} kesitinde seçilen semboller; iz süren {_fmt_pct_tr(ex['trig'])}/{_fmt_pct_tr(ex['gap'])} + %{_fmt_pct_tr(ex['stop'])} stop + {ex['hold_h']} saat kuralının canlı izlemesi.">
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
<h1 id="h1">{rule_name} takip — kesit {cutoff:%d.%m.%Y %H:%M}</h1>
<div class="sub" id="sub">{sub_txt}</div>
<div class="bar">
  <span><span id="dot" class="dot"></span><span id="ws">WS bağlanıyor…</span></span>
  <span>Şu an: <b id="now">—</b></span><span>Geçen: <b id="elapsed">—</b></span><span>Süre dolumu: <b id="expiry">—</b></span>
  <span>Mum yolu: <b id="path">—</b></span>
  <button id="theme" type="button">Tema</button>
  <button id="scan" type="button" title="M1H taramasını şimdi tarayıcıda yeniden çalıştırır (Python gerekmez); liste yenilenir">Tara</button>
</div>
<div class="sub" id="scan-note" hidden></div>
<div class="kpi">
  <div><b id="k-total">—</b><span>toplam net K/Z</span></div>
  <div><b id="k-open">—</b><span>açık pozisyon</span></div>
  <div><b id="k-closed">—</b><span>kapanan (iz süren / stop / süre)</span></div>
  <div><b id="k-mfe">—</b><span>ort. MFE</span></div>
  <div><b id="k-win">—</b><span>artıda olan</span></div>
</div>
<div class="wrap"><table id="t"><thead><tr>
  {th_html}
</tr></thead><tbody></tbody></table></div>
<p class="note">Durum: <span class="badge b-open">AÇIK</span> kural içinde · <span class="badge b-trail">İZ SÜREN AKTİF</span> +%<span id="ex-trig">{_fmt_pct_tr(ex['trig'])}</span> görüldü, stop zirveyi takip ediyor · <span class="badge b-win">KAPANDI +</span> / <span class="badge b-loss">KAPANDI −</span> iz süren veya stop ile · <span class="badge b-time">SÜRE DOLDU</span> <span id="ex-hold">{ex['hold_h']}</span> saat sonunda kapanıştan. Kapanış fiyatı 15 dk mum içindeyse stop seviyesinden, canlı akışta ise o anki fiyattan alınır.</p>
<script>
(function () {{
  "use strict";
  var DATA = {data};
  var M1H = {m1h_js};   // M1H sabitleri (Python'dan; tarayıcı içi tarama aynı sayılarla)
  var TH = {th_js};     // tablo başlıkları (kurala göre ek sütunlar)
  var EX = DATA.exit || {{ trig: 3, gap: 1.5, stop: 10, hold_h: 24 }};
  var FEE = 0.001125, STAKE = 10000, TRIG = EX.trig, GAP = EX.gap, STOP = EX.stop, HOLD_MS = EX.hold_h * 3600 * 1000, M15 = 900000;
  var CUT = DATA.cutoff_ms, EXP = CUT + HOLD_MS;
  var WS_BASES = ["wss://stream-cloud.binance.tr", "wss://stream.binance.me", "wss://stream.binance.com:9443"];
  var REST_BASES = ["https://api.binance.me", "https://api.binance.tr"];
  var pos = {{}};   // sym -> state
  function buildPos() {{   // DATA.rows'tan durumları (yeniden) kur; Tara sonrası liste değişir
    pos = {{}};
    DATA.rows.forEach(function (r) {{
      pos[r.sym] = {{ r: r, entry: r.entry, peak: r.entry, trough: r.entry, mfe_at: null, stop: r.entry * (1 - STOP / 100), trail: false, trail_stop: null,
                     live: null, live_at: 0, exit: null, exit_px: null, exit_at: null, path_bars: 0, path_ok: false }};
    }});
  }}
  buildPos();
  function applyExit() {{   // DATA.exit -> çıkış sabitleri (kural değişince)
    EX = DATA.exit; TRIG = EX.trig; GAP = EX.gap; STOP = EX.stop; HOLD_MS = EX.hold_h * 3600 * 1000; EXP = CUT + HOLD_MS;
    var a = document.getElementById("ex-trig"), b = document.getElementById("ex-hold");
    if (a) a.textContent = String(TRIG).replace(".", ","); if (b) b.textContent = EX.hold_h;
  }}
{M1H_JS}
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
  var depthLive = {{}};   // sym -> {{imb, bid, ask, at}}
  function imbTxt(v) {{ return v == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(2); }}
  function imbCls(v) {{ return v == null ? "" : v > 0.13 ? "up" : v > 0 ? "" : "dn"; }}
  function depthCell(r) {{
    var base = r.imb1 == null ? "<span class='flat'>" + (r.fut || DATA.browser_scan ? "kesitte yok" : "vadeli yok") + "</span>" :
      "<span class='" + imbCls(r.imb1) + "'>" + imbTxt(r.imb1) + "</span><span class='flat'> kesit</span>";
    var l = depthLive[r.sym];
    if (l) base += "<br><span class='" + imbCls(l.imb) + "'><b>" + imbTxt(l.imb) + "</b></span><span class='flat'> canlı " + tstr(l.at) + " · alış " + Math.round(l.bid / 1000) + "k / satış " + Math.round(l.ask / 1000) + "k</span>" +
      (l.imb <= 0 ? ' <span class="badge b-loss">SATIŞ AĞIR</span>' : l.imb > 0.13 ? ' <span class="badge b-win">ALIŞ AĞIR</span>' : "");
    return base;
  }}
  function fetchDepth(r) {{
    if (!r.fut) return;
    fetch("https://fapi.binance.com/fapi/v1/depth?symbol=" + r.fut + "&limit=1000").then(function (x) {{ if (!x.ok) throw new Error(x.status); return x.json(); }}).then(function (d) {{
      if (!d.bids || !d.asks || !d.bids.length || !d.asks.length) return;
      var mid = (parseFloat(d.bids[0][0]) + parseFloat(d.asks[0][0])) / 2, b = 0, a = 0;
      d.bids.forEach(function (x) {{ var p = parseFloat(x[0]); if (p >= mid * 0.99) b += p * parseFloat(x[1]); }});
      d.asks.forEach(function (x) {{ var p = parseFloat(x[0]); if (p <= mid * 1.01) a += p * parseFloat(x[1]); }});
      depthLive[r.sym] = {{ imb: (b + a) ? (b - a) / (b + a) : null, bid: b, ask: a, at: d.E || Date.now() }};
    }}).catch(function () {{}});
  }}
  function fetchAllDepth() {{ DATA.rows.forEach(fetchDepth); }}
  // Kurala özgü sütunlar (başlıklar TH.extra ile aynı sırada; ilk başlık Python'da, kural değişirse setHeader yeniden kurar).
  function setHeader() {{
    document.querySelector("#t thead tr").innerHTML = TH.base.concat(TH.extra[DATA.rule === "m1h" ? "m1h" : "n6"]).map(function (x) {{ return "<th>" + x + "</th>"; }}).join("");
  }}
  function extraCells(r) {{
    if (DATA.rule === "m1h") {{
      return '<td class="' + cls(r.r1) + '">' + fpct(r.r1) + " / " + fpct(r.r4) + "</td>" +
        "<td>" + (r.vol != null ? r.vol.toFixed(1) + "×" : "—") + "</td>" +
        "<td><b>" + (r.score != null ? r.score.toFixed(1) : "—") + "</b> / " + (r.base != null ? r.base.toFixed(0) + "%" : "—") + "</td>" +
        '<td class="' + cls(r.chg24) + '">' + fpct(r.chg24) + "</td>" +
        "<td>" + (r.room != null ? fpct(r.room) : "—") + "</td>" +
        '<td class="' + cls(r.vwap_rel) + '">' + fpct(r.vwap_rel) + "</td>" +
        "<td>" + (r.atr15 != null ? r.atr15.toFixed(2) + "%" : "—") + "</td>";
    }}
    return "<td>" + (r.adx != null ? r.adx.toFixed(0) : "—") + " / " + (r.di != null ? r.di.toFixed(0) : "—") + "</td>" +
      "<td>" + (r.vol != null ? r.vol.toFixed(1) + "×" : "—") + "</td>" +
      "<td>" + (r.rsi1 != null ? r.rsi1.toFixed(0) : "—") + " / " + (r.drsi != null ? r.drsi.toFixed(0) : "—") + "</td>" +
      '<td class="' + cls(r.chg24) + '">' + fpct(r.chg24) + "</td>" +
      "<td>" + (r.funding != null ? r.funding.toFixed(3) + "%" : "<span class='flat'>vadeli yok</span>") + "</td>" +
      '<td class="' + (r.oi24 != null ? cls(r.oi24) : "") + '">' + (r.oi24 != null ? fpct(r.oi24) : "—") + "</td>" +
      "<td>" + (r.taker != null ? r.taker.toFixed(2) : "—") + "</td>";
  }}

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
        "<td>" + (p.trail ? fp(p.trail_stop) + " <span class='flat'>(" + fpct((p.trail_stop / p.entry - 1) * 100) + ")</span>" : "<span class='flat'>+%" + TRIG + "'te</span>") + "</td>" +
        "<td>" + fp(p.stop) + "</td><td>" + st + "</td>" +
        "<td>" + (p.exit ? fp(p.exit_px) + " · " + tstr(p.exit_at) : "—") + "</td>" +
        extraCells(r) +
        "<td>" + depthCell(r) + "</td></tr>";
    }});
    document.querySelector("#t tbody").innerHTML = html || '<tr><td colspan="20" class="flat">Bu kesitte kurala uyan sembol yok.</td></tr>';
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
  var baseIdx = 0, ws = null, retryMs = 2000, lastMsg = 0;
  function setStatus(on, text) {{ document.getElementById("dot").className = "dot" + (on ? " on" : ""); document.getElementById("ws").textContent = text; }}
  function connect() {{
    var syms = DATA.rows.map(function (r) {{ return r.sym; }});   // Tara sonrası liste değişir; her bağlantıda yeniden okunur
    if (!syms.length) {{ setStatus(false, "sembol yok"); return; }}
    if (ws && ws.readyState <= 1) return;   // zaten bağlı/bağlanıyor (bekleyen yeniden deneme zamanlayıcısı)
    var base = WS_BASES[baseIdx % WS_BASES.length];
    var url = base + "/stream?streams=" + syms.map(function (s) {{ return s.toLowerCase() + "@miniTicker"; }}).join("/");
    setStatus(false, "Bağlanıyor: " + base.replace("wss://", ""));
    var sock;
    try {{ sock = new WebSocket(url); }} catch (e) {{ baseIdx++; setTimeout(connect, retryMs); return; }}
    ws = sock;
    sock.onopen = function () {{ if (sock !== ws) return; retryMs = 2000; setStatus(true, "Canlı: " + base.replace("wss://", "")); }};
    sock.onmessage = function (ev) {{
      if (sock !== ws) return;
      var msg; try {{ msg = JSON.parse(ev.data); }} catch (e) {{ return; }}
      var d = msg && msg.data ? msg.data : msg; if (!d || !d.s || d.c == null) return;
      var sym = String(d.s).toUpperCase(), px = parseFloat(d.c); if (!isFinite(px) || !pos[sym]) return;
      var p = pos[sym]; p.live = px; p.live_at = Date.now(); lastMsg = p.live_at;
      if (p.path_ok && !p.exit) step(p, px, px, px, p.live_at);   // canlı: tek fiyat adımı
    }};
    sock.onclose = function () {{ if (sock !== ws) return; setStatus(false, "Bağlantı koptu, yeniden deneniyor…"); baseIdx++; retryMs = Math.min(30000, retryMs * 1.5); setTimeout(connect, retryMs); }};
    sock.onerror = function () {{ try {{ sock.close(); }} catch (e) {{}} }};
  }}
  function reconnect() {{   // eski soketi sessizce kapat (onclose yeniden deneme kurmasın), yeni sembol listesiyle bağlan
    if (ws) {{ var old = ws; ws = null; old.onopen = old.onmessage = old.onclose = old.onerror = null; try {{ old.close(); }} catch (e) {{}} }}
    connect();
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
  fetchAllDepth(); setInterval(fetchAllDepth, 60 * 1000);   // derinlik dengesi dakikada bir USDT perp defterinden
  setInterval(render, 1000);
  render();

  // ---- Tara (2026-10-24): M1H taramasını tarayıcıda "şimdi" için yeniden çalıştır; Python gerekmez, aynı sabitler (M1H).
  function fetchJson(path, idx) {{   // REST_BASES sırayla denenir (fetchPath gibi), Promise döner
    idx = idx || 0;
    return fetch(REST_BASES[idx] + path).then(function (r) {{ if (!r.ok) throw new Error(r.status); return r.json(); }})
      .catch(function (e) {{ return idx + 1 < REST_BASES.length ? fetchJson(path, idx + 1) : Promise.reject(e); }});
  }}
  function pool(items, n, fn) {{   // en çok n eşzamanlı iş
    var i = 0;
    function next() {{ if (i >= items.length) return Promise.resolve(); var k = i++; return fn(items[k], k).then(next); }}
    var runners = []; for (var j = 0; j < n; j++) runners.push(next());
    return Promise.all(runners);
  }}
  function m1hSubText() {{   // n6/n7 sayfası M1H listesine geçince kural açıklaması
    var ex = DATA.exit, W = M1H.WEIGHTS, tr = function (x) {{ return String(x).replace(".", ","); }};
    return "Kural M1H (1 saatlik potansiyel), tarayıcıda yeniden tarandı: yalnız kesitten önce kapanmış 15 dk mumlar; puan = son 1/2/4 sa getirisi (tavanlı) + son 1 sa hacmi / 24 sa saatlik ortalaması (en çok " + tr(W.vr_cap) + "×) + VWAP üstü (+1 / −1) + yükselen dip (son 3 mum) + sembolün kendi 7 günlük \\"1 saatte +%" + tr(M1H.BASE_TARGET_PCT) + " görme\\" oranı / 10 + tepeye mesafe (%1,5–8 arası +1); son 1 saatte +%" + tr(W.spike_pct) + " üstü sıçrayan −" + tr(W.spike_pen) + ". " +
      "Evren: 24 sa hacim ≥ " + tr(M1H.MIN_QV / 1e6) + "M TL, stabil/altın pariteleri hariç; veri tarayıcı REST. Evren " + DATA.universe + " sembol, aday " + DATA.candidates + ", puana göre en iyi " + DATA.rows.length + ". Derinlik kesitte yok (tarayıcı taraması). " +
      "Giriş: kesitten önceki son 15 dk kapanışı. Çıkış: +%" + tr(ex.trig) + "'ten sonra zirvenin %" + tr(ex.gap) + " altına iz süren stop, −%" + tr(ex.stop) + " stop, en çok " + ex.hold_h + " saat. 10.000 TL/sembol, komisyon %0,1125/bacak. Yatırım tavsiyesi değildir.";
  }}
  function applyScan(picked, universe, candidates, cutoff) {{   // yeni liste: satırlar, durumlar, başlıklar, metinler, yol/tohum/derinlik/WS
    var old = {{}}; DATA.rows.forEach(function (r) {{ old[r.sym] = r; }});
    var switched = DATA.rule !== "m1h";
    DATA.rows = picked.map(function (f) {{
      var o = old[f.sym];
      return {{ sym: f.sym, entry: f.px, r1: f.r1, r4: f.r4, vol: f.vr, score: f.score, base: f.base, chg24: f.r24, room: f.room, vwap_rel: f.vwap_rel, atr15: f.atr15, qv: f.qv24,
               fut: o ? o.fut : null, imb1: null, bid1: null, ask1: null, depth_at: null, adx: null, di: null, rsi1: null, drsi: null, funding: null, oi24: null, taker: null }};
    }});
    DATA.universe = universe; DATA.candidates = candidates; DATA.browser_scan = true;
    if (switched) {{ DATA.rule = "m1h"; DATA.exit = M1H.EXIT; setHeader(); }}
    CUT = cutoff; applyExit(); buildPos(); depthLive = {{}};
    var d = new Date(CUT), pad = function (x) {{ return String(x).padStart(2, "0"); }};
    var dm = pad(d.getDate()) + "." + pad(d.getMonth() + 1), hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
    document.getElementById("h1").textContent = "M1H takip — kesit " + dm + "." + d.getFullYear() + " " + hm;
    document.title = "M1H Takip " + dm + " " + hm;
    var sub = document.getElementById("sub");
    sub.textContent = switched ? m1hSubText() : sub.textContent.replace(/Evren \\d+ sembol, aday \\d+, puana göre en iyi \\d+/, "Evren " + universe + " sembol, aday " + candidates + ", puana göre en iyi " + DATA.rows.length);
    render(); fetchAllPaths(); seed(); fetchAllDepth(); reconnect();
  }}
  var scanning = false;
  function runScan() {{
    if (scanning) return;
    var btn = document.getElementById("scan"), note = document.getElementById("scan-note"), t0 = Date.now(), skipped = 0;
    scanning = true; btn.disabled = true; btn.textContent = "Tarama…";
    fetchJson("/api/v3/exchangeInfo").then(function (info) {{
      var syms = (info.symbols || []).map(function (s) {{ return s.status === "TRADING" && s.quoteAsset === "TRY" ? String(s.symbol).toUpperCase() : null; }})
        .filter(function (s) {{ return s && !isStable(s); }}).sort();
      if (!syms.length) throw new Error("TRY sembolü bulunamadı");
      var cutoff = Date.now(), done = 0, feats = {{}};
      return pool(syms, 6, function (sym) {{
        return fetchJson("/api/v3/klines?symbol=" + sym + "&interval=15m&limit=" + M1H.KLINES_LIMIT)
          .then(function (raw) {{ feats[sym] = momentumFeatures(rowsToBars(raw), cutoff); }})
          .catch(function () {{ skipped++; feats[sym] = null; }})
          .then(function () {{ done++; btn.textContent = "Tarama " + done + "/" + syms.length + "…"; }});
      }}).then(function () {{
        if (skipped >= syms.length) throw new Error("hiç sembol çekilemedi");
        var universe = 0; Object.keys(feats).forEach(function (s) {{ if (feats[s] && feats[s].qv24 >= M1H.MIN_QV) universe++; }});
        var rk = rankRows(feats, DATA.top || 3);
        if (!rk.rows.length) throw new Error("aday yok (liste korundu)");
        applyScan(rk.rows, universe, rk.candidates, cutoff);
        note.hidden = false;
        note.textContent = "Son tarama " + tstr(cutoff) + " · " + syms.length + " sembol · " + ((Date.now() - t0) / 1000).toFixed(1) + " sn" + (skipped ? " · " + skipped + " sembol atlandı" : "");
      }});
    }}).catch(function (e) {{
      var msg = "Tarama başarısız: " + (e && e.message ? e.message : e);
      setStatus(false, msg); note.hidden = false; note.textContent = msg;
    }}).then(function () {{ scanning = false; btn.disabled = false; btn.textContent = "Tara"; }});
  }}
  document.getElementById("scan").addEventListener("click", runScan);
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
    ap.add_argument("--rule", choices=("n6", "n7", "m1h"), default="n7")
    ap.add_argument("--force-top", action="store_true", help="genişlik yüksek olsa da yalnız en iyi --top sembol")
    ap.add_argument("--symbols", default="", help="virgüllü manuel liste (kural yerine); giriş = kesit öncesi son 15 dk kapanışı")
    ap.add_argument("--depth-filter", action="store_true", help="derinlik dengesi ±1% ≤ 0 (satış ağır) olan adayları ele (varsayılan: yalnız göster)")
    ap.add_argument("--hold-hours", type=float, default=None, help="en çok tutma süresi (sa); varsayılan kurala göre (RULE_EXIT)")
    ap.add_argument("--stop-pct", type=float, default=None, help="stop %% (varsayılan kurala göre)")
    ap.add_argument("--trail-trig", type=float, default=None, help="iz süren tetiği %% (varsayılan kurala göre)")
    ap.add_argument("--trail-gap", type=float, default=None, help="iz süren zirve altı aralığı %% (varsayılan kurala göre)")
    args = ap.parse_args()
    cutoff = dt.datetime.fromisoformat(args.cutoff).replace(tzinfo=TZ)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    exit_params = {k: v for k, v in (("hold_h", args.hold_hours), ("stop", args.stop_pct), ("trig", args.trail_trig), ("gap", args.trail_gap)) if v is not None}
    if args.rule == "m1h":
        res = await MS.scan(cutoff_ms, args.top)
        res["depth_src"] = attach_depth(res["picked"], cutoff_ms)
    else:
        res = await build_list(cutoff_ms, args.top, args.rule, args.force_top, [x.strip().upper() for x in args.symbols.split(",") if x.strip()] or None, args.depth_filter)
    path = args.out or os.path.join(ROOT, f"takip_{args.rule}_{cutoff:%Y-%m-%d_%H%M}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html_page(res, cutoff, exit_params))
    ex = dict(RULE_EXIT[args.rule], **exit_params)
    if args.rule == "m1h":
        print(f"kesit {cutoff:%d.%m.%Y %H:%M} | kural M1H | veri {res.get('source', '')} | evren {res['universe']} | aday {res['candidates']} | seçilen {len(res['picked'])} | çıkış iz süren {ex['trig']:g}/{ex['gap']:g}, stop −{ex['stop']:g}%, en çok {ex['hold_h']:g} sa")
        print(f"derinlik kaynağı: {res.get('depth_src', '—')}")
        for r in res["picked"]:
            print(f"  {r['sym']:12} giriş {r['px']:g} | puan {r['score']:5.2f} | 1sa {r['r1']:+.2f}% 2sa {r['r2']:+.2f}% 4sa {r['r4']:+.2f}% 24sa {r['r24']:+.1f}% | hacim {r['vr']:.1f}× | VWAP {r['vwap_rel']:+.2f}% | tepeye {r['room']:.1f}% | taban +2%/1sa {r['base']:.0f}% | dip+ {r['hl']} | ATR15 {r['atr15']:.2f}% | 24sa hacim {r['qv24'] / 1e6:.0f}M | derinlik±1% {('%+.2f' % r['imb1']) if r.get('imb1') is not None else '—'}")
        print(f"HTML: {path}")
        return 0
    print(f"kesit {cutoff:%d.%m.%Y %H:%M} | kural {args.rule.upper()} | evren {res['universe']} | genişlik {res['breadth']:.0%} | N6 uyan {res['n6_count']} | elenen (fonlama<0) {len(res['dropped'])} | seçilen {len(res['picked'])}")
    print(f"derinlik kaynağı: {res.get('depth_src', '—')}")
    for r in res["dropped"]:
        print(f"  ELENDİ {r['sym']:12} {r.get('why', '')}: fonlama {('%+.3f%%' % r['f_funding']) if r.get('f_funding') is not None else 'yok'} | derinlik {('%+.2f' % r['imb1']) if r.get('imb1') is not None else '—'} | hacim {r['vol_ratio']:.1f}× | 24sa {r['chg24']:+.1f}%")
    for r in res["picked"]:
        print(f"  {r['sym']:12} giriş {r['px']:g} | ADX {r['adx4']:.0f} DI {r['di_diff']:.0f} hacim {r['vol_ratio']:.1f}× RSI1h {r['rsi1']:.0f} gRSI {r['d_rsi']:.0f} | 24sa {r['chg24']:+.1f}% | puan {r['score']:+d} | fonlama {('%+.3f%%' % r['f_funding']) if r.get('f_funding') is not None else 'vadeli yok'} | OI24 {('%+.1f%%' % r['f_oi_chg24']) if r.get('f_oi_chg24') is not None else '—'} | taker {('%.2f' % r['f_taker']) if r.get('f_taker') is not None else '—'} | derinlik±1% {('%+.2f (alış %.0fk / satış %.0fk)' % (r['imb1'], (r.get('bid1_usdt') or 0) / 1000, (r.get('ask1_usdt') or 0) / 1000)) if r.get('imb1') is not None else '—'}")
    print(f"HTML: {path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
