# Geçici sıralama smoke (read-only): kalite çarpanı + skor eşiği etkisi.
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import database
from app.routers.velocity import _journal_touch_rates, _quality_multiplier, _rank_score


async def main():
    rates = await _journal_touch_rates()
    rows = await database.get_velocity_candidates(limit=60)
    sample = [r for r in rows if r.get("velocity_score") is not None][:15]
    print(f"Ogrenilen sembol (yeterli orneklem): {len(rates)}")
    print("\nson adaylar uzerinde yeni siralama anahtari:")
    print(f"{'sembol':12} {'ham skor':>9} {'dokunus':>8} {'carpan':>7} {'sira-skoru':>11}")
    for r in sorted(sample, key=lambda c: -_rank_score(dict(c), rates)):
        sym = r["symbol"]
        base = float(r["velocity_score"] or 0)
        rate = rates.get(sym)
        mult = _quality_multiplier(rate)
        rate_s = f"{rate * 100:.0f}%" if rate is not None else "-"
        print(f"{sym:12} {base:9.2f} {rate_s:>8} {mult:7.1f} {_rank_score(dict(r), rates):11.2f}")

    # Min skor esiginin gecmis aciliklara etkisi (journal'daki gecen adaylar)
    rows = await database.get_velocity_candidates(limit=500)
    passing = [r for r in rows if r.get("status") == "evaluated" and r.get("passes")]
    below = [r for r in passing if float(r.get("velocity_score") or 0) < 10.0]
    touched_below = sum(1 for r in below if r.get("touched_target"))
    print(f"\nmin-skor=10 esigi: son 500 journal satirinda {len(passing)} gecen adaydan "
          f"{len(below)} tanesi elinirdi (dokunus {touched_below}/{len(below) if below else 0})")


asyncio.run(main())
