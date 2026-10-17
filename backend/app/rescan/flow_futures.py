"""İşlem akışı (aggTrades) ve vadeli işlem (OI / L-S / fonlama / defter) özellikleri — SAF, NEDENSEL kurucular (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ).

Her özellik 5 dk karar ızgarasındadır: satır i = açılışı ot[i] olan 5 dk mum; karar anı t_dec(i) = ot[i] + 5 dk (mum kapanışı). Satır i'nin özellikleri YALNIZ
t_dec(i) anında bilinen veriyle hesaplanır (kesilmiş girdiyle yeniden hesap aynı satırı verir: tests/test_flow_futures.py).

Veri zamanlama gerçekleri (ölçüldü, docs/ ve backend/work/flowfut/report.md bölüm "Nedensellik"):
  * `historical_trade_flow.minute_open_ms` = dakika AÇILIŞI; 5 dk mum i'nin dakikaları ot[i] <= minute < ot[i]+5dk -> t_dec(i)'de tamam.
  * `hist_futures_metrics.ts_ms` (create_time) 5 dk diliminin BAŞLANGICIDIR; satırın değeri dilim SONUNDA (ts+5 dk) ölçülür
    (OI'dan türetilen fiyat, spot fiyatla ts+5 dk'da r=0,94, ts'de r≈0). Yani ts_ms=T satırı t_dec = T+5 dk'dan önce BİLİNMEZ -> mum i'ye T = ot[i] satırı bağlanır.
  * `hist_futures_bookdepth.ts_ms` = dilimin son anlık görüntüsünün GERÇEK zamanı (ts <= dilim sonu); ts ∈ [ot[i], ot[i]+5dk) -> mum i (t_dec(i)'de bilinir).
  * `hist_funding_rate.funding_time_ms` = yerleşim anı; yalnız funding_time <= t_dec olan son oran kullanılır.
  `extra_lag` (bar) yayın gecikmesi duyarlılığı için tüm vadeli hizalamalara eklenir.

Önekler: `tf.` = işlem akışı, `fu.` = vadeli.
"""
from __future__ import annotations

import numpy as np

BAR_MS = 300_000
Z_WIN = 288            # 24 saat (5 dk bar)
Z_MIN = 144            # z için en az 12 saat geçmiş
W_BARS = (1, 3, 12)
W_MIN = {1: 5, 3: 15, 12: 60}
FLOW_KEYS = ("n", "bq", "sq", "bb", "sb", "bbq", "sbq", "bbn", "sbn", "wbq", "wsq", "mx")
FLOW_COLS_DB = {"n": "n_trades", "bq": "buy_quote", "sq": "sell_quote", "bb": "buy_base", "sb": "sell_base", "bbq": "big_buy_quote", "sbq": "big_sell_quote",
                "bbn": "big_buy_n", "sbn": "big_sell_n", "wbq": "whale_buy_quote", "wsq": "whale_sell_quote", "mx": "max_trade_quote"}
FUT_KEYS = ("oi", "oiv", "tt_sum", "tt_cnt", "acc", "taker")
BD_KEYS = ("bid_n1", "bid_n2", "bid_n5", "ask_n1", "ask_n2", "ask_n5")
RET_DZ = {3: 0.0015, 12: 0.003}           # dörtlü kadran: ölü bölge (logaritmik getiri / OI log değişimi)


# ------------------------------------------------------------------------------------------------ temel yardımcılar
def _c0(x: np.ndarray) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(x)])


def lag(x: np.ndarray, k: int) -> np.ndarray:
    """x[i-k]; ilk k satır NaN."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if k == 0:
        return x.copy()
    if k < len(x):
        out[k:] = x[:-k]
    return out


def roll_sum(x: np.ndarray, w: int) -> np.ndarray:
    """Son w değerin toplamı (güncel dahil); ilk w-1 satır NaN. NaN girdi -> NaN yayılır (toplam NaN değilse sonlu varsayılır; çağıran sıfır doldurur)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        c = _c0(x)
        out[w - 1:] = c[w:] - c[:-w]
    return out


def roll_max(x: np.ndarray, w: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) < w:
        return out
    st = np.stack([lag(x, k) for k in range(w)], axis=0)
    out = np.max(st, axis=0)
    out[: w - 1] = np.nan
    return out


def roll_mean_std(x: np.ndarray, n: int = Z_WIN, min_n: int = Z_MIN) -> tuple[np.ndarray, np.ndarray]:
    """Geriye dönük (güncel dahil) n barlık ortalama ve örneklem std'si; yalnız sonlu değerler; en az min_n sonlu değer yoksa NaN."""
    x = np.asarray(x, dtype=float)
    ok = np.isfinite(x)
    xs = np.where(ok, x, 0.0)
    c1, c2, cn = _c0(xs), _c0(xs * xs), _c0(ok.astype(float))
    idx = np.arange(len(x))
    lo = np.maximum(idx + 1 - n, 0)
    s1, s2, k = c1[idx + 1] - c1[lo], c2[idx + 1] - c2[lo], cn[idx + 1] - cn[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s1 / k
        var = (s2 - s1 * s1 / k) / (k - 1.0)
    var = np.maximum(var, 0.0)
    sd = np.sqrt(var)
    bad = k < min_n
    mean[bad] = np.nan
    sd[bad] = np.nan
    return mean, sd


def zscore(x: np.ndarray, n: int = Z_WIN, min_n: int = Z_MIN) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    mean, sd = roll_mean_std(x, n, min_n)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (x - mean) / sd
    z[~(sd > 1e-9)] = np.nan
    z[~np.isfinite(x)] = np.nan
    return z


def roll_slope(x: np.ndarray, m: int) -> np.ndarray:
    """Son m noktaya doğrusal eğim (birim / bar); ilk m-1 satır NaN."""
    x = np.asarray(x, dtype=float)
    cen = (m - 1) / 2.0
    num = np.zeros(len(x))
    for j in range(m):
        num = num + (j - cen) * lag(x, m - 1 - j)
    den = float(sum((j - cen) ** 2 for j in range(m)))
    out = num / den
    out[: m - 1] = np.nan
    return out


def sdiv(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a/b; b <= 0 ya da NaN ise NaN."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    out = np.full(np.broadcast(a, b).shape, np.nan)
    ok = np.isfinite(a) & np.isfinite(b) & (b > 0)
    out[ok] = (a / np.where(ok, b, 1.0))[ok]
    return out


def slog10(x: np.ndarray) -> np.ndarray:
    """işaret-korumalı log10(1+|x|)."""
    x = np.asarray(x, dtype=float)
    return np.sign(x) * np.log10(1.0 + np.abs(x))


def log_ret(c: np.ndarray, w: int) -> np.ndarray:
    c = np.asarray(c, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.log(c / lag(c, w))
    r[~np.isfinite(r)] = np.nan
    return r


def _ln(x: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.log(np.asarray(x, dtype=float))
    r[~np.isfinite(r)] = np.nan
    return r


# ------------------------------------------------------------------------------------------------ hizalama (seyrek satırlar -> 5 dk ızgara)
def minute_rows_to_bars(minute_ms: np.ndarray, cols: dict[str, np.ndarray], ot0: int, n5: int) -> dict[str, np.ndarray]:
    """Dakikalık akış satırlarını 5 dk mumlara toplar (toplam; `mx` için maksimum). Satır olmayan dakika = işlem yok (0)."""
    m = np.asarray(minute_ms, dtype=np.int64)
    idx = (m - int(ot0)) // BAR_MS
    ok = (idx >= 0) & (idx < n5)
    idx = idx[ok]
    out = {}
    for k in FLOW_KEYS:
        v = np.asarray(cols[k], dtype=float)[ok]
        v = np.where(np.isfinite(v), v, 0.0)
        if k == "mx":
            a = np.zeros(n5)
            np.maximum.at(a, idx, v)
        else:
            a = np.bincount(idx, weights=v, minlength=n5).astype(float)
        out[k] = a
    return out


def _ffill_rows(row_bar: np.ndarray, vals: np.ndarray, n5: int, ffill: int) -> tuple[np.ndarray, np.ndarray]:
    """row_bar: satırın bağlandığı bar (artan olmak zorunda değil; aynı barda sonuncusu kazanır). Dönüş: (n5, k) değerler (en çok `ffill` bar ileri taşınır), yaş (bar; NaN = yok)."""
    vals = np.asarray(vals, dtype=float)
    k = vals.shape[1]
    out = np.full((n5, k), np.nan)
    age = np.full(n5, np.nan)
    ok = (row_bar >= 0) & (row_bar < n5)
    rb, vv = row_bar[ok], vals[ok]
    if len(rb) == 0:
        return out, age
    o = np.argsort(rb, kind="stable")
    rb, vv = rb[o], vv[o]
    last = np.r_[rb[1:] != rb[:-1], True]                      # aynı barda son satır
    rb, vv = rb[last], vv[last]
    src = np.full(n5, -1, dtype=np.int64)
    src[rb] = np.arange(len(rb))
    pos = np.where(src >= 0, np.arange(n5), -1)
    pos = np.maximum.accumulate(pos)                          # son dolu bar
    a = np.arange(n5) - pos
    good = (pos >= 0) & (a <= ffill)
    out[good] = vv[src[pos[good]]]
    age[good] = a[good]
    return out, age


def align_metric_rows(ts_ms: np.ndarray, vals: np.ndarray, ot0: int, n5: int, *, extra_lag: int = 0, ffill: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """`hist_futures_metrics`: ts_ms = dilim BAŞLANGICI, değer dilim SONUNDA (ts+5 dk) bilinir -> bar i = (ts - ot0)//5dk (+ extra_lag)."""
    bar = (np.asarray(ts_ms, dtype=np.int64) - int(ot0)) // BAR_MS + int(extra_lag)
    return _ffill_rows(bar, vals, n5, ffill)


def align_snapshot_rows(ts_ms: np.ndarray, vals: np.ndarray, ot0: int, n5: int, *, extra_lag: int = 0, ffill: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """`hist_futures_bookdepth`: ts_ms = gerçek anlık görüntü zamanı; ts ∈ [ot[i], ot[i]+5dk) -> bar i (t_dec(i)'de bilinir)."""
    bar = (np.asarray(ts_ms, dtype=np.int64) - int(ot0)) // BAR_MS + int(extra_lag)
    return _ffill_rows(bar, vals, n5, ffill)


def funding_features(ft_ms: np.ndarray, rate: np.ndarray, t_dec: np.ndarray, *, extra_lag_ms: int = 0, hist: int = 21, min_hist: int = 6) -> dict[str, np.ndarray]:
    """Son YERLEŞMİŞ fonlama (funding_time <= t_dec - extra_lag_ms): bps, 21 yerleşimlik z, bir önceki yerleşime göre değişim, yaş (saat)."""
    ft = np.asarray(ft_ms, dtype=np.int64)
    r = np.asarray(rate, dtype=float) * 1e4                      # bps
    o = np.argsort(ft, kind="stable")
    ft, r = ft[o], r[o]
    z = np.full(len(r), np.nan)
    chg = np.full(len(r), np.nan)
    for k in range(len(r)):
        h = r[max(0, k - hist): k]
        h = h[np.isfinite(h)]
        if len(h) >= min_hist and h.std(ddof=1) > 1e-9:
            z[k] = (r[k] - h.mean()) / h.std(ddof=1)
        if k > 0:
            chg[k] = r[k] - r[k - 1]
    t = np.asarray(t_dec, dtype=np.int64) - int(extra_lag_ms)
    j = np.searchsorted(ft, t, side="right") - 1
    ok = j >= 0
    jj = np.where(ok, j, 0)
    nan = np.full(len(t), np.nan)
    return {"fund_bps": np.where(ok, r[jj], nan) if len(r) else nan, "fund_z": np.where(ok, z[jj], nan) if len(r) else nan,
            "fund_chg": np.where(ok, chg[jj], nan) if len(r) else nan, "fund_age_h": np.where(ok, (t - ft[jj]) / 3_600_000.0, nan) if len(r) else nan}


# ------------------------------------------------------------------------------------------------ işlem akışı özellikleri
def flow_feature_names() -> list[str]:
    return list(_flow_build(_dummy_flow(40), np.full(40, 1.0), 0))


def _dummy_flow(n: int) -> dict[str, np.ndarray]:
    return {k: np.zeros(n) for k in FLOW_KEYS}


def build_flow_features(bars: dict[str, np.ndarray], c5: np.ndarray, cov0: int = 0) -> tuple[list[str], np.ndarray]:
    """bars: 5 dk toplamlar (FLOW_KEYS); c5: 5 dk kapanış; cov0: akış verisinin kapsadığı ilk bar (öncesi NaN). Dönüş: (adlar, (n5, F) float32)."""
    d = _flow_build(bars, c5, cov0)
    names = list(d)
    return names, np.column_stack([d[k] for k in names]).astype(np.float32)


def _flow_build(bars: dict[str, np.ndarray], c5: np.ndarray, cov0: int) -> dict[str, np.ndarray]:
    c5 = np.asarray(c5, dtype=float)
    n5 = len(c5)
    B = {k: np.asarray(bars[k], dtype=float) for k in FLOW_KEYS}
    tq1 = B["bq"] + B["sq"]
    S: dict[tuple[str, int], np.ndarray] = {}
    for k in ("n", "bq", "sq", "bb", "sb", "bbq", "sbq", "bbn", "sbn", "wbq", "wsq"):
        for w in W_BARS:
            s = roll_sum(B[k], w)
            s[: max(cov0 + w - 1, 0)] = np.nan
            S[(k, w)] = s
    M: dict[int, np.ndarray] = {}
    for w in W_BARS:
        m = roll_max(B["mx"], w)
        m[: max(cov0 + w - 1, 0)] = np.nan
        M[w] = m
    typ, _ = roll_mean_std(np.where(np.arange(n5) >= cov0, tq1, np.nan), Z_WIN, Z_MIN)
    out: dict[str, np.ndarray] = {}
    ret = {w: log_ret(c5, w) for w in W_BARS}
    for w in W_BARS:
        m = W_MIN[w]
        tq = S[("bq", w)] + S[("sq", w)]
        big = S[("bbq", w)] + S[("sbq", w)]
        out[f"tf.buy_share_{m}"] = sdiv(S[("bq", w)], tq)
        out[f"tf.big_share_{m}"] = sdiv(big, tq)
        out[f"tf.bigbuy_share_{m}"] = sdiv(S[("bbq", w)], big)
        out[f"tf.big_net_{m}"] = sdiv(S[("bbq", w)] - S[("sbq", w)], tq)
        wn = S[("wbq", w)] - S[("wsq", w)]
        out[f"tf.whale_net_{m}"] = slog10(wn)
        with np.errstate(invalid="ignore", divide="ignore"):
            wrel = np.where(typ > 0, wn / (typ * w), np.nan)
        out[f"tf.whale_net_rel_{m}"] = wrel
        bigcnt = S[("bbn", w)] + S[("sbn", w)]
        out[f"tf.bigcnt_{m}"] = np.log1p(bigcnt)
        out[f"tf.bigcnt_z_{m}"] = zscore(np.log1p(bigcnt))
        out[f"tf.ntr_z_{m}"] = zscore(np.log1p(S[("n", w)]))
        avg = sdiv(tq, S[("n", w)])
        out[f"tf.avgsz_z_{m}"] = zscore(_ln(avg))
        out[f"tf.maxsz_z_{m}"] = zscore(np.log1p(M[w]))
        vw = sdiv(tq, S[("bb", w)] + S[("sb", w)])
        with np.errstate(invalid="ignore", divide="ignore"):
            vd = np.log(c5 / vw)
        vd[~np.isfinite(vd)] = np.nan
        out[f"tf.vwap_dist_{m}"] = vd
    bs15 = out["tf.buy_share_15"]
    bs60 = out["tf.buy_share_60"]
    out["tf.buy_share_z_15"] = zscore(bs15)
    out["tf.buy_share_z_60"] = zscore(bs60)
    out["tf.flow_acc"] = bs15 - bs60
    net15 = S[("bq", 3)] - S[("sq", 3)]
    tq30 = S[("bq", 3)] + S[("sq", 3)] + lag(S[("bq", 3)] + S[("sq", 3)], 3)
    out["tf.net_acc"] = np.where(tq30 > 0, (net15 - lag(net15, 3)) / np.where(tq30 > 0, tq30, 1.0), np.nan)
    for w in (3, 12):
        m = W_MIN[w]
        tq = S[("bq", w)] + S[("sq", w)]
        out[f"tf.absorb_sell_{m}"] = np.where(ret[w] >= -0.001, sdiv(S[("sbq", w)], tq), np.where(np.isfinite(ret[w]), 0.0, np.nan))
        out[f"tf.absorb_buy_{m}"] = np.where(ret[w] <= 0.001, sdiv(S[("bbq", w)], tq), np.where(np.isfinite(ret[w]), 0.0, np.nan))
    cvd = np.cumsum(B["bq"] - B["sq"])
    for m_bars in (6, 12):
        sl = roll_slope(cvd, m_bars)
        den = roll_sum(tq1, m_bars) / m_bars
        sl = np.where(den > 0, sl / np.where(den > 0, den, 1.0), np.nan)
        sl[: max(cov0 + m_bars - 1, 0)] = np.nan
        out[f"tf.cvd_slope_{5 * m_bars}"] = sl
    return out


# ------------------------------------------------------------------------------------------------ vadeli özellikleri
def futures_feature_names() -> list[str]:
    n = 60
    z = {k: np.full(n, 1.0) for k in FUT_KEYS}
    bd = {k: np.full(n, 1.0) for k in BD_KEYS}
    fund = {k: np.full(n, 0.0) for k in ("fund_bps", "fund_z", "fund_chg", "fund_age_h")}
    return list(_fut_build(z, bd, fund, np.full(n, 1.0), np.full(n, 1.0), 1.0, np.zeros(n)))


def build_futures_features(fut: dict[str, np.ndarray], bd: dict[str, np.ndarray], fund: dict[str, np.ndarray], c5: np.ndarray, usdtry5: np.ndarray, mult: float,
                           oi_age: np.ndarray | None = None) -> tuple[list[str], np.ndarray]:
    """fut: FUT_KEYS dizileri (n5; metrics hizalı); bd: BD_KEYS dizileri (n5); fund: funding_features çıktısı; c5: TRY spot kapanış; usdtry5: USDTTRY kapanış (hizalı);
    mult: perp çarpanı (1000PEPE -> 1000); oi_age: metrics satır yaşı (0 = bu barın taze satırı; baz için yalnız taze satır kullanılır)."""
    n5 = len(c5)
    age = np.zeros(n5) if oi_age is None else np.asarray(oi_age, dtype=float)
    d = _fut_build(fut, bd, fund, c5, usdtry5, mult, age)
    names = list(d)
    return names, np.column_stack([d[k] for k in names]).astype(np.float32)


def _fut_build(fut: dict, bd: dict, fund: dict, c5: np.ndarray, usdtry5: np.ndarray, mult: float, age: np.ndarray) -> dict[str, np.ndarray]:
    c5 = np.asarray(c5, dtype=float)
    out: dict[str, np.ndarray] = {}
    oi = np.asarray(fut["oi"], dtype=float)
    oiv = np.asarray(fut["oiv"], dtype=float)
    oi = np.where(oi > 0, oi, np.nan)
    oiv = np.where(oiv > 0, oiv, np.nan)
    loi = _ln(oi)
    ret = {w: log_ret(c5, w) for w in W_BARS}
    chg = {w: loi - lag(loi, w) for w in W_BARS}
    for w in W_BARS:
        out[f"fu.oi_chg_{W_MIN[w]}"] = chg[w] * 100.0
    out["fu.oi_z"] = zscore(loi)
    out["fu.oi_chg_z_15"] = zscore(chg[3])
    out["fu.oi_val_log10"] = np.log10(oiv)
    # fiyat / OI dört kadran (15 ve 60 dk)
    for w in (3, 12):
        m = W_MIN[w]
        dz = RET_DZ[w]
        pu, pd_ = ret[w] >= dz, ret[w] <= -dz
        ou, od = chg[w] >= dz, chg[w] <= -dz
        known = np.isfinite(ret[w]) & np.isfinite(chg[w])
        code = np.zeros(len(c5))
        code[pu & ou] = 1.0       # fiyat↑ OI↑: yeni long
        code[pu & od] = 2.0       # fiyat↑ OI↓: short kapatma
        code[pd_ & ou] = 3.0      # fiyat↓ OI↑: yeni short
        code[pd_ & od] = 4.0      # fiyat↓ OI↓: long tasfiyesi
        code[~known] = np.nan
        out[f"fu.quad_{m}"] = code
        if w == 3:
            for q, nm in ((1, "newlong"), (2, "shortcover"), (3, "newshort"), (4, "longliq")):
                out[f"fu.quad_{nm}_15"] = np.where(known, (code == q).astype(float), np.nan)
    # top trader / hesap L-S ve taker
    for key, nm in (("tt_sum", "tt_ls"), ("tt_cnt", "tt_cnt_ls"), ("acc", "acc_ls")):
        x = _ln(np.where(np.asarray(fut[key], dtype=float) > 0, fut[key], np.nan))
        out[f"fu.{nm}"] = x
        out[f"fu.{nm}_d3"] = x - lag(x, 3)
        out[f"fu.{nm}_d12"] = x - lag(x, 12)
        out[f"fu.{nm}_z"] = zscore(x)
    tk = _ln(np.where(np.asarray(fut["taker"], dtype=float) > 0, fut["taker"], np.nan))
    ok = np.isfinite(tk)
    t0 = np.where(ok, tk, 0.0)
    cnt3, cnt12 = roll_sum(ok.astype(float), 3), roll_sum(ok.astype(float), 12)
    m3 = np.where(cnt3 >= 2, roll_sum(t0, 3) / np.where(cnt3 > 0, cnt3, 1.0), np.nan)
    m12 = np.where(cnt12 >= 6, roll_sum(t0, 12) / np.where(cnt12 > 0, cnt12, 1.0), np.nan)
    out["fu.taker_ls"] = tk
    out["fu.taker_ls_m15"] = m3
    out["fu.taker_ls_m60"] = m12
    out["fu.taker_ls_z"] = zscore(m3)
    out["fu.taker_ls_acc"] = m3 - m12
    # fonlama
    for k in ("fund_bps", "fund_z", "fund_chg", "fund_age_h"):
        out["fu." + k] = np.asarray(fund[k], dtype=float)
    # baz: perp (OI notional / OI) / çarpan  ↔  TRY spot / USDTTRY
    with np.errstate(invalid="ignore", divide="ignore"):
        perp = oiv / oi / float(mult)
        spot = c5 / np.asarray(usdtry5, dtype=float)
        bas = 1e4 * np.log(perp / spot)
    bas[~np.isfinite(bas)] = np.nan
    bas[~(age == 0)] = np.nan
    out["fu.basis_bps"] = bas
    out["fu.basis_z"] = zscore(bas)
    out["fu.basis_d15"] = bas - lag(bas, 3)
    out["fu.basis_d60"] = bas - lag(bas, 12)
    # defter dengesizliği (bid-ask)/(bid+ask) ve derinlik
    bn = {k: np.where(np.asarray(bd[k], dtype=float) > 0, bd[k], np.nan) for k in BD_KEYS}
    for p in (1, 2, 5):
        b, a = bn[f"bid_n{p}"], bn[f"ask_n{p}"]
        imb = (b - a) / (b + a)
        out[f"fu.bd_imb{p}"] = imb
        out[f"fu.bd_imb{p}_d3"] = imb - lag(imb, 3)
    out["fu.bd_imb2_z"] = zscore(out["fu.bd_imb2"])
    dep2 = np.log10(bn["bid_n2"] + bn["ask_n2"])
    out["fu.bd_depth2_log"] = dep2
    out["fu.bd_depth2_z"] = zscore(dep2)
    out["fu.bd_bid2_chg15"] = _ln(bn["bid_n2"]) - lag(_ln(bn["bid_n2"]), 3)
    out["fu.bd_ask2_chg15"] = _ln(bn["ask_n2"]) - lag(_ln(bn["ask_n2"]), 3)
    return out


def family_of(name: str) -> str:
    """Özellik ailesi (rapor tabloları için)."""
    n = name.split(".", 1)[1] if "." in name else name
    if name.startswith("tf."):
        if n.startswith("whale"):
            return "tf_whale"
        if n.startswith(("big", "bigbuy")):
            return "tf_big"
        if n.startswith("absorb"):
            return "tf_absorb"
        if n.startswith("cvd") or n in ("flow_acc", "net_acc") or n.startswith("buy_share"):
            return "tf_dir"
        if n.startswith(("ntr", "avgsz", "maxsz")):
            return "tf_size"
        return "tf_vwap"
    if n.startswith("oi_"):
        return "fu_oi"
    if n.startswith("quad"):
        return "fu_quad"
    if n.startswith(("tt_", "acc_")):
        return "fu_ls"
    if n.startswith("taker"):
        return "fu_taker"
    if n.startswith("fund"):
        return "fu_fund"
    if n.startswith("basis"):
        return "fu_basis"
    if n.startswith("bd_"):
        return "fu_book"
    return "?"
