"""Exploratory event/control dataset for M5 trigger and M15/M30 context."""
import argparse, asyncio, json
from datetime import datetime
from pathlib import Path

from app.binance_tr_public import historical_klines
from scripts.capture_hourly_spike_mtf_snapshots import normalize, snapshot_at

MS={"5m":300000,"15m":900000,"30m":1800000}
DAYS={"5m":5,"15m":7,"30m":9,"1h":6}

async def fetch(symbol, tf, end_ms, sem):
    async with sem:
        try:return tf,normalize(await historical_klines(symbol,tf,DAYS[tf],end_ms)),None
        except Exception as exc:return tf,[],f"{type(exc).__name__}: {exc}"

def n(snapshot, *path):
    x=snapshot
    for key in path:
        if not isinstance(x,dict): return None
        x=x.get(key)
    return x

def normal_control_times(h1,event_ms,count):
    selected=[]
    for row in reversed(h1):
        if row["time"] > event_ms-24*3600000 or row["time"] >= event_ms: continue
        if not row["open"]: continue
        close=(row["close"]/row["open"]-1)*100; high=(row["high"]/row["open"]-1)*100
        if abs(close)<=3 and high<5 and all(abs(row["time"]-previous)>=6*3600000 for previous in selected):
            selected.append(row["time"])
            if len(selected)>=count: break
    return selected

def metrics(s): return s.get("key_metrics",{})
def trigger(m):
    return bool(m.get("price_vs_ema9_pct") is not None and m["price_vs_ema9_pct"]>0 and m.get("price_vs_vwap_pct") is not None and m["price_vs_vwap_pct"]>0 and (m.get("rsi_14") or 0)>=60 and (m.get("mfi_14") or 0)>=50 and (m.get("plus_di") or 0)>(m.get("minus_di") or 0) and (m.get("bb_position") or 0)>=.65)
def continuation(m15,m30):
    return any((m.get("plus_di") or 0)>(m.get("minus_di") or 0) and (m.get("rsi_14") or 0)>=60 for m in (m15,m30))
def reversal(m30,previous):
    return all((m30.get(k) is not None and previous.get(k) is not None and m30[k]>previous[k]) for k in ("rsi_14","mfi_14")) and n(m30,"cmo_9") is None

async def main(args):
    source=json.loads(Path(args.events).read_text(encoding="utf-8")); events=source["confirmed_events"][args.offset:args.offset + args.limit if args.limit else None]
    cutoff=int(datetime.fromisoformat(source["window"]["start"].replace(" +03","+03:00")).timestamp()*1000)+(args.hours*3600000*7//10)
    sem=asyncio.Semaphore(args.concurrency)
    async def one(event):
        start=int(event["hour_start_ms"]); loaded=await asyncio.gather(*(fetch(event["symbol"],tf,start+1,sem) for tf in DAYS)); data={tf:rows for tf,rows,error in loaded if not error}; errors={tf:error for tf,rows,error in loaded if error}
        controls=normal_control_times(data.get("1h",[]),start,args.controls_per_event)
        def point(time):
            snaps={tf:snapshot_at(event["symbol"],tf,data.get(tf,[]),time,args.timezone) for tf in MS}
            prev30=snapshot_at(event["symbol"],"30m",data.get("30m",[]),time-MS["30m"],args.timezone)
            ms={tf:metrics(x) for tf,x in snaps.items()}; p30=metrics(prev30)
            rev=all((ms["30m"].get(k) is not None and p30.get(k) is not None and ms["30m"][k]>p30[k]) for k in ("rsi_14","mfi_14")) and (n(snaps["30m"],"snapshot","momentum","cmo_9") or -999)>=(n(prev30,"snapshot","momentum","cmo_9") or 999)
            return {"time_ms":time,"snapshots":snaps,"flags":{"m5_trigger":trigger(ms["5m"]),"continuation_context":continuation(ms["15m"],ms["30m"]),"reversal_context":rev}}
        control_points=[point(control) for control in controls]
        return {"event":event,"event_point":point(start),"control_point":control_points[0] if control_points else None,"control_points":control_points,"errors":errors}
    rows=await asyncio.gather(*(one(e) for e in events))
    def rates(items,key,period):
        selected=[x for x in items if x and ((x["event"]["hour_start_ms"]<cutoff)==(period=="development"))]
        return {"n":len(selected),**{flag:sum(x[key]["flags"][flag] for x in selected) for flag in ("m5_trigger","continuation_context","reversal_context")}}
    valid_controls=[x for x in rows if x["control_point"]]
    payload={"research_only":True,"source":"Binance TR public historical OHLCV","event_source":args.events,"window_hours":args.hours,"cutoff_ms":cutoff,"definition":{"event":"H1 close/open >=20%","control":"same symbol, at least 24h earlier, H1 high <5% and absolute close move <=3%","warning":"Feature flags are exploratory hypotheses informed by the initial three examples, not validated trading rules."},"events":rows,"summary":{"events":len(rows),"controls":len(valid_controls),"development":{"events":rates(rows,"event_point","development"),"controls":rates(valid_controls,"control_point","development")},"oos":{"events":rates(rows,"event_point","oos"),"controls":rates(valid_controls,"control_point","oos")}}}
    Path(args.output).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(payload["summary"],ensure_ascii=False))

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--events",required=True);p.add_argument("--hours",type=int,default=1440);p.add_argument("--timezone",default="Europe/Istanbul");p.add_argument("--concurrency",type=int,default=16);p.add_argument("--controls-per-event",type=int,default=1);p.add_argument("--offset",type=int,default=0);p.add_argument("--limit",type=int);p.add_argument("--output",default="hourly-pump-context-60d.json");a=p.parse_args();asyncio.run(main(a))
