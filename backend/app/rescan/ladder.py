"""Merdiven yükseliş dedektörü — çevrimdışı PROTOTİP (2026-10-17, rejim kalkanı analizi).

Canlı Hız Avcısı 1 dk barlarda 3-5 barlık SIÇRAMA (ret3/ret5/ATR) arar; sıçramasız, mum mum
yükselen "merdiven" hareketleri ancak 20-25 dk sonra, RSI/MFI doyduktan sonra görür (LUNATRY
17 Ekim 01:05-01:53 örneği). Bu modül 5 dk barlarda şunu arar:

    son `n_bars` barın her biri önceki bara göre DAHA YÜKSEK KAPANIŞ ve en az eşit DİP
    (higher close + higher/equal low) · `n_bars` barlık kümülatif kazanç [gain_min, gain_max]
    (henüz patlamamış) · bar hacmi önceki 20 barın ortalamasına göre ≥ vol_min · RSI14(5m) ≤
    rsi_max (doymadan) · 24 saat quote hacmi ≥ min_quote_24h (havuz likiditesi).

Saf numpy; ağ/DB yok. Canlı koda bağlanmaz — önce rescan ile ölçülür.
"""
from __future__ import annotations

import numpy as np

# Dizi kolonları: open_time(ms), open, high, low, close, volume, quote_volume
COL_OT, COL_O, COL_H, COL_L, COL_C, COL_V, COL_QV = range(7)
BAR_MS = 300_000


def rolling_sum(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1:] = c[n:] - c[:-n]
    return out


def rsi_wilder(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder RSI (kanonik `_rsi` ile aynı yumuşatma); ilk `period` değer NaN."""
    n = len(close)
    out = np.full(n, np.nan)
    if n <= period:
        return out
    d = np.diff(close)
    gain = np.where(d > 0, d, 0.0); loss = np.where(d < 0, -d, 0.0)
    ag = float(gain[:period].mean()); al = float(loss[:period].mean())
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period, n - 1):
        ag = (ag * (period - 1) + gain[i]) / period
        al = (al * (period - 1) + loss[i]) / period
        out[i + 1] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def ladder_run_length(close: np.ndarray, low: np.ndarray) -> np.ndarray:
    """run[i] = i'de biten ardışık (yüksek kapanış ∧ dip ≥ önceki dip) bar sayısı."""
    n = len(close)
    up = np.zeros(n, dtype=bool)
    up[1:] = (close[1:] > close[:-1]) & (low[1:] >= low[:-1])
    run = np.zeros(n, dtype=np.int32)
    for i in range(1, n):
        run[i] = run[i - 1] + 1 if up[i] else 0
    return run


def ladder_signals(arr: np.ndarray, *, n_bars: int = 3, gain_min: float = 0.8, gain_max: float = 4.0,
                   vol_min: float = 1.0, rsi_max: float = 75.0, min_quote_24h: float = 5_000_000.0,
                   cooldown_bars: int = 12) -> np.ndarray:
    """Sinyal veren bar indeksleri (bar KAPANDIKTAN sonra; giriş = o barın kapanışı).

    cooldown_bars: aynı sembolde sinyaller arası en az bar (12 = 60 dk)."""
    c = arr[:, COL_C]; l = arr[:, COL_L]; v = arr[:, COL_V]; qv = arr[:, COL_QV]
    n = len(c)
    if n < max(30, n_bars + 21):
        return np.zeros(0, dtype=np.int64)
    run = ladder_run_length(c, l)
    gain = np.full(n, np.nan)
    gain[n_bars:] = (c[n_bars:] / np.where(c[:-n_bars] > 0, c[:-n_bars], np.nan) - 1) * 100
    vol20_prev = np.full(n, np.nan)
    s20 = rolling_sum(np.nan_to_num(v, nan=0.0), 20)
    vol20_prev[1:] = s20[:-1] / 20.0
    with np.errstate(divide="ignore", invalid="ignore"):
        volr = np.where(vol20_prev > 0, v / vol20_prev, np.nan)
    rsi = rsi_wilder(c, 14)
    qv24 = rolling_sum(np.nan_to_num(qv, nan=0.0), 288)
    cond = ((run >= n_bars) & (gain >= gain_min) & (gain <= gain_max) & (volr >= vol_min)
            & (rsi <= rsi_max) & (qv24 >= min_quote_24h))
    cond[: max(288, 21)] = False
    idx = np.flatnonzero(cond)
    if cooldown_bars <= 1 or len(idx) == 0:
        return idx
    kept = []
    last = -10 ** 9
    for i in idx:
        if i - last >= cooldown_bars:
            kept.append(int(i)); last = int(i)
    return np.array(kept, dtype=np.int64)


def signal_time_ms(arr: np.ndarray, i: int) -> int:
    """Sinyal anı = barın kapanış zamanı (open_time + 5 dk)."""
    return int(arr[i, COL_OT]) + BAR_MS
