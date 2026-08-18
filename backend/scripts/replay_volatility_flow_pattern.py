"""48h causal replay for the volatility/flow pattern (paper-only).

Warm-up data is fetched before the 48h test window. Entry decisions use only
closed M1 bars and completed resampled H1/H4 bars. No future label is used.
"""
import argparse, asyncio, bisect, json, math, time
from pathlib import Path
from datetime import datetime, timezone

from app.binance_tr_public import historical_klines, trading_symbols
from scripts.analyze_all_symbol_spike_snapshots import features

FEE = 0.0015
ORDER_VALUE = 500.0
INITIAL_CASH = 10000.0
MAX_POSITIONS = 4

def normalize(rows):
    return [{"time": int(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
             "close": float(r[4]), "volume": float(r[5])} for r in rows]

def aggregate(rows, minutes):
    step = minutes * 60_000; out = {}; result = []
    for row in rows:
        bucket = row["time"] // step * step
        item = out.get(bucket)
        if item is None:
            item = {"time": bucket, "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"], "volume": row["volume"]}; out[bucket] = item; result.append(item)
        else:
            item["high"] = max(item["high"], row["high"]); item["low"] = min(item["low"], row["low"]); item["close"] = row["close"]; item["volume"] += row["volume"]
    return result

async def fetch(symbol, end_ms, days, sem):
    async with sem:
        try:
            rows = await historical_klines(symbol, "1m", days_back=days, end_time_ms=end_ms)
            return symbol, normalize(rows), None
        except Exception as exc:
            return symbol, [], f"{type(exc).__name__}: {exc}"

def pattern_hit(rows, idx, h1, h4, min_atr_pct, min_bb_width_pct):
    current = features(rows, idx); prev = features(rows, idx - 1); ten = features(rows, idx - 10)
    if not current or not prev or not ten: return None
    core = {
        "atr_rising": current.get("atr_pct") is not None and prev.get("atr_pct") is not None and current["atr_pct"] >= min_atr_pct and current["atr_pct"] > prev["atr_pct"],
        "bb_width_rising": current.get("bb_width_pct") is not None and prev.get("bb_width_pct") is not None and current["bb_width_pct"] >= min_bb_width_pct and current["bb_width_pct"] > prev["bb_width_pct"],
        "ema_gap_positive_10m": current.get("ema9_21_gap_pct") is not None and ten.get("ema9_21_gap_pct") is not None and current["ema9_21_gap_pct"] > 0 and ten["ema9_21_gap_pct"] > 0,
        "di_gap_positive": current.get("di_gap") is not None and current["di_gap"] > 0,
        "cmf_turning_positive": current.get("cmf_20") is not None and prev.get("cmf_20") is not None and current["cmf_20"] > 0 and current["cmf_20"] > prev["cmf_20"],
    }
    ts = rows[idx]["time"]
    h1rows, h1times = h1; h4rows, h4times = h4
    h1idx = bisect.bisect_left(h1times, ts) - 1; h4idx = bisect.bisect_left(h4times, ts) - 1
    h1f = features(h1rows, h1idx) if h1idx >= 54 else None
    h4f = features(h4rows, h4idx) if h4idx >= 54 else None
    # Mixed means a small negative gap is allowed; this is intentionally a
    # research interpretation and is reported in the output.
    core["h1_neutral_or_bullish"] = bool(h1f and h1f.get("ema9_21_gap_pct") is not None and h1f["ema9_21_gap_pct"] >= -0.10)
    core["h4_neutral_or_bullish"] = bool(h4f and h4f.get("ema9_21_gap_pct") is not None and h4f["ema9_21_gap_pct"] >= -0.10)
    bonus = bool(current.get("volume_ratio_20") is not None and current["volume_ratio_20"] >= 1.5)
    return {"hit": all(core.values()), "bonus_volume": bonus, "features": {"atr_pct": current.get("atr_pct"), "bb_width_pct": current.get("bb_width_pct"), "ema_gap_pct": current.get("ema9_21_gap_pct"), "di_gap": current.get("di_gap"), "cmf": current.get("cmf_20"), "volume_ratio": current.get("volume_ratio_20")}, "gates": core}

async def main(args):
    end_ms = int(time.time() * 1000); test_start = end_ms - args.hours * 3600_000; fetch_days = args.hours // 24 + 8
    symbols = [s.upper() for s in args.symbols] if args.symbols else await trading_symbols("TRY")
    sem = asyncio.Semaphore(args.concurrency)
    loaded = await asyncio.gather(*(fetch(s, end_ms, fetch_days, sem) for s in symbols))
    series = {s: rows for s, rows, err in loaded if rows}; errors = {s: err for s, rows, err in loaded if err}
    indexes = {s: {row["time"]: i for i, row in enumerate(rows)} for s, rows in series.items()}
    higher_tf = {s: ((h1 := aggregate(rows, 60)), [x["time"] for x in h1], (h4 := aggregate(rows, 240)), [x["time"] for x in h4]) for s, rows in series.items()}
    all_times = sorted({row["time"] for rows in series.values() for row in rows if row["time"] >= test_start})
    positions, cash, fees, trades, signals, bonus_hits = {}, INITIAL_CASH, 0.0, [], 0, 0
    for ts in all_times:
        for symbol, position in list(positions.items()):
            row = series[symbol][indexes[symbol][ts]] if ts in indexes[symbol] else None
            if not row: continue
            exit_price = None; reason = None
            if row["low"] <= position["stop"]: exit_price, reason = position["stop"], "stop_loss"
            elif row["high"] >= position["target"]: exit_price, reason = position["target"], "take_profit"
            elif ts - position["time"] >= args.max_hold_minutes * 60_000: exit_price, reason = row["open"], "time_exit"
            if exit_price is not None:
                gross = (exit_price - position["entry"]) * position["qty"]; exit_fee = exit_price * position["qty"] * FEE; pnl = gross - exit_fee - position["entry_fee"]
                cash += exit_price * position["qty"] - exit_fee; fees += exit_fee; trades.append({**position, "symbol": symbol, "exit": exit_price, "exit_time": ts, "pnl": pnl, "reason": reason}); del positions[symbol]
        for symbol, rows in series.items():
            if symbol in positions or len(positions) >= MAX_POSITIONS or cash < ORDER_VALUE * (1 + FEE): continue
            idx = indexes[symbol].get(ts)
            if idx is None or ts < test_start or idx < 70 or (ts // 60_000) % args.decision_step_minutes != 0: continue
            cached = higher_tf[symbol]; h1, h4 = (cached[0], cached[1]), (cached[2], cached[3])
            decision = pattern_hit(rows, idx, h1, h4, args.min_atr_pct, args.min_bb_width_pct)
            if not decision or not decision["hit"]: continue
            signals += 1; bonus_hits += int(decision["bonus_volume"])
            entry = rows[idx]["open"] * (1 + args.spread_pct / 2 + args.slippage_pct); entry_fee = ORDER_VALUE * FEE; qty = ORDER_VALUE / entry; cash -= ORDER_VALUE + entry_fee
            positions[symbol] = {"entry": entry, "qty": qty, "entry_fee": entry_fee, "time": ts, "stop": entry * (1 - args.stop_pct), "target": entry * (1 + args.tp_pct), "volume_bonus": decision["bonus_volume"], "features": decision["features"]}; fees += entry_fee
    for symbol, position in list(positions.items()):
        row = series[symbol][-1]; exit_price = row["close"]; gross = (exit_price - position["entry"]) * position["qty"]; exit_fee = exit_price * position["qty"] * FEE; pnl = gross - exit_fee - position["entry_fee"]; cash += exit_price * position["qty"] - exit_fee; fees += exit_fee; trades.append({**position, "symbol": symbol, "exit": exit_price, "exit_time": row["time"], "pnl": pnl, "reason": "end_of_test"})
    pnls = [float(t["pnl"]) for t in trades]; equity = INITIAL_CASH; peak = equity; max_dd = 0.0
    for pnl in pnls: equity += pnl; peak = max(peak, equity); max_dd = max(max_dd, (peak - equity) / peak * 100)
    wins = sum(p > 0 for p in pnls); result = {"paper_only": True, "pattern": "volatility_flow_mtf_v1", "window_hours": args.hours, "symbols": len(series), "errors": errors, "signals": signals, "trades": trades, "closed_trades": len(trades), "wins": wins, "losses": len(trades) - wins, "win_rate_pct": wins / len(trades) * 100 if trades else 0, "net_pnl_try": sum(pnls), "net_pnl_pct": sum(pnls) / INITIAL_CASH * 100, "fees_try": fees, "max_drawdown_pct": max_dd, "volume_bonus_hits": bonus_hits, "assumptions": {"initial_cash_try": INITIAL_CASH, "order_value_try": ORDER_VALUE, "max_positions": MAX_POSITIONS, "commission_each_side": FEE, "stop_pct": args.stop_pct, "tp_pct": args.tp_pct, "max_hold_minutes": args.max_hold_minutes, "mixed_tf_gap_floor_pct": -0.10}, "limitations": ["Historical spread/orderbook/liquidity unavailable; configured spread/slippage are proxies.", "H1/H4 direction is EMA9/EMA21 on completed resampled bars.", "This is a research replay, not a live strategy activation."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"); print(json.dumps({k: result[k] for k in ("window_hours", "symbols", "signals", "closed_trades", "wins", "losses", "win_rate_pct", "net_pnl_try", "net_pnl_pct", "fees_try", "max_drawdown_pct", "volume_bonus_hits")}, ensure_ascii=False))

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--hours", type=int, default=48); p.add_argument("--symbols", nargs="*"); p.add_argument("--output", default="volatility-flow-pattern-replay-48h.json"); p.add_argument("--concurrency", type=int, default=6); p.add_argument("--spread-pct", type=float, default=0.001); p.add_argument("--slippage-pct", type=float, default=0.0005); p.add_argument("--stop-pct", type=float, default=0.015); p.add_argument("--tp-pct", type=float, default=0.02); p.add_argument("--max-hold-minutes", type=int, default=60); p.add_argument("--decision-step-minutes", type=int, default=5); p.add_argument("--min-atr-pct", type=float, default=0.005); p.add_argument("--min-bb-width-pct", type=float, default=0.01); a = p.parse_args(); asyncio.run(main(a))
