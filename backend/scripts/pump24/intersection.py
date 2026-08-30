"""Intersection test: v2 filter AND pump-continuation signals.

At every M5 decision bar compute:
  - v2 pass (watchlist filter)
  - pump rules: m5g0_ema_gap_pct>2, m5g0_atr_pct>=1.0/1.5, m5g0_vwap_dist>2, m5g0_awesome_pct>1.0
Then measure intersection sets: counts, touch rates (3-bar MFE >= targets),
avg MFE, and a stopless-3bar EV under taker/maker costs. Also an entry race
with stop for the intersection, for completeness.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pump24 import data as D
from pump24.run import fmt, universe, window_hours
from pump24.smc import build_frame

TZ = ZoneInfo("Europe/Istanbul")
STATE = Path(__file__).resolve().parent / "state"

TOUCH_TARGETS = [0.95, 1.5, 2.0]
PUMP_RULES = {
    "p_ema_gap_gt2": lambda f, i: (f["ema_gap_pct"][i] or -99) > 2,
    "p_atr_ge1.5": lambda f, i: (f["atr_pct"][i] or -99) > 1.5,
    "p_atr_ge1.0": lambda f, i: (f["atr_pct"][i] or -99) > 1.0,
    "p_vwap_dist_gt2": lambda f, i: (f["vwap_dist_pct"][i] or -99) > 2,
    "p_awesome_gt1": lambda f, i: (f["awesome_pct"][i] or -99) > 1.0,
    "p_bb_width_gt6": lambda f, i: (f["bb_width"][i] or -99) > 0.06,
}
COSTS = {"taker": 0.35, "maker": 0.15}


def linreg_slope_pct(closes, period=20):
    out = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        y = np.asarray(closes[i - period + 1:i + 1], dtype=float)
        x = np.arange(period, dtype=float)
        slope = float(np.polyfit(x, y, 1)[0])
        out[i] = slope / y[-1] * 100 if y[-1] else None
    return out


def v2_pass(f, i, lr):
    atr, bbw, rsi, mfi, aroon = f["atr_pct"][i], f["bb_width"][i], f["rsi_14"][i], f["mfi_14"][i], f["aroon_up"][i]
    if None in (atr, bbw, rsi, mfi, lr, aroon):
        return False
    return (atr >= 0.3 and bbw >= 0.025 and (rsi >= 60 or rsi <= 35)
            and 10 <= mfi <= 90 and (lr >= 0.2 or aroon >= 50))


def scan(symbols, start_ms, end_ms):
    conn = D.pg_connect()
    rows = []
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        if len(m5) < 80:
            continue
        f5 = build_frame(sym, "5m", m5)
        f5["lr_slope_pct"] = linreg_slope_pct(f5["close"])
        times = f5["open_time"]
        for i in range(60, len(m5) - 7):
            lr = f5["lr_slope_pct"][i]
            entry = f5["close"][i]
            if not entry:
                continue
            flags = {"v2": v2_pass(f5, i, lr)}
            for name, fn in PUMP_RULES.items():
                flags[name] = fn(f5, i)
            mfe3 = max((f5["high"][j] / entry - 1) * 100 for j in range(i + 1, i + 4))
            ret3 = (f5["close"][i + 3] / entry - 1) * 100
            rows.append({"sym": sym, "t": times[i], "entry": entry, "mfe3": mfe3, "ret3": ret3, **flags})
    conn.close()
    return rows


def set_stats(rows, mask_fn, label):
    sub = [r for r in rows if mask_fn(r)]
    n = len(sub)
    if n == 0:
        return {"label": label, "n": 0}
    out = {"label": label, "n": n,
           "pass_rate_pct": round(100 * n / max(1, len(rows)), 2)}
    for tgt in TOUCH_TARGETS:
        out[f"touch_{tgt}_pct"] = round(100 * sum(1 for r in sub if r["mfe3"] >= tgt) / n, 1)
    out["avg_mfe3_pct"] = round(float(np.mean([r["mfe3"] for r in sub])), 3)
    out["avg_ret3_pct"] = round(float(np.mean([r["ret3"] for r in sub])), 3)
    out["median_mfe3_pct"] = round(float(np.median([r["mfe3"] for r in sub])), 3)
    out["p75_mfe3_pct"] = round(float(np.percentile([r["mfe3"] for r in sub], 75)), 2)
    for cname, cost in COSTS.items():
        out[f"ev_stopless3_{cname}_pct"] = round(out["avg_ret3_pct"] - cost, 3)
    return out


def main():
    end_ms = window_hours(24)[1]
    train_end = end_ms - 24 * 3_600_000
    train_start = train_end - 144 * 3_600_000
    symbols = universe(top_n=50)

    print("[ix] scanning train ...", flush=True)
    tr = scan(symbols, train_start, train_end)
    print(f"[ix] train rows={len(tr)}", flush=True)
    print("[ix] scanning test ...", flush=True)
    te = scan(symbols, train_end, end_ms)
    print(f"[ix] test rows={len(te)}", flush=True)

    sets = [
        ("all_bars", lambda r: True),
        ("v2_only", lambda r: r["v2"]),
        ("p_atr_ge1.5_only", lambda r: r["p_atr_ge1.5"]),
        ("p_ema_gap_gt2_only", lambda r: r["p_ema_gap_gt2"]),
        ("v2_AND_p_atr_ge1.5", lambda r: r["v2"] and r["p_atr_ge1.5"]),
        ("v2_AND_p_ema_gap_gt2", lambda r: r["v2"] and r["p_ema_gap_gt2"]),
        ("v2_AND_p_vwap_dist_gt2", lambda r: r["v2"] and r["p_vwap_dist_gt2"]),
        ("v2_AND_p_awesome_gt1", lambda r: r["v2"] and r["p_awesome_gt1"]),
        ("v2_AND_p_bb_width_gt6", lambda r: r["v2"] and r["p_bb_width_gt6"]),
        ("v2_AND_p_atr_ge1.0", lambda r: r["v2"] and r["p_atr_ge1.0"]),
        ("v2_AND_p_atr_ge1.5_OR_vwap2", lambda r: r["v2"] and (r["p_atr_ge1.5"] or r["p_vwap_dist_gt2"])),
        ("v2_AND_p_atr_ge1.5_AND_awesome_gt1", lambda r: r["v2"] and r["p_atr_ge1.5"] and r["p_awesome_gt1"]),
    ]
    report = {"type": "pump24_intersection_test", "generated_at": datetime.now(TZ).isoformat(),
              "windows": {"train_hours": 144, "test_hours": 24},
              "sets_train": [set_stats(tr, fn, lab) for lab, fn in sets],
              "sets_test": [set_stats(te, fn, lab) for lab, fn in sets]}
    (STATE / "intersection_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    json.dump(report, open("../../../pump24_kesisim_test.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for w in ("train", "test"):
        print(f"== {w.upper()} ==", flush=True)
        for s in report[f"sets_{w}"]:
            if s["n"] == 0:
                print(f"  {s['label']:<38} n=0", flush=True)
                continue
            print(f"  {s['label']:<38} n={s['n']:<6} touch95={s['touch_0.95_pct']}% touch1.5={s['touch_1.5_pct']}% "
                  f"medMFE={s['median_mfe3_pct']}% p75={s['p75_mfe3_pct']}% avgRet3={s['avg_ret3_pct']}% "
                  f"EV(0.15)={s['ev_stopless3_maker_pct']}%", flush=True)
    print("[ix done]", flush=True)


if __name__ == "__main__":
    main()
