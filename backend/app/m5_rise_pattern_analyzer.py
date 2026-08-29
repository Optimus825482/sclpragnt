"""
M5 Rise Pattern Analyzer - 6 Saat Geriye Dönük Analiz

Bu script:
1. Son 6 saatlik tüm sembollerin M5 candle historylerini çeker
2. %2+ yükseliş yapan sembolleri tespit eder
3. Yükseliş başlamadan önceki 10 M1 ve 2 M5 mumunu alır
4. Ekteki gösterge listesinden ilgili göstergeleri hesaplar
5. Desen analizi yaparak ortak patternları raporlar
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np

# =============================================================================
# TEKNİK GÖSTERGE HESAPLAMALARI
# =============================================================================

def _ema(values: list, period: int) -> Optional[float]:
    """Üstel Hareketli Ortalama"""
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    value = float(np.mean(values[:period]))
    for item in values[period:]:
        value = alpha * float(item) + (1 - alpha) * value
    return value


def _atr(highs: list, lows: list, closes: list, period: int = 14) -> Optional[float]:
    """Ortalama Gerçek Aralık (ATR)"""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i], 
                 abs(highs[i] - prev), 
                 abs(lows[i] - prev))
        trs.append(tr)
    return float(np.mean(trs)) if trs else None


def _rsi(closes: list, period: int = 14) -> Optional[float]:
    """Göreceli Güç Endeksi (RSI)"""
    if len(closes) < period + 1:
        return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = np.mean(np.maximum(changes, 0))
    losses = np.mean(np.maximum(-changes, 0))
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return float(100 - (100 / (1 + gains / losses)))


def _macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[dict]:
    """MACD"""
    if len(closes) < slow + signal:
        return None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None
    macd_line = ema_fast - ema_slow
    # Signal line approximation
    hist = list(np.diff(closes[-signal:]))
    sig = _ema(list(closes[-signal:]), signal)
    return {
        "line": float(macd_line),
        "signal": float(sig) if sig else 0.0,
        "histogram": float(macd_line - sig) if sig else 0.0
    }


def _bollinger(closes: list, period: int = 20, std_mult: float = 2.0) -> Optional[dict]:
    """Bollinger Bantları"""
    if len(closes) < period:
        return None
    window = np.asarray(closes[-period:], dtype=float)
    mid = float(np.mean(window))
    std = float(np.std(window))
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return {
        "upper": upper,
        "middle": mid,
        "lower": lower,
        "width_pct": (upper - lower) / mid if mid else None,
        "position": (closes[-1] - lower) / (upper - lower) if upper != lower else None
    }


def _stochastic(highs: list, lows: list, closes: list, period: int = 14, smooth: int = 3) -> Optional[dict]:
    """Stokastik"""
    if len(closes) < period + smooth - 1:
        return None
    values = []
    for i in range(period - 1, len(closes)):
        hi = max(highs[i - period + 1:i + 1])
        lo = min(lows[i - period + 1:i + 1])
        values.append((closes[i] - lo) / (hi - lo) * 100 if hi != lo else 50.0)
    k = float(np.mean(values[-smooth:]))
    d = float(np.mean(values[-smooth * 2:-smooth])) if len(values) >= smooth * 2 else k
    return {"k": k, "d": d}


def _adx(highs: list, lows: list, closes: list, period: int = 14) -> Optional[dict]:
    """Ortalama Yönsel Endeks (ADX)"""
    if len(closes) < period * 2:
        return None
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(closes)):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]
        plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
        minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
        tr = max(highs[i] - lows[i], 
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
    if len(tr_list) < period:
        return None
    atr = float(np.mean(tr_list[-period:]))
    plus_di = (np.mean(plus_dm[-period:]) / atr * 100) if atr > 0 else 0
    minus_di = (np.mean(minus_dm[-period:]) / atr * 100) if atr > 0 else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return {"adx": float(dx), "plus_di": float(plus_di), "minus_di": float(minus_di)}


def _mfi(highs: list, lows: list, closes: list, volumes: list, period: int = 14) -> Optional[float]:
    """Para Akışı Endeksi (MFI)"""
    if len(closes) < period + 1:
        return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    flow = [typical[i] * volumes[i] for i in range(len(typical))]
    pos, neg = 0.0, 0.0
    for i in range(len(typical) - period, len(typical)):
        if typical[i] > typical[i - 1]:
            pos += flow[i]
        else:
            neg += flow[i]
    if neg == 0:
        return 100.0
    return float(100 - (100 / (1 + pos / neg)))


def _obv(closes: list, volumes: list) -> Optional[dict]:
    """Denge İşlem Hacmi (OBV)"""
    if len(closes) < 2:
        return None
    obv = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
    return {"value": float(obv), "slope": float(obv - (volumes[-1] if len(volumes) >= 5 else 0))}


def _cmo(closes: list, period: int = 9) -> Optional[float]:
    """Chande Momentum Osilatörü"""
    if len(closes) < period + 1:
        return None
    changes = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    gains = float(np.sum(np.maximum(changes, 0)))
    losses = float(np.sum(np.maximum(-changes, 0)))
    return float(100 * (gains - losses) / (gains + losses)) if (gains + losses) != 0 else 0.0


def _roc(closes: list, period: int = 12) -> Optional[float]:
    """Değişim Oranı (ROC)"""
    if len(closes) < period + 1:
        return None
    return float((closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100)


def _fisher_transform(highs: list, lows: list, length: int = 9) -> Optional[dict]:
    """Fisher Dönüşümü"""
    if len(highs) < length + 1:
        return None
    values = []
    for i in range(length, len(highs)):
        mids = [(highs[j] + lows[j]) / 2 for j in range(i - length + 1, i + 1)]
        hi, lo = max(mids), min(mids)
        midpoint = (highs[i] + lows[i]) / 2
        ratio = (midpoint - lo) / (hi - lo) - 0.5 if hi != lo else 0.0
        value = max(-0.999, min(0.999, 0.5 * ratio + 0.5 * (values[-1] if values else 0)))
        values.append(value)
    if not values:
        return None
    fisher = 0.5 * math.log((1 + values[-1]) / (1 - values[-1])) if abs(values[-1]) < 0.999 else 0
    return {"value": float(fisher), "length": length}


def _fvg_detection(opens: list, closes: list, highs: list, lows: list) -> list[dict]:
    """Fair Value Gap (FVG) Tespiti - 3 mumluk boşluk"""
    fvgs = []
    if len(closes) < 3:
        return fvgs
    for i in range(2, len(closes)):
        prev_mid = (highs[i-2] + lows[i-2]) / 2
        curr_mid = (highs[i] + lows[i]) / 2
        # Üst FVG
        if lows[i] > highs[i-2]:
            fvgs.append({
                "type": "bullish_fvg",
                "top": highs[i-2],
                "bottom": lows[i],
                "candle_idx": i
            })
        # Alt FVG
        if highs[i] < lows[i-2]:
            fvgs.append({
                "type": "bearish_fvg",
                "top": highs[i],
                "bottom": lows[i-2],
                "candle_idx": i
            })
    return fvgs


def _volume_profile(closes: list, volumes: list, bins: int = 10) -> Optional[dict]:
    """Volume Profile - İşlem Hacmi Profili"""
    if len(closes) < bins:
        return None
    min_price, max_price = min(closes), max(closes)
    if max_price == min_price:
        return None
    bucket_size = (max_price - min_price) / bins
    buckets = [0.0] * bins
    for i in range(len(closes)):
        bucket_idx = min(int((closes[i] - min_price) / bucket_size), bins - 1)
        buckets[bucket_idx] += volumes[i]
    max_bucket_idx = buckets.index(max(buckets))
    poc = min_price + (max_bucket_idx + 0.5) * bucket_size
    return {"poc": poc, "poc_pct": (closes[-1] - poc) / poc * 100 if poc != 0 else 0}


def _choppiness(highs: list, lows: list, closes: list, period: int = 14) -> Optional[float]:
    """Dalgalılık Endeksi (Choppiness)"""
    if len(closes) < period + 1:
        return None
    atr_sum = sum(_atr(highs[:i+1], lows[:i+1], closes[:i+1]) or 0 for i in range(len(closes) - period, len(closes)))
    highest_high = max(highs[-period:])
    lowest_low = min(lows[-period:])
    if lowest_low == highest_high:
        return 100.0
    return float(100 * math.log10(atr_sum / (highest_high - lowest_low)) / math.log10(period))


def _supertrend(highs: list, lows: list, closes: list, period: int = 10, multiplier: float = 3.0) -> Optional[dict]:
    """SuperTrend"""
    if len(closes) < period + 1:
        return None
    atr_val = _atr(highs, lows, closes, period) or 0
    hl2 = [(highs[i] + lows[i]) / 2 for i in range(len(closes))]
    upper = [hl2[0] + multiplier * atr_val]
    lower = [hl2[0] - multiplier * atr_val]
    trend = [1]  # 1 = bullish, -1 = bearish
    
    for i in range(1, len(closes)):
        curr_upper = hl2[i] + multiplier * atr_val
        curr_lower = hl2[i] - multiplier * atr_val
        upper.append(max(upper[i-1], curr_upper))
        lower.append(min(lower[i-1], curr_lower))
        if closes[i] > upper[i-1]:
            trend.append(1)
        elif closes[i] < lower[i-1]:
            trend.append(-1)
        else:
            trend.append(trend[i-1])
    return {
        "value": upper[-1] if trend[-1] == 1 else lower[-1],
        "trend": "bullish" if trend[-1] == 1 else "bearish",
        "direction_changed": trend[-1] != trend[-2] if len(trend) > 1 else False
    }


def _williams_r(highs: list, lows: list, closes: list, period: int = 14) -> Optional[float]:
    """Williams %R"""
    if len(closes) < period:
        return None
    highest = max(highs[-period:])
    lowest = min(lows[-period:])
    if highest == lowest:
        return -50.0
    return float(-100 * (highest - closes[-1]) / (highest - lowest))


def _cci(highs: list, lows: list, closes: list, period: int = 20) -> Optional[float]:
    """Emtia Kanal Endeksi (CCI)"""
    if len(closes) < period:
        return None
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    sma = np.mean(typical[-period:])
    mad = np.mean([abs(typical[i] - sma) for i in range(len(typical) - period, len(typical))])
    if mad == 0:
        return 0.0
    return float((typical[-1] - sma) / (0.015 * mad))


def _trix(closes: list, period: int = 15) -> Optional[dict]:
    """TRIX"""
    if len(closes) < period * 3:
        return None
    ema1 = list(np.convolve(closes, [1/period] * period, mode='valid'))
    ema2 = list(np.convolve(ema1, [1/period] * period, mode='valid'))
    ema3 = list(np.convolve(ema2, [1/period] * period, mode='valid'))
    if len(ema3) < 2:
        return None
    return {"value": float(ema3[-1]), "change": float(ema3[-1] - ema3[-2]) if len(ema3) > 1 else 0}


def _vortex(highs: list, lows: list, closes: list, period: int = 14) -> Optional[dict]:
    """Vortex Göstergesi"""
    if len(closes) < period + 1:
        return None
    plus_vm = [abs(highs[i] - lows[i-1]) for i in range(1, len(highs))]
    minus_vm = [abs(lows[i] - highs[i-1]) for i in range(1, len(lows))]
    plus_vi = np.sum(plus_vm[-period:]) / (_atr(highs, lows, closes, period) or 1)
    minus_vi = np.sum(minus_vm[-period:]) / (_atr(highs, lows, closes, period) or 1)
    return {"plus_vi": float(plus_vi), "minus_vi": float(minus_vi)}


# =============================================================================
# SNAPSHOT HESAPLAMA
# =============================================================================

def calculate_snapshot_indicators(
    highs: list, lows: list, closes: list, volumes: list
) -> dict:
    """Tüm göstergeleri hesapla ve snapshot olarak döndür"""
    snapshot = {}
    
    # Fiyat bilgileri
    atr_val = _atr(highs, lows, closes)
    snapshot["price_info"] = {
        "current": closes[-1] if closes else None,
        "high_10": max(highs[-10:]) if len(highs) >= 10 else max(highs) if highs else None,
        "low_10": min(lows[-10:]) if len(lows) >= 10 else min(lows) if lows else None,
        "change_5": ((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else None,
        "change_10": ((closes[-1] - closes[-10]) / closes[-10] * 100) if len(closes) >= 10 else None,
        "atr_pct": (atr_val / closes[-1] * 100) if closes and atr_val else None,
        "volume_avg": np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes) if volumes else None,
        "volume_ratio": volumes[-1] / np.mean(volumes[-20:]) if len(volumes) >= 20 and np.mean(volumes[-20:]) > 0 else 1.0,
    }
    
    # Trend göstergeleri
    ema_9 = _ema(closes, 9)
    ema_21 = _ema(closes, 21)
    ema_50 = _ema(closes, 50) if len(closes) >= 50 else None
    snapshot["trend"] = {
        "ema_9": ema_9,
        "ema_21": ema_21,
        "ema_50": ema_50,
        "alignment": _get_ema_alignment(ema_9, ema_21, ema_50),
    }
    
    adx_data = _adx(highs, lows, closes)
    if adx_data:
        snapshot["adx"] = adx_data
    
    supertrend = _supertrend(highs, lows, closes)
    if supertrend:
        snapshot["supertrend"] = supertrend
    
    # Momentum göstergeleri
    snapshot["momentum"] = {
        "rsi": _rsi(closes),
        "stochastic": _stochastic(highs, lows, closes),
        "macd": _macd(closes),
        "cmo": _cmo(closes),
        "roc": _roc(closes),
        "williams_r": _williams_r(highs, lows, closes),
        "cci": _cci(highs, lows, closes),
        "trix": _trix(closes),
    }
    
    # Volume göstergeleri
    snapshot["volume"] = {
        "mfi": _mfi(highs, lows, closes, volumes),
        "obv": _obv(closes, volumes),
        "volume_profile": _volume_profile(closes, volumes),
        "choppiness": _choppiness(highs, lows, closes),
    }
    
    # Fisher Transform
    snapshot["fisher"] = _fisher_transform(highs, lows)
    
    # FVG Tespiti
    snapshot["fvg"] = _fvg_detection([], closes, highs, lows)
    
    # Bollinger Bantları
    snapshot["bollinger"] = _bollinger(closes)
    
    # Vortex
    snapshot["vortex"] = _vortex(highs, lows, closes)
    
    return snapshot


def _get_ema_alignment(ema_9: Optional[float], ema_21: Optional[float], ema_50: Optional[float]) -> str:
    """EMA hizalamasını belirle"""
    if ema_9 is None or ema_21 is None:
        return "unknown"
    if ema_50 is not None:
        if ema_9 > ema_21 > ema_50:
            return "bullish"
        elif ema_9 < ema_21 < ema_50:
            return "bearish"
    if ema_9 > ema_21:
        return "bullish"
    elif ema_9 < ema_21:
        return "bearish"
    return "neutral"


# =============================================================================
# VERİTABANI İŞLEMLERİ
# =============================================================================

def get_db_connection():
    """Veritabanı bağlantısı oluştur"""
    db_path = os.path.join(os.path.dirname(__file__), "..", "scalper_db_v4.sqlite")
    return sqlite3.connect(db_path, check_same_thread=False)


def get_symbols_from_db(conn) -> list[str]:
    """Veritabanından sembol listesini al"""
    cur = conn.cursor()
    # Sadece 5m timeframe'deki sembolleri al
    cur.execute("SELECT DISTINCT symbol FROM market_candles WHERE timeframe = '5m' ORDER BY symbol")
    return [row[0] for row in cur.fetchall()]


def get_candles_from_db(conn, symbol: str, interval: str, lookback_minutes: int, 
                       threshold_time: Optional[int] = None) -> list[dict]:
    """Belirtilen sembol ve interval için mumları al (hem market hem historical)"""
    cur = conn.cursor()
    
    if threshold_time is None:
        lookback_ms = lookback_minutes * 60 * 1000
        threshold_time = int(time.time() * 1000) - lookback_ms
    
    # market_candles sorgula (timeframe sütunu var)
    cur.execute("""
        SELECT open_time, open, high, low, close, volume, close_time
        FROM market_candles
        WHERE symbol = ? AND timeframe = ? AND open_time > ?
        ORDER BY open_time ASC
    """, (symbol, interval, threshold_time))
    
    rows = cur.fetchall()
    return [
        {
            "timestamp": row[0],
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": row[6],
        }
        for row in rows
    ]


def save_analysis_results(conn, analysis_id: str, results: dict):
    """Analiz sonuçlarını veritabanına kaydet"""
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT OR REPLACE INTO research_runs (id, created_at, run_type, parameters, result)
            VALUES (?, ?, ?, ?, ?)
        """, (
            int(analysis_id.split("_")[-1]) if "_" in str(analysis_id) else 0,
            int(time.time() * 1000),
            "m5_rise_pattern_analysis",
            json.dumps({"lookback_hours": 6}),
            json.dumps(results, default=str)
        ))
        conn.commit()
    except Exception as e:
        print(f"⚠️ Veritabanına kayıt hatası: {e}")
        # Kayıt hata verse bile devam et


# =============================================================================
# ANA ANALİZ FONKSİYONU
# =============================================================================

def analyze_m5_rise_patterns():
    """Ana analiz fonksiyonu"""
    print("=" * 80)
    print("M5 RISE PATTERN ANALYZER - 6 SAATLIK ANALIZ")
    print("=" * 80)
    
    conn = get_db_connection()
    analysis_id = f"m5_rise_{int(time.time())}"
    
    # 1. Sembolleri al
    symbols = get_symbols_from_db(conn)
    print(f"\n📊 Toplam sembol sayısı: {len(symbols)}")
    
    # 2. Veritabanındaki en yeni veri zamanını bul
    cur = conn.cursor()
    cur.execute("SELECT MAX(open_time) FROM market_candles")
    max_db_time = cur.fetchone()[0] or 0
    
    # lookback_ms = 6 saat geriye git
    lookback_hours = 6
    lookback_minutes = lookback_hours * 60
    lookback_ms = lookback_minutes * 60 * 1000
    threshold_time = max_db_time - lookback_ms
    
    print(f"📅 Veritabanı son veri zamanı: {datetime.fromtimestamp(max_db_time/1000)}")
    print(f"📅 Analiz başlangıç zamanı: {datetime.fromtimestamp(threshold_time/1000)}")
    
    all_m5_data = {}
    for symbol in symbols:
        candles = get_candles_from_db(conn, symbol, "5m", lookback_minutes, threshold_time)
        if len(candles) >= 10:  # Minimum 10 mum gerekli
            all_m5_data[symbol] = candles
    
    print(f"✅ {len(all_m5_data)} sembol için M5 verisi çekildi")
    
    # 3. %2+ yükseliş yapan sembolleri tespit et
    risers_2pct = []
    
    for symbol, candles in all_m5_data.items():
        if len(candles) < 10:
            continue
        
        # Her mum çiftini kontrol et (yükseliş başlangıcı)
        for i in range(5, len(candles) - 1):
            prev_close = candles[i - 1]["close"]
            curr_close = candles[i]["close"]
            future_close = candles[i + 1]["close"] if i + 1 < len(candles) else curr_close
            
            # %2+ yükseliş tespit et
            rise_pct = (future_close - curr_close) / curr_close * 100
            
            if rise_pct >= 2.0:
                risers_2pct.append({
                    "symbol": symbol,
                    "rise_start_idx": i,
                    "rise_start_time": candles[i]["timestamp"],
                    "rise_start_price": candles[i]["close"],
                    "peak_price": future_close,
                    "peak_time": candles[i + 1]["timestamp"],
                    "rise_pct": rise_pct,
                    "prev_2_candles": [candles[i - 2], candles[i - 1]] if i >= 2 else [candles[i - 1]] if i >= 1 else [],
                    "rise_candle": candles[i],
                    "all_candles": candles,
                })
    
    print(f"\n📈 %2+ Yükseliş tespit edilen sembol sayısı: {len(risers_2pct)}")
    
    # 4. Her yükseliş için detaylı analiz
    all_snapshots = []
    pattern_features = defaultdict(list)
    
    for riser in risers_2pct:
        symbol = riser["symbol"]
        rise_start_idx = riser["rise_start_idx"]
        candles = riser["all_candles"]
        
        # YÜKSELİŞ ÖNCESİ son 50 M5 MUMU - ANA ANALİZ
        # Yükseliş başlayan mumdan HEMEN ÖNCE 50 M5 mum al (göstergeler için yeterli veri)
        m5_before_rise = candles[max(0, rise_start_idx - 50):rise_start_idx]
        
        # Yükseliş anı dahil son 53 M5 (50 önceki + 3 sonraki)
        m5_full_context = candles[max(0, rise_start_idx - 50):rise_start_idx + 3]
        
        # Snapshot hesapla
        snapshot = {
            "symbol": symbol,
            "rise_pct": riser["rise_pct"],
            "rise_start_time": riser["rise_start_time"],
            "rise_candle_price": riser["rise_start_price"],
            "m5_before_50_snapshot": None,  # Yükseliş ÖNCESİ son 50 M5 - ANA HEDEF
            "m5_rise_snapshot": None,        # Yükseliş anı
            "pattern_tags": [],
        }
        
        # M5 BEFORE SNAPSHOT - Yükseliş ÖNCESİ son 50 M5 mum (ANA ANALIZ!)
        if len(m5_before_rise) >= 30:
            m5_highs = [c["high"] for c in m5_before_rise]
            m5_lows = [c["low"] for c in m5_before_rise]
            m5_closes = [c["close"] for c in m5_before_rise]
            m5_volumes = [c["volume"] for c in m5_before_rise]
            snapshot["m5_before_50_snapshot"] = calculate_snapshot_indicators(m5_highs, m5_lows, m5_closes, m5_volumes)
        
        # M5 rise snapshot (yükseliş anı dahil)
        if len(m5_full_context) >= 20:
            m5r_highs = [c["high"] for c in m5_full_context]
            m5r_lows = [c["low"] for c in m5_full_context]
            m5r_closes = [c["close"] for c in m5_full_context]
            m5r_volumes = [c["volume"] for c in m5_full_context]
            snapshot["m5_rise_snapshot"] = calculate_snapshot_indicators(m5r_highs, m5r_lows, m5r_closes, m5r_volumes)
        
        # Pattern tagleri çıkar - YÜKSELİŞ ÖNCESİ 50 M5 MUM'DAN
        if snapshot["m5_before_50_snapshot"]:
            tags = extract_pattern_tags(snapshot["m5_before_50_snapshot"])
            snapshot["pattern_tags"].extend(tags)
        # Yükseliş anını da ekle ama öncelik yükseliş öncesi
        if snapshot["m5_rise_snapshot"]:
            tags = extract_pattern_tags(snapshot["m5_rise_snapshot"])
            snapshot["pattern_tags"].extend(tags)
        
        all_snapshots.append(snapshot)
        
        # Her sembolün taglerini kaydet
        for tag in snapshot["pattern_tags"]:
            pattern_features[tag].append(symbol)
    
    print(f"✅ {len(all_snapshots)} adet snapshot oluşturuldu")
    
    # 5. Desen analizi - ortak patternları bul
    print("\n" + "=" * 80)
    print("🔍 DESEN ANALİZİ - ORTAK PATTERNLAR")
    print("=" * 80)
    
    common_patterns = []
    for tag, symbols_with_tag in sorted(pattern_features.items(), key=lambda x: -len(x[1])):
        coverage = len(symbols_with_tag) / len(risers_2pct) * 100 if risers_2pct else 0
        if coverage >= 20:  # En az %20'de görülmüş olsun
            common_patterns.append({
                "pattern": tag,
                "count": len(symbols_with_tag),
                "coverage_pct": coverage,
                "symbols": list(set(symbols_with_tag)),
            })
    
    # En yaygın patternlardan başla
    common_patterns.sort(key=lambda x: -x["coverage_pct"])
    
    print(f"\n📊 Toplam {len(common_patterns)} ortak desen tespit edildi:")
    print("-" * 60)
    
    for i, pattern in enumerate(common_patterns[:15], 1):  # İlk 15'ini göster
        print(f"{i:2}. {pattern['pattern']:30} | {pattern['count']:3} sembol | %{pattern['coverage_pct']:5.1f}")
    
    # 6. Final rapor
    # Snapshot'lardan numpy tiplerini temizle
    clean_snapshots = []
    for snap in all_snapshots:
        clean_snap = {
            "symbol": snap["symbol"],
            "rise_pct": snap["rise_pct"],
            "rise_start_time": snap["rise_start_time"],
            "pattern_tags": snap["pattern_tags"],
        }
        # M5 before 50 snapshot temizle
        if snap.get("m5_before_50_snapshot"):
            clean_snap["m5_before_50_snapshot"] = _clean_for_json(snap["m5_before_50_snapshot"])
        # M5 rise snapshot temizle
        if snap.get("m5_rise_snapshot"):
            clean_snap["m5_rise_snapshot"] = _clean_for_json(snap["m5_rise_snapshot"])
        clean_snapshots.append(clean_snap)
    
    report = {
        "analysis_id": analysis_id,
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_symbols_analyzed": len(all_m5_data),
            "symbols_with_2pct_rise": len(risers_2pct),
            "snapshots_created": len(all_snapshots),
            "common_patterns_found": len(common_patterns),
        },
        "risers": [
            {
                "symbol": r["symbol"],
                "rise_pct": r["rise_pct"],
                "rise_start_time": r["rise_start_time"],
                "tags": all_snapshots[i]["pattern_tags"] if i < len(all_snapshots) else [],
            }
            for i, r in enumerate(risers_2pct)
        ],
        "common_patterns": common_patterns[:20],
        "all_snapshots": clean_snapshots,
    }
    
    # 7. Veritabanına kaydet
    save_analysis_results(conn, analysis_id, report)
    
    # 8. Raporu yazdır
    print("\n" + "=" * 80)
    print("📋 FİNAL RAPOR")
    print("=" * 80)
    
    print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║                    ANALİZ ÖZETİ                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  • Analiz ID: {analysis_id}
║  • İncelenen Sembol Sayısı: {len(all_m5_data)}
║  • %2+ Yükseliş Yapan Sembol: {len(risers_2pct)}
║  • Oluşturulan Snapshot: {len(all_snapshots)}
║  • Tespit Edilen Ortak Desen: {len(common_patterns)}
╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    if common_patterns:
        print("\n🎯 EN GÜÇLÜ ORTAK DESENLER:")
        print("-" * 60)
        for i, pattern in enumerate(common_patterns[:5], 1):
            print(f"""
{i}. {pattern['pattern']}
   • Görülme: {pattern['count']} sembol (%{pattern['coverage_pct']:.1f})
   • Semboller: {', '.join(pattern['symbols'][:5])}{'...' if len(pattern['symbols']) > 5 else ''}
""")
    
    conn.close()
    
    return report


def _clean_for_json(obj):
    """JSON serialization için numpy ve diğer tipleri temizle"""
    if isinstance(obj, dict):
        return {k: _clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_clean_for_json(item) for item in obj]
    elif hasattr(obj, 'item'):  # numpy types
        return obj.item()
    elif isinstance(obj, (np.integer, np.floating)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj


def extract_pattern_tags(snapshot: dict) -> list[str]:
    """Snapshot'tan pattern taglerini çıkar"""
    tags = []
    
    price_info = snapshot.get("price_info", {})
    
    # RSI seviyeleri
    rsi = snapshot.get("momentum", {}).get("rsi")
    if rsi:
        if rsi >= 70:
            tags.append("rsi_overbought")
        elif rsi <= 30:
            tags.append("rsi_oversold")
        elif rsi >= 55:
            tags.append("rsi_bullish_zone")
        elif rsi <= 45:
            tags.append("rsi_bearish_zone")
    
    # Stochastic
    stoch = snapshot.get("momentum", {}).get("stochastic")
    if stoch and stoch.get("k"):
        if stoch["k"] >= 80:
            tags.append("stoch_overbought")
        elif stoch["k"] <= 20:
            tags.append("stoch_oversold")
    
    # ADX
    adx_data = snapshot.get("adx", {})
    if adx_data:
        adx_val = adx_data.get("adx", 0)
        if adx_val >= 25:
            tags.append("adx_strong_trend")
        elif adx_val >= 20:
            tags.append("adx_moderate_trend")
    
    # Trend alignment
    trend = snapshot.get("trend", {})
    alignment = trend.get("alignment", "unknown")
    if alignment == "bullish":
        tags.append("ema_bullish")
    elif alignment == "bearish":
        tags.append("ema_bearish")
    
    # Volume
    vol_info = snapshot.get("volume", {})
    mfi = vol_info.get("mfi")
    if mfi:
        if mfi >= 80:
            tags.append("mfi_overbought")
        elif mfi <= 20:
            tags.append("mfi_oversold")
    
    vol_ratio = price_info.get("volume_ratio", 1.0)
    if vol_ratio >= 1.5:
        tags.append("volume_spike_strong")
    elif vol_ratio >= 1.2:
        tags.append("volume_spike")
    
    # Choppiness
    chop = vol_info.get("choppiness")
    if chop:
        if chop <= 38.2:
            tags.append("chop_trending")
        elif chop >= 61.8:
            tags.append("chop_choppy")
    
    # Bollinger
    bb = snapshot.get("bollinger")
    if bb and bb.get("position") is not None:
        pos = bb["position"]
        if pos >= 0.9:
            tags.append("bb_upper_band")
        elif pos <= 0.1:
            tags.append("bb_lower_band")
    
    # Williams %R
    williams = snapshot.get("momentum", {}).get("williams_r")
    if williams:
        if williams >= -20:
            tags.append("williams_overbought")
        elif williams <= -80:
            tags.append("williams_oversold")
    
    # MACD
    macd = snapshot.get("momentum", {}).get("macd")
    if macd:
        if macd.get("histogram", 0) > 0:
            tags.append("macd_bullish")
        else:
            tags.append("macd_bearish")
    
    # SuperTrend
    st = snapshot.get("supertrend", {})
    if st:
        tags.append(f"supertrend_{st.get('trend', 'unknown')}")
        if st.get("direction_changed"):
            tags.append("supertrend_reversal")
    
    # Fisher Transform
    fisher = snapshot.get("fisher")
    if fisher and fisher.get("value"):
        fv = fisher["value"]
        if fv >= 2.0:
            tags.append("fisher_overbought")
        elif fv <= -2.0:
            tags.append("fisher_oversold")
        elif fv >= 1.0:
            tags.append("fisher_bullish_zone")
        elif fv <= -1.0:
            tags.append("fisher_bearish_zone")
    
    # ATR yüksekliği
    atr_pct = price_info.get("atr_pct")
    if atr_pct:
        if atr_pct >= 0.5:
            tags.append("atr_high")
        elif atr_pct <= 0.2:
            tags.append("atr_low")
    
    # Fiyat değişimi
    change_5 = price_info.get("change_5")
    if change_5:
        if change_5 >= 1.0:
            tags.append("price_rising")
        elif change_5 <= -1.0:
            tags.append("price_falling")
    
    # ROC
    roc = snapshot.get("momentum", {}).get("roc")
    if roc:
        if roc >= 5:
            tags.append("roc_strong_up")
        elif roc <= -5:
            tags.append("roc_strong_down")
    
    # CCI
    cci = snapshot.get("momentum", {}).get("cci")
    if cci:
        if cci >= 100:
            tags.append("cci_overbought")
        elif cci <= -100:
            tags.append("cci_oversold")
    
    # TRIX
    trix = snapshot.get("momentum", {}).get("trix")
    if trix:
        if trix.get("change", 0) > 0:
            tags.append("trix_bullish")
        else:
            tags.append("trix_bearish")
    
    # Vortex
    vortex = snapshot.get("vortex")
    if vortex:
        plus_vi = vortex.get("plus_vi", 0)
        minus_vi = vortex.get("minus_vi", 0)
        if plus_vi > minus_vi:
            tags.append("vortex_bullish")
        else:
            tags.append("vortex_bearish")
    
    # CMO
    cmo = snapshot.get("momentum", {}).get("cmo")
    if cmo:
        if cmo >= 25:
            tags.append("cmo_bullish")
        elif cmo <= -25:
            tags.append("cmo_bearish")
    
    return list(set(tags))


if __name__ == "__main__":
    report = analyze_m5_rise_patterns()
    
    # JSON olarak kaydet
    output_file = os.path.join(os.path.dirname(__file__), "..", "m5_rise_analysis_report.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n✅ Rapor kaydedildi: {output_file}")
