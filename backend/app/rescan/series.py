"""Sembol başına numpy serileri: kapanmış-bar indeksi, ön-filtre, 24s ticker aynası, havuz.

Ön-filtre (`prefilter_mask`) canlı `passes` için GEREKLİ koşulların vektörel
karşılığıdır (BB genişliği, ATR tabanı, MFI uçları, bar sayısı). Pencereye bağlı
olmayan göstergelerle kurulduğu için TAM pencere taramasının sonucunu değiştirmez;
yalnızca geçemeyecek tick'lerde pahalı `scan_symbol_at_tick` çağrısını atlar.
RSI (Wilder, pencereye bağlı) ve fitil/yapısal kapılar ön-filtreye GİRMEZ.
"""
from __future__ import annotations

import math

import numpy as np

from app.config import config
from app.routers import velocity as V

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000}
# Sütun indeksleri (historical_candles -> kline satırı)
COL_OPEN_TIME, COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE, COL_VOL, COL_CLOSE_TIME, COL_QVOL, COL_TRADES = range(9)
_TOL = 1e-9


class SymbolSeries:
    """Tek sembol × tek zaman dilimi; `arr` sütunları: open_time, o, h, l, c, v, close_time, qv, trades."""

    def __init__(self, symbol: str, tf: str, arr: np.ndarray):
        self.symbol = str(symbol).upper()
        self.tf = tf
        self.tf_ms = TF_MS[tf]
        if arr.ndim != 2 or arr.shape[1] < 9:
            raise ValueError("SymbolSeries: 9 sütun bekleniyor")
        self.arr = np.asarray(arr, dtype=np.float64)
        self.open_time = self.arr[:, COL_OPEN_TIME].astype(np.int64)

    def __len__(self):
        return len(self.open_time)

    def closed_index(self, tick_ms: int) -> int:
        """`tick_ms` anında kapanmış SON barın indeksi; yoksa -1."""
        # open + tf <= tick  <=>  open <= tick - tf
        return int(np.searchsorted(self.open_time, int(tick_ms) - self.tf_ms, side="right")) - 1

    def window_rows(self, tick_ms: int, n: int) -> list[list]:
        """Son `n` kapanmış bar, kline satırı listesi olarak (scan girişi)."""
        j = self.closed_index(tick_ms)
        if j < 0:
            return []
        lo = max(0, j - n + 1)
        return self.arr[lo:j + 1].tolist()

    def last_close_at(self, tick_ms: int) -> float | None:
        j = self.closed_index(tick_ms)
        return float(self.arr[j, COL_CLOSE]) if j >= 0 else None


# ---------------------------------------------------------------- ön-filtre --

def _rolling_sum(x: np.ndarray, n: int) -> np.ndarray:
    """out[j] = sum(x[j-n+1..j]); j < n-1 -> nan."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1:] = c[n:] - c[:-n]
    return out


def bar_features(arr: np.ndarray) -> dict[str, np.ndarray]:
    """Her bar indeksi j için (o barı son kapanmış bar sayarak) ATR14%, BB20 genişliği %, MFI14."""
    h = arr[:, COL_HIGH]; l = arr[:, COL_LOW]; c = arr[:, COL_CLOSE]; v = arr[:, COL_VOL]
    n = len(c)
    nan = np.full(n, np.nan)
    if n < 21:
        return {"atr_pct": nan, "bb_width": nan, "mfi": nan}
    prev = np.empty(n); prev[0] = np.nan; prev[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    tr[0] = np.nan
    atr14 = _rolling_sum(np.nan_to_num(tr, nan=0.0), 14) / 14.0
    atr14[:14] = np.nan  # ilk 14 TR'de prev-close yok (kanonik _atr len>=15 ister)
    atr_pct = np.where(c > 0, atr14 / np.where(c > 0, c, 1.0) * 100.0, np.nan)
    s1 = _rolling_sum(c, 20); s2 = _rolling_sum(c * c, 20)
    mean = s1 / 20.0
    var = np.maximum(s2 / 20.0 - mean * mean, 0.0)
    std = np.sqrt(var)
    bb_width = np.where(mean != 0, (4.0 * std) / np.where(mean != 0, mean, 1.0) * 100.0, np.nan)
    tp = (h + l + c) / 3.0
    flow = tp * v
    tp_prev = np.empty(n); tp_prev[0] = np.nan; tp_prev[1:] = tp[:-1]
    pos = np.where(tp > tp_prev, flow, 0.0)
    neg = np.where(tp < tp_prev, flow, 0.0)
    pos[0] = 0.0; neg[0] = 0.0
    ps = _rolling_sum(pos, 14); ns = _rolling_sum(neg, 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        mfi = np.where(ns > 0, 100.0 - 100.0 / (1.0 + ps / np.where(ns > 0, ns, 1.0)),
                       np.where(ps > 0, 100.0, 50.0))
    mfi[:14] = np.nan
    return {"atr_pct": atr_pct, "bb_width": bb_width, "mfi": mfi}


def prefilter_mask(feats: dict[str, np.ndarray], *, prof_atr: float, min_atr_pct: float) -> np.ndarray:
    """Bar j'de canlı `passes`'ın GEREKLİ koşulları (bb, atr tabanı, mfi uçları)."""
    bb = feats["bb_width"]; atr = feats["atr_pct"]; mfi = feats["mfi"]
    breakout_floor = min(prof_atr, max(min_atr_pct, prof_atr * 0.6))
    ok = np.isfinite(bb) & np.isfinite(atr) & np.isfinite(mfi)
    ok &= bb >= V.VELOCITY_MIN_BB_WIDTH_PCT * (1 - _TOL)
    ok &= atr >= breakout_floor * (1 - _TOL)
    ok &= (mfi < V.VELOCITY_MFI_UPPER * (1 + _TOL)) & (mfi > V.VELOCITY_MFI_LOWER * (1 - _TOL))
    j = np.arange(len(bb))
    ok &= j >= 29  # len(rows) >= 30
    return ok


# ------------------------------------------------------------- 24s ticker --

def _rolling_max(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = w.max(axis=1)
    return out


def _rolling_min(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = w.min(axis=1)
    return out


def ticker_24h_at_ticks(series: SymbolSeries, ticks_ms: np.ndarray) -> dict[str, np.ndarray]:
    """5m seriden her tick için `/ticker/24hr` aynası.

    priceChangePercent = close(j)/close(j-288)-1 (24s = 288 × 5m), quoteVolume = son 288
    barın quote_volume toplamı, high/low = 288-bar uç değerleri, count = trade_count
    toplamı, lastPrice = close(j). Veri eksikse NaN (-> havuz/kapı için "bilinmiyor").
    """
    arr = series.arr
    n = len(arr)
    bars = 288 if series.tf == "5m" else int(86_400_000 // series.tf_ms)
    c = arr[:, COL_CLOSE]
    nan = np.full(len(ticks_ms), np.nan)
    if n < bars + 1:
        return {"change": nan.copy(), "qvol": nan.copy(), "high": nan.copy(), "low": nan.copy(),
                "count": nan.copy(), "last": nan.copy()}
    c_prev = np.full(n, np.nan); c_prev[bars:] = c[:-bars]
    with np.errstate(divide="ignore", invalid="ignore"):
        change = np.where(c_prev > 0, (c / np.where(c_prev > 0, c_prev, 1.0) - 1.0) * 100.0, np.nan)
    qvol = _rolling_sum(np.nan_to_num(arr[:, COL_QVOL], nan=0.0), bars)
    cnt = _rolling_sum(np.nan_to_num(arr[:, COL_TRADES], nan=0.0), bars)
    hi = _rolling_max(arr[:, COL_HIGH], bars)
    lo = _rolling_min(arr[:, COL_LOW], bars)
    idx = np.searchsorted(series.open_time, ticks_ms.astype(np.int64) - series.tf_ms, side="right") - 1
    valid = idx >= 0
    # Bayat seri (son bar tick'ten >2 tf eski) -> ticker'da da bayat olurdu; yine de
    # canlı ticker ölü sembolü listeler. Burada bayatlığı 24s'ye kadar tolere ederiz.
    stale = np.zeros(len(ticks_ms), dtype=bool)
    stale[valid] = (ticks_ms[valid] - series.open_time[idx[valid]]) > 86_400_000
    valid &= ~stale
    safe = np.where(valid, idx, 0)

    def pick(x):
        out = np.full(len(ticks_ms), np.nan)
        out[valid] = x[safe[valid]]
        return out

    return {"change": pick(change), "qvol": pick(qvol), "high": pick(hi), "low": pick(lo),
            "count": pick(cnt), "last": pick(c)}


def discovery_at_ticks(series1m: SymbolSeries, ticks_ms: np.ndarray) -> dict[str, np.ndarray]:
    """`early_discovery.top_candidates` aynası (1m kapanmış barlardan).

    return_1m_pct = close(j)/close(j-1)-1; volume_burst = qv(j) / max(medyan(qv[j-10..j-1]), taban).
    Canlı akış ~saniyelik örneklerle ölçer; burada 1m bar yaklaşımıdır (belgelenmiş sapma).
    """
    arr = series1m.arr
    n = len(arr)
    nan = np.full(len(ticks_ms), np.nan)
    if n < 12:
        return {"ret": nan.copy(), "burst": nan.copy()}
    c = arr[:, COL_CLOSE]; qv = np.nan_to_num(arr[:, COL_QVOL], nan=0.0)
    ret = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret[1:] = np.where(c[:-1] > 0, (c[1:] / np.where(c[:-1] > 0, c[:-1], 1.0) - 1.0) * 100.0, np.nan)
    med = np.full(n, np.nan)
    w = np.lib.stride_tricks.sliding_window_view(qv, 10)  # pencere j-10..j-1 -> w[j-10]
    med[10:] = np.median(w[:-1], axis=1) if len(w) > 1 else np.nan
    floor = float(getattr(config, "DISCOVERY_VOLUME_MEDIAN_FLOOR", 1.0) or 1.0)
    burst = np.where(np.isfinite(med), qv / np.maximum(med, floor), np.nan)
    idx = np.searchsorted(series1m.open_time, ticks_ms.astype(np.int64) - series1m.tf_ms, side="right") - 1
    valid = idx >= 0
    # Son 1m bar tick'ten en çok 2 dk eski olmalı (canlı: örnek yaşı <= 15 sn; 2 dk'da düşer).
    stale = np.zeros(len(ticks_ms), dtype=bool)
    stale[valid] = (ticks_ms[valid] - series1m.open_time[idx[valid]]) > 180_000
    valid &= ~stale
    safe = np.where(valid, idx, 0)
    o_ret = np.full(len(ticks_ms), np.nan); o_ret[valid] = ret[safe[valid]]
    o_b = np.full(len(ticks_ms), np.nan); o_b[valid] = burst[safe[valid]]
    return {"ret": o_ret, "burst": o_b}


# ------------------------------------------------------------------ havuz --

GAINER_MIN_QVOL = 5_000_000.0        # binance_tr_public._MIN_QUOTE_VOLUME["TRY"]
MOVER_MIN_QVOL = GAINER_MIN_QVOL * 0.5


def build_pool_matrix(symbols: list[str], tick24: dict[str, dict[str, np.ndarray]],
                      disc: dict[str, dict[str, np.ndarray]] | None, n_ticks: int, *,
                      universe: str = "top-gainers-daily",
                      gainer_n: int | None = None, mover_n: int | None = None,
                      discovery_n: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Her tick için havuz üyeliği (S×T bool) ve kaynak kodu (S×T int8: 0 yok,
    1 gainer, 2 mover, 3 discovery, 4 symbol). Canlı sıra: gainer → mover → discovery → SYMBOLS.
    `universe="all"` -> 24s hacmi bilinen/bilinmeyen tüm semboller (kaynak 5=all)."""
    S = len(symbols)
    gainer_n = int(gainer_n if gainer_n is not None else config.VELOCITY_POOL_SIZE)
    mover_n = int(mover_n if mover_n is not None else getattr(config, "DYNAMIC_ACTIVE_POOL_LIMIT", 15))
    discovery_n = int(discovery_n if discovery_n is not None else getattr(config, "DISCOVERY_POOL_INJECT_LIMIT", 8))
    src = np.zeros((S, n_ticks), dtype=np.int8)
    if universe == "all":
        src[:] = 5
        return src > 0, src
    change = np.full((S, n_ticks), np.nan); qvol = np.full((S, n_ticks), np.nan)
    hi = np.full((S, n_ticks), np.nan); lo = np.full((S, n_ticks), np.nan)
    cnt = np.full((S, n_ticks), np.nan); last = np.full((S, n_ticks), np.nan)
    for s, sym in enumerate(symbols):
        t = tick24.get(sym)
        if not t:
            continue
        change[s] = t["change"]; qvol[s] = t["qvol"]; hi[s] = t["high"]; lo[s] = t["low"]
        cnt[s] = t["count"]; last[s] = t["last"]
    # 1) top gainers: qvol >= 5M, change desc, ilk N
    g_score = np.where(np.isfinite(change) & (qvol >= GAINER_MIN_QVOL), change, -np.inf)
    _assign_topn(src, g_score, gainer_n, code=1)
    # 2) active movers: qvol >= 2.5M, last>0, hi>lo, range_pos>=0.4, day_range>=1%, activity desc
    with np.errstate(divide="ignore", invalid="ignore"):
        rng = hi - lo
        range_pos = np.where(rng > 0, (last - lo) / np.where(rng > 0, rng, 1.0), np.nan)
        day_range = np.where(lo > 0, rng / np.where(lo > 0, lo, 1.0) * 100.0, np.nan)
        act = ((range_pos * 40.0)
               + np.minimum(1.0, qvol / (GAINER_MIN_QVOL * 5.0)) * 30.0
               + np.minimum(1.0, cnt / 5000.0) * 30.0) * (1.0 + np.minimum(1.0, day_range / 10.0))
    m_ok = (np.isfinite(act) & (qvol >= MOVER_MIN_QVOL) & (last > 0) & (rng > 0)
            & (range_pos >= 0.40) & (day_range >= 1.0))
    _assign_topn(src, np.where(m_ok, act, -np.inf), mover_n, code=2)
    # 3) discovery: 1m getiri >= 0.4 ve hacim patlaması >= 2.0; |getiri| desc, ilk N
    if disc:
        min_ret = float(getattr(config, "DISCOVERY_MIN_RETURN_1M_PCT", 0.4))
        min_burst = float(getattr(config, "DISCOVERY_MIN_VOLUME_BURST", 2.0))
        d_score = np.full((S, n_ticks), -np.inf)
        for s, sym in enumerate(symbols):
            d = disc.get(sym)
            if not d:
                continue
            ok = np.isfinite(d["ret"]) & np.isfinite(d["burst"]) & (d["ret"] >= min_ret) & (d["burst"] >= min_burst)
            d_score[s] = np.where(ok, np.abs(d["ret"]), -np.inf)
        _assign_topn(src, d_score, discovery_n, code=3)
    # 4) sabit evren (config.SYMBOLS)
    fixed = {str(x).upper() for x in config.SYMBOLS}
    for s, sym in enumerate(symbols):
        if sym in fixed:
            row = src[s]
            row[row == 0] = 4
    return src > 0, src


def _assign_topn(src: np.ndarray, score: np.ndarray, n: int, *, code: int) -> None:
    """Sütun (tick) başına en yüksek `n` skoru al; daha önce atanmamışsa `code` yaz."""
    if n <= 0:
        return
    S, T = score.shape
    k = min(n, S)
    # argsort azalan; -inf olanlar elenir
    order = np.argsort(-score, axis=0, kind="stable")[:k]
    cols = np.arange(T)
    for r in range(k):
        rows = order[r]
        sel = np.isfinite(score[rows, cols]) & (score[rows, cols] > -np.inf) & (src[rows, cols] == 0)
        src[rows[sel], cols[sel]] = code


def pool_source_name(code: int) -> str:
    return {1: "gainer", 2: "mover", 3: "discovery", 4: "symbol", 5: "all"}.get(int(code), "unknown")
