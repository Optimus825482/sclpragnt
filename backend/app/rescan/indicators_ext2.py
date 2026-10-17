"""Genişletilmiş gösterge kütüphanesi v2 — rehberin YENİ (★) maddeleri (2026-10-17, çevrimdışı araştırma).

Canlı koda BAĞLANMAZ; ağ/DB yok; saf numpy (+scipy.lfilter). `indicators_ext.py` ile AYNI kurallar:
  * NEDENSELLİK: i. değer YALNIZ <= i barlarına bağlıdır (testle doğrulanır: gelecek barları değiştirmek geçmişi değiştirmez; diziyi kesmek aynı sonucu verir).
  * Salınım/fraktal tabanlı her şey (RSI ıraksaması, çift dip, otomatik Fibonacci/trend çizgisi, OTE ...) `right` bar SONRA onaylanır.
  * Gün tabanlı özellikler (önceki gün H/L, ORB, Judas, NDOG, TWAP, ADR) yalnız TAMAMLANMIŞ günlerin / o güne kadarki barların bilgisini kullanır.
  * Her gösterge birkaç ölçekten bağımsız özelliğe (uzaklık %, z, durum, son-k-barda-dönüş bayrağı) kodlanır; tüm adlar `x2.` önekli (`<tf>.x2.<ad>`).
  * Ortalamalar `_ema0` (ilk sonlu değerden tohumlu) ile yapılır: ısınma farkı yalnız ilk ~5n barı etkiler.

Kapsam (indicators_ext.py'de OLMAYANLAR): MA şeridi, PMO, Hızlandırıcı osilatör, Pring Special K, SMI (Blau), Woodies CCI, Aroon osilatörü, Bull/Bear Power,
Hacim Delta, Kümülatif Hacim, NVI/PVI, günün-saatine göre RVOL, BBTrend, Medyan Kanal, ADR, 7g/30g yüksek-alçak, TWAP, Lineer Regresyon Kanalı, RCI (+şerit),
Chandelier, RSI ıraksaması, Ulcer, Volatility Stop, Otomatik Fibonacci, trend çizgisi kırılımı; SMC: Breaker, iFVG, iOB, BPR, CISD, CRT/Turtle Soup, OTE,
Premium/Discount, Volume Imbalance, Liquidity Void, önceki gün H/L (+süpürme), ORB (UTC ve TR günü), Judas, killzone/seans, NDOG; formasyonlar: çift/üçlü dip,
Wyckoff spring/UTAD, VSA, mum formasyonları, V/fincan; topluluk: Range Filter, Coral, Gaussian Kanal, HA-RSI, Jurik (yaklaşık), QQE MOD, Sıkışma Momentumu (LazyBear),
SSL, TDI, T3, UT Bot, VuManChu Cipher B, Waddah Attar, WaveTrend; ileri: CoG, VHF, Ehlers ani trend çizgisi, Elder Impulse, RMI, Kase (yaklaşık), Kaufman ER,
Laguerre RSI, MAMA/FAMA, PGO, Psikolojik Çizgi, QStick, R2, RWI, Schaff, Cyber Cycle, STARC, Twiggs MF, DeMarker, FRAMA, Heikin-Ashi, BW MFI, OsMA, VIDYA.

Ana giriş: `compute_all(arr, tf)` -> (isimler `<tf>.x2.<ad>`, float32 matris). `arr`: pattern_study dizi düzeni (open_time, o, h, l, c, v, quote_v[, taker_base, taker_quote]).
"""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter, lfilter_zi

from app.rescan import indicators_ext as I
from app.rescan import pattern_study as P

DAY_MS = 86_400_000
TR_OFF_MS = 3 * 3_600_000                     # Europe/Istanbul = UTC+3 (DST yok)
BAR_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000}
BARS_PER_DAY = {"1m": 1440, "5m": 288, "15m": 96}

FAMILY: dict[str, str] = {}
__all__: list[str] = ["compute_all", "feature_names", "FAMILY"]


def _export(fn):
    __all__.append(fn.__name__)
    return fn


# ----------------------------------------------------------------------------------------------- yardımcılar
_f = I._f
_nz = I._nz
_div = I._div
shift = I.shift
sma = I.sma
rsum = I.rsum
_roll_sum0 = I._roll_sum0
_first_finite = I._first_finite
_tr = I._tr
_run = I._run


def _lf(x, b, a) -> np.ndarray:
    """IIR süzgeç (lfilter), ilk sonlu değerin kararlı-durum başlangıcıyla; baştaki NaN korunur."""
    x = _f(x)
    out = np.full(len(x), np.nan)
    f = _first_finite(x)
    if f >= len(x):
        return out
    y = x[f:]
    zi = lfilter_zi(b, a) * y[0]
    out[f:] = lfilter(b, a, y, zi=zi)[0]
    return out


def _ema0(x, n: float) -> np.ndarray:
    al = 2.0 / (n + 1.0)
    return _lf(x, [al], [1.0, -(1.0 - al)])


def _rma0(x, n: float) -> np.ndarray:
    al = 1.0 / n
    return _lf(x, [al], [1.0, -(1.0 - al)])


def _flag(cond, valid) -> np.ndarray:
    """0/1 bayrak; `valid` False -> NaN."""
    return np.where(valid, np.asarray(cond, dtype=bool).astype(float), np.nan)


def _cross_up(a, b) -> np.ndarray:
    a, b = _f(a), _f(b)
    pa, pb = shift(a, 1), shift(b, 1)
    ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(pa) & np.isfinite(pb)
    with np.errstate(invalid="ignore"):
        return _flag((a > b) & (pa <= pb), ok)


def _cross_dn(a, b) -> np.ndarray:
    a, b = _f(a), _f(b)
    pa, pb = shift(a, 1), shift(b, 1)
    ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(pa) & np.isfinite(pb)
    with np.errstate(invalid="ignore"):
        return _flag((a < b) & (pa >= pb), ok)


def _recent(flag, k: int) -> np.ndarray:
    """Son k barda (şimdiki dahil) bayrak var mı; bayrak NaN olan yerler NaN."""
    fl = _f(flag)
    return np.where(np.isfinite(fl), (_roll_sum0(fl, k) > 0).astype(float), np.nan)


def _rollmax_exp(x, w: int, mp: int) -> np.ndarray:
    """out[i] = max(x[max(0, i-w+1) .. i]) (i >= mp-1; öncesi NaN). van Herk/Gil-Werman, O(N). x sonlu varsayılır."""
    x = _f(x)
    N = len(x)
    out = np.full(N, np.nan)
    if N == 0 or N < mp:
        return out
    ninf = -np.inf
    y = np.concatenate([np.full(w - 1, ninf), np.where(np.isfinite(x), x, ninf)])
    M = len(y)
    pad = (-M) % w
    yp = np.concatenate([y, np.full(pad, ninf)]).reshape(-1, w)
    g = np.maximum.accumulate(yp, axis=1).reshape(-1)
    hh = np.maximum.accumulate(yp[:, ::-1], axis=1)[:, ::-1].reshape(-1)
    res = np.maximum(hh[:N], g[w - 1: w - 1 + N])
    res[res == ninf] = np.nan
    out[mp - 1:] = res[mp - 1:]
    return out


def _rollmin_exp(x, w: int, mp: int) -> np.ndarray:
    return -_rollmax_exp(-_f(x), w, mp)


def _atr(h, l, c, n: int = 14) -> np.ndarray:
    return P.atr_series(_f(h), _f(l), _f(c), n)


def _rsi(c, n: int = 14) -> np.ndarray:
    return P.rsi_series(_f(c), n)


def _clip(x, lo, hi) -> np.ndarray:
    return np.clip(_f(x), lo, hi)


def _swing_idx(h, l, left: int, right: int):
    """Onaylı fraktal tepe/dipler: (idx_h, px_h, conf_h) (tepe bar indeksi, fiyat, onay bar indeksi) ve aynısı dipler için. Onay = j + right."""
    sp = I.swing_pivots(h, l, left, right)
    ch = np.flatnonzero(np.isfinite(sp["sh_price"]))
    cl = np.flatnonzero(np.isfinite(sp["sl_price"]))
    return (ch - right, sp["sh_price"][ch], ch), (cl - right, sp["sl_price"][cl], cl)


def _last_pivots(N: int, piv, k: int = 3):
    """Her bar i için, i'de ONAYLI son k pivotun (indeks, fiyat): (J, Px) şekli (k, N); [0]=en yeni; yoksa -1/NaN."""
    pj, pp, pc = piv
    J = np.full((k, N), -1, dtype=np.int64)
    Px = np.full((k, N), np.nan)
    if len(pc) == 0:
        return J, Px
    pos = np.searchsorted(pc, np.arange(N), side="right") - 1          # i'de onaylı son pivotun sırası
    for q in range(k):
        pq = pos - q
        ok = pq >= 0
        J[q] = np.where(ok, pj[np.clip(pq, 0, len(pj) - 1)], -1)
        Px[q] = np.where(ok, pp[np.clip(pq, 0, len(pj) - 1)], np.nan)
    return J, Px


# ----------------------------------------------------------------------------------------------- gün / seans bağlamı
def _day_ctx(t: np.ndarray, off_ms: int):
    """Gün dilimleri: (seg_id, mins_ms (bar AÇILIŞININ gün başından ms'si), starts, ends (bitiş+1), full (dilim gün başından mı başlıyor))."""
    d = (t + off_ms) // DAY_MS
    first = np.r_[True, d[1:] != d[:-1]]
    starts = np.flatnonzero(first)
    ends = np.r_[starts[1:], len(t)]
    seg = np.cumsum(first) - 1
    mins = t - (d * DAY_MS - off_ms)
    full = mins[starts] == 0
    return seg, mins, starts, ends, full


@_export
def prev_day_levels(t, h, l, c, off_ms: int = 0) -> dict[str, np.ndarray]:
    """Önceki TAMAMLANMIŞ günün (UTC ya da off_ms ile TR) yüksek/alçak/kapanışı + o güne kadarki gün yüksek/alçak. Gün başından başlamayan (kısmi) ilk dilim
    'önceki gün' sayılmaz. Çıktılar bar başına: pdh, pdl, pdc, dhi, dlo, adr_pct (önceki <=14 tam günün ort. (H-L)/orta %, >=3 gün)."""
    t = np.asarray(t, dtype=np.int64)
    h, l, c = _f(h), _f(l), _f(c)
    N = len(t)
    seg, mins, starts, ends, full = _day_ctx(t, off_ms)
    K = len(starts)
    H = np.array([h[a:b].max() for a, b in zip(starts, ends)])
    L = np.array([l[a:b].min() for a, b in zip(starts, ends)])
    C = np.array([c[b - 1] for b in ends])
    rng_pct = (H - L) / np.maximum((H + L) / 2.0, 1e-12) * 100.0
    pdh = np.full(N, np.nan)
    pdl = np.full(N, np.nan)
    pdc = np.full(N, np.nan)
    adr = np.full(N, np.nan)
    for k in range(1, K):
        a, b = starts[k], ends[k]
        if full[k - 1]:
            pdh[a:b], pdl[a:b], pdc[a:b] = H[k - 1], L[k - 1], C[k - 1]
        prev = [rng_pct[j] for j in range(max(0, k - 14), k) if full[j]]
        if len(prev) >= 3:
            adr[a:b] = float(np.mean(prev))
    dhi = np.full(N, np.nan)
    dlo = np.full(N, np.nan)
    for a, b in zip(starts, ends):
        dhi[a:b] = np.maximum.accumulate(h[a:b])
        dlo[a:b] = np.minimum.accumulate(l[a:b])
    return {"pdh": pdh, "pdl": pdl, "pdc": pdc, "dhi": dhi, "dlo": dlo, "adr_pct": adr, "seg": seg, "mins": mins, "starts": starts, "ends": ends, "full": full}


def _day_feats(t, o, h, l, c, v, atr14, bar_ms: int) -> dict[str, np.ndarray]:
    """UTC ve TR günü: önceki gün H/L uzaklığı + süpürme, günün açılışına uzaklık (NDOG/DO), ORB 30/60 dk, Judas, TWAP, ADR kullanımı."""
    d: dict[str, np.ndarray] = {}
    N = len(c)
    ohlc4 = (o + h + l + c) / 4.0
    for tag, off in (("utc", 0), ("tr", TR_OFF_MS)):
        pl = prev_day_levels(t, h, l, c, off)
        mins, starts, ends, full = pl["mins"], pl["starts"], pl["ends"], pl["full"]
        pdh, pdl = pl["pdh"], pl["pdl"]
        ok = np.isfinite(pdh)
        d["pdh_dist_" + tag] = _div(c, pdh) * 100.0 - 100.0
        d["pdl_dist_" + tag] = _div(c, pdl) * 100.0 - 100.0
        d["pd_pos_" + tag] = _clip(_div(c - pdl, pdh - pdl), -1.0, 2.0)
        sw_lo = _flag((l < pdl) & (c > pdl), ok)
        sw_hi = _flag((h > pdh) & (c < pdh), ok)
        d["pdl_sweep_" + tag] = sw_lo
        d["pdh_sweep_" + tag] = sw_hi
        d["pdl_sweep_r12_" + tag] = _recent(sw_lo, 12)
        d["pdh_break_" + tag] = _flag(c > pdh, ok)
        dopen = np.full(N, np.nan)
        gap = np.full(N, np.nan)
        twap = np.full(N, np.nan)
        for k, (a, b) in enumerate(zip(starts, ends)):
            if not full[k]:
                continue
            dopen[a:b] = o[a]
            if a > 0:
                gap[a:b] = (o[a] / c[a - 1] - 1.0) * 100.0
            twap[a:b] = np.cumsum(ohlc4[a:b]) / np.arange(1, b - a + 1)
        d["dopen_dist_" + tag] = _div(c, dopen) * 100.0 - 100.0
        d["ndog_gap_" + tag] = gap
        d["twap_dist_" + tag] = _div(c, twap) * 100.0 - 100.0
        d["day_range_adr_" + tag] = _div((pl["dhi"] - pl["dlo"]) / np.maximum(c, 1e-12) * 100.0, pl["adr_pct"])
        d["adr_pct_" + tag] = pl["adr_pct"]
        for W in (30, 60):
            wms = W * 60_000
            orh = np.full(N, np.nan)
            orl = np.full(N, np.nan)
            for k, (a, b) in enumerate(zip(starts, ends)):
                if not full[k]:
                    continue
                inw = np.flatnonzero(mins[a:b] + bar_ms <= wms)
                if len(inw) == 0 or a + inw[-1] + 1 >= b:
                    continue
                e = a + inw[-1] + 1                                  # OR tamam: e. bar ve sonrası
                orh[e:b] = h[a:e].max()
                orl[e:b] = l[a:e].min()
            okk = np.isfinite(orh)
            up = _flag(c > orh, okk)
            dn = _flag(c < orl, okk)
            first_up = np.zeros(N)
            first_dn = np.zeros(N)
            for a, b in zip(starts, ends):
                u = np.nan_to_num(up[a:b])
                w_ = np.nan_to_num(dn[a:b])
                if u.any():
                    first_up[a + int(np.argmax(u))] = 1.0
                if w_.any():
                    first_dn[a + int(np.argmax(w_))] = 1.0
            nm = "orb%d_%s" % (W, tag)
            d[nm + "_state"] = np.where(okk, up - dn, np.nan)
            d[nm + "_dist_h"] = _div(c, orh) * 100.0 - 100.0
            d[nm + "_dist_l"] = _div(c, orl) * 100.0 - 100.0
            d[nm + "_up_first"] = np.where(okk, first_up, np.nan)
            d[nm + "_dn_first"] = np.where(okk, first_dn, np.nan)
            d[nm + "_up_r6"] = _recent(d[nm + "_up_first"], 6)
        # Judas swing: gün açılışından sonraki ilk 3 saatte açılışın >= 1*ATR altına (üstüne) sahte hareket, sonra açılışın üstüne (altına) dönüş; ilk 8 saat
        jb = np.full(N, np.nan)
        jbt = np.full(N, np.nan)
        jdp = np.full(N, np.nan)
        js = np.full(N, np.nan)
        for k, (a, b) in enumerate(zip(starts, ends)):
            if not full[k]:
                continue
            m_ = mins[a:b]
            early = m_ < 3 * 3_600_000
            lo_e = np.minimum.accumulate(np.where(early, l[a:b], np.inf))
            hi_e = np.maximum.accumulate(np.where(early, h[a:b], -np.inf))
            at = atr14[a:b]
            o0 = o[a]
            dip = (o0 - lo_e) / np.maximum(at, 1e-12)
            spk = (hi_e - o0) / np.maximum(at, 1e-12)
            win = m_ < 8 * 3_600_000
            cc = c[a:b]
            okb = np.isfinite(at) & (at > 0)
            st_b = (dip >= 1.0) & (cc > o0) & win
            st_s = (spk >= 1.0) & (cc < o0) & win
            jb[a:b] = np.where(okb, st_b.astype(float), np.nan)
            js[a:b] = np.where(okb, st_s.astype(float), np.nan)
            pb = np.r_[False, st_b[:-1]]
            jbt[a:b] = np.where(okb, (st_b & ~pb).astype(float), np.nan)
            jdp[a:b] = np.where(okb, np.clip(dip, 0, 10), np.nan)
        d["judas_bull_" + tag] = jb
        d["judas_bull_trig_" + tag] = jbt
        d["judas_bear_" + tag] = js
        d["judas_depth_" + tag] = jdp
    return d


def _session_feats(t, bar_ms: int) -> dict[str, np.ndarray]:
    """ICT killzone / seans bayrakları (EDT varsayımıyla UTC saatleri; veri Tem-Eki) + saat sin/cos (UTC ve TR günü)."""
    hr = ((t % DAY_MS) / 3_600_000.0)                       # bar açılışının UTC saati
    d = {
        "kz_asia": ((hr >= 0.0) & (hr < 4.0)).astype(float),
        "kz_london": ((hr >= 6.0) & (hr < 9.0)).astype(float),
        "kz_nyam": ((hr >= 11.0) & (hr < 14.0)).astype(float),
        "kz_nypm": ((hr >= 17.5) & (hr < 20.0)).astype(float),
        "kz_silver": (((hr >= 14.0) & (hr < 15.0)) | ((hr >= 7.0) & (hr < 8.0)) | ((hr >= 18.0) & (hr < 19.0))).astype(float),
        "hour_sin": np.sin(2 * np.pi * hr / 24.0),
        "hour_cos": np.cos(2 * np.pi * hr / 24.0),
        "tr_hour": (((t + TR_OFF_MS) % DAY_MS) / 3_600_000.0),
    }
    return d


def _rvol_tod(qv, bpd: int, ndays: int = 7, min_days: int = 3) -> np.ndarray:
    """Günün saatine göre RVOL: hacim / aynı saat dilimindeki önceki <= ndays günün ortalaması (>= min_days gün gerekir). Düzenli ızgara varsayılır."""
    qv = _f(qv)
    N = len(qv)
    S = np.full((ndays, N), np.nan)
    for k in range(1, ndays + 1):
        sh = k * bpd
        if sh < N:
            S[k - 1, sh:] = qv[:N - sh]
    cnt = np.isfinite(S).sum(axis=0)
    with np.errstate(invalid="ignore"):
        m = np.nansum(S, axis=0) / np.maximum(cnt, 1)
    m = np.where(cnt >= min_days, m, np.nan)
    return _div(qv, m)


# ----------------------------------------------------------------------------------------------- temel (basic) gösterge çekirdekleri
@_export
def aroon(h, l, n: int = 25) -> dict[str, np.ndarray]:
    """Aroon (n+1 barlık pencere): up = 100*(n - sonuncu_yüksekten_bu_yana_bar)/n, dn benzeri; osc = up - dn."""
    h, l = _f(h), _f(l)
    N = len(h)
    w = n + 1
    up = np.full(N, np.nan)
    dn = np.full(N, np.nan)
    if N >= w:
        Wh = np.lib.stride_tricks.sliding_window_view(h, w)[:, ::-1]
        Wl = np.lib.stride_tricks.sliding_window_view(l, w)[:, ::-1]
        sh = np.argmax(Wh, axis=1)               # ilk (= en yeni) maksimumun konumu = kaç bar önce
        sl = np.argmin(Wl, axis=1)
        up[w - 1:] = 100.0 * (n - sh) / n
        dn[w - 1:] = 100.0 * (n - sl) / n
    return {"up": up, "dn": dn, "osc": up - dn}


@_export
def rci(c, n: int) -> np.ndarray:
    """Rank Correlation Index (Spearman, zaman sırası ↔ fiyat sırası), [-100, 100]. Artan seri +100, azalan -100."""
    c = _f(c)
    N = len(c)
    out = np.full(N, np.nan)
    if N < n:
        return out
    W = np.lib.stride_tricks.sliding_window_view(c, n)
    order = np.argsort(W, axis=1, kind="stable")
    prank = np.argsort(order, axis=1, kind="stable") + 1
    trank = np.arange(1, n + 1)[None, :]
    d2 = ((trank - prank) ** 2).sum(axis=1)
    out[n - 1:] = (1.0 - 6.0 * d2 / (n * (n * n - 1.0))) * 100.0
    return out


@_export
def laguerre_rsi(c, gamma: float = 0.5) -> np.ndarray:
    """Ehlers Laguerre RSI [0,1]. L0 = (1-g)x + g L0[-1]; Li = -g L(i-1) + L(i-1)[-1] + g Li[-1]; CU/CD = Li-L(i+1) farklarının pozitif/negatif toplamı; CU+CD=0 -> 0,5."""
    c = _f(c)
    g = float(gamma)
    L0 = _lf(c, [1.0 - g], [1.0, -g])
    L1 = _lf(L0, [-g, 1.0], [1.0, -g])
    L2 = _lf(L1, [-g, 1.0], [1.0, -g])
    L3 = _lf(L2, [-g, 1.0], [1.0, -g])
    d1, d2, d3 = L0 - L1, L1 - L2, L2 - L3
    cu = np.maximum(d1, 0) + np.maximum(d2, 0) + np.maximum(d3, 0)
    cd = np.maximum(-d1, 0) + np.maximum(-d2, 0) + np.maximum(-d3, 0)
    s = cu + cd
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(s > 0, cu / np.where(s > 0, s, 1.0), 0.5)
    return np.where(np.isfinite(s), r, np.nan)


def _roll_std(x, n: int) -> np.ndarray:
    x = _f(x)
    N = len(x)
    out = np.full(N, np.nan)
    if N >= n:
        out[n - 1:] = np.lib.stride_tricks.sliding_window_view(x, n).std(axis=1)
    return out


def _roll_median(x, n: int) -> np.ndarray:
    x = _f(x)
    N = len(x)
    out = np.full(N, np.nan)
    if N >= n:
        out[n - 1:] = np.median(np.lib.stride_tricks.sliding_window_view(x, n), axis=1)
    return out


def _stoch_pos(x, hh, ll) -> np.ndarray:
    return _div(x - ll, hh - ll)


def _feat_basic(t, o, h, l, c, v, qv, tbq, has_tk, bpd: int, atr14) -> dict[str, np.ndarray]:
    d: dict[str, np.ndarray] = {}
    N = len(c)
    # --- MA şeridi (EMA 8/13/21/34)
    ms = [_ema0(c, n) for n in (8, 13, 21, 34)]
    al = sum(np.sign(ms[k] - ms[k + 1]) for k in range(3))
    d["ribbon_align"] = al
    d["ribbon_width"] = _div(np.maximum.reduce(ms) - np.minimum.reduce(ms), c) * 100.0
    d["ribbon_px"] = _div(c - np.mean(ms, axis=0), c) * 100.0
    bull = al == 3
    d["ribbon_flip_up6"] = _recent(np.where(np.isfinite(al), (bull & ~np.r_[False, bull[:-1]]).astype(float), np.nan), 6)
    d["ribbon_flip_dn6"] = _recent(np.where(np.isfinite(al), ((al == -3) & ~np.r_[False, (al == -3)[:-1]]).astype(float), np.nan), 6)
    # --- PMO
    roc1 = _div(c - shift(c, 1), shift(c, 1)) * 100.0
    pmo = _ema0(10.0 * _ema0(roc1[1:], 34), 19)
    pmo = np.r_[np.nan, pmo]
    ps = _ema0(pmo[1:], 10)
    ps = np.r_[np.nan, ps]
    d["pmo"] = pmo
    d["pmo_sig_diff"] = pmo - ps
    d["pmo_cross_up3"] = _recent(_cross_up(pmo, ps), 3)
    # --- Hızlandırıcı osilatör
    med = (h + l) / 2.0
    ao = sma(med, 5) - sma(med, 34)
    ac = ao - sma(ao, 5)
    d["ac_pct"] = _div(ac, c) * 100.0
    d["ac_chg"] = _div(ac - shift(ac, 1), c) * 100.0
    rise = (ac > shift(ac, 1)) & (shift(ac, 1) > shift(ac, 2))
    d["ac_up2"] = _flag(rise, np.isfinite(shift(ac, 2)))
    # --- Pring Special K (kısaltılmış: 8 bileşen, ROC 10..100)
    sk = np.zeros(N)
    for rl, sm_, wt in ((10, 10, 1), (15, 10, 2), (20, 10, 3), (30, 15, 4), (40, 50, 1), (65, 65, 2), (75, 75, 3), (100, 100, 4)):
        sk = sk + wt * sma(_div(c - shift(c, rl), shift(c, rl)) * 100.0, sm_)
    d["sk"] = sk
    d["sk_sig_diff"] = sk - sma(sk, 30)
    d["sk_chg5"] = sk - shift(sk, 5)
    # --- SMI (Blau 10,3,3)
    hh, ll = I.rolling_max(h, 10), I.rolling_min(l, 10)
    rel = c - (hh + ll) / 2.0
    rg = hh - ll
    num = _ema0(_ema0(rel[9:], 3), 3)
    den = _ema0(_ema0(rg[9:], 3), 3)
    smi = np.r_[np.full(9, np.nan), _div(num, 0.5 * den) * 100.0]
    ssig = np.r_[np.full(9, np.nan), _ema0(smi[9:], 3)]
    d["smi"] = smi
    d["smi_sig_diff"] = smi - ssig
    d["smi_cross_up_os"] = _recent(_flag((_cross_up(smi, ssig) > 0) & (smi < -40), np.isfinite(smi)), 3)
    # --- Woodies CCI
    c14 = I.cci(h, l, c, 14)
    c6 = I.cci(h, l, c, 6)
    d["wcci14"] = c14
    d["wcci6"] = c6
    d["wcci_diff"] = c6 - c14
    pos_run = _run(c14 > 0)
    neg_run = _run(c14 < 0)
    d["wcci_run"] = np.where(np.isfinite(c14), np.clip(pos_run - neg_run, -25, 25).astype(float), np.nan)
    side = _roll_sum0((c14 > 0).astype(float), 12)
    c14p = shift(c14, 1)
    d["wcci_zlr_long"] = _flag((c14p >= -25) & (c14p <= 25) & (c14 > c14p) & (side >= 6), np.isfinite(c14p))
    d["wcci_zlr_short"] = _flag((c14p >= -25) & (c14p <= 25) & (c14 < c14p) & (side <= 6), np.isfinite(c14p))
    # --- Aroon osilatörü
    ar = aroon(h, l, 25)
    d["aroon_osc"] = ar["osc"]
    d["aroon_up"] = ar["up"]
    d["aroon_osc_chg5"] = ar["osc"] - shift(ar["osc"], 5)
    d["aroon_cross_up3"] = _recent(_cross_up(ar["up"], ar["dn"]), 3)
    # --- Bull/Bear Power
    e13 = _ema0(c, 13)
    bp = _div(h - e13, c) * 100.0
    br = _div(l - e13, c) * 100.0
    d["bull_power"] = bp
    d["bear_power"] = br
    d["bbp_sum"] = bp + br
    d["bear_rising_pos"] = _flag((br < 0) & (br > shift(br, 1)) & (e13 > shift(e13, 1)), np.isfinite(shift(br, 1)))
    # --- Hacim Delta (taker al - sat)
    if has_tk:
        vd = 2.0 * tbq - qv
        d["vd_ratio"] = _div(vd, qv)
        d["vd_ratio_ema6"] = _ema0(np.nan_to_num(d["vd_ratio"]), 6)
        d["vd_sum12"] = _div(rsum(vd, 12), rsum(qv, 12))
        sd = np.sqrt(np.maximum(sma(vd * vd, bpd) - sma(vd, bpd) ** 2, 0.0))
        d["vd_z"] = _div(vd, sd)
        d["vd_div_up"] = _flag((c < shift(c, 6)) & (d["vd_sum12"] > 0.05), np.isfinite(d["vd_sum12"]) & np.isfinite(shift(c, 6)))
    else:
        for k in ("vd_ratio", "vd_ratio_ema6", "vd_sum12", "vd_z", "vd_div_up"):
            d[k] = np.full(N, np.nan)
    # --- Kümülatif Hacim indeksi (gövde/aralık ağırlıklı)
    cvi = np.cumsum(v * _nz(_div(c - o, h - l)))
    d["cvi_slope12"] = _div(cvi - shift(cvi, 12), rsum(v, 12))
    d["cvi_slope48"] = _div(cvi - shift(cvi, 48), rsum(v, 48))
    # --- NVI / PVI (log birikimli)
    r = np.r_[0.0, np.diff(np.log(np.maximum(c, 1e-12)))]
    vp = shift(v, 1)
    nv = np.cumsum(np.where(v < vp, r, 0.0))
    pv = np.cumsum(np.where(v > vp, r, 0.0))
    d["nvi_dist"] = (nv - _ema0(nv, 50)) * 100.0
    d["pvi_dist"] = (pv - _ema0(pv, 50)) * 100.0
    d["nvi_slope12"] = (nv - shift(nv, 12)) * 100.0
    d["pvi_slope12"] = (pv - shift(pv, 12)) * 100.0
    # --- günün saatine göre RVOL
    rv = _rvol_tod(qv, bpd)
    d["rvol_tod"] = rv
    d["rvol_tod_log"] = np.log(np.maximum(rv, 1e-3))
    d["rvol_tod_green3"] = _flag((rv > 3.0) & (c > o), np.isfinite(rv))
    d["rvol_tod_max3"] = I.rolling_max(np.nan_to_num(rv), 3)
    # --- BBTrend (20, 50)
    m20, m50 = sma(c, 20), sma(c, 50)
    s20, s50 = _roll_std(c, 20), _roll_std(c, 50)
    bbt = (np.abs((m20 - 2 * s20) - (m50 - 2 * s50)) - np.abs((m20 + 2 * s20) - (m50 + 2 * s50))) / np.maximum(m20, 1e-12) * 100.0
    d["bbtrend"] = bbt
    d["bbtrend_chg3"] = bbt - shift(bbt, 3)
    # --- Medyan Kanal (20, 2 ATR)
    md = _roll_median(c, 20)
    d["medch_pos"] = _div(c - md, 2.0 * atr14)
    d["medch_slope3"] = _div(md - shift(md, 3), shift(md, 3)) * 100.0
    d["medch_width"] = _div(4.0 * atr14, md) * 100.0
    # --- 7g / 30g yüksek-alçak uzaklığı (52 hafta vekili); pencere dolmadan >=3g / >=7g veri şart
    for nm, days, mpd in (("7d", 7, 3), ("30d", 30, 7)):
        w = days * bpd
        hx = _rollmax_exp(h, w, mpd * bpd)
        lx = _rollmin_exp(l, w, mpd * bpd)
        d["d%sh" % nm[:-1]] = _div(c, hx) * 100.0 - 100.0
        d["d%sl" % nm[:-1]] = _div(c, lx) * 100.0 - 100.0
        d["pos%s" % nm[:-1]] = _div(c - lx, hx - lx)
    # --- Lineer regresyon kanalı (100)
    lr = I.linreg_band(c, 100)
    d["lrc_pos"] = _div(c - lr["value"], 2.0 * lr["stderr"])
    d["lrc_width"] = _div(4.0 * lr["stderr"], c) * 100.0
    d["lrc_slope"] = _div(lr["slope"], c) * 100.0
    # --- RCI ve şerit
    r9, r26, r52 = rci(c, 9), rci(c, 26), rci(c, 52)
    d["rci9"], d["rci26"], d["rci52"] = r9, r26, r52
    d["rci_mean"] = (r9 + r26 + r52) / 3.0
    d["rci_all_rising"] = _flag((r9 > shift(r9, 1)) & (r26 > shift(r26, 1)) & (r52 > shift(r52, 1)), np.isfinite(shift(r52, 1)))
    d["rci9_cross_up_m80"] = _recent(_cross_up(r9, np.full(N, -80.0)), 3)
    # --- Ulcer indeksi
    mx = I.rolling_max(c, 14)
    dd = _div(c - mx, mx) * 100.0
    d["ulcer14"] = np.sqrt(sma(dd * dd, 14))
    return d


# ----------------------------------------------------------------------------------------------- durumlu çekirdekler (Chandelier, Volatility Stop)
@_export
def chandelier(h, l, c, n: int = 22, mult: float = 3.0) -> dict[str, np.ndarray]:
    """Chandelier Exit (everget Pine): long stop = HH(n) - mult*ATR(n) (c[-1] > önceki stop ise yükselir), short stop = LL(n) + mult*ATR(n);
    yön: -1 iken c > önceki short stop -> +1; +1 iken c < önceki long stop -> -1. Dönüş: dir (+1/-1), stop (aktif yönün stopu), flip_up/flip_dn (0/1)."""
    h, l, c = _f(h), _f(l), _f(c)
    N = len(c)
    atr = _atr(h, l, c, n)
    lsr = (I.rolling_max(h, n) - mult * atr).tolist()
    ssr = (I.rolling_min(l, n) + mult * atr).tolist()
    cl = c.tolist()
    dr = [float("nan")] * N
    stop = [float("nan")] * N
    fu = [float("nan")] * N
    fd = [float("nan")] * N
    ls_p = ss_p = float("nan")
    cur = 1
    for i in range(N):
        ls, ss = lsr[i], ssr[i]
        if ls != ls or ss != ss:
            continue
        if ls_p == ls_p and cl[i - 1] > ls_p:
            ls = max(ls, ls_p)
        if ss_p == ss_p and cl[i - 1] < ss_p:
            ss = min(ss, ss_p)
        prev = cur
        if ss_p == ss_p:
            if cur == -1 and cl[i] > ss_p:
                cur = 1
            elif cur == 1 and cl[i] < ls_p:
                cur = -1
        dr[i] = float(cur)
        stop[i] = ls if cur == 1 else ss
        fu[i] = 1.0 if (cur == 1 and prev == -1) else 0.0
        fd[i] = 1.0 if (cur == -1 and prev == 1) else 0.0
        ls_p, ss_p = ls, ss
    return {"dir": np.asarray(dr), "stop": np.asarray(stop), "flip_up": np.asarray(fu), "flip_dn": np.asarray(fd)}


@_export
def volatility_stop(h, l, c, n: int = 20, mult: float = 2.0) -> dict[str, np.ndarray]:
    """Volatility Stop (TradingView): ATR(n)*mult izleyen stop; yön kapanışın stopa göre konumuyla belirlenir; yön değişince stop yeniden başlar."""
    h, l, c = _f(h), _f(l), _f(c)
    N = len(c)
    am = (mult * _atr(h, l, c, n)).tolist()
    cl = c.tolist()
    st = [float("nan")] * N
    up = [float("nan")] * N
    fu = [float("nan")] * N
    fd = [float("nan")] * N
    mx = mn = float("nan")
    stop = float("nan")
    upt = True
    started = False
    for i in range(N):
        a = am[i]
        if a != a:
            continue
        if not started:
            mx = mn = cl[i]
            stop = cl[i] - a
            upt = True
            started = True
            st[i], up[i], fu[i], fd[i] = stop, 1.0, 0.0, 0.0
            continue
        mx = max(mx, cl[i])
        mn = min(mn, cl[i])
        stop = max(stop, mx - a) if upt else min(stop, mn + a)
        prev = upt
        upt = (cl[i] - stop) >= 0
        if upt != prev:
            mx = mn = cl[i]
            stop = cl[i] - a if upt else cl[i] + a
        st[i] = stop
        up[i] = 1.0 if upt else -1.0
        fu[i] = 1.0 if (upt and not prev) else 0.0
        fd[i] = 1.0 if ((not upt) and prev) else 0.0
    return {"dir": np.asarray(up), "stop": np.asarray(st), "flip_up": np.asarray(fu), "flip_dn": np.asarray(fd)}


# ----------------------------------------------------------------------------------------------- pivot tabanlı (RSI ıraksaması, Fibonacci/OTE/Premium-Discount, trend çizgisi, çift/üçlü dip)
def _feat_pivot(o, h, l, c, v, atr14) -> dict[str, np.ndarray]:
    d: dict[str, np.ndarray] = {}
    N = len(c)
    # --- RSI ıraksaması (fraktal 3/3; onay 3 bar sonra)
    rsi14 = _rsi(c, 14)
    ph3, pl3 = _swing_idx(h, l, 3, 3)
    bull = np.zeros(N)
    bear = np.zeros(N)
    pj, pp, pc = pl3
    for k in range(1, len(pj)):
        j1, j2 = pj[k - 1], pj[k]
        if 5 <= j2 - j1 <= 60 and pp[k] < pp[k - 1] and np.isfinite(rsi14[j1]) and np.isfinite(rsi14[j2]) and rsi14[j2] > rsi14[j1] and rsi14[j2] < 50:
            bull[pc[k]] = 1.0
    pj, pp, pc = ph3
    for k in range(1, len(pj)):
        j1, j2 = pj[k - 1], pj[k]
        if 5 <= j2 - j1 <= 60 and pp[k] > pp[k - 1] and np.isfinite(rsi14[j1]) and np.isfinite(rsi14[j2]) and rsi14[j2] < rsi14[j1] and rsi14[j2] > 50:
            bear[pc[k]] = 1.0
    okr = np.isfinite(rsi14)
    d["rsidiv_bull"] = np.where(okr, bull, np.nan)
    d["rsidiv_bull_r12"] = _recent(d["rsidiv_bull"], 12)
    d["rsidiv_bear"] = np.where(okr, bear, np.nan)
    d["rsidiv_bear_r12"] = _recent(d["rsidiv_bear"], 12)
    # --- Otomatik Fibonacci / OTE / Premium-Discount (fraktal 5/5)
    ph5, pl5 = _swing_idx(h, l, 5, 5)
    Jh, Ph = _last_pivots(N, ph5, 2)
    Jl, Pl = _last_pivots(N, pl5, 2)
    jh, H = Jh[0], Ph[0]
    jl, L = Jl[0], Pl[0]
    okf = (jh >= 0) & (jl >= 0) & (H > L) & (np.abs(jh - jl) <= 300)
    rng = np.where(okf, H - L, np.nan)
    dirn = np.where(jh > jl, 1.0, -1.0)
    ret = np.clip(np.where(dirn > 0, (H - c) / rng, (c - L) / rng), -1.0, 2.0)
    pdp = np.clip((c - L) / rng, -0.5, 1.5)
    d["fib_dir"] = np.where(okf, dirn, np.nan)
    d["fib_ret"] = ret
    d["fib_leg_pct"] = _div(rng, c) * 100.0
    lv = np.array([0.236, 0.382, 0.5, 0.618, 0.786])
    d["fib_near"] = np.min(np.abs(ret[:, None] - lv[None, :]), axis=1)
    zone = (ret >= 0.62) & (ret <= 0.79)
    ol = okf & (dirn > 0) & zone
    os_ = okf & (dirn < 0) & zone
    d["ote_long"] = _flag(ol, okf)
    d["ote_short"] = _flag(os_, okf)
    d["ote_long_tap"] = _flag(ol & ~np.r_[False, ol[:-1]], okf)
    d["ote_short_tap"] = _flag(os_ & ~np.r_[False, os_[:-1]], okf)
    d["pd_pos"] = pdp
    d["pd_discount"] = _flag(pdp < 0.5, okf)
    d["pd_deep_discount"] = _flag(pdp < 0.25, okf)
    # --- otomatik trend çizgisi kırılımı (fraktal 4/4): düşen direnç (son iki tepe) ve yükselen destek (son iki dip)
    ph4, pl4 = _swing_idx(h, l, 4, 4)
    ar = np.arange(N)
    J, Pp = _last_pivots(N, ph4, 2)
    j2, j1, p2, p1 = J[0], J[1], Pp[0], Pp[1]
    okt = (j1 >= 0) & (p2 < p1) & (j2 - j1 >= 5) & (ar - j2 <= 150)
    line = np.where(okt, p2 + (p2 - p1) / np.maximum(j2 - j1, 1) * (ar - j2), np.nan)
    same = (j2 == np.r_[-2, j2[:-1]])
    pl_ = shift(line, 1)
    brk = (c > line) & (shift(c, 1) <= pl_) & same & okt
    d["tl_res_dist"] = np.clip(_div(c, line) * 100.0 - 100.0, -10, 10)
    d["tl_res_break"] = _flag(brk, j1 >= 0)
    d["tl_res_break_r6"] = _recent(d["tl_res_break"], 6)
    J, Pp = _last_pivots(N, pl4, 2)
    j2, j1, p2, p1 = J[0], J[1], Pp[0], Pp[1]
    okt = (j1 >= 0) & (p2 > p1) & (j2 - j1 >= 5) & (ar - j2 <= 150)
    line = np.where(okt, p2 + (p2 - p1) / np.maximum(j2 - j1, 1) * (ar - j2), np.nan)
    same = (j2 == np.r_[-2, j2[:-1]])
    brk = (c < line) & (shift(c, 1) >= shift(line, 1)) & same & okt
    d["tl_sup_dist"] = np.clip(_div(c, line) * 100.0 - 100.0, -10, 10)
    d["tl_sup_break"] = _flag(brk, j1 >= 0)
    # --- çift / üçlü dip (fraktal 4/4; yaka çizgisi = aradaki en yüksek; kırılım = yaka üstüne ilk kapanış)
    pjl, ppl, pcl = pl4
    nk = len(pjl)
    neck2 = np.full(nk, np.nan)
    neck3 = np.full(nk, np.nan)
    ok2 = np.zeros(nk, dtype=bool)
    ok3 = np.zeros(nk, dtype=bool)
    floor2 = np.full(nk, np.nan)
    for k in range(1, nk):
        a_ = atr14[pcl[k]]
        if not (a_ == a_) or a_ <= 0:
            continue
        tol = 0.6 * a_
        gap = pjl[k] - pjl[k - 1]
        if 8 <= gap <= 100 and abs(ppl[k] - ppl[k - 1]) <= tol:
            nk2 = h[pjl[k - 1]: pjl[k] + 1].max()
            if nk2 - max(ppl[k], ppl[k - 1]) >= a_:
                neck2[k], ok2[k], floor2[k] = nk2, True, min(ppl[k], ppl[k - 1]) - tol
        if k >= 2 and ok2[k] and ok2[k - 1] and abs(ppl[k] - ppl[k - 2]) <= tol:
            neck3[k] = h[pjl[k - 2]: pjl[k] + 1].max()
            ok3[k] = True
    pos = np.searchsorted(pcl, ar, side="right") - 1
    pc_ = np.clip(pos, 0, max(nk - 1, 0))
    have = (pos >= 0) & (nk > 0)

    def _db(okk, neck):
        act = have & okk[pc_] & (ar - pjl[pc_] <= 150) & (c >= floor2[pc_])
        nk_ = np.where(act, neck[pc_], np.nan)
        brk_ = act & (c > nk_) & (shift(c, 1) <= shift(nk_, 1)) & (pos == np.r_[-2, pos[:-1]])
        return act, nk_, brk_

    if nk > 0:
        act2, nk2_, brk2 = _db(ok2, neck2)
        act3, nk3_, brk3 = _db(ok3, neck3)
    else:
        act2 = act3 = brk2 = brk3 = np.zeros(N, dtype=bool)
        nk2_ = np.full(N, np.nan)
    allv = np.isfinite(atr14)
    d["dbot_active"] = _flag(act2, allv)
    d["dbot_dist"] = np.where(act2, np.clip(_div(c, nk2_) * 100.0 - 100.0, -10, 10), np.nan)
    d["dbot_break"] = _flag(brk2, allv)
    d["dbot_break_r12"] = _recent(d["dbot_break"], 12)
    d["tbot_break"] = _flag(brk3, allv)
    d["tbot_break_r12"] = _recent(d["tbot_break"], 12)
    return d


# ----------------------------------------------------------------------------------------------- SMC bölge izleyicileri
def _fvg_inv(o, h, l, c, atr14, min_atr: float = 0.25, max_age: int = 60, bpr_span: int = 15) -> dict[str, np.ndarray]:
    """Inversion FVG (kapanışla tersine kırılan FVG kutusu karşı yönde bölge olur) ve Balanced Price Range (zıt yönlü iki FVG'nin kesişimi)."""
    N = len(c)
    atl = shift(atr14, 1).tolist()
    ol, hl, ll, cl = o.tolist(), h.tolist(), l.tolist(), c.tolist()
    keys = ["ifvg_bull_new", "ifvg_bull_active", "ifvg_bull_tap", "ifvg_bull_dist", "ifvg_bear_new", "ifvg_bear_tap",
            "bpr_bull_new", "bpr_bull_active", "bpr_bull_tap", "bpr_bear_new", "bpr_bear_tap"]
    out = {k: [0.0] * N for k in keys}
    for i in range(N):
        out["ifvg_bull_dist"][i] = 10.0
    bear_g: list = []
    bull_g: list = []
    ib: list = []
    ie: list = []
    rec_bull: list = []
    rec_bear: list = []
    bb: list = []
    be: list = []
    for i in range(N):
        a = atl[i]
        tap_b = tap_e = 0.0
        # iFVG bölgeleri
        nb = []
        for z in ib:
            if cl[i] < z[1] or i - z[2] > max_age:
                continue
            if i > z[2] and ll[i] <= z[0] and cl[i] >= z[1]:
                tap_b = 1.0
            nb.append(z)
        ib = nb
        ne = []
        for z in ie:
            if cl[i] > z[0] or i - z[2] > max_age:
                continue
            if i > z[2] and hl[i] >= z[1] and cl[i] <= z[0]:
                tap_e = 1.0
            ne.append(z)
        ie = ne
        # tersine çevrilme
        nbg = []
        for z in bear_g:
            if cl[i] > z[0]:
                ib.append([z[0], z[1], i])
                out["ifvg_bull_new"][i] = 1.0
            elif i - z[2] <= max_age:
                nbg.append(z)
        bear_g = nbg
        nug = []
        for z in bull_g:
            if cl[i] < z[1]:
                ie.append([z[0], z[1], i])
                out["ifvg_bear_new"][i] = 1.0
            elif i - z[2] <= max_age:
                nug.append(z)
        bull_g = nug
        # BPR bölgeleri
        tb = te = 0.0
        nb2 = []
        for z in bb:
            if cl[i] < z[1] or i - z[2] > max_age:
                continue
            if i > z[2] and ll[i] <= z[0] and cl[i] >= z[1]:
                tb = 1.0
            nb2.append(z)
        bb = nb2
        ne2 = []
        for z in be:
            if cl[i] > z[0] or i - z[2] > max_age:
                continue
            if i > z[2] and hl[i] >= z[1] and cl[i] <= z[0]:
                te = 1.0
            ne2.append(z)
        be = ne2
        rec_bull = [z for z in rec_bull if i - z[2] <= bpr_span]
        rec_bear = [z for z in rec_bear if i - z[2] <= bpr_span]
        # yeni FVG
        if i >= 2 and a == a and a > 0:
            if ll[i] > hl[i - 2] and (ll[i] - hl[i - 2]) >= min_atr * a:
                g = [ll[i], hl[i - 2], i]
                bull_g.append(g)
                for z in rec_bear:
                    lo_, hi_ = max(g[1], z[1]), min(g[0], z[0])
                    if hi_ > lo_:
                        bb.append([hi_, lo_, i])
                        out["bpr_bull_new"][i] = 1.0
                rec_bull.append(g)
            if hl[i] < ll[i - 2] and (ll[i - 2] - hl[i]) >= min_atr * a:
                g = [ll[i - 2], hl[i], i]
                bear_g.append(g)
                for z in rec_bull:
                    lo_, hi_ = max(g[1], z[1]), min(g[0], z[0])
                    if hi_ > lo_:
                        be.append([hi_, lo_, i])
                        out["bpr_bear_new"][i] = 1.0
                rec_bear.append(g)
        out["ifvg_bull_active"][i] = float(len(ib))
        out["ifvg_bull_tap"][i] = tap_b
        out["ifvg_bear_tap"][i] = tap_e
        out["bpr_bull_active"][i] = float(len(bb))
        out["bpr_bull_tap"][i] = tb
        out["bpr_bear_tap"][i] = te
        if ib:
            best = min(ib, key=lambda z: abs(cl[i] - z[0]))
            out["ifvg_bull_dist"][i] = max(-10.0, min(10.0, (cl[i] / best[0] - 1.0) * 100.0))
    res = {k: np.asarray(v) for k, v in out.items()}
    for v_ in res.values():
        v_[:20] = np.nan
    return res


def _breakers(o, h, l, c, atr14, k: float = 1.5, lookback: int = 5, max_age: int = 60, sweep_n: int = 20) -> dict[str, np.ndarray]:
    """Breaker Block (likidite süpüren order block'un ters yönde kırılması) ve Inversion OB (süpürme şartı YOK): düşüş OB'si = yer değiştirme-aşağıdan önceki son YÜKSELİŞ mumu;
    kapanış OB üstünü aşınca yükseliş breaker/iOB olur; sonra bölgeye dönüş = tap. Süpürme: OB mumunun tepesi önceki sweep_n barın en yükseğine eşit/üstünde."""
    N = len(c)
    atl = shift(atr14, 1).tolist()
    hx = shift(I.rolling_max(h, sweep_n), 1).tolist()
    lx = shift(I.rolling_min(l, sweep_n), 1).tolist()
    ol, hl, ll, cl = o.tolist(), h.tolist(), l.tolist(), c.tolist()
    keys = ["brk_bull_new", "brk_bull_active", "brk_bull_tap", "brk_bull_dist", "iob_bull_new", "iob_bull_active", "iob_bull_tap",
            "brk_bear_new", "brk_bear_tap", "iob_bear_new", "iob_bear_tap"]
    out = {kk: [0.0] * N for kk in keys}
    for i in range(N):
        out["brk_bull_dist"][i] = 10.0
    bear_ob: list = []          # [top, bot, born, swept] - tersine çevrilmeyi bekleyen düşüş OB'leri
    bull_ob: list = []
    zb: list = []               # aktif yükseliş breaker/iOB bölgeleri
    ze: list = []
    for i in range(N):
        a = atl[i]
        tp_b = tp_i = 0.0
        tq_b = tq_i = 0.0
        nz = []
        for z in zb:
            if cl[i] < z[1] or i - z[2] > max_age:
                continue
            if i > z[2] and ll[i] <= z[0] and cl[i] >= z[1]:
                tp_i = 1.0
                if z[3]:
                    tp_b = 1.0
            nz.append(z)
        zb = nz
        nz = []
        for z in ze:
            if cl[i] > z[0] or i - z[2] > max_age:
                continue
            if i > z[2] and hl[i] >= z[1] and cl[i] <= z[0]:
                tq_i = 1.0
                if z[3]:
                    tq_b = 1.0
            nz.append(z)
        ze = nz
        nz = []
        for z in bear_ob:
            if cl[i] > z[0]:
                zb.append([z[0], z[1], i, z[3]])
                out["iob_bull_new"][i] = 1.0
                if z[3]:
                    out["brk_bull_new"][i] = 1.0
            elif i - z[2] <= max_age:
                nz.append(z)
        bear_ob = nz
        nz = []
        for z in bull_ob:
            if cl[i] < z[1]:
                ze.append([z[0], z[1], i, z[3]])
                out["iob_bear_new"][i] = 1.0
                if z[3]:
                    out["brk_bear_new"][i] = 1.0
            elif i - z[2] <= max_age:
                nz.append(z)
        bull_ob = nz
        if a == a and a > 0:
            body = cl[i] - ol[i]
            if body < -k * a:
                for j in range(i - 1, max(i - lookback, 0) - 1, -1):
                    if cl[j] > ol[j]:
                        sw = hx[j] == hx[j] and hl[j] >= hx[j]
                        bear_ob.append([hl[j], ll[j], i, bool(sw)])
                        break
            elif body > k * a:
                for j in range(i - 1, max(i - lookback, 0) - 1, -1):
                    if cl[j] < ol[j]:
                        sw = lx[j] == lx[j] and ll[j] <= lx[j]
                        bull_ob.append([hl[j], ll[j], i, bool(sw)])
                        break
        out["iob_bull_active"][i] = float(len(zb))
        out["brk_bull_active"][i] = float(sum(1 for z in zb if z[3]))
        out["iob_bull_tap"][i] = tp_i
        out["brk_bull_tap"][i] = tp_b
        out["iob_bear_tap"][i] = tq_i
        out["brk_bear_tap"][i] = tq_b
        sw_z = [z for z in zb if z[3]]
        if sw_z:
            best = min(sw_z, key=lambda z: abs(cl[i] - z[0]))
            out["brk_bull_dist"][i] = max(-10.0, min(10.0, (cl[i] / best[0] - 1.0) * 100.0))
    res = {kk: np.asarray(v) for kk, v in out.items()}
    for v_ in res.values():
        v_[:20] = np.nan
    return res


def _cisd(o, c) -> dict[str, np.ndarray]:
    """CISD (delivery durumu değişimi): >=2 ardışık düşüş mumundan sonra kapanış, o serinin İLK mumunun açılışının üstüne çıkarsa yukarı CISD (<=10 bar içinde, ilk kez). Aynısı tersi."""
    N = len(c)
    ol, cl = o.tolist(), c.tolist()
    up = [0.0] * N
    dn = [0.0] * N
    run_b = run_s = 0
    open_b = open_s = 0.0
    arm_u = arm_d = None            # (referans açılış, bitiş indeksi)
    for i in range(N):
        bear = cl[i] < ol[i]
        bull = cl[i] > ol[i]
        if bear:
            if run_b == 0:
                open_b = ol[i]
            run_b += 1
        else:
            if run_b >= 2:
                arm_u = (open_b, i - 1)
            run_b = 0
        if bull:
            if run_s == 0:
                open_s = ol[i]
            run_s += 1
        else:
            if run_s >= 2:
                arm_d = (open_s, i - 1)
            run_s = 0
        if arm_u is not None:
            if i - arm_u[1] > 10:
                arm_u = None
            elif cl[i] > arm_u[0]:
                up[i] = 1.0
                arm_u = None
        if arm_d is not None:
            if i - arm_d[1] > 10:
                arm_d = None
            elif cl[i] < arm_d[0]:
                dn[i] = 1.0
                arm_d = None
    up, dn = np.asarray(up), np.asarray(dn)
    up[:10] = np.nan
    dn[:10] = np.nan
    return {"cisd_up": up, "cisd_dn": dn, "cisd_up_r6": _recent(up, 6), "cisd_dn_r6": _recent(dn, 6)}


def _vol_imbalance(o, h, l, c, atr14, max_age: int = 50) -> dict[str, np.ndarray]:
    """Volume Imbalance: ardışık iki mumun GÖVDELERİ arasında boşluk var ama fitiller örtüşüyor (tam FVG değil). Yükseliş: min(o,c)[i] > max(o,c)[i-1] ve l[i] <= h[i-1]."""
    N = len(c)
    atl = shift(atr14, 1).tolist()
    ol, hl, ll, cl = o.tolist(), h.tolist(), l.tolist(), c.tolist()
    new_b = [0.0] * N
    open_b = [0.0] * N
    tap_b = [0.0] * N
    new_e = [0.0] * N
    open_e = [0.0] * N
    zb: list = []
    ze: list = []
    for i in range(N):
        a = atl[i]
        tp = 0.0
        nz = []
        for z in zb:
            if cl[i] <= z[1] or i - z[2] > max_age:
                continue
            if i > z[2] and ll[i] <= z[0]:
                tp = 1.0
            nz.append(z)
        zb = nz
        ze = [z for z in ze if not (cl[i] >= z[0] or i - z[2] > max_age)]
        if i >= 1 and a == a and a > 0:
            bl, bh = min(ol[i], cl[i]), max(ol[i], cl[i])
            pl_, ph_ = min(ol[i - 1], cl[i - 1]), max(ol[i - 1], cl[i - 1])
            if bl > ph_ and ll[i] <= hl[i - 1] and (bl - ph_) >= 0.1 * a:
                zb.append([bl, ph_, i])
                new_b[i] = (bl - ph_) / a
            if bh < pl_ and hl[i] >= ll[i - 1] and (pl_ - bh) >= 0.1 * a:
                ze.append([pl_, bh, i])
                new_e[i] = (pl_ - bh) / a
        open_b[i] = float(len(zb))
        open_e[i] = float(len(ze))
        tap_b[i] = tp
    res = {"vi_bull_new": np.asarray(new_b), "vi_bull_open": np.asarray(open_b), "vi_bull_tap": np.asarray(tap_b),
           "vi_bear_new": np.asarray(new_e), "vi_bear_open": np.asarray(open_e)}
    for v_ in res.values():
        v_[:20] = np.nan
    return res


def _feat_smc(o, h, l, c, v, atr14) -> dict[str, np.ndarray]:
    d: dict[str, np.ndarray] = {}
    N = len(c)
    d.update(_fvg_inv(o, h, l, c, atr14))
    d.update(_breakers(o, h, l, c, atr14))
    d.update(_cisd(o, c))
    d.update(_vol_imbalance(o, h, l, c, atr14))
    a1 = shift(atr14, 1)
    # --- CRT / Turtle Soup: önceki n barın alçağı/yükseği süpürülüp kapanış geri içeri
    for nm, n in (("ts20", 20), ("ts50", 50)):
        pl_ = shift(I.rolling_min(l, n), 1)
        ph_ = shift(I.rolling_max(h, n), 1)
        ok = np.isfinite(pl_)
        d[nm + "_long"] = _flag((l < pl_) & (c > pl_), ok)
        d[nm + "_short"] = _flag((h > ph_) & (c < ph_), ok)
        d[nm + "_depth"] = np.where(d[nm + "_long"] == 1.0, _div(pl_ - l, a1), 0.0)
    l1, h1 = shift(l, 1), shift(h, 1)
    ok = np.isfinite(l1)
    d["crt_long"] = _flag((l < l1) & (c > l1) & (c < h1), ok)
    d["crt_short"] = _flag((h > h1) & (c < h1) & (c > l1), ok)
    d["ts20_long_r6"] = _recent(d["ts20_long"], 6)
    # --- Liquidity Void: 3 ardışık yeşil mum, toplam hareket >= 2,5 ATR; bölgeye (o[i-2], c[i]) geri dönüş
    g = c > o
    g3 = g & shift(g.astype(float), 1).astype(bool) & shift(g.astype(float), 2).astype(bool)
    mv = _div(c - shift(o, 2), a1)
    new = (g3 & (mv >= 2.5))
    new_f = np.where(np.isfinite(mv), new.astype(float), np.nan)
    d["void_up_new"] = np.where(new, mv, np.where(np.isfinite(mv), 0.0, np.nan))
    ar = np.arange(N)
    bi = np.maximum.accumulate(np.where(new, ar, -1))
    age = ar - bi
    top = np.where(bi >= 0, c[np.clip(bi, 0, N - 1)], np.nan)
    bot = np.where(bi >= 2, o[np.clip(bi - 2, 0, N - 1)], np.nan)
    ok = (bi >= 0) & (age >= 1) & (age <= 30)
    d["void_up_tap"] = _flag(ok & (l <= top) & (c >= bot), np.isfinite(mv))
    d["void_up_r30"] = _recent(new_f, 30)
    gd = c < o
    g3d = gd & shift(gd.astype(float), 1).astype(bool) & shift(gd.astype(float), 2).astype(bool)
    mvd = _div(shift(o, 2) - c, a1)
    d["void_dn_new"] = np.where(g3d & (mvd >= 2.5), mvd, np.where(np.isfinite(mvd), 0.0, np.nan))
    return d


# ----------------------------------------------------------------------------------------------- formasyonlar: Wyckoff, VSA, mumlar, V
def _feat_patterns(o, h, l, c, v, atr14) -> dict[str, np.ndarray]:
    d: dict[str, np.ndarray] = {}
    N = len(c)
    a1 = shift(atr14, 1)
    # --- Wyckoff spring / UTAD: dar aralığın (48 bar) alt/üst sınırının süpürülüp aynı barda geri alınması + hacim >= 1,5x
    LL = shift(I.rolling_min(l, 48), 1)
    HH = shift(I.rolling_max(h, 48), 1)
    vm = shift(sma(v, 20), 1)
    ok = np.isfinite(LL) & np.isfinite(vm) & np.isfinite(a1)
    ranged = (HH - LL) / np.maximum(a1, 1e-12) <= 12.0
    vol_hi = v > 1.5 * vm
    d["spring"] = _flag((l < LL) & (c > LL) & ranged & vol_hi, ok)
    d["utad"] = _flag((h > HH) & (c < HH) & ranged & vol_hi, ok)
    d["spring_r12"] = _recent(d["spring"], 12)
    d["utad_r12"] = _recent(d["utad"], 12)
    d["spring_depth"] = np.where(d["spring"] == 1.0, _div(LL - l, a1), 0.0)
    # --- VSA
    spread = h - l
    asp = shift(sma(spread, 20), 1)
    pos = _div(c - l, spread)
    v1, v2 = shift(v, 1), shift(v, 2)
    narrow = spread < 0.7 * asp
    lowv = (v < v1) & (v < v2)
    okv = np.isfinite(asp) & np.isfinite(vm) & np.isfinite(v2)
    d["vsa_nosupply"] = _flag((c < o) & narrow & lowv, okv)
    d["vsa_nodemand"] = _flag((c > o) & narrow & lowv, okv)
    dec = c < shift(c, 3)
    d["vsa_stopvol"] = _flag(dec & (v > 2.0 * vm) & (pos >= 0.5), okv)
    d["vsa_climax_dn"] = _flag((c < o) & (spread > 1.5 * asp) & (v > 2.5 * vm) & (pos >= 0.4), okv)
    d["vsa_ns_r6"] = _recent(d["vsa_nosupply"], 6)
    d["vsa_stop_r6"] = _recent(d["vsa_stopvol"], 6)
    # --- mum formasyonları (ATR göreli)
    body = np.abs(c - o)
    up_ = c > o
    dn_ = c < o
    c1, o1 = shift(c, 1), shift(o, 1)
    okc = np.isfinite(a1) & np.isfinite(shift(c, 4))
    eng = shift(dn_.astype(float), 1).astype(bool) & up_ & (o <= c1) & (c >= o1)
    d["cs_engulf"] = _flag(eng, okc)
    d["cs_engulf_dt"] = _flag(eng & (c1 < shift(c, 4)), okc)
    lw = np.minimum(o, c) - l
    uw = h - np.maximum(o, c)
    ham = (body > 0) & (lw >= 2.0 * body) & (uw <= 0.3 * np.maximum(body, 1e-12)) & (c1 < shift(c, 3)) & (spread >= 0.5 * a1)
    d["cs_hammer"] = _flag(ham, okc)
    b2 = np.abs(shift(c, 2) - shift(o, 2))
    ms = (shift(dn_.astype(float), 2).astype(bool) & (b2 >= 0.6 * a1) & (np.abs(c1 - o1) <= 0.3 * b2) & (np.maximum(o1, c1) < shift(c, 2))
          & up_ & (c > (shift(o, 2) + shift(c, 2)) / 2.0))
    d["cs_morning_star"] = _flag(ms, okc)
    u1, u2 = shift(up_.astype(float), 1).astype(bool), shift(up_.astype(float), 2).astype(bool)
    o2, c2 = shift(o, 2), shift(c, 2)
    tws = (up_ & u1 & u2 & (c > c1) & (c1 > c2) & (o >= o1) & (o <= c1) & (o1 >= o2) & (o1 <= c2) & (uw <= 0.3 * np.maximum(body, 1e-12))
           & (body >= 0.4 * a1) & (np.abs(c1 - o1) >= 0.4 * a1) & (np.abs(c2 - o2) >= 0.4 * a1))
    d["cs_3soldiers"] = _flag(tws, okc)
    cnt = sum(np.nan_to_num(d[k]) for k in ("cs_engulf_dt", "cs_hammer", "cs_morning_star", "cs_3soldiers"))
    d["cs_bull_count"] = np.where(okc, cnt, np.nan)
    d["cs_bull_r3"] = _recent(np.where(okc, (cnt > 0).astype(float), np.nan), 3)
    # --- V-dönüşü / fincan vekili (48 bar): yüksek -> dip (>= 4 ATR) -> toparlanma
    W = 48
    dep = np.full(N, np.nan)
    rec = np.full(N, np.nan)
    sl_ = np.full(N, np.nan)
    flag = np.full(N, np.nan)
    if N >= W:
        Wh = np.lib.stride_tricks.sliding_window_view(h, W)
        Wl = np.lib.stride_tricks.sliding_window_view(l, W)
        ih = np.argmax(Wh, axis=1)
        il = np.argmin(Wl, axis=1)
        Hh = Wh.max(axis=1)
        Ll = Wl.min(axis=1)
        cc = c[W - 1:]
        at = atr14[W - 1:]
        valid = (il > ih) & (Hh > Ll) & np.isfinite(at)
        dpt = np.where(valid, (Hh - Ll) / np.maximum(at, 1e-12), 0.0)
        rcv = np.where(valid, (cc - Ll) / np.maximum(Hh - Ll, 1e-12), 0.0)
        since = (W - 1 - il).astype(float)
        dep[W - 1:] = dpt
        rec[W - 1:] = rcv
        sl_[W - 1:] = np.where(valid, since, 0.0)
        flag[W - 1:] = (valid & (dpt >= 4.0) & (rcv >= 0.75) & (rcv <= 1.2) & (since >= 3) & (il - ih >= 4)).astype(float)
    d["v_depth_atr"] = dep
    d["v_recov"] = rec
    d["v_since_low"] = sl_
    d["v_flag"] = flag
    return d


# ----------------------------------------------------------------------------------------------- topluluk göstergeleri
@_export
def range_filter(c, per: int = 100, mult: float = 3.0) -> dict[str, np.ndarray]:
    """Range Filter (DonovanWall): filtre fiyat |dalga| * mult genişliğinden fazla hareket etmedikçe yerinde kalır. buy = yön yukarı + c > filtre + önceki durum short."""
    c = _f(c)
    N = len(c)
    ar = np.abs(c - shift(c, 1))
    rng = (_ema0(_ema0(np.nan_to_num(ar), per), per * 2 - 1) * mult).tolist()
    cl = c.tolist()
    filt = [float("nan")] * N
    dire = [0.0] * N
    buy = [0.0] * N
    sell = [0.0] * N
    f = cl[0] if N else 0.0
    up = dn = 0
    state = 0
    for i in range(N):
        x, r = cl[i], rng[i]
        fp = f
        if x > fp:
            f = fp if (x - r) < fp else (x - r)
        else:
            f = fp if (x + r) > fp else (x + r)
        if f > fp:
            up, dn = up + 1, 0
        elif f < fp:
            dn, up = dn + 1, 0
        xp = cl[i - 1] if i else x
        long_c = x > f and x > xp and up > 0
        short_c = x < f and x < xp and dn > 0
        prev = state
        if long_c:
            state = 1
        elif short_c:
            state = -1
        buy[i] = 1.0 if (state == 1 and prev == -1) else 0.0
        sell[i] = 1.0 if (state == -1 and prev == 1) else 0.0
        filt[i] = f
        dire[i] = 1.0 if up > 0 else (-1.0 if dn > 0 else 0.0)
    filt = np.asarray(filt)
    res = {"filt": filt, "dir": np.asarray(dire), "buy": np.asarray(buy), "sell": np.asarray(sell), "band": np.asarray(rng)}
    for k in ("filt", "dir", "buy", "sell", "band"):
        res[k][: per * 2] = np.nan
    return res


@_export
def coral_trend(c, sm: int = 21, cd: float = 0.4) -> np.ndarray:
    """LazyBear Coral Trend: altı kademeli EMA (c1 = 2/(di+1)); bfr = -cd^3*i6 + c3*i5 + c4*i4 + c5*i3."""
    di = (sm - 1) / 2.0 + 1.0
    c1 = 2.0 / (di + 1.0)
    c2 = 1.0 - c1
    c3 = 3.0 * (cd * cd + cd ** 3)
    c4 = -3.0 * (2.0 * cd * cd + cd + cd ** 3)
    c5 = 3.0 * cd + 1.0 + cd ** 3 + 3.0 * cd * cd
    x = _f(c)
    ii = []
    for _ in range(6):
        x = _lf(x, [c1], [1.0, -c2])
        ii.append(x)
    return -(cd ** 3) * ii[5] + c3 * ii[4] + c4 * ii[3] + c5 * ii[2]


@_export
def gaussian_filter(x, period: int = 144, poles: int = 4) -> np.ndarray:
    """Ehlers Gauss süzgeci (DonovanWall Gaussian Channel): 4 kutuplu IIR."""
    beta = (1.0 - np.cos(2.0 * np.pi / period)) / (2.0 ** (1.0 / poles) - 1.0)
    al = -beta + np.sqrt(beta * beta + 2.0 * beta)
    k = 1.0 - al
    a = [1.0, -4.0 * k, 6.0 * k ** 2, -4.0 * k ** 3, k ** 4]
    return _lf(x, [al ** 4], a)


def _ha_candles(o, h, l, c):
    hc = ((o + h + l + c) / 4.0)
    N = len(c)
    ho = np.empty(N)
    cl = hc.tolist()
    prev_o = (o[0] + c[0]) / 2.0 if N else 0.0
    hol = [0.0] * N
    for i in range(N):
        if i:
            prev_o = (hol[i - 1] + cl[i - 1]) / 2.0
        hol[i] = prev_o
    ho = np.asarray(hol)
    hh = np.maximum(h, np.maximum(ho, hc))
    hl = np.minimum(l, np.minimum(ho, hc))
    return ho, hh, hl, hc


@_export
def jurik_ma(x, length: int = 7, phase: float = 50.0, power: float = 2.0) -> np.ndarray:
    """Jurik MA'nın bilinen Pine yaklaşımı (everget): üç aşamalı uyarlamalı süzgeç."""
    x = _f(x)
    N = len(x)
    pr = 0.5 if phase < -100 else (2.5 if phase > 100 else phase / 100.0 + 1.5)
    beta = 0.45 * (length - 1) / (0.45 * (length - 1) + 2.0)
    al = beta ** power
    xl = x.tolist()
    out = [float("nan")] * N
    e0 = e1 = e2 = 0.0
    jma = xl[0] if N else 0.0
    e0 = jma
    for i in range(N):
        e0 = (1 - al) * xl[i] + al * e0
        e1 = (xl[i] - e0) * (1 - beta) + beta * e1
        e2 = (e0 + pr * e1 - jma) * (1 - al) ** 2 + al * al * e2
        jma = e2 + jma
        out[i] = jma
    return np.asarray(out)


def _qqe_line(rsima: list, dar: list) -> list:
    N = len(rsima)
    lb_p = sb_p = float("nan")
    rp = float("nan")
    trend = 1
    out = [float("nan")] * N
    for i in range(N):
        r, dd = rsima[i], dar[i]
        if r != r or dd != dd:
            continue
        ns, nl = r + dd, r - dd
        if lb_p == lb_p and rp > lb_p and r > lb_p:
            lb = max(lb_p, nl)
        else:
            lb = nl
        if sb_p == sb_p and rp < sb_p and r < sb_p:
            sb = min(sb_p, ns)
        else:
            sb = ns
        if sb_p == sb_p and rp <= sb_p and r > sb_p:
            trend = 1
        elif lb_p == lb_p and rp >= lb_p and r < lb_p:
            trend = -1
        out[i] = lb if trend == 1 else sb
        lb_p, sb_p, rp = lb, sb, r
    return out


@_export
def qqe_mod(c, rsi_n: int = 6, sf: int = 5, q1: float = 3.0, q2: float = 1.61, thresh: float = 3.0, bb_n: int = 50, bb_m: float = 0.35) -> dict[str, np.ndarray]:
    """QQE MOD (Mihkel00) yaklaşımı: iki QQE çizgisi (faktör 3 ve 1,61) + 1. çizginin Bollinger bandı. Mavi (long): RSI-MA-50 > üst bant VE 2. çizgi-50 > eşik."""
    c = _f(c)
    N = len(c)
    rsi = _rsi(c, rsi_n)
    rm = np.full(N, np.nan)
    f = _first_finite(rsi)
    rm[f:] = _ema0(rsi[f:], sf)
    atr_rsi = np.abs(shift(rm, 1) - rm)
    w = rsi_n * 2 - 1
    ma = np.full(N, np.nan)
    f2 = _first_finite(atr_rsi)
    ma[f2:] = _ema0(atr_rsi[f2:], w)
    da = np.full(N, np.nan)
    f3 = _first_finite(ma)
    da[f3:] = _ema0(ma[f3:], w)
    rml = rm.tolist()
    line1 = np.asarray(_qqe_line(rml, (da * q1).tolist()))
    line2 = np.asarray(_qqe_line(rml, (da * q2).tolist()))
    dev = line1 - 50.0
    basis = sma(dev, bb_n)
    sd = _roll_std(np.nan_to_num(dev), bb_n)
    sd = np.where(np.isfinite(basis), sd, np.nan)
    upper, lower = basis + bb_m * sd, basis - bb_m * sd
    ok = np.isfinite(upper) & np.isfinite(line2)
    blue = (rm - 50.0 > upper) & (line2 - 50.0 > thresh)
    red = (rm - 50.0 < lower) & (line2 - 50.0 < -thresh)
    bf = np.where(ok, blue.astype(float), np.nan)
    rf = np.where(ok, red.astype(float), np.nan)
    return {"hist": line2 - 50.0, "rm_vs_upper": rm - 50.0 - upper, "blue": bf, "red": rf,
            "blue_on": _flag(blue & ~np.r_[False, blue[:-1]], ok), "red_on": _flag(red & ~np.r_[False, red[:-1]], ok)}


@_export
def squeeze_lazybear(h, l, c, n: int = 20, bb_m: float = 2.0, kc_m: float = 1.5) -> dict[str, np.ndarray]:
    """LazyBear Squeeze Momentum: BB (SMA, popülasyon std) KC (SMA(c) +- SMA(TR)*1,5) içinde = sıkışık; momentum = linreg(c - ((HH+LL)/2 + SMA(c))/2, n)."""
    h, l, c = _f(h), _f(l), _f(c)
    basis = sma(c, n)
    sd = _roll_std(c, n)
    bbu, bbl = basis + bb_m * sd, basis - bb_m * sd
    rg = sma(_tr(h, l, c), n)
    kcu, kcl = basis + kc_m * rg, basis - kc_m * rg
    fin = np.isfinite(bbu) & np.isfinite(kcu)
    on = (bbl > kcl) & (bbu < kcu)
    mid = ((I.rolling_max(h, n) + I.rolling_min(l, n)) / 2.0 + basis) / 2.0
    val = I.linreg_band(c - mid, n)["value"]
    prev_on = np.r_[False, on[:-1]]
    return {"on": _flag(on, fin), "val": val, "release": _flag(prev_on & ~on, fin)}


@_export
def ssl_channel(h, l, c, n: int = 10) -> dict[str, np.ndarray]:
    """SSL kanalı: SMA(high,n)/SMA(low,n); Hlv = c > SMA(high) ? 1 : c < SMA(low) ? -1 : önceki."""
    h, l, c = _f(h), _f(l), _f(c)
    sh, sl = sma(h, n), sma(l, n)
    N = len(c)
    hl = [float("nan")] * N
    cur = 0
    for i in range(N):
        if sh[i] != sh[i]:
            continue
        if c[i] > sh[i]:
            cur = 1
        elif c[i] < sl[i]:
            cur = -1
        hl[i] = float(cur)
    hv = np.asarray(hl)
    prev = shift(hv, 1)
    return {"state": hv, "flip_up": _flag((hv == 1) & (prev == -1), np.isfinite(prev)), "flip_dn": _flag((hv == -1) & (prev == 1), np.isfinite(prev)),
            "hi": sh, "lo": sl}


@_export
def ut_bot(h, l, c, a: float = 1.0, per: int = 10) -> dict[str, np.ndarray]:
    """UT Bot Alerts: ATR(RMA) izleyen stop; buy = fiyat stopu yukarı keser."""
    h, l, c = _f(h), _f(l), _f(c)
    N = len(c)
    atr = _rma0(_tr(h, l, c), per)
    nl = (a * atr).tolist()
    cl = c.tolist()
    ts = [float("nan")] * N
    buy = [0.0] * N
    sell = [0.0] * N
    pos = [0.0] * N
    t_p = 0.0
    p_state = 0.0
    for i in range(N):
        x = cl[i]
        xp = cl[i - 1] if i else x
        loss = nl[i]
        if i == 0 or loss != loss:
            t_p = x
            continue
        if x > t_p and xp > t_p:
            t = max(t_p, x - loss)
        elif x < t_p and xp < t_p:
            t = min(t_p, x + loss)
        elif x > t_p:
            t = x - loss
        else:
            t = x + loss
        if xp <= t_p and x > t:
            buy[i] = 1.0
        if xp >= t_p and x < t:
            sell[i] = 1.0
        if xp < t_p and x > t_p:
            p_state = 1.0
        elif xp > t_p and x < t_p:
            p_state = -1.0
        pos[i] = p_state
        ts[i] = t
        t_p = t
    res = {"stop": np.asarray(ts), "buy": np.asarray(buy), "sell": np.asarray(sell), "pos": np.asarray(pos)}
    for v_ in res.values():
        v_[: per * 3] = np.nan
    return res


@_export
def wavetrend(h, l, c, n1: int = 9, n2: int = 12) -> dict[str, np.ndarray]:
    """LazyBear WaveTrend: ap = HLC3, esa = EMA(ap, n1), d = EMA(|ap - esa|, n1), ci = (ap - esa)/(0,015 d), wt1 = EMA(ci, n2), wt2 = SMA(wt1, 3)."""
    ap = (_f(h) + _f(l) + _f(c)) / 3.0
    esa = _ema0(ap, n1)
    d = _ema0(np.abs(ap - esa), n1)
    ci = _div(ap - esa, 0.015 * d)
    ci = np.where(np.isfinite(ci), ci, 0.0)
    wt1 = _ema0(ci, n2)
    wt2 = sma(wt1, 3)
    wt1[: n1 + n2 + 5] = np.nan
    wt2 = np.where(np.isfinite(wt1), wt2, np.nan)
    return {"wt1": wt1, "wt2": wt2}


def _feat_community(t, o, h, l, c, v, qv, atr14, bpd: int) -> dict[str, np.ndarray]:
    d: dict[str, np.ndarray] = {}
    N = len(c)
    # --- Range Filter
    rf = range_filter(c, 100, 3.0)
    d["rf_dist"] = _div(c - rf["filt"], c) * 100.0
    d["rf_dir"] = rf["dir"]
    d["rf_band"] = _div(rf["band"], c) * 100.0
    d["rf_buy"] = rf["buy"]
    d["rf_sell"] = rf["sell"]
    d["rf_buy_r6"] = _recent(rf["buy"], 6)
    # --- Coral Trend
    co = coral_trend(c)
    co[:80] = np.nan
    d["coral_dist"] = _div(c - co, c) * 100.0
    d["coral_slope"] = _div(co - shift(co, 1), c) * 100.0
    cu = co > shift(co, 1)
    okc = np.isfinite(shift(co, 1))
    d["coral_up"] = _flag(cu, okc)
    d["coral_flip_up3"] = _recent(_flag(cu & ~np.r_[False, cu[:-1]], np.isfinite(shift(co, 2))), 3)
    # --- Gaussian Channel (144, 4 kutup, 1,414 ATR-benzeri)
    gf = gaussian_filter(c, 144, 4)
    gt = gaussian_filter(_tr(h, l, c), 144, 4)
    gf[:200] = np.nan
    up, lo = gf + 1.414 * gt, gf - 1.414 * gt
    d["gc_pos"] = _div(c - gf, 1.414 * gt)
    d["gc_slope"] = _div(gf - shift(gf, 1), c) * 100.0
    d["gc_width"] = _div(up - lo, c) * 100.0
    d["gc_above_upper"] = _flag(c > up, np.isfinite(up))
    d["gc_cross_up"] = _recent(_cross_up(c, up), 3)
    # --- Heikin-Ashi RSI + HA mum renk serileri
    ho, hh, hl, hc = _ha_candles(o, h, l, c)
    rc, ro = _rsi(hc, 14), _rsi(ho, 14)
    d["harsi"] = rc - 50.0
    d["harsi_body"] = rc - ro
    bd = rc - ro
    d["harsi_flip_up3"] = _recent(_cross_up(bd, np.zeros(N)), 3)
    green = hc > ho
    d["ha_green_run"] = np.where(np.isfinite(shift(hc, 1)), np.minimum(_run(green), 30).astype(float), np.nan)
    d["ha_red_run"] = np.where(np.isfinite(shift(hc, 1)), np.minimum(_run(~green), 30).astype(float), np.nan)
    d["ha_flip_up"] = _flag(green & ~np.r_[False, green[:-1]], np.isfinite(shift(hc, 1)))
    nowick = green & (np.abs(hl - ho) <= 1e-9 * np.maximum(ho, 1e-12))
    d["ha_nolow_wick_up"] = _flag(nowick, np.isfinite(shift(hc, 1)))
    d["ha_body_atr"] = _div(hc - ho, atr14)
    # --- Jurik MA (yaklaşık)
    jm = jurik_ma(c, 7, 50.0, 2.0)
    jm[:50] = np.nan
    d["jma_dist"] = _div(c - jm, c) * 100.0
    d["jma_slope"] = _div(jm - shift(jm, 1), c) * 100.0
    # --- QQE MOD
    qm = qqe_mod(c)
    d["qqe_hist"] = qm["hist"]
    d["qqe_rm_vs_upper"] = qm["rm_vs_upper"]
    d["qqe_blue"] = qm["blue"]
    d["qqe_blue_on"] = qm["blue_on"]
    d["qqe_blue_on_r3"] = _recent(qm["blue_on"], 3)
    d["qqe_red_on"] = qm["red_on"]
    # --- Squeeze Momentum (LazyBear)
    sq = squeeze_lazybear(h, l, c)
    val = sq["val"]
    d["sqzm_on"] = sq["on"]
    d["sqzm_val"] = _div(val, c) * 100.0
    d["sqzm_chg"] = _div(val - shift(val, 1), c) * 100.0
    d["sqzm_rising_pos"] = _flag((val > 0) & (val > shift(val, 1)), np.isfinite(shift(val, 1)))
    d["sqzm_release"] = sq["release"]
    d["sqzm_rel_up"] = _flag((sq["release"] == 1.0) & (val > 0), np.isfinite(val) & np.isfinite(sq["release"]))
    d["sqzm_rel_dn"] = _flag((sq["release"] == 1.0) & (val < 0), np.isfinite(val) & np.isfinite(sq["release"]))
    d["sqzm_rel_up_r3"] = _recent(d["sqzm_rel_up"], 3)
    # --- SSL hibrit
    ss = ssl_channel(h, l, c, 10)
    hma60 = I.hull_ma(c, 60)
    d["ssl_state"] = ss["state"]
    d["ssl_flip_up"] = ss["flip_up"]
    d["ssl_flip_up_r3"] = _recent(ss["flip_up"], 3)
    d["ssl_flip_dn"] = ss["flip_dn"]
    d["ssl_in_channel"] = _flag((c <= ss["hi"]) & (c >= ss["lo"]), np.isfinite(ss["hi"]))
    d["ssl_base_dist"] = _div(c - hma60, c) * 100.0
    d["ssl_base_slope"] = _div(hma60 - shift(hma60, 1), c) * 100.0
    # --- TDI
    rs13 = _rsi(c, 13)
    pr, sg, bs = sma(rs13, 2), sma(rs13, 7), sma(rs13, 34)
    sdv = _roll_std(rs13, 34)
    bu, bl = bs + 1.6185 * sdv, bs - 1.6185 * sdv
    d["tdi_p_s"] = pr - sg
    d["tdi_p_base"] = pr - bs
    d["tdi_band_pos"] = _div(pr - bl, bu - bl)
    d["tdi_cross_up"] = _cross_up(pr, sg)
    d["tdi_cross_up_r3"] = _recent(d["tdi_cross_up"], 3)
    # --- Tillson T3 (5, 0,7)
    a_ = 0.7
    ee = c
    es = []
    for _ in range(6):
        ee = _ema0(ee, 5)
        es.append(ee)
    t3 = (-(a_ ** 3)) * es[5] + (3 * a_ ** 2 + 3 * a_ ** 3) * es[4] + (-6 * a_ ** 2 - 3 * a_ - 3 * a_ ** 3) * es[3] + (1 + 3 * a_ + a_ ** 3 + 3 * a_ ** 2) * es[2]
    t3[:60] = np.nan
    d["t3_dist"] = _div(c - t3, c) * 100.0
    d["t3_slope"] = _div(t3 - shift(t3, 1), c) * 100.0
    tu = t3 > shift(t3, 1)
    d["t3_flip_up3"] = _recent(_flag(tu & ~np.r_[False, tu[:-1]], np.isfinite(shift(t3, 2))), 3)
    # --- UT Bot
    ub = ut_bot(h, l, c, 1.0, 10)
    d["utb_dist"] = _div(c - ub["stop"], c) * 100.0
    d["utb_state"] = ub["pos"]
    d["utb_buy"] = ub["buy"]
    d["utb_sell"] = ub["sell"]
    d["utb_buy_r6"] = _recent(ub["buy"], 6)
    # --- WaveTrend + VuManChu Cipher B
    wt = wavetrend(h, l, c, 9, 12)
    w1, w2 = wt["wt1"], wt["wt2"]
    cu_ = _cross_up(w1, w2)
    d["wt1"], d["wt2"] = w1, w2
    d["wt_diff"] = w1 - w2
    d["wt_cross_up"] = cu_
    d["wt_cross_up_os53"] = _flag((cu_ == 1.0) & (w2 <= -53.0), np.isfinite(cu_) & np.isfinite(w2))
    d["wt_cross_up_os60"] = _flag((cu_ == 1.0) & (w2 <= -60.0), np.isfinite(cu_) & np.isfinite(w2))
    d["wt_cross_up_os53_r3"] = _recent(d["wt_cross_up_os53"], 3)
    d["wt_cross_dn_ob53"] = _flag((_cross_dn(w1, w2) == 1.0) & (w2 >= 53.0), np.isfinite(cu_) & np.isfinite(w2))
    mf = sma(_nz(_div(c - o, h - l)) * 150.0, 60) - 2.5
    d["vmc_mf"] = mf
    d["vmc_mf_chg3"] = mf - shift(mf, 3)
    d["vmc_green_mf"] = _flag((d["wt_cross_up_os53"] == 1.0) & (mf > shift(mf, 3)), np.isfinite(mf) & np.isfinite(shift(mf, 3)) & np.isfinite(d["wt_cross_up_os53"]))
    # --- Waddah Attar Explosion (150, 20, 40, BB 20/2, ölü bölge 3,7*RMA(TR,100))
    macd = _ema0(c, 20) - _ema0(c, 40)
    t1 = (macd - shift(macd, 1)) * 150.0
    e1 = 4.0 * _roll_std(c, 20)
    dead = _rma0(_tr(h, l, c), 100) * 3.7
    tup = np.where(t1 >= 0, t1, 0.0)
    ok = np.isfinite(t1) & np.isfinite(e1)
    expl = (tup > e1) & (tup > dead)
    d["wae_ratio"] = np.clip(_div(tup, np.maximum(e1, dead)), 0, 10)
    d["wae_expl_up"] = _flag(expl, ok)
    d["wae_expl_up_on"] = _flag(expl & ~np.r_[False, expl[:-1]], ok)
    d["wae_expl_up_r3"] = _recent(d["wae_expl_up_on"], 3)
    return d


# ----------------------------------------------------------------------------------------------- ileri (Ehlers vb.)
def _mama(src, fast: float = 0.5, slow: float = 0.05):
    x = src.tolist()
    N = len(x)
    sp = [0.0] * N
    dt = [0.0] * N
    q1 = [0.0] * N
    i1 = [0.0] * N
    i2 = [0.0] * N
    q2 = [0.0] * N
    re = [0.0] * N
    im = [0.0] * N
    per = [0.0] * N
    ph = [0.0] * N
    mama = [float("nan")] * N
    fama = [float("nan")] * N
    m_p = f_p = x[0] if N else 0.0

    def g(a, i, k):
        return a[i - k] if i - k >= 0 else 0.0
    for i in range(N):
        sp[i] = (4 * x[i] + 3 * g(x, i, 1) + 2 * g(x, i, 2) + g(x, i, 3)) / 10.0 if i >= 3 else x[i]
        k = 0.075 * g(per, i, 1) + 0.54
        dt[i] = (0.0962 * sp[i] + 0.5769 * g(sp, i, 2) - 0.5769 * g(sp, i, 4) - 0.0962 * g(sp, i, 6)) * k
        q1[i] = (0.0962 * dt[i] + 0.5769 * g(dt, i, 2) - 0.5769 * g(dt, i, 4) - 0.0962 * g(dt, i, 6)) * k
        i1[i] = g(dt, i, 3)
        ji = (0.0962 * i1[i] + 0.5769 * g(i1, i, 2) - 0.5769 * g(i1, i, 4) - 0.0962 * g(i1, i, 6)) * k
        jq = (0.0962 * q1[i] + 0.5769 * g(q1, i, 2) - 0.5769 * g(q1, i, 4) - 0.0962 * g(q1, i, 6)) * k
        a2 = i1[i] - jq
        b2 = q1[i] + ji
        i2[i] = 0.2 * a2 + 0.8 * g(i2, i, 1)
        q2[i] = 0.2 * b2 + 0.8 * g(q2, i, 1)
        r_ = i2[i] * g(i2, i, 1) + q2[i] * g(q2, i, 1)
        m_ = i2[i] * g(q2, i, 1) - q2[i] * g(i2, i, 1)
        re[i] = 0.2 * r_ + 0.8 * g(re, i, 1)
        im[i] = 0.2 * m_ + 0.8 * g(im, i, 1)
        if im[i] != 0 and re[i] != 0:
            ang = float(np.degrees(np.arctan(im[i] / re[i])))
            p = 360.0 / ang if ang != 0 else 0.0
        else:
            p = 0.0
        pp = g(per, i, 1)
        if p > 1.5 * pp:
            p = 1.5 * pp
        if p < 0.67 * pp:
            p = 0.67 * pp
        p = min(max(p, 6.0), 50.0)
        per[i] = 0.2 * p + 0.8 * pp
        ph[i] = np.degrees(np.arctan(q1[i] / i1[i])) if i1[i] != 0 else 0.0
        dp = g(ph, i, 1) - ph[i]
        if dp < 1.0:
            dp = 1.0
        al = max(fast / dp, slow)
        m_p = al * x[i] + (1 - al) * m_p
        f_p = 0.5 * al * m_p + (1 - 0.5 * al) * f_p
        mama[i], fama[i] = m_p, f_p
    return np.asarray(mama), np.asarray(fama)


def _frama(c, h, l, n: int = 16):
    half = n // 2
    hh8, ll8 = I.rolling_max(h, half), I.rolling_min(l, half)
    hh16, ll16 = I.rolling_max(h, n), I.rolling_min(l, n)
    n1 = (hh8 - ll8) / half
    n2 = (shift(hh8, half) - shift(ll8, half)) / half
    n3 = (hh16 - ll16) / n
    with np.errstate(invalid="ignore", divide="ignore"):
        dd = (np.log(n1 + n2) - np.log(n3)) / np.log(2.0)
    al = np.clip(np.exp(-4.6 * (dd - 1.0)), 0.01, 1.0)
    alist = al.tolist()
    xl = c.tolist()
    out = [float("nan")] * len(xl)
    f = xl[0] if xl else 0.0
    for i in range(len(xl)):
        a = alist[i]
        if a != a:
            a = 1.0
        f = a * xl[i] + (1 - a) * f
        out[i] = f
    return np.asarray(out), dd


def _vidya(c, n: int = 14, cmo_n: int = 9):
    cm = np.abs(I.cmo(c, cmo_n)) / 100.0
    al = 2.0 / (n + 1.0)
    xl = c.tolist()
    cl = cm.tolist()
    out = [float("nan")] * len(xl)
    v = xl[0] if xl else 0.0
    for i in range(len(xl)):
        k = al * (cl[i] if cl[i] == cl[i] else 0.0)
        v = k * xl[i] + (1 - k) * v
        out[i] = v
    return np.asarray(out)


def _schaff(c, length: int = 10, fast: int = 23, slow: int = 50, fac: float = 0.5):
    """Schaff Trend Cycle (Pine): MACD -> stokastik (length) -> fac ile yumuşat -> ikinci stokastik -> yumuşat."""
    def _stoch_smooth(x):
        v1 = I.rolling_min(x, length)
        v2 = I.rolling_max(x, length) - v1
        fr = ((x - v1) / np.where(v2 > 0, v2, np.nan) * 100.0).tolist()
        rdy = np.isfinite(v2).tolist()
        out = [float("nan")] * len(fr)
        prev_f = 0.0
        prev_s = float("nan")
        for i in range(len(fr)):
            if not rdy[i]:
                continue
            xx = fr[i] if fr[i] == fr[i] else prev_f
            prev_f = xx
            prev_s = xx if prev_s != prev_s else prev_s + fac * (xx - prev_s)
            out[i] = prev_s
        return np.asarray(out)
    macd = _ema0(c, fast) - _ema0(c, slow)
    out = _stoch_smooth(_stoch_smooth(macd))
    out[: slow + 2 * length] = np.nan
    return out


def _cyber_cycle(c, alpha: float = 0.07):
    x = c.tolist()
    N = len(x)
    sm = [0.0] * N
    cy = [0.0] * N
    for i in range(N):
        sm[i] = (x[i] + 2 * x[i - 1] + 2 * x[i - 2] + x[i - 3]) / 6.0 if i >= 3 else x[i]
        if i < 7:
            cy[i] = (x[i] - 2 * x[i - 1] + x[i - 2]) / 4.0 if i >= 2 else 0.0
        else:
            cy[i] = (1 - 0.5 * alpha) ** 2 * (sm[i] - 2 * sm[i - 1] + sm[i - 2]) + 2 * (1 - alpha) * cy[i - 1] - (1 - alpha) ** 2 * cy[i - 2]
    out = np.asarray(cy)
    out[:30] = np.nan
    return out


def _itrend(c, alpha: float = 0.07):
    x = c.tolist()
    N = len(x)
    it = [0.0] * N
    for i in range(N):
        if i < 7:
            it[i] = (x[i] + 2 * x[i - 1] + x[i - 2]) / 4.0 if i >= 2 else x[i]
        else:
            it[i] = ((alpha - alpha * alpha / 4.0) * x[i] + 0.5 * alpha * alpha * x[i - 1] - (alpha - 0.75 * alpha * alpha) * x[i - 2]
                     + 2 * (1 - alpha) * it[i - 1] - (1 - alpha) ** 2 * it[i - 2])
    out = np.asarray(it)
    out[:30] = np.nan
    return out


def _feat_advanced(t, o, h, l, c, v, qv, atr14, bpd: int) -> dict[str, np.ndarray]:
    d: dict[str, np.ndarray] = {}
    N = len(c)
    tr = _tr(h, l, c)
    # --- Center of Gravity (n=10)
    n = 10
    num = I._fir(c, np.arange(1, n + 1, dtype=float))
    cg = -_div(num, rsum(c, n)) + (n + 1) / 2.0
    d["cog"] = cg
    d["cog_chg"] = cg - shift(cg, 1)
    d["cog_cross_up"] = _cross_up(cg, shift(cg, 1))
    # --- VHF (28), Kaufman ER (10, 30)
    ac = np.abs(c - shift(c, 1))
    d["vhf28"] = _div(I.rolling_max(c, 28) - I.rolling_min(c, 28), rsum(ac, 28))
    d["er10"] = _div(np.abs(c - shift(c, 10)), rsum(ac, 10))
    d["er30"] = _div(np.abs(c - shift(c, 30)), rsum(ac, 30))
    # --- Ehlers Instantaneous Trendline
    it = _itrend(c)
    d["itrend_dist"] = _div(c - it, c) * 100.0
    d["itrend_slope"] = _div(it - shift(it, 1), c) * 100.0
    d["itrend_trig_cross_up"] = _cross_up(2.0 * it - shift(it, 2), it)
    # --- Elder Impulse
    e13 = _ema0(c, 13)
    macd = _ema0(c, 12) - _ema0(c, 26)
    hist = macd - _ema0(macd, 9)
    g_ = (e13 > shift(e13, 1)) & (hist > shift(hist, 1))
    r_ = (e13 < shift(e13, 1)) & (hist < shift(hist, 1))
    okh = np.isfinite(shift(hist, 1))
    imp = np.where(okh, g_.astype(float) - r_.astype(float), np.nan)
    d["impulse"] = imp
    d["impulse_green_run"] = np.where(okh, np.minimum(_run(g_), 30).astype(float), np.nan)
    d["impulse_flip_green"] = _flag(g_ & ~np.r_[False, g_[:-1]], okh)
    d["osma_pct"] = _div(hist, c) * 100.0
    d["osma_chg"] = _div(hist - shift(hist, 1), c) * 100.0
    m2 = _ema0(c, 6) - _ema0(c, 13)
    h2 = m2 - _ema0(m2, 5)
    d["osma_fast_pct"] = _div(h2, c) * 100.0
    # --- RMI (14, momentum 5)
    mom = c - shift(c, 5)
    up = _rma0(np.nan_to_num(np.maximum(mom, 0.0)), 14)
    dn = _rma0(np.nan_to_num(np.maximum(-mom, 0.0)), 14)
    rmi = 100.0 * _div(up, up + dn)
    rmi[:20] = np.nan
    d["rmi"] = rmi
    d["rmi_chg3"] = rmi - shift(rmi, 3)
    # --- Kase DevStop (yaklaşık): dev = ort(TR2) + 2,2*std(TR2) (30); uzun stop = max(h, h[-1]) - dev
    c1 = shift(c, 1)
    tr2 = np.maximum(h, c1) - np.minimum(l, c1)
    mean30 = sma(tr2, 30)
    sd30 = _roll_std(tr2, 30)
    stop_l = np.maximum(h, shift(h, 1)) - (mean30 + 2.2 * sd30)
    d["kase_dist"] = _div(c - stop_l, c) * 100.0
    d["kase_hit"] = _flag(c < shift(stop_l, 1), np.isfinite(shift(stop_l, 1)))
    # --- Laguerre RSI
    lr = laguerre_rsi(c, 0.5)
    lr[:20] = np.nan
    d["lrsi"] = lr
    d["lrsi_cross_up20"] = _cross_up(lr, np.full(N, 0.2))
    d["lrsi_cross_up20_r3"] = _recent(d["lrsi_cross_up20"], 3)
    d["lrsi_chg"] = lr - shift(lr, 1)
    # --- MAMA / FAMA
    ma_, fa_ = _mama(c)
    ma_[:100] = np.nan
    fa_[:100] = np.nan
    d["mama_dist"] = _div(c - ma_, c) * 100.0
    d["mama_fama"] = _div(ma_ - fa_, c) * 100.0
    d["mama_cross_up"] = _cross_up(ma_, fa_)
    # --- Pretty Good Oscillator, Psikolojik Çizgi, QStick
    d["pgo14"] = _div(c - sma(c, 14), _ema0(tr, 14))
    d["psy12"] = rsum((c > c1).astype(float), 12) / 12.0 * 100.0
    d["qstick8"] = _div(sma(c - o, 8), c) * 100.0
    # --- R-kare (14) ve işaretli
    for nn in (14,):
        out_r = np.full(N, np.nan)
        out_s = np.full(N, np.nan)
        if N >= nn:
            xc = np.arange(nn) - (nn - 1) / 2.0
            Wd = np.lib.stride_tricks.sliding_window_view(c, nn)
            dev = Wd - Wd.mean(axis=1, keepdims=True)
            sxy = dev @ xc
            syy = (dev ** 2).sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                r2 = np.where(syy > 0, sxy * sxy / (syy * (xc ** 2).sum()), 0.0)
            out_r[nn - 1:] = r2
            out_s[nn - 1:] = np.sign(sxy) * r2
        d["r2_%d" % nn] = out_r
        d["r2s_%d" % nn] = out_s
    # --- Random Walk Index (n=2..8)
    rwh = np.full(N, 0.0)
    rwl = np.full(N, 0.0)
    for nn in range(2, 9):
        a_n = sma(tr, nn)
        den = a_n * np.sqrt(nn)
        rwh = np.maximum(rwh, np.nan_to_num(_div(h - shift(l, nn), den)))
        rwl = np.maximum(rwl, np.nan_to_num(_div(shift(h, nn) - l, den)))
    okr = np.isfinite(shift(l, 8)) & np.isfinite(sma(tr, 8))
    d["rwi_hi"] = np.where(okr, rwh, np.nan)
    d["rwi_lo"] = np.where(okr, rwl, np.nan)
    d["rwi_diff"] = d["rwi_hi"] - d["rwi_lo"]
    # --- Schaff Trend Cycle
    stc = _schaff(c)
    d["stc"] = stc
    d["stc_chg"] = stc - shift(stc, 1)
    d["stc_cross_up25"] = _cross_up(stc, np.full(N, 25.0))
    d["stc_cross_up25_r3"] = _recent(d["stc_cross_up25"], 3)
    # --- Cyber Cycle
    cy = _cyber_cycle(c)
    d["cyber"] = _div(cy, c) * 100.0
    d["cyber_chg"] = _div(cy - shift(cy, 1), c) * 100.0
    d["cyber_cross_up"] = _cross_up(cy, shift(cy, 1))
    # --- STARC bandları (SMA6 +- 2 ATR15)
    mid = sma(c, 6)
    a15 = _atr(h, l, c, 15)
    d["starc_pos"] = _div(c - mid, 2.0 * a15)
    d["starc_width"] = _div(4.0 * a15, mid) * 100.0
    d["starc_break_up"] = _flag(c > mid + 2.0 * a15, np.isfinite(a15) & np.isfinite(mid))
    d["starc_break_dn"] = _flag(c < mid - 2.0 * a15, np.isfinite(a15) & np.isfinite(mid))
    # --- Twiggs Money Flow (21)
    trh, trl = np.maximum(h, c1), np.minimum(l, c1)
    ad = v * _nz(_div((c - trl) - (trh - c), trh - trl))
    ad[0] = 0.0
    tmf = _div(_rma0(ad, 21), _rma0(v, 21))
    tmf[:30] = np.nan
    d["tmf21"] = tmf
    d["tmf_chg5"] = tmf - shift(tmf, 5)
    # --- DeMarker (14)
    dmx = np.maximum(h - shift(h, 1), 0.0)
    dmn = np.maximum(shift(l, 1) - l, 0.0)
    dem = _div(sma(dmx, 14), sma(dmx, 14) + sma(dmn, 14))
    d["dem14"] = dem
    d["dem_cross_up30"] = _cross_up(dem, np.full(N, 0.3))
    # --- FRAMA (16)
    fr, dim = _frama(c, h, l, 16)
    fr[:40] = np.nan
    d["frama_dist"] = _div(c - fr, c) * 100.0
    d["frama_slope"] = _div(fr - shift(fr, 1), c) * 100.0
    d["frama_dim"] = dim
    # --- Bill Williams MFI (4 durum)
    mfi = _div(h - l, v)
    dm_ = mfi > shift(mfi, 1)
    dv_ = v > shift(v, 1)
    okm = np.isfinite(mfi) & np.isfinite(shift(mfi, 1))
    d["bwmfi_green"] = _flag(dm_ & dv_, okm)
    d["bwmfi_fade"] = _flag(~dm_ & ~dv_, okm)
    d["bwmfi_fake"] = _flag(dm_ & ~dv_, okm)
    d["bwmfi_squat"] = _flag(~dm_ & dv_, okm)
    d["bwmfi_squat_r3"] = _recent(d["bwmfi_squat"], 3)
    # --- VIDYA
    vd = _vidya(c, 14, 9)
    vd[:30] = np.nan
    d["vidya_dist"] = _div(c - vd, c) * 100.0
    d["vidya_slope"] = _div(vd - shift(vd, 1), c) * 100.0
    return d


# ----------------------------------------------------------------------------------------------- toplu hesap
@_export
def compute_all(arr: np.ndarray, tf: str = "5m", drop: tuple = ()) -> tuple[list[str], np.ndarray]:
    """v2 kütüphanesinin TÜM özellikleri: (isimler `<tf>.x2.<ad>`, float32 matris n x F). `arr` pattern_study düzeninde (7 ya da 9 kolon); i. satır yalnız <= i barlarına bağlıdır.
    `tf` in {"1m","5m","15m"}: günlük pencere uzunluğu (RVOL, 7g/30g, ADR) ve bar süresini (ORB) belirler. Taker kolonları yoksa Hacim-Delta sütunları NaN. `drop`: hesaplanmayacak aile adları (ör. ("x2_day",) -> gün/seans özellikleri 1m/15m'de atlanır)."""
    t = arr[:, P.COL_OT].astype(np.int64)
    o, h, l, c = (arr[:, k].astype(float) for k in (P.COL_O, P.COL_H, P.COL_L, P.COL_C))
    v = _nz(arr[:, P.COL_V])
    qv = _nz(arr[:, P.COL_QV])
    has_tk = arr.shape[1] > P.COL_TBQ
    tbq = _nz(arr[:, P.COL_TBQ]) if has_tk else np.zeros(len(c))
    N = len(c)
    bpd = BARS_PER_DAY[tf]
    bar_ms = BAR_MS[tf]
    atr14 = _atr(h, l, c, 14)
    F: dict[str, np.ndarray] = {}

    def put(fam, dd):
        for kk, vv in dd.items():
            F["x2." + kk] = vv
            FAMILY["x2." + kk] = fam

    put("x2_basic", _feat_basic(t, o, h, l, c, v, qv, tbq, has_tk, bpd, atr14))
    ce = chandelier(h, l, c, 22, 3.0)
    vs = volatility_stop(h, l, c, 20, 2.0)
    put("x2_basic", {"ce_state": ce["dir"], "ce_dist": _div(c - ce["stop"], c) * 100.0, "ce_flip_up": ce["flip_up"], "ce_flip_up_r3": _recent(ce["flip_up"], 3),
                     "ce_flip_dn": ce["flip_dn"], "vs_state": vs["dir"], "vs_dist": _div(c - vs["stop"], c) * 100.0, "vs_flip_up_r3": _recent(vs["flip_up"], 3),
                     "vs_flip_dn_r3": _recent(vs["flip_dn"], 3)})
    if "x2_day" not in drop:
        put("x2_day", _day_feats(t, o, h, l, c, v, atr14, bar_ms))
        put("x2_day", _session_feats(t, bar_ms))
    put("x2_pivot", _feat_pivot(o, h, l, c, v, atr14))
    put("x2_smc", _feat_smc(o, h, l, c, v, atr14))
    put("x2_pattern", _feat_patterns(o, h, l, c, v, atr14))
    put("x2_comm", _feat_community(t, o, h, l, c, v, qv, atr14, bpd))
    put("x2_adv", _feat_advanced(t, o, h, l, c, v, qv, atr14, bpd))
    names = [f"{tf}.{k}" for k in F]
    X = np.column_stack([np.asarray(F[k], dtype=float) for k in F])
    X[~np.isfinite(X) | (np.abs(X) > 1e9)] = np.nan
    return names, X.astype(np.float32)


def feature_names(tf: str = "5m", drop: tuple = ()) -> list[str]:
    """`compute_all`'ın üreteceği sütun adları (sahte dizi üzerinden; FAMILY'yi de doldurur)."""
    n = 900
    arr = np.zeros((n, 9))
    rng = np.random.default_rng(0)
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    arr[:, 0] = 1_790_000_000_000 - (1_790_000_000_000 % DAY_MS) + np.arange(n) * BAR_MS[tf]
    arr[:, 1] = np.r_[c[0], c[:-1]]
    arr[:, 4] = c
    arr[:, 2] = np.maximum(arr[:, 1], c) * 1.001
    arr[:, 3] = np.minimum(arr[:, 1], c) * 0.999
    arr[:, 5] = 100.0 + rng.random(n) * 50
    arr[:, 6] = arr[:, 5] * c
    arr[:, 7] = arr[:, 5] * 0.5
    arr[:, 8] = arr[:, 6] * 0.5
    return compute_all(arr, tf, drop)[0]
