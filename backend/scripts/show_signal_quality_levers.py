# Geçici sinyal kalitesi analizi (read-only): skor kovaları + öncü desen etkisi.
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import database


def _profile(candidate_id):
    return "15m" if "15dk-%3" in str(candidate_id) else "5m"


async def main():
    rows = await database.get_velocity_candidates(limit=500)
    evaluated = [r for r in rows if r.get("status") == "evaluated"]
    passing = [r for r in evaluated if r.get("passes")]
    print(f"Olculen={len(evaluated)} gecen={len(passing)}")

    # 1) Skor kovalarina gore dokunus orani (gecen adaylar)
    buckets = [(0, 2), (2, 5), (5, 10), (10, 30), (30, 99999)]
    print("\n=== SKOR KOVASI -> DOKUNUS ORANI (gecen adaylar, her iki profil) ===")
    for lo, hi in buckets:
        sub = [r for r in passing if lo <= float(r.get("velocity_score") or 0) < hi]
        if not sub:
            continue
        touched = sum(1 for r in sub if r.get("touched_target"))
        mfe = sum(float(r.get("mfe_pct") or 0) for r in sub) / len(sub)
        print(f"skor {lo:2}-{hi if hi < 99999 else '∞':<5} n={len(sub):3} "
              f"hit={touched / len(sub) * 100:5.1f}%  ort.mfe={mfe:+.2f}%")

    # 2) Profil bazli ayni analiz (15m hedefi daha rahat; karismasin)
    print("\n=== SKOR KOVASI (yalniz 15m profili) ===")
    for lo, hi in buckets:
        sub = [r for r in passing if _profile(r["candidate_id"]) == "15m"
               and lo <= float(r.get("velocity_score") or 0) < hi]
        if not sub:
            continue
        touched = sum(1 for r in sub if r.get("touched_target"))
        print(f"skor {lo:2}-{hi if hi < 99999 else '∞':<5} n={len(sub):3} "
              f"hit={touched / len(sub) * 100:5.1f}%")

    # 3) Oncu desen (M1+M3 ATR) hard sart olsaydi
    print("\n=== ONCU DESEN (outcome_details.leading_ok) ===")
    for label, pred in [("leading_ok", lambda d: d.get("leading_ok") is True),
                        ("leading_yok", lambda d: d.get("leading_ok") is False)]:
        sub = [r for r in passing if pred(r.get("outcome_details") or {})]
        if not sub:
            continue
        touched = sum(1 for r in sub if r.get("touched_target"))
        print(f"{label:12} n={len(sub):3} hit={touched / len(sub) * 100:5.1f}%")

    # 4) M5 desen kol bazli (trend vs v_donusu outcomelarda mode yok; pattern_ok ile bak)
    print("\n=== M5 DESEN (outcome_details.m5_pattern_ok) x dokunus ===")
    for label, pred in [("pattern_ok", lambda d: d.get("m5_pattern_ok") is True),
                        ("pattern_eksik", lambda d: d.get("m5_pattern_ok") is False)]:
        sub = [r for r in passing if pred(r.get("outcome_details") or {})]
        if not sub:
            continue
        touched = sum(1 for r in sub if r.get("touched_target"))
        print(f"{label:12} n={len(sub):3} hit={touched / len(sub) * 100:5.1f}%")

    # 5) Sembol kalitesi korelasyonu: iyi sembollerde gecen adaylar dokunuyor mu
    sym_stats = await database.get_velocity_symbol_quality_stats()
    good = {r["symbol"] for r in sym_stats
            if int(r["touched"] or 0) > 0 and (int(r["touched"] or 0) / max(1, int(r["evaluated"] or 1))) >= 0.20}
    blocked = {r["symbol"] for r in sym_stats
               if int(r["evaluated"] or 0) >= 3 and int(r["touched"] or 0) == 0
               and float(r["average_mfe_pct"] or 0) < 1.0}
    print("\n=== SEMBOL KALITESI x GECEN ADAY DOKUNUSU ===")
    for label, syms in [("iyi_sembol(>=20% dokunus)", good), ("kotu_sembol(journal-kapili)", blocked)]:
        sub = [r for r in passing if r["symbol"] in syms]
        if not sub:
            print(f"{label:28} n=0")
            continue
        touched = sum(1 for r in sub if r.get("touched_target"))
        print(f"{label:28} n={len(sub):3} hit={touched / len(sub) * 100:5.1f}%")


asyncio.run(main())
