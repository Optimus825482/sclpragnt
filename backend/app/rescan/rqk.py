"""Rational Quadratic Kernel (RQK) göstergesi — grafik (frontend) hesabının vektörel numpy portu (2026-10-17, çevrimdışı).

Canlı koda bağlanmaz; ağ/DB yok. `scripts/rqk_study.py` kullanır.

Kaynak: `frontend/app/charts/IndicatorPicker.tsx` → `SLING_SHOT_ENTRY.calculate` (varsayılan h = 8, r = 2, smoothColors = false).

Varyant A (uygulama, BİREBİR)
    yhat(i) = Σ_{k=0}^{min(h, i+1)-1} close[i-k]·w(k) / Σ w(k),   w(k) = (1 + k² / (h²·2·r))^(-r)
    Toplam YALNIZ son h muma uzanır (uygulama kesiyor); h aynı zamanda bant genişliği. yhat(0) = null (endIdx < 1).
    yhat2(i) = yhat(max(0, i-2))  (smoothColors için 2 bar gecikmeli)
    Renk (smoothColors = false), prev1 = yhat(i-1), prev2 = yhat(i-2):
        prev1 ve prev2 doluysa : bullish = prev1 < v   veya   (prev2 > prev1 ve not prev1 > v)
        yalnız prev1 doluysa   : bullish = prev1 < v
        ikisi de boşsa         : bullish = True
    Renk (smoothColors = true) : bullish = yhat2 != null ve yhat2 > v   (uygulama böyle — işaret ters görünüyor, aynen taşındı)
    AL işareti = bearish → bullish renk değişimi.

Varyant B (kanonik jdehorty Nadaraya-Watson RQK'ya yakın)
    Pencere x0 = 25 bar (k = 0..x0-1), bant genişliği h (pencereden BAĞIMSIZ), aynı ağırlık formülü.
    Renk: bullish = yhat(i-1) < yhat(i)  (oran-tabanlı; eşitlikte bearish — Pine'daki isBullishRate).

Not: zayıf nokta kayıtları — kapanışı sonlu olmayan barlar uygulamadaki gibi toplamdan atlanır (ağırlık da düşer).
"""
from __future__ import annotations

import numpy as np

DEFAULT_H = 8
DEFAULT_R = 2.0
CANON_WINDOW = 25


def rq_weights(n: int, h: float, r: float) -> np.ndarray:
    """w(k) = (1 + k²/(h²·2·r))^(-r),  k = 0..n-1."""
    k = np.arange(n, dtype=float)
    return (1.0 + (k * k) / (float(h) ** 2 * 2.0 * float(r))) ** (-float(r))


def _yhat(close: np.ndarray, taps: int, h: float, r: float) -> np.ndarray:
    """yhat(i) = Σ_{k<taps} w(k)·close[i-k] / Σ w(k) (yalnız sonlu kapanışlar), yhat(0) = NaN.

    Toplama SIRASI uygulamayla aynı (k = 0, 1, 2, … sırayla, `price·w` çarpımı sonra eklenir) → bit-düzeyinde aynı sonuç;
    bu önemli: düz (eşit kapanışlı) serilerde yhat(i) == yhat(i-1) eşitliği renk kuralını belirler ve farklı toplama sırası
    (ör. lfilter) 1 ulp farkla rengi değiştirir."""
    c = np.asarray(close, dtype=float)
    n = len(c)
    if n == 0:
        return np.full(0, np.nan)
    w = rq_weights(taps, h, r)
    num = np.zeros(n)
    den = np.zeros(n)
    for k in range(min(taps, n)):
        ck = c[: n - k]
        ok = np.isfinite(ck)
        num[k:] = num[k:] + np.where(ok, ck * w[k], 0.0)
        den[k:] = den[k:] + np.where(ok, w[k], 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den > 0, num / den, np.nan)
    out[0] = np.nan                     # calculateYhat(endIdx < 1) → null
    return out


def yhat_app(close: np.ndarray, h: float = DEFAULT_H, r: float = DEFAULT_R) -> np.ndarray:
    """Varyant A: pencere = son `max(3, h)` bar (uygulama `h`'ı tamsayıya çevirmez; h kesirliyse döngü ceil(h) bar döner)."""
    hh = max(3.0, float(h))
    taps = int(np.ceil(hh))             # JS: for (i = 0; i < min(h, endIdx+1); i++) → i = 0..ceil(h)-1
    return _yhat(close, taps, hh, max(0.25, float(r)))


def yhat_canon(close: np.ndarray, h: float = DEFAULT_H, r: float = DEFAULT_R, window: int = CANON_WINDOW) -> np.ndarray:
    """Varyant B: pencere sabit `window` bar, bant genişliği h."""
    return _yhat(close, int(window), max(3.0, float(h)), max(0.25, float(r)))


def lag(x: np.ndarray, k: int) -> np.ndarray:
    """out[i] = x[i-k] (başı NaN)."""
    out = np.full(len(x), np.nan)
    if 0 < k < len(x):
        out[k:] = x[: len(x) - k]
    elif k == 0:
        out[:] = x
    return out


def colors_app(y: np.ndarray, smooth: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Uygulama renk kuralı. Dönüş: (bull[n] bool, valid[n] bool). valid = yhat(i) dolu (rengi çizilir)."""
    n = len(y)
    valid = np.isfinite(y)
    bull = np.zeros(n, dtype=bool)
    if n == 0:
        return bull, valid
    if smooth:
        # yhat2(i) = yhat(max(0, i-2)); yhat(0) = null → i = 0,1,2 için null
        y2 = lag(y, 2)
        y2[:2] = np.nan
        bull = np.isfinite(y2) & (y2 > y)
        return bull & valid, valid
    p1 = lag(y, 1); p2 = lag(y, 2)
    h1 = np.isfinite(p1); h2 = np.isfinite(p2)
    with np.errstate(invalid="ignore"):
        is_bull_now = p1 < y
        is_bear_now = p1 > y
        was_bear = p2 > p1
        full = is_bull_now | (was_bear & ~is_bear_now)
        only1 = p1 < y
    bull = np.where(h1 & h2, full, np.where(h1, only1, True))
    return bull & valid, valid


def colors_canon(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Kanonik oran-tabanlı renk: bullish = yhat(i-1) < yhat(i) (eşitlik/NaN → bearish)."""
    p1 = lag(y, 1)
    valid = np.isfinite(y)
    with np.errstate(invalid="ignore"):
        bull = (p1 < y) & valid
    return bull, valid


def rqk(close: np.ndarray, h: float = DEFAULT_H, r: float = DEFAULT_R, variant: str = "A", smooth: bool = False,
        window: int = CANON_WINDOW) -> dict[str, np.ndarray]:
    """Tek çağrı: yhat, bull, valid, flip_up (bearish → bullish), flip_dn (bullish → bearish).
    flip_*[i] yalnız i-1 ve i ikisi de renkliyse (valid) True olur."""
    if variant == "A":
        y = yhat_app(close, h, r)
        bull, valid = colors_app(y, smooth)
    elif variant == "B":
        y = yhat_canon(close, h, r, window)
        bull, valid = colors_canon(y)
    else:
        raise ValueError("variant 'A' ya da 'B' olmalı")
    pb = lag(bull.astype(float), 1)
    pv = lag(valid.astype(float), 1) > 0
    flip_up = valid & pv & bull & (pb == 0)
    flip_dn = valid & pv & ~bull & (pb == 1)
    return {"yhat": y, "bull": bull, "valid": valid, "flip_up": flip_up, "flip_dn": flip_dn}


def bars_since_flip(flip_up: np.ndarray, flip_dn: np.ndarray) -> np.ndarray:
    """Mevcut renk durumunun yaşı: son renk değişiminden (herhangi yön) beri kaç bar (değişim barı = 0). Hiç değişim yoksa büyük sayı."""
    n = len(flip_up)
    ar = np.arange(n)
    ch = flip_up | flip_dn
    last = np.maximum.accumulate(np.where(ch, ar, -10 ** 9))
    return np.where(last < 0, 10 ** 9, ar - last)
