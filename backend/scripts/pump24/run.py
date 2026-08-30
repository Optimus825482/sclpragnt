"""CLI entry for the pump24 pipeline.

Usage (backend venv):
  venv/Scripts/python.exe -m scripts.pump24.run fetch      # klines -> DB
  venv/Scripts/python.exe -m scripts.pump24.run events     # %2 events + snapshots
  venv/Scripts/python.exe -m scripts.pump24.run patterns   # mine rules
  venv/Scripts/python.exe -m scripts.pump24.run backtest   # scan + lift
  venv/Scripts/python.exe -m scripts.pump24.run all        # full pipeline
  venv/Scripts/python.exe -m scripts.pump24.run smoke      # module smoke tests
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root (active_symbols.json cwd fallback)

from pump24 import data as D
from pump24 import events as E
from pump24 import patterns as P
from pump24.smc import build_frame

TZ = ZoneInfo("Europe/Istanbul")
STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_DIR.mkdir(exist_ok=True)


def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%m-%d %H:%M")


def window_hours(hours=24):
    end_ms = int(datetime.now(TZ).timestamp() * 1000) // 300_000 * 300_000 - 300_000
    return end_ms - hours * 3_600_000, end_ms


def universe(top_n=50):
    backend_root = Path(__file__).resolve().parents[2]
    info = json.load(open(backend_root / "active_symbols.json", encoding="utf-8"))
    symbols = [s for s in info["active"] if not s.startswith(("AIGENSYN", "1000CAT", "1000SATS", "1MBABYDOGE", "2Z"))]
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


def cmd_fetch(hours):
    start_ms, end_ms = window_hours(hours)
    symbols = universe(top_n=50)
    print(f"[fetch] {len(symbols)} symbols, {fmt(start_ms)}..{fmt(end_ms)}", flush=True)
    conn = D.pg_connect()
    counts = {}
    for sym in symbols:
        for tf in ("5m", "1m"):
            try:
                n = D.sync_symbol(conn, sym, tf, start_ms, end_ms)
                counts[f"{sym}:{tf}"] = n
                print(f"  {sym} {tf}: {n}", flush=True)
            except Exception as exc:
                counts[f"{sym}:{tf}"] = f"ERR {type(exc).__name__}: {str(exc)[:120]}"
                print(f"  {sym} {tf}: ERR {exc}", flush=True)
            time.sleep(0.1)
    (STATE_DIR / "fetch_counts.json").write_text(json.dumps(counts, indent=1))
    conn.close()
    ok = sum(1 for v in counts.values() if isinstance(v, int) and v > 0)
    print(f"[fetch done] {ok}/{len(counts)} symbol/timeframe pairs ok", flush=True)


def cmd_events(hours, min_rise_pct=2.0):
    start_ms, end_ms = window_hours(hours)
    symbols = universe(top_n=50)
    conn = D.pg_connect()
    all_events = []
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", start_ms - 6 * 3_600_000, end_ms)
        if len(m5) < 80 or len(m1) < E.MIN_M1_HISTORY + 1:
            print(f"  [skip] {sym}: m5={len(m5)} m1={len(m1)}", flush=True)
            continue
        m5_frame = build_frame(sym, "5m", m5)
        m1_frame = build_frame(sym, "1m", m1)
        raw = E.detect_events(m5, min_rise_pct)
        kept = 0
        for ev in raw:
            snap = E.event_snapshot(sym, m5_frame, m1_frame, ev)
            if snap:
                all_events.append(snap)
                kept += 1
        if raw:
            print(f"  {sym}: {len(raw)} raw, {kept} snapshot-ready", flush=True)
    E.save_snapshots(conn, all_events)
    E.save_events(conn, f"pump24_events_{int(min_rise_pct*10)}pct", all_events)
    (STATE_DIR / "events.json").write_text(json.dumps(all_events, ensure_ascii=False))
    conn.close()
    print(f"[events done] {len(all_events)} snapshot-ready events", flush=True)
    return all_events


def load_events():
    events = json.load(open(STATE_DIR / "events.json", encoding="utf-8"))
    return events


def cmd_patterns(min_frac=0.60):
    events = load_events()
    rules = P.mine_patterns(events, min_frac=min_frac)
    (STATE_DIR / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=1))
    print(f"[patterns done] {len(rules)} rules (frac>={min_frac})", flush=True)
    return rules


def cmd_backtest(hours, horizon_bars=3, target_pct=1.0, max_rules=120):
    start_ms, end_ms = window_hours(hours)
    symbols = universe(top_n=50)
    rules = json.load(open(STATE_DIR / "rules.json", encoding="utf-8"))[:max_rules]
    conn = D.pg_connect()
    tag_stats = {}
    total_bars = 0
    successes_total = 0
    from pump24.patterns import snapshot_hits, rule_tag
    for sym in symbols:
        m5 = D.load_candles(conn, sym, "5m", start_ms, end_ms)
        m1 = D.load_candles(conn, sym, "1m", start_ms - 6 * 3_600_000, end_ms)
        if len(m5) < 80 or len(m1) < 220:
            continue
        m5_frame = build_frame(sym, "5m", m5)
        m1_frame = build_frame(sym, "1m", m1)
        m1_idx = {t: k for k, t in enumerate(m1_frame["open_time"])}
        m5_times = m5_frame["open_time"]
        for i in range(60, len(m5) - horizon_bars):
            rise_ms = m5_times[i]
            entry = m5_frame["close"][i]
            if not entry:
                continue
            outcome = False
            for j in range(i + 1, min(i + 1 + horizon_bars, len(m5))):
                if (m5_frame["high"][j] / entry - 1) * 100 >= target_pct:
                    outcome = True
                    break
            groups = {}
            for g, off in (("m5_g0", 0), ("m5_g1", -1), ("m5_g2", -2)):
                idx = i + off
                groups[g] = {k: m5_frame[k][idx] for k in E.SNAPSHOT_FIELDS if k in m5_frame}
            for g, delta in (("m1_g0", 1), ("m1_g1", 2), ("m1_g2", 3)):
                j = m1_idx.get(rise_ms - delta * 60_000)
                if j is not None:
                    groups[g] = {k: m1_frame[k][j] for k in E.SNAPSHOT_FIELDS if k in m1_frame}
            total_bars += 1
            if outcome:
                successes_total += 1
            for rule in rules:
                if snapshot_hits(groups, rule):
                    tag = rule_tag(rule)
                    st = tag_stats.setdefault(tag, {"bars": 0, "successes": 0, "examples": []})
                    st["bars"] += 1
                    if outcome:
                        st["successes"] += 1
                        if len(st["examples"]) < 4:
                            st["examples"].append(f"{sym} {fmt(rise_ms)}")
    base_rate = 100 * successes_total / total_bars if total_bars else None
    results = []
    for tag, st in tag_stats.items():
        if st["bars"] < 10:
            continue
        acc = 100 * st["successes"] / st["bars"]
        results.append({"tag": tag, "n": st["bars"], "acc_pct": round(acc, 1),
                        "lift": round(acc - base_rate, 1) if base_rate is not None else None,
                        "examples": st["examples"]})
    results.sort(key=lambda r: -r["acc_pct"])
    out = {"window": {"start": fmt(start_ms), "end": fmt(end_ms)}, "total_bars": total_bars,
           "base_rate_pct": round(base_rate, 2) if base_rate is not None else None,
           "n_rules": len(rules), "results": results}
    (STATE_DIR / "backtest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    conn.close()
    print(f"[backtest done] {total_bars} bars, top tags: {[(r['tag'], r['acc_pct']) for r in results[:5]]}", flush=True)


def cmd_smoke():
    import random
    random.seed(7)
    rows = []
    price = 10.0
    t0 = 1_700_000_000_000
    for k in range(400):
        price *= (1 + random.gauss(0.0005, 0.004))
        rows.append({"open_time": t0 + k * 300_000, "close_time": t0 + k * 300_000 + 299_999,
                     "open": price * (1 - 0.001), "high": price * (1.004), "low": price * 0.996,
                     "close": price, "volume": random.random() * 1000})
    frame = build_frame("TEST", "5m", rows)
    for key in ("rsi_14", "macd_hist", "adx_14", "atr_pct", "bb_pos", "vwap_dist_pct",
                "vol_ratio_20", "supertrend_dir", "bos", "td9_bull", "candle_label"):
        series = frame[key]
        tail = [v for v in series[-100:] if v is not None]
        assert tail, f"empty series {key}"
    # compare RSI against app implementation on the last bar
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.technical_analysis import _rsi, _atr, _adx as app_adx
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    r_mine = frame["rsi_14"][-1]
    r_app = _rsi(closes)
    assert abs(r_mine - r_app) < 1e-6, f"RSI mismatch {r_mine} vs {r_app}"
    atr_mine = frame["atr_14"][-1]
    atr_app = _atr(highs, lows, closes)
    assert abs(atr_mine - atr_app) < 1e-6, f"ATR mismatch {atr_mine} vs {atr_app}"
    adx_mine = frame["adx_14"][-1]
    adx_app = app_adx(highs, lows, closes)["adx"]
    assert abs(adx_mine - adx_app) < 0.5, f"ADX mismatch {adx_mine} vs {adx_app}"
    # event detection on synthetic pump
    pumped = [dict(r) for r in rows]
    for k in range(380, 385):
        pumped[k]["close"] = pumped[k]["close"] * (1 + 0.03)
        pumped[k]["high"] = pumped[k]["close"]
    evs = E.detect_events(pumped, 2.0)
    assert evs, "no events detected on synthetic pump"
    print(f"[smoke OK] frame keys={len(frame)}, events={len(evs)}, "
          f"rsi={r_mine:.2f}, adx={adx_mine:.2f}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    if cmd == "smoke":
        cmd_smoke()
    elif cmd == "fetch":
        cmd_fetch(hours)
    elif cmd == "events":
        cmd_events(hours)
    elif cmd == "patterns":
        cmd_patterns()
    elif cmd == "backtest":
        cmd_backtest(hours)
    elif cmd == "all":
        cmd_fetch(hours)
        cmd_events(hours)
        cmd_patterns()
        cmd_backtest(hours)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
