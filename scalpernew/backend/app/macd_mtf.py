"""MACD MTF konfluans (2026-09-26): kullanıcının grafik metodunun makineye çevirisi.

Kullanıcı kuralı (Erkan, 2026-09-26): M1/M3/M5/M15/M30'da MACD çizgisi Signal'i
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
import asyncio
import logging
import time

import numpy as np

from app.state import market
from app.technical_analysis import _ema_series

logger = logging.getLogger("scalper.macd_mtf")

TFS = ("1m", "3m", "5m", "15m")
SCAN_DEFAULT_TFS = ("1m", "3m", "5m", "15m", "30m")
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



def _detect_squeeze(highs: list[float], lows: list[float], closes: list[float], period: int = 20) -> bool:
    """John Carter Squeeze: Bollinger Bantları Keltner Kanalı içinde mi (enerji sıkışması)?"""
    if len(closes) < period + 1:
        return False
    wc = np.asarray(closes[-period:], dtype=float)
    sma = float(np.mean(wc))
    std = float(np.std(wc))
    bb_upper = sma + 2.0 * std
    bb_lower = sma - 2.0 * std

    h = np.asarray(highs[-period:] if highs and len(highs) >= period else wc, dtype=float)
    l = np.asarray(lows[-period:] if lows and len(lows) >= period else wc, dtype=float)
    prev_c = np.asarray(closes[-period - 1:-1], dtype=float)
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = float(np.mean(tr))
    kc_upper = sma + 1.5 * atr
    kc_lower = sma - 1.5 * atr
    return bool(bb_lower > kc_lower and bb_upper < kc_upper)


def _dema_series(values: np.ndarray, period: int) -> list:
    """Double Exponential Moving Average (DEMA) serisi (Zero-Lag yapıtaşı)."""
    ema1 = _ema_series(values, period)
    valid_ema1 = [v for v in ema1 if v is not None]
    if len(valid_ema1) < period:
        return [None] * len(values)
    ema2 = _ema_series(valid_ema1, period)
    dema = [None] * len(values)
    valid_idx = [i for i, v in enumerate(ema1) if v is not None]
    for pos, i in enumerate(valid_idx):
        if ema2[pos] is not None:
            dema[i] = 2.0 * ema1[i] - ema2[pos]
    return dema


def _zl_macd_status(closes: list[float]) -> tuple[bool, bool]:
    """Zero-Lag MACD durumu: (zl_green, zl_fresh_cross)."""
    if len(closes) < _MIN_CANDLES:
        return False, False
    arr = np.asarray(closes, dtype=float)
    fast = _dema_series(arr, FAST)
    slow = _dema_series(arr, SLOW)
    zl_line = [f - s if (f is not None and s is not None) else None for f, s in zip(fast, slow)]
    valid_pos = [i for i, v in enumerate(zl_line) if v is not None]
    if len(valid_pos) < SIGNAL + 2:
        return False, False
    valid_vals = np.asarray([zl_line[i] for i in valid_pos], dtype=float)
    sig_valid = _ema_series(valid_vals, SIGNAL)
    if len(sig_valid) < 2 or sig_valid[-1] is None or sig_valid[-2] is None:
        return False, False
    curr_zl = valid_vals[-1]
    curr_sig = sig_valid[-1]
    prev_zl = valid_vals[-2]
    prev_sig = sig_valid[-2]
    zl_green = bool(curr_zl > curr_sig)
    zl_fresh_cross = bool(zl_green and prev_zl <= prev_sig)
    return zl_green, zl_fresh_cross


def _wavetrend_status(highs: list[float], lows: list[float], closes: list[float]) -> tuple[bool, bool]:
    """WaveTrend durumu: (wt_bullish, wt_oversold_cross)."""
    from app.technical_analysis import _wavetrend
    h = highs if highs and len(highs) == len(closes) else closes
    l = lows if lows and len(lows) == len(closes) else closes
    res = _wavetrend(h, l, closes)
    if not res:
        return False, False
    wt1 = res.get("wt1")
    wt2 = res.get("wt2")
    wt_bullish = bool(wt1 is not None and wt2 is not None and wt1 > wt2)
    wt_oversold_cross = bool(res.get("cross_up") and wt1 is not None and wt1 <= -45.0)
    return wt_bullish, wt_oversold_cross


def _tf_cell(symbol: str, tf: str) -> dict | None:
    """Tek TF hücresi: kesişim durumu/yaşı + eğimler + erken öncüler (trough, squeeze, ZL, WT)."""
    history = market.get_ut_kline(symbol, tf)
    closes = list((history or {}).get("closes") or [])
    if len(closes) < _MIN_CANDLES:
        return None
    closes = closes[-_MAX_SERIES:]
    highs = list((history or {}).get("highs") or [])[-len(closes):]
    lows = list((history or {}).get("lows") or [])[-len(closes):]

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
    prev_hist = float(macd[-2] - signal[-2]) if len(macd) > 1 and macd[-2] is not None and signal[-2] is not None else float(macd[-1] - signal[-1])
    curr_hist = float(macd[-1] - signal[-1])
    expanding = bool(bullish_now and (curr_hist > prev_hist or macd_slope > signal_slope))

    # --- ERKEN ÖNCÜ SİNYALLER (Leading Signals) ---
    # 1. Histogram Dip Dönüşü (Hist Trough / Velocity):
    # Henüz kesişim olmasa bile histogramın dipten yukarı bükülmesi (3-7 bar öncü)
    hist_turn_up = bool(curr_hist > prev_hist)
    hist_trough = bool(hist_turn_up and curr_hist < 0.0)

    # 2. Squeeze (Volatilite Sıkışması / Bollinger-Keltner)
    squeeze_on = _detect_squeeze(highs, lows, closes)

    # 3. Zero-Lag MACD (ZLEMA / DEMA MACD)
    zl_green, zl_fresh = _zl_macd_status(closes)

    # 4. WaveTrend (Oversold Cross & Bullish)
    wt_bullish, wt_os_cross = _wavetrend_status(highs, lows, closes)

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
        "expanding": expanding,
        "fresh_bull_cross": bool(bullish_now and age <= _FRESH_CROSS_MAX_BARS),
        # Erken öncüler:
        "hist_turn_up": hist_turn_up,
        "hist_trough": hist_trough,
        "squeeze": squeeze_on,
        "zl_green": zl_green,
        "zl_fresh_cross": zl_fresh,
        "wt_bullish": wt_bullish,
        "wt_oversold_cross": wt_os_cross,
    }


def _summarize(symbol: str, cells: list[dict | None], tfs: tuple = TFS) -> dict:
    available = [c for c in cells if c]
    base = {
        "symbol": symbol,
        "tfs": tfs,
        "coverage": len(available),
        "confluence": None,
        "verdict": "VERİ YOK",
        "green_count": 0,
        "parallel_up_count": 0,
        "expanding_count": 0,
        "fresh_cross": [],
        "early_trough_count": 0,
        "hist_turn_up_count": 0,
        "squeeze_count": 0,
        "zl_green_count": 0,
        "zl_fresh_cross": [],
        "wt_bullish_count": 0,
        "wt_oversold_cross": [],
        "early_spark": False,
        "cells": [],
    }
    if len(available) < 2:
        return base
    green_count = sum(1 for c in available if c["green"])
    parallel_count = sum(1 for c in available if c["parallel_up"])
    expanding_count = sum(1 for c in available if c.get("expanding"))
    fresh = [c["tf"] for c in available if c["fresh_bull_cross"]]

    # Erken Öncü Sayımları
    early_trough_count = sum(1 for c in available if c.get("hist_trough"))
    hist_turn_up_count = sum(1 for c in available if c.get("hist_turn_up"))
    squeeze_count = sum(1 for c in available if c.get("squeeze"))
    zl_green_count = sum(1 for c in available if c.get("zl_green"))
    zl_fresh = [c["tf"] for c in available if c.get("zl_fresh_cross")]
    wt_bullish_count = sum(1 for c in available if c.get("wt_bullish"))
    wt_os_cross = [c["tf"] for c in available if c.get("wt_oversold_cross")]

    # Erken Kıvılcım (Early Spark):
    # En erken dip dönüşü (>=2 TF'de negatiften yukarı ivmelenme)
    # VEYA Sıkışma + Eğim pozitif VEYA WaveTrend aşırı satım kesişimi
    early_spark = bool(
        early_trough_count >= 2 or
        (squeeze_count >= 1 and hist_turn_up_count >= 2) or
        bool(wt_os_cross) or
        bool(zl_fresh)
    )

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
        "expanding_count": expanding_count,
        "fresh_cross": fresh,
        "early_trough_count": early_trough_count,
        "hist_turn_up_count": hist_turn_up_count,
        "squeeze_count": squeeze_count,
        "zl_green_count": zl_green_count,
        "zl_fresh_cross": zl_fresh,
        "wt_bullish_count": wt_bullish_count,
        "wt_oversold_cross": wt_os_cross,
        "early_spark": early_spark,
        "cells": available,
    })
    return base



async def compute(symbol: str, *, tfs: tuple[str, ...] | None = None, force: bool = False) -> dict | None:
    """Sembol için MACD MTF konfluansını hesaplar (60 sn TTL önbellekli)."""
    sym = _norm(symbol)
    if not sym:
        return None
    active_tfs = tuple(tfs) if tfs else TFS
    cache_key = sym if active_tfs == TFS else f"{sym}:{'_'.join(active_tfs)}"
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and not force and now - cached[0] < _CACHE_TTL_SEC:
        return cached[1]
    if cache_key in _inflight:
        # Aynı sembol için yarışan ikinci çağrı: bayat değer varsa onu dön.
        return cached[1] if cached else None
    _inflight.add(cache_key)
    try:
        cells: list[dict | None] = []
        for tf in active_tfs:
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
        result = _summarize(sym, cells, tfs=active_tfs)
        stamp = time.time()
        result["computed_at"] = stamp
        _cache[cache_key] = (stamp, result)
        return result
    finally:
        _inflight.discard(cache_key)


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


async def scan_market(
    *,
    symbols: list[str] | None = None,
    tfs: tuple[str, ...] = SCAN_DEFAULT_TFS,
    min_verdict: str | None = None,
    fresh_only: bool = False,
    parallel_only: bool = False,
    scope: str = "active",
    force_refresh: bool = False,
) -> dict:
    """Aktif veya tüm Binance (TR/Global) çiftlerinde MACD MTF taraması yapar.

    M1, M3, M5, M15, M30 TF'lerinde MACD & Signal durumunu inceler.
    Kullanıcı metoduna uygun (GÜÇLÜ/ORTA, Taze Kesişim, Paralel Yukarı)
    adayları puanlayıp sıralar.
    """
    t0 = time.time()
    from app.config import config
    from app.state import analyzer

    quote_asset = getattr(config, "QUOTE_ASSET", "TRY") or "TRY"
    quote_asset = quote_asset.upper()

    target_symbols: list[str] = []
    if symbols:
        target_symbols = [_norm(s) for s in symbols if _norm(s)]
    elif scope == "all":
        try:
            from app.binance_tr_public import trading_symbols
            all_pairs = await trading_symbols(quote_asset)
            target_symbols = [_norm(s) for s in all_pairs if _norm(s).endswith(quote_asset)]
        except Exception as exc:
            logger.warning("scan_market trading_symbols error: %s", exc)
            target_symbols = []

    if not target_symbols:
        pool = set()
        for s in (getattr(config, "SYMBOLS", None) or []):
            if s:
                pool.add(_norm(s))
        statuses = getattr(config, "SYMBOL_ACTIVITY_STATUS", None) or {}
        for s, info in statuses.items():
            st = (info.get("status") if isinstance(info, dict) else str(info)).upper()
            if st == "ACTIVE":
                pool.add(_norm(s))
        for s in (analyzer.positions or {}):
            pool.add(_norm(s))
        for s in getattr(market, "symbols", []):
            pool.add(_norm(s))

        target_symbols = sorted([s for s in pool if s.endswith(quote_asset)])
        if not target_symbols:
            target_symbols = sorted(list(pool))

    if not target_symbols:
        target_symbols = [_norm(s) for s in (config.SYMBOLS or [])]

    # Eşzamanlı istek tavanı (REST limitlerine nazik)
    sem = asyncio.Semaphore(12)

    async def _scan_one(sym: str) -> dict | None:
        async with sem:
            try:
                res = await compute(sym, tfs=tfs, force=force_refresh)
                if not res or res.get("coverage", 0) < 2:
                    return None
                ticker = market.get_ticker(sym) or {}
                price = float(ticker.get("last_price") or ticker.get("last") or 0.0)
                if price <= 0:
                    kline = market.get_ut_kline(sym, "5m") or {}
                    closes = kline.get("closes") or []
                    price = float(closes[-1]) if closes else 0.0
                change_24h = None
                for key in ("price_change_percent", "change_24h", "change_pct"):
                    if ticker.get(key) is not None:
                        try:
                            change_24h = round(float(ticker[key]), 2)
                            break
                        except Exception:
                            pass
                return {
                    "symbol": sym,
                    "price": price,
                    "change_24h_pct": change_24h,
                    "confluence": res.get("confluence"),
                    "verdict": res.get("verdict"),
                    "green_count": res.get("green_count", 0),
                    "parallel_up_count": res.get("parallel_up_count", 0),
                    "expanding_count": res.get("expanding_count", 0),
                    "fresh_cross": res.get("fresh_cross", []),
                    "early_trough_count": res.get("early_trough_count", 0),
                    "squeeze_count": res.get("squeeze_count", 0),
                    "wt_oversold_cross": res.get("wt_oversold_cross", []),
                    "zl_fresh_cross": res.get("zl_fresh_cross", []),
                    "early_spark": res.get("early_spark", False),
                    "coverage": res.get("coverage", 0),
                    "tfs": res.get("cells", []),
                }
            except Exception as exc:
                logger.debug("scan_market error on %s: %s", sym, exc)
                return None

    tasks = [_scan_one(s) for s in target_symbols]
    scanned_results = await asyncio.gather(*tasks)
    valid_items = [r for r in scanned_results if r is not None]

    # İstatistikler
    guclu_count = sum(1 for r in valid_items if r["verdict"] == "GÜÇLÜ")
    orta_count = sum(1 for r in valid_items if r["verdict"] == "ORTA")
    zayif_count = sum(1 for r in valid_items if r["verdict"] == "ZAYIF")
    fresh_cross_count = sum(1 for r in valid_items if len(r["fresh_cross"]) > 0)
    parallel_up_count = sum(1 for r in valid_items if r["parallel_up_count"] >= 2)
    early_trough_count = sum(1 for r in valid_items if r.get("early_trough_count", 0) >= 2)
    squeeze_count = sum(1 for r in valid_items if r.get("squeeze_count", 0) >= 1)
    early_spark_count = sum(1 for r in valid_items if r.get("early_spark"))

    # Filtreleme
    filtered = valid_items
    if min_verdict == "GÜÇLÜ":
        filtered = [r for r in filtered if r["verdict"] == "GÜÇLÜ"]
    elif min_verdict == "ORTA":
        filtered = [r for r in filtered if r["verdict"] in ("GÜÇLÜ", "ORTA")]

    if fresh_only:
        filtered = [r for r in filtered if len(r["fresh_cross"]) > 0]
    if parallel_only:
        filtered = [r for r in filtered if r["parallel_up_count"] >= 2]

    # Sıralama: GÜÇLÜ önce, sonra yüksek konfluans, taze kesişim sayısı ve paralel sayısı
    order = {"GÜÇLÜ": 0, "ORTA": 1, "ZAYIF": 2, "VERİ YOK": 3}
    filtered.sort(
        key=lambda x: (
            order.get(x["verdict"], 9),
            -(x["confluence"] or 0),
            -len(x["fresh_cross"]),
            -x["parallel_up_count"],
            -(x["change_24h_pct"] or 0),
        )
    )

    return {
        "total_scanned": len(target_symbols),
        "valid_count": len(valid_items),
        "guclu_count": guclu_count,
        "orta_count": orta_count,
        "zayif_count": zayif_count,
        "fresh_cross_count": fresh_cross_count,
        "parallel_up_count": parallel_up_count,
        "early_trough_count": early_trough_count,
        "squeeze_count": squeeze_count,
        "early_spark_count": early_spark_count,
        "tfs": list(tfs),
        "scope": scope,
        "duration_sec": round(time.time() - t0, 2),
        "scanned_at": time.time(),
        "items": filtered,
    }



def reset_state_for_tests() -> None:
    _cache.clear()
    _inflight.clear()
