"""Stochastic RSI ve "ön sinyal" (çevrimdışı araştırma; canlı koda BAĞLANMAZ; ağ/DB yok; vektörel numpy).

Tanım (grafikteki ile aynı olmalı):
    RSI   = Wilder RSI(close, 14)           (ilk 14 değişimin ortalaması tohum, sonra (avg·13 + x)/14; kayıp 0 → 100, ikisi de 0 → 50)
    stoch = 100·(RSI − min(RSI, 14)) / (max(RSI, 14) − min(RSI, 14));   aralık 0 ise 0
    K     = SMA(stoch, 3)
    D     = SMA(K, 3)
Hiçbir değer, o bardan sonraki veriye bakmaz (nedensel). Yeterli veri yoksa NaN.

Ön sinyal ("ön sinyal") bar i'nin KAPANIŞINDA: K[i-1] ≤ D[i-1] ve K[i] > D[i] ve K[i-1] < seviye (20 ya da 30) ve çekirdek (RQK) i'de düşüş (kırmızı).
Not: `app/technical_analysis._stoch_rsi` aralık 0 iken 50 döner; burada (istenen tanım) 0.
"""
from __future__ import annotations

import numpy as np

try:  # scipy varsa IIR süzgeç; yoksa saf numpy döngüsü (aynı sonuç)
    from scipy.signal import lfilter as _lfilter
except Exception:  # pragma: no cover
    _lfilter = None


def _wilder_rma(x: np.ndarray, p: int) -> np.ndarray:
    """out[p-1] = mean(x[:p]); out[i] = (out[i-1]·(p-1) + x[i]) / p. x tamamen sonlu varsayılır. Öncesi NaN."""
    n = len(x)
    out = np.full(n, np.nan)
    if n < p:
        return out
    seed = float(np.mean(x[:p]))
    out[p - 1] = seed
    if n > p:
        a = 1.0 / p
        if _lfilter is not None:
            z, _ = _lfilter([a], [1.0, -(1.0 - a)], x[p:], zi=[(1.0 - a) * seed])
            out[p:] = z
        else:  # pragma: no cover
            prev = seed
            for i in range(p, n):
                prev = (prev * (p - 1) + x[i]) / p
                out[i] = prev
    return out


def rsi_wilder(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder RSI; out[i] i ≥ period için dolu (ilk `period` değişim tohum). Sonlu olmayan kapanış varsa o noktadan sonrası güvenilmez."""
    c = np.asarray(close, dtype=float)
    n = len(c)
    out = np.full(n, np.nan)
    if n <= period:
        return out
    d = np.diff(c)
    ag = _wilder_rma(np.where(d > 0, d, 0.0), period)
    al = _wilder_rma(np.where(d < 0, -d, 0.0), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(al == 0, np.where(ag > 0, 100.0, 50.0), 100.0 - 100.0 / (1.0 + ag / al))
    r = np.where(np.isfinite(ag) & np.isfinite(al), r, np.nan)
    out[1:] = r
    return out


def _rolling(x: np.ndarray, n: int, fn) -> np.ndarray:
    """out[i] = fn(x[i-n+1..i]); pencere tam değilse ya da içinde NaN varsa NaN."""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = fn(np.lib.stride_tricks.sliding_window_view(x, n), axis=1)
    return out


def sma(x: np.ndarray, n: int) -> np.ndarray:
    """Basit hareketli ortalama (NaN içeren pencere → NaN)."""
    return _rolling(np.asarray(x, dtype=float), n, np.mean)


def stoch_rsi(close: np.ndarray, rsi_len: int = 14, stoch_len: int = 14, k_len: int = 3, d_len: int = 3) -> dict[str, np.ndarray]:
    """Dönüş: rsi, stoch, k, d (hepsi close ile aynı uzunlukta, 0–100)."""
    rsi = rsi_wilder(close, rsi_len)
    lo = _rolling(rsi, stoch_len, np.min)
    hi = _rolling(rsi, stoch_len, np.max)
    rng = hi - lo
    with np.errstate(divide="ignore", invalid="ignore"):
        st = np.where(rng > 0, 100.0 * (rsi - lo) / np.where(rng > 0, rng, 1.0), 0.0)
    st = np.where(np.isfinite(rng), st, np.nan)
    k = sma(st, k_len)
    d = sma(k, d_len)
    return {"rsi": rsi, "stoch": st, "k": k, "d": d}


def cross_up(k: np.ndarray, d: np.ndarray) -> np.ndarray:
    """K[i-1] ≤ D[i-1] ve K[i] > D[i] (i-1 ve i'de dolu)."""
    out = np.zeros(len(k), dtype=bool)
    if len(k) > 1:
        out[1:] = (k[:-1] <= d[:-1]) & (k[1:] > d[1:])      # NaN karşılaştırmaları False verir
    return out


def pre_signal(k: np.ndarray, d: np.ndarray, bearish: np.ndarray, level: float = 20.0) -> np.ndarray:
    """Ön sinyal: aşağıdan (K[i-1] < seviye) yukarı K/D kesişimi ve çekirdek i'de düşüşte (bearish[i] True)."""
    k = np.asarray(k, dtype=float)
    out = cross_up(k, d)
    prev_low = np.zeros(len(k), dtype=bool)
    if len(k) > 1:
        prev_low[1:] = k[:-1] < level
    return out & prev_low & np.asarray(bearish, dtype=bool)
