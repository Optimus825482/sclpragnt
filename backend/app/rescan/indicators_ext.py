"""Genişletilmiş gösterge kütüphanesi — klasik (~100) + "smart money" (SMC) göstergeleri (2026-10-17, çevrimdışı araştırma).

Canlı koda BAĞLANMAZ; ağ/DB yok; saf numpy (+scipy.lfilter). Her fonksiyon 1-boyutlu `float` dizileri alır, aynı uzunlukta dizi
(ya da dizi sözlüğü) döndürür.

NEDENSELLİK: i. değer YALNIZ ≤ i barlarına bağlıdır (testle doğrulanır: gelecek barları değiştirmek geçmiş değerleri değiştirmez).
Salınım (swing) tepe/dipleri `right` bar SONRA onaylanır; onaylanmadan kullanılmaz. Veri yetersiz/ısınma → NaN.
Girdi varsayımı: OHLC sonlu (boşluklar `pattern_study.fill_gaps` ile düz mumla doldurulmuş); hacim/taker NaN → 0 sayılır.
Seri başındaki NaN'a izin verilir (ör. başka göstergenin çıktısı üzerine gösterge); ortada NaN beklenmez.

`pattern_study.features_matrix` ZATEN kapsar (burada TEKRAR YOK): EMA(7/20/50/99) uzaklık + eğim, RSI14, MFI14, ATR14%, Bollinger genişlik + %B,
MACD histogram (+eğim), ADX/±DI, Aroon, doğrusal regresyon EĞİMİ (10/20), ret1…20, hacim oranı, 24 sa yüksek/alçak uzaklığı, range_pos24,
yeşil/higher-low koşuları, drawdown12, taker özellikleri (pay, z, eğim, qratio, net6/12). `stochrsi.py` (StochRSI K/D) ve `rqk.py` (RQK) ayrıca vardır;
mum fitil reddi z-skoru `technical_analysis._wick_rejection_zscore` içinde vardır.

Ana giriş: `compute_all(arr, tf)` → (isimler, float32 matris). `arr`: pattern_study dizi düzeni (open_time, o, h, l, c, v, quote_v[, taker_base, taker_quote]).
Kategori sözlüğü: `FAMILY` (özellik adı → aile; `compute_all` çağrısından sonra dolar, `feature_names()` ile de doldurulur).
"""
from __future__ import annotations

from collections import deque

import numpy as np
from scipy.signal import lfilter

from app.rescan import pattern_study as P
from app.rescan.stochrsi import stoch_rsi as _stoch_rsi

BARS_PER_DAY = {"1m": 1440, "5m": 288, "15m": 96}
DAY_MS = 86_400_000

__all__: list[str] = []


def _export(fn):
    __all__.append(fn.__name__)
    return fn


# ----------------------------------------------------------------------------------------------- temel yardımcılar
def _f(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def _nz(x) -> np.ndarray:
    return np.nan_to_num(_f(x), nan=0.0, posinf=0.0, neginf=0.0)


def _div(a, b, default=np.nan):
    """Güvenli bölme: b == 0 ya da sonlu değilse `default`."""
    a = _f(a)
    b = _f(b)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where((b != 0) & np.isfinite(b), a / b, default)
    return r


def _first_finite(x: np.ndarray) -> int:
    fin = np.flatnonzero(np.isfinite(x))
    return int(fin[0]) if len(fin) else len(x)


def shift(x, k: int) -> np.ndarray:
    """out[i] = x[i-k] (başı NaN)."""
    return P.shift(_f(x), k)


@_export
def sma(x, n: int) -> np.ndarray:
    """Basit hareketli ortalama; ilk n-1 (ve baştaki NaN'lar sonrası) NaN."""
    x = _f(x)
    out = np.full(len(x), np.nan)
    f = _first_finite(x)
    y = x[f:]
    if len(y) < n:
        return out
    c = np.cumsum(np.insert(y, 0, 0.0))
    out[f + n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rsum(x, n: int) -> np.ndarray:
    """n barlık kayan toplam (baştaki NaN'lara izin verir)."""
    x = _f(x)
    out = np.full(len(x), np.nan)
    f = _first_finite(x)
    y = x[f:]
    if len(y) < n:
        return out
    c = np.cumsum(np.insert(y, 0, 0.0))
    out[f + n - 1:] = c[n:] - c[:-n]
    return out


def _roll_sum0(x, n: int) -> np.ndarray:
    """Baştaki eksikleri 0 sayan n barlık kayan toplam (olay bayrakları için)."""
    x = np.nan_to_num(_f(x), nan=0.0)
    c = np.cumsum(np.insert(x, 0, 0.0))
    idx = np.arange(len(x))
    lo = np.maximum(idx - n + 1, 0)
    return c[idx + 1] - c[lo]


@_export
def ema(x, n: int) -> np.ndarray:
    """SMA tohumlu EMA (kanonik, pattern_study.ema_seeded)."""
    return P.ema_seeded(_f(x), n)


def rolling_max(x, w: int) -> np.ndarray:
    x = _f(x)
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        out[w - 1:] = np.lib.stride_tricks.sliding_window_view(x, w).max(axis=1)
    return out


def rolling_min(x, w: int) -> np.ndarray:
    x = _f(x)
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        out[w - 1:] = np.lib.stride_tricks.sliding_window_view(x, w).min(axis=1)
    return out


def _fir(x, b) -> np.ndarray:
    """out[i] = Σ_k b[k]·x[i-k]; ilk len(b)-1 (+baştaki NaN) NaN."""
    x = _f(x)
    b = np.asarray(b, dtype=float)
    out = np.full(len(x), np.nan)
    f = _first_finite(x)
    y = x[f:]
    if len(y) < len(b):
        return out
    z = lfilter(b, [1.0], y)
    out[f + len(b) - 1:] = z[len(b) - 1:]
    return out


def _tr(h, l, c) -> np.ndarray:
    """Gerçek aralık; ilk bar h-l."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    pc = np.concatenate([[c[0]], c[:-1]])
    return np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))


def _roc_pct(x, n: int) -> np.ndarray:
    x = _f(x)
    return _div(x - shift(x, n), np.abs(shift(x, n))) * 100.0


def _run(cond) -> np.ndarray:
    return P.run_length(np.asarray(cond, dtype=bool)).astype(float)


# ----------------------------------------------------------------------------------------------- hareketli ortalamalar
@_export
def wma(x, n: int) -> np.ndarray:
    """Ağırlıklı HO (en yeni bar ağırlığı n, en eski 1)."""
    w = np.arange(n, 0, -1, dtype=float)       # lag 0 → n
    return _fir(x, w / w.sum())


@_export
def alma(x, n: int = 9, offset: float = 0.85, sigma: float = 6.0) -> np.ndarray:
    """Arnaud Legoux HO: Gauss ağırlıkları, tepe konumu offset·(n-1) (varsayılan 0,85 → yeni barlara yakın)."""
    m = offset * (n - 1)
    s = n / sigma
    k = np.arange(n, dtype=float)
    w = np.exp(-((k - m) ** 2) / (2.0 * s * s))
    w /= w.sum()
    return _fir(x, w[::-1])                      # k=n-1 en yeni → lag 0


@_export
def hull_ma(x, n: int = 21) -> np.ndarray:
    """Hull HO = WMA(2·WMA(n/2) − WMA(n), √n)."""
    raw = 2.0 * wma(x, max(n // 2, 1)) - wma(x, n)
    return wma(raw, max(int(round(np.sqrt(n))), 1))


@_export
def dema(x, n: int = 20) -> np.ndarray:
    """Çift üstel HO = 2·EMA − EMA(EMA)."""
    e1 = ema(x, n)
    e2 = ema(e1, n)
    return 2.0 * e1 - e2


@_export
def tema(x, n: int = 20) -> np.ndarray:
    """Üçlü üstel HO = 3·EMA − 3·EMA² + EMA³."""
    e1 = ema(x, n)
    e2 = ema(e1, n)
    e3 = ema(e2, n)
    return 3.0 * e1 - 3.0 * e2 + e3


@_export
def kama(x, n: int = 10, fast: int = 2, slow: int = 30) -> np.ndarray:
    """Kaufman uyarlanabilir HO (verimlilik oranı ER → yumuşatma sabiti)."""
    x = _f(x)
    N = len(x)
    out = np.full(N, np.nan)
    if N <= n:
        return out
    fsc, ssc = 2.0 / (fast + 1.0), 2.0 / (slow + 1.0)
    d = np.abs(np.diff(x, prepend=x[0]))
    vol = rsum(d, n)
    chg = np.abs(x - shift(x, n))
    er = np.where(vol > 0, chg / np.where(vol > 0, vol, 1.0), 0.0)
    sc = (er * (fsc - ssc) + ssc) ** 2
    xl = x.tolist()
    scl = sc.tolist()
    res = [np.nan] * N
    prev = xl[n - 1]
    for i in range(n, N):
        prev = prev + scl[i] * (xl[i] - prev)
        res[i] = prev
    return np.asarray(res)


@_export
def mcginley(x, n: int = 14) -> np.ndarray:
    """McGinley Dynamic: MD = MD₁ + (x − MD₁) / (n·(x/MD₁)⁴)."""
    x = _f(x)
    N = len(x)
    if N == 0:
        return np.full(0, np.nan)
    xl = x.tolist()
    res = [np.nan] * N
    prev = xl[0]
    res[0] = prev
    for i in range(1, N):
        r = xl[i] / prev if prev != 0 else 1.0
        den = n * (r ** 4) if r > 0 else float(n)
        prev = prev + (xl[i] - prev) / (den if den > 0.2 else 0.2)
        res[i] = prev
    out = np.asarray(res)
    out[:n] = np.nan                                                # ısınma
    return out


@_export
def linreg_band(x, n: int = 20) -> dict[str, np.ndarray]:
    """LSMA (doğrusal regresyon son-değer) + standart hata: {"value", "slope" (birim/bar), "stderr"}.
    Pencerede t=0..n-1; value = ŷ(n-1); stderr = √(SSE/(n-2))."""
    x = _f(x)
    N = len(x)
    val = np.full(N, np.nan)
    slope = np.full(N, np.nan)
    se = np.full(N, np.nan)
    if N < n:
        return {"value": val, "slope": slope, "stderr": se}
    xc = np.arange(n, dtype=float) - (n - 1) / 2.0
    sxx = float((xc ** 2).sum())
    win = np.lib.stride_tricks.sliding_window_view(x, n)
    m = win.mean(axis=1)
    dev = win - m[:, None]
    sl = dev @ xc / sxx
    res = dev - sl[:, None] * xc[None, :]
    sse = (res ** 2).sum(axis=1)
    val[n - 1:] = m + sl * (n - 1) / 2.0
    slope[n - 1:] = sl
    se[n - 1:] = np.sqrt(sse / max(n - 2, 1))
    return {"value": val, "slope": slope, "stderr": se}


# ----------------------------------------------------------------------------------------------- hacim / akış
@_export
def obv(c, v) -> np.ndarray:
    """On-Balance Volume (birikimli)."""
    c = _f(c)
    v = _nz(v)
    s = np.sign(np.diff(c, prepend=c[0]))
    return np.cumsum(s * v)


def flow_share(cum, vol, n: int) -> np.ndarray:
    """Birikimli akış serisinin n bar değişimi / n bar toplam hacim → [-1, 1] bandında ölçeksiz pay."""
    cum = _f(cum)
    return _div(cum - shift(cum, n), rsum(_nz(vol), n))


@_export
def obv_slope(c, v, n: int = 12) -> np.ndarray:
    """OBV n-bar değişimi / n-bar hacim (net işaretli hacim payı)."""
    return flow_share(obv(c, v), v, n)


def _mfm(h, l, c) -> np.ndarray:
    h = _f(h)
    l = _f(l)
    c = _f(c)
    return np.where(h > l, ((c - l) - (h - c)) / np.where(h > l, h - l, 1.0), 0.0)


@_export
def ad_line(h, l, c, v) -> np.ndarray:
    """Birikim/Dağıtım çizgisi."""
    return np.cumsum(_mfm(h, l, c) * _nz(v))


@_export
def ad_slope(h, l, c, v, n: int = 12) -> np.ndarray:
    """A/D çizgisinin n-bar değişimi / n-bar hacim."""
    return flow_share(ad_line(h, l, c, v), v, n)


@_export
def cmf(h, l, c, v, n: int = 20) -> np.ndarray:
    """Chaikin Para Akışı."""
    v = _nz(v)
    return _div(rsum(_mfm(h, l, c) * v, n), rsum(v, n))


@_export
def chaikin_osc(h, l, c, v, fast: int = 3, slow: int = 10) -> np.ndarray:
    """EMA(AD, fast) − EMA(AD, slow), SMA(hacim, slow) ile ölçeklenmiş."""
    ad = ad_line(h, l, c, v)
    return _div(ema(ad, fast) - ema(ad, slow), sma(_nz(v), slow))


@_export
def klinger(h, l, c, v, fast: int = 34, slow: int = 55, sig: int = 13) -> dict[str, np.ndarray]:
    """Klinger Hacim Osilatörü: {"kvo", "signal", "hist"} — SMA(hacim, slow) ile ölçeklenmiş."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    v = _nz(v)
    N = len(c)
    hlc = h + l + c
    trend = np.where(np.diff(hlc, prepend=hlc[0]) > 0, 1.0, -1.0)
    dm = h - l
    tl = trend.tolist()
    dl = dm.tolist()
    cml = [0.0] * N
    for i in range(1, N):
        cml[i] = (cml[i - 1] + dl[i]) if tl[i] == tl[i - 1] else (dl[i - 1] + dl[i])
    cm = np.asarray(cml)
    with np.errstate(divide="ignore", invalid="ignore"):
        vf = np.where(cm > 0, v * np.abs(2.0 * (dm / np.where(cm > 0, cm, 1.0)) - 1.0) * trend * 100.0, 0.0)
    kvo = _div(ema(vf, fast) - ema(vf, slow), sma(v, slow))
    s = ema(kvo, sig)
    return {"kvo": kvo, "signal": s, "hist": kvo - s}


@_export
def ease_of_movement(h, l, qv, n: int = 14) -> np.ndarray:
    """Hareket Kolaylığı (ölçeksiz): orta nokta % değişimi / (göreli hacim / aralık%), SMA(n); uçlar ±10'a kırpılı."""
    h = _f(h)
    l = _f(l)
    qv = _nz(qv)
    mid = (h + l) / 2.0
    dmid = _div(mid - shift(mid, 1), shift(mid, 1)) * 100.0
    rng = _div(h - l, mid) * 100.0
    rel = _div(qv, sma(qv, 20))
    box = _div(rel, np.maximum(rng, 1e-6))
    e = _div(dmid, box)
    return sma(np.clip(np.nan_to_num(e, nan=0.0), -10, 10), n)


@_export
def force_index(c, v, n: int = 13) -> np.ndarray:
    """Elder Kuvvet Endeksi: EMA(getiri% × göreli hacim, n) (ölçeksiz)."""
    c = _f(c)
    v = _nz(v)
    ret = _div(c - shift(c, 1), shift(c, 1)) * 100.0
    rel = _div(v, sma(v, 20))
    return ema(np.nan_to_num(ret * rel, nan=0.0), n)


@_export
def pvt(c, v) -> np.ndarray:
    """Fiyat-Hacim Trendi (birikimli)."""
    c = _f(c)
    v = _nz(v)
    r = np.nan_to_num(_div(c - shift(c, 1), shift(c, 1)), nan=0.0)
    return np.cumsum(r * v)


@_export
def pvt_slope(c, v, n: int = 12) -> np.ndarray:
    """PVT n-bar değişimi / n-bar hacim."""
    return flow_share(pvt(c, v), v, n)


@_export
def volume_oscillator(v, fast: int = 5, slow: int = 10) -> np.ndarray:
    """Hacim osilatörü: (SMA(hacim,fast) − SMA(hacim,slow)) / SMA(hacim,slow) × 100."""
    v = _nz(v)
    return _div(sma(v, fast) - sma(v, slow), sma(v, slow)) * 100.0


@_export
def cvd(qv, tbq) -> np.ndarray:
    """Taker tabanlı net hacim: birikimli Σ(2·taker_alış_quote − toplam_quote)."""
    return np.cumsum(2.0 * _nz(tbq) - _nz(qv))


@_export
def cvd_slope(qv, tbq, n: int = 12) -> np.ndarray:
    """CVD n-bar değişimi / n-bar quote hacmi ∈ [-1, 1] (≈ 2·taker payı − 1; mevcut tk_share ile affin eşdeğer)."""
    return flow_share(cvd(qv, tbq), qv, n)


@_export
def orderflow_imbalance_z(qv, tbq, n: int = 3, hist: int = 288) -> np.ndarray:
    """Emir akışı dengesizliği z-skoru: son n barın net taker payı, önceki `hist` barın (n bar boşluklu) aynı ölçüsünün ort/std'sine göre."""
    q = _nz(qv)
    net = 2.0 * _nz(tbq) - q
    x = _div(rsum(net, n), rsum(q, n), default=0.0)
    xs = shift(x, n)
    m = sma(xs, hist)
    m2 = sma(xs * xs, hist)
    sd = np.sqrt(np.maximum(m2 - m * m, 0.0))
    return np.clip(_div(x - m, sd, default=0.0), -10.0, 10.0)


# ----------------------------------------------------------------------------------------------- momentum osilatörleri
@_export
def cmo(c, n: int = 14) -> np.ndarray:
    """Chande Momentum Osilatörü."""
    c = _f(c)
    d = np.diff(c, prepend=c[0])
    up = rsum(np.where(d > 0, d, 0.0), n)
    dn = rsum(np.where(d < 0, -d, 0.0), n)
    return _div(up - dn, up + dn, default=0.0) * 100.0


@_export
def connors_rsi(c, rsi_n: int = 3, streak_n: int = 2, rank_n: int = 100) -> np.ndarray:
    """Connors RSI = (RSI(c,3) + RSI(seri,2) + yüzdelik sıra(ROC1, 100)) / 3."""
    c = _f(c)
    N = len(c)
    r1 = P.rsi_series(c, rsi_n)
    d = np.diff(c, prepend=c[0])
    up = _run(d > 0)
    dn = _run(d < 0)
    streak = np.where(d > 0, up, np.where(d < 0, -dn, 0.0))
    r2 = P.rsi_series(streak, streak_n)
    roc = np.nan_to_num(_div(c - shift(c, 1), shift(c, 1)) * 100.0, nan=0.0)
    pr = np.full(N, np.nan)
    if N > rank_n + 1:
        win = np.lib.stride_tricks.sliding_window_view(roc[:-1], rank_n)      # i için: roc[i-rank_n .. i-1]
        pr[rank_n:] = (win < roc[rank_n:, None]).mean(axis=1) * 100.0
    return (r1 + r2 + pr) / 3.0


@_export
def stochastic(h, l, c, k: int = 14, smooth: int = 3, d: int = 3) -> dict[str, np.ndarray]:
    """Yavaş Stokastik: {"k", "d", "raw"} (ham %K'nın SMA(smooth)'ı = K; D = SMA(K, d)). Aralık 0 → 50."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    hh, ll = rolling_max(h, k), rolling_min(l, k)
    raw = np.where(np.isfinite(hh), np.where(hh > ll, (c - ll) / np.where(hh > ll, hh - ll, 1.0) * 100.0, 50.0), np.nan)
    kk = sma(raw, smooth)
    return {"k": kk, "d": sma(kk, d), "raw": raw}


@_export
def stochrsi(c, rsi_n: int = 14, stoch_n: int = 14, k: int = 3, d: int = 3) -> dict[str, np.ndarray]:
    """StochRSI (mevcut `app.rescan.stochrsi`'e sarmalayıcı): {"rsi","stoch","k","d"}."""
    return _stoch_rsi(_f(c), rsi_n, stoch_n, k, d)


@_export
def williams_r(h, l, c, n: int = 14) -> np.ndarray:
    """Williams %R (−100…0)."""
    hh, ll = rolling_max(h, n), rolling_min(l, n)
    return np.where(np.isfinite(hh), np.where(hh > ll, (hh - _f(c)) / np.where(hh > ll, hh - ll, 1.0) * -100.0, -50.0), np.nan)


@_export
def ultimate_osc(h, l, c, p1: int = 7, p2: int = 14, p3: int = 28) -> np.ndarray:
    """Ultimate Oscillator."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    pc = np.concatenate([[c[0]], c[:-1]])
    bp = c - np.minimum(l, pc)
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    a1 = _div(rsum(bp, p1), rsum(tr, p1), 0.5)
    a2 = _div(rsum(bp, p2), rsum(tr, p2), 0.5)
    a3 = _div(rsum(bp, p3), rsum(tr, p3), 0.5)
    return 100.0 * (4.0 * a1 + 2.0 * a2 + a3) / 7.0


@_export
def awesome_osc(h, l, fast: int = 5, slow: int = 34) -> np.ndarray:
    """AO = SMA(orta,5) − SMA(orta,34), yavaş ortalamaya göre % (ölçeksiz)."""
    mid = (_f(h) + _f(l)) / 2.0
    return _div(sma(mid, fast) - sma(mid, slow), sma(mid, slow)) * 100.0


@_export
def tsi(c, long: int = 25, short: int = 13) -> np.ndarray:
    """Gerçek Güç Endeksi: 100·EMA(EMA(Δc))/EMA(EMA(|Δc|))."""
    c = _f(c)
    d = np.diff(c, prepend=c[0])
    num = ema(ema(d, long), short)
    den = ema(ema(np.abs(d), long), short)
    return _div(num, den, default=0.0) * 100.0


@_export
def trix(c, n: int = 15) -> np.ndarray:
    """TRIX = üçlü EMA'nın 1-bar % değişimi."""
    t = ema(ema(ema(c, n), n), n)
    return _div(t - shift(t, 1), shift(t, 1)) * 100.0


@_export
def kst(c, signal: int = 9) -> dict[str, np.ndarray]:
    """Know Sure Thing: ROC(10/15/20/30) SMA(10/10/10/15) ağırlık 1/2/3/4; {"kst","signal"}."""
    c = _f(c)
    k = (1 * sma(_roc_pct(c, 10), 10) + 2 * sma(_roc_pct(c, 15), 10) + 3 * sma(_roc_pct(c, 20), 10) + 4 * sma(_roc_pct(c, 30), 15))
    return {"kst": k, "signal": sma(k, signal)}


@_export
def fisher_transform(h, l, n: int = 9) -> dict[str, np.ndarray]:
    """Fisher Dönüşümü: {"fisher","trigger"(1 bar gecikmeli)}."""
    h = _f(h)
    l = _f(l)
    N = len(h)
    mid = (h + l) / 2.0
    hh, ll = rolling_max(mid, n), rolling_min(mid, n)
    x = np.where(np.isfinite(hh) & (hh > ll), (mid - ll) / np.where(hh > ll, hh - ll, 1.0) - 0.5, 0.0)
    xl = x.tolist()
    fl = [np.nan] * N
    v = 0.0
    fp = 0.0
    for i in range(N):
        v = 0.66 * xl[i] + 0.67 * v
        v = 0.999 if v > 0.999 else (-0.999 if v < -0.999 else v)
        fp = 0.5 * np.log((1.0 + v) / (1.0 - v)) + 0.5 * fp
        fl[i] = fp
    f = np.asarray(fl)
    f[:n] = np.nan
    return {"fisher": f, "trigger": shift(f, 1)}


@_export
def rvi_vigor(o, h, l, c, n: int = 10) -> dict[str, np.ndarray]:
    """Göreli Canlılık Endeksi (RVI): {"rvi","signal"}."""
    w = np.array([1.0, 2.0, 2.0, 1.0]) / 6.0
    num = _fir(_f(c) - _f(o), w)
    den = _fir(_f(h) - _f(l), w)
    r = _div(sma(num, n), sma(den, n), default=0.0)
    return {"rvi": r, "signal": _fir(r, w)}


@_export
def balance_of_power(o, h, l, c, smooth: int = 14) -> np.ndarray:
    """Güç Dengesi: SMA((c−o)/(h−l))."""
    h = _f(h)
    l = _f(l)
    raw = np.where(h > l, (_f(c) - _f(o)) / np.where(h > l, h - l, 1.0), 0.0)
    return sma(raw, smooth)


@_export
def cci(h, l, c, n: int = 20) -> np.ndarray:
    """Commodity Channel Index."""
    tp = (_f(h) + _f(l) + _f(c)) / 3.0
    out = np.full(len(tp), np.nan)
    if len(tp) < n:
        return out
    win = np.lib.stride_tricks.sliding_window_view(tp, n)
    m = win.mean(axis=1)
    mad = np.abs(win - m[:, None]).mean(axis=1)
    out[n - 1:] = np.where(mad > 0, (tp[n - 1:] - m) / (0.015 * np.where(mad > 0, mad, 1.0)), 0.0)
    return out


@_export
def dpo(c, n: int = 20) -> np.ndarray:
    """Trendden arındırılmış fiyat osilatörü (kapanışa göre %): c[i-(n/2+1)] − SMA(c,n)[i]."""
    c = _f(c)
    return _div(shift(c, n // 2 + 1) - sma(c, n), c) * 100.0


@_export
def smi_ergodic(c, long: int = 20, short: int = 5, signal: int = 5) -> dict[str, np.ndarray]:
    """SMI Ergodic = TSI(short, long) ve sinyal EMA: {"smi","signal"}."""
    t = tsi(c, long, short)
    return {"smi": t, "signal": ema(t, signal)}


@_export
def coppock(c, wma_n: int = 10, r1: int = 14, r2: int = 11) -> np.ndarray:
    """Coppock eğrisi: WMA(ROC14 + ROC11, 10)."""
    c = _f(c)
    return wma(_roc_pct(c, r1) + _roc_pct(c, r2), wma_n)


# ----------------------------------------------------------------------------------------------- trend / yapı
@_export
def vortex(h, l, c, n: int = 14) -> dict[str, np.ndarray]:
    """Vortex: {"plus","minus","diff"}."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    vmp = np.nan_to_num(np.abs(h - shift(l, 1)), nan=0.0)
    vmm = np.nan_to_num(np.abs(l - shift(h, 1)), nan=0.0)
    tr = rsum(_tr(h, l, c), n)
    vp = _div(rsum(vmp, n), tr)
    vm = _div(rsum(vmm, n), tr)
    return {"plus": vp, "minus": vm, "diff": vp - vm}


@_export
def parabolic_sar(h, l, af0: float = 0.02, step: float = 0.02, af_max: float = 0.2) -> dict[str, np.ndarray]:
    """Parabolik SAR: {"sar","state"(+1 yükseliş/−1 düşüş),"flip"(+1 yukarı dönüş, −1 aşağı, bu barda)}. İlk 35 bar ısınma (NaN)."""
    hl = _f(h).tolist()
    ll = _f(l).tolist()
    N = len(hl)
    sar = [np.nan] * N
    st = [np.nan] * N
    fl = [0.0] * N
    if N < 2:
        return {"sar": np.asarray(sar), "state": np.asarray(st), "flip": np.asarray(fl)}
    up = hl[1] >= hl[0]
    ep = hl[1] if up else ll[1]
    s = ll[0] if up else hl[0]
    af = af0
    sar[1] = s
    st[1] = 1.0 if up else -1.0
    for i in range(2, N):
        s = s + af * (ep - s)
        if up:
            s = min(s, ll[i - 1], ll[i - 2])
            if ll[i] < s:                                   # dönüş → düşüş
                up = False
                s = ep
                ep = ll[i]
                af = af0
                fl[i] = -1.0
            elif hl[i] > ep:
                ep = hl[i]
                af = min(af + step, af_max)
        else:
            s = max(s, hl[i - 1], hl[i - 2])
            if hl[i] > s:                                   # dönüş → yükseliş
                up = True
                s = ep
                ep = hl[i]
                af = af0
                fl[i] = 1.0
            elif ll[i] < ep:
                ep = ll[i]
                af = min(af + step, af_max)
        sar[i] = s
        st[i] = 1.0 if up else -1.0
    out = {"sar": np.asarray(sar), "state": np.asarray(st), "flip": np.asarray(fl)}
    out["state"][:35] = np.nan
    out["sar"][:35] = np.nan
    return out


@_export
def supertrend(h, l, c, period: int = 10, mult: float = 3.0) -> dict[str, np.ndarray]:
    """SuperTrend: {"line","state"(+1 yükseliş/−1 düşüş),"flip"}. ATR = Wilder RMA(TR). İlk 3·period bar ısınma (NaN)."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    N = len(c)
    atr = P.wilder_smooth(_tr(h, l, c), period)
    hl2 = (h + l) / 2.0
    ub = (hl2 + mult * atr).tolist()
    lb = (hl2 - mult * atr).tolist()
    cl = c.tolist()
    mid = hl2.tolist()
    line = [np.nan] * N
    st = [np.nan] * N
    fl = [0.0] * N
    fub = np.nan
    flb = np.nan
    trend = 1
    started = False
    for i in range(N):
        if not (ub[i] == ub[i]):
            continue
        if not started:
            fub, flb = ub[i], lb[i]
            trend = 1 if cl[i] >= mid[i] else -1
            started = True
        else:
            fub = ub[i] if (ub[i] < fub or cl[i - 1] > fub) else fub
            flb = lb[i] if (lb[i] > flb or cl[i - 1] < flb) else flb
            if trend == 1 and cl[i] < flb:
                trend = -1
                fl[i] = -1.0
            elif trend == -1 and cl[i] > fub:
                trend = 1
                fl[i] = 1.0
        line[i] = flb if trend == 1 else fub
        st[i] = float(trend)
    out = {"line": np.asarray(line), "state": np.asarray(st), "flip": np.asarray(fl)}
    out["state"][:3 * period] = np.nan
    out["line"][:3 * period] = np.nan
    return out


@_export
def supertrend_cluster(h, l, c, params=((10, 1.0), (11, 2.0), (12, 3.0))) -> dict[str, np.ndarray]:
    """3 SuperTrend kümesi: {"sum" (−3..+3: yükselişte olanlar − düşüşte olanlar), "flip_up_3" (son 3 barda yükselişe dönen SuperTrend sayısı),
    "agree_up" (hepsi yükselişte), "flip_all_up" (hepsi yükselişte, son 3 barda hep uyumlu ve 4 bar önce uyum yoktu = kümelenme dönüşü)}."""
    sts = [supertrend(h, l, c, p, m) for p, m in params]
    S = np.vstack([s["state"] for s in sts])
    F = np.vstack([s["flip"] for s in sts])
    ok = np.isfinite(S).all(axis=0)
    tot = np.where(ok, S.sum(axis=0), np.nan)
    flip3 = np.sum([_roll_sum0((F[k] > 0).astype(float), 3) for k in range(len(sts))], axis=0)
    agree = (np.nan_to_num(S, nan=-1.0).min(axis=0) > 0).astype(float)
    agree3 = _roll_sum0(agree, 3) == 3
    prev = np.nan_to_num(shift(agree, 4), nan=0.0) == 1.0
    flip_all = (agree3 & ~prev).astype(float)
    return {"sum": tot, "flip_up_3": np.where(ok, flip3, np.nan), "agree_up": np.where(ok, agree, np.nan), "flip_all_up": np.where(ok, flip_all, np.nan)}


@_export
def ichimoku(h, l, c, tenkan_n: int = 9, kijun_n: int = 26, senkou_n: int = 52, disp: int = 26) -> dict[str, np.ndarray]:
    """Ichimoku (nedensel): bulut i'de `disp` bar önce hesaplanan Senkou A/B'dir. Çıktılar:
    "cloud_pos" (+1 bulut üstü/0 içinde/−1 altında), "cloud_dist" (kapanışın bulut kenarına % uzaklığı, içindeyse 0), "cloud_thick" (kalınlık %),
    "tk_diff" ((Tenkan−Kijun)/c %), "tk_cross_up" (bu barda Tenkan Kijun'u yukarı kesti), "chikou" ((c − c[-disp])/c %)."""
    h = _f(h)
    l = _f(l)
    c = _f(c)

    def mid(n):
        return (rolling_max(h, n) + rolling_min(l, n)) / 2.0
    ten, kij = mid(tenkan_n), mid(kijun_n)
    sa = (ten + kij) / 2.0
    sb = mid(senkou_n)
    a = shift(sa, disp)
    b = shift(sb, disp)
    top = np.maximum(a, b)
    bot = np.minimum(a, b)
    fin = np.isfinite(top)
    pos = np.where(fin, np.where(c > top, 1.0, np.where(c < bot, -1.0, 0.0)), np.nan)
    dist = np.where(fin, np.where(c > top, (c / top - 1) * 100, np.where(c < bot, (c / bot - 1) * 100, 0.0)), np.nan)
    d = ten - kij
    cross = np.zeros(len(c))
    cross[1:] = ((d[1:] > 0) & (d[:-1] <= 0)).astype(float)
    cross = np.where(np.isfinite(d), cross, np.nan)
    return {"cloud_pos": pos, "cloud_dist": dist, "cloud_thick": _div(top - bot, c) * 100.0, "tk_diff": _div(d, c) * 100.0,
            "tk_cross_up": cross, "chikou": _div(c - shift(c, disp), c) * 100.0}


@_export
def donchian(h, l, c, n: int = 20) -> dict[str, np.ndarray]:
    """Donchian: {"pos" ((c−LL)/(HH−LL), pencere bugünü içerir), "break_up" (c, ÖNCEKİ n barın en yükseğini aştı), "width" (% aralık)}."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    hh, ll = rolling_max(h, n), rolling_min(l, n)
    pos = np.where(np.isfinite(hh), np.where(hh > ll, (c - ll) / np.where(hh > ll, hh - ll, 1.0), 0.5), np.nan)
    ph = shift(hh, 1)
    brk = np.where(np.isfinite(ph), (c > ph).astype(float), np.nan)
    return {"pos": pos, "break_up": brk, "width": _div(hh - ll, c) * 100.0}


@_export
def inside_bar_breakout(h, l, c) -> dict[str, np.ndarray]:
    """İç-bar kırılım filtresi: ana mum m=i−2, iç mum i−1 (h[i−1] < h[m], l[i−1] > l[m]); i'de kapanış > h[m] ("up") / < l[m] ("down")."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    N = len(c)
    inside = np.zeros(N, dtype=bool)
    inside[1:] = (h[1:] < h[:-1]) & (l[1:] > l[:-1])
    up = np.zeros(N)
    dn = np.zeros(N)
    if N > 2:
        prev_inside = inside[1:-1]               # i−1 iç bar (i = 2..N−1)
        up[2:] = (prev_inside & (c[2:] > h[:-2])).astype(float)
        dn[2:] = (prev_inside & (c[2:] < l[:-2])).astype(float)
    return {"up": up, "down": dn, "inside": inside.astype(float)}


@_export
def keltner(h, l, c, n: int = 20, atr_n: int = 10, mult: float = 1.5) -> dict[str, np.ndarray]:
    """Keltner: {"pos" ((c−orta)/(mult·ATR)), "width" (% = 2·mult·ATR/orta), "upper","lower","mid"}."""
    c = _f(c)
    mid = ema(c, n)
    atr = P.atr_series(_f(h), _f(l), c, atr_n)
    up, lo = mid + mult * atr, mid - mult * atr
    return {"pos": _div(c - mid, mult * atr), "width": _div(up - lo, mid) * 100.0, "upper": up, "lower": lo, "mid": mid}


@_export
def squeeze(h, l, c, n: int = 20, bb_k: float = 2.0, kc_mult: float = 1.5, release_look: int = 6) -> dict[str, np.ndarray]:
    """Sıkışma (Bollinger, Keltner içinde): {"on" (0/1), "run" (üst üste sıkışık bar), "ratio" (BB genişliği / KC genişliği),
    "since_off" (sıkışma bitişinden beri bar, max 24; sıkışıkken 0), "release" (bu bar sıkışık DEĞİL ve son `release_look` barda sıkışık vardı)}."""
    c = _f(c)
    N = len(c)
    kc = keltner(h, l, c, n, 10, kc_mult)
    m = sma(c, n)
    sd = np.full(N, np.nan)
    if N >= n:
        sd[n - 1:] = np.lib.stride_tricks.sliding_window_view(c, n).std(axis=1)
    bbu, bbl = m + bb_k * sd, m - bb_k * sd
    fin = np.isfinite(bbu) & np.isfinite(kc["upper"])
    on = np.where(fin, ((bbu < kc["upper"]) & (bbl > kc["lower"])).astype(float), np.nan)
    ratio = _div(bbu - bbl, kc["upper"] - kc["lower"])
    onb = np.nan_to_num(on, nan=0.0) > 0
    run = np.where(fin, _run(onb), np.nan)
    ar = np.arange(N)
    last_on = np.maximum.accumulate(np.where(onb, ar, -10 ** 9))
    since = np.where(onb, 0.0, np.minimum(ar - last_on, 24.0))
    prior = _roll_sum0(onb.astype(float), release_look + 1) - onb.astype(float)
    release = ((~onb) & (prior > 0)).astype(float)
    return {"on": on, "run": run, "ratio": ratio, "since_off": np.where(fin, since, np.nan), "release": np.where(fin, release, np.nan)}


@_export
def choppiness(h, l, c, n: int = 14) -> np.ndarray:
    """Choppiness Index (0–100; yüksek = yatay/testere)."""
    hh, ll = rolling_max(h, n), rolling_min(l, n)
    s = rsum(_tr(h, l, c), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where((hh > ll) & (s > 0), 100.0 * np.log10(s / np.where(hh > ll, hh - ll, 1.0)) / np.log10(n), np.nan)
    return v


@_export
def mass_index(h, l, ema_n: int = 9, sum_n: int = 25) -> np.ndarray:
    """Mass Index: Σ_25 EMA9(h−l) / EMA9(EMA9(h−l))."""
    rng = _f(h) - _f(l)
    e1 = ema(rng, ema_n)
    e2 = ema(e1, ema_n)
    return rsum(_div(e1, e2), sum_n)


@_export
def hist_vol(c, n: int = 20) -> np.ndarray:
    """Tarihsel oynaklık: log getirinin n-bar std'si (% / bar)."""
    c = _f(c)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(c / shift(c, 1))
    out = np.full(len(c), np.nan)
    r = r[1:]
    if len(r) >= n:
        out[n:] = np.lib.stride_tricks.sliding_window_view(r, n).std(axis=1, ddof=1) * 100.0
    return out


@_export
def chaikin_volatility(h, l, ema_n: int = 10, roc_n: int = 10) -> np.ndarray:
    """Chaikin Oynaklığı: EMA(h−l) ROC %."""
    h = _f(h)
    e = ema(h - _f(l), ema_n)
    prev = shift(e, roc_n)
    floor = 1e-6 * np.abs(h)                       # düz mumlarda EMA'nın sıfıra çökmesi → ROC patlamasın
    return np.clip(_div(e - prev, np.maximum(prev, floor)) * 100.0, -1000.0, 1000.0)


@_export
def relative_volatility_index(c, std_n: int = 10, smooth: int = 14) -> np.ndarray:
    """Göreli Oynaklık Endeksi (RSI benzeri, std üzerinde)."""
    c = _f(c)
    N = len(c)
    sd = np.full(N, np.nan)
    if N >= std_n:
        sd[std_n - 1:] = np.lib.stride_tricks.sliding_window_view(c, std_n).std(axis=1)
    dc = np.diff(c, prepend=c[0])
    up = np.where(np.isfinite(sd), np.where(dc > 0, sd, 0.0), np.nan)
    dn = np.where(np.isfinite(sd), np.where(dc < 0, sd, 0.0), np.nan)
    u, d = P.wilder_smooth(up, smooth), P.wilder_smooth(dn, smooth)
    return 100.0 * _div(u, u + d, default=0.5)


@_export
def atr_ratio(h, l, c, fast: int = 7, slow: int = 50) -> np.ndarray:
    """ATR(fast)/ATR(slow): oynaklık genişlemesi."""
    return _div(P.atr_series(_f(h), _f(l), _f(c), fast), P.atr_series(_f(h), _f(l), _f(c), slow))


# ----------------------------------------------------------------------------------------------- konum: VWAP / hacim profili
@_export
def vwap_session(open_time, h, l, c, v) -> np.ndarray:
    """Oturum VWAP'ı (oturum = UTC günü, hacim ağırlıklı tipik fiyat); oturumda hacim 0 ise tipik fiyat."""
    ot = np.asarray(open_time, dtype=np.int64)
    day = ot // DAY_MS
    tp = (_f(h) + _f(l) + _f(c)) / 3.0
    v = _nz(v)
    cp = np.cumsum(tp * v)
    cv = np.cumsum(v)
    first = np.concatenate([[True], day[1:] != day[:-1]])
    start = np.maximum.accumulate(np.where(first, np.arange(len(ot)), 0))
    cp0 = np.where(start > 0, cp[np.maximum(start - 1, 0)], 0.0)
    cv0 = np.where(start > 0, cv[np.maximum(start - 1, 0)], 0.0)
    sv = cv - cv0
    return np.where(sv > 0, (cp - cp0) / np.where(sv > 0, sv, 1.0), tp)


@_export
def anchored_vwap_swing_low(h, l, c, v, window: int = 288) -> dict[str, np.ndarray]:
    """Son `window` barın (24 sa) en düşük dibinden (en yeni eşitlik) çapalanmış VWAP: {"vwap","age" (bar sayısı/window)}."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    v = _nz(v)
    N = len(c)
    tp = (h + l + c) / 3.0
    cp = np.concatenate([[0.0], np.cumsum(tp * v)])
    cv = np.concatenate([[0.0], np.cumsum(v)])
    ll = l.tolist()
    dq: deque = deque()
    anchor = np.full(N, -1, dtype=np.int64)
    for i in range(N):
        while dq and ll[dq[-1]] >= ll[i]:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - window:
            dq.popleft()
        if i >= window - 1:
            anchor[i] = dq[0]
    idx = np.arange(N)
    ok = anchor >= 0
    a = np.where(ok, anchor, 0)
    sv = cv[idx + 1] - cv[a]
    vw = np.where(ok, np.where(sv > 0, (cp[idx + 1] - cp[a]) / np.where(sv > 0, sv, 1.0), tp), np.nan)
    return {"vwap": vw, "age": np.where(ok, (idx - a) / float(window), np.nan)}


@_export
def volume_profile_poc(h, l, c, v, window: int = 288, bins: int = 50, chunk: int = 2048) -> np.ndarray:
    """Son `window` barın hacim profili POC fiyatı (pencerenin [en düşük, en yüksek] aralığı `bins` kutuya bölünür; bar hacmi tipik fiyatının kutusuna eklenir)."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    v = _nz(v)
    N = len(c)
    out = np.full(N, np.nan)
    if N < window:
        return out
    tp = (h + l + c) / 3.0
    lo_all = rolling_min(l, window)[window - 1:]
    hi_all = rolling_max(h, window)[window - 1:]
    Wt = np.lib.stride_tricks.sliding_window_view(tp, window)
    Wv = np.lib.stride_tricks.sliding_window_view(v, window)
    M = N - window + 1
    for s in range(0, M, chunk):
        e = min(M, s + chunk)
        m = e - s
        lo = lo_all[s:e]
        hi = hi_all[s:e]
        rng = hi - lo
        ok = rng > 0
        b = np.floor((Wt[s:e] - lo[:, None]) / np.where(ok, rng, 1.0)[:, None] * bins).astype(np.int64)
        b = np.clip(b, 0, bins - 1)
        flat = (np.arange(m)[:, None] * bins + b).ravel()
        cnt = np.bincount(flat, weights=Wv[s:e].ravel(), minlength=m * bins).reshape(m, bins)
        pb = cnt.argmax(axis=1)
        poc = lo + (pb + 0.5) / bins * rng
        out[window - 1 + s: window - 1 + e] = np.where(ok, poc, np.nan)
    return out


# ----------------------------------------------------------------------------------------------- SMC yapıları
@_export
def swing_pivots(h, l, left: int = 3, right: int = 3) -> dict[str, np.ndarray]:
    """Fraktal tepe/dipler. Tepe j: h[j] ≥ önceki `left` barın en yükseği VE h[j] > sonraki `right` barın en yükseği (dip simetrik).
    ONAY j+right barında: dönen "sh_price"/"sl_price" i barında i−right'taki tepe/dip fiyatı (yoksa NaN) — yalnız ≤ i bilgisi."""
    h = _f(h)
    l = _f(l)
    N = len(h)
    sh = np.full(N, np.nan)
    sl = np.full(N, np.nan)
    w = left + right + 1
    if N < w:
        return {"sh_price": sh, "sl_price": sl}
    Wh = np.lib.stride_tricks.sliding_window_view(h, w)
    Wl = np.lib.stride_tricks.sliding_window_view(l, w)
    cen_h = Wh[:, left]
    cen_l = Wl[:, left]
    ph = (cen_h >= Wh[:, :left].max(axis=1)) & (cen_h > Wh[:, left + 1:].max(axis=1))
    pl = (cen_l <= Wl[:, :left].min(axis=1)) & (cen_l < Wl[:, left + 1:].min(axis=1))
    sh[w - 1:] = np.where(ph, cen_h, np.nan)       # pencere k ↔ merkez j = k+left, onay bar i = k+w-1
    sl[w - 1:] = np.where(pl, cen_l, np.nan)
    return {"sh_price": sh, "sl_price": sl}


@_export
def market_structure(o, h, l, c, left: int = 3, right: int = 3, eq_tol_atr: float = 0.15, reclaim_bars: int = 3) -> dict[str, np.ndarray]:
    """SMC piyasa yapısı (nedensel; salınımlar `right` bar sonra onaylanır). Çıktılar (i barı):
      "trend"        son kırılımın yönü (+1 yükseliş/−1 düşüş/0 yok)
      "bos_up"/"choch_up"/"bos_dn"/"choch_dn"   bu barda KAPANIŞ son (kırılmamış) tepeyi/dibi aştı: BOS = trend yönünde, CHoCH = ters yöne
      "since_choch_up"  son CHoCH-yukarıdan beri bar (max 60)
      "dist_sh"/"dist_sl"  kapanışın son onaylı tepeye/dibe % uzaklığı
      "sweep_low"    son onaylı dibin ALTINA fitil atıldı ve (aynı barda ya da ≤ `reclaim_bars` içinde) kapanış dibin ÜSTÜNE döndü (seviye başına ilk kez)
      "sweep_low_recent3"  son 3 barda sweep_low var
      "sweep_depth"  süpürme derinliği (% , olay barında; yoksa 0)
      "eql"/"eqh"    son iki onaylı dip/tepe ATR·eq_tol içinde eşit (eşit dipler/tepeler; durum)
      "sweep_eql"    sweep_low ve dipler eşitti."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    N = len(c)
    pv = swing_pivots(h, l, left, right)
    atr = P.atr_series(h, l, c, 14)
    shp = pv["sh_price"].tolist()
    slp = pv["sl_price"].tolist()
    ll = l.tolist()
    cl = c.tolist()
    al = atr.tolist()
    trend = [0.0] * N
    bos_up = [0.0] * N
    choch_up = [0.0] * N
    bos_dn = [0.0] * N
    choch_dn = [0.0] * N
    sweep = [0.0] * N
    depth = [0.0] * N
    since_cu = [60.0] * N
    dsh = [np.nan] * N
    dsl = [np.nan] * N
    eql = [0.0] * N
    eqh = [0.0] * N
    sweq = [0.0] * N
    sh_lvl = np.nan
    sl_lvl = np.nan
    sh_used = True
    sl_used = True
    prev_sl = np.nan
    prev_sh = np.nan
    eql_s = 0.0
    eqh_s = 0.0
    tr = 0.0
    last_cu = -10 ** 9
    touch_i = -10 ** 9
    touch_depth = 0.0
    swept_done = True
    for i in range(N):
        if shp[i] == shp[i]:
            if sh_lvl == sh_lvl:
                prev_sh = sh_lvl
            sh_lvl = shp[i]
            sh_used = False
            if prev_sh == prev_sh and al[i] == al[i]:
                eqh_s = 1.0 if abs(sh_lvl - prev_sh) <= eq_tol_atr * al[i] else 0.0
        if slp[i] == slp[i]:
            if sl_lvl == sl_lvl:
                prev_sl = sl_lvl
            sl_lvl = slp[i]
            sl_used = False
            swept_done = False
            touch_i = -10 ** 9
            if prev_sl == prev_sl and al[i] == al[i]:
                eql_s = 1.0 if abs(sl_lvl - prev_sl) <= eq_tol_atr * al[i] else 0.0
        if sh_lvl == sh_lvl and not sh_used and cl[i] > sh_lvl:
            sh_used = True
            if tr < 0:
                choch_up[i] = 1.0
                last_cu = i
            else:
                bos_up[i] = 1.0
            tr = 1.0
        if sl_lvl == sl_lvl and not sl_used:
            if ll[i] < sl_lvl and touch_i < 0:
                touch_i = i
                touch_depth = (sl_lvl - ll[i]) / sl_lvl * 100.0
            if touch_i >= 0 and not swept_done and cl[i] > sl_lvl and i - touch_i <= reclaim_bars:
                sweep[i] = 1.0
                depth[i] = touch_depth
                swept_done = True
                sweq[i] = eql_s
            if cl[i] < sl_lvl:
                sl_used = True                                   # kapanış dibin altında → yapı kırıldı
                if tr > 0:
                    choch_dn[i] = 1.0
                else:
                    bos_dn[i] = 1.0
                tr = -1.0
        trend[i] = tr
        since_cu[i] = min(i - last_cu, 60.0)
        if sh_lvl == sh_lvl:
            dsh[i] = (cl[i] / sh_lvl - 1.0) * 100.0
        if sl_lvl == sl_lvl:
            dsl[i] = (cl[i] / sl_lvl - 1.0) * 100.0
        eql[i] = eql_s
        eqh[i] = eqh_s
    sw = np.asarray(sweep)
    out = {"trend": np.asarray(trend), "bos_up": np.asarray(bos_up), "choch_up": np.asarray(choch_up), "bos_dn": np.asarray(bos_dn),
           "choch_dn": np.asarray(choch_dn), "since_choch_up": np.asarray(since_cu), "dist_sh": np.asarray(dsh), "dist_sl": np.asarray(dsl),
           "sweep_low": sw, "sweep_low_recent3": (_roll_sum0(sw, 3) > 0).astype(float), "sweep_depth": np.asarray(depth),
           "eql": np.asarray(eql), "eqh": np.asarray(eqh), "sweep_eql": np.asarray(sweq)}
    warm = left + right + 20
    for k in ("trend", "since_choch_up", "dist_sh", "dist_sl"):
        out[k][:warm] = np.nan
    return out


@_export
def fair_value_gaps(h, l, c, min_atr: float = 0.25, max_age: int = 50) -> dict[str, np.ndarray]:
    """Adil Değer Boşlukları (3 mum): yükseliş FVG: l[i] > h[i−2]; düşüş: h[i] < l[i−2]; boşluk ≥ min_atr·ATR14[i−1] olmalı. Çıktılar:
      "bull_new" (yeni boşluk büyüklüğü ATR cinsinden, yoksa 0), "bull_open" (son `max_age` bar içinde henüz DOLMAMIŞ yükseliş boşluğu sayısı),
      "bull_tap" (bu bar önceki bir açık yükseliş boşluğuna girdi — low ≤ boşluk üstü — ve kapanış boşluk altının üstünde; dolmadı),
      "bull_age" (en yeni açık yükseliş boşluğunun yaşı bar, yoksa max_age), "bear_new", "bear_open".
    Dolu = low ≤ boşluk altı (yükseliş) / high ≥ boşluk üstü (düşüş)."""
    h = _f(h)
    l = _f(l)
    c = _f(c)
    N = len(c)
    atl = P.atr_series(h, l, c, 14).tolist()
    hl = h.tolist()
    ll = l.tolist()
    cl = c.tolist()
    bn = [0.0] * N
    bo = [0.0] * N
    bt = [0.0] * N
    ba = [float(max_age)] * N
    rn = [0.0] * N
    ro = [0.0] * N
    bull: list = []
    bear: list = []          # [top, bottom, doğum_i]
    for i in range(N):
        nb = []
        tap = 0.0
        for g in bull:
            if i - g[2] > max_age or ll[i] <= g[1]:
                continue                                                        # süresi doldu / doldu
            if i > g[2] and ll[i] <= g[0] and cl[i] > g[1]:
                tap = 1.0
            nb.append(g)
        bull = nb
        bear = [g for g in bear if not (i - g[2] > max_age or hl[i] >= g[0])]
        if i >= 2 and atl[i - 1] == atl[i - 1] and atl[i - 1] > 0:
            a = atl[i - 1]
            if ll[i] > hl[i - 2] and (ll[i] - hl[i - 2]) >= min_atr * a:
                bull.append([ll[i], hl[i - 2], i])
                bn[i] = (ll[i] - hl[i - 2]) / a
            if hl[i] < ll[i - 2] and (ll[i - 2] - hl[i]) >= min_atr * a:
                bear.append([ll[i - 2], hl[i], i])
                rn[i] = (ll[i - 2] - hl[i]) / a
        bo[i] = float(len(bull))
        ro[i] = float(len(bear))
        bt[i] = tap
        ba[i] = float(min(i - bull[-1][2], max_age)) if bull else float(max_age)
    out = {"bull_new": np.asarray(bn), "bull_open": np.asarray(bo), "bull_tap": np.asarray(bt), "bull_age": np.asarray(ba),
           "bear_new": np.asarray(rn), "bear_open": np.asarray(ro)}
    for v_ in out.values():
        v_[:20] = np.nan
    return out


@_export
def displacement(o, c, h, l, k: float = 1.5) -> dict[str, np.ndarray]:
    """Yer değiştirme: gövde > k·ATR14[i−1]. {"body_atr" (işaretli gövde/ATR), "up", "down", "up_cnt5" (son 5 barda yukarı yer değiştirme sayısı)}."""
    o = _f(o)
    c = _f(c)
    atr = shift(P.atr_series(_f(h), _f(l), c, 14), 1)
    b = _div(c - o, atr)
    fin = np.isfinite(b)
    up = np.where(fin, (b > k).astype(float), np.nan)
    dn = np.where(fin, (b < -k).astype(float), np.nan)
    return {"body_atr": b, "up": up, "down": dn, "up_cnt5": np.where(fin, _roll_sum0(up, 5), np.nan)}


@_export
def order_blocks(o, h, l, c, k: float = 1.5, lookback: int = 5, max_age: int = 60) -> dict[str, np.ndarray]:
    """Yükseliş order block: yukarı yer değiştirme (gövde > k·ATR14[i−1]) barından önceki SON düşüş mumunun [low, high] bölgesi (j−1…j−lookback).
    Bölge, kapanış bölge altına inince ya da `max_age` sonra geçersiz. Çıktılar:
      "dist" (kapanışın en yakın aktif OB üstüne % uzaklığı; aktif yoksa +10; ±10'a kırpılı), "active" (aktif OB sayısı),
      "tap" (bu bar önceki bir aktif OB bölgesine girdi: low ≤ üst ve kapanış ≥ alt), "age" (en yeni aktif OB yaşı, yoksa max_age)."""
    o = _f(o)
    h = _f(h)
    l = _f(l)
    c = _f(c)
    N = len(c)
    atl = shift(P.atr_series(h, l, c, 14), 1).tolist()
    ol = o.tolist()
    hl = h.tolist()
    ll = l.tolist()
    cl = c.tolist()
    dist = [10.0] * N
    act = [0.0] * N
    tap = [0.0] * N
    age = [float(max_age)] * N
    obs: list = []                                                           # [top, bottom, doğum_i]
    for i in range(N):
        keep = []
        t = 0.0
        for z in obs:
            if i - z[2] > max_age or cl[i] < z[1]:
                continue
            if i > z[2] and ll[i] <= z[0] and cl[i] >= z[1]:
                t = 1.0
            keep.append(z)
        obs = keep
        a = atl[i]
        if a == a and a > 0 and (cl[i] - ol[i]) > k * a:
            for j in range(i - 1, max(i - lookback, 0) - 1, -1):
                if cl[j] < ol[j]:
                    obs.append([hl[j], ll[j], i])
                    break
        act[i] = float(len(obs))
        tap[i] = t
        if obs:
            best = min(obs, key=lambda z: abs(cl[i] - z[0]))
            dist[i] = max(-10.0, min(10.0, (cl[i] / best[0] - 1.0) * 100.0))
            age[i] = float(min(i - obs[-1][2], max_age))
    out = {"dist": np.asarray(dist), "active": np.asarray(act), "tap": np.asarray(tap), "age": np.asarray(age)}
    for v_ in out.values():
        v_[:20] = np.nan
    return out


@_export
def td_sequential(c) -> dict[str, np.ndarray]:
    """TD Sequential KURULUM sayacı (9'a kadar döner): "buy" = ardışık (c < c[−4]) sayısı, "sell" = ardışık (c > c[−4]); "buy9"/"sell9" = bu barda 9 tamamlandı."""
    c = _f(c)
    c4 = shift(c, 4)
    with np.errstate(invalid="ignore"):
        bu = _run(c < c4)
        se = _run(c > c4)
    bu_c = np.where(bu > 0, ((bu - 1) % 9) + 1, 0.0)
    se_c = np.where(se > 0, ((se - 1) % 9) + 1, 0.0)
    return {"buy": bu_c, "sell": se_c, "buy9": (bu_c == 9).astype(float), "sell9": (se_c == 9).astype(float)}


# ----------------------------------------------------------------------------------------------- toplu hesap
def _slope3(m):
    return _div(m - shift(m, 3), shift(m, 3)) * 100.0


FAMILY: dict[str, str] = {}


@_export
def compute_all(arr: np.ndarray, tf: str = "5m") -> tuple[list[str], np.ndarray]:
    """Kütüphanenin TÜM özelliklerini bir zaman dilimi dizisi için hesaplar: (isimler `<tf>.<ad>`, float32 matris n × F).
    `arr` pattern_study düzeninde (7 kolon ya da 9 kolon: taker); i. satır yalnız ≤ i barlarına bağlıdır.
    `tf` ∈ {"1m","5m","15m"} — 24 sa pencere uzunluğunu (AVWAP/hacim profili/z-skor tabanı) belirler. POC 1m için hesaplanmaz (sütun yok).
    Taker kolonları yoksa cvd_*/ofi_z sütunları NaN."""
    t = arr[:, P.COL_OT].astype(np.int64)
    o, h, l, c = (arr[:, k].astype(float) for k in (P.COL_O, P.COL_H, P.COL_L, P.COL_C))
    v = _nz(arr[:, P.COL_V])
    qv = _nz(arr[:, P.COL_QV])
    has_tk = arr.shape[1] > P.COL_TBQ
    tbq = _nz(arr[:, P.COL_TBQ]) if has_tk else np.zeros(len(c))
    N = len(c)
    bpd = BARS_PER_DAY[tf]
    F: dict[str, np.ndarray] = {}

    def put(fam, d):
        for kk, vv in d.items():
            F[kk] = vv
            FAMILY[kk] = fam

    # --- hareketli ortalamalar
    ma = {"alma": alma(c, 9), "wma": wma(c, 20), "hma": hull_ma(c, 21), "dema": dema(c, 20), "tema": tema(c, 20),
          "kama": kama(c, 10), "mcg": mcginley(c, 14)}
    d = {}
    for kk, m in ma.items():
        d[f"px_{kk}"] = _div(c, m) * 100.0 - 100.0
        d[f"slope_{kk}"] = _slope3(m)
    lr = linreg_band(c, 20)
    d["lsma_px"] = _div(c - lr["value"], c) * 100.0
    d["lsma_z"] = _div(c - lr["value"], lr["stderr"], default=0.0)
    d["lsma_se_pct"] = _div(lr["stderr"], c) * 100.0
    put("ma", d)
    # --- hacim / akış
    d = {}
    d["obv_slope12"] = obv_slope(c, v, 12)
    d["obv_slope48"] = obv_slope(c, v, 48)
    d["ad_slope12"] = ad_slope(h, l, c, v, 12)
    d["cmf20"] = cmf(h, l, c, v, 20)
    d["cmf20_chg5"] = d["cmf20"] - shift(d["cmf20"], 5)
    d["chaikin_osc"] = chaikin_osc(h, l, c, v)
    kv = klinger(h, l, c, v)
    d["kvo"] = kv["kvo"]
    d["kvo_hist"] = kv["hist"]
    d["eom14"] = ease_of_movement(h, l, qv, 14)
    d["efi13"] = force_index(c, v, 13)
    d["pvt_slope12"] = pvt_slope(c, v, 12)
    d["vol_osc"] = volume_oscillator(v, 5, 10)
    d["cvd_slope12"] = cvd_slope(qv, tbq, 12)
    d["cvd_slope48"] = cvd_slope(qv, tbq, 48)
    d["ofi_z"] = orderflow_imbalance_z(qv, tbq, 3, bpd)
    if not has_tk:
        for kk in ("cvd_slope12", "cvd_slope48", "ofi_z"):
            d[kk] = np.full(N, np.nan)
    put("flow", d)
    # --- osilatörler
    d = {}
    d["cmo14"] = cmo(c, 14)
    d["crsi"] = connors_rsi(c)
    st = stochastic(h, l, c)
    d["stoch_k"] = st["k"]
    d["stoch_d"] = st["d"]
    d["stoch_kd"] = st["k"] - st["d"]
    sr = stochrsi(c)
    d["stochrsi_k"] = sr["k"]
    d["stochrsi_d"] = sr["d"]
    d["stochrsi_kd"] = sr["k"] - sr["d"]
    d["willr14"] = williams_r(h, l, c, 14)
    d["ultosc"] = ultimate_osc(h, l, c)
    ao = awesome_osc(h, l)
    d["ao_pct"] = ao
    d["ao_chg"] = ao - shift(ao, 1)
    ts = tsi(c)
    d["tsi"] = ts
    d["tsi_sig_diff"] = ts - ema(ts, 7)
    tx = trix(c, 15)
    d["trix"] = tx
    d["trix_sig_diff"] = tx - ema(tx, 9)
    ks = kst(c)
    d["kst"] = ks["kst"]
    d["kst_sig_diff"] = ks["kst"] - ks["signal"]
    fi = fisher_transform(h, l, 9)
    d["fisher"] = fi["fisher"]
    d["fisher_chg"] = fi["fisher"] - fi["trigger"]
    rv = rvi_vigor(o, h, l, c)
    d["rvi"] = rv["rvi"]
    d["rvi_sig_diff"] = rv["rvi"] - rv["signal"]
    d["bop14"] = balance_of_power(o, h, l, c, 14)
    d["cci20"] = cci(h, l, c, 20)
    d["dpo20"] = dpo(c, 20)
    sm = smi_ergodic(c)
    d["smi_erg"] = sm["smi"]
    d["smi_sig_diff"] = sm["smi"] - sm["signal"]
    d["coppock"] = coppock(c)
    put("osc", d)
    # --- trend / yapı
    d = {}
    vx = vortex(h, l, c, 14)
    d["vi_plus"] = vx["plus"]
    d["vi_minus"] = vx["minus"]
    d["vi_diff"] = vx["diff"]
    cu = np.zeros(N)
    cu[1:] = ((vx["diff"][1:] > 0) & (vx["diff"][:-1] <= 0)).astype(float)
    d["vortex_cross_up3"] = np.where(np.isfinite(vx["diff"]), (_roll_sum0(cu, 3) > 0).astype(float), np.nan)
    ps = parabolic_sar(h, l)
    d["psar_state"] = ps["state"]
    d["psar_dist"] = _div(c - ps["sar"], c) * 100.0
    d["psar_flip_up3"] = np.where(np.isfinite(ps["state"]), (_roll_sum0((ps["flip"] > 0).astype(float), 3) > 0).astype(float), np.nan)
    s1 = supertrend(h, l, c, 10, 3.0)
    d["st_state"] = s1["state"]
    d["st_dist"] = _div(c - s1["line"], c) * 100.0
    d["st_flip_up3"] = np.where(np.isfinite(s1["state"]), (_roll_sum0((s1["flip"] > 0).astype(float), 3) > 0).astype(float), np.nan)
    sc = supertrend_cluster(h, l, c)
    d["st_cluster_sum"] = sc["sum"]
    d["st_cluster_flip_up3"] = sc["flip_up_3"]
    d["st_cluster_agree_up"] = sc["agree_up"]
    d["st_cluster_flip_all_up"] = sc["flip_all_up"]
    for kk, vv in ichimoku(h, l, c).items():
        d["ichi_" + kk] = vv
    dn = donchian(h, l, c, 20)
    d["donch_pos20"] = dn["pos"]
    d["donch_break20"] = dn["break_up"]
    d["donch_width20"] = dn["width"]
    d["inside_break_up"] = inside_bar_breakout(h, l, c)["up"]
    kc = keltner(h, l, c)
    d["kc_pos"] = kc["pos"]
    d["kc_width"] = kc["width"]
    sq = squeeze(h, l, c)
    d["squeeze_on"] = sq["on"]
    d["squeeze_run"] = sq["run"]
    d["bb_kc_ratio"] = sq["ratio"]
    d["squeeze_since_off"] = sq["since_off"]
    d["squeeze_release"] = sq["release"]
    ch = choppiness(h, l, c, 14)
    d["chop14"] = ch
    d["chop_drop12"] = ch - rolling_max(shift(ch, 1), 12)
    d["mass_index"] = mass_index(h, l)
    put("trend", d)
    # --- oynaklık
    d = {}
    d["atr_ratio"] = atr_ratio(h, l, c)
    d["hv20"] = hist_vol(c, 20)
    d["chaikin_vol"] = chaikin_volatility(h, l)
    d["rvi_vol"] = relative_volatility_index(c)
    put("vol", d)
    # --- konum: VWAP / POC
    d = {}
    vw = vwap_session(t, h, l, c, v)
    d["vwap_dist"] = _div(c, vw) * 100.0 - 100.0
    av = anchored_vwap_swing_low(h, l, c, v, bpd)
    d["avwap_dist"] = _div(c, av["vwap"]) * 100.0 - 100.0
    d["avwap_age"] = av["age"]
    if tf != "1m":
        d["poc_dist"] = _div(c, volume_profile_poc(h, l, c, v, bpd, 50)) * 100.0 - 100.0
    put("loc", d)
    # --- SMC
    d = {}
    for kk, vv in market_structure(o, h, l, c).items():
        d["ms_" + kk] = vv
    for kk, vv in fair_value_gaps(h, l, c).items():
        d["fvg_" + kk] = vv
    for kk, vv in order_blocks(o, h, l, c).items():
        d["ob_" + kk] = vv
    for kk, vv in displacement(o, c, h, l).items():
        d["disp_" + kk] = vv
    for kk, vv in td_sequential(c).items():
        d["td_" + kk] = vv
    put("smc", d)
    names = [f"{tf}.{k}" for k in F]
    if not F:
        return names, np.zeros((N, 0), np.float32)
    X = np.column_stack([F[k] for k in F])
    X[~np.isfinite(X) | (np.abs(X) > 1e9)] = np.nan               # sonsuz / absürt değerler → NaN (float32 taşmasını önler)
    return names, X.astype(np.float32)


def feature_names(tf: str = "5m") -> list[str]:
    """`compute_all`'ın üreteceği sütun adları (sahte dizi üzerinden; FAMILY'yi de doldurur)."""
    n = 700
    arr = np.zeros((n, 9))
    rng = np.random.default_rng(0)
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    arr[:, 0] = np.arange(n) * 300_000
    arr[:, 1] = np.r_[c[0], c[:-1]]
    arr[:, 4] = c
    arr[:, 2] = np.maximum(arr[:, 1], c) * 1.001
    arr[:, 3] = np.minimum(arr[:, 1], c) * 0.999
    arr[:, 5] = 100.0 + rng.random(n) * 50
    arr[:, 6] = arr[:, 5] * c
    arr[:, 7] = arr[:, 5] * 0.5
    arr[:, 8] = arr[:, 6] * 0.5
    return compute_all(arr, tf)[0]


__all__ += ["feature_names", "FAMILY", "shift", "rsum", "rolling_max", "rolling_min", "flow_share"]
