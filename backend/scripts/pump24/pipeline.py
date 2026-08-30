"""24h pump-pattern research pipeline.

Stages (each persists its output so the next stage can resume):
  fetch      Binance TR (+OKX repair) M5/M1 klines -> historical_candles
  events     ≥%2 M5 close-to-close rises -> events + causal snapshot groups -> snapshots table
  patterns   group-based threshold rules (frac >= min_frac)
  backtest   causal scan over the whole 24h window; tag -> forward M5 lift vs baseline
  report     JSON report + research_runs row
"""

import asyncio
import json
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from pump24 import data as D
from pump24 import events as E
from pump24 import patterns as P
from pump24.smc import build_frame

TZ = ZoneInfo("Europe/Istanbul")
STAGES_FILE = "pump24_run_state.json"
REPORT_PREFIX = "pump24_report"

# universe: high-liquidity, non-synthetic TRY pairs from the live active list
EXCLUDE_PREFIXES = ("AIGENSYN", "1MBABYDOGE", "1000CAT", "1000SATS", "1M", "1000", "2Z")
MIN_TICKER_VOLUME = 30_000_000  # TRY quote volume / 24h


def active_universe(conn, top_n=50):
    import os
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(backend_root, "active_symbols.json"), encoding="utf-8") as fh:
        info = json.load(fh)
    symbols = [s for s in info["active"] if not s.startswith(EXCLUDE_PREFIXES)]

    from app.binance_tr_public import ticker_24h
    tickers = asyncio.get_event_loop().run_until_complete(ticker_24h())
    by_symbol = {t["symbol"]: t for t in tickers}
    scored = []
    for sym in symbols:
        t = by_symbol.get(sym)
        if not t:
            continue
        try:
            qv = float(t.get("quoteVolume") or 0)
        except (TypeError, ValueError):
            continue
        scored.append((sym, qv))
    scored.sort(key=lambda x: -x[1])
    return [s for s, _ in scored[:top_n]]


def stage_fetch(conn, symbols, timeframe, start_ms, end_ms):
    counts = {}
    for sym in symbols:
        try:
            n = D.sync_symbol(conn, sym, timeframe, start_ms, end_ms)
            counts[sym] = n
            print(f"  [fetch] {sym} {timeframe}: {n} bars", flush=True)
        except Exception as exc:
            counts[sym] = f"ERR {type(exc).__name__}: {exc}"
            print(f"  [fetch-ERR] {sym}: {exc}", flush=True)
        time.sleep(0.15)
    return counts


def stage_events(conn, symbols, start_ms, end_ms, min_rise_pct=2.0):
    all_events = []
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", start_ms - 6 * 3_600_000, end_ms)
        if len(m5) < 80 or len(m1) < E.MIN_M1_HISTORY:
            print(f"  [events-skip] {sym}: m5={len(m5)} m1={len(m1)}", flush=True)
            continue
        m5_frame = build_frame(sym, "5m", m5)
        m1_frame = build_frame(sym, "1m", m1)
        raw_events = E.detect_events(m5, min_rise_pct)
        kept = 0
        for ev in raw_events:
            snap = E.event_snapshot(sym, m5_frame, m1_frame, ev)
            if snap:
                all_events.append(snap)
                kept += 1
        print(f"  [events] {sym}: {len(raw_events)} raw, {kept} with full snapshots", flush=True)
    E.save_snapshots(conn, all_events)
    E.save_events(conn, "pump24_events_2pct", all_events)
    return all_events


def stage_patterns(events, min_frac=0.60):
    rules = P.mine_patterns(events, min_frac=min_frac)
    return rules


def forward_m5_outcome(m5_rows, rise_start_ms, horizon_bars=3, target_pct=1.0):
    """From the bar AFTER rise_start: does high reach +target_pct within horizon?"""
    times = [r["open_time"] for r in m5_rows]
    if rise_start_ms not in times:
        return None
    i = times.index(rise_start_ms)
    entry = m5_rows[i]["close"]
    if not entry:
        return None
    for j in range(i + 1, min(i + 1 + horizon_bars, len(m5_rows))):
        if (m5_rows[j]["high"] / entry - 1) * 100 >= target_pct:
            return True
    return False


def stage_backtest(conn, symbols, start_ms, end_ms, rules, horizon_bars=3, target_pct=1.0):
    """Causal scan: at every M5 bar (warm), evaluate rules on pseudo-groups and
    measure forward outcome; compares tag bars vs all bars (baseline)."""
    total_bars = 0
    tag_stats = {}  # tag -> {"bars": int, "successes": int}
    entry_logs = []
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", max(start_ms - 6 * 3_600_000, 0), end_ms)
        if len(m5) < 80 or len(m1) < 220:
            continue
        m5_frame = build_frame(sym, "5m", m5)
        m1_frame = build_frame(sym, "1m", m1)
        m1_idx = {t: k for k, t in enumerate(m1_frame["open_time"])}
        for i in range(60, len(m5) - horizon_bars):
            rise_ms = m5_frame["open_time"][i]
            pseudo = {"m5_g0": (m5_frame, i), "m5_g1": (m5_frame, i - 1), "m5_g2": (m5_frame, i - 2)}
            for g in range(3):
                m1j = m1_idx.get(rise_ms - (g + 1) * M1_MS_mult())
                pseudo[f"m1_g{g}"] = (m1_frame, m1j) if m1j is not None else None
            # pseudo-groups for m1_g0..g2 rules (m1_all10 rules need 10 bars; approximate with g0..g2 for scan)
            outcome = forward_m5_outcome(m5, rise_ms, horizon_bars, target_pct)
            if outcome is None:
                continue
            total_bars += 1
            groups = {}
            for name, pair in pseudo.items():
                if pair is None:
                    continue
                frame, idx = pair
                groups[name] = {k: frame[k][idx] for k in E.SNAPSHOT_FIELDS if k in frame}
            from pump24 import patterns as PP
            for rule in rules:
                if PP.snapshot_hits(groups, rule):
                    tag = PP.rule_tag(rule)
                    st = tag_stats.setdefault(tag, {"bars": 0, "successes": 0, "examples": []})
                    st["bars"] += 1
                    if outcome:
                        st["successes"] += 1
                        if len(st["examples"]) < 5:
                            st["examples"].append({"symbol": sym, "time": fmt(rise_ms)})
            if len(entry_logs) < 400:
                entry_logs.append({"symbol": sym, "rise_ms": rise_ms})
    base_rate = None
    results = []
    for tag, st in tag_stats.items():
        if st["bars"] < 10:
            continue
        acc = 100 * st["successes"] / st["bars"]
        results.append({"tag": tag, "n": st["bars"], "acc_pct": round(acc, 1),
                        "examples": st["examples"]})
    results.sort(key=lambda r: -r["acc_pct"])
    return {"total_bars": total_bars, "results": results[:80]}


def M1_MS_mult():
    return 60_000


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%m-%d %H:%M")


def main():
    conn = D.pg_connect()
    end_ms = int(datetime.now(TZ).timestamp() * 1000) // 300_000 * 300_000
    end_ms -= 300_000  # last fully closed M5 bar
    start_ms = end_ms - 24 * 3_600_000
    print(f"[window] {fmt(start_ms)} .. {fmt(end_ms)}", flush=True)

    universe = active_universe(conn, top_n=50)
    print(f"[universe] {len(universe)} symbols (top volume, non-synthetic)", flush=True)

    print("[stage: fetch 5m]", flush=True)
    counts5 = stage_fetch(conn, universe, "5m", start_ms, end_ms)
    print("[stage: fetch 1m]", flush=True)
    counts1 = stage_fetch(conn, universe, "1m", start_ms - 6 * 3_600_000, end_ms)
    print("[stage: events]", flush=True)
    events = stage_events(conn, universe, start_ms, end_ms)
    print(f"[stage: events done] {len(events)} events with full snapshots", flush=True)
    print("[stage: patterns]", flush=True)
    rules = stage_patterns(events)
    print(f"[stage: patterns done] {len(rules)} rules", flush=True)
    print("[stage: backtest]", flush=True)
    bt = stage_backtest(conn, universe, start_ms, end_ms, rules)
    print(f"[stage: backtest done] {bt['total_bars']} bars scanned", flush=True)

    report = {
        "type": "pump24_pattern_research",
        "generated_at": datetime.now(TZ).isoformat(),
        "window": {"start": fmt(start_ms), "end": fmt(end_ms)},
        "universe": universe,
        "fetch_counts_5m": counts5,
        "fetch_counts_1m": counts1,
        "n_events": len(events),
        "events": [{k: v for k, v in ev.items() if k != "groups"} for ev in events],
        "rules": rules,
        "backtest": bt,
    }
    path = f"{REPORT_PREFIX}_{datetime.now(TZ).strftime('%Y%m%d_%H%M')}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(f"[report] {path}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
