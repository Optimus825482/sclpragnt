"""Pattern mining: group-based threshold rules with baseline-lift backtest.

Rules look like "rsi_14 < 40 in ≥70% of event snapshots" (user's example):
for each numeric field × group × direction we find the most selective
threshold that still fires in ≥ ``min_frac`` of events, then rank by frac.
The baseline scanner converts each rule into a causal tag at every bar of the
24h window and measures forward-M5 lift vs. the all-bar baseline.
"""

import math

RULE_FIELDS = [
    "rsi_14", "crsi", "cmo_9", "stoch_k", "stoch_d", "stochrsi_k", "stochrsi_d",
    "cci_20", "williams_14", "awesome_pct", "mfi_14", "tsi", "trix_15",
    "macd_hist_pct", "macd_line_pct", "macd_signal_pct",
    "ema_gap_pct", "adx_14", "di_gap",
    "atr_pct", "bb_pos", "bb_width", "chop_14", "vwap_dist_pct",
    "vol_ratio_20", "vol_osc", "obv_slope_norm", "cmf_20",
    "vortex_plus", "vortex_minus",
]

# field -> (lt thresholds, gt thresholds), scale-appropriate
FIELD_THRESHOLDS = {
    "rsi_14": ([20, 30, 40, 50], [50, 60, 70, 80]),
    "crsi": ([20, 30, 40, 50], [50, 60, 70, 80]),
    "cmo_9": ([-40, -20, 0, 20], [20, 40, 60, 80]),
    "stoch_k": ([20, 40, 60], [60, 80, 90]),
    "stoch_d": ([20, 40, 60], [60, 80, 90]),
    "stochrsi_k": ([10, 30, 50], [50, 70, 90]),
    "stochrsi_d": ([10, 30, 50], [50, 70, 90]),
    "cci_20": ([-150, -100, 0, 100], [0, 100, 150, 200]),
    "williams_14": ([-80, -60, -40], [-40, -20, -10]),
    "mfi_14": ([20, 30, 40, 50], [50, 60, 70, 80]),
    "tsi": ([-20, -10, 0, 10], [10, 20, 30]),
    "trix_15": ([-0.5, -0.2, 0, 0.2], [0, 0.2, 0.5]),
    "macd_hist": ([-0.01, -0.002, 0, 0.002], [0, 0.002, 0.01]),
    "ema_gap_pct": ([-2, -1, 0, 1], [0, 1, 2, 4]),
    "adx_14": ([10, 20, 30], [20, 30, 40, 50]),
    "di_gap": ([-10, 0, 10], [0, 10, 20, 30]),
    "atr_pct": ([0.3, 0.6, 1.0, 1.5, 2.5], [0.6, 1.0, 1.5, 2.5]),
    "bb_pos": ([0.0, 0.2, 0.4, 0.5], [0.5, 0.6, 0.8, 1.0]),
    "bb_width": ([0.01, 0.02, 0.04, 0.06], [0.02, 0.04, 0.06]),
    "awesome_pct": ([-1.0, -0.5, -0.2, 0], [0, 0.2, 0.5, 1.0]),
    "macd_hist_pct": ([-0.3, -0.1, 0, 0.05], [0, 0.05, 0.1, 0.3]),
    "macd_line_pct": ([-1.0, -0.5, -0.2, 0], [0, 0.2, 0.5, 1.0]),
    "macd_signal_pct": ([-1.0, -0.5, -0.2, 0], [0, 0.2, 0.5, 1.0]),
    "obv_slope_norm": ([-2, -1, 0, 1], [0, 1, 2, 4]),
    "chop_14": ([30, 40, 50, 60], [40, 50, 60, 70]),
    "vwap_dist_pct": ([-2, -1, 0, 0.5], [0, 0.5, 1, 2]),
    "vol_ratio_20": ([0.5, 0.8, 1.0], [1.2, 1.5, 2, 3, 5]),
    "vol_osc": ([-30, 0, 20], [0, 20, 50, 100]),
    "obv_slope_5": ([-0.05, -0.02, 0, 0.02], [0, 0.02, 0.05]),
    "cmf_20": ([-0.2, -0.1, 0, 0.1], [0, 0.1, 0.2]),
    "vortex_plus": ([0.8, 1.0, 1.2], [1.0, 1.2, 1.4]),
    "vortex_minus": ([0.8, 1.0, 1.2], [1.0, 1.2, 1.4]),
}
GROUP_SETS = [
    ("m5_g0", ["m5_g0"]),
    ("m5_g1", ["m5_g1"]),
    ("m5_g2", ["m5_g2"]),
    ("m5_g1_g2", ["m5_g1", "m5_g2"]),
    ("m1_g0", ["m1_g0"]),
    ("m1_g1", ["m1_g1"]),
    ("m1_g2", ["m1_g2"]),
    ("m1_all10", [f"m1_g{k}" for k in range(10)]),
]


def _num(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def group_stats(event_snapshots, field, prefixes, direction, thresholds):
    stats = []
    for th in thresholds:
        hits = valid = 0
        for ev in event_snapshots:
            values = [g.get(field) for name, g in ev.get("groups", {}).items()
                      if name in prefixes and _num(g.get(field))]
            if not values:
                continue
            valid += 1
            ok = (any(v < th for v in values) if direction == "lt"
                  else any(v > th for v in values))
            hits += 1 if ok else 0
        if valid:
            key = prefixes[0] if len(prefixes) == 1 else "+".join(prefixes)
            stats.append({"field": field, "group_key": key, "group_prefixes": list(prefixes),
                          "direction": direction, "threshold": th,
                          "frac": round(hits / valid, 3), "n": valid, "hits": hits})
    return stats


def mine_patterns(event_snapshots, min_frac=0.60, min_n=8, max_rules=400):
    """Most-selective threshold per (field, group, direction) with frac ≥ min_frac."""
    best = {}
    for field in RULE_FIELDS:
        lt_ts, gt_ts = FIELD_THRESHOLDS.get(field, ([10, 20, 30, 40, 50], [50, 60, 70, 80, 90]))
        for name, prefixes in GROUP_SETS:
            for direction, thresholds in (("lt", lt_ts), ("gt", gt_ts)):
                for s in group_stats(event_snapshots, field, prefixes, direction, thresholds):
                    if s["n"] < min_n or s["frac"] < min_frac:
                        continue
                    key = (s["field"], s["group_key"], s["direction"])
                    prev = best.get(key)
                    if prev is None:
                        best[key] = s
                    elif s["direction"] == "lt" and s["threshold"] < prev["threshold"]:
                        # tighter threshold only if frac stays ≥ min_frac (already guaranteed)
                        best[key] = s
                    elif s["direction"] == "gt" and s["threshold"] > prev["threshold"]:
                        best[key] = s
    return sorted(best.values(), key=lambda s: (-s["frac"], s["field"], s["group_key"]))[:max_rules]


def snapshot_hits(groups, rule):
    """Does ``rule`` hit in one event's groups dict (OR over the group's bars)?"""
    values = [g.get(rule["field"]) for name, g in groups.items()
              if name in rule["group_prefixes"] and _num(g.get(rule["field"]))]
    if not values:
        return False
    return (any(v < rule["threshold"] for v in values) if rule["direction"] == "lt"
            else any(v > rule["threshold"] for v in values))


def rule_tag(rule):
    short = rule["group_key"].replace("m5_g", "m5g").replace("m1_g", "m1g").replace("+", "_")
    return f"{short}_{rule['field']}_{rule['direction']}{rule['threshold']}"


def tag_frame_tags(frame, idx, rules, group_prefix_map):
    """Tags for scanning: evaluate rules on a *pseudo-groups* dict built from frames.

    group_prefix_map: {"m5_g0": (m5_frame, idx_m5), "m1_g0": (m1_frame, idx_m1), ...}
    """
    groups = {name: {k: frame[idx] for k, frame in [pair]}
              for name, pair in group_prefix_map.items()}
    return [rule_tag(rule) for rule in rules if snapshot_hits(groups, rule)]
