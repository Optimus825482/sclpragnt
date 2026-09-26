"""MACD MTF konfluans (2026-09-26): kullanıcının grafik metodunun makineye çevirisi.

Kullanıcı kuralı (Erkan, 2026-09-26): M1/M3/M5/M15'te MACD çizgisi Signal'i
AŞAĞIDAN YUKARI kesiyorsa YA DA her iki çizgi PARALEL YUKARI yönlü ise
yükseliş gerçektir; yalnızca tek TF'de görünen hareket fake'tir. Bu modül o
bakışı otomatikleştirir: her TF için kesişim durumu + yaşı, iki çizginin
eğimi ve "paralel yukarı" bayrağı; özet konfluans skoru LLM ikinci-göz
kanıdına ve pulse/warm satır rozetlerine gider.

Kaynak seriler `market.get_ut_kline` KAPANMIŞ mum serisidir — macd_monitor
hücreleriyle AYNI kaynak (`green` değerleri birebir uyuşur, iki görünüm
karşılaştırılabilir kalır). Eksik TF için `market.refresh_series` ile tek
REST tazelemesi yapılır; sonuç 60 sn TTL ile önbelleklenir.
"""
import logging
import time

import numpy as np

from app.state import market
from app.technical_analysis import _ema_series

logger = logging.getLogger("scalper.macd_mtf")

TFS = ("1m", "3m", "5m", "15m")
FAST, SLOW, SIGNAL = 12, 26, 9
_MIN_CANDLES = SLOW + SIGNAL + 15          # anlamlı seri tabanı (50 bar)
_SLOPE_WINDOW = 5                          # eğim penceresi (kapanmış bar)
_FRESH_CROSS_MAX_BARS = 3                  # "taze kesişim" yaşı (bar)
_MAX_SERIES = 150
_CACHE_TTL_SEC = 60.0
_REFRESH_PER_CALL = 12                     # refresh_many için sembol tavanı

_cache: dict[str, tuple[float, dict]] = {}
_inflight: set[str] = set()


def _norm(symbol: str) -> str:
    return str(symbol or "").replace("_", "").upper().strip()


def _ols_slope(values: list[float]) -> float:
    """Basit OLS eğimi (bar başına). <2 geçerli değer → 0.0."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = np.arange(n, dtype=float)
    ys = np.asarray(values, dtype=float)
    x_mean = float(xs.mean())
    y_mean = float(ys.mean())
    denom = float(((xs - x_mean) ** 2).sum())
    if denom == 0:
        return 0.0
    return float(((xs - x_mean) * (ys - y_mean)).sum() / denom)


def _macd_full_series(closes: list[float]) -> tuple[list, list] | None:
    """MACD + Signal çizgi serileri (kapanmış mumlar). Yetersizse None.

    `technical_analysis._macd` yalnızca SON değerleri döndürür; kesişim yaşı
    ve eğim için tam seriler gerekir — aynı 12/26/9 tanımı burada üretilir.
    """
    if len(closes) < _MIN_CANDLES:
        return None
    arr = np.asarray(closes, dtype=float)
    ema_fast = _ema_series(arr, FAST)
    ema_slow = _ema_series(arr, SLOW)
    macd = [f - s if (f is not None and s is not None) else None
            for f, s in zip(ema_fast, ema_slow)]
    valid_pos = [i for i, v in enumerate(macd) if v is not None]
    if len(valid_pos) < SIGNAL + 2:
        return None
    valid_vals = np.asarray([macd[i] for i in valid_pos], dtype=float)
    sig_valid = _ema_series(valid_vals, SIGNAL)
    signal = [None] * len(macd)
    for pos, i in enumerate(valid_pos):
        signal[i] = sig_valid[pos]
    # Sonu SİGONAL warmup'ı bozmasın: son _SLOPE_WINDOW+1 değer tam dolu olmalı.
    tail = signal[-(SIGNAL + 1):]
    if any(v is None for v in tail):
        return None
    return macd, signal


def _tf_cell(symbol: str, tf: str) -> dict | None:
    """Tek TF hücresi: kesişim durumu/yaşı + eğimler + paralel yukarı."""
    history = market.get_ut_kline(symbol, tf)
    closes = list((history or {}).get("closes") or [])
    if len(closes) < _MIN_CANDLES:
        return None
    closes = closes[-_MAX_SERIES:]
    series = _macd_full_series(closes)
    if series is None:
        return None
    macd, signal = series
    last_close = float(closes[-1]) or 1.0

    bullish_now = bool(macd[-1] > signal[-1])
    age = 0
    while len(macd) - age - 1 > 0 and macd[-age - 2] is not None and signal[-age - 2] is not None:
        prev_bullish = macd[-age - 2] > signal[-age - 2]
        if prev_bullish != bullish_now:
            break
        age += 1

    def _pct_slope(line: list) -> float:
        window = [v for v in line[-_SLOPE_WINDOW:] if v is not None]
        if len(window) < 3:
            return 0.0
        return round(_ols_slope(window) / last_close * 100.0, 4)

    macd_slope = _pct_slope(macd)
    signal_slope = _pct_slope(signal)
    return {
        "tf": tf,
        "macd": round(float(macd[-1]), 10),
        "signal": round(float(signal[-1]), 10),
        "hist": round(float(macd[-1] - signal[-1]), 10),
        "green": bullish_now,
        "cross_age_bars": age,
        "macd_slope_pct": macd_slope,
        "signal_slope_pct": signal_slope,
        "parallel_up": bool(macd_slope > 0 and signal_slope > 0),
        "fresh_bull_cross": bool(bullish_now and age <= _FRESH_CROSS_MAX_BARS),
    }


def _summarize(symbol: str, cells: list[dict | None]) -> dict:
    available = [c for c in cells if c]
    base = {
        "symbol": symbol,
        "tfs": TFS,
        "coverage": len(available),
        "confluence": None,
        "verdict": "VERİ YOK",
        "green_count": 0,
        "parallel_up_count": 0,
        "fresh_cross": [],
        "cells": [],
    }
    if len(available) < 2:
        return base
    green_count = sum(1 for c in available if c["green"])
    parallel_count = sum(1 for c in available if c["parallel_up"])
    fresh = [c["tf"] for c in available if c["fresh_bull_cross"]]
    # Ağırlık: yeşil (MACD>signal durumu) %60 + paralel yukarı (momentum) %40.
    # Taze kesişim bonusu: başlangıç profili (kullanıcının "baştan yakalama").
    score = (0.6 * green_count + 0.4 * parallel_count) / len(available) * 80.0
    if fresh:
        score += 20.0
    confluence = round(min(100.0, score), 1)
    if confluence >= 75.0:
        verdict = "GÜÇLÜ"
    elif confluence >= 45.0:
        verdict = "ORTA"
    else:
        verdict = "ZAYIF"
    base.update({
        "confluence": confluence,
        "verdict": verdict,
        "green_count": green_count,
        "parallel_up_count": parallel_count,
        "fresh_cross": fresh,
        "cells": available,
    })
    return base


async def compute(symbol: str, *, force: bool = False) -> dict | None:
    """Sembol için MACD MTF konfluansını hesaplar (60 sn TTL önbellekli)."""
    sym = _norm(symbol)
    if not sym:
        return None
    now = time.time()
    cached = _cache.get(sym)
    if cached and not force and now - cached[0] < _CACHE_TTL_SEC:
        return cached[1]
    if sym in _inflight:
        # Aynı sembol için yarışan ikinci çağrı: bayat değer varsa onu dön.
        return cached[1] if cached else None
    _inflight.add(sym)
    try:
        cells: list[dict | None] = []
        for tf in TFS:
            try:
                cell = _tf_cell(sym, tf)
                if cell is None:
                    # Mağazada bar yok: tek REST tazelemesi, sonra bir kez daha dene.
                    try:
                        await market.refresh_series(sym, tf, limit=_MAX_SERIES)
                    except Exception as exc:
                        logger.debug("macd_mtf refresh_series %s/%s: %s", sym, tf, exc)
                    cell = _tf_cell(sym, tf)
            except Exception as exc:
                logger.debug("macd_mtf hücre %s/%s: %s", sym, tf, exc)
                cell = None
            cells.append(cell)
        result = _summarize(sym, cells)
        stamp = time.time()
        result["computed_at"] = stamp
        _cache[sym] = (stamp, result)
        return result
    finally:
        _inflight.discard(sym)


def cached_compact(symbol: str) -> dict | None:
    """Senkron önbellek okuması — /state üretimini ASLA bloklamaz.

    Taze ya da bayat farketmez: kayıt varsa bayatlık `age_sec` ile birlikte
    döner (arayüz rozeti bayat veriyi soluk gösterebilir). Kayıt yoksa None.
    """
    entry = _cache.get(_norm(symbol))
    if not entry:
        return None
    stamp, result = entry
    compact = dict(result)
    compact.pop("cells", None)
    compact["age_sec"] = round(time.time() - stamp, 1)
    return compact


async def refresh_many(symbols: list[str]) -> int:
    """Verilen sembollerin önbelleğini tazeler (sıralı, tavanlı, hata yutucu).

    Fire-and-forget çağrılır: tarama döngüsünü bekletmez. Dönüş: tazelenen sayı.
    """
    refreshed = 0
    for sym in [s for s in (_norm(x) for x in (symbols or [])) if s][:_REFRESH_PER_CALL]:
        try:
            result = await compute(sym)
            if result is not None:
                refreshed += 1
        except Exception as exc:
            logger.debug("macd_mtf refresh_many %s: %s", sym, exc)
    return refreshed


def reset_state_for_tests() -> None:
    _cache.clear()
    _inflight.clear()
