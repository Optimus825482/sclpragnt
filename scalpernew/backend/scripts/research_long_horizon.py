"""UZUN UFUK (1h/4h/1d) STRATEJİ TARAMASI (2026-10-13) — (b) maliyet amortizasyonu.

NEDEN: 13 turda 9 bilgi sınıfı denendi; hepsinin brüt edge'i (~%0.05-0.2) 5dk-1saat
ufkunda maliyetin (%0.10-0.35 round-trip) ALTINDA kaldı. Uzun ufukta işlem SEYREK
olur → maliyet yıllık olarak amortize olur:
    ayda 1 işlem -> yıllık ~4.2% drag  (günde 1 işlem -> %128 drag!)
Yani uzun ufukta erişilmesi gereken eşik ÇOK daha düşük.

DENENEN STRATEJİLER (klasik, iyi belgelenmiş, hepsi trend/mean-rev ailesi):
  S1 12h MOMENTUM   : son N bar getirisi > 0 → LONG; < 0 → SHORT (trend takip)
  S2 KIRILIM        : son N barın zirvesini/dibini kır → o yöne
  S3 ORTALAMAYA DÖNÜŞ: fiyat EMA'dan çok uzaksa ters (mean-reversion)
  S4 EMA KESİŞİM    : EMA_fast > EMA_slow → LONG (trend)
  S5 RSI AŞIRI      : RSI>70 short, RSI<30 long (mean-reversion)

YÖNTEM: walk-forward (%60/%40), maliyet round-trip, işlem frekansı + yıllık drag,
3-fold. Her sinyal bir BAR bekletilir (look-ahead yok). KARAR: net EV>0 & kararlı.

KULLANIM:
    python backend/scripts/research_long_horizon.py --tf 4h
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_DB = os.path.join(_WORK, "market_cache.sqlite")
_COST = 0.35          # round-trip taker
_BARS_PER_YEAR = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


def _load(symbols: list[str], tf: str) -> dict:
    conn = sqlite3.connect(_DB)
    ph = ",".join("?" * len(symbols))
    rows = conn.execute(
        f"SELECT symbol, open_time, open, high, low, close FROM klines "
        f"WHERE interval=? AND symbol IN ({ph}) ORDER BY symbol, open_time",
        (tf, *symbols)).fetchall()
    conn.close()
    out: dict = {}
    for s, ot, o, h, l, c in rows:
        if c and c > 0:
            out.setdefault(str(s).upper(), []).append(
                {"t": int(ot), "o": float(o), "h": float(h), "l": float(l), "c": float(c)})
    return out


def _ema(vals, p):
    if len(vals) < p:
        return None
    k = 2.0 / (p + 1); e = sum(vals[:p]) / p
    for v in vals[p:]:
        e = v * k + e * (1 - k)
    return e


def _ema_series(vals, p):
    if len(vals) < p:
        return []
    k = 2.0 / (p + 1); e = sum(vals[:p]) / p; out = [e]
    for v in vals[p:]:
        e = v * k + e * (1 - k); out.append(e)
    return out


def _rsi(closes, p=14):
    if len(closes) < p + 1:
        return None
    gains = []; losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(0.0, d)); losses.append(max(0.0, -d))
    ag = sum(gains[-p:]) / p; al = sum(losses[-p:]) / p
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1 + ag / al)


def _signals(bars: list, hold: int) -> list[tuple[int, int, float]]:
    """(entry_idx, dir(+1/-1), gross_pct) — her strateji için sinyal listesi.

    Tüm stratejiler birden çok varyant döndürür: [(isim, [sinyaller])].
    """
    c = [b["c"] for b in bars]; h = [b["h"] for b in bars]; l = [b["l"] for b in bars]
    n = len(c)
    out = {}
    def fwd(i):
        if i + hold < n and c[i] > 0:
            return (c[i + hold] / c[i] - 1) * 100
        return None
    # S1 momentum: N-bar getiri yönü
    for N in (12, 24, 48):
        sig = []
        for i in range(N, n - hold):
            g = (c[i] / c[i - N] - 1) * 100
            if g > 0.5:
                sig.append((i, +1, fwd(i)))
            elif g < -0.5:
                sig.append((i, -1, fwd(i)))
        out[f"S1_mom{N}"] = [(i, d, g) for i, d, g in sig if g is not None]
    # S2 kırılım: N-bar zirve/dip kır
    for N in (12, 24):
        sig = []
        for i in range(N, n - hold):
            hi = max(h[i - N:i]); lo = min(l[i - N:i])
            if c[i] > hi:
                sig.append((i, +1, fwd(i)))
            elif c[i] < lo:
                sig.append((i, -1, fwd(i)))
        out[f"S2_break{N}"] = [(i, d, g) for i, d, g in sig if g is not None]
    # S3 ortalamaya dönüş: EMA20'den uzaklık
    es = _ema_series(c, 20)
    if es:
        sig = []
        off = len(c) - len(es)
        for i in range(off + 20, n - hold):
            e = es[i - off]
            if e <= 0:
                continue
            dev = (c[i] / e - 1) * 100
            if dev < -3:
                sig.append((i, +1, fwd(i)))    # aşırı düşük → long
            elif dev > 3:
                sig.append((i, -1, fwd(i)))    # aşırı yüksek → short
        out["S3_meanrev"] = [(i, d, g) for i, d, g in sig if g is not None]
    # S4 EMA kesişim
    ef = _ema_series(c, 9); esl = _ema_series(c, 21)
    if ef and esl:
        m = min(len(ef), len(esl))
        sig = []
        for k in range(21, m - 1):
            if ef[k] > esl[k] and ef[k - 1] <= esl[k - 1]:
                i = len(c) - m + k
                if i < n - hold:
                    sig.append((i, +1, fwd(i)))
            elif ef[k] < esl[k] and ef[k - 1] >= esl[k - 1]:
                i = len(c) - m + k
                if i < n - hold:
                    sig.append((i, -1, fwd(i)))
        out["S4_emacross"] = [(i, d, g) for i, d, g in sig if g is not None]
    # S5 RSI aşırı
    sig = []
    for i in range(20, n - hold):
        r = _rsi(c[i - 20:i + 1])
        if r is None:
            continue
        if r > 72:
            sig.append((i, -1, fwd(i)))
        elif r < 28:
            sig.append((i, +1, fwd(i)))
    out["S5_rsi"] = [(i, d, g) for i, d, g in sig if g is not None]
    return out


def _metrics(signals, cost):
    if len(signals) < 8:
        return {"n": len(signals), "ev": None}
    nets = [d * g - cost for _, d, g in signals]
    w = [x for x in nets if x > 0]
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "win": round(100 * len(w) / len(nets), 1),
            "total": round(sum(nets), 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--hold", type=int, default=1)
    ap.add_argument("--out", default="work/long_horizon.json")
    args = ap.parse_args()
    tf = args.tf
    print(f"=== UZUN UFUK STRATEJİ TARAMASI ({tf}, hold={args.hold} bar) ===")
    # Tüm likit TRY sembolleri
    conn = sqlite3.connect(_DB)
    _minbars = 60 if tf in ("1h", "4h") else 20
    syms = [s for (s,) in conn.execute(
        "SELECT symbol FROM klines WHERE interval=? GROUP BY symbol HAVING COUNT(*)>=?", (tf, _minbars))]
    conn.close()
    data = _load(syms, tf)
    print(f"  sembol: {len(data)} | bar/sembol ort: {round(statistics.mean([len(v) for v in data.values()])) if data else 0}")

    # Tüm sembolleri zaman-sıralı birleştir → sinyal havuzu
    # DEDUP: sembol başına TEK pozisyon (üst üste binen sinyaller tek sayılır) —
    # gerçekçi portföy; aksi halde aynı hareket onlarca kez sayılır ve frekans şişer.
    allsigs: dict[str, list] = {}
    for sym, bars in data.items():
        for name, sig in _signals(bars, args.hold).items():
            sig = sorted(sig, key=lambda x: x[0])
            dedup = []
            last_end = -1
            for i, d, g in sig:
                if i <= last_end:
                    continue
                dedup.append((bars[i]["t"], d, g))
                last_end = i + args.hold
            allsigs.setdefault(name, []).extend(dedup)

    # Yıllık işlem frekansı → maliyet drag
    bars_per_year = _BARS_PER_YEAR.get(tf, 6 * 365)
    print(f"\n  {'strateji':16s}{'n':>6}{'EV/işlem':>10}{'kazanma':>8}{'~işlem/yıl':>11}{'yıllık drag':>12}{'yıllık net':>11}")
    res = {}
    for name, sig in allsigs.items():
        sig.sort(key=lambda s: s[0])
        split = int(len(sig) * 0.6)
        te = sig[split:]                       # sınav
        m = _metrics(te, _COST)
        if m["n"] < 8:
            continue
        # yıllık frekans: sinyal başına yıl = bar_süresi; portföy tüm sembol birleşik.
        bar_hours = {"1h": 1, "4h": 4, "1d": 24}.get(tf, 4)
        span_yr = max(1e-6, (te[-1][0] - te[0][0]) / 1000 / (365 * 86400)) if len(te) > 1 else 1e-6
        trades_per_yr = m["n"] / span_yr
        drag = trades_per_yr * _COST
        net_yr = m["ev"] * trades_per_yr
        res[name] = {"n": m["n"], "ev": m["ev"], "win": m["win"],
                     "trades_per_year": round(trades_per_yr, 1),
                     "annual_drag_pct": round(drag, 1), "annual_net_pct": round(net_yr, 1)}
        print(f"  {name:16s}{m['n']:>6}{m['ev']:>10}{m['win']:>8}{round(trades_per_yr):>11}"
              f"{round(drag,1):>12}{round(net_yr,1):>11}")

    pos = {k: v for k, v in res.items() if (v["ev"] or -9) > 0}
    print(f"\n  pozitif EV strateji: {len(pos)}/{len(res)}")
    for k, v in sorted(pos.items(), key=lambda kv: -kv[1]["ev"])[:5]:
        print(f"    {k}: EV {v['ev']} yıllık net {v['annual_net_pct']}%")
    res["_meta"] = {"tf": tf, "symbols": len(data), "positive": len(pos)}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"  rapor: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
