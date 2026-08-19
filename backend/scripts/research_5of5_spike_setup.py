"""Causal paper study of the proposed early 5/5 spike setup; never trades."""
import argparse, asyncio, bisect, json, math, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.config import config
from app.binance_tr_public import historical_klines
from scripts.research_mtf_5of5_managed_replay import normalize, resample, ema, flow_proxy, volume_ratio

TFS = ("1m", "5m", "15m", "1h", "4h")

def atr(rows, n=14):
    if len(rows) < n + 1: return None
    values = [max(rows[i]["high"]-rows[i]["low"], abs(rows[i]["high"]-rows[i-1]["close"]), abs(rows[i]["low"]-rows[i-1]["close"])) for i in range(len(rows)-n, len(rows))]
    return sum(values)/n

def vwap(rows, n=20):
    sample=rows[-n:]; total=sum(x["volume"] for x in sample)
    return sum(((x["high"]+x["low"]+x["close"])/3)*x["volume"] for x in sample)/total if total else None

def width(rows):
    closes=[x["close"] for x in rows]
    if len(closes)<20: return None
    mean=sum(closes[-20:])/20; dev=math.sqrt(sum((x-mean)**2 for x in closes[-20:])/20)
    return (4*dev/mean) if mean else None

def radar(rows):
    closes=[x["close"] for x in rows]
    if len(closes)<55: return False
    e9,e21,e50,prev=ema(closes,9),ema(closes,21),ema(closes,50),ema(closes[:-1],9)
    return bool(e9 and e21 and e50 and prev and closes[-1]>e9>e21>e50 and e9>prev)

def radar_series(rows):
    """Precompute exact radar state for every closed candle in linear time."""
    closes=[x["close"] for x in rows]
    def series(period):
        result=[None]*len(closes)
        if len(closes)<period:return result
        current=sum(closes[:period])/period; result[period-1]=current; mult=2/(period+1)
        for index in range(period,len(closes)):
            current=(closes[index]-current)*mult+current; result[index]=current
        return result
    e9,e21,e50=series(9),series(21),series(50)
    return [bool(index and e9[index] and e21[index] and e50[index] and closes[index]>e9[index]>e21[index]>e50[index] and e9[index]>e9[index-1]) for index in range(len(closes))]

def ema_values(rows, period=9):
    closes=[x["close"] for x in rows]; result=[None]*len(closes)
    if len(closes)<period:return result
    current=sum(closes[:period])/period; result[period-1]=current; mult=2/(period+1)
    for i in range(period,len(closes)): current=(closes[i]-current)*mult+current; result[i]=current
    return result

def vwap_values(rows, period=20):
    result=[None]*len(rows); weighted=0.0; volume=0.0
    for i,row in enumerate(rows):
        typical=(row["high"]+row["low"]+row["close"])/3; weighted+=typical*row["volume"]; volume+=row["volume"]
        if i>=period:
            old=rows[i-period]; old_typical=(old["high"]+old["low"]+old["close"])/3
            weighted-=old_typical*old["volume"]; volume-=old["volume"]
        if i>=period-1 and volume: result[i]=weighted/volume
    return result

def width_values(rows, period=20):
    """Bollinger width for each completed row in linear time."""
    result=[None]*len(rows); total=0.0; squares=0.0
    for i,row in enumerate(rows):
        close=row["close"]; total+=close; squares+=close*close
        if i>=period:
            old=rows[i-period]["close"]; total-=old; squares-=old*old
        if i>=period-1:
            mean=total/period
            variance=max(0.0, squares/period-mean*mean)
            result[i]=(4*math.sqrt(variance)/mean) if mean else None
    return result

def adr_ok(m1):
    days=resample(m1,1440)
    if len(days)<15: return False
    history=[(x["high"]-x["low"])/x["close"] for x in days[-15:-1] if x["close"]]
    current=(days[-1]["high"]-days[-1]["low"])/days[-1]["close"] if days[-1]["close"] else 1
    return bool(history and current/(sum(history)/len(history))<=.80)

def find_pullback(m1, start, e9s, vwaps, limit=10):
    for index in range(start+1, min(len(m1)-1,start+limit+1)):
        e9,vw=e9s[index],vwaps[index]; row=m1[index]
        if e9 and vw and row["low"]>=min(e9,vw)*.999 and row["close"]>e9 and row["close"]>vw and row["close"]>row["open"] and row["close"]>m1[index-1]["close"]:
            return index+1
    return None

def outcome(m1, entry_index):
    entry=m1[entry_index]["open"]*(1+config.BACKTEST_ASSUMED_SPREAD_PCT/2+config.ESTIMATED_SLIPPAGE_PCT)
    future=m1[entry_index:min(len(m1),entry_index+15)]
    if len(future)<15: return None
    exit_fill=future[-1]["close"]*(1-config.BACKTEST_ASSUMED_SPREAD_PCT/2-config.ESTIMATED_SLIPPAGE_PCT)
    quantity=1000/entry; proceeds=quantity*exit_fill*(1-config.COMMISSION_PCT)
    spent=1000*(1+config.COMMISSION_PCT)
    return {"entry_time":m1[entry_index]["time"],"entry":entry,"max_up_pct":(max(x["high"] for x in future)/entry-1)*100,"max_down_pct":(min(x["low"] for x in future)/entry-1)*100,"close_15m_pct":(exit_fill/entry-1)*100,"net_15m_pct":(proceeds/spent-1)*100}

def summarize(events):
    if not events:return {"n":0}
    val=lambda k:sorted(x["outcome"][k] for x in events)
    med=lambda a:a[(len(a)-1)//2]
    net=val("net_15m_pct")
    return {"n":len(events),"median_max_up_pct":round(med(val("max_up_pct")),4),"median_max_down_pct":round(med(val("max_down_pct")),4),"median_close_15m_pct":round(med(val("close_15m_pct")),4),"median_net_15m_pct":round(med(net),4),"net_positive_rate":round(sum(x>0 for x in net)/len(net),4),"up_1pct_rate":round(sum(x>=1 for x in val("max_up_pct"))/len(events),4)}

async def fetch(symbol, days):
    try:return symbol,normalize(await historical_klines(symbol,"1m",days)),None
    except Exception as exc:return symbol,[],f"{type(exc).__name__}: {exc}"

async def main(args):
    loaded=await asyncio.gather(*(fetch(s.upper(),args.days) for s in args.symbols)); events=[]; provenance={}; errors={}
    stages=defaultdict(int)
    for symbol,m1,error in loaded:
        provenance[symbol]={"m1_closed_candles":len(m1)}
        if error or len(m1)<60*24*16: errors[symbol]=error or "insufficient_history"; continue
        frames={"1m":m1,**{tf:resample(m1,n) for tf,n in (("5m",5),("15m",15),("1h",60),("4h",240))}}
        times={tf:[x["close_time"] for x in rows] for tf,rows in frames.items()}
        radar_flags={tf:radar_series(rows) for tf,rows in frames.items()}
        m1e9,m1vwap=ema_values(m1),vwap_values(m1)
        states=[]
        for five_index,five in enumerate(frames["5m"]):
            end_m1=bisect.bisect_right(times["1m"],five["close_time"])
            ends={tf:bisect.bisect_right(times[tf],five["close_time"]) for tf in TFS}
            all5=all(ends[tf] and radar_flags[tf][ends[tf]-1] for tf in TFS); states.append(all5)
            if not all5 or five_index<24 or states[-2:]==[True,True]: continue
            stages["new_5of5"]+=1
            completed={tf:frames[tf][:ends[tf]] for tf in TFS}
            m5=completed["5m"]; widths=[width(m5[:i+1]) for i in range(19,len(m5))]; current=width(m5); previous=width(m5[:-1])
            squeeze_expand=bool(current and previous and current>=previous*1.15 and min(widths[-13:-1])<=sorted(widths[-25:-1])[6])
            if not squeeze_expand: continue
            stages["squeeze_expand"]+=1
            breakout=m5[-1]["close"]>max(x["high"] for x in m5[-4:-1])
            if not breakout: continue
            stages["breakout"]+=1
            m1c=completed["1m"]; vol_flow=all(x is not None and x>=threshold for x,threshold in ((volume_ratio(m1c),1.5),(volume_ratio(m5),1.2),(flow_proxy(m1c),.05),(flow_proxy(m5),.05)))
            if not vol_flow: continue
            stages["volume_flow"]+=1
            vw=vwap(m5); a=atr(m5); not_extended=bool(vw and a and m5[-1]["close"]-vw<=1.5*a and adr_ok(m1c))
            if not not_extended: continue
            stages["not_extended"]+=1
            entry_index=find_pullback(m1,end_m1-1,m1e9,m1vwap)
            if entry_index is None: continue
            stages["pullback"]+=1
            record=outcome(m1,entry_index) if entry_index is not None else None
            if record: events.append({"symbol":symbol,"signal_time":five["close_time"],"entry_delay_minutes":entry_index-(end_m1-1),"outcome":record})
    events.sort(key=lambda x:x["signal_time"]); split=int(len(events)*.7)
    result={"paper_only":True,"generated_at":datetime.now(timezone.utc).isoformat(),"source":"Binance TR public historical M1 OHLCV","symbols":args.symbols,"provenance":provenance,"errors":errors,"stage_counts":dict(stages),"rule":"New exact 5/5; M5 squeeze-to-expansion; prior 15m high breakout; M1 EMA9/VWAP-held bullish pullback within 10m; M1/M5 volume+flow; ADR and VWAP extension gates.","execution":"Next M1 open after causal pullback; 15m time outcome; 0.15% commission/side, 0.10% spread, 0.025% slippage/side.","partitions":{"in_sample":{"summary":summarize(events[:split]),"events":events[:split]},"out_of_sample":{"summary":summarize(events[split:]),"events":events[split:]}}}
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps({k:v["summary"] for k,v in result["partitions"].items()},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--symbols',nargs='+',required=True);p.add_argument('--days',type=int,default=30);p.add_argument('--output',default='5of5-spike-setup.json');a=p.parse_args();asyncio.run(main(a))
