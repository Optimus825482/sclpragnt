"""24h replay of the Fisher M3 + Kernel M5 exact-paper strategy.

Runs the SAME production loop (`fisher_m3_kernel_m5_shadow_loop` logic)
against historical closed candles: per symbol, walk each closed M1 bar,
feed causal M1/M3/M5 slices into the production observer
(FisherM3KernelM5Shadow.process), queue signals, fill at the next
completed M1 open. Applies the live position policy exactly:
- entry hour filter (FISHER_ENTRY_BLOCKED_HOURS)
- no TP/trailing/max-hold (source-exact contract)
- emergency stop (FISHER_EMERGENCY_STOP_PCT) intra-bar via M1 lows
- commission applied like the paper wallet

Also evaluates a counterfactual without the fixes to quantify their impact.
"""
import asyncio
import datetime
import sys
import os
from collections import defaultdict
from statistics import mean

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.fisher_m3_kernel_m5_shadow import FisherM3KernelM5Shadow
from app.config import config
from app.binance_tr_public import historical_klines


COMMISSION = 0.0015
HORIZON_MS = 24 * 3_600_000
WARMUP_BARS = 360  # 6h M1; M5 kernel needs 34 bars, M3 fisher needs 12 — plenty


def _slice(rows, start_ms, end_ms):
    return [r for r in rows if start_ms <= int(r[0]) and int(r[0]) + 59_999 <= end_ms]


def _to_klines(rows):
    return {
        "timestamps": [int(r[0]) for r in rows],
        "opens": [float(r[1]) for r in rows],
        "highs": [float(r[2]) for r in rows],
        "lows": [float(r[3]) for r in rows],
        "closes": [float(r[4]) for r in rows],
        "volumes": [float(r[5]) for r in rows],
    }


def _resample(rows, factor):
    out = {"timestamps": [], "opens": [], "highs": [], "lows": [], "closes": [], "volumes": []}
    bucket = []
    for row in rows:
        bucket.append(row)
        if len(bucket) == factor:
            out["timestamps"].append(int(bucket[0][0]))
            out["opens"].append(float(bucket[0][1]))
            out["highs"].append(max(float(r[2]) for r in bucket))
            out["lows"].append(min(float(r[3]) for r in bucket))
            out["closes"].append(float(bucket[-1][4]))
            out["volumes"].append(sum(float(r[5]) for r in bucket))
            bucket = []
    return out


class FisherReplay:
    def __init__(self, symbols, hours=24):
        self.symbols = symbols
        self.hours = hours
        self.emergency_stop = config.FISHER_EMERGENCY_STOP_PCT / 100.0
        self.blocked_hours = set(config.FISHER_ENTRY_BLOCKED_HOURS or [])

    async def load(self):
        self.data = {}
        for symbol in self.symbols:
            try:
                m1 = await historical_klines(symbol, "1m", 2)
                m3 = await historical_klines(symbol, "3m", 2)
                m5 = await historical_klines(symbol, "5m", 2)
            except Exception:
                continue
            if len(m1) < WARMUP_BARS + 60:
                continue
            self.data[symbol] = {"m1": m1, "m3": m3, "m5": m5}
        return len(self.data)

    def run(self, apply_fixes=True):
        """Replay the exact loop. apply_fixes=False → eski davranış (saat filtresi ve acil stop yok)."""
        observer = FisherM3KernelM5Shadow()
        pending: dict[str, dict] = {}
        cash = 10_000.0
        trades = []
        open_pos: dict[str, dict] = {}
        states = {}  # per-symbol m1 cursor for exact loop semantics

        end_ms = max(int(d["m1"][-1][0]) for d in self.data.values())
        start_ms = end_ms - HORIZON_MS

        # Her sembol için tüm adımları tek kronolojik akışta gezeriz.
        # Loop, her tarama turunda her sembolün son kapanmış M1'ini işler;
        # replay'de aynı etkiyi M1 barı başına tek "tur" ile yaparız.
        all_times = sorted({int(r[0]) for d in self.data.values() for r in d["m1"]
                            if start_ms <= int(r[0]) and int(r[0]) + 59_999 <= end_ms})

        for bar_ms in all_times:
            for symbol, d in self.data.items():
                state = states.setdefault(symbol, {"last_processed": 0})
                rows_before = [r for r in d["m1"] if int(r[0]) + 59_999 <= bar_ms + 59_999]
                if not rows_before:
                    continue
                last = rows_before[-1]
                if int(last[0]) <= state["last_processed"]:
                    continue
                state["last_processed"] = int(last[0])
                m1 = _to_klines(rows_before[-400:])
                m3_rows = [r for r in d["m3"] if int(r[0]) + 59_999 <= bar_ms + 59_999]
                m5_rows = [r for r in d["m5"] if int(r[0]) + 59_999 <= bar_ms + 59_999]
                if len(m3_rows) < 12 or len(m5_rows) < 34:
                    continue
                m3 = _to_klines(m3_rows[-400:])
                m5 = _to_klines(m5_rows[-200:])

                # 1) pending fill: sonraki tamamlanmış M1 açılışı
                queued = pending.get(symbol)
                if queued and int(last[0]) > int(queued["signal"]["m1_closed_at_ms"]):
                    fill_price = float(last[1])
                    pending.pop(symbol, None)
                    if queued["action"] == "open":
                        order_value = min(cash * 0.20, 1100.0)
                        fee = order_value * COMMISSION
                        quantity = order_value / fill_price
                        cash -= order_value
                        open_pos[symbol] = {"entry": fill_price, "qty": quantity, "order_value": order_value,
                                             "entry_time_ms": int(last[0])}
                        trades.append({"symbol": symbol, "action": "open", "price": fill_price,
                                        "at_ms": int(last[0]), "hour": datetime.datetime.fromtimestamp(int(last[0]) / 1000).hour})
                    elif symbol in open_pos:
                        pos = open_pos.pop(symbol)
                        proceeds = pos["qty"] * fill_price
                        fee = proceeds * COMMISSION
                        pnl = proceeds - fee - pos["order_value"]
                        trades.append({"symbol": symbol, "action": "close", "price": fill_price,
                                        "at_ms": int(last[0]), "hour": datetime.datetime.fromtimestamp(int(last[0]) / 1000).hour,
                                        "pnl": pnl, "reason": "exit_cross",
                                        "entry": pos["entry"], "hold_h": (int(last[0]) - pos["entry_time_ms"]) / 3_600_000})
                        cash += proceeds - fee

                # 2) açık pozisyon: acil durum stop (düzeltme uygulanmışsa)
                pos = open_pos.get(symbol)
                if pos and apply_fixes and self.emergency_stop > 0:
                    lows = [float(r[3]) for r in rows_before[-2:] if int(r[0]) >= pos["entry_time_ms"]]
                    if lows:
                        stop_price = pos["entry"] * (1 - self.emergency_stop)
                        if min(lows) <= stop_price:
                            stop_fill = stop_price
                            proceeds = pos["qty"] * stop_fill
                            fee = proceeds * COMMISSION
                            pnl = proceeds - fee - pos["order_value"]
                            trades.append({"symbol": symbol, "action": "close", "price": stop_fill,
                                            "at_ms": int(last[0]), "hour": datetime.datetime.fromtimestamp(int(last[0]) / 1000).hour,
                                            "pnl": pnl, "reason": "emergency_stop",
                                            "entry": pos["entry"], "hold_h": (int(last[0]) - pos["entry_time_ms"]) / 3_600_000})
                            cash += proceeds - fee
                            open_pos.pop(symbol, None)
                            pos = None

                # 3) sinyal gözlemi
                if symbol in open_pos or symbol in pending:
                    continue  # process çağrısı her bar yapılır ama sinyal pencerelemesi pozisyon durumuna bakar
                events = observer.process(symbol, m1, m3, m5)
                for event in events:
                    if event["type"] == "long_candidate":
                        hour = datetime.datetime.fromtimestamp(bar_ms / 1000).hour
                        if apply_fixes and hour in self.blocked_hours:
                            trades.append({"symbol": symbol, "action": "blocked_hour", "at_ms": bar_ms, "hour": hour})
                            continue
                        if symbol not in pending:
                            pending[symbol] = {"action": "open", "signal": event}
                    elif event["type"] == "exit_candidate" and symbol in open_pos:
                        if symbol not in pending:
                            pending[symbol] = {"action": "close", "signal": event}

        # kapanmamış pozisyonları son fiyatla kapat (raporlama için)
        for symbol, pos in list(open_pos.items()):
            last_close = float(self.data[symbol]["m1"][-1][4])
            proceeds = pos["qty"] * last_close
            fee = proceeds * COMMISSION
            trades.append({"symbol": symbol, "action": "close", "price": last_close,
                            "at_ms": end_ms, "hour": datetime.datetime.fromtimestamp(end_ms / 1000).hour,
                            "pnl": proceeds - fee - pos["order_value"], "reason": "unrealized_close",
                            "entry": pos["entry"],
                            "hold_h": (end_ms - pos["entry_time_ms"]) / 3_600_000})
            cash += proceeds - fee
            open_pos.pop(symbol, None)
        return {"final_cash": cash, "trades": trades}


def summarize(label, result, trades):
    closed = [t for t in trades if t["action"] == "close"]
    wins = [t for t in closed if t["pnl"] > 0]
    print(f"\n=== {label} ===")
    print(f"işlem: {len(closed)} | net PnL {sum(t['pnl'] for t in closed):+.1f} TL | win %{len(wins)/len(closed)*100:.0f}" if closed else "işlem yok")
    if closed:
        stops = [t for t in closed if t["reason"] == "emergency_stop"]
        worst = [t["pnl"] for t in closed if t["pnl"] < 0]
        print(f"emergency_stop tetiklenen: {len(stops)} | en kötü kayıp {min((t['pnl'] for t in closed), default=0):+.1f} TL")
        by_reason = defaultdict(list)
        for t in closed:
            by_reason[t["reason"]].append(t["pnl"])
        for reason, pnls in by_reason.items():
            print(f"  {reason}: n={len(pnls)} ort {mean(pnls):+.2f} TL")
        print(f"ort. hold: {mean(t['hold_h'] for t in closed):.1f}h")


async def main():
    from app.config import config as cfg
    symbols = [str(s).upper() for s in cfg.SYMBOLS][:12]
    replay = FisherReplay(symbols, hours=24)
    loaded = await replay.load()
    print(f"yüklü sembol: {loaded}/{len(symbols)}")

    # Uygulamadaki hali (düzeltmelerle)
    fixed = replay.run(apply_fixes=True)
    summarize("UYGULAMADAKİ HALİ (acil stop %3 + saat filtresi)", None, fixed["trades"])

    # Eski hali (karşı-olgu)
    old = replay.run(apply_fixes=False)
    summarize("ESKİ HALİ (düzeltmesiz — karşı-olgu)", None, old["trades"])

    # saat filtresinin etkisi: eski koşumda engellenen saatlere düşen işlemler
    old_closed = [t for t in old["trades"] if t["action"] == "close"]
    blocked_hours = set(cfg.FISHER_ENTRY_BLOCKED_HOURS or [])
    entered_blocked = [t for t in old_closed if t["hour"] in blocked_hours]
    print(f"\nEski koşumda yasaklı saatlerde açılan işlemler: {len(entered_blocked)}")
    if entered_blocked:
        print(f"  toplam PnL {sum(t['pnl'] for t in entered_blocked):+.1f} TL — bunlar yeni kurallada hiç açılmayacaktı")

    import json
    json.dump({"fixed": fixed, "old": old}, open("../work/fisher_replay_24h.json", "w", encoding="utf-8"), default=str, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
