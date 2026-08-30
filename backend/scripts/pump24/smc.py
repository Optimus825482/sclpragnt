"""SMC / price-action features and the composite per-bar frame builder.

All labels at bar ``i`` are computed from candles [0..i] only. Mirror of the
research_features block in ``app/technical_analysis.calculate_snapshot``.
"""

import math

import numpy as np

from pump24 import features as F


# ---------------------------------------------------------------------------
# per-bar SMC labels
# ---------------------------------------------------------------------------

def td9_bull_count_series(closes, lookback=4):
    out = [None] * len(closes)
    up = down = 0
    for i in range(lookback, len(closes)):
        if closes[i] > closes[i - lookback]:
            up, down = up + 1, 0
        elif closes[i] < closes[i - lookback]:
            down, up = down + 1, 0
        else:
            up = down = 0
        out[i] = up
    return out


def td9_bear_count_series(closes, lookback=4):
    out = [None] * len(closes)
    up = down = 0
    for i in range(lookback, len(closes)):
        if closes[i] > closes[i - lookback]:
            up, down = up + 1, 0
        elif closes[i] < closes[i - lookback]:
            down, up = down + 1, 0
        else:
            up = down = 0
        out[i] = down
    return out


def fvg_bullish_series(highs, lows, min_gap=0.0):
    """Bar i closes a bullish 3-candle FVG formed by bars i-2..i (completed)."""
    out = [None] * len(closes_placeholder(len(highs)))
    for i in range(2, len(highs)):
        gap = lows[i] - highs[i - 2]
        out[i] = gap if gap > max(min_gap, 0) else None
    return out


def closes_placeholder(n):
    return [0] * n


def fvg_bearish_series(highs, lows, min_gap=0.0):
    out = [None] * len(highs)
    for i in range(2, len(highs)):
        gap = lows[i - 2] - highs[i]
        out[i] = gap if gap > max(min_gap, 0) else None
    return out


def wick_rejection_series(opens, highs, lows, closes, lookback=20, z_threshold=1.5):
    n = len(closes)
    upper_z = [None] * n
    lower_z = [None] * n
    signal = [None] * n
    upper_ratios, lower_ratios = [], []
    for i in range(n):
        span = max(highs[i] - lows[i], 1e-12)
        upper = (highs[i] - max(opens[i], closes[i])) / span
        lower = (min(opens[i], closes[i]) - lows[i]) / span
        if len(upper_ratios) >= lookback:
            std_u = float(np.std(upper_ratios[-lookback:]))
            std_l = float(np.std(lower_ratios[-lookback:]))
            upper_z[i] = (upper - float(np.mean(upper_ratios[-lookback:]))) / std_u if std_u > 1e-12 else 0.0
            lower_z[i] = (lower - float(np.mean(lower_ratios[-lookback:]))) / std_l if std_l > 1e-12 else 0.0
            if upper_z[i] >= z_threshold and closes[i] <= lows[i] + span * 0.45:
                signal[i] = "bearish_rejection"
            elif lower_z[i] >= z_threshold and closes[i] >= lows[i] + span * 0.55:
                signal[i] = "bullish_rejection"
        upper_ratios.append(upper)
        lower_ratios.append(lower)
    return {"upper_z": upper_z, "lower_z": lower_z, "signal": signal}


def bos_series(highs, lows, closes, pivot_length=3):
    """Causal BOS label: uses the last swing confirmed BEFORE the current bar."""
    n = len(closes)
    out = [None] * n
    pivot_len = pivot_length
    pivots_high, pivots_low = [], []
    for i in range(n):
        # emit pivots confirmed at bar i (centre = i - pivot_len)
        centre = i - pivot_len
        if centre >= pivot_len:
            hw = highs[centre - pivot_len:centre + pivot_len + 1]
            lw = lows[centre - pivot_len:centre + pivot_len + 1]
            if highs[centre] == max(hw) and list(hw).count(highs[centre]) == 1:
                pivots_high.append((centre, highs[centre], i))
            if lows[centre] == min(lw) and list(lw).count(lows[centre]) == 1:
                pivots_low.append((centre, lows[centre], i))
        if i < pivot_len * 2 + 2:
            continue
        usable_high = next((p for p in reversed(pivots_high) if p[2] < i), None)
        usable_low = next((p for p in reversed(pivots_low) if p[2] < i), None)
        if usable_high and closes[i] > usable_high[1]:
            out[i] = "bullish"
        elif usable_low and closes[i] < usable_low[1]:
            out[i] = "bearish"
        else:
            out[i] = "none"
    return out


def inside_bar_series(highs, lows):
    out = [None] * len(highs)
    for i in range(1, len(highs)):
        out[i] = highs[i] < highs[i - 1] and lows[i] > lows[i - 1]
    return out


def candle_label_series(opens, highs, lows, closes):
    """Per-bar candle body label used for pattern mining."""
    out = [None] * len(closes)
    for i in range(1, len(closes)):
        body = closes[i] - opens[i]
        span = max(highs[i] - lows[i], 1e-12)
        body_ratio = abs(body) / span
        if body > 0 and body_ratio >= 0.6:
            out[i] = "strong_green"
        elif body < 0 and body_ratio >= 0.6:
            out[i] = "strong_red"
        elif body > 0 and body_ratio >= 0.3:
            out[i] = "green"
        elif body < 0 and body_ratio >= 0.3:
            out[i] = "red"
        else:
            out[i] = "doji"
    return out


# ---------------------------------------------------------------------------
# composite frame
# ---------------------------------------------------------------------------

FEATURE_KEYS = [
    "close", "open", "high", "low", "volume",
    "ret_1", "ret_3", "ret_5", "ret_10", "ret_15", "ret_30",
    "rsi_14", "crsi", "cmo_9", "stoch_k", "stoch_d", "stochrsi_k", "stochrsi_d",
    "cci_20", "williams_14", "awesome", "mfi_14", "tsi", "trix_15",
    "macd_line", "macd_signal", "macd_hist", "roc_5", "roc_10", "roc_21",
    "ema_9", "ema_21", "ema_50", "ema_gap_pct", "ema_bull_align",
    "adx_14", "plus_di", "minus_di", "di_gap",
    "atr_14", "atr_pct", "bb_pos", "bb_width", "chop_14",
    "vwap_20", "vwap_dist_pct", "vol_ratio_20", "vol_osc", "obv_slope_5", "cmf_20",
    "vortex_plus", "vortex_minus", "vortex_bull",
    "supertrend_dir", "aroon_up", "aroon_down", "ichimoku_above",
    "td9_bull", "td9_bear", "fvg_bull", "fvg_bear",
    "wick_upper_z", "wick_lower_z", "wick_signal", "bos", "inside_bar", "candle_label",
    "range_30_max_dist_pct", "donchian20_pos",
]


def fill_m1_gaps(rows):
    """Insert synthetic flat candles for missing M1 minutes (volume=0, flat price).

    These keep indicator windows time-aligned; they add no information
    (volume 0, unchanged close) so every feature remains causal and honest.
    """
    if len(rows) < 2:
        return rows
    out = [dict(rows[0])]
    for prev, cur in zip(rows, rows[1:]):
        gap = cur["open_time"] - prev["open_time"]
        if gap > 60_000:
            steps = int(gap // 60_000) - 1
            for s in range(1, steps + 1):
                t = prev["open_time"] + s * 60_000
                out.append({"open_time": t, "close_time": t + 59_999,
                            "open": prev["close"], "high": prev["close"],
                            "low": prev["close"], "close": prev["close"], "volume": 0.0})
        out.append(dict(cur))
    return out


def build_frame(symbol, timeframe, rows):
    """rows: chronological list of dicts with open/high/low/close/volume/open_time.
    Sparse M1 gaps (minutes with zero trades produce no Binance candle) are
    forward-filled so indicator series stay aligned and causal."""
    rows = fill_m1_gaps(rows) if timeframe == "1m" else rows
    opens = [r["open"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    closes = [r["close"] for r in rows]
    volumes = [r["volume"] for r in rows]
    n = len(rows)

    macd = F.macd_series(closes)
    bb = F.bollinger_series(closes)
    stoch = F.stochastic_series(highs, lows, closes)
    srsi = F.stoch_rsi_series(closes)
    adx = F.adx_series(highs, lows, closes)
    vplus, vminus = F.vortex_series(highs, lows, closes)
    st_dir = F.supertrend_series(highs, lows, closes)
    a_up, a_down = F.aroon_series(highs, lows)
    chop = F.choppiness_series(highs, lows, closes)
    awesome = F.awesome_series(highs, lows)
    wick = wick_rejection_series(opens, highs, lows, closes)
    bos = bos_series(highs, lows, closes)
    atr = F.atr_series(highs, lows, closes)
    vwap = F.vwap_series(highs, lows, closes, volumes)
    obv = F.obv_series(closes, volumes)

    def ret_series(k):
        out = [None] * n
        for i in range(k, n):
            base = closes[i - k]
            out[i] = (closes[i] / base - 1) * 100 if base else None
        return out

    ema9 = F.ema_series(closes, 9)
    ema21 = F.ema_series(closes, 21)
    ema50 = F.ema_series(closes, 50)
    vol_avg20 = F.rolling_mean(volumes, 20)
    don_hi = [None] * n
    don_lo = [None] * n
    for i in range(19, n):
        don_hi[i] = max(highs[i - 19:i + 1])
        don_lo[i] = min(lows[i - 19:i + 1])

    frame = {
        "open_time": [r["open_time"] for r in rows],
        "close_time": [r["close_time"] for r in rows],
        "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes,
        "ret_1": ret_series(1), "ret_3": ret_series(3), "ret_5": ret_series(5),
        "ret_10": ret_series(10), "ret_15": ret_series(15), "ret_30": ret_series(30),
        "rsi_14": F.rsi_series(closes),
        "crsi": F.connors_rsi_series(closes),
        "cmo_9": F.cmo_series(closes),
        "stoch_k": stoch["k"], "stoch_d": stoch["d"],
        "stochrsi_k": srsi["k"], "stochrsi_d": srsi["d"],
        "cci_20": F.cci_series(highs, lows, closes),
        "williams_14": F.williams_series(highs, lows, closes),
        "awesome": awesome,
        "mfi_14": F.mfi_series(highs, lows, closes, volumes),
        "tsi": F.tsi_series(closes),
        "trix_15": F.trix_series(closes),
        "macd_line": macd["line"], "macd_signal": macd["signal"], "macd_hist": macd["histogram"],
        "macd_line_pct": [None]*n, "macd_signal_pct": [None]*n, "macd_hist_pct": [None]*n,
        "awesome_pct": [None]*n, "obv_slope_norm": [0.0]*n,
        "roc_5": ret_series(5), "roc_10": ret_series(10), "roc_21": ret_series(21),
        "ema_9": ema9, "ema_21": ema21, "ema_50": ema50,
        "adx_14": adx["adx"], "plus_di": adx["plus_di"], "minus_di": adx["minus_di"],
        "atr_14": atr, "atr_pct": [None] * n, "bb_pos": bb["position"], "bb_width": bb["width_pct"],
        "chop_14": chop,
        "vwap_20": vwap, "vwap_dist_pct": [None] * n,
        "vol_ratio_20": [None if not va else v / va for v, va in zip(volumes, vol_avg20)],
        "vol_osc": F.volume_oscillator_series(volumes),
        "obv_slope_5": [0.0] * n, "cmf_20": F.cmf_series(highs, lows, closes, volumes),
        "vortex_plus": vplus, "vortex_minus": vminus, "vortex_bull": [False] * n,
        "supertrend_dir": st_dir,
        "aroon_up": a_up, "aroon_down": a_down,
        "ichimoku_above": F.ichimoku_above_cloud_series(highs, lows, closes),
        "td9_bull": td9_bull_count_series(closes),
        "td9_bear": td9_bear_count_series(closes),
        "fvg_bull": fvg_bullish_series(highs, lows),
        "fvg_bear": fvg_bearish_series(highs, lows),
        "wick_upper_z": wick["upper_z"], "wick_lower_z": wick["lower_z"],
        "wick_signal": wick["signal"],
        "bos": bos,
        "inside_bar": inside_bar_series(highs, lows),
        "candle_label": candle_label_series(opens, highs, lows, closes),
        "donchian20_pos": [None] * n,
        "ema_gap_pct": [None] * n, "ema_bull_align": [False] * n, "di_gap": [None] * n,
    }
    # derived (bar-causal)
    for i in range(n):
        e9, e21, e50 = ema9[i], ema21[i], ema50[i]
        frame["ema_gap_pct"][i] = (closes[i] / e9 - 1) * 100 if e9 else None
        frame["ema_bull_align"][i] = bool(e9 and e21 and e50 and e9 > e21 > e50)
        frame["di_gap"][i] = (adx["plus_di"][i] - adx["minus_di"][i]) if (adx["plus_di"][i] is not None and adx["minus_di"][i] is not None) else None
        frame["macd_line_pct"][i] = macd["line"][i] / closes[i] * 100 if macd["line"][i] is not None and closes[i] else None
        frame["macd_signal_pct"][i] = macd["signal"][i] / closes[i] * 100 if macd["signal"][i] is not None and closes[i] else None
        frame["macd_hist_pct"][i] = macd["histogram"][i] / closes[i] * 100 if macd["histogram"][i] is not None and closes[i] else None
        frame["awesome_pct"][i] = awesome[i] / closes[i] * 100 if awesome[i] is not None and closes[i] else None
        frame["obv_slope_norm"][i] = frame["obv_slope_5"][i] / vol_avg20[i] if vol_avg20[i] else None
        frame["atr_pct"][i] = atr[i] / closes[i] * 100 if atr[i] and closes[i] else None
        frame["vwap_dist_pct"][i] = (closes[i] / vwap[i] - 1) * 100 if vwap[i] else None
        frame["vortex_bull"][i] = bool(vplus[i] is not None and vminus[i] is not None and vplus[i] > vminus[i])
        frame["obv_slope_5"][i] = obv[i] - obv[max(0, i - 5)]
        if don_hi[i] is not None and don_hi[i] > don_lo[i]:
            frame["donchian20_pos"][i] = (closes[i] - don_lo[i]) / (don_hi[i] - don_lo[i])
    # 30-bar range position (causal: includes current bar)
    max_dist = [None] * n
    for i in range(29, n):
        hi30 = max(highs[i - 29:i + 1])
        max_dist[i] = (hi30 - closes[i]) / closes[i] * 100 if closes[i] else None
    frame["range_30_max_dist_pct"] = max_dist
    frame["_obv"] = obv
    frame["_symbol"] = symbol
    frame["_timeframe"] = timeframe
    return frame
