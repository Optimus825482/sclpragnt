"""YENİ VERİ KANALI ARAŞTIRMASI (2026-10-12).

BAĞLAM: Üç tur (çıkış / giriş seçici / fiyat-mum feature'ları) mevcut veriyle
genellenebilir edge bulamadı → `NO_FEATURE_EDGE`. Sonuç: YENİ VERİ KANALI gerekir.
Bu script iki aday kanalı GERÇEK aday geçmişi + GERÇEK mum verisiyle ölçer.

KANAL 1 — ORDER-FLOW / CVD PROXY (TRY native, ek API/anahtar yok):
    Binance klines 12 alan döner; 9. alan `taker_buy_base` = agresif ALICI hacmi.
    tbr = taker_buy / total_volume (0-1). CVD ≈ kümülatif (taker_buy - taker_sell).
    Neden umut verici: yükselişin ÖNCÜSÜ agresif alım olabilir (klasik order-flow
    hipotezi); klines grade'i anında bilinebilir, look-ahead yok.

KANAL 2 — GLOBAL→TR LEAD-LAG (309 ortak sembol):
    Aynı coin'in Binance Global USDT paritesi, TRY paritesinden ÖNCE mi hareket
    ediyor? TR piyasası daha az likit → Global'de başlayan hareket TR'ye gecikmeli
    yansıyabilir. Global 5m getirisi (sinyal anında) TR'nin geleceğini öngörür mü?

LOOK-AHEAD KORUMASI: tüm feature'lar `ts` anında KAPANMIŞ barlardan hesaplanır
(bar open_time+300 <= ts). Kanal 2'de Global bar HİZALAMASI zaman damgasıyla
yapılır; Global barı da ts'te kapanmış olmalı.

KULLANIM:
    python backend/scripts/research_data_channels.py --hours 400
    python backend/scripts/research_data_channels.py --hours 400 --fetch
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

from app.paper_sim import simulate_exit, tp_pct_for  # noqa: E402

_DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:518518Erkan@localhost:5432/scalper")
_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "..", "work", "channel_cache.json")
_BAR_MS = 300_000


# ---------------------------------------------------------------------------
# Veri çekimi (TR taker-buy + Global USDT) — önbellekli
# ---------------------------------------------------------------------------
async def _fetch_klines(base_url: str, symbol: str, start_ms: int, end_ms: int) -> list:
    """Sayfalanmış 5m klines (12 alan) çek."""
    import urllib.request
    import ssl
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    out = []
    cursor = start_ms
    while cursor < end_ms:
        url = (f"{base_url}/api/v3/klines?symbol={symbol}&interval=5m"
               f"&startTime={cursor}&endTime={end_ms}&limit=1000")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                batch = json.loads(r.read().decode())
        except Exception:
            break
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1][0]) + 1
        await asyncio.sleep(0.06)
    return out


def _to_bars(rows: list) -> dict:
    """12-alan klines → {"t","o","h","l","c","v","tb"} (tb = taker_buy_base)."""
    b = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [], "tb": []}
    for r in rows:
        try:
            b["t"].append(float(r[0]) / 1000.0)
            b["o"].append(float(r[1])); b["h"].append(float(r[2]))
            b["l"].append(float(r[3])); b["c"].append(float(r[4]))
            b["v"].append(float(r[5])); b["tb"].append(float(r[9]))
        except (IndexError, TypeError, ValueError):
            continue
    return b


async def _build_cache(cands: list[dict], fetch: bool) -> dict:
    if os.path.exists(_CACHE) and not fetch:
        with open(_CACHE, encoding="utf-8") as f:
            return json.load(f)
    import psycopg
    # Sembol evrenini adaylardan türet
    syms = sorted({c["symbol"] for c in cands})
    t0 = int(min(c["ts"] for c in cands) * 1000) - 2 * 86400_000     # 2g ısınma
    t1 = int(max(c["ts"] for c in cands) * 1000) + 3600_000
    print(f"  önbellek kurulacak: {len(syms)} sembol, {int((t1-t0)/86400000)} gün")

    # Global USDT karşılıkları
    global_map = await _global_symbol_map()
    cache = {"tr": {}, "gl": {}, "global_map": global_map, "built_at": time.time()}
    for i, sym in enumerate(syms):
        try:
            tr = await _fetch_klines("https://api.binance.me", sym, t0, t1)
            cache["tr"][sym] = _to_bars(tr)
            base = sym[:-3] if sym.endswith("TRY") else sym
            gsym = global_map.get(base)
            if gsym:
                gl = await _fetch_klines("https://api.binance.com", gsym, t0, t1)
                cache["gl"][sym] = _to_bars(gl)
        except Exception as exc:
            print(f"    {sym}: {type(exc).__name__}")
        if (i + 1) % 15 == 0:
            print(f"    ... {i+1}/{len(syms)}")
    with open(_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    print(f"  önbellek yazıldı: {_CACHE}")
    return cache


async def _global_symbol_map() -> dict:
    """TR base → Global USDT sembol ('WLD' → 'WLDUSDT'), TRADING olanlar."""
    import urllib.request
    import ssl
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request("https://api.binance.com/api/v3/exchangeInfo",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            data = json.loads(r.read().decode())
        m = {}
        for s in data.get("symbols", []):
            sym = s.get("symbol", "")
            if sym.endswith("USDT") and s.get("status") == "TRADING":
                m[sym[:-4]] = sym
        return m
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Feature'lar (yalnız kapanmış barlar)
# ---------------------------------------------------------------------------
import bisect  # noqa: E402


def _idx_closed(bars: dict, ts: float) -> int:
    """ts anında kapanmış son bar indeksi (bar kapanışı = open+300)."""
    return bisect.bisect_right(bars["t"], ts - 300.0) - 1


def _tr_features(bars: dict, ts: float) -> dict | None:
    """KANAL 1: order-flow (taker-buy) feature'ları."""
    i = _idx_closed(bars, ts)
    if i < 24:
        return None
    v = bars["v"]; tb = bars["tb"]; c = bars["c"]

    def tbr(k):
        if v[k] <= 0:
            return 0.5
        return tb[k] / v[k]
    ratio = tbr(i)
    # CVD (taker_buy - taker_sell) kümülatif son 12 bar, fiyata göre eğim
    window = range(max(0, i - 11), i + 1)
    cvd = sum(2 * tb[k] - v[k] for k in window)          # net agresif alım (base qty)
    cvd_norm = cvd / sum(v[k] for k in window) if sum(v[k] for k in window) > 0 else 0.0
    tbr_avg = statistics.mean([tbr(k) for k in window])
    tbr_dev = ratio - tbr_avg                            # son bar sapması
    ret3 = (c[i] / c[i - 3] - 1) * 100 if c[i - 3] > 0 else 0.0
    # Uyumsuzluk: fiyat yükseliyor ama net akış satıcı (klasik bearish diverjans)
    ret1 = (c[i] / c[i - 1] - 1) * 100 if c[i - 1] > 0 else 0.0
    net_bar = (2 * tb[i] - v[i]) / v[i] if v[i] > 0 else 0.0
    return {"tbr": ratio, "tbr_dev": tbr_dev, "cvd_norm": cvd_norm,
            "net_bar": net_bar, "ret1": ret1, "ret3": ret3,
            "div": (1.0 if (ret3 > 0 and cvd_norm < 0) else 0.0)}


def _gl_features(tr: dict, gl: dict, ts: float) -> dict | None:
    """KANAL 2: Global USDT öncü getirisi (TR'ye hizalı, yalnız kapanmış bar)."""
    ig = _idx_closed(gl, ts)
    if ig < 6:
        return None
    c = gl["c"]
    if c[ig - 1] <= 0 or c[ig - 3] <= 0:
        return None
    g1 = (c[ig] / c[ig - 1] - 1) * 100
    g3 = (c[ig] / c[ig - 3] - 1) * 100
    # Global taker-buy oranı (varsa) — ek sinyal
    gtbr = (gl["tb"][ig] / gl["v"][ig]) if gl["v"][ig] > 0 else 0.5
    return {"g_ret1": g1, "g_ret3": g3, "g_tbr": gtbr}


def _sim(cd: dict, bars: dict, *, commission_pct: float, slippage_pct: float):
    lo = bisect.bisect_left(bars["t"], cd["ts"])
    win = []
    for j in range(lo, len(bars["t"])):
        if bars["t"][j] > cd["ts"] + 125 * 60:
            break
        win.append({"open_time": bars["t"][j], "high": bars["h"][j],
                    "low": bars["l"][j], "close": bars["c"][j]})
    if not win:
        return None
    o = simulate_exit(win, cd["price"], entry_time=cd["ts"],
                      tp_pct=tp_pct_for(cd["target_pct"], 3.0), sl_pct=1.0,
                      trail_trigger_pct=2.0, trail_gap_pct=1.0, no_profit_min=30,
                      max_hold_min=120, commission_pct=commission_pct,
                      slippage_pct=slippage_pct, bar_seconds=300.0)
    return o.get("sim_pct")


def _load_cands(hours: float) -> list[dict]:
    import psycopg
    since = time.time() - hours * 3600.0
    out = []
    with psycopg.connect(_DB_URL, connect_timeout=8) as conn:
        for ts, sym, px, tgt in conn.execute(
            "SELECT created_at, symbol, price, target_pct FROM velocity_candidates "
            "WHERE passes=true AND created_at >= %s AND price > 0 ORDER BY created_at",
            (since,)):
            try:
                out.append({"ts": float(ts), "symbol": str(sym).upper(),
                            "price": float(px), "target_pct": float(tgt or 3.0)})
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# Analiz
# ---------------------------------------------------------------------------
def _ev(nets):
    nets = [n for n in nets if n is not None]
    if not nets:
        return {"n": 0, "ev": None}
    w = [x for x in nets if x > 0]; l = [x for x in nets if x <= 0]
    aw = statistics.mean(w) if w else 0.0; al = statistics.mean(l) if l else 0.0
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "wr": round(100 * len(w) / len(nets), 1),
            "pf": round(aw / abs(al), 2) if al else None}


def _pctile(vals, p):
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * p))] if s else 0.0


def _paired(sel, rest):
    import math
    sel = [x for x in sel if x is not None]; rest = [x for x in rest if x is not None]
    if not sel or not rest:
        return 0.0
    ms, mr = statistics.mean(sel), statistics.mean(rest)
    sd = statistics.pstdev(sel + rest)
    se = sd * math.sqrt(1 / len(sel) + 1 / len(rest))
    return (ms - mr) / se if se else 0.0


def _scan(recs: list[dict], keys: list[str], label: str) -> list[dict]:
    """Her feature için yüksek/alçak yarı (eşik eğitimde) → sınav EV + t."""
    recs = sorted(recs, key=lambda r: r["ts"])
    split = int(len(recs) * 0.6)
    tr, te = recs[:split], recs[split:]
    out = []
    for k in keys:
        tv = [r["f"][k] for r in tr]
        for side, p, better in (("high", 0.7, "ge"), ("low", 0.3, "le")):
            thr = _pctile(tv, p)
            sel = [r["net"] for r in te if (r["f"][k] >= thr if better == "ge" else r["f"][k] <= thr)]
            rest = [r["net"] for r in te if not (r["f"][k] >= thr if better == "ge" else r["f"][k] <= thr)]
            out.append({"feature": k, "side": side, "thr": round(thr, 4),
                        "test": _ev(sel), "t": round(_paired(sel, rest), 2)})
    out.sort(key=lambda x: -(x["test"]["ev"] if x["test"]["ev"] is not None else -9))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=400.0)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--commission", type=float, default=0.0015)
    ap.add_argument("--slippage", type=float, default=0.00025)
    ap.add_argument("--out", default="work/data_channel_research.json")
    args = ap.parse_args()

    print("=== YENİ VERİ KANALI ARAŞTIRMASI ===")
    cands = _load_cands(args.hours)
    print(f"aday: {len(cands)}")
    if len(cands) < 200:
        print("YETERSİZ VERİ"); return 1

    cache = await _build_cache(cands, args.fetch)
    trb = {s: _to_bars_from_cache(b) for s, b in cache.get("tr", {}).items()}
    glb = {s: _to_bars_from_cache(b) for s, b in cache.get("gl", {}).items()}
    print(f"TR bar: {len([s for s in trb if trb[s]['t']])} sembol | Global bar: {len(glb)} sembol")

    recs_of, recs_gl = [], []
    for cd in cands:
        tr = trb.get(cd["symbol"])
        if not tr or not tr["t"]:
            continue
        f = _tr_features(tr, cd["ts"])
        if f is None:
            continue
        net = _sim(cd, tr, commission_pct=args.commission, slippage_pct=args.slippage)
        if net is None:
            continue
        recs_of.append({"ts": cd["ts"], "sym": cd["symbol"], "f": f, "net": net})
        gl = glb.get(cd["symbol"])
        if gl and gl["t"]:
            gf = _gl_features(tr, gl, cd["ts"])
            if gf is not None:
                recs_gl.append({"ts": cd["ts"], "sym": cd["symbol"],
                                "f": {**gf, "ret1": f["ret1"]}, "net": net})
    print(f"KANAL1 (order-flow) kayıt: {len(recs_of)} | KANAL2 (lead-lag) kayıt: {len(recs_gl)}")

    report = {"generated_at": time.time(), "hours": args.hours}
    if recs_of:
        base = _ev([r["net"] for r in recs_of[int(len(recs_of) * .6):]])
        res = _scan(recs_of, ["tbr", "tbr_dev", "cvd_norm", "net_bar", "div"], "kanal1")
        report["channel1_orderflow"] = {"baseline_test": base, "features": res}
        print(f"\n== KANAL 1: ORDER-FLOW (baz SINAV EV {base['ev']}) ==")
        for r in res:
            print(f"  {r['feature']:9s} {r['side']:5s} thr {r['thr']:>9} → EV {r['test']['ev']:>7} "
                  f"n {r['test']['n']:>5} pf {r['test']['pf']} t={r['t']}")
        # Sembol yoğunlaşma (en iyi feature)
        best = res[0]
        pos = [r for r in res if r["test"]["ev"] and r["test"]["ev"] > 0 and r["t"] > 1.65]
        report["channel1_orderflow"]["positive_significant"] = pos
    if recs_gl:
        base2 = _ev([r["net"] for r in recs_gl[int(len(recs_gl) * .6):]])
        res2 = _scan(recs_gl, ["g_ret1", "g_ret3", "g_tbr", "ret1"], "kanal2")
        report["channel2_leadlag"] = {"baseline_test": base2, "features": res2}
        print(f"\n== KANAL 2: GLOBAL→TR LEAD-LAG (baz SINAV EV {base2['ev']}) ==")
        for r in res2:
            print(f"  {r['feature']:9s} {r['side']:5s} thr {r['thr']:>9} → EV {r['test']['ev']:>7} "
                  f"n {r['test']['n']:>5} pf {r['test']['pf']} t={r['t']}")
        pos2 = [r for r in res2 if r["test"]["ev"] and r["test"]["ev"] > 0 and r["t"] > 1.65]
        report["channel2_leadlag"]["positive_significant"] = pos2

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nrapor: {args.out}")
    for ch in ("channel1_orderflow", "channel2_leadlag"):
        if ch in report:
            p = report[ch].get("positive_significant", [])
            print(f"  {ch}: anlamlı pozitif feature = {len(p)}"
                  + (f" → {[x['feature']+':'+str(x['test']['ev']) for x in p]}" if p else ""))
    return 0


def _to_bars_from_cache(b: dict) -> dict:
    return {"t": b.get("t", []), "o": b.get("o", []), "h": b.get("h", []),
            "l": b.get("l", []), "c": b.get("c", []), "v": b.get("v", []),
            "tb": b.get("tb", [])}


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
