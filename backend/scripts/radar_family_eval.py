"""Sclpragnt RADAR stratejilerinin 14 günlük gerçek veriyle ölçümü.

Neden bu betik: radar 8 kaynağı birleştirir (velocity 5/15/30/60dk, günlük
momentum, short-squeeze, rising, pulse, snapback). Hepsi CANLI yayında
çalışıyor ama toplu ve dürüst bir ölçüm yok. Bu betik her aileyi gerçek 1m
mumlar üzerinde yeniden kurar ve aynı çıkış kurallarıyla karşılaştırır.

Kaynak mantıkları (kod okunarak çıkarıldı):
  velocity   : app/routers/velocity.py  VELOCITY_PROFILES (5dk %2 / 15dk %3)
  rising     : app/rising_signals.py    KDJ dip, SuperTrend, EMA50 bounce
  momentum   : monitoring._daily_momentum_candidates (daily_momentum_ok)
  pulse      : early_discovery.top_candidates (1dk getiri + hacim patlaması)

Çıkış modeli: sabit TP/SL (radarın hedef yüzdesi) + azami tutma.
Maliyet: %0.15 round-trip (BNB indirimli).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict

import numpy as np

DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"
FEE = 0.15
GENESIS = 'postgresql://postgres:518518Erkan@localhost:5432/scalper_global'


# ─── gösterge yardımcıları (vektörel) ────────────────────────────────────────

def ema(a: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(a), np.nan)
    if len(a) == 0:
        return out
    k = 2.0 / (p + 1.0)
    prev = a[0]
    for i in range(len(a)):
        prev = a[i] if i == 0 else a[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(a: np.ndarray, p: int = 14) -> np.ndarray:
    n = len(a)
    out = np.full(n, np.nan)
    if n < p + 1:
        return out
    d = np.diff(a)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = gain[:p].mean()
    al = loss[:p].mean()
    out[p] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
    for i in range(p, len(d)):
        ag = (ag * (p - 1) + gain[i]) / p
        al = (al * (p - 1) + loss[i]) / p
        out[i + 1] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
    return out


def kdj(H, L, C, period=9, signal=3):
    n = len(C)
    k = np.full(n, 50.0)
    d = np.full(n, 50.0)
    for i in range(period, n):
        lo = L[i - period + 1:i + 1].min()
        hi = H[i - period + 1:i + 1].max()
        rng = hi - lo
        rsv = (C[i] - lo) / rng * 100.0 if rng > 0 else 50.0
        k[i] = k[i - 1] + (1.0 / signal) * (rsv - k[i - 1])
        d[i] = d[i - 1] + (1.0 / signal) * (k[i] - d[i - 1])
    j = 3 * k - 2 * d
    return k, d, j


def atr(H, L, C, p=14):
    n = len(C)
    out = np.full(n, np.nan)
    if n < p + 1:
        return out
    tr = np.maximum(H[1:] - L[1:], np.maximum(np.abs(H[1:] - C[:-1]), np.abs(L[1:] - C[:-1])))
    v = tr[:p].mean()
    out[p] = v
    for i in range(p, len(tr)):
        v = (v * (p - 1) + tr[i]) / p
        out[i + 1] = v
    return out


def supertrend_bull(H, L, C, period=10, factor=3.0):
    n = len(C)
    a = atr(H, L, C, period)
    bull = np.zeros(n, dtype=bool)
    d = 1
    for i in range(period + 1, n):
        if np.isnan(a[i]):
            continue
        up = (H[i] + L[i]) / 2 + factor * a[i]
        dn = (H[i] + L[i]) / 2 - factor * a[i]
        if C[i] > up:
            d = 1
        elif C[i] < dn:
            d = -1
        bull[i] = d > 0
    return bull


# ─── simülasyon ──────────────────────────────────────────────────────────────

def simulate(entry_idx, entry, H, L, C, tp_pct, sl_pct, max_bars, fee=FEE):
    """Sabit TP/SL + azami tutma. Tek işlem net % getiri döndürür."""
    tp = entry * (1 + tp_pct / 100.0)
    sl = entry * (1 - sl_pct / 100.0)
    n = min(len(C) - entry_idx - 1, max_bars)
    if n <= 0:
        return None
    for k in range(1, n + 1):
        i = entry_idx + k
        # Muhafazakâr: aynı barda ikisi de görüldüyse SL kazanır
        if L[i] <= sl:
            return -sl_pct - fee
        if H[i] >= tp:
            return tp_pct - fee
    return (C[entry_idx + n] - entry) / entry * 100.0 - fee


# ─── takipçi çıkış (globall spot_monitor ile aynı kurallar) ──────────────────
TRAIL_ACTIVATE = 1.5   # kâr %1.5'e ulaşınca takipçi devreye girer
TRAIL_LOCK = 0.8       # o anda stop maliyet + %0.8'e kilitlenir
TRAIL_DISTANCE = 0.6   # sonrasında zirvenin %0.6 gerisinden gelir


def simulate_trail(entry_idx, entry, H, L, C, sl_pct, max_bars, fee=FEE):
    """Zirve takipçi stop. TP YOK — kâr sınırsız, kayıp tanımlı.

    Globall'daki ölçüm: takipçi, sabit TP/SL'den +0.07..+0.17 puan iyi.
    Burada aynı kurallar 1m veriye uygulanıyor.
    """
    stop = entry * (1 - sl_pct / 100.0)
    peak = entry
    trail = False
    n = min(len(C) - entry_idx - 1, max_bars)
    if n <= 0:
        return None
    for k in range(1, n + 1):
        i = entry_idx + k
        hi, lo = H[i], L[i]
        if hi > peak:
            peak = hi
        if not trail and (peak - entry) / entry * 100.0 >= TRAIL_ACTIVATE:
            trail = True
        if trail:
            stop = max(stop,
                       entry * (1 + TRAIL_LOCK / 100.0),
                       peak * (1 - TRAIL_DISTANCE / 100.0))
        if lo <= stop:
            # Dolum stop fiyatından (gap ölçülmedi; muhafazakâr değil ama
            # 1m barlarda gap küçük ve iki modelde de aynı varsayım)
            return (stop - entry) / entry * 100.0 - fee
    return (C[entry_idx + n] - entry) / entry * 100.0 - fee


def agg(results):
    a = np.asarray([r for r in results if r is not None], dtype=float)
    if len(a) == 0:
        return None
    g = a[a > 0].sum()
    ls = -a[a <= 0].sum()
    sd = a.std(ddof=1) if len(a) > 1 else 0.0
    return {
        "n": len(a), "wr": (a > 0).mean() * 100,
        "pf": (g / ls) if ls > 0 else float("inf"),
        "avg": a.mean(), "total": a.sum(),
        "tstat": (a.mean() / (sd / np.sqrt(len(a)))) if sd > 0 and len(a) > 1 else 0.0,
    }


# ─── ana akış ────────────────────────────────────────────────────────────────

async def load(days: int, limit_symbols: int):
    import asyncpg
    conn = await asyncpg.connect(DB)
    cutoff = int((__import__("time").time() - days * 86400) * 1000)
    rows = await conn.fetch(
        """SELECT symbol, open_time, open, high, low, close, volume
             FROM historical_candles
            WHERE timeframe='1m' AND open_time >= $1
              AND (symbol LIKE '%TRY' OR symbol LIKE '%USDT')
            ORDER BY symbol, open_time ASC""", cutoff)
    await conn.close()
    data = {}
    for r in rows:
        d = data.setdefault(r["symbol"], {"T": [], "O": [], "H": [], "L": [], "C": [], "V": []})
        d["T"].append(int(r["open_time"]))
        d["O"].append(float(r["open"]))
        d["H"].append(float(r["high"]))
        d["L"].append(float(r["low"]))
        d["C"].append(float(r["close"]))
        d["V"].append(float(r["volume"]))
    ordered = sorted(data.items(), key=lambda kv: -len(kv[1]["C"]))[:limit_symbols]
    return dict(ordered)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--symbols", type=int, default=120)
    args = ap.parse_args()

    data = asyncio.run(load(args.days, args.symbols))
    total_bars = sum(len(d["C"]) for d in data.values())
    sys.stdout.write(f"sembol: {len(data)}  |  bar: {total_bars:,}  |  {args.days} gün\n")
    sys.stdout.flush()

    per = defaultdict(list)
    per_coin = defaultdict(lambda: defaultdict(list))

    for sym, d in data.items():
        T = np.asarray(d["T"], dtype=np.int64)
        O = np.asarray(d["O"], dtype=float)
        H = np.asarray(d["H"], dtype=float)
        L = np.asarray(d["L"], dtype=float)
        C = np.asarray(d["C"], dtype=float)
        V = np.asarray(d["V"], dtype=float)
        n = len(C)
        if n < 300:
            continue

        e20 = ema(C, 20)
        e50 = ema(C, 50)
        _, _, J = kdj(H, L, C, 9, 3)
        r14 = rsi(C, 14)
        st_bull = supertrend_bull(H, L, C, 10, 3.0)
        vol_ma = np.convolve(V, np.ones(20) / 20, mode="same")
        ret1 = np.zeros(n)
        ret1[1:] = (C[1:] / C[:-1] - 1) * 100
        trend = np.nan_to_num(e20, nan=0) >= np.nan_to_num(e50, nan=0)

        def add(name, idx, tp, sl, mb):
            if idx >= n - 2:
                return
            e = C[idx]
            r = simulate(idx, e, H, L, C, tp, sl, mb)
            if r is not None:
                per[name].append(r)
                per_coin[name][sym].append(r)
            # Aynı girişin takipçi çıkışı — ad yanına "_trail"
            rt = simulate_trail(idx, e, H, L, C, sl, max(mb, 120))
            if rt is not None:
                per[name + "_trail"].append(rt)
                per_coin[name + "_trail"][sym].append(rt)

        for i in range(120, n - 60):
            # ── velocity 5dk: hızlı momentum + trend + hacim ──
            if ret1[i] > 0.35 and trend[i] and V[i] > vol_ma[i] * 1.5:
                add("velocity_5m", i, 2.0, 1.0, 5)
            # ── velocity 15dk ──
            if i >= 15:
                r15 = (C[i] / C[i - 15] - 1) * 100
                if r15 > 0.8 and trend[i] and V[i] > vol_ma[i] * 1.3:
                    add("velocity_15m", i, 3.0, 1.5, 15)
            # ── rising: KDJ dip (J<=15, yukarı kesiş) ──
            if i > 0 and J[i] <= 15 and J[i] > J[i - 1] and J[i - 1] <= J[i - 2]:
                add("rising_kdj_dip", i, 2.0, 1.0, 30)
            # ── rising: SuperTrend boğa + yeşil ──
            if st_bull[i] and ret1[i] > 0.2:
                add("rising_supertrend", i, 2.0, 1.0, 30)
            # ── momentum: 24 saatlik yükseliş ──
            if i >= 1440:
                r24 = (C[i] / C[i - 1440] - 1) * 100
                if r24 > 3.0 and trend[i]:
                    add("momentum_24h", i, 2.0, 1.0, 60)
            # ── pulse: 1dk sıçrama + hacim ──
            if ret1[i] > 0.6 and V[i] > vol_ma[i] * 3.0:
                add("pulse", i, 2.0, 1.0, 5)
            # ── RSI aşırı satım dönüşü (referans) ──
            if r14[i] < 30 and r14[i] > r14[i - 1]:
                add("rsi_oversold", i, 2.0, 1.0, 30)
            # ── rastgele referans (her 37. bar) ──
            if i % 37 == 0:
                add("__RASTGELE__", i, 2.0, 1.0, 30)

    sys.stdout.write("\n" + "=" * 92 + "\n")
    sys.stdout.write(f"RADAR STRATEJİLERİ — {args.days} gün, {len(data)} sembol\n")
    sys.stdout.write("  çıkış: sabit TP/SL (radar hedefi) + azami tutma | maliyet %0.15\n")
    sys.stdout.write("=" * 92 + "\n")
    sys.stdout.write("%-22s %7s %8s %7s %9s %9s %8s %8s\n" % (
        "strateji", "n", "WR", "PF", "ort%", "toplam%", "t-stat", "pozCoin"))
    sys.stdout.write("-" * 92 + "\n")

    rows = []
    for name, vals in per.items():
        s = agg(vals)
        if not s:
            continue
        coins_pos = sum(1 for v in per_coin[name].values() if v and np.mean(v) > 0)
        coins_n = len([k for k, v in per_coin[name].items() if v])
        rows.append((s["avg"], name, s, coins_pos, coins_n))

    for _, name, s, cp, cn in sorted(rows, key=lambda r: -r[0]):
        mark = " **" if abs(s["tstat"]) > 2.0 else (" *" if abs(s["tstat"]) > 1.5 else "")
        sys.stdout.write("%-22s %7d %7.1f%% %7.2f %+9.3f %+9.1f %+8.2f %4d/%-3d%s\n" % (
            name, s["n"], s["wr"], s["pf"], s["avg"], s["total"], s["tstat"], cp, cn, mark))
    sys.stdout.write("=" * 92 + "\n")
    sys.stdout.write("t-stat ** |t|>2.0 (%95 anlamlı)   * |t|>1.5 (zayıf)\n")


if __name__ == "__main__":
    main()
