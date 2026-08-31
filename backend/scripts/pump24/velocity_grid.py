"""Grid search for the v2 x M1/M3 leading-ATR pattern.

The pattern (v2 filter + M1 ATR>1.0 + M3 ATR>1.0) has high MFE (avg +1.54%
in 5m, +2.73% in 15m) but negative close-to-close return — prices spike and
revert. This grid tests whether any (target, stop, horizon, exit-mode)
combination turns the MFE into positive net EV after costs.

Two exit modes:
  race   — target vs stop race (first hit wins), exit at market on the other
  spike  — exit at target if touched; else exit at horizon close (no stop)

Costs: taker round-trip 0.35% (commission 0.15x2 + slippage 0.025x2),
maker 0.15%. Entry at signal close. Paper research only.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pump24.velocity_backtest import v_filter
from pump24 import data as D

STATE = Path(__file__).resolve().parent / "state"

TAKER_RT = 0.35
MAKER_RT = 0.15

# Grid: targets / stops / horizons in percent-of-price
TARGETS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
STOPS = [0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
HORIZONS = [5, 10, 15, 20, 30]


def run_grid(hours=24, symbols_limit=150, leading_only=True):
    end_ms = int(time.time() * 1000) // 60_000 * 60_000
    start_ms = end_ms - hours * 3_600_000
    conn = D.pg_connect()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM historical_candles WHERE timeframe='1m'")
    symbols = sorted(r[0] for r in cur.fetchall())[:symbols_limit]

    # Pre-collect signal bars with their forward M1 series (closes/highs/lows)
    signals = []  # list of dicts: symbol, entry, fwd arrays
    for sym in symbols:
        rows = D.load_candles(conn, sym, "1m", start_ms - 2 * 3_600_000, end_ms)
        if len(rows) < 100:
            continue
        closes = [r["close"] for r in rows]
        highs = [r["high"] for r in rows]
        lows = [r["low"] for r in rows]
        vols = [r["volume"] for r in rows]
        times = [r["open_time"] for r in rows]
        n = len(closes)
        i0 = next((k for k, t in enumerate(times) if t >= start_ms), n)
        def atr_at(idx):
            if idx < 15 or idx >= n:
                return 0.0
            trs = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
                   for j in range(idx - 14, idx + 1)]
            return (sum(trs) / len(trs)) / closes[idx] * 100 if trs else 0
        for i in range(i0, n - 31):
            if i < 45:
                continue
            passes, mode, ex = v_filter(closes[:i + 1], highs[:i + 1], lows[:i + 1], vols[:i + 1])
            if not passes:
                continue
            if leading_only and not (atr_at(i - 1) > 1.0 and atr_at(i - 3) > 1.0):
                continue
            entry = closes[i]
            signals.append({
                "symbol": sym,
                "entry": entry,
                "closes": closes[i:i + 31],
                "highs": highs[i:i + 31],
                "lows": lows[i:i + 31],
            })
    conn.close()
    print(f"[grid] {len(signals)} signals ({'leading-only' if leading_only else 'v2-only'})", flush=True)

    results = []
    for horizon in HORIZONS:
        for target in TARGETS:
            for stop in STOPS:
                for mode in ("race", "spike"):
                    n = win = 0
                    pnl_taker = pnl_maker = 0.0
                    hold_sum = 0
                    for s in signals:
                        entry = s["entry"]
                        exit_px = None
                        hold = horizon
                        # scan bars 1..horizon (1-based offset)
                        for k in range(1, min(horizon, len(s["closes"]) - 1) + 1):
                            hi = s["highs"][k]
                            lo = s["lows"][k]
                            if (hi / entry - 1) * 100 >= target:
                                # fill at target (optimistic limit); spike mode exits here too
                                exit_px = entry * (1 + target / 100)
                                hold = k
                                break
                            if mode == "race" and (lo / entry - 1) * 100 <= -stop:
                                exit_px = entry * (1 - stop / 100)
                                hold = k
                                break
                        if exit_px is None:
                            exit_px = s["closes"][min(horizon, len(s["closes"]) - 1)]
                        gross = (exit_px / entry - 1) * 100
                        n += 1
                        pnl_taker += gross - TAKER_RT
                        pnl_maker += gross - MAKER_RT
                        win += 1 if gross > 0 else 0
                        hold_sum += hold
                    if n >= 20:
                        results.append({
                            "mode": mode, "horizon": horizon, "target": target, "stop": stop,
                            "n": n, "win_rate": round(100 * win / n, 1),
                            "ev_taker": round(pnl_taker / n, 3), "ev_maker": round(pnl_maker / n, 3),
                            "avg_hold": round(hold_sum / n, 1),
                        })
    results.sort(key=lambda r: -r["ev_taker"])
    out = {"hours": hours, "signals": len(signals), "leading_only": leading_only,
           "costs": {"taker_rt": TAKER_RT, "maker_rt": MAKER_RT},
           "results": results}
    (STATE / "velocity_grid.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[grid] {len(results)} cells", flush=True)
    print("Top 12 by taker EV:", flush=True)
    for r in results[:12]:
        print(f"  {r['mode']:<6} H{r['horizon']:<3} T{r['target']} S{r['stop']}: "
              f"n={r['n']} win={r['win_rate']}% EVt={r['ev_taker']} EVm={r['ev_maker']}", flush=True)
    # count positive cells
    pos_taker = [r for r in results if r["ev_taker"] > 0]
    pos_maker = [r for r in results if r["ev_maker"] > 0]
    print(f"positive EV cells: taker={len(pos_taker)} maker={len(pos_maker)}", flush=True)
    return out


if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    run_grid(hours=hours, symbols_limit=limit)
