"""TRADINGVIEW POPÜLER MEKANİZMALARI — KENDİ HARNESS'İMİZDEN (2026-10-13).

NEDEN: Kullanıcı TradingView public stratejilerinin (buy/sell sinyali üreten popüler
scriptler) sinyalini buraya bağlamayı sordu. Değerlendirme: "popüler ve kârlı" bir liste
YOKTUR; popüler scriptler 5-6 mekanizmanın karışımıdır. Onların kodunu KOPYALAMADAN,
mekanizma ailelerini KENDİ dürüst harness'imizden geçiririz (TV = fikir kataloğu).

ÖLÇÜLEN 6 MEKANİZMA (TV'de en çok kopyalanan aileler):
  M1 ema_cross      : EMA_fast/EMA_slow kesişimi (trend-follow)
  M2 macd_rsi       : MACD sinyal kesişimi + RSI onayı (trend/momentum)  [TV "MACD+RSI 1H"]
  M3 supertrend     : ATR trailing band flip (trend-follow)             [TV en popüler]
  M4 donchian_break : N-bar zirve/dip kırılımı (breakout)
  M5 rsi_bb_meanrev : RSI aşırı + Bollinger (mean-reversion)
  M6 confluence     : RSI+MACD+BB+W%R ≥2 uyumlu (multi-indicator)       [TV "Min 2/4"]

HARNESS (proje standardı):
  * LOOK-AHEAD YOK: sinyal bar i KAPANIŞINDA karar → GİRİŞ ertesi bar AÇILIŞI (i+1).
  * DEDUP: sembol başına aynı anda TEK pozisyon (üst üste binen sinyal tek sayılır).
  * Walk-forward 5-fold + rastgele-kontrol (aynı sayıda rastgele giriş) + maliyet duyarlılığı.
  * LONG/SHORT ayrımı (TRY spot long-only olduğu için long-only kritik).

KULLANIM:
    python backend/scripts/research_tv_mechanisms.py --tf 1h
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")

_WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work")
_DB = os.path.join(_WORK, "market_cache.sqlite")
_COST = 0.35  # round-trip taker (proje standardı)


def _load(tf: str, min_bars: int) -> dict:
    conn = sqlite3.connect(_DB)
    syms = [s for (s,) in conn.execute(
        "SELECT symbol FROM klines WHERE interval=? AND symbol LIKE '%TRY' "
        "GROUP BY symbol HAVING COUNT(*)>=?", (tf, min_bars))]
    ph = ",".join("?" * len(syms))
    rows = conn.execute(
        f"SELECT symbol, open_time, open, high, low, close FROM klines "
        f"WHERE interval=? AND symbol IN ({ph}) ORDER BY symbol, open_time",
        (tf, *syms)).fetchall()
    conn.close()
    out: dict = {}
    for s, ot, o, h, l, c in rows:
        if c and c > 0 and o and o > 0:
            out.setdefault(str(s).upper(), []).append(
                {"t": int(ot), "o": float(o), "h": float(h), "l": float(l), "c": float(c)})
    return {k: v for k, v in out.items() if len(v) >= min_bars}


# ---------- indikatörler (saf, look-ahead yok) ----------
def _ema_series(vals, p):
    if len(vals) < p:
        return [None] * len(vals)
    k = 2.0 / (p + 1); e = sum(vals[:p]) / p
    out = [None] * (p - 1) + [e]
    for v in vals[p:]:
        e = v * k + e * (1 - k); out.append(e)
    return out


def _rsi_series(closes, p=14):
    out = [None] * len(closes)
    if len(closes) < p + 1:
        return out
    gains = losses = 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = max(0.0, d); l = max(0.0, -d)
        if i <= p:
            gains += g; losses += l
            if i == p:
                ag = gains / p; al = losses / p
                out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
        else:
            ag = (ag * (p - 1) + g) / p; al = (al * (p - 1) + l) / p
            out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    return out


def _macd_series(closes, f=12, s=26, sig=9):
    ef = _ema_series(closes, f); esv = _ema_series(closes, s)
    macd = [None if (a is None or b is None) else a - b for a, b in zip(ef, esv)]
    valid = [x for x in macd if x is not None]
    if len(valid) < sig:
        return macd, [None] * len(closes)
    sig_line = [None] * len(closes)
    k = 2.0 / (sig + 1); e = sum(valid[:sig]) / sig
    start = len(closes) - len(valid) + sig - 1
    sig_line[start] = e
    for idx in range(start + 1, len(closes)):
        e = macd[idx] * k + e * (1 - k); sig_line[idx] = e
    return macd, sig_line


def _atr_series(bars, p=14):
    out = [None] * len(bars)
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["h"] - b["l"])
        else:
            pc = bars[i - 1]["c"]
            trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    if len(bars) < p:
        return out
    a = sum(trs[:p]) / p; out[p - 1] = a
    for i in range(p, len(bars)):
        a = (a * (p - 1) + trs[i]) / p; out[i] = a
    return out


def _bb_series(closes, p=20, mult=2.0):
    up = [None] * len(closes); lo = [None] * len(closes)
    for i in range(p - 1, len(closes)):
        w = closes[i - p + 1:i + 1]
        m = sum(w) / p
        sd = (sum((x - m) ** 2 for x in w) / p) ** 0.5
        up[i] = m + mult * sd; lo[i] = m - mult * sd
    return up, lo


def _williams_r(bars, p=14):
    out = [None] * len(bars)
    for i in range(p - 1, len(bars)):
        w = bars[i - p + 1:i + 1]
        hh = max(b["h"] for b in w); ll = min(b["l"] for b in w)
        out[i] = -100.0 if hh == ll else (hh - bars[i]["c"]) / (hh - ll) * -100.0
    return out


# ---------- mekanizmalar: (timestamp, dir) listesi; karar bar i kapanışı ----------
def mech_signals(name: str, bars: list) -> list[tuple[int, int]]:
    c = [b["c"] for b in bars]
    n = len(c)
    sig: list[tuple[int, int]] = []

    if name == "M1_ema_cross":
        ef = _ema_series(c, 9); es = _ema_series(c, 21)
        for i in range(1, n):
            if None in (ef[i], es[i], ef[i - 1], es[i - 1]):
                continue
            if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
                sig.append((i, +1))
            elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
                sig.append((i, -1))

    elif name == "M2_macd_rsi":
        macd, sline = _macd_series(c)
        rsi = _rsi_series(c, 14)
        for i in range(1, n):
            if None in (macd[i], sline[i], macd[i - 1], sline[i - 1], rsi[i]):
                continue
            if macd[i] > sline[i] and macd[i - 1] <= sline[i - 1] and rsi[i] < 60:
                sig.append((i, +1))
            elif macd[i] < sline[i] and macd[i - 1] >= sline[i - 1] and rsi[i] > 40:
                sig.append((i, -1))

    elif name == "M3_supertrend":
        atr = _atr_series(bars, 10); mult = 3.0
        upper = lower = None; trend = 0
        for i in range(n):
            if atr[i] is None:
                continue
            mid = (bars[i]["h"] + bars[i]["l"]) / 2
            ub = mid + mult * atr[i]; lb = mid - mult * atr[i]
            if upper is None:
                upper, lower = ub, lb; continue
            upper = ub if (ub < upper or c[i - 1] > upper) else upper
            lower = lb if (lb > lower or c[i - 1] < lower) else lower
            new_trend = trend
            if trend <= 0 and c[i] > upper:
                new_trend = 1
            elif trend >= 0 and c[i] < lower:
                new_trend = -1
            if new_trend != 0 and new_trend != trend:
                sig.append((i, new_trend))
            trend = new_trend

    elif name == "M4_donchian_break":
        N = 24
        for i in range(N, n):
            hi = max(b["h"] for b in bars[i - N:i]); lo = min(b["l"] for b in bars[i - N:i])
            if c[i] > hi:
                sig.append((i, +1))
            elif c[i] < lo:
                sig.append((i, -1))

    elif name == "M5_rsi_bb_meanrev":
        rsi = _rsi_series(c, 14); up, lo = _bb_series(c, 20, 2.0)
        for i in range(n):
            if None in (rsi[i], up[i], lo[i]):
                continue
            if rsi[i] < 30 and c[i] <= lo[i]:
                sig.append((i, +1))
            elif rsi[i] > 70 and c[i] >= up[i]:
                sig.append((i, -1))

    elif name == "M6_confluence":
        rsi = _rsi_series(c, 14); macd, sline = _macd_series(c)
        up, lo = _bb_series(c, 20, 2.0); wr = _williams_r(bars, 14)
        for i in range(n):
            if None in (rsi[i], macd[i], sline[i], up[i], lo[i], wr[i]):
                continue
            bull = ((1 if rsi[i] < 50 else 0) + (1 if macd[i] > sline[i] else 0)
                    + (1 if c[i] < (up[i] + lo[i]) / 2 else 0) + (1 if wr[i] > -50 else 0))
            bear = ((1 if rsi[i] > 50 else 0) + (1 if macd[i] < sline[i] else 0)
                    + (1 if c[i] > (up[i] + lo[i]) / 2 else 0) + (1 if wr[i] < -50 else 0))
            if bull >= 3:
                sig.append((i, +1))
            elif bear >= 3:
                sig.append((i, -1))
    return sig


def _realize(bars, sig, hold):
    """LOOK-AHEAD YOK: karar bar i kapanışı → giriş bar i+1 AÇILIŞI, hold bar sonra açılış."""
    n = len(bars)
    out = []
    for i, d in sig:
        e = i + 1
        x = e + hold
        if x >= n:
            continue
        p0 = bars[e]["o"]; p1 = bars[x]["o"]
        if p0 > 0:
            out.append((bars[e]["t"], d, (p1 / p0 - 1) * 100))
    return out


def _dedup_by_time(sig_rows, hold, bar_ms):
    """Sembol başına tek pozisyon: bir pozisyon açıkken yeni sinyal sayılmaz."""
    out = []; last_end = -1
    for t, d, g in sorted(sig_rows, key=lambda r: r[0]):
        if t <= last_end:
            continue
        out.append((t, d, g)); last_end = t + hold * bar_ms
    return out


def _metrics(rows, cost, long_only=False, two_leg_per_dir=False):
    if long_only:
        rows = [r for r in rows if r[1] == +1]
    if not rows:
        return {"n": 0}
    cop = cost * (2 if two_leg_per_dir else 1)
    nets = [d * g - cop for _, d, g in rows]
    w = [x for x in nets if x > 0]
    return {"n": len(nets), "ev": round(statistics.mean(nets), 3),
            "win": round(100 * len(w) / len(nets), 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--hold", type=int, default=12)
    ap.add_argument("--minbars", type=int, default=200)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    tf = args.tf
    out_path = args.out or f"work/tv_mech_{tf}.json"
    print(f"=== TRADINGVIEW MEKANİZMA HARNESS ({tf}, hold={args.hold}, maliyet {_COST}) ===")
    data = _load(tf, args.minbars)
    print(f"  sembol: {len(data)} | ort bar: {round(statistics.mean([len(v) for v in data.values()]))}")

    names = ["M1_ema_cross", "M2_macd_rsi", "M3_supertrend",
             "M4_donchian_break", "M5_rsi_bb_meanrev", "M6_confluence"]
    bar_ms = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}.get(tf, 3_600_000)
    pool: dict[str, list] = {}
    for sym, bars in data.items():
        for nm in names:
            realized = _realize(bars, mech_signals(nm, bars), args.hold)
            pool.setdefault(nm, []).extend(_dedup_by_time(realized, args.hold, bar_ms))

    hdr = f"  {'mekanizma':20s}{'n':>6}{'EV/her':>9}{'win':>7}{'LO n':>7}{'LO EV':>8}{'5-fold (net)':>28}"
    print("\n  (LO=long-only; EV maliyet sonrası, tek bacak)")
    print(hdr)
    res: dict = {}
    rnd = random.Random(3)
    for nm in names:
        rows = sorted(pool[nm], key=lambda r: r[0])
        m_all = _metrics(rows, _COST)
        m_lo = _metrics(rows, _COST, long_only=True)
        if m_all["n"] < 10:
            print(f"  {nm:20s}  — az sinyal ({m_all['n']})")
            continue
        nets = [d * g - _COST for _, d, g in rows]
        nf = 5
        folds = [round(statistics.mean(nets[int(len(nets)*k/nf):int(len(nets)*(k+1)/nf)]), 2)
                 for k in range(nf)]
        pos = sum(1 for f in folds if f > 0)
        # rastgele-kontrol: aynı sayıda rastgele giriş (yön rastgele), maliyetsiz fark için
        ctrl = []
        for _ in range(m_all["n"]):
            r = data[rnd.choice(list(data.keys()))]
            if len(r) < args.hold + 2:
                continue
            i = rnd.randrange(1, len(r) - args.hold - 1)
            d = rnd.choice([+1, -1])
            g = (r[i+args.hold]["o"] / r[i]["o"] - 1) * 100
            ctrl.append((0, d, g))
        ctrl_ev = round(statistics.mean([d*g for _, d, g in ctrl]), 3) if ctrl else 0.0
        diff = round(m_all["ev"] - ctrl_ev, 3)
        res[nm] = {"n": m_all["n"], "ev": m_all["ev"], "win": m_all["win"],
                   "lo_n": m_lo.get("n"), "lo_ev": m_lo.get("ev"),
                   "folds": folds, "pos_folds": pos, "ctrl_ev": ctrl_ev, "diff_vs_ctrl": diff}
        print(f"  {nm:20s}{m_all['n']:>6}{m_all['ev']:>9}{m_all['win']:>7}"
              f"{(m_lo.get('n') or 0):>7}{(m_lo.get('ev') if m_lo.get('ev') is not None else 0):>8}"
              f"   {folds} {pos}/5")

    # maliyet duyarlılığı (tüm mekanizmalar, long-only)
    print("\n  == MALİYET DUYARLILIĞI (long-only EV) ==")
    print(f"  {'mekanizma':20s}{'c=0':>9}{'c=0.10':>9}{'c=0.20':>9}{'c=0.35':>9}")
    for nm in names:
        rows = [r for r in pool.get(nm, []) if r[1] == +1]
        if len(rows) < 10:
            continue
        evs = []
        for c in (0.0, 0.10, 0.20, 0.35):
            evs.append(round(statistics.mean([d*g - c for _, d, g in rows]), 3))
        print(f"  {nm:20s}" + "".join(f"{e:>9}" for e in evs))
        res.setdefault(nm, {})["cost_curve_lo"] = evs

    res["_meta"] = {"tf": tf, "hold": args.hold, "symbols": len(data), "cost": _COST}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"\n  rapor: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
