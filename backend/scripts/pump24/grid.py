"""Target/stop grid search with train->test OOS validation.

For each signal rule: scan every (target_pct, stop_pct, horizon_bars, entry_mode,
cost) cell. EV per trade:
  win  -> +target_net  (gross target - cost)
  stop -> -stop_gross - cost
  flat -> (close[end]/entry - 1) - cost
Selection happens on TRAIN only; the same cells are then reported on TEST (OOS).

Entry modes:
  close      entry = signal M5 bar close; race starts next bar (signal known at close)
  next_open  entry = next bar open (slippage-safe, one bar later); race from next bar
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pump24 import data as D
from pump24 import events as E
from pump24.patterns import snapshot_hits, rule_tag
from pump24.run import fmt, universe, window_hours
from pump24.smc import build_frame

TZ = ZoneInfo("Europe/Istanbul")
STATE = Path(__file__).resolve().parent / "state"

TARGETS = [0.6, 1.0, 1.5, 2.0, 2.5, 3.0]
STOPS = [0.5, 0.75, 1.0, 1.5, 2.0]
HORIZONS = [3, 6]                    # 15 / 30 minutes
ENTRY_MODES = ["close", "next_open"]
COSTS = {"taker": 0.35, "maker": 0.15}
RACE_TIMEOUT_PENALTY = 0.0           # flat trades just take the close-to-close move


def race(f5, i_first, entry, gross_target, stop_pct, horizon):
    """Race from bar i_first (inclusive). Returns (win, stop)."""
    tgt = entry * (1 + gross_target / 100)
    stop_px = entry * (1 - stop_pct / 100)
    n = len(f5["open"])
    for j in range(i_first, min(i_first + horizon, n)):
        if f5["low"][j] <= stop_px:
            return False, True
        if f5["high"][j] >= tgt:
            return True, False
    return False, False


def scan_cell_data(symbols, start_ms, end_ms, rules):
    """One pass: for every decision bar hit by a rule, store (horizon outcomes).

    Returns per-rule list of dicts: {entry_close, entry_next_open, close_to_close3,
    close_to_close6, race results are computed per cell from stored highs/lows?}
    Memory-friendly approach: store minimal per-bar arrays per event instead.
    """
    conn = D.pg_connect()
    per_rule = {rule_tag(r): [] for r in rules}
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", max(start_ms - 3_600_000, 0), end_ms)
        if len(m5) < 80 or len(m1) < 300:
            continue
        f5 = build_frame(sym, "5m", m5)
        f1 = build_frame(sym, "1m", m1)
        m1_idx = {t: k for k, t in enumerate(f1["open_time"])}
        times = f5["open_time"]
        for i in range(60, len(m5) - 8):  # reserve 6 race bars + buffer
            groups = {}
            for g, off in (("m5_g0", 0), ("m5_g1", -1), ("m5_g2", -2)):
                idx = i + off
                groups[g] = {k: f5[k][idx] for k in E.SNAPSHOT_FIELDS if k in f5}
            for g in range(10):
                j = m1_idx.get(times[i] - (g + 1) * 60_000)
                if j is not None:
                    groups[f"m1_g{g}"] = {k: f1[k][j] for k in E.SNAPSHOT_FIELDS if k in f1}
            hits = [rule_tag(r) for r in rules if snapshot_hits(groups, r)]
            if not hits:
                continue
            highs = f5["high"]; lows = f5["low"]; closes = f5["close"]; opens = f5["open"]
            rec = {"highs": highs[i + 1:i + 7], "lows": lows[i + 1:i + 7],
                   "closes": closes[i + 1:i + 7], "next_open": opens[i + 1],
                   "entry_close": closes[i], "end_close_3": closes[i + 3], "end_close_6": closes[i + 6]}
            for t in hits:
                per_rule[t].append(rec)
    conn.close()
    return per_rule


def eval_cells(per_rule_recs, base_recs):
    """Evaluate all grid cells from stored records."""
    results = {}
    for tag, recs in per_rule_recs.items():
        results[tag] = eval_rule(recs)
    results["__base__"] = eval_rule(base_recs)
    return results


def eval_rule(recs):
    rows = []
    for mode in ENTRY_MODES:
        for horizon in HORIZONS:
            for tgt in TARGETS:
                for stop in STOPS:
                    for cost_name, cost in COSTS.items():
                        n = win = stopn = 0
                        net_sum = 0.0
                        for rec in recs:
                            entry = rec["entry_close"] if mode == "close" else rec["next_open"]
                            if not entry:
                                continue
                            if mode == "close":
                                h = rec["highs"][:horizon]
                                l = rec["lows"][:horizon]
                                end_close = rec[f"end_close_{horizon}"]
                            else:
                                h = rec["highs"][:horizon]
                                l = rec["lows"][:horizon]
                                end_close = rec[f"end_close_{horizon}"]
                            w, s = race_from(h, l, entry, tgt, stop)
                            if w:
                                net = tgt - cost
                            elif s:
                                net = -stop - cost
                            else:
                                net = (end_close / entry - 1) * 100 - cost
                            n += 1
                            win += w
                            stopn += s
                            net_sum += net
                        if n:
                            rows.append({"mode": mode, "horizon": horizon, "target": tgt,
                                         "stop": stop, "cost": cost_name, "n": n,
                                         "win_pct": round(100 * win / n, 1),
                                         "stop_pct": round(100 * stopn / n, 1),
                                         "ev_pct": round(net_sum / n, 3)})
    rows.sort(key=lambda r: -r["ev_pct"])
    return rows


def race_from(highs, lows, entry, gross_target, stop_pct):
    tgt = entry * (1 + gross_target / 100)
    stop_px = entry * (1 - stop_pct / 100)
    for h, l in zip(highs, lows):
        if l <= stop_px:
            return False, True
        if h >= tgt:
            return True, False
    return False, False


def cmd_grid():
    end_ms = window_hours(24)[1]
    train_end = end_ms - 24 * 3_600_000
    train_start = train_end - 144 * 3_600_000
    symbols = universe(top_n=50)

    rules = json.load(open(STATE / "rules.json", encoding="utf-8"))
    # candidate rules: close-entry continuation signals with decent OOS support
    wanted = ["m5g0_ema_gap_pct_gt2", "m5g0_vwap_dist_pct_gt2", "m5g0_atr_pct_gt1.0",
              "m5g0_atr_pct_gt1.5", "m1g0_bb_width_gt0.02",
              "m5g0_macd_line_pct_gt0.5", "m5g0_awesome_pct_gt1.0", "m5g0_bb_width_gt0.06"]
    tag_map = {rule_tag(r): r for r in rules}
    sel = [tag_map[t] for t in wanted if t in tag_map]
    print(f"[grid] candidate rules: {[rule_tag(r) for r in sel]}", flush=True)

    print("[grid] scanning train window ...", flush=True)
    per_rule_tr = scan_cell_data(symbols, train_start, train_end, sel)
    print("[grid] evaluating train cells ...", flush=True)
    train_eval = eval_cells(per_rule_tr, [])

    # pick best cell per rule by train EV (n>=40, taker first honesty: report both costs)
    best = {}
    for tag, rows in train_eval.items():
        if tag == "__base__":
            continue
        for r in rows:
            if r["n"] < 40:
                continue
            if tag not in best or r["ev_pct"] > best[tag]["ev_pct"]:
                best[tag] = r
    print("[grid] best train cells:", flush=True)
    for tag, r in best.items():
        print(f"  {tag:<32} {r['mode']:<9} h={r['horizon']} tgt={r['target']} stop={r['stop']} "
              f"{r['cost']:<6} n={r['n']:<5} win={r['win_pct']}% ev={r['ev_pct']}%", flush=True)

    print("[grid] scanning test window (OOS) ...", flush=True)
    per_rule_te = scan_cell_data(symbols, train_end, end_ms, sel)
    test_eval = eval_cells(per_rule_te, [])

    # OOS check: for each rule's best train cell, find the same cell on test
    oos_rows = []
    for tag, best_cell in best.items():
        same = next((r for r in test_eval[tag]
                     if (r["mode"], r["horizon"], r["target"], r["stop"], r["cost"]) ==
                     (best_cell["mode"], best_cell["horizon"], best_cell["target"], best_cell["stop"], best_cell["cost"])), None)
        if same:
            oos_rows.append({"tag": tag, "train": best_cell, "test": same,
                             "ev_delta": round(same["ev_pct"] - best_cell["ev_pct"], 3)})
    oos_rows.sort(key=lambda r: -r["test"]["ev_pct"])
    print("[grid] OOS same-cell results:", flush=True)
    for row in oos_rows:
        print(f"  {row['tag']:<32} test n={row['test']['n']:<4} win={row['test']['win_pct']}% "
              f"ev={row['test']['ev_pct']}% (train {row['train']['ev_pct']}%, delta {row['ev_delta']})", flush=True)

    out = {"type": "pump24_grid_v1", "generated_at": datetime.now(TZ).isoformat(),
           "grid": {"targets": TARGETS, "stops": STOPS, "horizons": HORIZONS,
                    "entry_modes": ENTRY_MODES, "costs": COSTS},
           "train_best_cells": best, "oos_same_cell": oos_rows,
           "train_eval_full": {k: v[:15] for k, v in train_eval.items()},
           "test_eval_full": {k: v[:15] for k, v in test_eval.items()}}
    (STATE / "grid_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("../../../pump24_grid_raporu.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[grid done]", flush=True)


if __name__ == "__main__":
    cmd_grid()
