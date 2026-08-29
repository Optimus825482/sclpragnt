"""
M1 Veri Analizi - Yükseliş Öncesi Son 10 M1

Mevcut M1 verilerini kullanarak %2+ yükselişlerden önceki 
10 M1 mumunun göstergelerini analiz eder.
"""

import asyncio
import json
import math
import os
import sqlite3
import time
from collections import Counter
from datetime import datetime

import numpy as np
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.binance_tr_public import historical_klines


# =============================================================================
# GÖSTERGE FONKSIYONLARI
# =============================================================================

def _ema(values: list, period: int) -> float | None:
    if len(values) < period: return None
    alpha = 2 / (period + 1)
    value = float(np.mean(values[:period]))
    for item in values[period:]:
        value = alpha * float(item) + (1 - alpha) * value
    return value


def _atr(highs, lows, closes, period=14) -> float | None:
    if len(closes) < period + 1: return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev))
        trs.append(tr)
    return float(np.mean(trs)) if trs else None


def _rsi(closes, period=14) -> float | None:
    if len(closes) < period + 1: return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = np.mean(np.maximum(changes, 0))
    losses = np.mean(np.maximum(-changes, 0))
    if losses == 0: return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses)))


def _stochastic(highs, lows, closes, period=14, smooth=3) -> dict | None:
    if len(closes) < period + smooth - 1: return None
    values = []
    for i in range(period - 1, len(closes)):
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        values.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k = float(np.mean(values[-smooth:]))
    d = float(np.mean(values[-smooth * 2:-smooth])) if len(values) >= smooth * 2 else k
    return {"k": k, "d": d}


def _adx(highs, lows, closes, period=14) -> dict | None:
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


def _supertrend(highs, lows, closes, period=10, multiplier=3.0) -> dict | None:
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
    return {"value": upper[-1] if trend[-1] == 1 else lower[-1], 
             "trend": "bullish" if trend[-1] == 1 else "bearish",
             "direction_changed": trend[-1] != trend[-2] if len(trend) > 1 else False}


def _bollinger(closes, period=20, std_mult=2.0) -> dict | None:
    if len(closes) < period: return None
    window = np.asarray(closes[-period:], dtype=float)
    mid = float(np.mean(window))
    std = float(np.std(window))
    return {"upper": mid + std_mult * std, "middle": mid, "lower": mid - std_mult * std,
             "position": (closes[-1] - (mid - std_mult * std)) / (2 * std_mult * std) if std > 0 else None}


def _vortex(highs, lows, closes, period=14) -> dict | None:
    if len(closes) < period + 1: return None
    plus_vm = [abs(highs[i] - lows[i-1]) for i in range(1, len(highs))]
    minus_vm = [abs(lows[i] - highs[i-1]) for i in range(1, len(lows))]
    atr = _atr(highs, lows, closes, period) or 1
    plus_vi = np.sum(plus_vm[-period:]) / atr
    minus_vi = np.sum(minus_vm[-period:]) / atr
    return {"plus_vi": float(plus_vi), "minus_vi": float(minus_vi)}


def _mfi(highs, lows, closes, volumes, period=14) -> float | None:
    if len(closes) < period + 1: return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    flow = [typical[i] * volumes[i] for i in range(len(typical))]
    pos = neg = 0.0
    for i in range(len(typical) - period, len(typical)):
        if typical[i] > typical[i - 1]: pos += flow[i]
        else: neg += flow[i]
    if neg == 0: return 100.0
    return float(100 - (100 / (1 + pos / neg)))


def _williams_r(highs, lows, closes, period=14) -> float | None:
    if len(closes) < period: return None
    highest = max(highs[-period:])
    lowest = min(lows[-period:])
    if highest == lowest: return -50.0
    return float(-100 * (highest - closes[-1]) / (highest - lowest))


def _macd(closes, fast=12, slow=26, signal=9) -> dict | None:
    if len(closes) < slow + signal: return None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if ema_fast is None or ema_slow is None: return None
    macd_line = ema_fast - ema_slow
    sig = _ema(closes[-signal:], signal)
    return {"line": float(macd_line), "signal": float(sig) if sig else 0.0,
             "histogram": float(macd_line - sig) if sig else 0.0}


def _cmo(closes, period=9) -> float | None:
    if len(closes) < period + 1: return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = float(np.sum(np.maximum(changes, 0)))
    losses = float(np.sum(np.maximum(-changes, 0)))
    return float(100 * (gains - losses) / (gains + losses)) if (gains + losses) != 0 else 0.0


def _roc(closes, period=12) -> float | None:
    if len(closes) < period + 1: return None
    return float((closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100)


# =============================================================================
# SNAPSHOT HESAPLAMA
# =============================================================================

def calculate_snapshot(highs, lows, closes, volumes) -> dict:
    snapshot = {}
    
    # Fiyat
    atr_val = _atr(highs, lows, closes)
    atr_pct = (atr_val / closes[-1] * 100) if atr_val and closes[-1] else None
    vol_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes) if volumes else 1
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
    
    snapshot["price_info"] = {
        "current": closes[-1],
        "atr_pct": atr_pct,
        "volume_ratio": vol_ratio,
        "change_5": ((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else None,
    }
    
    # Trend
    ema_9 = _ema(closes, 9)
    ema_21 = _ema(closes, 21)
    ema_50 = _ema(closes, 50) if len(closes) >= 50 else None
    if ema_9 and ema_21:
        if ema_50:
            align = "bullish" if ema_9 > ema_21 > ema_50 else "bearish" if ema_9 < ema_21 < ema_50 else "neutral"
        else:
            align = "bullish" if ema_9 > ema_21 else "bearish" if ema_9 < ema_21 else "neutral"
    else:
        align = "unknown"
    snapshot["trend"] = {"ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50, "alignment": align}
    
    # Momentum
    snapshot["momentum"] = {
        "rsi": _rsi(closes),
        "stochastic": _stochastic(highs, lows, closes),
        "macd": _macd(closes),
        "cmo": _cmo(closes),
        "roc": _roc(closes),
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
    
    # Bollinger
    bb_data = _bollinger(closes)
    if bb_data: snapshot["bollinger"] = bb_data
    
    # Vortex
    v_data = _vortex(highs, lows, closes)
    if v_data: snapshot["vortex"] = v_data
    
    return snapshot


def extract_tags(snapshot: dict) -> list[str]:
    tags = []
    pi = snapshot.get("price_info", {})
    mom = snapshot.get("momentum", {})
    trend = snapshot.get("trend", {})
    vol = snapshot.get("volume", {})
    adx = snapshot.get("adx", {})
    st = snapshot.get("supertrend", {})
    bb = snapshot.get("bollinger", {})
    vortex = snapshot.get("vortex", {})
    
    # RSI
    rsi = mom.get("rsi")
    if rsi:
        if rsi >= 70: tags.append("rsi_overbought")
        elif rsi <= 30: tags.append("rsi_oversold")
        elif rsi >= 55: tags.append("rsi_bullish_zone")
        elif rsi <= 45: tags.append("rsi_bearish_zone")
    
    # Stochastic
    stoch = mom.get("stochastic")
    if stoch and stoch.get("k"):
        if stoch["k"] >= 80: tags.append("stoch_overbought")
        elif stoch["k"] <= 20: tags.append("stoch_oversold")
    
    # ADX
    adx_val = adx.get("adx", 0)
    if adx_val >= 25: tags.append("adx_strong_trend")
    elif adx_val >= 20: tags.append("adx_moderate_trend")
    
    # EMA
    align = trend.get("alignment", "unknown")
    if align == "bullish": tags.append("ema_bullish")
    elif align == "bearish": tags.append("ema_bearish")
    
    # Volume
    vr = vol.get("volume_ratio", 1)
    if vr >= 1.5: tags.append("volume_spike_strong")
    elif vr >= 1.2: tags.append("volume_spike")
    
    # MFI
    mfi = vol.get("mfi")
    if mfi:
        if mfi >= 80: tags.append("mfi_overbought")
        elif mfi <= 20: tags.append("mfi_oversold")
    
    # ATR
    atr_pct = pi.get("atr_pct")
    if atr_pct:
        if atr_pct >= 0.5: tags.append("atr_high")
        elif atr_pct <= 0.2: tags.append("atr_low")
    
    # ROC
    roc = mom.get("roc")
    if roc:
        if roc >= 5: tags.append("roc_strong_up")
        elif roc <= -5: tags.append("roc_strong_down")
    
    # Williams %R
    wr = mom.get("williams_r")
    if wr:
        if wr >= -20: tags.append("williams_overbought")
        elif wr <= -80: tags.append("williams_oversold")
    
    # MACD
    macd = mom.get("macd")
    if macd:
        if macd.get("histogram", 0) > 0: tags.append("macd_bullish")
        else: tags.append("macd_bearish")
    
    # CMO
    cmo = mom.get("cmo")
    if cmo:
        if cmo >= 25: tags.append("cmo_bullish")
        elif cmo <= -25: tags.append("cmo_bearish")
    
    # SuperTrend
    if st:
        tags.append(f"supertrend_{st.get('trend', 'unknown')}")
        if st.get("direction_changed"): tags.append("supertrend_reversal")
    
    # Bollinger
    bbp = bb.get("position")
    if bbp is not None:
        if bbp >= 0.9: tags.append("bb_upper_band")
        elif bbp <= 0.1: tags.append("bb_lower_band")
    
    # Vortex
    if vortex:
        if vortex.get("plus_vi", 0) > vortex.get("minus_vi", 0): tags.append("vortex_bullish")
        else: tags.append("vortex_bearish")
    
    # Price change
    ch5 = pi.get("change_5")
    if ch5:
        if ch5 >= 1: tags.append("price_rising")
        elif ch5 <= -1: tags.append("price_falling")
    
    return list(set(tags))


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
        except Exception as e:
            pass
    conn.commit()


def get_candles(conn, symbol, timeframe, lookback_ms):
    cur = conn.cursor()
    cur.execute("""
        SELECT open_time, open, high, low, close, volume
        FROM market_candles
        WHERE symbol = ? AND timeframe = ? AND open_time > ?
        ORDER BY open_time ASC
    """, (symbol, timeframe, int(time.time() * 1000) - lookback_ms))
    return [{"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in cur.fetchall()]


# =============================================================================
# ANA ANALIZ
# =============================================================================

async def fetch_data():
    """Binance'den veri çek"""
    print("=" * 80)
    print("VERİ ÇEKME - Binance TR")
    print("=" * 80)
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM market_candles WHERE timeframe = '5m'")
    symbols = [r[0] for r in cur.fetchall()]
    
    hours_back = 6
    lookback_ms = hours_back * 60 * 60 * 1000
    
    for symbol in symbols:
        print(f"\n📥 {symbol}", end=" ", flush=True)
        
        # M1 verisi çek
        try:
            m1 = await historical_klines(symbol, "1m", hours_back)
            if m1:
                save_candles(conn, symbol, "1m", m1)
                print(f"M1:{len(m1)}", end=" ", flush=True)
        except Exception as e:
            print(f"M1❌", end=" ", flush=True)
        
        # M5 verisi çek
        try:
            m5 = await historical_klines(symbol, "5m", hours_back)
            if m5:
                save_candles(conn, symbol, "5m", m5)
                print(f"M5:{len(m5)}", end=" ", flush=True)
        except Exception as e:
            print(f"M5❌", end=" ", flush=True)
        
        print()
    
    conn.close()
    print("\n✅ Veri çekme tamamlandı!")


def analyze():
    """M1 verilerini analiz et"""
    print("\n" + "=" * 80)
    print("M1 YÜKSELİŞ ÖNCESİ ANALİZ")
    print("=" * 80)
    
    conn = get_db()
    
    # Sembolleri al
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM market_candles WHERE timeframe = '5m'")
    symbols = [r[0] for r in cur.fetchall()]
    
    # Her sembol için verileri al - tam zaman aralığını kullan
    m5_data = {}
    m1_data = {}
    for symbol in symbols:
        # M5 için
        cur.execute("""
            SELECT open_time, open, high, low, close, volume
            FROM market_candles
            WHERE symbol = ? AND timeframe = '5m'
            ORDER BY open_time ASC
        """, (symbol,))
        m5 = [{"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in cur.fetchall()]
        
        # M1 için
        cur.execute("""
            SELECT open_time, open, high, low, close, volume
            FROM market_candles
            WHERE symbol = ? AND timeframe = '1m'
            ORDER BY open_time ASC
        """, (symbol,))
        m1 = [{"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in cur.fetchall()]
        
        if len(m5) >= 10: m5_data[symbol] = m5
        if len(m1) >= 10: m1_data[symbol] = m1
    
    print(f"\n📊 M5: {len(m5_data)} sembol, M1: {len(m1_data)} sembol")
    
    if not m5_data or not m1_data:
        print("❌ Yeterli veri yok!")
        conn.close()
        return
    
    # %2+ yükselişleri tespit et (M5 bazında)
    risers = []
    for symbol, candles in m5_data.items():
        for i in range(5, len(candles) - 1):
            curr_close = candles[i]["close"]
            future_close = candles[i + 1]["close"]
            rise_pct = (future_close - curr_close) / curr_close * 100
            
            if rise_pct >= 2.0:
                risers.append({
                    "symbol": symbol,
                    "rise_idx": i,
                    "rise_time": candles[i]["timestamp"],
                    "rise_pct": rise_pct,
                })
    
    print(f"📈 %2+ M5 yükseliş: {len(risers)} adet")
    
    # Her yükseliş için M1 analizi
    snapshots = []
    for riser in risers:
        symbol = riser["symbol"]
        rise_time = riser["rise_time"]
        
        if symbol not in m1_data:
            continue
        
        m1 = m1_data[symbol]
        
        # Yükselişten 10 dk önceye kadar olan son 10 M1
        cutoff = rise_time - 10 * 60 * 1000
        m1_before = [c for c in m1 if c["timestamp"] < rise_time and c["timestamp"] >= cutoff]
        
        if len(m1_before) < 5:
            m1_before = [c for c in m1 if c["timestamp"] < rise_time][-10:]
        
        if len(m1_before) < 5:
            continue
        
        # Snapshot
        highs = [c["high"] for c in m1_before]
        lows = [c["low"] for c in m1_before]
        closes = [c["close"] for c in m1_before]
        volumes = [c["volume"] for c in m1_before]
        
        snap = calculate_snapshot(highs, lows, closes, volumes)
        tags = extract_tags(snap)
        
        snapshots.append({
            "symbol": symbol,
            "rise_pct": riser["rise_pct"],
            "rise_time": riser["rise_time"],
            "m1_count": len(m1_before),
            "tags": tags,
            "snapshot": snap,
        })
    
    print(f"✅ Analiz: {len(snapshots)} M1 snapshot")
    
    if not snapshots:
        print("❌ Analiz edilebilir M1 verisi yok!")
        conn.close()
        return
    
    # Tag analizi
    all_tags = []
    for s in snapshots:
        all_tags.extend(s["tags"])
    
    tag_counts = Counter(all_tags)
    total = len(snapshots)
    
    print("\n" + "=" * 80)
    print("🎯 M1 YÜKSELİŞ ÖNCESİ 10 MUMDA TESPİT EDİLEN DESENLER")
    print("=" * 80)
    
    for tag, count in tag_counts.most_common(25):
        pct = count / total * 100
        bar = "█" * int(pct / 5)
        print(f"{tag:<35} | {count:>4} | %{pct:>6.1f} | {bar}")
    
    # İstatistikler
    all_rsi, all_stoch, all_mfi, all_adx, all_atr, all_vol = [], [], [], [], [], []
    
    for s in snapshots:
        snap = s["snapshot"]
        mom = snap.get("momentum", {})
        vol = snap.get("volume", {})
        adx = snap.get("adx", {})
        
        if mom.get("rsi"): all_rsi.append(mom["rsi"])
        stoch = mom.get("stochastic")
        if stoch and stoch.get("k"): all_stoch.append(stoch["k"])
        if vol.get("mfi"): all_mfi.append(vol["mfi"])
        if adx.get("adx"): all_adx.append(adx["adx"])
        if snap.get("price_info", {}).get("atr_pct"): all_atr.append(snap["price_info"]["atr_pct"])
        if vol.get("volume_ratio"): all_vol.append(vol["volume_ratio"])
    
    print("\n" + "=" * 80)
    print("📊 M1 GÖSTERGE İSTATİSTİKLERİ")
    print("=" * 80)
    
    def s(arr, name):
        if not arr: return f"{name}: N/A"
        return f"{name}: ort={sum(arr)/len(arr):.1f} min={min(arr):.1f} max={max(arr):.1f}"
    
    print(f"\n{s(all_rsi, 'RSI')}")
    print(s(all_stoch, 'StochK'))
    print(s(all_mfi, 'MFI'))
    print(s(all_adx, 'ADX'))
    print(s(all_atr, 'ATR%'))
    print(s(all_vol, 'VolRatio'))
    
    # Rapor kaydet
    report = {
        "analysis_id": f"m1_rise_{int(time.time())}",
        "timestamp": datetime.now().isoformat(),
        "m1_snapshots": len(snapshots),
        "total_risers": len(risers),
        "patterns": [{"tag": t, "count": c, "pct": round(c/total*100, 1)} for t, c in tag_counts.most_common(25)],
        "stats": {
            "rsi": {"mean": sum(all_rsi)/len(all_rsi) if all_rsi else None},
            "stoch": {"mean": sum(all_stoch)/len(all_stoch) if all_stoch else None},
            "mfi": {"mean": sum(all_mfi)/len(all_mfi) if all_mfi else None},
            "adx": {"mean": sum(all_adx)/len(all_adx) if all_adx else None},
            "atr_pct": {"mean": sum(all_atr)/len(all_atr) if all_atr else None},
        }
    }
    
    output = os.path.join(os.path.dirname(__file__), "..", "m1_rise_analysis_report.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Rapor: {output}")
    conn.close()


async def main():
    await fetch_data()
    # Sonra en son veri zamanını bulup analiz yap
    import sqlite3
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "scalper_db_v4.sqlite"))
    cur = conn.cursor()
    cur.execute("SELECT MAX(open_time) FROM market_candles WHERE timeframe = '5m'")
    max_time = cur.fetchone()[0] or int(time.time() * 1000)
    conn.close()
    
    # Global değişken olarak sakla
    global _max_db_time
    _max_db_time = max_time
    analyze()


if __name__ == "__main__":
    asyncio.run(main())
