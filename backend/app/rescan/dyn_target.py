"""Sinyal anında bilinen bilgiyle DİNAMİK hedef (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ).

Soru: bildirim hedefi sabit (%2,5 / 3 / 4) ama her sembolün sinyal anındaki durumu farklı (oynaklık, 24 sa zirveye
yakınlık, yakın zirve, geçmiş potansiyel). Hedef sembolün durumundan türetilirse ve TÜM maliyetler düşülünce net hedef
%2'nin altındaysa bildirim atılmazsa kârlılık artar mı? Bu modül yalnız hedefi üretir (ileriye bakmadan: t anından
SONRA oluşan hiçbir bar kullanılmaz); politika ölçümü `scripts/policy7d_study.py` içindedir.

Üç varyant (hepsi "brüt hedef", % olarak, giriş fiyatına göre):
  (a) ATR ölçekli      : k × ATR14(5m)% × sqrt(ufuk_dk / 5)
  (b) direnç payı      : min( (a), pay × en yakın direnç mesafesi ), direnç = 24 sa en yüksek ve son 60 dk en yüksek
                         (fiyatın `tol_pct` üzerindeki en yakın seviye; fiyat tüm seviyelerin üstündeyse direnç yok → (a))
  (c) ampirik potansiyel: sembolün KENDİ ufuk-MFE'sinin ÖNCEKİ 14 günlük q'luk yüzdelik değeri
                         (MFE_a = max(5m yüksekler[a+1..a+n]) / kapanış[a] − 1, pencere t'den önce tamamen kapanmış)
Net hedef = brüt − (2 × ücret bacağı + giriş kayması + çıkış kayması).

Nedensellik: "kapanmış bar" = açılış + bar süresi ≤ t. Tüm fonksiyonlar t'den sonraki verinin değişmesinin sonucu
DEĞİŞTİRMEDİĞİNİ sağlar (testle doğrulanır, bkz. tests/test_dyn_target.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FEE_LEG_PCT = 0.1125          # BNB taker, bacak başına (%)
FEE_MAKER_PCT = 0.0675        # 2026-10-17: BNB maker (kâr al bekleyen LIMIT), bacak başına (%)
BAR1 = 60_000
BAR5 = 300_000
DAY_MS = 86_400_000


# ------------------------------------------------------------------------------------------------ maliyet / net hedef
def round_trip_cost_pct(slip_in_pct: float = 0.15, slip_out_pct: float = 0.0, fee_leg_pct: float = FEE_LEG_PCT,
                        fee_exit_leg_pct: float = FEE_MAKER_PCT) -> float:
    """Hedefe ulaşan işlemin gidiş-dönüş maliyeti (%): giriş ücreti (taker) + giriş kayması + çıkış ücreti + çıkış kayması.

    2026-10-17: kâr al bekleyen LIMIT emirdir → çıkış maker (%0,0675) ve kaymasız. Varsayılan
    0,1125 + 0,15 + 0,0675 + 0 = %0,33 (eski: iki taker bacak + iki kayma = %0,525).
    """
    return fee_leg_pct + slip_in_pct + fee_exit_leg_pct + slip_out_pct


def net_target_pct(gross_pct, cost_pct: float | None = None):
    """Brüt hedef − toplam maliyet. NaN korunur."""
    c = round_trip_cost_pct() if cost_pct is None else cost_pct
    return np.asarray(gross_pct, dtype=float) - c


# ------------------------------------------------------------------------------------------------ yardımcılar
def last_closed_index(open_time: np.ndarray, t_ms, bar_ms: int) -> np.ndarray:
    """t'den ÖNCE (açılış + süre ≤ t) kapanmış son barın indeksi; yoksa -1."""
    return np.searchsorted(np.asarray(open_time) + bar_ms, np.asarray(t_ms, dtype=np.int64), side="right") - 1


def atr_target_pct(atr_pct, horizon_min, k: float):
    """(a) k × ATR14(5m)% × sqrt(ufuk/5). atr_pct NaN → NaN."""
    return k * np.asarray(atr_pct, dtype=float) * np.sqrt(np.asarray(horizon_min, dtype=float) / 5.0)


def rolling_max(x: np.ndarray, window: int) -> np.ndarray:
    """out[i] = max(x[i-window+1..i]); i < window-1 için NaN (tam pencere yoksa belirsiz)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) < window:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    out[window - 1:] = sliding_window_view(x, window).max(axis=1)
    return out


def mfe_forward_pct(open5: np.ndarray, h5: np.ndarray, c5: np.ndarray, n: int) -> np.ndarray:
    """M[a] = (max(h5[a+1..a+n]) / c5[a] − 1) × 100. Pencere zaman-sürekli değilse (eksik bar) veya sona taşarsa NaN."""
    h5 = np.asarray(h5, dtype=float)
    c5 = np.asarray(c5, dtype=float)
    ot = np.asarray(open5, dtype=np.int64)
    m = len(h5)
    out = np.full(m, np.nan)
    if m <= n:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    w = sliding_window_view(h5[1:], n)             # w[a] = h5[a+1..a+n]
    mx = w.max(axis=1)
    cnt = len(mx)
    cont = (ot[n:n + cnt] - ot[:cnt]) == n * BAR5   # a .. a+n sürekli
    ok = cont & (c5[:cnt] > 0)
    out[:cnt] = np.where(ok, (mx / c5[:cnt] - 1.0) * 100.0, np.nan)
    return out


@dataclass
class SymbolCandles:
    """Tek sembolün 1m + 5m mumları (artan open_time, ms)."""
    open1: np.ndarray
    h1: np.ndarray
    open5: np.ndarray
    h5: np.ndarray
    l5: np.ndarray
    c5: np.ndarray

    def __post_init__(self):
        self._rm24 = rolling_max(self.h5, 288)
        self._mfe_cache: dict[int, np.ndarray] = {}

    def rm24(self) -> np.ndarray:
        return self._rm24

    def mfe_fwd(self, n: int) -> np.ndarray:
        arr = self._mfe_cache.get(n)
        if arr is None:
            arr = mfe_forward_pct(self.open5, self.h5, self.c5, n)
            self._mfe_cache[n] = arr
        return arr


# ------------------------------------------------------------------------------------------------ (b) direnç
def peak_levels(sc: SymbolCandles, t_ms: np.ndarray, peak_min: int = 60) -> tuple[np.ndarray, np.ndarray]:
    """(son `peak_min` dk 1m en yüksek, 24 sa en yüksek [5m kapanmış + son peak]) — t'den önce kapanmış barlardan.
    Veri yoksa NaN."""
    t_ms = np.asarray(t_ms, dtype=np.int64)
    n = len(t_ms)
    last1 = last_closed_index(sc.open1, t_ms, BAR1)
    idx = last1[:, None] - np.arange(peak_min, dtype=np.int64)[None, :]
    ok = idx >= 0
    idx_c = np.clip(idx, 0, len(sc.open1) - 1)
    ok &= sc.open1[idx_c] >= (t_ms[:, None] - peak_min * BAR1)
    ok &= (last1 >= 0)[:, None]
    hv = np.where(ok, sc.h1[idx_c], -np.inf)
    peak = hv.max(axis=1) if n else np.array([])
    peak = np.where(np.isfinite(peak), peak, np.nan)
    last5 = last_closed_index(sc.open5, t_ms, BAR5)
    h24 = np.where(last5 >= 0, sc.rm24()[np.clip(last5, 0, len(sc.open5) - 1)], np.nan)
    # 24 sa penceresi tam değilse NaN → peak'e düş
    h24 = np.fmax(h24, peak)
    return peak, h24


def room_to_resistance_pct(price, peak60, high24, tol_pct: float = 0.3, levels: str = "both") -> np.ndarray:
    """Fiyatın `tol_pct` üzerindeki EN YAKIN direnç seviyesine yüzde mesafe (inf: direnç yok).
    levels: 'both' (60 dk zirve + 24 sa zirve) | 'h24' | 'peak60'."""
    price = np.asarray(price, dtype=float)
    lv = []
    if levels in ("both", "peak60"):
        lv.append(np.asarray(peak60, dtype=float))
    if levels in ("both", "h24"):
        lv.append(np.asarray(high24, dtype=float))
    best = np.full(price.shape, np.inf)
    for L in lv:
        d = (L / price - 1.0) * 100.0
        valid = np.isfinite(d) & (d >= tol_pct)
        best = np.where(valid, np.minimum(best, d), best)
    return best


# ------------------------------------------------------------------------------------------------ (c) ampirik
def empirical_upside_pct(sc: SymbolCandles, t_ms, horizon_min, lookback_days: int = 14, q: float = 0.6,
                         min_anchors: int = 500) -> np.ndarray:
    """Sembolün kendi ufuk-MFE dağılımının ÖNCEKİ `lookback_days` günlük q'luk yüzdeliği (%). Pencereleri t'den ÖNCE
    tamamen kapanmış çapalar (a ≤ son_kapanmış − n). Yetersiz çapa → NaN. horizon_min skaler ya da dizi."""
    t_ms = np.asarray(t_ms, dtype=np.int64)
    hz = np.broadcast_to(np.asarray(horizon_min, dtype=int), t_ms.shape)
    out = np.full(len(t_ms), np.nan)
    last5 = last_closed_index(sc.open5, t_ms, BAR5)
    for h in np.unique(hz):
        n = max(1, int(round(h / 5)))
        M = sc.mfe_fwd(n)
        for i in np.where(hz == h)[0]:
            hi = last5[i] - n          # son çapa (dahil): a+n ≤ last5 → a ≤ last5−n
            if hi < 0:
                continue
            lo = int(np.searchsorted(sc.open5, t_ms[i] - lookback_days * DAY_MS, side="left"))
            if hi - lo + 1 < min_anchors:
                continue
            seg = M[lo:hi + 1]
            seg = seg[np.isfinite(seg)]
            if len(seg) >= min_anchors:
                out[i] = float(np.quantile(seg, q))
    return out


# ------------------------------------------------------------------------------------------------ birleşik
@dataclass(frozen=True)
class DynParams:
    k_atr: float = 1.5            # (a) ATR çarpanı
    room_frac: float = 0.9        # (b) direnç mesafesinin hedefe çevrilen payı
    room_tol_pct: float = 0.3
    room_levels: str = "both"
    emp_q: float = 0.6            # (c) yüzdelik
    emp_days: int = 14
    min_gross_pct: float = 0.0    # altı → hedef yok (NaN)


def compute_targets(sc: SymbolCandles, t_ms, price, horizon_min, atr_pct, params: DynParams = DynParams(),
                    emp: np.ndarray | None = None) -> dict:
    """Bir sembolün sinyal anları için üç varyantın brüt hedefi (%) + bileşenler.
    `emp`: önceden hesaplanmış (c) dizisi (k değişince yeniden hesaplamamak için).
    Dönüş: dict(a, b, c, atr, room, emp, peak60, high24) — hepsi (N,) float."""
    t_ms = np.asarray(t_ms, dtype=np.int64)
    price = np.asarray(price, dtype=float)
    a = atr_target_pct(atr_pct, horizon_min, params.k_atr)
    peak, h24 = peak_levels(sc, t_ms)
    room = room_to_resistance_pct(price, peak, h24, params.room_tol_pct, params.room_levels)
    b = np.where(np.isfinite(room), np.fmin(a, params.room_frac * room), a)
    b = np.where(np.isfinite(a), b, np.nan)
    c = emp if emp is not None else empirical_upside_pct(sc, t_ms, horizon_min, params.emp_days, params.emp_q)
    out = {"a": a, "b": b, "c": c, "atr": np.asarray(atr_pct, dtype=float), "room": room, "emp": c,
           "peak60": peak, "high24": h24}
    return out
