"""Run one shared-balance, chronological paper backtest across symbols."""
import argparse, asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import database
from app.analyzer import ScalpAnalyzer
from app.backtest import _close_trade, _fetch_klines
from app.config import config


async def main(args):
    symbols = [s.upper() for s in args.symbols]
    await database.init_db()
    series = {}
    for symbol in symbols:
        try:
            data = await asyncio.to_thread(_fetch_klines, symbol, args.interval, args.days)
            series[symbol] = data
            print(f"[DATA] {symbol} | candles={len(data['closes'])}", flush=True)
        except Exception as exc:
            print(f"[SKIP] {symbol} | {exc}", flush=True)
    if not series:
        raise SystemExit("Kullanılabilir tarihsel veri yok")

    analyzer = ScalpAnalyzer(None)
    fn = analyzer.strategy_bb_mfi_mean_reversion
    timeline = sorted({t for data in series.values() for t in data["times"]})
    idx = {s: {t: i for i, t in enumerate(d["times"])} for s, d in series.items()}
    cash = float(config.INITIAL_BALANCE_TRY)
    initial = cash
    positions = {}
    trades = []
    total_fees = 0.0
    max_equity = cash
    max_dd = 0.0

    for ts in timeline:
        # First process exits, so released cash can be reused on this candle.
        for symbol, pos in list(positions.items()):
            data, i = series[symbol], idx[symbol].get(ts, -1)
            if i < 0: continue
            high, low = data["highs"][i], data["lows"][i]
            exit_price = None; reason = None
            if low <= pos["stop"]:
                exit_price, reason = pos["stop"], "fixed_stop_loss"
            elif high >= pos["target"]:
                exit_price, reason = pos["target"], "fixed_take_profit"
            if exit_price is not None:
                cash, pnl, fee, trade = _close_trade(cash, pos["entry"], exit_price, pos["qty"], pos["invested"], reason)
                total_fees += fee; trade.update({"symbol": symbol, "entry_time": pos["time"], "exit_time": ts, "layers": pos["layers"]})
                trades.append(trade); del positions[symbol]

        # Then evaluate entries using only candles closed at this timestamp.
        for symbol, data in series.items():
            i = idx[symbol].get(ts, -1)
            if i < 55 or i + 1 >= len(data["opens"]): continue
            window = {k: v[:i + 1] for k, v in data.items()}
            if fn(window, symbol) != "buy": continue
            pos = positions.get(symbol)
            if pos and pos["layers"] >= args.pyramiding: continue
            if pos is None and len(positions) >= args.max_positions: continue
            order_value = cash * args.order_pct
            if order_value <= config.MIN_NOTIONAL or cash < order_value * (1 + config.COMMISSION_PCT): continue
            entry = data["opens"][i + 1]
            fee = order_value * config.COMMISSION_PCT; cash -= order_value + fee; total_fees += fee
            qty = order_value / entry
            if pos:
                total = pos["qty"] + qty
                pos["entry"] = (pos["entry"] * pos["qty"] + entry * qty) / total
                pos["qty"], pos["invested"], pos["layers"] = total, pos["invested"] + order_value, pos["layers"] + 1
                pos["stop"] = pos["entry"] * (1 - args.stop_pct); pos["target"] = pos["entry"] * (1 + args.tp_pct)
            else:
                positions[symbol] = {"entry": entry, "qty": qty, "invested": order_value, "layers": 1, "stop": entry * (1 - args.stop_pct), "target": entry * (1 + args.tp_pct), "time": data["times"][i + 1]}

        equity = cash + sum(p["qty"] * series[s]["closes"][idx[s].get(ts, 0)] for s, p in positions.items())
        max_equity = max(max_equity, equity); max_dd = max(max_dd, (max_equity - equity) / max_equity if max_equity else 0)

    # Open positions are excluded from realized PnL; return their principal to cash.
    cash += sum(p["invested"] for p in positions.values())
    wins = sum(t["pnl"] > 0 for t in trades)
    result = {"initial_balance": initial, "final_balance": round(cash, 2), "net_pnl": round(cash - initial, 2), "net_pnl_pct": round((cash / initial - 1) * 100, 2), "symbols": len(series), "trades": len(trades), "wins": wins, "losses": len(trades) - wins, "win_rate": round(wins / len(trades) * 100, 2) if trades else 0, "commission": round(total_fees, 2), "max_drawdown_pct": round(max_dd * 100, 2), "open_positions_excluded": len(positions), "order_pct": args.order_pct, "pyramiding": args.pyramiding, "trades_detail": trades}
    print("[COMPLETE] portfolio backtest", flush=True); print("RESULT_JSON=" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--symbols", nargs="+", required=True); p.add_argument("--interval", default="5m"); p.add_argument("--days", type=int, default=1); p.add_argument("--order-pct", type=float, default=0.10); p.add_argument("--pyramiding", type=int, default=2); p.add_argument("--max-positions", type=int, default=36); p.add_argument("--stop-pct", type=float, default=config.BB_MFI_STOP_LOSS_PCT); p.add_argument("--tp-pct", type=float, default=config.BB_MFI_TAKE_PROFIT_PCT); asyncio.run(main(p.parse_args()))
