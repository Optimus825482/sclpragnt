# Geçici sembol kalitesi öğrenim raporu (read-only).
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import database
from app.config import config
from app.routers.velocity import _symbol_quality

MIN_EVAL = config.VELOCITY_SYMBOL_QUALITY_JOURNAL_MIN_EVALUATED
MAX_MFE = config.VELOCITY_SYMBOL_QUALITY_JOURNAL_MAX_AVG_MFE_PCT


async def main():
    stats = await database.get_velocity_symbol_quality_stats()
    rows = []
    for r in stats:
        sym = r["symbol"]
        ev = int(r["evaluated"] or 0)
        tou = int(r["touched"] or 0)
        mfe = float(r["average_mfe_pct"] or 0)
        q = await _symbol_quality(sym)
        blocked = ev >= MIN_EVAL and tou == 0 and mfe < MAX_MFE
        rows.append((sym, ev, tou, (tou / ev * 100) if ev else 0.0, mfe, q, blocked))
    rows.sort(key=lambda r: r[3])

    print(f"Journal kalite kapi esikleri: min_olcum={MIN_EVAL}, max_mfe={MAX_MFE}%")
    print()
    print("=== ENGELLENECEK SEMBOLLER (yeterli olcum + 0 dokunus + dusuk MFE) ===")
    blocked_rows = [r for r in rows if r[6]]
    if not blocked_rows:
        print("(yok — hicbir sembol esikleri karsilamiyor)")
    for sym, ev, tou, rate, mfe, q, _ in blocked_rows:
        tq = f"{q:+.2f}%" if q is not None else "islem yok"
        print(f"{sym:12} olcum={ev:3} dokunus={tou} mfe={mfe:+.2f}%  islem-kalitesi={tq}")
    print()
    print("=== EN KOTU 10 (tum kanit) ===")
    for sym, ev, tou, rate, mfe, q, blocked in rows[:10]:
        flag = "ENGELLI" if blocked else "gecer"
        tq = f"{q:+.2f}%" if q is not None else "-"
        print(f"{sym:12} olcum={ev:3} oran={rate:5.1f}% mfe={mfe:+.2f}%  islem={tq:>8}  -> {flag}")
    print()
    print("=== EN IYI 10 ===")
    for sym, ev, tou, rate, mfe, q, _ in rows[-10:][::-1]:
        tq = f"{q:+.2f}%" if q is not None else "-"
        print(f"{sym:12} olcum={ev:3} oran={rate:5.1f}% mfe={mfe:+.2f}%  islem={tq:>8}")
    print()
    print(f"Toplam ogrenilen sembol: {len(rows)}")


asyncio.run(main())
