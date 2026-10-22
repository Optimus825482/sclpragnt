"""Sembol başına çok zamanlı teknik analiz raporu — sistem kurallarından BAĞIMSIZ (2026-10-21, kullanıcı isteği).

Her sembol için Binance TR public klines (15m / 1h / 4h / 1d) çekilir ve standart teknik analiz yapılır:
  * Trend yapısı: SMA 7/20/50/99 + EMA 20/50 dizilimi (1h, 4h), fiyatın MA'lara konumu, 4h yüksek tepe/dip yapısı.
  * Momentum: RSI14 (1h, 4h), MACD 12/26/9 (1h, 4h; çizgi, sinyal, histogram ve yönü), StochRSI K (1h), ADX14 (+DI/−DI, 4h).
  * Oynaklık: ATR14 (1h, 4h, %), Bollinger 20/2 (1h) konumu ve bant genişliği.
  * Hacim: 24 sa VWAP, OBV eğimi (1h, 24 mum), son 12 sa hacim / 7 gün ortalaması.
  * Seviyeler: 1h swing tepe/dipleri (fraktal, 3 mum), klasik günlük pivotlar (P, R1, R2, S1, S2), 24 sa ve 7 gün tepe/dip.
  * Fibonacci: 4h'te son belirgin dip→tepe bacağı; geri çekilme 0,382 / 0,5 / 0,618; uzantı 1,272 / 1,618.
  * Mum: son kapanan 1h ve 4h mum (gövde, fitiller) ve basit formasyon adı.
  * Sentez: yön (yükseliş / nötr / düşüş), T1 ve T2 hedefleri (en yakın dirençler, Bollinger üst bandı, Fibonacci uzantısı,
    ATR projeksiyonu), geçersizlik seviyesi (en yakın swing dip / S1), hedefe ulaşma süresi tahmini iki yoldan:
    (a) ATR hızı: mesafe / (ATR1h × verimlilik 0,6); (b) TARİHSEL: son 7 günde her 15 dk mumdan sonra aynı yüzdeyi
    kaç saatte gördüğü (medyan) ve 72 saat içinde görme oranı.
  * Giriş fiyatı verildiyse (SEMBOL=fiyat): şu anki kâr/zarar, T1/T2'nin girişe göre yüzdesi.

Çıktı: docs/TEKNIK_ANALIZ_<tarih>.md (Türkçe) + stdout. Bu bir yatırım tavsiyesi değildir; göstergelerin söylediğini özetler.

KULLANIM: python backend/scripts/ta_symbol_report.py MINATRY=3.73 WTRY=0.7807 ...   (fiyatsız: python ... MINATRY WTRY)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import math
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.binance_tr_public import klines      # noqa: E402
from app import ma_buy_signals as S           # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=3))
DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "docs"))
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


# ------------------------------------------------------------------------------------------------------- veri
def bars(rows, tf_ms: int, now_ms: int) -> list[dict]:
    out = []
    for r in rows or []:
        try:
            b = {"t": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]),
                 "v": float(r[5]), "q": float(r[7]) if len(r) > 7 else float(r[5]) * float(r[4])}
        except (TypeError, ValueError, IndexError):
            continue
        if b["t"] + tf_ms <= now_ms:
            out.append(b)
    return out


async def fetch_all(sym: str, now_ms: int) -> dict:
    out = {}
    for tf, lim in (("15m", 720), ("1h", 400), ("4h", 200), ("1d", 120)):
        out[tf] = bars(await klines(sym, tf, limit=lim), TF_MS[tf], now_ms)
    return out


# ------------------------------------------------------------------------------------------------------- göstergeler
def last(x):
    return x[-1] if x else None


def ema(vals, n):
    return S.ema_series(vals, n)


def sma(vals, n):
    return S.sma_series(vals, n)


def macd(closes, f=12, s=26, sig=9):
    ef, es = ema(closes, f), ema(closes, s)
    line = [None if (a is None or b is None) else a - b for a, b in zip(ef, es)]
    vals = [v for v in line if v is not None]
    sg = ema(vals, sig)
    signal = [None] * (len(line) - len(vals)) + sg
    hist = [None if (a is None or b is None) else a - b for a, b in zip(line, signal)]
    return line, signal, hist


def atr(b, n=14):
    tr = []
    for i in range(1, len(b)):
        pc = b[i - 1]["c"]
        tr.append(max(b[i]["h"] - b[i]["l"], abs(b[i]["h"] - pc), abs(b[i]["l"] - pc)))
    if len(tr) < n:
        return None
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a


def adx_di(b, n=14):
    """Wilder ADX, +DI, −DI (son değer)."""
    if len(b) < 2 * n + 1:
        return None, None, None
    tr, pdm, mdm = [], [], []
    for i in range(1, len(b)):
        h, l, pc, ph, pl = b[i]["h"], b[i]["l"], b[i - 1]["c"], b[i - 1]["h"], b[i - 1]["l"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)

    def rma(x):
        a = sum(x[:n]) / n
        out = [a]
        for v in x[n:]:
            a = (a * (n - 1) + v) / n
            out.append(a)
        return out
    trs, ps, ms = rma(tr), rma(pdm), rma(mdm)
    dip = [100 * p / t if t else 0 for p, t in zip(ps, trs)]
    dim = [100 * m / t if t else 0 for m, t in zip(ms, trs)]
    dx = [100 * abs(a - b_) / (a + b_) if (a + b_) else 0 for a, b_ in zip(dip, dim)]
    adx = rma(dx)
    return adx[-1], dip[-1], dim[-1]


def bollinger(closes, n=20, k=2.0):
    if len(closes) < n:
        return None
    w = closes[-n:]
    m = sum(w) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
    return {"mid": m, "up": m + k * sd, "lo": m - k * sd, "width_pct": (4 * k * sd / m) * 100 / 2 if m else None,
            "pos": (closes[-1] - (m - k * sd)) / (2 * k * sd) if sd else 0.5}


def obv_slope(b, n=24):
    obv = 0.0
    series = []
    for i in range(1, len(b)):
        if b[i]["c"] > b[i - 1]["c"]:
            obv += b[i]["v"]
        elif b[i]["c"] < b[i - 1]["c"]:
            obv -= b[i]["v"]
        series.append(obv)
    if len(series) < n + 1:
        return None
    base = sum(abs(x) for x in series[-n:]) / n or 1.0
    return (series[-1] - series[-n - 1]) / base


def vwap(b):
    num = sum((x["h"] + x["l"] + x["c"]) / 3 * x["v"] for x in b)
    den = sum(x["v"] for x in b)
    return num / den if den else None


def swings(b, k=3):
    """Fraktal tepe/dipler: (index, fiyat)."""
    highs, lows = [], []
    for i in range(k, len(b) - k):
        if all(b[i]["h"] > b[j]["h"] for j in range(i - k, i + k + 1) if j != i):
            highs.append((i, b[i]["h"]))
        if all(b[i]["l"] < b[j]["l"] for j in range(i - k, i + k + 1) if j != i):
            lows.append((i, b[i]["l"]))
    return highs, lows


def pivots(day):
    h, l, c = day["h"], day["l"], day["c"]
    p = (h + l + c) / 3
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l)}


def fib_leg(b4, lookback=60):
    """Son belirgin dip→tepe bacağı (4h fraktal k=2). Dönüş: {low, high, low_t, high_t, retr, ext} ya da None."""
    seg = b4[-lookback:]
    highs, lows = swings(seg, 2)
    if not highs or not lows:
        return None
    hi_i, hi = max(highs, key=lambda x: x[1])            # bacağın tepesi: pencere içindeki en yüksek fraktal
    lows_before = [x for x in lows if x[0] < hi_i]
    if not lows_before:
        return None
    lo_i, lo = min(lows_before, key=lambda x: x[1])
    if hi <= lo:
        return None
    rng = hi - lo
    return {"low": lo, "high": hi, "low_t": seg[lo_i]["t"], "high_t": seg[hi_i]["t"],
            "retr": {"0.382": hi - 0.382 * rng, "0.5": hi - 0.5 * rng, "0.618": hi - 0.618 * rng},
            "ext": {"1.272": lo + 1.272 * rng, "1.618": lo + 1.618 * rng}}


def candle_name(b):
    o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    rng = h - l or 1e-12
    body = abs(c - o) / rng
    up = (h - max(o, c)) / rng
    dn = (min(o, c) - l) / rng
    if body < 0.1:
        return "doji (kararsızlık)"
    if dn > 0.6 and body < 0.3:
        return "çekiç (alt fitil uzun, alıcı tepkisi)"
    if up > 0.6 and body < 0.3:
        return "kayan yıldız (üst fitil uzun, satıcı tepkisi)"
    if body > 0.7:
        return "güçlü " + ("yeşil gövde" if c > o else "kırmızı gövde")
    return "yeşil" if c > o else "kırmızı"


def engulfing(b_prev, b):
    if b["c"] > b["o"] and b_prev["c"] < b_prev["o"] and b["c"] >= b_prev["o"] and b["o"] <= b_prev["c"]:
        return "yükseliş yutan"
    if b["c"] < b["o"] and b_prev["c"] > b_prev["o"] and b["o"] >= b_prev["c"] and b["c"] <= b_prev["o"]:
        return "düşüş yutan"
    return None


def time_to_reach(b15, pct, max_h=72):
    """Son 7 günde her 15 dk mumdan sonra +pct% seviyesini ilk görme süresi (saat): (ulaşma oranı, medyan saat)."""
    n = max_h * 4
    hours, reached, total = [], 0, 0
    for i in range(len(b15) - n):
        c = b15[i]["c"]
        lvl = c * (1 + pct / 100)
        total += 1
        for k in range(1, n + 1):
            if b15[i + k]["h"] >= lvl:
                hours.append(k / 4)
                reached += 1
                break
    if not total:
        return None, None
    return reached / total, (st.median(hours) if hours else None)


def fmt(x, d=None):
    if x is None:
        return "—"
    if d is None:
        d = 4 if abs(x) < 10 else (2 if abs(x) < 1000 else 1)
    return f"{x:,.{d}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def pct(x, d=2):
    return "—" if x is None else f"{x:+.{d}f}%".replace(".", ",")


# ------------------------------------------------------------------------------------------------------- analiz
def analyze(sym: str, entry: float | None, data: dict, now_ms: int) -> tuple[list[str], dict]:
    b15, b1, b4, b1d = data["15m"], data["1h"], data["4h"], data["1d"]
    c1 = [x["c"] for x in b1]
    c4 = [x["c"] for x in b4]
    px = b15[-1]["c"]
    lines = [f"## {sym}  —  {fmt(px)} TRY" + (f"  (giriş {fmt(entry)}, {pct((px / entry - 1) * 100)})" if entry else ""), ""]

    # --- trend
    s7_4, s20_4, s50_4, s99_4 = (last(sma(c4, n)) for n in (7, 20, 50, 99))
    e20_4, e50_4 = last(ema(c4, 20)), last(ema(c4, 50))
    s20_1, s50_1, e20_1, e50_1 = last(sma(c1, 20)), last(sma(c1, 50)), last(ema(c1, 20)), last(ema(c1, 50))
    h4h, l4h = swings(b4[-60:], 2)
    hh = "yüksek tepe" if len(h4h) >= 2 and h4h[-1][1] > h4h[-2][1] else ("alçak tepe" if len(h4h) >= 2 else "—")
    hl = "yüksek dip" if len(l4h) >= 2 and l4h[-1][1] > l4h[-2][1] else ("alçak dip" if len(l4h) >= 2 else "—")
    above = sum(1 for m in (s7_4, s20_4, s50_4, s99_4) if m is not None and px > m)
    align4 = "yükseliş dizilimi" if (s7_4 and s20_4 and s50_4 and s7_4 > s20_4 > s50_4) else ("düşüş dizilimi" if (s7_4 and s20_4 and s50_4 and s7_4 < s20_4 < s50_4) else "karışık")
    trend4 = ("yükseliş" if above >= 3 and hl == "yüksek dip" else "düşüş" if above <= 1 and hh == "alçak tepe" else "nötr / dönüş")
    lines += ["**Trend**",
              f"- 4h: fiyat SMA7 {fmt(s7_4)} / SMA20 {fmt(s20_4)} / SMA50 {fmt(s50_4)} / SMA99 {fmt(s99_4)} — {above}/4 üstünde, {align4}; "
              f"yapı: {hh}, {hl} → **{trend4}**.",
              f"- 1h: EMA20 {fmt(e20_1)} / EMA50 {fmt(e50_1)} ({'fiyat üstte' if e20_1 and px > e20_1 else 'fiyat altta'}; "
              f"{'EMA20 > EMA50 kısa vade yukarı' if e20_1 and e50_1 and e20_1 > e50_1 else 'EMA20 < EMA50 kısa vade aşağı'})."]

    # --- momentum
    rsi1, rsi4 = last(S.rsi_series(c1, 14)), last(S.rsi_series(c4, 14))
    ml1, ms1, mh1 = macd(c1)
    ml4, ms4, mh4 = macd(c4)
    mh1_dir = "artıyor" if mh1[-1] is not None and mh1[-2] is not None and mh1[-1] > mh1[-2] else "azalıyor"
    mh4_dir = "artıyor" if mh4[-1] is not None and mh4[-2] is not None and mh4[-1] > mh4[-2] else "azalıyor"
    st1 = last(S.stoch_rsi_k(c1))
    adx4, dip4, dim4 = adx_di(b4)
    rsi_txt = lambda r: "—" if r is None else f"{r:.0f} ({'aşırı alım' if r >= 70 else 'aşırı satım' if r <= 30 else 'nötr'})"
    lines += ["**Momentum**",
              f"- RSI14: 1h {rsi_txt(rsi1)}, 4h {rsi_txt(rsi4)}.",
              f"- MACD 12/26/9: 1h {'çizgi sinyalin üstünde' if ml1[-1] is not None and ms1[-1] is not None and ml1[-1] > ms1[-1] else 'çizgi sinyalin altında'}, histogram {mh1_dir}; "
              f"4h {'üstünde' if ml4[-1] is not None and ms4[-1] is not None and ml4[-1] > ms4[-1] else 'altında'}, histogram {mh4_dir}.",
              f"- StochRSI K (1h): {fmt(st1, 0)} ({'tavan bölgesi' if st1 is not None and st1 > 80 else 'taban bölgesi' if st1 is not None and st1 < 20 else 'orta'}).",
              f"- ADX14 (4h): {fmt(adx4, 0)} ({'trend güçlü' if adx4 and adx4 >= 25 else 'trend zayıf / yatay'}), +DI {fmt(dip4, 0)} / −DI {fmt(dim4, 0)} → "
              f"{'alıcılar baskın' if dip4 and dim4 and dip4 > dim4 else 'satıcılar baskın'}."]

    # --- oynaklık + hacim
    a1, a4 = atr(b1), atr(b4)
    a1p = a1 / px * 100 if a1 else None
    bb = bollinger(c1)
    vw = vwap(b15[-96:])
    obv = obv_slope(b1, 24)
    q12 = sum(x["q"] for x in b15[-48:])
    qavg = sum(x["q"] for x in b15[-672:]) / 14 if len(b15) >= 672 else None
    vr = q12 / qavg if qavg else None
    lines += ["**Oynaklık ve hacim**",
              f"- ATR14: 1h {fmt(a1)} ({pct(a1p)}), 4h {fmt(a4)} ({pct(a4 / px * 100 if a4 else None)}).",
              f"- Bollinger 20/2 (1h): alt {fmt(bb['lo'])} / orta {fmt(bb['mid'])} / üst {fmt(bb['up'])}; fiyat bant içinde %{bb['pos'] * 100:.0f} konumda"
              f"{' (üst banda yaslanmış)' if bb['pos'] > 0.9 else ' (alt banda yakın)' if bb['pos'] < 0.1 else ''}; bant genişliği {pct(bb['width_pct'], 1)}." if bb else "- Bollinger: veri yetersiz.",
              f"- 24 sa VWAP {fmt(vw)} ({'fiyat üstünde' if vw and px > vw else 'fiyat altında'}); OBV 24 mum eğimi {fmt(obv, 2)} "
              f"({'alım baskısı' if obv and obv > 0.1 else 'satış baskısı' if obv and obv < -0.1 else 'dengeli'}); son 12 sa hacim / 7 gün ort. {fmt(vr, 2)}×."]

    # --- seviyeler
    hi24, lo24 = max(x["h"] for x in b15[-96:]), min(x["l"] for x in b15[-96:])
    hi7, lo7 = max(x["h"] for x in b15[-672:]), min(x["l"] for x in b15[-672:])
    sh, sl = swings(b1[-200:], 3)
    res = sorted({round(p, 10) for _, p in sh if p > px})[:3]
    sup = sorted({round(p, 10) for _, p in sl if p < px}, reverse=True)[:3]
    pv = pivots(b1d[-1]) if b1d else None
    lines += ["**Seviyeler**",
              f"- Dirençler (1h swing): {', '.join(fmt(r) for r in res) or '—'}; 24 sa tepe {fmt(hi24)}, 7 gün tepe {fmt(hi7)}.",
              f"- Destekler (1h swing): {', '.join(fmt(s) for s in sup) or '—'}; 24 sa dip {fmt(lo24)}, 7 gün dip {fmt(lo7)}.",
              (f"- Günlük pivot: P {fmt(pv['P'])}, R1 {fmt(pv['R1'])}, R2 {fmt(pv['R2'])}, S1 {fmt(pv['S1'])}, S2 {fmt(pv['S2'])}." if pv else "- Pivot: günlük veri yok.")]
    fb = fib_leg(b4)
    if fb:
        lines += [f"- Fibonacci (4h bacak {fmt(fb['low'])} → {fmt(fb['high'])}, {dt.datetime.fromtimestamp(fb['low_t'] / 1000, TZ):%d.%m} → "
                  f"{dt.datetime.fromtimestamp(fb['high_t'] / 1000, TZ):%d.%m}): geri çekilme 0,382 {fmt(fb['retr']['0.382'])} / 0,5 {fmt(fb['retr']['0.5'])} / "
                  f"0,618 {fmt(fb['retr']['0.618'])}; uzantı 1,272 {fmt(fb['ext']['1.272'])} / 1,618 {fmt(fb['ext']['1.618'])}."]
    # --- mum
    c1_last, c4_last = b1[-1], b4[-1]
    eng1 = engulfing(b1[-2], b1[-1])
    lines += ["**Mum**",
              f"- Son 1h: {candle_name(c1_last)}{' + ' + eng1 if eng1 else ''}; son 4h: {candle_name(c4_last)}."]

    # --- sentez: hedefler ve zaman
    cands_up = [r for r in res] + ([bb["up"]] if bb and bb["up"] > px else []) + ([pv["R1"], pv["R2"]] if pv else []) + \
        ([fb["high"]] if fb and fb["high"] > px else []) + ([fb["ext"]["1.272"], fb["ext"]["1.618"]] if fb else []) + [hi24, hi7]
    ups = sorted({round(x, 10) for x in cands_up if x and x > px * 1.002})
    t1 = ups[0] if ups else px * (1 + (a1p or 1) * 2 / 100)
    t2 = next((u for u in ups if u > t1 * 1.01), None) or px * (1 + (a1p or 1) * 4 / 100)
    inval = max([s for s in sup] + ([pv["S1"]] if pv and pv["S1"] < px else []) + [lo24]) if (sup or pv) else lo24
    score = 0
    score += 1 if trend4 == "yükseliş" else -1 if trend4 == "düşüş" else 0
    score += 1 if (e20_1 and e50_1 and e20_1 > e50_1 and px > e20_1) else -1 if (e20_1 and px < e20_1) else 0
    score += 1 if (mh1[-1] is not None and mh1[-1] > 0 and mh1_dir == "artıyor") else -1 if (mh1[-1] is not None and mh1[-1] < 0) else 0
    score += 1 if (dip4 and dim4 and dip4 > dim4 and adx4 and adx4 >= 20) else 0
    score += 1 if (obv and obv > 0.1) else -1 if (obv and obv < -0.1) else 0
    score -= 1 if (rsi1 and rsi1 >= 75) else 0
    bias = "YÜKSELİŞ" if score >= 3 else "DÜŞÜŞ" if score <= -2 else "NÖTR"
    d1, d2 = (t1 / px - 1) * 100, (t2 / px - 1) * 100
    eff = 0.6
    h1_atr = d1 / (a1p * eff) if a1p else None
    h2_atr = d2 / (a1p * eff) if a1p else None
    r1, m1 = time_to_reach(b15, d1)
    r2, m2 = time_to_reach(b15, d2)
    summ = {"sym": sym, "px": px, "entry": entry, "bias": bias, "score": score, "t1": t1, "t2": t2, "inval": inval,
            "d1": d1, "d2": d2, "h1": h1_atr, "h2": h2_atr, "r1": r1, "m1": m1, "r2": r2, "m2": m2, "rsi1": rsi1}
    lines += ["**Sentez**",
              f"- Yön puanı {score:+d} → **{bias}** (trend, 1h EMA, MACD, DI/ADX, OBV, RSI aşırılığı).",
              f"- T1 {fmt(t1)} ({pct(d1)} şu andan{', girişe göre ' + pct((t1 / entry - 1) * 100) if entry else ''}): ATR hızıyla ~{fmt(h1_atr, 1)} sa; "
              f"tarihsel: son 7 günde bu artışı 72 sa içinde görme oranı {fmt(r1 * 100 if r1 is not None else None, 0)}%, görenlerde medyan {fmt(m1, 1)} sa.",
              f"- T2 {fmt(t2)} ({pct(d2)} şu andan{', girişe göre ' + pct((t2 / entry - 1) * 100) if entry else ''}): ATR hızıyla ~{fmt(h2_atr, 1)} sa; "
              f"tarihsel görme oranı {fmt(r2 * 100 if r2 is not None else None, 0)}%, medyan {fmt(m2, 1)} sa.",
              f"- Geçersizlik: {fmt(inval)} ({pct((inval / px - 1) * 100)} şu andan) altında kapanış yükseliş senaryosunu bozar.", ""]
    return lines, summ


async def main(argv: list[str]) -> int:
    items = []
    for a in argv:
        s, _, e = a.partition("=")
        items.append((s.strip().upper(), float(e) if e else None))
    if not items:
        print("kullanım: ta_symbol_report.py SEMBOL[=giriş] ...")
        return 2
    now_ms = int(time.time() * 1000)
    gen = dt.datetime.now(TZ)
    lines = [f"# Teknik analiz — {gen:%Y-%m-%d %H:%M} ({len(items)} sembol)", "",
             "Sistem kurallarından bağımsız, standart çok zamanlı teknik analiz (15m / 1h / 4h / 1d, Binance TR). "
             "Hedefler en yakın dirençler, Bollinger üst bandı, günlük pivotlar ve Fibonacci uzantılarından; süre tahmini ATR hızı ve sembolün "
             "son 7 günde aynı yüzdeyi görme süresinden. Bu bir yatırım tavsiyesi değildir; göstergelerin bugünkü okumasıdır.", ""]
    summaries = []
    for sym, entry in items:
        try:
            data = await fetch_all(sym, now_ms)
            ls, summ = analyze(sym, entry, data, now_ms)
            lines += ls
            summaries.append(summ)
        except Exception as exc:  # noqa: BLE001
            lines += [f"## {sym}", "", f"HATA: {type(exc).__name__}: {exc}", ""]
    # özet tablo
    lines += ["## Özet", "",
              "| Sembol | Şu an | Giriş | K/Z | Yön | T1 | T1 girişe göre | T1 süre (ATR / tarihsel medyan) | T1 görme oranı | T2 | T2 girişe göre | Geçersizlik |",
              "|---|---:|---:|---:|---|---:|---:|---|---:|---:|---:|---:|"]
    for s in summaries:
        e = s["entry"]
        lines.append(f"| {s['sym']} | {fmt(s['px'])} | {fmt(e) if e else '—'} | {pct((s['px'] / e - 1) * 100) if e else '—'} | {s['bias']} ({s['score']:+d}) | "
                     f"{fmt(s['t1'])} ({pct(s['d1'])}) | {pct((s['t1'] / e - 1) * 100) if e else '—'} | ~{fmt(s['h1'], 1)} sa / {fmt(s['m1'], 1)} sa | "
                     f"{fmt(s['r1'] * 100 if s['r1'] is not None else None, 0)}% | {fmt(s['t2'])} ({pct(s['d2'])}) | {pct((s['t2'] / e - 1) * 100) if e else '—'} | "
                     f"{fmt(s['inval'])} ({pct((s['inval'] / s['px'] - 1) * 100)}) |")
    md = "\n".join(lines)
    os.makedirs(DOCS_DIR, exist_ok=True)
    path = os.path.join(DOCS_DIR, f"TEKNIK_ANALIZ_{gen:%Y-%m-%d_%H%M}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    print(f"\nRapor: {path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main(sys.argv[1:])))
