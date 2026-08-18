"""
72-hour BB_MFI_MEAN_REVERSION backtest — 18 symbols × 3 stop/TP scenarios.
Pulls 5m candles from Binance TR public API, runs deterministic walk-forward.
"""
import sys, os, asyncio, json, time
from collections import Counter
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "..", "backend"))

from app.binance_tr_public import klines as fetch_klines
from app.config import config
from app.technical_analysis import _mfi


def calc_ema(prices, period):
    if len(prices) < period: return None
    alpha = 2 / (period + 1)
    v = float(np.mean(prices[:period]))
    for p in prices[period:]: v = alpha * float(p) + (1 - alpha) * v
    return v


def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    d = np.diff(np.asarray(closes[-period - 1:], dtype=float))
    g = np.mean(np.maximum(d, 0)); l = np.mean(np.maximum(-d, 0))
    if l == 0: return 100.0 if g > 0 else 50.0
    return float(100 - (100 / (1 + g / l)))


def calc_bb(closes, period=21, std=2.0):
    if len(closes) < period: return None
    w = np.asarray(closes[-period:], dtype=float)
    m = float(np.mean(w)); s = float(np.std(w))
    return {"upper": m + std * s, "middle": m, "lower": m - std * s}


async def backtest_symbol(sym, stop_pct, tp_pct):
    """Run deterministic walk-forward for one symbol."""
    raw = await fetch_klines(sym, "5m", limit=900)
    if not raw or len(raw) < 55:
        return None

    opens  = np.array([float(r[1]) for r in raw])
    highs  = np.array([float(r[2]) for r in raw])
    lows   = np.array([float(r[3]) for r in raw])
    closes = np.array([float(r[4]) for r in raw])
    vols   = np.array([float(r[5]) for r in raw])
    n = len(closes)

    balance = 10000.0
    position = None
    trades = []
    COMM = 0.0015  # commission per side

    for i in range(max(21, config.BB_MFI_MFI_PERIOD + 1), n):
        wc = closes[:i + 1].tolist()
        wh = highs[:i + 1].tolist()
        wl = lows[:i + 1].tolist()
        wv = vols[:i + 1].tolist()

        # --- Position exit logic ---
        if position is not None:
            entry  = position["entry"]
            qty    = position["qty"]
            invested = position["invested"]

            # 1. Stop-loss check (intrabar low)
            stop_price = entry * (1 - stop_pct)
            if lows[i] <= stop_price:
                exit_v = stop_price * qty
                fee_entry = invested * COMM
                fee_exit  = exit_v * COMM
                pnl = (exit_v - invested) - fee_entry - fee_exit
                balance += invested + pnl
                trades.append({"entry": entry, "exit": stop_price, "pnl": round(pnl, 4), "reason": "stop_loss", "bars": i - position["bar"]})
                position = None
                continue

            # 2. Take-profit check (intrabar high)
            tp_price = entry * (1 + tp_pct)
            if highs[i] >= tp_price:
                exit_v = tp_price * qty
                fee_entry = invested * COMM
                fee_exit  = exit_v * COMM
                pnl = (exit_v - invested) - fee_entry - fee_exit
                balance += invested + pnl
                trades.append({"entry": entry, "exit": tp_price, "pnl": round(pnl, 4), "reason": "take_profit", "bars": i - position["bar"]})
                position = None
                continue

            # 3. BB-MFI sell signal
            bb = calc_bb(wc, config.BB_MFI_BB_PERIOD, config.BB_MFI_BB_STD_DEV)
            rsi_val = calc_rsi(wc, config.BB_MFI_RSI_PERIOD)
            mfi_val = _mfi(wh, wl, wc, wv, config.BB_MFI_MFI_PERIOD)
            if bb and rsi_val is not None and mfi_val is not None:
                if wc[-1] > bb["upper"] and rsi_val > config.BB_MFI_EXIT_RSI_MIN and mfi_val > config.BB_MFI_EXIT_MFI_MIN:
                    exit_price = opens[i + 1] if i + 1 < n else closes[i]
                    exit_v = exit_price * qty
                    fee_entry = invested * COMM
                    fee_exit  = exit_v * COMM
                    pnl = (exit_v - invested) - fee_entry - fee_exit
                    balance += invested + pnl
                    trades.append({"entry": entry, "exit": exit_price, "pnl": round(pnl, 4), "reason": "bb_mfi_sell", "bars": i - position["bar"]})
                    position = None
                    continue

            continue  # position open, not selling → next bar

        # --- Entry logic (no position open) ---
        bb = calc_bb(wc, config.BB_MFI_BB_PERIOD, config.BB_MFI_BB_STD_DEV)
        rsi_val = calc_rsi(wc, config.BB_MFI_RSI_PERIOD)
        mfi_val = _mfi(wh, wl, wc, wv, config.BB_MFI_MFI_PERIOD)
        if not bb or rsi_val is None or mfi_val is None:
            continue

        # Volume ratio
        avg_vol = float(np.mean(vols[max(0, i - 21):i])) if i >= 21 else 0
        vol_ratio = vols[i] / avg_vol if avg_vol > 0 else 1.0

        # v3 entry signal
        if (wc[-1] < bb["lower"]
            and mfi_val < config.BB_MFI_ENTRY_MFI_MAX
            and vol_ratio >= config.BB_MFI_ENTRY_VOLUME_RATIO_MIN):
            # Enter at next bar open
            if i + 1 >= n:
                continue
            entry_price = float(opens[i + 1])
            order_pct_val = config.ORDER_PCT
            order_value = balance * order_pct_val
            fee = order_value * COMM
            if balance < order_value + fee:
                continue
            balance -= (order_value + fee)
            qty = order_value / entry_price
            position = {
                "entry": entry_price,
                "qty": qty,
                "invested": order_value,
                "bar": i + 1,
            }

    # Close open position at end
    if position:
        entry = position["entry"]
        qty = position["qty"]
        invested = position["invested"]
        exit_price = float(closes[-1])
        exit_v = exit_price * qty
        fee_entry = invested * COMM
        fee_exit = exit_v * COMM
        pnl = (exit_v - invested) - fee_entry - fee_exit
        balance += invested + pnl
        trades.append({"entry": entry, "exit": exit_price, "pnl": round(pnl, 4), "reason": "open_at_end", "bars": n - 1 - position["bar"]})

    total_pnl = round(balance - 10000.0, 4)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] <= 0)
    w_pnls = [t["pnl"] for t in trades if t["pnl"] > 0]
    l_pnls = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gross_profit = sum(w_pnls)
    gross_loss = abs(sum(l_pnls))

    return {
        "symbol": sym,
        "candles": n,
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "pnl": total_pnl,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "avg_win": round(sum(w_pnls) / len(w_pnls), 4) if w_pnls else 0,
        "avg_loss": round(sum(l_pnls) / len(l_pnls), 4) if l_pnls else 0,
        "reasons": dict(Counter(t["reason"] for t in trades)),
        "balance": round(balance, 2),
        "trades_list": trades,
    }


async def main():
    SCENARIOS = [
        ("A_LIVE",      0.08882, 0.02317),
        ("B_BALANCED",  0.035,   0.035),
        ("C_TIGHT",     0.025,   0.025),
    ]

    all_results = {}

    for sname, stop, tp in SCENARIOS:
        print(f"\n{'='*80}")
        print(f"  SCENARIO {sname}: stop_loss={stop:.2%}  take_profit={tp:.2%}  RR_against={stop/tp:.1f}:1")
        print(f"{'='*80}")
        print(f"  {'Symbol':<8} {'Candles':>7} {'Trades':>7} {'Wins':>6} {'PnL':>10} {'WR':>6} {'PF':>6} {'Exit Reasons'}")
        print(f"  {'─'*8} {'─'*7} {'─'*7} {'─'*6} {'─'*10} {'─'*6} {'─'*6} {'─'*30}")

        agg_t = agg_w = 0
        agg_pnl = 0.0
        sym_results = []

        for sym in config.SYMBOLS:
            r = await backtest_symbol(sym, stop, tp)
            if r is None:
                print(f"  {sym:<8} {'SKIP':>7}")
                continue
            agg_t += r["trades"]
            agg_w += r["wins"]
            agg_pnl += r["pnl"]
            sym_results.append(r)
            reasons_str = ", ".join(f"{k}:{v}" for k, v in r["reasons"].items())
            pf_str = f'{r["profit_factor"]:.2f}' if r["profit_factor"] else "—"
            print(f"  {r['symbol']:<8} {r['candles']:>7} {r['trades']:>7} {r['wins']:>6} {r['pnl']:>+10.2f} {r['win_rate']:>5.1f}% {pf_str:>6} {reasons_str}")

        agg_wr = round(agg_w / agg_t * 100, 1) if agg_t else 0
        print(f"  {'─'*8} {'─'*7} {'─'*7} {'─'*6} {'─'*10} {'─'*6}")
        print(f"  {'TOTAL':<8} {'':>7} {agg_t:>7} {agg_w:>6} {agg_pnl:>+10.2f} {agg_wr:>5.1f}%")

        all_results[sname] = {
            "stop": stop, "tp": tp,
            "trades": agg_t, "wins": agg_w, "pnl": round(agg_pnl, 2), "wr": agg_wr,
            "symbols": sym_results,
        }

    # Final comparison
    print(f"\n\n{'='*80}")
    print(f"  FINAL COMPARISON — 18 symbols, ~900 candles each (~3.1 days of 5m)")
    print(f"{'='*80}")
    print(f"  {'Scenario':<16} {'Stop':>7} {'TP':>7} {'Trades':>7} {'Wins':>6} {'PnL':>10} {'WR':>6}")
    print(f"  {'─'*16} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*10} {'─'*6}")
    best = max(all_results.values(), key=lambda x: x["pnl"])
    for name, r in all_results.items():
        marker = " ← BEST" if r is best else ""
        print(f"  {name:<16} {r['stop']:>6.1%} {r['tp']:>6.1%} {r['trades']:>7} {r['wins']:>6} {r['pnl']:>+10.2f} {r['wr']:>5.1f}%{marker}")

    # Save full JSON
    out_path = os.path.join(BASE, "..", "docs", "backtest_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  Full results saved to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
