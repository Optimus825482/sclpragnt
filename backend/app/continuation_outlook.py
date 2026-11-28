"""Yükseliş devamı görünümü ("daha yukarı gider mi, nereye kadar?").

AMAÇ
----
Grafik asistanı "yükselme isteği var mı, nereye kadar çıkar?" sorusuna
uydurma seviye/olasılıkla değil, **hazır hesaplanmış** sayılarla cevap versin:

* trend hizası (1h/4h EMA + MACD yönü),
* momentum ve yorulma işaretleri (RSI, hacim temposu),
* yukarıdaki ilk engel (1h swing direnci / Fibonacci uzantısı) ve ATR cinsinden
  mesafe,
* sembolün KENDİ son 7 gününde aynı yüzdenin 24 saat içinde görülme oranı
  (ampirik taban oran) ve medyan süre,
* tek satırlık hazır cümle (`sentence`) — model bunu aynen kullanabilir.

Tüm hesaplar saf Python'dur (numpy yok); ağ çağrısı yalnız `build()` içindedir.
"""

from __future__ import annotations

import math
import time
from statistics import median

from app.binance_tr_public import klines

MINUTE_MS = 60_000
HORIZON_HOURS = 24
LOOKBACK_DAYS = 7


# ---------------------------------------------------------------- indikatörler
def _closes(rows) -> list[float]:
    return [float(r[4]) for r in rows]


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    out = sum(values[:period]) / period
    for value in values[period:]:
        out = value * k + out * (1 - k)
    return out


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains = closes = 0.0
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains += max(change, 0.0)
        closes += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, closes / period
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def atr(rows, period: int = 14) -> float | None:
    if len(rows) <= period:
        return None
    ranges = []
    for index in range(1, len(rows)):
        high, low = float(rows[index][2]), float(rows[index][3])
        prev_close = float(rows[index - 1][4])
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(ranges[-period:]) / period


def macd_hist(values: list[float]) -> float | None:
    if len(values) < 35:
        return None
    fast, slow = ema(values, 12), ema(values, 26)
    if fast is None or slow is None:
        return None
    return fast - slow


def swing_highs(rows, lookback: int = 60) -> list[float]:
    highs = [float(r[2]) for r in rows[-lookback:]]
    return [highs[i] for i in range(1, len(highs) - 1) if highs[i] >= highs[i - 1] and highs[i] >= highs[i + 1]]


def swing_lows(rows, lookback: int = 60) -> list[float]:
    lows = [float(r[3]) for r in rows[-lookback:]]
    return [lows[i] for i in range(1, len(lows) - 1) if lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1]]


def reach_rate(rows15m, upside_pct: float, horizon_bars: int = HORIZON_HOURS * 4) -> dict:
    """Son 7 günde aynı yüzdenin ufuk içinde görülme oranı ve medyan süresi."""
    closes = _closes(rows15m)
    highs = [float(r[2]) for r in rows15m]
    if upside_pct is None or upside_pct <= 0 or len(closes) < 50:
        return {"rate_pct": None, "median_hours": None, "samples": 0}
    hits, hours = 0, []
    limit = min(len(closes), LOOKBACK_DAYS * 96)
    start = max(0, len(closes) - limit)
    samples = 0
    for index in range(start, len(closes) - 1):
        target = closes[index] * (1 + upside_pct / 100)
        window = highs[index + 1 : index + 1 + horizon_bars]
        if not window:
            continue
        samples += 1
        for offset, value in enumerate(window, start=1):
            if value >= target:
                hits += 1
                hours.append(offset * 15 / 60)
                break
    if not samples:
        return {"rate_pct": None, "median_hours": None, "samples": 0}
    return {
        "rate_pct": round(100 * hits / samples, 1),
        "median_hours": round(median(hours), 1) if hours else None,
        "samples": samples,
    }


def _volume_ratio(rows, recent: int = 4) -> float | None:
    volumes = [float(r[5]) for r in rows]
    if len(volumes) < 40:
        return None
    base = sum(volumes[-40:-recent]) / max(1, 40 - recent)
    if base <= 0:
        return None
    return sum(volumes[-recent:]) / recent / base


# ---------------------------------------------------------------- görünüm
def outlook_from_klines(rows_15m, rows_1h, rows_4h) -> dict:
    """Hazır yükseliş görünümü. Ağ yok; yalnız verilen mumlar kullanılır."""
    if not rows_1h or len(rows_1h) < 60:
        return {"status": "unavailable", "reason": "insufficient_candles"}

    price = float(rows_1h[-1][4])
    c1h, c4h = _closes(rows_1h), _closes(rows_4h) if rows_4h else []
    e20, e50 = ema(c1h[-120:], 20), ema(c1h[-200:], 50)
    e20_4, e50_4 = (ema(c4h[-120:], 20), ema(c4h[-200:], 50)) if len(c4h) >= 50 else (None, None)
    rsi_1h, rsi_4h = rsi(c1h[-120:]), (rsi(c4h[-120:]) if len(c4h) > 20 else None)
    hist_1h = macd_hist(c1h[-120:])
    hist_4h = macd_hist(c4h[-120:]) if len(c4h) > 40 else None
    atr_1h = atr(rows_1h)
    atr_pct = round(atr_1h / price * 100, 2) if atr_1h and price else None
    vol_ratio = _volume_ratio(rows_15m or rows_1h)

    score = 0
    for value, reference in ((price, e20), (e20, e50), (price, e20_4), (e20_4, e50_4)):
        if value is not None and reference is not None and value > reference:
            score += 1
    if hist_1h is not None and hist_1h > 0:
        score += 1
    if hist_4h is not None and hist_4h > 0:
        score += 1
    max_score = 6

    # Yukarıdaki ilk engel: fiyatın üstündeki en yakın 1h swing tepesi
    above = [high for high in swing_highs(rows_1h) if high > price]
    resistance = min(above) if above else None
    resistance_source = "1h_swing_high"
    if resistance is None:
        # Engel yoksa ATR tabanlı ilk uzantı kullanılır (uydurma seviye değil).
        if atr_1h:
            resistance = price + 2 * atr_1h
            resistance_source = "atr_2x_extension"
        else:
            resistance_source = None
    upside_pct = round((resistance / price - 1) * 100, 2) if resistance else None
    atr_multiple = round((resistance - price) / atr_1h, 2) if resistance and atr_1h else None

    rate = reach_rate(rows_15m or [], upside_pct)

    supports = [low for low in swing_lows(rows_1h) if low < price]
    invalidation = max(supports) if supports else (price - 2 * atr_1h if atr_1h else None)

    exhausted = bool(
        (rsi_4h is not None and rsi_4h >= 75)
        or (rsi_1h is not None and rsi_1h >= 80)
        or (vol_ratio is not None and vol_ratio < 0.8 and score >= 4)
    )
    if score >= 5 and not exhausted:
        verdict, label = "DEVAM_EDER", "yükseliş devam edebilir"
    elif exhausted:
        verdict, label = "DONUS_RISKI", "istek var ama yorulmuş; dönüş riski yüksek"
    elif score >= 4:
        verdict, label = "DEVAM_EDER", "yükseliş eğilimi korunuyor"
    elif score <= 2:
        verdict, label = "ZAYIF", "yükselme isteği zayıf"
    else:
        verdict, label = "ZAYIF", "kararsız; teyit gerekli"

    parts = [f"{label} (trend {score}/{max_score})"]
    if upside_pct is not None and resistance is not None:
        parts.append(
            f"ilk engel {resistance:.8g} (+%{upside_pct:.2f}"
            + (f", {atr_multiple:g} ATR" if atr_multiple is not None else "")
            + ")"
        )
    if rate.get("rate_pct") is not None:
        parts.append(
            f"son {LOOKBACK_DAYS} günde bu mesafeyi {HORIZON_HOURS} saatte görme oranı %{rate['rate_pct']}"
            + (f" (medyan {rate['median_hours']:g} sa)" if rate.get("median_hours") else "")
        )
    if invalidation is not None:
        parts.append(f"yükseliş bu senaryoda {invalidation:.8g} altı kapanışta bozulur")

    return {
        "status": "ok",
        "symbol_price": price,
        "verdict": verdict,
        "label": label,
        "sentence": "; ".join(parts) + ".",
        "trend_score": score,
        "trend_max_score": max_score,
        "exhausted": exhausted,
        "ema_1h_20": e20,
        "ema_1h_50": e50,
        "ema_4h_20": e20_4,
        "ema_4h_50": e50_4,
        "rsi_1h": round(rsi_1h, 1) if rsi_1h is not None else None,
        "rsi_4h": round(rsi_4h, 1) if rsi_4h is not None else None,
        "macd_hist_1h": round(hist_1h, 8) if hist_1h is not None else None,
        "macd_hist_4h": round(hist_4h, 8) if hist_4h is not None else None,
        "atr_pct_1h": atr_pct,
        "volume_ratio_1h": round(vol_ratio, 2) if vol_ratio is not None else None,
        "upside_target": resistance,
        "upside_target_source": resistance_source,
        "upside_pct": upside_pct,
        "upside_atr_multiple": atr_multiple,
        "reach_rate": rate,
        "invalidation": invalidation,
        "horizon_hours": HORIZON_HOURS,
        "as_of": time.time(),
    }


async def build(symbol: str) -> dict:
    """Sembol için hazır görünüm (4 kline isteği). Hata → fail-open sözlük."""
    symbol = str(symbol or "").replace("_", "").upper()
    if not symbol:
        return {"status": "unavailable", "reason": "no_symbol"}
    try:
        rows_15m = await klines(symbol, "15m", 700)
        rows_1h = await klines(symbol, "1h", 200)
        rows_4h = await klines(symbol, "4h", 200)
    except Exception as exc:  # noqa: BLE001 — asistan yolunu düşürmemeli
        return {"status": "unavailable", "reason": "candle_fetch_failed", "detail": str(exc)[:120]}
    if not rows_1h:
        return {"status": "unavailable", "reason": "no_candles"}
    return outlook_from_klines(rows_15m, rows_1h, rows_4h)
