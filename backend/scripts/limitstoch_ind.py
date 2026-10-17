"""Aşama 1: her (sembol, zaman dilimi) için çekirdek + StochRSI göstergelerini hesapla ve önbelleğe yaz (work/limitstoch/cache/ind)."""
from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limitstoch_lib as L  # noqa: E402


def one(args):
    tf, sym = args
    L.get_ind(tf, sym)
    return sym


def main():
    syms = L.symbols("5m")
    t0 = time.time()
    jobs = [(tf, s) for tf in ("5m", "15m", "1m") for s in syms]
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, _ in enumerate(ex.map(one, jobs, chunksize=4)):
            if i % 100 == 0:
                print(i, len(jobs), round(time.time() - t0), flush=True)
    print("bitti", round(time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
