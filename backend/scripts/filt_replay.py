"""Filtreli replay: sadece atr_pct >= X adaylari GERCEK mumlarla trailing replay."""
import psycopg, argparse, random, statistics as st
DB="postgresql://postgres:518518Erkan@localhost:5432/scalper"
FEE=float(__import__("os").getenv("FEE","0.30"))
def run(limit, gap, sl, max_min, atr_min, seed=7):
    random.seed(seed)
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("""select symbol, created_at, price from velocity_candidates
            where net_pct is not null and price>0 and atr_pct>=%s
            order by random() limit %s""",(atr_min,limit))
        cands=cur.fetchall()
    nets=[]
    with psycopg.connect(DB) as c, c.cursor() as cur:
        for sym,t0,entry in cands:
            t0=int(t0)
            cur.execute("""select high, low, close from historical_candles
                where symbol=%s and timeframe='1m' and open_time>=%s and open_time<=%s
                order by open_time limit %s""",(sym,(t0-60)*1000,(t0+max_min*60)*1000,max_min+2))
            bars=cur.fetchall()
            if len(bars)<3: continue
            best=entry; exit_px=None
            for (hi,lo,cl) in bars:
                if hi>best: best=hi
                lvl=max(best*(1-gap/100), entry*(1-sl/100))
                if cl<=lvl: exit_px=lvl; break
            if exit_px is None: exit_px=bars[-1][2]
            nets.append((exit_px/entry-1)*100-FEE)
    n=len(nets)
    if n<30: print(f"atr>={atr_min}: ornek yetersiz ({n})"); return
    print(f"atr>={atr_min:>4} n={n:>5} ort={st.mean(nets):+7.3f}% med={st.median(nets):+7.3f}% "
          f"kazanan={100*sum(1 for x in nets if x>0)/n:5.1f}%")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--limit",type=int,default=700); p.add_argument("--gap",type=float,default=0.3)
    p.add_argument("--sl",type=float,default=1.5); p.add_argument("--max-min",type=int,default=240,dest="max_min")
    a=p.parse_args()
    print(f"gap={a.gap}% sl={a.sl}% max={a.max_min}dk fee={FEE}%")
    for atr in (0, 0.5, 1.0, 1.5):
        run(a.limit,a.gap,a.sl,a.max_min,atr)
