"""
24 Saat Desen Eşleştirme Analizi - Geliştirilmiş Filtreler

Eklenen Filtreler:
1. ADX >= 25 (Güçlü trend)
2. ATR% >= 0.3 (Minimum volatilite)
3. RSI < 70 (Overbought kontrolü)
4. Supertrend direction_changed = false (Yeni trend değil)
5. Volume Spike Strong + Price Rising (Kombinasyon)
6. VWAP kontrolü
"""

import asyncio
import json
import os
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.binance_tr_public import historical_klines


# =============================================================================
# GÖSTERGE FONKSIYONLARI
# =============================================================================

def _ema(values: list, period: int) -> Optional[float]:
    if len(values) < period: return None
    alpha = 2 / (period + 1)
    value = float(np.mean(values[:period]))
    for item in values[period:]:
        value = alpha * float(item) + (1 - alpha) * value
    return value


def _atr(highs, lows, closes, period=14) -> Optional[float]:
    if len(closes) < period + 1: return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev))
        trs.append(tr)
    return float(np.mean(trs)) if trs else None


def _rsi(closes, period=14) -> Optional[float]:
    if len(closes) < period + 1: return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = np.mean(np.maximum(changes, 0))
    losses = np.mean(np.maximum(-changes, 0))
    if losses == 0: return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses)))


def _stochastic(highs, lows, closes, period=14, smooth=3) -> Optional[dict]:
    if len(closes) < period + smooth - 1: return None
    values = []
    for i in range(period - 1, len(closes)):
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        values.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k = float(np.mean(values[-smooth:]))
    return {"k": k, "d": float(np.mean(values[-smooth * 2:-smooth])) if len(values) >= smooth * 2 else k}


def _adx(highs, lows, closes, period=14) -> Optional[dict]:
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
    atr = float(np.mean(tr_list[-period:]))
    plus_di = (np.mean(plus_dm[-period:]) / atr * 100) if atr > 0 else 0
    minus_di = (np.mean(minus_dm[-period:]) / atr * 100) if atr > 0 else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return {"adx": float(dx), "plus_di": float(plus_di), "minus_di": float(minus_di)}


def _supertrend(highs, lows, closes, period=10, multiplier=3.0) -> Optional[dict]:
    if len(closes) < period + 1: return None
    atr_val = _atr(highs, lows, closes, period) or 0
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


def _vortex(highs, lows, closes, period=14) -> Optional[dict]:
    if len(closes) < period + 1: return None
    plus_vm = [abs(highs[i] - lows[i-1]) for i in range(1, len(highs))]
    minus_vm = [abs(lows[i] - highs[i-1]) for i in range(1, len(lows))]
    atr = _atr(highs, lows, closes, period) or 1
    plus_vi = np.sum(plus_vm[-period:]) / atr
    minus_vi = np.sum(minus_vm[-period:]) / atr
    return {"plus_vi": float(plus_vi), "minus_vi": float(minus_vi)}


def _mfi(highs, lows, closes, volumes, period=14) -> Optional[float]:
    if len(closes) < period + 1: return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    flow = [typical[i] * volumes[i] for i in range(len(typical))]
    pos = neg = 0.0
    for i in range(len(typical) - period, len(typical)):
        if typical[i] > typical[i - 1]: pos += flow[i]
        else: neg += flow[i]
    if neg == 0: return 100.0
    return float(100 - (100 / (1 + pos / neg)))


def _williams_r(highs, lows, closes, period=14) -> Optional[float]:
    if len(closes) < period: return None
    highest = max(highs[-period:])
    lowest = min(lows[-period:])
    if highest == lowest: return -50.0
    return float(-100 * (highest - closes[-1]) / (highest - lowest))


def _cmo(closes, period=9) -> Optional[float]:
    if len(closes) < period + 1: return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = float(np.sum(np.maximum(changes, 0)))
    losses = float(np.sum(np.maximum(-changes, 0)))
    return float(100 * (gains - losses) / (gains + losses)) if (gains + losses) != 0 else 0.0


def _bollinger(closes, period=20, std_mult=2.0) -> Optional[dict]:
    if len(closes) < period: return None
    window = np.asarray(closes[-period:], dtype=float)
    mid = float(np.mean(window))
    std = float(np.std(window))
    return {"upper": mid + std_mult * std, "middle": mid, "lower": mid - std_mult * std,
            "position": (closes[-1] - (mid - std_mult * std)) / (2 * std_mult * std) if std > 0 else None}


def _vwap(highs, lows, closes, volumes) -> Optional[float]:
    """VWAP = Ortalama Fiyat * Hacim"""
    if len(closes) < 2 or len(volumes) < 2: return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    total_tpv = sum(typical[i] * volumes[i] for i in range(len(typical)))
    total_vol = sum(volumes)
    return total_tpv / total_vol if total_vol > 0 else None


# =============================================================================
# SNAPSHOT HESAPLAMA
# =============================================================================

def calculate_snapshot(highs, lows, closes, volumes) -> dict:
    snapshot = {"price_info": {}, "trend": {}, "momentum": {}, "volume": {}}
    
    # Fiyat bilgileri
    atr_val = _atr(highs, lows, closes)
    atr_pct = (atr_val / closes[-1] * 100) if atr_val and closes[-1] else None
    vol_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes) if volumes else 1
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    change_5 = ((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else None
    
    snapshot["price_info"] = {
        "current": closes[-1],
        "atr_pct": atr_pct,
        "volume_ratio": vol_ratio,
        "change_5": change_5,
        "vwap": _vwap(highs, lows, closes, volumes),
    }
    
    # Trend
    ema_9 = _ema(closes, 9)
    ema_21 = _ema(closes, 21)
    ema_50 = _ema(closes, 50) if len(closes) >= 50 else None
    if ema_9 and ema_21:
        if ema_50:
            alignment = "bullish" if ema_9 > ema_21 > ema_50 else "bearish" if ema_9 < ema_21 < ema_50 else "neutral"
        else:
            alignment = "bullish" if ema_9 > ema_21 else "bearish" if ema_9 < ema_21 else "neutral"
    else:
        alignment = "unknown"
    snapshot["trend"] = {"alignment": alignment, "ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50}
    
    # Momentum
    snapshot["momentum"] = {
        "rsi": _rsi(closes),
        "stochastic": _stochastic(highs, lows, closes),
        "cmo": _cmo(closes),
        "williams_r": _williams_r(highs, lows, closes),
    }
    
    # Volume
    snapshot["volume"] = {"mfi": _mfi(highs, lows, closes, volumes), "volume_ratio": vol_ratio}
    
    # ADX
    adx_data = _adx(highs, lows, closes)
    if adx_data: snapshot["adx"] = adx_data
    
    # SuperTrend
    st_data = _supertrend(highs, lows, closes)
    if st_data: snapshot["supertrend"] = st_data
    
    # Vortex
    vortex_data = _vortex(highs, lows, closes)
    if vortex_data: snapshot["vortex"] = vortex_data
    
    # Bollinger
    bb_data = _bollinger(closes)
    if bb_data: snapshot["bollinger"] = bb_data
    
    return snapshot


def check_pattern_match_enhanced(snapshot: dict) -> dict:
    """GELIŞTIRILMIŞ Desen Eşleşmesi - Ek Filtrelerle"""
    pi = snapshot.get("price_info", {})
    mom = snapshot.get("momentum", {})
    trend = snapshot.get("trend", {})
    vol = snapshot.get("volume", {})
    adx = snapshot.get("adx", {})
    st = snapshot.get("supertrend", {})
    vortex = snapshot.get("vortex", {})
    bb = snapshot.get("bollinger", {})
    
    matches = []
    score = 0.0
    reasons = []  # Başarısızlık nedenleri
    
    # ===== TEMEL PATTERNLER =====
    
    # 1. CMO Bullish (>25)
    cmo = mom.get("cmo")
    if cmo is not None and cmo >= 25:
        matches.append("cmo_bullish")
        score += 2.0
    
    # 2. CMO Bearish (<-25)
    if cmo is not None and cmo <= -25:
        matches.append("cmo_bearish")
        score += 1.5
    
    # 3. Volume Spike Strong (>1.5x)
    vr = vol.get("volume_ratio", 1)
    if vr >= 1.5:
        matches.append("volume_spike_strong")
        score += 1.5
    elif vr >= 1.2:
        matches.append("volume_spike")
        score += 1.0
    
    # 4. SuperTrend Bullish
    if st.get("trend") == "bullish":
        matches.append("supertrend_bullish")
        score += 2.0
        # Yeni trend değilse ek puan
        if not st.get("direction_changed"):
            matches.append("supertrend_stable")
            score += 1.0
    
    # 5. Vortex Bullish
    if vortex and vortex.get("plus_vi", 0) > vortex.get("minus_vi", 0):
        matches.append("vortex_bullish")
        score += 1.0
    
    # 6. EMA Bullish
    if trend.get("alignment") == "bullish":
        matches.append("ema_bullish")
        score += 1.0
    
    # 7. ADX Strong Trend (YENI FILTRE!)
    adx_val = adx.get("adx", 0)
    if adx_val >= 25:
        matches.append("adx_strong_trend")
        score += 1.5
    elif adx_val < 15:
        reasons.append("Dusuk_ADX")
    
    # 8. Price Rising
    change_5 = pi.get("change_5", 0)
    if change_5 is not None and change_5 >= 1:
        matches.append("price_rising")
        score += 0.5
    elif change_5 is not None and change_5 <= -1:
        matches.append("price_falling")
        score += 0.5
    
    # ===== YENI EK FILTRELER =====
    
    # 9. ATR High (YENI!)
    atr_pct = pi.get("atr_pct")
    if atr_pct is not None and atr_pct >= 0.3:
        matches.append("atr_sufficient")
        score += 1.0
    elif atr_pct is not None and atr_pct < 0.2:
        reasons.append("Dusuk_ATR")
    
    # 10. RSI Not Overbought (YENI!)
    rsi = mom.get("rsi")
    if rsi is not None:
        if rsi <= 70:
            matches.append("rsi_safe")
            score += 0.5
        if rsi >= 80:
            reasons.append("RSI_Overbought")
        if rsi <= 30:
            matches.append("rsi_oversold")
            score += 0.5
    
    # 11. VWAP Above (YENI!)
    vwap = pi.get("vwap")
    current_price = pi.get("current")
    if vwap and current_price:
        if current_price > vwap:
            matches.append("above_vwap")
            score += 0.5
        else:
            matches.append("below_vwap")
    
    # 12. Williams %R
    wr = mom.get("williams_r")
    if wr and wr >= -20:
        reasons.append("Williams_Overbought")
    elif wr and wr <= -80:
        matches.append("williams_oversold")
        score += 0.5
    
    # 13. MFI
    mfi = vol.get("mfi")
    if mfi and mfi >= 80:
        reasons.append("MFI_Overbought")
    elif mfi and mfi <= 20:
        matches.append("mfi_oversold")
        score += 0.5
    
    # ===== KOMBINASYON KONTROL =====
    
    # Volume Spike + Price Rising = Güçlü sinyal
    if "volume_spike_strong" in matches and "price_rising" in matches:
        matches.append("spike_plus_rising")
        score += 2.0
    
    # Volume Spike + Price Falling = Terslenme sinyali
    if "volume_spike_strong" in matches and "price_falling" in matches:
        matches.append("spike_plus_falling")
        score += 1.5
    
    # CMO + ADX + ATR = Güçlü trend
    if "cmo_bullish" in matches and "adx_strong_trend" in matches and "atr_sufficient" in matches:
        matches.append("strong_trend_combo")
        score += 2.0
    
    # ===== BAŞARIŞIZLIK KONTROLÜ =====
    
    if reasons:
        for r in reasons:
            if r not in matches:
                matches.append(f"FAIL_{r}")
    
    return {
        "matches": matches,
        "score": score,
        "pattern_strength": "strong" if score >= 6 else "medium" if score >= 3 else "weak",
        "reasons": reasons,
    }


# =============================================================================
# VERITABANI
# =============================================================================

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


# =============================================================================
# 24 SAAT ANALIZ
# =============================================================================

async def fetch_24h_data():
    print("=" * 80)
    print("24 SAAT VERİ ÇEKME")
    print("=" * 80)
    
    conn = get_db()
    symbols = get_symbols(conn)
    
    now_ms = int(time.time() * 1000)
    hours_back = 24
    lookback_ms = hours_back * 60 * 60 * 1000
    
    for symbol in symbols:
        print(f"📥 {symbol}", end=" ", flush=True)
        try:
            m1 = await historical_klines(symbol, "1m", hours_back)
            if m1:
                save_candles(conn, symbol, "1m", m1)
                print(f"M1:{len(m1)}", end=" ", flush=True)
        except: print(f"M1❌", end=" ", flush=True)
        
        try:
            m5 = await historical_klines(symbol, "5m", hours_back)
            if m5:
                save_candles(conn, symbol, "5m", m5)
                print(f"M5:{len(m5)}", end=" ", flush=True)
        except: print(f"M5❌", end=" ", flush=True)
        print()
    
    conn.close()
    print("\n✅ Veri çekme tamamlandı!")


def analyze_24h_patterns():
    print("\n" + "=" * 80)
    print("24 SAAT GELIŞTIRILMIŞ DESEN EŞLEŞTİRME ANALİZİ")
    print("=" * 80)
    
    conn = get_db()
    symbols = get_symbols(conn)
    
    now_ms = int(time.time() * 1000)
    hours_back = 24
    start_ms = now_ms - (hours_back * 60 * 60 * 1000)
    
    hourly_results = []
    
    for hour_offset in range(hours_back):
        hour_start = start_ms + (hour_offset * 60 * 60 * 1000)
        hour_end = hour_start + (60 * 60 * 1000)
        
        hour_matches = []
        
        for symbol in symbols:
            # Son 10 M1 çek
            m1_candles = get_candles(conn, symbol, "1m", hour_start - 10 * 60 * 1000, hour_start)
            
            if len(m1_candles) < 10: continue
            
            highs = [c["high"] for c in m1_candles]
            lows = [c["low"] for c in m1_candles]
            closes = [c["close"] for c in m1_candles]
            volumes = [c["volume"] for c in m1_candles]
            
            snapshot = calculate_snapshot(highs, lows, closes, volumes)
            pattern_result = check_pattern_match_enhanced(snapshot)
            
            # GELIŞTIRILMIŞ: Sadece güçlü sinyalleri al
            if pattern_result["score"] >= 4.0:  # Minimum 4 puan
                future_candles = get_candles(conn, symbol, "1m", hour_start, hour_end)
                
                if len(future_candles) >= 5:
                    entry_price = m1_candles[-1]["close"]
                    future_high = max(c["high"] for c in future_candles)
                    future_low = min(c["low"] for c in future_candles)
                    upside = (future_high - entry_price) / entry_price * 100
                    downside = (entry_price - future_low) / entry_price * 100
                    success = upside >= 1.0
                    
                    hour_matches.append({
                        "symbol": symbol,
                        "hour": hour_offset,
                        "hour_time": datetime.fromtimestamp(hour_start / 1000).strftime("%H:%M"),
                        "pattern": pattern_result,
                        "score": pattern_result["score"],
                        "upside_pct": upside,
                        "downside_pct": downside,
                        "success": success,
                        "matches": pattern_result["matches"],
                    })
        
        hourly_results.append({
            "hour": hour_offset,
            "hour_time": datetime.fromtimestamp(hour_start / 1000).strftime("%Y-%m-%d %H:00"),
            "matches": hour_matches,
            "match_count": len(hour_matches),
            "success_count": sum(1 for m in hour_matches if m["success"]),
        })
        
        if hour_matches:
            success_rate = sum(1 for m in hour_matches if m["success"]) / len(hour_matches) * 100
            print(f"  {datetime.fromtimestamp(hour_start/1000).strftime('%H:%M')}: {len(hour_matches)} eşleşme, %{success_rate:.0f} başarı")
    
    conn.close()
    
    total_matches = sum(h["match_count"] for h in hourly_results)
    total_success = sum(h["success_count"] for h in hourly_results)
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  24 SAAT GELIŞTIRILMIŞ ANALİZ                                     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Toplam Eşleşme: {total_matches}
║  Başarılı: {total_success}
║  BAŞARI ORANI: %{total_success/total_matches*100 if total_matches > 0 else 0:.1f}
╚═══════════════════════════════════════════════════════════════════════════════╝
    """)
    
    # Pattern bazlı analiz
    all_patterns = []
    for h in hourly_results:
        for m in h["matches"]:
            all_patterns.extend(m["matches"])
    
    pattern_stats = Counter([p for p in all_patterns if not p.startswith("FAIL_")])
    
    print("\n" + "=" * 80)
    print("PATTERN BAZLI BAŞARI (GELIŞTIRILMIŞ)")
    print("=" * 80)
    
    for pattern, count in pattern_stats.most_common(15):
        successful = 0
        for h in hourly_results:
            for m in h["matches"]:
                if pattern in m["matches"] and m["success"]:
                    successful += 1
        rate = successful / count * 100 if count > 0 else 0
        bar = "█" * int(rate / 5)
        print(f"{pattern:<35} {count:>4} kez  %{rate:>5.1f}  {bar}")
    
    # Raporu kaydet
    report = {
        "analysis_id": f"24h_pattern_v2_{int(time.time())}",
        "timestamp": datetime.now().isoformat(),
        "hours_analyzed": hours_back,
        "total_matches": total_matches,
        "total_success": total_success,
        "success_rate": total_success / total_matches * 100 if total_matches > 0 else 0,
        "hourly_results": hourly_results,
        "pattern_stats": dict(pattern_stats.most_common(20)),
    }
    
    output = os.path.join(os.path.dirname(__file__), "..", "24h_pattern_analysis_v2_report.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n✅ Rapor: {output}")
    return report


async def main():
    await fetch_24h_data()
    analyze_24h_patterns()


if __name__ == "__main__":
    asyncio.run(main())
