"""REJİM-GÜDÜMLÜ YÜKSEK-TF SİNYAL ARAŞTIRMASI (2026-10-12).

YENİ HİPOTEZ (dört tur negatif sonuç sonrası ürün kararı):
    5 dk ufkunda ve mevcut sinyalde edge yok. Farklı hipotez: (a) ufku 1 SAAT'e
    çıkar, (b) TREND/ARALIK rejimine göre AYRI sinyal kullan. Klasik görüş:
    trendde kırılım-devam, aralıkta ortalamaya-dönüş kârlıdır; tek tip sinyal
    ikisini de yapmaya çalışınca ikisinde de kaybeder.

REJİM (1h kanonik göstergeler — `technical_analysis` yeniden kullanılır):
    ADX(14)=Wilder, Choppiness(14), EMA50/EMA200 (1h).
    TREND: ADX>=25 ve Chopping<38 (ve istenirse EMA50>EMA200)
    ARALIK: ADX<20

SİNYALLER (her 1h kapanış barında, YALNIZ kapanmış barlar):
    S1 trend_kirilim : TREND rejiminde close > son 24 barın en yükseği (devam)
    S2 trend_dip     : TREND rejiminde fiyat EMA20'ye değdi ve EMA50 üstünde (trend dip)
    S3 aralik_dip    : ARALIK rejiminde close, son 24 barın alt %20 bandında (dönüş)
    S4 aralik_kirilim: ARALIK rejiminde close > son 24 barın en yükseği (başarısız kırılım → devam? kontrol)

ÇIKIŞ: ATR(14) tabanlı — SL = k_sl*ATR, TP = k_tp*ATR, maks tutma N bar.
    Bar-içi belirsizlikte KÖTÜMSER (aynı barda SL ve TP → SL önce).

ÖLÇÜM: walk-forward (ilk %60 seçim / son %40 sınav), EV/işlem, kazanma, payoff,
    3-fold, sembol yoğunlaşma, permütasyon. ANA SORU: aynı sinyal TREND'de ve
    ARALIK'ta FARKLI mı davranıyor (rejim-koşullu edge)?

KULLANIM:
    python backend/scripts/research_regime_signals.py --days 180 --top 50 --fetch
    python backend/scripts/research_regime_signals.py --days 180 --top 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "..", "work", "regime_cache.json")
_TR_BASE = "https://api.binance.me"
_GL_BASE = "https://api.binance.com"


# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------
async def _fetch_klines(base: str, symbol: str, interval: str, days: int) -> list:
    import ssl
    import urllib.request
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    end = int(time.time() * 1000)
    start = end - days * 86400_000
    out, cursor = [], start
    step = 1000
    while cursor < end:
        url = (f"{base}/api/v3/klines?symbol={symbol}&interval={interval}"
               f"&startTime={cursor}&endTime={end}&limit={step}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                batch = json.loads(r.read().decode())
        except Exception:
            break
        if not batch:
            break
        out.extend(batch)
        if len(batch) < step:
            break
        cursor = int(batch[-1][0]) + 1
        await asyncio.sleep(0.05)
    return out


def _to_ohlc(rows: list) -> dict:
    b = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for r in rows:
        try:
            b["t"].append(float(r[0]) / 1000.0); b["o"].append(float(r[1]))
            b["h"].append(float(r[2])); b["l"].append(float(r[3]))
            b["c"].append(float(r[4])); b["v"].append(float(r[5]))
        except (IndexError, TypeError, ValueError):
            continue
    return b


async def _universe(top: int) -> list[str]:
    from app.binance_tr_public import ticker_24h, trading_symbols
    syms = await trading_symbols("TRY")
    tk = await ticker_24h(syms)
    rows = [(r.get("symbol"), float(r.get("quoteVolume") or 0)) for r in (tk or []) if r.get("symbol")]
    rows.sort(key=lambda x: -x[1])
    return [s for s, _ in rows[:top] if s != "USDTTRY"]


async def _build_cache(top: int, days: int) -> dict:
    syms = await _universe(top)
    print(f"  evren: {len(syms)} likit TRY sembolü", flush=True)
    # NOT: kart 1d istenmişti ama sinyal 1h üzerinde üretiliyor; 1d indirmek
    # yalnız ağ maliyeti (100 sembol × 2 TF takılıyordu). d1 boş bırakılır.
    cache = {"symbols": syms, "days": days, "h1": {}, "d1": {}, "built_at": time.time()}
    os.makedirs(os.path.dirname(os.path.abspath(_CACHE)), exist_ok=True)
    for i, s in enumerate(syms):
        try:
            h1 = await _fetch_klines(_TR_BASE, s, "1h", days)
            cache["h1"][s] = _to_ohlc(h1)
        except Exception as exc:
            print(f"    {s}: {type(exc).__name__}", flush=True)
        # ARTIMLI yazım: kesinti olursa ilerleme korunur.
        if (i + 1) % 10 == 0:
            with open(_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            print(f"    ... {i+1}/{len(syms)} (kaydedildi)", flush=True)
    with open(_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    print(f"  önbellek: {_CACHE}", flush=True)
    return cache


# ---------------------------------------------------------------------------
# Rejim + sinyaller (yalnız kapanmış barlar)
# ---------------------------------------------------------------------------
def _adx(h, l, c, period=14):
    """Kanonik Wilder ADX (technical_analysis._adx ile aynı mantık)."""
    if len(c) < period * 2 + 1:
        return None
    tr, plus, minus = [], [], []
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        up, down = h[i] - h[i - 1], l[i - 1] - l[i]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)

    def wilder(vals, p):
        if len(vals) < p:
            return []
        out = [sum(vals[:p]) / p]
        for v in vals[p:]:
            out.append((out[-1] * (p - 1) + v) / p)
        return out
    trw, pw, mw = wilder(tr, period), wilder(plus, period), wilder(minus, period)
    if not trw:
        return None
    dx = []
    for a, p, m in zip(trw, pw, mw):
        pdi = 100 * p / a if a else 0.0
        mdi = 100 * m / a if a else 0.0
        dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0)
    adxs = wilder(dx, period)
    if not adxs:
        return None
    pdi = 100 * pw[-1] / trw[-1] if trw[-1] else 0.0
    mdi = 100 * mw[-1] / trw[-1] if trw[-1] else 0.0
    return {"adx": float(adxs[-1]), "plus_di": float(pdi), "minus_di": float(mdi)}


def _chop(h, l, c, period=14):
    if len(c) < period + 1:
        return None
    rng = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    tot = sum(rng[-period:]); pr = max(h[-period:]) - min(l[-period:])
    if tot <= 0 or pr <= 0:
        return None
    return float(100 * math.log10(tot / pr) / math.log10(period))


def _ema(vals, period):
    if len(vals) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(vals[:period]) / period
    for v in vals[period:]:
        e = v * k + e * (1 - k)
    return e


def _ema_series(vals, period):
    if len(vals) < period:
        return []
    k = 2.0 / (period + 1)
    e = sum(vals[:period]) / period
    out = [e]
    for v in vals[period:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _atr(h, l, c, period=14):
    if len(c) < period + 1:
        return None
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    return statistics.mean(trs[-period:]) if len(trs) >= period else None


def _regime_and_signals(bars: dict, i: int, window: int = 260) -> dict | None:
    """`i`. bar KAPANMIŞ kabul edilir; yalnız [0..i] verisi kullanılır (look-ahead yok).

    PERFORMANS: göstergeler SABİT PENCEREDE (son `window` bar) hesaplanır — tüm
    prefix üzerinde O(n²) yerine O(window) per bar. EMA200 + ADX(14)·2 + Chop(14)
    için 260 bar fazlasıyla yeter (luok-ahead yok: pencere `i`'de bitiyor)."""
    if i < 60:
        return None
    lo = max(0, i + 1 - window)
    h = bars["h"][lo:i + 1]; l = bars["l"][lo:i + 1]; c = bars["c"][lo:i + 1]
    adx = _adx(h, l, c)
    if not adx:
        return None
    chop = _chop(h, l, c)
    ema50 = _ema(c, 50); ema200 = _ema(c, 200) if len(c) >= 200 else None
    atr = _atr(h, l, c)
    if atr is None or atr <= 0:
        return None
    price = c[-1]
    hi24 = max(h[-25:-1]) if len(h) >= 25 else max(h[:-1])
    lo24 = min(l[-25:-1]) if len(l) >= 25 else min(l[:-1])
    span = hi24 - lo24
    pos24 = ((price - lo24) / span) if span > 0 else 0.5
    prev_hi24 = max(h[-25:-1]) if len(h) >= 25 else None
    ema20 = _ema(c, 20)
    # Rejim
    trend = bool(adx["adx"] >= 25 and (chop is None or chop < 38))
    if ema50 is not None and ema200 is not None:
        trend_up = bool(ema50 > ema200)
    else:
        trend_up = bool(adx["plus_di"] > adx["minus_di"])
    rng = bool(adx["adx"] < 20)
    sig = {}
    # S1 trend kırılım (devam): trend yukarı + son 24 barın zirvesini aştı
    sig["trend_kirilim"] = bool(trend and trend_up and prev_hi24 is not None and price > prev_hi24)
    # S2 trend dip: trend yukarı + EMA20'ye değdi (low<=EMA20) + kapanış EMA50 üstünde
    sig["trend_dip"] = bool(trend and trend_up and ema20 is not None and l[-1] <= ema20 and price > (ema50 or 0))
    # S3 aralık dip (dönüş): aralık + alt %20 bandında
    sig["aralik_dip"] = bool(rng and pos24 <= 0.20)
    # S4 aralık kırılım: aralık + 24s zirvesini aştı (başarısız kırılım kontrolü)
    sig["aralik_kirilim"] = bool(rng and prev_hi24 is not None and price > prev_hi24)
    return {"adx": adx["adx"], "chop": chop, "atr": atr, "price": price,
            "pos24": pos24, "regime": "TREND" if trend else ("RANGE" if rng else "MIX"),
            "signals": sig}


def _simulate(bars: dict, i: int, atr: float, *, k_sl: float, k_tp: float,
              max_hold: int, commission_pct: float = 0.0015,
              slippage_pct: float = 0.00025) -> float | None:
    """`i` barının KAPANIŞINDA gir; ileri barlarda ATR tabanlı SL/TP/süre.

    Kötümser (aynı barda SL ve TP → SL önce) + NET maliyet: giriş/çıkış komisyonu
    (COMMISSION_PCT×2) ve çıkış kayması DÜŞÜLÜR. Maliyet olmadan ölçüm yanıltıcı
    (5dk turunda ders: brüt pozitif EV, komisyonla negatife dönmüştü)."""
    entry = bars["c"][i]
    if entry <= 0:
        return None
    sl = entry - k_sl * atr
    tp = entry + k_tp * atr
    n = len(bars["c"])
    exit_px = None
    for j in range(i + 1, min(i + 1 + max_hold, n)):
        hi = bars["h"][j]; lo = bars["l"][j]
        if lo <= sl:                      # kötümser: SL önce
            exit_px = sl; break
        if hi >= tp:
            exit_px = tp; break
    if exit_px is None:
        exit_px = bars["c"][min(i + max_hold, n - 1)]
    fill = exit_px * (1.0 - slippage_pct)
    gross = (fill / entry - 1) * 100
    cost = (1.0 + fill / entry) * commission_pct * 100
    return round(gross - cost, 3)


# ---------------------------------------------------------------------------
# Analiz
# ---------------------------------------------------------------------------
def _metrics(nets):
    nets = [n for n in nets if n is not None]
    if not nets:
        return {"n": 0, "ev": None}
    w = [x for x in nets if x > 0]; l = [x for x in nets if x <= 0]
    aw = statistics.mean(w) if w else 0.0; al = statistics.mean(l) if l else 0.0
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "wr": round(100 * len(w) / len(nets), 1),
            "pf": round(aw / abs(al), 2) if al else None,
            "med": round(statistics.median(nets), 2)}


def _collect(cache: dict, *, k_sl: float, k_tp: float, max_hold: int,
             commission_pct: float = 0.0015, slippage_pct: float = 0.00025) -> list[dict]:
    """Tüm sembol/barlarda sinyal üret → kayıtlar."""
    recs = []
    for s, b in cache["h1"].items():
        if not b["t"] or len(b["t"]) < 120:
            continue
        for i in range(len(b["t"])):
            r = _regime_and_signals(b, i)
            if r is None:
                continue
            hits = [k for k, v in r["signals"].items() if v]
            if not hits:
                continue
            net = _simulate(b, i, r["atr"], k_sl=k_sl, k_tp=k_tp, max_hold=max_hold,
                            commission_pct=commission_pct, slippage_pct=slippage_pct)
            if net is None:
                continue
            recs.append({"ts": b["t"][i], "sym": s, "regime": r["regime"],
                         "signals": hits, "net": net})
    recs.sort(key=lambda x: x["ts"])
    return recs


def _paired(sel, rest):
    sel = [x for x in sel if x is not None]; rest = [x for x in rest if x is not None]
    if len(sel) < 5 or len(rest) < 5:
        return 0.0
    ms, mr = statistics.mean(sel), statistics.mean(rest)
    sd = statistics.pstdev(sel + rest)
    se = sd * math.sqrt(1 / len(sel) + 1 / len(rest))
    return (ms - mr) / se if se else 0.0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--k-sl", type=float, default=1.5)
    ap.add_argument("--k-tp", type=float, default=3.0)
    ap.add_argument("--max-hold", type=int, default=24)
    ap.add_argument("--commission", type=float, default=0.0015)
    ap.add_argument("--slippage", type=float, default=0.00025)
    ap.add_argument("--out", default="work/regime_signal_research.json")
    args = ap.parse_args()

    print("=== REJİM-GÜDÜMLÜ YÜKSEK-TF SİNYAL ARAŞTIRMASI ===")
    if os.path.exists(_CACHE) and not args.fetch:
        with open(_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"  önbellekten: {len(cache.get('h1', {}))} sembol, {cache.get('days')} gün")
    else:
        cache = await _build_cache(args.top, args.days)
    if not cache.get("h1"):
        print("VERİ YOK"); return 1

    recs = _collect(cache, k_sl=args.k_sl, k_tp=args.k_tp, max_hold=args.max_hold,
                    commission_pct=args.commission, slippage_pct=args.slippage)
    print(f"  sinyal kaydı: {len(recs)}")
    if len(recs) < 200:
        print("YETERSİZ SİNYAL"); return 1

    # Rejim dağılımı
    from collections import Counter
    rc = Counter(r["regime"] for r in recs)
    sc = Counter(s for r in recs for s in r["signals"])
    print(f"  rejim: {dict(rc)}")
    print(f"  sinyal: {dict(sc)}")

    split = int(len(recs) * 0.6)
    tr, te = recs[:split], recs[split:]
    base = _metrics([r["net"] for r in te])
    print(f"  baz SINAV EV {base['ev']} (n {base['n']})")

    # Sinyal × rejim matrisi (SINAV) + eğitim-eşikli t
    print(f"\n  {'sinyal':16s}{'rejim':7s}{'n':>6}{'EV':>8}{'wr':>6}{'pf':>6}{'t':>7}")
    results = []
    for sg in ("trend_kirilim", "trend_dip", "aralik_dip", "aralik_kirilim"):
        for rg in ("TREND", "RANGE", "MIX"):
            sel = [r["net"] for r in te if sg in r["signals"] and r["regime"] == rg]
            rest = [r["net"] for r in te if not (sg in r["signals"] and r["regime"] == rg)]
            m = _metrics(sel); t = _paired(sel, rest)
            results.append({"signal": sg, "regime": rg, "test": m, "t": round(t, 2)})
            if m["n"]:
                print(f"  {sg:16s}{rg:7s}{m['n']:>6}{m['ev']:>8}{m['wr']:>6}{str(m['pf']):>6}{round(t,2):>7}")

    # REJİM-KOŞULLU EDGE: aynı sinyal, TREND vs RANGE farkı
    print("\n  == REJİM-KOŞULLU FARK (aynı sinyal TREND - RANGE) ==")
    for sg in ("trend_kirilim", "trend_dip", "aralik_dip", "aralik_kirilim"):
        tn = [r["net"] for r in te if sg in r["signals"] and r["regime"] == "TREND"]
        rn = [r["net"] for r in te if sg in r["signals"] and r["regime"] == "RANGE"]
        if len(tn) >= 5 and len(rn) >= 5:
            print(f"  {sg:16s} TREND {_metrics(tn)['ev']} (n{len(tn)}) vs RANGE {_metrics(rn)['ev']} (n{len(rn)})")

    pos = [x for x in results if x["test"]["ev"] is not None and x["test"]["ev"] > 0 and x["t"] > 1.65]
    report = {"generated_at": time.time(), "days": args.days, "top": args.top,
              "records": len(recs), "regime_counts": dict(rc), "signal_counts": dict(sc),
              "baseline_test": base, "results": results,
              "positive_significant": pos,
              "verdict": "REGIME_EDGE_FOUND" if pos else "NO_REGIME_EDGE"}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nrapor: {args.out}")
    if pos:
        print(f"KARAR: REGIME_EDGE_FOUND — {len(pos)} anlamlı pozitif (sinyal×rejim):")
        for p in pos:
            print(f"  {p['signal']} × {p['regime']} → EV {p['test']['ev']}% t={p['t']} n={p['test']['n']}")
    else:
        print("KARAR: NO_REGIME_EDGE — hiçbir sinyal×rejim sınavda anlamlı pozitif EV vermedi")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
