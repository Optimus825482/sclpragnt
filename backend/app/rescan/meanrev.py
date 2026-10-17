"""Ortalamaya dönüş + PASİF (limit) icra çalışması için SAF yardımcılar (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ, DB'ye dokunmaz).

Sözleşme (tests/test_meanrev.py):
  * 5 dk özellikleri/tetikleri NEDENSELDİR: satır i = açılışı ot[i] olan mum; değer yalnız bar ≤ i verisiyle hesaplanır, karar anı t_dec(i) = ot[i] + 5 dk.
    Kesilmiş girdiyle yeniden hesap aynı satırı verir. NaN girdi → NaN çıktı (eksik pencere asla tetik üretmez).
  * Limit alış dolumu: karar anından sonraki 1 dk barlarda (sütun 0 = t_dec'te AÇILAN bar) İLK bar k: LOW ≤ limit (dokunma, iyimser) ya da dakika VWAP ≤ limit (katı).
    Dolum fiyatı = limit (açılış daha iyi olsa bile — kötümser).
  * Çıkış (dolum barı = sütun 0): kâr al LİMİT satış entry×(1+T): HIGH ≥ seviye (ya da katı: VWAP ≥ seviye), DOLUM BARINDA değerlendirilmez (sıra bilinmez);
    stop: LOW ≤ entry×(1−SL) dolum barı DÂHİL (kötümser); aynı barda ikisi → STOP. Stop dolumu min(stop, bar açılışı)×(1−kayma), zaman stopu son barın kapanışı×(1−kayma).
    `exit_sim.simulate` ile (dolum barında TP hariç tutulduğunda) aynı sonucu verir (test).
  * Net = X·(1−f_çıkış) / (E·(1+f_giriş)) − 1; ücretler yüzde olarak parametre (maker/taker ayrımı çağırandadır).
"""
from __future__ import annotations

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

BAR5_MS = 300_000
BAR1_MS = 60_000

R_TP, R_SL, R_TIME = 0, 1, 2
REASON_NAMES = ("TP", "SL", "zaman")


# ------------------------------------------------------------------------------------------------ pencereli temel yardımcılar
def lag(x: np.ndarray, k: int) -> np.ndarray:
    """x[i−k]; ilk k satır NaN (son eksen zaman olmak zorunda değil: 1B)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if k == 0:
        return x.copy()
    if k < len(x):
        out[k:] = x[:-k]
    return out


def _roll(x: np.ndarray, w: int, fn) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        out[w - 1:] = fn(sliding_window_view(x, w), axis=1)
    return out


def roll_mean(x: np.ndarray, w: int) -> np.ndarray:
    """Son w değerin ortalaması (güncel dahil); pencerede NaN varsa NaN."""
    return _roll(x, w, np.mean)


def roll_std(x: np.ndarray, w: int) -> np.ndarray:
    """Popülasyon std'si (ddof=0, TradingView ta.stdev ile aynı); pencerede NaN varsa NaN."""
    return _roll(x, w, np.std)


def roll_sum(x: np.ndarray, w: int) -> np.ndarray:
    return _roll(x, w, np.sum)


def roll_min_prior(x: np.ndarray, w: int) -> np.ndarray:
    """out[i] = min(x[i−w .. i−1]) — güncel bar HARİÇ (önceki w bar). İlk w satır NaN."""
    m = _roll(x, w, np.min)
    out = np.full(len(m), np.nan)
    out[1:] = m[:-1]
    return out


# ------------------------------------------------------------------------------------------------ göstergeler
def bollinger_lower(c: np.ndarray, n: int = 20, k: float = 2.0) -> np.ndarray:
    """Alt bant: SMA(n) − k·std(n, ddof=0); güncel bar dahil."""
    return roll_mean(c, n) - k * roll_std(c, n)


def mfi(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray, n: int = 14) -> np.ndarray:
    """Money Flow Index: tp=(H+L+C)/3, ham akış=tp·hacim, tp artışı → pozitif / düşüşü → negatif (eşitlik sayılmaz); MFI = 100·pos/(pos+neg) (n bar toplamı).
    İlk n bar NaN; pos+neg=0 → NaN."""
    h = np.asarray(h, dtype=float); l = np.asarray(l, dtype=float); c = np.asarray(c, dtype=float); v = np.asarray(v, dtype=float)
    tp = (h + l + c) / 3.0
    d = tp - lag(tp, 1)
    mf = tp * v
    pos = np.where(np.isfinite(d) & np.isfinite(mf), np.where(d > 0, mf, 0.0), np.nan)
    neg = np.where(np.isfinite(d) & np.isfinite(mf), np.where(d < 0, mf, 0.0), np.nan)
    ps, ns = roll_sum(pos, n), roll_sum(neg, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = 100.0 * ps / (ps + ns)
    out[~np.isfinite(out)] = np.nan
    return out


def atr_pct(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    """ATR(n)/kapanış × 100 (basit ortalama TR; TR[0] = H−L). Güncel bar dahil (exit_sim.atr_pct_at ile aynı pencere)."""
    h = np.asarray(h, dtype=float); l = np.asarray(l, dtype=float); c = np.asarray(c, dtype=float)
    pc = np.concatenate([[c[0]], c[:-1]]) if len(c) else c
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    with np.errstate(invalid="ignore", divide="ignore"):
        return roll_mean(tr, n) / c * 100.0


def simple_ret(c: np.ndarray, k: int) -> np.ndarray:
    """c[i]/c[i−k] − 1."""
    c = np.asarray(c, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = c / lag(c, k) - 1.0
    r[~np.isfinite(r)] = np.nan
    return r


def sweep_trigger(l: np.ndarray, c: np.ndarray, w: int = 288, m: int = 3) -> np.ndarray:
    """Likidite süpürmesi: j barı önceki w barın (24 sa) en düşüğünü AŞAĞI keser (yeni dip) ve j..j+m içinde bir bar önceki dibin ÜSTÜNDE kapanır.
    Tetik, bu geri-kapanışın İLK olduğu k barında (karar k kapanışında). Önceki dip = min(l[j−w..j−1]) (güncel bar hariç)."""
    l = np.asarray(l, dtype=float); c = np.asarray(c, dtype=float)
    pl = roll_min_prior(l, w)
    with np.errstate(invalid="ignore"):
        lvl = np.where(l < pl, pl, np.nan)
    out = np.zeros(len(l), dtype=bool)
    for o in range(m + 1):
        lv = lag(lvl, o)
        with np.errstate(invalid="ignore"):
            cand = np.isfinite(lv) & (c > lv)
            for q in range(1, o + 1):                 # j..k−1 barlarında daha önce geri-kapanış olmadı
                cand &= ~(lag(c, q) > lv)
        out |= cand
    return out


# ------------------------------------------------------------------------------------------------ kesit (cross-section) yardımcıları: (S, T), sütun = an
def xs_flag(score: np.ndarray, valid: np.ndarray, q: float, side: str, min_valid: int = 20) -> np.ndarray:
    """Her sütunda (an) geçerli ∧ sonlu skorlu semboller arasında alt (side='low': skor ≤ q-yüzdelik) ya da üst (side='high': skor ≥ (1−q)-yüzdelik) dilim bayrağı.
    Geçerli sembol < min_valid ise sütun boş. Yalnız o sütunun verisi kullanılır (nedensel)."""
    score = np.asarray(score, dtype=float)
    ok = np.asarray(valid, dtype=bool) & np.isfinite(score)
    x = np.where(ok, score, np.nan)
    cnt = ok.sum(axis=0)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        thr = np.nanpercentile(x, 100.0 * (q if side == "low" else 1.0 - q), axis=0)
    with np.errstate(invalid="ignore"):
        f = ok & ((x <= thr[None, :]) if side == "low" else (x >= thr[None, :]))
    return f & (cnt >= min_valid)[None, :]


def xs_mean(x: np.ndarray, valid: np.ndarray, clip: float = 0.3, min_valid: int = 20) -> np.ndarray:
    """Sütun başına geçerli ∧ sonlu değerlerin ortalaması (±clip'e kırpılmış); geçerli sayısı < min_valid → NaN. (S,T) → (T,)."""
    x = np.asarray(x, dtype=float)
    ok = np.asarray(valid, dtype=bool) & np.isfinite(x)
    s = np.where(ok, np.clip(x, -clip, clip), 0.0).sum(axis=0)
    n = ok.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = s / n
    out[n < min_valid] = np.nan
    return out


def cooldown(mask: np.ndarray, k: int) -> np.ndarray:
    """Her satırda (1B ya da (S,T)) bir tetikten sonraki k−1 barı bastırır: tetik, bir önceki KABUL EDİLEN tetikten ≥ k bar sonra kabul edilir."""
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim == 2:
        return np.stack([cooldown(r, k) for r in mask]) if len(mask) else mask.copy()
    out = np.zeros(len(mask), dtype=bool)
    last = -10 ** 9
    for i in np.flatnonzero(mask):
        if i - last >= k:
            out[i] = True
            last = i
    return out


# ------------------------------------------------------------------------------------------------ vadeli baz (basis) — flow_futures ile aynı hizalama
def basis_z_series(ot0: int, n5: int, c5_try: np.ndarray, usdtry5: np.ndarray, m_ts: np.ndarray, m_oi: np.ndarray, m_oiv: np.ndarray, mult: float,
                   *, extra_lag: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """(baz bps, 24 sa z-skoru) — `flow_futures._fut_build` ile aynı mantık: metrics satırı ts=T, 5 dk diliminin BAŞLANGICIDIR, değer T+5 dk'da bilinir →
    T = ot[i] satırı bar i'ye bağlanır (karar t_dec(i)=ot[i]+5 dk'da bilinir). Yalnız taze (yaş 0) satırdan baz; baz = 1e4·ln(perp/spot),
    perp = OI notional / OI / çarpan, spot = TRY kapanış / USDTTRY."""
    from app.rescan import flow_futures as FF
    vals, age = FF.align_metric_rows(np.asarray(m_ts, dtype=np.int64), np.column_stack([np.asarray(m_oi, float), np.asarray(m_oiv, float)]), int(ot0), int(n5),
                                     extra_lag=extra_lag, ffill=3)
    oi = np.where(vals[:, 0] > 0, vals[:, 0], np.nan)
    oiv = np.where(vals[:, 1] > 0, vals[:, 1], np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        perp = oiv / oi / float(mult)
        spot = np.asarray(c5_try, dtype=float) / np.asarray(usdtry5, dtype=float)
        bas = 1e4 * np.log(perp / spot)
    bas[~np.isfinite(bas)] = np.nan
    bas[~(age == 0)] = np.nan
    return bas, FF.zscore(bas)


# ------------------------------------------------------------------------------------------------ limit dolum + çıkış
def first_idx(mask: np.ndarray) -> np.ndarray:
    """(N, W) bool → her satırda ilk True indeksi; yoksa W (sentinel)."""
    mask = np.asarray(mask, dtype=bool)
    if mask.shape[1] == 0:
        return np.zeros(mask.shape[0], dtype=np.int64)
    idx = np.argmax(mask, axis=1)
    return np.where(mask.any(axis=1), idx, mask.shape[1]).astype(np.int64)


def limit_buy_fill(L: np.ndarray, VW: np.ndarray, limit: np.ndarray, v_max: int, mode: str) -> np.ndarray:
    """Pencere (N, ≥v_max): sütun 0 = karar anında açılan 1 dk bar. İlk dolum barı (0..v_max−1); dolmadıysa v_max (sentinel).
    mode 'low': LOW ≤ limit (dokunma); 'vwap': dakika VWAP ≤ limit (NaN = işlem yok → dolmaz)."""
    limit = np.asarray(limit, dtype=float)[:, None]
    with np.errstate(invalid="ignore"):
        if mode == "low":
            hit = np.asarray(L)[:, :v_max] <= limit
        elif mode == "vwap":
            hit = np.asarray(VW)[:, :v_max] <= limit
        else:
            raise ValueError(mode)
    return first_idx(hit)


def first_hits(H: np.ndarray, L: np.ndarray, VW: np.ndarray, entry: np.ndarray, tps: tuple, sls: tuple, tp_mode: str, nb: int,
               skip_first_tp: bool) -> tuple[dict, dict]:
    """Çıkış pencereleri (N, ≥nb), sütun 0 = dolum (ya da piyasa giriş) barı. Dönüş: ({tp%: ilk TP indeksi}, {sl%: ilk stop indeksi}); yok → nb (sentinel).
    TP: 'high' → HIGH ≥ entry(1+T); 'vwap' → VWAP ≥ seviye. skip_first_tp: sütun 0'da TP değerlendirilmez (limit dolum barı)."""
    entry = np.asarray(entry, dtype=float)[:, None]
    tpi, sli = {}, {}
    src = np.asarray(H)[:, :nb] if tp_mode == "high" else np.asarray(VW)[:, :nb]
    Ln = np.asarray(L)[:, :nb]
    with np.errstate(invalid="ignore"):
        for t in tps:
            hit = src >= entry * (1.0 + t / 100.0)
            if skip_first_tp and nb > 0:
                hit[:, 0] = False
            tpi[t] = first_idx(hit)
        for s in sls:
            sli[s] = first_idx(Ln <= entry * (1.0 - s / 100.0))
    return tpi, sli


def resolve_exit(i_tp: np.ndarray, i_sl: np.ndarray, nb: int, entry: np.ndarray, O: np.ndarray, C: np.ndarray, tp_pct: float, sl_pct: float, *,
                 slip_pct: float, fee_entry_pct: float, fee_tp_pct: float, fee_stop_pct: float, tp_slip_pct: float = 0.0,
                 o0: np.ndarray | None = None) -> dict:
    """İlk-vuruş indekslerinden çıkışı çöz (nb = zaman stopu bar sayısı; indeks ≥ nb = vuruş yok). TP indeksi STOP indeksinden KESİN küçükse TP (eşitlik → stop).
    o0: sütun 0'ın stop-boşluk referansı (limit dolumunda dolum fiyatı); None → O[:,0].
    Dönüş: net, gross (yüzde), reason (0 TP, 1 SL, 2 zaman), hold (bar), exit_rel (= çıkış/entry)."""
    entry = np.asarray(entry, dtype=float)
    n = len(entry)
    rows = np.arange(n)
    tp_first = (i_tp < nb) & (i_tp < i_sl)
    sl_first = (i_sl < nb) & ~tp_first
    stop = entry * (1.0 - sl_pct / 100.0)
    s = slip_pct / 100.0
    j_sl = np.minimum(i_sl, nb - 1)
    o_sl = np.asarray(O)[rows, j_sl].astype(float)
    if o0 is not None:
        o_sl = np.where(j_sl == 0, np.asarray(o0, dtype=float), o_sl)
    px_sl = np.minimum(stop, o_sl) * (1.0 - s)
    px_tp = entry * (1.0 + tp_pct / 100.0) * (1.0 - tp_slip_pct / 100.0)
    px_tm = np.asarray(C)[:, nb - 1].astype(float) * (1.0 - s)
    reason = np.where(tp_first, R_TP, np.where(sl_first, R_SL, R_TIME)).astype(np.int8)
    exit_px = np.where(tp_first, px_tp, np.where(sl_first, px_sl, px_tm))
    hold = np.where(tp_first, i_tp + 1, np.where(sl_first, i_sl + 1, nb)).astype(float)
    f_exit = np.where(tp_first, fee_tp_pct, fee_stop_pct) / 100.0
    f_e = fee_entry_pct / 100.0
    with np.errstate(invalid="ignore", divide="ignore"):
        net = exit_px * (1.0 - f_exit) / (entry * (1.0 + f_e)) - 1.0
        gross = exit_px / entry - 1.0
    return {"net": net * 100.0, "gross": gross * 100.0, "reason": reason, "hold": hold, "exit_rel": exit_px / entry}


def limit_exit(O, H, L, C, VW, entry, tp_pct, sl_pct, nb, *, tp_mode="high", skip_first_tp=True, slip_pct=0.15, fee_entry_pct=0.0675,
               fee_tp_pct=0.0675, fee_stop_pct=0.1125, tp_slip_pct=0.0, o0=None) -> dict:
    """Tek (T, SL, nb) için sarmalayıcı (test / yardımcı)."""
    tpi, sli = first_hits(H, L, VW, entry, (tp_pct,), (sl_pct,), tp_mode, nb, skip_first_tp)
    return resolve_exit(tpi[tp_pct], sli[sl_pct], nb, entry, O, C, tp_pct, sl_pct, slip_pct=slip_pct, fee_entry_pct=fee_entry_pct, fee_tp_pct=fee_tp_pct,
                        fee_stop_pct=fee_stop_pct, tp_slip_pct=tp_slip_pct, o0=o0)


# ------------------------------------------------------------------------------------------------ eşleştirilmiş rastgele giriş
def match_random(atr_ev: np.ndarray, atr_pool: np.ndarray, idx_pool: np.ndarray, n_draw: int, rng: np.random.Generator, width: float = 0.05) -> np.ndarray:
    """Her olay için havuzdan (aynı sembol/blok/evren) ATR'si olaya en yakın ±max(3, width·|havuz|) SIRA içinden n_draw rastgele bar seçer (yerine koyarak).
    Dönüş (n_olay, n_draw) havuz bar değerleri; havuz boşsa −1."""
    atr_ev = np.asarray(atr_ev, dtype=float)
    ok = np.isfinite(atr_pool)
    ap, ip = np.asarray(atr_pool, dtype=float)[ok], np.asarray(idx_pool)[ok]
    out = np.full((len(atr_ev), n_draw), -1, dtype=np.int64)
    if len(ap) == 0 or len(atr_ev) == 0:
        return out
    o = np.argsort(ap, kind="stable")
    ap, ip = ap[o], ip[o]
    half = max(3, int(round(width * len(ap))))
    pos = np.searchsorted(ap, atr_ev)
    lo = np.clip(pos - half, 0, len(ap) - 1)
    hi = np.clip(pos + half, 0, len(ap) - 1)
    r = rng.random((len(atr_ev), n_draw))
    pick = lo[:, None] + np.floor(r * (hi - lo + 1)[:, None]).astype(np.int64)
    pick = np.minimum(pick, hi[:, None])
    out[:] = ip[pick]
    out[~np.isfinite(atr_ev)] = -1
    return out


# ------------------------------------------------------------------------------------------------ gün-kümeli istatistik (gün başına toplamlardan)
def cluster_se_from_sums(n_g: np.ndarray, s_g: np.ndarray) -> float:
    """Ortalamanın gün-kümeli SE'si, gün başına (adet, toplam) dizilerinden; `exit_sim.cluster_se` ile aynı sayı."""
    n_g = np.asarray(n_g, dtype=float); s_g = np.asarray(s_g, dtype=float)
    n = n_g.sum()
    if n < 2:
        return float("nan")
    mean = s_g.sum() / n
    d = s_g - n_g * mean
    return float(math.sqrt((d ** 2).sum()) / n)


def mean_se(n_g: np.ndarray, s_g: np.ndarray) -> tuple[float, float, float]:
    """(ortalama, gün-kümeli SE, n) — adet 0 ise (NaN, NaN, 0)."""
    n = float(np.asarray(n_g, dtype=float).sum())
    if n <= 0:
        return float("nan"), float("nan"), 0.0
    return float(np.asarray(s_g, dtype=float).sum() / n), cluster_se_from_sums(n_g, s_g), n


def diff_se(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float]:
    """(a − b, bağımsız SE'ler toplamı karesi kökü) — muhafazakâr (ortak gün etkisi iptal sayılmaz)."""
    if not (a[2] > 0 and b[2] > 0 and math.isfinite(a[1]) and math.isfinite(b[1])):
        return float("nan"), float("nan")
    return a[0] - b[0], math.sqrt(a[1] ** 2 + b[1] ** 2)
