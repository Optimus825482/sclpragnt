"""Early-entry validation: fire M1/previous-M5 rules at the decision bar's OPEN.

The close-entry OOS showed the signal is real (fee-target ~70-74%) but
breakeven because entry happens after the first pump bar. M1-based rules
(m1_g0..g9) and previous-M5 rules (m5_g1/g2) are causally available at the
decision bar's open, so entry = decision-bar open, race starts inside the
decision bar itself (3 M5 bars total).
"""

import json
import sys
from datetime import datetime
from itertools import combinations
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
ROUND_TRIP_COST_PCT = 0.35
NET_TARGET_PCT = 0.60
STOP_PCT = 1.5
EARLY_GROUPS_OK = {"m5_g1", "m5_g2"} | {f"m1_g{k}" for k in range(10)}


def race_outcome(f5, i, entry):
    """Race from inside bar i (entry at its open): target vs stop, 3 bars."""
    tgt_gross = entry * (1 + (NET_TARGET_PCT + ROUND_TRIP_COST_PCT) / 100)
    stop_px = entry * (1 - STOP_PCT / 100)
    hit = stop = False
    mfe = mae = 0.0
    for j in range(i, min(i + 3, len(f5["open"]))):
        mfe = max(mfe, (f5["high"][j] / entry - 1) * 100)
        mae = min(mae, (f5["low"][j] / entry - 1) * 100)
        if f5["low"][j] <= stop_px:
            stop = True
            break
        if f5["high"][j] >= tgt_gross:
            hit = True
            break
    if hit:
        net = NET_TARGET_PCT
    elif stop:
        net = -STOP_PCT - ROUND_TRIP_COST_PCT
    else:
        end = min(i + 3, len(f5["open"]) - 1)
        net = (f5["close"][end] / entry - 1) * 100 - ROUND_TRIP_COST_PCT
    return hit, stop, net, mfe, mae


def scan(symbols, start_ms, end_ms, rules, combos=None):
    """combos: list of rule-lists; each combo fires only if ALL its rules hit."""
    conn = D.pg_connect()
    stats = {}
    combo_stats = {j: {"n": 0, "hit": 0, "stop": 0, "net_sum": 0.0} for j in range(len(combos or []))}
    base = {"n": 0, "hit": 0, "net_sum": 0.0}
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", max(start_ms - 3_600_000, 0), end_ms)
        if len(m5) < 80 or len(m1) < 300:
            continue
        f5 = build_frame(sym, "5m", m5)
        f1 = build_frame(sym, "1m", m1)
        m1_idx = {t: k for k, t in enumerate(f1["open_time"])}
        times = f5["open_time"]
        for i in range(60, len(m5) - 3):
            entry = f5["open"][i]
            if not entry:
                continue
            groups = {}
            for g, off in (("m5_g1", -1), ("m5_g2", -2)):
                idx = i + off
                groups[g] = {k: f5[k][idx] for k in E.SNAPSHOT_FIELDS if k in f5}
            for g in range(10):
                j = m1_idx.get(times[i] - (g + 1) * 60_000)
                if j is not None:
                    groups[f"m1_g{g}"] = {k: f1[k][j] for k in E.SNAPSHOT_FIELDS if k in f1}
            hit, stop, net, mfe, mae = race_outcome(f5, i, entry)
            base["n"] += 1
            base["hit"] += hit
            base["net_sum"] += net
            hits = [rule_tag(r) for r in rules if snapshot_hits(groups, r)]
            for tag in hits:
                st = stats.setdefault(tag, {"n": 0, "hit": 0, "stop": 0, "net_sum": 0.0,
                                            "mfe_sum": 0.0, "mae_sum": 0.0, "ex": []})
                st["n"] += 1
                st["hit"] += hit
                st["stop"] += stop
                st["net_sum"] += net
                st["mfe_sum"] += mfe
                st["mae_sum"] += mae
                if hit and len(st["ex"]) < 4:
                    st["ex"].append(f"{sym} {fmt(times[i])}")
            if combos:
                for j, combo_rules in enumerate(combos):
                    if all(snapshot_hits(groups, r) for r in combo_rules):
                        cst = combo_stats[j]
                        cst["n"] += 1
                        cst["hit"] += hit
                        cst["stop"] += stop
                        cst["net_sum"] += net
    conn.close()
    return stats, base, combo_stats


def summarize(stats, base, min_n=15):
    base_hit = 100 * base["hit"] / base["n"] if base["n"] else None
    base_ev = base["net_sum"] / base["n"] if base["n"] else None
    rows = []
    for tag, st in stats.items():
        if st["n"] < min_n:
            continue
        ev = st["net_sum"] / st["n"]
        rows.append({"tag": tag, "n": st["n"],
                     "hit_pct": round(100 * st["hit"] / st["n"], 1),
                     "stop_pct": round(100 * st["stop"] / st["n"], 1),
                     "ev_net_pct": round(ev, 3),
                     "ev_lift_pct": round(ev - base_ev, 3) if base_ev is not None else None,
                     "avg_mfe_pct": round(st["mfe_sum"] / st["n"], 2),
                     "avg_mae_pct": round(st["mae_sum"] / st["n"], 2)})
    rows.sort(key=lambda r: -r["ev_net_pct"])
    return {"base_hit_pct": round(base_hit, 2) if base_hit is not None else None,
            "base_ev_net_pct": round(base_ev, 3) if base_ev is not None else None,
            "bars": base["n"], "rules": rows}


def combo_summary(combos, combo_stats):
    rows = []
    for j, combo in enumerate(combos):
        st = combo_stats[j]
        if st["n"] < 15:
            continue
        rows.append({"tags": [rule_tag(r) for r in combo], "n": st["n"],
                     "hit_pct": round(100 * st["hit"] / st["n"], 1),
                     "stop_pct": round(100 * st["stop"] / st["n"], 1),
                     "ev_net_pct": round(st["net_sum"] / st["n"], 3)})
    rows.sort(key=lambda r: -r["ev_net_pct"])
    return rows


def cmd_early():
    end_ms = window_hours(24)[1]
    train_end = end_ms - 24 * 3_600_000
    train_start = train_end - 144 * 3_600_000
    symbols = universe(top_n=50)
    rules_all = json.load(open(STATE / "oos_rules_train.json", encoding="utf-8"))
    early_rules = [r for r in rules_all if set(r["group_prefixes"]) <= EARLY_GROUPS_OK]
    print(f"[early] train rules {len(rules_all)} -> early-entry eligible {len(early_rules)}", flush=True)

    # pass 1: single-rule scan on train to pick top-6 by EV
    stats_tr, base_tr, _ = scan(symbols, train_start, train_end, early_rules)
    train_summary = summarize(stats_tr, base_tr)
    print(f"[early] train bars={base_tr['n']} base_hit={train_summary['base_hit_pct']}% "
          f"base_ev={train_summary['base_ev_net_pct']}%", flush=True)
    for r in train_summary["rules"][:10]:
        print(f"  TR {r['tag']:<40} n={r['n']:<5} hit={r['hit_pct']}% ev={r['ev_net_pct']}% "
              f"lift={r['ev_lift_pct']} mfe={r['avg_mfe_pct']}", flush=True)

    # pass 2: combos of top-6 early rules by train EV, scanned on train then test
    top = [r["tag"] for r in train_summary["rules"][:6]]
    tag_map = {rule_tag(r): r for r in early_rules}
    sel = [tag_map[t] for t in top if t in tag_map]
    combos = [list(c) for k in (2, 3) for c in combinations(sel, k)]
    _, _, combo_stats_tr = scan(symbols, train_start, train_end, early_rules, combos)
    train_combo_rows = combo_summary(combos, combo_stats_tr)
    stats_te, base_te, combo_stats_te = scan(symbols, train_end, end_ms, early_rules, combos)
    test_combo_rows = combo_summary(combos, combo_stats_te)
    test_summary = summarize(stats_te, base_te)
    print(f"[early] test bars={base_te['n']} base_hit={test_summary['base_hit_pct']}% "
          f"base_ev={test_summary['base_ev_net_pct']}%", flush=True)
    for r in test_summary["rules"][:10]:
        print(f"  TE {r['tag']:<40} n={r['n']:<5} hit={r['hit_pct']}% ev={r['ev_net_pct']}% "
              f"lift={r['ev_lift_pct']} mfe={r['avg_mfe_pct']}", flush=True)
    print("[early] top combos on test:", flush=True)
    for row in test_combo_rows[:8]:
        print(f"  n={row['n']:<5} hit={row['hit_pct']}% ev={row['ev_net_pct']}%  AND {' AND '.join(row['tags'])}", flush=True)

    out = {"type": "pump24_early_entry_v1",
           "generated_at": datetime.now(TZ).isoformat(),
           "exec": {"entry": "decision-bar OPEN", "groups": sorted(EARLY_GROUPS_OK),
                    "target_net_pct": NET_TARGET_PCT, "stop_pct": STOP_PCT,
                    "round_trip_cost_pct": ROUND_TRIP_COST_PCT, "race_bars": 3},
           "train": train_summary, "test": test_summary,
           "train_combos": train_combo_rows, "test_combos": test_combo_rows}
    (STATE / "early_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open("../../../pump24_early_raporu.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[early done]", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "early"
    if cmd == "early":
        cmd_early()
    else:
        print(__doc__)
