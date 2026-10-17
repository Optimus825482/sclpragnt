"""Lorentzian Classification (jdehorty, TradingView) - NEDENSEL numpy yeniden uygulaması (2026-10-17, çevrimdışı araştırma).

Canlı koda bağlanmaz; ağ/DB yok. `scripts/lorentzian_study.py` kullanır.

Kaynak (birebir okunan): jdehorty/MLExtensions + KernelFunctions ve ana betik (artificial-intelligence-edge/lorentzian-classification
ports/pinescript v2). Betikten ÖNEMLİ bulgular:

1. Eğitim etiketi betikte `y_train_series = src[4] < src[0] ? SHORT : src[4] > src[0] ? LONG : NEUTRAL` ve dizilere o barın
   özellikleriyle AYNI barda eklenir. Yani etiket GEÇMİŞ 4 barlık hareketin TERSİdir (son 4 barda yükseldiyse SHORT) ve gecikmesizdir.
   Betiğin belgelediği niyet ise "4 bar SONRAKİ yön"dür. İkisi de uygulanır:
     label_mode = "pine"   : y[j] = sign(c[j-4] - c[j])  (betik NE YAPIYORSA o; gecikme 0, geçmiş = j <= t)
     label_mode = "future" : y[j] = sign(c[j+4] - c[j])  (niyet; yalnız j <= t-4 kullanılabilir)
     label_mode = "event"  : dışarıdan verilen 0/1 etiket (biz: 60 dk MFE >= %1,5); gecikme = etiket ufku
2. Yaklaşık en yakın komşu (ANN) döngüsü: kronolojik (eskiden yeniye) gez, `d >= lastDistance and i % 4 != 0` olanları ekle
   (Pine'da `i%4` = sıfırdan farklıysa doğru; v2 betiği bunu `i % 4 != 0` yazar), k = 8'i aşınca `lastDistance = distances[round(k*3/4)]`,
   en eskiyi at. Tahmin = komşu etiketlerinin toplamı (-8..8).
   Fark: betik büyüyen bir diziyle (son 2000 barlık pencerede genişleyerek) çalışır; burada `window` barlık KAYAN pencere kullanılır,
   i%4 eşlemesi MUTLAK bar indeksine göredir. Betikteki `var predictions/distances` dizilerinin barlar arası taşınması yok sayılır
   (her bar için taze liste; bar başına ≫ 8 ekleme olduğundan etkisi önemsiz).
3. Özellikler (MLExtensions): n_rsi = rescale(ema(rsi,n2), 0..100 -> 0..1); n_wt, n_cci, n_adx(sma) ; n_wt/n_cci `normalize` ile
   KOŞAN (genişleyen) min/max'a göre 0..1 (nedensel). n_adx rescale(adx, 0..100).
4. Filtreler: volatilite = ATR(1) > ATR(10); rejim = KLMF eğim düşüşü >= eşik (-0,1); ADX filtresi, EMA/SMA filtreleri varsayılan kapalı.
5. Çekirdek: Rational Quadratic Nadaraya-Watson (h=8, r=8, x=25 -> 0..x+1 = 27 örnek), boğa = yhat[t-1] < yhat[t].
6. Sinyal: prediction > 0 ve filtreler -> LONG, < 0 -> SHORT, aksi halde önceki sinyal; giriş = sinyal DEĞİŞTİĞİ bar ∧ çekirdek boğa.

Nedensellik: her bar t çıktısı yalnız barlar <= t'ye bağlıdır (kesme-değişmezliği testle doğrulanır).
"""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from app.rescan import rqk as _rqk

K_DEFAULT = 8
WINDOW_DEFAULT = 2000
HORIZON = 4


# ------------------------------------------------------------------------------------------------ yumuşatıcılar
def _ffill(x: np.ndarray) -> np.ndarray:
    """Sonlu olmayan değerleri bir önceki sonlu değerle doldur (baştakiler NaN kalır). Özyinelemeli süzgeçleri NaN zehirlenmesinden korur."""
    ok = np.isfinite(x)
    idx = np.where(ok, np.arange(len(x)), -1)
    np.maximum.accumulate(idx, out=idx)
    return np.where(idx >= 0, x[np.maximum(idx, 0)], np.nan)


def ema(x: np.ndarray, n: int) -> np.ndarray:
    """Üstel ortalama, alfa = 2/(n+1); ilk sonlu değerle tohumlanır (tek yönlü -> nedensel). Baştaki NaN korunur;
    ortadaki sonlu olmayan girdi bir önceki sonlu girdiyle yer değiştirir (düz mum kaynaklı 0/0 zehirlenmesi olmasın)."""
    x = _ffill(np.asarray(x, dtype=float))
    out = np.full(len(x), np.nan)
    fin = np.flatnonzero(np.isfinite(x))
    if len(fin) == 0:
        return out
    f = fin[0]
    if n <= 1:
        out[f:] = x[f:]
        return out
    a = 2.0 / (n + 1.0)
    y, _ = lfilter([a], [1.0, -(1.0 - a)], x[f:], zi=[(1.0 - a) * x[f]])
    out[f:] = y
    return out


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder (Pine ta.rma): alfa = 1/n, ilk n değerin SMA'sıyla tohumlanır; ilk sonlu indeksten n-1 sonrası dolu."""
    x = _ffill(np.asarray(x, dtype=float))
    out = np.full(len(x), np.nan)
    fin = np.flatnonzero(np.isfinite(x))
    if len(fin) == 0 or len(x) - fin[0] < n:
        return out
    f = fin[0]
    s = f + n - 1
    a = 1.0 / n
    out[s] = x[f:s + 1].mean()
    if s + 1 < len(x):
        y, _ = lfilter([a], [1.0, -(1.0 - a)], x[s + 1:], zi=[(1.0 - a) * out[s]])
        out[s + 1:] = y
    return out


def sma(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    cs = np.concatenate([[0.0], np.cumsum(np.where(np.isfinite(x), x, 0.0))])
    cnt = np.concatenate([[0], np.cumsum(np.isfinite(x))])
    s = cs[n:] - cs[:-n]
    c = cnt[n:] - cnt[:-n]
    out[n - 1:] = np.where(c == n, s / n, np.nan)
    return out


def _rolling_dev(x: np.ndarray, n: int) -> np.ndarray:
    """Pine ta.dev: pencere içi ortalamadan mutlak sapmaların ortalaması."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    out[n - 1:] = np.abs(w - w.mean(axis=1, keepdims=True)).mean(axis=1)
    return out


# ------------------------------------------------------------------------------------------------ MLExtensions özellikleri
def normalize_expanding(x: np.ndarray, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    """MLExtensions `normalize`: tarihsel (genişleyen) min/max'a göre [lo, hi] aralığına ölçekle. Nedensel."""
    x = np.asarray(x, dtype=float)
    mn = np.fmin.accumulate(np.where(np.isfinite(x), x, np.nan))
    mx = np.fmax.accumulate(np.where(np.isfinite(x), x, np.nan))
    return lo + (hi - lo) * (x - mn) / np.maximum(mx - mn, 1e-9)


def rsi(close: np.ndarray, n: int) -> np.ndarray:
    c = np.asarray(close, dtype=float)
    d = np.full(len(c), np.nan)
    d[1:] = np.diff(c)
    up = rma(np.where(np.isfinite(d), np.maximum(d, 0.0), np.nan), n)
    dn = rma(np.where(np.isfinite(d), np.maximum(-d, 0.0), np.nan), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = up / dn
        out = np.where(dn == 0, 100.0, 100.0 - 100.0 / (1.0 + rs))
    out = np.where(np.isfinite(up) & np.isfinite(dn), out, np.nan)
    return out


def cci(src: np.ndarray, n: int) -> np.ndarray:
    s = np.asarray(src, dtype=float)
    m = sma(s, n)
    dev = _rolling_dev(s, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (s - m) / (0.015 * dev)
    return np.where(np.isfinite(out), out, np.nan)


def n_rsi(close, n1: int = 14, n2: int = 1) -> np.ndarray:
    return np.clip(ema(rsi(close, n1), n2) / 100.0, 0.0, 1.0)


def n_cci(close, n1: int = 20, n2: int = 1) -> np.ndarray:
    return normalize_expanding(ema(cci(close, n1), n2))


def n_wt(hlc3, n1: int = 10, n2: int = 11) -> np.ndarray:
    s = np.asarray(hlc3, dtype=float)
    e1 = ema(s, n1)
    e2 = ema(np.abs(s - e1), n1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ci = (s - e1) / (0.015 * e2)
    ci = np.where(np.isfinite(ci), ci, np.nan)
    wt1 = ema(ci, n2)
    wt2 = sma(wt1, 4)
    return normalize_expanding(wt1 - wt2)


def n_adx(high, low, close, n1: int = 20) -> np.ndarray:
    h = np.asarray(high, dtype=float); l = np.asarray(low, dtype=float); c = np.asarray(close, dtype=float)
    n = len(c)
    pc = np.concatenate([[c[0]], c[:-1]])
    ph = np.concatenate([[h[0]], h[:-1]])
    pl = np.concatenate([[l[0]], l[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    up = np.maximum(h - ph, 0.0)
    dn = np.maximum(pl - l, 0.0)
    dmp = np.where(up > dn, up, 0.0)
    dmn = np.where(dn > up, dn, 0.0)
    k = 1.0 - 1.0 / n1
    sm = lambda x: lfilter([1.0], [1.0, -k], x)  # noqa: E731  (s_t = s_{t-1}(1-1/n) + x_t, s_{-1} = 0)
    trs, dps, dns = sm(tr), sm(dmp), sm(dmn)
    with np.errstate(divide="ignore", invalid="ignore"):
        dip = dps / trs * 100.0
        din = dns / trs * 100.0
        dx = np.abs(dip - din) / (dip + din) * 100.0
    dx = np.where(np.isfinite(dx), dx, np.nan)
    adx = sma(dx, n1)
    out = np.clip(adx / 100.0, 0.0, 1.0)
    out[:2] = np.nan
    return out


DEFAULT_FEATURES = (("RSI", 14, 1), ("WT", 10, 11), ("CCI", 20, 1), ("ADX", 20, 2), ("RSI", 9, 1))


def build_features(o, h, l, c, spec=DEFAULT_FEATURES) -> np.ndarray:
    """(n, len(spec)) float32; betiğin 5 varsayılan özelliği. Isınma barları NaN."""
    h = np.asarray(h, dtype=float); l = np.asarray(l, dtype=float); c = np.asarray(c, dtype=float)
    hlc3 = (h + l + c) / 3.0
    cols = []
    for name, a, b in spec:
        if name == "RSI":
            cols.append(n_rsi(c, a, b))
        elif name == "WT":
            cols.append(n_wt(hlc3, a, b))
        elif name == "CCI":
            cols.append(n_cci(c, a, b))
        elif name == "ADX":
            cols.append(n_adx(h, l, c, a))
        else:
            raise ValueError(name)
    F = np.column_stack(cols).astype(np.float32)
    F[:60] = np.nan                    # ısınma: ADX/CCI/WT yerleşsin (bit-düzeyi değil, kararlılık için)
    return F


# ------------------------------------------------------------------------------------------------ mesafe
def lorentzian_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Σ_i log(1 + |a_i - b_i|), son eksen üzerinden."""
    return np.log1p(np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float))).sum(axis=-1)


# ------------------------------------------------------------------------------------------------ etiketler
def labels_pine(c: np.ndarray, horizon: int = HORIZON) -> np.ndarray:
    """Betiğin yazdığı etiket: sign(c[j-h] - c[j]) (GEÇMİŞ hareketin tersi; gecikmesiz). int8."""
    c = np.asarray(c, dtype=float)
    y = np.zeros(len(c), dtype=np.int8)
    if len(c) > horizon:
        y[horizon:] = np.sign(c[:-horizon] - c[horizon:]).astype(np.int8)
    return y


def labels_future(c: np.ndarray, horizon: int = HORIZON) -> np.ndarray:
    """Niyet edilen etiket: sign(c[j+h] - c[j]) (j+h sonrası bilinir). Son h bar 0."""
    c = np.asarray(c, dtype=float)
    y = np.zeros(len(c), dtype=np.int8)
    if len(c) > horizon:
        y[:-horizon] = np.sign(c[horizon:] - c[:-horizon]).astype(np.int8)
    return y


# ------------------------------------------------------------------------------------------------ ANN çekirdeği
def ann_predict(F: np.ndarray, y: np.ndarray, *, lag: int, k: int = K_DEFAULT, window: int = WINDOW_DEFAULT, mod4: str = "pine",
                min_hist: int = 500, chunk: int = 8192, t_from: int = 0, t_to: int | None = None) -> dict:
    """Her t için ANN tahmini. Geçmiş j ∈ [t-lag-(window-1), t-lag], kronolojik gezilir.

    F: (n, nf) özellikler (NaN satırlar geçmişte atlanır; t'de NaN ise çıktı NaN). y: (n,) etiket (j barı için).
    mod4: "pine" -> j % 4 != 0 ; "eq0" -> j % 4 == 0 ; "none" -> hepsi.
    Dönüş: pred (n,) komşu etiket toplamı, meand (n,) komşu ortalama mesafesi, nn (n,) komşu sayısı, hist (n,) kullanılabilir geçmiş sayısı.
    pred, hist < min_hist ise NaN. Hesaplanan aralık [t_from, t_to).
    Vektörleşme: zaman ekseninde (bar bazlı) paralel, pencere ekseninde sıralı döngü; durum (D, Y, cnt, last) bar başına tutulur."""
    F = np.asarray(F, dtype=np.float32)
    y = np.asarray(y, dtype=np.float32)
    n, nf = F.shape
    t_to = n if t_to is None else min(n, t_to)
    pred = np.full(n, np.nan, dtype=np.float32)
    meand = np.full(n, np.nan, dtype=np.float32)
    nn_out = np.zeros(n, dtype=np.int16)
    hist_out = np.zeros(n, dtype=np.int32)
    fin = np.isfinite(F).all(axis=1)
    cfin = np.concatenate([[0], np.cumsum(fin)])            # kullanılabilir (sonlu) geçmiş sayımı için
    cut = int(round(k * 3 / 4))
    Fz = np.where(np.isfinite(F), F, 0.0).astype(np.float32)
    for c0 in range(max(t_from, 0), t_to, chunk):
        tt = np.arange(c0, min(c0 + chunk, t_to), dtype=np.int64)
        m = len(tt)
        q = Fz[tt]                                           # (m, nf)
        qok = fin[tt]
        jlo = tt - lag - (window - 1)
        jhi = tt - lag
        hist = cfin[np.clip(jhi + 1, 0, n)] - cfin[np.clip(np.maximum(jlo, 0), 0, n)]
        hist = np.where(jhi >= 0, hist, 0)
        D = np.zeros((m, k + 1), dtype=np.float32)
        Y = np.zeros((m, k + 1), dtype=np.float32)
        cnt = np.zeros(m, dtype=np.int16)
        last = np.full(m, -1.0, dtype=np.float32)
        ar = np.arange(m)
        for p in range(window):
            j = jlo + p
            ok = (j >= 0) & (j <= jhi) & qok
            if mod4 == "pine":
                ok &= (j & 3) != 0
            elif mod4 == "eq0":
                ok &= (j & 3) == 0
            jc = np.where(ok, j, 0)
            ok &= fin[jc]
            if not ok.any():
                continue
            d = np.log1p(np.abs(Fz[jc] - q)).sum(axis=1)
            cond = ok & (d >= last)
            idx = np.flatnonzero(cond)
            if len(idx) == 0:
                continue
            ci = cnt[idx]
            D[idx, ci] = d[idx]
            Y[idx, ci] = y[jc[idx]]
            cnt[idx] = ci + 1
            last[idx] = d[idx]
            ov = idx[cnt[idx] > k]
            if len(ov):
                last[ov] = D[ov, cut]
                D[ov, :-1] = D[ov, 1:]
                Y[ov, :-1] = Y[ov, 1:]
                cnt[ov] = k
        valid = qok & (hist >= min_hist) & (cnt > 0)
        mask = np.arange(k + 1)[None, :] < cnt[:, None]
        s = (Y * mask).sum(axis=1)
        md = (D * mask).sum(axis=1) / np.maximum(cnt, 1)
        pred[tt] = np.where(valid, s, np.nan)
        meand[tt] = np.where(valid, md, np.nan)
        nn_out[tt] = cnt
        hist_out[tt] = hist
    return {"pred": pred, "meand": meand, "nn": nn_out, "hist": hist_out}


def ann_predict_bruteforce(F: np.ndarray, y: np.ndarray, t: int, *, lag: int, k: int = K_DEFAULT, window: int = WINDOW_DEFAULT,
                           mod4: str = "pine") -> tuple[float, list[float]]:
    """Tek bar için Pine döngüsünün satır satır (yavaş) karşılığı - testlerde `ann_predict` ile karşılaştırmak için."""
    dist: list[float] = []
    pr: list[float] = []
    last = -1.0
    jlo = t - lag - (window - 1)
    for j in range(max(jlo, 0), t - lag + 1):
        if mod4 == "pine" and j % 4 == 0:
            continue
        if mod4 == "eq0" and j % 4 != 0:
            continue
        if not np.isfinite(F[j]).all():
            continue
        d = float(np.log1p(np.abs(F[j].astype(np.float32) - F[t].astype(np.float32))).sum())
        if d >= last:
            last = d
            dist.append(d); pr.append(float(y[j]))
            if len(pr) > k:
                last = dist[int(round(k * 3 / 4))]
                dist.pop(0); pr.pop(0)
    return float(sum(pr)), dist


# ------------------------------------------------------------------------------------------------ filtreler / çekirdek
def filter_volatility(h, l, c, min_len: int = 1, max_len: int = 10) -> np.ndarray:
    h = np.asarray(h, dtype=float); l = np.asarray(l, dtype=float); c = np.asarray(c, dtype=float)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    a1 = tr if min_len == 1 else rma(tr, min_len)
    a2 = rma(tr, max_len)
    with np.errstate(invalid="ignore"):
        return np.isfinite(a2) & (a1 > a2)


def regime_filter(ohlc4, h, l, threshold: float = -0.1) -> np.ndarray:
    """KLMF eğim düşüşü >= eşik (MLExtensions.regime_filter)."""
    src = np.asarray(ohlc4, dtype=float); h = np.asarray(h, dtype=float); l = np.asarray(l, dtype=float)
    n = len(src)
    d = np.zeros(n)
    d[1:] = np.diff(src)
    v1 = lfilter([0.2], [1.0, -0.8], d)
    v2 = lfilter([0.1], [1.0, -0.8], h - l)
    with np.errstate(divide="ignore", invalid="ignore"):
        omega = np.abs(v1 / v2)
    omega = np.minimum(np.where(np.isfinite(omega), omega, 0.0), 1e3)      # düz mumlarda v2 -> 0: omega^4 taşmasın (alfa -> 1)
    alpha = (-omega ** 2 + np.sqrt(omega ** 4 + 16.0 * omega ** 2)) / 8.0
    klmf = np.zeros(n)
    prev = 0.0
    for i in range(n):                                      # zamanla değişen alfa -> sıralı (n ~ 26k, hızlı)
        prev = alpha[i] * src[i] + (1.0 - alpha[i]) * prev
        klmf[i] = prev
    slope = np.zeros(n)
    slope[1:] = np.abs(np.diff(klmf))
    e = ema(slope, 200)
    with np.errstate(divide="ignore", invalid="ignore"):
        dec = (slope - e) / e
    return np.isfinite(dec) & (dec >= threshold)


def kernel_bullish(close, h: float = 8.0, r: float = 8.0, x: int = 25) -> np.ndarray:
    """RQK boğa renk: yhat[t-1] < yhat[t]; pencere 0..x+1 (x+2 örnek)."""
    y = _rqk._yhat(np.asarray(close, dtype=float), int(x) + 2, float(h), float(r))
    p1 = _rqk.lag(y, 1)
    with np.errstate(invalid="ignore"):
        return np.isfinite(y) & (p1 < y)


def signal_from(pred: np.ndarray, filt_ok: np.ndarray) -> np.ndarray:
    """Betik sinyali: pred>0 ∧ filtre -> +1, pred<0 ∧ filtre -> -1, aksi halde bir önceki. int8."""
    sig = np.zeros(len(pred), dtype=np.int8)
    cur = 0
    p = np.nan_to_num(pred, nan=0.0)
    for i in range(len(pred)):
        if filt_ok[i]:
            if p[i] > 0:
                cur = 1
            elif p[i] < 0:
                cur = -1
        sig[i] = cur
    return sig


def lorentzian(o, h, l, c, *, label_mode: str = "future", k: int = K_DEFAULT, window: int = WINDOW_DEFAULT, mod4: str = "pine",
               use_volatility: bool = True, use_regime: bool = True, regime_thr: float = -0.1, use_kernel: bool = True,
               min_hist: int = 500, t_from: int = 0, t_to: int | None = None, spec=DEFAULT_FEATURES) -> dict:
    """Tüm hat. Dönüş: pred, sig, entry_long (yeni LONG sinyali ∧ çekirdek boğa), filt, bull, feats, meand."""
    c = np.asarray(c, dtype=float)
    F = build_features(o, h, l, c, spec)
    if label_mode == "pine":
        y, lag = labels_pine(c), 0
    elif label_mode == "future":
        y, lag = labels_future(c), HORIZON
    else:
        raise ValueError("label_mode 'pine' ya da 'future'")
    r = ann_predict(F, y, lag=lag, k=k, window=window, mod4=mod4, min_hist=min_hist, t_from=t_from, t_to=t_to)
    n = len(c)
    ok = np.ones(n, dtype=bool)
    if use_volatility:
        ok &= filter_volatility(h, l, c)
    if use_regime:
        ok &= regime_filter((np.asarray(o, float) + np.asarray(h, float) + np.asarray(l, float) + c) / 4.0, h, l, regime_thr)
    bull = kernel_bullish(c) if use_kernel else np.ones(n, dtype=bool)
    sig = signal_from(r["pred"], ok)
    chg = np.zeros(n, dtype=bool)
    chg[1:] = sig[1:] != sig[:-1]
    entry = (sig == 1) & chg & bull
    return {"pred": r["pred"], "meand": r["meand"], "hist": r["hist"], "sig": sig, "entry_long": entry, "filt": ok, "bull": bull, "feats": F}


# ------------------------------------------------------------------------------------------------ Varyant B: bizim etiket + bizim özellikler
OUR_FEATURE_NAMES = ("atr14_pct", "ret1", "ret10", "ema50_99_gap", "taker3", "vol_ratio", "range_pos24")
EVENT_HORIZON = 12            # 12 x 5 dk = 60 dk
EVENT_PCT = 1.5


def _roll_sum(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.concatenate([[0.0], np.cumsum(x)])
        out[n - 1:] = cs[n:] - cs[:-n]
    return out


def our_features(o, h, l, c, qv, tbq) -> np.ndarray:
    """Yedi nedensel özellik (5 dk, t barı kapanışında bilinen): 5m ATR14% (SMA TR), ret1 %, ret10 %, EMA50/EMA99 farkı %,
    3 barlık taker alış payı (tbq/qv), hacim oranı (qv / önceki 24 barın ort. qv), 24 bar aralık konumu. (n, 7) float32; ısınma NaN."""
    o = np.asarray(o, float); h = np.asarray(h, float); l = np.asarray(l, float); c = np.asarray(c, float)
    qv = np.nan_to_num(np.asarray(qv, float), nan=0.0); tbq = np.nan_to_num(np.asarray(tbq, float), nan=0.0)
    n = len(c)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = sma(tr, 14) / c * 100.0
    ret1 = np.full(n, np.nan); ret1[1:] = (c[1:] / c[:-1] - 1.0) * 100.0
    ret10 = np.full(n, np.nan); ret10[10:] = (c[10:] / c[:-10] - 1.0) * 100.0
    e50, e99 = ema(c, 50), ema(c, 99)
    gap = (e50 - e99) / e99 * 100.0
    q3, t3 = _roll_sum(qv, 3), _roll_sum(tbq, 3)
    with np.errstate(divide="ignore", invalid="ignore"):
        taker3 = np.where(q3 > 0, t3 / q3, 0.5)
    prev24 = np.full(n, np.nan)
    s24 = _roll_sum(qv, 24)
    prev24[24:] = s24[23:-1] / 24.0
    with np.errstate(divide="ignore", invalid="ignore"):
        vr = np.where(prev24 > 0, qv / prev24, np.nan)
    vr = np.minimum(vr, 20.0)
    hh = np.full(n, np.nan); ll = np.full(n, np.nan)
    if n >= 24:
        hh[23:] = np.lib.stride_tricks.sliding_window_view(h, 24).max(axis=1)
        ll[23:] = np.lib.stride_tricks.sliding_window_view(l, 24).min(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rp = np.where(hh > ll, (c - ll) / (hh - ll), 0.5)
    F = np.column_stack([atr, ret1, ret10, gap, taker3, vr, rp]).astype(np.float32)
    F[:100] = np.nan                     # EMA99 ısınması
    return F


def causal_squash(F: np.ndarray, win: int = 2000, min_periods: int = 200, clip: float = 3.0) -> np.ndarray:
    """Her sütunu YALNIZ geçmişe (t dâhil, son `win` bar) bakan z-skoruyla [0, 1]'e çevirir: (clip(z, ±clip) + clip) / (2 clip). NaN korunur."""
    F = np.asarray(F, dtype=np.float64)
    n, nf = F.shape
    out = np.full((n, nf), np.nan)
    for j in range(nf):
        x = F[:, j]
        ok = np.isfinite(x)
        x0 = np.where(ok, x, 0.0)
        cs = np.concatenate([[0.0], np.cumsum(x0)]); cs2 = np.concatenate([[0.0], np.cumsum(x0 * x0)]); cn = np.concatenate([[0], np.cumsum(ok)])
        i = np.arange(n)
        lo = np.maximum(i + 1 - win, 0)
        cnt = cn[i + 1] - cn[lo]
        s = cs[i + 1] - cs[lo]
        s2 = cs2[i + 1] - cs2[lo]
        with np.errstate(divide="ignore", invalid="ignore"):
            mu = s / cnt
            sd = np.sqrt(np.maximum(s2 / cnt - mu * mu, 0.0))
            z = np.where((cnt >= min_periods) & (sd > 1e-12), (x - mu) / sd, np.nan)
        out[:, j] = (np.clip(z, -clip, clip) + clip) / (2 * clip)
    out[~ok_rows(F)] = np.nan
    return out.astype(np.float32)


def ok_rows(F: np.ndarray) -> np.ndarray:
    return np.isfinite(F).all(axis=1)


def event_label(o, h, horizon: int = EVENT_HORIZON, pct: float = EVENT_PCT) -> tuple[np.ndarray, np.ndarray]:
    """t barı kapanışında karar -> giriş = t+1 AÇILIŞI; olay = t+1..t+horizon yüksekleri >= giriş x (1+pct/100) (60 dk MFE).
    Dönüş: (ev int8: 1/0, pencere tamamlanmadıysa -1 ; mfe_pct float32 (NaN ...)). Etiket t+horizon kapanışında bilinir."""
    o = np.asarray(o, float); h = np.asarray(h, float)
    n = len(o)
    mfe = np.full(n, np.nan)
    if n > horizon + 1:
        w = np.lib.stride_tricks.sliding_window_view(h[1:], horizon).max(axis=1)      # w[i] = max(h[i+1 .. i+horizon])
        m = n - 1 - horizon + 1
        mfe[:m] = (w[:m] / o[1:1 + m] - 1.0) * 100.0
    ev = np.where(np.isfinite(mfe), (mfe >= pct).astype(np.int8), np.int8(-1)).astype(np.int8)
    return ev, mfe.astype(np.float32)


def knn_event(F_raw: np.ndarray, ev: np.ndarray, *, k: int = K_DEFAULT, window: int = WINDOW_DEFAULT, min_hist: int = 500,
              mod4: str = "pine", win_norm: int = 2000) -> dict:
    """Varyant B: aynı ANN/Lorentzian makinesi, etiket = olay (0/1), gecikme = 12 bar. Skor = komşular arasındaki olay sayısı (0..k)."""
    Fn = causal_squash(F_raw, win_norm)
    y = np.where(ev > 0, 1.0, 0.0).astype(np.float32)     # -1 (tamamlanmamış) bar geçmişe zaten girmez (lag = horizon)
    return ann_predict(Fn, y, lag=EVENT_HORIZON, k=k, window=window, mod4=mod4, min_hist=min_hist)
