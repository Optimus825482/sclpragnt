"""
6 Saatlik Historical Veri ile LONG Pattern Analizi

Sadece LONG pozisyonlar icin:
- Son 6 saat historical veri
- 24 saat geriye donuk backtest
- Pattern eslestirme ve basari orani
"""

import asyncio
import json
import os
import sqlite3
import time
from collections import Counter
from datetime import datetime
from typing import Optional
import numpy as np
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from app.binance_tr_public import historical_klines


def ema(values, period):
    if len(values) < period: return None
    alpha = 2 / (period + 1)
    value = float(np.mean(values[:period]))
    for item in values[period:]:
        value = alpha * float(item) + (1 - alpha) * value
    return value


def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1: return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev))
        trs.append(tr)
    return float(np.mean(trs)) if trs else None


def rsi(closes, period=14):
    if len(closes) < period + 1: return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = float(np.mean([max(c, 0) for c in changes]))
    losses = float(np.mean([max(-c, 0) for c in changes]))
    if losses == 0: return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses))


def adx(highs, lows, closes, period=14):
    if len(closes) < period * 2: return None
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(closes)):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]
        plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
        minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
    if len(tr_list) < period: return None
    atr_val = float(np.mean(tr_list[-period:]))
    plus_di = (np.mean(plus_dm[-period:]) / atr_val * 100) if atr_val > 0 else 0
    minus_di = (np.mean(minus_dm[-period:]) / atr_val * 100) if atr_val > 0 else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return {"adx": float(dx), "plus_di": float(plus_di), "minus_di": float(minus_di)}


def supertrend(highs, lows, closes, period=10, multiplier=3.0):
    if len(closes) < period + 1: return None
    atr_val = atr(highs, lows, closes, period) or 0
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(len(closes))]
    upper, lower = [hl2[0] + multiplier * atr_val], [hl2[0] - multiplier * atr_val]
    trend = [1]
    for i in range(1, len(closes)):
        curr_upper = hl2[i] + multiplier * atr_val
        curr_lower = hl2[i] - multiplier * atr_val
        upper.append(max(upper[i-1], curr_upper))
        lower.append(min(lower[i-1], curr_lower))
        if closes[i] > upper[i-1]: trend.append(1)
        elif closes[i] < lower[i-1]: trend.append(-1)
        else: trend.append(trend[i-1])
    return {"trend": "bullish" if trend[-1] == 1 else "bearish", 
             "direction_changed": trend[-1] != trend[-2] if len(trend) > 1 else False}


def mfi(highs, lows, closes, volumes, period=14):
    if len(closes) < period + 1: return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    flow = [typical[i] * volumes[i] for i in range(len(typical))]
    pos = neg = 0.0
    for i in range(len(typical) - period, len(typical)):
        if typical[i] > typical[i - 1]: pos += flow[i]
        else: neg += flow[i]
    if neg == 0: return 100.0
    return float(100 - (100 / (1 + pos / neg))


def cmo(closes, period=9):
    if len(closes) < period + 1: return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = float(np.sum([max(c, 0) for c in changes]))
    losses = float(np.sum([max(-c, 0) for c in changes]))
    return float(100 * (gains - losses) / (gains + losses)) if (gains + losses) != 0 else 0.0


def williams_r(highs, lows, closes, period=14):
    if len(closes) < period: return None
    highest = max(highs[-period:])
    lowest = min(lows[-period:])
    if highest == lowest: return -50.0
    return float(-100 * (highest - closes[-1]) / (highest - lowest))


def vwap(highs, lows, closes, volumes):
    if len(closes) < 2: return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    total_tpv = sum(typical[i] * volumes[i] for i in range(len(typical)))
    total_vol = sum(volumes)
    return total_tpv / total_vol if total_vol > 0 else None


def bollinger(closes, period=20, std_mult=2.0):
    if len(closes) < period: return None
    window = np.asarray(closes[-period:], dtype=float)
    mid = float(np.mean(window))
    std = float(np.std(window))
    return {"upper": mid + std_mult * std, "middle": mid, "lower": mid - std_mult * std,
             "position": (closes[-1] - (mid - std_mult * std)) / (2 * std_mult * std) if std > 0 else None}


def stochastic(highs, lows, closes, period=14, smooth=3):
    if len(closes) < period + smooth - 1: return None
    values = []
    for i in range(period - 1, len(closes)):
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        values.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k = float(np.mean(values[-smooth:]))
    return {"k": k, "d": float(np.mean(values[-smooth * 2:-smooth])) if len(values) >= smooth * 2 else k}


def calculate_snapshot(highs, lows, closes, volumes):
    snapshot = {"price_info": {}, "trend": {}, "momentum": {}, "volume": {}}
    
    atr_val = atr(highs, lows, closes)
    atr_pct = (atr_val / closes[-1] * 100) if atr_val and closes[-1] else None
    vol_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes) if volumes else 1
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change_5 = ((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else None
    
    snapshot["price_info"] = {
        "current": closes[-1],
        "atr_pct": atr_pct,
        "volume_ratio": vol_ratio,
        "change_5": change_5,
        "vwap": vwap(highs, lows, closes, volumes),
    }
    
    # Trend
    ema_9 = ema(closes, 9)
    ema_21 = ema(closes, 21)
    if ema_9 and ema_21:
        alignment = "bullish" if ema_9 > ema_21 else "bearish"
    else:
        alignment = "unknown"
    snapshot["trend"] = {"alignment": alignment, "ema_9": ema_9, "ema_21": ema_21}
    
    # Momentum
    snapshot["momentum"] = {
        "rsi": rsi(closes),
        "stochastic": stochastic(highs, lows, closes),
        "cmo": cmo(closes),
        "williams_r": williams_r(highs, lows, closes),
    }
    
    # Volume
    snapshot["volume"] = {"mfi": mfi(highs, lows, closes, volumes), "volume_ratio": vol_ratio}
    
    # ADX
    adx_data = adx(highs, lows, closes)
    if adx_data: snapshot["adx"] = adx_data
    
    # SuperTrend
    st_data = supertrend(highs, lows, closes)
    if st_data: snapshot["supertrend"] = st_data
    
    # Bollinger
    bb_data = bollinger(closes)
    if bb_data: snapshot["bollinger"] = bb_data
    
    return snapshot


def check_long_pattern(snapshot):
    """LONG pozisyon icin desen kontrolu"""
    pi = snapshot.get("price_info", {})
    mom = snapshot.get("momentum", {})
    trend = snapshot.get("trend", {})
    vol = snapshot.get("volume", {})
    adx_data = snapshot.get("adx", {})
    st = snapshot.get("supertrend", {})
    bb = snapshot.get("bollinger", {})
    
    matches = []
    score = 0.0
    warnings = []
    
    # 1. Volume Spike Strong (>1.5x) - EN ONEMLI
    vr = vol.get("volume_ratio", 1)
    if vr >= 1.5:
        matches.append("vol_spike_strong")
        score += 3.0
    elif vr >= 1.2:
        matches.append("vol_spike")
        score += 1.5
    
    # 2. CMO Bearish (<-25) - TERSLENME BEKLENTISI
    cmo_val = mom.get("cmo")
    if cmo_val is not None and cmo_val <= -25:
        matches.append("cmo_bearish")
        score += 2.5
        if cmo_val <= -50:
            matches.append("cmo_oversold")
            score += 1.0
    
    # 3. SuperTrend Bullish - ONAY
    if st.get("trend") == "bullish":
        matches.append("supertrend_bull")
        score += 2.0
        if not st.get("direction_changed"):
            matches.append("supertrend_stable")
            score += 0.5
    
    # 4. Fiyat VWAP altinda - GIRIS ICIN IYI SEVIYE
    vwap_val = pi.get("vwap")
    price = pi.get("current")
    if vwap_val and price:
        if price < vwap_val:
            matches.append("below_vwap")
            score += 1.5
        else:
            matches.append("above_vwap")
            score += 0.5
    
    # 5. ADX >= 25 - GUCULU TREND
    adx_val = adx_data.get("adx", 0)
    if adx_val >= 25:
        matches.append("adx_strong")
        score += 1.5
    elif adx_val < 15:
        warnings.append("adx_weak")
    
    # 6. ATR% >= 0.3 - YETERLI HAREKET
    atr_pct = pi.get("atr_pct")
    if atr_pct is not None and atr_pct >= 0.3:
        matches.append("atr_ok")
        score += 1.0
    elif atr_pct is not None and atr_pct < 0.15:
        warnings.append("atr_low")
    
    # 7. RSI < 70 - OVERBOUGHT DEGIL
    rsi_val = mom.get("rsi")
    if rsi_val is not None:
        if rsi_val < 70:
            matches.append("rsi_safe")
            score += 0.5
        if rsi_val <= 30:
            matches.append("rsi_oversold")
            score += 1.0
        if rsi_val >= 80:
            warnings.append("rsi_overbought")
    
    # 8. Williams %R <= -80 - ASIRI SATIM
    wr_val = mom.get("williams_r")
    if wr_val is not None and wr_val <= -80:
        matches.append("williams_oversold")
        score += 1.0
    
    # 9. EMA Bullish
    if trend.get("alignment") == "bullish":
        matches.append("ema_bull")
        score += 1.0
    
    # 10. MFI <= 20 - ASIRI SATIM
    mfi_val = vol.get("mfi")
    if mfi_val is not None and mfi_val <= 20:
        matches.append("mfi_oversold")
        score += 1.0
    
    # 11. BB Alt banda yakin
    bbp = bb.get("position")
    if bbp is not None and bbp <= 0.2:
        matches.append("bb_lower")
        score += 1.0
    
    # KOMBINASYON BONUS
    # Volume Spike + CMO Bearish = GUCULU TERSLENME
    if "vol_spike_strong" in matches and "cmo_bearish" in matches:
        matches.append("combo_spike_reversal")
        score += 2.0
    
    # Below VWAP + RSI Oversold = IYI GIRIS NOKTASI
    if "below_vwap" in matches and "rsi_oversold" in matches:
        matches.append("combo_vwap_rsi")
        score += 1.5
    
    if warnings:
        for w in warnings:
            matches.append("warn_" + w)
    
    return {
        "matches": matches,
        "score": score,
        "strength": "strong" if score >= 8 else "medium" if score >= 5 else "weak",
        "warnings": warnings,
    }


def get_db():
    return sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "scalper_db_v4.sqlite"))


def save_candles(conn, symbol, timeframe, candles):
    cur = conn.cursor()
    fetched_at = time.time()
    for c in candles:
        try:
            close_time = c[6] if len(c) > 6 else c[0] + 60000
            cur.execute("""
                INSERT OR REPLACE INTO market_candles 
                (symbol, timeframe, open_time, close_time, open, high, low, close, volume, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, timeframe, c[0], close_time, float(c[1]), float(c[2]), 
                  float(c[3]), float(c[4]), float(c[5]), "binance_tr_public", fetched_at))
        except: pass
    conn.commit()


def get_candles(conn, symbol, timeframe, start_time, end_time):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume
        FROM market_candles
        WHERE symbol = ? AND timeframe = ? AND open_time >= ? AND open_time < ?
        ORDER BY open_time ASC
    """, (symbol, timeframe, start_time, end_time))
    return [{"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in cur.fetchall()]


def get_symbols(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM market_candles WHERE timeframe = '5m'")
    return [r[0] for r in cur.fetchall()]


async def fetch_data():
    print("=" * 70)
    print("6 SAATLIK HISTORICAL VERI CEKME (24 SAAT GERI)")
    print("=" * 70)
    
    conn = get_db()
    symbols = get_symbols(conn)
    
    for symbol in symbols:
        print(f"Input {symbol}", end=" ", flush=True)
        try:
            m1 = await historical_klines(symbol, "1m", 24)
            if m1:
                save_candles(conn, symbol, "1m", m1)
                print(f"1m:{len(m1)}", end=" ", flush=True)
        except Exception as e:
            print("1mX", end=" ", flush=True)
        
        try:
            m5 = await historical_klines(symbol, "5m", 24)
            if m5:
                save_candles(conn, symbol, "5m", m5)
                print(f"5m:{len(m5)}", end=" ", flush=True)
        except Exception as e:
            print("5mX", end=" ", flush=True)
        print()
    
    conn.close()
    print("\n✅ Veri cekme tamamlandi!")


def run_backtest():
    print("\n" + "=" * 70)
    print("6 SAATLIK HISTORICAL BACKTEST - LONG POZISYON ANALIZI")
    print("=" * 70)
    
    conn = get_db()
    symbols = get_symbols(conn)
    
    now_ms = int(time.time() * 1000)
    hours_back = 6
    
    results = []
    
    for symbol in symbols:
        candles = get_candles(conn, symbol, "1m", now_ms - hours_back * 60 * 60 * 1000, now_ms)
        
        if len(candles) < 10: continue
        
        for i in range(0, len(candles) - 10, 5):
            period_start = candles[i]["timestamp"]
            period_candles = candles[i:i + 10]
            
            if len(period_candles) < 10: continue
            
            highs = [c["high"] for c in period_candles]
            lows = [c["low"] for c in period_candles]
            closes = [c["close"] for c in period_candles]
            volumes = [c["volume"] for c in period_candles]
            
            snapshot = calculate_snapshot(highs, lows, closes, volumes)
            pattern = check_long_pattern(snapshot)
            
            if pattern["score"] < 5: continue
            
            future_start = candles[i + 10]["timestamp"] if i + 10 < len(candles) else None
            if not future_start: continue
            
            future_end = min(future_start + 30 * 60 * 1000, now_ms)
            future_candles = get_candles(conn, symbol, "1m", future_start, future_end)
            
            if len(future_candles) < 3: continue
            
            entry_price = closes[-1]
            future_high = max(c["high"] for c in future_candles)
            future_low = min(c["low"] for c in future_candles)
            
            upside = (future_high - entry_price) / entry_price * 100
            downside = (entry_price - future_low) / entry_price * 100
            
            success = upside >= 1.0
            
            results.append({
                "symbol": symbol,
                "time": datetime.fromtimestamp(period_start / 1000).strftime("%H:%M"),
                "pattern": pattern,
                "score": pattern["score"],
                "upside": upside,
                "downside": downside,
                "success": success,
                "matches": pattern["matches"],
            })
    
    conn.close()
    
    total = len(results)
    successful = sum(1 for r in results if r["success"])
    failed = total - successful
    
    print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  6 SAATLIK HISTORICAL BACKTEST - LONG ANALIZ                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Toplam Sinyal: {total}
║  Basarili (LONG): {successful}
║  Basarisiz: {failed}
║  BASARI ORANI: %{successful/total*100 if total > 0 else 0:.1f}
╚══════════════════════════════════════════════════════════════════════════════╝
    """)
    
    # Pattern bazli analiz
    pattern_stats = Counter()
    pattern_success = Counter()
    
    for r in results:
        for m in r["matches"]:
            if not m.startswith("warn_") and not m.startswith("combo_"):
                pattern_stats[m] += 1
                if r["success"]: pattern_success[m] += 1
    
    print("\n" + "=" * 70)
    print("PATTERN BAZLI BASARI (LONG)")
    print("=" * 70)
    
    for pattern, count in pattern_stats.most_common(15):
        succ = pattern_success[pattern]
        rate = succ / count * 100 if count > 0 else 0
        bar = "█" * int(rate / 5)
        print(f"{pattern:<30} {count:>4} sin. %{rate:>5.1f} {bar}")
    
    # Kombinasyon analizi
    combo_stats = Counter()
    combo_success = Counter()
    
    for r in results:
        for m in r["matches"]:
            if m.startswith("combo_"):
                combo_stats[m] += 1
                if r["success"]: combo_success[m] += 1
    
    print("\n" + "=" * 70)
    print("KOMBINASYON BASARI (LONG)")
    print("=" * 70)
    
    for combo, count in combo_stats.most_common():
        succ = combo_success[combo]
        rate = succ / count * 100 if count > 0 else 0
        bar = "█" * int(rate / 5)
        print(f"{combo:<30} {count:>4} sin. %{rate:>5.1f} {bar}")
    
    report = {
        "type": "6h_historical_long_backtest",
        "timestamp": datetime.now().isoformat(),
        "total_signals": total,
        "successful": successful,
        "failed": failed,
        "success_rate": successful / total * 100 if total > 0 else 0,
        "results": results,
        "pattern_stats": dict(pattern_stats),
    }
    
    output = os.path.join(os.path.dirname(__file__), "..", "6h_long_backtest_report.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n✅ Rapor: {output}")
    return report


async def main():
    await fetch_data()
    run_backtest()


if __name__ == "__main__":
    asyncio.run(main())
