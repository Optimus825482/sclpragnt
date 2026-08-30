"""≥%2 M5 pump event detection + causal snapshot groups + DB persistence.

Groups (per user spec):
  m5_g0 = the rise-start M5 candle (open_time == rise_start_ms)
  m5_g1 = one M5 candle before, m5_g2 = two before
  m1_g0..m1_g9 = the 10 M1 candles immediately BEFORE the rise-start M5 candle
                 (g0 = closest to the rise start, i.e. the 11:15 bar for an 11:25 rise)
"""

import json
import math
import time

from pump24 import features as F
from pump24.smc import build_frame

M5_MS = 300_000
M1_MS = 60_000
SNAPSHOT_VERSION = "pump24-snap-v1"
MIN_RISE_PCT = 2.0
PRIOR_BARS = 2
M1_COUNT = 10
MIN_M1_HISTORY = 200   # M1 bars required before the event for a warm frame
MIN_M5_HISTORY = 60    # M5 bars (incl. rise bar) required for a warm frame

SNAPSHOT_FIELDS = [
    "close", "ret_1", "ret_3", "ret_5", "ret_10", "ret_15", "ret_30",
    "rsi_14", "crsi", "cmo_9", "stoch_k", "stoch_d", "stochrsi_k", "stochrsi_d",
    "cci_20", "williams_14", "awesome", "mfi_14", "tsi", "trix_15",
    "macd_line", "macd_signal", "macd_hist",
    "macd_line_pct", "macd_signal_pct", "macd_hist_pct", "awesome_pct", "obv_slope_norm",
    "ema_gap_pct", "ema_bull_align",
    "adx_14", "plus_di", "minus_di", "di_gap",
    "atr_pct", "bb_pos", "bb_width", "chop_14",
    "vwap_dist_pct", "vol_ratio_20", "vol_osc", "obv_slope_5", "cmf_20",
    "vortex_plus", "vortex_minus", "vortex_bull",
    "supertrend_dir", "aroon_up", "aroon_down", "ichimoku_above",
    "td9_bull", "td9_bear", "fvg_bull", "fvg_bear",
    "wick_upper_z", "wick_lower_z", "wick_signal", "bos", "inside_bar", "candle_label",
    "donchian20_pos",
]


def detect_events(m5_rows, min_rise_pct=MIN_RISE_PCT, prior_bars=PRIOR_BARS, cooldown_bars=6):
    """Rise-start M5 candle: close_i vs close_{i-1} >= min_rise_pct, dedup within cooldown."""
    events = []
    last_ts = None
    for i in range(prior_bars, len(m5_rows)):
        prev_close = m5_rows[i - 1]["close"]
        if not prev_close:
            continue
        rise = (m5_rows[i]["close"] / prev_close - 1) * 100
        if rise >= min_rise_pct:
            ts = m5_rows[i]["open_time"]
            if last_ts is not None and ts - last_ts < cooldown_bars * M5_MS:
                continue
            events.append({
                "rise_start_ms": ts,
                "rise_pct": round(rise, 4),
                "rise_start_close": m5_rows[i]["close"],
                "prior_close": prev_close,
            })
            last_ts = ts
    return events


def _clean(value):
    if isinstance(value, float) and (not math.isfinite(value)):
        return None
    return value


def build_snap(frame, idx):
    out = {}
    for key in SNAPSHOT_FIELDS:
        series = frame.get(key)
        value = series[idx] if series is not None and idx < len(series) else None
        out[key] = _clean(value)
    return out


def event_snapshot(symbol, m5_frame, m1_frame, event,
                   min_m1_history=MIN_M1_HISTORY, min_m5_history=MIN_M5_HISTORY):
    """Attach causal snapshot groups to ``event``; returns event dict or None."""
    rise_ms = event["rise_start_ms"]
    m5_times = m5_frame["open_time"]
    m1_times = m1_frame["open_time"]

    if rise_ms not in m5_times:
        return None
    gi = m5_times.index(rise_ms)
    if gi < PRIOR_BARS or gi + 1 < MIN_M5_HISTORY:
        return None
    if m1_times[0] >= rise_ms:
        return None

    m1_before = [t for t in m1_times if rise_ms - M1_COUNT * M1_MS <= t < rise_ms]
    if len(m1_before) < M1_COUNT:
        return None
    m1_hist_count = sum(1 for t in m1_times if t < rise_ms)
    if m1_hist_count < min_m1_history:
        return None

    groups = {}
    for off in range(PRIOR_BARS + 1):
        idx = gi - off
        groups[f"m5_g{off}"] = {"open_time": m5_times[idx], **build_snap(m5_frame, idx)}

    m1_idx = {t: k for k, t in enumerate(m1_times)}
    for k, t in enumerate(reversed(m1_before)):  # g0 = closest to the rise
        idx = m1_idx[t]
        groups[f"m1_g{k}"] = {"open_time": t, **build_snap(m1_frame, idx)}

    return {**event, "symbol": symbol, "snapshot_version": SNAPSHOT_VERSION, "groups": groups}


def save_snapshots(conn, events):
    """Upsert into historical_feature_snapshots (5m/1m row per group bar)."""
    rows = []
    captured = int(time.time())
    for ev in events:
        for name, g in (ev.get("groups") or {}).items():
            tf = "5m" if name.startswith("m5") else "1m"
            rows.append((ev["symbol"], tf, g["open_time"], captured, SNAPSHOT_VERSION,
                         json.dumps({"group": name, **g}, separators=(",", ":"))))
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO historical_feature_snapshots (symbol,timeframe,open_time,captured_at,feature_version,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (symbol,timeframe,open_time,feature_version) DO NOTHING", rows)
    conn.commit()
    return len(rows)


def save_events(conn, run_type, events):
    """Persist event summary rows into research_runs.result for later stages."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO research_runs (run_type, scope, symbols, timeframes, parameters, result, status, paper_only) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (run_type, "pump24_events", json.dumps(sorted({e["symbol"] for e in events})),
             json.dumps(["1m", "5m"]), json.dumps({"min_rise_pct": MIN_RISE_PCT}),
             json.dumps(events), "completed", True))
    conn.commit()
    return True
