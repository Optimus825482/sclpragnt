"""Yeni erken-giriş dedektörü prototipleri (çevrimdışı, 2026-10-17) — merdiven denemesinin başarısızlığından sonra.

Dört FARKLI fikir; hepsi saf numpy (EMA için varsa scipy.lfilter, yoksa döngü), ağ/DB yok, canlı koda bağlanmaz:

  1. ema_fan_5m          — EMA7 > EMA20 > EMA99 (5m) yeni açıldı, EMA7 yukarı eğimli, 6 barlık kazanç sınırlı, RSI ≤ 70
  2. breakout_compress_5m — Bollinger(20) genişliği sıkışmışken önceki 48 bar zirvesinin hacimli kırılımı
  3. rs_vs_btc_5m         — altcoin kendi başına yükseliyor (30 dk getirisi BTC'den ≥ x puan fazla, BTC yatay/düşük)
  4. persist_1m           — 1 dk'da kapanış > EMA9 > EMA21 en az M dakika kesintisiz, hacim artıyor, kazanç sınırlı

Dizi kolonları (ladder.py ile aynı): open_time(ms), open, high, low, close, volume, quote_volume.
Her dedektör SİNYAL BAR İNDEKSLERİNİ döner (bar kapandıktan sonra; giriş = o barın kapanışı), sembol başına 60 dk soğuma.
"""
from __future__ import annotations

import numpy as np

from app.rescan.ladder import COL_C, COL_H, COL_L, COL_O, COL_OT, COL_QV, COL_V, rolling_sum, rsi_wilder  # noqa: F401

BAR_5M_MS = 300_000
BAR_1M_MS = 60_000

try:  # hızlı EMA; yoksa saf döngü
    from scipy.signal import lfilter as _lfilter
except Exception:  # pragma: no cover
    _lfilter = None


def ema(x: np.ndarray, period: int) -> np.ndarray:
    """Standart EMA (alpha = 2/(p+1), ilk değerle tohumlu, ewm adjust=False ile aynı)."""
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return x.copy()
    a = 2.0 / (period + 1.0)
    if _lfilter is not None and np.isfinite(x).all():
        y, _ = _lfilter([a], [1.0, -(1.0 - a)], x, zi=[(1.0 - a) * x[0]])
        return y
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1.0 - a) * out[i - 1]
    return out


def run_length(cond: np.ndarray) -> np.ndarray:
    """run[i] = i'de biten ardışık True sayısı (vektörel)."""
    n = len(cond)
    ar = np.arange(n)
    last_false = np.maximum.accumulate(np.where(cond, -1, ar))
    return np.where(cond, ar - last_false, 0).astype(np.int64)


def cooldown(idx: np.ndarray, bars: int) -> np.ndarray:
    """Aynı sembolde ardışık sinyaller arası en az `bars` bar."""
    if bars <= 1 or len(idx) == 0:
        return idx.astype(np.int64)
    kept: list[int] = []
    last = -10 ** 9
    for i in idx:
        if i - last >= bars:
            kept.append(int(i))
            last = int(i)
    return np.array(kept, dtype=np.int64)


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    """out[i] = x[i-k] (başı NaN)."""
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[: len(x) - k]
    return out


def _ratio_prev(v: np.ndarray, n: int) -> np.ndarray:
    """v[i] / (önceki n barın ortalaması; i dahil değil)."""
    prev = np.full(len(v), np.nan)
    s = rolling_sum(np.nan_to_num(v, nan=0.0), n)
    prev[1:] = s[:-1] / n
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(prev > 0, v / prev, np.nan)


def signal_time_ms(arr: np.ndarray, i: int, bar_ms: int = BAR_5M_MS) -> int:
    """Sinyal anı = barın kapanış zamanı (open_time + bar süresi)."""
    return int(arr[i, COL_OT]) + bar_ms


# --------------------------------------------------------------------------------------------- 1. EMA yelpazesi
def ema_fan_5m(arr: np.ndarray, *, k: int = 3, g_min: float = 0.8, g_max: float = 4.0, rsi_max: float = 70.0,
               min_quote_24h: float = 5_000_000.0, cooldown_bars: int = 12) -> np.ndarray:
    """EMA7 > EMA20 > EMA99 (5m kapanış) YENİ açıldı (k+1 bar önce açık değildi), EMA7 son k barda yükseliyor,
    son 6 barlık kümülatif kazanç [g_min, g_max] %, RSI14(5m) ≤ rsi_max."""
    c = arr[:, COL_C]
    n = len(c)
    if n < 330:
        return np.zeros(0, dtype=np.int64)
    e7, e20, e99 = ema(c, 7), ema(c, 20), ema(c, 99)
    fan = (e7 > e20) & (e20 > e99)
    up_run = np.zeros(n, dtype=np.int64)
    up_run[1:] = run_length(e7[1:] > e7[:-1])
    fresh = np.zeros(n, dtype=bool)
    fresh[k + 1:] = ~fan[: n - k - 1]
    gain6 = (c / _shift(c, 6) - 1.0) * 100.0
    rsi = rsi_wilder(c, 14)
    qv24 = rolling_sum(np.nan_to_num(arr[:, COL_QV], nan=0.0), 288)
    with np.errstate(invalid="ignore"):
        cond = (fan & fresh & (up_run >= k) & (gain6 >= g_min) & (gain6 <= g_max)
                & (rsi <= rsi_max) & (qv24 >= min_quote_24h))
    cond[:300] = False  # EMA99 ısınması + 24 sa likidite penceresi
    return cooldown(np.flatnonzero(cond), cooldown_bars)


# --------------------------------------------------------------------------------------------- 2. Sıkışma kırılımı
def bollinger_width(c: np.ndarray, period: int = 20) -> np.ndarray:
    """(üst − alt) / orta = 4·std/ortalama (popülasyon std); ilk period-1 değer NaN."""
    n = len(c)
    out = np.full(n, np.nan)
    if n < period:
        return out
    win = np.lib.stride_tricks.sliding_window_view(c, period)
    m = win.mean(axis=1)
    sd = win.std(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[period - 1:] = np.where(m > 0, 4.0 * sd / m, np.nan)
    return out


def breakout_compress_5m(arr: np.ndarray, *, vol_min: float = 1.5, hi_lb: int = 48, squeeze_q: float = 1 / 3,
                         rsi_max: float = 75.0, gain3_max: float = 4.0, min_quote_24h: float = 5_000_000.0,
                         cooldown_bars: int = 12) -> np.ndarray:
    """Bollinger(20) genişliğinin son 24 bar ortalaması, son 100 barlık genişlik dağılımının alt üçte birinde
    (sıkışma) ve kapanış önceki `hi_lb` barın en yükseğini aşıyor; bar hacmi ≥ vol_min × önceki 20 bar ortalaması;
    RSI14 ≤ rsi_max; son 3 bar kazancı ≤ gain3_max (patlamış değil)."""
    c = arr[:, COL_C]; h = arr[:, COL_H]
    n = len(c)
    if n < 330:
        return np.zeros(0, dtype=np.int64)
    w = bollinger_width(c, 20)
    # w[19:] NaN'sız; pencere i-100..i-1 (i hariç) için alt-üçte-bir eşiği
    wv = w[19:]
    thr = np.full(n, np.nan)
    if len(wv) >= 100:
        q = np.quantile(np.lib.stride_tricks.sliding_window_view(wv, 100), squeeze_q, axis=1)  # q[k]: wv[k..k+99]
        # wv[k+99] = w[k+118]; i = k+119 için pencere i-100..i-1 = w[k+19..k+118] = wv[k..k+99]
        thr[119: 119 + len(q)] = q[: n - 119] if len(q) > n - 119 else q
    s24 = rolling_sum(np.nan_to_num(w, nan=0.0), 24) / 24.0
    mean24_prev = _shift(s24, 1)  # i hariç son 24 bar
    prior_hi = np.full(n, np.nan)
    if n > hi_lb:
        sw = np.lib.stride_tricks.sliding_window_view(h, hi_lb).max(axis=1)  # sw[j]: h[j..j+hi_lb-1]
        prior_hi[hi_lb:] = sw[: n - hi_lb]
    volr = _ratio_prev(arr[:, COL_V], 20)
    rsi = rsi_wilder(c, 14)
    gain3 = (c / _shift(c, 3) - 1.0) * 100.0
    qv24 = rolling_sum(np.nan_to_num(arr[:, COL_QV], nan=0.0), 288)
    with np.errstate(invalid="ignore"):
        cond = ((mean24_prev <= thr) & (c > prior_hi) & (volr >= vol_min) & (rsi <= rsi_max)
                & (gain3 <= gain3_max) & (qv24 >= min_quote_24h))
    cond[:300] = False
    return cooldown(np.flatnonzero(cond), cooldown_bars)


# --------------------------------------------------------------------------------------------- 3. BTC'ye göre güç
def rs_vs_btc_5m(arr: np.ndarray, btc_ot: np.ndarray, btc_close: np.ndarray, *, x: float = 1.0,
                 vol_min: float = 1.0, btc_max: float = 0.2, g60_max: float = 5.0, rsi_max: float = 100.0,
                 min_quote_24h: float = 5_000_000.0, cooldown_bars: int = 12) -> np.ndarray:
    """30 dk getirisi (6 bar) − BTCTRY 30 dk getirisi ≥ x puan ve sembolün kendi 30 dk getirisi > 0; BTC 30 dk
    getirisi ≤ btc_max %; son 3 bar yükselen dipler; bar hacmi ≥ vol_min × önceki 20 bar ort.; 60 dk (12 bar)
    kazancı ≤ g60_max %. BTC, open_time ile hizalanır (eksik bar → sinyal yok)."""
    c = arr[:, COL_C]; l = arr[:, COL_L]
    n = len(c)
    if n < 330 or len(btc_ot) == 0:
        return np.zeros(0, dtype=np.int64)
    j = np.searchsorted(btc_ot, arr[:, COL_OT])
    j = np.clip(j, 0, len(btc_ot) - 1)
    ok = btc_ot[j] == arr[:, COL_OT]
    bc = np.where(ok, btc_close[j], np.nan)
    ret_s = (c / _shift(c, 6) - 1.0) * 100.0
    ret_b = (bc / _shift(bc, 6) - 1.0) * 100.0
    hl = np.zeros(n, dtype=bool)
    hl[2:] = (l[2:] > l[1:-1]) & (l[1:-1] > l[:-2])
    g60 = (c / _shift(c, 12) - 1.0) * 100.0
    volr = _ratio_prev(arr[:, COL_V], 20)
    rsi = rsi_wilder(c, 14)
    qv24 = rolling_sum(np.nan_to_num(arr[:, COL_QV], nan=0.0), 288)
    with np.errstate(invalid="ignore"):
        cond = ((ret_s - ret_b >= x) & (ret_s > 0) & (ret_b <= btc_max) & hl & (volr >= vol_min)
                & (g60 <= g60_max) & (rsi <= rsi_max) & (qv24 >= min_quote_24h))
    cond[:300] = False
    return cooldown(np.flatnonzero(cond), cooldown_bars)


# --------------------------------------------------------------------------------------------- 4. 1 dk kalıcılık
def persist_1m(arr: np.ndarray, *, m: int = 8, g_min: float = 0.6, g_max: float = 3.0, vol_min: float = 1.2,
               rsi_max: float = 75.0, min_quote_24h: float = 5_000_000.0, cooldown_bars: int = 60,
               align_5m: bool = False) -> np.ndarray:
    """align_5m=True: yalnız 5 dk sınırında kapanan 1m barlarda sinyal (5m değerlendirme/şans tabanıyla birebir
    hizalı duyarlılık varyantı; canlı tarama kadansına da benzer).

    1 dk: kapanış > EMA9 ve EMA9 > EMA21 en az m dakika kesintisiz; EMA21 10 dk eğimi > 0; m dakikalık kazanç
    [g_min, g_max] %; son m dakikanın dakika-başı hacmi ≥ vol_min × ondan önceki 60 dakikanın dakika-başı ort.;
    RSI14(1m) ≤ rsi_max; 24 sa (1440 dk) quote ≥ min_quote_24h."""
    c = arr[:, COL_C]; v = np.nan_to_num(arr[:, COL_V], nan=0.0)
    n = len(c)
    if n < 1500 + m:
        return np.zeros(0, dtype=np.int64)
    e9, e21 = ema(c, 9), ema(c, 21)
    run = run_length((c > e9) & (e9 > e21))
    slope = e21 > _shift(e21, 10)
    gain = (c / _shift(c, m) - 1.0) * 100.0
    vm = rolling_sum(v, m) / m
    v60 = rolling_sum(v, 60) / 60.0
    prior = _shift(v60, m)  # i-m'de biten 60 dk
    with np.errstate(divide="ignore", invalid="ignore"):
        volr = np.where(prior > 0, vm / prior, np.nan)
    rsi = rsi_wilder(c, 14)
    qv24 = rolling_sum(np.nan_to_num(arr[:, COL_QV], nan=0.0), 1440)
    with np.errstate(invalid="ignore"):
        cond = ((run >= m) & slope & (gain >= g_min) & (gain <= g_max) & (volr >= vol_min)
                & (rsi <= rsi_max) & (qv24 >= min_quote_24h))
    cond[:1500] = False
    if align_5m:
        cond &= ((arr[:, COL_OT] + BAR_1M_MS) % BAR_5M_MS) == 0
    return cooldown(np.flatnonzero(cond), cooldown_bars)
