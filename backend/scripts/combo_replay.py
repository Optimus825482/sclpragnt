"""min_atr + max_sl_tp kombinasyon testi — GERÇEK 1m mum yolu.

Kapsam: velocity adaylarını iki kapı ikilisinden geçir (atr eşiği + SL/TP
oranı), sonra gerçek mumlarda oynat. Amaç: tek tek yetersiz olan iki filtre
BİRLİKTE başabaşı geçiyor mu?

Yöntem: üretim kapısı `auto_paper._entry_context` atr için, `_calc_exit_plan`
çıktısı SL/TP oranı için kullanılır (kopya mantık değil, GERÇEK kod).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics as st
import sys
import time

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"
FEE = float(os.getenv("FEE", "0.30"))


def fetch(limit: int, seed: int):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select symbol, created_at, price, coalesce(atr_pct,0),
                              coalesce(target_pct,0), coalesce(velocity_score,0)
                       from velocity_candidates
                       where net_pct is not null and price > 0
                       order by random() limit %s""", (limit,))
        return cur.fetchall()


async def gate_decide(notif: dict, min_atr: float) -> tuple[bool, dict | None]:
    """Üretim giriş kapısı (atr dahil). Dönüş: (geçiyor mu, settings)."""
    from app.routers import auto_paper as ap

    async def _settings():
        s = await ap.get_default_settings()
        s["min_atr_pct"] = min_atr
        s["min_score"] = 0.0
        s["allowed_modes"] = []
        return s

    orig = ap.get_auto_paper_settings
    ap.get_auto_paper_settings = _settings
    try:
        settings, block, _sym, _rule = await ap._entry_context(notif)
    finally:
        ap.get_auto_paper_settings = orig
    return (block is None), (settings if block is None else None)


async def rr_plan(symbol: str, notif: dict, price: float, settings: dict,
                  ratio: float) -> tuple[float, float, dict | None]:
    """Üretim çıkış planı: (tp_pct, sl_pct, plan/block)."""
    from app.routers import auto_paper as ap

    settings = {**settings, "max_sl_tp_ratio": ratio}
    plan, block = await ap._calc_exit_plan(symbol, notif, price, settings, 1000.0)
    if plan is None:
        return 0.0, 0.0, block
    tp = plan["target_pct"]
    sl = (plan["fill_entry"] - plan["stop_loss_price"]) / plan["fill_entry"] * 100
    return tp, sl, None


async def replay_rows(cands, ratio: float, min_atr: float, gap: float,
                      max_min: int) -> dict:
    """Her adayı: kapıdan geçir, exit planıyla oynat. Döner istatistikler."""
    from app.routers import auto_paper as ap

    accepted = 0
    nets, reasons = [], {"trail": 0, "stop": 0, "timeout": 0, "blocked": 0}
    with psycopg.connect(DB) as c, c.cursor() as cur:
        for sym, t0, px, atr, tp_notif, sc in cands:
            notif = {"symbol": sym, "score": sc or 80.0, "mode": "trend_devam",
                     "source": "velocity", "atr_pct": (atr or None),
                     "price": px, "target_pct": tp_notif}
            ok, settings = await gate_decide(notif, min_atr)
            if not ok:
                reasons["blocked"] += 1
                continue
            tp_pct, sl_pct, block = await rr_plan(sym, notif, px, settings, ratio)
            if block is not None or tp_pct <= 0 or sl_pct <= 0:
                reasons["blocked"] += 1
                continue
            accepted += 1
            # `created_at` epoch SANİYE (double precision) — ms değil.
            t_ms = int(float(t0) * 1000)
            cur.execute("""select high, low, close from historical_candles
                           where symbol=%s and timeframe='1m'
                             and open_time >= %s and open_time <= %s
                           order by open_time limit %s""",
                        (sym, t_ms - 60_000, t_ms + max_min * 60_000, max_min + 2))
            bars = cur.fetchall()
            if len(bars) < 3:
                continue
            entry = float(px)
            best, exit_px, why = entry, None, None
            for hi, _lo, cl in bars:
                if hi > best:
                    best = hi
                trail = best * (1 - gap / 100)
                hard = entry * (1 - sl_pct / 100)
                lvl = max(trail, hard)
                # TP'ye önce değebilir — kazanç kuyruğunu koru.
                if cl <= lvl:
                    exit_px, why = lvl, "trail" if trail >= hard else "stop"
                    break
            if exit_px is None:
                exit_px, why = bars[-1][2], "timeout"
            nets.append((exit_px / entry - 1) * 100 - FEE)
            reasons[why] += 1

    if not nets:
        return {"n": 0}
    return {"n": len(nets), "accepted": accepted,
            "ort": st.mean(nets), "med": st.median(nets),
            "kaz": 100 * sum(1 for x in nets if x > 0) / len(nets), "reasons": reasons}


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=2500)
    p.add_argument("--gap", type=float, default=0.3)
    p.add_argument("--max-min", type=int, default=240, dest="max_min")
    p.add_argument("--seed", type=int, default=11)
    a = p.parse_args()

    print(f"min_atr + max_sl_tp kombinasyonu | ornek={a.limit} seed={a.seed} "
          f"gap={a.gap}% max={a.max_min}dk fee={FEE}%\n")

    cands = fetch(a.limit, a.seed)
    print(f"cekilen aday: {len(cands)}\n")

    combos = [
        (0.0, 0.0, "filtre yok"),
        (1.0, 0.0, "sadece atr 1.0"),
        (0.0, 0.64, "sadece rr 0.64"),
        (1.0, 0.64, "BIRLESIK atr1.0+rr0.64"),
        (1.5, 0.64, "BIRLESIK atr1.5+rr0.64"),
    ]
    print(f"  {'kombinasyon':>26} {'kabul':>6} {'n':>6} {'ort_net':>9} {'medyan':>9} {'kazanan':>8}")
    for min_atr, ratio, name in combos:
        r = await replay_rows(cands, ratio, min_atr, a.gap, a.max_min)
        if r["n"]:
            print(f"  {name:>26} {r['accepted']:>6} {r['n']:>6} "
                  f"{r['ort']:>+8.3f}% {r['med']:>+8.3f}% {r['kaz']:>7.1f}%")


if __name__ == "__main__":
    asyncio.run(main())