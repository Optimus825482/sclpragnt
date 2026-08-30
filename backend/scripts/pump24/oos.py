"""Out-of-sample validation + fee-aware entry simulation for the pump24 patterns.

Stages:
  fetch7d   7-day M5+M1 klines for the top-50 universe -> DB (Binance TR keeps ~8d of 1m)
  oos       train window = -168h..-24h: detect events, mine rules;
            test window = -24h..now: score ALL mined rules OOS;
            fixed candidate combo scored on both windows;
            fee-aware sim: entry at decision-bar close, round-trip 0.35%,
            target +0.6% net vs stop race + no-stop horizon return + MFE/MAE.
"""

import json
import math
import sys
import time
from datetime import datetime
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pump24 import data as D
from pump24 import events as E
from pump24 import patterns as P
from pump24.run import fmt, universe, window_hours
from pump24.smc import build_frame

TZ = ZoneInfo("Europe/Istanbul")
STATE = Path(__file__).resolve().parent / "state"
ROUND_TRIP_COST_PCT = 0.35          # commission 0.15 x2 + slippage 0.025 x2
NET_TARGET_PCT = 0.60               # net profit target per trade
STOP_PCT = 1.5                      # race stop
HORIZON_BARS = 3                    # 15 minutes
FIXED_COMBO = ["m5g0_atr_pct_gt1.5", "m1g0_atr_pct_gt0.6", "m5g0_awesome_pct_gt1.0"]


def fetch7d():
    start_ms, end_ms = window_hours(168)
    symbols = universe(top_n=50)
    conn = D.pg_connect()
    n_ok = 0
    for sym in symbols:
        try:
            n5 = D.sync_symbol(conn, sym, "5m", start_ms, end_ms)
            n1 = D.sync_symbol(conn, sym, "1m", start_ms, end_ms)
            n_ok += 1
            if n_ok % 10 == 0:
                print(f"  [{n_ok}/{len(symbols)}] {sym} 5m={n5} 1m={n1}", flush=True)
        except Exception as exc:
            print(f"  [ERR] {sym}: {exc}", flush=True)
        time.sleep(0.08)
    conn.close()
    print(f"[fetch7d done] {n_ok}/{len(symbols)} symbols", flush=True)


def scan_symbols(symbols, start_ms, end_ms, rules, fixed_rules, collect_base=True):
    """Scan M5 decision bars; returns per-rule stats, fixed-combo stats and
    fee-sim outcomes. rules: list of rule dicts (tags computed here)."""
    tag_stats = {}
    fixed_stats = {"n": 0, "raw_target_hits": 0, "fee_target": 0, "stop_first": 0,
                   "net_sum": 0.0, "mfe_sum": 0.0, "mae_sum": 0.0, "events": []}
    base = {"n": 0, "raw_target_hits": 0, "fee_target": 0, "net_sum": 0.0}
    conn = D.pg_connect()
    from pump24.patterns import snapshot_hits, rule_tag
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", max(start_ms - 3_600_000, 0), end_ms)
        if len(m5) < 80 or len(m1) < 300:
            continue
        f5 = build_frame(sym, "5m", m5)
        f1 = build_frame(sym, "1m", m1)
        m1_idx = {t: k for k, t in enumerate(f1["open_time"])}
        times = f5["open_time"]
        for i in range(60, len(m5) - HORIZON_BARS):
            rise = times[i]
            entry = f5["close"][i]
            if not entry:
                continue
            highs = f5["high"]; lows = f5["low"]; closes = f5["close"]
            tgt_raw = entry * (1 + 0.01)
            tgt_fee = entry * (1 + (NET_TARGET_PCT + ROUND_TRIP_COST_PCT) / 100)
            stop_px = entry * (1 - STOP_PCT / 100)
            hit_fee = stop_first = False
            mfe = mae = 0.0
            for j in range(i + 1, i + 1 + HORIZON_BARS):
                mfe = max(mfe, (highs[j] / entry - 1) * 100)
                mae = min(mae, (lows[j] / entry - 1) * 100)
                if lows[j] <= stop_px and not hit_fee:
                    stop_first = True
                if highs[j] >= tgt_fee and not stop_first:
                    hit_fee = True
                    break
            horizon_ret = (closes[i + HORIZON_BARS] / entry - 1) * 100 - ROUND_TRIP_COST_PCT
            base["n"] += 1
            base["raw_target_hits"] += any((highs[j] / entry - 1) * 100 >= 1.0 for j in range(i + 1, i + 1 + HORIZON_BARS))
            base["fee_target"] += hit_fee
            base["net_sum"] += horizon_ret
            groups = {}
            for g, off in (("m5_g0", 0), ("m5_g1", -1), ("m5_g2", -2)):
                idx = i + off
                groups[g] = {k: f5[k][idx] for k in E.SNAPSHOT_FIELDS if k in f5}
            for g in range(10):
                j = m1_idx.get(rise - (g + 1) * 60_000)
                if j is not None:
                    groups[f"m1_g{g}"] = {k: f1[k][j] for k in E.SNAPSHOT_FIELDS if k in f1}
            hits = [rule_tag(r) for r in rules if snapshot_hits(groups, r)]
            for tag in hits:
                st = tag_stats.setdefault(tag, {"n": 0, "raw": 0, "fee": 0, "stop": 0,
                                                "net_sum": 0.0, "mfe_sum": 0.0, "mae_sum": 0.0})
                st["n"] += 1
                st["raw"] += any((highs[j] / entry - 1) * 100 >= 1.0 for j in range(i + 1, i + 1 + HORIZON_BARS))
                st["fee"] += hit_fee
                st["stop"] += stop_first
                st["net_sum"] += horizon_ret
                st["mfe_sum"] += mfe
                st["mae_sum"] += mae
            if all(snapshot_hits(groups, r) for r in fixed_rules):
                fixed_stats["n"] += 1
                fixed_stats["raw_target_hits"] += any((highs[j] / entry - 1) * 100 >= 1.0 for j in range(i + 1, i + 1 + HORIZON_BARS))
                fixed_stats["fee_target"] += hit_fee
                fixed_stats["stop_first"] += stop_first
                fixed_stats["net_sum"] += horizon_ret
                fixed_stats["mfe_sum"] += mfe
                fixed_stats["mae_sum"] += mae
                if len(fixed_stats["events"]) < 12:
                    fixed_stats["events"].append({"symbol": sym, "time": fmt(rise),
                                                  "net_ret_pct": round(horizon_ret, 2),
                                                  "fee_target": bool(hit_fee)})
    conn.close()
    return tag_stats, fixed_stats, base


def summarize_rule_stats(tag_stats, base, min_n=15):
    base_raw = 100 * base["raw_target_hits"] / base["n"] if base["n"] else None
    base_fee = 100 * base["fee_target"] / base["n"] if base["n"] else None
    rows = []
    for tag, st in tag_stats.items():
        if st["n"] < min_n:
            continue
        rows.append({
            "tag": tag, "n": st["n"],
            "raw_acc_pct": round(100 * st["raw"] / st["n"], 1),
            "raw_lift": round(100 * st["raw"] / st["n"] - base_raw, 1),
            "fee_acc_pct": round(100 * st["fee"] / st["n"], 1),
            "fee_lift": round(100 * st["fee"] / st["n"] - base_fee, 1),
            "stop_first_pct": round(100 * st["stop"] / st["n"], 1),
            "avg_net_ret_pct": round(st["net_sum"] / st["n"], 3),
            "avg_mfe_pct": round(st["mfe_sum"] / st["n"], 2),
            "avg_mae_pct": round(st["mae_sum"] / st["n"], 2),
        })
    rows.sort(key=lambda r: -r["fee_acc_pct"])
    return {"base_raw_pct": round(base_raw, 2), "base_fee_pct": round(base_fee, 2), "bars": base["n"], "rules": rows}


def cmd_oos():
    end_ms = window_hours(24)[1]
    train_start = end_ms - 168 * 3_600_000
    train_end = end_ms - 24 * 3_600_000
    symbols = universe(top_n=50)
    print(f"[oos] train {fmt(train_start)}..{fmt(train_end)} | test {fmt(train_end)}..{fmt(end_ms)}", flush=True)

    # ---- TRAIN: events + mining on -168..-24 ----
    conn = D.pg_connect()
    train_events = []
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", train_start, train_end)
        m1 = D.load_candles(conn, sym, "1m", train_start - 3_600_000, train_end)
        if len(m5) < 300 or len(m1) < 600:
            continue
        f5 = build_frame(sym, "5m", m5)
        f1 = build_frame(sym, "1m", m1)
        for ev in E.detect_events(m5, 2.0):
            snap = E.event_snapshot(sym, f5, f1, ev)
            if snap:
                train_events.append(snap)
    conn.close()
    print(f"[oos] train events: {len(train_events)}", flush=True)
    rules = P.mine_patterns(train_events, min_frac=0.60)
    tag_map = {P.rule_tag(r): r for r in rules}
    fixed_rules = [tag_map[t] for t in FIXED_COMBO if t in tag_map]
    print(f"[oos] mined rules: {len(rules)} (fixed combo present: {len(fixed_rules)}/3)", flush=True)
    (STATE / "oos_rules_train.json").write_text(json.dumps(rules, ensure_ascii=False, indent=1))
    (STATE / "oos_events_train.json").write_text(json.dumps(train_events, ensure_ascii=False))

    # ---- TEST: OOS scoring on last 24h ----
    tag_stats, fixed_stats, base = scan_symbols(symbols, train_end, end_ms, rules, fixed_rules)
    test_summary = summarize_rule_stats(tag_stats, base)

    # ---- TRAIN-window in-sample scoring of the same rules (for comparison) ----
    tag_stats_tr, fixed_stats_tr, base_tr = scan_symbols(symbols, train_start, train_end, rules, fixed_rules)
    train_summary = summarize_rule_stats(tag_stats_tr, base_tr)

    out = {
        "type": "pump24_oos_v1",
        "generated_at": datetime.now(TZ).isoformat(),
        "windows": {"train": {"start": fmt(train_start), "end": fmt(train_end), "hours": 144},
                    "test": {"start": fmt(train_end), "end": fmt(end_ms), "hours": 24}},
        "sim": {"round_trip_cost_pct": ROUND_TRIP_COST_PCT, "net_target_pct": NET_TARGET_PCT,
                "stop_pct": STOP_PCT, "horizon_bars": HORIZON_BARS},
        "train_events": len(train_events),
        "fixed_combo": {"tags": FIXED_COMBO,
                        "train": fixed_stats_tr, "test": fixed_stats,
                        "test_acc_pct": round(100 * fixed_stats["fee_target"] / fixed_stats["n"], 1) if fixed_stats["n"] else None,
                        "test_base_fee_pct": test_summary["base_fee_pct"]},
        "test_rules": test_summary,
        "train_rules_top": {"base_raw_pct": train_summary["base_raw_pct"],
                            "base_fee_pct": train_summary["base_fee_pct"],
                            "rules": train_summary["rules"][:20]},
    }
    out_path = "../../../pump24_oos_raporu.json"
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    (STATE / "oos_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[oos done] {out_path}", flush=True)
    print(json.dumps(out["fixed_combo"]["test"], ensure_ascii=False)[:600], flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "oos"
    if cmd == "fetch7d":
        fetch7d()
    elif cmd == "oos":
        cmd_oos()
    else:
        print(__doc__)
