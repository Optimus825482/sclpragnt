"""Veri-önce çıkış deseni çalışması — saf numpy yardımcıları (2026-10-17, çevrimdışı).

Canlı koda bağlanmaz; ağ/DB yok. `scripts/breakout_pattern_study.py` bunları kullanır.

İçerik
  * `aggregate_bars`      — 1 dk mumlardan k dk mum (3 dk): open_time k·dk sınırlarına hizalı, yalnız TAM kovalar.
  * `features_matrix`     — bir zaman dilimi için ~44 gösterge (kanonik `app.technical_analysis` tanımlarıyla birebir;
                            parite testi `tests/test_pattern_study.py`). Hepsi nedensel: i. değer yalnız ≤ i barları kullanır.
  * `event_mask` / `find_events` — "LUNA tipi" merdiven yükseliş olayı tanımı (parametreleri `EventParams`).
  * `auc_matrix`, `smd`, `fwer_threshold` — olay/taban karşılaştırma istatistikleri.
  * `fit_pattern_tree`    — sığ karar ağacından birleşik (AND) desen çıkarımı.
  * `Condition`, `eval_conditions` — desenleri eşik koşullarının bileşimi olarak ifade etme/uygulama.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import lfilter

# Dizi kolonları (ladder.py / strategies.py ile aynı): open_time(ms), open, high, low, close, volume, quote_volume
COL_OT, COL_O, COL_H, COL_L, COL_C, COL_V, COL_QV = range(7)
BAR_1M_MS = 60_000
BAR_5M_MS = 300_000
TF_BAR_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000}
TF_BARS_PER_DAY = {"1m": 1440, "3m": 480, "5m": 288}
TZ_OFFSET_H = 3  # İstanbul (DST yok)


# ----------------------------------------------------------------------------------------------- toplulaştırma
def aggregate_bars(arr: np.ndarray, factor: int, bar_ms: int = BAR_1M_MS) -> np.ndarray:
    """`bar_ms` mumlarından `factor` katı süreli mum üretir (1 dk → 3 dk için factor=3).

    open_time, factor·bar_ms sınırlarına hizalanır (3 dk: open_time % 180000 == 0). YALNIZ eksiksiz kovalar
    (factor adet mum, dakika ofsetleri 0..factor-1) üretilir; eksik/kısmi kova (veri başı/sonu ya da boşluk) atılır.
    open = kovanın ilk açılışı, high = max, low = min, close = son kapanış, volume/quote_volume = toplam.
    """
    if len(arr) == 0:
        return np.zeros((0, 7))
    ot = arr[:, COL_OT].astype(np.int64)
    span = factor * bar_ms
    b = ot // span
    chg = np.flatnonzero(np.diff(b)) + 1
    starts = np.concatenate([[0], chg]).astype(np.int64)
    ends = np.concatenate([chg, [len(b)]]).astype(np.int64)
    cnt = ends - starts
    kb = b[starts]
    ok = (cnt == factor) & (ot[starts] == kb * span) & (ot[ends - 1] == kb * span + (factor - 1) * bar_ms)
    if not ok.any():
        return np.zeros((0, 7))
    st, en, kb = starts[ok], ends[ok], kb[ok]
    out = np.empty((len(st), 7))
    out[:, COL_OT] = kb * span
    out[:, COL_O] = arr[st, COL_O]
    out[:, COL_C] = arr[en - 1, COL_C]
    # reduceat tüm diziyi bölümler; ok olmayan kovaları da hesaplayıp sonra seçmek için tam kova başlangıçlarından
    h_all = np.maximum.reduceat(arr[:, COL_H], starts)
    l_all = np.minimum.reduceat(arr[:, COL_L], starts)
    v_all = np.add.reduceat(np.nan_to_num(arr[:, COL_V], nan=0.0), starts)
    q_all = np.add.reduceat(np.nan_to_num(arr[:, COL_QV], nan=0.0), starts)
    out[:, COL_H], out[:, COL_L] = h_all[ok], l_all[ok]
    out[:, COL_V], out[:, COL_QV] = v_all[ok], q_all[ok]
    return out


def fill_gaps(arr: np.ndarray, bar_ms: int) -> np.ndarray:
    """Eksik mum satırlarını (o aralıkta işlem yok) DÜZ mumla doldurur: open=high=low=close=önceki kapanış, hacim 0.

    Likit olmayan TRY çiftlerinde 5 dk / 1 dk satırlar sık eksiktir (ör. LUNATRY 17 Ekim 01:00–01:25); ham satır
    sayısıyla EMA/RSI/24 sa pencereleri zamanla uyumsuzlaşır. Doldurma TradingView/exchange grafiğiyle aynıdır
    ve 24 sa pencereyi gerçekten 24 saat yapar. Zaman ızgarası ilk–son open_time arası tamdır."""
    if len(arr) < 2:
        return arr.copy()
    ot = arr[:, COL_OT].astype(np.int64)
    n_full = int((ot[-1] - ot[0]) // bar_ms) + 1
    if n_full == len(arr) and np.all(np.diff(ot) == bar_ms):
        return arr.copy()
    pos = ((ot - ot[0]) // bar_ms).astype(np.int64)
    out = np.zeros((n_full, 7))
    out[:, COL_OT] = ot[0] + np.arange(n_full, dtype=np.int64) * bar_ms
    have = np.zeros(n_full, dtype=bool); have[pos] = True
    out[pos] = arr[:, :7]
    # önceki gerçek barın kapanışı: have olan son indeksin kapanışı
    last_idx = np.maximum.accumulate(np.where(have, np.arange(n_full), -1))
    fc = out[last_idx, COL_C]
    miss = ~have
    for k in (COL_O, COL_H, COL_L, COL_C):
        out[miss, k] = fc[miss]
    out[miss, COL_V] = 0.0; out[miss, COL_QV] = 0.0
    return out


# ----------------------------------------------------------------------------------------------- temel yardımcılar
def rolling_sum(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1:] = c[n:] - c[:-n]
    return out


def shift(x: np.ndarray, k: int) -> np.ndarray:
    """out[i] = x[i-k] (başı NaN)."""
    out = np.full(len(x), np.nan)
    if 0 < k < len(x):
        out[k:] = x[: len(x) - k]
    elif k == 0:
        out[:] = x
    return out


def run_length(cond: np.ndarray) -> np.ndarray:
    """run[i] = i'de biten ardışık True sayısı."""
    n = len(cond)
    ar = np.arange(n)
    last_false = np.maximum.accumulate(np.where(cond, -1, ar))
    return np.where(cond, ar - last_false, 0).astype(np.int64)


def _recursive(x: np.ndarray, p: int, alpha: float) -> np.ndarray:
    """out[f+p-1] = mean(x[f:f+p]) (f = ilk sonlu indeks); sonra out[i] = alpha·x[i] + (1-alpha)·out[i-1]. Öncesi NaN.
    Kanonik `_ema_series` / `_wilder_series` (SMA tohumlu) ile aynı."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    fin = np.flatnonzero(np.isfinite(x))
    if len(fin) == 0:
        return out
    f = int(fin[0])
    y = x[f:]
    if len(y) < p:
        return out
    seed = float(y[:p].mean())
    out[f + p - 1] = seed
    if len(y) > p:
        z, _ = lfilter([alpha], [1.0, -(1.0 - alpha)], y[p:], zi=[(1.0 - alpha) * seed])
        out[f + p:] = z
    return out


def ema_seeded(x: np.ndarray, p: int) -> np.ndarray:
    return _recursive(x, p, 2.0 / (p + 1.0))


def wilder_smooth(x: np.ndarray, p: int) -> np.ndarray:
    return _recursive(x, p, 1.0 / p)


def rsi_series(c: np.ndarray, p: int = 14) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) <= p:
        return out
    d = np.diff(c)
    ag = wilder_smooth(np.where(d > 0, d, 0.0), p)
    al = wilder_smooth(np.where(d < 0, -d, 0.0), p)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(al == 0, np.where(ag > 0, 100.0, 50.0), 100.0 - 100.0 / (1.0 + ag / al))
    r = np.where(np.isfinite(ag) & np.isfinite(al), r, np.nan)
    out[1:] = r
    return out


def mfi_series(h, l, c, v, p: int = 14) -> np.ndarray:
    n = len(c)
    out = np.full(n, np.nan)
    if n <= p:
        return out
    tp = (h + l + c) / 3.0
    flow = tp * np.nan_to_num(v, nan=0.0)
    pos = np.zeros(n); neg = np.zeros(n)
    up = tp[1:] > tp[:-1]; dn = tp[1:] < tp[:-1]
    pos[1:] = np.where(up, flow[1:], 0.0); neg[1:] = np.where(dn, flow[1:], 0.0)
    ps = np.maximum(rolling_sum(pos, p), 0.0); ns = np.maximum(rolling_sum(neg, p), 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(ns > 0, 100.0 - 100.0 / (1.0 + ps / ns), np.where(ps > 0, 100.0, 50.0))
    out[p:] = r[p:]
    return out


def atr_series(h, l, c, p: int = 14) -> np.ndarray:
    """Kanonik `_atr`: son p gerçek aralığın BASİT ortalaması."""
    n = len(c)
    tr = np.full(n, np.nan)
    if n < 2:
        return tr
    pc = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    out = np.full(n, np.nan)
    if n >= p + 1:
        out[p:] = rolling_sum(tr[1:], p)[p - 1:] / p
    return out


def bollinger_series(c: np.ndarray, p: int = 20, k: float = 2.0):
    """(genişlik_oran, %B). Kanonik `_bollinger`: popülasyon std, width=(üst-alt)/orta, position=(c-alt)/(üst-alt)."""
    n = len(c)
    w = np.full(n, np.nan); pb = np.full(n, np.nan)
    if n < p:
        return w, pb
    win = np.lib.stride_tricks.sliding_window_view(c, p)
    m = win.mean(axis=1); sd = win.std(axis=1)
    up, lo = m + k * sd, m - k * sd
    with np.errstate(divide="ignore", invalid="ignore"):
        w[p - 1:] = np.where(m != 0, (up - lo) / m, np.nan)
        pb[p - 1:] = np.where(up != lo, (c[p - 1:] - lo) / (up - lo), np.nan)
    return w, pb


def macd_series(c: np.ndarray, fast: int = 12, slow: int = 26, sig: int = 9):
    """(çizgi, sinyal, histogram) — kanonik `_macd`: SMA tohumlu EMA'lar, sinyal = MACD çizgisinin geçerli kısmında EMA."""
    ef, es = ema_seeded(c, fast), ema_seeded(c, slow)
    line = ef - es
    signal = ema_seeded(line, sig)
    return line, signal, line - signal


def adx_series(h, l, c, p: int = 14):
    """Kanonik `_adx`: Wilder yumuşatmalı +DI/−DI, DX, ADX (ADX = DX'in Wilder ortalaması). (adx, +di, −di)."""
    n = len(c)
    nan = np.full(n, np.nan)
    if n < 2 * p + 1:
        return nan.copy(), nan.copy(), nan.copy()
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    up = h[1:] - h[:-1]; dn = l[:-1] - l[1:]
    plus = np.where((up > dn) & (up > 0), up, 0.0); minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    trw, pw, mw = wilder_smooth(tr, p), wilder_smooth(plus, p), wilder_smooth(minus, p)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(trw > 0, 100 * pw / trw, 0.0); mdi = np.where(trw > 0, 100 * mw / trw, 0.0)
        s = pdi + mdi
        dx = np.where(s > 0, 100 * np.abs(pdi - mdi) / s, 0.0)
    dx = np.where(np.isfinite(trw), dx, np.nan)
    adx = wilder_smooth(dx, p)
    pdi = np.where(np.isfinite(trw), pdi, np.nan); mdi = np.where(np.isfinite(trw), mdi, np.nan)
    a, pd_, md_ = nan.copy(), nan.copy(), nan.copy()
    a[1:], pd_[1:], md_[1:] = adx, pdi, mdi
    return a, pd_, md_


def aroon_series(h: np.ndarray, l: np.ndarray, p: int = 25):
    """Kanonik `_aroon`: son p+1 bar, eşitlikte SON oluşum. (up, down)."""
    n = len(h)
    up = np.full(n, np.nan); dn = np.full(n, np.nan)
    if n < p + 1:
        return up, dn
    hw = np.lib.stride_tricks.sliding_window_view(h, p + 1)[:, ::-1]
    lw = np.lib.stride_tricks.sliding_window_view(l, p + 1)[:, ::-1]
    up[p:] = 100.0 * (p - hw.argmax(axis=1)) / p
    dn[p:] = 100.0 * (p - lw.argmin(axis=1)) / p
    return up, dn


def linreg_slope_pct(c: np.ndarray, p: int = 10) -> np.ndarray:
    """Kanonik `_linreg_slope_pct`: p barlık doğrusal regresyon eğimi, ortalamaya göre % / bar."""
    n = len(c)
    out = np.full(n, np.nan)
    if n < p:
        return out
    xc = np.arange(p, dtype=float) - (p - 1) / 2.0
    sxx = float((xc ** 2).sum())
    win = np.lib.stride_tricks.sliding_window_view(c, p)
    slope = win @ xc / sxx
    m = win.mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[p - 1:] = np.where(m != 0, slope / m * 100.0, np.nan)
    return out


def _rolling_ext(x: np.ndarray, w: int, fn) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan)
    if n >= w:
        out[w - 1:] = fn(np.lib.stride_tricks.sliding_window_view(x, w), axis=1)
    return out


def _pct(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, (a / b - 1.0) * 100.0, np.nan)


# ----------------------------------------------------------------------------------------------- özellik matrisi
def features_matrix(arr: np.ndarray, tf: str) -> tuple[list[str], np.ndarray]:
    """Bir zaman dilimi için özellik matrisi (n × F). Sütun adları `<tf>.<ad>`. i. satır yalnız ≤ i barlarına bağlıdır.

    `tf`: "1m" | "3m" | "5m" — yalnız 24 sa pencere uzunluğunu (bar sayısı) belirler.
    """
    o, h, l, c = arr[:, COL_O], arr[:, COL_H], arr[:, COL_L], arr[:, COL_C]
    v = np.nan_to_num(arr[:, COL_V], nan=0.0); qv = np.nan_to_num(arr[:, COL_QV], nan=0.0)
    n = len(c)
    bpd = TF_BARS_PER_DAY[tf]
    F: dict[str, np.ndarray] = {}
    e7, e20, e50, e99 = (ema_seeded(c, p) for p in (7, 20, 50, 99))
    F["px_ema7"], F["px_ema20"] = _pct(c, e7), _pct(c, e20)
    F["px_ema50"], F["px_ema99"] = _pct(c, e50), _pct(c, e99)
    F["ema7_20"], F["ema20_50"], F["ema50_99"] = _pct(e7, e20), _pct(e20, e50), _pct(e50, e99)
    F["ema7_slope3"] = _pct(e7, shift(e7, 3)); F["ema20_slope3"] = _pct(e20, shift(e20, 3))
    F["ema50_slope10"] = _pct(e50, shift(e50, 10)); F["ema99_slope10"] = _pct(e99, shift(e99, 10))
    with np.errstate(invalid="ignore"):
        fan = (e7 > e20).astype(float) + (e20 > e50) + (e50 > e99) + (c > e7)
    F["fan_score"] = np.where(np.isfinite(e99), fan, np.nan)
    F["rsi14"] = rsi_series(c, 14)
    F["mfi14"] = mfi_series(h, l, c, v, 14)
    atr = atr_series(h, l, c, 14)
    F["atr14_pct"] = np.where(c > 0, atr / c * 100.0, np.nan)
    bw, pb = bollinger_series(c, 20)
    F["bb_width_pct"], F["bb_pctb"] = bw * 100.0, pb
    _, _, mh = macd_series(c)
    F["macd_hist_pct"] = np.where(c > 0, mh / c * 100.0, np.nan)
    F["macd_hist_slope"] = np.where(c > 0, (mh - shift(mh, 1)) / c * 100.0, np.nan)
    adx, pdi, mdi = adx_series(h, l, c, 14)
    F["adx14"], F["plus_di14"], F["minus_di14"] = adx, pdi, mdi
    au, ad = aroon_series(h, l, 25)
    F["aroon_up25"], F["aroon_down25"] = au, ad
    F["linreg10_pct"], F["linreg20_pct"] = linreg_slope_pct(c, 10), linreg_slope_pct(c, 20)
    for k in (1, 3, 5, 10, 20):
        F[f"ret{k}"] = _pct(c, shift(c, k))
    # hacim oranı: bar / önceki 20 bar ort.; son 3 bar ort. / ondan önceki 20 bar ort.
    s20 = rolling_sum(v, 20)
    prev20 = shift(s20, 1) / 20.0
    with np.errstate(divide="ignore", invalid="ignore"):
        F["vol_ratio"] = np.where(prev20 > 0, v / prev20, np.nan)
        m3 = rolling_sum(v, 3) / 3.0
        p20_3 = shift(s20, 3) / 20.0
        F["vol_ratio3"] = np.where(p20_3 > 0, m3 / p20_3, np.nan)
    q24 = rolling_sum(qv, bpd)
    with np.errstate(divide="ignore", invalid="ignore"):
        F["qv24_log10"] = np.where(q24 > 0, np.log10(q24), np.nan)
    hi24, lo24 = _rolling_ext(h, bpd, np.max), _rolling_ext(l, bpd, np.min)
    F["dist_high24_pct"], F["dist_low24_pct"] = _pct(c, hi24), _pct(c, lo24)
    with np.errstate(divide="ignore", invalid="ignore"):
        F["range_pos24"] = np.where(hi24 > lo24, (c - lo24) / (hi24 - lo24), np.nan)
    F["green_run"] = run_length(c > o).astype(float)
    hl = np.zeros(n, dtype=bool); hl[1:] = l[1:] > l[:-1]
    F["hl_run"] = run_length(hl).astype(float)
    gr = (c > o).astype(float)
    F["green_share12"] = rolling_sum(gr, 12) / 12.0
    step = np.full(n, np.nan); step[1:] = (c[1:] / np.where(c[:-1] > 0, c[:-1], np.nan) - 1.0) * 100.0
    F["max_candle12"] = _rolling_ext(np.nan_to_num(step, nan=0.0), 12, np.max)
    # 12 bar içi, çalışan zirveden maksimum geri çekilme (kapanış bazlı, %)
    if n >= 12:
        win = np.lib.stride_tricks.sliding_window_view(c, 12)
        rh = np.maximum.accumulate(win, axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            dd = np.max((rh - win) / np.where(rh > 0, rh, np.nan), axis=1) * 100.0
        F["drawdown12_pct"] = np.concatenate([np.full(11, np.nan), dd])
    else:
        F["drawdown12_pct"] = np.full(n, np.nan)
    if tf == "5m":
        F["hour"] = (((arr[:, COL_OT] // 1000 + TZ_OFFSET_H * 3600) // 3600) % 24).astype(float)
    names = [f"{tf}.{k}" for k in F]
    X = np.column_stack([F[k] for k in F]) if F else np.zeros((n, 0))
    return names, X


# ----------------------------------------------------------------------------------------------- olay tanımı
@dataclass
class EventParams:
    """"LUNA tipi" merdiven yükseliş olayı. Tüm eşikler % (gain, dd, candle) ya da oran."""
    win_bars: int = 12            # pencere: 12 × 5 dk = 60 dk
    min_gain: float = 4.0         # başlangıç referansından pencere zirve kapanışına en az % yükseliş
    green_min: float = 0.70       # koşudaki mumlardan yeşil (kapanış > açılış) payı
    max_dd: float = 1.5           # çalışan zirveden maksimum geri çekilme (%)
    max_candle: float = 2.5       # tek mumun (kapanıştan kapanışa) azami kazancı (%)
    min_q24: float = 5_000_000.0  # 24 sa quote hacmi (TRY)
    min_len: int = 3              # koşu en az bu kadar mum
    dedupe_hours: float = 3.0     # sembol başına olaylar arası en az
    dd_mode: str = "close"        # "close": kapanıştan kapanışa; "hl": çalışan zirve = high, dip = low
    require_start_low: bool = True  # koşudaki hiçbir kapanış başlangıç referansının altına inmesin


def event_mask(arr: np.ndarray, p: EventParams, *, warm_bars: int = 288) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Her olası başlangıç mumu s için (s. mum koşunun İLK mumu; referans P0 = c[s-1]) olay koşulu.

    Koşu s..s+e (e = 0..win_bars-1). Bir (s, e) çifti GEÇERLİ ise: kapanış kazancı ≥ min_gain, gerçek (hacimli) mumların
    yeşil payı ≥ green_min, çalışan zirveden geri çekilme ≤ max_dd, tek mum kazancı ≤ max_candle, koşu boyunca kapanış
    ≥ P0 ve en az min_len gerçek mum. s için olay = bir e'nin geçerli olması; raporlanan e = geçerli koşular içinde en yüksek kapanışlı
    (tırmanışın sonundaki tek mumluk patlama koşuyu bozmasın diye; eşit zirvede en kısa). `fill_gaps` ile doldurulmuş (hacimsiz) mumlar
    yeşil/kırmızı sayılmaz. Ek: ilk mum yeşil ve P0'ın üstünde (koşu yerel dipten sonraki ilk yükseliş mumuyla başlar),
    24 sa quote ≥ min_q24, pencerede zaman boşluğu yok.

    Dönüş: (mask[n], ayrıntılar: gain, e_star, green, dd, maxc — seçilen e için; geçersiz yerde NaN).
    Son `win_bars-1` mum için tam pencere yoktur → False."""
    n = len(arr)
    W = p.win_bars
    mask = np.zeros(n, dtype=bool)
    det = {k: np.full(n, np.nan) for k in ("gain", "e_star", "green", "dd", "maxc")}
    if n < W + 2:
        return mask, det
    ot, o, h, l, c = (arr[:, k] for k in (COL_OT, COL_O, COL_H, COL_L, COL_C))
    v = np.nan_to_num(arr[:, COL_V], nan=0.0)
    qv = np.nan_to_num(arr[:, COL_QV], nan=0.0)
    q24 = rolling_sum(qv, 288)
    m = n - W  # s = 1 .. n-W
    sw = np.lib.stride_tricks.sliding_window_view
    Wc = sw(c, W)[1:1 + m]; Wo = sw(o, W)[1:1 + m]; Wh = sw(h, W)[1:1 + m]; Wl = sw(l, W)[1:1 + m]
    Wv = sw(v, W)[1:1 + m]
    P0 = c[:m]
    rows = np.arange(m)
    ecols = np.arange(W)[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        gain = (Wc / P0[:, None] - 1.0) * 100.0
        prev = np.concatenate([P0[:, None], Wc[:, :-1]], axis=1)
        step = (Wc / prev - 1.0) * 100.0
        maxc = np.maximum.accumulate(step, axis=1)
        if p.dd_mode == "hl":
            rh = np.maximum.accumulate(np.concatenate([P0[:, None], Wh], axis=1), axis=1)[:, 1:]
            dd_all = (rh - Wl) / rh * 100.0
        else:
            rh = np.maximum.accumulate(np.concatenate([P0[:, None], Wc], axis=1), axis=1)[:, 1:]
            dd_all = (rh - Wc) / rh * 100.0
        dd = np.maximum.accumulate(dd_all, axis=1)
        real = Wv > 0
        n_real = np.cumsum(real, axis=1)
        n_green = np.cumsum(real & (Wc > Wo), axis=1)
        green = n_green / np.maximum(n_real, 1)
        if p.require_start_low:
            lowok = np.minimum.accumulate(Wc, axis=1) >= P0[:, None]
        else:
            lowok = np.ones_like(Wc, dtype=bool)
        valid = ((gain >= p.min_gain) & (green >= p.green_min) & (dd <= p.max_dd) & (maxc <= p.max_candle)
                 & lowok & (ecols + 1 >= p.min_len) & (n_real >= p.min_len))
    any_valid = valid.any(axis=1)
    e_sel = np.where(valid, gain, -np.inf).argmax(axis=1)   # geçerli koşular içinde zirve kapanış (eşitte en erken)
    first_up = (Wc[:, 0] > Wo[:, 0]) & (Wc[:, 0] > P0) & real[:, 0]
    contig = (ot[W:W + m] - ot[:m]) == (W * BAR_5M_MS)  # ot[s+W-1] - ot[s-1] == W bar
    ok = any_valid & first_up & contig & (q24[:m] >= p.min_q24) & (rows + 1 >= warm_bars)
    mask[1:1 + m] = ok
    det["gain"][1:1 + m] = np.where(ok, gain[rows, e_sel], np.nan)
    det["e_star"][1:1 + m] = np.where(ok, e_sel, np.nan)
    det["green"][1:1 + m] = np.where(ok, green[rows, e_sel], np.nan)
    det["dd"][1:1 + m] = np.where(ok, dd[rows, e_sel], np.nan)
    det["maxc"][1:1 + m] = np.where(ok, maxc[rows, e_sel], np.nan)
    return mask, det


def find_events(sym: str, arr: np.ndarray, p: EventParams, *, t_min_ms: int | None = None,
                t_max_ms: int | None = None, warm_bars: int = 288) -> list[dict]:
    """Olaylar: sembol başına `dedupe_hours` aralıklı, EN ERKEN geçerli başlangıç. t0 = koşunun ilk mumunun
    open_time'ı (= o ana dek kapanmış mumlardan gözlenen durum). t_min/t_max t0 üzerinde süzgeçtir."""
    mask, det = event_mask(arr, p, warm_bars=warm_bars)
    idx = np.flatnonzero(mask)
    out: list[dict] = []
    last_t = -10 ** 18
    gap = int(p.dedupe_hours * 3_600_000)
    for s in idx:
        t0 = int(arr[s, COL_OT])
        if t_min_ms is not None and t0 < t_min_ms:
            continue
        if t_max_ms is not None and t0 > t_max_ms:
            continue
        if t0 - last_t < gap:
            continue
        last_t = t0
        e = int(det["e_star"][s])
        out.append({"sym": sym, "s": int(s), "t0": t0, "gain": float(det["gain"][s]), "dur_min": (e + 1) * 5,
                    "green": float(det["green"][s]), "dd": float(det["dd"][s]), "maxc": float(det["maxc"][s]),
                    "t_end": t0 + (e + 1) * BAR_5M_MS, "p0": float(arr[s - 1, COL_C])})
    return out


# ----------------------------------------------------------------------------------------------- istatistikler
def snapshot_index(ot: np.ndarray, bar_ms: int, t_ms: int | np.ndarray, max_stale_bars: int = 3):
    """`t_ms` anında KAPANMIŞ son barın indeksi (open + bar ≤ t). Bayat ise (son kapanıştan > max_stale_bars bar) -1."""
    idx = np.searchsorted(ot + bar_ms, t_ms, side="right") - 1
    idx = np.asarray(idx)
    safe = np.clip(idx, 0, max(len(ot) - 1, 0))
    if len(ot) == 0:
        return np.full(np.shape(idx), -1)
    stale = (np.asarray(t_ms) - (ot[safe] + bar_ms)) > max_stale_bars * bar_ms
    return np.where((idx < 0) | stale, -1, idx)


def _rank_cols(X: np.ndarray) -> np.ndarray:
    from scipy.stats import rankdata
    return np.column_stack([rankdata(X[:, j], method="average") for j in range(X.shape[1])])


def auc_matrix(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Her sütun için AUC = P(olay > taban) + ½P(eşit). X'te NaN olmamalı (tam vakalar)."""
    n1 = int(y.sum()); n0 = len(y) - n1
    R = _rank_cols(X)
    return (R[y.astype(bool)].sum(axis=0) - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def smd(X: np.ndarray, y: np.ndarray, winsor: float = 0.01) -> np.ndarray:
    """Standartlaştırılmış ortalama farkı (olay − taban) / havuz std; uç %1 winsorize."""
    lo, hi = np.quantile(X, winsor, axis=0), np.quantile(X, 1 - winsor, axis=0)
    Xw = np.clip(X, lo, hi)
    yb = y.astype(bool)
    a, b = Xw[yb], Xw[~yb]
    n1, n0 = len(a), len(b)
    sp = np.sqrt(((n1 - 1) * a.var(axis=0, ddof=1) + (n0 - 1) * b.var(axis=0, ddof=1)) / max(n1 + n0 - 2, 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sp > 0, (a.mean(axis=0) - b.mean(axis=0)) / sp, 0.0)


def iqr(X: np.ndarray) -> np.ndarray:
    q = np.quantile(X, [0.25, 0.75], axis=0)
    return q[1] - q[0]


def fwer_threshold(X: np.ndarray, y: np.ndarray, strata: np.ndarray, *, n_perm: int = 500, alpha: float = 0.05,
                   seed: int = 0) -> tuple[float, np.ndarray]:
    """Tabakalı (sembol içi) etiket permütasyonuyla max_j |AUC_j − ½| sıfır dağılımı; (alpha üst kuantili, tüm değerler).
    Çoklu karşılaştırma için: gözlenen |AUC−½| bu eşiğin üstündeyse aile-bazlı p<alpha."""
    rng = np.random.default_rng(seed)
    n1 = int(y.sum()); n0 = len(y) - n1
    R = _rank_cols(X)
    groups = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    mx = np.empty(n_perm)
    for b in range(n_perm):
        yp = np.zeros(len(y))
        for g in groups:
            k = int(y[g].sum())
            if k:
                yp[rng.choice(g, size=k, replace=False)] = 1.0
        auc = (yp @ R - n1 * (n1 + 1) / 2.0) / (n1 * n0)
        mx[b] = np.abs(auc - 0.5).max()
    return float(np.quantile(mx, 1 - alpha)), mx


# ----------------------------------------------------------------------------------------------- desenler
@dataclass(frozen=True)
class Condition:
    feature: str   # "5m.rsi14"
    op: str        # "<=" | ">"
    value: float

    def text(self) -> str:
        return f"{self.feature} {self.op} {self.value:.4g}"


def eval_conditions(cols: dict[str, np.ndarray], conds: list[Condition]) -> np.ndarray:
    """AND bileşimi; NaN → False."""
    if not conds:
        raise ValueError("boş desen")
    n = len(next(iter(cols.values())))
    m = np.ones(n, dtype=bool)
    for cd in conds:
        x = cols[cd.feature]
        with np.errstate(invalid="ignore"):
            m &= (x <= cd.value) if cd.op == "<=" else (x > cd.value)
    return m


def merge_conditions(conds: list[Condition]) -> list[Condition]:
    """Aynı özellik+yön tekrarlarını en sıkı eşiğe indirger (ağaç yollarında olur)."""
    best: dict[tuple[str, str], float] = {}
    for c in conds:
        k = (c.feature, c.op)
        if k not in best:
            best[k] = c.value
        else:
            best[k] = min(best[k], c.value) if c.op == "<=" else max(best[k], c.value)
    return [Condition(f, op, v) for (f, op), v in best.items()]


@dataclass
class TreePattern:
    conditions: list[Condition]
    leaf_recall: float
    leaf_fpr: float
    depth: int
    features_used: list[str] = field(default_factory=list)


def fit_pattern_tree(X: np.ndarray, y: np.ndarray, names: list[str], *, depth: int, min_leaf_events: int,
                     min_recall: float = 0.10, seed: int = 0, max_fpr: float | None = None,
                     pos_share: float = 0.5) -> TreePattern | None:
    """Sığ karar ağacı (sınıf ağırlıklı) → olay/taban oranı (dengeli) en yüksek yaprağın yolu = AND deseni.
    `min_leaf_events`: yaprakta en az bu kadar olay; `min_recall`: yaprak olay payı en az bu kadar.
    `max_fpr` verilirse: yaprağın taban payı ≤ max_fpr olmalı ve EN YÜKSEK olay payına (recall) sahip yaprak seçilir
    (seçicilik kısıtlı desen). `pos_share`: olay sınıfının toplam ağırlık payı (0.5 = dengeli; küçük değer ağacı
    yanlış alarmdan kaçınmaya iter)."""
    from sklearn.tree import DecisionTreeClassifier
    yb = y.astype(bool)
    n1 = int(yb.sum()); n0 = len(yb) - n1
    if n1 < 4 or n0 < 4:
        return None
    w = np.where(yb, pos_share / n1, (1.0 - pos_share) / n0)
    # min_samples_leaf'i olay sayısıyla ayarlamak yerine ağırlıklı kriter kullanıyoruz: yaprak olay sayısı sonradan süzülür.
    tr = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=max(3, min_leaf_events // 2), random_state=seed)
    tr.fit(X, yb.astype(int), sample_weight=w)
    t = tr.tree_
    leaves_of = tr.apply(X)
    best = None
    for leaf in np.unique(leaves_of):
        inl = leaves_of == leaf
        e = int((inl & yb).sum()); b = int((inl & ~yb).sum())
        rec, fpr = e / n1, b / n0
        if e < min_leaf_events or rec < min_recall:
            continue
        if max_fpr is not None:
            if fpr > max_fpr:
                continue
            score = rec
        else:
            score = rec / (rec + fpr + 1e-12)   # dengeli-önsel kesinlik
        if best is None or score > best[0]:
            best = (score, leaf, rec, fpr)
    if best is None:
        return None
    _, leaf, rec, fpr = best
    path: list[Condition] = []
    parent = {}
    for nid in range(t.node_count):
        for ch, op in ((t.children_left[nid], "<="), (t.children_right[nid], ">")):
            if ch != -1:
                parent[int(ch)] = (nid, op)
    nid = int(leaf)
    while nid in parent:
        pn, op = parent[nid]
        path.append(Condition(names[int(t.feature[pn])], op, float(t.threshold[pn])))
        nid = pn
    path.reverse()
    conds = merge_conditions(path)
    return TreePattern(conds, rec, fpr, depth, sorted({c.feature for c in conds}))
