"""M1 pre-attack forensics with a wide indicator vector (from the TradingView
guide) vs matched non-attack control windows on the same symbols.

For every detected >=2% M5 attack (last 2h), computes ~25 indicator values on
the 5 closed M1 bars BEFORE the attack candle, then samples control windows
(same symbol, no +1% move in the following 5 minutes) and ranks metrics by
separation (Cohen's d + conditional hit-rate lift). Pure research, read-only.
"""
import asyncio
import json
import math
import sys
import os
from datetime import datetime
from statistics import mean, median

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.binance_tr_public import trading_symbols, klines

MIN_ATTACK_PCT = 2.0
SCAN_HOURS = 2
PRE_BARS = 5


def f(vals):
    return [float(v) for v in vals]


def sma(vals, n):
    if len(vals) < n: return None
    return sum(vals[-n:]) / n


def ema(vals, n):
    if len(vals) < n: return None
    k = 2 / (n + 1); e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, n=14):
    if len(closes) < n + 1: return None
    gains, losses = [], []
    for i in range(len(closes) - n, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(0, d)); losses.append(max(0, -d))
    ag, al = mean(gains), mean(losses)
    return 100 - 100 / (1 + ag / al) if al else 100.0


def true_ranges(highs, lows, closes):
    return [max(h - l, abs(h - pc), abs(l - pc)) for h, l, pc in zip(highs[1:], lows[1:], closes[:-1])]


def atr_pct(highs, lows, closes, n=14):
    trs = true_ranges(highs, lows, closes)
    if len(trs) < n: return None
    return mean(trs[-n:]) / closes[-1] * 100 if closes[-1] else None


def mfi(highs, lows, closes, vols, n=14):
    if len(closes) < n + 1: return None
    pos, neg = 0.0, 0.0
    for i in range(len(closes) - n, len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        ptp = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3
        flow = tp * vols[i]
        if tp > ptp: pos += flow
        elif tp < ptp: neg += flow
    return 100 - 100 / (1 + pos / neg) if neg else 100.0


def cmo(closes, n=9):
    if len(closes) < n + 1: return None
    ups, downs = [], []
    for i in range(len(closes) - n, len(closes)):
        d = closes[i] - closes[i - 1]
        ups.append(max(0, d)); downs.append(max(0, -d))
    su, sd = sum(ups), sum(downs)
    return (su - sd) / (su + sd) * 100 if (su + sd) else 0.0


def stochastic(highs, lows, closes, n=14):
    if len(closes) < n: return None
    hh, ll = max(highs[-n:]), min(lows[-n:])
    if hh == ll: return None
    return (closes[-1] - ll) / (hh - ll) * 100


def cci(highs, lows, closes, n=20):
    if len(closes) < n: return None
    tps = [(h + l + c) / 3 for h, l, c in zip(highs[-n:], lows[-n:], closes[-n:])]
    m = mean(tps)
    md = mean(abs(tp - m) for tp in tps)
    return (tps[-1] - m) / (0.015 * md) if md else 0.0


def trix(closes, n=15):
    if len(closes) < 3 * n + 2: return None
    def ema_series(vals, k):
        out, e = [], sum(vals[:k]) / k
        out.append(e)
        alpha = 2 / (k + 1)
        for v in vals[k:]:
            e = v * alpha + e * (1 - alpha); out.append(e)
        return out
    e1 = ema_series(closes, n); e2 = ema_series(e1, n); e3 = ema_series(e2, n)
    return (e3[-1] / e3[-2] - 1) * 100 if e3[-2] else None


def tsi(closes, long=25, short=13):
    if len(closes) < long + short + 2: return None
    mom = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    def d_ema(vals, k):
        alpha = 2 / (k + 1)
        e1 = vals[0]; out = [e1]
        for v in vals[1:]:
            e1 = v * alpha + e1 * (1 - alpha); out.append(e1)
        alpha2 = 2 / (short + 1)
        e2 = out[0]; out2 = [e2]
        for v in out[1:]:
            e2 = v * alpha2 + e2 * (1 - alpha2); out2.append(e2)
        return out2
    num = d_ema(mom, long); den = d_ema([abs(m) for m in mom], long)
    return 100 * num[-1] / den[-1] if den[-1] else None


def obv_slope_pct(highs, lows, closes, vols, bars=5):
    if len(closes) < bars + 1: return None
    obv = [0.0]
    for i in range(1, len(closes)):
        obv.append(obv[-1] + (vols[i] if closes[i] > closes[i - 1] else -vols[i] if closes[i] < closes[i - 1] else 0))
    avg_vol = mean(vols[-20:])
    return (obv[-1] - obv[-bars - 1]) / (avg_vol * bars) if avg_vol else None


def vwap_dist(highs, lows, closes, vols, n=20):
    if len(closes) < n: return None
    tpv = sum((h + l + c) / 3 * v for h, l, c, v in zip(highs[-n:], lows[-n:], closes[-n:], vols[-n:]))
    vv = sum(vols[-n:])
    return (closes[-1] - tpv / vv) / (tpv / vv) * 100 if vv and tpv else None


def bollinger(closes, n=20, mult=2.0):
    if len(closes) < n: return None, None
    m = mean(closes[-n:])
    sd = (sum((c - m) ** 2 for c in closes[-n:]) / n) ** 0.5
    upper, lower = m + mult * sd, m - mult * sd
    pb = (closes[-1] - lower) / (upper - lower) if upper != lower else 0.5
    width = (upper - lower) / m * 100 if m else None
    return pb, width


def choppiness(highs, lows, closes, n=14):
    if len(closes) < n + 1: return None
    trs = true_ranges(highs, lows, closes)[-n:]
    hh, ll = max(highs[-n:]), min(lows[-n:])
    if hh == ll or sum(trs) == 0: return None
    return 100 * math.log10(sum(trs) / (hh - ll)) / math.log10(n)


def linreg_slope_pct(closes, n=20):
    if len(closes) < n: return None
    xs = list(range(n)); ys = closes[-n:]
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den else 0
    return slope / my * 100 * 10 if my else None  # 10-bar projectable %


def vortex(highs, lows, closes, n=14):
    if len(closes) < n + 1: return None
    trs, vp, vm = [], [], []
    for i in range(len(closes) - n, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
        vp.append(abs(highs[i] - lows[i - 1])); vm.append(abs(lows[i] - highs[i - 1]))
    st = sum(trs)
    return (sum(vp) / st, sum(vm) / st) if st else None


def supertrend_dir(highs, lows, closes, n=10, mult=3.0):
    trs = true_ranges(highs, lows, closes)
    if len(trs) < n: return None
    atr = mean(trs[-n:])
    mid = (highs[-1] + lows[-1]) / 2
    # son bar yönü: kapanış, band merkezine göre + trend kabası (basitleştirilmiş)
    return 1 if closes[-1] > mid else -1


def aroon_osc(highs, lows, n=25):
    if len(highs) < n + 1: return None
    hwin, lwin = highs[-(n + 1):], lows[-(n + 1):]
    up = (n - (len(hwin) - 1 - hwin.index(max(hwin)))) / n * 100
    dn = (n - (len(lwin) - 1 - lwin.index(min(lwin)))) / n * 100
    return up - dn


def td_seq_proxy(closes):
    if len(closes) < 5: return None, None
    bull = 0; i = len(closes) - 1
    while i > 0 and closes[i] > closes[i - 1] and bull < 9:
        bull += 1; i -= 1
    bear = 0; i = len(closes) - 1
    while i > 0 and closes[i] < closes[i - 1] and bear < 9:
        bear += 1; i -= 1
    return bull, bear


def hull_slope_pct(closes, n=9):
    if len(closes) < n + 2: return None
    half = max(2, n // 2)
    w1 = [2 * c for c in closes[-half:]]; w2 = closes[-n:]
    raw = mean(w1) - mean(w2)
    # kaba eğim: son iki raw değeri
    w1b = [2 * c for c in closes[-half - 1:-1]]; w2b = closes[-n - 1:-1]
    raw_b = mean(w1b) - mean(w2b)
    return (raw - raw_b) / closes[-1] * 100 if closes[-1] else None


def elder_force_norm(closes, vols, n=13):
    if len(closes) < n + 1: return None
    efs = [(closes[i] - closes[i - 1]) * vols[i] for i in range(len(closes) - n, len(closes))]
    norm = mean(vols[-n:]) * closes[-1]
    return mean(efs) / norm if norm else None


def volume_oscillator(vols, fast=5, slow=20):
    if len(vols) < slow: return None
    sf, ss = mean(vols[-fast:]), mean(vols[-slow:])
    return (sf - ss) / ss * 100 if ss else None


def vwma_sma_gap(closes, vols, n=20):
    if len(closes) < n: return None
    vw = sum(c * v for c, v in zip(closes[-n:], vols[-n:])) / sum(vols[-n:])
    sm = mean(closes[-n:])
    return (vw - sm) / sm * 100 if sm else None


def taker_delta(rows, n=5):
    if len(rows) < n: return None
    ds = []
    for r in rows[-n:]:
        vol, tb = float(r[5]), float(r[9]) if len(r) > 9 else None
        if vol and tb is not None:
            ds.append(2 * tb / vol - 1)
    return mean(ds) if ds else None


def rich_vector(rows, decision_index):
    """decision_index: bu bar KAPANMIŞ; sonraki 5 bar atak penceresi."""
    window = rows[:decision_index + 1]
    highs = f([r[2] for r in window]); lows = f([r[3] for r in window])
    closes = f([r[4] for r in window]); vols = f([r[5] for r in window])
    vec = {}
    vec["rsi14"] = rsi(closes)
    vec["mfi14"] = mfi(highs, lows, closes, vols)
    vec["cmo9"] = cmo(closes)
    k = stochastic(highs, lows, closes)
    vec["stoch_k"] = k
    vec["williams_r"] = k - 100 if k is not None else None
    vec["cci20"] = cci(highs, lows, closes)
    vec["trix15"] = trix(closes)
    vec["tsi"] = tsi(closes)
    vec["obv_slope5"] = obv_slope_pct(highs, lows, closes, vols)
    vec["vwap_dist20_pct"] = vwap_dist(highs, lows, closes, vols)
    pb, bw = bollinger(closes)
    vec["bollinger_pb"] = pb; vec["bollinger_width_pct"] = bw
    vec["choppiness14"] = choppiness(highs, lows, closes)
    vec["roc5_pct"] = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else None
    vec["elder_force_norm"] = elder_force_norm(closes, vols)
    vec["volume_osc"] = volume_oscillator(vols)
    vec["vwma_sma_gap_pct"] = vwma_sma_gap(closes, vols)
    vec["hull_slope_pct"] = hull_slope_pct(closes)
    vec["linreg_slope10_pct"] = linreg_slope_pct(closes)
    vx = vortex(highs, lows, closes)
    vec["vortex_plus_minus"] = (vx[0] - vx[1]) if vx else None
    vec["supertrend_dir"] = supertrend_dir(highs, lows, closes)
    vec["aroon_osc"] = aroon_osc(highs, lows)
    bull, bear = td_seq_proxy(closes)
    vec["td_bull_count"] = bull; vec["td_bear_count"] = bear
    vec["taker_delta5"] = taker_delta(window)
    vec["atr14_pct"] = atr_pct(highs, lows, closes)
    vec["ret5_pct"] = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else None
    return vec


def next5_max_high_pct(rows, i):
    """i kapanmış; sonraki 5 barda yükseklik, i kapanışına göre max %."""
    if i + 5 >= len(rows): return None
    base = float(rows[i][4])
    if base <= 0: return None
    return (max(float(r[2]) for r in rows[i + 1:i + 6]) / base - 1) * 100


async def main():
    symbols = await trading_symbols("TRY")
    print(f"{len(symbols)} sembolde M5 taraması…", flush=True)
    sem = asyncio.Semaphore(8)
    attacks = []

    async def scan(symbol):
        async with sem:
            try:
                rows = await klines(symbol, "5m", 27)
            except Exception:
                return
            if len(rows) < 10: return
            cutoff = int(rows[-1][0]) - SCAN_HOURS * 3_600_000
            for i in range(1, len(rows)):
                if int(rows[i][0]) < cutoff: continue
                ch = (float(rows[i][4]) / float(rows[i - 1][4]) - 1) * 100
                if ch >= MIN_ATTACK_PCT:
                    attacks.append({"symbol": symbol, "attack_open_ms": int(rows[i][0]), "change": round(ch, 2)})

    await asyncio.gather(*(scan(s) for s in symbols))
    attacks.sort(key=lambda a: a["attack_open_ms"])
    print(f"atak: {len(attacks)} → {len({a['symbol'] for a in attacks})} sembol", flush=True)

    # M1 geçmişi sembol başına tek seferde (1 gün)
    m1_cache = {}
    sem1 = asyncio.Semaphore(6)
    async def load_m1(symbol):
        async with sem1:
            try:
                m1_cache[symbol] = await klines(symbol, "1m", 1000)
            except Exception:
                m1_cache[symbol] = []

    await asyncio.gather(*(load_m1({a['symbol'] for a in attacks}.pop()) for _ in []) ) if False else \
        await asyncio.gather(*(load_m1(s) for s in {a['symbol'] for a in attacks}))

    hits, controls = [], []
    for a in attacks:
        rows = m1_cache.get(a["symbol"]) or []
        # atak başlangıcından önce kapanmış barları bul
        pre_idx = [i for i, r in enumerate(rows) if int(r[0]) + 59_999 <= a["attack_open_ms"] - 300_000 + 59_999]
        # atak M5 mumunun AÇILIŞINDAN hemen önceki kapanmış M1 barı
        pre_idx = [i for i, r in enumerate(rows) if int(r[0]) + 59_999 <= a["attack_open_ms"] - 1]
        if not pre_idx or len(pre_idx) < 45:
            continue
        di = pre_idx[-1]
        # M1 penceresi atak M5 mumunu kapsamalı (sonraki 5 bar atakla çakışmalı)
        vec = rich_vector(rows, di)
        vec["nxt5"] = next5_max_high_pct(rows, di)
        hits.append({"symbol": a["symbol"], "attack_time": datetime.fromtimestamp(a["attack_open_ms"] / 1000).strftime("%H:%M"),
                     "change": a["change"], "vec": vec})
        # kontroller: aynı sembolde sonraki 5 dk < %1 hareket
        count = 0
        for i in range(40, len(rows) - 6):
            if count >= 6: break
            if i > di - 30 and i < di + 30: continue  # atak çevresini dışla
            mx = next5_max_high_pct(rows, i)
            if mx is None or mx >= 1.0: continue
            cvec = rich_vector(rows, i)
            cvec["nxt5"] = mx
            controls.append({"symbol": a["symbol"], "vec": cvec})
            count += 1

    print(f"hit: {len(hits)} | kontrol: {len(controls)}")
    if not hits or not controls:
        print("yeterli veri yok"); return

    # ayırt edicilik: Cohen d + koşullu oran
    report = []
    keys = list(hits[0]["vec"].keys())
    for key in keys:
        hv = [h["vec"].get(key) for h in hits if isinstance(h["vec"].get(key), (int, float))]
        cv = [c["vec"].get(key) for c in controls if isinstance(c["vec"].get(key), (int, float))]
        if len(hv) < 3 or len(cv) < 5: continue
        mh, mc = mean(hv), mean(cv)
        sd = (sum((x - mc) ** 2 for x in cv) / len(cv)) ** 0.5 or 1e-9
        d = (mh - mc) / sd
        report.append({"metric": key, "hit_mean": round(mh, 3), "ctrl_mean": round(mc, 3), "d": round(d, 2)})
    report.sort(key=lambda r: -abs(r["d"]))

    print("\n=== AYIRT EDİCİLİK SIRALAMASI (|Cohen d| — pozitif d: atak öncesi daha yüksek) ===")
    for r in report:
        print(f"  {r['metric']:20} hit {r['hit_mean']:+9.2f}  ctrl {r['ctrl_mean']:+9.2f}  d={r['d']:+.2f}")

    out = {"generated_at": datetime.now().isoformat(), "hits": hits, "controls": len(controls), "ranking": report}
    with open("../work/m1_indicator_forensics.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, default=str, indent=1)
    print("\nDetay: work/m1_indicator_forensics.json")


if __name__ == "__main__":
    asyncio.run(main())
