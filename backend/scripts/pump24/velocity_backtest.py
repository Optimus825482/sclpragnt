"""Independent backtest of the live v2 velocity filter.

Replays the exact filter math from ``app/routers/velocity.py`` (same formulas,
same thresholds) on stored 1m candles, then measures the same forward outcome
the live loop uses: within horizon minutes, did MFE reach target%?

Why this exists: the live panel mixes 5dk-%2 and 15dk-%3 profiles into one
"koşullu isabet" number and its MFE unit is wrong in the UI. This backtest
gives profile-separated, definition-consistent numbers, and lets us test the
learning loop's ATR-threshold adjustment end to end on history.

Paper research only — no orders, no state writes.
"""

import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from pump24 import data as D

TZ = ZoneInfo("Europe/Istanbul")
STATE = Path(__file__).resolve().parent / "state"

# --- exact copies of the live filter formulas (velocity.py) -----------------

MIN_ATR_PCT = 0.30
MIN_BB_WIDTH_PCT = 2.5
TREND_RSI_MIN = 60.0
REVERSAL_RSI_MAX = 35.0
STRUCT_SLOPE_PCT = 0.20
MFI_UPPER = 90.0
MFI_LOWER = 10.0
RSI_UPPER = 80.0


def v_rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    return 100 - 100 / (1 + gains / losses) if losses else 100.0


def v_mfi(highs, lows, closes, vols, n=14):
    if len(closes) < n + 1:
        return None
    pos = neg = 0.0
    for i in range(len(closes) - n, len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        prev = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3
        flow = tp * vols[i]
        if tp > prev:
            pos += flow
        elif tp < prev:
            neg += flow
    return 100.0 if not neg else 100 - 100 / (1 + pos / neg)


def v_bb_width(closes, n=20, mult=2.0):
    if len(closes) < n:
        return None
    m = sum(closes[-n:]) / n
    sd = (sum((c - m) ** 2 for c in closes[-n:]) / n) ** 0.5
    return (4 * sd) / m * 100 if m else None


def v_linreg_slope(closes, n=20):
    if len(closes) < n:
        return None
    xs = list(range(n))
    ys = closes[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den else 0
    return slope / my * 100 * 10 if my else None


def v_aroon_up(highs, n=25):
    if len(highs) < n + 1:
        return None
    win = highs[-(n + 1):]
    return (n - (len(win) - 1 - win.index(max(win)))) / n * 100


def v_filter(row_closes, row_highs, row_lows, row_vols):
    """Returns (passes: bool, mode: str|None, exhausted: bool)."""
    i = len(row_closes) - 1
    price = row_closes[-1]
    if price <= 0:
        return False, None, False
    trs = [max(row_highs[j] - row_lows[j],
                abs(row_highs[j] - row_closes[j - 1]),
                abs(row_lows[j] - row_closes[j - 1]))
           for j in range(max(1, i - 14), i + 1)]
    atr_pct = (sum(trs) / len(trs)) / price * 100 if trs else 0.0
    bb_width = v_bb_width(row_closes)
    rsi = v_rsi(row_closes)
    mfi = v_mfi(row_highs, row_lows, row_closes, row_vols)
    slope = v_linreg_slope(row_closes)
    aroon_up = v_aroon_up(row_highs)
    ret3 = (row_closes[-1] / row_closes[-4] - 1) * 100 if len(row_closes) >= 4 else 0.0
    if rsi is None:
        return False, None, False
    mode = "trend_devam" if rsi >= TREND_RSI_MIN else \
           "v_donusu" if rsi <= REVERSAL_RSI_MAX else None
    struct_ok = (slope is not None and slope >= STRUCT_SLOPE_PCT) or \
                (aroon_up is not None and aroon_up >= 50)
    exhausted = (mfi is not None and mfi >= MFI_UPPER) or \
                (mfi is not None and mfi <= MFI_LOWER) or \
                (rsi is not None and rsi >= RSI_UPPER)
    passes = (not exhausted and
              atr_pct >= MIN_ATR_PCT and
              bb_width is not None and bb_width >= MIN_BB_WIDTH_PCT and
              mode is not None and
              (struct_ok or (mode == "v_donusu" and ret3 >= 0.30)))
    return passes, mode, exhausted


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%m-%d %H:%M")


def run_backtest(hours=24, horizon_minutes=5, target_pct=2.0, step_minutes=1,
                 start_offset_hours=None, symbols_limit=None):
    """Scan stored 1m bars every ``step_minutes``; on pass, measure forward MFE
    over the next ``horizon_minutes``. Returns per-symbol + aggregate stats."""
    end_ms = int(time.time() * 1000) // 60_000 * 60_000
    start_ms = end_ms - hours * 3_600_000
    if start_offset_hours:
        start_ms = end_ms - start_offset_hours * 3_600_000
    conn = D.pg_connect()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='1m' AND open_time >= %s",
                (start_ms - 2 * 3_600_000,))
    symbols = sorted(r[0] for r in cur.fetchall())
    if symbols_limit:
        symbols = symbols[:symbols_limit]

    passing = {"n": 0, "touched": 0, "mfe_sum": 0.0, "ret_sum": 0.0}
    scanned = 0
    per_symbol = {}
    examples = []
    step_ms = step_minutes * 60_000
    for sym in symbols:
        rows = D.load_candles(conn, sym, "1m", start_ms - 2 * 3_600_000, end_ms)
        if len(rows) < 100:
            continue
        closes = [r["close"] for r in rows]
        highs = [r["high"] for r in rows]
        lows = [r["low"] for r in rows]
        vols = [r["volume"] for r in rows]
        times = [r["open_time"] for r in rows]
        # scan from the first bar at/after start_ms
        i0 = next((k for k, t in enumerate(times) if t >= start_ms), len(times))
        scanned += 1
        sym_passing = sym_touched = 0
        for i in range(i0, len(rows) - horizon_minutes):
            if times[i] % step_ms != 0 and times[i] != times[i0]:
                continue
            if i < 45:
                continue
            passes, mode, exhausted = v_filter(closes[:i + 1], highs[:i + 1],
                                               lows[:i + 1], vols[:i + 1])
            if not passes:
                continue
            entry = closes[i]
            best = entry
            for j in range(i + 1, min(i + 1 + horizon_minutes, len(rows))):
                best = max(best, highs[j])
            mfe = (best / entry - 1) * 100
            fwd_ret = (closes[min(i + horizon_minutes, len(rows) - 1)] / entry - 1) * 100
            passing["n"] += 1
            passing["touched"] += 1 if mfe >= target_pct else 0
            passing["mfe_sum"] += mfe
            passing["ret_sum"] += fwd_ret
            sym_passing += 1
            sym_touched += 1 if mfe >= target_pct else 0
            if len(examples) < 10:
                examples.append({"symbol": sym, "at": fmt(times[i]), "mode": mode,
                                 "mfe": round(mfe, 2), "touched": mfe >= target_pct})
        per_symbol[sym] = {"passing": sym_passing, "touched": sym_touched}
    conn.close()
    n = passing["n"]
    out = {
        "window": {"start": fmt(start_ms), "end": fmt(end_ms)},
        "horizon_minutes": horizon_minutes, "target_pct": target_pct,
        "step_minutes": step_minutes, "symbols_scanned": scanned,
        "passing_count": n,
        "touch_pct": round(100 * passing["touched"] / n, 2) if n else None,
        "avg_mfe_pct": round(passing["mfe_sum"] / n, 3) if n else None,
        "avg_ret_pct": round(passing["ret_sum"] / n, 3) if n else None,
        "examples": examples,
    }
    (STATE / "velocity_bt.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[bt {horizon_minutes}dk-%{target_pct}] {n} passing / {scanned} symbols "
          f"| touch {out['touch_pct']}% | avg MFE {out['avg_mfe_pct']}% | avg ret {out['avg_ret_pct']}%",
          flush=True)
    return out


if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    horizon = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    target = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    step = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    run_backtest(hours=hours, horizon_minutes=horizon, target_pct=target,
                 step_minutes=step)
