"""Tarama aileleri araştırması — gerçek 1m mum replay.

Kapsam: velocity (kontrol), rising (rising_alerts), monitoring bildirimleri
(monitoring_notifications) ve gerçekleşmiş auto_paper_trades.

Üç ölçüm:
  A) Her ailenin gerçek replay performansı (aynı çıkış modeliyle kıyaslanabilir)
  B) Gerçekleşmiş işlemlerin asimetri teşhisi (kazanç/kayıp oranı, stop genişliği)
  C) Çıkış modeli duyarlılığı: sabit TP mi, trailing mi, stop genişliği ne olmalı
"""
from __future__ import annotations

import argparse
import os
import statistics as st
import sys

import psycopg

DB = "postgresql://postgres:518518Erkan@localhost:5432/scalper"
FEE = float(os.getenv("FEE", "0.30"))


def fetch_family(name: str, limit: int):
    """Aile -> [(symbol, created_at, price)] listesi.

    NOT: `rising_alerts` ailesinde `price` VE `expected_price` kolonlari
    TAMAMEN BOS (2026-11-10 olcumu: 4.279 kayitta 0 dolu). Bu aile mum
    replay'i ile OLULEMEZ; `rising_mfe()` ile MFE/MAE uzerinden olculur.
    """
    sql = {
        "velocity": """select symbol, created_at, price from velocity_candidates
                       where net_pct is not null and price > 0""",
        "notifications": """select symbol, detected_at as created_at, price
                            from monitoring_notifications
                            where price > 0 and mfe_pct is not null""",
        "trades": """select symbol, entry_time as created_at, entry_price as price
                     from auto_paper_trades where status='closed' and entry_price>0""",
    }[name]
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute(f"select * from ({sql}) q order by random() limit %s", (limit,))
        return cur.fetchall()


def rising_mfe():
    """rising ailesini MFE/MAE ile olc (fiyat kayitli olmadigi icin replay yok).

    Muhafazakar: TP ve SL ikisi de degdiyse SL once sayilir (mum-ici siralama
    bilinmiyor).
    """
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select kind, mfe_pct, mae_pct from rising_alerts
                       where mfe_pct is not null and mae_pct is not null""")
        rows = cur.fetchall()
    out = {}
    for kind in sorted({r[0] for r in rows}):
        sub = [(float(m), float(a)) for k, m, a in rows if k == kind]
        if not sub:
            continue
        out[kind] = {
            "n": len(sub),
            "mfe": sum(m for m, _a in sub) / len(sub),
            "mae": sum(a for _m, a in sub) / len(sub),
            "mfe_ge_1": 100 * sum(1 for m, _a in sub if m >= 1.0) / len(sub),
        }
    return out


def replay(cands, gap: float, sl: float, max_min: int):
    """Gerçek 1m mumlarla trailing replay. Döner: (netler, çıkış nedenleri)."""
    nets, reasons = [], {"trail": 0, "stop": 0, "timeout": 0}
    with psycopg.connect(DB) as c, c.cursor() as cur:
        for sym, t0, entry in cands:
            if not t0 or not entry or entry <= 0:
                continue
            t0 = int(t0)
            cur.execute("""select high, low, close from historical_candles
                           where symbol=%s and timeframe='1m'
                             and open_time >= %s and open_time <= %s
                           order by open_time limit %s""",
                        (sym, (t0 - 60) * 1000, (t0 + max_min * 60) * 1000, max_min + 2))
            bars = cur.fetchall()
            if len(bars) < 3:
                continue
            best, exit_px, why = entry, None, None
            for hi, _lo, cl in bars:
                if hi > best:
                    best = hi
                trail_lvl = best * (1 - gap / 100)
                hard_lvl = entry * (1 - sl / 100)
                lvl = max(trail_lvl, hard_lvl)
                if cl <= lvl:
                    exit_px = lvl
                    why = "trail" if trail_lvl >= hard_lvl else "stop"
                    break
            if exit_px is None:
                exit_px, why = bars[-1][2], "timeout"
            nets.append((exit_px / entry - 1) * 100 - FEE)
            reasons[why] += 1
    return nets, reasons


def summarize(nets):
    if not nets:
        return None
    return {"n": len(nets), "ort": st.mean(nets), "med": st.median(nets),
            "kaz": 100 * sum(1 for x in nets if x > 0) / len(nets)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=1200)
    p.add_argument("--gap", type=float, default=0.3)
    p.add_argument("--sl", type=float, default=2.0)
    p.add_argument("--max-min", type=int, default=240, dest="max_min")
    a = p.parse_args()

    print(f"gap={a.gap}% sl={a.sl}% max={a.max_min}dk fee={FEE}% ornek/aile={a.limit}\n")

    print("A) AİLE KARŞILAŞTIRMASI — aynı çıkış modeli, gerçek 1m mum")
    print(f"  {'aile':>16} {'ham':>6} {'n':>6} {'ort_net':>9} {'medyan':>9} {'kazanan':>8}")
    for fam in ("velocity", "notifications", "trades"):
        cands = fetch_family(fam, a.limit)
        nets, _r = replay(cands, a.gap, a.sl, a.max_min)
        s = summarize(nets)
        if s:
            print(f"  {fam:>16} {len(cands):>6} {s['n']:>6} {s['ort']:>+8.3f}% "
                  f"{s['med']:>+8.3f}% {s['kaz']:>7.1f}%")
        else:
            print(f"  {fam:>16} {len(cands):>6} veri yok")

    print("\nA2) rising ailesi — fiyat KAYITLI DEGIL, MFE/MAE ile kismi olcum")
    rm = rising_mfe()
    print(f"  {'kind':>10} {'n':>6} {'ort_mfe':>8} {'ort_mae':>8} {'MFE>=1':>7}")
    for kind, v in rm.items():
        print(f"  {kind:>10} {v['n']:>6} {v['mfe']:>8.3f} {v['mae']:>8.3f} {v['mfe_ge_1']:>6.1f}%")
    print("  NOT: replaysiz; mum-ici siralama bilinmiyor (muhafazar).")

    print("\nB) GERÇEKLEŞMİŞ İŞLEMLER — asimetri teşhisi")
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select count(*),
            round(avg(case when pnl_pct>0 then pnl_pct end)::numeric,3),
            round(avg(case when pnl_pct<=0 then pnl_pct end)::numeric,3)
            from auto_paper_trades where status='closed'""")
        n, win, loss = cur.fetchone()
        if n and win and loss:
            ratio = abs(float(win) / float(loss))
            print(f"  islem={n}  ort kazanan={win}%  ort kaybeden={loss}%")
            print(f"  kazanc/kayip orani = {ratio:.3f}")
            cur.execute("""select round(100.0*avg(case when pnl_pct>0 then 1 else 0 end),1)
                           from auto_paper_trades where status='closed'""")
            wr = float(cur.fetchone()[0]) / 100
            need = (1 - wr) / wr
            print(f"  kazanan orani = {wr*100:.1f}%  ->  gereken oran = {need:.3f}")
            verdict = "KÂRLI" if ratio > need else "ZARARLI"
            print(f"  sonuc: {verdict} (oran {ratio:.3f} {'>' if ratio > need else '<'} esik {need:.3f})")

        print("\n  stop genişliğine göre (gerçekleşmiş):")
        cur.execute("""select
            case when (entry_price-stop_loss)/entry_price*100 >= 5 then 'genis(>=5%)'
                 when (entry_price-stop_loss)/entry_price*100 >= 3 then 'orta(3-5%)'
                 else 'dar(<3%)' end arm,
            count(*), round(avg(pnl_pct)::numeric,3),
            round(100.0*avg(case when pnl_pct>0 then 1 else 0 end),1)
          from auto_paper_trades where stop_loss>0 and entry_price>0
          group by 1 order by 1""")
        for r in cur.fetchall():
            print(f"    {r[0]:>14} n={r[1]:>5} ort={r[2]:>7}% kazanan={r[3]}%")

    print("\nC) ÇIKIŞ MODELİ DUYARLILIĞI (velocity ailesi)")
    cands = fetch_family("velocity", a.limit)
    print(f"  {'gap':>5} {'SL':>5} {'n':>6} {'ort_net':>9} {'kazanan':>8}")
    for gap, sl in ((0.3, 1.5), (0.3, 2.0), (0.3, 3.0), (0.5, 2.0), (1.0, 2.0)):
        nets, _r = replay(cands, gap, sl, a.max_min)
        s = summarize(nets)
        if s:
            print(f"  {gap:>5.1f} {sl:>5.1f} {s['n']:>6} {s['ort']:>+8.3f}% {s['kaz']:>7.1f}%")


if __name__ == "__main__":
    main()
