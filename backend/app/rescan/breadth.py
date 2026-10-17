"""Piyasa genişliği, göreli güç, SMT ıraksaması ve zaman (seans) özellikleri — SAF, NEDENSEL (2026-10-17, çevrimdışı araştırma).

Canlı koda BAĞLANMAZ, DB'ye dokunmaz. Girdiler zaman ekseni SON eksen olan diziler:
  * panel: (S, T) — S sembol, T adet 5 dk karar barı. Bar k'nın OPEN zamanı `t0 + k·300 000` ms, KAPANIŞ (karar) zamanı `t0 + (k+1)·300 000`.
  * seri : (T,)
`V` (S, T) bool = "geçerli evren" (var olan ∧ 24 sa quote ≥ eşik); geçersiz hücreler genişlik sayımlarına girmez.

NEDENSELLİK SÖZLEŞMESİ: her çıktının [..., t] elemanı yalnız girdilerin [..., :t+1] kısmına bağlıdır (tests/test_breadth.py kesme testi:
dizi t'de kesilip yeniden hesaplanınca [:t+1] aynı çıkar). Fraktal salınımlar k bar GECİKMEYLE onaylanır (t'de onaylanan salınım t−k'dadır).
Gün sınırı olan özellikler (açılış aralığı, önceki gün) yalnız TAMAMLANMIŞ günleri / tamamlanmış açılış aralığını kullanır.

Zaman: TR = UTC+3 (sabit; Türkiye'de yaz saati yok). Killzone (TR saati, karar anı t_dec için [başlangıç, bitiş)):
  Asya 03:00–07:00, Londra 10:00–13:00, New York 15:30–18:00 (ICT seansları TR saatine yaklaşık dönüşüm; kesin sınırlar tartışmalı).
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import lfilter
from scipy.stats import rankdata

BAR_MS = 300_000
BARS_PER_DAY = 288
TZ_OFFSET_MS = 3 * 3_600_000
KILLZONES = {"asya": (3 * 60, 7 * 60), "londra": (10 * 60, 13 * 60), "ny": (15 * 60 + 30, 18 * 60)}   # TR dakika-gün


# ------------------------------------------------------------------------------------------------ temel yardımcılar
def shift(x: np.ndarray, k: int) -> np.ndarray:
    """Son eksende k bar GERİ kaydır (out[t] = x[t−k]); baş NaN."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if k <= 0:
        return x.copy() if k == 0 else out
    if k < x.shape[-1]:
        out[..., k:] = x[..., :-k]
    return out


def _ffill_1d(y: np.ndarray) -> np.ndarray:
    idx = np.where(np.isfinite(y), np.arange(len(y)), 0)
    np.maximum.accumulate(idx, out=idx)
    return y[idx]


def ema(x: np.ndarray, span: int) -> np.ndarray:
    """Nedensel EMA (alpha = 2/(span+1)), ilk `span` sonlu değerin ortalamasıyla (SMA) tohumlu; öncesi NaN, ortadaki NaN'da son değer taşınır.
    (T,) ya da (S, T)."""
    x = np.asarray(x, dtype=float)
    if x.ndim == 2:
        return np.vstack([ema(r, span) for r in x]) if len(x) else x.copy()
    out = np.full(len(x), np.nan)
    fin = np.flatnonzero(np.isfinite(x))
    if len(fin) == 0:
        return out
    f = int(fin[0])
    y = _ffill_1d(x[f:])
    if len(y) < span:
        return out
    a = 2.0 / (span + 1.0)
    seed = float(y[:span].mean())
    out[f + span - 1] = seed
    if len(y) > span:
        z, _ = lfilter([a], [1.0, -(1.0 - a)], y[span:], zi=[(1.0 - a) * seed])
        out[f + span:] = z
    return out


def rolling_sum(x: np.ndarray, n: int) -> np.ndarray:
    """Son n barın toplamı (t dâhil); NaN → 0 sayılır, ilk n−1 bar NaN."""
    x = np.nan_to_num(np.asarray(x, dtype=float), nan=0.0)
    cs = np.cumsum(x, axis=-1)
    out = np.full(x.shape, np.nan)
    if x.shape[-1] >= n:
        prev = np.zeros_like(cs)
        prev[..., n:] = cs[..., :-n]
        out[..., n - 1:] = (cs - prev)[..., n - 1:]
    return out


def rolling_ext(x: np.ndarray, w: int, fn=np.max) -> np.ndarray:
    """Son w barın (t dâhil) max/min'i; pencerede NaN varsa NaN (yetersiz/geçersiz veri)."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if x.shape[-1] < w:
        return out
    out[..., w - 1:] = fn(sliding_window_view(x, w, axis=-1), axis=-1)
    return out


def lag_return(C: np.ndarray, lag: int) -> np.ndarray:
    """lag-bar getiri (%) : C[t]/C[t−lag] − 1."""
    return (np.asarray(C, dtype=float) / shift(C, lag) - 1.0) * 100.0


def xs_rank_pct(X: np.ndarray) -> np.ndarray:
    """Her sütunda (zaman) kesitsel yüzdelik sıra [0,1] (eşitlikte ortalama sıra); NaN'lar hariç. Tek geçerli sembol → 0,5."""
    X = np.asarray(X, dtype=float)
    r = rankdata(X, axis=0, method="average", nan_policy="omit").astype(float)
    n = np.isfinite(X).sum(axis=0)
    out = np.where(np.isfinite(X), (r - 1.0) / np.maximum(n - 1.0, 1.0), np.nan)
    out[:, n < 2] = np.where(np.isfinite(X[:, n < 2]), 0.5, np.nan)
    return out


# ------------------------------------------------------------------------------------------------ genişlik (piyasa düzeyi, (T,))
def valid_universe(QV: np.ndarray, min_quote24: float, bars_24h: int = 288) -> np.ndarray:
    """V[s,t]: son 24 sa (288 bar, t dâhil) quote hacmi ≥ eşik. 24 sa dolmadan (ilk 287 bar / listeleme öncesi) geçersiz."""
    q = rolling_sum(np.where(np.isnan(QV), 0.0, QV), bars_24h)
    exists = np.cumsum(np.isfinite(QV), axis=-1) >= bars_24h
    return np.isfinite(q) & (q >= min_quote24) & exists


def pct_above(C: np.ndarray, E: np.ndarray, V: np.ndarray, min_n: int = 10) -> np.ndarray:
    """Geçerli semboller arasında kapanış > EMA payı (T,); geçerli sayı < min_n → NaN."""
    ok = V & np.isfinite(C) & np.isfinite(E)
    n = ok.sum(axis=0)
    a = ((C > E) & ok).sum(axis=0)
    return np.where(n >= min_n, a / np.maximum(n, 1), np.nan)


def adv_dec(C: np.ndarray, V: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """lag-bar yükselen / düşen / geçerli sayısı (T,) (düz = ne biri ne öbürü)."""
    Cp = shift(C, lag)
    ok = V & np.isfinite(C) & np.isfinite(Cp)
    adv = ((C > Cp) & ok).sum(axis=0).astype(float)
    dec = ((C < Cp) & ok).sum(axis=0).astype(float)
    return adv, dec, ok.sum(axis=0).astype(float)


def ad_ratio(adv: np.ndarray, dec: np.ndarray, min_n: float = 10) -> np.ndarray:
    n = adv + dec
    return np.where(n >= min_n, adv / np.maximum(n, 1), np.nan)


def ad_line_slope(adv1: np.ndarray, dec1: np.ndarray, nvalid: np.ndarray, n: int) -> np.ndarray:
    """A/D çizgisi (1-bar net ilerleyenlerin kümülatifi) eğimi: (AD[t]−AD[t−n])/n / geçerli sayısı = son n barın ortalama net-ilerleyen payı."""
    ad = np.cumsum(np.nan_to_num(adv1 - dec1))
    return (ad - shift(ad, n)) / n / np.maximum(nvalid, 1.0)


def mcclellan(adv1: np.ndarray, dec1: np.ndarray, fast: int = 19, slow: int = 39) -> np.ndarray:
    """McClellan osilatörü: oran-ayarlı net ilerleyenlerin (adv−dec)/(adv+dec)·1000 EMA(fast) − EMA(slow)."""
    n = adv1 + dec1
    rana = np.where(n > 0, 1000.0 * (adv1 - dec1) / np.maximum(n, 1.0), 0.0)
    return ema(rana, fast) - ema(rana, slow)


def net_highs_lows(C: np.ndarray, H: np.ndarray, L: np.ndarray, V: np.ndarray, window: int = 288, min_n: int = 10) -> np.ndarray:
    """(yeni 24 sa tepe sayısı − yeni 24 sa dip sayısı)/geçerli sayısı. Yeni tepe: H[t] > önceki `window` barın en yükseği (t hariç)."""
    pmax = shift(rolling_ext(H, window, np.max), 1)
    pmin = shift(rolling_ext(L, window, np.min), 1)
    ok = V & np.isfinite(pmax) & np.isfinite(pmin)
    nh = ((H > pmax) & ok).sum(axis=0)
    nl = ((L < pmin) & ok).sum(axis=0)
    n = ok.sum(axis=0)
    return np.where(n >= min_n, (nh - nl) / np.maximum(n, 1), np.nan)


def breadth_thrust(ratio: np.ndarray, span: int = 10, lo: float = 0.40, hi: float = 0.615, within: int = 12) -> tuple[np.ndarray, np.ndarray]:
    """Zweig-benzeri genişlik itişi. s = EMA(span) of adv/(adv+dec). İtiş = s ≤ lo görüldükten SONRA en çok `within` bar içinde s > hi.
    Dönüş: (s, thrust) — thrust 1.0 durum bayrağı (s > hi ∧ son `within` barda s ≤ lo görüldü), aksi 0.0 (s NaN → NaN)."""
    s = ema(np.where(np.isfinite(ratio), ratio, np.nan), span)
    low = np.where(np.isfinite(s) & (s <= lo), np.arange(len(s)), -10 ** 9)
    last_low = np.maximum.accumulate(low)
    age = np.arange(len(s)) - last_low
    thrust = np.where(np.isfinite(s), ((s > hi) & (age <= within)).astype(float), np.nan)
    return s, thrust


def pct_taker_buy(TBQ: np.ndarray, QV: np.ndarray, V: np.ndarray, thr: float = 0.55, smooth: int = 3, min_n: int = 10) -> np.ndarray:
    """Son `smooth` barda taker-alış payı (Σtaker_buy_quote/Σquote) > thr olan geçerli sembol payı (T,)."""
    QVm = np.where(np.isfinite(TBQ), QV, 0.0)           # taker verisi eksik bar paydadan da düşer
    num, den = rolling_sum(TBQ, smooth), rolling_sum(QVm, smooth)
    ok = V & np.isfinite(num) & np.isfinite(den) & (den > 0)
    sh = np.where(ok, num / np.where(den > 0, den, 1.0), np.nan)
    n = ok.sum(axis=0)
    return np.where(n >= min_n, ((sh > thr) & ok).sum(axis=0) / np.maximum(n, 1), np.nan)


def xs_mean_std(R: np.ndarray, V: np.ndarray, clip: float = 20.0, min_n: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Getiri paneli R (%) için kesitsel ortalama (EW piyasa getirisi; ±clip % kırpılmış) ve standart sapma (dağılım). (T,) × 2."""
    ok = V & np.isfinite(R)
    Rc = np.where(ok, np.clip(R, -clip, clip), 0.0)
    n = ok.sum(axis=0)
    mu = Rc.sum(axis=0) / np.maximum(n, 1)
    var = (np.where(ok, (Rc - mu) ** 2, 0.0)).sum(axis=0) / np.maximum(n, 1)
    return np.where(n >= min_n, mu, np.nan), np.where(n >= min_n, np.sqrt(var), np.nan)


def ew_index(C: np.ndarray, V: np.ndarray, min_n: int = 10) -> np.ndarray:
    """Eşit ağırlıklı piyasa endeksi (seviye, 100'den başlar): 1-bar kırpılmış ortalama log-getirilerin kümülatifi."""
    r1 = np.log(np.asarray(C, dtype=float) / shift(C, 1)) * 100.0
    mu, _ = xs_mean_std(r1, V, min_n=min_n)
    return 100.0 * np.exp(np.cumsum(np.nan_to_num(mu)) / 100.0)


# ------------------------------------------------------------------------------------------------ göreli güç, beta, USDTTRY
def rolling_beta_corr(r: np.ndarray, rb: np.ndarray, w: int, min_frac: float = 0.8) -> tuple[np.ndarray, np.ndarray]:
    """Sembol 1-bar getirileri r (S,T) ile referans rb (T,) arasında son w barda beta ve korelasyon. Eksik (NaN) bar sayısı > (1−min_frac)·w → NaN."""
    r = np.asarray(r, dtype=float)
    rb = np.asarray(rb, dtype=float)
    ok = np.isfinite(r) & np.isfinite(rb)[None, :]
    x = np.where(ok, r, 0.0)
    y = np.where(ok, rb[None, :], 0.0)

    def rs(a):
        return rolling_sum(a, w)

    n, sx, sy = rs(ok.astype(float)), rs(x), rs(y)
    sxy, sxx, syy = rs(x * y), rs(x * x), rs(y * y)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy / n - (sx / n) * (sy / n)
        vx = sxx / n - (sx / n) ** 2
        vy = syy / n - (sy / n) ** 2
        beta = cov / vy
        corr = cov / np.sqrt(vx * vy)
    bad = (n < min_frac * w) | ~(vy > 1e-18) | ~(vx > 1e-18)
    return np.where(bad, np.nan, beta), np.where(bad, np.nan, np.clip(corr, -1.0, 1.0))


# ------------------------------------------------------------------------------------------------ fraktal salınımlar + SMT
def fractal_swings(h: np.ndarray, l: np.ndarray, k: int = 3) -> dict[str, np.ndarray]:
    """(T,) h/l için nedensel fraktal salınımlar. Salınım tepesi i: h[i] > önceki k barın en yükseği ∧ h[i] ≥ sonraki k barın en yükseği;
    t = i+k'da ONAYLANIR (t'ye kadar veri). Dönüş (hepsi (T,), ileri doldurulmuş): sh (son tepe), sh_prev (bir önceki), sh_age (son tepenin bar yaşı = t−i);
    sl, sl_prev, sl_age dipler için."""
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    T = len(h)
    out = {}
    for nm, x, fn, cmp_left, cmp_right in (("sh", h, np.max, np.greater, np.greater_equal), ("sl", l, np.min, np.less, np.less_equal)):
        rk = rolling_ext(x, k, fn)                       # rk[t] = fn(x[t−k+1..t])
        idx = np.arange(T)
        i = idx - k
        conf = np.zeros(T, dtype=bool)
        valid = i - 1 >= k - 1                           # sol pencere rk[i−1] tanımlı
        ii = i[valid]
        with np.errstate(invalid="ignore"):
            conf[valid] = cmp_left(x[ii], rk[ii - 1]) & cmp_right(x[ii], rk[idx[valid]])
        ci = np.flatnonzero(conf)
        vals = x[ci - k]
        pos = np.searchsorted(ci, idx, side="right") - 1
        last = np.where(pos >= 0, vals[np.clip(pos, 0, max(len(vals) - 1, 0))] if len(vals) else np.nan, np.nan)
        prev = np.where(pos >= 1, vals[np.clip(pos - 1, 0, max(len(vals) - 1, 0))] if len(vals) else np.nan, np.nan)
        age = np.where(pos >= 0, idx - (ci[np.clip(pos, 0, max(len(ci) - 1, 0))] - k) if len(ci) else np.nan, np.nan)
        out[nm], out[nm + "_prev"], out[nm + "_age"] = last, prev, age.astype(float)
    return out


def smt_flags(sym: dict[str, np.ndarray], ref: dict[str, np.ndarray], max_age: int = 36) -> tuple[np.ndarray, np.ndarray]:
    """SMT ıraksaması (sembol ↔ referans: BTC ya da EW endeks). Her iki tarafın son iki ONAYLI salınımı da `max_age` bar içinde olmalı.
    smt_low : +1 sembol YÜKSEK dip (HL) ∧ ref ALÇAK dip (LL) [boğa SMT]; −1 sembol LL ∧ ref HL [sembol göreli zayıf]; 0 diğer.
    smt_high: +1 sembol YÜKSEK tepe (HH) ∧ ref ALÇAK tepe (LH) [sembol göreli güçlü]; −1 sembol LH ∧ ref HH [ayı SMT]; 0 diğer."""
    def pair(a, b, key):
        ok = (np.isfinite(a[key]) & np.isfinite(a[key + "_prev"]) & np.isfinite(b[key]) & np.isfinite(b[key + "_prev"])
              & (a[key + "_age"] <= max_age) & (b[key + "_age"] <= max_age))
        sd = np.sign(a[key] - a[key + "_prev"])
        rd = np.sign(b[key] - b[key + "_prev"])
        res = np.where(ok & (sd > 0) & (rd < 0), 1.0, np.where(ok & (sd < 0) & (rd > 0), -1.0, 0.0))
        return np.where(ok, res, np.nan)
    return pair(sym, ref, "sl"), pair(sym, ref, "sh")


# ------------------------------------------------------------------------------------------------ zaman / seans
def tr_clock(t_dec_ms) -> dict[str, np.ndarray]:
    """Karar anı (ms, UTC epoch) → TR yerel saat: hour (0–23), hour_f (kesirli), mod (dakika-gün), dow (0=Pazartesi), killzone kodu (0 yok, 1 Asya, 2 Londra, 3 NY)."""
    t = np.asarray(t_dec_ms, dtype=np.int64) + TZ_OFFSET_MS
    mod = ((t // 60_000) % 1440).astype(np.int64)
    day = t // 86_400_000
    dow = ((day + 3) % 7).astype(np.int64)                 # 1970-01-01 Perşembe → (0 + 3) % 7 = 3 (Pazartesi = 0)
    kz = np.zeros(mod.shape, dtype=np.int64)
    for code, (a, b) in enumerate(KILLZONES.values(), start=1):
        kz[(mod >= a) & (mod < b)] = code
    return {"hour": mod // 60, "hour_f": mod / 60.0, "mod": mod, "dow": dow, "kz": kz}


def _day_stack(x: np.ndarray, offset: int) -> tuple[np.ndarray, int]:
    """(T,) → (D, 288): gün sınırı bar indeksi `offset`+288·m. Dönüş (Y, pad)."""
    pad = (-offset) % BARS_PER_DAY
    n = pad + len(x)
    D = -(-n // BARS_PER_DAY)
    y = np.full(D * BARS_PER_DAY, np.nan)
    y[pad: pad + len(x)] = x
    return y.reshape(D, BARS_PER_DAY), pad


def _day_unstack(Y: np.ndarray, pad: int, T: int) -> np.ndarray:
    return Y.reshape(-1)[pad: pad + T]


def opening_range(h: np.ndarray, l: np.ndarray, c: np.ndarray, offset: int, or_bars: int = 6, fresh: int = 12) -> dict[str, np.ndarray]:
    """Gün açılış aralığı (günün ilk `or_bars` 5 dk barı; 6 = ilk 30 dk). `offset` = ilk gün sınırı bar indeksi (TR günü için 0 — ızgara TR gece yarısı;
    UTC günü için 36). Aralık yalnız TAMAMLANDIKTAN sonra (gün içi konum ≥ or_bars) kullanılır.
    Dönüş (T,): state (+1 üstünde / −1 altında / 0 içinde, NaN: aralık hazır değil), dist (aralığın dışındaysa en yakın uca % uzaklık, içerideyse 0),
    fresh (+1/−1: bugünün İLK kırılımı son `fresh` bar içinde ve kırılım yönü sürüyor; 0 diğer)."""
    T = len(c)
    Yh, _ = _day_stack(np.asarray(h, dtype=float), offset)
    Yl, _ = _day_stack(np.asarray(l, dtype=float), offset)
    Yc, pad = _day_stack(np.asarray(c, dtype=float), offset)
    orh = np.max(Yh[:, :or_bars], axis=1)[:, None]            # NaN yayılır (eksik gün başlangıcı → NaN)
    orl = np.min(Yl[:, :or_bars], axis=1)[:, None]
    pos = np.arange(BARS_PER_DAY)[None, :]
    avail = (pos >= or_bars) & np.isfinite(orh) & np.isfinite(orl) & np.isfinite(Yc)
    up = avail & (Yc > orh)
    dn = avail & (Yc < orl)
    state = np.where(avail, up.astype(float) - dn.astype(float), np.nan)
    with np.errstate(invalid="ignore"):
        dist = np.where(up, (Yc / orh - 1.0) * 100.0, np.where(dn, (Yc / orl - 1.0) * 100.0, np.where(avail, 0.0, np.nan)))
    out = {}
    fr = np.zeros(Yc.shape)
    for sgn, m in ((1.0, up), (-1.0, dn)):
        first_cnt = np.cumsum(m, axis=1)
        first = m & (first_cnt == 1)                           # günün ilk kırılım barı
        fpos = np.where(first.any(axis=1), np.argmax(first, axis=1), -10 ** 6)[:, None]
        recent = (pos - fpos >= 0) & (pos - fpos <= fresh) & m
        fr = np.where(recent, sgn, fr)
    fr = np.where(avail, fr, np.nan)
    out["state"], out["dist"], out["fresh"] = (_day_unstack(a, pad, T) for a in (state, dist, fr))
    return out


def prev_day_levels(h: np.ndarray, l: np.ndarray, c: np.ndarray, offset: int = 0, sweep_bars: int = 12) -> dict[str, np.ndarray]:
    """Önceki (TAMAMLANMIŞ) günün tepe/dibi: dist_pdh, dist_pdl (% uzaklık), sweep_pdl (+1: son `sweep_bars` barda PDL altına inildi ∧ şimdi PDL üstünde = dip süpürme+geri alma),
    sweep_pdh (−1: PDH üstüne çıkıldı ∧ şimdi PDH altında). Önceki gün eksik/yarım → NaN."""
    T = len(c)
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    Yh, pad = _day_stack(h, offset)
    Yl, _ = _day_stack(l, offset)
    dh = np.max(Yh, axis=1)                                    # günün tamamı (NaN: yarım gün)
    dl = np.min(Yl, axis=1)
    pdh = np.concatenate([[np.nan], dh[:-1]])[:, None] * np.ones((1, BARS_PER_DAY))
    pdl = np.concatenate([[np.nan], dl[:-1]])[:, None] * np.ones((1, BARS_PER_DAY))
    PDH, PDL = _day_unstack(pdh, pad, T), _day_unstack(pdl, pad, T)
    with np.errstate(invalid="ignore"):
        broke_lo = np.isfinite(PDL) & (l < PDL)
        broke_hi = np.isfinite(PDH) & (h > PDH)
        rl = rolling_sum(broke_lo.astype(float), sweep_bars) > 0
        rh = rolling_sum(broke_hi.astype(float), sweep_bars) > 0
        ok = np.isfinite(PDH) & np.isfinite(PDL) & np.isfinite(c)
        sw_lo = np.where(ok, (rl & (c > PDL)).astype(float), np.nan)
        sw_hi = np.where(ok, -(rh & (c < PDH)).astype(float), np.nan)
        return {"dist_pdh": (c / PDH - 1.0) * 100.0, "dist_pdl": (c / PDL - 1.0) * 100.0, "sweep_pdl": sw_lo, "sweep_pdh": sw_hi}


def rvol_tod(qv: np.ndarray, smooth: int = 3, days: int = 7, min_days: int = 3) -> np.ndarray:
    """Aynı gün-içi saate göre göreli hacim: son `smooth` barın quote toplamı / önceki en çok `days` GÜNÜN aynı barındaki aynı toplamların ortalaması
    (≥ min_days gün yoksa NaN). Yalnız önceki günler. `qv` (T,), ızgara TR gece yarısında başlar (offset 0)."""
    T = len(qv)
    qs = rolling_sum(np.asarray(qv, dtype=float), smooth)
    Y, pad = _day_stack(qs, 0)
    D = Y.shape[0]
    base = np.full(Y.shape, np.nan)
    for d in range(1, D):
        w = Y[max(0, d - days): d]
        n = np.isfinite(w).sum(axis=0)
        with np.errstate(invalid="ignore"):
            m = np.nansum(np.where(np.isfinite(w), w, 0.0), axis=0) / np.maximum(n, 1)
        base[d] = np.where(n >= min_days, m, np.nan)
    b = _day_unstack(base, pad, T)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(b > 0, np.minimum(qs / b, 100.0), np.nan)


# ------------------------------------------------------------------------------------------------ BTC 1 sa EMA200 "kalkan" (canlı ile aynı tanım)
def btc_shield_ema(price5: np.ndarray, hour_closes_prior: np.ndarray, bars_per_hour: int = 12, hour_phase: int = 0, period: int = 200, n_window: int = 210) -> np.ndarray:
    """Canlı kalkan: EMA200 (SMA tohumlu) of closes[-210:], son kapanış = forming 1 sa barın anlık fiyatı. 5 dk BTC kapanışları `price5` (T,) —
    bar k saatin hour_phase-inci 5 dk barıdır: (k + hour_phase) % 12 == 11 ise k bar SAAT KAPANIŞIDIR.
    `hour_closes_prior`: price5[0]'dan ÖNCE tamamlanmış saatlik kapanışlar (eski → yeni; ≥ n_window−1 eleman önerilir).
    Dönüş (T,): EMA200 (forming fiyat dâhil). Kalkan AÇIK ⇔ price5 < dönüş."""
    price5 = np.asarray(price5, dtype=float)
    T = len(price5)
    a = 2.0 / (period + 1.0)
    # tamamlanmış saat kapanışları dizisi: prior + bu serideki saat bitişleri
    is_close = ((np.arange(T) + hour_phase) % bars_per_hour) == (bars_per_hour - 1)
    hc_new = price5[is_close]
    hc_all = np.concatenate([np.asarray(hour_closes_prior, dtype=float), hc_new])
    n_prior = len(hour_closes_prior)
    out = np.full(T, np.nan)
    # her bar için "son tamamlanmış saat" indeksi (hc_all içinde) ve onun EMA'sı (n_window−1 eleman penceresi)
    comp_before = np.cumsum(is_close) - is_close.astype(int)     # bar k'dan ÖNCE biten saat sayısı (k saat bitişiyse k hariç)
    last_idx = n_prior + comp_before - 1                          # k anında tamamlanmış en son saat (hc_all indeksi)
    cache: dict[int, float] = {}

    def e_prev(j: int) -> float:
        if j in cache:
            return cache[j]
        w = hc_all[max(0, j - (n_window - 1) + 1): j + 1]        # n_window−1 elemanlı pencere (j dâhil)
        if len(w) < period:
            cache[j] = np.nan
            return np.nan
        v = float(np.mean(w[:period]))
        for x in w[period:]:
            v = a * float(x) + (1 - a) * v
        cache[j] = v
        return v

    for k in range(T):
        j = int(last_idx[k])
        if j < 0:
            continue
        e = e_prev(j)
        if np.isfinite(e) and np.isfinite(price5[k]):
            out[k] = a * price5[k] + (1 - a) * e
    return out


# ------------------------------------------------------------------------------------------------ toplu özellik kurucu
MARKET_FEATURES = [
    "b_pct_ema20_5m", "b_pct_ema50_5m", "b_pct_ema20_1h", "b_pct_ema50_1h",
    "b_adr_5", "b_adr_15", "b_adr_60", "b_adslope_12", "b_adslope_48", "b_mcc_5m", "b_mcc_1h",
    "b_nhl_24h", "b_thrust_s", "b_thrust", "b_thrust_recent", "b_tk55", "b_disp_5", "b_disp_15", "b_disp_60",
    "m_ret_15", "m_ret_60", "m_ret_240", "btc_ret_15", "btc_ret_60", "btc_ret_240", "usd_ret_15", "usd_ret_60", "usd_ret_240", "usd_ret_1440",
    "m_nvalid",
]
SYMBOL_FEATURES = [
    "rs_btc_15", "rs_btc_60", "rs_btc_240", "rs_mkt_15", "rs_mkt_60", "rs_mkt_240", "rk_15", "rk_60", "rk_240",
    "beta_btc_24h", "corr_btc_24h", "rs_usd_60",
    "smt_low_btc", "smt_high_btc", "smt_low_mkt", "smt_high_mkt",
    "orb_tr_state", "orb_tr_dist", "orb_tr_fresh", "orb_utc_state", "orb_utc_dist", "orb_utc_fresh",
    "pd_dist_pdh", "pd_dist_pdl", "pd_sweep_pdl", "pd_sweep_pdh", "rvol_tod",
]


def market_features(C, H, L, QV, TBQ, V) -> dict[str, np.ndarray]:
    """Piyasa düzeyi özellikleri → {ad: (T,) float32}."""
    out: dict[str, np.ndarray] = {}
    for sp, nm in ((20, "5m"), (50, "5m")):
        out[f"b_pct_ema{sp}_{nm}"] = pct_above(C, ema(C, sp), V)
    out["b_pct_ema20_1h"] = pct_above(C, ema(C, 240), V)          # 1 sa EMA20 ≈ 5 dk kapanışlarında EMA(240)
    out["b_pct_ema50_1h"] = pct_above(C, ema(C, 600), V)          # 1 sa EMA50 ≈ EMA(600)
    for lag, nm in ((1, "5"), (3, "15"), (12, "60")):
        a, d, _ = adv_dec(C, V, lag)
        out[f"b_adr_{nm}"] = ad_ratio(a, d)
    a1, d1, n1 = adv_dec(C, V, 1)
    out["b_adslope_12"] = ad_line_slope(a1, d1, n1, 12)
    out["b_adslope_48"] = ad_line_slope(a1, d1, n1, 48)
    out["b_mcc_5m"] = mcclellan(a1, d1, 19, 39)
    out["b_mcc_1h"] = mcclellan(a1, d1, 19 * 12, 39 * 12)
    out["b_nhl_24h"] = net_highs_lows(C, H, L, V)
    s, th = breadth_thrust(ad_ratio(a1, d1))
    out["b_thrust_s"], out["b_thrust"] = s, th
    out["b_thrust_recent"] = np.where(np.isfinite(th), (rolling_sum(np.nan_to_num(th), 36) > 0).astype(float), np.nan)
    out["b_tk55"] = pct_taker_buy(TBQ, QV, V)
    for lag, nm in ((1, "5"), (3, "15"), (12, "60")):
        _, sd = xs_mean_std(lag_return(C, lag), V)
        out[f"b_disp_{nm}"] = sd
    for lag, nm in ((3, "15"), (12, "60"), (48, "240")):
        mu, _ = xs_mean_std(lag_return(C, lag), V)
        out[f"m_ret_{nm}"] = mu
    out["m_nvalid"] = V.sum(axis=0).astype(float)
    return {k: v.astype(np.float32) for k, v in out.items()}


def btc_usd_features(btc_c, usd_c) -> dict[str, np.ndarray]:
    out = {}
    for lag, nm in ((3, "15"), (12, "60"), (48, "240")):
        out[f"btc_ret_{nm}"] = lag_return(btc_c, lag)
        out[f"usd_ret_{nm}"] = lag_return(usd_c, lag)
    out["usd_ret_1440"] = lag_return(usd_c, 288)
    return {k: v.astype(np.float32) for k, v in out.items()}


def symbol_feature_iter(C, H, L, QV, V, btc_idx: int, mkt_level: np.ndarray, mkt_ret: dict[str, np.ndarray], usd_ret_60: np.ndarray):
    """Sembol düzeyi özellikleri tek tek üretir: yield (ad, (S,T) float32). Bellek için çağıran her birini diske yazıp bırakabilir."""
    S, T = C.shape
    btc_c = C[btc_idx]
    for lag, nm in ((3, "15"), (12, "60"), (48, "240")):
        R = lag_return(C, lag)
        yield f"rs_btc_{nm}", (R - R[btc_idx][None, :]).astype(np.float32)
        yield f"rs_mkt_{nm}", (R - mkt_ret[nm][None, :]).astype(np.float32)
        Rv = np.where(V, R, np.nan)
        yield f"rk_{nm}", xs_rank_pct(Rv).astype(np.float32)
    r1 = np.log(C / shift(C, 1))
    beta, corr = rolling_beta_corr(r1, r1[btc_idx], 288)
    yield "beta_btc_24h", beta.astype(np.float32)
    yield "corr_btc_24h", corr.astype(np.float32)
    R60 = lag_return(C, 12)
    yield "rs_usd_60", ((1 + R60 / 100.0) / (1 + usd_ret_60[None, :] / 100.0) * 100.0 - 100.0).astype(np.float32)
    # SMT
    sw_btc = fractal_swings(H[btc_idx], L[btc_idx])
    sw_mkt = fractal_swings(mkt_level, mkt_level)
    smt = {"low_btc": np.full((S, T), np.nan, np.float32), "high_btc": np.full((S, T), np.nan, np.float32),
           "low_mkt": np.full((S, T), np.nan, np.float32), "high_mkt": np.full((S, T), np.nan, np.float32)}
    for s in range(S):
        sw = fractal_swings(H[s], L[s])
        smt["low_btc"][s], smt["high_btc"][s] = smt_flags(sw, sw_btc)
        smt["low_mkt"][s], smt["high_mkt"][s] = smt_flags(sw, sw_mkt)
    for k, v in smt.items():
        yield f"smt_{k}", v
    # gün/seans
    ORB = {"orb_tr": 0, "orb_utc": 36}
    orbs = {k: {"state": np.full((S, T), np.nan, np.float32), "dist": np.full((S, T), np.nan, np.float32), "fresh": np.full((S, T), np.nan, np.float32)} for k in ORB}
    pd = {k: np.full((S, T), np.nan, np.float32) for k in ("dist_pdh", "dist_pdl", "sweep_pdl", "sweep_pdh")}
    rv = np.full((S, T), np.nan, np.float32)
    for s in range(S):
        for k, off in ORB.items():
            r = opening_range(H[s], L[s], C[s], off)
            for kk in ("state", "dist", "fresh"):
                orbs[k][kk][s] = r[kk]
        r = prev_day_levels(H[s], L[s], C[s], 0)
        for kk in pd:
            pd[kk][s] = r[kk]
        rv[s] = rvol_tod(QV[s])
    for k in ORB:
        for kk in ("state", "dist", "fresh"):
            yield f"{k}_{kk}", orbs[k][kk]
    for kk in pd:
        yield f"pd_{kk}", pd[kk]
    yield "rvol_tod", rv
