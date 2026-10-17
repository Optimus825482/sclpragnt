"""Altcoin rotasyonu çalışması için SAF yardımcılar (2026-10-17, çevrimdışı araştırma; canlı koda BAĞLANMAZ, DB'ye dokunmaz).

Girdiler saatlik paneller: (T, S) — T saat (satır), S sembol. Satır j = j. saatlik bar; karar o barın KAPANIŞINDA (yalnız [..j] verisi),
dolum fiyatı PX[j] (karar anından sonraki ilk ~15 dk barın açılışı). `r[j]` = PX[j−1] → PX[j] basit getirisi (j anına kadar birikir).

Sözleşme (tests/test_rotation.py): `topk_weights` eşit ağırlıklı k'lı sepet; `simulate_sleeve` ağırlıkları fiyatla sürükler, yeniden dengede
yalnız |Δw| × (ücret+kayma) öder (devir temelli maliyet); `deflated_sharpe` Bailey & López de Prado (2014).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

EULER_GAMMA = 0.5772156649015329


# ------------------------------------------------------------------------------------------------ sepet seçimi
def topk_weights(score: np.ndarray, valid: np.ndarray, k: int, largest: bool = True, min_valid: int = 20) -> np.ndarray:
    """(T, S) skor → (T, S) hedef ağırlık: her satırda geçerli ∧ sonlu skorlu semboller arasında en yüksek (largest) / en düşük k sembole 1/k.
    Geçerli sembol sayısı < min_valid ise satır boş (nakit). Sonlu skorlu aday sayısı < k ise var olanlar yine 1/k alır (kalan nakit)."""
    score = np.asarray(score, dtype=float)
    T, S = score.shape
    ok = np.asarray(valid, dtype=bool) & np.isfinite(score)
    key = np.where(ok, score if largest else -score, -np.inf)
    out = np.zeros((T, S))
    kk = min(k, S)
    if kk < 1:
        return out
    idx = np.argpartition(-key, kk - 1, axis=1)[:, :kk]
    rows = np.arange(T)[:, None]
    picked = np.isfinite(key[rows, idx])
    w = np.zeros((T, S))
    w[rows, idx] = np.where(picked, 1.0 / k, 0.0)
    enough = ok.sum(axis=1) >= min_valid
    return np.where(enough[:, None], w, out)


# ------------------------------------------------------------------------------------------------ portföy simülasyonu
def simulate_sleeve(r: np.ndarray, w_target: np.ndarray, rebal: np.ndarray, cost_leg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Tek 'kol' (sleeve): r (T,S) saatlik getiri (NaN → 0), w_target (T,S) hedef ağırlıklar, rebal (T,) bool.
    Her saat j: önce mevcut ağırlıklarla getiri birikir (gross[j] = w·r[j]) ve ağırlıklar fiyatla sürüklenir; sonra rebal[j] ise hedefe geçilir ve
    |Δw| toplamı × cost_leg (bacak başına oran = ücret+kayma) portföy değerinden düşülür (net[j] = gross[j] − maliyet).
    Dönüş: (net, gross, turn) — hepsi (T,); turn[j] = Σ|Δw| (alış+satış, portföy payı; yalnız rebal saatlerinde ≠ 0)."""
    r = np.nan_to_num(np.asarray(r, dtype=float), nan=0.0)
    w_target = np.asarray(w_target, dtype=float)
    T, S = r.shape
    net, gross, turn = np.zeros(T), np.zeros(T), np.zeros(T)
    w = np.zeros(S)
    for j in range(T):
        g = float(w @ r[j])
        gross[j] = g
        if w.any():
            w = w * (1.0 + r[j]) / (1.0 + g)
        net[j] = g
        if rebal[j]:
            tv = float(np.abs(w_target[j] - w).sum())
            net[j] = g - tv * cost_leg
            turn[j] = tv
            w = w_target[j].copy()
    return net, gross, turn


def daily_compound(r: np.ndarray, hours_per_day: int = 24) -> np.ndarray:
    """Saatlik getiri (T,) → günlük bileşik getiri (⌊T/24⌋,). Yarım son gün atılır."""
    r = np.asarray(r, dtype=float)
    D = len(r) // hours_per_day
    return np.prod(1.0 + r[: D * hours_per_day].reshape(D, hours_per_day), axis=1) - 1.0


def max_drawdown(r: np.ndarray) -> float:
    """Getiri serisinden (bileşik) en büyük tepe-dip düşüşü (negatif oran, ör. −0,12). Boş → 0."""
    r = np.asarray(r, dtype=float)
    if r.size == 0:
        return 0.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float((eq / peak - 1.0).min())


def total_return(r: np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    return float(np.prod(1.0 + r) - 1.0) if r.size else 0.0


# ------------------------------------------------------------------------------------------------ Sharpe / DSR
def sharpe(r: np.ndarray) -> float:
    """Periyot başına Sharpe (ort/std, ddof=1); <2 gözlem ya da sıfır std → NaN."""
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return float("nan")
    sd = float(r.std(ddof=1))
    return float(r.mean() / sd) if sd > 1e-12 * (abs(float(r.mean())) + 1e-12) else float("nan")


def moments(r: np.ndarray) -> tuple[float, float]:
    """(çarpıklık, TAM basıklık [normal = 3]); sapma 0 ise (0, 3)."""
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 3:
        return 0.0, 3.0
    d = r - r.mean()
    s2 = float((d ** 2).mean())
    if s2 <= 0:
        return 0.0, 3.0
    return float((d ** 3).mean() / s2 ** 1.5), float((d ** 4).mean() / s2 ** 2)


def expected_max_sr(n_trials: int, sr_var: float) -> float:
    """Eşit-sıfır Sharpe'lı n bağımsız denemenin beklenen maksimum Sharpe'ı (Bailey & LdP): sqrt(Var[SR]) · ((1−γ)Φ⁻¹(1−1/n) + γΦ⁻¹(1−1/(n·e)))."""
    if n_trials <= 1 or not sr_var > 0:
        return 0.0
    return math.sqrt(sr_var) * ((1.0 - EULER_GAMMA) * norm.ppf(1.0 - 1.0 / n_trials) + EULER_GAMMA * norm.ppf(1.0 - 1.0 / (n_trials * math.e)))


def deflated_sharpe(sr_hat: float, n_obs: int, skew: float, kurt: float, n_trials: int, sr_var: float) -> float:
    """Deflated Sharpe Oranı = P[gerçek SR > 0 | n_trials denemenin en iyisi]. sr_hat periyot başına Sharpe (örn. günlük), n_obs gözlem sayısı,
    kurt TAM basıklık. n_trials=1 → Olasılıksal Sharpe (PSR, eşik 0). 0,5 civarı = şanstan ayırt edilemez; ≥ 0,95 güçlü."""
    if not (math.isfinite(sr_hat) and n_obs > 1):
        return float("nan")
    sr0 = expected_max_sr(n_trials, sr_var)
    denom = 1.0 - skew * sr_hat + (kurt - 1.0) / 4.0 * sr_hat ** 2
    if denom <= 0:
        return float("nan")
    return float(norm.cdf((sr_hat - sr0) * math.sqrt(n_obs - 1) / math.sqrt(denom)))


def min_track_record(sr_hat: float, skew: float, kurt: float, sr0: float = 0.0, conf: float = 0.95) -> float:
    """Gözlenen Sharpe'ın sr0'dan `conf` güvenle ayırt edilmesi için gereken gözlem (periyot) sayısı (MinTRL, Bailey & LdP):
    1 + (1 − skew·SR + (kurt−1)/4·SR²)·(z_conf/(SR − sr0))². SR ≤ sr0 ise sonsuz."""
    if not (math.isfinite(sr_hat) and sr_hat > sr0):
        return float("inf")
    return 1.0 + (1.0 - skew * sr_hat + (kurt - 1.0) / 4.0 * sr_hat ** 2) * (norm.ppf(conf) / (sr_hat - sr0)) ** 2
