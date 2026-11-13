"""Honest replay: velocity adaylarini GERCEK 1m mumlarla yeniden oynat.

Sahte varsayim yok: her aday icin giris anindan sonraki 1m mumlari sirayla
yururuz; trailing stop mum KAPANISINDAN izlenir (mum-ici tepe SL'i asla
tetiklemez -> muhafazakar).
"""
import psycopg, sys, random
DB="postgresql://postgres:518518Erkan@localhost:5432/scalper"
FEE=0.30

def main(limit=4000, gap=0.3, sl=1.5, max_min=240, seed=42):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select candidate_id, symbol, created_at, price, target_pct
                       from velocity_candidates
                       where net_pct is not null and price>0
                       order by random() limit %s""",(limit,))
        cands=cur.fetchall()
    print(f"aday: {len(cands)} | trailing gap={gap}% SL={sl}% max={max_min}dk fee={FEE}%")
    nets=[]; reasons={"trail":0,"stop":0,"timeout":0}
    with psycopg.connect(DB) as c, c.cursor() as cur:
        for cid,sym,t0,entry,tp in cands:
            t0=int(t0)
            cur.execute("""select open_time, high, low, close from historical_candles
                           where symbol=%s and timeframe='1m'
                             and open_time >= %s and open_time <= %s
                           order by open_time limit %s""",
                        (sym, (t0-60)*1000, (t0+max_min*60)*1000, max_min+2))
            bars=cur.fetchall()
            if len(bars)<3: continue
            best=entry; exit_px=None; why=None
            for (ot,hi,lo,cl) in bars:
                if hi>best: best=hi
                trail_stop = best*(1-gap/100)
                hard_stop  = entry*(1-sl/100)
                stop_lvl   = max(trail_stop, hard_stop)
                if cl <= stop_lvl:
                    exit_px=stop_lvl; why="trail" if trail_stop>=hard_stop else "stop"; break
            if exit_px is None:
                exit_px=bars[-1][3]; why="timeout"
            net=(exit_px/entry-1)*100 - FEE
            nets.append(net); reasons[why]+=1
    import statistics as st
    n=len(nets)
    if not n: print("ornek yok"); return
    print(f"olculen: {n} islem")
    print(f"  ort_net = {st.mean(nets):+.3f}%   medyan = {st.median(nets):+.3f}%")
    print(f"  kazanan = {100*sum(1 for x in nets if x>0)/n:.1f}%")
    print(f"  en iyi = {max(nets):+.2f}%  en kotu = {min(nets):+.2f}%")
    print(f"  cikis: trail={reasons['trail']} stop={reasons['stop']} timeout={reasons['timeout']}")

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--limit",type=int,default=4000)
    p.add_argument("--gap",type=float,default=0.3); p.add_argument("--sl",type=float,default=1.5)
    p.add_argument("--max-min",type=int,default=240, dest="max_min")
    a=p.parse_args()
    main(a.limit,a.gap,a.sl,a.max_min)
