"""VectorBT research runner for public Binance TR candles.

This is deliberately separate from the paper-trading engine. It evaluates
closed-candle signals on the next candle and includes commission and slippage.
It does not place orders or write application state.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import vectorbt as vbt

from app.backtest import _fetch_klines
from app.config import config


@dataclass(frozen=True)
class Candidate:
    name: str
    timeframe: str
    description: str


INTERVAL_FREQ = {"1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}


def _frame(symbol: str, interval: str, days: int) -> pd.DataFrame:
    raw = _fetch_klines(symbol, interval, days)
    index = pd.to_datetime(raw["times"], unit="s", utc=True)
    frame = pd.DataFrame({key: raw[key] for key in ("opens", "highs", "lows", "closes", "volumes")}, index=index)
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous = frame["closes"].shift(1)
    true_range = pd.concat([
        frame["highs"] - frame["lows"],
        (frame["highs"] - previous).abs(),
        (frame["lows"] - previous).abs(),
    ], axis=1).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()


def _adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    up = frame["highs"].diff()
    down = -frame["lows"].diff()
    plus = up.where((up > down) & (up > 0), 0.0)
    minus = down.where((down > up) & (down > 0), 0.0)
    tr = _atr(frame, period)
    plus_di = 100 * plus.rolling(period, min_periods=period).sum() / tr.replace(0, np.nan)
    minus_di = 100 * minus.rolling(period, min_periods=period).sum() / tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period, min_periods=period).mean()


def _supertrend_direction(frame: pd.DataFrame, period: int = 9, multiplier: float = 0.35) -> pd.Series:
    """Standard OHLC Supertrend direction; no Heikin-Ashi transformation."""
    atr = _atr(frame, period)
    midpoint = (frame["highs"] + frame["lows"]) / 2
    upper = midpoint + multiplier * atr
    lower = midpoint - multiplier * atr
    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = pd.Series(0, index=frame.index, dtype="int8")
    for i in range(1, len(frame)):
        if pd.isna(atr.iloc[i]):
            continue
        if direction.iloc[i - 1] == 0:
            final_upper.iloc[i] = upper.iloc[i]
            final_lower.iloc[i] = lower.iloc[i]
            direction.iloc[i] = 1 if frame["closes"].iloc[i] >= midpoint.iloc[i] else -1
            continue
        previous_close = frame["closes"].iloc[i - 1]
        if pd.notna(final_upper.iloc[i - 1]) and (upper.iloc[i] < final_upper.iloc[i - 1] or previous_close > final_upper.iloc[i - 1]):
            final_upper.iloc[i] = upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]
        if pd.notna(final_lower.iloc[i - 1]) and (lower.iloc[i] > final_lower.iloc[i - 1] or previous_close < final_lower.iloc[i - 1]):
            final_lower.iloc[i] = lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]
        previous_direction = direction.iloc[i - 1]
        if previous_direction < 0 and frame["closes"].iloc[i] > final_upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif previous_direction > 0 and frame["closes"].iloc[i] < final_lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = previous_direction
    return direction


def _heikin_ashi(frame: pd.DataFrame) -> pd.DataFrame:
    """Build HA candles only for research; execution price remains real close."""
    ha = frame.copy()
    ha_close = (frame["opens"] + frame["highs"] + frame["lows"] + frame["closes"]) / 4
    ha_open = ha_close.copy()
    if len(frame):
        ha_open.iloc[0] = (frame["opens"].iloc[0] + frame["closes"].iloc[0]) / 2
    for i in range(1, len(frame)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2
    ha["opens"] = ha_open
    ha["closes"] = ha_close
    ha["highs"] = pd.concat([frame["highs"], ha_open, ha_close], axis=1).max(axis=1)
    ha["lows"] = pd.concat([frame["lows"], ha_open, ha_close], axis=1).min(axis=1)
    return ha


def _dpmo(frame: pd.DataFrame) -> pd.Series:
    src = frame["closes"]
    impulse = src / src.shift(1).replace(0, np.nan) * 100
    pmo2 = (impulse - 100).ewm(span=35, adjust=False, min_periods=35).mean()
    pmo = (10 * pmo2).ewm(span=20, adjust=False, min_periods=20).mean()
    signal = pmo.ewm(span=10, adjust=False, min_periods=10).mean()
    return pmo - signal


def _parabolic_sar(frame: pd.DataFrame, start: float = 0.02, step: float = 0.05, maximum: float = 0.2) -> pd.Series:
    high, low, close = frame["highs"].to_numpy(), frame["lows"].to_numpy(), frame["closes"].to_numpy()
    sar = np.full(len(frame), np.nan)
    if not len(frame):
        return pd.Series(sar, index=frame.index)
    bull, extreme, acceleration = True, high[0], start
    sar[0] = low[0]
    for i in range(1, len(frame)):
        value = sar[i - 1] + acceleration * (extreme - sar[i - 1])
        if bull:
            value = min(value, low[i - 1], low[i - 2] if i > 1 else low[i - 1])
            if low[i] < value:
                bull, value, extreme, acceleration = False, extreme, low[i], start
            elif high[i] > extreme:
                extreme, acceleration = high[i], min(maximum, acceleration + step)
        else:
            value = max(value, high[i - 1], high[i - 2] if i > 1 else high[i - 1])
            if high[i] > value:
                bull, value, extreme, acceleration = True, extreme, high[i], start
            elif low[i] < extreme:
                extreme, acceleration = low[i], min(maximum, acceleration + step)
        sar[i] = value
    return pd.Series(sar, index=frame.index)


def _std_filtered_long(frame: pd.DataFrame) -> pd.Series:
    """Close-source equivalent of STD-Filtered N-Pole GF defaults."""
    src = frame["closes"].copy()
    deviation = src.rolling(10, min_periods=10).std()
    filtered = src.where((src - src.shift(1)).abs() >= deviation, src.shift(1))
    period, order = 25, 5
    w = 2 * np.pi / period
    b = (1 - np.cos(w)) / (1.414 ** (2 / order) - 1)
    alpha = -b + np.sqrt(b * b + 2 * b)
    output = pd.Series(np.nan, index=frame.index, dtype=float)
    for i in range(len(frame)):
        if pd.isna(filtered.iloc[i]):
            continue
        value = filtered.iloc[i] * alpha ** order
        for r in range(1, order + 1):
            if i - r >= 0 and pd.notna(output.iloc[i - r]):
                value += (-1 if r % 2 == 0 else 1) * math.comb(order, r) * (1 - alpha) ** r * output.iloc[i - r]
        output.iloc[i] = value
    previous = output.shift(1)
    return (output > previous) & (output.shift(1) <= output.shift(2))


def _trend_phase_long(frame: pd.DataFrame) -> pd.Series:
    """Score early bullish M5 trend phases; avoid late/chased entries.

    This is research-only and intentionally uses closed-candle information. The
    phase gate rewards a fresh EMA alignment, rising ADX and price near EMA21;
    it rejects overextended/overbought continuation candles.
    """
    close = frame["closes"]
    ema9, ema21, ema50 = _ema(close, 9), _ema(close, 21), _ema(close, 50)
    atr = _atr(frame)
    adx = _adx(frame)
    rsi = _rsi(close)
    volume_ratio = frame["volumes"] / frame["volumes"].rolling(20, min_periods=20).mean()
    vwap = (frame["closes"] * frame["volumes"]).rolling(20, min_periods=20).sum() / frame["volumes"].rolling(20, min_periods=20).sum()
    dpmo = _dpmo(frame)
    sar_direction = _supertrend_direction(frame, period=9, multiplier=0.35)

    bullish_alignment = (ema9 > ema21) & (ema21 > ema50)
    alignment_start = bullish_alignment & ~bullish_alignment.shift(1).fillna(False)
    alignment_age = alignment_start.astype(int).groupby(alignment_start.cumsum()).cumsum()
    # A trend can remain eligible after the cross, but not after a long chase.
    fresh_alignment = alignment_age.between(1, 36)
    adx_rising = adx > adx.shift(3)
    trend_strength = adx.between(18, 48)
    momentum = close > close.shift(3)
    price_location = (close > ema21) & (close > vwap)
    not_overextended = ((close - ema21).abs() <= atr * 1.35) & (close < ema21 + atr * 1.8)
    not_overbought = rsi.between(42, 72)
    volume_ok = volume_ratio >= 0.8
    directional_confirmation = (dpmo > 0) & (sar_direction > 0)

    score = (
        bullish_alignment.astype(int)
        + trend_strength.astype(int)
        + adx_rising.astype(int)
        + momentum.astype(int)
        + price_location.astype(int)
        + not_overextended.astype(int)
        + not_overbought.astype(int)
        + volume_ok.astype(int)
        + directional_confirmation.astype(int)
    )
    eligible = (
        fresh_alignment & bullish_alignment & trend_strength & adx_rising
        & momentum & price_location & not_overextended & not_overbought
        & volume_ok & directional_confirmation & (score >= 8)
    )
    # Enter only when the phase becomes eligible, not on every qualifying bar.
    return eligible & ~eligible.shift(1).fillna(False)


def _tv_confluence_trend_long(frame: pd.DataFrame, min_score: int = 75, min_volume: float = 1.0, max_distance_atr: float = 0.8) -> pd.Series:
    """TradingView-style trend confluence for early M5 long entries."""
    close = frame["closes"]
    ema9, ema21, ema50 = _ema(close, 9), _ema(close, 21), _ema(close, 50)
    atr = _atr(frame)
    adx = _adx(frame)
    rsi = _rsi(close)
    volume_ratio = frame["volumes"] / frame["volumes"].rolling(20, min_periods=20).mean()
    vwap = (close * frame["volumes"]).rolling(20, min_periods=20).sum() / frame["volumes"].rolling(20, min_periods=20).sum()
    dpmo = _dpmo(frame)
    supertrend = _supertrend_direction(frame, period=9, multiplier=0.35)

    up = frame["highs"].diff()
    down = -frame["lows"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_di = plus_dm.rolling(14, min_periods=14).sum() / atr.replace(0, np.nan)
    minus_di = minus_dm.rolling(14, min_periods=14).sum() / atr.replace(0, np.nan)
    bullish_alignment = (ema9 > ema21) & (ema21 > ema50)
    alignment_start = bullish_alignment & ~bullish_alignment.shift(1).fillna(False)
    alignment_age = alignment_start.astype(int).groupby(alignment_start.cumsum()).cumsum()
    early_phase = alignment_age.between(1, 36)
    adx_strength = adx >= 20
    adx_rising = adx > adx.shift(3)
    directional = plus_di > minus_di
    momentum = (dpmo > 0) & (dpmo > dpmo.shift(2))
    price_vwap = close > vwap
    volume_ok = volume_ratio >= min_volume
    distance_ok = ((close - ema21) >= 0) & ((close - ema21) <= atr * max_distance_atr)
    not_overbought = rsi.between(40, 72)
    supertrend_ok = supertrend > 0
    score = (
        bullish_alignment.astype(int) * 20
        + ((ema9 > ema9.shift(2)) & (ema21 > ema21.shift(2))).astype(int) * 10
        + price_vwap.astype(int) * 10
        + supertrend_ok.astype(int) * 15
        + (adx_strength & adx_rising).astype(int) * 15
        + directional.astype(int) * 10
        + momentum.astype(int) * 10
        + volume_ok.astype(int) * 5
        + distance_ok.astype(int) * 5
    )
    eligible = (
        early_phase & supertrend_ok & adx_strength & adx_rising & directional
        & momentum & price_vwap & volume_ok & distance_ok & not_overbought
        & (score >= min_score)
    )
    return eligible & ~eligible.shift(1).fillna(False)


def _williams_fractal_ma_long(frame: pd.DataFrame) -> pd.Series:
    """Williams Fractal + 20/50/100 MA pullback, confirmed without look-ahead."""
    close, low = frame["closes"], frame["lows"]
    ma20 = close.rolling(20, min_periods=20).mean()
    ma50 = close.rolling(50, min_periods=50).mean()
    ma100 = close.rolling(100, min_periods=100).mean()
    bullish_alignment = (ma20 > ma50) & (ma50 > ma100)
    # The center candle is two bars back; shifting the centered calculation by
    # two bars makes the fractal available only after both right-side candles close.
    fractal_low = low.shift(2) == low.rolling(5, center=True, min_periods=5).min().shift(2)
    pullback = (close <= ma20) | (close <= ma50)
    valid_structure = close > ma100
    raw = bullish_alignment & pullback & fractal_low & valid_structure
    return raw & ~raw.shift(1).fillna(False)


def _run_ma50_risk(frame: pd.DataFrame, candidate: str, order_size: float, risk_reward: float, min_atr_stop: float = 1.0, cooldown_bars: int = 5) -> dict:
    """Williams/MA entry with entry-time MA50 stop and R:R target."""
    entries, _ = _signals(frame, candidate)
    close, high, low = frame["closes"], frame["highs"], frame["lows"]
    ma50 = close.rolling(50, min_periods=50).mean()
    atr = _atr(frame)
    fee_rate, slippage = float(config.COMMISSION_PCT), float(config.ESTIMATED_SLIPPAGE_PCT)
    trades, fees = [], 0.0
    i = 0
    cooldown_until = -1
    while i < len(frame) - 1:
        if i < cooldown_until or not bool(entries.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        entry = float(close.iloc[entry_i]) * (1 + slippage)
        stop = float(ma50.iloc[entry_i]) * (1 - slippage)
        if not np.isfinite(stop) or stop <= 0 or stop >= entry:
            i += 1
            continue
        risk = entry - stop
        if not np.isfinite(atr.iloc[entry_i]) or risk < float(atr.iloc[entry_i]) * min_atr_stop:
            i += 1
            continue
        target = entry + risk * risk_reward
        qty = order_size / entry
        exit_i = None
        exit_price = None
        reason = None
        for j in range(entry_i + 1, len(frame)):
            if float(low.iloc[j]) <= stop:
                exit_i, exit_price, reason = j, stop * (1 - slippage), "ma50_stop"
                break
            if float(high.iloc[j]) >= target:
                exit_i, exit_price, reason = j, target * (1 - slippage), "risk_reward_target"
                break
        if exit_i is None:
            i += 1
            continue
        gross = (exit_price - entry) * qty
        trade_fees = (entry + exit_price) * qty * fee_rate
        net = gross - trade_fees
        fees += trade_fees
        trades.append(net)
        i = exit_i + 1
        cooldown_until = i + cooldown_bars
    wins = sum(1 for x in trades if x > 0)
    losses = len(trades) - wins
    gross_wins = sum(x for x in trades if x > 0)
    gross_losses = -sum(x for x in trades if x <= 0)
    return {"candidate": candidate, "bars": len(frame), "signals": int(entries.sum()), "trades": len(trades), "wins": wins, "losses": losses, "win_rate_pct": round(100 * wins / len(trades), 2) if trades else 0.0, "net_pnl": round(sum(trades), 4), "return_pct": round(sum(trades) / config.INITIAL_BALANCE_TRY * 100, 4), "profit_factor": round(gross_wins / gross_losses, 4) if gross_losses else None, "total_fees": round(fees, 4), "ma50_stop": True, "risk_reward": risk_reward, "min_atr_stop": min_atr_stop, "cooldown_bars": cooldown_bars}


def _signals(frame: pd.DataFrame, candidate: str, higher_frame: pd.DataFrame | None = None) -> tuple[pd.Series, pd.Series]:
    close = frame["closes"]
    ema9, ema21, ema50 = _ema(close, 9), _ema(close, 21), _ema(close, 50)
    atr = _atr(frame)
    adx = _adx(frame)
    volume_ratio = frame["volumes"] / frame["volumes"].rolling(20, min_periods=20).mean()
    rsi = _rsi(close)

    body = (frame["closes"] - frame["opens"]).abs()
    candle_range = (frame["highs"] - frame["lows"]).replace(0, np.nan)
    bullish = frame["closes"] > frame["opens"]
    bearish = frame["closes"] < frame["opens"]
    # Selective reversal/continuation patterns; intentionally excludes engulfing.
    morning_star = (
        bearish.shift(2) & bullish & bullish.shift(0)
        & (body.shift(1) <= candle_range.shift(1) * 0.35)
        & (close > (frame["opens"].shift(2) + frame["closes"].shift(2)) / 2)
    )
    three_white_soldiers = (
        bullish & bullish.shift(1) & bullish.shift(2)
        & (close > close.shift(1)) & (close.shift(1) > close.shift(2))
        & (body / candle_range > 0.55)
    )
    evening_star = (
        bullish.shift(2) & bearish
        & (body.shift(1) <= candle_range.shift(1) * 0.35)
        & (close < (frame["opens"].shift(2) + frame["closes"].shift(2)) / 2)
    )
    three_black_crows = (
        bearish & bearish.shift(1) & bearish.shift(2)
        & (close < close.shift(1)) & (close.shift(1) < close.shift(2))
        & (body / candle_range > 0.55)
    )

    if candidate == "trend_regime":
        entries = (ema9 > ema21) & (ema21 > ema50) & (adx >= 25) & (volume_ratio >= 1.1) & (close > close.shift(1) + atr * 0.15)
        exits = (ema9 < ema21) | (adx < 18)
    elif candidate == "donchian_volume":
        upper = frame["highs"].rolling(20, min_periods=20).max().shift(1)
        lower = frame["lows"].rolling(20, min_periods=20).min().shift(1)
        entries = (close > upper) & (volume_ratio >= 1.2) & (adx >= 20)
        exits = close < lower
    elif candidate == "rsi_bollinger":
        middle = close.rolling(20, min_periods=20).mean()
        std = close.rolling(20, min_periods=20).std()
        entries = (close < middle - 2 * std) & (rsi < 35) & (volume_ratio > 0.5)
        exits = (close > middle) | (rsi > 55)
    elif candidate == "ess_long":
        middle = close.rolling(20, min_periods=20).mean()
        std = close.rolling(20, min_periods=20).std()
        lower = middle - 2.1 * std
        entries = (close <= lower) & (rsi < 20)
        # Source strategy's first long profit target: middle Bollinger band.
        exits = close >= middle
    elif candidate == "std_dpmo_smartsar_long":
        std_long = _std_filtered_long(frame)
        dpmo = _dpmo(frame)
        dpmo_long = (dpmo > 0) & (dpmo.shift(1) <= 0)
        sar = _parabolic_sar(frame)
        ema_fast = _ema(close, 7)
        ema_slow = _ema(close, 21)
        signal = _ema(ema_fast - ema_slow, 9)
        money_flow = ((2 * close - frame["lows"] - frame["highs"]) / (frame["highs"] - frame["lows"]).replace(0, np.nan) * frame["volumes"]).fillna(0).cumsum()
        rvi = ((close - frame["opens"]) / (frame["highs"] - frame["lows"]).replace(0, np.nan)).fillna(0)
        smart_sar_long = (ema_fast - ema_slow > signal) & (close > sar) & (close.shift(1) <= sar.shift(1)) & (money_flow > 0) & (rvi > rvi.rolling(10, min_periods=10).mean())
        entries = std_long & dpmo_long & smart_sar_long
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "std_dpmo_smartsar_relaxed_long":
        # Controlled relaxation: require bullish state, not three same-bar crosses.
        std_long_state = _std_filtered_long(frame).rolling(3, min_periods=1).max().astype(bool)
        dpmo = _dpmo(frame)
        sar = _parabolic_sar(frame)
        ema_fast = _ema(close, 7)
        ema_slow = _ema(close, 21)
        signal = _ema(ema_fast - ema_slow, 9)
        money_flow = ((2 * close - frame["lows"] - frame["highs"]) / (frame["highs"] - frame["lows"]).replace(0, np.nan) * frame["volumes"]).fillna(0).cumsum()
        rvi = ((close - frame["opens"]) / (frame["highs"] - frame["lows"]).replace(0, np.nan)).fillna(0)
        smart_sar_state = (ema_fast - ema_slow > signal) & (close > sar) & (money_flow > 0) & (rvi > rvi.rolling(10, min_periods=10).mean())
        entries = std_long_state & (dpmo > 0) & smart_sar_state
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "std_dpmo_smartsar_quality_long":
        std_long_state = _std_filtered_long(frame).rolling(3, min_periods=1).max().astype(bool)
        dpmo = _dpmo(frame)
        sar = _parabolic_sar(frame)
        ema_fast = _ema(close, 7)
        ema_slow = _ema(close, 21)
        signal = _ema(ema_fast - ema_slow, 9)
        adx = _adx(frame)
        volume_ratio = frame["volumes"] / frame["volumes"].rolling(20, min_periods=20).mean()
        money_flow = ((2 * close - frame["lows"] - frame["highs"]) / (frame["highs"] - frame["lows"]).replace(0, np.nan) * frame["volumes"]).fillna(0).cumsum()
        rvi = ((close - frame["opens"]) / (frame["highs"] - frame["lows"]).replace(0, np.nan)).fillna(0)
        smart_sar_state = (ema_fast - ema_slow > signal) & (close > sar) & (money_flow > 0) & (rvi > rvi.rolling(10, min_periods=10).mean())
        raw_entries = std_long_state & (dpmo > 0) & smart_sar_state & (adx >= 18) & (volume_ratio >= 0.8) & (close > ema_slow)
        entries = raw_entries & ~raw_entries.shift(1).rolling(3, min_periods=1).max().fillna(False).astype(bool)
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "std_dpmo_smartsar_regime_long":
        std_long_state = _std_filtered_long(frame).rolling(3, min_periods=1).max().astype(bool)
        dpmo = _dpmo(frame)
        sar = _parabolic_sar(frame)
        ema_fast = _ema(close, 7)
        ema_slow = _ema(close, 21)
        signal = _ema(ema_fast - ema_slow, 9)
        adx = _adx(frame)
        atr_pct = _atr(frame, 14) / close
        volume_ratio = frame["volumes"] / frame["volumes"].rolling(20, min_periods=20).mean()
        money_flow = ((2 * close - frame["lows"] - frame["highs"]) / (frame["highs"] - frame["lows"]).replace(0, np.nan) * frame["volumes"]).fillna(0).cumsum()
        rvi = ((close - frame["opens"]) / (frame["highs"] - frame["lows"]).replace(0, np.nan)).fillna(0)
        smart_sar_state = (ema_fast - ema_slow > signal) & (close > sar) & (money_flow > 0) & (rvi > rvi.rolling(10, min_periods=10).mean())
        raw_entries = std_long_state & (dpmo > 0) & smart_sar_state & (adx >= 20) & (volume_ratio >= 1.0) & (close > ema_slow) & atr_pct.between(0.0015, 0.008)
        entries = raw_entries & ~raw_entries.shift(1).rolling(4, min_periods=1).max().fillna(False).astype(bool)
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "trend_phase_long":
        entries = _trend_phase_long(frame)
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "tv_confluence_trend_long":
        entries = _tv_confluence_trend_long(frame)
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "tv_mtf_confluence_long":
        if higher_frame is None:
            raise ValueError("tv_mtf_confluence_long için üst timeframe verisi gerekli")
        entries = _tv_confluence_trend_long(frame)
        hc = higher_frame["closes"]
        h9, h21, h50 = _ema(hc, 9), _ema(hc, 21), _ema(hc, 50)
        hst = _supertrend_direction(higher_frame, period=9, multiplier=0.35)
        higher_ok = ((h9 > h21) & (h21 > h50) & (hc > h50) & (hst > 0))
        higher_ok = higher_ok.reindex(frame.index, method="ffill").fillna(False)
        entries = entries & higher_ok
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "tv_mtf_confluence_relaxed_long":
        if higher_frame is None:
            raise ValueError("tv_mtf_confluence_relaxed_long için üst timeframe verisi gerekli")
        entries = _tv_confluence_trend_long(frame, min_score=65, min_volume=0.8, max_distance_atr=1.2)
        hc = higher_frame["closes"]
        h9, h21, h50 = _ema(hc, 9), _ema(hc, 21), _ema(hc, 50)
        hst = _supertrend_direction(higher_frame, period=9, multiplier=0.35)
        higher_ok = ((h9 > h21) & (h21 > h50) & (hc > h50) & (hst > 0))
        higher_ok = higher_ok.reindex(frame.index, method="ffill").fillna(False)
        entries = entries & higher_ok
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "tv_mtf_regime_long":
        if higher_frame is None:
            raise ValueError("tv_mtf_regime_long için üst timeframe verisi gerekli")
        entries = _tv_confluence_trend_long(frame, min_score=65, min_volume=0.8, max_distance_atr=1.2)
        hc = higher_frame["closes"]
        h9, h21, h50 = _ema(hc, 9), _ema(hc, 21), _ema(hc, 50)
        h_adx = _adx(higher_frame)
        hst = _supertrend_direction(higher_frame, period=9, multiplier=0.35)
        higher_ok = ((h9 > h21) & (h21 > h50) & (hc > h50) & (hst > 0) & (h_adx >= 20) & (h_adx > h_adx.shift(3)))
        higher_ok = higher_ok.reindex(frame.index, method="ffill").fillna(False)
        entries = entries & higher_ok
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "tv_mtf_regime_relaxed_long":
        if higher_frame is None:
            raise ValueError("tv_mtf_regime_relaxed_long için üst timeframe verisi gerekli")
        entries = _tv_confluence_trend_long(frame, min_score=65, min_volume=0.8, max_distance_atr=1.2)
        hc = higher_frame["closes"]
        h9, h21, h50 = _ema(hc, 9), _ema(hc, 21), _ema(hc, 50)
        h_adx = _adx(higher_frame)
        hst = _supertrend_direction(higher_frame, period=9, multiplier=0.35)
        higher_ok = ((h9 > h21) & (h21 > h50) & (hc > h50) & (hst > 0) & (h_adx >= 18) & (h_adx > h_adx.shift(3)))
        higher_ok = higher_ok.reindex(frame.index, method="ffill").fillna(False)
        entries = entries & higher_ok
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "williams_fractal_ma_long":
        entries = _williams_fractal_ma_long(frame)
        exits = pd.Series(False, index=frame.index, dtype=bool)
    elif candidate == "strong_candlestick":
        entries = (morning_star | three_white_soldiers) & (volume_ratio >= 1.1) & (adx >= 18)
        exits = evening_star | three_black_crows
    elif candidate in {"supertrend_long", "supertrend_long_ha"}:
        trend_frame = _heikin_ashi(frame) if candidate.endswith("_ha") else frame
        direction = _supertrend_direction(trend_frame, period=9, multiplier=0.35)
        # Supertrend is an entry filter only. Bearish flips do not close a long.
        entries = (direction > 0) & (direction.shift(1) < 0)
        exits = pd.Series(False, index=frame.index, dtype=bool)
    else:
        raise ValueError(f"Unknown candidate: {candidate}")
    # Signals are calculated at candle close; shift execution to the next bar.
    return entries.shift(1).fillna(False).astype(bool), exits.shift(1).fillna(False).astype(bool)


def _run(frame: pd.DataFrame, candidate: str, order_size: float, take_profit: float, stop_loss: float, atr_target_mult: float | None = None, atr_stop_mult: float | None = None, trailing_stop: bool = False, higher_frame: pd.DataFrame | None = None) -> dict:
    entries, exits = _signals(frame, candidate, higher_frame)
    stop_kwargs = {}
    if atr_target_mult is not None or atr_stop_mult is not None:
        atr_pct = (_atr(frame) / frame["closes"]).clip(lower=0.0001, upper=0.2)
        if atr_target_mult is not None:
            stop_kwargs["tp_stop"] = atr_pct * atr_target_mult
        if atr_stop_mult is not None:
            stop_kwargs["sl_stop"] = atr_pct * atr_stop_mult
    if candidate in {"supertrend_long", "supertrend_long_ha"}:
        stop_kwargs.setdefault("tp_stop", take_profit)
        stop_kwargs.setdefault("sl_stop", stop_loss)
    elif candidate in {"ess_long", "std_dpmo_smartsar_long", "std_dpmo_smartsar_relaxed_long", "std_dpmo_smartsar_quality_long", "std_dpmo_smartsar_regime_long", "trend_phase_long", "tv_confluence_trend_long", "tv_mtf_confluence_long", "tv_mtf_confluence_relaxed_long", "tv_mtf_regime_long", "tv_mtf_regime_relaxed_long", "williams_fractal_ma_long"}:
        stop_kwargs.setdefault("tp_stop", take_profit)
        stop_kwargs.setdefault("sl_stop", stop_loss)
    if trailing_stop:
        stop_kwargs["sl_trail"] = True
    portfolio = vbt.Portfolio.from_signals(
        frame["closes"],
        entries=entries,
        exits=exits,
        size=order_size,
        size_type=vbt.portfolio.enums.SizeType.Value,
        direction=vbt.portfolio.enums.Direction.LongOnly,
        init_cash=config.INITIAL_BALANCE_TRY,
        fees=config.COMMISSION_PCT,
        slippage=config.ESTIMATED_SLIPPAGE_PCT,
        freq=INTERVAL_FREQ[ARGS.interval],
        **stop_kwargs,
    )
    trades = portfolio.trades.records_readable
    wins = int((trades["PnL"] > 0).sum()) if len(trades) else 0
    losses = int((trades["PnL"] <= 0).sum()) if len(trades) else 0
    gross_wins = float(trades.loc[trades["PnL"] > 0, "PnL"].sum()) if len(trades) else 0.0
    gross_losses = float(-trades.loc[trades["PnL"] <= 0, "PnL"].sum()) if len(trades) else 0.0
    return {
        "candidate": candidate,
        "bars": len(frame),
        "signals": int(entries.sum()),
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(100 * wins / len(trades), 2) if len(trades) else 0.0,
        "net_pnl": round(float(portfolio.total_return() * config.INITIAL_BALANCE_TRY), 4),
        "return_pct": round(float(portfolio.total_return() * 100), 4),
        "profit_factor": round(gross_wins / gross_losses, 4) if gross_losses else None,
        "max_drawdown_pct": round(float(portfolio.max_drawdown() * 100), 4),
        "total_fees": round(float(portfolio.orders.records_readable["Fees"].sum()), 4),
        "benchmark_return_pct": round(float((frame["closes"].iloc[-1] / frame["closes"].iloc[0] - 1) * 100), 4),
        "atr_target_mult": atr_target_mult,
        "atr_stop_mult": atr_stop_mult,
        "trailing_stop": trailing_stop,
    }


def _run_staged(frame: pd.DataFrame, candidate: str, order_size: float, take_profit: float, stop_loss: float, break_even_trigger: float, trailing_trigger: float, trailing_distance: float, higher_frame: pd.DataFrame | None = None) -> dict:
    """Research-only staged exit: initial SL -> break-even -> trailing."""
    entries, _ = _signals(frame, candidate, higher_frame)
    close, high, low = frame["closes"], frame["highs"], frame["lows"]
    fee_rate = float(config.COMMISSION_PCT)
    slippage = float(config.ESTIMATED_SLIPPAGE_PCT)
    trades, fees = [], 0.0
    i = 0
    while i < len(frame) - 1:
        if not bool(entries.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        entry = float(close.iloc[entry_i]) * (1 + slippage)
        qty = order_size / entry
        stop = entry * (1 - stop_loss)
        target = entry * (1 + take_profit)
        peak = entry
        exit_i, exit_price, reason = None, None, None
        for j in range(entry_i + 1, len(frame)):
            peak = max(peak, float(high.iloc[j]))
            if float(low.iloc[j]) <= stop:
                exit_i, exit_price, reason = j, stop * (1 - slippage), "staged_stop"
                break
            if float(high.iloc[j]) >= target:
                exit_i, exit_price, reason = j, target * (1 - slippage), "profit_target"
                break
            if peak >= entry * (1 + break_even_trigger):
                stop = max(stop, entry * (1 + fee_rate * 2.0))
            if peak >= entry * (1 + trailing_trigger):
                stop = max(stop, peak * (1 - trailing_distance))
        if exit_i is None:
            i += 1
            continue
        gross = (exit_price - entry) * qty
        trade_fees = (entry + exit_price) * qty * fee_rate
        net = gross - trade_fees
        fees += trade_fees
        trades.append({"pnl": net, "gross": gross, "reason": reason, "entry_i": entry_i, "exit_i": exit_i})
        i = exit_i + 1
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = len(trades) - wins
    gross_wins = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_losses = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    return {"candidate": candidate, "bars": len(frame), "signals": int(entries.sum()), "trades": len(trades), "wins": wins, "losses": losses, "win_rate_pct": round(100 * wins / len(trades), 2) if trades else 0.0, "net_pnl": round(sum(t["pnl"] for t in trades), 4), "return_pct": round(sum(t["pnl"] for t in trades) / config.INITIAL_BALANCE_TRY * 100, 4), "profit_factor": round(gross_wins / gross_losses, 4) if gross_losses else None, "total_fees": round(fees, 4), "staged_exit": True, "break_even_trigger": break_even_trigger, "trailing_trigger": trailing_trigger, "trailing_distance": trailing_distance}


def main() -> None:
    global ARGS
    parser = argparse.ArgumentParser(description="VectorBT public Binance TR strategy research")
    parser.add_argument("--symbols", default="BTCTRY,ETHTRY,SOLTRY")
    parser.add_argument("--interval", choices=sorted(INTERVAL_FREQ), default="5m")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--order-size", type=float, default=config.DEFAULT_ORDER_USDT)
    parser.add_argument("--take-profit", type=float, default=config.SPOT_PROFIT_TARGET_PCT)
    parser.add_argument("--stop-loss", type=float, default=config.HARD_STOP_LOSS_PCT)
    parser.add_argument("--atr-target-mult", type=float, default=None)
    parser.add_argument("--atr-stop-mult", type=float, default=None)
    parser.add_argument("--trailing-stop", action="store_true")
    parser.add_argument("--staged-exit", action="store_true")
    parser.add_argument("--break-even-trigger", type=float, default=0.0075)
    parser.add_argument("--trailing-trigger", type=float, default=0.0125)
    parser.add_argument("--trailing-distance", type=float, default=0.006)
    parser.add_argument("--ma50-stop", action="store_true")
    parser.add_argument("--risk-reward", type=float, default=1.5)
    parser.add_argument("--min-atr-stop", type=float, default=1.0)
    parser.add_argument("--cooldown-bars", type=int, default=5)
    parser.add_argument("--candidates", default="trend_regime,donchian_volume,rsi_bollinger,strong_candlestick,supertrend_long,supertrend_long_ha,ess_long,std_dpmo_smartsar_long,std_dpmo_smartsar_relaxed_long,trend_phase_long,tv_confluence_trend_long,tv_mtf_confluence_long,tv_mtf_confluence_relaxed_long,tv_mtf_regime_long,tv_mtf_regime_relaxed_long,williams_fractal_ma_long")
    ARGS = parser.parse_args()
    if not 1 <= ARGS.days <= 365:
        parser.error("--days 1 ile 365 arasında olmalı")
    output = []
    for symbol in [item.strip().upper() for item in ARGS.symbols.split(",") if item.strip()]:
        frame = _frame(symbol, ARGS.interval, ARGS.days)
        higher_frame = _frame(symbol, "15m", ARGS.days) if any(name in ARGS.candidates for name in ("tv_mtf_confluence_long", "tv_mtf_confluence_relaxed_long", "tv_mtf_regime_long", "tv_mtf_regime_relaxed_long")) else None
        for candidate in [item.strip() for item in ARGS.candidates.split(",") if item.strip()]:
            if ARGS.ma50_stop:
                result = _run_ma50_risk(frame, candidate, ARGS.order_size, ARGS.risk_reward, ARGS.min_atr_stop, ARGS.cooldown_bars)
            elif ARGS.staged_exit:
                result = _run_staged(frame, candidate, ARGS.order_size, ARGS.take_profit, ARGS.stop_loss, ARGS.break_even_trigger, ARGS.trailing_trigger, ARGS.trailing_distance, higher_frame)
            else:
                result = _run(frame, candidate, ARGS.order_size, ARGS.take_profit, ARGS.stop_loss, ARGS.atr_target_mult, ARGS.atr_stop_mult, ARGS.trailing_stop, higher_frame)
            output.append({"symbol": symbol, "interval": ARGS.interval, "days": ARGS.days, "take_profit": ARGS.take_profit, "stop_loss": ARGS.stop_loss, **result})
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
