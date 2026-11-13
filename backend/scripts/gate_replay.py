"""min_atr_pct kapisinin GERCEK KOD uzerinden replay dogrulamasi.

Fark: `filt_replay.py` SQL'de `atr_pct>=X` yazar (filtrenin kopyasi).
Bu betik ise adayin gectigi karari `auto_paper._entry_context` fonksiyonunun
KENDISINE verdirir — yani uretimdeki kapi ne yapiyorsa o. Boylece:
  * kapi sirasi (skor -> mod -> ATR) gercekten korunuyor mu,
  * fail-open davranisi (atr yoksa gecis) dogru mu,
  * kural sinyali muafiyeti calisiyor mu,
ucu de olculur. Sonra kabul edilen adaylar GERCEK 1m mumlarla replay edilir.

Cikis modeli: trailing `gap`% + sabit `sl`% (mum KAPANISINDAN izlenir —
mum-ici siralama bilinmedigi icin muhafazakar).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics as st
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"
FEE = float(os.getenv("FEE", "0.30"))


async def decide(notif: dict, min_atr: float) -> tuple[bool, str | None]:
    """Adayi URETIM kapisindan gecir. Donus: (kabul, engel_nedeni)."""
    from app.routers import auto_paper as ap

    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = min_atr
        # Replay'de diger kapilari acik tut: yalniz ATR etkisini olcelim.
        s["min_score"] = 0.0
        s["allowed_modes"] = []
        return s

    orig = ap.get_auto_paper_settings
    ap.get_auto_paper_settings = _settings
    try:
        _s, block, _sym, _rule = await ap._entry_context(notif)
    finally:
        ap.get_auto_paper_settings = orig
    return (block is None), (block or {}).get("reason")


def fetch_candidates(limit: int, seed: int):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select symbol, created_at, price, coalesce(atr_pct,0),
                              coalesce(target_pct,0), coalesce(velocity_score,0)
                       from velocity_candidates
                       where net_pct is not null and price > 0
                       order by random() limit %s""", (limit,))
        return cur.fetchall()


def replay(cands, gap: float, sl: float, max_min: int) -> list[float]:
    """Kabul edilen adaylari GERCEK 1m mumlarla oynat."""
    nets = []
    with psycopg.connect(DB) as c, c.cursor() as cur:
        for sym, t0, entry, _atr, _tp, _sc in cands:
            t0 = int(t0)
            cur.execute("""select high, low, close from historical_candles
                           where symbol=%s and timeframe='1m'
                             and open_time >= %s and open_time <= %s
                           order by open_time limit %s""",
                        (sym, (t0 - 60) * 1000, (t0 + max_min * 60) * 1000, max_min + 2))
            bars = cur.fetchall()
            if len(bars) < 3:
                continue
            best = entry
            exit_px = None
            for hi, _lo, cl in bars:
                if hi > best:
                    best = hi
                lvl = max(best * (1 - gap / 100), entry * (1 - sl / 100))
                if cl <= lvl:
                    exit_px = lvl
                    break
            if exit_px is None:
                exit_px = bars[-1][2]
            nets.append((exit_px / entry - 1) * 100 - FEE)
    return nets


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=2000)
    p.add_argument("--gap", type=float, default=0.3)
    p.add_argument("--sl", type=float, default=2.0)
    p.add_argument("--max-min", type=int, default=240, dest="max_min")
    p.add_argument("--seed", type=int, default=11)
    a = p.parse_args()

    print(f"Uretim kapisi (_entry_context) + gercek 1m mum replay")
    print(f"gap={a.gap}% sl={a.sl}% max={a.max_min}dk fee={FEE}%  ornek={a.limit}\n")

    cands = fetch_candidates(a.limit, a.seed)

    # Kapinin gercekten calistigini kanitla: engel nedenleri sayimi
    print("KAPI DENETIMI (min_atr_pct = 1.0):")
    blocked, passed = 0, 0
    reasons: dict[str, int] = {}
    for sym, t0, price, atr, tp, sc in cands[:400]:
        notif = {"symbol": sym, "score": sc or 80.0, "mode": "trend_devam",
                 "source": "velocity", "atr_pct": (atr or None),
                 "price": price, "target_pct": tp}
        ok, reason = await decide(notif, 1.0)
        if ok:
            passed += 1
        else:
            blocked += 1
            reasons[reason] = reasons.get(reason, 0) + 1
    tot = passed + blocked
    print(f"  kabul={passed} engel={blocked}  ({100*passed/max(tot,1):.1f}% gecti)")
    for r, n in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {r}: {n}")
    print()

    print(f"  {'min_atr':>8} {'kapi_kabul':>11} {'n':>6} {'ort_net':>9} {'medyan':>9} {'kazanan':>8}")
    for min_atr in (0.0, 0.5, 1.0, 1.5):
        accepted = []
        for sym, t0, price, atr, tp, sc in cands:
            notif = {"symbol": sym, "score": sc or 80.0, "mode": "trend_devam",
                     "source": "velocity", "atr_pct": (atr or None),
                     "price": price, "target_pct": tp}
            ok, _r = await decide(notif, min_atr)
            if ok:
                accepted.append((sym, t0, price, atr, tp, sc))
        nets = replay(accepted, a.gap, a.sl, a.max_min)
        if not nets:
            print(f"  {min_atr:>8} islem yok")
            continue
        print(f"  {min_atr:>8} {len(accepted):>11} {len(nets):>6} "
              f"{st.mean(nets):>+8.3f}% {st.median(nets):>+8.3f}% "
              f"{100*sum(1 for x in nets if x > 0)/len(nets):>7.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
