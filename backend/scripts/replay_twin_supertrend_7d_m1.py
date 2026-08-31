"""7 gün M1 replay — sadece twin_supertrend (Twin Range Filter + SuperTrend).

replay_tv_strategies_24h.py çatısını kullanır; tek strateji, satır bazlı çıktı,
12 ana sembol. Amaç: tek bar tetikleyicisi sıkılaştırmasıyla 7 günlük M1'de
Twin Range Filter + SuperTrend konfluansının işlem dağılımını ve PnL'sini görmek.
"""
import asyncio
import os
import sys
from collections import defaultdict
from statistics import mean

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.replay_tv_strategies_24h import (
    TVReplay, SYMBOLS, TIMEFRAMES, summarize,
)


async def main():
    replay = TVReplay(SYMBOLS, "M1")
    replay.load_days_override = 8  # 7 gün + warmup
    loaded = await replay.load()
    print(f"[M1 twin_supertrend] yüklü sembol: {loaded}/{len(SYMBOLS)}", flush=True)
    if loaded == 0:
        return

    data_end = max(int(d["rows"][-1][0]) for d in replay.data.values())
    day_ms = 24 * 3_600_000
    win_start = data_end - 7 * day_ms

    r = replay.run("twin_supertrend", start_ms=win_start, end_ms=data_end)
    summarize("M1 twin_supertrend / 7G", r)

    # sembol bazlı dağılım
    print("\nsembol bazlı:", flush=True)
    by_sym = defaultdict(list)
    for t in r["trades"]:
        if t["action"] == "close":
            by_sym[t["symbol"]].append(t["pnl"])
    for s, pnls in sorted(by_sym.items()):
        print(f"  {s}: n={len(pnls)} toplam {sum(pnls):+.1f} TL | win "
              f"%{sum(1 for p in pnls if p > 0) / len(pnls) * 100:.0f}", flush=True)

    import json
    out = {"window_hours": 168, "symbols": SYMBOLS, "strategy": "twin_supertrend",
           "trades": r["trades"], "final_cash": r["final_cash"]}
    with open("../work/replay_twin_supertrend_7d_m1.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print("\nrapor: ../work/replay_twin_supertrend_7d_m1.json", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
