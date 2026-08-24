"""Chronological shared-wallet replay of the live BB-MFI paper strategy."""

import argparse
import asyncio
import bisect
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analyzer import ScalpAnalyzer
from app import database
from app.binance_tr_public import historical_klines, orderbook, ticker_24h, trading_symbols
from app.config import config
from app.technical_analysis import _adx, _bollinger, _cci, _ema, _mfi, calculate_snapshot


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def live_parity_snapshot():
    """Record the live BB-MFI settings that deterministically affect a replay."""
    names = (
        "ACTIVE_STRATEGY", "ACTIVE_STRATEGY_TIMEFRAME", "SYMBOLS", "INITIAL_BALANCE_TRY",
        "ORDER_PCT", "PYRAMIDING_LAYERS", "MAX_OPEN_POSITIONS", "COMMISSION_PCT",
        "ESTIMATED_SLIPPAGE_PCT", "BACKTEST_ASSUMED_SPREAD_PCT", "BB_MFI_PINE_VERSION",
        "BB_MFI_STOP_LOSS_PCT", "BB_MFI_TAKE_PROFIT_PCT", "BB_MFI_ENTRY_VOLUME_RATIO_MIN",
        "BB_MFI_DIP_CONFIRMATION_ENABLED", "BB_MFI_DIP_MIN_CLOSE_POSITION",
        "BB_MFI_ENTRY_MFI_REVERSAL_ENABLED", "BB_MFI_ENTRY_MFI_REVERSAL_MIN_DELTA",
        "BB_MFI_REQUIRE_DATA_READY", "BB_MFI_BEARISH_REQUIRE_REVERSAL_CONFIRMATION",
        "BB_MFI_BEAR_PRESSURE_FILTER_ENABLED", "BB_MFI_BEAR_PRESSURE_MIN_ADX",
        "BB_MFI_BEAR_PRESSURE_MIN_DI_GAP", "BB_MFI_BEAR_PRESSURE_MIN_RETURN_1H_PCT",
        "BB_MFI_BEAR_PRESSURE_MIN_RETURN_15M_PCT",
    )
    return {name.lower(): getattr(config, name) for name in names}


def apply_live_parity_72h_profile(args):
    """Freeze a read-only 72-hour replay to the running BB-MFI paper profile."""
    if config.ACTIVE_STRATEGY != "BB_MFI_MEAN_REVERSION":
        raise SystemExit("--live-parity-72h yalnız BB_MFI_MEAN_REVERSION için kullanılabilir")
    if not config.SYMBOLS:
        raise SystemExit("--live-parity-72h için ayarlı sembol listesi boş")
    # The same profile can be evaluated on a completed earlier 72-hour window
    # without changing any strategy or portfolio rule.  This keeps OOS runs
    # chronological and avoids using candles that overlap the baseline.
    args.start_hours_ago = float(args.live_parity_end_hours_ago) + 72.0
    args.end_hours_ago = float(args.live_parity_end_hours_ago)
    args.start_date = None
    args.end_date = None
    args.data_source = "public"
    # 72 saatlik karar penceresi + indikatör warm-up; daha kısa indirme ile
    # pencerenin ilk günü sessizce atlanır ve parity bozulur.
    args.fetch_days = max(int(args.fetch_days), 4)
    args.pine_version = "current"
    requested_symbols = [str(symbol).replace("_", "").upper() for symbol in (args.symbols or [])]
    args.symbols = requested_symbols if args.live_parity_keep_symbols and requested_symbols else [str(symbol).replace("_", "").upper() for symbol in config.SYMBOLS]
    args.use_all_requested = True
    args.open_position_policy = "mark-to-market"
    args.order_pct = config.ORDER_PCT
    args.pyramiding = config.PYRAMIDING_LAYERS
    args.max_positions = config.MAX_OPEN_POSITIONS
    args.stop_pct = config.BB_MFI_STOP_LOSS_PCT
    args.tp_pct = config.BB_MFI_TAKE_PROFIT_PCT
    # A multiplier is research-only: it leaves every decision rule unchanged
    # while making the modeled fills more conservative for robustness checks.
    args.spread_pct = config.BACKTEST_ASSUMED_SPREAD_PCT * args.live_parity_cost_multiplier
    args.slippage_pct = config.ESTIMATED_SLIPPAGE_PCT * args.live_parity_cost_multiplier
    args.entry_min_volume_ratio = config.BB_MFI_ENTRY_VOLUME_RATIO_MIN
    args.entry_dip_confirmation = config.BB_MFI_DIP_CONFIRMATION_ENABLED
    args.entry_dip_min_close_position = config.BB_MFI_DIP_MIN_CLOSE_POSITION
    args.entry_mfi_reversal = config.BB_MFI_ENTRY_MFI_REVERSAL_ENABLED
    args.entry_mfi_reversal_min_delta = config.BB_MFI_ENTRY_MFI_REVERSAL_MIN_DELTA
    args.high_downtrend_entry_filter = config.BB_MFI_BEAR_PRESSURE_FILTER_ENABLED
    args.high_downtrend_min_adx = config.BB_MFI_BEAR_PRESSURE_MIN_ADX
    args.high_downtrend_min_di_gap = config.BB_MFI_BEAR_PRESSURE_MIN_DI_GAP
    args.high_downtrend_min_return_1h_pct = config.BB_MFI_BEAR_PRESSURE_MIN_RETURN_1H_PCT
    args.high_downtrend_min_return_15m_pct = config.BB_MFI_BEAR_PRESSURE_MIN_RETURN_15M_PCT
    args.pyramid_require_net_profit = config.BB_MFI_PYRAMID_REQUIRE_NET_PROFIT
    args.pyramid_profit_extension_layers = config.BB_MFI_PYRAMID_PROFIT_EXTENSION_LAYERS


def rows_to_series(rows):
    result = {key: [] for key in ("opens", "highs", "lows", "closes", "volumes", "times")}
    seen = set()
    now_ms = int(time.time() * 1000)
    for row in rows:
        if isinstance(row, dict):
            close_ms = int(row["close_time"])
            values = [float(row[key]) for key in ("open", "high", "low", "close", "volume")]
        else:
            close_ms = int(row[6])
            values = [float(row[index]) for index in range(1, 6)]
        if close_ms > now_ms or close_ms in seen:
            continue
        if not all(math.isfinite(value) for value in values):
            continue
        seen.add(close_ms)
        for key, value in zip(("opens", "highs", "lows", "closes", "volumes"), values):
            result[key].append(value)
        result["times"].append(close_ms // 1000)
    return result


def window_at(data, index, lookback=250):
    """Bound replay indicator input; BB/MFI/RSI need far less than full history."""
    start = max(0, index - lookback + 1)
    return {key: values[start:index + 1] for key, values in data.items()}


def data_quality(data):
    times = data.get("times", [])
    gaps = [times[index] - times[index - 1] for index in range(1, len(times))
            if times[index] - times[index - 1] > 450]
    return {
        "candle_count": len(times), "sorted": times == sorted(times),
        "duplicate_timestamps": len(times) != len(set(times)),
        "missing_gap_count": len(gaps), "max_gap_seconds": max(gaps) if gaps else 0,
    }


def arm_profit_lock(position, candle_high, trigger_pct, lock_pct):
    """Raise a long position's exit floor after a confirmed profitable move.

    The caller invokes this after intrabar exits, so an OHLC bar that merely
    touched the trigger cannot also claim a same-bar stop fill.
    """
    if trigger_pct <= 0 or candle_high < position["entry"] * (1 + trigger_pct):
        return False
    candidate = position["entry"] * (1 + lock_pct)
    previous = float(position.get("profit_lock_stop") or 0)
    if candidate <= previous:
        return False
    position["profit_lock_stop"] = candidate
    return True


def activity_metrics(analyzer, data, quote_volume, spread_pct):
    closes, highs, lows, volumes = (data[key] for key in ("closes", "highs", "lows", "volumes"))
    if len(closes) < 21:
        return {"status": "WARMING", "reason": "insufficient_candles"}
    low, high = min(lows[-3:]), max(highs[-3:])
    range_pct = ((high - low) / low * 100) if low else 0.0
    atr = analyzer.calculate_atr(data, 14) or 0.0
    atr_pct = atr / closes[-1] if closes[-1] else 0.0
    average_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / average_volume if average_volume else 0.0
    checks = {
        "quote_volume": quote_volume >= config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY,
        "range_15m": range_pct >= config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT,
        "atr": atr_pct >= config.SYMBOL_ACTIVITY_MIN_ATR_PCT,
        "volume_ratio": volume_ratio >= config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO,
        "spread": spread_pct is not None and spread_pct <= config.SYMBOL_ACTIVITY_MAX_SPREAD_PCT,
    }
    return {
        "status": "ACTIVE" if all(checks.values()) else "PASSIVE",
        "quote_volume": round(quote_volume, 2), "range_15m_pct": round(range_pct, 4),
        "atr_pct": round(atr_pct * 100, 4), "volume_ratio": round(volume_ratio, 4),
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "checks": checks,
        "reason": "active" if all(checks.values()) else "movement_or_liquidity_below_threshold",
    }


def m1_activity_passes(analyzer, data, index, args):
    """Causal M1 volatility confirmation for an M5 entry decision."""
    if not args.activity_m1_filter:
        return True
    if index is None or index < 14:
        return False
    window = window_at(data, index, lookback=30)
    closes, highs, lows = (window[key] for key in ("closes", "highs", "lows"))
    sample = min(args.activity_m1_range_bars, len(highs))
    low, high = min(lows[-sample:]), max(highs[-sample:])
    range_pct = ((high - low) / low * 100) if low else 0.0
    atr = analyzer.calculate_atr(window, 14) or 0.0
    atr_pct = atr / closes[-1] * 100 if closes[-1] else 0.0
    return range_pct >= args.activity_m1_min_range_pct and atr_pct >= args.activity_m1_min_atr_pct


def m1_flat_candle_passes(data, index, args):
    """Reject a causal M1 window with too many completed flat H-L candles."""
    if not args.activity_m1_flat_filter:
        return True
    if data is None or index is None or index < 29:
        return False
    highs, lows = data["highs"], data["lows"]
    max_range_pct = args.activity_m1_flat_max_range_pct

    def count_flat(size):
        sample_highs, sample_lows = highs[index - size + 1:index + 1], lows[index - size + 1:index + 1]
        if len(sample_highs) != size or any(low <= 0 for low in sample_lows):
            return None
        return sum((high - low) / low * 100 <= max_range_pct for high, low in zip(sample_highs, sample_lows))

    flat_5m, flat_30m = count_flat(5), count_flat(30)
    if flat_5m is None or flat_30m is None:
        return False
    flat_cluster = (flat_5m >= args.activity_m1_flat_5m_max_count or
                    flat_30m >= args.activity_m1_flat_30m_max_count)
    if not flat_cluster:
        return True
    if args.activity_m1_flat_max_volume_ratio <= 0:
        return False
    volumes = data.get("volumes") or []
    recent, prior = volumes[index - 4:index + 1], volumes[index - 24:index - 4]
    if len(recent) < 5 or len(prior) < 20:
        return False
    prior_average = sum(prior) / len(prior)
    recent_average = sum(recent) / len(recent)
    # Flat but actively traded candles can be absorption, not inactivity.
    return bool(prior_average and recent_average / prior_average > args.activity_m1_flat_max_volume_ratio)


def m1_m5_compression_passes(analyzer, m1_data, m1_index, m5_window, args):
    """Reject only an unusually compressed M1+M5 context (research-only)."""
    if not args.activity_m1_m5_compression_filter:
        return True
    if m1_data is None or m1_index is None or m1_index < 20:
        return True  # Unknown data must never be silently classified as inactive.
    m1_window = window_at(m1_data, m1_index, lookback=100)
    m1_closes = m1_window["closes"]
    m1_atr = analyzer.calculate_atr(m1_window, 14)
    m5_atr = analyzer.calculate_atr(m5_window, 14)
    m1_bb = _bollinger(m1_closes, 20, 2.0) or {}
    if not m1_closes or not m5_window["closes"] or m1_atr is None or m5_atr is None or m1_bb.get("width_pct") is None:
        return True
    m1_atr_pct = m1_atr / m1_closes[-1] * 100 if m1_closes[-1] else None
    m5_atr_pct = m5_atr / m5_window["closes"][-1] * 100 if m5_window["closes"][-1] else None
    m1_bb_width_pct = float(m1_bb["width_pct"]) * 100
    compressed = (m1_atr_pct is not None and m5_atr_pct is not None and
                  m1_atr_pct <= args.activity_m1_compression_max_atr_pct and
                  m5_atr_pct <= args.activity_m5_compression_max_atr_pct and
                  m1_bb_width_pct <= args.activity_m1_compression_max_bb_width_pct)
    return not compressed


def _percentile(values, fraction):
    """Nearest-rank percentile, deliberately using only values already seen."""
    finite = sorted(value for value in values if value is not None and math.isfinite(value))
    if not finite:
        return None
    position = max(0, min(len(finite) - 1, math.ceil(len(finite) * fraction) - 1))
    return finite[position]


def m1_relative_idle_observation(data, index, args):
    """Detect a symbol that is quiet relative to *its own* recent M1 history.

    It measures the user's requested H-L zeros first.  A one-tick proxy is
    added because exchange candles can print a non-zero H-L despite no useful
    price discovery.  No absolute price or cross-symbol threshold is used.
    """
    if not args.activity_m1_relative_idle_filter:
        return {"ready": False, "inactive": False, "score": 0}
    if data is None or index is None:
        return {"ready": False, "inactive": False, "score": 0}
    highs, lows, closes, volumes = (data[key] for key in ("highs", "lows", "closes", "volumes"))
    end, window_size, lookback = index + 1, args.activity_m1_relative_idle_window_minutes, args.activity_m1_relative_idle_lookback_minutes
    prior_start = end - window_size - lookback
    if prior_start < 0 or end > len(closes):
        return {"ready": False, "inactive": False, "score": 0}
    recent_ranges = [
        (high - low) / low * 100 for high, low in zip(highs[end - window_size:end], lows[end - window_size:end]) if low > 0
    ]
    prior_ranges = [
        (high - low) / low * 100 for high, low in zip(highs[prior_start:end - window_size], lows[prior_start:end - window_size]) if low > 0
    ]
    if len(recent_ranges) != window_size or len(prior_ranges) < lookback * 0.9:
        return {"ready": False, "inactive": False, "score": 0}
    positive_prior_ranges = [value for value in prior_ranges if value > 0]
    tick_like_limit = _percentile(positive_prior_ranges, 0.10)
    zero_hl_count = sum(value == 0 for value in recent_ranges)
    tick_like_count = sum(value <= tick_like_limit for value in recent_ranges) if tick_like_limit is not None else 0
    range_threshold = _percentile(prior_ranges, args.activity_m1_relative_idle_range_percentile)
    range_compressed = range_threshold is not None and _percentile(recent_ranges, 0.50) <= range_threshold
    prior_chunk_averages = [
        sum(volumes[start:start + window_size]) / window_size
        for start in range(prior_start, end - window_size, window_size)
        if len(volumes[start:start + window_size]) == window_size
    ]
    recent_volume_average = sum(volumes[end - window_size:end]) / window_size
    volume_threshold = _percentile(prior_chunk_averages, args.activity_m1_relative_idle_volume_percentile)
    volume_quiet = volume_threshold is not None and recent_volume_average <= volume_threshold
    frozen_microstructure = (zero_hl_count >= args.activity_m1_relative_idle_min_zero_hl_count or
                             tick_like_count >= args.activity_m1_relative_idle_min_ticklike_count)
    score = sum((frozen_microstructure, range_compressed, volume_quiet))
    return {
        "ready": True, "inactive": score >= args.activity_m1_relative_idle_min_score, "score": score,
        "zero_hl_count": zero_hl_count, "tick_like_count": tick_like_count,
        "range_compressed": range_compressed, "volume_quiet": volume_quiet,
    }


def _m1_inactivity_observation(data, index, args):
    """Causal, per-symbol quiet-market score for research only.

    The score is intentionally an *inactivity* observation, not a direction
    signal.  Compression thresholds are relative to the symbol's preceding
    M1 distribution so a low-priced or high-priced TRY pair is not treated
    differently solely due to its nominal price.
    """
    if data is None or index is None or index < 139:
        return {"ready": False, "score": 0, "inactive": False}
    closes, highs, lows, volumes = (data[key] for key in ("closes", "highs", "lows", "volumes"))
    end = index + 1

    def feature_at(stop):
        sample_closes, sample_highs, sample_lows, sample_volumes = (
            closes[max(0, stop - 100):stop], highs[max(0, stop - 100):stop],
            lows[max(0, stop - 100):stop], volumes[max(0, stop - 100):stop],
        )
        if len(sample_closes) < 40 or not sample_closes[-1]:
            return None
        price = sample_closes[-1]
        bb = _bollinger(sample_closes, 20, 2.0) or {}
        donchian_span = max(sample_highs[-20:]) - min(sample_lows[-20:])
        true_ranges = [
            max(sample_highs[pos] - sample_lows[pos], abs(sample_highs[pos] - sample_closes[pos - 1]), abs(sample_lows[pos] - sample_closes[pos - 1]))
            for pos in range(1, len(sample_closes))
        ]
        atr_ema = _ema(true_ranges, 13)
        cmf_volume = sum(sample_volumes[-20:])
        cmf = (sum(
            (((close - low) - (high - close)) / (high - low) if high != low else 0.0) * volume
            for high, low, close, volume in zip(sample_highs[-20:], sample_lows[-20:], sample_closes[-20:], sample_volumes[-20:])
        ) / cmf_volume) if cmf_volume else None
        force = [(sample_closes[pos] - sample_closes[pos - 1]) * sample_volumes[pos] for pos in range(1, len(sample_closes))]
        efi = _ema(force, 13)
        traded_value = sum(close * volume for close, volume in zip(sample_closes[-13:], sample_volumes[-13:]))
        momentum = [sample_closes[pos] - sample_closes[pos - 1] for pos in range(1, len(sample_closes))]

        def ema_series(values, period):
            if len(values) < period:
                return []
            alpha = 2.0 / (period + 1)
            value = sum(values[:period]) / period
            result = [value]
            for item in values[period:]:
                value = alpha * item + (1 - alpha) * value
                result.append(value)
            return result

        first_momentum = ema_series(momentum, 25)
        first_absolute = ema_series([abs(item) for item in momentum], 25)
        double_momentum = ema_series(first_momentum, 13)
        double_absolute = ema_series(first_absolute, 13)
        tsi = (double_momentum[-1] / double_absolute[-1] * 100
               if double_momentum and double_absolute and double_absolute[-1] else None)
        return {
            "bb_width_pct": float(bb.get("width_pct") or 0.0) * 100,
            "donchian_width_pct": donchian_span / price * 100,
            "atr_ema_pct": atr_ema / price * 100 if atr_ema is not None else None,
            "cmf_20": cmf,
            "efi_13_normalized_pct": efi / traded_value * 100 if efi is not None and traded_value else None,
            "tsi_25_13": tsi,
            "cci_20": _cci(sample_highs, sample_lows, sample_closes, 20),
        }

    current = feature_at(end)
    # The replay decides activity hourly; five-minute historical samples retain
    # the same causal distribution while preventing a 120x nested indicator
    # recomputation for every symbol and refresh.
    history = [feature_at(stop) for stop in range(end - args.activity_m1_inactivity_lookback_minutes, end - 1, 5)]
    history = [item for item in history if item]
    required_history = max(6, args.activity_m1_inactivity_lookback_minutes // 5 - 2)
    if current is None or len(history) < required_history:
        return {"ready": False, "score": 0, "inactive": False}
    low_volatility = sum(
        current[key] is not None and current[key] <= _percentile([item[key] for item in history], 0.25)
        for key in ("bb_width_pct", "donchian_width_pct", "atr_ema_pct")
    ) >= 2
    recent_volumes, prior_volumes = volumes[end - 5:end], volumes[end - 25:end - 5]
    volume_ratio = (sum(recent_volumes) / len(recent_volumes)) / (sum(prior_volumes) / len(prior_volumes)) if sum(prior_volumes) else None
    low_volume = volume_ratio is not None and volume_ratio <= args.activity_m1_inactivity_max_volume_ratio
    flat_count = sum(
        (high - low) / low * 100 <= args.activity_m1_flat_max_range_pct
        for high, low in zip(highs[end - 30:end], lows[end - 30:end]) if low > 0
    )
    flat_cluster = flat_count >= args.activity_m1_inactivity_flat_30m_min_count
    median_abs_efi = _percentile(
        [abs(item["efi_13_normalized_pct"]) for item in history if item["efi_13_normalized_pct"] is not None], 0.50
    )
    neutral_flow = (current["cmf_20"] is not None and abs(current["cmf_20"]) <= args.activity_m1_inactivity_max_abs_cmf and
                    current["efi_13_normalized_pct"] is not None and median_abs_efi is not None and
                    abs(current["efi_13_normalized_pct"]) <= median_abs_efi)
    neutral_momentum = ((current["tsi_25_13"] is not None and abs(current["tsi_25_13"]) <= args.activity_m1_inactivity_max_abs_tsi) or
                        (current["cci_20"] is not None and abs(current["cci_20"]) <= args.activity_m1_inactivity_max_abs_cci))
    score = sum((flat_cluster, low_volatility, low_volume, neutral_flow, neutral_momentum))
    return {
        "ready": True, "score": score, "inactive": score >= args.activity_m1_inactivity_score_min,
        "flat_30m_count": flat_count, "low_volatility": low_volatility, "volume_ratio": volume_ratio,
        "neutral_flow": neutral_flow, "neutral_momentum": neutral_momentum,
    }


def m30_activity_passes(analyzer, data, index, args):
    """Causal higher-timeframe movement and optional downtrend guard."""
    if not args.activity_m30_filter:
        return True
    if index is None or index < 20:
        return False
    window = window_at(data, index, lookback=40)
    closes, highs, lows = (window[key] for key in ("closes", "highs", "lows"))
    low, high = min(lows[-2:]), max(highs[-2:])
    range_pct = ((high - low) / low * 100) if low else 0.0
    atr = analyzer.calculate_atr(window, 14) or 0.0
    atr_pct = atr / closes[-1] * 100 if closes[-1] else 0.0
    if range_pct < args.activity_m30_min_range_pct or atr_pct < args.activity_m30_min_atr_pct:
        return False
    if args.activity_m30_regime_filter:
        ema_now = analyzer.calculate_ema(closes, 20)
        ema_before = analyzer.calculate_ema(closes[:-3], 20)
        if ema_now is None or ema_before is None or not ema_before:
            return False
        slope_pct = (ema_now - ema_before) / ema_before * 100
        if slope_pct < -args.activity_m30_max_ema20_decline_pct:
            return False
    return True


def historical_activity(analyzer, window, spread_pct, args=None, m1_data=None, m1_index=None,
                        m30_data=None, m30_index=None, apply_auxiliary=True):
    """Time-correct counterpart of the live activity gate for replay."""
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    if len(closes) < 21:
        return False, "warming"
    quote_volume = sum(close * volume for close, volume in zip(closes[-288:], volumes[-288:]))
    range_pct = ((max(highs[-3:]) - min(lows[-3:])) / min(lows[-3:]) * 100) if min(lows[-3:]) else 0.0
    atr = analyzer.calculate_atr(window, 14) or 0.0
    atr_pct = atr / closes[-1] if closes[-1] else 0.0
    avg_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / avg_volume if avg_volume else 0.0
    m5_range_min = args.activity_m5_min_range_pct if args is not None else config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT
    m5_atr_min = args.activity_m5_min_atr_pct / 100 if args is not None else config.SYMBOL_ACTIVITY_MIN_ATR_PCT
    m5_volume_min = args.activity_m5_min_volume_ratio if args is not None else config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO
    quote_volume_min = args.activity_min_quote_volume_try if args is not None else config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY
    volume_only = args.activity_volume_only if args is not None else config.SYMBOL_ACTIVITY_VOLUME_ONLY
    movement_gate = True if volume_only else (range_pct >= m5_range_min and atr_pct >= m5_atr_min)
    active = (quote_volume >= quote_volume_min and movement_gate and volume_ratio >= m5_volume_min)
    if not active:
        return False, "base_activity"
    if args is not None and apply_auxiliary:
        if args.activity_m1_filter and not m1_activity_passes(analyzer, m1_data, m1_index, args):
            return False, "m1_range_atr"
        if args.activity_m1_flat_filter and not m1_flat_candle_passes(m1_data, m1_index, args):
            return False, "m1_flat_candles"
        relative_idle = m1_relative_idle_observation(m1_data, m1_index, args)
        if relative_idle["ready"] and relative_idle["inactive"]:
            return False, f"m1_relative_idle_score_{relative_idle['score']}"
        if not m1_m5_compression_passes(analyzer, m1_data, m1_index, window, args):
            return False, "m1_m5_compression"
        if args.activity_m1_inactivity_score_filter:
            inactivity = _m1_inactivity_observation(m1_data, m1_index, args)
            if inactivity["ready"] and inactivity["inactive"]:
                return False, f"m1_inactivity_score_{inactivity['score']}"
        if args.activity_m30_filter and not m30_activity_passes(analyzer, m30_data, m30_index, args):
            return False, "m30_activity"
    return True, "active"


def historical_quality_score(analyzer, window, spread_pct):
    """Rank an already-ACTIVE symbol without using future candles."""
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    quote_volume = sum(close * volume for close, volume in zip(closes[-288:], volumes[-288:]))
    atr = analyzer.calculate_atr(window, 14) or 0.0
    atr_pct = atr / closes[-1] if closes[-1] else 0.0
    avg_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0.0
    volume_ratio = volumes[-1] / avg_volume if avg_volume else 0.0
    # Score favours liquid, tradable volatility and volume while penalizing spread.
    return math.log10(max(quote_volume, 1)) + min(atr_pct * 100, 3) + min(volume_ratio, 3) - spread_pct * 2


async def current_spread(symbol):
    try:
        book = await orderbook(symbol, 5)
        bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
        mid = (bid + ask) / 2
        return ((ask - bid) / mid * 100) if mid else None
    except Exception as exc:
        print(f"[ACTIVITY-WARN] {symbol} orderbook alınamadı: {exc}", flush=True)
        return None


async def load_market(symbols, days, data_source, start_ts, end_ts, interval="5m"):
    if data_source == "historical-db":
        interval_ms = {"1m": 60 * 1000, "3m": 3 * 60 * 1000, "5m": 5 * 60 * 1000,
                       "15m": 15 * 60 * 1000, "30m": 30 * 60 * 1000}[interval]
        warmup_ms = max(int(days * 86400 * 1000), 250 * interval_ms)
        start_ms = int(start_ts * 1000) - warmup_ms
        end_ms = int(end_ts * 1000)

        async def load_cached(symbol):
            try:
                rows = await database.get_market_candles(symbol, interval, start_ms, end_ms)
                data = rows_to_series(rows)
                print(f"[DATA] {symbol} source=historical_candles interval={interval} candles={len(data['times'])}", flush=True)
                return symbol, data, 0.0, None, None
            except Exception as exc:
                return symbol, None, 0.0, None, str(exc)

        return await asyncio.gather(*(load_cached(symbol) for symbol in symbols))

    ticker_rows = await ticker_24h()
    quote_volumes = {str(row.get("symbol", "")).upper(): float(row.get("quoteVolume", 0) or 0) for row in ticker_rows}
    semaphore = asyncio.Semaphore(6)

    async def fetch(symbol):
        async with semaphore:
            try:
                # Preserve the chronological OOS boundary.  Fetching the latest
                # `days` without this end timestamp makes an older requested
                # window silently depend on newer public candles.
                rows, spread = await asyncio.gather(
                    historical_klines(symbol, interval, days, int(end_ts * 1000)), current_spread(symbol))
                data = rows_to_series(rows)
                print(f"[DATA] {symbol} source=BinanceTR-public interval={interval} candles={len(data['times'])}", flush=True)
                return symbol, data, quote_volumes.get(symbol, 0.0), spread, None
            except Exception as exc:
                return symbol, None, 0.0, None, str(exc)

    return await asyncio.gather(*(fetch(symbol) for symbol in symbols))


def feature_snapshot(analyzer, window):
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    bb = analyzer.calculate_bollinger_bands(closes, config.BB_MFI_BB_PERIOD, config.BB_MFI_BB_STD_DEV)
    return {
        "close": closes[-1],
        "bb_lower": bb["lower"] if bb else None,
        "mfi": _mfi(highs, lows, closes, volumes, config.BB_MFI_MFI_PERIOD),
        "rsi": analyzer.calculate_rsi(closes, config.BB_MFI_RSI_PERIOD),
        "atr": analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD),
    }


def pine_profile(version):
    return {
        "v1": {"bb_period": 21, "bb_std": 2.0, "rsi_period": 13,
               "buy_rsi_min": 30.0, "sell_rsi_min": 70.0, "stop_pct": None, "tp_pct": None},
        "v2": {"bb_period": 18, "bb_std": 2.0, "rsi_period": 13,
               "buy_rsi_min": 22.0, "sell_rsi_min": 82.0, "stop_pct": 0.06604, "tp_pct": 0.02328},
        "v3": {"bb_period": 21, "bb_std": 2.0, "rsi_period": 13, "mfi_period": 16,
               "buy_mfi_max": 59.0, "sell_rsi_min": 69.0, "sell_mfi_min": 69.0,
               "stop_pct": 0.08882, "tp_pct": 0.02317},
    }.get(version)


def strategy_decision(analyzer, window, symbol, version):
    if version == "current":
        return analyzer.strategy_bb_mfi_mean_reversion(window, symbol)
    profile = pine_profile(version)
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    minimum = max(profile["bb_period"], profile.get("mfi_period", 0) + 1, profile["rsi_period"] + 1)
    if min(len(closes), len(highs), len(lows), len(volumes)) < minimum:
        return None
    bb = analyzer.calculate_bollinger_bands(closes, profile["bb_period"], profile["bb_std"])
    rsi = analyzer.calculate_rsi(closes, profile["rsi_period"])
    if not bb or rsi is None:
        return None
    if version in {"v1", "v2"}:
        if closes[-1] < bb["lower"] and rsi > profile["buy_rsi_min"]:
            return "buy"
        if closes[-1] > bb["upper"] and rsi > profile["sell_rsi_min"]:
            return "sell"
        return None
    mfi = _mfi(highs, lows, closes, volumes, profile["mfi_period"])
    if mfi is None:
        return None
    if closes[-1] < bb["lower"] and mfi < profile["buy_mfi_max"]:
        return "buy"
    if closes[-1] > bb["upper"] and rsi > profile["sell_rsi_min"] and mfi > profile["sell_mfi_min"]:
        return "sell"
    return None


def entry_filter_passes(analyzer, window, args):
    """Optional, causal filters evaluated only on the already-closed signal candle."""
    if not args.entry_ema200_filter and not args.entry_momentum_slowdown_filter:
        return True
    closes = window["closes"]
    if args.entry_ema200_filter:
        ema200 = analyzer.calculate_ema(closes, 200)
        if ema200 is None or closes[-1] < ema200:
            return False
    if args.entry_momentum_slowdown_filter:
        # Mean-reversion entry is allowed only after the latest closed candle
        # stops extending the immediate selloff.
        if len(closes) < 2 or closes[-1] < closes[-2]:
            return False
    return True


def entry_volume_dip_passes(window, args):
    """Causal entry confirmation: liquid signal candle plus rejection from its low."""
    volumes, highs, lows, closes = (window[key] for key in ("volumes", "highs", "lows", "closes"))
    if args.entry_min_volume_ratio > 0:
        average = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0.0
        if not average or volumes[-1] / average < args.entry_min_volume_ratio:
            return False, "entry_volume_ratio"
    if args.entry_dip_confirmation:
        candle_range = highs[-1] - lows[-1]
        close_position = (closes[-1] - lows[-1]) / candle_range if candle_range > 0 else 0.0
        if close_position < args.entry_dip_min_close_position:
            return False, "dip_not_rejected"
    if args.entry_mfi_reversal:
        profile = pine_profile(args.pine_version)
        mfi_period = profile.get("mfi_period", config.BB_MFI_MFI_PERIOD) if profile else config.BB_MFI_MFI_PERIOD
        previous_mfi = _mfi(highs[:-1], lows[:-1], closes[:-1], volumes[:-1], mfi_period)
        current_mfi = _mfi(highs, lows, closes, volumes, mfi_period)
        if previous_mfi is None or current_mfi is None or current_mfi < previous_mfi + args.entry_mfi_reversal_min_delta:
            return False, "mfi_not_reversing"
    if args.entry_mfi_slowdown_max_drop is not None:
        profile = pine_profile(args.pine_version)
        mfi_period = profile.get("mfi_period", config.BB_MFI_MFI_PERIOD) if profile else config.BB_MFI_MFI_PERIOD
        previous_mfi = _mfi(highs[:-1], lows[:-1], closes[:-1], volumes[:-1], mfi_period)
        current_mfi = _mfi(highs, lows, closes, volumes, mfi_period)
        if previous_mfi is None or current_mfi is None or current_mfi < previous_mfi - args.entry_mfi_slowdown_max_drop:
            return False, "mfi_still_falling"
    return True, None


def high_downtrend_entry(analyzer, window, args):
    """Reject a mean-reversion long during a confirmed, fast M5 selloff."""
    closes, highs, lows = (window[key] for key in ("closes", "highs", "lows"))
    adx_data = _adx(highs, lows, closes) or {}
    adx, plus_di, minus_di = adx_data.get("adx"), adx_data.get("plus_di"), adx_data.get("minus_di")
    if len(closes) < 13 or not all(isinstance(value, (int, float)) for value in (adx, plus_di, minus_di)):
        return True
    return_1h = closes[-1] / closes[-13] - 1 if closes[-13] else 0.0
    return_15m = closes[-1] / closes[-4] - 1 if closes[-4] else 0.0
    return (adx >= args.high_downtrend_min_adx and
            minus_di - plus_di >= args.high_downtrend_min_di_gap and
            return_1h <= -args.high_downtrend_min_return_1h_pct / 100 and
            return_15m <= -args.high_downtrend_min_return_15m_pct / 100)


def low_volume_for_pyramid(window, threshold):
    volumes = window["volumes"]
    if len(volumes) < 21:
        return False
    average = sum(volumes[-21:-1]) / 20
    return bool(average and volumes[-1] / average < threshold)


def all_position_layers_net_profitable(position, exit_fill, commission_pct):
    """True only when every existing entry layer clears its own entry and exit costs."""
    layers = position.get("entry_layers") or []
    if not layers:
        return False
    for layer in layers:
        proceeds = layer["quantity"] * exit_fill
        if proceeds - proceeds * commission_pct - layer["invested"] - layer["entry_fees"] <= 0:
            return False
    return True


def replay_features(analyzer, window, version):
    profile = pine_profile(version)
    if not profile:
        return feature_snapshot(analyzer, window)
    closes, highs, lows, volumes = (window[key] for key in ("closes", "highs", "lows", "volumes"))
    bb = analyzer.calculate_bollinger_bands(closes, profile["bb_period"], profile["bb_std"])
    return {"close": closes[-1], "bb_lower": bb["lower"] if bb else None,
            "bb_upper": bb["upper"] if bb else None,
            "rsi": analyzer.calculate_rsi(closes, profile["rsi_period"]),
            "mfi": _mfi(highs, lows, closes, volumes, profile.get("mfi_period", 16)) if version == "v3" else None,
            "atr": analyzer.calculate_atr(window, config.SYSTEM_ATR_PERIOD)}


def mtf_entry_features(analyzer, symbol, price, signal_ts, base_window, mtf_series):
    """Build causal M1/M5/M15/H1/H4 snapshots using only closed candles."""
    snapshots = {}
    for interval, data in mtf_series.items():
        if not data or not data.get("times"):
            continue
        end = bisect.bisect_right(data["times"], signal_ts)
        if end < 55:
            continue
        start = max(0, end - 250)
        snapshots[interval] = {
            "opens": data["opens"][start:end], "highs": data["highs"][start:end],
            "lows": data["lows"][start:end], "closes": data["closes"][start:end],
            "volumes": data["volumes"][start:end],
            "timestamps": [value * 1000 for value in data["times"][start:end]],
            "last_closed_at_ms": data["times"][end - 1] * 1000,
        }
    if "5m" not in snapshots:
        snapshots["5m"] = {
            "opens": base_window["opens"], "highs": base_window["highs"],
            "lows": base_window["lows"], "closes": base_window["closes"],
            "volumes": base_window["volumes"],
            "timestamps": [value * 1000 for value in base_window["times"]],
            "last_closed_at_ms": base_window["times"][-1] * 1000,
        }
    result = {"symbol": symbol, "price": price, "signal_timestamp": signal_ts, "timeframes": {}}
    for interval in ("1m", "5m", "15m", "1h", "4h"):
        snapshot = calculate_snapshot(symbol, price, snapshots, primary_timeframe=interval)
        bollinger = ((snapshot.get("channels") or {}).get("bollinger") or {})
        raw = snapshots.get(interval) or {}
        closes = raw.get("closes") or []
        ema9 = analyzer.calculate_ema(closes, 9)
        previous_ema9 = analyzer.calculate_ema(closes[:-1], 9)
        ema21 = analyzer.calculate_ema(closes, 21)
        ema50 = analyzer.calculate_ema(closes, 50)
        # Exact Gainer Radar definition, not merely the broader snapshot
        # alignment label: price must be above EMA9 and EMA9 must be rising.
        radar_bullish = bool(ema9 and previous_ema9 and ema21 and ema50 and closes and
                             closes[-1] > ema9 > ema21 > ema50 and ema9 > previous_ema9)
        result["timeframes"][interval] = {
            "data_ready": snapshot.get("data_ready", False),
            "alignment": (snapshot.get("trend") or {}).get("alignment"),
            "atr_pct": (snapshot.get("volatility") or {}).get("atr_pct"),
            "bb_position": bollinger.get("position"),
            "bb_width_pct": bollinger.get("width_pct"),
            "rsi_14": (snapshot.get("momentum") or {}).get("rsi_14"),
            "volume_ratio_20": (snapshot.get("volume") or {}).get("volume_ratio_20"),
            "orderflow_proxy_20": analyzer.calculate_orderflow_proxy(raw),
            "radar_bullish": radar_bullish,
        }
    return result


def mtf_entry_gate(features, mode):
    """Research-only causal gate; thresholds come from the prior trade study."""
    tf = features.get("timeframes", {})
    align_15m = (tf.get("15m") or {}).get("alignment")
    align_1h = (tf.get("1h") or {}).get("alignment")
    bullish_count = sum((tf.get(interval) or {}).get("alignment") == "bullish" for interval in ("1m", "5m", "15m", "1h", "4h"))
    radar_all_5 = all((tf.get(interval) or {}).get("radar_bullish") is True for interval in ("1m", "5m", "15m", "1h", "4h"))
    if mode == "bullish-count":
        return bullish_count >= 3, f"bullish_count_{bullish_count}"
    if mode in {"all-5", "all-5-volume-flow"}:
        if not radar_all_5:
            return False, "radar_not_5of5"
        if mode == "all-5":
            return True, "radar_5of5"
        m1, m5 = tf.get("1m") or {}, tf.get("5m") or {}
        volume_ok = all(isinstance(item.get("volume_ratio_20"), (int, float)) and item["volume_ratio_20"] >= 1.0 for item in (m1, m5))
        flow_ok = all(isinstance(item.get("orderflow_proxy_20"), (int, float)) and item["orderflow_proxy_20"] >= 0.0 for item in (m1, m5))
        return volume_ok and flow_ok, f"radar_5of5_volume_{'ok' if volume_ok else 'fail'}_flow_{'ok' if flow_ok else 'fail'}"
    if mode in {"acetry-rule", "acetry-rule-relaxed"}:
        m1 = tf.get("1m") or {}
        h1 = tf.get("1h") or {}
        h4 = tf.get("4h") or {}
        relaxed = mode == "acetry-rule-relaxed"
        rsi_limit = 45 if relaxed else 40
        atr_limit = 0.0005 if relaxed else 0.00866
        bb_limit = 0.005 if relaxed else 0.03830
        rsi_ok = isinstance(m1.get("rsi_14"), (int, float)) and m1["rsi_14"] < rsi_limit
        atr_ok = isinstance(m1.get("atr_pct"), (int, float)) and m1["atr_pct"] >= atr_limit
        bb_ok = isinstance(m1.get("bb_width_pct"), (int, float)) and m1["bb_width_pct"] >= bb_limit
        h1_ok = h1.get("alignment") == "bullish"
        h4_ok = h4.get("alignment") in {"bullish", "mixed"}
        passed = rsi_ok and atr_ok and bb_ok and h1_ok and h4_ok and bullish_count >= 2
        return passed, f"acetry_{'relaxed' if relaxed else 'strict'}_rsi_{'ok' if rsi_ok else 'fail'}_atr_{'ok' if atr_ok else 'fail'}_bb_{'ok' if bb_ok else 'fail'}_h1_{'ok' if h1_ok else 'fail'}_h4_{'ok' if h4_ok else 'fail'}_bullish_{bullish_count}"
    if mode == "high-tf":
        return align_1h == "bullish" and align_15m != "mixed", "high_tf_alignment"
    score = 0
    if align_1h == "bullish" and align_15m != "mixed": score += 2
    if align_15m == "bullish": score += 1
    atr_5m = (tf.get("5m") or {}).get("atr_pct") or 0
    bb_5m = (tf.get("5m") or {}).get("bb_position")
    if atr_5m >= 0.0034: score += 1
    if bb_5m is not None and bb_5m <= 0.145: score += 1
    if (tf.get("1m") or {}).get("alignment") == "mixed": score -= 2
    if align_15m == "mixed" or align_1h == "mixed": score -= 2
    return score >= 2, f"research_score_{score}"


async def run(args):
    if args.live_parity_72h:
        apply_live_parity_72h_profile(args)
    if args.interval not in {"1m", "3m", "5m", "15m"}:
        raise SystemExit("Bu replay yalnızca 1m, 3m, 5m veya 15m ile çalışır")
    now = int(time.time())
    local_tz = ZoneInfo(args.timezone)
    end_ts = min(now, int(datetime.fromisoformat(args.end_date).replace(tzinfo=local_tz).timestamp())) if args.end_date else now - int(args.end_hours_ago * 3600)
    start_ts = int(datetime.fromisoformat(args.start_date).replace(tzinfo=local_tz).timestamp()) if args.start_date else now - int(args.start_hours_ago * 3600)
    if start_ts >= end_ts:
        raise SystemExit("start-hours-ago, end-hours-ago değerinden büyük olmalıdır")
    if args.profit_lock_trigger_pct < 0 or args.profit_lock_pct < 0 or args.profit_lock_pct > args.profit_lock_trigger_pct:
        raise SystemExit("profit-lock yüzdeleri 0 <= lock <= trigger olmalıdır")

    discovered_symbols = args.symbols or await trading_symbols("TRY")
    requested_symbols = [symbol.replace("_", "").upper() for symbol in discovered_symbols]
    profile = pine_profile(args.pine_version)
    base_stop_pct = args.stop_pct if args.stop_pct is not None else (profile["stop_pct"] if profile else config.BB_MFI_STOP_LOSS_PCT)
    stop_pct = args.risk_stop_pct if args.risk_stop_pct is not None else base_stop_pct
    tp_pct = args.tp_pct if args.tp_pct is not None else (profile["tp_pct"] if profile else config.BB_MFI_TAKE_PROFIT_PCT)
    stop_pct = stop_pct if stop_pct and stop_pct > 0 else None
    tp_pct = tp_pct if tp_pct and tp_pct > 0 else None
    print(f"[START] strategy={config.ACTIVE_STRATEGY} pine_version={args.pine_version} initial={config.INITIAL_BALANCE_TRY:.2f} TRY window={iso(start_ts)}..{iso(end_ts)}", flush=True)
    print(f"[CONFIG] universe={len(requested_symbols)} source={'cli' if args.symbols else 'BinanceTR-exchangeInfo'} order_pct={args.order_pct:.4f} pyramiding={args.pyramiding} max_positions={args.max_positions} commission={config.COMMISSION_PCT:.6f} spread={args.spread_pct:.6f} slippage={args.slippage_pct:.6f}", flush=True)

    if args.data_source == "historical-db":
        await database.init_db()
    loaded = await load_market(requested_symbols, args.fetch_days, args.data_source, start_ts, end_ts, args.interval)
    analyzer = ScalpAnalyzer(None)
    series, activity, quality, skipped = {}, {}, {}, {}
    for symbol, data, quote_volume, live_spread, error in loaded:
        if error or not data or not data["times"]:
            skipped[symbol] = error or "empty_candles"
            print(f"[DATA-SKIP] {symbol} reason={skipped[symbol]}", flush=True)
            continue
        status = activity_metrics(analyzer, data, quote_volume, live_spread)
        activity[symbol] = status
        quality[symbol] = data_quality(data)
        print(f"[ACTIVITY] {symbol} status={status['status']} metrics={json.dumps(status, ensure_ascii=False)}", flush=True)
        if args.use_all_requested or args.historical_activity or args.data_source == "historical-db" or status["status"] == "ACTIVE":
            series[symbol] = data
    if not series:
        raise SystemExit("Aktif ve kullanılabilir sembol bulunamadı")

    indices = {symbol: {ts: index for index, ts in enumerate(data["times"])} for symbol, data in series.items()}
    mtf_series_by_symbol = {symbol: {} for symbol in series}
    mtf_quality = {}
    if args.mtf_feature_gate != "none":
        for interval, warmup_days in (("1m", 4), ("15m", 6), ("1h", 14), ("4h", 40)):
            loaded_mtf = await load_market(list(series), warmup_days, args.data_source, start_ts, end_ts, interval)
            for symbol, data, _, _, error in loaded_mtf:
                if error or not data or not data["times"]:
                    skipped[f"{symbol}:{interval}"] = error or "empty_candles"
                    continue
                mtf_series_by_symbol[symbol][interval] = data
                mtf_quality[f"{symbol}:{interval}"] = data_quality(data)
        print(f"[MTF] gate={args.mtf_feature_gate} symbols={len(mtf_series_by_symbol)} loaded={sum(len(value) for value in mtf_series_by_symbol.values())}", flush=True)
    if args.initial_active_only:
        # Start from the symbols that were objectively ACTIVE at the beginning
        # of this replay window, not from today's visible activity list.
        initially_active = {}
        for symbol, data in series.items():
            index = next((i for i, candle_ts in enumerate(data["times"]) if candle_ts >= start_ts), None)
            if index is None:
                continue
            # Universe selection stays on the existing M5 gate; M1 is then an
            # execution-time confirmation on that same fixed universe.
            # The starting universe deliberately uses only the base M5/volume
            # gate. M1/M30 series are loaded immediately afterwards and are
            # applied to every actual entry decision.
            active, _ = historical_activity(analyzer, window_at(data, index), args.spread_pct,
                                            args, apply_auxiliary=False)
            if active:
                initially_active[symbol] = (data, historical_quality_score(analyzer, window_at(data, index), args.spread_pct))
        if args.initial_active_limit:
            initially_active = dict(sorted(initially_active.items(), key=lambda item: item[1][1], reverse=True)[:args.initial_active_limit])
        initially_active = {symbol: item[0] for symbol, item in initially_active.items()}
        series = initially_active
        indices = {symbol: {ts: index for index, ts in enumerate(data["times"])} for symbol, data in series.items()}
        if not series:
            raise SystemExit("Pencere başlangıcında ACTIVE sembol bulunamadı")
    m1_series, m1_indices, m30_series, m30_indices = {}, {}, {}, {}
    auxiliary = (("1m", m1_series, m1_indices, args.activity_m1_filter or args.activity_m1_flat_filter or args.activity_m1_inactivity_score_filter or args.activity_m1_m5_compression_filter or args.activity_m1_relative_idle_filter),
                 ("30m", m30_series, m30_indices, args.activity_m30_filter))
    required_auxiliary = set()
    for interval, target_series, target_times, enabled in auxiliary:
        if not enabled:
            continue
        loaded_auxiliary = await load_market(list(series), args.fetch_days, args.data_source, start_ts, end_ts, interval)
        for symbol, data, _, _, error in loaded_auxiliary:
            if error or not data or not data["times"]:
                skipped[f"{symbol}:{interval}"] = error or "empty_candles"
                continue
            target_series[symbol] = data
            target_times[symbol] = data["times"]
        required_auxiliary.update(target_series)
        series = {symbol: data for symbol, data in series.items() if symbol in target_series}
        indices = {symbol: {ts: index for index, ts in enumerate(data["times"])} for symbol, data in series.items()}
        if not series:
            raise SystemExit(f"{interval} aktivite filtresi için kullanılabilir sembol bulunamadı")
    timeline = sorted({ts for data in series.values() for ts in data["times"] if start_ts <= ts <= end_ts})
    cash = initial = float(config.INITIAL_BALANCE_TRY)
    positions, trades = {}, []
    fees_paid = 0.0
    peak_equity, max_drawdown = cash, 0.0
    signal_counts = Counter()
    daily_stop_counts = Counter()
    daily_symbol_pnl = Counter()
    filter_counts = Counter()
    loss_cooldown_until = {}
    activity_status = {symbol: False for symbol in series}
    activity_status_reason = {symbol: "warming" for symbol in series}
    last_activity_bucket = None

    def arm_loss_cooldown(symbol, pnl, exit_ts):
        """Record realised symbol PnL and optionally block fresh entries after a loss."""
        exit_day = datetime.fromtimestamp(exit_ts, tz=local_tz).date().isoformat()
        daily_symbol_pnl[(symbol, exit_day)] += pnl
        if args.symbol_loss_cooldown_hours <= 0 or pnl >= 0:
            return
        until = exit_ts + int(args.symbol_loss_cooldown_hours * 3600)
        loss_cooldown_until[symbol] = max(loss_cooldown_until.get(symbol, 0), until)

    for ts in timeline:
        exits = entries = blocked = signals = 0
        activity_bucket = ts // (args.activity_refresh_minutes * 60)
        day_key = datetime.fromtimestamp(ts, tz=local_tz).date().isoformat()
        if args.historical_activity and activity_bucket != last_activity_bucket:
            last_activity_bucket = activity_bucket
            for symbol, data in series.items():
                index = indices[symbol].get(ts)
                if index is None: continue
                m1_index = bisect.bisect_right(m1_indices.get(symbol, []), ts) - 1
                m30_index = bisect.bisect_right(m30_indices.get(symbol, []), ts) - 1
                active, state = historical_activity(
                    analyzer, window_at(data, index), args.spread_pct, args,
                    m1_series.get(symbol), m1_index if m1_index >= 0 else None,
                    m30_series.get(symbol), m30_index if m30_index >= 0 else None,
                )
                activity_status[symbol] = active
                activity_status_reason[symbol] = state
                position = positions.get(symbol)
                price = data["opens"][index]
                if args.passive_direct_exit and not active and position:
                    exit_fill = price * (1 - args.spread_pct / 2 - args.slippage_pct)
                    proceeds = position["quantity"] * exit_fill
                    exit_fee = proceeds * config.COMMISSION_PCT
                    pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                    cash += proceeds - exit_fee; fees_paid += exit_fee
                    trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                                   "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                                   "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6),
                                   "reason": "historical_activity_passive_direct_exit"})
                    arm_loss_cooldown(symbol, pnl, ts)
                    del positions[symbol]; exits += 1
                elif not args.disable_passive_net_exit and not active and position:
                    exit_fill = price * (1 - args.spread_pct / 2 - args.slippage_pct)
                    proceeds = position["quantity"] * exit_fill
                    exit_fee = proceeds * config.COMMISSION_PCT
                    pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                    if pnl >= 0:
                        cash += proceeds - exit_fee; fees_paid += exit_fee
                        trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                                       "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                                       "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6),
                                       "reason": "historical_activity_passive_net_exit"})
                        arm_loss_cooldown(symbol, pnl, ts)
                        del positions[symbol]; exits += 1
                if (args.passive_loss_exit_hours > 0 and not active and symbol in positions and position and
                      ts - position["entry_time"] >= args.passive_loss_exit_hours * 3600):
                    close = data["closes"][index]
                    ema9 = analyzer.calculate_ema(window_at(data, index)["closes"], 9)
                    ema21 = analyzer.calculate_ema(window_at(data, index)["closes"], 21)
                    atr = analyzer.calculate_atr(window_at(data, index), 14) or 0.0
                    if ema9 is not None and ema21 is not None and ema9 < ema21 and close < position["entry"] - atr:
                        exit_fill = price * (1 - args.spread_pct / 2 - args.slippage_pct)
                        proceeds = position["quantity"] * exit_fill; exit_fee = proceeds * config.COMMISSION_PCT
                        cash += proceeds - exit_fee; fees_paid += exit_fee
                        pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                        trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                                       "entry": position["entry"], "exit": exit_fill, "layers": position["layers"], "pnl": round(pnl, 6),
                                       "commission": round(position["entry_fees"] + exit_fee, 6), "reason": "historical_passive_loss_ema_atr_exit"})
                        arm_loss_cooldown(symbol, pnl, ts)
                        del positions[symbol]; exits += 1
        # Confirmed sell signals from the previous candle execute at this open.
        for symbol, position in list(positions.items()):
            index = indices[symbol].get(ts)
            if index is None or index < 1:
                continue
            data = series[symbol]
            if (args.breakeven_exit_after_hours > 0 and
                    ts - position["entry_time"] >= args.breakeven_exit_after_hours * 3600):
                exit_quote = data["opens"][index]
                exit_fill = exit_quote * (1 - args.spread_pct / 2 - args.slippage_pct)
                proceeds = position["quantity"] * exit_fill
                exit_fee = proceeds * config.COMMISSION_PCT
                pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                if pnl >= 0:
                    cash += proceeds - exit_fee; fees_paid += exit_fee
                    trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                                   "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                                   "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6),
                                   "reason": "cost_breakeven_exit"})
                    arm_loss_cooldown(symbol, pnl, ts)
                    del positions[symbol]; exits += 1
                    print(f"[EXIT] {iso(ts)} {symbol} reason=cost_breakeven_exit pnl={pnl:+.2f} cash={cash:.2f}", flush=True)
                    continue
            if args.max_hold_hours > 0 and ts - position["entry_time"] >= args.max_hold_hours * 3600:
                exit_quote, reason = data["opens"][index], "max_hold_exit"
                exit_fill = exit_quote * (1 - args.spread_pct / 2 - args.slippage_pct)
                proceeds = position["quantity"] * exit_fill
                exit_fee = proceeds * config.COMMISSION_PCT
                cash += proceeds - exit_fee; fees_paid += exit_fee
                pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                               "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                               "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6), "reason": reason})
                arm_loss_cooldown(symbol, pnl, ts)
                del positions[symbol]; exits += 1
                print(f"[EXIT] {iso(ts)} {symbol} reason={reason} pnl={pnl:+.2f} cash={cash:.2f}", flush=True)
                continue
            if args.adverse_ema_atr_exit_hours > 0 and ts - position["entry_time"] >= args.adverse_ema_atr_exit_hours * 3600:
                window = window_at(data, index - 1)
                ema9 = analyzer.calculate_ema(window["closes"], 9)
                ema21 = analyzer.calculate_ema(window["closes"], 21)
                atr = analyzer.calculate_atr(window, 14) or 0.0
                close = window["closes"][-1]
                if ema9 is not None and ema21 is not None and ema9 < ema21 and close < position["entry"] - atr * args.adverse_ema_atr_multiplier:
                    exit_quote, reason = data["opens"][index], "adverse_ema_atr_exit"
                    exit_fill = exit_quote * (1 - args.spread_pct / 2 - args.slippage_pct)
                    proceeds = position["quantity"] * exit_fill
                    exit_fee = proceeds * config.COMMISSION_PCT
                    cash += proceeds - exit_fee; fees_paid += exit_fee
                    pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                    trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                                   "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                                   "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6), "reason": reason})
                    arm_loss_cooldown(symbol, pnl, ts)
                    del positions[symbol]; exits += 1
                    print(f"[EXIT] {iso(ts)} {symbol} reason={reason} pnl={pnl:+.2f} cash={cash:.2f}", flush=True)
                    continue
            previous_window = window_at(data, index - 1)
            if strategy_decision(analyzer, previous_window, symbol, args.pine_version) != "sell":
                continue
            exit_quote, reason = data["opens"][index], "bb_mfi_v3_signal_exit"
            exit_fill = exit_quote * (1 - args.spread_pct / 2 - args.slippage_pct)
            proceeds = position["quantity"] * exit_fill
            exit_fee = proceeds * config.COMMISSION_PCT
            cash += proceeds - exit_fee
            fees_paid += exit_fee
            pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
            trade = {"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                     "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                     "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6), "reason": reason}
            trades.append(trade)
            arm_loss_cooldown(symbol, pnl, ts)
            del positions[symbol]
            exits += 1
            print(f"[EXIT] {iso(ts)} {symbol} reason={reason} pnl={pnl:+.2f} cash={cash:.2f}", flush=True)

        # Confirmed buy signals from the previous candle execute at this open.
        for symbol, data in series.items():
            index = indices[symbol].get(ts)
            if index is None or index < 21:
                continue
            window = window_at(data, index - 1)
            feature = replay_features(analyzer, window, args.pine_version)
            decision = strategy_decision(analyzer, window, symbol, args.pine_version)
            signal_counts[decision or "none"] += 1
            if decision != "buy":
                continue
            if args.historical_activity and not activity_status.get(symbol, False):
                blocked += 1; filter_counts[f"historical_activity_{activity_status_reason.get(symbol, 'passive')}"] += 1
                continue
            signals += 1
            print(f"[SIGNAL] {iso(data['times'][index - 1])} {symbol} BUY fill_at={iso(ts)} features={json.dumps(feature, ensure_ascii=False, default=str)}", flush=True)
            # Research-only exported-trade candidate.  This is deliberately
            # applied after the strategy has produced a causal BUY and uses a
            # fixed RSI(14), matching the persisted decision snapshot field.
            # It never mutates Config or the live analyzer contract.
            if args.entry_min_rsi14 > 0:
                rsi14 = analyzer.calculate_rsi(window["closes"], 14)
                if rsi14 is None or rsi14 < args.entry_min_rsi14:
                    blocked += 1; filter_counts["entry_min_rsi14"] += 1
                    print(f"[BLOCKED] {symbol} reason=entry_min_rsi14 value={rsi14}", flush=True)
                    continue
            if args.mtf_feature_gate != "none":
                mtf_features = mtf_entry_features(analyzer, symbol, data["opens"][index], data["times"][index - 1], window, {"5m": data, **mtf_series_by_symbol.get(symbol, {})})
                passed, gate_reason = mtf_entry_gate(mtf_features, args.mtf_feature_gate)
                if not passed:
                    blocked += 1; filter_counts[f"mtf_{gate_reason}"] += 1
                    print(f"[BLOCKED] {symbol} reason=mtf_{gate_reason}", flush=True)
                    continue
            if args.daily_stop_limit and daily_stop_counts[(symbol, day_key)] >= args.daily_stop_limit:
                blocked += 1
                print(f"[BLOCKED] {symbol} reason=daily_stop_limit", flush=True)
                continue
            if (args.daily_symbol_loss_limit_try > 0 and
                    daily_symbol_pnl[(symbol, day_key)] <= -args.daily_symbol_loss_limit_try):
                blocked += 1; filter_counts["daily_symbol_loss_limit"] += 1
                print(f"[BLOCKED] {symbol} reason=daily_symbol_loss_limit pnl={daily_symbol_pnl[(symbol, day_key)]:+.2f}", flush=True)
                continue
            if ts < loss_cooldown_until.get(symbol, 0):
                blocked += 1; filter_counts["symbol_loss_cooldown"] += 1
                print(f"[BLOCKED] {symbol} reason=symbol_loss_cooldown until={iso(loss_cooldown_until[symbol])}", flush=True)
                continue
            downtrend_risk = high_downtrend_entry(analyzer, window, args)
            if args.high_downtrend_entry_filter and downtrend_risk:
                blocked += 1; filter_counts["high_downtrend_entry"] += 1
                print(f"[BLOCKED] {symbol} reason=high_downtrend_entry", flush=True)
                continue
            if not entry_filter_passes(analyzer, window, args):
                blocked += 1
                print(f"[BLOCKED] {symbol} reason=entry_filter", flush=True)
                continue
            entry_ok, entry_reason = entry_volume_dip_passes(window, args)
            if not entry_ok:
                blocked += 1; filter_counts[entry_reason] += 1
                print(f"[BLOCKED] {symbol} reason={entry_reason}", flush=True)
                continue
            position = positions.get(symbol)
            if position and position["layers"] >= args.pyramiding:
                extension_allowed = False
                if position["layers"] < args.pyramiding + args.pyramid_profit_extension_layers:
                    exit_fill = data["opens"][index] * (1 - args.spread_pct / 2 - args.slippage_pct)
                    extension_allowed = all_position_layers_net_profitable(position, exit_fill, config.COMMISSION_PCT)
                if not extension_allowed:
                    blocked += 1
                    print(f"[BLOCKED] {symbol} reason=max_layers", flush=True)
                    continue
            if position and (args.pyramid_require_net_profit or args.pyramid_block_underwater_after_hours > 0):
                exit_fill = data["opens"][index] * (1 - args.spread_pct / 2 - args.slippage_pct)
                proceeds = position["quantity"] * exit_fill
                exit_fee = proceeds * config.COMMISSION_PCT
                unrealized_pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
                aged_underwater = (args.pyramid_block_underwater_after_hours > 0 and
                                   ts - position["entry_time"] >= args.pyramid_block_underwater_after_hours * 3600)
                if unrealized_pnl <= 0 and (args.pyramid_require_net_profit or aged_underwater):
                    blocked += 1; filter_counts["pyramid_underwater"] += 1
                    print(f"[BLOCKED] {symbol} reason=pyramid_underwater pnl={unrealized_pnl:+.2f}", flush=True)
                    continue
            if (position and args.pyramid_low_volume_block and position.get("entry_high_downtrend_risk") and
                    ts - position["entry_time"] >= args.pyramid_low_volume_after_hours * 3600 and
                    low_volume_for_pyramid(window, args.pyramid_low_volume_ratio_max)):
                blocked += 1; filter_counts["pyramid_low_volume"] += 1
                print(f"[BLOCKED] {symbol} reason=pyramid_low_volume", flush=True)
                continue
            # Live contract: zero means no global position cap.
            if position is None and args.max_positions > 0 and len(positions) >= args.max_positions:
                blocked += 1
                print(f"[BLOCKED] {symbol} reason=max_open_positions", flush=True)
                continue
            marked_positions = sum(pos["quantity"] * series[held]["closes"][indices[held].get(ts, 0)] for held, pos in positions.items())
            equity = cash + marked_positions
            available_cash = cash / (1 + config.COMMISSION_PCT)
            order_base = available_cash if args.remaining_cash_sizing else equity
            order_value = min(order_base * args.order_pct, available_cash)
            if order_value < config.MIN_PARTIAL_ORDER_TRY:
                blocked += 1
                print(f"[BLOCKED] {symbol} reason=insufficient_cash order={order_value:.2f} cash={cash:.2f}", flush=True)
                continue
            entry_quote = data["opens"][index]
            entry_fill = entry_quote * (1 + args.spread_pct / 2 + args.slippage_pct)
            entry_fee = order_value * config.COMMISSION_PCT
            quantity = order_value / entry_fill
            cash -= order_value + entry_fee
            fees_paid += entry_fee
            if position:
                total_quantity = position["quantity"] + quantity
                position["entry"] = (position["entry"] * position["quantity"] + entry_fill * quantity) / total_quantity
                position["quantity"] = total_quantity
                position["invested"] += order_value
                position["entry_fees"] += entry_fee
                position["layers"] += 1
                position.setdefault("entry_layers", []).append({"quantity": quantity, "invested": order_value, "entry_fees": entry_fee})
                position.pop("profit_lock_stop", None)
            else:
                position = {"entry": entry_fill, "quantity": quantity, "invested": order_value,
                            "entry_fees": entry_fee, "layers": 1, "entry_time": ts,
                            "entry_layers": [{"quantity": quantity, "invested": order_value, "entry_fees": entry_fee}],
                            "entry_high_downtrend_risk": downtrend_risk}
                positions[symbol] = position
            position["stop"] = position["entry"] * (1 - stop_pct) if stop_pct is not None else None
            position["target"] = position["entry"] * (1 + tp_pct) if tp_pct is not None else None
            entries += 1
            print(f"[ENTRY] {iso(ts)} {symbol} layer={position['layers']} value={order_value:.2f} entry={entry_fill:.8f} cash={cash:.2f}", flush=True)

        # Intrabar stop/target events occur after the candle open. Conservative
        # ordering assumes stop first when both levels are touched in one bar.
        for symbol, position in list(positions.items()):
            index = indices[symbol].get(ts)
            if index is None:
                continue
            data = series[symbol]
            high, low = data["highs"][index], data["lows"][index]
            fixed_stop = position["stop"]
            profit_lock_stop = position.get("profit_lock_stop")
            active_stop = max(value for value in (fixed_stop, profit_lock_stop) if value is not None) if any(value is not None for value in (fixed_stop, profit_lock_stop)) else None
            if active_stop is not None and low <= active_stop:
                exit_quote = active_stop
                reason = "profit_lock_stop" if profit_lock_stop is not None and active_stop == profit_lock_stop else "fixed_stop_loss"
            elif position["target"] is not None and high >= position["target"]:
                exit_quote, reason = position["target"], "fixed_take_profit"
            else:
                if arm_profit_lock(position, high, args.profit_lock_trigger_pct, args.profit_lock_pct):
                    print(f"[PROFIT-LOCK-ARMED] {symbol} floor={position['profit_lock_stop']:.8f}", flush=True)
                continue
            exit_fill = exit_quote * (1 - args.spread_pct / 2 - args.slippage_pct)
            proceeds = position["quantity"] * exit_fill
            exit_fee = proceeds * config.COMMISSION_PCT
            cash += proceeds - exit_fee
            fees_paid += exit_fee
            pnl = proceeds - exit_fee - position["invested"] - position["entry_fees"]
            trades.append({"symbol": symbol, "entry_time": position["entry_time"], "exit_time": ts,
                           "entry": position["entry"], "exit": exit_fill, "layers": position["layers"],
                           "pnl": round(pnl, 6), "commission": round(position["entry_fees"] + exit_fee, 6), "reason": reason})
            arm_loss_cooldown(symbol, pnl, ts)
            if reason == "fixed_stop_loss":
                daily_stop_counts[(symbol, day_key)] += 1
            del positions[symbol]
            exits += 1
            print(f"[EXIT] {iso(ts)} {symbol} reason={reason} pnl={pnl:+.2f} cash={cash:.2f}", flush=True)

        marked = cash
        for symbol, position in positions.items():
            index = indices[symbol].get(ts)
            mark = series[symbol]["closes"][index] if index is not None else position["entry"]
            marked += position["quantity"] * mark
        peak_equity = max(peak_equity, marked)
        max_drawdown = max(max_drawdown, (peak_equity - marked) / peak_equity if peak_equity else 0.0)
        print(f"[SCAN] {iso(ts)} symbols={len(series)} signals={signals} entries={entries} exits={exits} blocked={blocked} open={len(positions)} cash={cash:.2f} equity={marked:.2f}", flush=True)

    excluded_open = []
    marked_open = []
    if args.open_position_policy == "exclude":
        # Compatibility mode for prior research reports: unfinished trades are
        # treated as if never opened.
        for symbol, position in positions.items():
            restored = position["invested"] + position["entry_fees"]
            cash += restored
            fees_paid -= position["entry_fees"]
            excluded_open.append({"symbol": symbol, "entry_time": position["entry_time"], "layers": position["layers"], "restored_try": round(restored, 6)})
            print(f"[OPEN-EXCLUDED] {symbol} restored={restored:.2f} reason=treated_as_never_opened", flush=True)
    else:
        # Portfolio-parity mode: retain open paper positions at their last
        # available close instead of erasing their capital and PnL.
        for symbol, position in positions.items():
            data = series[symbol]
            closing_index = max((index for index, ts in enumerate(data["times"]) if ts <= end_ts), default=None)
            mark_price = data["closes"][closing_index] if closing_index is not None else position["entry"]
            liquidation_fill = mark_price * (1 - args.spread_pct / 2 - args.slippage_pct)
            marked_value = position["quantity"] * liquidation_fill
            exit_fee = marked_value * config.COMMISSION_PCT
            unrealized_pnl = marked_value - exit_fee - position["invested"] - position["entry_fees"]
            cash += marked_value - exit_fee
            fees_paid += exit_fee
            marked_open.append({"symbol": symbol, "entry_time": position["entry_time"], "layers": position["layers"],
                                "mark_price": round(mark_price, 8), "liquidation_fill": round(liquidation_fill, 8),
                                "marked_value_try": round(marked_value - exit_fee, 6),
                                "unrealized_pnl_try": round(unrealized_pnl, 6)})
            print(f"[OPEN-MARKED] {symbol} value={marked_value:.2f} unrealized={unrealized_pnl:+.2f}", flush=True)

    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] <= 0]
    gross_profit = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))
    result = {
        "paper_only": True, "source": "Binance TR public API", "retrieved_at": iso(now),
        "replay_mode": "live_parity_72h" if args.live_parity_72h else "research_override",
        "live_config_snapshot": live_parity_snapshot() if args.live_parity_72h else None,
        "fill_model": "next_completed_candle_signal_then_next_candle_open_with_modeled_costs",
        "window": {"start": iso(start_ts), "end": iso(end_ts), "hours": round((end_ts - start_ts) / 3600, 2)},
        "strategy": config.ACTIVE_STRATEGY, "pine_version": args.pine_version,
        "pine_profile": profile,
        "risk_stop_pct": stop_pct,
        "effective_tp_pct": tp_pct,
        "selection_mode": ("all_requested_scan_symbols" if args.use_all_requested else
                           "historical_cached_requested_symbols" if args.data_source == "historical-db" else
                           "current_activity_active_only"),
        "initial_active_only": args.initial_active_only,
        "initial_active_limit": args.initial_active_limit,
        "passive_loss_exit_hours": args.passive_loss_exit_hours,
        "passive_net_exit_enabled": not args.disable_passive_net_exit,
        "passive_direct_exit": args.passive_direct_exit,
        "activity_refresh_minutes": args.activity_refresh_minutes,
        "activity_m1_filter": args.activity_m1_filter,
        "activity_m1_range_bars": args.activity_m1_range_bars,
        "activity_m1_min_range_pct": args.activity_m1_min_range_pct,
        "activity_m1_min_atr_pct": args.activity_m1_min_atr_pct,
        "activity_m1_flat_filter": args.activity_m1_flat_filter,
        "activity_m1_flat_max_range_pct": args.activity_m1_flat_max_range_pct,
        "activity_m1_flat_5m_max_count": args.activity_m1_flat_5m_max_count,
        "activity_m1_flat_30m_max_count": args.activity_m1_flat_30m_max_count,
        "activity_m1_flat_max_volume_ratio": args.activity_m1_flat_max_volume_ratio,
        "activity_m1_relative_idle_filter": args.activity_m1_relative_idle_filter,
        "activity_m1_relative_idle_window_minutes": args.activity_m1_relative_idle_window_minutes,
        "activity_m1_relative_idle_lookback_minutes": args.activity_m1_relative_idle_lookback_minutes,
        "activity_m1_relative_idle_min_score": args.activity_m1_relative_idle_min_score,
        "activity_m1_relative_idle_min_zero_hl_count": args.activity_m1_relative_idle_min_zero_hl_count,
        "activity_m1_relative_idle_min_ticklike_count": args.activity_m1_relative_idle_min_ticklike_count,
        "activity_m1_relative_idle_range_percentile": args.activity_m1_relative_idle_range_percentile,
        "activity_m1_relative_idle_volume_percentile": args.activity_m1_relative_idle_volume_percentile,
        "activity_m1_m5_compression_filter": args.activity_m1_m5_compression_filter,
        "activity_m1_compression_max_atr_pct": args.activity_m1_compression_max_atr_pct,
        "activity_m5_compression_max_atr_pct": args.activity_m5_compression_max_atr_pct,
        "activity_m1_compression_max_bb_width_pct": args.activity_m1_compression_max_bb_width_pct,
        "activity_m1_inactivity_score_filter": args.activity_m1_inactivity_score_filter,
        "activity_m1_inactivity_score_min": args.activity_m1_inactivity_score_min,
        "activity_m1_inactivity_lookback_minutes": args.activity_m1_inactivity_lookback_minutes,
        "activity_m1_inactivity_flat_30m_min_count": args.activity_m1_inactivity_flat_30m_min_count,
        "activity_m1_inactivity_max_volume_ratio": args.activity_m1_inactivity_max_volume_ratio,
        "activity_m1_inactivity_max_abs_cmf": args.activity_m1_inactivity_max_abs_cmf,
        "activity_m1_inactivity_max_abs_tsi": args.activity_m1_inactivity_max_abs_tsi,
        "activity_m1_inactivity_max_abs_cci": args.activity_m1_inactivity_max_abs_cci,
        "activity_m5_min_range_pct": args.activity_m5_min_range_pct,
        "activity_m5_min_atr_pct": args.activity_m5_min_atr_pct,
        "activity_m5_min_volume_ratio": args.activity_m5_min_volume_ratio,
        "activity_m30_filter": args.activity_m30_filter,
        "activity_m30_regime_filter": args.activity_m30_regime_filter,
        "activity_m30_min_range_pct": args.activity_m30_min_range_pct,
        "activity_m30_min_atr_pct": args.activity_m30_min_atr_pct,
        "activity_m30_max_ema20_decline_pct": args.activity_m30_max_ema20_decline_pct,
        "daily_stop_limit": args.daily_stop_limit,
        "daily_symbol_loss_limit_try": args.daily_symbol_loss_limit_try,
        "symbol_loss_cooldown_hours": args.symbol_loss_cooldown_hours,
        "max_hold_hours": args.max_hold_hours,
        "breakeven_exit_after_hours": args.breakeven_exit_after_hours,
        "adverse_ema_atr_exit_hours": args.adverse_ema_atr_exit_hours,
        "adverse_ema_atr_multiplier": args.adverse_ema_atr_multiplier,
        "entry_ema200_filter": args.entry_ema200_filter,
        "entry_momentum_slowdown_filter": args.entry_momentum_slowdown_filter,
        "activity_volume_only": args.activity_volume_only,
        "activity_min_quote_volume_try": args.activity_min_quote_volume_try,
        "entry_min_volume_ratio": args.entry_min_volume_ratio,
        "entry_dip_confirmation": args.entry_dip_confirmation,
        "entry_dip_min_close_position": args.entry_dip_min_close_position,
        "entry_mfi_reversal": args.entry_mfi_reversal,
        "entry_mfi_reversal_min_delta": args.entry_mfi_reversal_min_delta,
        "entry_mfi_slowdown_max_drop": args.entry_mfi_slowdown_max_drop,
        "high_downtrend_entry_filter": args.high_downtrend_entry_filter,
        "entry_min_rsi14": args.entry_min_rsi14,
        "high_downtrend_min_adx": args.high_downtrend_min_adx,
        "high_downtrend_min_di_gap": args.high_downtrend_min_di_gap,
        "high_downtrend_min_return_1h_pct": args.high_downtrend_min_return_1h_pct,
        "high_downtrend_min_return_15m_pct": args.high_downtrend_min_return_15m_pct,
        "pyramid_require_net_profit": args.pyramid_require_net_profit,
        "pyramid_block_underwater_after_hours": args.pyramid_block_underwater_after_hours,
        "pyramid_profit_extension_layers": args.pyramid_profit_extension_layers,
        "pyramid_low_volume_block": args.pyramid_low_volume_block,
        "filter_counts": dict(filter_counts),
        "remaining_cash_sizing": args.remaining_cash_sizing,
        "historical_activity_gate": args.historical_activity,
        "initial_balance_try": initial, "final_balance_try": round(cash, 6),
        "net_pnl_try": round(cash - initial, 6), "net_pnl_pct": round((cash / initial - 1) * 100, 6),
        "closed_trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 4) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "fees_total_including_open_liquidation_try": round(fees_paid, 6), "max_drawdown_pct": round(max_drawdown * 100, 6),
        "active_symbols": sorted(series), "activity": activity, "skipped_symbols": skipped,
        "data_quality": quality,
        "mtf_feature_gate": args.mtf_feature_gate,
        "acetry_rule": {"m1_rsi_lt": 45 if args.mtf_feature_gate == "acetry-rule-relaxed" else 40,
                         "m1_atr_pct_gte": 0.0005 if args.mtf_feature_gate == "acetry-rule-relaxed" else 0.00866,
                         "m1_bb_width_pct_gte": 0.005 if args.mtf_feature_gate == "acetry-rule-relaxed" else 0.03830,
                         "h1_alignment": "bullish", "h4_alignment": ["bullish", "mixed"], "mtf_bullish_count_gte": 2},
        "mtf_data_quality": mtf_quality,
        "prepared_features": ["bb_lower", "bb_upper", "mfi", "rsi", "atr", "close", "m1_alignment", "m5_alignment", "m15_alignment", "h1_alignment", "h4_alignment", "mtf_atr_pct", "mtf_bb_position"],
        "open_position_policy": args.open_position_policy,
        "open_positions_excluded": excluded_open, "open_positions_marked": marked_open,
        "signal_counts": dict(signal_counts),
        "exit_reasons": dict(Counter(trade["reason"] for trade in trades)), "trades": trades,
        "cost_model": {"commission_pct_each_side": config.COMMISSION_PCT,
                       "assumed_full_spread_pct": args.spread_pct, "slippage_pct_each_side": args.slippage_pct},
        "profit_lock": {"trigger_pct": args.profit_lock_trigger_pct, "lock_pct": args.profit_lock_pct,
                        "same_bar_fill": False},
        "limitations": [
            "Historical order-book depth, ticker path and spread are unavailable; configured spread/slippage model fills.",
            "This reuses the deterministic BB-MFI signal and shared-wallet rules, but cannot reconstruct historical WebSocket arrival order or intrabar ticker fills.",
        ],
        "reconciliation": {"expected": round(initial + sum(trade["pnl"] for trade in trades) + sum(item["unrealized_pnl_try"] for item in marked_open), 6),
                           "actual": round(cash, 6),
                           "difference": round(cash - (initial + sum(trade["pnl"] for trade in trades) + sum(item["unrealized_pnl_try"] for item in marked_open)), 8)},
    }
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[COMPLETE] result={output.resolve()}", flush=True)
    print("RESULT_JSON=" + json.dumps({key: result[key] for key in ("initial_balance_try", "final_balance_try", "net_pnl_try", "net_pnl_pct", "closed_trades", "wins", "losses", "win_rate_pct", "profit_factor", "fees_total_including_open_liquidation_try", "max_drawdown_pct", "active_symbols", "open_positions_excluded", "open_positions_marked", "reconciliation")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--live-parity-72h", action="store_true",
                        help="Aktif BB-MFI paper ayarlarını dondurur ve 72 saatlik, salt-okunur ortak cüzdan replay çalıştırır")
    parser.add_argument("--live-parity-end-hours-ago", type=float, default=0.0,
                        help="Live-parity penceresinin bitişini şimdiye göre geriye kaydırır; OOS için yalnız --live-parity-72h ile kullanılır")
    parser.add_argument("--live-parity-cost-multiplier", type=float, default=1.0,
                        help="Live-parity dolum maliyetlerini yalnız araştırma için çarpar; karar kurallarını değiştirmez")
    parser.add_argument("--live-parity-keep-symbols", action="store_true",
                        help="--live-parity-72h ile açıkça verilen sembolleri korur; verilmezse canlı yapılandırmadaki evren kullanılır")
    parser.add_argument("--use-all-requested", action="store_true", help="Verilen tarama evrenini güncel ACTIVE filtresi uygulamadan replay et")
    parser.add_argument("--interval", choices=("1m", "3m", "5m", "15m"), default="5m")
    parser.add_argument("--data-source", choices=("public", "historical-db"), default="public")
    parser.add_argument("--pine-version", choices=("current", "v1", "v2", "v3"), default="current")
    parser.add_argument("--mtf-feature-gate", choices=("none", "high-tf", "research-score", "bullish-count", "all-5", "all-5-volume-flow", "acetry-rule", "acetry-rule-relaxed"), default="none",
                        help="M1/M5/M15/H1/H4 causal entry feature gate; research only")
    parser.add_argument("--fetch-days", type=int, default=2, help="Feature warmup dahil public candle window")
    parser.add_argument("--start-hours-ago", type=float, default=24)
    parser.add_argument("--end-hours-ago", type=float, default=3)
    parser.add_argument("--start-date", help="ISO yerel tarih/saat; ör. 2026-07-20T00:00:00")
    parser.add_argument("--end-date", help="ISO yerel tarih/saat; gelecekteyse mevcut zamana kırpılır")
    parser.add_argument("--timezone", default="Europe/Istanbul")
    parser.add_argument("--order-pct", type=float, default=config.ORDER_PCT)
    parser.add_argument("--pyramiding", type=int, default=config.PYRAMIDING_LAYERS)
    parser.add_argument("--max-positions", type=int, default=config.MAX_OPEN_POSITIONS)
    parser.add_argument("--stop-pct", type=float, help="Sabit stopu Pine profilinin üzerine yazar")
    parser.add_argument("--risk-stop-pct", type=float,
                        help="Araştırma için strateji sinyalini değiştirmeden eklenen koruyucu stop")
    parser.add_argument("--tp-pct", type=float, help="Sabit kâr hedefini Pine profilinin üzerine yazar")
    parser.add_argument("--spread-pct", type=float, default=config.BACKTEST_ASSUMED_SPREAD_PCT)
    parser.add_argument("--slippage-pct", type=float, default=config.ESTIMATED_SLIPPAGE_PCT)
    parser.add_argument("--profit-lock-trigger-pct", type=float, default=0.0,
                        help="Pozisyon bu brüt yükselişi gördükten sonraki mumlarda maliyet-kilit stopu etkinleşir")
    parser.add_argument("--profit-lock-pct", type=float, default=0.0,
                        help="Kilitli stopun giriş fiyatının üzerindeki seviyesi; 0 gerçek brüt break-even'dır")
    parser.add_argument("--open-position-policy", choices=("exclude", "mark-to-market"), default="exclude")
    parser.add_argument("--historical-activity", action="store_true", help="Aktiviteyi her saat geçmiş mumlardan yeniden hesapla")
    parser.add_argument("--activity-refresh-minutes", type=int, default=60, help="Tarihsel aktivite kontrol periyodu (dakika)")
    parser.add_argument("--activity-m5-min-range-pct", type=float, default=config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT, help="M5 son üç mum aralık alt sınırı (yüzde)")
    parser.add_argument("--activity-m5-min-atr-pct", type=float, default=config.SYMBOL_ACTIVITY_MIN_ATR_PCT * 100, help="M5 ATR alt sınırı (yüzde)")
    parser.add_argument("--activity-m5-min-volume-ratio", type=float, default=config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO, help="M5 hacim oranı alt sınırı")
    parser.add_argument("--activity-volume-only", action="store_true", help="Aktivitede M5 range/ATR yerine yalnız 24s TL hacmi ve M5 hacim oranını kullan")
    parser.add_argument("--activity-min-quote-volume-try", type=float, default=config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY, help="Aktivite için geçmiş 24 saat minimum TL hacmi")
    parser.add_argument("--activity-m1-filter", action="store_true", help="M5 aktivitesine M1 range ve ATR doğrulaması ekle")
    parser.add_argument("--activity-m1-range-bars", type=int, default=5, help="M1 hareket aralığı için son mum sayısı")
    parser.add_argument("--activity-m1-min-range-pct", type=float, default=0.08, help="M1 kısa aralık alt sınırı (yüzde)")
    parser.add_argument("--activity-m1-min-atr-pct", type=float, default=0.05, help="M1 ATR alt sınırı (yüzde)")
    parser.add_argument("--activity-m1-flat-filter", action="store_true", help="Son tamamlanmış M1 mumlarda H-L düz yoğunluğu yüksekse sembolü pasifleştir")
    parser.add_argument("--activity-m1-flat-max-range-pct", type=float, default=config.SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT, help="Düz kabul edilen M1 H-L maksimum aralığı (yüzde)")
    parser.add_argument("--activity-m1-flat-5m-max-count", type=int, default=config.SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT, help="Son 5 M1 mumda pasifleştirme eşiği")
    parser.add_argument("--activity-m1-flat-30m-max-count", type=int, default=config.SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT, help="Son 30 M1 mumda pasifleştirme eşiği")
    parser.add_argument("--activity-m1-flat-max-volume-ratio", type=float, default=0.0, help="Düz küme engeli için son 5dk/önceki 20dk maksimum M1 hacim oranı; 0 H-L kuralı")
    parser.add_argument("--activity-m1-relative-idle-filter", action="store_true", help="M1 H-L sıfır/tek-tick yoğunluğunu sembolün kendi geçmişiyle karşılaştıran deneysel filtre")
    parser.add_argument("--activity-m1-relative-idle-window-minutes", type=int, default=30, help="Deneysel göreli hareketsizlik güncel M1 penceresi")
    parser.add_argument("--activity-m1-relative-idle-lookback-minutes", type=int, default=360, help="Deneysel göreli hareketsizlik karşılaştırma geçmişi")
    parser.add_argument("--activity-m1-relative-idle-min-score", type=int, default=3, help="Mikroyapı+darlık+hacim göreli hareketsizlik puan eşiği (1-3)")
    parser.add_argument("--activity-m1-relative-idle-min-zero-hl-count", type=int, default=18, help="Güncel pencerede minimum H-L=0 mum sayısı")
    parser.add_argument("--activity-m1-relative-idle-min-ticklike-count", type=int, default=27, help="Güncel pencerede sembol içi tek-tick benzeri mum sayısı")
    parser.add_argument("--activity-m1-relative-idle-range-percentile", type=float, default=0.10, help="Güncel medyan H-L için geçmiş göreli darlık yüzdeliği")
    parser.add_argument("--activity-m1-relative-idle-volume-percentile", type=float, default=0.25, help="Güncel ortalama hacim için geçmiş göreli alt yüzdelik")
    parser.add_argument("--activity-m1-m5-compression-filter", action="store_true", help="M1 ve M5 ATR ile M1 Bollinger aynı anda sıkışıksa deneysel engelleme uygula")
    parser.add_argument("--activity-m1-compression-max-atr-pct", type=float, default=0.07, help="Deneysel sıkışma engeli M1 ATR üst sınırı (yüzde)")
    parser.add_argument("--activity-m5-compression-max-atr-pct", type=float, default=0.30, help="Deneysel sıkışma engeli M5 ATR üst sınırı (yüzde)")
    parser.add_argument("--activity-m1-compression-max-bb-width-pct", type=float, default=0.80, help="Deneysel sıkışma engeli M1 Bollinger genişlik üst sınırı (yüzde)")
    parser.add_argument("--activity-m1-inactivity-score-filter", action="store_true", help="M1 H-L, sıkışma, hacim, CMF/EFI ve TSI/CCI ile deneysel hareketsizlik puanı uygula")
    parser.add_argument("--activity-m1-inactivity-score-min", type=int, default=3, help="Deneysel M1 hareketsizlik puanında engelleme eşiği (0-5)")
    parser.add_argument("--activity-m1-inactivity-lookback-minutes", type=int, default=120, help="Sembol içi sıkışma yüzdelikleri için geçmiş M1 dakika sayısı")
    parser.add_argument("--activity-m1-inactivity-flat-30m-min-count", type=int, default=18, help="Deneysel puanda son 30 M1 mumda düz H-L sayısı")
    parser.add_argument("--activity-m1-inactivity-max-volume-ratio", type=float, default=0.50, help="Deneysel puanda son 5dk/önceki 20dk M1 hacim oranı üst sınırı")
    parser.add_argument("--activity-m1-inactivity-max-abs-cmf", type=float, default=0.05, help="Deneysel puanda mutlak CMF üst sınırı")
    parser.add_argument("--activity-m1-inactivity-max-abs-tsi", type=float, default=15.0, help="Deneysel puanda mutlak TSI üst sınırı")
    parser.add_argument("--activity-m1-inactivity-max-abs-cci", type=float, default=100.0, help="Deneysel puanda mutlak CCI üst sınırı")
    parser.add_argument("--activity-m30-filter", action="store_true", help="M5 aktivitesine M30 range ve ATR doğrulaması ekle")
    parser.add_argument("--activity-m30-regime-filter", action="store_true", help="M30 EMA20 sert düşüş rejiminde yeni long girişi engelle")
    parser.add_argument("--activity-m30-min-range-pct", type=float, default=0.45, help="Son iki M30 mumunun hareket alanı alt sınırı (yüzde)")
    parser.add_argument("--activity-m30-min-atr-pct", type=float, default=0.20, help="M30 ATR alt sınırı (yüzde)")
    parser.add_argument("--activity-m30-max-ema20-decline-pct", type=float, default=0.15, help="Üç M30 mumda izin verilen EMA20 düşüşü (yüzde)")
    parser.add_argument("--initial-active-only", action="store_true", help="Yalnız replay başlangıcında tarihsel olarak ACTIVE olan sembollerle başla")
    parser.add_argument("--initial-active-limit", type=int, default=0, help="Başlangıç ACTIVE evreninden kalite puanıyla en iyi N sembol")
    parser.add_argument("--passive-loss-exit-hours", type=float, default=0.0, help="Pasif zarar pozisyonu için EMA/ATR kontrollü çıkış süresi")
    parser.add_argument("--disable-passive-net-exit", action="store_true", help="Pasife dönen pozisyonun net kâr/başabaş otomatik kapanışını kapat")
    parser.add_argument("--passive-direct-exit", action="store_true", help="Pasife dönen açık pozisyonu PnL'den bağımsız hemen kapat")
    parser.add_argument("--daily-stop-limit", type=int, default=0, help="Sembol başına günlük stop sonrası yeni giriş limiti; 0 kapalı")
    parser.add_argument("--daily-symbol-loss-limit-try", type=float, default=0.0,
                        help="Sembolün gün içi net gerçekleşmiş zararı bu TL eşiğine ulaşınca yeni girişleri durdur; 0 kapalı")
    parser.add_argument("--symbol-loss-cooldown-hours", type=float, default=0.0,
                        help="Net zarar kapanışından sonra aynı sembolde yeni giriş soğuma süresi; 0 kapalı")
    parser.add_argument("--max-hold-hours", type=float, default=0.0,
                        help="Pozisyon için maksimum elde tutma süresi; 0 kapalı")
    parser.add_argument("--breakeven-exit-after-hours", type=float, default=0.0,
                        help="Bu yaştan sonra net maliyet/başabaş üstüne gelen pozisyonu kapat; 0 kapalı")
    parser.add_argument("--adverse-ema-atr-exit-hours", type=float, default=0.0,
                        help="Bu yaştan sonra net zararda EMA9<EMA21 ve ATR bozulması varsa çık; 0 kapalı")
    parser.add_argument("--adverse-ema-atr-multiplier", type=float, default=1.0,
                        help="Aleyhe EMA/ATR çıkışında giriş altındaki minimum ATR katsayısı")
    parser.add_argument("--entry-ema200-filter", action="store_true", help="Girişi yalnız kapanış EMA200 üzerinde ise kabul et")
    parser.add_argument("--entry-min-rsi14", type=float, default=0.0,
                        help="Araştırma için mevcut BUY sinyalinde minimum RSI(14); 0 kapalı")
    parser.add_argument("--entry-momentum-slowdown-filter", action="store_true", help="Girişi son kapanış önceki kapanışın altına inmediğinde kabul et")
    parser.add_argument("--entry-min-volume-ratio", type=float, default=0.0, help="Sinyal mumunun önceki 20 M5 mumuna göre minimum hacim oranı; 0 kapalı")
    parser.add_argument("--entry-dip-confirmation", action="store_true", help="Alt BB sinyal mumunun kendi aralığında dipten dönüş kapanışı doğrulamasını iste")
    parser.add_argument("--entry-dip-min-close-position", type=float, default=0.55, help="Dip doğrulamasında kapanışın mum aralığındaki minimum yeri (0-1)")
    parser.add_argument("--entry-mfi-reversal", action="store_true", help="V3 girişinde MFI'ın önceki kapanmış muma göre yükselmesini iste")
    parser.add_argument("--entry-mfi-reversal-min-delta", type=float, default=0.0, help="MFI dönüşü için minimum puan artışı")
    parser.add_argument("--entry-mfi-slowdown-max-drop", type=float,
                        help="MFI önceki muma göre bu puandan fazla düşüyorsa girişi engelle; verilmezse kapalı")
    parser.add_argument("--high-downtrend-entry-filter", action="store_true", help="Güçlü M5 düşüş trendindeki mean-reversion long girişini engelle")
    parser.add_argument("--high-downtrend-min-adx", type=float, default=50, help="Düşüş trendi giriş engeli için minimum ADX")
    parser.add_argument("--high-downtrend-min-di-gap", type=float, default=0.0,
                        help="Giriş engeli için minimum (-DI - +DI) farkı; 0 eski davranışı korur")
    parser.add_argument("--high-downtrend-min-return-1h-pct", type=float, default=2.0, help="Giriş engeli için minimum 1 saatlik düşüş (yüzde)")
    parser.add_argument("--high-downtrend-min-return-15m-pct", type=float, default=1.0, help="Giriş engeli için minimum 15 dakikalık düşüş (yüzde)")
    parser.add_argument("--pyramid-low-volume-block", action="store_true", help="Riskli girişten sonra düşük M5 hacminde ek katmanı engelle")
    parser.add_argument("--pyramid-require-net-profit", action="store_true",
                        help="Mevcut pozisyon net kârda değilse yeni piramit katmanını engelle")
    parser.add_argument("--pyramid-block-underwater-after-hours", type=float, default=0.0,
                        help="Pozisyon bu süre boyunca net zarardaysa yeni piramit katmanını engelle; 0 kapalı")
    parser.add_argument("--pyramid-profit-extension-layers", type=int, default=0,
                        help="Normal piramit sınırı sonrası, tüm katmanlar net kârda ise izin verilen ek katman; 0 kapalı")
    parser.add_argument("--pyramid-low-volume-after-hours", type=float, default=2.0, help="Ek katman engeli için minimum pozisyon yaşı")
    parser.add_argument("--pyramid-low-volume-ratio-max", type=float, default=0.70, help="Ek katman engeli için maksimum M5 hacim oranı")
    parser.add_argument("--remaining-cash-sizing", action="store_true", help="Her girişte toplam özsermaye yerine kalan kullanılabilir nakdin yüzdesini kullan")
    parser.add_argument("--output", default="portfolio-replay-latest.json")
    args = parser.parse_args()
    if args.activity_refresh_minutes <= 0:
        parser.error("--activity-refresh-minutes pozitif olmalıdır")
    if args.live_parity_end_hours_ago < 0:
        parser.error("--live-parity-end-hours-ago negatif olamaz")
    if args.live_parity_cost_multiplier <= 0:
        parser.error("--live-parity-cost-multiplier pozitif olmalıdır")
    if args.symbol_loss_cooldown_hours < 0:
        parser.error("--symbol-loss-cooldown-hours negatif olamaz")
    if args.max_hold_hours < 0:
        parser.error("--max-hold-hours negatif olamaz")
    if args.pyramid_block_underwater_after_hours < 0:
        parser.error("--pyramid-block-underwater-after-hours negatif olamaz")
    if args.pyramid_profit_extension_layers < 0:
        parser.error("--pyramid-profit-extension-layers negatif olamaz")
    if args.breakeven_exit_after_hours < 0:
        parser.error("--breakeven-exit-after-hours negatif olamaz")
    if args.adverse_ema_atr_exit_hours < 0 or args.adverse_ema_atr_multiplier < 0:
        parser.error("EMA/ATR çıkış parametreleri negatif olamaz")
    if args.activity_min_quote_volume_try < 0 or args.entry_min_volume_ratio < 0:
        parser.error("hacim eşikleri negatif olamaz")
    if args.activity_m1_flat_max_range_pct < 0:
        parser.error("--activity-m1-flat-max-range-pct negatif olamaz")
    if args.activity_m1_flat_max_volume_ratio < 0:
        parser.error("--activity-m1-flat-max-volume-ratio negatif olamaz")
    if args.activity_m1_relative_idle_window_minutes < 5 or args.activity_m1_relative_idle_lookback_minutes < args.activity_m1_relative_idle_window_minutes * 2:
        parser.error("M1 göreli hareketsizlik için pencere en az 5dk ve geçmiş en az iki pencere olmalıdır")
    if not 1 <= args.activity_m1_relative_idle_min_score <= 3:
        parser.error("--activity-m1-relative-idle-min-score 1 ile 3 arasında olmalıdır")
    if not 0 <= args.activity_m1_relative_idle_min_zero_hl_count <= args.activity_m1_relative_idle_window_minutes:
        parser.error("M1 göreli hareketsizlik H-L=0 sayısı pencere içinde olmalıdır")
    if not 1 <= args.activity_m1_relative_idle_min_ticklike_count <= args.activity_m1_relative_idle_window_minutes:
        parser.error("M1 göreli hareketsizlik tek-tick sayısı pencere içinde olmalıdır")
    if not 0 < args.activity_m1_relative_idle_range_percentile <= 1 or not 0 < args.activity_m1_relative_idle_volume_percentile <= 1:
        parser.error("M1 göreli hareketsizlik yüzdelikleri 0 ile 1 arasında olmalıdır")
    if (args.activity_m1_compression_max_atr_pct < 0 or args.activity_m5_compression_max_atr_pct < 0 or
            args.activity_m1_compression_max_bb_width_pct < 0):
        parser.error("M1/M5 sıkışma eşikleri negatif olamaz")
    if not 0 <= args.activity_m1_inactivity_score_min <= 5:
        parser.error("--activity-m1-inactivity-score-min 0 ile 5 arasında olmalıdır")
    if args.activity_m1_inactivity_lookback_minutes < 40:
        parser.error("--activity-m1-inactivity-lookback-minutes en az 40 olmalıdır")
    if not 1 <= args.activity_m1_inactivity_flat_30m_min_count <= 30:
        parser.error("--activity-m1-inactivity-flat-30m-min-count 1 ile 30 arasında olmalıdır")
    if args.activity_m1_inactivity_max_volume_ratio < 0 or args.activity_m1_inactivity_max_abs_cmf < 0:
        parser.error("M1 hareketsizlik hacim ve CMF eşikleri negatif olamaz")
    if args.activity_m1_inactivity_max_abs_tsi < 0 or args.activity_m1_inactivity_max_abs_cci < 0:
        parser.error("M1 hareketsizlik TSI ve CCI eşikleri negatif olamaz")
    if not 1 <= args.activity_m1_flat_5m_max_count <= 5:
        parser.error("--activity-m1-flat-5m-max-count 1 ile 5 arasında olmalıdır")
    if not 1 <= args.activity_m1_flat_30m_max_count <= 30:
        parser.error("--activity-m1-flat-30m-max-count 1 ile 30 arasında olmalıdır")
    if args.daily_symbol_loss_limit_try < 0:
        parser.error("--daily-symbol-loss-limit-try negatif olamaz")
    if not 0 <= args.entry_dip_min_close_position <= 1:
        parser.error("--entry-dip-min-close-position 0 ile 1 arasında olmalıdır")
    if args.entry_mfi_slowdown_max_drop is not None and args.entry_mfi_slowdown_max_drop < 0:
        parser.error("--entry-mfi-slowdown-max-drop negatif olamaz")
    asyncio.run(run(args))
