#!/usr/bin/env python3
"""
Out-of-Sample Backtest: 6 saat geriden baslayan 24 saatlik veri.

Mantik:
- Pattern analizi icin SON 6 SAAT kullanildi (kirlenen pencere).
- Bu backtest onu DISARIDA birakir: 30 saat oncesinden 6 saat oncesine
  kadar olan 24 saatlik pencereyi ceker (yani simdi-30s .. simdi-6s).
- Desen eslestirmesi ayni long kurallarla calisir, basari oranina bakar.
"""

import asyncio
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.binance_tr_public import historical_klines


# ---------------- Indicator helpers ----------------

def ema_v(values, period):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    val = float(np.mean(values[:period]))
    for item in values[period:]:
        val = alpha * float(item) + (1 - alpha) * val
    return val


def atr_v(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    return float(np.mean(trs))


def rsi_v(closes, period=14):
    if len(closes) < period + 1:
        return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = float(np.mean(np.maximum(changes, 0)))
    losses = float(np.mean(np.maximum(-changes, 0)))
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses)))


def adx_v(highs, lows, closes, period=14):
    if len(closes) < period * 2:
        return None
    pdm_total, mdm_total, trs = [], [], []
    for i in range(1, len(closes)):
        hd = highs[i] - highs[i - 1]
        ld = lows[i - 1] - lows[i]
        pdm_total.append(hd if hd > ld and hd > 0 else 0.0)
        mdm_total.append(ld if ld > hd and ld > 0 else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = float(np.mean(trs[-period:]))
    pdi = np.mean(pdm_total[-period:]) / atr * 100 if atr > 0 else 0.0
    mdi = np.mean(mdm_total[-period:]) / atr * 100 if atr > 0 else 0.0
    dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0.0
    return {"adx": float(dx), "pdi": float(pdi), "mdi": float(mdi)}


def cmo_v(closes, period=9):
    if len(closes) < period + 1:
        return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = float(np.sum(np.maximum(changes, 0)))
    losses = float(np.sum(np.maximum(-changes, 0)))
    return float(100 * (gains - losses) / (gains + losses)) if (gains + losses) else 0.0


def vwap_v(highs, lows, closes, volumes):
    if len(closes) < 2:
        return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    tv = sum(volumes)
    return sum(tp[i] * volumes[i] for i in range(len(closes))) / tv if tv > 0 else None


def st_v(highs, lows, closes, period=10, mult=3.0):
    if len(closes) < period + 1:
        return None
    atr_val = atr_v(highs, lows, closes, period) or 0
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(len(closes))]
    upper, lower = [hl2[0] + mult * atr_val], [hl2[0] - mult * atr_val]
    trend = [1]
    for i in range(1, len(closes)):
        cu, cl = hl2[i] + mult * atr_val, hl2[i] - mult * atr_val
        upper.append(max(upper[i - 1], cu))
        lower.append(min(lower[i - 1], cl))
        if closes[i] > upper[i - 1]:
            trend.append(1)
        elif closes[i] < lower[i - 1]:
            trend.append(-1)
        else:
            trend.append(trend[i - 1])
    return {"trend": "bullish" if trend[-1] == 1 else "bearish",
            "changed": trend[-1] != trend[-2] if len(trend) > 1 else False}


def williams_v(highs, lows, closes, period=14):
    if len(closes) < period:
        return None
    hi, lo = max(highs[-period:]), min(lows[-period:])
    if hi == lo:
        return -50.0
    return float(-100 * (hi - closes[-1]) / (hi - lo))


def bb_v(closes, period=20, mult=2.0):
    if len(closes) < period:
        return None
    w = np.asarray(closes[-period:], dtype=float)
    mid, std = float(np.mean(w)), float(np.std(w))
    upper, lower = mid + mult * std, mid - mult * std
    pos = (closes[-1] - lower) / (upper - lower) if upper != lower else None
    return {"position": pos, "upper": upper, "lower": lower}


# ---------------- Snapshot ----------------

def build_snapshot(highs, lows, closes, volumes):
    atr_val = atr_v(highs, lows, closes)
    atr_pct = (atr_val / closes[-1] * 100) if atr_val and closes[-1] else None
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)) if volumes else 1.0
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change5 = ((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else None
    ema9, ema21 = ema_v(closes, 9), ema_v(closes, 21)
    return {
        "price": {"close": closes[-1], "atr_pct": atr_pct, "vol_ratio": vol_ratio,
                   "change5": change5, "vwap": vwap_v(highs, lows, closes, volumes)},
        "trend": {"alignment": "bullish" if ema9 and ema21 and ema9 > ema21 else "bearish"},
        "momentum": {"rsi": rsi_v(closes), "cmo": cmo_v(closes), "williams": williams_v(highs, lows, closes)},
        "adx": adx_v(highs, lows, closes),
        "st": st_v(highs, lows, closes),
        "bb": bb_v(closes),
    }


def check_long(snap):
    pi, mom, adx_d, st = snap["price"], snap["momentum"], snap["adx"], snap["st"]
    matches, score, warns = [], 0.0, []

    vr = pi.get("vol_ratio", 1)
    if vr >= 1.5:
        matches.append("vol_spike_strong"); score += 3.0
    elif vr >= 1.2:
        matches.append("vol_spike"); score += 1.5

    cmo = mom.get("cmo")
    if cmo is not None and cmo <= -25:
        matches.append("cmo_bearish"); score += 2.5

    if st and st.get("trend") == "bullish":
        matches.append("st_bull"); score += 2.0

    vwap = pi.get("vwap")
    if vwap and pi["close"] < vwap:
        matches.append("below_vwap"); score += 1.5

    adx_val = adx_d.get("adx", 0) if adx_d else 0
    if adx_val >= 25:
        matches.append("adx_strong"); score += 1.5
    elif adx_val < 15:
        warns.append("adx_weak")

    atr_pct = pi.get("atr_pct")
    if atr_pct is not None and atr_pct >= 0.3:
        matches.append("atr_ok"); score += 1.0

    rsi = mom.get("rsi")
    if rsi is not None:
        if rsi < 70:
            matches.append("rsi_safe"); score += 0.5
        if rsi <= 30:
            matches.append("rsi_oversold"); score += 1.0
        if rsi >= 80:
            warns.append("rsi_overbought")

    wr = mom.get("williams")
    if wr is not None and wr <= -80:
        matches.append("williams_oversold"); score += 1.0

    bb_obj = snap.get("bb") or {}
    bbp = bb_obj.get("position")
    if bbp is not None and bbp <= 0.2:
        matches.append("bb_lower"); score += 1.0

    if "vol_spike_strong" in matches and "cmo_bearish" in matches:
        matches.append("combo_spike_reversal"); score += 2.0
    if "below_vwap" in matches and "rsi_oversold" in matches:
        matches.append("combo_vwap_rsi"); score += 1.5

    for w in warns:
        matches.append("warn_" + w)
    return {"matches": matches, "score": score}


# ---------------- DB ----------------

def get_db():
    return sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "scalper_db_v4.sqlite"))


def save_candles(conn, sym, tf, candles):
    cur = conn.cursor()
    ft = time.time()
    for c in candles:
        try:
            ct = c[6] if len(c) > 6 else c[0] + 60000
            cur.execute("""
                INSERT OR REPLACE INTO market_candles
                (symbol, timeframe, open_time, close_time, open, high, low, close, volume, source, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (sym, tf, c[0], ct, float(c[1]), float(c[2]), float(c[3]), float(c[4]),
                  float(c[5]), "binance_tr_public", ft))
        except Exception:
            pass
    conn.commit()


def get_candles(conn, sym, tf, start_ms, end_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume
        FROM market_candles
        WHERE symbol=? AND timeframe=? AND open_time>=? AND open_time<?
        ORDER BY open_time ASC
    """, (sym, tf, start_ms, end_ms))
    return [{"ts": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]} for r in cur.fetchall()]


def get_syms(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM market_candles WHERE timeframe='5m'")
    return [r[0] for r in cur.fetchall()]


# ---------------- Fetch 30h (6h offset + 24h lookback) ----------------

async def fetch_data():
    print("=" * 70)
    print("VERI CEKME: 6 saat geriden baslayan 24 saatlik pencere")
    print("=" * 70)
    conn = get_db()
    syms = get_syms(conn)
    for sym in syms:
        print(f"{sym}", end=" ", flush=True)
        try:
            m1 = await historical_klines(sym, "1m", 36)  # 36 saatlik veri, 6s offset icin
            if m1:
                save_candles(conn, sym, "1m", m1)
                print(f"1m:{len(m1)}", end=" ", flush=True)
        except Exception:
            print("1mX", end=" ", flush=True)
        print()
    conn.close()
    print("\nTamamlandi!")


# ---------------- Out-of-sample backtest ----------------

def backtest():
    print("\n" + "=" * 70)
    print("OUT-OF-SAMPLE BACKTEST: 6s-geri baslangicli 24s pencere")
    print("=" * 70)

    conn = get_db()
    syms = get_syms(conn)
    now_ms = int(time.time() * 1000)

    # Pencere: now - 30h .. now - 6h  (yani son 6 saat DISARIDA)
    end_ms = now_ms - 6 * 3600000
    start_ms = end_ms - 24 * 3600000

    results = []
    for sym in syms:
        candles = get_candles(conn, sym, "1m", start_ms, end_ms)
        if len(candles) < 10:
            continue

        for i in range(0, len(candles) - 10, 5):
            period = candles[i:i + 10]
            if len(period) < 10:
                continue
            hs = [c["h"] for c in period]
            ls = [c["l"] for c in period]
            cs = [c["c"] for c in period]
            vs = [c["v"] for c in period]
            pat = check_long(build_snapshot(hs, ls, cs, vs))
            if pat["score"] < 5:
                continue

            next_start = candles[i + 10]["ts"] if i + 10 < len(candles) else None
            if not next_start:
                continue
            future = get_candles(conn, sym, "1m", next_start, min(next_start + 1800000, end_ms))
            if len(future) < 3:
                continue
            entry = cs[-1]
            future_high = max(c["h"] for c in future)
            upside = (future_high - entry) / entry * 100
            success = upside >= 1.0
            results.append({
                "symbol": sym,
                "time": datetime.fromtimestamp(period[0]["ts"] / 1000).strftime("%m-%d %H:%M"),
                "score": round(pat["score"], 1),
                "upside": round(upside, 2),
                "success": success,
                "matches": pat["matches"],
            })

    conn.close()

    total = len(results)
    success_n = sum(1 for r in results if r["success"])
    rate = success_n / total * 100 if total > 0 else 0.0

    print(f"""
+{"=" * 66}
| OUT-OF-SAMPLE SONUC (son 6 saat HARIC, 24 saat pencere)
+{"=" * 66}
| Veri penceresi: {datetime.fromtimestamp(start_ms / 1000).strftime('%m-%d %H:%M')} -> {datetime.fromtimestamp(end_ms / 1000).strftime('%m-%d %H:%M')}
| Toplam Sinyal : {total}
| Basarili      : {success_n}
| Basarisiz     : {total - success_n}
| BASARI ORANI  : %{rate:.1f}
+{"-" * 66}
""")

    pstats, psucc = Counter(), Counter()
    for r in results:
        for m in r["matches"]:
            if not m.startswith("warn_") and not m.startswith("combo_"):
                pstats[m] += 1
                if r["success"]:
                    psucc[m] += 1

    print("\nPattern bazli basari (long):")
    for p, cnt in pstats.most_common(15):
        s = psucc[p]
        pr = s / cnt * 100 if cnt > 0 else 0
        bar = chr(9608) * int(pr / 5)
        print(f"  {p:<30} {cnt:>3} sin  %{pr:>5.1f}  {bar}")

    cstats, csucc = Counter(), Counter()
    for r in results:
        for m in r["matches"]:
            if m.startswith("combo_"):
                cstats[m] += 1
                if r["success"]:
                    csucc[m] += 1
    if cstats:
        print("\nKombinasyonlar:")
        for c, cnt in cstats.most_common():
            s = csucc[c]
            pr = s / cnt * 100 if cnt > 0 else 0
            bar = chr(9608) * int(pr / 5)
            print(f"  {c:<30} {cnt:>3} sin  %{pr:>5.1f}  {bar}")

    # karsilastirma icin isabetli/yanlis orenkleri goster
    print("\nOrnek sinyaller:")
    for r in results[:15]:
        mark = "BASARILI" if r["success"] else "basarisiz"
        print(f"  {r['time']} {r['symbol']:<12} +%{r['upside']:.2f} {mark}")

    report = {
        "type": "outofsample_24h_long",
        "window": {"start_ms": start_ms, "end_ms": end_ms},
        "total": total,
        "success": success_n,
        "rate": rate,
        "results": results,
    }
    out = os.path.join(os.path.dirname(__file__), "..", "outofsample_24h_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nRapor: {out}")


async def main():
    await fetch_data()
    backtest()


if __name__ == "__main__":
    asyncio.run(main())