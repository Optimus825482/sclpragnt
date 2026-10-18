"""MA şerit BUY sinyali — saf (ağ/DB yok) hesap; `frontend/app/charts/signals.ts::maRibbonBuySignals` ile BİREBİR.

2026-10-18 (kullanıcı isteği): grafikteki "BUY" rozetinin kuralları taramaya taşındı. İki koşul (bar i kapanışında):
  * `fast_cross_mid`: orta (mavi, 20) > yavaş (mor, 99) iken hızlı (turuncu, 7) ortayı AŞAĞIDAN yukarı keser.
  * `mid_cross_slow`: hızlı > orta iken orta yavaşı AŞAĞIDAN yukarı keser.
2. kural StochRSI K, `stoch_max` (80) üstündeyken tetiklenmez. İki koşul aynı barda olursa TEK sinyal (kurallar birlikte listelenir) — grafik de bar başına tek rozet çizer.
Kesişim = önceki bar a0 <= b0 VE bu bar a1 > b1. Ortalamalar EMA (SMA tohumlu) ya da SMA; ilk geçerli değer
period−1. indeksinde başlar. TS ile eşlik `tests/fixtures/ma_buy_parity.json` (iki tarafta da sınanır).
"""
from __future__ import annotations

import math
from typing import Sequence

RULE_FAST_CROSS_MID = "fast_cross_mid"
RULE_MID_CROSS_SLOW = "mid_cross_slow"
ALL_RULES = (RULE_FAST_CROSS_MID, RULE_MID_CROSS_SLOW)
DEFAULT_PERIODS = (7, 20, 99)


def _period(value) -> int:
    """TS `Math.max(1, Math.round(x))` ile aynı (yarımlar yukarı)."""
    return max(1, int(math.floor(float(value) + 0.5)))


def ema_series(values: Sequence[float], period) -> list:
    """SMA tohumlu EMA (TS `emaSeries`): out[period-1] = ilk `period` değerin ortalaması; alpha = 2/(n+1)."""
    n = _period(period)
    out: list = [None] * len(values)
    if len(values) < n:
        return out
    alpha = 2.0 / (n + 1)
    total = 0.0
    for i in range(n):
        total += values[i]
    prev = total / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def sma_series(values: Sequence[float], period) -> list:
    """Kayan toplamlı SMA (TS `smaSeries` ile aynı işlem sırası → aynı kayan nokta sonucu)."""
    n = _period(period)
    out: list = [None] * len(values)
    total = 0.0
    for i in range(len(values)):
        total += values[i]
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def _cross_up(a0: float, b0: float, a1: float, b1: float) -> bool:
    """Yukarı kesişim; göreli 1e-9 tolerans (TS `maCrossUp` ile aynı) → kayan nokta farkı sahte kesişim üretmez."""
    return a0 <= b0 + abs(b0) * 1e-9 and a1 > b1 + abs(b1) * 1e-9


def rsi_series(values: Sequence[float], period: int) -> list:
    """Wilder RSI (TS `rsiSeries`): ilk `period` bar tanımsız."""
    out: list = [None] * len(values)
    if len(values) < period + 1:
        return out
    gain = loss = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        if d > 0:
            gain += d
        else:
            loss -= d
    avg_gain, avg_loss = gain / period, loss / period

    def to_rsi():
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100 - 100 / (1 + avg_gain / avg_loss)

    out[period] = to_rsi()
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
        out[i] = to_rsi()
    return out


def _sma_opt(src: list, length: int) -> list:
    out: list = [None] * len(src)
    for i in range(len(src)):
        if i < length - 1:
            continue
        window = src[i - length + 1:i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum(window) / length
    return out


def stoch_rsi_k(values: Sequence[float], rsi_len: int = 14, stoch_len: int = 14, k_len: int = 3) -> list:
    """StochRSI K çizgisi (TS `stochRsi(...).k` ile aynı tanım)."""
    r = rsi_series(values, rsi_len)
    stoch: list = [None] * len(r)
    for i, cur in enumerate(r):
        if cur is None or i < stoch_len - 1:
            continue
        window = r[i - stoch_len + 1:i + 1]
        if any(v is None for v in window):
            continue
        hi, lo = max(window), min(window)
        stoch[i] = 0.0 if hi == lo else 100 * (cur - lo) / (hi - lo)
    return _sma_opt(stoch, k_len)


def detect_ma_buy(closes: Sequence[float], periods: Sequence = DEFAULT_PERIODS, use_sma: bool = False,
                  slow_cross: bool = True, stoch_max: float | None = 80.0, stoch_params: Sequence = (14, 14, 3)) -> list:
    """Kapanış serisinde tüm BUY sinyalleri: [{index, rules, fast, mid, slow}] (indeks artan).

    `slow_cross=False` → yalnız `fast_cross_mid` (grafikteki "showMaSlowCross" kapalı hâli).
    """
    fast_len, mid_len, slow_len = (periods[0], periods[1], periods[2])
    stoch_k = (stoch_rsi_k(closes, *stoch_params)
               if slow_cross and stoch_max is not None and stoch_max < 100 else None)
    fn = sma_series if use_sma else ema_series
    fast, mid, slow = fn(closes, fast_len), fn(closes, mid_len), fn(closes, slow_len)
    out: list = []
    for i in range(1, len(closes)):
        f0, m0, s0 = fast[i - 1], mid[i - 1], slow[i - 1]
        f1, m1, s1 = fast[i], mid[i], slow[i]
        if f0 is None or m0 is None or f1 is None or m1 is None or s1 is None:
            continue
        cond1 = m1 > s1 and _cross_up(f0, m0, f1, m1)
        cond2 = bool(slow_cross) and s0 is not None and f1 > m1 and _cross_up(m0, s0, m1, s1)
        # 2026-10-18 (kullanıcı kuralı): 2. kural StochRSI K > stoch_max (80) iken tetiklenmez; K tanımsızsa engellemez.
        if cond2 and stoch_k is not None and stoch_k[i] is not None and stoch_k[i] > stoch_max:
            cond2 = False
        rules = []
        if cond1:
            rules.append(RULE_FAST_CROSS_MID)
        if cond2:
            rules.append(RULE_MID_CROSS_SLOW)
        if rules:
            out.append({"index": i, "rules": rules, "fast": f1, "mid": m1, "slow": s1})
    return out


def outcome_metrics(signal_price: float, bars_after: Sequence[dict], bar_minutes: int, horizon_min: int = 15):
    """Sinyalden sonraki `horizon_min` dk için ölçüm (YÜZDE, sinyal mumu KAPANIŞINA göre) ya da veri eksikse None.

    `bars_after`: sinyal mumundan SONRAKİ kapanmış mumlar, artan sırada; [{high, low, close}] (en az horizon/bar mum).
    Dönüş: max_rise_5m/10m/15m_pct (kümülatif en yüksek), max_drop_15m_pct (en düşük), close_15m_pct, peak_bar_minutes
    (zirve mumunun kapanış dakikası: 5 / 10 / 15). Mum süresi 5 dk'yı bölmüyorsa ilgili ara dilim None kalır.
    """
    price = float(signal_price)
    bar_minutes = max(1, int(bar_minutes))
    need = max(1, horizon_min // bar_minutes)
    if price <= 0 or len(bars_after) < need:
        return None
    use = list(bars_after[:need])

    def pct(x: float) -> float:
        return round((float(x) / price - 1.0) * 100.0, 4)

    metrics: dict = {}
    for minutes in (5, 10, 15):
        bars_needed = minutes // bar_minutes if minutes % bar_minutes == 0 else 0
        if bars_needed < 1 or bars_needed > need:
            metrics[f"max_rise_{minutes}m_pct"] = None
            continue
        metrics[f"max_rise_{minutes}m_pct"] = pct(max(float(b["high"]) for b in use[:bars_needed]))
    highs = [float(b["high"]) for b in use]
    peak_idx = max(range(len(highs)), key=lambda k: (highs[k], -k))   # eşitte İLK zirve
    metrics["max_drop_15m_pct"] = pct(min(float(b["low"]) for b in use))
    metrics["close_15m_pct"] = pct(use[-1]["close"])
    metrics["peak_bar_minutes"] = (peak_idx + 1) * bar_minutes
    return metrics
