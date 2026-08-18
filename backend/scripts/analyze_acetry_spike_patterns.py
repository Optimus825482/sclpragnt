"""Analyze ACETRY spike events by single timeframe and MTF combinations."""
import json
import math
import statistics
from pathlib import Path


INPUT = Path(__file__).resolve().parents[1] / "acetry-7d-mtf-spike-research.json"
OUTPUT = INPUT.with_name("acetry-7d-mtf-pattern-analysis.json")
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
FIELDS = ("adx", "di_gap", "ema20_slope_3_pct", "atr_pct", "volume_ratio_20", "bb_position", "bb_width_pct", "rsi_14", "mfi_14")


def vals(rows, path):
    out = []
    for row in rows:
        current = row
        for part in path.split("."):
            current = current.get(part) if isinstance(current, dict) else None
        if isinstance(current, (int, float)) and math.isfinite(float(current)):
            out.append(float(current))
    return out


def categorical_vals(rows, path):
    out = []
    for row in rows:
        current = row
        for part in path.split("."):
            current = current.get(part) if isinstance(current, dict) else None
        if isinstance(current, str):
            out.append(current)
    return out


def median(values):
    return round(statistics.median(values), 6) if values else None


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * p)))], 6)


def rank_biserial(a, b):
    """P(|A>B|)-P(|B>A|), positive means A tends higher than B."""
    pairs = [(x, y) for x in a for y in b]
    if not pairs:
        return None
    greater = sum(x > y for x, y in pairs)
    lower = sum(x < y for x, y in pairs)
    return round((greater - lower) / len(pairs), 6)


def summarize_feature(events, controls, path):
    event_values = vals(events, path)
    control_values = vals(controls, path)
    return {"events_n": len(event_values), "controls_n": len(control_values),
            "event_median": median(event_values), "control_median": median(control_values),
            "delta": round(median(event_values) - median(control_values), 6) if event_values and control_values else None,
            "rank_biserial": rank_biserial(event_values, control_values)}


def spearman(x, y):
    if len(x) != len(y) or len(x) < 3:
        return None
    def rank(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        index = 0
        while index < len(order):
            end = index
            while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
                end += 1
            average = (index + end) / 2 + 1
            for position in order[index:end + 1]:
                ranks[position] = average
            index = end + 1
        return ranks
    rx, ry = rank(x), rank(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    numerator = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denominator = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(numerator / denominator, 6) if denominator else None


def outcome_summary(rows):
    returns = vals(rows, "onset_to_peak_pct")
    durations = vals(rows, "onset_to_peak_minutes")
    return {"n": len(rows), "return_median_pct": median(returns), "return_p75_pct": percentile(returns, .75),
            "duration_median_min": median(durations), "duration_p75_min": percentile(durations, .75)}


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    events, controls = data["events"], data["controls"]
    single = {}
    for tf in TIMEFRAMES:
        paths = {"alignment": f"features.timeframes.{tf}.alignment"}
        paths.update({field: f"features.timeframes.{tf}.{field}" for field in FIELDS})
        features = {name: summarize_feature(events, controls, path) for name, path in paths.items() if name != "alignment"}
        event_align = categorical_vals(events, paths["alignment"])
        control_align = categorical_vals(controls, paths["alignment"])
        single[tf] = {"event_outcome": outcome_summary(events), "alignment_event_counts": {key: event_align.count(key) for key in ("bullish", "mixed", "bearish")},
                      "alignment_control_counts": {key: control_align.count(key) for key in ("bullish", "mixed", "bearish")}, "features": features,
                      "strongest_separators": sorted(((abs(v["rank_biserial"] or 0), name, v) for name, v in features.items()), reverse=True)[:5],
                      "return_correlations": {field: spearman(vals(events, f"features.timeframes.{tf}.{field}"), vals(events, "onset_to_peak_pct")) for field in FIELDS}}

    mtf = {}
    for key, predicate in {
        "bullish_count_ge_3": lambda r: r["features"]["mtf_bullish_count"] >= 3,
        "bullish_count_le_1": lambda r: r["features"]["mtf_bullish_count"] <= 1,
        "alignment_score_ge_1": lambda r: r["features"]["mtf_alignment_score"] >= 1,
        "alignment_score_le_-2": lambda r: r["features"]["mtf_alignment_score"] <= -2,
        "h1_h4_both_bullish": lambda r: r["features"]["timeframes"]["1h"]["alignment"] == "bullish" and r["features"]["timeframes"]["4h"]["alignment"] == "bullish",
        "h1_or_h4_bullish": lambda r: r["features"]["timeframes"]["1h"]["alignment"] == "bullish" or r["features"]["timeframes"]["4h"]["alignment"] == "bullish",
        "lower_tf_oversold_higher_tf_bullish": lambda r: r["features"]["timeframes"]["1m"]["rsi_14"] < 40 and r["features"]["timeframes"]["1h"]["alignment"] == "bullish",
    }.items():
        selected = [r for r in events if predicate(r)]
        control_selected = [r for r in controls if predicate(r)]
        mtf[key] = {"events": outcome_summary(selected), "controls_n": len(control_selected),
                    "event_share_pct": round(len(selected) / len(events) * 100, 2),
                    "control_share_pct": round(len(control_selected) / len(controls) * 100, 2)}
    mtf["bullish_count_distribution"] = {str(i): outcome_summary([r for r in events if r["features"]["mtf_bullish_count"] == i]) for i in range(6)}
    mtf["alignment_score_distribution"] = {str(i): outcome_summary([r for r in events if r["features"]["mtf_alignment_score"] == i]) for i in range(-5, 6)}

    output = {"source": str(INPUT), "event_count": len(events), "control_count": len(controls), "single_timeframe": single, "mtf_patterns": mtf,
              "interpretation_guardrails": ["Tek sembol ve 7 günlük örneklem; sonuçlar keşif amaçlıdır.", "Kontrol sınıfı sonraki 60 dakikada %0.5'in altında kalan dönemlerden alınmıştır.", "Aynı olaylar zaman dilimleri arasında tekrar kullanıldığı için tekil bağımsız örnek sayısı 87'dir.", "Spread, orderbook, likidite ve slippage geçmişi bu veri setinde yoktur."]}
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
