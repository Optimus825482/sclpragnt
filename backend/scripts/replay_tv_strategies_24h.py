"""24h replay: TradingView'dan seçilen en uygun 3 strateji — M1/M5/M15 koşumları.

Stratejiler (önceki taramanın "en uygun" listesinden), her TF'de AYNI parametrelerle
çalışır (TradingView'da aynı script'i farklı timeframe'e uygulamak gibi):
  1. MACKETINGS  — 4'lü EMA hiyerarşisi (20/30/100/200) + band retest/breakout,
                    stop %0.8 → BE %0.3/+%1.0 → TP %2.5, momentum kaybında band-cross çıkışı.
  2. RAPID       — Heikin-Ashi 3-barlık ivme sekansı + ADX>=25 kapısı,
                    ATR TP/SL + max kayıp tavanı (Plug) %3.
  3. VWAP_PULLBACK — HTF bias (5×TF: fiyat>VWAP & EMA9>EMA21) + LTF pullback & EMA9 reclaim.

Koşum: fisher_replay_24h.py çatısı — Binance TR public klines, per-sembol kronolojik
yürüyüş, sinyal barı kapanışında işlem, %0.15 tek-yön komisyon, 10.000 TL kağıt
cüzdan, pozisyon başına 1.000 TL. Tutma süreleri dakika cinsinden sabit
(M1:60dk, M5:12bar, M15:4bar; rapid alt-sınırı M1:15bar, M5:3bar, M15:1bar).
"""
import asyncio
import bisect
import datetime
import json
import os
import sys
from collections import defaultdict
from statistics import mean

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.binance_tr_public import historical_klines
from app.config import config

COMMISSION = 0.0015          # tek yön %0.15 (proje paper cüzdanla aynı)
POSITION_VALUE = 1000.0      # işlem başına ~1.000 TL
INITIAL_CASH = 10_000.0
HORIZON_HOURS = int(os.getenv("TV_REPLAY_HOURS", "24"))
HORIZON_MS = HORIZON_HOURS * 3_600_000
LOAD_DAYS = max(2, HORIZON_HOURS // 24 + 1)   # pencere + warmup günü

# TF başına: Binance interval adı, bar dakikası, warmup (dk), max hold (dk), rapid alt-sınırı (dk)
TIMEFRAMES = {
    "M1":  {"iv": "1m",  "min": 1,  "warmup_min": 240, "max_hold_min": 60, "rapid_min_hold_min": 15},
    "M5":  {"iv": "5m",  "min": 5,  "warmup_min": 240, "max_hold_min": 60, "rapid_min_hold_min": 15},
    "M15": {"iv": "15m", "min": 15, "warmup_min": 240, "max_hold_min": 60, "rapid_min_hold_min": 15},
}
# VWAP_PULLBACK için HTF bias: 5× baz TF (Binance interval adları)
HTF_BIAS_TF = {"M1": "5m", "M5": "15m", "M15": "30m"}

# Strateji parametreleri (tüm TF'lerde aynı — TV'da script parametreleri sabit kalır)
EMA_PERIODS = {"fast": 20, "mid": 30, "slow": 100, "trend": 200}
MACK_STOP_PCT = 0.008
MACK_BE_TRIGGER_PCT = 0.010
MACK_TP_PCT = 0.025
MACK_BE_PROTECT_PCT = 0.003
RAPID_ADX_MIN = 25.0
RAPID_PLUG_PCT = 0.03          # ATR stopun tavanı (maks kayıp %3)
RAPID_TP_ATR_MULT = 3.0
RAPID_SL_ATR_MULT = 1.5
VWAP_TP_ATR_MULT = 2.0
VWAP_SL_ATR_MULT = 1.0
TWIN_SUPERTREND_SL_PCT = 0.03   # giriş fiyatının %3 altı/üstü sabit stop

if os.getenv("TV_REPLAY_SYMBOLS"):
    SYMBOLS = [s.strip().upper() for s in os.getenv("TV_REPLAY_SYMBOLS").split(",") if s.strip()]
else:
    SYMBOLS = [str(s).upper() for s in config.SYMBOLS][:12]


# ---------------------------------------------------------------- teknik yardımcılar
def _ema_series(values, period):
    if len(values) < period:
        return [None] * len(values)
    alpha = 2 / (period + 1)
    out = [None] * (period - 1)
    ema = float(np.mean(values[:period]))
    out.append(ema)
    for v in values[period:]:
        ema = alpha * float(v) + (1 - alpha) * ema
        out.append(ema)
    return out


def _atr_series(highs, lows, closes, period=14):
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = len(c)
    out = [None] * n
    if n < period + 1:
        return out
    for i in range(period, n):
        window_h = h[i - period + 1:i + 1]
        window_l = l[i - period + 1:i + 1]
        prev_c = c[i - period:i]
        tr = np.maximum(window_h - window_l, np.maximum(np.abs(window_h - prev_c), np.abs(window_l - prev_c)))
        out[i] = float(np.mean(tr))
    return out


def _adx_series(highs, lows, closes, period=14):
    """Wilder ADX serisi (Rapid Scalper ADX kapısı için)."""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = len(c)
    out = [None] * n
    if n < 2 * period + 2:
        return out
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = np.zeros(n - 1)
    plus = np.zeros(n - 1)
    minus = np.zeros(n - 1)
    atr[period - 1] = np.mean(tr[:period])
    plus[period - 1] = np.mean(plus_dm[:period])
    minus[period - 1] = np.mean(minus_dm[:period])
    for i in range(period, n - 1):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        plus[i] = (plus[i - 1] * (period - 1) + plus_dm[i]) / period
        minus[i] = (minus[i - 1] * (period - 1) + minus_dm[i]) / period
    dxs = []
    for i in range(period - 1, n - 1):
        if atr[i] == 0:
            dxs.append(0.0)
            continue
        pdi = 100 * plus[i] / atr[i]
        mdi = 100 * minus[i] / atr[i]
        s = pdi + mdi
        if s == 0:
            dxs.append(0.0)
            continue
        dxs.append(100 * abs(pdi - mdi) / s)
    if len(dxs) >= period:
        adx = np.zeros(len(dxs))
        adx[period - 1] = np.mean(dxs[:period])
        for i in range(period, len(dxs)):
            adx[i] = (adx[i - 1] * (period - 1) + dxs[i]) / period
        for j in range(period - 1, len(dxs)):
            idx = period + j
            if idx < n:
                out[idx] = float(adx[j])
    return out


def _vwap_series(rows):
    """Session-VWAP serisi (kriptoda UTC gün sınırına göre sıfırlanır)."""
    n = len(rows)
    out = [None] * n
    day_cum_pv = 0.0
    day_cum_v = 0.0
    day_key = None
    for i, r in enumerate(rows):
        ts = int(r[0])
        key = datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        if key != day_key:
            day_key = key
            day_cum_pv = 0.0
            day_cum_v = 0.0
        tp = (float(r[2]) + float(r[3]) + float(r[4])) / 3
        v = float(r[5])
        day_cum_pv += tp * v
        day_cum_v += v
        if day_cum_v > 0:
            out[i] = day_cum_pv / day_cum_v
    return out


def _ha(rows):
    """Heikin-Ashi açılış/kapanış serileri."""
    opens = [None] * len(rows)
    closes = [None] * len(rows)
    prev_ha_open = None
    for i, r in enumerate(rows):
        o = float(r[1]); c = float(r[4])
        ha_close = (o + float(r[2]) + float(r[3]) + c) / 4
        ha_open = (prev_ha_open + ha_close) / 2 if prev_ha_open is not None else (o + c) / 2
        opens[i] = ha_open
        closes[i] = ha_close
        prev_ha_open = ha_open
    return opens, closes


def _smoothrng(x, t, m):
    """TradingView Twin Range Filter'ın smoothrng fonksiyonu (EMA tabanlı)."""
    wper = t * 2 - 1
    n = len(x)
    avrng = [0.0] * n
    ema_av = [None] * n
    if n >= 2:
        avrng[0] = 0.0
        avrng[1] = abs(x[1] - x[0])
        alpha = 2 / (t + 1)
        for i in range(2, n):
            avrng[i] = alpha * abs(x[i] - x[i - 1]) + (1 - alpha) * avrng[i - 1]
        if n >= wper:
            ema_av[wper - 1] = float(np.mean(avrng[:wper]))
            alpha_w = 2 / (wper + 1)
            for i in range(wper, n):
                ema_av[i] = alpha_w * avrng[i] + (1 - alpha_w) * ema_av[i - 1]
    return [v * m if v is not None else None for v in ema_av]


def _rngfilt(x, r):
    """TradingView Twin Range Filter'ın rngfilt fonksiyonu (feedback loop)."""
    n = len(x)
    out = [None] * n
    prev = None
    for i in range(n):
        if r[i] is None:
            out[i] = x[i] if i == 0 else out[i - 1]
            prev = out[i]
            continue
        if prev is None:
            out[i] = x[i]
        elif x[i] > prev:
            out[i] = x[i] - r[i] if x[i] - r[i] > prev else prev
        else:
            out[i] = x[i] + r[i] if x[i] + r[i] < prev else prev
        prev = out[i]
    return out


def twinrange_supertrend_signals(rows):
    """Twin Range Filter + SuperTrend(10,4) konfluansı.

    TwinRange tarafı: TradingView script'indeki longCond/shortCond ve CondIni geçişi.
    SuperTrend tarafı: trend -1→1 (buy) / 1→-1 (sell) dönüşü.
    Sinyal: long/upward>0 VE aynı mumda SuperTrend buy → 1,
            short/downward>0 VE aynı mumda SuperTrend sell → -1.
    Dönüş: (sig, trend) — trend SuperTrend trend serisidir (1/-1), çıkış için.
    """
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    hl2 = [(h + l) / 2 for h, l in zip(highs, lows)]
    n = len(closes)

    # --- Twin Range Filter: filt serisi ve upward/downward sayaçları
    smrng1 = _smoothrng(closes, 12, 4.0)
    smrng2 = _smoothrng(closes, 2, 2.0)
    smrng = [(a + b) / 2 if a is not None and b is not None else None
             for a, b in zip(smrng1, smrng2)]
    filt = _rngfilt(closes, smrng)
    upward = [0.0] * n
    downward = [0.0] * n
    for i in range(1, n):
        if filt[i] is None or filt[i - 1] is None:
            continue
        if filt[i] > filt[i - 1]:
            upward[i] = upward[i - 1] + 1
            downward[i] = 0.0
        elif filt[i] < filt[i - 1]:
            downward[i] = downward[i - 1] + 1
            upward[i] = 0.0
        else:
            upward[i] = upward[i - 1]
            downward[i] = downward[i - 1]

    # --- SuperTrend(10, 4): trend serisi ve dönüşler
    period = 10
    mult = 4.0
    atr = _atr_series(highs, lows, closes, period)
    trend = [1] * n
    up = [0.0] * n
    dn = [0.0] * n
    for i in range(1, n):
        if atr[i] is None:
            trend[i] = trend[i - 1]
            continue
        # TradingView: up = src - mult*atr; up := close[1] > up[1] ? max(up, up[1]) : up
        cur_up = hl2[i] - mult * atr[i]
        cur_dn = hl2[i] + mult * atr[i]
        prev_up = up[i - 1]
        prev_dn = dn[i - 1]
        up[i] = max(cur_up, prev_up) if closes[i - 1] > prev_up else cur_up
        dn[i] = min(cur_dn, prev_dn) if closes[i - 1] < prev_dn else cur_dn
        # trend := trend==-1 and close > dn[1] ? 1 : trend==1 and close < up[1] ? -1 : trend
        if trend[i - 1] == -1 and closes[i] > prev_dn:
            trend[i] = 1
        elif trend[i - 1] == 1 and closes[i] < prev_up:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]

    sig = [0] * n
    cond_ini = [0] * n
    for i in range(1, n):
        if filt[i] is None or filt[i - 1] is None:
            continue
        source_above = closes[i] > filt[i]
        source_below = closes[i] < filt[i]
        # script'teki longCond: (source>filt ve upward>0) — source vs source[1] yönü iki
        # kolda da var, sadeleşince "source>filt ve upward>0" olur.
        long_cond = source_above and upward[i] > 0
        short_cond = source_below and downward[i] > 0
        cond_ini[i] = 1 if long_cond else (-1 if short_cond else cond_ini[i - 1])
        # tek bar tetikleyici: CondIni önceki barda -1 iken bu barda 1'e dönünce long,
        # 1 iken -1'e dönünce short (script'in long/short tanımı).
        long_trigger = long_cond and cond_ini[i - 1] == -1
        short_trigger = short_cond and cond_ini[i - 1] == 1
        if long_trigger and trend[i] == 1 and trend[i - 1] == -1:
            sig[i] = 1
        elif short_trigger and trend[i] == -1 and trend[i - 1] == 1:
            sig[i] = -1
    return sig, trend


# ---------------------------------------------------------------- strateji sinyalleri
def macketings_signals(rows):
    """4'lü EMA hiyerarşisi + band retest/breakout. 1: long, -1: short, 0: yok."""
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    n = len(closes)
    ema_fast = _ema_series(closes, EMA_PERIODS["fast"])
    ema_mid = _ema_series(closes, EMA_PERIODS["mid"])
    ema_slow = _ema_series(closes, EMA_PERIODS["slow"])
    ema_trend = _ema_series(closes, EMA_PERIODS["trend"])
    sig = [0] * n
    for i in range(5, n):
        f, m, s, t = ema_fast[i], ema_mid[i], ema_slow[i], ema_trend[i]
        f1, m1, s1, t1 = ema_fast[i - 1], ema_mid[i - 1], ema_slow[i - 1], ema_trend[i - 1]
        if None in (f, m, s, t, f1, m1, s1, t1):
            continue
        if f > s > t and f1 <= s1:
            if lows[i] <= max(f, m) and closes[i] > max(f, m):
                sig[i] = 1
        elif f < s < t and f1 >= s1:
            if highs[i] >= min(f, m) and closes[i] < min(f, m):
                sig[i] = -1
    return sig


def rapid_scalper_signals(rows):
    """Heikin-Ashi 3-barlık ivme sekansı + ADX kapısı + renk flip önkoşulu."""
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    n = len(rows)
    ha_open, ha_close = _ha(rows)
    adx = _adx_series(highs, lows, closes, 14)
    sig = [0] * n

    def body_len(j):
        return abs(ha_close[j] - ha_open[j])

    for i in range(10, n):
        if adx[i] is None or adx[i] < RAPID_ADX_MIN:
            continue
        # uzun sekans: HA gövdesi pozitif, açılış low'a yakın, gövde büyüyor
        long_seq = all(
            ha_close[j] > ha_open[j]
            and ha_open[j] <= lows[j] * 1.0005
            and body_len(j) > body_len(j - 1) * 0.95
            and body_len(j) > 0
            for j in range(i - 2, i + 1)
        )
        if long_seq and ha_close[i - 3] < ha_open[i - 3]:
            sig[i] = 1
            continue
        short_seq = all(
            ha_close[j] < ha_open[j]
            and ha_open[j] >= highs[j] * 0.9995
            and body_len(j) > body_len(j - 1) * 0.95
            and body_len(j) > 0
            for j in range(i - 2, i + 1)
        )
        if short_seq and ha_close[i - 3] > ha_open[i - 3]:
            sig[i] = -1
    return sig


def vwap_pullback_signals(rows, htf_rows):
    """HTF bias (5×TF) + LTF pullback & EMA9 reclaim."""
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    n = len(closes)
    ema9 = _ema_series(closes, 9)
    ema21 = _ema_series(closes, 21)
    vwap = _vwap_series(rows)
    htf_closes = [float(r[4]) for r in htf_rows]
    htf_ema9 = _ema_series(htf_closes, 9)
    htf_ema21 = _ema_series(htf_closes, 21)
    htf_vwap = _vwap_series(htf_rows)
    sig = [0] * n
    for i in range(30, n):
        ts = int(rows[i][0])
        mi = None
        for j in range(len(htf_rows) - 1, -1, -1):
            if int(htf_rows[j][0]) <= ts:
                mi = j
                break
        if mi is None or mi < 30:
            continue
        if htf_vwap[mi] is None or htf_ema9[mi] is None or htf_ema21[mi] is None:
            continue
        long_bias = htf_closes[mi] > htf_vwap[mi] and htf_ema9[mi] > htf_ema21[mi]
        short_bias = htf_closes[mi] < htf_vwap[mi] and htf_ema9[mi] < htf_ema21[mi]
        if ema9[i] is None or ema21[i] is None or ema9[i - 1] is None:
            continue
        if long_bias and lows[i] <= ema9[i] and closes[i] > ema9[i] and closes[i - 1] <= ema9[i - 1]:
            sig[i] = 1
        elif short_bias and highs[i] >= ema9[i] and closes[i] < ema9[i] and closes[i - 1] >= ema9[i - 1]:
            sig[i] = -1
    return sig


# ---------------------------------------------------------------- replay motoru
class TVReplay:
    def __init__(self, symbols, tf):
        self.symbols = symbols
        self.tf = tf
        self.bar_min = TIMEFRAMES[tf]["min"]
        self.iv = TIMEFRAMES[tf]["iv"]
        self.warmup_bars = max(30, TIMEFRAMES[tf]["warmup_min"] // self.bar_min)
        self.max_hold_bars = TIMEFRAMES[tf]["max_hold_min"] // self.bar_min
        self.rapid_min_hold_bars = max(1, TIMEFRAMES[tf]["rapid_min_hold_min"] // self.bar_min)
        self.htf_tf = HTF_BIAS_TF[tf]
        self.load_days_override = None
        self.data = {}

    async def load(self):
        loaded = 0
        days = self.load_days_override or LOAD_DAYS
        for symbol in self.symbols:
            try:
                rows = await historical_klines(symbol, self.iv, days)
                htf_rows = await historical_klines(symbol, self.htf_tf, days)
                if len(rows) < self.warmup_bars + 24:
                    print(f"  {symbol}: yetersiz {self.tf} ({len(rows)})")
                    continue
                self.data[symbol] = {"rows": rows, "htf": htf_rows}
                loaded += 1
            except Exception as e:
                print(f"  {symbol}: veri hatası {type(e).__name__}: {str(e)[:120]}")
                continue
            await asyncio.sleep(0.2)   # Binance TR rate-limit nefes payı
        return loaded

    def run(self, strategy, use_be=False, allowed=None, start_ms=None, end_ms=None):
        trades = []
        cash = INITIAL_CASH
        open_pos = {}
        if end_ms is None:
            end_ms = max(int(d["rows"][-1][0]) for d in self.data.values())
        if start_ms is None:
            start_ms = end_ms - HORIZON_MS
        if allowed is None:
            allowed = set(self.data.keys())

        signals = {}
        trends = {}
        ts_axis = {}
        for symbol, d in self.data.items():
            rows = d["rows"]
            ts_axis[symbol] = [int(r[0]) for r in rows]
            if strategy == "macketings":
                signals[symbol] = macketings_signals(rows)
            elif strategy == "rapid":
                signals[symbol] = rapid_scalper_signals(rows)
            elif strategy == "vwap_pullback":
                signals[symbol] = vwap_pullback_signals(rows, d["htf"])
            elif strategy == "twin_supertrend":
                sig_series, trend_series = twinrange_supertrend_signals(rows)
                signals[symbol] = sig_series
                trends[symbol] = trend_series

        all_times = sorted({int(r[0]) for d in self.data.values() for r in d["rows"]
                            if start_ms <= int(r[0]) and int(r[0]) + 59_999 <= end_ms})

        for bar_ms in all_times:
            for symbol, d in self.data.items():
                if symbol not in allowed:
                    continue
                rows = d["rows"]
                axis = ts_axis[symbol]
                # dikotomi: bar_ms'e karşılık gelen son mum indeksi (O(log n))
                k = bisect.bisect_right(axis, bar_ms) - 1
                if k < 0:
                    continue
                idx = k
                if int(rows[idx][0]) + 59_999 > bar_ms + 59_999:
                    continue
                sig = signals[symbol][idx] if idx < len(signals[symbol]) else 0
                price = float(rows[idx][4])
                pos = open_pos.get(symbol)

                # 1) açık pozisyon yönetimi
                if pos:
                    hold = idx - pos["entry_idx"]
                    pnl_pct = (price / pos["entry"] - 1) * (1 if pos["side"] == 1 else -1)
                    exit_reason = None
                    if strategy == "macketings":
                        if pnl_pct <= -MACK_STOP_PCT:
                            exit_reason = "stop"
                        elif pnl_pct >= MACK_BE_TRIGGER_PCT:
                            ema_fast = _ema_series([float(r[4]) for r in rows[:idx + 1]], EMA_PERIODS["fast"])
                            ema_slow = _ema_series([float(r[4]) for r in rows[:idx + 1]], EMA_PERIODS["slow"])
                            f = ema_fast[-1]; s = ema_slow[-1]
                            f1 = ema_fast[-2] if len(ema_fast) > 1 else None
                            s1 = ema_slow[-2] if len(ema_slow) > 1 else None
                            if pos["side"] == 1 and f is not None and s is not None and f1 is not None and s1 is not None and f < s and f1 >= s1:
                                exit_reason = "band_cross"
                            elif pos["side"] == -1 and f is not None and s is not None and f1 is not None and s1 is not None and f > s and f1 <= s1:
                                exit_reason = "band_cross"
                            elif pnl_pct >= MACK_TP_PCT:
                                exit_reason = "tp"
                        if exit_reason is None and pnl_pct >= MACK_BE_PROTECT_PCT:
                            if pos["side"] == 1 and price <= pos["be_price"]:
                                exit_reason = "be"
                            elif pos["side"] == -1 and price >= pos["be_price"]:
                                exit_reason = "be"
                        if exit_reason is None and hold >= self.max_hold_bars:
                            exit_reason = "max_hold"
                    elif strategy == "twin_supertrend":
                        # SuperTrend trend dönüşü (sell/buy) gelince çık — TwinRange'den bağımsız
                        trend_series = trends.get(symbol)
                        if trend_series is not None:
                            if (pos["side"] == 1 and idx < len(trend_series)
                                    and trend_series[idx] == -1):
                                exit_reason = "supertrend_exit"
                            elif (pos["side"] == -1 and idx < len(trend_series)
                                    and trend_series[idx] == 1):
                                exit_reason = "supertrend_exit"
                        # sabit stop: giriş fiyatının %3 altı/üstü
                        if exit_reason is None:
                            stop_price = pos["entry"] * (1 - TWIN_SUPERTREND_SL_PCT
                                                         if pos["side"] == 1
                                                         else 1 + TWIN_SUPERTREND_SL_PCT)
                            if pos["side"] == 1 and price <= stop_price:
                                exit_reason = "stop"
                            elif pos["side"] == -1 and price >= stop_price:
                                exit_reason = "stop"
                        if exit_reason is None and hold >= self.max_hold_bars:
                            exit_reason = "max_hold"
                    elif strategy == "rapid":
                        atr = _atr_series([float(r[2]) for r in rows[:idx + 1]],
                                          [float(r[3]) for r in rows[:idx + 1]],
                                          [float(r[4]) for r in rows[:idx + 1]], 14)[-1]
                        if atr is None:
                            atr = price * 0.01
                        sl_dist = max(atr * RAPID_SL_ATR_MULT, price * RAPID_PLUG_PCT)
                        tp_dist = atr * RAPID_TP_ATR_MULT
                        if pos["side"] == 1:
                            if price <= pos["entry"] - sl_dist:
                                exit_reason = "stop"
                            elif price >= pos["entry"] + tp_dist:
                                exit_reason = "tp"
                        else:
                            if price >= pos["entry"] + sl_dist:
                                exit_reason = "stop"
                            elif price <= pos["entry"] - tp_dist:
                                exit_reason = "tp"
                        if exit_reason is None and hold >= self.rapid_min_hold_bars:
                            exit_reason = "max_hold"
                    elif strategy == "vwap_pullback":
                        atr = _atr_series([float(r[2]) for r in rows[:idx + 1]],
                                          [float(r[3]) for r in rows[:idx + 1]],
                                          [float(r[4]) for r in rows[:idx + 1]], 14)[-1]
                        if atr is None:
                            atr = price * 0.01
                        if pos["side"] == 1:
                            if price <= pos["entry"] - atr * VWAP_SL_ATR_MULT:
                                exit_reason = "stop"
                            elif price >= pos["entry"] + atr * VWAP_TP_ATR_MULT:
                                exit_reason = "tp"
                        else:
                            if price >= pos["entry"] + atr * VWAP_SL_ATR_MULT:
                                exit_reason = "stop"
                            elif price <= pos["entry"] - atr * VWAP_TP_ATR_MULT:
                                exit_reason = "tp"
                        # BE koruması: +0.3 ATR kâr gördüyse fiyat geri dönüp girişi geçerse kapat
                        if use_be and exit_reason is None and pnl_pct >= 0.002:
                            be_level = pos["entry"] * (1.002 if pos["side"] == 1 else (1 - 0.002))
                            if pos["side"] == 1 and price <= be_level:
                                exit_reason = "be"
                            elif pos["side"] == -1 and price >= be_level:
                                exit_reason = "be"
                        if exit_reason is None and hold >= self.max_hold_bars:
                            exit_reason = "max_hold"

                    if exit_reason:
                        proceeds = pos["qty"] * price
                        fee = proceeds * COMMISSION
                        gross = pos["qty"] * (price - pos["entry"]) if pos["side"] == 1 else pos["qty"] * (pos["entry"] - price)
                        pnl = gross - fee
                        trades.append({"symbol": symbol, "action": "close", "price": price,
                                       "at_ms": bar_ms, "hour": datetime.datetime.fromtimestamp(bar_ms / 1000).hour,
                                       "pnl": pnl, "reason": exit_reason, "side": pos["side"],
                                       "entry": pos["entry"],
                                       "hold_bars": (idx - pos["entry_idx"]),
                                       "hold_min": (idx - pos["entry_idx"]) * self.bar_min})
                        cash += proceeds - fee
                        open_pos.pop(symbol, None)

                # 2) yeni giriş
                if sig != 0 and symbol not in open_pos:
                    if cash < POSITION_VALUE:
                        continue
                    qty = POSITION_VALUE / price
                    cash -= POSITION_VALUE
                    open_pos[symbol] = {"entry": price, "qty": qty, "order_value": POSITION_VALUE,
                                        "entry_idx": idx, "side": sig,
                                        "be_price": price * (1.003 if sig == 1 else (1 - 0.003))}
                    trades.append({"symbol": symbol, "action": "open", "price": price,
                                   "at_ms": bar_ms, "hour": datetime.datetime.fromtimestamp(bar_ms / 1000).hour,
                                   "side": sig})

        # kapanmamış pozisyonları son fiyatla kapat
        for symbol, pos in list(open_pos.items()):
            last_close = float(self.data[symbol]["rows"][-1][4])
            proceeds = pos["qty"] * last_close
            fee = proceeds * COMMISSION
            gross = pos["qty"] * (last_close - pos["entry"]) if pos["side"] == 1 else pos["qty"] * (pos["entry"] - last_close)
            trades.append({"symbol": symbol, "action": "close", "price": last_close,
                           "at_ms": end_ms, "hour": datetime.datetime.fromtimestamp(end_ms / 1000).hour,
                           "pnl": gross - fee, "reason": "unrealized_close",
                           "side": pos["side"], "entry": pos["entry"], "hold_bars": 0, "hold_min": 0})
            cash += proceeds - fee
        return {"final_cash": cash, "trades": trades}


def summarize(label, result):
    trades = result["trades"]
    closed = [t for t in trades if t["action"] == "close"]
    opened = [t for t in trades if t["action"] == "open"]
    net = sum(t["pnl"] for t in closed)
    wins = [t for t in closed if t["pnl"] > 0]
    print(f"\n=== {label} ===")
    if not closed:
        print("işlem yok")
        return
    print(f"açılış: {len(opened)} | kapanış: {len(closed)} | net PnL {net:+.1f} TL | "
          f"win %{len(wins) / len(closed) * 100:.0f}")
    by_reason = defaultdict(list)
    for t in closed:
        by_reason[t["reason"]].append(t["pnl"])
    for reason, pnls in sorted(by_reason.items()):
        print(f"  {reason}: n={len(pnls)} ort {mean(pnls):+.2f} TL | toplam {sum(pnls):+.1f} TL")
    print(f"  ort hold: {mean(t['hold_min'] for t in closed):.0f} dk | "
          f"en kötü {min(t['pnl'] for t in closed):+.1f} TL | en iyi {max(t['pnl'] for t in closed):+.1f} TL")
    by_sym = defaultdict(list)
    for t in closed:
        by_sym[t["symbol"]].append(t["pnl"])
    sym_line = ", ".join(f"{s}:{sum(v):+.0f}TL({len(v)})" for s, v in sorted(by_sym.items()))
    print(f"  semboller: {sym_line}")


async def main():
    tf_list = os.getenv("TV_REPLAY_TFS", "M5,M15").split(",")
    tf_list = [tf.strip().upper() for tf in tf_list if tf.strip().upper() in TIMEFRAMES]
    out_all = {"window_hours": 24, "symbols": SYMBOLS, "commission_pct": COMMISSION * 100,
               "position_value_tl": POSITION_VALUE, "timeframes": {}}
    for tf in tf_list:
        replay = TVReplay(SYMBOLS, tf)
        loaded = await replay.load()
        print(f"\n[{tf}] yüklü sembol: {loaded}/{len(SYMBOLS)}")
        if loaded == 0:
            print("veri yok — atlanıyor")
            continue
        results = {}
        for strat in ["macketings", "rapid", "vwap_pullback", "twin_supertrend"]:
            r = replay.run(strat)
            results[strat] = r
            summarize(f"{tf} / {strat.upper()}", r)
        out_all["timeframes"][tf] = {
            "bar_min": replay.bar_min,
            "results": {k: {"final_cash": v["final_cash"], "trades": v["trades"]} for k, v in results.items()},
        }
    with open("../work/replay_tv_strategies_24h.json", "w", encoding="utf-8") as f:
        json.dump(out_all, f, ensure_ascii=False, indent=1, default=str)
    print("\nrapor: ../work/replay_tv_strategies_24h.json")

    # M5 VWAP-Pullback A/B: baz → +BE koruması → +BE+sembol kalite filtresi
    if "M5" in out_all["timeframes"]:
        replay = TVReplay(SYMBOLS, "M5")
        loaded = await replay.load()
        print(f"\n[M5 A/B] yüklü sembol: {loaded}/{len(SYMBOLS)}")
        base = replay.run("vwap_pullback")
        with_be = replay.run("vwap_pullback", use_be=True)
        # sembol kalite filtresi: baz koşumda kapanmış işlemlerde ortalama PnL negatif
        # olan sembolleri engelle (velocity VELOCITY_SYMBOL_QUALITY_FILTER mantığı)
        by_sym = defaultdict(list)
        for t in base["trades"]:
            if t["action"] == "close":
                by_sym[t["symbol"]].append(t["pnl"])
        allowed = {s for s, pnls in by_sym.items() if mean(pnls) >= 0}
        if not allowed:
            allowed = set(by_sym.keys())  # hepsi negatifse filtresiz koş (0 sembol kalmasın)
        print(f"  kalite filtresi: {len(allowed)}/{len(by_sym)} sembol açık "
              f"({', '.join(sorted(allowed))})")
        with_be_q = replay.run("vwap_pullback", use_be=True, allowed=allowed)
        for label, r in [("BAZ (M5 vwap_pullback)", base),
                         ("+BE koruması", with_be),
                         ("+BE + sembol kalite filtresi", with_be_q)]:
            summarize(f"M5 VWAP / {label}", r)

    # 7 günlük OOS A/B: ilk 3 gün öğren (sembol kalitesi), son 4 günde uygula
    if os.getenv("TV_REPLAY_7D", "1") == "1" and "M5" in out_all["timeframes"]:
        print("\n[M5 7G OOS]")
        replay = TVReplay(SYMBOLS, "M5")
        replay.load_days_override = 8   # 7 gün + warmup
        loaded = await replay.load()
        print(f"  yüklü sembol: {loaded}/{len(SYMBOLS)}")
        if loaded:
            data_end = max(int(d["rows"][-1][0]) for d in replay.data.values())
            day_ms = 24 * 3_600_000
            # 7 günlük pencere (warmup verinin başında)
            win_start = data_end - 7 * day_ms
            # öğrenme penceresi: 7 günün ilk 3 günü
            learn_end = win_start + 3 * day_ms
            test_start = learn_end
            test_end = data_end

            # öğrenme koşumu: kalite sinyali için sembol başına ortalama PnL
            learn = replay.run("vwap_pullback", start_ms=win_start, end_ms=learn_end)
            learn_sym = defaultdict(list)
            for t in learn["trades"]:
                if t["action"] == "close":
                    learn_sym[t["symbol"]].append(t["pnl"])
            n_learn = {s: len(v) for s, v in learn_sym.items()}
            quality_ok = {s for s, pnls in learn_sym.items() if mean(pnls) >= 0}
            print(f"  öğrenme penceresi: {len(learn_sym)} sembol, "
                  f"kalite filtresi {len(quality_ok)}/{len(learn_sym)} sembol açık")
            if len(quality_ok) < 2:
                print("  uyarı: kalite filtresi 2'den az sembol seçti — filtresiz koşumla karşılaştır")

            # test koşumları: OOS penceresinde
            oos_base = replay.run("vwap_pullback", start_ms=test_start, end_ms=test_end)
            oos_q = replay.run("vwap_pullback", start_ms=test_start, end_ms=test_end, allowed=quality_ok)
            # aynı anda TÜM 7 günlük pencere koşumları (raporlama)
            full_base = replay.run("vwap_pullback", start_ms=win_start, end_ms=test_end)
            full_q = replay.run("vwap_pullback", start_ms=win_start, end_ms=test_end, allowed=quality_ok)
            for label, r in [("OOS BAZ (son 4g)", oos_base),
                             ("OOS + kalite filtresi (son 4g)", oos_q),
                             ("7G BAZ (tüm pencere)", full_base),
                             ("7G + kalite filtresi (tüm pencere)", full_q)]:
                summarize(f"M5 VWAP / {label}", r)
            # kalite filtresinin OOS etkisini net göster
            oos_base_closed = [t for t in oos_base["trades"] if t["action"] == "close"]
            oos_q_closed = [t for t in oos_q["trades"] if t["action"] == "close"]
            print(f"\n  OOS fark: baz {sum(t['pnl'] for t in oos_base_closed):+.1f} TL "
                  f"({len(oos_base_closed)} işlem) → filtrelı {sum(t['pnl'] for t in oos_q_closed):+.1f} TL "
                  f"({len(oos_q_closed)} işlem)")


if __name__ == "__main__":
    asyncio.run(main())
