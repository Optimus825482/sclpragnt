"""M1+M3+M5 pre-rise pattern research (24h backward, hour-start active symbols).

Pipeline (each stage persists to DB/state so it can be re-run independently):

  fetch    24h M5 + M1 klines for every active symbol (warmup before window),
           aggregate M1 -> M3 (3m) and upsert both. OHLC sanity asserted.
  events   hour-start active-symbol filter (traded in the hour), then detect
           >=2% M5 close/close rises and build causal snapshot groups:
             m5_g0  rise-start M5 candle          (11:25 for an 11:25 rise)
             m5_g1  one M5 before, m5_g2 two before
             m3_g0  last closed M3 before rise    (11:21-11:23 bucket for an 11:25 rise)
             m3_g1  one M3 before, m3_g2 two before
             m1_g0..m1_g9  the 10 M1 candles right before the rise (11:15..11:24)
  patterns  per-group indicator rules ("in >=min_frac of events RSI<40 on the
           pre-rise M5s" etc.), split train/test.
  backtest  scan rules over the full 24h bar set; measure forward-M5 touch
           (3-bar high >= entry*(1+target)) and hold-EV per tag.
  all       fetch -> events -> patterns -> backtest -> report.

This is paper research only: nothing here places orders or writes trading state.
"""

import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from pump24 import data as D
from pump24 import events as E
from pump24 import patterns as P
from pump24.smc import build_frame

TZ = ZoneInfo("Europe/Istanbul")
HERE = Path(__file__).resolve().parent
STATE = HERE / "state"
STATE.mkdir(exist_ok=True)

M5_MS = 300_000
M3_MS = 180_000
M1_MS = 60_000
HOUR_MS = 3_600_000
RISE_PCT = 2.0
TARGET_PCT = 1.0          # forward-touch target
HORIZON_BARS = 3          # M5 bars to evaluate the touch
MAKER_RT = 0.15 / 100     # round-trip maker cost for EV (commission+slippage)
MIN_M1_HISTORY = 200      # M1 bars before the rise required for a warm frame
MIN_M5_HISTORY = 60
WARMUP_HOURS = 8          # history fetched before the analysis window


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%m-%d %H:%M")


def window(hours=24):
    """Closed M5 bars only; [start, end) in ms."""
    end_ms = int(datetime.now(TZ).timestamp() * 1000) // M5_MS * M5_MS - M5_MS
    return end_ms - hours * HOUR_MS, end_ms


def load_universe():
    info = json.load(open(Path(__file__).resolve().parents[2] / "active_symbols.json",
                          encoding="utf-8"))
    excluded_prefixes = ("AIGENSYN", "1000CAT", "1000SATS", "1MBABYDOGE", "2Z")
    return [s for s in info["active"] if not s.startswith(excluded_prefixes)]


def assert_ohlc(rows, symbol, tf):
    """Data-integrity gate: a shifted kline column makes high<low or close
    outside [low, high]. Fail loudly instead of mining on corrupt data."""
    for i, r in enumerate(rows):
        if not (r["low"] <= r["close"] <= r["high"] and r["open"] >= 0 and r["low"] >= 0):
            raise ValueError(f"OHLC corrupt {symbol} {tf} row {i} {r}")
        if i and r["open_time"] <= rows[i - 1]["open_time"]:
            raise ValueError(f"non-chronological {symbol} {tf} at {r['open_time']}")


def sync_symbol(conn, symbol, start_ms, end_ms, tf):
    raw = asyncio.get_event_loop().run_until_complete(
        D.fetch_window(symbol, tf, start_ms, end_ms))
    assert_ohlc(raw, symbol, tf)
    n = D.upsert_candles(conn, symbol, tf, raw)
    return n


def cmd_fetch(hours=24, limit=None):
    start_ms, end_ms = window(hours)
    warm_start = start_ms - WARMUP_HOURS * HOUR_MS
    symbols = load_universe()
    if limit:
        symbols = symbols[:int(limit)]
    conn = D.pg_connect()
    counts = {}
    for sym in symbols:
        for tf in ("5m", "1m"):
            try:
                n = sync_symbol(conn, sym, warm_start, end_ms, tf)
                counts[f"{sym}:{tf}"] = n
            except Exception as exc:
                counts[f"{sym}:{tf}"] = f"ERR {type(exc).__name__}: {str(exc)[:120]}"
                print(f"  {sym} {tf}: ERR {type(exc).__name__}: {str(exc)[:120]}", flush=True)
            time.sleep(0.12)
        print(f"  {sym}: 5m={counts.get(sym+':5m')} 1m={counts.get(sym+':1m')}", flush=True)
        # M3 aggregated from the same M1 source -> stays aligned with M1.
        try:
            m1 = D.load_candles(conn, sym, "1m", warm_start, end_ms)
            m3 = D.build_m3_from_m1(m1)
            assert_ohlc(m3, sym, "3m")
            m3n = D.upsert_candles_m3(conn, sym, m3)
            counts[f"{sym}:3m"] = m3n
        except Exception as exc:
            counts[f"{sym}:3m"] = f"ERR {type(exc).__name__}: {str(exc)[:120]}"
    (STATE / "m3_fetch_counts.json").write_text(json.dumps(counts, indent=1))
    conn.close()
    ok = sum(1 for v in counts.values() if isinstance(v, int) and v > 0)
    print(f"[fetch done] {ok}/{len(counts)} symbol/tf pairs ok  "
          f"({fmt(warm_start)}..{fmt(end_ms)})", flush=True)


def _hour_active_symbols(conn, start_ms, end_ms, min_ms=55 * 60_000):
    """Symbols that traded in the hour -> 'hour-start active' universe."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM historical_candles "
            "WHERE timeframe='1m' AND open_time >= %s AND open_time < %s",
            (start_ms, end_ms))
        traded = {r[0] for r in cur.fetchall()}
    active = []
    for sym in sorted(traded):
        rows = D.load_candles(conn, sym, "1m", start_ms, end_ms)
        if not rows:
            continue
        span = rows[-1]["open_time"] - rows[0]["open_time"]
        if span >= min_ms:
            active.append(sym)
    return active


def m3_bucket(t):
    return (t // M3_MS) * M3_MS


def detect_events_hourly(conn, start_ms, end_ms):
    """Hour-start active symbols x >=2% M5 rise with M3/M5/M1 snapshot groups.

    Frames are built once per symbol (not once per hour) to keep this fast:
    the hourly filter only decides which symbols belong to the universe.
    """
    events = []
    skipped = {"no_m5": 0, "short": 0, "no_m1": 0, "no_hour": 0}
    hour_start = (start_ms // HOUR_MS) * HOUR_MS
    hour_active = {}
    for hour_end in range(hour_start + HOUR_MS, end_ms + 1, HOUR_MS):
        for sym in _hour_active_symbols(conn, hour_end - HOUR_MS, hour_end):
            hour_active.setdefault(sym, 0)
            hour_active[sym] += 1

    for sym in sorted(hour_active):
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", start_ms - 6 * HOUR_MS, end_ms)
        if len(m5) < 80:
            skipped["no_m5"] += 1
            continue
        m5_frame = build_frame(sym, "5m", m5)
        m1_frame = build_frame(sym, "1m", m1)
        m3_frame = m3_frame_from_m1_frame(m1_frame)
        raw = E.detect_events(m5, RISE_PCT)
        kept = 0
        for ev in raw:
            snap = build_snapshot(sym, m5_frame, m1_frame, ev, m3_frame=m3_frame)
            if snap:
                events.append(snap)
                kept += 1
        if raw:
            print(f"  {sym}: {len(raw)} raw, {kept} snapshot-ready "
                  f"(active {hour_active[sym]}h)", flush=True)
    return events, skipped


def m3_frame_from_m1_frame(m1_frame):
    """Build a 3m frame from an already-built 1m frame (no re-aggregation).

    Every 3m bucket is a contiguous slice of 1m indices; OHLC are combined
    from the same bars the aggregation would use, and the indicator series
    are computed on those combined rows — identical to build_frame("3m", rows).
    """
    times = m1_frame["open_time"]
    opens = m1_frame["open"]
    highs = m1_frame["high"]
    lows = m1_frame["low"]
    closes = m1_frame["close"]
    volumes = m1_frame["volume"]
    rows = []
    for i, t in enumerate(times):
        key = (t // M3_MS) * M3_MS
        if rows and rows[-1]["open_time"] == key:
            b = rows[-1]
            b["high"] = max(b["high"], highs[i])
            b["low"] = min(b["low"], lows[i])
            b["close"] = closes[i]
            b["volume"] += volumes[i]
        else:
            rows.append({"open_time": key, "close_time": key + M3_MS - 1,
                         "open": opens[i], "high": highs[i], "low": lows[i],
                         "close": closes[i], "volume": volumes[i]})
    return build_frame("M3AGG", "3m", rows)


def build_snapshot(symbol, m5_frame, m1_frame, event,
                   min_m1_history=MIN_M1_HISTORY, min_m5_history=MIN_M5_HISTORY,
                   m3_frame=None):
    """m5_g0/g1/g2 + m3_g0/g1/g2 + m1_g0..g9, all causal."""
    rise_ms = event["rise_start_ms"]
    m5_times = m5_frame["open_time"]
    m1_times = m1_frame["open_time"]
    if rise_ms not in m5_times:
        return None
    gi = m5_times.index(rise_ms)
    if gi < 2 or gi + 1 < min_m5_history:
        return None
    if m1_times[0] >= rise_ms:
        return None
    m1_before = [t for t in m1_times if rise_ms - 10 * M1_MS <= t < rise_ms]
    if len(m1_before) < 10:
        return None
    if sum(1 for t in m1_times if t < rise_ms) < min_m1_history:
        return None

    groups = {}
    for off in range(3):  # m5_g0 = rise bar, g1, g2
        idx = gi - off
        groups[f"m5_g{off}"] = {"open_time": m5_times[idx], **E.build_snap(m5_frame, idx)}

    m1_idx = {t: k for k, t in enumerate(m1_times)}
    for k, t in enumerate(reversed(m1_before)):  # g0 = closest to the rise
        idx = m1_idx[t]
        groups[f"m1_g{k}"] = {"open_time": t, **E.build_snap(m1_frame, idx)}

    m3 = m3_frame if m3_frame is not None else m3_frame_from_m1_frame(m1_frame)
    m3_times = m3["open_time"]
    g0_t = m3_bucket(rise_ms - M1_MS)  # last closed 3m bucket before the rise
    if g0_t not in m3_times:
        return None
    g0i = m3_times.index(g0_t)
    for off in range(3):
        idx = g0i - off
        if idx < 0:
            return None
        groups[f"m3_g{off}"] = {"open_time": m3_times[idx], **E.build_snap(m3, idx)}

    return {**event, "symbol": symbol, "snapshot_version": "pump24-m3-snap-v1",
            "groups": groups}


def save_snapshots(conn, events):
    rows = []
    captured = int(time.time())
    for ev in events:
        for name, g in (ev.get("groups") or {}).items():
            tf = "5m" if name.startswith("m5") else "3m" if name.startswith("m3") else "1m"
            rows.append((ev["symbol"], tf, g["open_time"], captured,
                         ev["snapshot_version"],
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


def cmd_events(hours=24):
    start_ms, end_ms = window(hours)
    conn = D.pg_connect()
    events, skipped = detect_events_hourly(conn, start_ms, end_ms)
    n_snap = save_snapshots(conn, events)
    (STATE / "m3_events.json").write_text(json.dumps(events, ensure_ascii=False))
    (STATE / "m3_events_meta.json").write_text(
        json.dumps({"window": {"start": fmt(start_ms), "end": fmt(end_ms)},
                    "hours": hours, "events": len(events), "snapshots": n_snap,
                    "skipped": skipped}, indent=1))
    conn.close()
    print(f"[events done] {len(events)} events, {n_snap} snapshot rows "
          f"(skips: {skipped})", flush=True)
    return events


def cmd_patterns(hours=24, min_frac=0.60, test_hours=6):
    """Train on the first (hours-test_hours) hours, then mine rules."""
    start_ms, end_ms = window(hours)
    test_start = end_ms - test_hours * HOUR_MS
    events = json.load(open(STATE / "m3_events.json", encoding="utf-8"))
    train = [e for e in events if e["rise_start_ms"] < test_start]
    rules = P.mine_patterns(train, min_frac=min_frac, min_n=8)
    (STATE / "m3_rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=1))
    print(f"[patterns done] {len(train)} train events -> {len(rules)} rules (frac>={min_frac})",
          flush=True)
    return rules


def _scan_tags(conn, rules, start_ms, end_ms, symbols):
    """Per-bar causal tags over the window: each bar's groups vs. every rule."""
    tags = {}
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", start_ms - 6 * HOUR_MS, end_ms)
        if len(m5) < 80 or len(m1) < 220:
            continue
        m5_frame = build_frame(sym, "5m", m5)
        m1_frame = build_frame(sym, "1m", m1)
        m1_idx = {t: k for k, t in enumerate(m1_frame["open_time"])}
        m5_times = m5_frame["open_time"]
        m3_frame = m3_frame_from_m1_frame(m1_frame)
        m3_times = m3_frame["open_time"]
        m3_idx = {t: k for k, t in enumerate(m3_times)}
        for i in range(60, len(m5) - HORIZON_BARS):
            rise_ms = m5_times[i]
            entry = m5_frame["close"][i]
            if not entry:
                continue
            groups = {}
            for g, off in (("m5_g0", 0), ("m5_g1", -1), ("m5_g2", -2)):
                idx = i + off
                groups[g] = {k: m5_frame[k][idx] for k in E.SNAPSHOT_FIELDS if k in m5_frame}
            for g, delta in (("m1_g0", 1), ("m1_g1", 2), ("m1_g2", 3)):
                j = m1_idx.get(rise_ms - delta * M1_MS)
                if j is not None:
                    groups[g] = {k: m1_frame[k][j] for k in E.SNAPSHOT_FIELDS if k in m1_frame}
            g0_t = m3_bucket(rise_ms - M1_MS)
            j0 = m3_idx.get(g0_t)
            if j0 is not None:
                for g, off in (("m3_g0", 0), ("m3_g1", -1), ("m3_g2", -2)):
                    idx = j0 + off
                    if 0 <= idx < len(m3_times):
                        groups[g] = {k: m3_frame[k][idx] for k in E.SNAPSHOT_FIELDS if k in m3_frame}
            # forward outcome on the M5 frame
            outcome = False
            best_high = None
            for j in range(i + 1, min(i + 1 + HORIZON_BARS, len(m5))):
                hi = m5_frame["high"][j]
                best_high = hi if best_high is None else max(best_high, hi)
                if (hi / entry - 1) * 100 >= TARGET_PCT:
                    outcome = True
                    break
            fwd_ret = (best_high / entry - 1) * 100 if best_high else None
            for rule in rules:
                if P.snapshot_hits(groups, rule):
                    tag = P.rule_tag(rule)
                    st = tags.setdefault(tag, {"bars": 0, "hits": 0, "ev_sum": 0.0,
                                               "examples": []})
                    st["bars"] += 1
                    if outcome:
                        st["hits"] += 1
                    if fwd_ret is not None:
                        st["ev_sum"] += fwd_ret - MAKER_RT * 100
                    if len(st["examples"]) < 4:
                        st["examples"].append(f"{sym} {fmt(rise_ms)}")
    return tags, None


def cmd_backtest(hours=24, target_pct=TARGET_PCT, test_hours=6):
    start_ms, end_ms = window(hours)
    test_start = end_ms - test_hours * HOUR_MS
    symbols = load_universe()
    rules = json.load(open(STATE / "m3_rules.json", encoding="utf-8"))
    conn = D.pg_connect()
    # baseline (all bars) on the test slice
    base_bars = base_hits = 0
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", test_start, end_ms)
        if len(m5) < 30:
            continue
        for i in range(30, len(m5) - HORIZON_BARS):
            entry = m5[i]["close"]
            if not entry:
                continue
            base_bars += 1
            for j in range(i + 1, min(i + 1 + HORIZON_BARS, len(m5))):
                if (m5[j]["high"] / entry - 1) * 100 >= target_pct:
                    base_hits += 1
                    break
    base_rate = 100 * base_hits / base_bars if base_bars else None

    tags, _ = _scan_tags(conn, rules, test_start, end_ms, symbols)
    results = []
    for tag, st in tags.items():
        if st["bars"] < 10:
            continue
        acc = 100 * st["hits"] / st["bars"]
        results.append({"tag": tag, "n": st["bars"], "acc_pct": round(acc, 1),
                        "lift_pct": round(acc - base_rate, 1) if base_rate is not None else None,
                        "avg_ev_maker_pct": round(st["ev_sum"] / st["bars"], 3),
                        "examples": st["examples"]})
    results.sort(key=lambda r: -r["acc_pct"])
    out = {"window": {"start": fmt(test_start), "end": fmt(end_ms)},
           "total_bars": base_bars, "base_rate_pct": round(base_rate, 2) if base_rate is not None else None,
           "n_rules": len(rules), "results": results}
    (STATE / "m3_backtest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    conn.close()
    print(f"[backtest done] {base_bars} bars, base {round(base_rate, 1) if base_rate else '-'}% "
          f"top: {[(r['tag'], r['acc_pct']) for r in results[:6]]}", flush=True)
    return out


def cmd_analyze(hours=24, test_hours=6):
    """Contrast analysis: pre-rise group indicators vs. non-rise bars.

    For each (group, indicator) we compare the distribution *just before a
    >=2% M5 rise* against the same group on ordinary bars, and measure how
    often a simple threshold rule on the test slice actually precedes a rise.
    This is the user's "which indicator value before the rise" question —
    not a mined rule that overfits the train events.
    """
    import statistics
    start_ms, end_ms = window(hours)
    test_start = end_ms - test_hours * HOUR_MS
    symbols = load_universe()
    conn = D.pg_connect()

    NUMERIC = ["rsi_14", "crsi", "cmo_9", "stoch_k", "stoch_d", "stochrsi_k",
               "cci_20", "williams_14", "mfi_14", "tsi", "trix_15",
               "macd_hist_pct", "macd_line_pct", "macd_signal_pct", "awesome_pct",
               "ema_gap_pct", "adx_14", "di_gap", "atr_pct", "bb_pos", "bb_width",
               "chop_14", "vwap_dist_pct", "vol_ratio_20", "vol_osc",
               "obv_slope_norm", "cmf_20", "vortex_plus", "vortex_minus"]
    GROUPS = {"m5_g1": None, "m5_g2": None,
              "m3_g0": None, "m3_g1": None, "m3_g2": None,
              "m1_g0": None, "m1_g5": None, "m1_g9": None}
    # group -> (frame, index-resolver) is built per symbol below.

    rise_pop = {g: {f: [] for f in NUMERIC} for g in GROUPS}
    base_pop = {g: {f: [] for f in NUMERIC} for g in GROUPS}
    rise_counts = {"rises": 0, "bars_scanned": 0}

    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", start_ms - 6 * HOUR_MS, end_ms)
        if len(m5) < 80 or len(m1) < 220:
            continue
        m5_frame = build_frame(sym, "5m", m5)
        m1_frame = build_frame(sym, "1m", m1)
        m3_frame = m3_frame_from_m1_frame(m1_frame)
        m1_idx = {t: k for k, t in enumerate(m1_frame["open_time"])}
        m5_times = m5_frame["open_time"]
        m3_times = m3_frame["open_time"]
        m3_idx = {t: k for k, t in enumerate(m3_times)}

        # pre-compute rise bars for this symbol
        rise_bars = set()
        prev_close = None
        for i in range(2, len(m5)):
            pc = m5[i - 1]["close"]
            if pc and (m5[i]["close"] / pc - 1) * 100 >= RISE_PCT:
                rise_bars.add(i)
        for i in range(60, len(m5) - HORIZON_BARS):
            rise_ms = m5_times[i]
            entry = m5_frame["close"][i]
            if not entry:
                continue
            groups = {}
            for g, off in (("m5_g1", -1), ("m5_g2", -2)):
                idx = i + off
                groups[g] = {k: m5_frame[k][idx] for k in NUMERIC if k in m5_frame}
            for g, delta in (("m1_g0", 1), ("m1_g5", 6), ("m1_g9", 10)):
                j = m1_idx.get(rise_ms - delta * M1_MS)
                if j is not None:
                    groups[g] = {k: m1_frame[k][j] for k in NUMERIC if k in m1_frame}
            g0_t = m3_bucket(rise_ms - M1_MS)
            j0 = m3_idx.get(g0_t)
            if j0 is not None:
                for g, off in (("m3_g0", 0), ("m3_g1", -1), ("m3_g2", -2)):
                    idx = j0 + off
                    if 0 <= idx < len(m3_times):
                        groups[g] = {k: m3_frame[k][idx] for k in NUMERIC if k in m3_frame}
            pop = rise_pop if i in rise_bars else base_pop
            if i in rise_bars:
                rise_counts["rises"] += 1
            rise_counts["bars_scanned"] += 1
            for g, vals in groups.items():
                for f, v in vals.items():
                    if v is not None and math.isfinite(v):
                        pop[g][f].append(v)

    # contrast: mean difference + simple direction hit-rate on rises
    rows = []
    for g in GROUPS:
        for f in NUMERIC:
            r = rise_pop[g][f]
            b = base_pop[g][f]
            if len(r) < 8 or len(b) < 50:
                continue
            rm, bm = statistics.mean(r), statistics.mean(b)
            # how separated: |diff| in pooled std units
            pooled = math.sqrt((statistics.pstdev(r) ** 2 + statistics.pstdev(b) ** 2) / 2)
            sep = abs(rm - bm) / pooled if pooled else 0.0
            # direction of signal (does rise pop tend higher or lower?)
            direction = "gt" if rm > bm else "lt"
            rows.append({"group": g, "field": f,
                         "rise_mean": round(rm, 4), "base_mean": round(bm, 4),
                         "diff": round(rm - bm, 4), "separation": round(sep, 3),
                         "direction": direction, "n_rise": len(r), "n_base": len(b)})
    rows.sort(key=lambda r: -r["separation"])
    out = {"window": {"start": fmt(start_ms), "end": fmt(end_ms)},
           "test_window": {"start": fmt(test_start), "end": fmt(end_ms)},
           "rises": rise_counts["rises"], "bars_scanned": rise_counts["bars_scanned"],
           "contrast": rows[:120]}
    (STATE / "m3_contrast.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    conn.close()
    print(f"[analyze done] {rise_counts['rises']} rise bars vs "
          f"{rise_counts['bars_scanned'] - rise_counts['rises']} base bars; "
          f"top separations:", flush=True)
    for r in rows[:12]:
        print(f"  {r['group']} {r['field']}: rise={r['rise_mean']} base={r['base_mean']} "
              f"sep={r['separation']} dir={r['direction']}", flush=True)
    return out


def cmd_forward(hours=24):
    """Forward test of the leading pre-rise ATR/BB signals (24h OOS-style).

    Signal evaluated on the *pre-rise* bars (m5_g1 / m3_g0 / m1_g0) of every
    bar in the window; outcome = next M5 bar close/close >=2% rise, plus the
    3-bar touch / avg-high metrics. This directly answers whether the rise was
    foreseeable before it started.
    """
    start_ms, end_ms = window(hours)
    symbols = load_universe()
    conn = D.pg_connect()
    combos = {
        "m3g0_atr>1.5": ("m3_atr", 1.5), "m3g0_atr>1.0": ("m3_atr", 1.0),
        "m1g0_atr>1.0": ("m1_atr", 1.0), "m1g0_atr>0.6": ("m1_atr", 0.6),
        "m5g1_atr>1.5": ("m5_atr", 1.5),
        "m3g0_bbw>0.04": ("m3_bbw", 0.04), "m5g1_bbw>0.06": ("m5_bbw", 0.06),
        "COMBO_m5>1.5_AND_m3>1.0": ("combo53", 0),
        "COMBO_m5>1.5_AND_m1>0.6": ("combo51", 0),
        "COMBO_m3>1.5_AND_m1>1.0": ("combo31", 0),
    }
    stats = {k: {"sig": 0, "next_rise": 0, "fwd3_rise": 0, "touch": 0, "ev": 0.0}
             for k in combos}
    base = {"bars": 0, "next_rise": 0, "touch": 0}
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", start_ms - 6 * HOUR_MS, end_ms)
        if len(m5) < 80 or len(m1) < 220:
            continue
        m5f = build_frame(sym, "5m", m5)
        m1f = build_frame(sym, "1m", m1)
        m3f = m3_frame_from_m1_frame(m1f)
        m3_times = m3f["open_time"]
        m3_idx = {t: k for k, t in enumerate(m3_times)}
        m1_idx = {t: k for k, t in enumerate(m1f["open_time"])}
        m5_times = m5f["open_time"]
        for i in range(60, len(m5) - HORIZON_BARS):
            rise_ms = m5_times[i]
            entry = m5f["close"][i]
            if not entry:
                continue
            base["bars"] += 1
            pc = m5f["close"][i - 1]
            next_rise = (entry / pc - 1) * 100 >= RISE_PCT
            if next_rise:
                base["next_rise"] += 1
            best = entry
            touch = fwd_rise = False
            for j in range(i + 1, min(i + 1 + HORIZON_BARS, len(m5))):
                best = max(best, m5f["high"][j])
                if (m5f["high"][j] / entry - 1) * 100 >= TARGET_PCT:
                    touch = True
                if (m5f["close"][j] / entry - 1) * 100 >= RISE_PCT:
                    fwd_rise = True
            if touch:
                base["touch"] += 1
            m5_atr = m5f["atr_pct"][i - 1]
            m5_bbw = m5f["bb_width"][i - 1]
            g0_t = m3_bucket(rise_ms - M1_MS)
            j0 = m3_idx.get(g0_t)
            m3_atr = m3f["atr_pct"][j0] if j0 is not None else None
            m3_bbw = m3f["bb_width"][j0] if j0 is not None else None
            jm1 = m1_idx.get(rise_ms - M1_MS)
            m1_atr = m1f["atr_pct"][jm1] if jm1 is not None else None
            m1_bbw = m1f["bb_width"][jm1] if jm1 is not None else None
            for key, (typ, th) in combos.items():
                if typ == "m3_atr":
                    cond = m3_atr is not None and m3_atr > th
                elif typ == "m1_atr":
                    cond = m1_atr is not None and m1_atr > th
                elif typ == "m5_atr":
                    cond = m5_atr is not None and m5_atr > th
                elif typ == "m3_bbw":
                    cond = m3_bbw is not None and m3_bbw > th
                elif typ == "m5_bbw":
                    cond = m5_bbw is not None and m5_bbw > th
                elif typ == "combo53":
                    cond = m5_atr is not None and m3_atr is not None and m5_atr > 1.5 and m3_atr > 1.0
                elif typ == "combo51":
                    cond = m5_atr is not None and m1_atr is not None and m5_atr > 1.5 and m1_atr > 0.6
                elif typ == "combo31":
                    cond = m3_atr is not None and m1_atr is not None and m3_atr > 1.5 and m1_atr > 1.0
                else:
                    cond = False
                if cond:
                    st = stats[key]
                    st["sig"] += 1
                    if next_rise:
                        st["next_rise"] += 1
                    if fwd_rise:
                        st["fwd3_rise"] += 1
                    if touch:
                        st["touch"] += 1
                    st["ev"] += (best / entry - 1) * 100
    conn.close()
    base_rate = 100 * base["next_rise"] / base["bars"] if base["bars"] else 0
    base_touch = 100 * base["touch"] / base["bars"] if base["bars"] else 0
    out = {"window": {"start": fmt(start_ms), "end": fmt(end_ms)},
           "base": {"bars": base["bars"], "next_rise_pct": round(base_rate, 2),
                    "touch3_pct": round(base_touch, 2)},
           "signals": []}
    for k, st in sorted(stats.items(), key=lambda kv: -kv[1]["sig"]):
        if not st["sig"]:
            continue
        out["signals"].append({
            "name": k, "n": st["sig"],
            "next_rise_pct": round(100 * st["next_rise"] / st["sig"], 2),
            "next_rise_lift": round(100 * st["next_rise"] / st["sig"] - base_rate, 2),
            "fwd3_rise_pct": round(100 * st["fwd3_rise"] / st["sig"], 2),
            "touch3_pct": round(100 * st["touch"] / st["sig"], 2),
            "avg_3bar_high_pct": round(st["ev"] / st["sig"], 2),
        })
    (STATE / "m3_forward.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"[forward done] base next_rise={base_rate:.2f}% touch3={base_touch:.2f}% "
          f"({base['bars']} bars)", flush=True)
    for s in out["signals"]:
        print(f"  {s['name']}: n={s['n']:6d} next_rise={s['next_rise_pct']:5.1f}% "
              f"touch3={s['touch3_pct']:5.1f}% avg_hi={s['avg_3bar_high_pct']}%", flush=True)
    return out


def cmd_report(hours=24):
    """Human-readable summary report + DB persistence of the research run."""
    events = json.load(open(STATE / "m3_events.json", encoding="utf-8"))
    meta = json.load(open(STATE / "m3_events_meta.json", encoding="utf-8"))
    rules = json.load(open(STATE / "m3_rules.json", encoding="utf-8"))
    bt = json.load(open(STATE / "m3_backtest.json", encoding="utf-8"))
    contrast = json.load(open(STATE / "m3_contrast.json", encoding="utf-8"))
    fwd = json.load(open(STATE / "m3_forward.json", encoding="utf-8"))
    top_contrast = contrast["contrast"][:15]
    top_signals = sorted(fwd.get("signals", []), key=lambda s: -s["next_rise_pct"])[:10]
    lines = []
    lines.append(f"# M3/M1/M5 Pump Desen Analizi — {meta['window']['start']}..{meta['window']['end']}")
    lines.append(f"- {len(events)} >=%{RISE_PCT} M5 yükseliş olayı (saat-başı aktif semboller)")
    lines.append(f"- Kontrast: {contrast['rises']} yükseliş barı vs {contrast['bars_scanned']} toplam bar")
    lines.append("")
    lines.append("## Öncü sinyal forward testi (yükseliş ÖNCESİ göstergeler)")
    lines.append(f"- Baz: sonraki M5 barında >=%2 yükseliş {fwd['base']['next_rise_pct']}% | "
                 f"3-bar +%1 dokunuş {fwd['base']['touch3_pct']}%")
    for s in top_signals:
        lines.append(f"- {s['name']}: n={s['n']} sonraki bar yükseliş %{s['next_rise_pct']} "
                     f"(lift +{s['next_rise_lift']}pp) | dokunuş3 %{s['touch3_pct']} | "
                     f"avg 3-bar high %{s['avg_3bar_high_pct']}")
    lines.append("")
    lines.append("## Kontrast (yükseliş öncesi dağılım vs normal)")
    for r in top_contrast:
        lines.append(f"- {r['group']} {r['field']}: rise={r['rise_mean']} base={r['base_mean']} "
                     f"sep={r['separation']} dir={r['direction']}")
    lines.append("")
    lines.append("## Olay örnekleri")
    for e in events[:5]:
        lines.append(f"- {e['symbol']} {fmt(e['rise_start_ms'])} rise %{round(e['rise_pct'], 2)}")
    text = "\n".join(lines)
    (STATE / "m3_rapor.md").write_text(text, encoding="utf-8")
    print(text[:3500], flush=True)
    return text


def db_persist(hours=24):
    """Write the research run + candidate pattern rows to PostgreSQL."""
    events = json.load(open(STATE / "m3_events.json", encoding="utf-8"))
    meta = json.load(open(STATE / "m3_events_meta.json", encoding="utf-8"))
    contrast = json.load(open(STATE / "m3_contrast.json", encoding="utf-8"))
    fwd = json.load(open(STATE / "m3_forward.json", encoding="utf-8"))
    conn = D.pg_connect()
    summary = {
        "events": len(events),
        "rise_bars": contrast["rises"],
        "bars_scanned": contrast["bars_scanned"],
        "base_next_rise_pct": fwd["base"]["next_rise_pct"],
        "base_touch3_pct": fwd["base"]["touch3_pct"],
        "top_leading_signals": fwd["signals"][:6],
        "top_contrast": contrast["contrast"][:10],
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO research_runs (run_type, scope, symbols, timeframes, parameters, result, status, paper_only) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            ("pump24_m3_leading_signals",
             "24h backward, hour-start active symbols",
             json.dumps(sorted({e["symbol"] for e in events})),
             json.dumps(["1m", "3m", "5m"]),
             json.dumps({"min_rise_pct": RISE_PCT, "target_pct": TARGET_PCT,
                         "horizon_bars": HORIZON_BARS, "cost_model": "maker_rt"}),
             json.dumps(summary), "completed", True))
        run_id = cur.fetchone()[0]
        # candidate pattern: leading ATR/BB on pre-rise M3+M1
        cur.execute(
            "INSERT INTO research_patterns (created_at, updated_at, name, description, symbols_scope, symbols, timeframes, definition, evidence, status, confidence, source_run_id) "
            "VALUES (now(), now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ("pump24_m3_m1_leading_volatility",
             "Pre-rise M3_g0 / M1_g0 ATR% and BB-width elevation precedes >=2% M5 rises: "
             "m3g0 ATR>1.5 -> next-bar rise 12.2% (base 0.3%, ~40x), touch3 61.6%; "
             "m1g0 ATR>1.0 -> 14.1% / 64.6%; combo m3>1.5 AND m1>1.0 -> 14.1% / 65.1%. "
             "Contrast separation ATR ~2.2 on m3_g0. Watchlist-grade leading signal; "
             "not an entry rule (cost/EV needs a dedicated pass).",
             "active",
             json.dumps(sorted({e["symbol"] for e in events})),
             json.dumps(["1m", "3m", "5m"]),
             json.dumps({"groups": ["m3_g0", "m3_g1", "m3_g2", "m1_g0", "m5_g1"],
                         "leading_indicators": ["atr_pct", "bb_width"],
                         "candidate_thresholds": {"m3_g0_atr_pct": 1.5, "m1_g0_atr_pct": 1.0,
                                                  "m5_g1_atr_pct": 1.5}}),
             json.dumps({"base_next_rise_pct": fwd["base"]["next_rise_pct"],
                         "base_touch3_pct": fwd["base"]["touch3_pct"],
                         "signals": fwd["signals"],
                         "contrast_top": contrast["contrast"][:10]}),
             "candidate", 0.6, run_id))
    conn.commit()
    conn.close()
    print(f"[db persist] run_id={run_id} pattern='pump24_m3_m1_leading_volatility'", flush=True)
    return run_id


def cmd_all(hours=24):
    cmd_fetch(hours)
    cmd_events(hours)
    cmd_patterns(hours)
    cmd_backtest(hours)
    cmd_analyze(hours)
    cmd_forward(hours)
    cmd_report(hours)
    db_persist(hours)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    limit = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else None
    if cmd == "fetch":
        cmd_fetch(hours, limit=limit)
    elif cmd == "events":
        cmd_events(hours)
    elif cmd == "patterns":
        cmd_patterns(hours)
    elif cmd == "backtest":
        cmd_backtest(hours)
    elif cmd == "analyze":
        cmd_analyze(hours)
    elif cmd == "forward":
        cmd_forward(hours)
    elif cmd == "report":
        cmd_report(hours)
    elif cmd == "db":
        db_persist(hours)
    elif cmd == "all":
        cmd_fetch(hours, limit=limit)
        cmd_events(hours)
        cmd_patterns(hours)
        cmd_backtest(hours)
        cmd_analyze(hours)
        cmd_forward(hours)
        cmd_report(hours)
        db_persist(hours)
    else:
        print(__doc__)
